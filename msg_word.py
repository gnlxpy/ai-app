import html
import json
from enum import Enum
import re
from anthropic import Anthropic
from pydantic import BaseModel, Field, model_validator
from config import settings
from anthropic.types import Message
from db import Db


client = Anthropic(api_key=settings.ANTHROPIC_TOKEN)
default_model = "claude-haiku-4-5-20251001"


class PartOfSpeech(str, Enum):
    """Наиболее частые части речи в словарных выписках.

    Точный набор значений `pos` в вашей БД стоит проверить запросом
    `SELECT DISTINCT pos FROM words_examples_grouped` и актуализировать
    перечисление. Сейчас pos хранится и передаётся как str — этот enum
    можно подключить для валидации после проверки реальных данных.
    """

    NOUN = "noun"
    VERB = "verb"
    ADJECTIVE = "adjective"
    ADVERB = "adverb"
    PRONOUN = "pronoun"
    PREPOSITION = "preposition"
    CONJUNCTION = "conjunction"
    INTERJECTION = "interjection"
    DETERMINER = "determiner"
    IDIOM = "idiom"
    PHRASE = "phrase"


class RawMeaning(BaseModel):
    """Одна строка значения из words_examples_grouped + подтянутые переводы."""

    id: int = Field(description="Индекс значения во входном списке для данного слова")
    pos: str
    meaning: str
    examples: list[str]
    synonyms: list[str]
    antonyms: list[str]
    translate_ru: list[str] = Field(default_factory=list)
    translate_uk: list[str] = Field(default_factory=list)
    translate_ge: list[str] = Field(default_factory=list)


class WordRaw(BaseModel):
    """Все сырые данные по слову из 3 таблиц, готовые к отправке в LLM."""

    word: str
    sounds_enpr: str
    sounds_ipa: str
    sounds_en_us_url: str
    sounds_en_uk_url: str
    raw_meanings: list[RawMeaning]


def get_answer(message: Message) -> str:
    """Извлекает текст ответа, аккуратно склеивая все text-блоки без лишних переносов.
    
    Обрабатывает как обычные text-блоки, так и блоки с citations,
    пропускает thinking-блоки.
    
    :param message: Ответ Anthropic API.
    :return: Итоговый текст ответа или пустая строка если нет text-блоков.
    """
    # Склеиваем все text-блоки подряд БЕЗ разделителя,
    # т.к. citations разбивают одну фразу на несколько блоков
    parts = [block.text for block in message.content if block.type == "text"]
    result = "".join(parts).strip()
    
    if not result:
        # Отладка: если ответ пуст, выведем что вернула модель
        print(f"⚠️ get_answer() вернула пустую строку. message.content: {message.content}")
    
    return result


def extract_json(text: str) -> str:
    """Извлекает JSON из markdown code fences или возвращает текст как есть.
    
    Модель может вернуть JSON завёрнутым в ```json...``` — нужно это убрать.
    
    :param text: Текст, потенциально содержащий JSON в markdown.
    :return: Чистый JSON без code fences.
    """
    # Ищем код внутри ``` ... ```
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Если code fences нет, вернём как есть
    return text.strip()


def sanitize_field(text: str) -> str:
    """Убирает HTML-теги, которые модель могла ошибочно добавить, и экранирует
    оставшиеся спецсимволы (&, <, >), чтобы Telegram не пытался парсить их как разметку.
    :param text: Сырой текст поля из ответа модели.
    :return: Безопасный для parse_mode="HTML" текст без тегов модели.
    """
    without_tags = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    return html.escape(without_tags, quote=False).strip()


def fetch_word_raw(word: str) -> WordRaw | None:
    """Собирает все данные по слову из 3 таблиц ClickHouse в единую структуру.

    :param word: Слово для поиска.
    :return: WordRaw с сырыми значениями и метаданными или None, если слова нет.
    """
    # Получаем все данные через единый метод Db
    raw_data = Db.get_word_raw_data(word)
    if not raw_data:
        print(f"Слово '{word}' не найдено в таблицах ClickHouse")
        return None

    word_meta = raw_data['word_meta']
    examples_rows = raw_data['examples']
    translations_data = raw_data['translations']

    # Джойн переводов по pos (без meaning)
    translations_by_pos = {
        row["pos"]: row
        for row in translations_data
    }

    raw_meanings = []
    for idx, row in enumerate(examples_rows):
        translation = translations_by_pos.get(row["pos"], {})
        raw_meanings.append(
            RawMeaning(
                id=idx,
                pos=row["pos"],
                meaning=row["meaning"],
                examples=row["examples"],
                synonyms=row["synonyms"],
                antonyms=row["antonyms"],
                translate_ru=translation.get("translate_ru", []),
                translate_uk=translation.get("translate_uk", []),
                translate_ge=translation.get("translate_ge", []),
            )
        )

    return WordRaw(word=word, raw_meanings=raw_meanings, **word_meta)


