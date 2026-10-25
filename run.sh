#!/usr/bin/env bash
# Launcher for the 3.3L DTC Troubleshooting Assistant.
#
#   ./run.sh                   interactive command-line assistant (Phase 7/9.1)
#   ./run.sh demo              serve the demo website + API on 0.0.0.0:8000
#   ./run.sh demo --check      start, verify with the preset smoke test, stop again
#   ./run.sh demo --port 8080  use another port
#
# Checks the setup and rebuilds any missing data/index files first. Nothing here
# changes retrieval, the gate, the index or the records.
set -euo pipefail

cd "$(dirname "$0")"
PY=".venv/bin/python"
export PYTHONPATH=src
export ANONYMIZED_TELEMETRY=False

MODE="cli"
PORT=8000
CHECK=0
if [[ "${1:-}" == "demo" ]]; then
  MODE="demo"
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --check) CHECK=1; shift ;;
      --port)  PORT="${2:?--port needs a number}"; shift 2 ;;
      -h|--help)
        sed -n '2,10p' "$0"; exit 0 ;;
      *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
  done
fi

MODEL="models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
LOG="/tmp/dtc_demo_${PORT}.log"
SERVER_PID=""

step() { printf '\n>> %s\n' "$1"; }
note() { printf '   %s\n' "$1"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------- 1. setup
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

# The LLM is only ever used for optional phrasing, and llama_cpp is imported
# lazily inside Phraser._load(). The demo's own paths are rule-based, so a
# missing llama-cpp-python is a warning there and an error only for the CLI.
"$PY" -c "import pdfplumber, chromadb, rank_bm25, sentence_transformers" 2>/dev/null \
  || fail "Core packages missing in .venv. Run: .venv/bin/pip install -r requirements.txt"
HAVE_LLAMA=1
"$PY" -c "import llama_cpp" 2>/dev/null || HAVE_LLAMA=0

[[ -f "3.3L DTC Manual.pdf" ]] || fail "The manual '3.3L DTC Manual.pdf' is missing from $(pwd)."

# ---------------------------------------------------------- 2. parsed manual
if [[ ! -f data/dtc_records.jsonl ]]; then
  step "First run: parsing the 545-page manual (about 2 minutes, one time only)..."
  "$PY" src/parse_dtc.py --first 8 --last 545 >/dev/null
  "$PY" src/enrich_images.py >/dev/null
  "$PY" src/schema.py >/dev/null
fi

# ------------------------------------------------------------- 3. the index
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

# ----------------------------------------------------------- 4. the model
if [[ "$MODE" == "cli" ]]; then
  if [[ ! -f "$MODEL" ]]; then
    step "Downloading the local AI model (~490 MB, one time only)..."
    mkdir -p models
    "$PY" -c "from huggingface_hub import hf_hub_download; hf_hub_download('Qwen/Qwen2.5-0.5B-Instruct-GGUF', 'qwen2.5-0.5b-instruct-q4_k_m.gguf', local_dir='models')" >/dev/null \
      || fail "Model download failed (needs internet once). Exact-code questions still work; symptom questions need the model."
  fi
  exec "$PY" src/cli.py
fi

# =========================================================== demo mode =====
# 5. synthetic demo data ----------------------------------------------------
if [[ ! -f data/demo/synthetic_fleet_log.csv ]]; then
  step "Generating the synthetic demo data (seeded, a few seconds)..."
  "$PY" scripts/gen_demo_data.py >/dev/null \
    || fail "Demo data generation failed. Run: PYTHONPATH=src $PY scripts/gen_demo_data.py"
fi

if [[ ! -f "$MODEL" || "$HAVE_LLAMA" == "0" ]]; then
  step "Running WITHOUT the local language model."
  note "Every demo path is rule-based and works: fleet, vehicle, advisories,"
  note "candidates, refusals, verify-code, audit and the symptom search itself."
  note "Only the optional 'add AI one-line summary' checkbox needs the model."
fi

# 6. start the server -------------------------------------------------------
stop_server() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$SERVER_PID" 2>/dev/null || true
  fi
}

