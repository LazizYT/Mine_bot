"""Content Storage — единое хранилище постов, проходящих через Smart Queue.

Каждый пост, добавленный в очередь, сохраняется здесь с полным метаданными.
Smart Queue отвечает за обработку, Content Storage — за долговременное хранение
и повторное использование контента в разных каналах.
"""
import re
import time
import hashlib
import random
from datetime import datetime

import database

POST_STATUSES = ['draft', 'queued', 'available', 'scheduled', 'publishing',
                 'published', 'archived', 'disabled', 'failed']

SELECTION_ALGOS = ['random', 'weighted', 'fifo', 'lifo', 'least_used',
                   'category_rotation', 'smart']

REUSE_MODES = ['never', 'after_days', 'unlimited']

POST_SOURCES = ['telegram', 'manual', 'ai', 'modrinth', 'curseforge', 'userbot']


# ---------------------------------------------------------------------------
# Хэш / дубликаты
# ---------------------------------------------------------------------------
def _normalize_text(text):
    """Нормализация текста для сравнения: нижний регистр, без html/пробелов."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'#\w+', ' ', text)          # убираем хэштеги
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def compute_content_hash(text, media=""):
    """Устойчивый хэш содержимого (нормализованный текст + media)."""
    norm = _normalize_text(text)[:2000]
    med = (media or "").strip()
    return hashlib.sha1(f"{norm}|{med}".encode('utf-8')).hexdigest()


def find_duplicates(text=None, media=None, source_url=None, content_hash=None):
    """Поиск похожих постов по хэшу / source_url. Возвращает список постов."""
    c = database._connect()
    cur = c.cursor()
    results = []
    if content_hash:
        cur.execute("SELECT id, title, text, status FROM posts WHERE content_hash = ?", (content_hash,))
        results.extend(cur.fetchall())
    if source_url:
        cur.execute("SELECT id, title, text, status FROM posts WHERE source_url = ?", (source_url,))
        results.extend(cur.fetchall())
    c.close()
    # уникализация по id
    seen = set()
    uniq = []
    for row in results:
        if row[0] not in seen:
            seen.add(row[0])
            uniq.append(row)
    return uniq


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def _parse_tags(tags):
    """tags может быть списком или строкой через запятую."""
    if not tags:
        return []
    if isinstance(tags, str):
        return [t.strip() for t in tags.replace('#', '').split(',') if t.strip()]
    return [str(t).strip() for t in tags if str(t).strip()]


def _sync_tags(conn, post_id, tags):
    """Привязывает теги к посту (через справочник content_tags)."""
    cur = conn.cursor()
    cur.execute("DELETE FROM post_tags WHERE post_id = ?", (post_id,))
    for tag in _parse_tags(tags):
        cur.execute("INSERT OR IGNORE INTO content_tags (tag) VALUES (?)", (tag,))
        cur.execute("SELECT id FROM content_tags WHERE tag = ?", (tag,))
        row = cur.fetchone()
        if row:
            cur.execute("INSERT OR IGNORE INTO post_tags (post_id, tag_id) VALUES (?, ?)", (post_id, row[0]))


def create_post(text="", media="", media_type="text", caption="", title="",
                source="telegram", source_url="", original_message_id="",
                original_channel_id="", category="", language="uz",
                hashtags="", tags="", priority=5, status="available",
                duplicate_check=True, check_anyway=False):
    """
    Создаёт пост в Content Storage.
    duplicate_check=True — ищет дубликат; если найден и check_anyway=False — возвращает (None, duplicate).
    Возвращает (post_id, duplicate_or_None).
    """
    if duplicate_check and not check_anyway:
        h = compute_content_hash(text, media)
        dup = find_duplicates(content_hash=h, source_url=source_url)
        if dup:
            return None, dup

    now = int(time.time())
    chash = compute_content_hash(text, media)
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("""INSERT INTO posts
        (source, source_url, original_message_id, original_channel_id, title, text, media,
         media_type, caption, hashtags, category, language, created_at, updated_at, status,
         priority, tags, content_hash)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (source, source_url, original_message_id, original_channel_id, title, text, media,
         media_type, caption, hashtags, category, language, now, now, status,
         priority, ",".join(_parse_tags(tags)), chash))
    post_id = cur.lastrowid
    _sync_tags(conn, post_id, tags)
    conn.commit()
    conn.close()
    return post_id, None


