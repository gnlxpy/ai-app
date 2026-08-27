import re
from pydantic import BaseModel, Field, model_validator
import chromadb
import random
from config import settings
from anthropic import Anthropic
from anthropic.types import Message
from db import Db
import html


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


def get_answer(message: Message) -> str:
    """Извлекает текст ответа, аккуратно склеивая все text-блоки без лишних переносов.
    :param message: Ответ Anthropic API.
    :return: Итоговый текст без разрывов от citation-блоков.
    """
    # Склеиваем все text-блоки подряд БЕЗ разделителя,
    # т.к. citations разбивают одну фразу на несколько блоков
    parts = [block.text for block in message.content if block.type == "text"]
    return "".join(parts)


def sanitize_field(text: str) -> str:
    """Убирает HTML-теги, которые модель могла ошибочно добавить, и экранирует
    оставшиеся спецсимволы (&, <, >), чтобы Telegram не пытался парсить их как разметку.
    :param text: Сырой текст поля из ответа модели.
    :return: Безопасный для parse_mode="HTML" текст без тегов модели.
    """
    without_tags = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    return html.escape(without_tags, quote=False).strip()


class IdiomPost(BaseModel):
    hook: str = Field(
        description=(
            "1 цепляющая фраза-затравка, до 15 слов. "
            "Добавь в начало ОДИН эмодзи, подходящий по настроению идиомы "
            "(например 😅 для иронично-скептичных идиом, 🤞 для идиом про надежду)."
        )
    )
    meaning: str = Field(description="Значение идиомы простым языком")
    origin: str = Field(
        description=(
            "Происхождение идиомы. Указывай только то, что реально нашёл через web_search "
            "и можешь связать с конкретным источником. НЕ используй обороты вида "
            "'некоторые источники предполагают' или 'возможно, связано с...' — это "
            "звучит как факт, но не проверяемо читателем. Если конкретное происхождение "
            "не подтверждается поиском — прямо напиши: 'Точное происхождение идиомы "
            "не задокументировано', без добавления сочинённых версий."
        )
    )
    translation_ru: list[str] = Field(
        description="Буквальный/словарный перевод идиомы, 1-2 варианта."
    )
    analogs_ru: list[str] = Field(
        description=(
            "ТОЛЬКО готовые русские идиомы/пословицы с похожим смыслом. "
            "ЗАПРЕЩЕНО включать кальки или дословные переводы английской идиомы "
            "(например, 'не задерживай дыхание' — это калька, а не аналог, "
            "её включать нельзя, даже с пометкой 'калька, но прижилась'). "
            "Если нашёл только 1 подходящий аналог — верни список из 1 элемента, "
            "не добавляй слабые варианты ради количества. "
            "Хорошие примеры для идиом про 'напрасно ждать/надеяться': "
            "'как рак на горе свистнет', 'после дождичка в четверг', 'ждать у моря погоды'."
        )
    )
    examples: list[dict[str, str]] = Field(
        description="Список примеров: {'en': ..., 'ru': ..., 'comment': ...}"
    )
    teacher_tip: str = Field(
        description=(
            "Короткий методический совет для читателя. Обращайся на 'вы' "
            "к подписчику Telegram-канала, НЕ используй слова 'студенты'/'учащиеся'."
        )
    )
    cta: str = Field(
        description=(
            "Задание для самостоятельной практики: предложи составить своё "
            "предложение с идиомой мысленно или письменно для себя. "
            "НЕ проси делиться, писать в комментариях, отправлять куда-либо — "
            "ответ никуда не отправляется, это просто упражнение на закрепление."
        )
    )

    @model_validator(mode="after")
    def sanitize_fields(self) -> "IdiomPost":
        """Убирает теги от модели и экранирует спецсимволы во всех текстовых полях."""
        self.hook = sanitize_field(self.hook)
        self.meaning = sanitize_field(self.meaning)
        self.origin = sanitize_field(self.origin)
        self.teacher_tip = sanitize_field(self.teacher_tip)
        self.cta = sanitize_field(self.cta)
        self.translation_ru = [sanitize_field(s) for s in self.translation_ru]
        self.analogs_ru = [sanitize_field(s) for s in self.analogs_ru]
        self.examples = [{k: sanitize_field(v) for k, v in ex.items()} for ex in self.examples]
        return self


def gen_msg_structured(idiom_text: str, model: str = default_model) -> IdiomPost:
    """Генерирует структурированные данные об идиоме через Claude API.
    :param idiom_text: Строка с идиомой, значением и примерами из БД.
    :param model: Модель Claude.
    :return: Валидированный объект IdiomPost.
    """
    system_prompt = " ".join(
        [
            "Ты должен корректно переводить английские идиомы на русский язык и искать русские аналоги.",
            "Ты можешь использовать веб-поиск для проверки значения, происхождения и аналогов.",
            "После поиска верни ТОЛЬКО валидный JSON по схеме ниже, без markdown-разметки,",
            "без ```json, без пояснений до или после JSON.",
            "Значения ВСЕХ полей — чистый текст без HTML-тегов и без разметки цитирования",
            "(никаких <cite>, <a>, <b> и подобных внутри значений полей).",
            "Пиши связным текстом своими словами, не переноси обрывки цитат из источников.",
            f"Схема: {IdiomPost.model_json_schema()}",
        ]
    )

    message = client.messages.create(
        model=model,
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Идиома: {idiom_text}"}],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 3,
        }],
    )
    print(message.usage)
    raw_text = "".join(b.text for b in message.content if b.type == "text")
    return IdiomPost.model_validate_json(raw_text)


def render_telegram_post(post: IdiomPost, idiom_title: str) -> str:
    """Собирает финальный HTML-пост для Telegram из структурированных данных.
    :param post: Валидированный объект с контентом.
    :param idiom_title: Заголовок идиомы (англ.).
    :return: Готовый HTML-текст с фиксированными эмодзи-заголовками и отступами.
    """
    safe_title = html.escape(idiom_title, quote=False)
    examples_html = "\n\n".join(
        f"<b>Пример {i}:</b>\n<i>{ex['en']}</i>\n{ex['ru']}\n<code>{ex['comment']}</code>"
        for i, ex in enumerate(post.examples, start=1)
    )
    return "\n\n".join([
        post.hook,
        f"<b>📖 Идиома дня: {safe_title}</b>",
        f"<b>💭 Значение:</b> {post.meaning}",
        f"<b>📜 Происхождение:</b> {post.origin}",
        f"<b>🔄 Перевод:</b> {', '.join(post.translation_ru)}",
        f"<b>🇷🇺 Аналоги:</b> {', '.join(post.analogs_ru)}",
        f"<b>✍️ Примеры:</b>\n\n{examples_html}",
        f"<b>💡 Совет:</b> {post.teacher_tip}",
        f"<b>🎯 Задание:</b> {post.cta}",
    ])

def get_idiom_title(idiom_eng: str) -> str:
    pattern = r"Idiom:\s*(.*?);"
    match = re.search(pattern, idiom_eng)
    if not match:
        return ''
    extracted_text = match.group(1)
    return extracted_text


def gen_msg(idiom_eng: str) -> str:
    idiom_title = get_idiom_title(idiom_eng)
    idiom_post = gen_msg_structured(idiom_eng)
    idiom_post_rendered = render_telegram_post(idiom_post, idiom_title)
    return idiom_post_rendered


if __name__ == '__main__':
    pass
