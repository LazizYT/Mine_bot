"""USERBOT (Pyrogram) — перехват постов из каналов-источников (RU/EN).

Подписанный аккаунт слушает указанные каналы (userbot_sources). При новом посте:
  - скачивает медиа (фото / альбом / видео / документ + вложенный файл),
  - переводит текст на узбекский через Groq (ai_generator.translate_post),
  - сохраняет результат в Content Storage (статус 'available') для последующей
    автопубликации в каналы.

Тщательная логика (2026-08-11):
  * Антиповтор: каждая обработанная message_id фиксируется в `userbot_history`
    (UNIQUE по source_username+message_id). Один и тот же пост НИКОГДА не качается
    дважды — ни при рестарте, ни при дублировании апдейтов.
  * Альбомы: все фото одного media_group объединяются в ОДИН пост (media_type=album).
  * Бэкфилл: при старте догоняются посты, пропущенные пока юзербот был офлайн.
  * Видео: скачивается как media_type=video и корректно публикуется (send_video).

Библиотека Pyrogram подключена лениво: если юзербот отключён в env (USERBOT_ENABLED=0)
или нет API_ID/API_HASH — клиент не создаётся и никакие ошибки не возникают.
"""
import os
import time
import threading

import config
import database
import content_storage
import ai_generator
import scheduler_engine


_ub = None           # Pyrogram Client (ленивый)
_started = False
_lock = threading.Lock()
_album_lock = threading.Lock()
_active_groups = set()   # media_group_id, которые сейчас обрабатываются


# ---------------------------------------------------------------------------
# Конфигурация / статус
# ---------------------------------------------------------------------------
def is_configured():
    """Есть ли всё необходимое для запуска юзербота."""
    return bool(config.USERBOT_API_ID and config.USERBOT_API_HASH) and (
        bool(config.USERBOT_SESSION_STRING) or
        os.path.exists(config.USERBOT_SESSION_FILE))


def is_enabled():
    return bool(getattr(config, 'USERBOT_ENABLED', False)) and is_configured()


def status():
    """Статус юзербота для панели."""
    history = []
    try:
        history = database.userbot_history_list(limit=5)
    except Exception:
        pass
    return {
        'enabled': bool(getattr(config, 'USERBOT_ENABLED', False)),
        'configured': is_configured(),
        'running': _started and _ub is not None,
        'api_id': str(config.USERBOT_API_ID)[:3] + '***' if config.USERBOT_API_ID else '',
        'has_session_string': bool(config.USERBOT_SESSION_STRING),
        'has_session_file': os.path.exists(config.USERBOT_SESSION_FILE),
        'session_file': config.USERBOT_SESSION_FILE,
        'media_dir': config.USERBOT_MEDIA_DIR,
        'backfill_limit': int(getattr(config, 'USERBOT_BACKFILL_LIMIT', 10) or 10),
        'recent_captures': len(history),
    }


# ---------------------------------------------------------------------------
# Медиа / перевод
# ---------------------------------------------------------------------------
def _get_media_dir():
    d = config.USERBOT_MEDIA_DIR
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _translate(text):
    """Перевод текста поста на узбекский (только если текст непустой)."""
    if not text or not text.strip():
        return ""
    try:
        return ai_generator.translate_post(text, "uz") or ""
    except Exception as e:
        print(f"⚠️ userbot: ошибка перевода: {e}")
        return ""


def _download(client, media, prefix, source_username, message_id, ext):
    """Скачивает медиа в папку userbot. Возвращает путь или None."""
    fp = os.path.join(_get_media_dir(), f"{prefix}_{source_username.strip('@')}_{message_id}.{ext}")
    try:
        client.download_media(media, file_name=fp)
        return fp if os.path.exists(fp) else None
    except Exception as e:
        print(f"⚠️ userbot: не удалось скачать {prefix} {message_id}: {e}")
        return None


def _existing_post_id(source_url):
    """Если такой source_url уже сохранён (дубликат) — вернуть его id."""
    try:
        dups = content_storage.find_duplicates(source_url=source_url)
        return dups[0][0] if dups else None
    except Exception:
        return None


def _log_captured(post_id, source_username, message_id, text):
    scheduler_engine.log_event('userbot_captured',
                               f"Captured post #{post_id} from {source_username} (msg {message_id})",
                               data=(text or '')[:200])
    database.audit_log('userbot_captured', f"post:{post_id}", new_value=f"{source_username} msg:{message_id}")
    print(f"✅ userbot: пост #{post_id} из {source_username} (msg {message_id}) сохранён")


