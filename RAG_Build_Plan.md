# Clean & Robust RAG for the 3.3L DTC Troubleshooting Manual — Build Plan

**Source:** `3.3L DTC Manual.pdf` — TATA Motors 3.3L_NGE_BSVI (ECU MD1CS018), 545 pages, dated 15/08/2019.

**Confirmed constraints**
- Query modes to support: **exact DTC lookup**, **symptom/effect**, **component/system**, **conversational diagnosis** (all four).
- Images: **full multimodal**, achieved **fully locally at ingest** — OCR the schematics (+ optional tiny local VLM) into text + pin-maps stored in each record. No cloud, no GPU. Live query path is text-only.
- Compute: **GitHub Codespace, 16 GB RAM, CPU-only, no GPU, no cloud API.** Everything (ingest + query) runs on-box and must stay within the 16 GB envelope.

**Design principle:** structure-aware, one-record-per-DTC. We exploit the fixed 7-section template rather than blind fixed-size chunking. "Robust" is *measured* by a validation harness, not assumed.

---

## Memory budget (16 GB Codespace, CPU-only, fully local)

**Golden rule: never keep two large models resident at once.** The pipeline runs in distinct passes; each loads one model, does its work, and releases it before the next.

| Moment | Resident components | Approx. RAM |
|---|---|---|
| Base Codespace (Linux + VS Code server + Python) | — | ~2–3 GB |
| Ingest · PDF parse | pdfplumber/PyMuPDF, **one page at a time** | +~0.5 GB |
| Ingest · image OCR | Tesseract | +~0.2 GB |
| Ingest · (optional) local VLM caption | moondream2 / SmolVLM Q4, run **alone** | +~2–3 GB |
| Ingest · embedding | all-MiniLM-L6-v2 (384-dim) | +~0.3 GB |
| **Query time (steady state)** | MiniLM + Qwen2.5-0.5B-Instruct Q4 + ChromaDB + FastAPI | **+~1.3 GB** |

Worst single moment ≈ base + VLM ≈ **~5–6 GB**. Steady-state query service ≈ **~4 GB total**. Comfortable headroom under 16 GB.

**RAM-safety rules baked into the code:**
1. **One model at a time** — vision pass, then release; embed pass, then release; LLM loaded only by the query service.
2. **Stream the PDF page-by-page** — never hold all 545 rendered pages/images in memory.
3. **ChromaDB persisted to disk**, memory-mapped — the ~600-record × 384-dim index is <10 MB anyway.
4. **Small models only** — MiniLM (~90 MB), Qwen2.5-0.5B GGUF Q4 (~400 MB), optional VLM Q4 (~2–3 GB) used once.
5. **Dedup images before captioning** — many DTCs reuse the same schematic (rail-pressure trio, injector 1–4, ~85 FCCU alarms); hash-dedup cuts the vision pass to a fraction and slashes ingest time.
6. **Bounded batch sizes** for embedding (e.g. 32) so peak stays flat.

---

## Document structure (verified from the PDF)

- Pages 1–7: Table of Contents (DTC code → page).
- Each DTC entry follows a fixed template:
  1. Header: `Pxxxx-xx: <description>`
  2. **Overview** table: Code block (Fault Code, MIL, CEL, Immo Lamp, Message on IC) · Cause (numbered) · Effect on Vehicle
  3. **Checkpoints** (numbered)
  4. **Trouble Shooting Steps** table: Sr. No. · Steps · Specifications
  5. **Circuit Schematic Diagram** (image)
  6. **Circuit Description** (paragraph)
  7. **Location & Component Image** (image)

## Known hazards this plan must defend against
1. **Inconsistent table extraction** — step numbers decouple from step text on some pages (e.g. P0192-00, P0117-00) while others extract cleanly (P0194-00). Must repair using word coordinates.
2. **Branching step logic** — steps cross-reference ("go to Step 7 / else Step 11"); a DTC's steps must stay in one record.
3. **Pin references in images** — steps cite pins (A71, A83, A11, A51) defined only in schematic images.
4. **Repeated boilerplate** — page header/footer repeats ~545×; must be stripped.
5. **Near-duplicate DTCs** — rail-pressure trio, injector cyl 1–4, ~85 P16xx FCCU alarms are textually near-identical; the code is the disambiguator.
6. **Code is not a unique key** — suffixes matter (-00, -9B, -11, -1F, -85…) and P0180-11 appears twice (pp. 99 & 194). Retrieval key = code + suffix + page/occurrence.

---

## Phase 0 — Environment setup (one-time)
- Install **Python 3.11** (currently absent; the `python` on PATH is the Windows Store stub). Create a project venv.
- Core deps (all CPU-only, no GPU, no network):
  - `pdfplumber` (word-level bboxes for table repair), `pymupdf` (image extraction),
  - `pytesseract` + system `tesseract-ocr` (schematic OCR), `imagehash`+`Pillow` (image dedup),
  - `sentence-transformers` (all-MiniLM-L6-v2 embeddings), `chromadb` (local persistent vector store), `rank-bm25` (lexical),
  - `llama-cpp-python` (runs Qwen2.5-0.5B-Instruct GGUF on CPU for generation),
  - `fastapi` + `uvicorn` (the `/ingest` and `/query` endpoints).
  - Optional local VLM (`moondream2` / `SmolVLM` GGUF) only if OCR alone proves insufficient.
- System pkg: `sudo apt-get install -y tesseract-ocr`.
- Deliverable: `requirements.txt`, `README` with setup steps. **No `.env`/API key needed — nothing leaves the box.**

