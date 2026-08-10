# AGENTS.md — проект MINE_BOT_OS (Telegram-бот + Flask-панель)

Этот файл — постоянная память проекта. Обновляй его при каждом значимом изменении
(новые фиксы, настройки, договорённости с пользователем), чтобы следующий сеанс
opencode сразу знал контекст.

## Кратко о проекте

- Telegram-бот (pyTelegramBotAPI) для автоматизации канала @lazikomods про Minecraft-моды
  + Flask веб-панель управления (dashboard).
- ИИ: Groq (llama-3.3-70b-versatile), промпт хранится в БД и редактируется из веб-панели.
- БД: SQLite. Медиа: водяные знаки через Pillow. Планировщик: APScheduler.
- Точка входа: `main.py` (запуск через `launcher.py`). Веб-сервер: `webapp.py` (порт из `PORT`, дефолт 8080).

## Запуск

- Локально: `pip install -r requirements.txt`, создать `.env` (см. `.env.example`/INSTALL.md), `python main.py`.
- На сервере (justrunmy.app): Docker-образ собирается из `Dockerfile` (python:3.11-slim), CMD = `python launcher.py`.

## Обязательные env-переменные (файл `.env`, НЕ коммитится)

- `TELEGRAM_TOKEN` (обязательная), `GROQ_API_KEY`, `GEMINI_KEY`, `CURSEFORGE_API_KEY`, `CHANNELS` (дефолт `@lazikomods`), `PORT` (дефолт 8080).
- `ADMIN_IDS` задаётся в `config.py`, а не в env.
- `DB_PATH` — путь к SQLite (дефолт `data/bot_data.db` относительно рабочей папки).

## Деплой: justrunmy.app

- Git remote: `https://Bc2g6:d7A9Xxs6H@justrunmy.app/git/r_e2R5D` (branch `deploy`), командой `git push -u <remote> HEAD:deploy`.
- Приложение: **Git r_e2R5D**, HTTPS URL: `https://gitr_e2r5d-883.xs001.jrnm.app` (порт 80).
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

## ВАЖНО: незавершённая задача — настройка приложения в панели justrunmy.app

Пользователь показал панель Settings приложения Git r_e2R5D. Нужно настроить:

- **Env-переменные**: TELEGRAM_TOKEN, GROQ_API_KEY, GEMINI_KEY, CURSEFORGE_API_KEY (значения взять из локального `.env` — на момент разговора файла `.env` в репозитории НЕ было), CHANNELS, PORT=8080.
- **Порт**: сейчас в панели указан порт 80, но Flask слушает 8080 (дефолт `PORT`). Нужно поменять mapping на 8080 (или задать PORT=80) — иначе HTTPS-ссылка не откроет дашборд.
- **Volume**: в панели смонтирован `/data`, но БД и водяные знаки лежат в `/app/data`. Нужен volume на `/app/data` (путь в контейнере), чтобы данные переживали рестарты/редеплои.
- **Run command**: не задавать (используется CMD из Dockerfile: `python launcher.py`).

Способ: либо руками в панели, либо инструментами `jrnm_*` (после перезапуска opencode):
`jrnm_set_env_vars`, `jrnm_set_app_ports`, `jrnm_add_app_volume`, `jrnm_start_or_restart_app`.

## Правило работы

Пользователь просил: **сохранять текущую переписку/контекст для будущего меня и делать так всегда**.
=> Держать AGENTS.md актуальным после каждого значимого шага (фиксы, деплой, настройки, решения).
