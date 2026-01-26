#!/usr/bin/env bash
set -euo pipefail

OS_URL="${OPENSEARCH_URL:-http://opensearch-node1:9200}"

echo "[ingest-api] waiting for OpenSearch at ${OS_URL} ..."
for i in $(seq 1 180); do
  if curl -s "${OS_URL}" >/dev/null 2>&1; then
    echo "[ingest-api] OpenSearch reachable."
    break
  fi
  sleep 1
  if [ "$i" -eq 180 ]; then
    echo "[ingest-api] OpenSearch not reachable after 180s" >&2
    exit 1
  fi
done

exec uvicorn app:app --host 0.0.0.0 --port 8080
