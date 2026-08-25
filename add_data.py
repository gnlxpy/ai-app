import json

import chromadb
from rag import VectorIndex


def load_json(file: str = 'EN_Idioms.json'):
    data_obj = None
    with open(file, 'r') as f:
        data = f.read()
        data_obj = json.loads(data)
    return data_obj


def prepare_data(data_obj: list):
    main_list = []
    idioms_set = set()
    for row in data_obj:
        if row["Idiom"][0] in idioms_set:
            continue
        else:
            idioms_set.add(row["Idiom"][0])
        sentence_text = 'Sentence: '
        sentence_num = 0
        if row["Sentence"]:
            for sentence in row["Sentence"]:
                sentence_num += 1
                sentence_text += f'{sentence_num}) {sentence} '
        else:
            sentence_text += '-'
        row_text = f'Idiom: {row["Idiom"][0]}; Meaning: {row["Meaning"]}; {sentence_text}'
        main_list.append(row_text)
    return main_list


def add_data():
    client = VectorIndex()
    raw_data = load_json()
    data_obj = prepare_data(raw_data)
    print('data_obj', len(data_obj))
    client.add_documents(data_obj)


if __name__ == '__main__':
    add_data()
