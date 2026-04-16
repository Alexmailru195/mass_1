from elasticsearch import Elasticsearch
import os

ES_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
es_client = Elasticsearch([ES_URL])

INDEX_NAME = "messages"


def init_index():
    if not es_client.indices.exists(index=INDEX_NAME):
        es_client.indices.create(index=INDEX_NAME, body={
            "mappings": {
                "properties": {
                    "msg_id": {"type": "integer"},
                    "text": {"type": "text", "analyzer": "standard"},
                    "sender": {"type": "keyword"},
                    "chat_id": {"type": "integer"},
                    "timestamp": {"type": "date"}
                }
            }
        })
        print(">>> Elasticsearch index created!")


def index_message(msg_id: int, text: str, sender: str, chat_id: int, timestamp: str):
    try:
        es_client.index(index=INDEX_NAME, id=msg_id, document={
            "msg_id": msg_id,
            "text": text,
            "sender": sender,
            "chat_id": chat_id,
            "timestamp": timestamp
        })
    except Exception as e:
        print(f"ES Indexing Error: {e}")


def search_messages(query: str, chat_id: int = None):
    must_clauses = [{"match": {"text": query}}]
    if chat_id:
        must_clauses.append({"term": {"chat_id": chat_id}})

    response = es_client.search(index=INDEX_NAME, body={
        "query": {
            "bool": {
                "must": must_clauses
            }
        },
        "size": 50
    })

    hits = response['hits']['hits']
    return [{"id": h['_source']['msg_id'], "text": h['_source']['text'], "sender": h['_source']['sender']} for h in
            hits]