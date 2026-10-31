# Срез 0. Итоги

Дата: 31.10.2026. План — [slice-0-plan.md](slice-0-plan.md).

## Что сделано

- **Окружение** одной командой: PostgreSQL 16, RabbitMQ, MinIO, Core API, SPA. MinIO собирается из исходников: публичные образы больше не раздаются ([ADR 0008](../adr/0008-minio-from-source.md)).
- **БД.** Миграция `0001` — побайтная копия `schema.sql` и права роли `ohbeat_app`. Миграция `0002` — `refresh_tokens`, `login_attempts`, `UNIQUE` на договор позиции, индексы. Сиды: 12 жанров, 4 лицензии, Артист, Продюсер, Администратор.
- **Core API:** регистрация, вход, ротация и отзыв токенов, профиль с аватаром, данные покупателя, подключение к продажам, справочники.
- **SPA:** шапка с RU/EN, регистрация, вход, профиль, «Данные покупателя», «Подключиться к продажам», юридические страницы-заглушки, toast при потере связи.

## Проверки

| Что | Результат |
| --- | --- |
| Тесты бэкенда (`pytest`) | 57 прошли, 0 пропущено |
| Тесты фронтенда (`vitest`) | 15 прошли |
| Типы (`tsc`) и сборка под Safari 15+ | без ошибок |
| Ручной прогон в браузере | регистрация → данные покупателя (ИП) → подключение к продажам; ширина 320 px; переключение RU/EN |
| Загрузка из браузера прямо в MinIO | `204` с источника `http://localhost:5173` (CORS работает), аватар опубликован, `Cache-Control: immutable` |

## Требование → код → тест

| Требование | Код | Тест |
| --- | --- | --- |
| FR-31 регистрация, роль Артиста, Audit Log | `backend/app/auth/service.py` → `register` | `test_auth.py::test_fr31_*` |
| FR-31 согласия обязательны | `backend/app/auth/schemas.py` (`check_true`), `frontend/src/pages/RegisterPage.tsx` | `test_fr31_register_requires_both_consents` |
| FR-32 профиль | `backend/app/users/service.py` → `update_profile` | `test_users.py::test_fr32_update_profile` |
| FR-32 данные покупателя (UI-спец. §2) | `users/schemas.py` → `BillingIn`, `common/validators.py`, `frontend/src/pages/BillingPage.tsx` | `test_fr32_billing_*`, `test_inn_checksum`, `validation.test.ts` |
| FR-33 подключение к продажам | `users/service.py` → `connect_producer`, `frontend/src/pages/ProducerConnectPage.tsx` | `test_fr33_*` |
| NFR-4 Argon2id | `backend/app/common/security.py` | `test_nfr4_password_stored_as_argon2_hash` |
| NFR-5 правила пароля | `common/validators.py` → `check_password`, `frontend/src/lib/validation.ts` | `test_nfr5_weak_passwords_rejected`, `validation.test.ts` |
| NFR-22 аватар по содержимому | `common/images.py`, `users/service.py` → `_publish_avatar` | `test_nfr22_*`, `test_s3_rejects_file_bigger_than_declared_limit` |
| NFR-26 два языка | `common/i18n.py`, `frontend/src/i18n.ts` | `test_error_message_language_follows_accept_language` |
| NFR-28/29 даты по Москве | `frontend/src/lib/validation.ts` → `formatMoscowDateTime` | `validation.test.ts` |
| NFR-32 Audit Log только на добавление | `migrations/sql/0001_grants.sql` | `test_schema.py::test_nfr32_*` |
| REST §2.8: 5 неудач за 15 минут | `auth/service.py` → `_recent_failures`, `login` | `test_login_blocked_after_5_failures_*`, `test_login_failures_older_than_15_minutes_*` |
| REST §2.8: ротация refresh-токенов | `auth/service.py` → `refresh` | `test_refresh_rotates_token`, `test_reuse_of_revoked_refresh_token_revokes_whole_family` |
| Схема = `schema.sql` (ADR 0002) | `migrations/versions/0001_reference_schema.py` | `test_migration_0001_equals_reference_schema`, `test_migration_sql_is_unchanged_copy_of_spec_schema` |
| Единый формат ошибок | `backend/app/common/errors.py` | проверяется во всех тестах на ошибки |

