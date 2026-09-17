# Clean RAG — TATA Motors 3.3L DTC Troubleshooting Manual

A fully local, CPU-only retrieval system over `3.3L DTC Manual.pdf` (545 pages,
3.3L_NGE_BSVI, ECU MD1CS018). **Nothing leaves the machine**: no cloud APIs, no
API keys, no `.env`. Design is specified in [RAG_Build_Plan.md](RAG_Build_Plan.md).

## How to run

```bash
./run.sh
```

It checks the setup, then shows `Enter your query>`. Type a question and press Enter. Type
`quit` or press Ctrl+C to exit. On the very first run it also rebuilds any missing data files,
the search index and the local model download. Those are one-time steps, a few minutes in total.

Things you can ask:

| you type | what you get | speed |
|---|---|---|
| `how do I fix P0192-00` or just `P0340` | the full troubleshooting procedure for that code, straight from the manual | instant |
| `list all EGR faults` | every DTC in that subsystem | instant |
| `the adblue has turned to solid ice` | a short AI-phrased answer, plus the ranked list of matching DTCs | ~10 s (first one ~30 s) |
| `what is the warranty period` | refused: not covered by this manual | instant |

The ranked "Top matching DTCs" list comes from the search itself and is the part to trust. The
small local AI model only phrases the answer and sometimes dwells on the second match.

If `.venv` does not exist yet, `run.sh` stops and prints the one-time setup commands (also below).

For the web API instead: `.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000`.

## Core design

One **record per DTC**, not fixed-size chunking. Each DTC's troubleshooting steps
form a branching decision tree ("if lose, go to Step 13"), so the steps must stay
together in a single record or the repair logic breaks.

The manual uses a fixed 7-section template per DTC: header, Overview table,
Checkpoints, Trouble Shooting Steps table, Circuit Schematic, Circuit Description,
Location & Component Image.

**Critical:** flat text extraction scrambles the step tables on some pages — Sr.No
decouples from Steps text (verified on P0192-00, P0117-00) while other pages extract
cleanly (P0194-00). The parser therefore rebuilds the Sr.No ↔ Steps ↔ Specifications
mapping from **pdfplumber word coordinates** (x-column clustering, y-row grouping),
never from the flat text.

DTC code is **not** a unique key — suffixes are significant (-00, -9B, -11, -1F, -85)
and P0180-11 appears on two pages. Retrieval key = `code + suffix + page/occurrence`.

## Requirements

- **Python 3.12** — *not* 3.14. Several dependencies have no 3.14 wheels, and
  `llama-cpp-python` would fall back to a source build.
- System package: `tesseract-ocr`.
- CPU-only. No GPU required or used.

## Setup

```bash
sudo apt-get update && sudo apt-get install -y tesseract-ocr cmake build-essential
/usr/bin/python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel

# CPU-only torch first — avoids pulling ~2.5 GB of unused CUDA wheels
.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1
.venv/bin/pip install -r requirements.txt
```

`llama-cpp-python` must be built from source against glibc. The project's own
prebuilt CPU index serves a **musl/Alpine** wheel that fails to load on this image
(`libc.musl-x86_64.so.1: cannot open shared object file`):

```bash
CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_CUDA=OFF -DGGML_BLAS=OFF" FORCE_CMAKE=1 \
  .venv/bin/pip install --no-binary :all: llama-cpp-python==0.3.2
```

Verify:

```bash
.venv/bin/python -c "import pdfplumber, fitz, chromadb, llama_cpp, sentence_transformers; print('ok')"
```

## Memory discipline

The box is small, so the pipeline **never holds two large models at once**. Each
phase loads one model, does its work, and releases it before the next starts. The
PDF is streamed page-by-page; no run ever holds all 545 rendered pages.

| Moment | Resident | Approx. RAM |
|---|---|---|
| Base (Linux + VS Code server) | — | ~2.7 GB |
| Ingest · PDF parse | pdfplumber, one page at a time | +~0.5 GB |
| Ingest · image OCR | Tesseract | +~0.2 GB |
| Ingest · embedding | all-MiniLM-L6-v2, batch 32 | +~0.3 GB |
| Query (steady state) | MiniLM + Qwen2.5-0.5B Q4 + Chroma + FastAPI | +~1.3 GB |

Steady-state query total lands around **4 GB**. Images are hash-deduped before OCR
(many DTCs reuse the same schematic), which cuts the vision pass substantially.

## Pipeline

| Phase | Script | Output |
|---|---|---|
| 1 · Extract & structure | `src/parse_dtc.py` | `data/dtc_raw.jsonl` |
| 2 · Local image enrichment (OCR) | `src/enrich_images.py` | `images/`, `data/dtc_enriched.jsonl` |
| 3 · Canonical schema | `src/schema.py` | `data/dtc_records.jsonl` |
| 4 · Indexing | `src/build_index.py` | `index/` (Chroma + BM25 + code dict) |
| 5 · Retrieval | `src/retrieve.py` | — |
| 6 · Answering & diagnosis | `src/answer.py`, `src/diagnose.py` | — |
| 7 · Validation harness | `src/validate.py` | evaluation report |

Served via FastAPI `/ingest` and `/query` (`app.py`).

## Query modes

1. **Exact DTC** — regex hit on a code goes to a code dict, bypassing embedding ambiguity between near-identical DTCs; answered deterministically from structured fields, no LLM.
2. **Symptom / effect** — hybrid semantic + BM25, fused with Reciprocal Rank Fusion.
3. **Component / system** — metadata filter on the `system` tag.
4. **Conversational diagnosis** — a state machine walks `steps[]` following `goto[]` branches from the technician's answers.
