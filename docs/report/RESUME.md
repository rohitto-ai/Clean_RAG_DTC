# RESUME — Clean RAG for the 3.3L DTC Manual

**State: Phases 0–2 complete and committed. Next action is Phase 3 (canonical schema),
then Phase 4 (indexing). Nothing is mid-flight or half-applied.**

_Last updated: 2026-09-15_

---

## Where the project is

| Phase | Status | Deliverable |
|---|---|---|
| 0 · Environment | ✅ done | venv on **Python 3.12**, `requirements.txt`, README |
| 1 · Extraction & structuring | ✅ done | `data/dtc_raw.jsonl` — **314 records**, 545 pages |
| 1b · Validation harness | ✅ done | `data/validation_report.md` |
| 2 · Image enrichment (OCR-fallback) | ✅ done | `data/dtc_enriched.jsonl`, `images/` (64 unique) |
| **3 · Canonical schema** | ⬜ **next** | `src/schema.py`, `data/dtc_records.jsonl` |
| 4 · Indexing | ⬜ | `src/build_index.py`, `index/` (Chroma + BM25 + code dict) |
| 5 · Retrieval | ⬜ | `src/retrieve.py` |
| 6 · Answering & diagnosis | ⬜ | `src/answer.py`, `src/diagnose.py` |
| 7 · Evaluation harness | ⬜ | extend `src/validate.py` |

## Exact next action

Write **`src/schema.py`** (Phase 3): formalise the record shape already present in
`data/dtc_enriched.jsonl` as a typed/validated schema and emit
`data/dtc_records.jsonl`. The fields exist and are populated — this is
formalisation plus a `system`-tag pass, not new extraction. Then Phase 4:
embed with all-MiniLM-L6-v2 (batch 32) into a persistent ChromaDB, plus an
exact-code dict and a BM25 index.

Run everything with the venv interpreter: `.venv/bin/python`.

```bash
.venv/bin/python src/parse_dtc.py --first 8 --last 545   # ~68 s, 72 MB peak
.venv/bin/python src/validate.py                          # regenerates the report
.venv/bin/python src/enrich_images.py                     # ~seconds, 241 MB peak
```

## Open decisions for you

1. **Branch polarity (Phase 6).** Deliberately not modelled yet, as you directed.
   The evidence is now collected: `data/branch_patterns.json`, 32 signatures over
   1205 branching steps. Key finding — the largest shape is `IF X` with **zero**
   goto targets (419 steps), i.e. an implicit fall-through "else". Only **5 steps
   total** have an explicit two-way `else`. So polarity will mostly have to be
   inferred from condition + fall-through. **Needs your design call before Phase 6.**

2. **Out-of-range `goto` targets.** 37 references across 20 records point past the
   last step. These are **source-document defects** (verified on pp. 20, 22, 83,
   248, 390 — the manual prints "Step 9" twice, skips labels, etc.). In 20/20 the
   final step is a terminal "Check DTC". Recommendation: resolve to the terminal
   step in Phase 6 and log it in Phase 7. `goto[]` is currently **verbatim**.

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

## Reports

- [phase0_environment.md](phase0_environment.md)
- [phase1_extraction.md](phase1_extraction.md)
- [phase2_enrichment.md](phase2_enrichment.md)
