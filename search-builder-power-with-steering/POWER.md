---
name: "search-builder"
displayName: "Local Search Builder"
description: "Prototype search locally via FastAPI (Docling + OpenSearch) through MCP tools."
keywords:
  - opensearch
  - docling
  - ingest
  - search
  - mcp
  - fastapi
  - rag
---

## Overview
This power provides MCP tools to control the Search Builder Application (FastAPI + OpenSearch + Docling).
Use it to ingest data (S3 or local folder) and run search queries.

## Prerequisites
- Search Builder FastAPI is running and reachable (default example: `http://127.0.0.1:8080`)
- OpenSearch is reachable from the FastAPI container
- (Optional) OpenSearch Dashboards is running for manual validation

## Available MCP Tools (Server: search-builder)

### Health
- `health_check()`
  - Check FastAPI + OpenSearch readiness.

### Manifest
- `get_manifest(index_name?, topic?)`
  - Query the manifest index in OpenSearch through FastAPI (`POST /manifest`).
  - If `index_name` is provided, returns the matching manifest doc(s).
  - Else if `topic` is provided, returns indexes relevant to the topic.
  - Else returns top 20 manifest docs.

### Ingest (S3 source)
- `start_ingest_s3(type, bucket, prefix, index_name, delete_local, max_files, aws_region, topic)`
  - Start an async ingest task from S3.
  - Returns: `task_id`

### Ingest (Local source)
- `start_ingest_local(AbstractPath, index_name, type, topic, scan)`
  - Start an async ingest task from a local folder path.
  - Returns: `task_id`

### Task Status
- `get_task(task_id)`
  - Fetch task status/result/error.
- `wait_task(task_id, timeout_s, poll_s)`
  - Poll task until `SUCCEEDED` or `FAILED`.

### Search
- `search(index, query, size, mode, target_field)`
  - Execute search against a specific index.
  - `mode` can be `BM25`, `dense`, or `sparse`.
  - IMPORTANT: Every search MUST follow the Manifest-gated workflow in `steering/manifest.md`.
  - set `target_field` only when you find the index is from json from its manifest.
  
---

## Steering (IMPORTANT)
Before running search, follow the steering rules:

- `steering/manifest.md` (REQUIRED: Manifest-gated Search workflow)
- `steering/ingest.md` (Ingest best practices and constraints)
- `steering/troubleshooting.md` (Common issues & debugging checklist)
