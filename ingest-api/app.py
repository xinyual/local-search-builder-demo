import threading
import os
import re
from langchain_text_splitters import MarkdownHeaderTextSplitter
import json
import time
import shutil
from pathlib import Path
import requests
from contextlib import asynccontextmanager
import tempfile
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, List, Optional, Iterable, Tuple
from sparse_ingestion_search import *
from typing import Any, Dict, Optional
import boto3
from docling_core.transforms.chunker import HybridChunker
from botocore.config import Config
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dense_ingestion_search import *
from hybrid import *
from preparation import *
import asyncio
import traceback

from opensearchpy import OpenSearch, helpers
from manifest import *

from docling.document_converter import DocumentConverter


DATA_ROOT = os.environ.get("DATA_ROOT", "/data")


class TaskCreateResponse(BaseModel):
    task_id: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # PENDING/RUNNING/SUCCEEDED/FAILED
    result: Optional[dict] = None
    error: Optional[str] = None

class QueryResponse(BaseModel):
    result: Dict[str, Any]

async def _set_task(task_id: str, **fields):
    async with TASKS_LOCK:
        TASKS.setdefault(task_id, {})
        TASKS[task_id].update(fields)

TASKS: Dict[str, Dict[str, Any]] = {}
TASKS_LOCK = asyncio.Lock()

TASKS_LOCK = threading.Lock()


def resolve_local_ingest_path(user_path: str) -> str:
    """
    Make sure user_path is inside DATA_ROOT.
    Supports:
      - "/data"
      - "/data/subdir"
      - "subdir"  (treated as DATA_ROOT/subdir)
    """
    root = Path(DATA_ROOT).resolve()

    if not user_path:
        raise ValueError("AbstractPath is empty")

    p = Path(user_path)

    # if relative path, resolve under DATA_ROOT
    if not p.is_absolute():
        p = root / p

    p = p.resolve()

    # prevent path traversal / escaping DATA_ROOT
    if root not in p.parents and p != root:
        raise ValueError(f"AbstractPath must be under DATA_ROOT={root}. Got: {p}")

    if not p.exists():
        raise ValueError(f"AbstractPath not found in container: {p}")

    return str(p)

def set_task_sync(task_id: str, **fields):
    if not task_id:
        return
    with TASKS_LOCK:
        TASKS.setdefault(task_id, {})
        TASKS[task_id].update(fields)

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
ALLOWED_EXT = {".pdf", ".txt", ".md", ".html", ".htm", ".docx", ".pptx", ".png"}
GLOBAL_RESOURCE = {}

TASK_STATUS = {}

class AwsCredentials(BaseModel):
    access_key_id: str
    secret_access_key: str
    session_token: Optional[str] = None

# -----------------------------
# Models
# -----------------------------
class IngestRequest(BaseModel):
    bucket: str = Field(..., description="S3 bucket name")
    prefix: str = Field("", description="Optional prefix within the bucket")
    index_name: str = Field(INDEX_NAME_DEFAULT, description="OpenSearch index name")
    delete_local: bool = Field(True, description="Whether to delete local files after ingest")
    max_files: Optional[int] = Field(None, description="Optional cap for number of files to ingest (PoC safety)")
    aws_region: str = AWS_REGION
    type: str = Field("BM25", description="the ingestion type, can be BM25/dense/sparse")
    topic: str = Field("", description="the topic of this ingestion")

class LocalIngestRequest(BaseModel):
    AbstractPath: str = Field(..., description="S3 bucket name")
    index_name: str = Field(INDEX_NAME_DEFAULT, description="OpenSearch index name")
    type: str = Field("BM25", description="the ingestion type, can be BM25/dense/sparse")
    topic: str = Field("", description="the topic of this ingestion")


class GetManifestRequest(BaseModel):
    index_name: str = Field(..., description="the target index name")
    topic: str = Field(..., description="the target topic")


class SearchRequest(BaseModel):
    query: str = Field(..., description="search queries")
    index: str = Field(..., description="target index")
    size: int = Field(..., description="query size")
    mode: str = Field(..., description="the search mode, can be BM25/dense/sparse")

