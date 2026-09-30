#!/usr/bin/env bash
# Wandelt die eBon-PDFs in eBon/ mit derselben n8n-Funktion wie der Import („Text aus PDF lesen“, extractFromFile, joinPages) in Text um
# und legt das Ergebnis in eBon/.text/<name>.txt ab (Prüfstand: rewe-service/tests/test_ebon_pdfs.py). Braucht Docker; kein Bezug zur Produktion.
set -euo pipefail
cd "$(dirname "$0")/.."
IMG="${N8N_IMAGE:-n8nio/n8n:2.40.7}"
NAME="n8n-pdftext-$$"
docker run -d --name "$NAME" -e N8N_ENCRYPTION_KEY=test -e N8N_RUNNERS_ENABLED=false -e N8N_RESTRICT_FILE_ACCESS_TO=/ebon -v "$PWD/eBon:/ebon:ro" -v "$PWD/workflows/tests:/t:ro" --entrypoint sleep "$IMG" 600 >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
docker exec "$NAME" n8n import:workflow --input=/t/pdf_text.workflow.json >/dev/null 2>&1
docker exec "$NAME" n8n execute --id=EbonPdfText0001 > /tmp/pdf_text_$$.json 2>/dev/null || true
mkdir -p eBon/.text
python3 - "$$" <<'PY'
import json, re, sys, pathlib
raw = open(f"/tmp/pdf_text_{sys.argv[1]}.json", encoding="utf-8").read()
start = raw.index("{")
data = json.loads(raw[start:raw.rindex("}") + 1])
runs = data["data"]["resultData"]["runData"]["Ausgabe"][0]["data"]["main"][0]
for item in runs:
    j = item["json"]
    name = pathlib.Path(j["datei"]).stem
    pathlib.Path("eBon/.text", name + ".txt").write_text(j["text"], encoding="utf-8")
    print("eBon/.text/" + name + ".txt", len(j["text"]), "Zeichen")
PY
rm -f /tmp/pdf_text_$$.json
