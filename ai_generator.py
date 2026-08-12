import config
import re
import requests
from bs4 import BeautifulSoup
from groq import Groq
import database

# Ленивая инициализация Groq-клиента.
# Создаём клиент только при первом реальном запросе, чтобы отсутствие/невалидность
# GROQ_API_KEY не роняло весь бот на импорте (Groq() бросает GroqError при api_key=None).
_client = None

# Текущий провайдер (для статуса в панели).
_last_provider = "none"

def _get_client():
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            return None
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def _last_ai_provider():
    """Последний успешно сработавший провайдер (groq/openrouter/…)."""
    return _last_provider


def chat_completion(messages, **kwargs):
    """
    ЕДИНАЯ точка вызова ИИ с автоматическим переключением провайдера:
      1. Groq (основной), 2. OpenRouter (бесплатные модели, список из env)…
    При 429/ошибке одного провайдера — переключается на следующий.
    Возвращает готовый текст ответа или None, если все провайдеры недоступны.
    """
    global _last_provider

    # --- 1) Groq ---
    if config.GROQ_API_KEY:
        cli = _get_client()
        if cli is not None:
            try:
                res = cli.chat.completions.create(messages=messages, model=MODEL_ID, **kwargs)
                text = res.choices[0].message.content.strip()
                _last_provider = "groq"
                return text
            except Exception as e:
                print(f"⚠️ Groq ошибка: {e}")
                # Продолжаем на следующем провайдере.

    # --- 2) OpenRouter (бесплатные модели) ---
    if getattr(config, 'OPENROUTER_API_KEY', ''):
        try:
            model = kwargs.pop('model', None)
            text = _openrouter_completion(messages, model=model, **kwargs)
            if text is not None:
                _last_provider = "openrouter"
                return text
        except Exception as e:
            print(f"⚠️ OpenRouter ошибка: {e}")

    _last_provider = "none"
    return None


def _openrouter_completion(messages, **kwargs):
    """Запрос к OpenRouter: перебирает бесплатные модели по очереди.
    Возвращает текст первого успешного ответа или None."""
    key = config.OPENROUTER_API_KEY
    if not key:
        return None
    models = list(getattr(config, 'OPENROUTER_MODELS', []) or [])
    if kwargs.get('model'):
        models = [kwargs['model']] + models
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {"messages": messages}
    for k in ('temperature', 'max_tokens', 'top_p'):
        if k in kwargs:
            body[k] = kwargs[k]
    for model in models:
        try:
            body['model'] = model
            r = requests.post(url, json=body, headers=headers, timeout=60)
            if r.status_code == 200:
                data = r.json()
                return data['choices'][0]['message']['content'].strip()
            print(f"⚠️ OpenRouter {model}: HTTP {r.status_code} — {r.text[:200]}")
        except Exception as e:
            print(f"⚠️ OpenRouter {model}: {e}")
    return None

# Промпт-инструкция для ИИ. Определяет роль, стиль и структуру поста.
PROMPT_TEMPLATE = """
Sen Minecraft modlari bo‘yicha professional Telegram kontent muharririsan.

Vazifa:
Foydalanuvchi bergan mod, mapa, shader, addon yoki texture haqida qisqa, qiziqarli va maksimal darajada jalb qiluvchi Telegram post yarat.

Maqsad:
- Post qisqa bo‘lsin
- Vizual jihatdan chiroyli bo‘lsin
- Emoji bilan boyitilsin
- Ma’lumotga boy bo‘lsin
- Auditoriyani reaksiyaga undasin
- Postga mos hashtaglar avtomatik tanlansin

Mavjud hashtaglar bazasi:
#Mods #Maps #Textures #Shaders #Addons #Mobs #Biomes #Structures #Survival #Magic #Armor #Tools #Furniture #Redstone #Utility #Building #Horror #Adventure #FPS #UI #Guns #Vehicles
#Multiplayer #Singleplayer #Custom #Vanilla #Fun #Realistic #Fantasy #SciFi #Historical #Nature #City #Space #Underwater #Animals #Tech #Combat #Farming #Roleplay #MiniGames

Qoidalar:
1. Faqat postga mos 3–5 ta hashtag tanla
2. Har doim #Minecraft qo‘sh
3. Tavsif emotsional va hype uslubida yozilsin
4. Har bir asosiy imkoniyat alohida punktda bo‘lsin
5. Post professional Telegram kanal formatida bo‘lsin
6. HTML formatlashni saqla
7. CTA (auditoriya reaksiyasi) bo‘lishi shart
8. Yakunda obuna chaqiruvi bo‘lsin

Format:

📦 <b>[Mod/Karta nomi]</b>

<blockquote expandable><b>Nima bu? ✨</b>
[Qisqa, hayajonli, emojilarga boy tavsif]

<b>Asosiy imkoniyatlar: 🛠</b>
• [Feature 1 🔥]
• [Feature 2 💎]
• [Feature 3 🚀]</blockquote>

<blockquote>Sizga yoqdimi? 😎
🔥 — Albatta!
🌚 — Shunchaki...</blockquote>

#Minecraft #[MosXeshteg1] #[MosXeshteg2] #[MosXeshteg3]

💎 Obuna bo‘ling: @lazikomods

Qo‘shimcha:
- Agar mod juda mashhur bo‘lsa, hype darajasini oshir
- Agar mapa bo‘lsa, exploration urg‘usini kuchaytir
- Agar shader/texture bo‘lsa, grafika va vizual sifatga e’tibor ber
- Agar addon bo‘lsa, gameplay o‘zgarishlarini urg‘ula
- Har safar original va takrorlanmaydigan uslub yarat
"""

