// The whole path of the product through the interface, as people go it (CLAUDE.md, "сквозная проверка"):
// registration → connecting to sales → publishing a beat → catalog → buying Basic → contract → download
// → buying Exclusive with the SMS code → contract with the ПЭП stamp → stems.
// Each browser (Chromium, WebKit) gets its own new users, so runs never depend on each other.
import { createHash } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { png, wav, zip } from "./files";
import { emails, smsCode } from "./inbox";

const PASSWORD = "E2e-pass1!";
const PHONE_DIGITS = "9001234567";
const PHONE = `+7${PHONE_DIGITS}`;

async function register(page: Page, email: string, name: string) {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill(PASSWORD);
  await page.getByLabel("Имя или псевдоним").fill(name);
  // FR-31: consent to personal data processing and the ПЭП agreement are required
  await page.getByRole("checkbox").nth(0).check();
  await page.getByRole("checkbox").nth(1).check();
  await page.getByRole("button", { name: "Зарегистрироваться" }).click();
  await expect(page).toHaveURL(/\/profile/);
}

async function fillBilling(page: Page, lastName: string, email: string) {
  await page.goto("/billing");
  await page.getByLabel("Фамилия").fill(lastName);
  await page.getByLabel("Имя", { exact: true }).fill("Тест");
  await page.getByLabel("Email для уведомлений").fill(email);
  await page.getByPlaceholder("(900) 123-45-67").fill(PHONE_DIGITS);
  await page.getByRole("button", { name: "Сохранить и продолжить" }).click();
  await expect(page.getByText("Данные сохранены")).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page.getByRole("link", { name: "Войти" }).first()).toBeVisible();
}

/** Cart → checkout with the offer → order page; returns the order id. */
async function placeOrder(page: Page, beatId: number, license: "basic" | "exclusive"): Promise<string> {
  await page.goto(`/beats/${beatId}`);
  await page.locator(`input[type=radio][value=${license}]`).check();
  await page.getByRole("button", { name: "В корзину" }).click();
  await expect(page.getByText("Бит добавлен в корзину")).toBeVisible();
  await page.goto("/checkout");
  await page.getByRole("checkbox").check(); // FR-16, FR-17: no order without the offer
  await page.getByRole("button", { name: "Оформить заказ" }).click();
  await expect(page).toHaveURL(/\/orders\/\d+$/);
  return page.url().split("/").pop() as string;
}