## Экскурсия по коду

**Как проходит запрос, на примере `POST /v1/auth/register`:**

1. Браузер отправляет запрос на `localhost:5173/v1/...`. Vite (`frontend/vite.config.ts`) пересылает его в контейнер `api`.
2. `backend/app/main.py` — точка входа. Middleware определяет язык по `Accept-Language`, затем FastAPI находит нужный роутер.
3. `backend/app/auth/router.py` — HTTP-слой. Здесь только «принять → вызвать сервис → вернуть ответ».
4. Pydantic-схема `RegisterRequest` (`auth/schemas.py`) проверяет тело. При ошибке `common/errors.py` превращает её в `400 VALIDATION_ERROR` с `details` по полям.
5. `backend/app/auth/service.py` → `register` — бизнес-правило FR-31. Все вставки идут в одной транзакции, и `db.commit()` в конце фиксирует их разом.
6. Модели таблиц (`users/models.py`, `auth/models.py`, `common/audit.py`) только описывают существующие таблицы. Таблицы создают миграции, а не код.

**Где что лежит:**

| Файл | Зачем |
| --- | --- |
| `docker-compose.yml` | Все сервисы и порядок запуска (`depends_on`) |
| `infra/postgres/init-roles.sh` | Роли БД: владелец, `ohbeat_app`, `ohbeat_api` |
| `backend/migrations/sql/*.sql` | Схема на чистом SQL |
| `backend/seeds/run.py`, `seeds/init_storage.py` | Начальные данные и бакеты MinIO |
| `backend/app/common/` | Общее: настройки, БД, ошибки, переводы, безопасность, хранилище, Audit Log |
| `backend/tests/conftest.py` | Как тесты получают чистую БД `ohbeat_test` |
| `frontend/src/api/client.ts` | HTTP-клиент: токены, обновление по `401`, загрузка в S3 с прогрессом |
| `frontend/src/pages/*` | Экраны |

## Как проверить руками

1. Запуск: `cp .env.example .env` (один раз), затем `docker compose up --build`.
2. Интерфейс: <http://localhost:5173>. Логины и пароли тестовых аккаунтов — в `.env.example` (`SEED_*`).
3. Swagger: <http://localhost:8000/docs>. Можно зарегистрироваться прямо оттуда и сравнить с REST §2.8.
4. Тесты:
   - `docker compose exec api pytest -v`
   - `docker compose exec frontend npx vitest run`
5. Данные в БД: `docker compose exec postgres psql -U postgres -d ohbeat`, затем:
   - `SELECT * FROM audit_log ORDER BY id;` — записи о согласиях и подключении к продажам;
   - `SELECT user_id, token_hash, revoked_at FROM refresh_tokens;` — только хэши, цепочка ротации;
   - `SELECT email, password_hash FROM users;` — строки `$argon2id$...`.
6. MinIO Console: <http://localhost:9001> (логин и пароль — `MINIO_ROOT_*` в `.env`). Аватары лежат в `public-media/avatars/`.
7. Попробовать NFR-32 самому: в psql выполнить `SET ROLE ohbeat_app; UPDATE audit_log SET action = 'x';` → `permission denied`.

## Что важно знать

- **Аватар через диалог выбора файла** инструментом браузера не проверен: он не умеет открывать системный диалог. Тот же запрос (presigned POST из страницы в MinIO) проверен скриптом в браузере, а весь путь — автотестами. Выбор файла руками стоит попробовать вам на экране профиля.
- **IP в Audit Log** показывает адрес шлюза Docker (`172.18.0.1`), а не настоящий IP браузера: Docker Desktop на Windows скрывает адрес клиента. Код берёт IP из `X-Forwarded-For` и в обычной сети записал бы настоящий адрес.
- **Новые GAP:** GAP-46…GAP-49 (ограничения полей профиля, имена полей согласий, смысл `avatar_key`, ответ при пустых данных покупателя).
- **Новый ADR:** 0008 (MinIO из исходников).
