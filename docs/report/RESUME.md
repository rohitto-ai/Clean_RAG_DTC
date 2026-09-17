# RESUME — Clean RAG for the 3.3L DTC Manual

**State: PHASE 8 COMPLETE; Phase 9.1 (advise mode) + 9.1b (step column-bleed fix) + 9.2 (baseline comparison) DONE.** All phases 0–8 are done on branch `phase8-limitations`. The
Phase 8 configuration is adopted as the production default. The frozen TEST split has been
evaluated once and is now spent. The previous system is preserved as tag `v1-phase7`.

_Last updated: 2026-09-17_

**Phase 9.1:** `src/advise.py` + `POST /advise` return the top-3 DTCs, each with a deterministic fix block (additive; retrieval, gate and indexes unchanged). Details: `docs/report/phase9_1_advise_mode.md`.

**Phase 9.1b:** fixed the parser column-bleed (steps band clamped to the footer + header-anchored column guard). The detector `scripts/detect_step_bleed.py` found 3 records / 34 garbled steps (P0117-00, P00C6-00, P0A1B-12); it now finds 0. DEV metrics are unchanged; **current production determinism hash `ffff9bc707d8754d`** (was `76b16c2b9ab8f9f2`, data changed). Advise related codes now prefer the same system. The 8.5 TEST predates the fix and was not re-run. Details: `docs/report/phase9_1b_step_fix.md`.

**Phase 9.2:** 5-method comparison (keyword BM25, rule-based code lookup, dense-only, naive 500-char chunks in `index_naive/`, production hybrid) on a 935-case auto-generated set (`data/gold_autogen.jsonl`, NOT human-verified) and DEV. Hybrid is best on every non-code stratum (DEV near-dup MRR 1.000 vs ≤0.643; DEV symptom 0.711 vs ≤0.340; paraphrase 0.875 vs ≤0.792); naive chunking is weakest. DEV is not held out for hybrid; baselines were NOT run on the spent TEST. Details: `docs/report/phase9_2_baselines_eval.md`.

## Final result (Phase 8.5, gold v2.2 TEST, one shot)

| TEST | v1-phase7 | **conservative headline (both ablated)** | adopted production (full) |
|---|---|---|---|
| overall MRR | 0.562 | **0.601** | 0.728 |
| symptom hit@1 / MRR | 23.1% / 0.291 | **23.1% / 0.368** | 53.8% / 0.628 |
| near-duplicate MRR | 0.690 | 0.690 | 0.679 |
| exact-code hit@1 | 100% | 100% | 100% |
| out-of-scope refused | 3/6 | **2/6** | 6/6 |
| in-scope passed | 29/30 | 30/30 | 30/30 |

**Honest reading:** most of the TEST symptom gain comes from lexicon entries whose wording also
appears in TEST. The defensible gain over v1 is +0.077 symptom MRR with no hit@1 change. Gate v2
is weaker than v1 on commercial phrasing its stoplist doesn't cover. Full analysis:
`docs/report/phase8_5_final_eval.md`.

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
| 6 · Answering & diagnosis | ✅ done | `src/answer.py`, `src/diagnose.py` |
| 7 · Evaluation + service | ✅ done | `src/evaluate.py`, `app.py` — **30 pass / 1 xfail / 0 fail** |

## Phase 8 status

| step | status |
|---|---|
| 0 · Snapshot | ✅ tag `v1-phase7` → `dbf944b`, pushed; branch `phase8-limitations` |
| 8.0 · Evaluation foundation | ✅ `data/gold_v2.json` **v2.1** (70 q, DEV 34 / TEST 36), overlap ceiling rule, baselines re-recorded |
| 8.1 · L2 skip-branch fixes | ✅ 5 fixed via `MANUAL_CORRECTIONS`; suite 37 pass / 1 xfail / 0 fail |
| 8.2 · Symptom vocabulary gap (L1) | ✅ DEV only. Embedder: keep MiniLM. Lexicon config C4: DEV symptom MRR 0.278 → 0.715 |
| 8.2b · Compound cylinder token | ✅ **C4b** = C4 + `cylinder_<N>` BM25 token: guardrails **14/14**, DEV identical to C4 |
| 8.3 · Relevance gate (L3) | ✅ DEV only, on C4b. Gate v2 (signal + non-diagnostic intent): OOS refused **6/6**, in-scope **28/28** |
| 8.3b · Deterministic retrieval | ✅ exact dense ranking + total RRF order. DEV result byte-identical in 3 processes / 3 hash seeds |
| 8.4 · Image-derived pins (L4) | ✅ characterized limitation: recall 31%, audited precision 38%, 3 genuine new pins vs 61 false. Supplementary file only; indexes untouched |
| 8.5 · Final TEST evaluation + adoption | ✅ one-shot, pre-registered; C4b + gate v2 adopted; suite 44/1/0, guardrails 14/14, production hash 76b16c2b9ab8f9f2 |
| 8.5 · Final TEST evaluation | ⏸ frozen until then |

