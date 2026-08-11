import sqlite3
import time
import os
from datetime import datetime, timedelta

# Путь к файлу базы данных SQLite.
# По умолчанию 'data/bot_data.db' (относительно рабочей папки).
# На Railway/Docker можно переопределить через env DB_PATH (например /app/data/bot_data.db),
# чтобы данные сохранялись на Volume при перезагрузках.
DB_PATH = os.getenv('DB_PATH', os.path.join('data', 'bot_data.db'))

def _connect():
    """Утилита: открыть соединение с БД (используется сервисными модулями).

    WAL-режим + busy_timeout — защита от "database is locked" при конкурентной
    записи из нескольких потоков (Flask + APScheduler + бот).
    """
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn

def init_db():
    """Инициализация структуры базы данных при запуске приложения."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
        
    conn = _connect()
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

    # Черновики постов на пользователя (переживают рестарт бота)
    c.execute('''CREATE TABLE IF NOT EXISTS drafts
                 (user_id INTEGER PRIMARY KEY, photo TEXT, text TEXT, document TEXT, channel TEXT, updated INTEGER)''')

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

    # Память ИИ: ручные заметки админа, всегда подаются в контекст генерации
    c.execute('''CREATE TABLE IF NOT EXISTS ai_memory
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, note TEXT, created_at INTEGER)''')

    # ================= CONTENT STORAGE =================
    # Единое хранилище всех постов, проходящих через Smart Queue
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source TEXT DEFAULT 'telegram',
                  source_url TEXT,
                  original_message_id TEXT,
                  original_channel_id TEXT,
                  title TEXT,
                  text TEXT,
                  media TEXT,
                  media_type TEXT DEFAULT 'text',
                  caption TEXT,
                  hashtags TEXT,
                  category TEXT,
                  language TEXT DEFAULT 'uz',
                  created_at INTEGER,
                  updated_at INTEGER,
                  status TEXT DEFAULT 'available',
                  priority INTEGER DEFAULT 5,
                  is_used INTEGER DEFAULT 0,
                  usage_count INTEGER DEFAULT 0,
                  last_used_at INTEGER,
                  times_published INTEGER DEFAULT 0,
                  published_channels TEXT,
                  tags TEXT,
                  content_hash TEXT)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_lang ON posts(language)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_hash ON posts(content_hash)")

    # Теги (справочник) и связь пост<->тег
    c.execute('''CREATE TABLE IF NOT EXISTS content_tags
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS post_tags
                 (post_id INTEGER, tag_id INTEGER, PRIMARY KEY (post_id, tag_id))''')

    # ================= CHANNELS =================
    # Расширенная конфигурация каналов (1:1 с managed_channels)
    c.execute('''CREATE TABLE IF NOT EXISTS channel_settings
                 (channel_id INTEGER PRIMARY KEY,
                  name TEXT,
                  username TEXT,
                  network_id INTEGER,
                  active INTEGER DEFAULT 1,
                  description TEXT DEFAULT '',
                  auto_publish INTEGER DEFAULT 1,
                  interval_hours REAL DEFAULT 6,
                  cron TEXT DEFAULT '',
                  timezone TEXT DEFAULT 'Asia/Tashkent',
                  start_time TEXT DEFAULT '',
                  end_time TEXT DEFAULT '',
                  max_posts_per_day INTEGER DEFAULT 0,
                  selection TEXT DEFAULT 'random',
                  categories TEXT DEFAULT '',
                  tags TEXT DEFAULT '',
                  languages TEXT DEFAULT 'uz',
                  sources TEXT DEFAULT '',
                  reuse_mode TEXT DEFAULT 'never',
                  reuse_days INTEGER DEFAULT 7,
                  post_template TEXT DEFAULT '',
                  prefix TEXT DEFAULT '',
                  suffix TEXT DEFAULT '',
                  hashtags TEXT DEFAULT '',
                  link_preview INTEGER DEFAULT 1,
                  media_settings TEXT DEFAULT '',
                  duplicate_protection INTEGER DEFAULT 1,
                  flood_protection INTEGER DEFAULT 1,
                  failed_retry_count INTEGER DEFAULT 3,
                  cooldown INTEGER DEFAULT 0,
                  rate_limit INTEGER DEFAULT 0,
                  min_delay INTEGER DEFAULT 0,
                  created_at INTEGER,
                  updated_at INTEGER)''')

    # Сети каналов
    c.execute('''CREATE TABLE IF NOT EXISTS networks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  description TEXT DEFAULT '',
                  created_at INTEGER,
                  updated_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS network_channels
                 (network_id INTEGER, channel_id INTEGER, PRIMARY KEY (network_id, channel_id))''')

    # Шаблоны настроек каналов
    c.execute('''CREATE TABLE IF NOT EXISTS templates
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  description TEXT DEFAULT '',
                  data TEXT DEFAULT '{}',
                  created_at INTEGER,
                  updated_at INTEGER)''')

    # ================= USERBOT (источники контента) =================
    # Каналы-источники (RU/EN), которые юзербот слушает для перехвата постов.
    c.execute('''CREATE TABLE IF NOT EXISTS userbot_sources
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  enabled INTEGER DEFAULT 1,
                  last_message_id INTEGER DEFAULT 0,
                  created_at INTEGER,
                  updated_at INTEGER)''')

    # История перехваченных постов (антиповтор: не качаем один пост дважды).
    # unique по (source_username, message_id) — защита от повторной обработки.
    # media_group_id позволяет группировать альбомы (все фото одного поста).
    c.execute('''CREATE TABLE IF NOT EXISTS userbot_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_username TEXT,
                  message_id INTEGER,
                  media_group_id TEXT DEFAULT '',
                  post_id INTEGER,
                  status TEXT DEFAULT 'captured',
                  created_at INTEGER,
                  UNIQUE(source_username, message_id))''')

    # ================= SCHEDULES & PUBLICATIONS =================
    c.execute('''CREATE TABLE IF NOT EXISTS schedules
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  channel_id INTEGER,
                  post_id INTEGER,
                  scheduled_at INTEGER,
                  status TEXT DEFAULT 'pending',
                  created_at INTEGER)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(status, scheduled_at)")

    c.execute('''CREATE TABLE IF NOT EXISTS publications
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  post_id INTEGER,
                  channel_id INTEGER,
                  network_id INTEGER,
                  scheduled_at INTEGER,
                  published_at INTEGER,
                  status TEXT DEFAULT 'SUCCESS',
                  error TEXT DEFAULT '',
                  retry_count INTEGER DEFAULT 0,
                  message_id TEXT DEFAULT '',
                  created_at INTEGER)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_pub_channel ON publications(channel_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pub_status ON publications(status)")

    c.execute('''CREATE TABLE IF NOT EXISTS publication_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  publication_id INTEGER,
                  channel_id INTEGER,
                  post_id INTEGER,
                  event TEXT,
                  details TEXT DEFAULT '',
                  created_at INTEGER)''')

    # ================= EVENTS / AUDIT =================
    c.execute('''CREATE TABLE IF NOT EXISTS system_events
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_type TEXT,
                  message TEXT,
                  data TEXT DEFAULT '',
                  created_at INTEGER)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON system_events(event_type)")

    c.execute('''CREATE TABLE IF NOT EXISTS audit_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user TEXT DEFAULT 'admin',
                  action TEXT,
                  target TEXT DEFAULT '',
                  old_value TEXT DEFAULT '',
                  new_value TEXT DEFAULT '',
                  created_at INTEGER)''')

    # Миграции для существующей таблицы queue -> связь с posts
    try: c.execute("ALTER TABLE queue ADD COLUMN post_id INTEGER")
    except: pass
    try: c.execute("ALTER TABLE queue ADD COLUMN priority INTEGER DEFAULT 5")
    except: pass
    try: c.execute("ALTER TABLE queue ADD COLUMN category TEXT")
    except: pass
    try: c.execute("ALTER TABLE queue ADD COLUMN tags TEXT")
    except: pass
    try: c.execute("ALTER TABLE queue ADD COLUMN created_at INTEGER")
    except: pass

    conn.commit()
    conn.close()
    
    # Инициализация дефолтных значений
    init_defaults()

def init_defaults():
    from ai_generator import PROMPT_TEMPLATE
    conn = _connect()
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
    conn = _connect()
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
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, path, name, is_active FROM watermarks")
    rows = c.fetchall()
    conn.close()
    return rows

def set_active_watermark(wm_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE watermarks SET is_active = 0")
    c.execute("UPDATE watermarks SET is_active = 1 WHERE id = ?", (wm_id,))
    conn.commit()
    conn.close()

def get_active_watermark():
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT path FROM watermarks WHERE is_active = 1")
    res = c.fetchone()
    conn.close()
    return res[0] if res else 'templates/logo.png'

def delete_watermark(wm_id):
    conn = _connect()
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
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, name, prompt, is_active FROM ai_prompts")
    rows = c.fetchall()
    conn.close()
    return rows

def add_prompt(name, prompt):
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT INTO ai_prompts (name, prompt, is_active) VALUES (?, ?, 0)", (name, prompt))
    conn.commit()
    conn.close()

def delete_prompt(prompt_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM ai_prompts WHERE id = ? AND is_active = 0", (prompt_id,))
    conn.commit()
    conn.close()

def get_active_prompt():
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT prompt, id FROM ai_prompts WHERE is_active = 1")
    res = c.fetchone()
    conn.close()
    return res if res else (None, None)

def activate_prompt(prompt_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE ai_prompts SET is_active = 0")
    c.execute("UPDATE ai_prompts SET is_active = 1 WHERE id = ?", (prompt_id,))
    conn.commit()
    conn.close()

def update_prompt(prompt_id, name, prompt):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE ai_prompts SET name = ?, prompt = ? WHERE id = ?", (name, prompt, prompt_id))
    conn.commit()
    conn.close()

def update_active_prompt(new_prompt):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE ai_prompts SET prompt = ? WHERE is_active = 1", (new_prompt,))
    conn.commit()
    conn.close()

# --- Глобальные настройки ---
def set_global_setting(key, value):
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_global_setting(key, default=""):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT value FROM global_settings WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

# --- Управление каналами ---
def add_channel(username):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO managed_channels (username) VALUES (?)", (username,))
        conn.commit()
    finally: conn.close()

def remove_channel(username):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM managed_channels WHERE username = ?", (username,))
    conn.commit()
    conn.close()

def get_all_managed_channels():
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT username FROM managed_channels")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# --- Статистика ---
def save_sub_count(channel_id, count):
    date = datetime.now().strftime('%Y-%m-%d')
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO stats_subscribers (channel_id, count, date) VALUES (?, ?, ?)", (channel_id, count, date))
    conn.commit()
    conn.close()

def get_sub_history(channel_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT date, count FROM stats_subscribers WHERE channel_id = ? ORDER BY date ASC LIMIT 30", (channel_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_post_views(post_id, views):
    date = datetime.now().strftime('%Y-%m-%d')
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO stats_posts (post_id, views, date) VALUES (?, ?, ?)", (post_id, views, date))
    conn.commit()
    conn.close()

# --- Настройки пользователя ---
def update_user_setting(user_id, key, value):
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)", (user_id, key, str(value)))
    conn.commit()
    conn.close()

def get_user_setting(user_id, key, default=None):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

# --- Очередь ---
def add_to_queue(photo_id, text, document_id=None, channel_id=None, scheduled_time=None):
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT INTO queue (photo_id, text, document_id, channel_id, scheduled_time) VALUES (?, ?, ?, ?, ?)", 
              (photo_id, text, document_id, channel_id, scheduled_time))
    conn.commit()
    conn.close()

def get_ready_posts():
    conn = _connect()
    c = conn.cursor()
    current_time = int(time.time())
    c.execute('''SELECT id, photo_id, text, document_id, channel_id FROM queue 
                 WHERE status='pending' AND (scheduled_time IS NULL OR scheduled_time <= ?) 
                 ORDER BY scheduled_time ASC''', (current_time,))
    rows = c.fetchall()
    conn.close()
    return rows

def update_message_id(post_id, message_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE queue SET message_id = ? WHERE id = ?", (message_id, post_id))
    conn.commit()
    conn.close()

def mark_as_posted(post_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE queue SET status='posted' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

def get_published_history(limit=50):
    conn = _connect()
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
    conn = _connect()
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
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, photo_id, text, document_id, channel_id, scheduled_time FROM queue WHERE status='pending' ORDER BY scheduled_time ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_posts():
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT * FROM queue")
    rows = c.fetchall()
    conn.close()
    return rows

def get_post_by_id(post_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, photo_id, text, document_id, channel_id, scheduled_time, status FROM queue WHERE id = ?", (post_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_post_content(post_id, text, scheduled_time):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE queue SET text = ?, scheduled_time = ? WHERE id = ?", (text, scheduled_time, post_id))
    conn.commit()
    conn.close()

def delete_from_queue(post_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM queue WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

def get_pending_posts():
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, scheduled_time FROM queue WHERE status='pending' ORDER BY scheduled_time ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_last_scheduled_time():
    """Возвращает максимальное scheduled_time среди ожидающих постов (или None, если очередь пуста)."""
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT MAX(scheduled_time) FROM queue WHERE status='pending'")
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def update_post_times(updates):
    conn = _connect()
    c = conn.cursor()
    for post_id, scheduled_time in updates.items():
        c.execute("UPDATE queue SET scheduled_time = ? WHERE id = ?", (scheduled_time, post_id))
    conn.commit()
    conn.close()


def record_published_post(photo_id, text, document_id, channel_id):
    conn = _connect()
    c = conn.cursor()
    current_time = int(time.time())
    c.execute("INSERT INTO queue (photo_id, text, document_id, channel_id, scheduled_time, status) VALUES (?, ?, ?, ?, ?, 'posted')", 
              (photo_id, text, document_id, channel_id, current_time))
    conn.commit()
    conn.close()

def save_comment(user_name, text, timestamp):
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT INTO comments (user_name, text, timestamp) VALUES (?, ?, ?)", (user_name, text, timestamp))
    conn.commit()
    conn.close()

def get_all_comments(limit=200):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT user_name, text FROM comments ORDER BY timestamp ASC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def clear_comments():
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM comments")
    conn.commit()
    conn.close()

# --- Черновики (переживают рестарт бота) ---
def save_draft(user_id, photo, text, document, channel):
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO drafts (user_id, photo, text, document, channel, updated) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, photo, text, document, channel, int(time.time())))
    conn.commit()
    conn.close()

def get_user_draft(user_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT photo, text, document, channel FROM drafts WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {'photo': row[0], 'text': row[1], 'document': row[2], 'channel': row[3]} if row else None

def delete_draft(user_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM drafts WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- Статистика публикаций (для аналитики дашборда) ---
def get_post_stats():
    """Возвращает количество опубликованных постов: всего, сегодня, за неделю и за месяц."""
    import pytz
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM queue WHERE status='posted'")
    total = c.fetchone()[0]

    tashkent_tz = pytz.timezone('Asia/Tashkent')
    now = datetime.now(tashkent_tz)
    today_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    week_start = int((now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    month_start = int((now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

    def count_since(ts):
        c.execute("SELECT COUNT(*) FROM queue WHERE status='posted' AND scheduled_time >= ?", (ts,))
        return c.fetchone()[0]

    today = count_since(today_start)
    week = count_since(week_start)
    month = count_since(month_start)

    # Ежедневная динамика за последние 30 дней
    labels, data = [], []
    for i in range(29, -1, -1):
        day = now - timedelta(days=i)
        day_start = int(day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        day_end = day_start + 86400
        c.execute("SELECT COUNT(*) FROM queue WHERE status='posted' AND scheduled_time >= ? AND scheduled_time < ?", (day_start, day_end))
        labels.append(day.strftime('%d.%m'))
        data.append(c.fetchone()[0])
    conn.close()
    return {'total': total, 'today': today, 'week': week, 'month': month,
            'labels': labels, 'data': data}

# --- Память ИИ (ручные заметки админа) ---
def add_memory_note(note):
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT INTO ai_memory (note, created_at) VALUES (?, ?)", (note, int(time.time())))
    conn.commit()
    conn.close()

def get_memory_notes():
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, note, created_at FROM ai_memory ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_memory_note(note_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM ai_memory WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()

def clear_memory_notes():
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM ai_memory")
    conn.commit()
    conn.close()

# --- Аудит (audit_log) ---
def audit_log(action, target='', old_value='', new_value='', user='admin'):
    """Записывает действие в audit_log."""
    conn = _connect()
    c = conn.cursor()
    c.execute("INSERT INTO audit_log (user, action, target, old_value, new_value, created_at) VALUES (?, ?, ?, ?, ?, ?)",
              (user, action, target, old_value, new_value, int(time.time())))
    conn.commit()
    conn.close()

def get_audit_log(limit=200, action=None):
    """История аудита. Фильтр по action (опционально)."""
    conn = _connect()
    c = conn.cursor()
    if action:
        c.execute("SELECT id, user, action, target, old_value, new_value, created_at FROM audit_log WHERE action = ? ORDER BY id DESC LIMIT ?", (action, limit))
    else:
        c.execute("SELECT id, user, action, target, old_value, new_value, created_at FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'user': r[1], 'action': r[2], 'target': r[3],
             'old_value': r[4], 'new_value': r[5], 'created_at': r[6]} for r in rows]


# --- USERBOT источники (userbot_sources) ---
def userbot_add_source(username, enabled=1):
    """Добавляет канал-источник для юзербота."""
    conn = _connect()
    c = conn.cursor()
    now = int(time.time())
    c.execute("""INSERT OR IGNORE INTO userbot_sources (username, enabled, last_message_id, created_at, updated_at)
                 VALUES (?, ?, 0, ?, ?)""", (username, 1 if enabled else 0, now, now))
    conn.commit()
    conn.close()

def userbot_remove_source(username):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM userbot_sources WHERE username = ?", (username,))
    conn.commit()
    conn.close()

def userbot_get_sources():
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, username, enabled, last_message_id, created_at FROM userbot_sources ORDER BY id ASC")
    rows = [{'id': r[0], 'username': r[1], 'enabled': r[2], 'last_message_id': r[3], 'created_at': r[4]} for r in c.fetchall()]
    conn.close()
    return rows

def userbot_set_enabled(username, enabled):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE userbot_sources SET enabled = ?, updated_at = ? WHERE username = ?",
              (1 if enabled else 0, int(time.time()), username))
    conn.commit()
    conn.close()

def userbot_set_last_message(username, message_id):
    conn = _connect()
    c = conn.cursor()
    c.execute("UPDATE userbot_sources SET last_message_id = ?, updated_at = ? WHERE username = ?",
              (message_id, int(time.time()), username))
    conn.commit()
    conn.close()

def userbot_get_last_message(username):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT last_message_id FROM userbot_sources WHERE username = ?", (username,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else 0


# --- USERBOT история перехваченных постов (userbot_history) ---
def userbot_history_add(source_username, message_id, media_group_id="", post_id=None, status='captured'):
    """Фиксирует факт перехвата сообщения (антиповтор). Возвращает True если добавлено, False если уже было."""
    conn = _connect()
    c = conn.cursor()
    now = int(time.time())
    c.execute("INSERT OR IGNORE INTO userbot_history (source_username, message_id, media_group_id, post_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
              (source_username, int(message_id), media_group_id or "", post_id, status, now))
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def userbot_history_exists(source_username, message_id):
    """True если сообщение уже перехвачено (любой статус)."""
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT 1 FROM userbot_history WHERE source_username = ? AND message_id = ?", (source_username, int(message_id)))
    r = c.fetchone()
    conn.close()
    return r is not None

def userbot_history_get(source_username, message_id):
    """Запись истории (dict) или None."""
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT id, source_username, message_id, media_group_id, post_id, status, created_at FROM userbot_history WHERE source_username = ? AND message_id = ?",
              (source_username, int(message_id)))
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return {'id': r[0], 'source_username': r[1], 'message_id': r[2], 'media_group_id': r[3],
            'post_id': r[4], 'status': r[5], 'created_at': r[6]}

def userbot_history_list(limit=100, source_username=None):
    """Последние перехваченные посты (для панели)."""
    conn = _connect()
    c = conn.cursor()
    if source_username:
        c.execute("SELECT id, source_username, message_id, media_group_id, post_id, status, created_at FROM userbot_history WHERE source_username = ? ORDER BY id DESC LIMIT ?",
                  (source_username, limit))
    else:
        c.execute("SELECT id, source_username, message_id, media_group_id, post_id, status, created_at FROM userbot_history ORDER BY id DESC LIMIT ?", (limit,))
    rows = [{'id': r[0], 'source_username': r[1], 'message_id': r[2], 'media_group_id': r[3],
             'post_id': r[4], 'status': r[5], 'created_at': r[6]} for r in c.fetchall()]
    conn.close()
    return rows


# --- Бэкапы БД ---
import shutil

BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), 'backups')
BACKUP_KEEP = 14  # храним 14 последних бэкапов


def backup_db(keep=BACKUP_KEEP):
    """Ежедневный бэкап БД (SQLite online backup API, безопасен при WAL).
    Возвращает путь к созданному бэкапу или None при ошибке."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = time.strftime('%Y%m%d_%H%M%S')
        dest = os.path.join(BACKUP_DIR, f'bot_data_{ts}.db')
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        _prune_backups(keep)
        return dest
    except Exception as e:
        print(f"❌ Ошибка бэкапа БД: {e}")
        return None


def _prune_backups(keep):
    try:
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith('bot_data_') and f.endswith('.db')])
        while len(backups) > keep:
            os.remove(os.path.join(BACKUP_DIR, backups.pop(0)))
    except Exception as e:
        print(f"❌ Ошибка чистки бэкапов: {e}")


init_db()
