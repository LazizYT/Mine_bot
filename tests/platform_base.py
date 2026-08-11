"""Общие тестовые данные для тестов платформы.
Тесты используют отдельную временную БД (env DB_PATH), чтобы не трогать продакшен-данные.
"""
import os
import sys
import tempfile

# Отдельная временная БД для всех тестов платформы
_tmp_db = tempfile.mkdtemp(prefix="tg_bot_tests_")
os.environ['DB_PATH'] = os.path.join(_tmp_db, 'test_bot_data.db')

# В тестах авторизация панели отключена
os.environ['PANEL_AUTH_REQUIRED'] = '0'

# Импортируем модули проекта после установки DB_PATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
database.init_db()
