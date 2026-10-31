# ADR 0005. Тесты: pytest на настоящих сервисах, Vitest, Playwright

Дата: 31.10.2026. Статус: принято.

## Контекст

Обязательные тесты (CLAUDE.md): гонка двух покупателей за Exclusive, повторный вебхук, повторная доставка сообщения из очереди, истёкший резерв при `waiting_for_capture`, оплата после `expired`, сумма `transfers` и комиссии. Браузеры по NFR-15 включают Safari 15+.

## Варианты

- **Бэкенд:** pytest на сервисах из `docker compose` или pytest + Testcontainers. Testcontainers на Windows с Docker Desktop заметно медленнее.
- **Фронтенд:** Vitest или Jest. Vitest встроен в Vite и не требует отдельной настройки.
- **Сквозные тесты:** Playwright или Cypress. Cypress не поддерживает Safari, Playwright запускает движок WebKit.

## Решение

- pytest на настоящих PostgreSQL, RabbitMQ и MinIO из `docker compose`. Каждый тест работает в отдельной чистой БД или откатываемой транзакции. Время подменяется, а не ожидается.
- Vitest для компонентов и правил валидации.
- Playwright для сквозного сценария (Chromium и WebKit).

## Последствия

- Гонки проверяются честно: параллельные соединения к настоящему PostgreSQL.
- В названиях тестов — номера требований (`test_fr18_...`).