# ---------------------------------------------------------------------------
# Захват одного поста (фото / видео / документ / текст)
# ---------------------------------------------------------------------------
def capture_message(client, message, source_username):
    """Обработка одного сообщения (не альбом). Возвращает post_id (или id дубликата) или None."""
    try:
        raw_text = (message.caption or message.text or "").strip()
        uz_text = _translate(raw_text)

        media_paths = []
        file_path = None
        media_type = 'text'

        if message.photo:
            media_type = 'photo'
            p = _download(client, message.photo, 'ph', source_username, message.id, 'jpg')
            if p:
                media_paths.append(p)
        elif message.video:
            media_type = 'video'
            p = _download(client, message.video, 'vid', source_username, message.id, 'mp4')
            if p:
                media_paths.append(p)
        elif message.document:
            media_type = 'document'
            fname = getattr(message.document, 'file_name', None) or f"file_{message.id}"
            safe_name = os.path.basename(fname)
            file_path = os.path.join(_get_media_dir(), f"doc_{source_username.strip('@')}_{message.id}_{safe_name}")
            try:
                client.download_media(message.document, file_name=file_path)
                if not os.path.exists(file_path):
                    file_path = None
            except Exception as e:
                print(f"⚠️ userbot: не удалось скачать документ {message.id}: {e}")
                file_path = None

        if media_type == 'text' and not raw_text:
            return None

        source_url = f"https://t.me/{source_username.strip('@')}/{message.id}"
        post_id, dup = content_storage.create_post(
            text=uz_text or raw_text or "",
            media=",".join(media_paths),
            media_type=media_type,
            caption="",
            title="",
            source="userbot",
            source_url=source_url,
            original_message_id=str(message.id),
            original_channel_id=str(message.chat.id),
            category="",
            language="uz",
            tags="",
            priority=5,
            status='available',
            duplicate_check=True,
            check_anyway=False,
        )
        if post_id is None:
            post_id = _existing_post_id(source_url)
        if post_id and file_path:
            media_full = (content_storage.get_post(post_id) or {}).get('media', '')
            media_full = f"{media_full},doc:{file_path}" if media_full else f"doc:{file_path}"
            content_storage.update_post(post_id, media=media_full)
        if post_id:
            _log_captured(post_id, source_username, message.id, uz_text or raw_text)
        else:
            print(f"⚠️ userbot: пустой/дубликат {source_username} msg {message.id}")
        return post_id
    except Exception as e:
        print(f"❌ userbot: ошибка обработки сообщения {message.id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Захват альбома (media_group) — все фото/видео в ОДИН пост
# ---------------------------------------------------------------------------
def capture_album(client, messages, source_username):
    """Обрабатывает список сообщений одной media_group как один пост."""
    try:
        members = [m for m in messages if m.photo or m.video]
        if not members:
            return None
        raw_text = ""
        for m in members:
            if getattr(m, 'caption', None):
                raw_text = m.caption.strip()
                break
        uz_text = _translate(raw_text)

        media_paths = []
        for m in members:
            if m.photo:
                p = _download(client, m.photo, 'ph', source_username, m.id, 'jpg')
            elif m.video:
                p = _download(client, m.video, 'vid', source_username, m.id, 'mp4')
            else:
                p = None
            if p:
                media_paths.append(p)
        if not media_paths and not uz_text:
            return None

        first = members[0]
        source_url = f"https://t.me/{source_username.strip('@')}/{first.id}"
        post_id, dup = content_storage.create_post(
            text=uz_text or raw_text or "",
            media=",".join(media_paths),
            media_type='album',
            caption="",
            title="",
            source="userbot",
            source_url=source_url,
            original_message_id=str(first.id),
            original_channel_id=str(first.chat.id),
            category="",
            language="uz",
            tags="",
            priority=5,
            status='available',
            duplicate_check=True,
            check_anyway=False,
        )
        if post_id is None:
            post_id = _existing_post_id(source_url)
        if post_id:
            _log_captured(post_id, source_username, first.id, uz_text or raw_text)
        return post_id
    except Exception as e:
        print(f"❌ userbot: ошибка обработки альбома: {e}")
        return None


def _process_message(client, message, source_username):
    """Роутинг: альбом → capture_album, иначе → capture_message."""
    if message.service or getattr(message, 'out', False):
        return None
    if getattr(message, 'media_group_id', None):
        return _process_album(client, message, source_username)
    return capture_message(client, message, source_username)


def _process_album(client, message, source_username):
    """Собирает все члены media_group и захватывает одним постом."""
    gid = message.media_group_id
    with _album_lock:
        if gid in _active_groups:
            return None
        # Если хотя бы один член группы уже перехвачен — пропускаем целиком
        if database.userbot_history_exists(source_username, message.id):
            return None
        _active_groups.add(gid)
    try:
        members = client.get_media_group(message.chat.id, message.id) or []
        members = [m for m in members if m.photo or m.video]
        if not members:
            return None
        if any(database.userbot_history_exists(source_username, m.id) for m in members):
            return None
        post_id = capture_album(client, members, source_username)
        # фиксируем ВСЕ члены группы в истории, чтобы другие фото не создали дубли
        for m in members:
            database.userbot_history_add(source_username, m.id, gid, post_id, status='captured' if post_id else 'skipped')
        max_id = max(m.id for m in members)
        last = database.userbot_get_last_message(source_username)
        if max_id > last:
            database.userbot_set_last_message(source_username, max_id)
        return post_id
    finally:
        with _album_lock:
            _active_groups.discard(gid)


# ---------------------------------------------------------------------------
# Бэкфилл пропущенных постов (запускается при старте)
# ---------------------------------------------------------------------------
def backfill(client, source_username):
    """Догоняет посты из канала-источника, которые могли быть пропущены
    пока юзербот был офлайн. Проходит по последним N сообщениям и захватывает новые."""
    try:
        limit = int(getattr(config, 'USERBOT_BACKFILL_LIMIT', 10) or 10)
        last_id = database.userbot_get_last_message(source_username)
        history = list(client.get_chat_history(source_username, limit=limit)) or []
        # идём от старых к новым, чтобы не пропустить порядок
        candidates = [m for m in reversed(history) if m.id > last_id]
        for m in candidates:
            if database.userbot_history_exists(source_username, m.id):
                continue
            _process_message(client, m, source_username)
            if not getattr(m, 'media_group_id', None):
                database.userbot_history_add(source_username, m.id, "", None, status='skipped')
                last = database.userbot_get_last_message(source_username)
                if m.id > last:
                    database.userbot_set_last_message(source_username, m.id)
        if candidates:
            print(f"🔁 userbot: бэкфилл {source_username}: проверено {len(candidates)} постов")
    except Exception as e:
        print(f"⚠️ userbot: ошибка бэкфилла {source_username}: {e}")


def _source_usernames():
    return [s['username'] for s in database.userbot_get_sources() if s['enabled']]


# ---------------------------------------------------------------------------
# Запуск / остановка
# ---------------------------------------------------------------------------
def start():
    """Запускает юзербота в отдельном потоке (если настроен и включён)."""
    global _ub, _started
    if _started:
        return
    if not is_enabled():
        print("ℹ️ userbot отключён (USERBOT_ENABLED=0 или нет api_id/hash/session)")
        return
    if not is_configured():
        print("⚠️ userbot: не хватает API_ID/API_HASH или сессии — запуск пропущен")
        return
    _started = True
    t = threading.Thread(target=_run, daemon=True, name="userbot")
    t.start()


def _run():
    global _ub
    try:
        import asyncio
        # ВАЖНО: Pyrogram берёт loop в конструкторе Client() — установим его заранее,
        # иначе в потоке без текущего loop будет RuntimeError.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        from pyrogram import Client, filters

        # Pyrogram требует имя (name) всегда, даже при session_string.
        if config.USERBOT_SESSION_STRING:
            _ub = Client("userbot", api_id=int(config.USERBOT_API_ID),
                         api_hash=config.USERBOT_API_HASH,
                         session_string=config.USERBOT_SESSION_STRING)
        else:
            _ub = Client(config.USERBOT_SESSION_FILE, api_id=int(config.USERBOT_API_ID),
                         api_hash=config.USERBOT_API_HASH)

        @_ub.on_message(filters.channel)
        def handle_channel_post(client, message):
            try:
                chat = message.chat
                uname = chat.username or ""
                if not uname or f"@{uname}" not in _source_usernames():
                    return
                # антиповтор: уже перехваченное сообщение не трогаем
                if database.userbot_history_exists(f"@{uname}", message.id):
                    return
                post_id = _process_message(client, message, f"@{uname}")
                # для одиночных сообщений фиксируем историю + last_message_id
                if not getattr(message, 'media_group_id', None):
                    database.userbot_history_add(f"@{uname}", message.id, "",
                                                 post_id, status='captured' if post_id else 'skipped')
                    last = database.userbot_get_last_message(f"@{uname}")
                    if message.id > last:
                        database.userbot_set_last_message(f"@{uname}", message.id)
            except Exception as e:
                print(f"❌ userbot: handler error: {e}")

        print("🚀 Userbot (Pyrogram) запущен...")
        # В фоновом потоке нельзя использовать _ub.run() (он зовёт idle(),
        # который ставит обработчики сигналов — только main thread).
        # start() в Pyrogram синхронный: вызываем его напрямую,
        # затем держим event loop живым через run_forever.
        _ub.start()

        # Бэкфилл пропущенных постов (после подключения, до run_forever)
        try:
            for src in _source_usernames():
                backfill(_ub, src)
        except Exception as e:
            print(f"⚠️ userbot: бэкфилл пропущен: {e}")

        loop.run_forever()
    except Exception as e:
        print(f"❌ userbot: ошибка запуска: {e}")
    finally:
        _started = False
        _ub = None


def stop():
    """Останавливает юзербота (если клиент запущен)."""
    global _ub, _started
    if _ub is not None:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_ub.stop()))
            else:
                _ub.stop()
        except Exception:
            try:
                _ub.stop()
            except Exception:
                pass
    _started = False