def get_post(post_id):
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("""SELECT id, source, source_url, original_message_id, original_channel_id,
                   title, text, media, media_type, caption, hashtags, category, language,
                   created_at, updated_at, status, priority, is_used, usage_count, last_used_at,
                   times_published, published_channels, tags, content_hash
                   FROM posts WHERE id = ?""", (post_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    cols = ['id', 'source', 'source_url', 'original_message_id', 'original_channel_id',
            'title', 'text', 'media', 'media_type', 'caption', 'hashtags', 'category',
            'language', 'created_at', 'updated_at', 'status', 'priority', 'is_used',
            'usage_count', 'last_used_at', 'times_published', 'published_channels',
            'tags', 'content_hash']
    return dict(zip(cols, row))


def update_post(post_id, **fields):
    """Обновляет поля поста. fields: text, title, category, tags, hashtags, language,
    status, priority, media, media_type, caption, source, source_url + счётчики использования."""
    allowed = ['text', 'title', 'category', 'tags', 'hashtags', 'language', 'status',
               'priority', 'media', 'media_type', 'caption', 'source', 'source_url',
               'usage_count', 'is_used', 'times_published', 'last_used_at', 'published_channels']
    conn = database._connect()
    cur = conn.cursor()
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            if k == 'tags':
                v = ",".join(_parse_tags(v))
            sets.append(f"{k} = ?")
            vals.append(v)
    if sets:
        vals.append(int(time.time()))
        cur.execute(f"UPDATE posts SET {', '.join(sets)}, updated_at = ? WHERE id = ?", vals + [post_id])
        if 'tags' in fields:
            _sync_tags(conn, post_id, fields['tags'])
        conn.commit()
    conn.close()


def delete_post(post_id):
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM post_tags WHERE post_id = ?", (post_id,))
    cur.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()


def set_post_status(post_id, status):
    update_post(post_id, status=status)


def archive_post(post_id):
    update_post(post_id, status='archived')


def restore_post(post_id):
    update_post(post_id, status='available')


def duplicate_post(post_id):
    """Создаёт копию поста (новый id), status=draft."""
    p = get_post(post_id)
    if not p:
        return None
    new_id, _ = create_post(
        text=p['text'], media=p['media'], media_type=p['media_type'], caption=p['caption'],
        title=p['title'], source=p['source'], source_url=p['source_url'], category=p['category'],
        language=p['language'], hashtags=p['hashtags'], tags=p['tags'], priority=p['priority'],
        status='draft', duplicate_check=False)
    return new_id


def list_posts(status=None, category=None, language=None, source=None, tag=None,
               page=1, per_page=50, sort='created_at', order='desc', search=None):
    """Выборка постов с фильтрами и пагинацией."""
    conn = database._connect()
    cur = conn.cursor()
    where, vals = [], []
    if status:
        where.append("status = ?"); vals.append(status)
    if category:
        where.append("category = ?"); vals.append(category)
    if language:
        where.append("language = ?"); vals.append(language)
    if source:
        where.append("source = ?"); vals.append(source)
    if search:
        where.append("(text LIKE ? OR title LIKE ? OR category LIKE ?)")
        vals += [f"%{search}%"] * 3
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = cur.execute(f"SELECT COUNT(*) FROM posts {w}", vals).fetchone()[0]
    if tag:
        w2 = (" AND " if where else "WHERE ") + "id IN (SELECT pt.post_id FROM post_tags pt JOIN content_tags ct ON ct.id=pt.tag_id WHERE ct.tag=?)"
        w += w2
        vals.append(tag)
        total = cur.execute(f"SELECT COUNT(*) FROM posts {w}", vals).fetchone()[0]
    sort_col = sort if sort in ['created_at', 'updated_at', 'priority', 'usage_count', 'times_published', 'last_used_at'] else 'created_at'
    order_sql = "DESC" if order == 'desc' else "ASC"
    offset = (page - 1) * per_page
    cur.execute(f"""SELECT id, title, text, category, language, source, status, priority,
                    usage_count, times_published, last_used_at, tags, media, created_at
                    FROM posts {w} ORDER BY {sort_col} {order_sql} LIMIT ? OFFSET ?""", vals + [per_page, offset])
    rows = cur.fetchall()
    conn.close()
    return {'total': total, 'page': page, 'per_page': per_page, 'pages': max(1, (total + per_page - 1) // per_page), 'items': rows}


def get_post_tags(post_id):
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("""SELECT ct.tag FROM post_tags pt JOIN content_tags ct ON ct.id = pt.tag_id WHERE pt.post_id = ?""", (post_id,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Reuse-логика
# ---------------------------------------------------------------------------
def check_reuse(post, channel_id, settings):
    """
    Проверяет, можно ли использовать пост для канала channel_id.
    Возвращает (ok: bool, reason: str).
    """
    if not post:
        return False, "no post"
    mode = (settings or {}).get('reuse_mode', 'never')
    reuse_days = int((settings or {}).get('reuse_days', 7) or 7)

    pub_channels = post.get('published_channels') or ''
    already = channel_id in [x.strip() for x in pub_channels.split(',') if x.strip()]

    if mode == 'never':
        if post.get('times_published', 0) > 0:
            return False, "already used"
        return True, "ok"
    if mode == 'unlimited':
        return True, "ok"
    if mode == 'after_days':
        last_used = post.get('last_used_at') or 0
        if last_used and (int(time.time()) - last_used) < reuse_days * 86400:
            return False, f"cooldown {reuse_days}d"
        return True, "ok"
    return True, "ok"


def mark_used(post_id, channel_id):
    """Фиксирует факт использования поста в канале."""
    p = get_post(post_id)
    if not p:
        return
    now = int(time.time())
    channels = [x for x in (p.get('published_channels') or '').split(',') if x.strip()]
    if channel_id not in channels:
        channels.append(channel_id)
    update_post(post_id, usage_count=(p.get('usage_count', 0) + 1),
                is_used=1 if p.get('usage_count', 0) + 1 > 0 else 0,
                times_published=p.get('times_published', 0) + 1,
                last_used_at=now, published_channels=",".join(channels))


def reset_usage(post_id):
    update_post(post_id, usage_count=0, is_used=0, times_published=0, last_used_at=0, published_channels="")


# ---------------------------------------------------------------------------
# Селекторы
# ---------------------------------------------------------------------------
def _apply_filters(posts, channel_filters, lang):
    """Фильтрует кандидатов по категориям/тегам/языкам/источникам канала."""
    cats = [x.strip().lower() for x in (channel_filters.get('categories') or '').split(',') if x.strip()]
    tags = [x.strip().lower() for x in (channel_filters.get('tags') or '').split(',') if x.strip()]
    langs = [x.strip().lower() for x in (channel_filters.get('languages') or '').split(',') if x.strip()]
    srcs = [x.strip().lower() for x in (channel_filters.get('sources') or '').split(',') if x.strip()]

    result = []
    for row in posts:
        # row: (id, title, text, category, language, source, status, priority, usage_count, times_published, last_used_at, tags, media, created_at)
        pid, title, text, category, language, source, status, priority, uc, tp, lua, tags_s, media, created = row
        ok = True
        if cats and (category or '').lower() not in cats:
            ok = False
        if langs and (language or '').lower() not in langs:
            ok = False
        if srcs and (source or '').lower() not in srcs:
            ok = False
        if tags:
            post_tags = [t.strip().lower() for t in (tags_s or '').replace('#', '').split(',') if t.strip()]
            if not any(t in post_tags for t in tags):
                ok = False
        if ok:
            result.append(row)
    return result


def _candidates(channel_id, settings):
    """Все доступные посты (status available/queued), отфильтрованные по правилам канала."""
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("""SELECT id, title, text, category, language, source, status, priority,
                   usage_count, times_published, last_used_at, tags, media, created_at
                   FROM posts WHERE status IN ('available','queued')""")
    rows = cur.fetchall()
    conn.close()
    rows = _apply_filters(rows, settings, settings.get('languages'))
    return rows


def _to_post_dict(row):
    return {
        'id': row[0], 'title': row[1], 'text': row[2], 'category': row[3],
        'language': row[4], 'source': row[5], 'status': row[6], 'priority': row[7],
        'usage_count': row[8], 'times_published': row[9], 'last_used_at': row[10],
        'tags': row[11], 'media': row[12], 'created_at': row[13],
        'published_channels': ''
    }


def select_post(channel_id, settings, exclude_post_ids=None):
    """
    Главная точка выбора поста для канала.
    settings — dict конфигурации канала (selection, categories, tags, languages, sources, reuse_*).
    exclude_post_ids — посты, которые уже назначены в этом цикле (чтобы не повторяться).
    Возвращает post_id или None.
    """
    selection = (settings or {}).get('selection', 'random')
    candidates = _candidates(channel_id, settings)
    if not candidates:
        return None

    # исключаем уже выбранные в этом прогоне
    if exclude_post_ids:
        candidates = [r for r in candidates if r[0] not in exclude_post_ids]

    # фильтр по reuse
    allowed = []
    for row in candidates:
        pd = _to_post_dict(row)
        pd['published_channels'] = settings.get('_published_channels_map', {}).get(pd['id'], '')
        ok, _reason = check_reuse(pd, channel_id, settings)
        if ok:
            allowed.append(row)
    if not allowed:
        return None

    if selection == 'fifo':
        return min(allowed, key=lambda r: (r[13], r[0]))[0]
    if selection == 'lifo':
        return max(allowed, key=lambda r: (r[13], r[0]))[0]
    if selection == 'least_used':
        return min(allowed, key=lambda r: (r[8], r[13], r[0]))[0]
    if selection == 'weighted':
        # вес: приоритет -> вероятность
        weights = []
        for r in allowed:
            w = max(1, int(r[7]))
            weights.append(w)
        chosen = random.choices(allowed, weights=weights, k=1)[0]
        return chosen[0]
    if selection == 'category_rotation':
        # простейшая ротация: самый давно не использованный категорийный пост
        return min(allowed, key=lambda r: (r[11] if isinstance(r[11], (int, float)) else 0, r[13]))[0]
    # smart / random
    return random.choice(allowed)[0]


# ---------------------------------------------------------------------------
# Статистика хранилища
# ---------------------------------------------------------------------------
def storage_stats():
    conn = database._connect()
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    available = cur.execute("SELECT COUNT(*) FROM posts WHERE status='available'").fetchone()[0]
    scheduled = cur.execute("SELECT COUNT(*) FROM posts WHERE status='scheduled'").fetchone()[0]
    published = cur.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
    failed = cur.execute("SELECT COUNT(*) FROM posts WHERE status='failed'").fetchone()[0]
    archived = cur.execute("SELECT COUNT(*) FROM posts WHERE status='archived'").fetchone()[0]
    most_used = cur.execute("SELECT id, title, usage_count FROM posts ORDER BY usage_count DESC LIMIT 5").fetchall()
    least_used = cur.execute("SELECT id, title, usage_count FROM posts ORDER BY usage_count ASC LIMIT 5").fetchall()
    conn.close()
    return {'total': total, 'available': available, 'scheduled': scheduled,
            'published': published, 'failed': failed, 'archived': archived,
            'most_used': most_used, 'least_used': least_used}
