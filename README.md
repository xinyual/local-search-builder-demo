# Local Search Builder (OpenSearch + FastAPI + Docling + MCP)

This repo provides a **self-contained local Search Builder stack** for prototyping search applications:

- **OpenSearch Cluster** (data store + search engine)
- **OpenSearch Dashboards** (UI for validation / manual inspection)
- **FastAPI Ingest/Search Service** (Docling-based parsing + indexing + search endpoints)
- **MCP Server (HTTP / Streamable HTTP)** to integrate with AI IDEs (e.g., Kiro Power)

The goal is to support a milestone-1 workflow:
- Ingest from **local folder** or **S3**
- Extract text with **Docling (no ML models required)**
- Run **BM25** search (and optionally dense/sparse/hybrid later)
- Maintain a **manifest index** to route search execution

---

## Repository Structure

```
code/
  docker-compose.yml

  ingest-api/
    app.py
    requirements.txt
    Dockerfile
    entrypoint.sh

  search-builder-mcp/
    src/index.ts
    package.json
    tsconfig.json
    Dockerfile

  search-builder-power/
    POWER.md
    steering/
      manifest.md
      ingest.md
      troubleshooting.md
    mcp.json
```

---

## Quick Start

### 1) Build Docker images

From the `code/` folder:

```bash
docker compose build
```

### 2) Start the full stack

```bash
docker compose up
```

Or run in background:

```bash
docker compose up -d
```

---

## Services & Ports

| Service | Container | Port | Description |
|--------|-----------|------|-------------|
| OpenSearch | `opensearch-node1` | `9200` | OpenSearch HTTP API |
| OpenSearch Dashboards | `opensearch-dashboards` | `5601` | Dashboards UI |
| FastAPI backend | `ingest-api` | `8080` | Ingest / search REST API |
| MCP server (HTTP) | `search-builder-mcp` | `9000` | MCP endpoint for AI IDE |

### Verify health

FastAPI health:

```bash
curl http://127.0.0.1:8080/health
```

MCP health:

```bash
curl http://127.0.0.1:9000/health
```

---

## Local Ingestion and Mounting

### Why mount is required

When ingesting from **local folders**, the FastAPI service runs **inside Docker**.  
That means it cannot directly access arbitrary host paths unless you mount them into the container.

### Recommended mount strategy

Mount a host directory into the container at a stable path like `/data`.

Example in `docker-compose.yml`:

```yaml
ingest-api:
  volumes:
    - ./local_data:/data:ro
```

This allows the FastAPI service to read local files from:

- Host path: `./local_data`
- Container path: `/data`

✅ **Always pass container-visible paths** to `ingest_from_local`.

---

## Ingest API Usage

### A) Ingest from local folder

**Endpoint**
- `POST /ingest_from_local`

**Example request**
```bash
curl -X POST http://127.0.0.1:8080/ingest_from_local \
  -H 'Content-Type: application/json' \
  -d '{
    "AbstractPath": "/data",
    "index_name": "docs",
    "type": "BM25",
    "topic": ""
  }'
```

It returns a task object:
```json
{ "task_id": "..." }
```

Check task status:

```bash
curl http://127.0.0.1:8080/tasks/<TASK_ID>
```

---

### B) Ingest from S3

**Endpoint**
- `POST /ingest_from_s3`

Example request (credentials must be provided by you):

```bash
curl -X POST http://127.0.0.1:8080/ingest_from_s3 \
  -H 'Content-Type: application/json' \
  -d '{
    "bucket": "YOUR_BUCKET",
    "prefix": "",
    "index_name": "docs",
    "type": "BM25",
    "aws_region": "us-east-1",
    "delete_local": true,
    "max_files": 100,
    "topic": ""
  }'
```

---

## Manifest and Search Routing

This system maintains a **Manifest Index** inside OpenSearch.

Each manifest document represents one ingested index, including:
- `index_name`
- data `source` (local or S3)
- supported search methods (`BM25`, `dense`, `sparse`, ...)
- optional `topic` tags (provided by the AI IDE)

### Query manifest

**Endpoint**
- `POST /manifest`

Example:

```bash
curl -X POST http://127.0.0.1:8080/manifest \
  -H 'Content-Type: application/json' \
  -d '{
    "index_name": "docs",
    "topic": ""
  }'
```

---

## Search API Usage

**Endpoint**
- `POST /search`

Example:

```bash
curl -X POST http://127.0.0.1:8080/search \
  -H 'Content-Type: application/json' \
  -d '{
    "index": "docs",
    "query": "your query here",
    "size": 5,
    "mode": "BM25"
  }'
```

### Required workflow (manifest-gated)

**Every search workflow MUST query the manifest first:**

1) `GET /health`
2) `POST /manifest` (index/topic optional)
3) select `index_name` and `supported_search_methods` from manifest results
4) `POST /search` using the selected `index` and `mode`

**Do NOT hard-code index/mode unless explicitly debugging.**

---

## MCP Server (HTTP / Streamable HTTP)

This repo provides an MCP server over HTTP, designed for AI IDE integration.

- MCP endpoint: `http://127.0.0.1:9000/mcp`
- MCP health: `http://127.0.0.1:9000/health`

### Example: list tools via MCP

```bash
curl -s http://127.0.0.1:9000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/list",
    "params":{}
  }'
```

### Example: call a tool (health_check)

```bash
curl -s http://127.0.0.1:9000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"health_check",
      "arguments":{}
    }
  }'
```

---

## Kiro Power Integration

A Kiro Power is included under:

```
search-builder-power/
```

It defines:
- available MCP tools
- recommended workflows
- steering documents for routing/search gating

### Note on transport

This repo uses **HTTP-based MCP** (not stdio).  
Your AI IDE should connect to:

```
http://127.0.0.1:9000/mcp
```

---

## Troubleshooting

### "ingest_from_local cannot find files"
- Ensure host folder is mounted into the `ingest-api` container
- Use container paths like `/data/...` not host absolute paths

Check mount visibility:

```bash
docker compose exec ingest-api sh -lc "ls -la /data"
```

### "fetch failed" when MCP calls FastAPI
- Ensure `SEARCH_BUILDER_API_BASE` is correct inside MCP container
- In docker-compose, MCP should use service name:

```yaml
SEARCH_BUILDER_API_BASE=http://ingest-api:8080
```

Verify from inside MCP container:

```bash
docker compose exec search-builder-mcp node -e "
fetch('http://ingest-api:8080/health').then(r=>r.text()).then(console.log).catch(console.error)
"
```

### Rebuild cleanly

```bash
docker compose down
docker compose build --no-cache
docker compose up
```

---

## Development Notes

### Rebuild only MCP image

```bash
docker compose build search-builder-mcp
docker compose up -d search-builder-mcp
```

### Rebuild only FastAPI image

```bash
docker compose build ingest-api
docker compose up -d ingest-api
```

---

## License
Apache-2.0 (or your preferred license)
