#!/usr/bin/env bash
# One-click launcher for the 3.3L DTC Troubleshooting Assistant.
#
#   ./run.sh        (or: bash run.sh)
#
# Checks the setup, rebuilds any missing data/index files, downloads the local
# model if needed, then asks for your query and answers it.
set -euo pipefail

cd "$(dirname "$0")"
PY=".venv/bin/python"
export PYTHONPATH=src
export ANONYMIZED_TELEMETRY=False

step() { printf '\n>> %s\n' "$1"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

# 1. Python environment -------------------------------------------------------
if [[ ! -x "$PY" ]]; then
  fail "Python environment .venv not found. Set it up once (see README.md, 'Setup'):
    /usr/bin/python3.12 -m venv .venv
    .venv/bin/pip install --upgrade pip setuptools wheel
    .venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1
    .venv/bin/pip install -r requirements.txt
    CMAKE_ARGS=\"-DGGML_NATIVE=OFF -DGGML_CUDA=OFF -DGGML_BLAS=OFF\" FORCE_CMAKE=1 \\
      .venv/bin/pip install --no-binary :all: llama-cpp-python==0.3.2
  then run ./run.sh again."
fi
"$PY" -c "import pdfplumber, chromadb, rank_bm25, sentence_transformers, llama_cpp" 2>/dev/null \
  || fail "Some Python packages are missing in .venv. Run: .venv/bin/pip install -r requirements.txt"

[[ -f "3.3L DTC Manual.pdf" ]] || fail "The manual '3.3L DTC Manual.pdf' is missing from $(pwd)."

# 2. Parsed manual (gitignored build artifacts) -------------------------------
if [[ ! -f data/dtc_records.jsonl ]]; then
  step "First run: parsing the 545-page manual (about 2 minutes, one time only)..."
  "$PY" src/parse_dtc.py --first 8 --last 545 >/dev/null
  "$PY" src/enrich_images.py >/dev/null
  "$PY" src/schema.py >/dev/null
fi

# 3. Search index (production config: lexicon aliases + cylinder token) --------
if ! "$PY" - <<'EOF' 2>/dev/null
import json, sys
m = json.load(open("index/meta.json"))
ok = m.get("aliases", {}).get("mode") == "bm25" and m.get("bm25", {}).get("cylinder_compound")
sys.exit(0 if ok else 1)
EOF
then
  step "Building the search index (about 30 seconds, one time only)..."
  "$PY" src/build_index.py --rebuild --aliases bm25 --cylinder-token >/dev/null 2>&1 \
    || fail "Index build failed. Run: PYTHONPATH=src $PY src/build_index.py --rebuild --aliases bm25 --cylinder-token"
fi

# 4. Local language model -----------------------------------------------------
MODEL="models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
if [[ ! -f "$MODEL" ]]; then
  step "Downloading the local AI model (~490 MB, one time only)..."
  mkdir -p models
  "$PY" -c "from huggingface_hub import hf_hub_download; hf_hub_download('Qwen/Qwen2.5-0.5B-Instruct-GGUF', 'qwen2.5-0.5b-instruct-q4_k_m.gguf', local_dir='models')" >/dev/null \
    || fail "Model download failed (needs internet once). Exact-code questions still work; symptom questions need the model."
fi

# 5. Ask and answer -----------------------------------------------------------
exec "$PY" src/cli.py