# Основная модель Groq (первичного провайдера).
MODEL_ID = "llama-3.3-70b-versatile"

def get_memory_context(limit=10):
    """
    Собирает ручные заметки админа из таблицы ai_memory (память ИИ).
    Возвращает пустую строку, если заметок нет, чтобы не менять поведение.
    """
    try:
        notes = database.get_memory_notes()
    except Exception:
        return ""
    if not notes:
        return ""
    lines = [f"- {n[1]}" for n in notes[:limit]]
    return "ADMIN MEMORY (important notes from the channel admin, always respect them):\n" + "\n".join(lines) + "\n\n"

def extract_url(text):
    """Извлекает первую найденную URL-ссылку из текста."""
    urls = re.findall(r'(https?://[^\s]+)', text)
    return urls[0] if urls else None

def fetch_page_content(url):
    """Загружает содержимое страницы по ссылке и очищает его от скриптов/стилей для передачи в ИИ."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        # Удаляем лишние теги, которые не несут смысловой нагрузки для описания мода
        for s in soup(["script", "style"]): s.extract()
        return soup.get_text(separator=' ', strip=True)[:3000]
    except: return ""

def limit_hashtags(text, limit=5):
    """
    Очищает текст от избыточного количества хэштегов.
    Оставляет максимум 5 уникальных тегов, где #Minecraft всегда первый.
    """
    lines = text.strip().split('\n')
    main_body = []
    hashtags = []
    
    hashtag_pattern = re.compile(r'#\w+')
    
    for line in lines:
        found_in_line = hashtag_pattern.findall(line)
        # Если строка состоит только из хэштегов, собираем их в список
        if found_in_line and len(line.strip().replace(' ', '')) == sum(len(h) for h in found_in_line):
            for h in found_in_line:
                if h not in hashtags:
                    hashtags.append(h)
        else:
            main_body.append(line)

    # Если хэштеги были вплетены в текст, а не в конце, извлекаем их
    if not hashtags:
        all_tags = hashtag_pattern.findall(text)
        for h in all_tags:
            if h not in hashtags:
                hashtags.append(h)

    # Формируем финальный список: #Minecraft + остальные до лимита
    final_tags = []
    if '#Minecraft' in hashtags:
        final_tags.append('#Minecraft')
        hashtags.remove('#Minecraft')
    
    final_tags.extend(hashtags[:limit - len(final_tags)])
    
    # Очищаем основной текст от хэштегов в самом конце
    clean_body = "\n".join(main_body).strip()
    clean_body = re.sub(r'(#\w+\s*)+$', '', clean_body).strip()
    
    return clean_body + "\n\n" + " ".join(final_tags)

import mod_parser

def generate_post(user_input, persona="uz"):
    """Основная функция генерации поста через Groq API."""

    url = extract_url(user_input)
    site_content = fetch_page_content(url) if url else ""
    
    # --- ИНТЕЛЛЕКТУАЛЬНЫЙ ПАРСИНГ ---
    mod_metadata = ""
    if url:
        meta = mod_parser.parse_mod_data(url)
        if meta:
            mod_metadata = f"\nVERIFIED MOD DATA ({meta['source']}):\nTitle: {meta['title']}\nDescription: {meta['summary']}\nVersion: {meta['version']}\nDownloads: {meta['downloads']}\n"

    # Получаем промпт из БД
    db_prompt = database.get_active_prompt()
    effective_prompt_template = db_prompt[0] if db_prompt and db_prompt[0] else PROMPT_TEMPLATE

    # Определяем язык вывода
    lang_map = {
        'uz': "O'zbek tilida (Uzbek)",
        'ru': "на русском языке (Russian)",
        'en': "in English"
    }
    target_lang = lang_map.get(persona, "O'zbek tilida")

    # Формируем полный промпт
    memory = get_memory_context()
    prompt = f"TASK: Write a Minecraft mod post strictly {target_lang}.\n\n{memory}{effective_prompt_template}\n\nDATA TO PROCESS:\n{user_input}\n{mod_metadata}\n{site_content}\n\nREMINDER: Use the VERIFIED MOD DATA if available. The entire post must be {target_lang}."
    
    if not config.GROQ_API_KEY and not getattr(config, 'OPENROUTER_API_KEY', ''):
        print("⚠️ generate_post: no AI providers configured.")
        return None

    try:
        gen = chat_completion([{"role": "user", "content": prompt}])
        if not gen:
            return None
        gen = gen.strip()
        
        # Приводим упоминание канала к актуальному хэндлу (из env CHANNELS)
        gen = gen.replace('@Lazikomods', config.DEFAULT_CHANNEL).replace('@lazikomods', config.DEFAULT_CHANNEL)
        
        # Добавляем рекламную подпись ПЕРЕД обработкой хэштегов, чтобы все чистилось вместе
        ad_text = database.get_global_setting('ad_text', '')
        if ad_text and ad_text not in gen:
            gen += f"\n\n{ad_text}"
            
        # Пост-обработка хэштегов (лимитирование)
        gen = limit_hashtags(gen)
        
        # Финальная очистка: удаляем лишние пробелы в концах строк и ограничиваем пустые строки
        lines = [line.strip() for line in gen.split('\n')]
        # Убираем полностью пустые строки, которые могли возникнуть из-за strip(),
        # но сохраняем структуру (макс 1 пустая строка между блоками текста)
        new_lines = []
        for line in lines:
            if line:
                new_lines.append(line)
            elif new_lines and new_lines[-1] != "":
                new_lines.append("")
        
        gen = '\n'.join(new_lines).strip()
        # Гарантируем, что нет более 2 переносов строк подряд
        gen = re.sub(r'\n{3,}', '\n\n', gen)
            
        return gen
    except Exception as e:
        print(f"Ошибка генерации поста: {e}")
        return None


def translate_post(text, target_persona="uz"):
    """Переводит готовый пост на другой язык, сохраняя всю HTML разметку и эмодзи."""
    if not config.GROQ_API_KEY and not getattr(config, 'OPENROUTER_API_KEY', ''):
        return None
    try:
        lang_map = {
            'uz': "O'zbek tili (Uzbek)",
            'ru': "Русский язык (Russian)",
            'en': "English"
        }
        target_lang = lang_map.get(target_persona, "English")
        
        prompt = f"Translate this Telegram post strictly to {target_lang}. Keep all HTML tags like <b>, <blockquote>, <blockquote expandable> exactly as they are. Do not remove any emojis.\n\n{get_memory_context()}\nText to translate:\n\n{text}"
        
        gen = chat_completion([{"role": "user", "content": prompt}])
        if not gen:
            return None
        return gen.strip().replace('@Lazikomods', config.DEFAULT_CHANNEL).replace('@lazikomods', config.DEFAULT_CHANNEL)
    except Exception as e:
        print(f"Ошибка перевода: {e}")
        return None

def generate_reply(comment_text, persona="uz"):
    """Генерирует живой, человечный ответ на комментарий пользователя."""
    if not config.GROQ_API_KEY and not getattr(config, 'OPENROUTER_API_KEY', ''):
        return None
    try:
        # Инструкции для разных языков, чтобы сохранить "вайб"
        personality = {
            'uz': "Siz Minecraft fanatisiz va @Lazikomods kanalida moderatormiz. Juda do'stona, samimiy va qisqa javob bering. 'Imba', 'Gap yo'q', 'Zo'r' kabi so'zlarni ishlating. Robotdek gapirmang.",
            'ru': "Ты — фанат Майнкрафта и модератор канала @Lazikomods. Отвечай как живой человек: используй сленг (имба, годно, топ, чекай), будь на позитиве. Никакого официоза и фраз типа 'чем я могу вам помочь'.",
            'en': "You are a Minecraft fan and moderator of @Lazikomods. Reply like a real human: use slang (cool, sick, OP, lit), be energetic and very brief. Don't sound like a robot or a support agent."
        }

        selected_personality = personality.get(persona, personality['uz'])
        lang_map = {'uz': "O'zbek tilida", 'ru': "на русском языке", 'en': "in English"}
        target_lang = lang_map.get(persona, "O'zbek tilida")

        prompt = f"""
        {selected_personality}
        {get_memory_context()}
        Foydalanuvchi yozdi: "{comment_text}"

        Vazifa: Ushbu xabarga {target_lang} qisqa (1 ta gap) javob ber. 
        Agar rahmat aytsa — xursand bo'l. Agar savol so'rasa — do'stona javob ber.
        Faqat matn, xeshteglar kerak emas.
        """

        res = chat_completion([{"role": "user", "content": prompt}], temperature=0.7)
        if not res:
            return None
        return res.strip().replace('"', '')
    except Exception as e:
        print(f"Ошибка ответа на комментарий: {e}")
        return None

def generate_suggestion_request(persona="uz"):
    """Генерирует пост с запросом предложений от подписчиков."""
    if not config.GROQ_API_KEY and not getattr(config, 'OPENROUTER_API_KEY', ''):
        return None
    try:
        lang_map = {'uz': "O'zbek tilida", 'ru': "на русском языке", 'en': "in English"}
        target_lang = lang_map.get(persona, "O'zbek tilida")

        prompt = f"""
        {get_memory_context()}
        Minecraft kanali uchun qisqa va qiziqarli post yoz. 
        Maqsad: Obunachilardan qanday modlar, karta yoki teksturalar ko'rishni xohlashlarini so'rash.
        Stil: Do'stona, emojilarga boy.
        Til: {target_lang}.
        Post oxirida obunachilarni kommentariyada yozishga unda.
        HTML teglaridan foydalan (<b>, <i>).
        """

        res = chat_completion([{"role": "user", "content": prompt}])
        if not res:
            return None
        return res.strip()
    except Exception as e:
        print(f"Ошибка генерации опроса: {e}")
        return None

def rewrite_post(text, style="short", persona="uz"):
    """Переписывает готовый пост в выбранном стиле (short/long/funny/pro)."""
    if not config.GROQ_API_KEY and not getattr(config, 'OPENROUTER_API_KEY', ''):
        return None
    try:
        style_map = {
            'short': 'very short and punchy, keep only the key info (3-5 lines), still with a CTA',
            'long': 'detailed and comprehensive, expand every feature into its own point',
            'funny': 'funny, hype, casual and meme-like tone, keep it engaging',
            'pro': 'professional, clean, structured marketing tone'
        }
        lang_map = {'uz': "O'zbek tilida", 'ru': "на русском языке", 'en': "in English"}
        target_lang = lang_map.get(persona, "O'zbek tilida")

        prompt = f"""
