# AGENTS.md — проект MINE_BOT_OS (Telegram-бот + Flask-панель)

Этот файл — постоянная память проекта. Обновляй его при каждом значимом изменении
(новые фиксы, настройки, договорённости с пользователем), чтобы следующий сеанс
opencode сразу знал контекст.

## Кратко о проекте

- Telegram-бот (pyTelegramBotAPI) для автоматизации канала @lazikosmods про Minecraft-моды
  + Flask веб-панель управления (dashboard).
  - ВАЖНО: канал — именно **@lazikosmods** (с 's'), подтверждено пользователем. В коде теперь везде подставляется актуальный хэндл из env CHANNELS.
- ИИ: Groq (llama-3.3-70b-versatile), промпт хранится в БД и редактируется из веб-панели.
- БД: SQLite. Медиа: водяные знаки через Pillow. Планировщик: APScheduler.
- Точка входа: `main.py` (запуск через `launcher.py`). Веб-сервер: `webapp.py` (порт из `PORT`, дефолт 8080).

## Запуск

- Локально: `pip install -r requirements.txt`, создать `.env` (см. `.env.example`/INSTALL.md), `python main.py`.
- На сервере (justrunmy.app): Docker-образ собирается из `Dockerfile` (python:3.11-slim), CMD = `python launcher.py`.

## Обязательные env-переменные (файл `.env`, НЕ коммитится)

- `TELEGRAM_TOKEN` (обязательная), `GROQ_API_KEY`, `GEMINI_KEY`, `CHANNELS` (фактически `@lazikosmods`), `PORT` (дефолт 8080). Опционально `PANEL_USER`/`PANEL_PASSWORD` (Basic-авторизация панели).
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
   - Канал: `WATERMARK_TEXT` и промпт приведены к @lazikosmods, в сгенерированном тексте хэндл подменяется на `config.DEFAULT_CHANNEL`.
   - Фото без подписи больше не ломает генерацию (заглушка "Minecraft mod photo").
   - Альбомы: уникальные temp-файлы + очистка в finally (была гонка + мусор на диске).
   - Callback `sel_`: split по `_` с maxsplit=2 — каналы с `_` в username больше не ломаются.
   - Кеш статистики подписчиков (10 мин) вместо вызова Telegram API на каждый заход в панель.
   - **Фича 2 — черновики в БД**: таблица `drafts`, переживают рестарт бота; кнопка «Восстановить черновик» при нажатии «Создать».
   - **Фича 3 — аналитика публикаций**: `database.get_post_stats()`, роут `/api/analytics`, карточки TOTAL/TODAY/WEEK/MONTH + график PUBLISHED_PER_DAY (bar chart).
   - **Фича 5 — мониторинг оттока**: `publisher.check_subscriber_drop()` каждые 6ч сравнивает подписчиков и шлёт админу алерт при оттоке.
   - Мёртвый код удалён: `main_new.py`, `reorder_logic.py`, `playwright` и `google-genai` из requirements, `import utils` в handlers.

## ВЫПОЛНЕНО: настройка приложения в панели justrunmy.app (id 53038, имя MineBot_cli)

Приложение полностью настроено через MCP (инструменты `jrnm_*`):

- **Env-переменные заданы**: TELEGRAM_TOKEN, GROQ_API_KEY, GEMINI_KEY, CHANNELS=@lazikosmods, PORT=8080. (CURSEFORGE_API_KEY НЕ задан — пользователь решил пропустить, функция не работает; в логах соответствующий warning.)
- **Порт**: HTTPS mapping containerPort **8080** → внешний 80, домен `gitr_e2r5d-883` → `https://gitr_e2r5d-883.xs001.jrnm.app` открывает дашборд.
- **Volume**: `/app/data` (id 49215). Старый `/data` удалён. БД и водяные знаки лежат на volume — **проверено**: после рестарта маркер-файл и `bot_data.db` сохранились.
- **Run command**: задана явно `python launcher.py` (через `jrnm_set_app_command`).
- Статус: RUNNING, restarts 0. В логах только warning про CurseForge, бот + Flask (порт 8080) поднялись.
- Значения для env взяты из локального `.env` (в нём теперь есть TELEGRAM_TOKEN, GROQ_API_KEY, GEMINI_KEY, CHANNELS=@lazikosmods).

### Деплой через git (не тестировался с новой конфигурацией)
- Git remote: `https://Bc2g6:d7A9Xxs6H@justrunmy.app/git/r_e2R5D` (branch `deploy`), командой `git push -u <remote> HEAD:deploy`.
- Пуш автоматически пересобирает Docker-образ и рестартит приложение. Volume `/app/data` переживёт редеплой.

## Правило работы

Пользователь просил: **сохранять текущую переписку/контекст для будущего меня и делать так всегда**.
=> Держать AGENTS.md актуальным после каждого значимого шага (фиксы, деплой, настройки, решения).