class RankedMeanings(BaseModel):
    """Ответ LLM на шаге ранжирования — только id, без текста."""

    ranked_ids: list[int] = Field(
        description="ID значений из входного списка, упорядоченные по убыванию "
        "употребимости, максимум 7 элементов"
    )

    @model_validator(mode="after")
    def limit_to_seven(self) -> "RankedMeanings":
        """Подстраховка на случай, если модель вернёт больше 7 id вопреки промту."""
        self.ranked_ids = self.ranked_ids[:7]
        return self


RANK_MEANINGS_PROMPT = """\
You are an expert on the usage frequency of English word meanings in modern English.
You are given a list of meanings for the word "{word}", each with a part of speech, \
a definition, and examples.
Each meaning has a numeric id assigned — use ONLY these ids, do not invent any.

Return ONLY valid JSON in the form {{"ranked_ids": [id, id, ...]}}, with no text before/after \
and no markdown code fences.
Markdown code fences (```json, ```) are FORBIDDEN.

Ranking rules:
1. Order the ids by descending frequency of use of the meaning in modern English — from the most \
basic/common to the rarest or most archaic.
2. No more than 7 ids in the result.
3. If several meanings in the list effectively duplicate each other (describing the same sense in \
different words due to imprecise grouping in the source) — keep only one id for that sense, the one \
with the fullest and most accurate wording.
4. Do not add ids that are not in the input data, and do not rely on the order in the list — only on \
actual frequency.

Data (id | pos | meaning | examples):
{meanings_block}
"""


