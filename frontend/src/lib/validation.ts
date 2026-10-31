// Client-side rules — the same as on the server (FR-3, NFR-11), so the user sees an error
// before sending the form. The server checks everything again.

/** NFR-5: at least 8 characters, an uppercase Latin letter, a digit and a special character. */
export function isStrongPassword(value: string): boolean {
  return value.length >= 8 && /[A-Z]/.test(value) && /\d/.test(value) && /[^A-Za-z0-9]/.test(value);
}

/** UI spec §2 item 2: only letters, spaces and hyphens. */
export const NAME_PATTERN = /^[A-Za-zА-Яа-яЁё]+(?:[ -][A-Za-zА-Яа-яЁё]+)*$/;

/** UI spec §2 item 2: the first letter of every word becomes uppercase. */
export function capitalizeName(value: string): string {
  return value.replace(/(^|[ -])([a-zа-яё])/g, (_, sep: string, letter: string) => sep + letter.toUpperCase());
}

const INN_10 = [2, 4, 10, 3, 5, 9, 4, 6, 8];
const INN_11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8];
const INN_12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8];

function controlDigit(digits: number[], weights: number[]): number {
  return (weights.reduce((sum, w, i) => sum + w * digits[i], 0) % 11) % 10;
}

/** UI spec §2 item 6: 10 digits for a company, 12 for a sole proprietor, with a checksum. */
export function isValidInn(inn: string): boolean {
  if (!/^(\d{10}|\d{12})$/.test(inn)) return false;
  const d = inn.split("").map(Number);
  if (d.length === 10) return controlDigit(d, INN_10) === d[9];
  return controlDigit(d, INN_11) === d[10] && controlDigit(d, INN_12) === d[11];
}

/** National part of a phone number from what the user typed.
 *  UI spec §2 item 4: with the code +7 a leading "8" is replaced by "+7" (dropped from the national part). */
export function normalizeNationalNumber(countryCode: string, typed: string): string {
  let digits = typed.replace(/\D/g, "");
  if (countryCode === "+7") {
    if (digits.startsWith("8")) digits = digits.slice(1);
    else if (digits.startsWith("7") && digits.length > 10) digits = digits.slice(1);
    return digits.slice(0, 10);
  }
  return digits.slice(0, 14);
}

/** Display mask for Russian numbers: (900) 123-45-67. */
export function formatNationalNumber(countryCode: string, digits: string): string {
  if (countryCode !== "+7") return digits;
  const parts = [digits.slice(0, 3), digits.slice(3, 6), digits.slice(6, 8), digits.slice(8, 10)];
  let out = "";
  if (parts[0]) out += `(${parts[0]}${parts[0].length === 3 ? ")" : ""}`;
  if (parts[1]) out += ` ${parts[1]}`;
  if (parts[2]) out += `-${parts[2]}`;
  if (parts[3]) out += `-${parts[3]}`;
  return out;
}

/** E.164 as stored in billing_profiles.phone. */
export function toE164(countryCode: string, digits: string): string {
  return `${countryCode}${digits}`;
}

export function isCompleteNationalNumber(countryCode: string, digits: string): boolean {
  if (countryCode === "+7") return digits.length === 10;
  const total = countryCode.length - 1 + digits.length;
  return total >= 7 && total <= 15;
}

/** Splits a stored E.164 number back into the code and the national part. */
export function splitE164(phone: string | null, codes: string[]): { code: string; digits: string } {
  if (!phone) return { code: "+7", digits: "" };
  const code = [...codes].sort((a, b) => b.length - a.length).find((c) => phone.startsWith(c)) ?? "+7";
  return { code, digits: phone.slice(code.length) };
}

// NFR-22: images up to 5 MB and 2048×2048 px, JPG/PNG/WebP
export const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const MAX_IMAGE_SIDE = 2048;

export function readImageSize(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
      URL.revokeObjectURL(url);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("not an image"));
    };
    img.src = url;
  });
}

/** NFR-28, NFR-29: DD.MM.YYYY HH:MM in Moscow time. */
export function formatMoscowDateTime(iso: string): string {
  const parts = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("day")}.${get("month")}.${get("year")} ${get("hour")}:${get("minute")}`;
}
