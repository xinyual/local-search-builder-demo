from opensearchpy import OpenSearch

def create_dense_ingest_pipeline(client: OpenSearch, dense_model_id, pipeline_name):
    body = {
          "description": "A text embedding pipeline",
          "processors": [
            {
              "text_embedding": {
                "model_id": dense_model_id,
                "field_map": {
                  "passage_text": "passage_dense_embedding"
                }
              }
            }
          ]
        }
    client.transport.perform_request("PUT", url="/_ingest/pipeline/{}".format(pipeline_name), body=body)

def create_dense_index(client: OpenSearch, index_name, pipeline_name):
    if client.indices.exists(index=index_name):
        print("index already exists")
        return
    body = {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "knn": True,
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
                "passage_dense_embedding": {
                    "type": "knn_vector",
                    "dimension": 384,
                    "method": {
                      "name": "hnsw",
                      "space_type": "l2",
                      "engine": "lucene",
                      "parameters": {
                        "ef_construction": 128,
                        "m": 24
                      }
                    }
                  },
                "meta": {"type": "object", "enabled": True},
            }
        },
    }
    client.transport.perform_request("PUT", url="/{}".format(index_name), body=body)
