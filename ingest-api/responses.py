from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class TaskCreateResponse(BaseModel):
    task_id: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # PENDING/RUNNING/SUCCEEDED/FAILED
    result: Optional[dict] = None
    error: Optional[str] = None


class QueryResponse(BaseModel):
    result: Dict[str, Any]



class IngestResponse(BaseModel):
    bucket: str
    prefix: str
    index_name: str
    downloaded: int
    parsed: int
    indexed_chunks: int
    skipped: int
    failures: int

class GetMappingResponse(BaseModel):
    result: Dict[str, Any]

class LocalIngestResponse(BaseModel):
    AbstractPath: str
    index_name: str
    parsed: int
    indexed_chunks: int
    failures: int