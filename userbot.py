"""USERBOT (Pyrogram) — перехват постов из каналов-источников (RU/EN).

Подписанный аккаунт слушает указанные каналы (userbot_sources). При новом посте:
  - НИЧЕГО не скачивает и не хранит локально,
  - пересылает (server-side copy) пост в ЛС основного бота (@avto_postmine_bot),
    добавляя в подпись скрытый маркер __UBR__:<source_url>,
  - основной бот распознаёт маркер, переводит текст на узбекский, сохраняет пост
    в Content Storage + умную очередь и публикует в каналы.

Тщательная логика (2026-08-11):
  * Антиповтор: каждая обработанная message_id фиксируется в `userbot_history`
    (UNIQUE по source_username+message_id). Один и тот же пост НИКОГДА не
    пересылается дважды — ни при рестарте, ни при дублировании апдейтов.
  * Альбомы: вся media_group пересылается в бота одним copy_media_group.
  * Бэкфилл: при старте догоняются посты, пропущенные пока юзербот был офлайн.

Библиотека Pyrogram подключена лениво: если юзербот отключён в env (USERBOT_ENABLED=0)
или нет API_ID/API_HASH — клиент не создаётся и никакие ошибки не возникают.
"""
import os
import re
import threading
import time

import config
import database
import scheduler_engine


# Скрытый маркер, который юзербот добавляет в подпись пересылаемого поста.
# Основной бот ищет его в caption/text и обрабатывает пост как «релей от юзербота».
UB_MARKER = "__UBR__:"


_ub = None           # Pyrogram Client (ленивый)
_started = False
_lock = threading.Lock()
_album_lock = threading.Lock()
_active_groups = set()   # media_group_id, которые сейчас обрабатываются
_last_relay_ts = 0.0     # timestamp последней пересылки боту (для задержки)


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
        'backfill_limit': int(getattr(config, 'USERBOT_BACKFILL_LIMIT', 10) or 10),
        'bot_username': str(config.USERBOT_BOT_USERNAME or 'avto_postmine_bot'),
        'recent_captures': len(history),
    }


# ---------------------------------------------------------------------------
# Релей в основного бота (юзербот НЕ скачивает медиа — копирует посты в ЛС бота)
# ---------------------------------------------------------------------------
def _is_ad_post(text):
    """Проверяет, похож ли пост на рекламу по ключевым словам / ссылкам.
    Возвращает True, если пост надо ОТФИЛЬТРОВАТЬ (не пересылать боту)."""
    raw = (text or "").lower().strip()
    if not raw:
        return False
    kws = getattr(config, 'USERBOT_AD_KEYWORDS', None) or []
    for kw in kws:
        if kw and kw in raw:
            return True
    # ссылки на сторонние каналы/чаты как признак промо
    if re.search(r't\.me/(joinchat|[+-a-zA-Z0-9_]{4,})', raw):
        return True
    return False


def _relay_throttle():
    """Задержка перед следующей пересылкой боту (USERBOT_RELAY_DELAY сек).
    Даёт основному боту время сгенерировать узбекский пост (Groq rate limit)."""
    delay = float(getattr(config, 'USERBOT_RELAY_DELAY', 0) or 0)
    global _last_relay_ts
    if delay <= 0:
        return
    with _lock:
        since = time.time() - _last_relay_ts
        if _last_relay_ts and since < delay:
            time.sleep(delay - since)
        _last_relay_ts = time.time()


def _ad_throttle(text):
    """Комбинированная проверка: фильтр рекламы + задержка. True — пересылать."""
    if _is_ad_post(text):
        return False
    _relay_throttle()
    return True


def _bot_target():
    """Куда пересылать посты: username/chat основного бота (@avto_postmine_bot)."""
    uname = str(config.USERBOT_BOT_USERNAME or 'avto_postmine_bot').strip().lstrip('@')
    return uname or 'avto_postmine_bot'


def _ub_caption(orig_caption, source_url):
    """Подпись с скрытым маркером для основного бота."""
    return f"{orig_caption}\n\n{UB_MARKER}{source_url}"


def _relay_to_bot(client, message, source_username):
    """Пересылает одиночный пост в ЛС бота (server-side copy). Возвращает True/False."""
    try:
        target = _bot_target()
        raw = (message.caption or message.text or "").strip()
        source_url = f"https://t.me/{source_username.strip('@')}/{message.id}"
        if message.photo or message.video or message.document:
            client.copy_message(target, message.chat.id, message.id,
                                caption=_ub_caption(raw, source_url))
        elif raw:
            client.send_message(target, _ub_caption(raw, source_url))
        else:
            return False
        return True
    except Exception as e:
        print(f"❌ userbot: не удалось переслать пост {message.id} боту: {e}")
        return False


