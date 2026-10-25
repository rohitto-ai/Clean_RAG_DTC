# Phase 10.5 — Demo runbook

_2026-10-25 · branch `phase10-demo` · launcher hardening only — retrieval, gate, index and records are unchanged_

Everything a presenter needs: one command to start, one to verify, a laptop fallback with no
internet, the Codespace checklist, and what to do when it breaks on stage.

---

## 1. The two commands

```bash
./run.sh demo --check      # pre-flight: start, verify, stop. Exit 0 = safe to present
./run.sh demo              # start and keep serving on 0.0.0.0:8000
```

`./run.sh demo` does, in order:

1. checks `.venv` and the core packages;
2. parses the manual if `data/dtc_records.jsonl` is missing (~2 min, one time);
3. **rebuilds `index/` if it is missing or not the production configuration** (`--aliases bm25
   --cylinder-token`, ~30 s);
4. generates `data/demo/` if the synthetic feed is missing (seeded, a few seconds);
5. starts `uvicorn app:app --host 0.0.0.0 --port 8000` and **waits until `GET /health` reports
   `ok`** (it tails the server log and stops with a clear error if start-up dies);
6. **warms the models** with one `POST /symptom` and one `GET /vehicle/DEMO-MAT-0001`, so the
   first click in front of the audience is not the one that pays the embedding cost;
7. prints the local URL, the Codespace URL, the server log path and the pre-flight command.

Typical output:

```
>> Starting the service on 0.0.0.0:8000 ...
   healthy after 9s (pid 8545)
>> Warming the models (first retrieval pays the embedding cost)...
   health        : ok, startup 5.8s, hash ffff9bc707d8754d
   /symptom warm :    51.2 ms  -> ['P0192-00', 'P0193-00', 'P0088-00']
   /vehicle warm :     3.6 ms  -> HIGH, 1 episode(s)

============================================================
  DEMO READY
     local      http://127.0.0.1:8000/
     codespace  https://<name>-8000.app.github.dev/
     server log /tmp/dtc_demo_8000.log
     pre-flight ./run.sh demo --check
  Press Ctrl+C to stop.
============================================================
```

`--check` does all of the above, then runs `scripts/demo_smoke.py` against the running server,
**stops the server it started**, and exits with the smoke test's status — so it can be run
repeatedly and wired into CI:

```
==== DEMO SMOKE: 43/43 passed ====
   server stopped (this was a check run)

>> DEMO CHECK PASSED — ready to present.
```

Verified twice from a clean shell (`env -i`), both exit 0. A failure exits non-zero and prints
`DEMO CHECK FAILED — do not present until this is green.` An unreachable server is reported as
a clean FAIL, not a traceback.

Other flags: `--port N` to move off 8000. If a healthy server is already on the port, the script
says so and reuses it rather than failing — and in that case `--check` leaves it running.

---

## 2. Local fallback: a Windows laptop with no internet

Use this when the Codespace is unavailable. **Everything below except the one-time downloads
works fully offline.** Do the downloads while you still have internet, then carry the folder.

### 2a. Fastest path — no internet, no LLM (recommended for the viva)

The demo's own paths are **rule-based**: fleet, vehicle, advisories, candidates, refusals,
verify-code, audit, and the symptom search itself (dense + BM25 retrieval). The local language
model is used **only** for the optional "add AI one-line summary" checkbox, and `llama_cpp` is
imported lazily, so neither the model file nor `llama-cpp-python` needs to exist.

What to copy onto a USB stick from a working machine:

| copy | why | size |
|---|---|---|
| the whole repository folder | code, reports, `data/demo/` | ~40 MB |
| `index/` | the built search index — skips a 30 s rebuild and the PDF parse | ~5 MB |
| `data/dtc_records.jsonl` + `data/dtc_raw.jsonl` + `data/dtc_enriched.jsonl` | the parsed manual — skips the ~2 min parse | ~6 MB |
| `3.3L DTC Manual.pdf` | only needed if you must re-parse | ~9 MB |
| the Python 3.12 installer and a wheel cache (below) | offline install | ~400 MB |
| *(optional)* `models/qwen2.5-0.5b-instruct-q4_k_m.gguf` | only for AI summaries | 490 MB |

**On a machine with internet**, build a wheel cache for Windows:

```powershell
py -3.12 -m pip download -d wheels --index-url https://download.pytorch.org/whl/cpu torch==2.5.1
py -3.12 -m pip download -d wheels -r requirements.txt
```