class IngestResponse(BaseModel):
    bucket: str
    prefix: str
    index_name: str
    downloaded: int
    parsed: int
    indexed_chunks: int
    skipped: int
    failures: int

class LocalIngestResponse(BaseModel):
    AbstractPath: str
    index_name: str
    parsed: int
    indexed_chunks: int
    failures: int


# -----------------------------
# OpenSearch
# -----------------------------
def get_os_client() -> OpenSearch:
    return OpenSearch(OPENSEARCH_URL, verify_certs=False, ssl_show_warn=False)


def ensure_index(client: OpenSearch, index_name: str, type: str) -> None:
    """Create a simple text index if not exists."""
    if type == "sparse":
        if GLOBAL_RESOURCE.get(SPARSE_MODEL_ID, "").startswith("deploy") or GLOBAL_RESOURCE.get(SPARSE_MODEL_ID, "").startswith("download"):
            raise Exception("sparse model is still preparing")
        if GLOBAL_RESOURCE.get(SPARSE_INGEST_PIPELINE, "") == "":
            create_sparse_ingest_pipeline(client, GLOBAL_RESOURCE.get(SPARSE_MODEL_ID), SPARSE_INGEST_PIPELINE)
            GLOBAL_RESOURCE[SPARSE_INGEST_PIPELINE] = SPARSE_INGEST_PIPELINE
        create_sparse_index(client, index_name, SPARSE_INGEST_PIPELINE)
        return
    elif type == "dense":
        if GLOBAL_RESOURCE.get(DENSE_MODEL_ID, "").startswith("deploy") or GLOBAL_RESOURCE.get(DENSE_MODEL_ID, "").startswith("download"):
            raise Exception("dense model is still preparing")
        if GLOBAL_RESOURCE.get(DENSE_INGEST_PIPELINE, "") == "":
            create_dense_ingest_pipeline(client, GLOBAL_RESOURCE.get(DENSE_MODEL_ID), DENSE_INGEST_PIPELINE)
            GLOBAL_RESOURCE[DENSE_INGEST_PIPELINE] = DENSE_INGEST_PIPELINE
        create_dense_index(client, index_name, DENSE_INGEST_PIPELINE)
        return
    elif type == "hybrid":
        if GLOBAL_RESOURCE.get(SPARSE_MODEL_ID, "").startswith("deploy") or GLOBAL_RESOURCE.get(SPARSE_MODEL_ID, "").startswith("download"):
            raise Exception("sparse model is still preparing")
        if GLOBAL_RESOURCE.get(DENSE_MODEL_ID, "").startswith("deploy") or GLOBAL_RESOURCE.get(DENSE_MODEL_ID, "").startswith("download"):
            raise Exception("dense model is still preparing")
        if GLOBAL_RESOURCE.get(DENSE_INGEST_PIPELINE, "") == "":
            create_hybrid_ingest_pipeline(client, GLOBAL_RESOURCE.get(DENSE_MODEL_ID), GLOBAL_RESOURCE.get(SPARSE_MODEL_ID),  HYBRID_INGEST_PIPELINE)
            GLOBAL_RESOURCE[HYBRID_INGEST_PIPELINE] = HYBRID_INGEST_PIPELINE
        create_hybrid_index(client, index_name, HYBRID_INGEST_PIPELINE)
        return
    if client.indices.exists(index=index_name):
        print("index already exists")
        return
    body = {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
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
                "meta": {"type": "object", "enabled": True},
            }
        },
    }
    client.indices.create(index=index_name, body=body)


# -----------------------------
# S3 download
# -----------------------------
def make_s3_client(region: str):
    cfg = Config(
        region_name=region,
        retries={"max_attempts": 10, "mode": "standard"},
    )
    return boto3.client(
        "s3",
        region_name=region,
        config=cfg,
    )



def list_s3_objects(bucket: str, prefix: str, s3) -> Iterable[Dict]:
    """Generator of S3 objects under prefix."""
    kwargs = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": S3_MAX_KEYS}
    token = None
    while True:
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            yield obj
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break