### DEV results (gold v2.2) — 8.2

| DEV | symptom hit@1 | symptom MRR | overall MRR | gate OOS / in-scope |
|---|---|---|---|---|
| before (production retriever) | 16.7% | 0.278 | 0.603 | 4/6 · 27/28 |
| C4: aliases→BM25 + expansion→BM25 | 58.3% | 0.711 | 0.861 | 4/6 · 28/28 |
| C4b: C4 + cylinder_<N> token | 58.3% | 0.711 | 0.861 | 4/6 · 28/28 |
| **C4b + gate v2 (selected), deterministic** | **58.3%** | **0.711** | **0.861** | **6/6 · 28/28** |

(8.2/8.2b originally reported 0.715 / 0.863 — an approximate-search artefact, corrected in 8.3b.)

Gold v2.2: the overlap ceiling is now uniform (DEV 0.090 / TEST 0.098 mean overlap).
TEST figures from 8.0 (v2.1) remain the frozen before-picture; not re-run.

## Next steps (Phase 8 is complete — these are recommendations)

1. **Independent query author.** The gold set, lexicon and stoplist share one author, and 8.5
   showed that is the largest source of optimism. A new held-out set written by someone who
   hasn't seen the lexicon is the most valuable next measurement. **TEST v2.2 is spent** and must
   not be reused as a clean held-out set.
2. **Gate: restore a stricter signal floor for intent-free queries**, or grow the stoplist from
   an independent source. Gate v2's lowered `dense_min` (0.23) lets unfamiliar commercial phrasing
   through (TEST conservative 2/6 vs v1 3/6).
3. **Merge** `phase8-limitations` → `main` after review (PR opened in 8.5).
4. Smaller: number words and ordinals for the cylinder token; negation in symptom queries; the
   image-pin redesign (pin-block detection + net-anchored numbers), only if pins from images are
   ever needed.

**Production is now:** `Retriever()` (auto config from `index/` meta: lexicon + BM25 expansion,
exact dense, cylinder token) + gate v2 by default (`data/production_config.json`). Reproduce v1:
`git checkout v1-phase7`.

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

0. **Phase 8.5 outcome:** TEST measured once; the conservative (both-ablated) headline is the
   number to quote. Adopted (a) for production — see the final report for why (a) rather than (d).

1. ~~**Ranking non-determinism.**~~ **FIXED in 8.3b:** the dense pool now comes from the
   exact matrix, with a total RRF order. The DEV result is byte-identical across 3 processes
   and 3 hash seeds. True C4b DEV symptom MRR 0.711 (not 0.715).

2. **Gate v2 intent stoplist vs TEST.** 8 of 50 intent terms match TEST out-of-scope wording
   (resale, discount, buy, purchase, service centre, warranty, bluetooth, infotainment), all
   `user`-provenance from the 8.3 brief. Found by a check run only after the stoplist was
   frozen. Planned: report TEST with these ablated at 8.5.

3. ~~**Lexicon/TEST contamination.**~~ **DECIDED:** keep the 19 TEST-matching entries; 8.5
   reports TEST both full and ablated, ablated = conservative headline.

2. ~~**Injector short-circuit confusion.**~~ **FIXED in 8.2b** via the `cylinder_<N>` BM25
   token; guardrails 14/14. Remaining gap: number words / ordinals ("cylinder one",
   "3rd cylinder") are not folded.

3. ~~**TEST split authoring bias.**~~ **RESOLVED (v2.1):** the 13 TEST symptom queries were
   rewritten under a 0.15 word-overlap ceiling (TEST mean 0.412 → 0.098); TEST symptom
   hit@1 fell 76.9% → 23.1%, level with DEV. **Still open:** DEV has **8 grandfathered
   queries over the ceiling** (d015 d017 d018 d019 d020 d021 d023 d025), making DEV
   slightly easier than TEST on mean overlap (0.168 vs 0.098). Rewriting them would
   equalise difficulty but change the DEV baseline — your call, and best made before 8.2.

2. **L2 corrected count: 5 mismatches, not 6.** P0194-00 s7 was a false positive from
   the Phase 7 fix-verb detector and is correctly NOT overridden (its skip reaches the
   real remedy, s9 "Change the rail pressure sensor"). Pinned by a regression test.

3. **Symptom retrieval is weak** (Phase 7: 27.3% hit@1; gold_v2 DEV: 25.0%). Vocabulary gap, not a ranking bug.
   Fix is the synonym layer described above. Deliberately NOT tuned during Phase 7,
   because tuning against the measuring set would have invalidated the number.

4. ~~**`skip_true_branch` mismatches.**~~ **FIXED in 8.1** — 5 genuine cases corrected
   via `MANUAL_CORRECTIONS` in `src/diagnose.py`, logged as `manual_correction`.

