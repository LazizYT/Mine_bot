"""Аутентификация панели: Telegram WebApp initData + сессионные токены.

Доступ к панели разрешён ТОЛЬКО аккаунту(-ам) из config.ADMIN_IDS.
Два способа входа:
  1. Открытие панели через Telegram WebApp (кнопка /studio в боте) — initData
     подписан секретом WebAppData = HMAC-SHA256("WebAppData", bot_token).
  2. Basic-авторизация (PANEL_USER/PANEL_PASSWORD) как запасной вход из браузера.

После успешного входа выдаётся подписанная сессионная cookie (panel_session).
"""
import hmac
import hashlib
import json
import time
import urllib.parse

_SESSION_TTL = 7 * 86400  # 7 дней


def _secret_key(bot_token):
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def validate_tg_init_data(init_data, bot_token):
    """Проверяет подпись initData Telegram WebApp. Возвращает dict пользователя или None."""
    try:
        params = {}
        for part in init_data.split("&"):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            params[k] = v
        received_hash = params.pop("hash", None)
        if not received_hash:
            return None
        # Значения приходят URL-encoded, подпись считается по декодированным
        decoded = {k: urllib.parse.unquote_plus(v) for k, v in params.items()}
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(decoded.items()))
        calc = hmac.new(_secret_key(bot_token), data_check_string.encode("utf-8"),
                        hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        auth_date = int(decoded.get("auth_date", 0))
        if time.time() - auth_date > 86400:  # не старше суток
            return None
        user = json.loads(decoded.get("user", "{}"))
        return user if isinstance(user, dict) else None
    except Exception:
        return None


def make_session_token(user_id, bot_token):
    """Подписанный токен сессии: <user_id>.<expiry>.<sig>."""
    payload = f"{int(user_id)}.{int(time.time()) + _SESSION_TTL}"
    sig = hmac.new(bot_token.encode("utf-8"), payload.encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token, bot_token):
    """Возвращает user_id если токен валиден и не истёк, иначе None."""
    if not token:
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        expected = hmac.new(bot_token.encode("utf-8"), payload.encode("utf-8"),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        user_id_s, exp_s = payload.split(".")
        if int(exp_s) < time.time():
            return None
        return int(user_id_s)
    except Exception:
        return None