def safe_local_path(root_dir: str, s3_key: str) -> str:
    # prevent path traversal; normalize to a safe relative path
    rel = s3_key.lstrip("/").replace("..", "__")
    return os.path.join(root_dir, rel)


def download_s3_prefix(bucket: str, prefix: str, local_dir: str, s3, max_files: Optional[int] = None) -> Tuple[int, int]:
    """
    Download all objects under s3://bucket/prefix to local_dir.
    Returns (downloaded_count, skipped_count).
    """
    downloaded = 0
    skipped = 0
    for obj in list_s3_objects(bucket, prefix, s3):
        key = obj["Key"]
        # skip "folders"
        if key.endswith("/"):
            skipped += 1
            continue
        ext = os.path.splitext(key)[1].lower()
        if ext and ext not in ALLOWED_EXT:
            skipped += 1
            continue

        dst = safe_local_path(local_dir, key)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        print("start download s3://{}/{} to {}".format(bucket, key, dst))
        s3.download_file(bucket, key, dst)
        downloaded += 1

        if max_files is not None and downloaded >= max_files:
            break
    print("download {} objects from {}".format(downloaded, bucket))
    return downloaded, skipped


# -----------------------------
# Docling parse + chunk
# -----------------------------
def parse_with_docling(converter: DocumentConverter, path: str) -> List[Any]:
    """
    Return a text/markdown string extracted by Docling.
    For PoC: export Markdown (usually better structured for RAG/indexing).
    """
    result = converter.convert(path)
    doc = result.document
    header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3"),
        ("####", "h4"),
        ("#####", "h5")
        ]
    )
    md_header_splits = header_splitter.split_text(doc.export_to_markdown())
    return md_header_splits

def chunk_by_docling_chunker(doc):
    chunker = HybridChunker(merge_list_items=True)
    chunks = list(chunker.chunk(dl_doc=doc))
    res = []
    for chunk in chunks:
        meta = chunk.meta
        headings = meta.headings if meta and meta.headings else []
        res.append({"text": chunker.contextualize(chunk), "path": " ".join(headings)})
    return res

def chunk_text(md: str, max_chars: int = 4500, overlap: int = 200) -> List[str]:
    """
    Simple character-based chunker (PoC). Replace with token-based chunking later.
    """

    md = (md or "").strip()
    if not md:
        return []
    chunks = []
    header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3"),
        ("####", "h4"),
        ("#####", "h5")
       ]
    )
    md_header_splits = header_splitter.split_text(md)
    for split in md_header_splits:
        text = split.page_content
        i = 0
        n = len(text)
        while i < n:
            j = min(n, i + max_chars)
            chunks.append({"text": text[i:j], "path": " > ".join([split.metadata.get(k) for k in ["h1","h2","h3","h4", "h5"] if split.metadata.get(k)])})
            if j == n:
                break
            i = max(0, j - overlap)
    return chunks


def iter_local_files(root_dir: str) -> Iterable[str]:
    for base, _, files in os.walk(root_dir):
        for f in files:
            yield os.path.join(base, f)


def compute_doc_id(bucket: str, key: str) -> str:
    # Stable doc id for dedup
    return f"{bucket}:{key}"



# -----------------------------
# Cleanup
# -----------------------------
def delete_local_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def wait_opensearch():
    for _ in range(180):
        try:
            r = requests.get(OPENSEARCH_URL, timeout=1)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("OpenSearch not reachable")