def _relay_group_to_bot(client, messages, source_username):
    """Пересылает media_group в ЛС бота. Возвращает True/False."""
    try:
        target = _bot_target()
        first = messages[0]
        source_url = f"https://t.me/{source_username.strip('@')}/{first.id}"
        # Подписи: все элементы группы, но маркер добавляем в первую подпись.
        captions = []
        for m in messages:
            cap = (m.caption or "").strip()
            if m.id == first.id and cap:
                cap = _ub_caption(cap, source_url)
            elif m.id == first.id:
                cap = f"\n\n{UB_MARKER}{source_url}"
            captions.append(cap)
        client.copy_media_group(target, first.chat.id, first.id, captions=captions)
        return True
    except Exception as e:
        print(f"❌ userbot: не удалось переслать альбом боту: {e}")
        return False


def _log_relayed(source_username, message_id, ok):
    status = 'captured' if ok else 'skipped'
    scheduler_engine.log_event('userbot_captured',
                               f"Relayed {source_username} msg {message_id} to bot ({status})",
                               data=status)
    database.audit_log('userbot_captured', f"msg:{message_id}", new_value=f"{source_username} {status}")
    print(f"{'✅' if ok else '⚠️'} userbot: {source_username} msg {message_id} → бот ({status})")


# ---------------------------------------------------------------------------
# Захват одного поста (фото / видео / документ / текст)
# ---------------------------------------------------------------------------
def capture_message(client, message, source_username):
    """Обработка одного сообщения (не альбом). Возвращает True/False (релей удался?).

    Медиа НЕ скачивается: пост пересылается (server-side copy) в ЛС основного бота
    со скрытым маркером __UBR__:<source_url> в подписи. Бот сам переведёт текст,
    сохранит пост в Content Storage и поставит в умную очередь.
    """
    try:
        raw_text = (message.caption or message.text or "").strip()
        if message.photo or message.video or message.document:
            pass
        elif not raw_text:
            return False
        if not _ad_throttle(raw_text):
            print(f"🚫 userbot: {source_username} msg {message.id} → реклама отфильтрована")
            return False
        ok = _relay_to_bot(client, message, source_username)
        _log_relayed(source_username, message.id, ok)
        return ok
    except Exception as e:
        print(f"❌ userbot: ошибка обработки сообщения {message.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Захват альбома (media_group) — пересылка всей группы в бота
# ---------------------------------------------------------------------------
def capture_album(client, messages, source_username):
    """Пересылает media_group в ЛС бота одним copy_media_group. Возвращает True/False."""
    try:
        members = [m for m in messages if m.photo or m.video]
        if not members:
            return False
        caption = next((m.caption or "" for m in members if m.caption), "")
        if _is_ad_post(caption):
            print(f"🚫 userbot: {source_username} альбом → реклама отфильтрована")
            return False
        _relay_throttle()
        ok = _relay_group_to_bot(client, members, source_username)
        _log_relayed(source_username, members[0].id, ok)
        return ok
    except Exception as e:
        print(f"❌ userbot: ошибка обработки альбома: {e}")
        return False


def _process_message(client, message, source_username):
    """Роутинг: альбом → capture_album, иначе → capture_message."""
    if message.service or getattr(message, 'out', False):
        return None
    if getattr(message, 'media_group_id', None):
        return _process_album(client, message, source_username)
    return capture_message(client, message, source_username)


def _process_album(client, message, source_username):
    """Собирает все члены media_group и пересылает одним релеем."""
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
        ok = capture_album(client, members, source_username)
        # фиксируем ВСЕ члены группы в истории, чтобы другие фото не создали дубли
        for m in members:
            database.userbot_history_add(source_username, m.id, gid, None, status='captured' if ok else 'skipped')
        max_id = max(m.id for m in members)
        last = database.userbot_get_last_message(source_username)
        if max_id > last:
            database.userbot_set_last_message(source_username, max_id)
        return ok
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
                ok = _process_message(client, message, f"@{uname}")
                # для одиночных сообщений фиксируем историю + last_message_id
                if not getattr(message, 'media_group_id', None):
                    database.userbot_history_add(f"@{uname}", message.id, "",
                                                 None, status='captured' if ok else 'skipped')
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
