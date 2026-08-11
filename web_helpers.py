"""Общие хелперы веб-панели (без Flask-приложения)."""
import time
import os
from datetime import datetime, timedelta
import pytz

import database
import config
from bot_instance import bot

# Кеш статистики подписчиков (не дёргать Telegram API на каждый запрос страницы)
_stats_cache = {'ts': 0, 'data': None}
_STATS_CACHE_TTL = 600  # 10 минут

file_path_cache = {}


def collect_stats():
    global _stats_cache
    now = time.time()
    if _stats_cache['data'] is not None and now - _stats_cache['ts'] < _STATS_CACHE_TTL:
        return _stats_cache['data']
    channels = database.get_all_managed_channels()
    for ch in channels:
        try:
            count = bot.get_chat_member_count(ch)
            database.save_sub_count(ch, count)
        except Exception:
            pass
    _stats_cache = {'ts': now, 'data': True}
    return True


def get_telegram_file_url(file_id):
    if file_id in file_path_cache:
        return file_path_cache[file_id]
    try:
        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{file_info.file_path}"
        file_path_cache[file_id] = url
        return url
    except Exception:
        return None


def format_timestamp(ts):
    if not ts:
        return "⏰ ASAP"
    tz = pytz.timezone('Asia/Tashkent')
    return datetime.fromtimestamp(ts, tz).strftime('%d.%m %H:%M')


def get_channel_growth(channel_id):
    history = database.get_sub_history(channel_id)
    if not history or len(history) < 2:
        return {'24h': 0, '7d': 0, '30d': 0, 'current': 0}

    current = history[-1][1]

    def get_diff(days):
        target_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        prev = next((h[1] for h in reversed(history) if h[0] <= target_date), history[0][1])
        return current - prev

    return {
        '24h': get_diff(1),
        '7d': get_diff(7),
        '30d': get_diff(30),
        'current': current
    }


# ---------------------------------------------------------------------------
# Аутентификация
# ---------------------------------------------------------------------------
SESSION_COOKIE = 'panel_session'


def is_admin(user_id):
    return int(user_id) in [int(a) for a in getattr(config, 'ADMIN_IDS', [])]


def check_session(request):
    token = request.cookies.get(SESSION_COOKIE)
    uid = _verify_token(token)
    if uid is not None and is_admin(uid):
        return uid
    return None


def check_basic_auth(request):
    if not config.PANEL_PASSWORD:
        return None
    auth = request.authorization
    if auth and auth.username == config.PANEL_USER and auth.password == config.PANEL_PASSWORD:
        return config.PANEL_USER
    return None


def _verify_token(token):
    import panel_auth
    return panel_auth.verify_session_token(token, config.TELEGRAM_TOKEN)