async def wait_to_deploy_model_bg(task_id: str, type_str: str):
    model_id = ""

    try:
        # 1) wait register/download task
        while True:
            task_status = await asyncio.to_thread(get_task_status, get_os_client(), task_id)

            state = task_status.get("state")
            if state == "COMPLETED":
                model_id = task_status["model_id"]
                break
            elif state == "FAILED":
                GLOBAL_RESOURCE[type_str] = task_status.get("error", "unknown error")
                return

            await asyncio.sleep(20)

        # 2) deploy model
        deploy_model_task = await asyncio.to_thread(deploy_model, get_os_client(), model_id)
        GLOBAL_RESOURCE[type_str] = f"deploy model with task id: {deploy_model_task}"

        # 3) wait deploy task
        while True:
            task_status = await asyncio.to_thread(get_task_status, get_os_client(), deploy_model_task)

            state = task_status.get("state")
            if state == "COMPLETED":
                GLOBAL_RESOURCE[type_str] = model_id
                if type_str == DENSE_MODEL_ID:
                    GLOBAL_RESOURCE[DENSE_QUERY_MODEL_ID] = model_id
                return
            elif state == "FAILED":
                GLOBAL_RESOURCE[type_str] = task_status.get("error", "unknown error")
                return

            await asyncio.sleep(20)

    except asyncio.CancelledError:
        GLOBAL_RESOURCE[type_str] = "cancelled"
        raise
    except Exception as e:
        GLOBAL_RESOURCE[type_str] = f"exception: {repr(e)}"
        return

async def init_things_bg():
    put_config(get_os_client())
    sparse_model_task_id = await asyncio.to_thread(register_sparse_model, get_os_client())
    dense_model_task_id  = await asyncio.to_thread(register_dense_model,  get_os_client())

    GLOBAL_RESOURCE[SPARSE_MODEL_ID] = f"downloading with task id: {sparse_model_task_id}"
    GLOBAL_RESOURCE[DENSE_MODEL_ID] = f"downloading with task id: {dense_model_task_id}"
    GLOBAL_RESOURCE[DENSE_QUERY_MODEL_ID] = f"downloading with task id: {dense_model_task_id}"

    sparse_task = asyncio.create_task(
        wait_to_deploy_model_bg(sparse_model_task_id, SPARSE_MODEL_ID),
        name="wait_sparse_model"
    )
    dense_task = asyncio.create_task(
        wait_to_deploy_model_bg(dense_model_task_id, DENSE_MODEL_ID),
        name="wait_dense_model"
    )

    await asyncio.to_thread(create_manifest_index, get_os_client())

    return [sparse_task, dense_task]

@asynccontextmanager
async def lifespan(app: FastAPI):
    converter = DocumentConverter()
    GLOBAL_RESOURCE["converter"] = converter

    app.state.bg_tasks = []
    bg_tasks = await init_things_bg()
    app.state.bg_tasks.extend(bg_tasks)

    yield

    for t in app.state.bg_tasks:
        t.cancel()
    await asyncio.gather(*app.state.bg_tasks, return_exceptions=True)


app = FastAPI(lifespan=lifespan)


# -----------------------------
# Orchestration
# -----------------------------
def bulk_index_chunks_batched_docling(
    client: OpenSearch,
    index_name: str,
    bucket: str,
    prefix: str,
    local_root: str,
    converter: DocumentConverter,
    batch_size: int = 200,             # OpenSearch bulk batch size (chunks)
    docling_batch_size: int = 1,       # Docling convert batch size (files)
) -> Tuple[int, int, int]:
    """
    Batch-convert files with Docling (convert_all), then chunk and bulk index.
    Returns (parsed_files, indexed_chunks, failures).
    """
    parsed_files = 0
    indexed_chunks = 0
    failures = 0
    actions = []

    def flush():
        nonlocal indexed_chunks, actions
        if not actions:
            return
        helpers.bulk(client, actions, request_timeout=120)
        indexed_chunks += len(actions)
        actions = []
    print("local path is: " + local_root)
    def iter_files_in_batches(root: str, n: int) -> List[List[str]]:
        buf: List[str] = []
        for p in iter_local_files(root):
            buf.append(p)
            if len(buf) >= n:
                yield buf
                buf = []
        if buf:
            yield buf

    # 一次性计算 s3_key / doc_id 等（避免重复 os.path 操作）
    def to_s3_key(path: str) -> str:
        return os.path.relpath(path, local_root).replace("\\", "/")

    now = datetime.now(timezone.utc).isoformat()

    for file_batch in iter_files_in_batches(local_root, docling_batch_size):
        try:
            print("convert {} files".format(len(file_batch)))
            results = converter.convert_all(file_batch)
        except Exception as e:
            print("error is:" + str(e))
            failures += len(file_batch)
            continue

        for path, res in zip(file_batch, results):
            try:
                doc = getattr(res, "document", None)
                if doc is None:
                    failures += 1
                    continue
                chunks = chunk_by_docling_chunker(doc)
                parsed_files += 1
            except Exception as e:
                print(str(e))
                failures += 1
                continue

            s3_key = to_s3_key(path)
            doc_id = compute_doc_id(bucket, s3_key)
            source = f"s3://{bucket}/{s3_key}" if len(bucket) > 0 else path
            for cid, c in enumerate(chunks):
                actions.append(
                    {
                        "_index": index_name,
                        "_source": {
                            "doc_id": doc_id,
                            "s3_bucket": bucket,
                            "s3_key": s3_key,
                            "source": f"s3://{bucket}/{s3_key}",
                            "chunk_id": cid,
                            "passage_text": c.get("text"),
                            "section": c.get("path"),
                            "ingested_at": now,
                            "meta": {
                                "prefix": prefix,
                                "local_path": path,
                            },
                        },
                    }
                )
                if len(actions) >= batch_size:
                    flush()

    flush()
    client.indices.refresh(index=index_name)
    return parsed_files, indexed_chunks, failures

