import json
import re
from ch import Ch
import enum


class Tables(enum.Enum):
    USERS = 'users'
    IDIOMS = 'idioms'
    IDIOMS_HISTORY = 'idioms_history'
    WORDS = 'words'
    WORDS_HISTORY = 'words_history'
    WORDS_EXAMPLES = 'words_examples_grouped'
    WORDS_TRANSLATIONS = 'words_translations_grouped'


class Db:

    @staticmethod
    def get_users_tg_ids() -> bool | list:
        users_db = Ch.query('SELECT * FROM %(table)s FINAL WHERE status = true', {'table': Tables.USERS.value})
        print(users_db)
        if not isinstance(users_db, list):
            return False
        elif len(users_db) == 0:
            return []
        return [i['tgid'] for i in users_db]

    @staticmethod
    def create_user(tgid: str, name: str, status: bool = True):
        users = Ch.query('SELECT * FROM %(table)s FINAL WHERE tgid = %(tgid)s;', {'table': Tables.USERS.value, 'tgid': tgid})
        if users:
            return False
        r = Ch.insert(Tables.USERS.value, [[tgid, name, status]], ['tgid', 'name', 'status'])
        return r

    @staticmethod
    def update_user(tgid: int | str, status: bool):
        users = Ch.query('SELECT * FROM %(table)s FINAL WHERE tgid = %(tgid)s;', {'table': Tables.USERS.value, 'tgid': tgid})
        if not users:
            return False
        user_name = users[0]['name']
        r = Ch.insert(Tables.USERS.value, [[tgid, user_name, status]], ['tgid', 'name', 'status'])
        return r

    @staticmethod
    def get_idioms_history():
        last_idiom_text = Ch.query('SELECT * FROM %(table)s ORDER BY date DESC LIMIT 1;' , {'table': Tables.IDIOMS_HISTORY.value})
        if not last_idiom_text:
            return False
        return last_idiom_text[0]

    @staticmethod
    def insert_idioms_history(idiom: str, message: str):
        r = Ch.insert(Tables.IDIOMS_HISTORY.value, [[idiom, message]], ['idiom', 'message'])
        return r

    @staticmethod
    def get_random_idiom():
        query = """
SELECT idiom, meaning, examples
FROM %(table)s
WHERE idiom NOT IN (SELECT idiom FROM %(table2)s)
ORDER BY rand()
LIMIT 1;
"""
        idioms_list = Ch.query(query, {'table': Tables.IDIOMS.value, 'table2': Tables.IDIOMS_HISTORY.value})
        if not idioms_list:
            return False
        return idioms_list[0]

    @staticmethod
    def get_idioms(word: str):
        query = """
SELECT idiom, meaning, examples
FROM %(table)s
WHERE match(idiom, %(pattern)s)
LIMIT 10;
"""
        # \b — граница слова, (?i) — регистронезависимо;
        # re.escape на случай спецсимволов, хотя word и так проходит
        # валидацию regex'ом ^[a-zA-Z]{1,15}$ на уровне хендлера в main.py
        pattern = rf"(?i)\b{re.escape(word)}\b"
        idioms_list = Ch.query(query, {'table': Tables.IDIOMS.value, 'pattern': pattern})
        if not idioms_list:
            return False
        return idioms_list

    @staticmethod
    def get_word_info(word: str):
        tables_list = [
            {'table': Tables.WORDS.value, 'result': None},
            {'table': Tables.WORDS_EXAMPLES.value, 'result': None},
            {'table': Tables.WORDS_TRANSLATIONS.value, 'result': None}
        ]
        for item in tables_list:
            result = Ch.query("SELECT * FROM %(table)s WHERE word ILIKE %(word)s LIMIT 0, 10;", {'table': item['table'], 'word': word})
            if not result:
                return False
            item['result'] = result
        return json.loads(tables_list)

    @staticmethod
    def check_word(word: str):
        result = Ch.query("SELECT word FROM %(table)s WHERE word ILIKE %(word)s LIMIT 0, 10;", {'table': Tables.WORDS.value, 'word': word})
        if not result:
            return False
        return True

    @staticmethod
    def get_word_raw_data(word: str) -> dict | None:
        """Собирает сырые данные по слову из 3 таблиц ClickHouse для fetch_word_raw.
        
        :param word: Слово для поиска.
        :return: Словарь с ключами 'word_meta', 'examples', 'translations' или None.
        """
        # Получаем метаданные слова (транскрипции, аудио)
        word_data = Ch.query(
            "SELECT sounds_enpr, sounds_ipa, sounds_en_us_url, sounds_en_uk_url "
            "FROM %(table)s WHERE word = %(word)s LIMIT 1;",
            {'table': Tables.WORDS.value, 'word': word}
        )
        
        if not word_data:
            return None
        
        # Получаем примеры со значениями
        examples_data = Ch.query(
            "SELECT pos, meaning, examples, synonyms, antonyms "
            "FROM %(table)s WHERE word = %(word)s;",
            {'table': Tables.WORDS_EXAMPLES.value, 'word': word}
        )
        
        if not examples_data:
            return None
        
        # Получаем переводы
        translations_data = Ch.query(
            "SELECT pos, translate_ru, translate_uk, translate_ge "
            "FROM %(table)s WHERE word = %(word)s;",
            {'table': Tables.WORDS_TRANSLATIONS.value, 'word': word}
        )
        
        # Если переводов нет, возвращаем пустой список
        if not translations_data:
            translations_data = []
        
        return {
            'word_meta': word_data[0],  # Берём первую (единственную) строку
            'examples': examples_data,
            'translations': translations_data,
        }

    @staticmethod
    def insert_words_history(word: str, message: str, idiom_button: bool):
        r = Ch.insert(Tables.WORDS_HISTORY.value, [[word, message, idiom_button]], ['word', 'message', 'idiom_button'])
        return r

    @staticmethod
    def get_words_history(word: str):
        word_history = Ch.query('SELECT * FROM %(table)s WHERE word = %(word)s LIMIT 1;' , {'table': Tables.WORDS_HISTORY.value, 'word': word})
        if not word_history:
            return False
        return word_history[0]
