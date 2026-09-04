import asyncio
import json
import time
from anthropic import AsyncAnthropic
from config import settings
from ch import Ch


MODEL: str = "claude-haiku-4-5"
CONCURRENCY: int = 10
PAGE_SIZE: int = 100_000
BATCH_MIN_SENSES: int = 3


client = AsyncAnthropic(api_key=settings.ANTHROPIC_TOKEN)

RANKING_TOOL: dict = {
    "name": "submit_ranking",
    "description": "Return the given senses of a word ordered from most to least commonly used in real English",
    "input_schema": {
        "type": "object",
        "properties": {
            "ranking": {
                "type": "array",
                "items": {"type": "string"},
                "description": "All sense ids from the input, ordered most-common-sense-first",
            }
        },
        "required": ["ranking"],
    },
}

SYSTEM_PROMPT: str = (
    "You are an expert lexicographer of contemporary English usage. "
    "You will be given a word and a numbered list of its dictionary senses, "
    "each with a short id. Rank the ids from the sense a native speaker "
    "encounters most often in everyday speech, writing and media, to the "
    "sense encountered least often, based on real-world usage frequency — "
    "not etymology, dictionary order, or formality. If two senses are "
    "duplicates or near-duplicates, keep them adjacent. "
    "You must call submit_ranking exactly once. The 'ranking' array must "
    "contain every given id exactly once, in ranked order, with no ids "
    "added, omitted, or repeated, and no extra text outside the tool call."
)


def get_long_examples(offset: int, limit: int) -> list[dict]:
    """Выгружает значения слов постранично и группирует их по слову.
    :param offset: Смещение постраничной выгрузки.
    :param limit: Размер страницы.
    :param batch_min: Минимальное число значений у слова, чтобы включить его в выгрузку.
    :return: [{"word": ..., "meaning_list": [{"pos": ..., "meaning": ...}, ...]}, ...]
    """
    data_db = Ch.query(
        f"SELECT word, pos, meaning FROM words_examples_grouped ORDER BY word LIMIT {offset}, {limit}"
    )
    main_data = []
    data_tmp = []
    for n, item in enumerate(data_db):
        if item["word"][0] == '-' or len(item["word"]) <= 2:
            continue
        data_tmp.append(item)
        is_last_row = n + 1 == len(data_db)
        if is_last_row or item["word"] != data_db[n + 1]["word"]:
            main_data.append(data_tmp)
            data_tmp = []

    return [
        {
            "word": group[0]["word"],
            "meaning_list": [{"pos": row["pos"], "meaning": row["meaning"]} for row in group],
        }
        for group in main_data
        if len(group)
    ]


async def rank_word(semaphore: asyncio.Semaphore, item: dict) -> list[dict]:
    """Ранжирует значения одного слова одним синхронным (в рамках вызова) запросом к API.
    :param semaphore: Ограничитель числа одновременных запросов к API.
    :param item: {"word": ..., "meaning_list": [{"pos": ..., "meaning": ...}, ...]}.
    :return: [{"word": ..., "meaning": ..., "frequency": ...}, ...] по этому слову; пусто при ошибке.
    """
    senses = [{"id": str(i), "pos": s["pos"], "meaning": s["meaning"]} for i, s in enumerate(item["meaning_list"])]

    async with semaphore:
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{
                    "role": "user",
                    "content": f'Word: "{item["word"]}"\nSenses: {json.dumps(senses, ensure_ascii=False)}',
                }],
                tools=[RANKING_TOOL],
                tool_choice={"type": "tool", "name": "submit_ranking"},
            )
        except Exception as exc:  # сетевые сбои, 429 rate limit, таймауты
            print(f"Ошибка запроса для '{item['word']}': {exc}")
            return []

    if response.stop_reason == "max_tokens":
        print(f"Truncated response for '{item['word']}' (max_tokens)")
        return []

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_ranking":
            ranking = block.input.get("ranking")
            expected_ids = {s["id"] for s in senses}
            if not isinstance(ranking, list) or set(ranking) != expected_ids:
                print(f"Invalid ranking for '{item['word']}': {block.input}")
                return []
            n = len(ranking)
            rows = []
            for rank_pos, local_id in enumerate(ranking):
                try:
                    sense = item["meaning_list"][int(local_id)]
                except (ValueError, IndexError):
                    print(f"Некорректный id '{local_id}' для слова '{item['word']}'")
                    continue
                rows.append({
                    "word": item["word"],
                    "meaning": sense["meaning"],
                    "frequency": round(100 * (n - rank_pos) / n),
                })
            return rows

    print(f"Нет tool_use в ответе для '{item['word']}'")
    return []


async def rank_words_page(words_meanings: list[dict]) -> list[dict]:
    """Параллельно (с ограничением конкурентности) ранжирует все слова одной страницы выгрузки.
    :param words_meanings: Результат get_long_examples.
    :return: Плоский список {"word", "meaning", "frequency"} по всем словам страницы.
    """
    semaphore = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(rank_word(semaphore, item) for item in words_meanings))
    return [row for word_rows in results for row in word_rows]


def load_scores(rows: list[dict]) -> None:
    """Создаёт (при отсутствии) таблицу-справочник meaning_freq и заливает в неё оценки.
    :param rows: [{"word": ..., "meaning": ..., "frequency": ...}, ...].
    """
    if not rows:
        return
    # Ch.command("""
    #     CREATE TABLE IF NOT EXISTS default.meaning_freq
    #     (word String, meaning String, frequency UInt8)
    #     ENGINE = MergeTree() ORDER BY (word, meaning)
    # """)
    Ch.insert(
        "default.meaning_freq",
        [(r["word"], r["meaning"], r["frequency"]) for r in rows],
    )


async def words_cleaning_realtime(start_offset: int = 0, page_size: int = PAGE_SIZE) -> None:
    """Постранично прогоняет весь словарь через API в реальном времени и заливает оценки в ClickHouse.
    :param start_offset: С какого смещения начинать (удобно для продолжения прерванного прогона).
    :param page_size: Размер страницы выгрузки из ClickHouse.
    """
    offset = start_offset
    while True:
        words_meanings = get_long_examples(offset, page_size)
        print(f'words_meanings length: {len(words_meanings)}')
        if not words_meanings:
            print(f"Страница с offset={offset} пуста - завершаю")
            break

        rows = await rank_words_page(words_meanings)
        load_scores(rows)
        print(f"offset={offset}: слов={len(words_meanings)}, оценок сохранено={len(rows)}")
        time.sleep(10)

        offset += page_size
