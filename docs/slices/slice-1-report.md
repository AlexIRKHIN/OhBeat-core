# Срез 1. Итоги

Дата: 02.11.2026. План — [slice-1-plan.md](slice-1-plan.md). Части FR-34 перенесены по решению аналитика: публичная страница продюсера — в срез 2, статистика продаж — в срез 3.

## Что сделано

- **1a — Core API.** Создание бита с проверками и стоп-листом, формы прямой загрузки в MinIO и их перевыпуск, подтверждение загрузки (`processing` + `outbox` в одной транзакции), «Мои биты», цены, снятие с продажи, возврат, логическое удаление. Новые процессы: outbox relay (`outbox-relay`), планировщик FR-8 (`scheduler`). Очереди RabbitMQ: рабочие, три очереди задержки и DLQ.
- **1b — Media Worker** (`media-worker`, без HTTP и без доступа к БД): проверка WAV, ZIP и обложки по содержимому, мок-антивирус, MP3 320 и превью 128 с войстегом «OhBeat» каждые 20 с, раскладка по бакетам, повторы 30 с / 2 мин / 10 мин и DLQ. **Приём результатов** в Core API (`media-results`): идемпотентный, с письмом Продюсеру (мок пишет в лог). Генератор образцов файлов (`samples/`).
- **1c — экраны.** «Загрузить бит» по UI-спецификации §1 и «Мои биты»; пункты меню у Продюсера; доступ к экранам только с ролью Продюсера.

## Проверки

| Что | Результат |
| --- | --- |
| Тесты Core API (`pytest`) | 142 прошли |
| Тесты Media Worker (`pytest`, настоящие FFmpeg, MinIO, RabbitMQ) | 32 прошли |
| Тесты фронтенда (`vitest`) | 22 прошли |
| Типы и сборка фронтенда | без ошибок |
| Живой прогон через API | хороший бит → `active` (5 файлов с размерами и хэшами); WAV на 11 минут, обложка 3:2, ZIP с `.exe`, случайные байты вместо WAV → `rejected` с понятной причиной; письма в логе |
| Живой прогон в браузере | MP3 в зоне WAV → красное уведомление; фильтр BPM; блокировка жанров после третьего; цена 99 → ошибка у поля; Exclusive без ZIP → подсказка и неактивная кнопка; отправка: «Отправка…» → «Загрузка файлов» → «Проверяем…» → «Бит загружен и обрабатывается» → «Мои биты» → сам сменился на «Опубликован»; снять с продажи; удалить через модальное окно; «Загрузить заново» с заполненными данными; ширина 320 px; RU/EN без непереведённых ключей |
| Превью из публичного бакета | `206 Partial Content`, `Cache-Control: immutable`; приватный бакет без подписи — `403` |

## Требование → код → тест

| Требование | Код | Тест |
| --- | --- | --- |
| FR-1 файлы, стемы для Trackout/Exclusive | `frontend/src/pages/UploadBeatPage.tsx`, `backend/app/catalog/service.py` → `create_beat` | `test_beats_create.py::test_fr1_*` |
| FR-2, FR-3 форма и проверки на клиенте | `UploadBeatPage.tsx`, `frontend/src/lib/beatFiles.ts` | `beatFiles.test.ts`; ручной прогон |
| FR-4 прогресс и «Повторить» | `UploadBeatPage.tsx` → `uploadOne`, `components/Dropzone.tsx`, `api/client.ts` → `uploadToS3` | ручной прогон |
| FR-5 сообщение и статус в «Моих битах» | `UploadBeatPage.tsx` → `confirm`, `pages/MyBeatsPage.tsx` (опрос каждые 5 с) | ручной прогон |
| FR-6 проверки, стоп-лист, presigned POST, перевыпуск | `catalog/service.py` → `create_beat`, `reissue_uploads`; `catalog/stoplist.py` | `test_beats_create.py::test_fr6_*`, `test_beats_confirm.py::test_fr6_*` |
| FR-7 HeadObject + outbox в одной транзакции | `catalog/service.py` → `confirm_upload`, `common/outbox.py` | `test_fr7_*` |
| FR-7 relay, «как минимум один раз» | `background/relay.py` | `test_relay.py` |
| FR-8 брошенные загрузки | `catalog/service.py` → `delete_abandoned_uploads`, `background/scheduler.py` | `test_fr8_uploading_older_than_24h_becomes_deleted` |
| FR-9 проверки по содержимому | `worker/worker/checks.py`, `antivirus.py` | `worker/tests/test_checks.py` |
| FR-10 MP3 320 и превью с войстегом | `worker/worker/media.py` | `test_fr10_*` |
| FR-11 раскладка по бакетам | `worker/worker/processor.py` | `test_fr10_fr11_processed_outputs` |
| FR-12 `active` / `rejected` + уведомление | `backend/app/catalog/media_results.py`, `notifications/service.py` | `test_media_results.py::test_fr12_*` |
| FR-13 ключи, а не ссылки | `catalog/models.py` (`storage_key`), ссылки строятся при выдаче | `test_fr6_create_beat_returns_upload_forms` |
| FR-34 «Мои биты», цены, скрыть / вернуть / удалить | `catalog/service.py`, `MyBeatsPage.tsx` | `test_beats_manage.py` |
| NFR-20 удаление с подтверждением, логическое | `components/Modal.tsx`, `delete_beat` | `test_nfr20_logical_delete`; ручной прогон |
| Повторная доставка сообщения (обязательный) | `media_results.py` (`WHERE status = 'processing'` + блокировка), детерминированные ключи Worker'а | `test_repeated_delivery_*`, `test_repeated_command_writes_the_same_keys` |
| Повторы и DLQ | `worker/worker/main.py`, `backend/app/background/media_results.py` | `test_temporary_failure_*` |