Rewrite the Telegram post below {target_lang}.
Style: {style_map.get(style, style_map['short'])}.
Keep all HTML tags (<b>, <blockquote>, <blockquote expandable>) and emojis.
Keep the same hashtags structure. Do not add a signature.
{get_memory_context()}
Post:
{text}
"""
        res = chat_completion([{"role": "user", "content": prompt}])
        if not res:
            return None
        return res.strip().replace('@Lazikomods', config.DEFAULT_CHANNEL).replace('@lazikomods', config.DEFAULT_CHANNEL)
    except Exception as e:
        print(f"Ошибка рерайта: {e}")
        return None

def improve_prompt(description):
    """Улучшает пользовательское описание до полноценного system-промпта для ИИ."""
    if not config.GROQ_API_KEY and not getattr(config, 'OPENROUTER_API_KEY', ''):
        return description
    try:
        prompt = f"""
You are an expert prompt engineer. A Telegram content bot about Minecraft mods lets the admin define an AI "persona" (system prompt). 
Turn the short description below into a detailed, ready-to-use system prompt. 
Rules: write in the same language as the description, keep it structured (role, goal, style, format rules), use bullet points. 
Do NOT add any commentary outside the prompt itself.

Description: "{description}"
"""
        res = chat_completion([{"role": "user", "content": prompt}])
        if not res:
            return description
        return res.strip()
    except Exception as e:
        print(f"Ошибка улучшения промпта: {e}")
        return description
