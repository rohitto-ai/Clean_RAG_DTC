# RESUME — Clean RAG for the 3.3L DTC Manual

**State: Phases 0–3 complete and committed. Next action is Phase 4 (indexing).
Nothing is mid-flight or half-applied.**

_Last updated: 2026-09-16_

---

## Where the project is

| Phase | Status | Deliverable |
|---|---|---|
| 0 · Environment | ✅ done | venv on **Python 3.12**, `requirements.txt`, README |
| 1 · Extraction & structuring | ✅ done | `data/dtc_raw.jsonl` — **314 records**, 545 pages |
| 1b · Validation harness | ✅ done | `data/validation_report.md` |
| 2 · Image enrichment (OCR-fallback) | ✅ done | `data/dtc_enriched.jsonl`, `images/` (64 unique) |
| 3 · Canonical schema | ✅ done | `data/dtc_records.jsonl` — **314/314 schema-valid** |
| **4 · Indexing** | ⬜ **next** | `src/build_index.py`, `index/` (Chroma + BM25 + code dict) |
| 5 · Retrieval | ⬜ | `src/retrieve.py` |
| 6 · Answering & diagnosis | ⬜ | `src/answer.py`, `src/diagnose.py` |
| 7 · Evaluation harness | ⬜ | extend `src/validate.py` |

## Exact next action

Write **`src/build_index.py`** (Phase 4). Read `data/dtc_records.jsonl` (314 records)
and build three indexes into `./index/`:

1. **Embeddings** — build the embedding text per record (description + cause + effect
   + checkpoints + circuit_description + pin_map), encode with **all-MiniLM-L6-v2**
   (384-dim, ~90 MB) at **batch size 32** to keep peak RAM flat, and store vectors +
   full metadata in a **persistent on-disk ChromaDB**.
2. **Exact-code dict** — `code_full` → record. Must be a *list* per code, not a single
   value: `P0180-11`, `P0180-12` and `P061C-00` each appear twice. Key on
   code + suffix + page/occurrence.
3. **BM25** — `rank-bm25` over the same text, for the lexical half of RRF fusion.

Load the embedding model, use it, release it. Do not hold it alongside anything else.

Run everything with the venv interpreter: `.venv/bin/python`.

```bash
.venv/bin/python src/parse_dtc.py --first 8 --last 545   # ~68 s, 72 MB peak
.venv/bin/python src/enrich_images.py                     # ~seconds, 241 MB peak
.venv/bin/python src/schema.py                            # ~seconds, 17 MB peak
.venv/bin/python src/validate.py                          # regenerates the report
```

The `.jsonl` files are gitignored build artifacts. If they are missing, regenerate
them with the three commands above, in that order, before doing anything else.

## Open decisions for you

1. ~~**Branch polarity.**~~ **DECIDED and built** (2026-09-16): modelled
   conservatively with a `polarity_confidence` flag; never fabricate a route.
   `on_true`/`on_false` are `null` where the manual does not state a route, which
   means "fall through to n+1". Implemented in `src/schema.py`; rationale and
   distributions in `docs/report/phase3_schema.md`. **Result: only 5 steps in the
   whole manual state an explicit `else`**, so Phase 6 will be walking implicit
   fall-throughs far more often than stated two-way branches.

2. **Out-of-range `goto` targets — STILL OPEN, and now load-bearing.** 37 references
   across 20 records point past the last step. These are **source-document defects**
   (verified on pp. 20, 22, 83, 248, 390 — the manual prints "Step 9" twice, skips
   labels, etc.). In 20/20 the final step is a terminal "Check DTC".
   `goto[]` is verbatim and `on_true` now carries these out-of-range values live,
   all marked `polarity_confidence: "low"`. **Phase 6 must clamp them to the terminal
   step** — a consumer that follows `on_true` blindly will dereference a
   non-existent step. Recommendation unchanged: clamp in Phase 6, log in Phase 7.

3. **Image-derived pins.** OCR scored **0%** and was skipped for a structural
   reason, not a quality one: the text cites `A71`, but the schematic draws
   connector `C016-A` with a bare pin `71` — the literal token is never rendered.
   `pin_map[]` is text-derived instead (383 high-confidence pins). If you want
   image-derived pins later, the retry must use the *composition* rule
   (connector label + nearby pin number), not another OCR parameter sweep.
   See `docs/report/phase2_enrichment.md`. **No VLM** — deferred/off on this box.

## Things a newcomer will get wrong

- **The box is 7.75 GiB, not 16 GB** (2-core Codespace, no swap). The plan budgets
  against 16 GB. Everything fits, but the optional VLM pass does not.
- **Use `/usr/bin/python3.12`, never the 3.14 on `PATH`** — missing wheels.
- **`llama-cpp-python` must be built from source**; the prebuilt CPU index serves a
  musl/Alpine wheel that will not load here.
- **Never parse the step table from flat text.** A naive "Step N" split on P0192-00
  gives 22 rows against a truth of 13, and the phantoms *overwrite real steps*.
  Row starts are decided geometrically, by the Sr.No x-band.
- **The DTC code is not a unique key** — `P0180-11`, `P0180-12` and `P061C-00` each
  appear twice. Key on code + suffix + page/occurrence.
- **The manual has two templates**, not one: 113 records are full 7-section, 173 are
  reduced 4-section (no schematic/description/location at all). The reduced form is
  real document structure — do not treat it as extraction damage.
- **Never read branch polarity off `goto[]`** — it is a *sorted* list. For
  "…then go to Step 12 else go to Step 11" the sorted `goto` is `[11, 12]` but the
  routing is `on_true=12, on_false=11`. Use `on_true`/`on_false`, which were derived
  positionally. `goto[]` is the verbatim audit trail, not the routing.
- **`on_true` can point outside the step list** (37 steps). Always check membership.

## Reports

- [phase0_environment.md](phase0_environment.md)
- [phase1_extraction.md](phase1_extraction.md)
- [phase2_enrichment.md](phase2_enrichment.md)
- [phase3_schema.md](phase3_schema.md)