## Экскурсия по коду

| Где | Что посмотреть |
| --- | --- |
| `backend/app/catalog/service.py` | `create_beat` (FR-6) и `confirm_upload` (FR-7): одна транзакция «статус + outbox» |
| `backend/app/background/relay.py` | Как outbox превращается в сообщение RabbitMQ и почему возможны дубли |
| `backend/app/common/rabbit.py` | Схема очередей и комментарий-картинка |
| `worker/worker/processor.py` | Обработка одной командой: скачать → проверить → MP3 → разложить → результат |
| `worker/worker/main.py` | ACK, повтор через очередь задержки, NACK в DLQ |
| `backend/app/catalog/media_results.py` | Почему повторное сообщение ничего не ломает |
| `frontend/src/pages/UploadBeatPage.tsx` | Шаги загрузки в браузере: создание → параллельная загрузка → подтверждение |

## Как проверить руками

1. `docker compose up -d` (после изменений кода — `docker compose up -d --build`).
2. Образцы файлов: `docker compose run --rm media-worker python -m worker.samples` → папка `samples/`.
3. Войти Продюсером (логин и пароль — `SEED_PRODUCER_*` в `.env`) → «Загрузить бит» → `samples/good_master.wav`, `good_cover.jpg`, `good_stems.zip` → через несколько секунд в «Моих битах» «Опубликован», в карточке можно послушать превью с войстегом.
4. Плохие образцы (`bad_*`) — каждый даст свою причину отклонения.
5. Свои глаза:
   - RabbitMQ UI <http://localhost:15672> → Queues;
   - MinIO Console <http://localhost:9001>;
   - `docker compose logs -f media-worker media-results` — шаги обработки и письма.
6. Повторы и DLQ: `ANTIVIRUS_MODE=unavailable` в `.env` → `docker compose up -d media-worker` → загрузить бит с ZIP → в RabbitMQ UI сообщение проходит очереди задержки (около 12,5 минуты) и попадает в `beat_processing_dlq`. Потом вернуть `normal`.
7. Тесты:
   - `docker compose exec api pytest`
   - `docker compose exec media-worker pytest`
   - `docker compose exec frontend npx vitest run`

## Что важно знать

- **Выбор файла через системный диалог** в браузере вручную я не проверял: инструмент не умеет его открывать. Файлы подкладывались скриптом в те же поля. Дальше путь был настоящий: проверки, загрузка в MinIO, подтверждение, обработка. Попробуйте один раз сами перетащить файл мышью в зону «Master WAV».
- **«Обработка» в «Моих битах» мелькает очень коротко**: локально 6–40-секундный WAV обрабатывается за 1–2 секунды. То, что список сам обновился, видно по повторному запросу.
- **Исправлено по ходу:** служебные файлы macOS в ZIP теперь считаются посторонними (GAP-18); поле BPM правильно фильтрует вставленный текст; у тестов Core API свои бакеты MinIO; кнопки «Повторить» у файлов остаются активными, пока форма заблокирована на время загрузки.
- **Новых GAP в части 1c нет.** За срез добавлены GAP-50…GAP-57. ADR 0006 уточнён: образец «вируса» помечен собственной меткой, а не EICAR.
