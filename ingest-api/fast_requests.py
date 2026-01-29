from typing import Dict, List, Optional, Iterable, Tuple
from pydantic import BaseModel, Field
from constants import INDEX_NAME_DEFAULT, AWS_REGION

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
    scan: bool = Field(False, description="whether to scan this ingestion")


class GetManifestRequest(BaseModel):
    index_name: str = Field(..., description="the target index name")
    topic: str = Field(..., description="the target topic")


class SearchRequest(BaseModel):
    query: str = Field(..., description="search queries")
    index: str = Field(..., description="target index")
    size: int = Field(..., description="query size")
    mode: str = Field(..., description="the search mode, can be BM25/dense/sparse")
    target_field: str = Field("", description="the target field query on. Only work on index from json files with dynamic mapping")
