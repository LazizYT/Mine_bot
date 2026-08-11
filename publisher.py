import os
import telebot
import config
import database
import time

def _open_media(item):
    """Открывает медиа для отправки: локальный файл → file object; иначе file_id/URL."""
    if not item:
        return None
    item = str(item).strip()
    if not item:
        return None
    if os.path.exists(item):
        return open(item, 'rb')
    return item

def _split_media(media_str):
    """Разбивает строку media на (фото/видео пути, документы). Документы имеют префикс doc:."""
    photos, docs = [], []
    for part in str(media_str or '').split(','):
        part = part.strip()
        if not part:
            continue
        if part.startswith('doc:'):
            docs.append(part[4:])
        else:
            photos.append(part)
    return photos, docs

_VIDEO_EXT = ('.mp4', '.webm', '.mov', '.mkv', '.avi', '.m4v')

def _is_video(path):
    return str(path).lower().endswith(_VIDEO_EXT)

def publish_post_data(bot, post_id, photo_id, text, document_id, channel_id, is_auto=False, media_type='photo'):
    """
    Основная функция публикации контента в Telegram канал.
    Проверяет права бота в канале.
    photo_id/document_id могут быть file_id, URL или локальными путями к файлам.
    media_type: photo / album / video / text / document.
    """
    try:
        # Проверка прав администратора
        member = bot.get_chat_member(channel_id, bot.get_me().id)
        if member.status not in ['administrator', 'creator']:
            raise Exception(f"Бот не является администратором в канале {channel_id}")

        # Добавляем текст умной очереди, если это автопостинг
        if is_auto:
            sq_text = database.get_global_setting('smart_queue_text', '')
            if sq_text and sq_text not in text:
                text += f"\n\n{sq_text}"

        # 1. Отправка медиа
        sent_message = None
        if media_type == 'video' and photo_id:
            # одиночное видео
            if len(text) <= 1024:
                sent_message = bot.send_video(channel_id, _open_media(photo_id), caption=text, parse_mode='HTML')
            else:
                bot.send_video(channel_id, _open_media(photo_id))
                sent_message = bot.send_message(channel_id, text, parse_mode='HTML')
        elif photo_id:
            if ',' in photo_id: # Если в строке несколько ID через запятую — это альбом
                ids = photo_id.split(',')
                # Формируем список MediaGroup. Текст (caption) прикрепляем к первому элементу.
                media = []
                for i, pid in enumerate(ids):
                    cap = text if i == 0 and len(text) <= 1024 else None
                    if _is_video(pid):
                        media.append(telebot.types.InputMediaVideo(media=_open_media(pid), caption=cap, parse_mode='HTML'))
                    else:
                        media.append(telebot.types.InputMediaPhoto(media=_open_media(pid), caption=cap, parse_mode='HTML'))
                messages = bot.send_media_group(channel_id, media)
                sent_message = messages[0] # Сохраняем ID первого сообщения в группе
                # Если текст слишком длинный для подписи к фото (>1024 симв), отправляем его отдельным сообщением
                if len(text) > 1024:
                    bot.send_message(channel_id, text, parse_mode='HTML')
            else: # Одиночное фото/видео
                if _is_video(photo_id):
                    if len(text) <= 1024:
                        sent_message = bot.send_video(channel_id, _open_media(photo_id), caption=text, parse_mode='HTML')
                    else:
                        bot.send_video(channel_id, _open_media(photo_id))
                        sent_message = bot.send_message(channel_id, text, parse_mode='HTML')
                elif len(text) <= 1024:
                    sent_message = bot.send_photo(channel_id, _open_media(photo_id), caption=text, parse_mode='HTML')
                else:
                    bot.send_photo(channel_id, _open_media(photo_id))
                    sent_message = bot.send_message(channel_id, text, parse_mode='HTML')
        else: # Только текст (без фото)
            sent_message = bot.send_message(channel_id, text, parse_mode='HTML')
            
        # 2. Отправка документов (поддержка нескольких файлов через запятую)
        if document_id:
            doc_ids = document_id.split(',')
            for d_id in doc_ids:
                d_id = d_id.strip()
                if d_id:
                    try:
                        bot.send_document(channel_id, _open_media(d_id))
                    except Exception as de:
                        print(f"⚠️ Ошибка отправки документа {d_id}: {de}")
        
        # Если публикация прошла успешно, уведомляем админа
        for admin in getattr(config, 'ADMIN_IDS', []):
            try: 
                post_title = text.split('\n')[0].replace('📦 ', '')[:50]
                msg = f"✅ <b>Пост опубликован:</b>\nМод: {post_title}\nКанал: {channel_id}\nВремя: {time.strftime('%H:%M:%S', time.localtime())}"
                if is_auto: msg = f"✅ <b>Автопостинг:</b> Мод <i>{post_title}</i> успешно опубликован в {channel_id} в {time.strftime('%H:%M:%S', time.localtime())}!"
                bot.send_message(admin, msg, parse_mode='HTML')
            except: pass

        # Если это пост из очереди (post_id != -1), помечаем его как опубликованный в БД
        if post_id != -1: 
            database.mark_as_posted(post_id)
            if sent_message:
                database.update_message_id(post_id, sent_message.message_id)


                    
        print(f"✅ Пост #{post_id} опубликован в {channel_id}!")
        return True
    except Exception as e:
        # В случае ошибки при автопостинге — уведомляем админа
        if post_id != -1 and is_auto:
            for admin in getattr(config, 'ADMIN_IDS', []):
                try: bot.send_message(admin, f"❌ <b>Ошибка автопостинга:</b> Канал {channel_id}. Ошибка: {e}", parse_mode='HTML')
                except: pass
        print(f"❌ Ошибка публикации в {channel_id}: {e}")
        return False

