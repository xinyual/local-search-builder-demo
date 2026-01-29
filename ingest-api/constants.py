import os
from typing import Any, Dict, Optional
import threading
from opensearchpy import OpenSearch
import asyncio

# -----------------------------
# Config
# -----------------------------
OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200").rstrip("/")
INDEX_NAME_DEFAULT = os.environ.get("INDEX_NAME", "docs")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_MAX_KEYS = int(os.environ.get("S3_MAX_KEYS", "1000"))
DOWNLOAD_CONCURRENCY = int(os.environ.get("DOWNLOAD_CONCURRENCY", "10"))

SPARSE_INGEST_PIPELINE = "sparse_ingest_pipeline"
SPARSE_MODEL_ID = "sparse_model_id"
DENSE_INGEST_PIPELINE = "dense_ingest_pipeline"
DENSE_MODEL_ID = "dense_model_id"
DENSE_QUERY_MODEL_ID = "dense_query_model_id"
HYBRID_INGEST_PIPELINE = "hybrid_ingest_pipeline"

# A small allowlist for "mainstream text docs"
ALLOWED_EXT = {".pdf", ".txt", ".md", ".html", ".htm", ".docx", ".pptx"}
ALLOWED_EXT_FOR_JSON = {".json", ".jsonl"}
GLOBAL_RESOURCE = {}

TASK_STATUS = {}

TASKS: Dict[str, Dict[str, Any]] = {}
TASKS_LOCK = threading.Lock()

DATA_ROOT = os.environ.get("DATA_ROOT", "/data")

WATCH_LOCK = asyncio.Lock()

# -----------------------------
# OpenSearch
# -----------------------------
def get_os_client() -> OpenSearch:
    return OpenSearch(OPENSEARCH_URL, verify_certs=False, ssl_show_warn=False)


def set_task_sync(task_id: str, **fields):
    if not task_id:
        return
    with TASKS_LOCK:
        TASKS.setdefault(task_id, {})
        TASKS[task_id].update(fields)
