"""Тесты аутентификации панели (panel_auth.py): Telegram initData + сессионные токены."""
import unittest
import hmac
import hashlib
import json
import time
import urllib.parse

sys_path_setup = __import__('sys')
sys_path_setup.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import platform_base  # noqa: F401

import panel_auth

BOT_TOKEN = "123456:TEST-TOKEN"


def _build_init_data(user_id=8641832514, auth_date=None, username="laziko"):
    """Собирает корректно подписанный initData для тестов."""
    auth_date = auth_date or int(time.time())
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": user_id, "first_name": "Laziko", "username": username}),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    parts = [f"{k}={urllib.parse.quote_plus(v)}" for k, v in params.items()]
    parts.append(f"hash={calc}")
    return "&".join(parts)


class TestPanelAuth(unittest.TestCase):

    def test_valid_init_data_admin(self):
        init = _build_init_data()
        user = panel_auth.validate_tg_init_data(init, BOT_TOKEN)
        self.assertIsNotNone(user)
        self.assertEqual(user['id'], 8641832514)

    def test_valid_init_data_wrong_token(self):
        init = _build_init_data()
        user = panel_auth.validate_tg_init_data(init, "WRONG:TOKEN")
        self.assertIsNone(user)

    def test_valid_init_data_wrong_user(self):
        init = _build_init_data(user_id=111111)
        user = panel_auth.validate_tg_init_data(init, BOT_TOKEN)
        self.assertIsNotNone(user)
        self.assertEqual(user['id'], 111111)

    def test_stale_init_data_rejected(self):
        init = _build_init_data(auth_date=int(time.time()) - 3 * 86400)
        user = panel_auth.validate_tg_init_data(init, BOT_TOKEN)
        self.assertIsNone(user)

    def test_session_token_roundtrip(self):
        token = panel_auth.make_session_token(8641832514, BOT_TOKEN)
        self.assertEqual(panel_auth.verify_session_token(token, BOT_TOKEN), 8641832514)

    def test_session_token_tampered(self):
        token = panel_auth.make_session_token(8641832514, BOT_TOKEN)
        tampered = token[:-2] + ("ff" if not token.endswith("ff") else "ee")
        self.assertIsNone(panel_auth.verify_session_token(tampered, BOT_TOKEN))

    def test_session_token_expired(self):
        token = panel_auth.make_session_token(8641832514, BOT_TOKEN)
        payload, sig = token.rsplit(".", 1)
        old_payload = payload.split(".")[0] + "." + str(int(time.time()) - 10)
        expired = f"{old_payload}.{sig}"
        self.assertIsNone(panel_auth.verify_session_token(expired, BOT_TOKEN))


if __name__ == '__main__':
    unittest.main()
