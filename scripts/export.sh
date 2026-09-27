#!/usr/bin/env bash
# Exportiert die Vorrat-Workflows aus dem lokalen n8n-Container nach workflows/.
set -euo pipefail
cd "$(dirname "$0")/.."
CONTAINER="${N8N_CONTAINER:-n8n-n8n-1}"
WORKFLOWS=(
  "dD6BSMITP0JfC72f:00-grocy-einrichten"
  "WI7rA3dd4TMM2WVb:01-ebon-import"
  "2dBOwb9KJDnwi1Id:02-planer"
  "JStsSgy75x6xLQzD:03-telegram-bot"
  "Zo6OQr9lp55H9cjS:04-mhd-waechter"
)
mkdir -p workflows
for pair in "${WORKFLOWS[@]}"; do
  id="${pair%%:*}"; name="${pair##*:}"
  docker exec "$CONTAINER" n8n export:workflow --id="$id" --pretty --output="/tmp/$name.json" >/dev/null
  docker cp "$CONTAINER:/tmp/$name.json" "workflows/$name.json" >/dev/null
  echo "exportiert: $name"
done