def ingest_local_dir_to_opensearch(req: LocalIngestRequest, type="BM25", task_id="") -> LocalIngestResponse:
    os_client = get_os_client()
    ensure_index(os_client, req.index_name, type)
    converter = GLOBAL_RESOURCE.get("converter")
    try:
        set_task_sync(task_id, status="converting and bulking")
        parsed, indexed_chunks, failures = bulk_index_chunks_batched_docling(
            client=os_client,
            index_name=req.index_name,
            bucket="",
            prefix="",
            local_root=req.AbstractPath,
            converter=converter,
            batch_size=200
        )
        update_manifest(get_os_client(), index_name=req.index_name, source=req.AbstractPath, support_search_methods=["BM25"]
                        , topic=req.topic)

        return LocalIngestResponse(
            AbstractPath=req.AbstractPath,
            index_name=req.index_name,
            parsed=parsed,
            indexed_chunks=indexed_chunks,
            failures=failures,
        )
    except Exception as e:
        print(str(e))


def ingest_s3_to_opensearch(req: IngestRequest, type="BM25", task_id="") -> IngestResponse:
    s3 = make_s3_client(req.aws_region)
    os_client = get_os_client()
    try:
        ensure_index(os_client, req.index_name, type)
    except Exception as err:
        raise err

    tmpdir = tempfile.mkdtemp(prefix="rag_ingest_")
    downloaded = skipped = 0
    parsed = indexed_chunks = failures = 0

    try:
        set_task_sync(task_id, status="downloading files")

        downloaded, skipped = download_s3_prefix(
            bucket=req.bucket,
            prefix=req.prefix or "",
            local_dir=tmpdir,
            s3=s3,
            max_files=req.max_files,
        )

        converter = GLOBAL_RESOURCE.get("converter")

        set_task_sync(task_id, status="converting and bulking")

        parsed, indexed_chunks, failures = bulk_index_chunks_batched_docling(
            client=os_client,
            index_name=req.index_name,
            bucket=req.bucket,
            prefix=req.prefix or "",
            local_root=tmpdir,
            converter=converter,
            batch_size=200
        )

        update_manifest(get_os_client(), index_name=req.index_name, source=req.bucket, support_search_methods=["BM25"]
                        , topic=req.topic)

        return IngestResponse(
            bucket=req.bucket,
            prefix=req.prefix or "",
            index_name=req.index_name,
            downloaded=downloaded,
            parsed=parsed,
            indexed_chunks=indexed_chunks,
            skipped=skipped,
            failures=failures,
        )
    finally:
        if req.delete_local:
            delete_local_dir(tmpdir)

