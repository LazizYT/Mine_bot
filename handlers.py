import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import threading
import time
import pytz
import html
import re
from datetime import datetime, timedelta

import config
import database
import ai_generator
import watermarker
import keyboards
import publisher
import scheduler_engine
import strings
from bot_instance import bot

# Глобальные словари для хранения текущего состояния пользователей
user_current_draft_id = {} 
user_states = {} 

def get_user_lang(user_id):
    return database.get_user_setting(user_id, 'persona', 'uz')

def get_txt(user_id, key, **kwargs):
    lang = get_user_lang(user_id)
    text = strings.MESSAGES.get(lang, strings.MESSAGES['uz']).get(key, key)
    return text.format(**kwargs)

def ensure_html_tags(text):
    if '<b>' not in text:
        lines = text.split('\n')
        if lines:
            lines[0] = f"📦 <b>{lines[0].replace('📦', '').strip()}</b>"
            text = '\n'.join(lines)
    if '<blockquote' not in text:
        lines = text.split('\n')
        if len(lines) > 3:
            end_idx = len(lines)
            for i, line in enumerate(lines):
                if '#' in line or '?' in line:
                    end_idx = i
                    break
            middle = '\n'.join(lines[1:end_idx]).strip()
            if middle:
                return lines[0] + "\n\n<blockquote expandable>" + middle + "</blockquote>\n\n" + '\n'.join(lines[end_idx:])
    return text

def _channel_id_by_username(username):
    """Числовой id канала из managed_channels (или создаёт)."""
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM managed_channels WHERE username = ?", (username,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO managed_channels (username) VALUES (?)", (username,))
        cid = cur.lastrowid
        conn.commit()
    else:
        cid = row[0]
    conn.close()
    return cid

def _add_to_queue_integrated(photo, text, document, channel, scheduled_time=None):
    """
    Интеграция Smart Queue -> Content Storage (Фаза 4):
    сохраняет пост в storage, затем создаёт запись в очереди.
    """
    lang = database.get_user_setting(config.ADMIN_IDS[0], 'persona', 'uz')
    media_type = 'album' if photo and ',' in photo else ('photo' if photo else ('document' if document else 'text'))
    # document хранится через запятую — кладём как есть
    cid = _channel_id_by_username(channel)
    scheduler_engine.add_to_storage_and_queue(
        text=text, media=photo or "", media_type=media_type,
        channel_id=cid, channel_username=channel,
        scheduled_time=scheduled_time, language=lang, source='telegram')

