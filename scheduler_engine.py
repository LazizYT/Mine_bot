"""Scheduler Engine — автоматическая публикация контента по расписанию.

Проверяет активные каналы, определяет кому пора публиковать (interval/cron + timezone),
выбирает подходящий пост из Content Storage (с учётом фильтров/reuse/дубликатов),
создаёт publication job, публикует и логирует результат.

TEST MODE / DRY RUN: публикации не отправляются в Telegram, только выводятся.
"""
import time
import random
from datetime import datetime, timedelta

import pytz

import config
import database
import channel_manager
import content_storage
import publisher

# Глобальный флаг тестового режима (хранится в global_settings)
def test_mode_enabled():
    return database.get_global_setting('test_mode', '0') == '1'

def set_test_mode(enabled):
    database.set_global_setting('test_mode', '1' if enabled else '0')


def _tz(tzname):
    try:
        return pytz.timezone(tzname or 'Asia/Tashkent')
    except Exception:
        return pytz.timezone('Asia/Tashkent')


def _parse_interval(text):
    """interval может быть числом часов или строкой 'Xh'/'Xm'."""
    if text is None or text == '':
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        pass
    t = str(text).strip().lower()
    if t.endswith('h'):
        try: return float(t[:-1])
        except: return None
    if t.endswith('m'):
        try: return float(t[:-1]) / 60.0
        except: return None
    try:
        return float(t)
    except:
        return None


def _cron_next(cron, now_dt):
    """Простая поддержка cron 'минута час' и 'минута час день месяц день_недели'.
    Возвращает следующий datetime (в локальном времени) или None."""
    parts = cron.split()
    if len(parts) < 2:
        return None
    minute_f = parts[0]
    hour_f = parts[1]
    day_f = parts[2] if len(parts) > 2 else '*'
    month_f = parts[3] if len(parts) > 3 else '*'
    dow_f = parts[4] if len(parts) > 4 else '*'

    def field_ok(value, spec):
        if spec == '*' or spec == '*/1':
            return True
        if spec.startswith('*/'):
            step = int(spec[2:])
            return value % step == 0
        try:
            return int(spec) == value
        except:
            return False

    probe = now_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(48 * 60):  # 2 суток вперёд
        if (field_ok(probe.minute, minute_f) and field_ok(probe.hour, hour_f) and
                (month_f == '*' or field_ok(probe.month, month_f)) and
                (day_f == '*' or field_ok(probe.day, day_f)) and
                (dow_f == '*' or field_ok(probe.weekday(), dow_f))):
            return probe
        probe += timedelta(minutes=1)
    return None


def compute_next_run(settings, last_run_at=None, now_ts=None):
    """
    Вычисляет следующее время публикации для канала с учётом timezone.
    Возвращает unix-ts или None, если канал не должен публиковать.
    """
    if not settings.get('active') or not settings.get('auto_publish'):
        return None
    now_ts = now_ts or int(time.time())
    tz = _tz(settings.get('timezone'))
    now_dt = datetime.fromtimestamp(now_ts, tz)

    cron = settings.get('cron') or ''
    if cron.strip():
        nxt = _cron_next(cron.strip(), now_dt)
        return int(nxt.timestamp()) if nxt else None

    interval = _parse_interval(settings.get('interval_hours'))
    if interval is None or interval <= 0:
        return None

    last_run = last_run_at
    if not last_run:
        # первый запуск: публикуем скоро (через 1 минуту, чтобы не толпой)
        return now_ts + 60
    return int(last_run + interval * 3600)


