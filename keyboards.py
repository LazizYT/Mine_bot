from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import config
import database
import strings

def get_main_menu(lang='uz'):
    btns = strings.BUTTONS.get(lang, strings.BUTTONS['uz'])
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton(btns['create']))
    markup.add(KeyboardButton(btns['lang']))
    return markup

def get_cancel_markup(lang='uz'):
    btns = strings.BUTTONS.get(lang, strings.BUTTONS['uz'])
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton(btns['cancel']))
    return markup

def get_resume_markup(lang='uz'):
    btns = strings.BUTTONS.get(lang, strings.BUTTONS['uz'])
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("↩️ " + btns.get('resume_draft', 'Resume draft'), callback_data="resume_draft"))
    return markup

def get_channel_select_menu(target_id, channels, action_type="pub"):
    """
    Клавиатура для выбора канала.
    action_type может быть 'pub' (опубликовать сейчас) или 'sq' (смарт-очередь), 'sched' (интервал).
    """
    markup = InlineKeyboardMarkup()
    for ch in channels:
        markup.add(InlineKeyboardButton(ch, callback_data=f"sel_{action_type}_{ch}"))
    
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_draft"))
    return markup

def get_draft_markup(target_id, lang='uz'):
    btns = strings.BUTTONS.get(lang, strings.BUTTONS['uz'])
    markup = InlineKeyboardMarkup(row_width=2)
    
    smart_label = btns['smart_queue']
    interval = database.get_global_setting('smart_queue_interval', '6')
    
    markup.add(
        InlineKeyboardButton(f"{smart_label} (+{interval} h)", callback_data="add_to_smart_q")
    )
    markup.add(
        InlineKeyboardButton(btns['now'], callback_data="pub_now"),
        InlineKeyboardButton(btns['later'], callback_data="pub_queue_menu")
    )
    markup.add(
        InlineKeyboardButton(btns['edit'], callback_data="edit_text"),
        InlineKeyboardButton(btns['rewrite'], callback_data="rewrite_menu")
    )
    markup.add(
        InlineKeyboardButton(btns['translate'], callback_data="translate_menu"),
        InlineKeyboardButton(btns['delete'], callback_data="cancel_action")
    )
    return markup

def get_translate_menu(target_id):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data=f"tr_uz"),
        InlineKeyboardButton("🇷🇺 Русский", callback_data=f"tr_ru"),
        InlineKeyboardButton("🇺🇸 English", callback_data=f"tr_en"),
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_draft")
    )
    return markup

def get_language_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="set_lang_uz"),
        InlineKeyboardButton("🇷🇺 Русский", callback_data="set_lang_ru"),
        InlineKeyboardButton("🇺🇸 English", callback_data="set_lang_en")
    )
    return markup

def get_queue_menu(target_id, lang='uz'):
    btns = strings.BUTTONS.get(lang, strings.BUTTONS['uz'])
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("2h", callback_data=f"sched_i_2"), 
        InlineKeyboardButton("6h", callback_data=f"sched_i_6")
    )
    markup.add(
        InlineKeyboardButton(btns['exact'], callback_data=f"sched_exact"), 
        InlineKeyboardButton(btns['back'], callback_data="back_to_draft")
    )
    return markup

def get_rewrite_menu(target_id, lang='uz'):
    btns = strings.BUTTONS.get(lang, strings.BUTTONS['uz'])
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(btns['short'], callback_data=f"rewrite_short"), 
        InlineKeyboardButton(btns['long'], callback_data=f"rewrite_long"),
    )
    markup.add(
        InlineKeyboardButton(btns['funny'], callback_data=f"rewrite_funny"), 
        InlineKeyboardButton(btns['pro'], callback_data=f"rewrite_pro"),
    )
    markup.add(InlineKeyboardButton(btns['back'], callback_data="back_to_draft"))
    return markup
