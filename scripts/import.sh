#!/usr/bin/env bash
# Importiert alle Workflows aus workflows/ in den lokalen n8n-Container (gleiche IDs, überschreibt bestehende).
set -euo pipefail
cd "$(dirname "$0")/.."
CONTAINER="${N8N_CONTAINER:-n8n-n8n-1}"
for f in workflows/*.json; do
  docker cp "$f" "$CONTAINER:/tmp/$(basename "$f")" >/dev/null
  docker exec "$CONTAINER" n8n import:workflow --input="/tmp/$(basename "$f")"
done
