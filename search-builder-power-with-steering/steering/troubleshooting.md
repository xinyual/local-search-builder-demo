# Troubleshooting

This file provides a practical checklist for diagnosing failures.

---

## 1) health_check() fails
Symptoms:
- `health_check()` tool errors
- connection refused / timeouts

Checklist:
- Confirm FastAPI is running and reachable (example: `http://127.0.0.1:8080/health`)
- Confirm OpenSearch is reachable from FastAPI container (`OPENSEARCH_URL`)
- If using Docker Compose, confirm services are on the same network

---

## 2) Manifest lookup returns empty / unexpected results
Symptoms:
- `get_manifest(...)` returns no hits
- returned docs do not include expected fields

Checklist:
- Confirm manifest index exists in OpenSearch
- Confirm your ingest workflow writes manifest docs correctly
- Validate mapping/fields in manifest documents:
  - `index_name`
  - `supported_search_methods`
  - optional `topic`, `source`, etc.

---

## 3) Search returns poor results / wrong index
Symptoms:
- irrelevant hits
- wrong index being queried
- wrong mode used

Checklist:
- Ensure you followed manifest-gated search workflow:
  1) health_check()
  2) get_manifest()
  3) select index/mode from manifest output
  4) search()
- Confirm the manifest doc for the selected index contains the correct:
  - `index_name`
  - `supported_search_methods`

---

## 4) Ingest from Local fails
Symptoms:
- file not found
- cannot scan AbstractPath
- empty file list

Checklist:
- Confirm `AbstractPath` exists inside the FastAPI runtime environment
- If FastAPI runs in Docker:
  - confirm the folder is mounted into the container
  - confirm permissions allow reading
- For PoC, use a stable mounted path (e.g. `/data`)

---

## 5) Ingest from S3 fails
Symptoms:
- download errors
- permission denied
- signature mismatch

Checklist:
- Validate AWS credentials and region
- Validate bucket/prefix exist
- Check CloudWatch / FastAPI logs if available
- Retry with `max_files=5` for quick sanity test

---

## Debug Exception Reminder
Direct `search(...)` without `get_manifest()` is only allowed when explicitly requested.
Otherwise, always follow manifest-gated search rules.