def find_due_channels(now_ts=None):
    """Каналы, которым пора публиковать (по их расписанию). Batch-запрос без N+1."""
    now_ts = now_ts or int(time.time())
    channels = channel_manager.get_all_channel_settings()
    due = []
    conn = database._connect()
    cur = conn.cursor()
    for row in channels:
        channel_id = row[0]
        username = row[1]
        settings = {
            'active': row[3], 'auto_publish': row[4], 'interval_hours': row[5],
            'cron': row[6] or '', 'timezone': row[7] or 'Asia/Tashkent',
        }
        if not settings['active'] or not settings['auto_publish']:
            continue
        # последняя публикация канала
        cur.execute("SELECT published_at FROM publications WHERE channel_id = ? AND status='SUCCESS' ORDER BY id DESC LIMIT 1", (channel_id,))
        lr = cur.fetchone()
        last_run = lr[0] if lr else None
        # последний pending schedule
        cur.execute("SELECT scheduled_at FROM schedules WHERE channel_id = ? AND status='pending' ORDER BY scheduled_at ASC LIMIT 1", (channel_id,))
        sch = cur.fetchone()
        if sch:
            if sch[0] <= now_ts:
                due.append({'channel_id': channel_id, 'username': username, 'scheduled_at': sch[0]})
            continue
        nxt = compute_next_run(settings, last_run, now_ts)
        if nxt and nxt <= now_ts:
            due.append({'channel_id': channel_id, 'username': username, 'scheduled_at': nxt})
    conn.close()
    return due


def build_channel_settings(channel_id, username):
    """Полный dict настроек канала для селектора."""
    settings = channel_manager.get_settings(username) or {}
    # карта published_channels для reuse
    conn = database._connect()
    cur = conn.cursor()
    # подгрузим published_channels всех постов
    cur.execute("SELECT id, published_channels FROM posts")
    pmap = {}
    for pid, pch in cur.fetchall():
        pmap[pid] = pch or ''
    conn.close()
    settings['_published_channels_map'] = pmap
    settings['channel_id'] = channel_id
    return settings


