import telebot
from apscheduler.schedulers.background import BackgroundScheduler
import time
import threading
import config
import database
import publisher
import scheduler_engine
import handlers
import webapp
import userbot
from bot_instance import bot

# Инициализация бота
database.init_db()

# Глобальные кеши
user_drafts = {}
album_cache = {}

# Регистрация всех обработчиков из модуля handlers
handlers.register_handlers(bot, user_drafts, album_cache)

# Настройка планировщика: основной движок автопубликации
scheduler = BackgroundScheduler()
scheduler.add_job(scheduler_engine.run_scheduler, 'interval', minutes=1, args=[bot])
# Автоматический опрос предложений каждые 3 дня
scheduler.add_job(publisher.auto_ask_suggestions, 'interval', days=3, args=[bot])
# Мониторинг оттока подписчиков каждые 6 часов
scheduler.add_job(publisher.check_subscriber_drop, 'interval', hours=6, args=[bot])
# Ретраи упавших публикаций
scheduler.add_job(scheduler_engine.retry_failed, 'interval', minutes=30, args=[bot])
# Ежедневный бэкап БД (хранятся в data/backups, volume переживает рестарты)
scheduler.add_job(database.backup_db, 'cron', hour=3, minute=5)
scheduler.start()

# Юзербот (Pyrogram): перехват постов из каналов-источников
userbot.start()

# Запуск Web Dashboard в отдельном потоке
def start_web():
    webapp.run_server()

if __name__ == "__main__":
    print("Запуск Web Dashboard...")
    threading.Thread(target=start_web, daemon=True).start()
    
    print("Бот Mine Bot запущен и готов к работе!")
    while True:
        try:
            bot.polling(none_stop=True, timeout=90)
        except Exception as e:
            print(f"Ошибка в основном цикле: {e}")
            time.sleep(5)