def rank_meanings(word_raw: WordRaw, model: str = default_model) -> list[RawMeaning]:
    """Ранжирует значения слова по употребимости через Claude и возвращает топ-7 (или меньше).

    :param word_raw: Сырые данные слова со всеми найденными значениями.
    :param model: Модель Claude.
    :return: Список RawMeaning, отфильтрованный и упорядоченный по убыванию частотности.
    """
    if len(word_raw.raw_meanings) <= 3:
        # Значений и так немного — не тратим лишний вызов API.
        print(
            f"'{word_raw.word}': {len(word_raw.raw_meanings)} значений, ранжирование не нужно"
        )
        return word_raw.raw_meanings

    meanings_block = "\n".join(
        f"{m.id} | {m.pos} | {m.meaning} | {'; '.join(m.examples[:2])}"
        for m in word_raw.raw_meanings
    )
    prompt = RANK_MEANINGS_PROMPT.format(word=word_raw.word, meanings_block=meanings_block)

    message = client.messages.create(
        model=model,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    
    answer_text = get_answer(message)
    clean_json = extract_json(answer_text)
    try:
        ranked = RankedMeanings.model_validate_json(clean_json)
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга JSON от модели: {e}")
        raise

    by_id = {m.id: m for m in word_raw.raw_meanings}
    return [by_id[i] for i in ranked.ranked_ids if i in by_id]


class MeaningCard(BaseModel):
    """Одно финальное значение в карточке слова."""

    pos: str = Field(description="Часть речи как в источнике, например noun, verb")
    meaning: str = Field(
        description="Значение на английском, при необходимости слегка причёсанное"
    )
    examples: list[str] = Field(
        description="До 3 примеров на английском, самых показательных и разных по контексту"
    )
    synonyms: list[str] = Field(
        default_factory=list,
        description="До 5 синонимов для этого значения"
    )
    antonyms: list[str] = Field(
        default_factory=list,
        description="До 3 антонимов для этого значения"
    )
    translate_ru: list[str] = Field(description="До 3 переводов на русский из предоставленных")
    # translate_uk: list[str] = Field(description="До 3 переводов на украинский из предоставленных")
    # translate_ge: list[str] = Field(description="До 3 переводов на грузинский из предоставленных")

    @model_validator(mode="after")
    def sanitize(self) -> "MeaningCard":
        """Убирает теги/спецсимволы и подстраховывает лимиты."""
        self.pos = sanitize_field(self.pos)
        self.meaning = sanitize_field(self.meaning)
        self.examples = [sanitize_field(e) for e in self.examples][:3]
        self.synonyms = [sanitize_field(s) for s in self.synonyms][:5]
        self.antonyms = [sanitize_field(a) for a in self.antonyms][:3]
        self.translate_ru = [sanitize_field(t) for t in self.translate_ru][:3]
        # self.translate_uk = [sanitize_field(t) for t in self.translate_uk][:3]
        # self.translate_ge = [sanitize_field(t) for t in self.translate_ge][:3]
        return self


class MeaningCardsResponse(BaseModel):
    """Схема, которую реально заполняет модель на шаге сборки — без транскрипций/аудио,
    их подставляем из БД напрямую, чтобы не доверять модели точное копирование ссылок."""

    meanings: list[MeaningCard] = Field(description="До 7 значений, по убыванию употребимости")


class WordPost(BaseModel):
    """Финальная карточка слова, готовая для рендера в Telegram."""

    word: str
    sounds_enpr: str
    sounds_ipa: str
    sounds_en_us_url: str
    sounds_en_uk_url: str
    meanings: list[MeaningCard]

    @model_validator(mode="after")
    def sanitize_word(self) -> "WordPost":
        self.word = sanitize_field(self.word)
        return self


ASSEMBLE_WORD_POST_PROMPT = """\
You are assembling a word card for "{word}" for an English-learning Telegram bot \
(Oxford-dictionary-style format). The meanings have already been selected and ordered \
by frequency of use — do not change their order.

IMPORTANT: do not invent new content. Your task is to select and lightly polish what \
is already present in the data below:
- keep meaning in English; you may slightly shorten/smooth the wording, but do not change the meaning;
- from examples, pick at most 3 of the most illustrative ones, ideally varied in context;
- from synonyms, pick at most 5 of the most common and natural ones, removing duplicates and overly rare ones;
- from antonyms, pick at most 3 of the most direct opposites, removing duplicates and overly rare ones;
- from translate_ru/translate_uk/translate_ge, pick at most 3 of the most natural variants for each \
language, removing duplicates, calques, and outdated/rare variants; if there are fewer than 3 variants, \
return them as is;
- do NOT translate anything yourself — use only what is given in the input translate_* arrays;
- copy pos from the source data unchanged.

Return ONLY valid JSON matching the schema below. The first character of your response must be '{{', \
the last must be '}}'. Markdown code fences (```json, ```) are FORBIDDEN.

Schema: {schema}

Word data (ranked meanings):
{payload}
"""


def assemble_word_post(
    word_raw: WordRaw, ranked: list[RawMeaning], model: str = default_model
) -> WordPost:
    """Финальная сборка карточки слова через Claude: отбор примеров/переводов и структурирование.

    :param word_raw: Сырые данные слова (транскрипции, аудио-ссылки).
    :param ranked: Отранжированные значения (результат rank_meanings).
    :param model: Модель Claude.
    :return: Валидированный WordPost.
    """
    payload = json.dumps([m.model_dump() for m in ranked], ensure_ascii=False)
    prompt = ASSEMBLE_WORD_POST_PROMPT.format(
        word=word_raw.word,
        schema=MeaningCardsResponse.model_json_schema(),
        payload=payload,
    )

    message = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    answer_text = get_answer(message)
    clean_json = extract_json(answer_text)
    response = MeaningCardsResponse.model_validate_json(clean_json)

    # Транскрипции и аудио-ссылки берём напрямую из БД, а не из ответа модели —
    # не доверяем LLM точное копирование технических значений.
    return WordPost(
        word=word_raw.word,
        sounds_enpr=word_raw.sounds_enpr,
        sounds_ipa=word_raw.sounds_ipa,
        sounds_en_us_url=word_raw.sounds_en_us_url,
        sounds_en_uk_url=word_raw.sounds_en_uk_url,
        meanings=response.meanings,
    )


def render_telegram_word_post(post: WordPost) -> str:
    """Собирает финальный HTML-пост карточки слова для Telegram.

    :param post: Валидированный WordPost.
    :return: Готовый HTML-текст для отправки с parse_mode="HTML".
    """
    header = "\n".join(
        [
            f"<b>📖 {post.word}</b>",
            f"<code>{post.sounds_enpr}</code> · <code>{post.sounds_ipa}</code>",
            f'🔊 <a href="{post.sounds_en_us_url}">US</a> · <a href="{post.sounds_en_uk_url}">UK</a>',
        ]
    )

    # Основной блок значений с примерами, синонимами, антонимами (БЕЗ переводов)
    meanings_blocks = []
    for i, m in enumerate(post.meanings, start=1):
        lines = [f"<b>{i}. {m.pos}</b> — {m.meaning}"]
        lines.extend(f"<i>{ex}</i>" for ex in m.examples)
        
        if m.synonyms:
            lines.append(f"<b>Synonyms:</b> {', '.join(m.synonyms)}")
        if m.antonyms:
            lines.append(f"<b>Antonyms:</b> {', '.join(m.antonyms)}")
        if m.translate_ru:
            lines.append(f"<b>ru:</b> {', '.join(m.translate_ru)}")

        meanings_blocks.append("\n".join(lines))

    sections = [header, *meanings_blocks]

    return "\n\n".join(sections)


def gen_msg_word(word: str) -> tuple:
    """Полный пайплайн: слово -> данные из БД -> ранжирование -> сборка -> HTML для Telegram.

    :param word: Слово для карточки (например "set").
    :return: Готовый HTML-пост или None, если слово не найдено в БД.
    """
    idiom_button = False
    word_raw = fetch_word_raw(word)
    if not word_raw:
        return False, idiom_button
    ranked = rank_meanings(word_raw)
    post = assemble_word_post(word_raw, ranked)
    rendered_post = render_telegram_word_post(post)
    if rendered_post:
        check_idioms = Db.get_idioms(word)
        if check_idioms:
            idiom_button = True
    else:
        return False, idiom_button
    return rendered_post, idiom_button
