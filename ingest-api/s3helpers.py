from botocore.config import Config
import boto3
from typing import Dict, List, Optional, Iterable, Tuple
from constants import S3_MAX_KEYS
import os
from pydantic import BaseModel, Field
from constants import *

class AwsCredentials(BaseModel):
    access_key_id: str
    secret_access_key: str
    session_token: Optional[str] = None

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

def safe_local_path(root_dir: str, s3_key: str) -> str:
    # prevent path traversal; normalize to a safe relative path
    rel = s3_key.lstrip("/").replace("..", "__")
    return os.path.join(root_dir, rel)

