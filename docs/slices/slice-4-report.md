# Срез 4. Итоги

Дата: 12.11.2026. План — [slice-4-plan.md](slice-4-plan.md). Решение аналитика по GAP-70 — вариант А (миграция `0003`).

## Что сделано

- **Миграция `0003`:** колонка `signature_otps.created_at` и два индекса (GAP-70). Это записано в ADR 0007 как дополнение.
- **Core API**, модуль `backend/app/signature/`:
  - `GET /v1/orders/{id}/contract-draft` — текст договора по каждой позиции Exclusive и его SHA-256, до запроса кода;
  - `POST /v1/orders/{id}/signature/otp` — лимиты NFR-31, отмена прежнего кода, HMAC нового, SMS, `202`;
  - `POST /v1/orders/{id}/signature/verify` — блокировка строки кода, срок, попытки, сравнение HMAC; затем договор `otp` на каждую позицию Exclusive и записи в Audit Log.
- **Мок SMS:** метод `send_sms` в интерфейсе `Notifier`. Код пишется в лог `api` (`docker compose logs api | grep SMS`). `SMS_MODE=unavailable` изображает недоступность провайдера (GAP-72).
- **Единый формат ошибок** теперь умеет передавать заголовки: `429` отдаёт `Retry-After` (GAP-73).
- **Экран:** блок «Договор на Exclusive» на странице заказа:
  - текст и хэш договора;
  - «Подписать», поле кода (`autocomplete="one-time-code"` — телефон сам подставит код из SMS);
  - отсчёт жизни кода и паузы до нового;
  - ошибки понятным текстом.
- **PDF:** штамп ПЭП из 3c впервые работает на живых данных. Колонку подписей в штампе расширил: «Способ подтверждения» больше не переносится.

## Проверки

| Что | Результат |
| --- | --- |
| Тесты Core API | 257 прошли (+18 по подписи) |
| Тесты мока ЮKassa / Media Worker | 15 / 32 прошли (без изменений) |
| Тесты фронтенда | 41 прошёл (+2: отсчёты, поле кода) |
| Типы | без ошибок |
| Браузер, сквозной Exclusive | Exclusive на Nova Pulse → заказ № 5, резерв 14:57, оплата выключена → блок договора с текстом и SHA-256 → «Подписать» → «Код отправлен на +7 (900) ***-**-33», отсчёты 4:56 и 0:56 → код из лога → неверный код «осталось попыток: 2» → верный → «Договор на Exclusive подписан», оплата включилась → «Успешная оплата» → MP3, WAV, стемы и договор 5-1 скачиваются, хэш PDF совпал с БД, бит `sold` |
| PDF 5-1 | штамп ПЭП по RFC §5: маска телефона, «одноразовый SMS-код», время МСК, «соглашение о ПЭП от 03.11.2026», полный SHA-256 проекта = `contracts.draft_sha256` |
| БД после покупки | `signature_otps`: `attempts = 1`, `confirmed_at` заполнен, `code_hash = hmac-sha256$…`; Audit Log: `order.created → signature.otp_sent → signature.code_rejected → contract.signed → payment.created → … → contract.generated → payment.succeeded` |
| Ширина 375 px | блок подписи без горизонтальной прокрутки, текст договора прокручивается внутри рамки |

## Требование → код → тест

| Требование | Код | Тест |
| --- | --- | --- |
| RFC §3 п. 2: текст до кода | `signature/service.py` → `contract_draft`; `SignaturePanel.tsx` | `test_contract_draft_is_shown_before_the_code`, `test_contract_draft_needs_a_pending_order_with_exclusive` |
| RFC §3 п. 3, §6: подпись → `contracts` (`otp`), Audit Log | `verify` | `test_rfc3_send_code_and_sign` |
| RFC §2, FR-17: без подписи нет платежа | `payments/service.py` (`428`, срез 3) | `test_fr26_exclusive_purchase_end_to_end` |
| NFR-31: 3 попытки | `verify` (`attempts`, `CODE_ATTEMPTS_EXCEEDED`) | **`test_nfr31_three_wrong_attempts_then_429_even_for_the_right_code`** |
| NFR-31: одновременный перебор | `verify` → `SELECT … FOR UPDATE` строки кода | **`test_nfr31_parallel_guessing_counts_only_three_attempts`** |
| NFR-31: 5 минут | `send_code` (`expires_at`), `verify` | **`test_nfr31_code_lives_five_minutes`** |
| NFR-31: повтор не раньше 60 с; новый код отменяет старый (GAP-34) | `send_code` (лимит, `UPDATE … expires_at = now()`) | **`test_nfr31_resend_not_earlier_than_60_seconds_and_new_code_cancels_old`** |
| NFR-31: 5 в час на пользователя | `send_code` (блокировка строки пользователя, счёт через `orders.customer_id`) | **`test_nfr31_five_codes_per_hour_per_user_over_all_orders`** |
| NFR-31: в БД только хэш | `_code_hash` (HMAC-SHA256 с `OTP_SECRET`) | **`test_nfr31_only_an_hmac_of_the_code_is_stored`** |
| Одноразовость (GAP-34) | `verify`, `_signable` | **`test_gap34_signed_once`** |
| GAP-28: один код на все Exclusive, договор на каждую позицию | `_exclusive_drafts`, `verify` | **`test_fr26_exclusive_purchase_end_to_end`** |
| FR-26, RFC §5: штамп ПЭП, `draft_sha256` и `pdf_sha256` | `contracts/issue.py` → `stamp` | `test_fr26_exclusive_purchase_end_to_end`, `test_fr26_stamps_and_determinism` |
| GAP-9: хэши проектов при отправке = в договорах | `send_code` → audit `signature.otp_sent` | `test_fr26_exclusive_purchase_end_to_end` |
| GAP-33: телефон из снимка заказа | `send_code` | `test_rfc3_send_code_and_sign`, `test_gap33_phone_required_if_the_snapshot_has_none` |
| GAP-34: резерв истёк | `_signable` | `test_gap34_reservation_over_blocks_signing` |
| GAP-72: SMS недоступен | `send_code` (SMS до коммита), `LogNotifier.send_sms` | `test_gap72_sms_failure_keeps_nothing_and_spends_no_limit`, `test_log_mock_can_pretend_the_provider_is_down` |
| GAP-73: нет кода → `410`; `429` с `Retry-After` | `verify`, `_too_many`, `ApiError.headers` | `test_gap73_verify_without_a_code_is_expired`, тест повтора через 60 с |
| Доступ только владельцу | `owned_order` | `test_signature_only_for_the_owner` |
| Формат кода не тратит попытку | `VerifyIn` | `test_wrong_format_does_not_spend_an_attempt` |