/** "Go to payment" → the payment page of the YooKassa mock → back to OhBeat → paid. */
async function pay(page: Page, total: string) {
  await page.getByRole("button", { name: "Перейти к оплате" }).click();
  await expect(page).toHaveURL(/localhost:8100\/checkout\//);
  await page.getByRole("button", { name: "Успешная оплата" }).click();
  await expect(page).toHaveURL(/\/orders\/\d+\/return$/);
  await expect(page.getByText(`Оплата прошла: ${total}`)).toBeVisible({ timeout: 60_000 }); // FR-27
}

/** Fresh links (FR-28): their kinds and the SHA-256 of the contract PDF downloaded by one of them. */
async function downloads(page: Page): Promise<{ kinds: string[]; contractSha: string }> {
  await page.getByRole("button", { name: "Скачать файлы" }).click();
  const links = page.locator("a[download]");
  await expect(links.first()).toBeVisible();
  const kinds = await links.allTextContents();
  const contract = links.filter({ hasText: "Договор" }).first();
  const response = await page.request.get((await contract.getAttribute("href")) as string);
  expect(response.status()).toBe(200);
  const body = await response.body();
  expect(body.subarray(0, 4).toString()).toBe("%PDF");
  return { kinds, contractSha: createHash("sha256").update(body).digest("hex") };
}

test("the whole path: publish, buy Basic and Exclusive, contracts and files", async ({ page }, testInfo) => {
  const run = `${testInfo.project.name}-${Date.now()}`;
  const producerEmail = `producer-${run}@example.com`;
  const artistEmail = `artist-${run}@example.com`;
  const title = `E2E ${testInfo.project.name} ${Date.now() % 100000}`;

  await test.step("Producer: registration, contract details, connecting to sales (FR-31 … FR-33)", async () => {
    await register(page, producerEmail, `E2E Producer ${testInfo.project.name}`);
    await fillBilling(page, "Продюсеров", producerEmail);
    await page.goto("/producer/connect");
    await page.getByLabel("Идентификатор продавца в ЮKassa").fill(`mock-seller-e2e-${testInfo.project.name}`);
    await page.getByRole("checkbox").nth(0).check();
    await page.getByRole("checkbox").nth(1).check();
    await page.getByRole("button", { name: "Подключиться" }).click();
    await expect(page.getByText("Готово! Теперь вы Продюсер.")).toBeVisible();
  });

  let beatId = 0;
  await test.step("Producer: direct upload to S3, processing by Media Worker, publication (FR-1 … FR-12)", async () => {
    await page.goto("/producer/beats/new");
    const tone = wav(6, 220);
    await page.locator("#cover").setInputFiles({ name: "cover.png", mimeType: "image/png", buffer: png(256, [62, 170, 234]) });
    await page.locator("#wav").setInputFiles({ name: "master.wav", mimeType: "audio/wav", buffer: tone });
    await page.locator("#stems").setInputFiles({
      name: "stems.zip",
      mimeType: "application/zip",
      buffer: zip([{ name: "drums.wav", data: wav(6, 110) }, { name: "melody.wav", data: tone }]),
    });
    await page.locator("#title").fill(title);
    await page.locator("#bpm").fill("120");
    await page.locator("#musical_key").selectOption("Am");
    await page.getByRole("button", { name: "Trap", exact: true }).click();
    for (const [name, price] of [["Basic", "1500"], ["Exclusive", "20000"]]) {
      await page.getByRole("checkbox", { name, exact: true }).check();
      await page.getByLabel(`${name} — Цена, ₽`).fill(price);
    }
    const submit = page.getByRole("button", { name: "Опубликовать бит" });
    await expect(submit).toBeEnabled(); // NFR-11: nothing is left to fill in
    const created = page.waitForResponse((r) => r.url().endsWith("/v1/beats") && r.request().method() === "POST");
    await submit.click();
    beatId = (await (await created).json()).id;
    await expect(page).toHaveURL(/\/producer\/beats$/, { timeout: 120_000 });

    // The worker checks the files, adds the voice tag and makes the preview: the status changes by itself
    const row = page.locator("article").filter({ hasText: title }); // the card of the beat in My beats
    await expect(async () => {
      await page.reload();
      await expect(row.getByText("Опубликован", { exact: true })).toBeVisible({ timeout: 2_000 }); // the status badge
    }).toPass({ timeout: 120_000, intervals: [3_000] });
    await signOut(page);
  });

  const since = new Date();
  await test.step("Artist: registration and buyer details with a phone (FR-31, FR-32)", async () => {
    await register(page, artistEmail, `E2E Artist ${testInfo.project.name}`);
    await fillBilling(page, "Артистов", artistEmail);
  });

  await test.step("Catalog: the beat is published with a preview (FR-13, US-A1)", async () => {
    await page.goto(`/beats/${beatId}`);
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    await expect(page.getByText("1 500 ₽")).toBeVisible(); // the Producer's price, without the fee (FR-15)
  });

  await test.step("Basic: order, payment with the split, contract by offer, download (FR-14 … FR-30)", async () => {
    await placeOrder(page, beatId, "basic");
    await expect(page.getByText("1 650 ₽").first()).toBeVisible(); // 1 500 + the 10 % fee on top (FR-30)
    await pay(page, "1 650 ₽");
    const { kinds, contractSha } = await downloads(page);
    expect(kinds).toEqual(["MP3", expect.stringMatching(/^Договор № \d+-1 \(PDF\)$/)]);

    await page.goto("/purchases"); // the hash shown to the Artist is the hash of the file (RFC ПЭП §3)
    await expect(page.getByText(`SHA-256: ${contractSha}`)).toBeVisible();
    expect(await emails(producerEmail, "Продажа на OhBeat", since)).toHaveLength(1); // FR-24
  });

  await test.step("Exclusive: reservation, contract draft, SMS code, payment, stems (FR-18, RFC ПЭП, NFR-31)", async () => {
    await placeOrder(page, beatId, "exclusive");
    await expect(page.getByText(/Бит зарезервирован за вами ещё/)).toBeVisible(); // FR-18
    await expect(page.getByRole("button", { name: "Перейти к оплате" })).toBeDisabled(); // 428 until signed
    await expect(page.getByText("ЛИЦЕНЗИОННЫЙ ДОГОВОР")).toBeVisible(); // the draft is read before the code

    const asked = new Date();
    await page.getByRole("button", { name: "Подписать" }).click();
    await expect(page.getByText("Код отправлен на +7 (900) ***-**-67.")).toBeVisible();
    const code = await smsCode(PHONE, asked);
    await page.locator("#otp-code").fill(code === "000000" ? "111111" : "000000"); // a wrong one first
    await page.getByRole("button", { name: "Подтвердить" }).click();
    await expect(page.getByText("Неверный код, осталось попыток: 2")).toBeVisible(); // NFR-31
    await page.locator("#otp-code").fill(code);
    await page.getByRole("button", { name: "Подтвердить" }).click();
    await expect(page.getByText("Договор на Exclusive подписан.")).toBeVisible();

    await pay(page, "22 000 ₽");
    const { kinds } = await downloads(page);
    expect(kinds).toEqual(["MP3", "WAV", "Стемы (ZIP)", expect.stringMatching(/^Договор № \d+-1 \(PDF\)$/)]);

    await page.goto(`/beats/${beatId}`); // FR-24: a sold Exclusive leaves the catalog
    await expect(page.getByText("Страница не найдена")).toBeVisible();
  });
});
