import json
import time

from fast_requests import *
from responses import *
from constants import *
from manifest import *
from s3helpers import *
from dense_ingestion_search import *
from hybrid import *
from sparse_ingestion_search import *
from docling_and_chunking import *
from docling.document_converter import DocumentConverter
import shutil
import tempfile
from datetime import datetime, timezone
from sqlite_operations import list_candidate_files, mark_ingested


def ingest_entrance(req, type="BM25", task_id="", source_mode="local"):
    if source_mode != "local":
        return ingest_s3_to_opensearch(req, type=type, task_id=task_id)
    return ingest_local_dir_to_opensearch(req, type=type, task_id=task_id)

def ingest_json_files(all_paths: List[str], index_name: str) -> Tuple[List[str], int, int]:
    all_candidate = []
    failures = 0
    for path in all_paths:
        if path.endswith(".json"):
            try:
                all_candidate.append(
                    {
                        "_index": index_name,
                        "_source": json.load(open(path))
                    }
                )
            except Exception as e:
                failures += 1
                continue
        elif path.endswith("jsonl"):
            with open(path, "r") as f:
                for line in f.readlines():
                    try:
                        all_candidate.append(
                            {
                                "_index": index_name,
                                "_source": json.loads(line)
                            }
                        )
                    except Exception as e:
                        failures += 1
                        continue
    helpers.bulk(get_os_client(), all_candidate)
    return all_paths, len(all_candidate), failures


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
        if req.scan:
            GLOBAL_RESOURCE["watch_map"][req.index_name] = {
                    "index_name": req.index_name,
                    "folder": req.AbstractPath,
                    "type":  req.type,
                    "enabled": True,
                    "interval_s": 1800,
                    "last_scan_ts": time.time(),
                }
            mark_ingested(req.index_name, parsed)

        return LocalIngestResponse(
            AbstractPath=req.AbstractPath,
            index_name=req.index_name,
            parsed=len(parsed),
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
            parsed=len(parsed),
            indexed_chunks=indexed_chunks,
            skipped=skipped,
            failures=failures,
        )
    finally:
        if req.delete_local:
            delete_local_dir(tmpdir)

def _bulk_index_chunks_batched_docling(
    client: OpenSearch,
    index_name: str,
    bucket: str,
    prefix: str,
    local_root: str,
    candidate_list: List[str],
    converter: DocumentConverter,
    batch_size: int = 200,             # OpenSearch bulk batch size (chunks)
    docling_batch_size: int = 1,       # Docling convert batch size (files)
) -> Tuple[List[str], int, int]:
    """
        Batch-convert files with Docling (convert_all), then chunk and bulk index.
        Returns (parsed_files, indexed_chunks, failures).
        """
    flag = True if candidate_list[0].endswith(".json") or candidate_list[0].endswith(".jsonl") else False
    if flag:
        return ingest_json_files(candidate_list, index_name)
    parsed_files = []
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


    def iter_files_in_batches(candidate: List[str], n: int) -> List[List[str]]:
        buf: List[str] = []
        for p in candidate:
            buf.append(p)
            if len(buf) >= n:
                yield buf
                buf = []
        if buf:
            yield buf

    def to_s3_key(path: str) -> str:
        return os.path.relpath(path, local_root).replace("\\", "/")

    now = datetime.now(timezone.utc).isoformat()

    for file_batch in iter_files_in_batches(candidate_list, docling_batch_size):
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
                parsed_files.append(path)
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

def bulk_index_chunks_batched_docling(
    client: OpenSearch,
    index_name: str,
    bucket: str,
    prefix: str,
    local_root: str,
    converter: DocumentConverter,
    batch_size: int = 200,             # OpenSearch bulk batch size (chunks)
    docling_batch_size: int = 1,       # Docling convert batch size (files)
) -> Tuple[List[str], int, int]:
    """
    Batch-convert files with Docling (convert_all), then chunk and bulk index.
    Returns (parsed_files, indexed_chunks, failures).
    """
    all_paths = list_candidate_files(local_root)
    return _bulk_index_chunks_batched_docling(
        client, index_name, bucket, prefix, local_root, all_paths, converter, batch_size, docling_batch_size
    )


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
# Cleanup
# -----------------------------
def delete_local_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def iter_local_files(root_dir: str) -> Iterable[str]:
    for base, _, files in os.walk(root_dir):
        for f in files:
            yield os.path.join(base, f)


def compute_doc_id(bucket: str, key: str) -> str:
    # Stable doc id for dedup
    return f"{bucket}:{key}"


