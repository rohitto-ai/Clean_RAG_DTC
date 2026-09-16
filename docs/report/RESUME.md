# RESUME — Clean RAG for the 3.3L DTC Manual

**State: Phases 0–6 complete and committed. Next action is Phase 7 (evaluation &
robustness harness). Nothing is mid-flight or half-applied.**

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
| 4 · Indexing | ✅ done | `index/` — 314 vectors + BM25 + code dict |
| 5 · Retrieval | ✅ done | `src/retrieve.py` — router + RRF |
| 6 · Answering & diagnosis | ✅ done | `src/answer.py`, `src/diagnose.py` — **30 pass / 1 xfail / 0 fail** |
| **7 · Evaluation harness** | ⬜ **next** | extend `src/validate.py` + gold query set |

## Exact next action

Build the **Phase 7 evaluation & robustness harness** (extend `src/validate.py`, or
add `src/evaluate.py` and call it from there). The build plan asks for:

1. **Retrieval quality** — hand-build a **~30-query gold set** spanning the four
   modes (exact DTC, symptom/effect, component/system, conversational), then report
   **hit@k and MRR**. This is the one metric the project still has no number for;
   everything so far is spot-checked.
2. **Coverage / step integrity / boilerplate** — already implemented in
   `src/validate.py` §§1–3. Keep them.
3. **New, from Phase 6** — report how often the state machine fires a **clamp**
   (37 out-of-range targets exist) and a **`skip_true_branch` inference** (256
   conditional steps are shaped for it) across an automated walk of all 314 records.
   Both are logged in the diagnosis trace already.
4. **Grounding check** — assert out-of-scope queries return `NOT_COVERED` via the
   deterministic gate and never reach the model.

Then wire the **FastAPI `/ingest` and `/query` service** (`app.py`), which the build
plan lists but nothing has built yet.

Run everything with the venv interpreter: `.venv/bin/python`.

```bash
.venv/bin/python src/parse_dtc.py --first 8 --last 545   # ~68 s,   72 MB peak
.venv/bin/python src/enrich_images.py                     # seconds, 241 MB peak
.venv/bin/python src/schema.py                            # seconds,  17 MB peak
.venv/bin/python src/build_index.py --rebuild             # ~21 s,  680 MB peak
.venv/bin/python src/validate.py                          # regenerates the report
PYTHONPATH=src .venv/bin/python src/smoke_index.py        # 31 tests, ~1.1 GB peak
PYTHONPATH=src .venv/bin/python src/retrieve.py <query>   # ad-hoc retrieval CLI
```

`data/*.jsonl`, `index/` and `models/` are gitignored build artifacts. Regenerate
them with the commands above **in that order**. The GGUF re-download command is in
`docs/report/phase6_answer_diagnose.md`.

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

3. **Is Qwen2.5-1.5B worth it?** 0.5B phrasing is serviceable but weak — it cites
   correctly and stays in context, but rambles ("the effect on the vehicle is NA").
   1.5B would cost ~3x latency (~30 s/answer vs 9 s) on these 4 vCPUs; RAM is no
   longer a constraint. My read: **not clearly worth it** — the fast path handles the
   primary exact-DTC workflow with no generation at all, and the *relevance gate*,
   not the model, is what prevents fabrication. **Do not switch unless you say so.**

4. **Image-derived pins.** OCR scored **0%** and was skipped for a structural
   reason, not a quality one: the text cites `A71`, but the schematic draws
   connector `C016-A` with a bare pin `71` — the literal token is never rendered.
   `pin_map[]` is text-derived instead (383 high-confidence pins). If you want
   image-derived pins later, the retry must use the *composition* rule
   (connector label + nearby pin number), not another OCR parameter sweep.
   See `docs/report/phase2_enrichment.md`. **No VLM** — deferred/off on this box.

## Things a newcomer will get wrong

- **Re-measure RAM at the start of every session.** As of 2026-09-16 this box is
  **16 GiB / 4 vCPU**, matching the build plan. On 2026-09-15 the same repo's
  Codespace was the 2-core / 8 GiB type. The machine type has changed once already,
  so trust `/proc/meminfo`, not the docs.
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
- **`on_true` can point outside the step list** (37 steps). Always check membership;
  `src/diagnose.py` clamps to the terminal step and logs it.
- **Never let the LLM decide whether a question is in scope.** Qwen2.5-0.5B failed
  this both ways — it fabricated tyre-change instructions with an invented psi
  figure, and separately refused a valid query. `answer.is_relevant()` gates
  deterministically on the retrieval signal before the model is consulted.
- **24% of conditional steps have `on_true == n+1`**, which makes plain fall-through
  send "yes" and "no" to the same place and leaves whole step ranges unreachable
  (P0192-00 steps 9-12). `diagnose.py` skips the true-branch step and logs a
  `skip_true_branch` inference. Do not remove it without re-reading
  `docs/report/phase6_answer_diagnose.md`.
- **Equal-weight RRF cannot break a symmetric rank swap.** If two docs exchange ranks
  1 and 2 between the rankers, their RRF scores are identical *for every k* — it is
  structural, not a tuning problem. `src/retrieve.py` breaks such ties by summed
  min-max-normalised ranker scores. Do not "fix" it by changing `RRF_K`.
- **A subsystem keyword is a soft signal, never a hard filter**, unless grouping
  intent is also present. Filtering on it turns "EGR valve stuck closed" into a
  14-record dump instead of returning P042F-00.
- **The dense index deliberately excludes step text.** Steps are near-identical
  boilerplate across hundreds of DTCs; embedding them destroys discrimination between
  near-duplicate families. Do not "fix" this by adding them. See
  `docs/report/phase4_indexing.md`.
- **Never key an index on `code_full` alone** — 3 codes appear twice, so ids must
  include page + occurrence or you silently drop records (314 → 311).
- **Do not use a default word-splitting tokenizer for BM25** — it shatters `P0192-00`
  into `["p","0192","00"]` and `A71` into `["a","71"]`, destroying the highest-signal
  identifiers. `src/build_index.py:tokenize` preserves them.

## Reports

- [phase0_environment.md](phase0_environment.md)
- [phase1_extraction.md](phase1_extraction.md)
- [phase2_enrichment.md](phase2_enrichment.md)
- [phase3_schema.md](phase3_schema.md)
- [phase4_indexing.md](phase4_indexing.md)
- [phase5_retrieval.md](phase5_retrieval.md)
- [phase6_answer_diagnose.md](phase6_answer_diagnose.md)
