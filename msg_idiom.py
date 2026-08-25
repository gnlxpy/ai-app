
import chromadb
import random
from config import settings
from anthropic import Anthropic
from anthropic.types import Message
from db import Db


client = Anthropic(api_key=settings.ANTHROPIC_TOKEN)
default_model = "claude-sonnet-5"


def get_uniq_randint(collection_count: int):
    idioms_ids = Db.get_idioms_ids()
    while True:
        randint_str = str(random.randint(1, collection_count))
        if randint_str in idioms_ids:
            continue
        else:
            return randint_str


def get_random_idiom() -> str | bool:
    client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
    collection = client.get_collection(
        name=settings.IDIOMS_COLLECTION,
    )
    collection_count = collection.count()
    randint_str = get_uniq_randint(collection_count)
    idiom = collection.get(randint_str)
    if not idiom:
        return False
    idiom_texts = idiom.get('documents')
    if not idiom or not idiom_texts:
        return False
    return idiom_texts[0], randint_str


def get_answer(ai_msg: Message) -> str:
    return "\n".join(
        block.text
        for block in ai_msg.content
        if block.type == "text"
    )


def gen_msg(idiom_text: str, model: str = default_model, max_tokens: int = 8000) -> Message:
    messages = [
        {
            "role": "user",
            "content": f"Расскажи о данной идиоме дня: {idiom_text}"
        }
    ]
    system_prompt = " ".join(
        [
            "Ты должен корректно переводить английские идиомы на русский язык и искать русские аналоги.",
            "Ты можешь использовать веб-поиск. После поиска выполни задачу пользователя:",
            "1) собери информацию об идиоме на английском языке;",
            "2) переведи английскую идиому на русский язык;",
            "3) найди русскоязычные аналоги идиомы по смыслу;",
            "4) дай развёрнутый ответ как учитель английского.",
            "Форматируй ответ только в Telegram HTML.",
            "Используй только теги: <b>, <strong>, <i>, <em>, <u>, <s>, <code>, <pre>, <a>.",
            "Не используй Markdown, таблицы и заголовки Markdown.",
            "Ответ не должен превышать 3900 букв без учёта тегов.",
        ]
    )

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        system=system_prompt,
        tools=[
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
                "user_location": {
                    "type": "approximate",
                    "city": "Tbilisi",
                    "timezone": "Asia/Tbilisi",
                }
            }
        ]
        )
    print(message.usage)
    message_text = get_answer(message)
    
    return message_text


def prepare_and_send_idiom():

    return 