5. **Is Qwen2.5-1.5B worth it?** 0.5B phrasing is serviceable but weak — it cites
   correctly and stays in context, but rambles ("the effect on the vehicle is NA").
   1.5B would cost ~3x latency (~30 s/answer vs 9 s) on these 4 vCPUs; RAM is no
   longer a constraint. My read: **not clearly worth it** — the fast path handles the
   primary exact-DTC workflow with no generation at all, and the *relevance gate*,
   not the model, is what prevents fabrication. **Do not switch unless you say so.**

6. **Image-derived pins.** OCR scored **0%** and was skipped for a structural
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
- **Never rank from Chroma's HNSW for a reported metric.** Its dense top-50 pool changed
  between processes. `Retriever(exact_dense=True)` (the default since 8.3b) ranks from the
  exact matrix, which is also faster at this size (9.5 ms vs 13.0 ms). Also keep ties
  TOTALLY ordered: never let a `set` iteration order decide a rank.
- **A matching metric is not proof of reproducibility.** Two HNSW runs had identical MRR but
  different top-5 lists. Hash the full canonical output (`scripts/determinism_proof.py`).
- **A signal threshold that separates 6 negatives exactly is not evidence.** In 8.3,
  `dense≥0.33 or bm25≥10.7` refused 6/6 on DEV but was fitted to one point (margins
  0.007 / 0.09). Prefer refusal reasons that hold by construction (intent).
- **Schematic connector drawings reuse the ECU connector label.** "C016-A" labels BOTH the pin
  block and a connector drawing with "Bosch : 1 928 405 455" beneath it. Any proximity-based
  pin reader will read part numbers as pins (8.4: 44 of 64 false compositions).
- **A BM25 tokenizer change is an INDEX property.** Changing the shared tokenizer globally
  would silently break the production index (query `cylinder_2` vs corpus `cylinder`,`2`).
  Record the option in the index and have the Retriever read it — see `cylinder_compound`.
- **Never append lexicon aliases to the DENSE text.** It gives near-duplicate families
  (injectors 1–4) identical alias strings, pulls their embeddings together, and broke a
  baseline-passing guardrail (config C6). Aliases go to BM25 only.
- **A "better" embedder breaks the relevance gate.** bge/gte/e5 all refused 0/6
  out-of-scope queries with the MiniLM-calibrated threshold. Recalibrate before swapping.
- **Subsystem-level aliases must be right for every record in the subsystem.** Mixed
  subsystems (engine_position = crank + cam) need description-level aliases, or a cam DTC
  gets crank aliases.
- **TEST v2.2 is SPENT (evaluated in 8.5).** Do not report new results on it as held-out.
- **Never tune against TEST in `data/gold_v2.json`**, and never look at TEST
  per-query misses. `src/evaluate_v2.py` withholds them on purpose.
- **An anti-copy substring check is not enough to keep a gold set honest.** It passed
  every original TEST query while they reused ~2.5x more manual vocabulary than DEV.
  Run `src/check_gold.py` (word-overlap ceiling, defined in `src/gold_overlap.py`)
  before freezing any split. Domain nouns like "sensor" must COUNT as overlap — an
  ad-hoc stoplist that dropped them understated DEV's overlap (0.12 vs true 0.168).
- **Codes are not unique keys — this applies to overrides too.** `MANUAL_CORRECTIONS`
  asserts the page, so an override cannot attach to a same-coded record elsewhere.
- **Never gate on Chroma's top-1 distance.** HNSW is approximate: three runs of the
  same deterministic check gave 27/31, 28/31 and 29/31 while the embeddings were
  byte-identical across processes. `retrieve.exact_max_sim()` does brute force over
  all 314 vectors (~482 KB) instead. Ranking tolerates approximation; thresholds
  do not.
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
- [phase7_evaluation.md](phase7_evaluation.md) — the v1 results chapter
- [phase8_0_eval_foundation.md](phase8_0_eval_foundation.md) — gold v2.1, overlap rule, split correction, baselines, L2 fixes
- [phase8_2_symptom_retrieval.md](phase8_2_symptom_retrieval.md) — gold v2.2, embedder benchmark, lexicon, C4/C4b, guardrails
- [phase8_3_relevance_gate.md](phase8_3_relevance_gate.md) — two-reason gate, thresholds, intent taxonomy
- [phase8_3b_determinism.md](phase8_3b_determinism.md) — exact ranking, 3-process proof, corrected DEV baseline
- [phase8_4_image_pins.md](phase8_4_image_pins.md) — composition OCR: recall, audited precision, verdict
- [phase8_5_final_eval.md](phase8_5_final_eval.md) — **the Phase 8 results chapter**: one-shot TEST, ablations, adoption
- [phase9_1_advise_mode.md](phase9_1_advise_mode.md) — top-3 DTCs with fix steps; the step/spec column parse defect
