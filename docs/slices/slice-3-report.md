# Срез 3. Итоги

Дата: 04.11.2026. План — [slice-3-plan.md](slice-3-plan.md). Срез делали тремя частями: 3a (корзина и заказ), 3b (платёж и вебхук), 3c (выдача).

## Что сделано

- **Корзина и заказ (3a):**
  - корзина на сервере: одна лицензия на бит, недоступные позиции помечены;
  - заказ — одна транзакция: снимок данных покупателя и Продюсеров, цена и комиссия в позиции, атомарный резерв Exclusive на 15 минут, договоры-оферты (строки `contracts`) с `draft_sha256`;
  - FR-29 в планировщике: оба запроса из `Database_Schema.md` §6.
- **Платёж и вебхук (3b):**
  - мок ЮKassa — отдельный контейнер `yookassa-mock`: API v3, страница оплаты, пульт с поломками, вебхуки с повторами;
  - Core API работает с ЮKassa через интерфейс `PaymentGateway`: 1 попытка + 3 повтора с одним `Idempotence-Key`;
  - вебхук: сверка статуса запросом `GET /v3/payments/{id}`, дедупликация в `payment_events`, проверка FR-23 в одной транзакции, `capture`/`cancel` после ответа `200`;
  - планировщик доводит платежи, зависшие в холде (GAP-35).
- **Выдача (3c):**
  - PDF договора для каждой позиции: текст подписанного проекта плюс отметка — «акцепт оферты» или штамп ПЭП по RFC §5. Делается в транзакции `payment.succeeded` и лежит в `private-media/contracts/{заказ}-{n}.pdf` вместе с `pdf_sha256`;
  - ссылки на скачивание по составу лицензии, не дольше часа (NFR-8);
  - «Мои покупки», «Мои продажи» за период, письма Продюсеру и Артисту (мок пишет их в лог).
- **Экраны:**
  - выбор лицензии и «В корзину» на странице бита;
  - корзина со счётчиком в шапке;
  - оформление: оферта, окно «цена изменилась», ветка «нет данных покупателя»;
  - страница заказа с обратным отсчётом резерва и кнопкой оплаты;
  - страница возврата: опрос 2 с / 60 с, ссылки на файлы;
  - «Мои покупки», «Мои продажи».
- **Демо-набор:** второй Продюсер «Nova Sound» с 4 битами (`SEED_PRODUCER2_*`), чтобы в одном платеже было два продавца.

## Проверки

| Что | Результат |
| --- | --- |
| Тесты Core API | 239 прошли (+68 за срез: заказы 29, платежи 26, выдача 13) |
| Тесты мока ЮKassa | 15 прошли |
| Тесты Media Worker | 32 прошли (без изменений) |
| Тесты фронтенда | 39 прошли (+10: корзина, страница возврата, копейки, период продаж) |
| Типы | без ошибок |
| Браузер, 3a | гость → «В корзину» → вход → возврат на бит; два Продюсера в корзине, 4 755 + 475,50 = 5 230,50 ₽; без данных покупателя → форма → возврат на оформление; цена изменилась в БД → окно «1 500 → 1 600», новая сумма 5 340,50 ₽ → заказ создан; Exclusive → резерв 14:58 и «Зарезервирован за вами» в корзине |
| Браузер, 3b | «Отказ банка» → «Оплата не прошла. Недостаточно средств» → «Оплатить снова» → новый платёж → «Оплата прошла: 5 340,50 ₽»; в пульте 1 600 ₽ и 3 255 ₽ продавцам и 485,50 ₽ платформе; поломка 500 ×4 → ровно 4 попытки → «Платежный сервис временно недоступен»; «Холд без уведомления» → через 60 с текст FR-27 → вебхук из пульта → заказ оплачен; вебхук 3 раза одновременно → три `200`, новых событий нет |
| Браузер, 3c | оплата Trackout → на странице возврата MP3, WAV, стемы и договор № 4-1; все 4 ссылки открываются из браузера (`200`, `attachment`), хэш скачанного PDF совпал с `pdf_sha256`; «Мои покупки» — 4 позиции; «Мои продажи» Nova Sound — 3 позиции, 10 654 ₽; ширина 375 px — без поломок |

## Требование → код → тест