import ai_generator

def auto_ask_suggestions(bot):
    """Автоматически генерирует и публикует пост с запросом предложений."""
    try:
        # Берем язык по умолчанию (админа)
        admin_lang = database.get_user_setting(config.ADMIN_IDS[0], 'persona', 'uz')
        text = ai_generator.generate_suggestion_request(admin_lang)
        
        if text:
            bot.send_message(config.DEFAULT_CHANNEL, text, parse_mode='HTML')
            # Также записываем это событие в БД как опубликованный пост
            database.record_published_post(None, text, None, config.DEFAULT_CHANNEL)
            print("📢 Авто-опрос опубликован!")
    except Exception as e:
        print(f"❌ Ошибка авто-опроса: {e}")

def process_queue(bot):
    """Функция для планировщика (APScheduler). Проверяет очередь и публикует готовые посты."""
    posts = database.get_ready_posts()
    for post in posts:
        post_id, photo_id, text, document_id, channel_id = post
        target_channel = channel_id if channel_id else config.DEFAULT_CHANNEL
        publish_post_data(bot, post_id, photo_id, text, document_id, target_channel, is_auto=True)

def check_subscriber_drop(bot):
    """Каждые несколько часов сравнивает число подписчиков с прошлым срезом и уведомляет админа о падении."""
    try:
        channels = database.get_all_managed_channels()
        for ch in channels:
            try:
                current = bot.get_chat_member_count(ch)
            except Exception as e:
                print(f"⚠️ Не удалось получить число подписчиков {ch}: {e}")
                continue

            history = database.get_sub_history(ch)
            # history: список (date, count) по возрастанию дат
            prev = history[-2][1] if len(history) >= 2 else None

            # Сохраняем текущий срез
            database.save_sub_count(ch, current)

            if prev is not None and current < prev:
                drop = prev - current
                for admin in getattr(config, 'ADMIN_IDS', []):
                    try:
                        bot.send_message(
                            admin,
                            f"⚠️ <b>Падение подписчиков:</b>\n"
                            f"Канал: {ch}\n"
                            f"Было: {prev}\n"
                            f"Стало: {current}\n"
                            f"Отток: -{drop}",
                            parse_mode='HTML'
                        )
                    except: pass
                print(f"📉 Отток подписчиков в {ch}: -{drop}")
    except Exception as e:
        print(f"❌ Ошибка проверки подписчиков: {e}")
