import sqlite3
import time
import os
from datetime import datetime

# Путь к файлу базы данных SQLite.
# По умолчанию 'data/bot_data.db' (относительно рабочей папки).
# На Railway/Docker можно переопределить через env DB_PATH (например /app/data/bot_data.db),
# чтобы данные сохранялись на Volume при перезагрузках.
DB_PATH = os.getenv('DB_PATH', os.path.join('data', 'bot_data.db'))

def init_db():
    """Инициализация структуры базы данных при запуске приложения."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Таблица очереди постов: хранит медиа, текст, статус и время публикации
    c.execute('''CREATE TABLE IF NOT EXISTS queue
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  photo_id TEXT,
                  text TEXT,
                  document_id TEXT,
                  status TEXT DEFAULT 'pending',
                  message_id INTEGER)''')
    
    # Динамическое добавление колонок (для миграции старых БД без удаления данных)
    try: c.execute("ALTER TABLE queue ADD COLUMN channel_id TEXT")
    except: pass
    try: c.execute("ALTER TABLE queue ADD COLUMN scheduled_time INTEGER")
    except: pass
    try: c.execute("ALTER TABLE queue ADD COLUMN message_id INTEGER")
    except: pass
        
    # Таблица индивидуальных настроек пользователей (язык, активный канал)
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings
                 (user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (user_id, key))''')

    # Таблица комментариев пользователей (для анализа через Groq)
    c.execute('''CREATE TABLE IF NOT EXISTS comments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_name TEXT, text TEXT, timestamp INTEGER)''')

    # Таблица списка каналов, которыми управляет бот
    c.execute('''CREATE TABLE IF NOT EXISTS managed_channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE)''')

    # Статистика подписчиков (срез по дням)
    c.execute('''CREATE TABLE IF NOT EXISTS stats_subscribers
                 (channel_id TEXT, count INTEGER, date TEXT, PRIMARY KEY (channel_id, date))''')

    # Статистика просмотров постов
    c.execute('''CREATE TABLE IF NOT EXISTS stats_posts
                 (post_id INTEGER PRIMARY KEY, views INTEGER, date TEXT)''')

    # Глобальные настройки (рекламный текст и прочее)
    c.execute('''CREATE TABLE IF NOT EXISTS global_settings
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # Таблица водяных знаков (до 5 штук)
    c.execute('''CREATE TABLE IF NOT EXISTS watermarks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, name TEXT, is_active INTEGER DEFAULT 0)''')

    # Таблица промптов для ИИ
    c.execute('''CREATE TABLE IF NOT EXISTS ai_prompts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, prompt TEXT, is_active INTEGER DEFAULT 0)''')

    conn.commit()
    conn.close()
    
    # Инициализация дефолтных значений
    init_defaults()

def init_defaults():
    from ai_generator import PROMPT_TEMPLATE
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Промпт
    c.execute("SELECT COUNT(*) FROM ai_prompts")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO ai_prompts (name, prompt, is_active) VALUES (?, ?, ?)", 
                  ("Minecraft Default", PROMPT_TEMPLATE, 1))
    
    # Дефолтный водяной знак
    c.execute("SELECT COUNT(*) FROM watermarks")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO watermarks (path, name, is_active) VALUES (?, ?, ?)", 
                  ("templates/logo.png", "Original Logo", 1))
    
    conn.commit()
    conn.close()

# --- Управление водяными знаками ---
def add_watermark_db(path, name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM watermarks")
    if c.fetchone()[0] >= 5:
        conn.close()
        return False
    c.execute("INSERT INTO watermarks (path, name) VALUES (?, ?)", (path, name))
    conn.commit()
    conn.close()
    return True

def get_all_watermarks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, path, name, is_active FROM watermarks")
    rows = c.fetchall()
    conn.close()
    return rows

def set_active_watermark(wm_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE watermarks SET is_active = 0")
    c.execute("UPDATE watermarks SET is_active = 1 WHERE id = ?", (wm_id,))
    conn.commit()
    conn.close()

def get_active_watermark():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT path FROM watermarks WHERE is_active = 1")
    res = c.fetchone()
    conn.close()
    return res[0] if res else 'templates/logo.png'

def delete_watermark(wm_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT path FROM watermarks WHERE id = ?", (wm_id,))
    path = c.fetchone()
    if path and os.path.exists(path[0]) and 'logo.png' not in path[0]:
        try: os.remove(path[0])
        except: pass
    c.execute("DELETE FROM watermarks WHERE id = ?", (wm_id,))
    conn.commit()
    conn.close()

# --- Управление промптами ---
def get_all_prompts():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, prompt, is_active FROM ai_prompts")
    rows = c.fetchall()
    conn.close()
    return rows

def add_prompt(name, prompt):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO ai_prompts (name, prompt, is_active) VALUES (?, ?, 0)", (name, prompt))
    conn.commit()
    conn.close()

def delete_prompt(prompt_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM ai_prompts WHERE id = ? AND is_active = 0", (prompt_id,))
    conn.commit()
    conn.close()

def get_active_prompt():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT prompt, id FROM ai_prompts WHERE is_active = 1")
    res = c.fetchone()
    conn.close()
    return res if res else (None, None)

def activate_prompt(prompt_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE ai_prompts SET is_active = 0")
    c.execute("UPDATE ai_prompts SET is_active = 1 WHERE id = ?", (prompt_id,))
    conn.commit()
    conn.close()

def update_prompt(prompt_id, name, prompt):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE ai_prompts SET name = ?, prompt = ? WHERE id = ?", (name, prompt, prompt_id))
    conn.commit()
    conn.close()

def update_active_prompt(new_prompt):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE ai_prompts SET prompt = ? WHERE is_active = 1", (new_prompt,))
    conn.commit()
    conn.close()

# --- Глобальные настройки ---
def set_global_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_global_setting(key, default=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM global_settings WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

# --- Управление каналами ---
def add_channel(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO managed_channels (username) VALUES (?)", (username,))
        conn.commit()
    finally: conn.close()

def remove_channel(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM managed_channels WHERE username = ?", (username,))
    conn.commit()
    conn.close()

def get_all_managed_channels():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username FROM managed_channels")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# --- Статистика ---
def save_sub_count(channel_id, count):
    date = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO stats_subscribers (channel_id, count, date) VALUES (?, ?, ?)", (channel_id, count, date))
    conn.commit()
    conn.close()

def get_sub_history(channel_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT date, count FROM stats_subscribers WHERE channel_id = ? ORDER BY date ASC LIMIT 30", (channel_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_post_views(post_id, views):
    date = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO stats_posts (post_id, views, date) VALUES (?, ?, ?)", (post_id, views, date))
    conn.commit()
    conn.close()

# --- Настройки пользователя ---
def update_user_setting(user_id, key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)", (user_id, key, str(value)))
    conn.commit()
    conn.close()

def get_user_setting(user_id, key, default=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

# --- Очередь ---
def add_to_queue(photo_id, text, document_id=None, channel_id=None, scheduled_time=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO queue (photo_id, text, document_id, channel_id, scheduled_time) VALUES (?, ?, ?, ?, ?)", 
              (photo_id, text, document_id, channel_id, scheduled_time))
    conn.commit()
    conn.close()

def get_ready_posts():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    current_time = int(time.time())
    c.execute('''SELECT id, photo_id, text, document_id, channel_id FROM queue 
                 WHERE status='pending' AND (scheduled_time IS NULL OR scheduled_time <= ?) 
                 ORDER BY scheduled_time ASC''', (current_time,))
    rows = c.fetchall()
    conn.close()
    return rows

def update_message_id(post_id, message_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE queue SET message_id = ? WHERE id = ?", (message_id, post_id))
    conn.commit()
    conn.close()

def mark_as_posted(post_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE queue SET status='posted' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

def get_published_history(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, photo_id, text, channel_id, scheduled_time, message_id 
                 FROM queue 
                 WHERE status='posted' 
                 ORDER BY scheduled_time DESC LIMIT ?""", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_stats():
    import pytz
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM queue")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM queue WHERE status='posted'")
    published = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM queue WHERE status='pending'")
    queue_count = c.fetchone()[0]
    tashkent_tz = pytz.timezone('Asia/Tashkent')
    today_start = int(datetime.now(tashkent_tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    c.execute("SELECT COUNT(*) FROM queue WHERE scheduled_time >= ?", (today_start,))
    today = c.fetchone()[0]
    conn.close()
    return {'total': total, 'published': published, 'queue': queue_count, 'today': today}

def get_all_pending():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, photo_id, text, document_id, channel_id, scheduled_time FROM queue WHERE status='pending' ORDER BY scheduled_time ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_posts():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM queue")
    rows = c.fetchall()
    conn.close()
    return rows

def get_post_by_id(post_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, photo_id, text, document_id, channel_id, scheduled_time, status FROM queue WHERE id = ?", (post_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_post_content(post_id, text, scheduled_time):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE queue SET text = ?, scheduled_time = ? WHERE id = ?", (text, scheduled_time, post_id))
    conn.commit()
    conn.close()

def delete_from_queue(post_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM queue WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

def get_pending_posts():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, scheduled_time FROM queue WHERE status='pending' ORDER BY scheduled_time ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_last_scheduled_time():
    """Возвращает максимальное scheduled_time среди ожидающих постов (или None, если очередь пуста)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT MAX(scheduled_time) FROM queue WHERE status='pending'")
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def update_post_times(updates):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for post_id, scheduled_time in updates.items():
        c.execute("UPDATE queue SET scheduled_time = ? WHERE id = ?", (scheduled_time, post_id))
    conn.commit()
    conn.close()


def record_published_post(photo_id, text, document_id, channel_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    current_time = int(time.time())
    c.execute("INSERT INTO queue (photo_id, text, document_id, channel_id, scheduled_time, status) VALUES (?, ?, ?, ?, ?, 'posted')", 
              (photo_id, text, document_id, channel_id, current_time))
    conn.commit()
    conn.close()

def save_comment(user_name, text, timestamp):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO comments (user_name, text, timestamp) VALUES (?, ?, ?)", (user_name, text, timestamp))
    conn.commit()
    conn.close()

def get_all_comments():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_name, text FROM comments ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def clear_comments():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM comments")
    conn.commit()
    conn.close()

init_db()
