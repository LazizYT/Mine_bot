import config
import database
import ai_generator

MODEL_ID = "llama-3.3-70b-versatile"

def analyze_comments():
    """Собирает последние комментарии из БД и просит Groq/OpenRouter сделать выжимку."""
    if not (config.GROQ_API_KEY or getattr(config, 'OPENROUTER_API_KEY', '')):
        return "❌ ИИ не настроен (GROQ_API_KEY / OPENROUTER_API_KEY) — анализ комментариев недоступен."

    comments = database.get_all_comments()

    if not comments:
        return "📭 Пока нет новых комментариев от подписчиков."

    # Ограничиваем объём: берём только последние 200 комментариев,
    # чтобы не превысить контекст модели.
    comments = comments[-200:]

    # Собираем все комментарии в один текст
    comments_text = "\n".join([f"- {c[0]}: {c[1]}" for c in comments])

    # Инструкция для ИИ
    prompt = f"""
    Ты — аналитик Telegram-канала о модах Minecraft.
    {ai_generator.get_memory_context()}
    Ниже приведены сообщения из чата. 
    ВАЖНО: В списке могут быть как комментарии пользователей, так и описания модов от самого канала.
    Твоя задача: 
    1. ИГНОРИРУЙ любые описания модов (длинные тексты с пунктами, хештегами и т.д.).
    2. ФОКУСИРУЙСЯ только на реальных запросах пользователей (например: "нужен мод на машины", "сделайте карту города", "спасибо за мод").
    3. Сгруппируй пожелания и укажи количество просящих.

    Формат ответа (используй эмодзи):
    💡 Конкретные запросы (моды/карты/шейдеры):
    - [Суть запроса] (X человек)
    
    💬 Общая обратная связь и благодарности:
    - ...

    ⚠️ Жалобы (если есть):
    - ...

    Сообщения для анализа:
    {comments_text}
    """

    try:
        text = ai_generator.chat_completion([{"role": "user", "content": prompt}])
        if not text:
            return "❌ ИИ не смог проанализировать комментарии."
        return text.strip()
    except Exception as e:
        print(f"Ошибка ИИ при анализе: {e}")
        return "❌ Произошла ошибка при анализе комментариев."