health_ok() {
  "$PY" - "$1" <<'EOF' 2>/dev/null
import json, sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1] + "/health", timeout=3) as r:
        sys.exit(0 if json.load(r).get("status") == "ok" else 1)
except Exception:
    sys.exit(1)
EOF
}

BASE="http://127.0.0.1:${PORT}"
REUSED=0
if health_ok "$BASE"; then
  step "A demo server is already answering on ${BASE} — reusing it."
  REUSED=1
else
  step "Starting the service on 0.0.0.0:${PORT} ..."
  T0=$(date +%s)
  : > "$LOG"
  "$PY" -m uvicorn app:app --host 0.0.0.0 --port "$PORT" --log-level warning >>"$LOG" 2>&1 &
  SERVER_PID=$!
  trap 'stop_server' EXIT

  ready=0
  for _ in $(seq 1 120); do          # up to ~4 minutes: a cold first start parses nothing
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      printf '\n--- server log ---\n'; tail -25 "$LOG"
      fail "The server exited during start-up (see $LOG)."
    fi
    if health_ok "$BASE"; then ready=1; break; fi
    sleep 2
  done
  [[ "$ready" == "1" ]] || { printf '\n--- server log ---\n'; tail -25 "$LOG";
    fail "The server did not become healthy on ${BASE} (see $LOG)."; }
  note "healthy after $(( $(date +%s) - T0 ))s (pid $SERVER_PID)"
fi

# 7. warm the models --------------------------------------------------------
step "Warming the models (first retrieval pays the embedding cost)..."
"$PY" - "$BASE" <<'EOF' || fail "Warm-up calls failed; the service is up but not answering."
import json, sys, time, urllib.request

base = sys.argv[1]


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"content-type": "application/json"} if data else {})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        payload = json.load(r)
    return payload, (time.perf_counter() - t) * 1000


h, _ = call("GET", "/health")
print(f"   health        : {h['status']}, startup {h['startup_seconds']}s, "
      f"hash {h['determinism_hash']}")
s, ms = call("POST", "/symptom", {"query": "rail pressure sensor short to ground"})
print(f"   /symptom warm : {ms:7.1f} ms  -> {[r['code_full'] for r in s.get('results', [])]}")
v, ms = call("GET", "/vehicle/DEMO-MAT-0001")
print(f"   /vehicle warm : {ms:7.1f} ms  -> {v['worst_severity']}, "
      f"{len(v['episodes'])} episode(s)")
EOF

# 8. the smoke check --------------------------------------------------------
if [[ "$CHECK" == "1" ]]; then
  step "Running the preset smoke test against ${BASE} ..."
  if "$PY" scripts/demo_smoke.py --base "$BASE"; then
    SMOKE=0
  else
    SMOKE=$?
  fi
  if [[ "$REUSED" == "0" ]]; then
    stop_server
    trap - EXIT
    note "server stopped (this was a check run)"
  fi
  if [[ "$SMOKE" == "0" ]]; then
    printf '\n>> DEMO CHECK PASSED — ready to present.\n'
  else
    printf '\n>> DEMO CHECK FAILED — do not present until this is green.\n' >&2
  fi
  exit "$SMOKE"
fi

# 9. tell the presenter where to go ----------------------------------------
cat <<BANNER

============================================================
  DEMO READY
     local      ${BASE}/
BANNER
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  cat <<BANNER
     codespace  https://${CODESPACE_NAME}-${PORT}.app.github.dev/
                (Ports panel -> port ${PORT} -> Visibility: Public for the demo,
                 back to Private afterwards)
BANNER
fi
cat <<BANNER
     server log ${LOG}
     pre-flight ./run.sh demo --check
  Press Ctrl+C to stop.
============================================================
BANNER

if [[ "$REUSED" == "1" ]]; then
  note "This shell did not start the server, so Ctrl+C will not stop it."
  exit 0
fi
wait "$SERVER_PID"