def register_handlers(bot_instance, user_drafts, album_cache):
    """Регистрация всех обработчиков."""

    @bot.message_handler(commands=['start'])
    def handle_start(message):
        user_id = message.from_user.id
        if not database.get_user_setting(user_id, 'persona'):
            database.update_user_setting(user_id, 'persona', 'uz')
        
        lang = get_user_lang(user_id)
        # ИСПРАВЛЕНИЕ: Web App кнопки только в ЛС (Private Chat)
        markup = keyboards.get_main_menu(lang) if message.chat.type == 'private' else None
        
        bot.send_message(
            message.chat.id, 
            get_txt(user_id, 'welcome'),
            parse_mode='HTML', 
            reply_markup=markup
        )

    @bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'])
    def handle_group_message(message):
        """Обработка комментариев в группах."""
        # Игнорируем сообщения от других ботов
        if message.from_user and message.from_user.is_bot: return
        
        # ИСПРАВЛЕНИЕ: Игнорируем ТОЛЬКО автоматические репосты из канала.
        # Если админ пишет от имени канала или просто пользователь комментирует — слушаем.
        if hasattr(message, 'is_automatic_forward') and message.is_automatic_forward: return
        
        if not message.text: return
        
        # Сохраняем для анализа
        user_name = message.from_user.first_name if message.from_user else "User"
        database.save_comment(user_name, message.text, int(time.time()))
        
        # Генерируем живой ответ
        admin_lang = database.get_user_setting(config.ADMIN_IDS[0], 'persona', 'uz')
        reply_text = ai_generator.generate_reply(message.text, admin_lang)
        
        if reply_text:
            try: bot.reply_to(message, reply_text)
            except: pass

    @bot.message_handler(content_types=['text', 'photo'])
    def handle_text_photo(message):
        # Обрабатываем только в личке, чтобы не мешать комментариям
        if message.chat.type != 'private': return
        
        user_id = message.from_user.id
        lang = get_user_lang(user_id)
        btns = strings.BUTTONS.get(lang, strings.BUTTONS['uz'])
        
        if user_states.get(user_id) == "EDITING":
            target_id = user_current_draft_id.get(user_id)
            if target_id and target_id in user_drafts:
                user_drafts[target_id]['text'] = ensure_html_tags(message.text)
                user_states[user_id] = None
                bot.send_message(message.chat.id, get_txt(user_id, 'text_updated'), reply_markup=keyboards.get_main_menu(lang))
                send_draft_preview(message.chat.id, user_id, user_drafts[target_id])
            return

        if user_states.get(user_id) == "SETTING_TIME":
            target_id = user_current_draft_id.get(user_id)
            if target_id and target_id in user_drafts:
                time_match = re.search(r'(\d{1,2})\.(\d{1,2})\s+(\d{1,2})[:\-\s](\d{1,2})', message.text)
                if time_match:
                    day, month, hour, minute = map(int, time_match.groups())
                    tz = pytz.timezone('Asia/Tashkent')
                    dt = tz.localize(datetime(datetime.now().year, month, day, hour, minute))
                    if dt.timestamp() < time.time(): dt = dt.replace(year=dt.year + 1)
                    
                    draft = user_drafts[target_id]
                    _add_to_queue_integrated(draft.get('photo'), draft.get('text'), draft.get('document'),
                                             draft.get('channel', config.DEFAULT_CHANNEL), int(dt.timestamp()))
                    user_states[user_id] = None
                    bot.delete_message(message.chat.id, target_id)
                    bot.send_message(message.chat.id, get_txt(user_id, 'scheduled', time=dt.strftime('%d.%m %H:%M')), reply_markup=keyboards.get_main_menu(lang))
                else:
                    bot.send_message(message.chat.id, get_txt(user_id, 'enter_time'), parse_mode='HTML')
            return

        if message.text == btns['create']:
            saved = database.get_user_draft(user_id)
            if saved:
                markup = keyboards.get_resume_markup(lang)
            else:
                markup = keyboards.get_cancel_markup(lang)
            bot.send_message(message.chat.id, get_txt(user_id, 'choose_action'), reply_markup=markup)
            return
        if message.text == btns['lang']:
            bot.send_message(message.chat.id, get_txt(user_id, 'choose_lang'), reply_markup=keyboards.get_language_menu())
            return
        if message.text == btns['cancel']:
            user_states[user_id] = None
            bot.send_message(message.chat.id, get_txt(user_id, 'cancel_msg'), reply_markup=keyboards.get_main_menu(lang))
            return

        if message.media_group_id:
            if message.media_group_id not in album_cache:
                album_cache[message.media_group_id] = []
                bot.send_message(message.chat.id, get_txt(user_id, 'album_loading'))
                threading.Timer(2.0, process_album, args=[message.media_group_id, message.chat.id, message.from_user.id]).start()
            album_cache[message.media_group_id].append(message)
            return
        
        process_single_message(message)

    def process_single_message(message):
        user_id = message.from_user.id
        lang = get_user_lang(user_id)
        temp_in, temp_out = f"in_{message.message_id}.jpg", f"out_{message.message_id}.jpg"
        status_msg = bot.send_message(message.chat.id, get_txt(user_id, 'generation_start'), parse_mode='HTML')
        try:
            bot.send_chat_action(message.chat.id, 'upload_photo')
            user_input = message.caption or message.text or "Minecraft mod photo"
            generated_text = ai_generator.generate_post(user_input, lang)
            if not generated_text:
                bot.edit_message_text("❌ Ошибка ИИ при генерации поста. Попробуйте ещё раз.", message.chat.id, status_msg.message_id)
                return
            photo_id = None
            if message.photo:
                bot.edit_message_text(get_txt(user_id, 'processing_photo'), message.chat.id, status_msg.message_id, parse_mode='HTML')
                file_info = bot.get_file(message.photo[-1].file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                with open(temp_in, 'wb') as f: f.write(downloaded_file)
                watermarker.add_watermark(temp_in, temp_out)
                with open(temp_out, 'rb') as f:
                    sent = bot.send_photo(message.chat.id, f)
                    photo_id = sent.photo[-1].file_id
                    bot.delete_message(message.chat.id, sent.message_id) 
            bot.delete_message(message.chat.id, status_msg.message_id)
            draft = {'photo': photo_id, 'text': generated_text, 'document': None, 'channel': database.get_user_setting(user_id, 'active_channel', config.DEFAULT_CHANNEL)}
            send_draft_preview(message.chat.id, user_id, draft)
        except Exception as e: bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status_msg.message_id)
        finally:
            for f in [temp_in, temp_out]: 
                if os.path.exists(f): os.remove(f)

    def send_draft_preview(chat_id, user_id, draft):
        lang = get_user_lang(user_id)
        try:
            if draft['photo']:
                if ',' in draft['photo']:
                    media = [telebot.types.InputMediaPhoto(media=pid) for pid in draft['photo'].split(',')]
                    bot.send_media_group(chat_id, media)
                    sent = bot.send_message(chat_id, draft['text'], parse_mode='HTML')
                else:
                    sent = bot.send_photo(chat_id, draft['photo'], caption=draft['text'], parse_mode='HTML')
            else:
                sent = bot.send_message(chat_id, draft['text'], parse_mode='HTML')
        except: sent = bot.send_message(chat_id, f"⚠️ HTML Error. Raw text:\n\n{draft['text']}")
        
        user_drafts[sent.message_id] = draft
        user_current_draft_id[user_id] = sent.message_id
        database.save_draft(user_id, draft.get('photo'), draft.get('text'), draft.get('document'), draft.get('channel', config.DEFAULT_CHANNEL))
        bot.edit_message_reply_markup(chat_id, sent.message_id, reply_markup=keyboards.get_draft_markup(sent.message_id, lang))

    @bot.message_handler(content_types=['document'])
    def handle_document(message):
        if message.chat.type != 'private': return
        user_id = message.from_user.id
        target_id = user_current_draft_id.get(user_id)
        if target_id and target_id in user_drafts:
            curr = user_drafts[target_id].get('document', '')
            user_drafts[target_id]['document'] = f"{curr},{message.document.file_id}" if curr else message.document.file_id
            bot.reply_to(message, get_txt(user_id, 'file_attached', count=len(user_drafts[target_id]['document'].split(','))), parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: True)
    def callback_handler(call):
        chat_id, target_id, user_id = call.message.chat.id, call.message.message_id, call.from_user.id
        lang = get_user_lang(user_id)
        
        if call.data.startswith("set_lang_"):
            new_lang = call.data.split('_')[2]
            database.update_user_setting(user_id, 'persona', new_lang)
            bot.delete_message(chat_id, target_id)
            bot.send_message(chat_id, get_txt(user_id, 'lang_selected'), parse_mode='HTML', reply_markup=keyboards.get_main_menu(new_lang))
            return

        if call.data == "cancel_action":
            # Удаляем черновик из словаря и из БД
            if target_id in user_drafts:
                del user_drafts[target_id]
            database.delete_draft(user_id)
            
            # Удаляем сообщение с черновиком
            try:
                bot.delete_message(chat_id, target_id)
            except:
                pass
            
            # Отправляем главное меню
            bot.send_message(chat_id, get_txt(user_id, 'cancel_msg'), reply_markup=keyboards.get_main_menu(lang))
            return

        if call.data == "resume_draft":
            saved = database.get_user_draft(user_id)
            if saved:
                send_draft_preview(chat_id, user_id, saved)
                bot.delete_message(chat_id, target_id)
            else:
                bot.answer_callback_query(call.id, get_txt(user_id, 'no_draft'))
            return

        # Навигация
        if call.data == "back_to_draft":
            bot.edit_message_reply_markup(chat_id, target_id, reply_markup=keyboards.get_draft_markup(target_id, lang))
            return

        # Меню выбора каналов
        if call.data == "pub_now":
            channels = database.get_all_managed_channels()
            if not channels: channels = [config.DEFAULT_CHANNEL]
            bot.edit_message_reply_markup(chat_id, target_id, reply_markup=keyboards.get_channel_select_menu(target_id, channels, "pub"))
            return
        
        if call.data == "add_to_smart_q":
            channels = database.get_all_managed_channels()
            if not channels: channels = [config.DEFAULT_CHANNEL]
            bot.edit_message_reply_markup(chat_id, target_id, reply_markup=keyboards.get_channel_select_menu(target_id, channels, "sq"))
            return

        if call.data == "pub_queue_menu":
            bot.edit_message_reply_markup(chat_id, target_id, reply_markup=keyboards.get_queue_menu(target_id, lang))
            return

        if call.data == "sched_exact":
            user_states[user_id] = "SETTING_TIME"
            user_current_draft_id[user_id] = target_id
            bot.send_message(chat_id, get_txt(user_id, 'enter_time'), parse_mode='HTML')
            bot.answer_callback_query(call.id)
            return

        if call.data.startswith("sched_i_"):
            h = int(call.data.split('_')[2])
            channels = database.get_all_managed_channels()
            if not channels: channels = [config.DEFAULT_CHANNEL]
            bot.edit_message_reply_markup(chat_id, target_id, reply_markup=keyboards.get_channel_select_menu(target_id, channels, f"sched{h}"))
            return

        # Финальные действия после выбора канала
        draft = user_drafts.get(target_id)
        if not draft:
            bot.answer_callback_query(call.id, get_txt(user_id, 'err_draft'))
            return

        if call.data.startswith("sel_"):
            parts = call.data.split('_', 2)  # split('_', 2): channel может содержать '_'
            action = parts[1]
            channel = parts[2]
            
            if action == "pub":
                publisher.publish_post_data(bot, -1, draft['photo'], draft['text'], draft['document'], channel)
                database.delete_draft(user_id)
                bot.delete_message(chat_id, target_id)
                bot.send_message(chat_id, get_txt(user_id, 'published'), reply_markup=keyboards.get_main_menu(lang))
            
            elif action == "sq":
                interval = int(database.get_global_setting('smart_queue_interval', 6))
                last_time = database.get_last_scheduled_time() or int(time.time())
                sched_time = max(int(time.time()), last_time) + interval * 3600
                _add_to_queue_integrated(draft['photo'], draft['text'], draft['document'], channel, sched_time)
                database.delete_draft(user_id)
                bot.delete_message(chat_id, target_id)
                bot.send_message(chat_id, get_txt(user_id, 'smart_queue_added'), reply_markup=keyboards.get_main_menu(lang))

            elif action.startswith("sched"):
                h = int(action.replace("sched", ""))
                _add_to_queue_integrated(draft['photo'], draft['text'], draft['document'], channel, int(time.time()) + h*3600)
                database.delete_draft(user_id)
                bot.delete_message(chat_id, target_id)
                bot.send_message(chat_id, get_txt(user_id, 'scheduled', time=f"+{h}h"), reply_markup=keyboards.get_main_menu(lang))
            return

        # Остальные меню
        if call.data == "translate_menu":
            bot.edit_message_reply_markup(chat_id, target_id, reply_markup=keyboards.get_translate_menu(target_id))
        elif call.data.startswith("tr_"):
            t_lang = call.data.split('_')[1]
            bot.answer_callback_query(call.id, get_txt(user_id, 'translating'))
            new_text = ai_generator.translate_post(draft['text'], t_lang)
            if not new_text:
                bot.answer_callback_query(call.id, "❌ Ошибка перевода", show_alert=True)
                return
            draft['text'] = new_text
            send_draft_preview(chat_id, user_id, draft)
            bot.delete_message(chat_id, target_id)
        elif call.data == "edit_text":
            user_states[user_id] = "EDITING"
            bot.send_message(chat_id, get_txt(user_id, 'enter_text'))
        elif call.data == "rewrite_menu":
            bot.edit_message_reply_markup(chat_id, target_id, reply_markup=keyboards.get_rewrite_menu(target_id, lang))
        elif call.data.startswith("rewrite_"):
            style = call.data.split('_')[1]
            bot.answer_callback_query(call.id, get_txt(user_id, 'rewriting'))
            new_text = ai_generator.rewrite_post(draft['text'], style, lang)
            if not new_text:
                bot.answer_callback_query(call.id, "❌ Ошибка рерайта", show_alert=True)
                return
            draft['text'] = new_text
            send_draft_preview(chat_id, user_id, draft)
            bot.delete_message(chat_id, target_id)

    def process_album(media_group_id, chat_id, user_id):
        lang = get_user_lang(user_id)
        msgs = album_cache.get(media_group_id)
        if not msgs: return
        status = bot.send_message(chat_id, get_txt(user_id, 'album_loading'))
        temp_files = []
        try:
            txt = ai_generator.generate_post(next((m.caption for m in msgs if m.caption), "Album"), lang)
            if not txt:
                bot.edit_message_text("❌ Ошибка ИИ при генерации поста.", chat_id, status.message_id)
                return
            p_ids = []
            for i, m in enumerate(msgs):
                bot.edit_message_text(get_txt(user_id, 'album_processing', i=i+1, total=len(msgs)), chat_id, status.message_id)
                f_info = bot.get_file(m.photo[-1].file_id)
                temp_in = f"temp_{media_group_id}_{i}.jpg"
                temp_out = f"out_{media_group_id}_{i}.jpg"
                temp_files += [temp_in, temp_out]
                with open(temp_in, 'wb') as f: f.write(bot.download_file(f_info.file_path))
                watermarker.add_watermark(temp_in, temp_out)
                with open(temp_out, 'rb') as f:
                    s = bot.send_photo(config.LOG_CHANNEL if hasattr(config, 'LOG_CHANNEL') else chat_id, f)
                    p_ids.append(s.photo[-1].file_id)
                    if not hasattr(config, 'LOG_CHANNEL'): bot.delete_message(chat_id, s.message_id)
            bot.delete_message(chat_id, status.message_id)
            send_draft_preview(chat_id, user_id, {'photo': ",".join(p_ids), 'text': txt, 'document': None})
        except Exception as e: bot.edit_message_text(f"❌ Error: {e}", chat_id, status.message_id)
        finally:
            for f in temp_files:
                if os.path.exists(f): os.remove(f)
            if media_group_id in album_cache: del album_cache[media_group_id]
