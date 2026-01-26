from opensearchpy import OpenSearch
def create_sparse_ingest_pipeline(client: OpenSearch, sparse_model_id, pipeline_name):
    body = {
        "description": "An sparse encoding ingest pipeline",
        "processors": [
            {
                "sparse_encoding": {
                    "model_id": sparse_model_id,
                    "prune_type": "max_ratio",
                    "prune_ratio": 0.1,
                    "field_map": {
                        "passage_text": "passage_sparse_embedding"
                    }
                }
            }
        ]
    }
    client.transport.perform_request("PUT", url="/_ingest/pipeline/{}".format(pipeline_name), body=body)

def create_sparse_index(client: OpenSearch, index_name, pipeline_name):
    if client.indices.exists(index=index_name):
        print("index already exists")
        return
    body = {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "default_pipeline": pipeline_name
            }
        },
        "mappings": {
            "properties": {
                "doc_id": {"type": "keyword"},
                "s3_bucket": {"type": "keyword"},
                "s3_key": {"type": "keyword"},
                "source": {"type": "keyword"},
                "chunk_id": {"type": "integer"},
                "passage_text": {"type": "text"},
                "ingested_at": {"type": "date"},
                "passage_sparse_embedding": {"type": "rank_features"},
                "meta": {"type": "object", "enabled": True},
            }
        },
    }
    client.transport.perform_request("PUT", url="/{}".format(index_name), body=body)

