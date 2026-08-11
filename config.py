import os
from dotenv import load_dotenv

load_dotenv()

ADMIN_IDS = [8641832514]  # Твой ID администратора — доступ к панели только у этого аккаунта
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


if not TELEGRAM_TOKEN:
    raise ValueError("❌ КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_TOKEN не установлен!")
if not GROQ_API_KEY:
    print("⚠️ WARNING: GROQ_API_KEY is not set. AI functions might fail.")
if not GEMINI_KEY:
    print("⚠️ WARNING: GEMINI_KEY is not set.")

CHANNELS_STR = os.getenv("CHANNELS", "@lazikomods")
AVAILABLE_CHANNELS = [ch.strip() for ch in CHANNELS_STR.split(',')]
DEFAULT_CHANNEL = AVAILABLE_CHANNELS[0] if AVAILABLE_CHANNELS else ""

WATERMARK_TEXT = os.getenv("WATERMARK_TEXT", "@lazikomods")

PANEL_USER = os.getenv("PANEL_USER", "admin")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
# Обязательная авторизация панели. По умолчанию ВКЛ — панель больше не открыта миру.
PANEL_AUTH_REQUIRED = os.getenv("PANEL_AUTH_REQUIRED", "1").lower() in ("1", "true", "yes", "on")

# 🤖 USERBOT (Pyrogram) — перехват постов из каналов-источников (RU/EN)
# и создание узбекских постов через Groq-перевод.
# Для работы нужны API_ID/API_HASH (my.telegram.org) и сессия:
#   - USERBOT_SESSION_STRING — строковая сессия Pyrogram (рекомендуется для Docker),
#   - либо USERBOT_SESSION_FILE — путь к .session файлу (по умолчанию data/userbot.session).
# Получить api_id/api_hash: https://my.telegram.org -> API development tools.
USERBOT_ENABLED = os.getenv("USERBOT_ENABLED", "0").lower() in ("1", "true", "yes", "on")
USERBOT_API_ID = os.getenv("USERBOT_API_ID", "")
USERBOT_API_HASH = os.getenv("USERBOT_API_HASH", "")
USERBOT_SESSION_STRING = os.getenv("USERBOT_SESSION_STRING", "")
USERBOT_SESSION_FILE = os.getenv("USERBOT_SESSION_FILE", os.path.join('data', 'userbot.session'))
# Локальная папка для скачанного медиа (должна лежать на volume в Docker)
USERBOT_MEDIA_DIR = os.getenv("USERBOT_MEDIA_DIR", os.path.join('data', 'userbot_media'))
# Канал-хранилище: юзербот НЕ скачивает медиа, а копирует посты в приватный канал
# (серверно, без нагрузки). id созданного канала сохраняется в global_settings
# ('userbot_storage_chat_id'). Опционально можно задать готовый канал вручную:
#   USERBOT_STORAGE_CHANNEL = "@username" или "-100xxxxxxxx"
# USERBOT_STORAGE_TITLE — название, если канал будет создаваться автоматически.
USERBOT_STORAGE_CHANNEL = os.getenv("USERBOT_STORAGE_CHANNEL", "")
USERBOT_STORAGE_TITLE = os.getenv("USERBOT_STORAGE_TITLE", "Laziko Content Storage")
# Username бота, которого юзербот добавит админом в созданный канал-хранилище.
USERBOT_BOT_USERNAME = os.getenv("USERBOT_BOT_USERNAME", "")

# 🧠 НОВАЯ НАСТРОЙКА: Интервал умной очереди (в часах)
SMART_QUEUE_INTERVAL_HOURS = 6