def create_schedule(channel_id, post_id, scheduled_at):
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("INSERT INTO schedules (channel_id, post_id, scheduled_at, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (channel_id, post_id, scheduled_at, int(time.time())))
    conn.commit()
    conn.close()


def add_to_storage_and_queue(text, media, media_type, channel_id, channel_username,
                             scheduled_time, category="", tags="", language="uz",
                             source="telegram", priority=5):
    """
    Интеграция Smart Queue -> Content Storage (Фаза 4).
    Сохраняет пост в storage, создаёт запись в queue (smart queue), создаёт schedule.
    Возвращает (post_id, queue_id) или (None, None).
    """
    post_id, dup = content_storage.create_post(
        text=text, media=media, media_type=media_type, source=source,
        category=category, language=language, tags=tags, priority=priority,
        status='scheduled' if scheduled_time else 'queued')
    if post_id is None:
        return None, None
    # запись в smart queue
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("""INSERT INTO queue (photo_id, text, document_id, status, channel_id, scheduled_time, post_id, priority, category, tags, created_at)
                   VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)""",
                (media, text, None, channel_username, scheduled_time, post_id, priority, category, tags, int(time.time())))
    queue_id = cur.lastrowid
    conn.commit()
    conn.close()
    if scheduled_time:
        create_schedule(channel_id, post_id, scheduled_time)
    return post_id, queue_id


def select_best_post(channel_id, username, settings, exclude=None):
    """Выбор поста с учётом reuse-правил (не публиковать недавно в тот же канал)."""
    # published_channels map для канала
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("""SELECT p.id, p.published_channels FROM posts p
                   WHERE p.status IN ('available','queued','scheduled')""")
    pmap = {}
    for pid, pch in cur.fetchall():
        pmap[pid] = pch or ''
    conn.close()
    settings = dict(settings or {})
    settings['_published_channels_map'] = pmap
    return content_storage.select_post(channel_id, settings, exclude_post_ids=exclude)


def run_scheduler(bot, dry_run=False):
    """
    Главный проход планировщика.
    dry_run=True — только показать, что было бы опубликовано (DRY RUN).
    Возвращает отчёт {due, selected, skipped, reasons}.
    """
    report = {'due': 0, 'selected': 0, 'skipped': 0, 'reasons': []}
    now_ts = int(time.time())
    due = find_due_channels(now_ts)
    report['due'] = len(due)

    for ch in due:
        username = ch['username']
        if not username:
            report['skipped'] += 1
            report['reasons'].append(('no_username', username))
            continue
        settings = build_channel_settings(ch['channel_id'], username)
        post_id = select_best_post(ch['channel_id'], username, settings)
        if post_id is None:
            report['skipped'] += 1
            report['reasons'].append(('no_content', username))
            log_event('empty_storage', f"Channel {username} has no available content", data=username)
            notify_admin(f"⚠️ Канал {username} — нет подходящего контента.")
            continue

        report['selected'] += 1
        post = content_storage.get_post(post_id)
        scheduled_at = ch['scheduled_at']

        if test_mode_enabled() or dry_run:
            log_event('test_mode', f"[TEST] would publish Post #{post_id} to {username} at {scheduled_at}")
            if dry_run:
                report['reasons'].append(('dry_run', f"{username} -> #{post_id}"))
            continue

        # реальная публикация
        ok, msg_id = _publish(bot, post_id, username, post, scheduled_at)
        if ok:
            content_storage.update_post(post_id, status='published')
            content_storage.mark_used(post_id, username)
            log_publication(post_id, ch['channel_id'], None, scheduled_at, 'SUCCESS', message_id=msg_id)
            database.audit_log('auto_publish', f"post:{post_id}", new_value=f"{username} ok")
            notify_admin(f"✅ Опубликовано #{post_id} в {username}")
        else:
            log_publication(post_id, ch['channel_id'], None, scheduled_at, 'FAILED', error=msg_id)
            database.audit_log('auto_publish_failed', f"post:{post_id}", new_value=f"{username}: {msg_id}")
            notify_admin(f"❌ Ошибка публикации #{post_id} в {username}: {msg_id}")

    return report


def _publish(bot, post_id, username, post, scheduled_at):
    """Публикует пост в канал. Возвращает (ok, message_id_or_error)."""
    try:
        text = post.get('text') or ''
        media = post.get('media') or ''
        media_type = post.get('media_type') or 'text'
        photos, docs = publisher._split_media(media)
        media_arg = ",".join(photos) if media_type in ('photo', 'album', 'video', 'document') else None
        doc_arg = ",".join(docs) if docs else None
        ok = publisher.publish_post_data(bot, -1, media_arg,
                                         text, doc_arg, username, is_auto=True,
                                         media_type=media_type)
        if not ok:
            return False, "publish_post_data returned False"
        return True, ""
    except Exception as e:
        return False, str(e)


def log_publication(post_id, channel_id, network_id, scheduled_at, status, error="", message_id=""):
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("""INSERT INTO publications (post_id, channel_id, network_id, scheduled_at, published_at, status, error, retry_count, message_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (post_id, channel_id, network_id, scheduled_at, int(time.time()), status, error, message_id, int(time.time())))
    pid = cur.lastrowid
    cur.execute("INSERT INTO publication_logs (publication_id, channel_id, post_id, event, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pid, channel_id, post_id, status, error, int(time.time())))
    conn.commit()
    conn.close()
    return pid


def retry_failed(bot):
    """Повтор всех FAILED публикаций."""
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("SELECT id, post_id, channel_id FROM publications WHERE status='FAILED' AND retry_count < 3")
    rows = cur.fetchall()
    conn.close()
    done = 0
    for pid, post_id, channel_id in rows:
        # получаем username канала
        settings = channel_manager.get_settings_by_id(channel_id) if hasattr(channel_manager, 'get_settings_by_id') else None
        username = None
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT username FROM managed_channels WHERE id = ?", (channel_id,))
        r = cur.fetchone()
        conn.close()
        username = r[0] if r else None
        if not username:
            continue
        post = content_storage.get_post(post_id)
        if not post:
            continue
        ok, err = _publish(bot, post_id, username, post, int(time.time()))
        conn = database._connect()
        cur = conn.cursor()
        if ok:
            cur.execute("UPDATE publications SET status='SUCCESS', error='', retry_count = retry_count + 1, published_at = ? WHERE id = ?", (int(time.time()), pid))
            content_storage.update_post(post_id, status='published')
            content_storage.mark_used(post_id, username)
            database.audit_log('retry_success', f"pub:{pid}", new_value=f"post:{post_id}")
        else:
            cur.execute("UPDATE publications SET retry_count = retry_count + 1, error = ?, published_at = ? WHERE id = ?", (err, int(time.time()), pid))
            database.audit_log('retry_failed', f"pub:{pid}", new_value=err)
        conn.commit()
        conn.close()
        done += 1
    return done


def log_event(event_type, message, data=""):
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("INSERT INTO system_events (event_type, message, data, created_at) VALUES (?, ?, ?, ?)",
                (event_type, message, data, int(time.time())))
    conn.commit()
    conn.close()


def notify_admin(text):
    """Отправляет уведомление админу (молча при ошибке)."""
    if database.get_global_setting('notifications_enabled', '1') != '1':
        return
    try:
        from bot_instance import bot
        for admin in getattr(config, 'ADMIN_IDS', []):
            try:
                bot.send_message(admin, text, parse_mode='HTML')
            except Exception:
                pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Publication history / analytics
# ---------------------------------------------------------------------------
def publication_history(status=None, channel_id=None, page=1, per_page=50):
    conn = database._connect()
    cur = conn.cursor()
    where, vals = [], []
    if status:
        where.append("status = ?"); vals.append(status)
    if channel_id:
        where.append("channel_id = ?"); vals.append(channel_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = cur.execute(f"SELECT COUNT(*) FROM publications {w}", vals).fetchone()[0]
    cur.execute(f"""SELECT p.id, p.post_id, p.channel_id, p.status, p.error, p.retry_count,
                    p.message_id, p.scheduled_at, p.published_at, m.username
                    FROM publications p
                    LEFT JOIN managed_channels m ON m.id = p.channel_id
                    {w} ORDER BY p.id DESC LIMIT ? OFFSET ?""", vals + [per_page, (page - 1) * per_page])
    rows = [{'id': r[0], 'post_id': r[1], 'channel_id': r[2], 'status': r[3], 'error': r[4],
             'retry_count': r[5], 'message_id': r[6], 'scheduled_at': r[7], 'published_at': r[8],
             'channel': r[9] or ''} for r in cur.fetchall()]
    conn.close()
    return {'total': total, 'page': page, 'per_page': per_page, 'items': rows}


def analytics():
    conn = database._connect()
    cur = conn.cursor()
    total_posts = cur.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    published_posts = cur.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
    available_posts = cur.execute("SELECT COUNT(*) FROM posts WHERE status='available'").fetchone()[0]
    failed_posts = cur.execute("SELECT COUNT(*) FROM posts WHERE status='failed'").fetchone()[0]
    archived_posts = cur.execute("SELECT COUNT(*) FROM posts WHERE status='archived'").fetchone()[0]
    total_pubs = cur.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
    ok_pubs = cur.execute("SELECT COUNT(*) FROM publications WHERE status='SUCCESS'").fetchone()[0]
    err_pubs = cur.execute("SELECT COUNT(*) FROM publications WHERE status='FAILED'").fetchone()[0]
    # публикации по дням (последние 14)
    import datetime as dt
    days = {}
    for i in range(13, -1, -1):
        day = (dt.datetime.now() - dt.timedelta(days=i)).strftime('%Y-%m-%d')
        days[day] = 0
    cur.execute("SELECT published_at FROM publications WHERE status='SUCCESS'")
    tz = pytz.timezone('Asia/Tashkent')
    for (ts,) in cur.fetchall():
        try:
            day = datetime.fromtimestamp(ts, tz).strftime('%Y-%m-%d')
            if day in days:
                days[day] += 1
        except Exception:
            pass
    conn.close()
    return {
        'posts': {'total': total_posts, 'published': published_posts, 'available': available_posts,
                  'failed': failed_posts, 'archived': archived_posts},
        'publications': {'total': total_pubs, 'success': ok_pubs, 'failed': err_pubs},
        'per_day': days,
    }


def calendar_events(day=None):
    """События календаря публикаций для заданного дня (YYYY-MM-DD) или сегодня."""
    conn = database._connect()
    cur = conn.cursor()
    if not day:
        day = datetime.now().strftime('%Y-%m-%d')
    start = int(datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=pytz.timezone('Asia/Tashkent')).timestamp())
    end = start + 86400
    cur.execute("""SELECT s.scheduled_at, m.username, s.post_id
                   FROM schedules s
                   LEFT JOIN managed_channels m ON m.id = s.channel_id
                   WHERE s.status='pending' AND s.scheduled_at >= ? AND s.scheduled_at < ?
                   ORDER BY s.scheduled_at ASC""", (start, end))
    rows = [{'time': r[0], 'channel': r[1] or '', 'post_id': r[2]} for r in cur.fetchall()]
    conn.close()
    return rows