**On the offline laptop:**

```powershell
# 1. Python 3.12 (NOT 3.13/3.14 - several dependencies have no wheels there).
#    Run the python-3.12.x-amd64.exe installer, tick "Add python.exe to PATH".
py -3.12 --version                      # expect Python 3.12.x

# 2. create the environment inside the repo folder
cd C:\path\to\Clean_RAG_DTC
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip setuptools wheel --no-index --find-links wheels

# 3. install, offline, from the wheel cache
.\.venv\Scripts\pip install --no-index --find-links wheels torch==2.5.1
.\.venv\Scripts\pip install --no-index --find-links wheels -r requirements.txt

# 4. confirm the core imports (llama_cpp is deliberately NOT in this list)
.\.venv\Scripts\python -c "import pdfplumber, chromadb, rank_bm25, sentence_transformers, openpyxl; print('ok')"
```

> **The embedder must already be on disk.** `all-MiniLM-L6-v2` is downloaded by
> `sentence-transformers` on first use. Copy the Hugging Face cache from the online machine —
> `%USERPROFILE%\.cache\huggingface` (Linux: `~/.cache/huggingface`) — or set
> `HF_HUB_OFFLINE=1` after copying it. Without it, retrieval cannot start.

Then start the demo. `run.sh` is bash; on Windows use Git Bash, or run the three steps directly:

```powershell
# Git Bash:
./run.sh demo --check && ./run.sh demo

# or plain PowerShell, without run.sh:
$env:PYTHONPATH="src"; $env:ANONYMIZED_TELEMETRY="False"
.\.venv\Scripts\python scripts\gen_demo_data.py      # only if data\demo\ is empty
.\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. If `index/` was copied, start-up is ~6 s; if not, the first run
rebuilds it (~30 s) and re-parses the manual if the records are missing (~2 min).

### 2b. Full path — with the LLM

Only needed to demonstrate the AI summary checkbox. `llama-cpp-python` ships Windows wheels, so
the Linux source build is not required:

```powershell
.\.venv\Scripts\pip install --no-index --find-links wheels llama-cpp-python==0.3.2
mkdir models
# copy qwen2.5-0.5b-instruct-q4_k_m.gguf into models\
```

On Linux the wheel index serves a musl build that will not load, hence the source build in
`README.md`:

```bash
CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_CUDA=OFF -DGGML_BLAS=OFF" FORCE_CMAKE=1 \
  .venv/bin/pip install --no-binary :all: llama-cpp-python==0.3.2
```

If the model or the package is missing, `./run.sh demo` prints a clear notice and carries on —
only the summary checkbox is unavailable.

---

## 3. Codespace checklist

**Before the viva**

- [ ] Open the Codespace early; it may need to resume (30–60 s).
- [ ] `./run.sh demo --check` → expect `43/43` and `DEMO CHECK PASSED`.
- [ ] Settings → Codespaces → **Default idle timeout**: raise it (e.g. 90–240 min). A Codespace
      suspends on *no terminal or editor activity*; inbound HTTP alone may not reset it.
- [ ] `./run.sh demo` and leave the terminal in the foreground — that terminal is itself the
      keep-alive, and Ctrl+C stops the server cleanly.
- [ ] Ports panel → port **8000** → **Port Visibility → Public**, then open the forwarded URL
      once yourself to confirm it loads.
- [ ] Have `docs/report/img/phase10_4_*.png` open in a second tab (see §4).

**During**

- Present from the forwarded `https://<name>-8000.app.github.dev/` URL, not `127.0.0.1`.
- Keep the uvicorn terminal visible; it is also the keep-alive.

**After**

- [ ] Ports panel → port 8000 → **Visibility → Private**. A public port exposes the whole API,
      including `/audit`.
- [ ] Ctrl+C the server.

```bash
# CLI equivalents
gh codespace ports visibility 8000:public  -c "$CODESPACE_NAME"
gh codespace ports visibility 8000:private -c "$CODESPACE_NAME"
```

**If the forwarded URL drops** (blank page, 502, or "port not forwarded"):

1. Is the server still alive? The uvicorn terminal should show no traceback; `tail
   /tmp/dtc_demo_8000.log`.
2. Ports panel → is 8000 still listed? If not, re-add it: *Forward a Port* → `8000`, and set
   Visibility to Public again — **visibility resets to Private when a port is re-forwarded.**