def ingest_entrance(req, type="BM25", task_id="", source_mode="local"):
    if source_mode != "local":
        return ingest_s3_to_opensearch(req, type=type, task_id=task_id)
    return ingest_local_dir_to_opensearch(req, type=type, task_id=task_id)

async def run_ingest_task(task_id: str, req, mode: str, source_mode: str):
    set_task_sync(task_id, status="RUNNING", result=None, error=None)

    try:
        result = await asyncio.to_thread(ingest_entrance, req, mode, task_id, source_mode)
        set_task_sync(task_id, status="SUCCEEDED", result=result.dict() if hasattr(result, "dict") else result)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        set_task_sync(task_id, status="FAILED", error=err)



# -----------------------------
# FastAPI
# -----------------------------
print("start")
app = FastAPI(title="S3 -> Docling -> OpenSearch Ingest API", lifespan=lifespan)

@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: str):
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if t is None:
            raise HTTPException(status_code=404, detail="task_id not found")
        t = dict(t)

    return TaskStatusResponse(
        task_id=task_id,
        status=t.get("status", "PENDING"),
        result=t.get("result"),
        error=t.get("error"),
    )

@app.get("/health")
def health():
    return {"ok": True, "opensearch": OPENSEARCH_URL, SPARSE_MODEL_ID: GLOBAL_RESOURCE.get(SPARSE_MODEL_ID, ""),
            DENSE_MODEL_ID: GLOBAL_RESOURCE.get(DENSE_MODEL_ID, ""),
            DENSE_QUERY_MODEL_ID: GLOBAL_RESOURCE.get(DENSE_QUERY_MODEL_ID, "")}

@app.post("/manifest", response_model=QueryResponse)
def get_manifest_request(req: GetManifestRequest):
    return QueryResponse(result=get_manifest(get_os_client(), req.index_name, req.topic))

@app.post("/ingest_from_s3", response_model=TaskCreateResponse)
async def ingest_async_from_s3(req: IngestRequest):
    task_id = str(uuid4())
    set_task_sync(task_id, status="PENDING")

    asyncio.create_task(run_ingest_task(task_id, req, mode=req.type, source_mode='s3'))

    return TaskCreateResponse(task_id=task_id)

@app.post("/ingest_from_local", response_model=TaskCreateResponse)
async def ingest_async_from_local(req: LocalIngestRequest):
    task_id = str(uuid4())
    set_task_sync(task_id, status="PENDING")


    try:
        resolved = resolve_local_ingest_path(req.AbstractPath)
    except Exception as e:
        set_task_sync(task_id, status="FAILED", error=str(e))
        return TaskCreateResponse(task_id=task_id)
    print("resolved path is: " + resolved)
    # overwrite path with resolved one
    req.AbstractPath = resolved

    asyncio.create_task(run_ingest_task(task_id, req, mode=req.type, source_mode='local'))

    return TaskCreateResponse(task_id=task_id)

@app.post("/search", response_model=QueryResponse)
def search(req: SearchRequest):
    if req.mode == "dense":
        query_body = {
            "_source": {
                "excludes": ["passage_sparse_embedding", "passage_dense_embedding"]
            },
            "query": {
                "neural": {
                    "passage_dense_embedding": {
                        "query_text": req.query,
                        "model_id": GLOBAL_RESOURCE.get(DENSE_QUERY_MODEL_ID),
                        "k": 10
                    }
                }
            },
            "size": req.size
        }
    elif req.mode == "sparse":
        query_body = {
            "_source": {
                "excludes": ["passage_sparse_embedding", "passage_dense_embedding"]
            },
            "query": {
                "neural_sparse": {
                    "passage_sparse_embedding": {
                        "query_text": req.query
                    }
                }
            },
            "size": req.size
        }
    else:
        query_body = {
            "query": {
                "match":{
                    "passage_text": req.query
                }
            },
            "size": req.size
        }
    ret = get_os_client().transport.perform_request(
        "POST", url="/{}/_search".format(req.index), body=query_body
    )
    return QueryResponse(result=ret)
