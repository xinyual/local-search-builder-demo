# Ingest Steering

This file describes how to ingest data correctly for milestone-1.

## Mandatory Pre-check
Before any ingest workflow:
1) Call `health_check()`

If health check fails, stop and surface the error (do not retry blindly).

---

## Ingest Modes (Milestone-1 Recommendation)
For milestone-1, prefer:
- ingestion type: `BM25`
- search mode: `BM25`

Dense/Sparse/Hybrid may exist as extensions but are not the default focus.

---

## Ingest from S3 (Recommended)
Tool:
- `start_ingest_s3(type, bucket, prefix, index_name, delete_local, max_files, aws_region, topic)`

Behavior:
- FastAPI downloads objects from S3 into a **temporary folder inside the container**
- Docling parses locally within the container
- OpenSearch indexing happens inside the same environment
- This flow avoids local file path mapping issues

Notes:
- Only provide `topic` if the user clearly specifies a concrete topic.
- Avoid storing or logging AWS long-lived credentials.

---

## Ingest from Local Folder
Tool:
- `start_ingest_local(AbstractPath, index_name, type, topic)`

### Mandatory Rule (Docker)
Local ingest runs inside the FastAPI container.

So `AbstractPath` MUST be a container path that is accessible to FastAPI.

✅ Recommended convention:
- Mount your host folder into container `/data`
- Always pass `AbstractPath` under `/data`

Examples:
- `AbstractPath="/data"`
- `AbstractPath="/data/my_dataset"`

❌ Do NOT pass host absolute paths like:
- `/Users/user_name/...`
They are not visible inside the container unless mounted.
Notes:
- Only provide `topic` if the user clearly specifies a concrete topic.
- Prefer using a stable mounted root path (e.g., `/data`, `/workspace`) instead of random absolute paths.

---

## Required Ingest Workflow (MUST FOLLOW)
A) Local ingest:
1) `health_check()`
2) `start_ingest_local(...)`
3) `wait_task(task_id)`

B) S3 ingest:
1) `health_check()`
2) `start_ingest_s3(...)`
3) `wait_task(task_id)`

If ingestion fails:
- Always call `get_task(task_id)` and inspect the error trace.
