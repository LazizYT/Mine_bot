"""USERBOT (Pyrogram) — перехват постов из каналов-источников (RU/EN).

Подписанный аккаунт слушает указанные каналы (userbot_sources). При новом посте:
  - скачивает медиа (фото / альбом / видео / документ + вложенный файл),
  - переводит текст на узбекский через Groq (ai_generator.translate_post),
  - сохраняет результат в Content Storage (статус 'available') для последующей
    автопубликации в каналы.

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
    return {
        'enabled': bool(getattr(config, 'USERBOT_ENABLED', False)),
        'configured': is_configured(),
        'running': _started and _ub is not None,
        'api_id': str(config.USERBOT_API_ID)[:3] + '***' if config.USERBOT_API_ID else '',
        'has_session_string': bool(config.USERBOT_SESSION_STRING),
        'has_session_file': os.path.exists(config.USERBOT_SESSION_FILE),
        'session_file': config.USERBOT_SESSION_FILE,
        'media_dir': config.USERBOT_MEDIA_DIR,
    }


# ---------------------------------------------------------------------------
# Основная логика захвата поста
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


def capture_message(client, message, source_username):
    """
    Обработка одного сообщения из канала-источника.
    Скачивает медиа, переводит текст, сохраняет пост в Content Storage.
    Возвращает post_id или None.
    """
    try:
        if message.service:
            return None
        if message.out:
            return None

        # Текст поста: caption у медиа или обычный text
        raw_text = (message.caption or message.text or "").strip()
        uz_text = _translate(raw_text)

        # Тип медиа и скачивание
        media_type = 'text'
        media_paths = []
        file_path = None  # вложенный файл (документ с названием)

        if message.media_group_id:
            media_type = 'album'
        if message.photo:
            media_type = 'photo'
        if message.video:
            media_type = 'video'
        if message.document:
            media_type = 'document' if media_type == 'text' else media_type
            if message.document.file_name:
                file_path = os.path.join(_get_media_dir(),
                                         f"doc_{source_username.strip('@')}_{message.id}_{message.document.file_name}")
            else:
                file_path = os.path.join(_get_media_dir(),
                                         f"doc_{source_username.strip('@')}_{message.id}")

        # Скачиваем основной медиа-файл
        if message.photo:
            fp = os.path.join(_get_media_dir(), f"ph_{source_username.strip('@')}_{message.id}.jpg")
            try:
                client.download_media(message.photo, file_name=fp)
                if os.path.exists(fp):
                    media_paths.append(fp)
            except Exception as e:
                print(f"⚠️ userbot: не удалось скачать фото {message.id}: {e}")
        if message.video:
            fp = os.path.join(_get_media_dir(), f"vid_{source_username.strip('@')}_{message.id}.mp4")
            try:
                client.download_media(message.video, file_name=fp)
                if os.path.exists(fp):
                    media_paths.append(fp)
            except Exception as e:
                print(f"⚠️ userbot: не удалось скачать видео {message.id}: {e}")
        if message.document:
            try:
                client.download_media(message.document, file_name=file_path)
                if not os.path.exists(file_path):
                    file_path = None
            except Exception as e:
                print(f"⚠️ userbot: не удалось скачать документ {message.id}: {e}")
                file_path = None

        # Сохраняем в Content Storage
        post_id, dup = content_storage.create_post(
            text=uz_text or raw_text or "",
            media=",".join(media_paths),
            media_type=media_type,
            caption="",
            title="",
            source="userbot",
            source_url=f"https://t.me/{source_username.strip('@')}/{message.id}",
            original_message_id=str(message.id),
            original_channel_id=str(message.chat.id),
            category="",
            language="uz",
            tags="",
            priority=5,
            status='available',
            duplicate_check=False,
        )
        if post_id:
            # Вложенный файл храним в отдельном поле media (дополняем списком документов)
            if file_path:
                media_full = (content_storage.get_post(post_id) or {}).get('media', '')
                if media_full:
                    content_storage.update_post(post_id, media=media_full + ",doc:" + file_path)
                else:
                    content_storage.update_post(post_id, media="doc:" + file_path)
            scheduler_engine.log_event('userbot_captured',
                                       f"Captured post #{post_id} from {source_username} (msg {message.id})",
                                       data=uz_text[:200])
            database.audit_log('userbot_captured', f"post:{post_id}", new_value=f"{source_username} msg:{message.id}")
            print(f"✅ userbot: пост #{post_id} из {source_username} (msg {message.id}) сохранён")
        else:
            print(f"⚠️ userbot: дубликат/ошибка сохранения {source_username} msg {message.id}")
        return post_id
    except Exception as e:
        print(f"❌ userbot: ошибка обработки сообщения {message.id}: {e}")
        return None


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
        from pyrogram import Client, filters

        kwargs = {"api_id": int(config.USERBOT_API_ID), "api_hash": config.USERBOT_API_HASH}
        if config.USERBOT_SESSION_STRING:
            kwargs["session_string"] = config.USERBOT_SESSION_STRING
        else:
            kwargs["session_name"] = config.USERBOT_SESSION_FILE

        _ub = Client(**kwargs)

        @_ub.on_message(filters.channel)
        def handle_channel_post(client, message):
            # Находим источник по username канала
            try:
                chat = message.chat
                uname = chat.username or ""
                src = _source_usernames()
                if not uname or f"@{uname}" not in src:
                    return
                last = database.userbot_get_last_message(f"@{uname}")
                if message.id and last and message.id <= last:
                    return
                capture_message(client, message, f"@{uname}")
                if message.id:
                    database.userbot_set_last_message(f"@{uname}", message.id)
            except Exception as e:
                print(f"❌ userbot: handler error: {e}")

        print("🚀 Userbot (Pyrogram) запущен...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _ub.run()  # блокирующий цикл
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
            _ub.stop()
        except Exception:
            pass
    _started = False