| Требование | Код | Тест |
| --- | --- | --- |
| FR-14: одна лицензия на бит, блокировка недоступного | `orders/cart.py` → `put_item`, `unavailable_reason`; `BeatPage.tsx` → `LicensePicker` | `test_fr14_*`, `test_cart_*` |
| FR-15: пересчёт, комиссия отдельной строкой, `PRICE_CHANGED` | `cart.get_cart`, `orders/service.py` → `create_order`; `CheckoutPage.tsx` | `test_fr15_*`, `cart.test.ts` |
| FR-16, FR-17: оферта обязательна | `OrderCreate.offer_accepted`, кнопка неактивна без галочки | `test_fr16_offer_must_be_accepted` |
| FR-18: атомарный резерв, сообщения по фактическому статусу | `create_order`, шаг 3 (`UPDATE … WHERE status = 'active'`) | **`test_fr18_race_of_buyers_for_one_exclusive[2, 10]`**, `test_fr18_second_transaction_waits_for_the_lock_and_finds_reserved`, `test_fr18_failed_reservation_rolls_back_the_whole_order` |
| FR-19: резерв блокирует любые лицензии | `unavailable_reason`, `FOR SHARE` в `create_order` | `test_fr19_no_lease_of_a_reserved_beat` |
| FR-20: платёж `capture: false`, `Idempotence-Key`, `return_url` | `payments/service.py` → `create_payment`, `payment_body` | `test_fr20_fr30_payment_with_split_for_three_producers` |
| FR-21: 3 повтора с одним ключом, `503`, резерв сохраняется | `payments/gateway.py` → `_request` | `test_fr21_gap62_http_client_retries_three_times_with_the_same_key`, `test_fr21_provider_unavailable_keeps_the_reservation` |
| FR-22: сверка статуса, один раз на событие, `200` на повторы, IP | `payments/events.py` → `process`; `payments/router.py` | **`test_fr22_repeated_webhook_three_times_in_a_row`**, **`…_at_once`**, `test_fr22_body_is_not_trusted`, `test_fr22_ip_check`, `test_fr22_yookassa_unreachable_…` |
| FR-23: проверка продажи, `capture`/`cancel` | `events._on_hold`, `_sell`, `decision` | **`test_fr23_expired_reservation_beat_still_free_is_sold`**, **`…_taken_by_another_order_is_canceled`**, **`…_already_sold_is_canceled`**, `test_fr23_lease_of_a_beat_sold_meanwhile_is_canceled` |
| FR-24: `paid` (в том числе из `expired`), скрыть Exclusive, уведомить | `events._on_succeeded`, `_sale_emails` | **`test_fr24_lease_order_expired_after_24h_still_paid`**, `test_fr22_fr24_hold_capture_and_paid` |
| FR-25: отказ банка → повтор с новым ключом | `events._on_canceled`, `create_payment` (GAP-40) | `test_fr25_after_bank_decline_a_new_payment_has_a_new_key` |
| FR-26: PDF договора, `pdf_sha256` | `contracts/issue.py` → `issue_contracts`, `render_pdf`, `stamp` | `test_fr26_pdf_for_every_item_is_stored_with_its_hash`, `test_fr26_stamps_and_determinism`, `test_fr26_contract_text_must_be_the_signed_one` |
| FR-27: опрос 2 с / 60 с, ссылки, текст таймаута | `PaymentReturnPage.tsx`, `lib/payment.ts` | `payment.test.ts`; ручной прогон |
| FR-28, NFR-8: ссылки по лицензии, ≤ 1 часа, только владельцу оплаченного | `purchases/service.py` → `downloads`; `storage.presigned_get` | `test_fr28_*`, `test_nfr8_link_lifetime_never_exceeds_an_hour` |
| FR-29: истёкшие резервы и заказы | `orders/expiry.py` | `test_fr29_*` |
| FR-30, NFR-25: сплитование, комиссия сверх цены | `orders/money.py`, `payments/service.py` → `transfers_for`; проверка в моке | **`test_fr20_fr30_payment_with_split_for_three_producers`**, `test_fr30_fee_is_rounded_to_kopecks_per_item`, мок `test_fr30_wrong_split_is_refused` |
| FR-32: снимок данных в заказе | `orders/service.py` → `_snapshot` | `test_fr15_fr30_fr32_order_for_two_producers` |
| REST §2.12: «Мои покупки» | `purchases/service.py` → `purchases`; `PurchasesPage.tsx` | `test_my_purchases_lists_paid_items_with_date_and_hash` |
| REST §2.10, UC-14: статистика продаж | `purchases/service.py` → `sales`; `SalesPage.tsx` | `test_uc14_*`, `SalesPage.test.ts` |
| NFR-7: Audit Log | `write_audit` в заказе, оферте, каждом событии платежа, отмене, оплате, выпуске договора | `test_fr15_fr30_fr32_…`, `test_fr22_fr24_hold_capture_and_paid` |
| NFR-20: файлы покупателя после удаления бита | `downloads` не смотрит на статус бита | `test_nfr20_files_stay_available_after_the_beat_is_deleted` |
| GAP-35: падение между коммитом и `capture` | `events.settle_stuck_payments` в планировщике | `test_gap35_crash_before_capture_is_finished_by_the_scheduler`, `test_gap35_scheduler_cancels_for_a_canceled_order` |
| GAP-37: окончательный отказ `capture`, истёк холд | `events._capture_failed`, `_on_canceled` | `test_gap37_*` |
| GAP-43: PDF до коммита, одинаковый при повторе | `issue_contracts`, `SOURCE_DATE_EPOCH` | `test_gap43_*` (в том числе другой процесс) |