Жирным выделены тесты из плана среза (раздел 9).

## Экскурсия по коду

- **Начните с** [`signature/service.py`](../../backend/app/signature/service.py). В шапке файла — три шага подписи. Дальше читайте по порядку:
  - `send_code`: блокировка строки пользователя, лимиты, отмена прежнего кода, HMAC, SMS до коммита;
  - `verify`: `SELECT … FOR UPDATE` и комментарий, зачем он нужен; неверный код фиксируется коммитом до ответа с ошибкой.
- **Хэш кода:** функция `_code_hash`. Секрет `OTP_SECRET` лежит в `.env`, без него хэш из базы бесполезен.
- **Миграция:** `backend/migrations/sql/0003_signature_otps_created_at.sql`.
- **Мок SMS:** `backend/app/notifications/service.py` → `LogNotifier.send_sms`.
- **Экран:** `frontend/src/components/SignaturePanel.tsx`; отсчёты и очистка поля кода — `frontend/src/lib/time.ts`.

## Как проверить руками

1. Войдите Артистом, положите в корзину Exclusive и оформите заказ. Свободные демо-биты с Exclusive: Gold Chains (вернётся в продажу, когда истечёт заказ № 6), Midnight Neon, Trap Lord, Velvet R&B, Pop Sugar.
2. На странице заказа прочитайте договор и нажмите «Подписать». Код возьмите из лога:
   ```bash
   docker compose logs api | grep SMS
   ```
3. Введите неверный код и посмотрите счётчик попыток. Три неверных подряд → «Попытки ввода закончились». Нажмите «Отправить код ещё раз» — кнопка станет активной через 60 с.
4. Введите верный код → «Перейти к оплате» → «Успешная оплата» → скачайте договор и посмотрите штамп ПЭП.
5. В БД:
   - `SELECT id, order_id, attempts, created_at, expires_at, confirmed_at, code_hash FROM signature_otps;`
   - `SELECT signature_type, signer_phone, draft_sha256 FROM contracts WHERE signature_type = 'otp';`
   - `SELECT action, details FROM audit_log WHERE action LIKE 'signature%' OR action = 'contract.signed' ORDER BY id;`
6. Недоступный SMS: `SMS_MODE=unavailable` в `.env` → `docker compose up -d` → «Подписать» → «SMS-сервис временно недоступен». Потом верните `normal`.

## Что важно знать

- **Exclusive теперь покупается целиком:** корзина → заказ и резерв → подпись кодом → оплата → `sold` → PDF со штампом ПЭП → MP3, WAV, стемы.
- **Заказ № 6 (Gold Chains)** я оставил неподписанным при проверке вёрстки на телефоне. Он истечёт сам (FR-29), и бит вернётся в продажу — заодно живая демонстрация планировщика.
- **Договор 5-1** выпущен до расширения колонки штампа. Его не перегенерирую: файл и `pdf_sha256` должны оставаться прежними. Новые договоры получат новую вёрстку штампа.
- **Код в логе — это и есть «доставка».** В настоящем окружении на его месте был бы SMS-провайдер за тем же интерфейсом `Notifier`.
- **Время подписи входит в 15 минут резерва.** Подпись резерв не продлевает (FR-18). Если время вышло, блок подписи исчезает и остаётся «Время резерва вышло».
- **Новые GAP:** 70–73. GAP-70 решён вариантом А.
