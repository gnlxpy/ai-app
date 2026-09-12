import re
from pydantic import BaseModel, Field, model_validator
from config import settings
from anthropic import Anthropic
from anthropic.types import Message
import html


client = Anthropic(api_key=settings.ANTHROPIC_TOKEN)
default_model = "claude-sonnet-5"


def extract_json_block(text: str) -> str:
    """Вырезает JSON-объект из текста, отбрасывая любые преамбулы модели
    (например, комментарии перед вызовом web_search).
    :param text: Склеенный текст всех text-блоков ответа модели.
    :return: Подстрока от первой '{' до последней '}'.
    :raises ValueError: если фигурные скобки не найдены.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"В ответе модели не найден JSON-объект: {text[:200]!r}")
    return text[start : end + 1]


def get_answer(message: Message) -> str:
    """Извлекает и очищает JSON-текст ответа, отбрасывая преамбулы модели
    (актуально при использовании web_search — модель может добавлять
    комментарии в отдельных text-блоках до финального JSON).
    :param message: Ответ Anthropic API.
    :return: Строка, содержащая только JSON-объект.
    """
    parts = [block.text for block in message.content if block.type == "text"]
    joined = "".join(parts)
    return extract_json_block(joined)


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


def gen_msg_structured(idiom_dict: dict, model: str = default_model) -> IdiomPost:
    """Генерирует структурированные данные об идиоме через Claude API.
    :param idiom_text: Строка с идиомой, значением и примерами из БД.
    :param model: Модель Claude.
    :return: Валидированный объект IdiomPost.
    """
    system_prompt = " ".join(
        [
            "Ты должен корректно переводить английские идиомы на русский язык и искать русские аналоги.",
            "Ты можешь использовать веб-поиск для проверки значения, происхождения и аналогов.",
            "После поиска верни ТОЛЬКО валидный JSON по схеме ниже.",
            "ПЕРВЫЙ символ твоего ответа должен быть '{', ПОСЛЕДНИЙ символ — '}'.",
            "Запрещены любые слова до или после JSON (например 'Готово, вот результат:'),",
            "запрещены markdown code fences (```json, ```).",
            "Значения ВСЕХ полей — чистый текст без HTML-тегов.",
            "Пиши связным текстом своими словами, не переноси обрывки цитат из источников.",
            f"Схема: {IdiomPost.model_json_schema()}",
        ]
    )

    message = client.messages.create(
        model=model,
        max_tokens=6000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Идиома: {idiom_dict['idiom']}, значение: {idiom_dict['meaning']}, примеры: {idiom_dict['examples']}"}],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 3,
        }],
    )
    print(message.usage)
    try:
        json_str = get_answer(message)
        print('json_str\n', json_str)
        return IdiomPost.model_validate_json(json_str)
    except Exception as e:
        print(f"Не удалось распарсить ответ модели: {e}")
        raise


def render_telegram_post(post: IdiomPost, idiom_dict: dict) -> str:
    """Собирает финальный HTML-пост для Telegram из структурированных данных.
    :param post: Валидированный объект с контентом.
    :param idiom_title: Заголовок идиомы (англ.).
    :return: Готовый HTML-текст с фиксированными эмодзи-заголовками и отступами.
    """
    examples_html = "\n\n".join(
        f"<b>Пример {i}:</b>\n<i>{ex['en']}</i>\n{ex['ru']}\n<code>{ex['comment']}</code>"
        for i, ex in enumerate(post.examples, start=1)
    )
    return "\n\n".join([
        post.hook,
        f"<b>📖 Идиома дня: {idiom_dict['idiom']}</b>",
        f"<b>💭 Значение:</b> {post.meaning}",
        f"<b>📜 Происхождение:</b> {post.origin}",
        f"<b>🔄 Перевод:</b> {', '.join(post.translation_ru)}",
        f"<b>🇷🇺 Аналоги:</b> {', '.join(post.analogs_ru)}",
        f"<b>✍️ Примеры:</b>\n\n{examples_html}",
        f"<b>💡 Совет:</b> {post.teacher_tip}",
        f"<b>🎯 Задание:</b> {post.cta}",
    ])


def gen_msg_idiom(idiom_dict: dict) -> str:
    idiom_post = gen_msg_structured(idiom_dict)
    idiom_post_rendered = render_telegram_post(idiom_post, idiom_dict)
    return idiom_post_rendered


if __name__ == '__main__':
    pass
