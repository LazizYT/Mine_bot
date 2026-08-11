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

CHANNELS_STR = os.getenv("CHANNELS", "@lazikosmods")
AVAILABLE_CHANNELS = [ch.strip() for ch in CHANNELS_STR.split(',')]
DEFAULT_CHANNEL = AVAILABLE_CHANNELS[0] if AVAILABLE_CHANNELS else ""

WATERMARK_TEXT = os.getenv("WATERMARK_TEXT", "@lazikosmods")

PANEL_USER = os.getenv("PANEL_USER", "admin")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
# Обязательная авторизация панели. По умолчанию ВКЛ — панель больше не открыта миру.
PANEL_AUTH_REQUIRED = os.getenv("PANEL_AUTH_REQUIRED", "1").lower() in ("1", "true", "yes", "on")

# 🧠 НОВАЯ НАСТРОЙКА: Интервал умной очереди (в часах)
SMART_QUEUE_INTERVAL_HOURS = 6