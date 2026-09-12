import traceback
from db import Db
import telebot
from config import settings


bot = telebot.TeleBot(settings.TELEGRAM_TOKEN, threaded=True, num_threads=4)


def send_tg_msg(tg_id: int | str, msg: str) -> bool:
    """Отправка сообщения пользователю"""
    try:
        bot.send_message(
            tg_id,
            msg,
            parse_mode="HTML"
        )
        return True
    
    except Exception as e:
        if 'blocked by the user' in e.description:
            Db.update_user_status(tg_id, False)
        traceback.print_exc()
        return False


def send_tg_msg_to_all(msg: str, users_ids: list):
    try:
        for user in users_ids:
            send_tg_msg(user, msg)

        return True
    except Exception:
        traceback.print_exc()
        return False
