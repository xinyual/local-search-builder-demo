from opensearchpy import OpenSearch


def put_config(client: OpenSearch):
    body = {
      "persistent" : {
        "plugins.ml_commons.allow_registering_model_via_url" : True,
        "plugins.ml_commons.only_run_on_ml_node" : False,
        "plugins.ml_commons.native_memory_threshold" : 99,
        "plugins.ml_commons.memory_feature_enabled": True
      }
    }
    client.transport.perform_request(
        "PUT", url="/_cluster/settings/", body=body
    )


def register_dense_model(client: OpenSearch):
    ## current use small one
    body = {
          "name": "huggingface/sentence-transformers/all-MiniLM-L6-v2",
          "version": "1.0.2",
          "model_format": "TORCH_SCRIPT"
        }
    ret = client.transport.perform_request(
        "POST", url="/_plugins/_ml/models/_register", body=body
    )
    return ret["task_id"]

def register_sparse_model(client: OpenSearch):
    body = {
      "name": "amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v2-mini",
      "version": "1.0.0",
      "model_format": "TORCH_SCRIPT"
    }
    ret = client.transport.perform_request(
        "POST", url="/_plugins/_ml/models/_register", body=body
    )
    return ret["task_id"]

def deploy_model(client: OpenSearch, model_id: str):
    ret = client.transport.perform_request(
        "POST", url=f"/_plugins/_ml/models/{model_id}/_deploy"
    )
    return ret["task_id"]

def get_task_status(client: OpenSearch, task_id):
    ret = client.transport.perform_request(
        "GET", url=f"/_plugins/_ml/tasks/{task_id}"
    )
    return ret



