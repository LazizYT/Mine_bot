# AGENTS.md — проект MINE_BOT_OS (Telegram-бот + Flask-панель)

Этот файл — постоянная память проекта. Обновляй его при каждом значимом изменении
(новые фиксы, настройки, договорённости с пользователем), чтобы следующий сеанс
opencode сразу знал контекст.

## Кратко о проекте

- Telegram-бот (pyTelegramBotAPI) для автоматизации канала @lazikomods про Minecraft-моды
  + Flask веб-панель управления (dashboard).
  - ВАЖНО: канал — именно **@lazikomods** (БЕЗ 's'!), подтверждено пользователем. В коде подставляется актуальный хэндл из env CHANNELS.
- ИИ: Groq (llama-3.3-70b-versatile), промпт хранится в БД и редактируется из веб-панели.
- БД: SQLite. Медиа: водяные знаки через Pillow. Планировщик: APScheduler.
- Точка входа: `main.py` (запуск через `launcher.py`). Веб-сервер: `webapp.py` (порт из `PORT`, дефолт 8080).

## Запуск

- Локально: `pip install -r requirements.txt`, создать `.env` (см. `.env.example`/INSTALL.md), `python main.py`.
- На сервере (justrunmy.app): Docker-образ собирается из `Dockerfile` (python:3.11-slim), CMD = `python launcher.py`.

## Обязательные env-переменные (файл `.env`, НЕ коммитится)

- `TELEGRAM_TOKEN` (обязательная), `GROQ_API_KEY`, `GEMINI_KEY`, `CHANNELS` (фактически `@lazikomods`), `PORT` (дефолт 8080). Опционально `PANEL_USER`/`PANEL_PASSWORD` (запасной вход по паролю; на проде заданы), `PANEL_AUTH_REQUIRED` (дефолт 1 — авторизация ОБЯЗАТЕЛЬНА).
- CurseForge удалён полностью (env `CURSEFORGE_API_KEY` больше не читается).
- `ADMIN_IDS` задаётся в `config.py`, а не в env.
- `DB_PATH` — путь к SQLite (дефолт `data/bot_data.db` относительно рабочей папки → в контейнере `/app/data/bot_data.db`, на volume).

## Деплой: justrunmy.app

- Git remote: `https://Bc2g6:d7A9Xxs6H@justrunmy.app/git/r_e2R5D` (branch `deploy`), командой `git push -u <remote> HEAD:deploy`.
- Приложение: **MineBot_cli (id 53038)**, HTTPS URL: `https://gitr_e2r5d-883.xs001.jrnm.app` (порт 80 → контейнер 8080).
- Пуш автоматически пересобирает Docker-образ и рестартит приложение.

## MCP доступ к justrunmy.app (настроен)

- `opencode.json` подключает remote MCP-сервер `justrunmy` → `https://justrunmy.app/api/mcp`.
- Ключ `X-User-Identity` лежит в `.opencode/jrnm_identity.txt` (в gitignore, НЕ коммитить), подставляется через `{file:...}`.
- Инструменты `jrnm_*` позволяют: статус/логи/порты/volume/env приложения, рестарт, команды в контейнере, деплой.
- ВАЖНО: MCP подхватывается только после перезапуска opencode.

## Последние фиксы (сделаны)

