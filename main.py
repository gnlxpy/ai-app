from enum import Enum
from functools import wraps
import logging
from typing import Any, Callable
from db import Db
from msg_idioms_list import gen_msg_word_idioms
from msg_scheduler import start_scheduler
from msg_word import gen_msg_word
from tg import bot
from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
import redis
import time
from config import settings


redis_client = redis.Redis(host=settings.REDIS_HOST, password=settings.REDIS_PSW, port=6379, db=3, decode_responses=True, ssl=False)
class _SuppressBreakPolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Break infinity polling" not in record.getMessage()


logging.getLogger("TeleBot").addFilter(_SuppressBreakPolling())


class BotAction(str, Enum):
    """Действия, доступные под инлайн-кнопками бота."""
 
    WORD_SHOW_IDIOMS = "word:idioms"  # кнопка "Idioms with the word" на карточке слова


def is_rate_limited(
    user_id: int,
    max_requests: int = 3,
    window_seconds: int = 60,
) -> bool:
    """Проверяет, превысил ли пользователь лимит запросов (sliding window log).

    :param user_id: Telegram ID пользователя.
    :param max_requests: Максимум запросов за окно.
    :param window_seconds: Ширина окна в секундах.
    :return: True, если лимит превышен и запрос нужно отклонить.
    """
    key = f"spam:{user_id}"
    now = time.time()
    window_start = now - window_seconds

    # Шаг 1: чистим устаревшее и считаем текущее количество — БЕЗ добавления нового
    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    _, request_count = pipe.execute()

    if request_count >= max_requests:
        return True  # лимит превышен, новый запрос НЕ добавляем в окно

    # Шаг 2: лимит не превышен — регистрируем текущий запрос
    pipe = redis_client.pipeline()
    pipe.zadd(key, {f"{now}:{user_id}": now})  # уникальный member, чтобы избежать коллизий
    pipe.expire(key, window_seconds)
    pipe.execute()

    return False


def build_word_keyboard(word: str | None | bool) -> InlineKeyboardMarkup | None:
    """Собирает инлайн-клавиатуру для карточки слова — одна кнопка "Idioms with the word".
 
    :param word: Слово из карточки — кладётся в callback_data как есть
        (Ch.get_idioms(word) принимает текст слова, а не id).
    :return: Готовая разметка InlineKeyboardMarkup.
    """
    if not word:
        return None
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            text="Idioms with the word",
            callback_data=f"{BotAction.WORD_SHOW_IDIOMS.value}:{word}",
        ),
    )
    return markup


def rate_limit(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Декоратор для message/callback-хендлеров, ограничивающий частоту вызова на пользователя.
 
    Работает и с Message, и с CallbackQuery — у обоих есть .from_user.
 
    :param handler: Оборачиваемый хендлер.
    :return: Обёрнутая функция с проверкой rate-limit перед вызовом оригинала.
    """
 
    @wraps(handler)
    def wrapper(update: Message | CallbackQuery, *args: Any, **kwargs: Any) -> Any:
        user_id = update.from_user.id
        chat_id = update.chat.id if isinstance(update, Message) else update.message.chat.id
 
        if is_rate_limited(user_id, settings.RATE_LIMIT_MAX_REQUESTS, settings.RATE_LIMIT_WINDOW_SECONDS):
            print(f"Rate limit: user_id={user_id} превысил {settings.RATE_LIMIT_MAX_REQUESTS}/{settings.RATE_LIMIT_WINDOW_SECONDS}с")
            if isinstance(update, CallbackQuery):
                bot.answer_callback_query(update.id, text="⏳ Слишком много запросов, подожди немного", show_alert=True)
            else:
                bot.send_message(chat_id, "⏳ Слишком много запросов, подожди немного")
            return None
 
        return handler(update, *args, **kwargs)
 
    return wrapper


@bot.message_handler(commands=['start'])
@rate_limit
def send_welcome(message: Message):
    bot.send_message(message.chat.id, f"Привет {message.chat.first_name}, я бот который будет рассказывать про английские идиомы! 🤖")
    time.sleep(5)
    last_idiom = Db.get_idioms_history()
    if not last_idiom:
        return
    bot.send_message(message.chat.id, f'Готов?? Знаю, что да! 🚀\n\nВот первая:\n')
    time.sleep(2)
    bot.send_message(message.chat.id, last_idiom['message'], parse_mode="HTML")
    time.sleep(5)
    bot.send_message(message.chat.id, f'А еще я могу находить значения слов и идиомы по ним в оксфордском словаре, просто отправь слово и получи подробную информацию 🤓')
    Db.create_user(str(message.chat.id), message.chat.first_name, True)
    print(f'New user add to db: {message.chat.id}')
    return


@bot.message_handler(regexp='^[a-zA-Z]{1,15}$')
@rate_limit
def send_msg_word(message: Message):
    idiom_button_word = None
    history_word = Db.get_words_history(message.text)
    if history_word:
        if history_word['idiom_button']:
            idiom_button_word = message.text
        bot.send_message(
            chat_id=message.chat.id,
            text=history_word['message'],
            parse_mode="HTML",
            reply_markup=build_word_keyboard(idiom_button_word)
        )
        return

    check_word = Db.check_word(message.text)
    if not check_word:
        bot.send_message(message.chat.id, "Такого слова еще нет...")
        return
    bot.send_message(message.chat.id, "Ищу...")
    rendered_post, idiom_button = gen_msg_word(message.text)
    if idiom_button:
        idiom_button_word = message.text
    if not rendered_post:
        bot.send_message(message.chat.id, "Произошла ошибка Х_Х")
        return
    bot.send_message(
        chat_id=message.chat.id,
        text=rendered_post,
        parse_mode="HTML",
        reply_markup=build_word_keyboard(idiom_button_word)
    )
    Db.insert_words_history(message.text, rendered_post, True if idiom_button else False)


@bot.callback_query_handler(func=lambda call: call.data.startswith(BotAction.WORD_SHOW_IDIOMS.value))
@rate_limit
def handle_word_idioms_callback(call: CallbackQuery) -> None:
    """Обрабатывает нажатие кнопки "Idioms with the word" — присылает 5 идиом с примерами.
 
    :param call: Объект callback-запроса от Telegram.
    :return: None.
    """
    _, word = call.data.rsplit(":", 1)
    msg = gen_msg_word_idioms(word)
    bot.send_message(call.message.chat.id, msg, parse_mode="HTML")


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
