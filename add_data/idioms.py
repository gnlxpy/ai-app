import time
from config import settings
import voyageai
from config import settings
import json
from ch import Ch

vo = voyageai.Client(api_key=settings.VOYAGE_TOKEN)

def get_embeddings(texts: list[str], output_dimension: int) -> list[float]:
    result = vo.embed(texts, model="voyage-4", input_type="document", output_dimension=output_dimension)
    return result.embeddings


def read_idiom_json(path: str) -> list[dict]:
    idioms_tuple = set()
    main_data = []
    n = 0
    with open(path, 'r') as f:
        data = json.loads(f.read())
        for row in data:
            idioms = row.get('Idiom')
            idiom = idioms[0]
            if idiom in idioms_tuple:
                print(f"Skipping duplicate idiom: {idiom}")
                continue
            idioms_tuple.add(idiom)
            meaning = row.get('Meaning')
            examples = row.get('Sentence')
            if not meaning or not examples:
                print(f"Skipping idiom '{idiom}' due to missing meaning or examples.")
                continue
            # embedding = get_embedding(f'{idiom} - {meaning}')
            main_data.append({
                'Idiom': idiom,
                'Meaning': meaning,
                'Sentence': examples})
            n += 1
            if n % 100 == 0:
                print(f"Processed {n} idioms.")
    return main_data


def add_idiom_embeddings(data, batch_size=300, sleep_time=21, output_dimension=256):
    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        batch_texts = [f"{row['Idiom']} - {row['Meaning']}" for row in batch]
        batch_embeddings = get_embeddings(batch_texts, output_dimension)
        for j, row in enumerate(batch):
            row['embedding'] = batch_embeddings[j]
        print(f"Processed batch {i // batch_size + 1} of {len(data) // batch_size + 1}")
        time.sleep(sleep_time)  # Пауза между запросами к API

    return data


def prepare_idiom_data_for_db(data):
    db_data = []
    for row in data:
        db_data.append((row['Idiom'], row['Meaning'], row['Sentence'], row['embedding']))
    return db_data


def add_idioms_to_db():
    path = settings.BASE_DIR + 'EN_Idioms.json'
    data = read_idiom_json(path)
    data = data
    data_embeddings = add_idiom_embeddings(data)
    print(f"Prepared {len(data_embeddings)} idioms with embeddings.")
    db_data = prepare_idiom_data_for_db(data_embeddings)
    result = Ch.insert('idioms', db_data)
    print(f"Inserted {result} rows into the database.")
