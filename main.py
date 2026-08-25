import logging
import time
from db import Db
from msg_scheduler import start_scheduler
from tg import bot


class _SuppressBreakPolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Break infinity polling" not in record.getMessage()


logging.getLogger("TeleBot").addFilter(_SuppressBreakPolling())


@bot.message_handler(commands=['start'])
def send_welcome(message):
    tgid_list = Db.get_users_tg_ids()
    if message.chat.id not in tgid_list:
        bot.send_message(message.chat.id, f"Привет {message.chat.first_name}, я бот который будет рассказывать про идиомы! 🤖")
        idiom_text = Db.get_today_idiom()
        bot.send_message(message.chat.id, f'Готов?? Знаю, что да! 🚀\n\nВот первая:')
        bot.send_message(message.chat.id, idiom_text, parse_mode="HTML")
        Db.create_user(message.chat.id, message.chat.first_name, True)
        return
    bot.send_message(message.chat.id, f"Привет, {message.chat.first_name}!")


if __name__ == '__main__':
    scheduler = start_scheduler()
    try:
        print("Bot polling started")
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except KeyboardInterrupt:
                raise
            except Exception:
                print("BOT CRASHED")
                print("Restarting polling in 60 seconds...")
                time.sleep(60)

    except KeyboardInterrupt:
        print("Получен CTRL+C, завершаем работу...")
        bot.stop_polling()
    finally:
        scheduler.shutdown(wait=True)
