#!/usr/bin/env bash
set -euo pipefail

ROOT="/hve-library"
PYTHON_BIN="${HVE_KNOWLEDGE_PYTHON:-/home/hans/.hve-knowledge/venv/bin/python3}"
TIMEOUT_SECONDS="${HVE_INTAKE_TIMEOUT_SECONDS:-300}"
POLL_SECONDS="${HVE_INTAKE_POLL_SECONDS:-5}"
KEEP_ARTIFACTS=0

usage() {
  cat <<'EOF'
Usage: validate-knowledge-intake.sh [--root PATH] [--python PATH] [--keep-artifacts]

Runs an end-to-end Phase 1 intake validation:
1. Clean PDF ingests and appears in LanceDB
2. Duplicate PDF does not add duplicate chunks
3. Corrupt PDF is quarantined without index pollution
4. Manifest ends indexed for the clean PDF
5. Structured logs are validated if intake.jsonl exists
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --keep-artifacts)
      KEEP_ARTIFACTS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ROOT="$(python3 - <<'PY' "$ROOT"
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PREFIX="validate-intake-${TIMESTAMP}-$$"
CLEAN_PDF="${TMP_DIR}/${PREFIX}.pdf"
DUPLICATE_PDF="${TMP_DIR}/${PREFIX}-duplicate.pdf"
CORRUPT_PDF="${TMP_DIR}/${PREFIX}-corrupt.pdf"
LOG_FILE="${TMP_DIR}/validate-knowledge-intake.log"
DOC_ID=""
CHUNK_COUNT=0

cleanup() {
  if [[ "${KEEP_ARTIFACTS}" -eq 0 ]]; then
    rm -rf "${TMP_DIR}"
  else
    echo "KEEP ${TMP_DIR}"
  fi
}
trap cleanup EXIT

cleanup_root_artifacts() {
  local clean_doc_id="$1"
  local corrupt_doc_id="$2"
  local clean_source_path="$3"
  local duplicate_failed_path="$4"
  local corrupt_failed_path="$5"
  "${PYTHON_BIN}" - <<'PY' "${ROOT}" "${clean_doc_id}" "${corrupt_doc_id}" "${clean_source_path}" "${duplicate_failed_path}" "${corrupt_failed_path}"
import json
import sys
from pathlib import Path

import lancedb

root = Path(sys.argv[1])
doc_ids = [value for value in (sys.argv[2], sys.argv[3]) if value]
paths = [Path(value) for value in sys.argv[4:] if value]

for document_id in doc_ids:
    manifest_path = root / "state" / "manifests" / f"{document_id}.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("chunk_path", "extracted_text_path"):
            candidate = payload.get(key)
            if candidate:
                paths.append(Path(candidate))
        for stage in ("extraction", "chunking", "indexing", "finalize"):
            paths.append(root / "state" / "failed" / f"{document_id}-{stage}.json")
        paths.append(manifest_path)

for path in paths:
    if path.exists():
        path.unlink()

db = lancedb.connect(str(root / "index" / "lancedb"))
table_names = set(db.table_names())
if "library_chunks" in table_names and doc_ids:
    table = db.open_table("library_chunks")
    quoted = ", ".join("'" + document_id.replace("'", "''") + "'" for document_id in doc_ids)
    table.delete(f"document_id IN ({quoted})")
PY
}

require_path() {
  if [[ ! -e "$1" ]]; then
    echo "ERROR missing required path: $1" >&2
    exit 1
  fi
}

log() {
  echo "$*" | tee -a "${LOG_FILE}"
}

wait_for_path_gone() {
  local path="$1"
  local waited=0
  while [[ -e "${path}" ]]; do
    if (( waited >= TIMEOUT_SECONDS )); then
      echo "ERROR timed out waiting for ${path} to disappear" >&2
      exit 1
    fi
    sleep "${POLL_SECONDS}"
    waited=$((waited + POLL_SECONDS))
  done
}

