"""Channel Manager — конфигурация каналов, сети, шаблоны, bulk-действия.

Каждый канал имеет собственную настройку автопубликации (interval/cron/timezone,
алгоритм выбора, фильтры, reuse). Каналы объединяются в сети. Шаблоны позволяют
применять одинаковые настройки к множеству каналов одним действием.
"""
import time
import json

import database

# Поля, которые копируются при clone/template apply (НЕ копируются уникальные: id/username)
CLONABLE_FIELDS = ['name', 'network_id', 'active', 'description', 'auto_publish',
                   'interval_hours', 'cron', 'timezone', 'start_time', 'end_time',
                   'max_posts_per_day', 'selection', 'categories', 'tags', 'languages',
                   'sources', 'reuse_mode', 'reuse_days', 'post_template', 'prefix',
                   'suffix', 'hashtags', 'link_preview', 'media_settings',
                   'duplicate_protection', 'flood_protection', 'failed_retry_count',
                   'cooldown', 'rate_limit', 'min_delay']

DEFAULT_SETTINGS = {
    'name': '', 'network_id': None, 'active': 1, 'description': '', 'auto_publish': 1,
    'interval_hours': 6, 'cron': '', 'timezone': 'Asia/Tashkent', 'start_time': '',
    'end_time': '', 'max_posts_per_day': 0, 'selection': 'random', 'categories': '',
    'tags': '', 'languages': 'uz', 'sources': '', 'reuse_mode': 'never',
    'reuse_days': 7, 'post_template': '', 'prefix': '', 'suffix': '',
    'hashtags': '', 'link_preview': 1, 'media_settings': '',
    'duplicate_protection': 1, 'flood_protection': 1, 'failed_retry_count': 3,
    'cooldown': 0, 'rate_limit': 0, 'min_delay': 0,
}


def _connect():
    return database._connect()