## Phase 1 — Extraction & structuring
- Parse the TOC (pp. 1–7) → authoritative list of expected DTCs + page numbers (used later for validation).
- Split body at each `Pxxxx-xx:` header → one raw block per DTC (stitching across page breaks, dropping intervening headers/footers).
- **Section parser** for the 7 sub-sections into typed fields.
- **Table-repair routine** (the critical robustness step): reconstruct the Sr.No ↔ Steps ↔ Specifications mapping from pdfplumber word x/y coordinates (column clustering by x, row grouping by y) instead of trusting the flat text. Normalize every step to `{n, text, goto[]}` by parsing "go to Step N".
- Deliverable: `parse_dtc.py`, intermediate `dtc_raw.jsonl`.

## Phase 2 — Multimodal enrichment (one-time, fully local, CPU)
- With PyMuPDF, extract the schematic + location images bound to each DTC's page range (streamed page-by-page).
- **Dedup** images by hash first — reused schematics are processed once (big time/RAM saving).
- **OCR-first (primary):** run Tesseract on each unique schematic → pull pin labels / net names (A71, A83, A11…) into a structured `pin_map[]`. Cheap, fast, ~200 MB RAM, no GPU. Because the step text already cites pins, OCR mainly anchors/confirms them.
- **Optional tiny local VLM (fallback):** if OCR misses too much on some diagrams, run a small quantized VLM (moondream2/SmolVLM) **once, alone** → short `description`. Loaded in its own pass, released after.
- Merge OCR text + pin_map (+ optional description) into the DTC record; keep `image_refs` (paths) so a UI can display the original.
- Deliverable: `enrich_images.py`, `images/` extracted assets, enriched `dtc_enriched.jsonl`. **No network access at any point.**

## Phase 3 — Canonical DTC record schema
Each DTC becomes one self-contained record + retrieval chunk:
```
{ dtc_code, suffix, code_full, description, system,        # system = rail_pressure|egr|injector|turbo_boost|...
  fault_code, MIL, CEL, immo_lamp, ic_message,
  effect, cause[], checkpoints[], steps[{n,text,goto[]}], specifications[],
  circuit_description, pin_map[], image_refs[], page, occurrence }
```
- `system` tag assigned by a rules/keyword map over the description (drives component/system queries).
- Deliverable: `schema.py`, final `dtc_records.jsonl`.

## Phase 4 — Indexing (local, CPU)
- Build the **embedding text** per record (description + cause + effect + checkpoints + circuit_description + pin_map) with a CPU-friendly model (`all-MiniLM-L6-v2`, 384-dim, ~90 MB) — batch size ~32 to keep peak RAM flat.
- Store vectors + full metadata in **ChromaDB** (persistent, on-disk, supports metadata filtering).
- Build two companion indexes: an **exact-code dict** (`code_full → record`) and a **BM25** lexical index for hybrid retrieval.
- Deliverable: `build_index.py`, persistent `./index/`.

## Phase 5 — Retrieval layer (serves all four modes)
- **Router** inspects the query:
  - Regex hit on a DTC code → **exact lookup** via the code dict (bypasses embedding ambiguity; solves near-duplicates).
  - Component/system keyword → **metadata filter** on `system`, return the group.
  - Otherwise → **hybrid semantic + BM25**, fused with **Reciprocal Rank Fusion**.
- Return top-k full DTC records (not fragments).
- Deliverable: `retrieve.py`.

## Phase 6 — Answering & conversational orchestration (local)
- **Fast path (exact DTC):** render a deterministic templated answer straight from the structured fields — cause, effect, checkpoints, ordered steps, referenced pins, "see schematic (page N)". No LLM needed → instant even on CPU.
- **LLM path (symptom/conversational):** `Qwen2.5-0.5B-Instruct` GGUF (Q4) via `llama-cpp-python`, CPU-only (~400 MB), to phrase answers and drive the step-tree dialogue. *Note: CPU generation is the main latency cost; keep prompts tight and prefer the fast path where possible. If quality is short and RAM allows, Qwen2.5-1.5B Q4 (~1 GB) is a drop-in upgrade still well within budget.*
- **Conversational diagnosis:** a state machine walks `steps[]`, following `goto[]` branches based on the technician's yes/no at each step.
- Deliverable: `answer.py`, `diagnose.py` (state machine).

## Phase 7 — Evaluation & robustness harness
- **Coverage:** every TOC DTC produced exactly one record; report any missing/duplicate/malformed.
- **Step integrity:** every `goto` resolves to an existing step within the same DTC.
- **Retrieval quality:** hand-built gold set (~30 queries across the 4 modes) → hit@k / MRR.
- **Boilerplate check:** assert no header/footer strings leaked into records.
- Deliverable: `validate.py` + a short evaluation report.

---

## Proposed file layout
```
RAG_Clean For DTC/
  RAG_Build_Plan.md          (this file)
  requirements.txt  .env  README.md
  data/  dtc_raw.jsonl  dtc_enriched.jsonl  dtc_records.jsonl
  images/
  index/                     (Chroma + BM25 + code dict)
  src/  parse_dtc.py  enrich_images.py  schema.py  build_index.py
        retrieve.py  answer.py  diagnose.py  validate.py
  app.py                     (CLI/simple UI entry)
```

## Open decisions (not blocking Phase 0–1)
- Final local generation model (0.5B default → 1.5B if quality is short) — decide after a quick CPU latency benchmark in the Codespace. Both fit 16 GB.
- OCR-only vs OCR + tiny VLM for schematics — start OCR-only; add the VLM pass only if pin extraction is insufficient.
- Whether to add a lightweight local UI (FastAPI + CLI first, optional web UI later).

## Suggested execution order
Phase 0 → **Phase 1 proof-of-concept on ~5 DTCs including a broken-table one** → validate table repair → then scale to all 545 pages → Phases 2–7.