0. **ХАРДЕНИНГ + РЕФАКТОРИНГ (2026-08-11)**:
   - **Панель теперь ТОЛЬКО для владельца**: `config.ADMIN_IDS = [8641832514]` (user id пользователя). Новая авторизация: `panel_auth.py` (валидация Telegram WebApp initData по HMAC + подписанные сессионные cookie `panel_session`). Вход через кнопку Studio в боте (WebApp initData) ИЛИ по логину/паролю (`/api/auth/login`). Включена ОБЯЗАТЕЛЬНО (`PANEL_AUTH_REQUIRED=1` по умолчанию; отключается только `PANEL_AUTH_REQUIRED=0` для тестов). Неавторизованные: HTML → редирект на `/auth`, API → 401.
   - **SQLite WAL**: `database._connect()` теперь `PRAGMA journal_mode=WAL` + `busy_timeout=10000` + `timeout=15` — защита от "database is locked" при конкурентной записи. Все прямые `sqlite3.connect(DB_PATH)` заменены на `_connect()`.
   - **waitress**: prod-сервер вместо Flask dev server (`waitress.serve(threads=8)`, fallback на `app.run`). Добавлен в requirements.txt.
   - **Blueprints**: `webapp.py` ужат до фабрики приложения (82 маршрута); логика разнесена: `web_helpers.py` (общие хелперы + auth-гейт), `web_blueprints/auth.py`, `web_blueprints/main.py` (дашборд + legacy API), `web_blueprints/platform.py` (/api/platform/*). Тесты не сломаны.
   - **Бэкапы БД**: `database.backup_db()` (SQLite online backup API, безопасен при WAL) в `data/backups/`, хранит 14 копий, ежедневно в 03:05 (джоб в `main.py`).
   - **Тесты при сборке**: Dockerfile теперь запускает `python -m unittest` (dummy env-токены на время сборки) — сломанный код не доедет до деплоя. Всего **62 теста OK** (включая `test_panel_auth.py` — 7 тестов, и пагинация audit).
   - **Пагинация AUDIT** в /platform: `/api/platform/audit` принимает `page`/`per_page`/`action` и возвращает `total`/`pages`; в панели PREV/NEXT + счётчик.
   - **ПРОД-ENV**: `CHANNELS=@lazikomods` (БЕЗ 's', подтверждено пользователем). PANEL_USER/PANEL_PASSWORD заданы (запасной вход по паролю).
   - **Проблема**: панель теперь требует авторизации — при первом открытии через Telegram WebApp покажется страница входа с кнопкой "ВОЙТИ ЧЕРЕЗ TELEGRAM" (автоматически). Если открывать из обычного браузера — логин/пароль.

0. **CONTENT DISTRIBUTION PLATFORM (2026-08-11, фазы 1-8)**:
   - **Новые модули**: `content_storage.py` (Content Storage: CRUD постов, дедуп по content_hash, reuse-логика, селекторы random/weighted/fifo/lifo/least_used/category_rotation/smart, `select_post`, `storage_stats`), `channel_manager.py` (настройки каналов `ensure/get/save/get_all/channel_table`, сети `create/get/rename/delete/add_channel/pause_network/is_network_paused/clone_network`, шаблоны `create/get/delete/apply_template`, bulk `bulk_update`, `clone_settings`, `delete_channel`), `scheduler_engine.py` (test_mode, `compute_next_run` interval/cron+tz, `find_due_channels`, `build_channel_settings`, `add_to_storage_and_queue`, `select_best_post`, `run_scheduler(dry_run)`, `retry_failed`, `log_publication`, `log_event`, `notify_admin`, `publication_history`, `analytics`, `calendar_events`).
   - **БД** (`database.py`): таблицы `posts`, `content_tags`, `post_tags`, `channel_settings`, `networks`, `network_channels`, `templates`, `schedules`, `publications`, `publication_logs`, `system_events`, `audit_log` + миграции queue (`post_id`, `priority`, `category`, `tags`, `created_at`); хелпер `database._connect()`. `channel_settings` поля: name/username/network_id/active/auto_publish/interval_hours/cron/timezone/start_time/end_time/max_posts_per_day/selection/categories/tags/languages/sources/reuse_mode/reuse_days/post_template/prefix/suffix/hashtags/link_preview/media_settings/duplicate_protection/flood_protection/failed_retry_count/cooldown/rate_limit/min_delay.
   - **Интеграция Smart Queue** (`handlers.py`): `_add_to_queue_integrated()` + `_channel_id_by_username()` — все три точки добавления в очередь (черновики/авто/расписание) теперь сохраняют пост и в storage, и в queue, и в schedules.
   - **Планировщик** (`main.py`): `scheduler_engine.run_scheduler` каждую минуту + `retry_failed` каждые 30 мин (вместо publisher.process_queue).
   - **Web-панель**: новая страница `/platform` (`templates/platform.html`) — Storage/Channels/Networks/Templates/Scheduler/Publications/Analytics/Events. API `/api/platform/*` (36 роутов: posts CRUD/archive/restore/duplicate/publish, channels settings/clone/bulk, networks CRUD/pause/clone, templates CRUD/apply, scheduler run/test-mode, publications history/retry, analytics, calendar, events, storage stats, settings).
   - **Фикс**: в `scheduler_engine.build_channel_settings` убран битый лишний запрос (`SELECT post_id ... FROM posts`).
   - **Фикс**: `channel_table()` — `reuse_mode`/`reuse_days` теперь отдаются корректно (была путаница).
   - **Фикс**: `content_storage.update_post` — добавлены счётчики использования (`usage_count`, `is_used`, `times_published`, `last_used_at`, `published_channels`) — раньше `mark_used` молча их терял.
   - **Фикс**: `channel_manager.add_channel_to_network` — теперь вызывает `ensure_settings` (иначе `network_id` не проставлялся, если канал ещё не имел настроек).
   - **Аудит (Phase 9)**: `database.audit_log()`/`get_audit_log()`; запись во все мутирующие роуты `/api/platform/*` + в `run_scheduler`/`retry_failed`; API `/api/platform/audit`.
   - **Страница ошибок**: разделы ERRORS (failed publications + топ ошибок) и AUDIT в `/platform`.
   - **Тесты (Phase 9)**: `tests/` (unittest, стандартная библиотека, работают в Docker; отдельная временная БД через `DB_PATH`): `test_content_storage.py`, `test_channel_manager.py`, `test_scheduler_engine.py`, `test_webapp.py`, `test_handlers.py`. Запуск: `python -m unittest discover -s tests -p "test_*.py"`. **54 теста OK.**
   - **Тесты**: локально проверены CRUD постов, дедуп, селекторы, каналы/сети/шаблоны/clone/bulk, scheduler dry-run, calendar, аналитика, все `/api/platform/*` + `/platform` (200), интеграция queue→storage (post_id связан), `main`/`handlers` импортируются. Тестовые данные в БД очищены.

1. `database.py` — `DB_PATH` теперь `os.getenv('DB_PATH', os.path.join('data','bot_data.db'))` (кроссплатформенно), папка создаётся автоматически.
2. `database.py` — добавлена функция `get_last_scheduled_time()` (её вызывал `handlers.py`).
3. `mod_parser.py` — реализован `parse_modrinth()` через официальный Modrinth API (проверен: Sodium, 203M+ downloads).
4. `INSTALL.md` — документированы реальные env-переменные.
5. **БАГ-ФИКС-ПАК (2026-08-10) + фичи 2/3/5 + удаление CurseForge**:
   - CurseForge полностью удалён: роуты `/api/curseforge/*`, `mod_parser` (остался только Modrinth), `curseforge.html`, `config.CURSEFORGE_API_KEY`, `BROWSER_ACT_API_KEY`, `google-genai` из requirements.
   - Web-панель: добавлены недостающие роуты `/api/delete/<id>`, `/api/prompts/improve`, `/api/prompts/select`, `/api/settings/interval`, `/api/system/clear-memory`, `/api/upload/logo` (раньше фронтенд получал 404).
   - Панель: починен рендер очереди (в dashboard.html была заглушка-комментарий, очередь не отображалась), Sortable теперь таргетит правильный контейнер, исправлен XSS в комментариях (innerHTML → textContent).
   - Опциональная Basic-авторизация панели (env PANEL_USER/PANEL_PASSWORD; если пароль пуст — панель открыта).
   - Groq-клиент теперь создаётся лениво (`_get_client()`) — отсутствие GROQ_API_KEY больше НЕ роняет бота при импорте. `generate_post`/`translate_post`/`rewrite_post` возвращают None при ошибке (раньше ошибка попадала в пост).
   - Добавлена отсутствовавшая `ai_generator.rewrite_post()` — фича «рерайт» раньше падала AttributeError.
   - Канал: `WATERMARK_TEXT` и промпт приведены к @lazikomods, в сгенерированном тексте хэндл подменяется на `config.DEFAULT_CHANNEL`.
   - Фото без подписи больше не ломает генерацию (заглушка "Minecraft mod photo").
   - Альбомы: уникальные temp-файлы + очистка в finally (была гонка + мусор на диске).
   - Callback `sel_`: split по `_` с maxsplit=2 — каналы с `_` в username больше не ломаются.
   - Кеш статистики подписчиков (10 мин) вместо вызова Telegram API на каждый заход в панель.
   - **Фича 2 — черновики в БД**: таблица `drafts`, переживают рестарт бота; кнопка «Восстановить черновик» при нажатии «Создать».
   - **Фича 3 — аналитика публикаций**: `database.get_post_stats()`, роут `/api/analytics`, карточки TOTAL/TODAY/WEEK/MONTH + график PUBLISHED_PER_DAY (bar chart).
   - **Фича 5 — мониторинг оттока**: `publisher.check_subscriber_drop()` каждые 6ч сравнивает подписчиков и шлёт админу алерт при оттоке.
   - Мёртвый код удалён: `main_new.py`, `reorder_logic.py`, `playwright` и `google-genai` из requirements, `import utils` в handlers.
6. **ПАМЯТЬ ИИ (2026-08-10)**: таблица `ai_memory` (ручные заметки админа, хранятся в БД на volume). Функции `add_memory_note`/`get_memory_notes`/`delete_memory_note`/`clear_memory_notes`. Заметки автоматически подставляются в контекст всех генераций ИИ: `generate_post`, `translate_post`, `rewrite_post`, `generate_reply`, `generate_suggestion_request`, `improve_prompt`, `comments_analyzer.analyze_comments` (через `ai_generator.get_memory_context(limit=10)`). Панель: вкладка «Память» (Xotira/Memory) — CRUD через `/api/memory` (GET/POST), `/api/memory/<id>` (DELETE), `/api/memory/clear` (POST).
7. **БАГ-ФИКСЫ ПАНЕЛИ (2026-08-10)**:
   - Кнопка «studio» (Web App из BotFather) открывала `/studio` → 404. Добавлены алиасы роутов `@app.route('/studio')` и `@app.route('/app')` (тот же дашборд, что `/`).
   - Фото постов не отображались: в карточках очереди/истории не было `<img>`. Добавлены превью (`/file/<file_id>`). Роут `/file/<file_id>` переделан с redirect (токен в URL, в WebApp не грузился) на прокси через `bot.download_file` — отдаёт image/jpeg напрямую, без утечки токена.
   - Кнопка EDIT не работала: `onclick="editPost({{ item|tojson }})"` — кавычки JSON ломали HTML-атрибут. Теперь `editPost(id)` грузит пост через новый роут `/api/post/<id>` (JSON). Аналогично VIEW (`viewFullText(id)`).
   - Роут `api_clear_ai_memory` переименован (конфликт имени endpoint со старым `/api/system/clear-memory`).

## ВЫПОЛНЕНО: настройка приложения в панели justrunmy.app (id 53038, имя MineBot_cli)

Приложение полностью настроено через MCP (инструменты `jrnm_*`):

- **Env-переменные заданы**: TELEGRAM_TOKEN, GROQ_API_KEY, GEMINI_KEY, CHANNELS=@lazikomods, PORT=8080. (CURSEFORGE_API_KEY НЕ задан — пользователь решил пропустить, функция не работает; в логах соответствующий warning.)
- **Порт**: HTTPS mapping containerPort **8080** → внешний 80, домен `gitr_e2r5d-883` → `https://gitr_e2r5d-883.xs001.jrnm.app` открывает дашборд.
- **Volume**: `/app/data` (id 49215). Старый `/data` удалён. БД и водяные знаки лежат на volume — **проверено**: после рестарта маркер-файл и `bot_data.db` сохранились.
- **Run command**: задана явно `python launcher.py` (через `jrnm_set_app_command`).
- Статус: RUNNING, restarts 0. В логах только warning про CurseForge, бот + Flask (порт 8080) поднялись.
- Значения для env взяты из локального `.env` (в нём теперь есть TELEGRAM_TOKEN, GROQ_API_KEY, GEMINI_KEY, CHANNELS=@lazikomods).

### Деплой через git (проверено 2026-08-10)
- Git remote: `https://Bc2g6:d7A9Xxs6H@justrunmy.app/git/r_e2R5D` (branch `deploy`), командой `git push justrunmy HEAD:deploy`.
- Пуш автоматически пересобирает Docker-образ и рестартит приложение. Volume `/app/data` переживёт редеплой.
- После деплоя проверено: root 200, `/api/stats` 200, `/api/analytics` 200, `/logo.png` 200, `/api/curseforge/*` → 404 (удалён), очередь/график рендерятся, в логах нет warning'ов про CurseForge/Groq.

## Правило работы

Пользователь просил: **сохранять текущую переписку/контекст для будущего меня и делать так всегда**.
=> Держать AGENTS.md актуальным после каждого значимого шага (фиксы, деплой, настройки, решения).
