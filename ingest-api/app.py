from pathlib import Path
from uuid import uuid4
import traceback
from lifeSpanInit import *
from ingest import *




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