# ---------------------------------------------------------------------------
# Channel settings
# ---------------------------------------------------------------------------
def ensure_settings(channel_username):
    """Гарантирует наличие строки настроек для канала. Возвращает dict настроек."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM managed_channels WHERE username = ?", (channel_username,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO managed_channels (username) VALUES (?)", (channel_username,))
        channel_id = cur.lastrowid
        conn.commit()
    else:
        channel_id = row[0]

    cur.execute("SELECT * FROM channel_settings WHERE channel_id = ?", (channel_id,))
    srow = cur.fetchone()
    now = int(time.time())
    if not srow:
        cols = list(DEFAULT_SETTINGS.keys()) + ['username', 'created_at', 'updated_at']
        cur.execute("""INSERT INTO channel_settings (channel_id, username, created_at, updated_at)
                       VALUES (?, ?, ?, ?)""", (channel_id, channel_username, now, now))
        conn.commit()
        settings = dict(DEFAULT_SETTINGS)
        settings['username'] = channel_username
    else:
        cols = [d[0] for d in cur.description]
        settings = dict(zip(cols, srow))
    conn.close()
    return settings


def get_settings_by_id(channel_id):
    """Настройки канала по числовому id."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT username FROM managed_channels WHERE id = ?", (channel_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return get_settings(row[0])


def get_settings(channel_username):
    """Настройки канала (dict) или None, если канал не в БД."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM managed_channels WHERE username = ?", (channel_username,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    cur.execute("SELECT * FROM channel_settings WHERE channel_id = ?", (row[0],))
    srow = cur.fetchone()
    cols = [d[0] for d in cur.description]
    conn.close()
    if not srow:
        return ensure_settings(channel_username)
    return dict(zip(cols, srow))


def save_settings(channel_username, updates):
    """Сохраняет произвольный набор полей настроек канала."""
    settings = ensure_settings(channel_username)
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM managed_channels WHERE username = ?", (channel_username,))
    channel_id = cur.fetchone()[0]
    allowed = set(CLONABLE_FIELDS)
    sets, vals = [], []
    for k, v in updates.items():
        if k in allowed:
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k} = ?"); vals.append(v)
    if sets:
        vals.append(int(time.time()))
        cur.execute(f"UPDATE channel_settings SET {', '.join(sets)}, updated_at = ? WHERE channel_id = ?",
                    vals + [channel_id])
        conn.commit()
    conn.close()
    return True


def get_all_channel_settings():
    """Все настройки каналов + имена каналов."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""SELECT cs.channel_id, m.username, cs.name, cs.active, cs.auto_publish,
                   cs.interval_hours, cs.cron, cs.timezone, cs.selection, cs.categories,
                   cs.languages, cs.reuse_mode, cs.reuse_days, cs.network_id,
                   cs.post_template, cs.max_posts_per_day, cs.failed_retry_count
                   FROM channel_settings cs
                   LEFT JOIN managed_channels m ON m.id = cs.channel_id""")
    rows = cur.fetchall()
    conn.close()
    return rows


def channel_table():
    """Данные для таблицы каналов (следующая публикация, последняя, ошибки)."""
    import content_storage
    rows = get_all_channel_settings()
    out = []
    for r in rows:
        channel_id, username, name, active, auto, interval_h, cron, tz, sel, cats, langs, reuse, reuse_d, net_id, tpl, maxd, retry = r
        # последняя публикация
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT scheduled_at, status FROM publications WHERE channel_id = ? ORDER BY id DESC LIMIT 1", (channel_id,))
        last = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM publications WHERE channel_id = ? AND status != 'SUCCESS'", (channel_id,))
        err_count = cur.fetchone()[0]
        conn.close()
        out.append({
            'channel_id': channel_id,
            'username': username or '',
            'name': name or username or '',
            'status': 'ACTIVE' if active else 'DISABLED',
            'auto_publish': auto,
            'interval_hours': interval_h,
            'cron': cron,
            'timezone': tz,
            'selection': sel,
            'categories': cats,
            'languages': langs,
            'reuse_mode': reuse,
            'reuse_days': reuse_d,
            'network_id': net_id,
            'last_post': last[0] if last else None,
            'last_status': last[1] if last else None,
            'errors': err_count,
        })
    return out


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------
def create_network(name, description=""):
    conn = _connect()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("INSERT INTO networks (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (name, description, now, now))
    nid = cur.lastrowid
    conn.commit()
    conn.close()
    return nid


def get_networks():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""SELECT n.id, n.name, n.description,
                   (SELECT COUNT(*) FROM network_channels nc WHERE nc.network_id = n.id),
                   (SELECT COUNT(*) FROM publications p JOIN channel_settings cs ON p.channel_id = cs.channel_id WHERE cs.network_id = n.id AND p.status='SUCCESS')
                   FROM networks n ORDER BY n.id DESC""")
    rows = [{'id': r[0], 'name': r[1], 'description': r[2], 'channels': r[3], 'publications': r[4]} for r in cur.fetchall()]
    conn.close()
    return rows


def rename_network(nid, name):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE networks SET name = ?, updated_at = ? WHERE id = ?", (name, int(time.time()), nid))
    conn.commit()
    conn.close()


def delete_network(nid):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM network_channels WHERE network_id = ?", (nid,))
    cur.execute("DELETE FROM networks WHERE id = ?", (nid,))
    conn.commit()
    conn.close()


