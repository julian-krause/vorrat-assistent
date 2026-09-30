#!/usr/bin/env bash
# Führt die Tests der n8n-Code-Knoten im n8n-Image aus (dort ist luxon vorhanden): workflows/tests/run.sh
cd "$(dirname "$0")/.."
docker run --rm -v "$PWD:/w" -e LUXON_PATH=/usr/local/lib/node_modules/n8n/node_modules/luxon --entrypoint node n8nio/n8n:2.40.7 --test /w/tests/*.test.cjs