3. If the Codespace suspended, the browser tab will 502. Return to the VS Code window to resume
   it, then `./run.sh demo` again (start-up ~10 s, the index and data are still on disk).
4. Still stuck → present from `http://127.0.0.1:8000/` in the Codespace's own *Simple Browser*
   (Ctrl+Shift+P → "Simple Browser: Show"), sharing your screen instead of the URL.

---

## 4. Panic section — two minutes

### Restart in under 60 seconds

```bash
pkill -f "uvicorn app:app" ; ./run.sh demo
```

Start-up is ~6 s plus warm-up, so this is comfortably inside a minute **provided `index/` and
`data/` are intact** (they are, unless the Codespace was rebuilt). Say out loud: *"restarting —
it loads in about ten seconds."* Then re-check visibility (§3) if the port was re-forwarded.

If the port is wedged, move: `./run.sh demo --port 8080` and forward 8080.

If retrieval itself is broken (`/health` not `ok`, or an index error in the log):

```bash
PYTHONPATH=src .venv/bin/python src/build_index.py --rebuild --aliases bm25 --cylinder-token
```

~30 s, then `./run.sh demo` again.

### If the live demo cannot be saved — show these instead

All captured from the real UI at 1280×720; they are in `docs/report/img/` and embedded with
commentary in [phase10_4_website.md](phase10_4_website.md). Show them in this order, which
matches the 10-minute script:

| # | file | what to say |
|---|---|---|
| 1 | `phase10_4_fleet_replay.png` | "A synthetic telematics feed replaying; the fleet view shows only what has arrived — 60 of 1,000 rows here." |
| 2 | `phase10_4_fleet_critical.png` | "Filtered to CRITICAL. A red stop lamp is CRITICAL by rule; nothing escalates into it on counts alone." |
| 3 | `phase10_4_vehicle_advisory.png` | "SPN/FMI → P-code → advisory. The steps are the manual's own text, with the page number." |
| 4 | `phase10_4_vehicle_ambiguous.png` | **Safety moment 1** — "One SPN+FMI maps to jammed-open *and* jammed-closed. It refuses to choose." |
| 5 | `phase10_4_verify_mismatch.png` | **Safety moment 2** — "The technician typed a real code, one character off. Flagged, never auto-corrected." |
| 6 | `phase10_4_symptom_answer.png` | "Plain technician language, no code: top-3 with full procedures." |
| 7 | `phase10_4_symptom_refusal.png` | **Safety moment 3** — "Out of scope is refused, not answered." |
| 8 | `phase10_4_why_panel.png` | "Retrieval ranks, the gate decision and its numbers, citations, and every step labelled RULE or AI. Exactly one step is AI, and it only phrases." |
| 9 | `phase10_4_audit.png` | "Every request logged with its decision, latency, git commit and determinism hash." |

Say plainly that these are screenshots of the same system, captured by
`scripts/capture_screens.py` from the running UI — not mock-ups.

### Things that look like failures but are not

| symptom | what it actually is |
|---|---|
| A vehicle row shows a dash instead of a severity badge | That vehicle's only rows were malformed and were rejected. Correct behaviour. |
| `AMBIGUOUS` / `CANDIDATES` with no repair steps | By design — the key is ambiguous, so nothing is advised. |
| A symptom query returns "Not covered in this manual" | The gate refusing out-of-scope input. Also by design. |
| The AI summary checkbox takes 15–30 s the first time | The local model loading. Leave it off unless demonstrating the RULE/AI split. |
| `/fleet` takes ~60 ms | It re-runs the ladder for all 199 vehicles each call; there is no cache. |

---

## 5. Verification for this phase

| check | result |
|---|---|
| `./run.sh demo --check`, clean shell, run 1 | **43/43, exit 0** |
| `./run.sh demo --check`, clean shell, run 2 | **43/43, exit 0** |
| failure path (`--base` to a dead port) | clean `FAIL` line, **exit 1**, no traceback |
| `src/test_api.py` | **61/61** |
| smoke suite | **44 passed / 1 xfail / 0 failed** |
| determinism `--defaults` | **`ffff9bc707d8754d`** |

Nothing in this phase touches retrieval, the gate, the index or the records: `run.sh` gained a
`demo` target, and `scripts/demo_smoke.py` gained a clean failure message for an unreachable
server.