def network_channels(nid):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""SELECT m.username FROM network_channels nc
                   JOIN managed_channels m ON m.id = nc.channel_id WHERE nc.network_id = ?""", (nid,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def add_channel_to_network(nid, channel_username):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM managed_channels WHERE username = ?", (channel_username,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO managed_channels (username) VALUES (?)", (channel_username,))
        cid = cur.lastrowid
        conn.commit()
    else:
        cid = row[0]
    cur.execute("INSERT OR IGNORE INTO network_channels (network_id, channel_id) VALUES (?, ?)", (nid, cid))
    # проставляем network_id в настройки
    cur.execute("UPDATE channel_settings SET network_id = ?, updated_at = ? WHERE channel_id = ?", (nid, int(time.time()), cid))
    conn.commit()
    conn.close()


def remove_channel_from_network(nid, channel_username):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM managed_channels WHERE username = ?", (channel_username,))
    row = cur.fetchone()
    if row:
        cur.execute("DELETE FROM network_channels WHERE network_id = ? AND channel_id = ?", (nid, row[0]))
        cur.execute("UPDATE channel_settings SET network_id = NULL WHERE channel_id = ?", (row[0],))
    conn.commit()
    conn.close()


def pause_network(nid, pause=True):
    """Пауза/возобновление всех каналов сети (не удаляет контент/расписание)."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""UPDATE channel_settings SET active = ?, updated_at = ?
                   WHERE network_id = ?""", (0 if pause else 1, int(time.time()), nid))
    conn.commit()
    conn.close()


def is_network_paused(nid):
    """Сеть считается на паузе, если ни один её канал не активен."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""SELECT COUNT(*) FROM channel_settings cs
                   WHERE cs.network_id = ? AND cs.active = 1""", (nid,))
    active = cur.fetchone()[0]
    conn.close()
    return active == 0


def clone_network(nid, new_name):
    """Клонирование сети: копируются шаблоны/настройки каналов, но не id/история."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT name, description FROM networks WHERE id = ?", (nid,))
    src = cur.fetchone()
    if not src:
        conn.close()
        return None
    new_id = create_network(new_name, src[1])
    # копируем настройки каналов в новую сеть (создаём новые каналы с префиксом)
    channels = network_channels(nid)
    for ch in channels:
        settings = get_settings(ch)
        new_ch = ch
        # если имя изменили — оставляем username тем же, но сеть новую
        add_channel_to_network(new_id, new_ch)
        save_settings(new_ch, {'network_id': new_id})
    conn.close()
    return new_id


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def create_template(name, description, data):
    """data — dict полей настроек, которые будут применены к каналам."""
    conn = _connect()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("INSERT INTO templates (name, description, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, description, json.dumps(data, ensure_ascii=False), now, now))
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


def get_templates():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, data, created_at FROM templates ORDER BY id DESC")
    rows = [{'id': r[0], 'name': r[1], 'description': r[2], 'data': json.loads(r[3] or '{}'), 'created_at': r[4]} for r in cur.fetchall()]
    conn.close()
    return rows


def delete_template(tid):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM templates WHERE id = ?", (tid,))
    conn.commit()
    conn.close()


def apply_template(tid, channels):
    """Применяет шаблон к списку каналов (username)."""
    templates = get_templates()
    tpl = next((t for t in templates if t['id'] == tid), None)
    if not tpl:
        return 0
    data = {k: v for k, v in tpl['data'].items() if k in CLONABLE_FIELDS}
    count = 0
    for ch in channels:
        save_settings(ch, data)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------
def bulk_update(channels, updates):
    """Применяет одинаковые изменения к нескольким каналам."""
    allowed = set(CLONABLE_FIELDS)
    clean = {k: v for k, v in updates.items() if k in allowed}
    count = 0
    for ch in channels:
        save_settings(ch, clean)
        count += 1
    return count


def clone_settings(source_username, target_usernames):
    """Клонирует конфигурацию канала на другие (без уникальных id/username)."""
    src = get_settings(source_username)
    if not src:
        return 0
    data = {k: src.get(k) for k in CLONABLE_FIELDS if k not in ('username',)}
    count = 0
    for ch in target_usernames:
        save_settings(ch, data)
        count += 1
    return count


def delete_channel(channel_username):
    """Удаляет канал из БД и настроек (не трогает Telegram)."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM managed_channels WHERE username = ?", (channel_username,))
    row = cur.fetchone()
    if row:
        cid = row[0]
        cur.execute("DELETE FROM channel_settings WHERE channel_id = ?", (cid,))
        cur.execute("DELETE FROM network_channels WHERE channel_id = ?", (cid,))
        cur.execute("DELETE FROM schedules WHERE channel_id = ?", (cid,))
        cur.execute("DELETE FROM publications WHERE channel_id = ?", (cid,))
        cur.execute("DELETE FROM managed_channels WHERE id = ?", (cid,))
    conn.commit()
    conn.close()