wait_for_path_present() {
  local path="$1"
  local waited=0
  while [[ ! -e "${path}" ]]; do
    if (( waited >= TIMEOUT_SECONDS )); then
      echo "ERROR timed out waiting for ${path} to appear" >&2
      exit 1
    fi
    sleep "${POLL_SECONDS}"
    waited=$((waited + POLL_SECONDS))
  done
}

require_path "${PYTHON_BIN}"
require_path "${REPO_DIR}/knowledge/layer/run_intake_pipeline.py"
require_path "${ROOT}/intake/inbox"
require_path "${ROOT}/intake/failed"
require_path "${ROOT}/raw/pdfs"
require_path "${ROOT}/state/manifests"
require_path "${ROOT}/index/lancedb"

python3 - <<'PY' "${CLEAN_PDF}"
from pathlib import Path
import sys

pdf = Path(sys.argv[1])
payload = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 111 >>
stream
BT
/F1 24 Tf
72 720 Td
(Hermes CFO intake validation smoke test.) Tj
0 -32 Td
(Bitcoin treasury, liquidity, and risk controls.) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000010 00000 n 
0000000063 00000 n 
0000000122 00000 n 
0000000248 00000 n 
0000000410 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
480
%%EOF
"""
pdf.write_bytes(payload)
PY

cp "${CLEAN_PDF}" "${DUPLICATE_PDF}"
printf 'not-a-real-pdf\n' > "${CORRUPT_PDF}"

cp "${CLEAN_PDF}" "${ROOT}/intake/inbox/"
log "STEP clean-ingest $(basename "${CLEAN_PDF}")"
"${PYTHON_BIN}" "${REPO_DIR}/knowledge/layer/run_intake_pipeline.py" --root "${ROOT}" | tee -a "${LOG_FILE}"
wait_for_path_gone "${ROOT}/intake/inbox/$(basename "${CLEAN_PDF}")"

mapfile -t CLEAN_META < <("${PYTHON_BIN}" - <<'PY' "${ROOT}" "$(basename "${CLEAN_PDF}")"
import json
import sys
from pathlib import Path

import lancedb

root = Path(sys.argv[1])
pdf_name = sys.argv[2]
manifests = sorted((root / "state" / "manifests").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
target = None
for manifest_path in manifests:
    payload = json.loads(manifest_path.read_text())
    source_path = str(payload.get("source_path", ""))
    if source_path.endswith("/raw/pdfs/" + pdf_name):
        target = (manifest_path.stem, payload)
        break
if target is None:
    raise SystemExit("manifest-not-found")
document_id, manifest = target
db = lancedb.connect(str(root / "index" / "lancedb"))
table = db.open_table("library_chunks")
rows = table.search().where(f"document_id = '{document_id}'").to_list()
print(document_id)
print(len(rows))
print(manifest.get("status"))
print(manifest.get("ingest_status"))
print(manifest.get("source_path"))
PY
)

DOC_ID="${CLEAN_META[0]}"
CHUNK_COUNT="${CLEAN_META[1]}"
STATUS="${CLEAN_META[2]}"
INGEST_STATUS="${CLEAN_META[3]}"
SOURCE_PATH="${CLEAN_META[4]}"

if [[ "${CHUNK_COUNT}" -le 0 ]]; then
  echo "ERROR clean PDF produced zero chunks in LanceDB" >&2
  exit 1
fi
if [[ "${STATUS}" != "indexed" || "${INGEST_STATUS}" != "ingested" ]]; then
  echo "ERROR clean PDF manifest not indexed/ingested: status=${STATUS} ingest_status=${INGEST_STATUS}" >&2
  exit 1
fi
if [[ ! -f "${SOURCE_PATH}" ]]; then
  echo "ERROR archived PDF missing at ${SOURCE_PATH}" >&2
  exit 1
fi
log "PASS clean-ingest document_id=${DOC_ID} chunks=${CHUNK_COUNT}"

cp "${DUPLICATE_PDF}" "${ROOT}/intake/inbox/"
log "STEP duplicate-ingest $(basename "${DUPLICATE_PDF}")"
"${PYTHON_BIN}" "${REPO_DIR}/knowledge/layer/run_intake_pipeline.py" --root "${ROOT}" | tee -a "${LOG_FILE}"
wait_for_path_gone "${ROOT}/intake/inbox/$(basename "${DUPLICATE_PDF}")"
wait_for_path_present "${ROOT}/intake/failed/$(basename "${DUPLICATE_PDF}")"

DUPLICATE_COUNT="$("${PYTHON_BIN}" - <<'PY' "${ROOT}" "${DOC_ID}"
import sys
from pathlib import Path
import lancedb

root = Path(sys.argv[1])
document_id = sys.argv[2]
db = lancedb.connect(str(root / "index" / "lancedb"))
table = db.open_table("library_chunks")
rows = table.search().where(f"document_id = '{document_id}'").to_list()
print(len(rows))
PY
)"
if [[ "${DUPLICATE_COUNT}" != "${CHUNK_COUNT}" ]]; then
  echo "ERROR duplicate ingest changed LanceDB row count: before=${CHUNK_COUNT} after=${DUPLICATE_COUNT}" >&2
  exit 1
fi
log "PASS duplicate-ingest document_id=${DOC_ID} chunks=${DUPLICATE_COUNT}"

cp "${CORRUPT_PDF}" "${ROOT}/intake/inbox/"
log "STEP corrupt-ingest $(basename "${CORRUPT_PDF}")"
set +e
"${PYTHON_BIN}" "${REPO_DIR}/knowledge/layer/run_intake_pipeline.py" --root "${ROOT}" | tee -a "${LOG_FILE}"
CORRUPT_EXIT=$?
set -e
if [[ "${CORRUPT_EXIT}" -eq 0 ]]; then
  echo "ERROR corrupt ingest unexpectedly exited 0" >&2
  exit 1
fi
wait_for_path_gone "${ROOT}/intake/inbox/$(basename "${CORRUPT_PDF}")"
wait_for_path_present "${ROOT}/intake/failed/$(basename "${CORRUPT_PDF}")"

CORRUPT_FAILED="$("${PYTHON_BIN}" - <<'PY' "${ROOT}"
from pathlib import Path
import sys

root = Path(sys.argv[1])
failed = sorted((root / "state" / "failed").glob("*-extraction.json"), key=lambda p: p.stat().st_mtime, reverse=True)
print(failed[0] if failed else "")
PY
)"
if [[ -z "${CORRUPT_FAILED}" ]]; then
  echo "ERROR corrupt ingest did not record extraction failure metadata" >&2
  exit 1
fi
CORRUPT_DOC_ID="$(basename "${CORRUPT_FAILED}")"
CORRUPT_DOC_ID="${CORRUPT_DOC_ID%-extraction.json}"

LOG_PATH="${ROOT}/state/logs/intake.jsonl"
if [[ -f "${LOG_PATH}" ]]; then
  "${PYTHON_BIN}" - <<'PY' "${LOG_PATH}"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
if not lines:
    raise SystemExit("empty-intake-log")
for line in lines[-10:]:
    json.loads(line)
print("PASS structured-log-json")
PY
  log "PASS structured-log-json path=${LOG_PATH}"
else
  log "SKIP structured-log-json path=${LOG_PATH}"
fi

if [[ "${KEEP_ARTIFACTS}" -eq 0 ]]; then
  cleanup_root_artifacts \
    "${DOC_ID}" \
    "${CORRUPT_DOC_ID}" \
    "${SOURCE_PATH}" \
    "${ROOT}/intake/failed/$(basename "${DUPLICATE_PDF}")" \
    "${ROOT}/intake/failed/$(basename "${CORRUPT_PDF}")"
fi

log "PASS validate-knowledge-intake document_id=${DOC_ID} chunks=${CHUNK_COUNT} root=${ROOT}"
