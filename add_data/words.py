import time
from pathlib import Path
import json
from ch import Ch
from config import settings


def count_lines(file_path: str | Path, chunk_size: int = 1024 * 1024) -> int:
    """Считает количество строк в файле подсчётом байт-переводов построчно, без загрузки файла в память.
    :param file_path: Путь к jsonl-файлу.
    :param chunk_size: Размер буфера чтения в байтах (по умолчанию 1 МБ).
    :return: Количество строк в файле.
    """
    path = Path(file_path)
    count = 0
    with path.open('rb') as f:
        while chunk := f.read(chunk_size):
            count += chunk.count(b'\n')

    return count


def extract_lines_batch(
    file_path: str | Path,
    output_path: str = 'docs/',
    start_line: int = 0,
    batch_size: int = 300,
) -> Path:
    """Извлекает диапазон строк одним проходом по файлу и сохраняет как json-список.
    :param file_path: Путь к исходному jsonl-файлу.
    :param output_path: Путь для сохранения результата.
    :param start_line: Номер первой строки диапазона (0-indexed).
    :param batch_size: Количество строк в батче.
    :return: Путь к сохранённому json-файлу.
    """
    path = Path(file_path)
    out_path = Path(f"{output_path}batch_rows.json")
    end_line = start_line + batch_size

    result: list[dict] = []
    with path.open('r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            if idx < start_line:
                continue
            if idx >= end_line:
                break
            result.append(json.loads(line))

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Сохранено {len(result)} строк в {out_path.name} (диапазон {start_line}–{end_line - 1})")
    return out_path


def prepare_wiktext_for_db(path: str) -> dict[str, list]:
    word_data_set = set()
    word_data = []
    translations_data = []
    examples_data = []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.loads(f.read())

    for row in data:
        word = row.get('word')
        if not word:
            continue
        pos = row.get('pos')
        enpr = ''
        ipa = ''
        audio_uk = ''
        audio_us = ''
        translate_meaning = ''
        translate_ru = []
        translete_ge = []
        translate_uk = []
        sounds_raw = row.get('sounds')
        if sounds_raw:
            for item in row['sounds']:
                value = item.get('enpr')
                if not enpr and value:
                    enpr = value
                value = item.get('ipa')
                if not ipa and value:
                    ipa = value
                value = item.get('audio')
                if not audio_uk and value and 'uk' in value.lower():
                    audio_uk = item.get('mp3_url')
                if not audio_us and value and 'us' in value.lower():
                    audio_us = item.get('mp3_url')

        translations_raw = row.get('translations')
        if translations_raw:
            for item in row['translations']:
                lang = item.get('lang')
                value = item.get('word')

                if not isinstance(value, str) or not value:
                    continue

                if lang == 'Russian':
                    translate_ru.append(value)
                elif lang == 'Ukrainian':
                    translate_uk.append(value)
                elif lang == 'Georgian':
                    translete_ge.append(value)

                if not translate_meaning and item.get('sense'):
                    translate_meaning = item.get('sense')

            if translate_ru or translate_uk or translete_ge:
                translations_data.append((word, pos, translate_meaning, translate_ru, translate_uk, translete_ge))

        if word not in word_data_set:
            word_data.append((word, enpr, ipa, audio_us, audio_uk))
            word_data_set.add(word)

        senses_raw = row.get('senses')
        if senses_raw:
            for sense in row['senses']:
                example_dict = {'examples': [], 'meaning': '' ,'synonyms': [], 'antonyms': []}
                examples_raw = sense.get('examples')
                if examples_raw:
                    glosses_raw = sense.get('glosses')
                    if glosses_raw:
                        meaning = glosses_raw[0]
                        if not meaning:
                            continue
                        example_dict['meaning'] = glosses_raw[0]
                    for example in sense['examples']:
                        example_text = example.get('text')
                        if isinstance(example_text, str) and example_text:
                            example_dict['examples'].append(example_text)
                    synonyms_raw = sense.get('synonyms')
                    if synonyms_raw:
                        example_dict['synonyms'] = [
                            item.get('word')
                            for item in synonyms_raw
                            if isinstance(item.get('word'), str) and item.get('word')
                        ]
                    antonyms_raw = sense.get('antonyms')
                    if antonyms_raw:
                        example_dict['antonyms'] = [
                            item.get('word')
                            for item in antonyms_raw
                            if isinstance(item.get('word'), str) and item.get('word')
                        ]

                if example_dict['meaning'] and example_dict['examples']:
                    examples_data.append((word, pos, example_dict['meaning'], example_dict['examples'], example_dict['synonyms'], example_dict['antonyms']))

    return {'words': word_data, 'words_examples': examples_data, 'words_translations': translations_data}


def add_wiktext_to_db(offset: int = 0, batch_size: int = 500_000):
    path = settings.BASE_DIR + 'raw-wiktextract-data.jsonl'
    rows_num = count_lines(path)
    print(f"Total number of rows in the file: {rows_num}")
    while offset < rows_num:
        print(f"Processing batch starting at line {offset}...")
        batch_size = 1_000_000
        extract_lines_batch(
            file_path=path,
            start_line=offset,
            batch_size=batch_size
        )
        print(f"Extracted lines {offset} to {offset + batch_size} into 'docs/batch_rows.json'.")
        time.sleep(1)
        data_db = prepare_wiktext_for_db('docs/batch_rows.json')
        print(f"Prepared data for database insertion from db words {len(data_db['words'])}, words_examples {len(data_db['words_examples'])}, and words_translations {len(data_db['words_translations'])}.")
        for table, data in data_db.items():
            result = Ch.insert(table, data)
            print(f"Inserted {result} rows into the '{table}' table.")
            if not result:
                print(f"Failed to insert data into the '{table}' table!!!!")
                quit()

        offset += batch_size
