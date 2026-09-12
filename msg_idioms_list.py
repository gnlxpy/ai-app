from html import escape
from pydantic import BaseModel, ConfigDict

from db import Db

 
TELEGRAM_MESSAGE_LIMIT: int = 4096
 
 
class IdiomWithExamplesRow(BaseModel):
    """Строка результата с идиомой, значением и списком примеров использования."""
 
    model_config = ConfigDict(str_strip_whitespace=True)
 
    idiom: str
    meaning: str
    examples: list[str]
 
 
def pick_shortest_example(examples: list[str]) -> str:
    """Выбирает из списка примеров самый короткий.
 
    Примеры из корпуса сильно разнятся по длине (от одной фразы до длинной
    цитаты); короткий пример читается в карточке идиомы лучше и не раздувает
    сообщение.
 
    :param examples: Список примеров использования идиомы.
    :return: Один, самый короткий по длине текста пример.
    """
    return min(examples, key=len)
 
 
def format_idioms_with_examples_message(
    word: str,
    idioms_raw: list[dict[str, str | list[str]]] | bool,
) -> str:
    """Готовит список идиом с одним примером каждой к отправке в Telegram (HTML).
 
    Для каждой идиомы берёт значение и один (самый короткий) пример из БД,
    экранирует HTML-спецсимволы и обрезает итоговое сообщение под лимит
    Telegram в 4096 символов.
 
    :param word: Слово, по которому искали идиомы — для заголовка сообщения.
    :param idioms_raw: Список словарей {idiom, meaning, examples: list[str]}
        либо False, если ничего не найдено.
    :return: Готовая HTML-строка для bot.send_message(..., parse_mode="HTML").
    """
    word_escaped = escape(word, quote=False)
 
    if not idioms_raw:
        return f"No idioms found for the word <b>{word_escaped}</b> 🤷"
 
    rows = [IdiomWithExamplesRow.model_validate(row) for row in idioms_raw]
 
    header = f"<b>Idioms with the word «{word_escaped}»:</b>"
    items = []
    for i, row in enumerate(rows, start=1):
        example = pick_shortest_example(row.examples)
        items.append(
            f"{i}. <b>{escape(row.idiom, quote=False)}</b>\n"
            f"   {escape(row.meaning, quote=False)}\n"
            f"   <i>«{escape(example, quote=False)}»</i>"
        )
 
    message = header + "\n\n" + "\n\n".join(items)
 
    if len(message) > TELEGRAM_MESSAGE_LIMIT:
        print(f"Сообщение с идиомами+примерами для '{word}' превысило лимит Telegram, обрезаю")
        message = message[: TELEGRAM_MESSAGE_LIMIT - 4] + "\n…"
 
    return message


def gen_msg_word_idioms(word: str):
    data_raw = Db.get_idioms(word)
    if not data_raw:
        return False
    message = format_idioms_with_examples_message(word, data_raw)
    return message
