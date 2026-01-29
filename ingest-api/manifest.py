from typing import List

from opensearchpy import OpenSearch, helpers
from sqlite_operations import list_candidate_files
from torchvision.datasets.utils import list_files

MANIFEST_INDEX_NAME = "search_application_manifest"

def create_manifest_index(client: OpenSearch):
    if client.indices.exists(index=MANIFEST_INDEX_NAME):
        return
    index_body = {
        "mappings": {
            "properties": {
                "index_name": {
                    "type": "keyword"
                },
                "source": {
                    "type": "keyword"
                },
                "support_search_methods": {
                    "type": "text"
                },
                "topic": {
                    "type": "text"
                },
                "from_json": {
                    "type": "boolean"
                }
            }
        }
    }
    client.indices.create(
        index=MANIFEST_INDEX_NAME, body=index_body
    )
    return


def get_manifest(client:OpenSearch, index_name: str, topic: str):
    if index_name != None and len(index_name) > 0:
        index_body = {
            "query": {
                "term": {
                    "index_name": {
                        "value": index_name
                    }
                }
            }
        }
        return client.search(index=MANIFEST_INDEX_NAME, body=index_body)
    elif topic != None and len(topic) > 0:
        index_body = {
            "query": {
                "match": {
                    "topic": topic
                }
            }
        }
        return client.search(index=MANIFEST_INDEX_NAME, body=index_body)
    else:
        index_body = {
            "query": {
                "match_all": {}
            },
            "size": 20
        }
        return client.search(index=MANIFEST_INDEX_NAME, body=index_body)

def update_manifest(client:OpenSearch, index_name: str, source: str, support_search_methods: List[str], topic: str):
    candidates = list_candidate_files(source)
    flag = True if candidates[0].endswith(".json") or candidates[0].endswith(".jsonl") else False
    update_body = {
        "index_name": index_name,
        "source": source,
        "support_search_methods": support_search_methods,
        "topic": topic,
        "from_json": flag
    }
    client.index(index=MANIFEST_INDEX_NAME, body=update_body)