Жирным выделены обязательные тесты из CLAUDE.md.

## Экскурсия по коду

- **Заказ:** начните с [`orders/service.py`](../../backend/app/orders/service.py) → `create_order`. В шапке файла все шаги транзакции. Шаг 3 — резерв, ради которого написан тест гонки.
- **Платёж:** [`payments/service.py`](../../backend/app/payments/service.py) → `create_payment` — проверки, сплитование, запрос в ЮKassa. Как именно ходим в ЮKassa и повторяем — в [`payments/gateway.py`](../../backend/app/payments/gateway.py).
- **Вебхук — сердце среза:** [`payments/events.py`](../../backend/app/payments/events.py):
  - `process` — сверка, дедупликация, блокировки;
  - `_on_hold` → `_sell` — проверка FR-23 в точке сохранения (savepoint);
  - `decision` — «списать или отменить» только по данным из БД;
  - `run_followups` — вызовы после ответа `200`;
  - `settle_stuck_payments` — планировщик.
- **Договор:** [`contracts/draft.py`](../../backend/app/contracts/draft.py) — текст проекта. [`contracts/issue.py`](../../backend/app/contracts/issue.py) — PDF и штамп. Шаблоны — в `contracts/templates/`.
- **Выдача:** [`purchases/service.py`](../../backend/app/purchases/service.py).
- **Мок ЮKassa:** [`yookassa_mock/mock/main.py`](../../yookassa_mock/mock/main.py) — адреса и пульт, [`payments.py`](../../yookassa_mock/mock/payments.py) — статусная модель платежа, [`webhooks.py`](../../yookassa_mock/mock/webhooks.py) — повторы уведомлений.
- **Фронтенд:** `pages/CheckoutPage.tsx`, `pages/OrderPage.tsx` (`PayPanel`), `pages/PaymentReturnPage.tsx`, `components/DownloadLinks.tsx`.

## Как проверить руками

1. `docker compose up -d`. Демо-набор, если его ещё нет: `docker compose exec api python -m seeds.demo_beats`.
2. Войдите Артистом (`SEED_ARTIST_*` в `.env`). Положите в корзину биты разных Продюсеров: у «Nova Sound» и «Test Producer» по нескольку битов.
3. Оформите заказ → «Перейти к оплате» → на странице мока «Успешная оплата» → на странице возврата «Скачать файлы».
4. Попробуйте «Отказ банка» и «Оплатить снова».
5. Пульт мока: <http://localhost:8100/admin>. Там видно распределение денег, можно повторить вебхук «подряд» или «одновременно» и сломать запросы.
6. Логи: `docker compose logs -f api`. В них цепочка платежа, строки `already processed: duplicate` и письма `EMAIL to=…`.
7. «Мои покупки»: хэш договора можно сверить с файлом. В PowerShell: `Get-FileHash .\contract-4-1.pdf -Algorithm SHA256`.
8. Войдите Продюсером (`SEED_PRODUCER2_*`) → «Мои продажи».
9. В БД:
   - `SELECT * FROM payment_events;`
   - `SELECT pdf_key, pdf_sha256 FROM contracts;`
   - `SELECT action, details FROM audit_log ORDER BY id DESC LIMIT 15;`
10. Ускорить резерв для демонстрации: `RESERVATION_TTL_MINUTES=2` в `.env`, затем `docker compose up -d`.

## Что важно знать

- **Exclusive пока нельзя оплатить:** заказ создаётся и резервирует бит, но платёж отвечает `428 SIGNATURE_REQUIRED`. Подпись кодом из SMS — срез 4. Штамп ПЭП для PDF уже готов и проверен тестом.
- **Договоры заказов № 1 и № 3** выпущены после 3c той же функцией `issue_contracts`: эти заказы оплатили ещё до появления PDF. Проверка `draft_sha256` для них прошла.
- **Воспроизводимый PDF.** Шрифт внутри PDF хранил время генерации, поэтому повторная генерация давала другой `pdf_sha256`. Исправлено через `SOURCE_DATE_EPOCH`, это записано в ADR 0004 и покрыто тестом на два процесса.
- **Новые GAP:** 66 (свой резерв в корзине), 67 (имя события — по фактическому статусу), 68 (второй холд оплаченного заказа), 69 (период статистики продаж).
- **Упрощения, о которых надо знать:**
  - юридический текст договора и оферты — заглушка (GAP-31);
  - возвраты при двойном списании вне MVP: такой случай только записывается в Audit Log (GAP-68);
  - поле даты в «Моих продажах» — стандартное поле браузера. Формат даты в нём задаёт язык браузера: в русском — ДД.ММ.ГГГГ.
- **Шапка сайта:** пунктов меню стало больше, поэтому полное меню видно от 1280 px, а уже — кнопка ☰.
