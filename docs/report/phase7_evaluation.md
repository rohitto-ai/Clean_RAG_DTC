# Phase 7 — Evaluation, Integrity Walk & Service

This is the results chapter. It reports the first end-to-end quality numbers the
project has, validates the riskiest inference made in Phase 6, walks all 314 step
graphs, and stands up the demo service.

## Objective

Measure what was previously only spot-checked: retrieval quality against a
hand-built gold set, honesty on out-of-scope questions, and the structural
soundness of every DTC's decision tree. Then expose it over FastAPI.

---

## 1. Validating the `skip_true_branch` inference (highest-risk item)

Phase 6 added an inference: when a conditional step's `on_true` target **is** the
next step, the false branch skips that step. It was applied to **256 conditional
steps** but verified on only one DTC. So it was audited first.

### Sizing it before judging it

| | count | share |
|---|---|---|
| Total candidates (`condition` set and `on_true == n+1`) | 256 | 100% |
| **Benign** — no step after the true target, so both branches land on the terminal anyway | **155** | **61%** |
| **Behaviour-changing** — a real skip occurs | **101** | 39% |
| …of those, the skip lands on a *fix-verb* step (the risky shape) | **6** | 2.3% of all |

So 61% of applications cannot change an outcome at all.

### Manual audit of 25 sampled cases, across 25 distinct DTCs

Each case was judged by reading the actual text of the step being skipped.

| Verdict | n | Meaning |
|---|---|---|
| **CORRECT** | 7 | The skipped step is a fix that only applies if the condition held (e.g. *"Fix the back-out cables…"* after *"…any wire back-out, if yes go to step 3"*). Skipping it on "no" is right. |
| **BENIGN** | 17 | The true target is the terminal step and nothing follows it — both answers reach "Clear and check DTC". The inference changes nothing. |
| **MISMATCH** | 1 | See below. |

**MATCH RATE: 24/25 = 96%** overall; **7/8 = 87.5%** among cases where the
inference actually changes behaviour.

### The one mismatch

`P0194-00` step 6: *"If error still present go to Step 7"* — where step 7 is a
**check** (*"Check the wire harness for any pin / wire back-out…"*) and step 8 is
the **fix** for that check (*"Fix the back-out cables…"*).

Answering **no** (error is gone) should end the procedure. Instead the inference
skips to step 8 and applies a fix for a check that was never performed.

Corpus-wide this shape occurs **6 times**: `P0192-00 s6`, `P0193-00 s6`,
`P0194-00 s6`, `P0194-00 s7`, `P0627-11 s4`, `P0627-13 s4` — i.e. **2.3% of the
256 applications**. Every use is logged as a `skip_true_branch` inference in the
diagnosis trace, so any affected walk is identifiable after the fact.

> **Correction (Phase 8.1, 2026-09-16):** verifying each case before fixing it showed
> **5 genuine mismatches, not 6.** `P0194-00 s7` was a false positive from the
> fix-verb detector: its true target is the *fix*, and its skip lands on s9 "Change the
> rail pressure sensor", which is reachable only via "no back-out found" — the correct
> flow. The corpus figure should read **5 cases (2.0%)**. The 24/25 audit match rate is
> unaffected. The five are now fixed via `MANUAL_CORRECTIONS`; see
> [phase8_0_eval_foundation.md](phase8_0_eval_foundation.md).

**This is a measured limitation, not a solved problem.** The 6 cases are listed so
they can be hand-corrected if this goes near a real workshop.

---

## 2. Gold query set (v1 draft — for review)

**38 queries** in `data/gold_queries.json`, covering all four modes plus the hard
cases. **Symptom queries are paraphrased in the evaluator's own words** — manual
description text is deliberately never copied into a query, or BM25 would match
trivially and the metric would be meaningless. (This bites: `"camshaft no signal"`
used to rank correctly; the paraphrase `"the cam sensor gives no output
whatsoever"` does not.)

| mode | n |
|---|---|
| exact_code | 8 |
| near_duplicate | 8 |
| symptom | 11 |
| system_group | 4 |
| out_of_scope | 7 |

<details><summary><b>Full gold set (auditable)</b></summary>

**exact_code**
| query | expected | notes |
|---|---|---|
| what does P0192-00 mean | P0192-00 | full code with suffix |
| P0340 | P0340-00 | base code, no suffix |
| P0180-11 | P0180-11 | DUPLICATE: must return both (pp. 100, 195) |
| show me trouble code P2153-00 | P2153-00 | code inside a sentence |
| how do I fix P0117-00 | P0117-00 | natural phrasing |
| P0100 | P0100-00, -9B, -9C | 3 suffix variants |
| details for U0102-00 | U0102-00 | U-family (CAN) |
| P042F-00 repair procedure | P042F-00 | code + intent |

**near_duplicate**
| query | expected | notes |
|---|---|---|
| the cam sensor gives no output whatsoever | P0340-00 | vs P0341-00 |
| cam position reading is erratic and noisy | P0341-00 | vs P0340-00 |
| crank position reading is noisy and unstable | P0336-00 | crank/cam confusion |
| number three injector has a broken winding | P0203-00 | cylinder 1–4 |
| cylinder one injector is shorted to the main feed | P2147-00 | vs P0201-00 |
| fuel rail sender pulled down to earth | P0192-00 | rail trio |
| fuel rail sender reading has drifted off calibration | P0194-00 | rail trio |
| fuel rail sender wire is broken or touching positive | P0193-00 | rail trio |

**symptom**
| query | expected |
|---|---|
| engine will not crank up and there is no signal from the cam | P0340-00 |
| coolant gauge stuck reading at the bottom of the scale | P0117-00 |
| the wire to the engine temperature sender has gone open | P0118-00 |
| exhaust recirculation flap is seized shut | P042F-00 |
| exhaust recirculation flap is seized wide open | P042E-00 |
| soot trap is completely blocked up | P244B-00 |
| adblue tank has almost run dry | P203F-00 / P203F-7B |
| charge pressure from the turbo is under target | P0047-00 / P004C-00 / P006E-00 |
| throttle pedal sensors do not agree with each other | P2135-00 |
| supply voltage is reading above the permitted ceiling | P0562-00 |
| loss of pulling power with the dash warning light on | rail-pressure family |

**system_group**: list all EGR faults · show me every injector related fault code ·
what soot trap faults are there · all fuel rail pressure codes

**out_of_scope**: how do I change a tyre · what is the capital of France · how much
does this truck cost · what gearbox oil viscosity should I use · book me a service
appointment · how do I reset my mobile phone · what is the warranty period on this
engine
</details>

---

## 3. Retrieval metrics

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| **exact_code** | 8 | **100.0%** | 100.0% | 100.0% | **1.000** |
| **near_duplicate** | 8 | 62.5% | 87.5% | **100.0%** | 0.760 |
| **symptom** | 11 | **27.3%** | 54.5% | 63.6% | 0.402 |
| **OVERALL** | 27 | 59.3% | 77.8% | 85.2% | **0.685** |

- **Near-duplicate rank-1 accuracy: 5/8 (62.5%)**, hit@5 100% — the right answer is
  always retrieved, sometimes not ranked first.
- **system_group: 4/4 exact** — correct mode, correct subsystem, complete group.

### Reading these numbers honestly

**exact_code is solved.** 100% at rank 1, MRR 1.000, including duplicates and
unsuffixed codes. This is the primary technician workflow and it is exact.

**Symptom retrieval is the weak point at 27.3% hit@1.** The cause is vocabulary, not
ranking: the manual writes formal ECU terminology while a technician describes a
symptom. `"exhaust recirculation flap is seized shut"` misses `P042F-00`
(*"EGR valve jammed at closed position"*) entirely — no lexical overlap for BM25,
and MiniLM does not bridge *flap↔valve*, *seized↔jammed*, *soot trap↔Diesel
Particulate Filter*. This is exactly what the paraphrase discipline was designed to
expose, and it did.

The honest read: **this system is excellent at code lookup, good at
near-duplicates, and weak at free-text symptom search.** The fix is a domain
synonym/expansion layer at query time (flap→valve, soot trap→DPF, sender→sensor,
seized→jammed/stuck), which is a contained piece of work and the clear next step.
It was **not** done here — tuning retrieval against the same gold set that measures
it would invalidate the metric.

---

## 4. Honesty / grounding

| | result |
|---|---|
| Out-of-scope correctly gated (no answer) | **6 / 7** |
| In-scope passed the gate | **29 / 31** |

**The fabrication this prevents.** Before the gate existed, asked *"how do I change
a tyre"* with irrelevant DTC context, Qwen2.5-0.5B produced confident invented
instructions, including a fabricated specification:

> *"**Check the Tire Pressure**: Ensure that the pressure on all four tires is
> within the recommended range. This is typically **between 30-40 psi for a 3.3L
> NGE BSVI engine**."*

That number appears nowhere in the manual and the manual has nothing to say about
tyres. It now returns `That is not covered in this manual.` from the deterministic
gate, and the model is never invoked.

**The failures, both explicable:**
- **1 leak:** *"what is the warranty period on this engine"* (dense 0.322, bm25 9.17)
  passes because *"engine"* is genuinely a corpus term. Vehicle-adjacent commercial
  questions are the gate's blind spot.
- **2 wrongly gated:** the two *"soot trap"* queries (dense 0.25–0.27). Same
  vocabulary gap as the symptom weakness — a synonym layer would fix the gate and
  symptom retrieval together.

Thresholds (`dense ≥ 0.30` **or** `bm25 ≥ 8.0`) were calibrated on 11 queries and
clearly do not fully generalise to 38.

---

## 5. Corpus-wide integrity walk (all 314 records)

Every DTC's step graph was traversed under four answer policies (all-yes, all-no,
alternating both ways), bounded.

| metric | value |
|---|---|
| Records walked | **314** |
| Records where a branch **fails to reach a terminal step** | **0** |
| Records needing a clamp | 13 |
| Total clamps fired | 33 |
| Records needing a `skip_true_branch` inference | 146 |
| Total inferences fired | 326 |
| Loop-guard fires | 0 |

**No dead ends.** Every branch of every DTC reaches a terminal step. This is the
strongest structural result in the project: despite 37 out-of-range targets, 4
self-references and widespread mis-numbering in the source, the traversal always
terminates correctly.

Loop-guard fires are 0 in practice — the 4 self-referencing steps are on paths the
clamp resolves first. The guard is retained as a safety net and is exercised by a
synthetic cycle test in the suite.

---

## 6. FastAPI service

```bash
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

| endpoint | purpose |
|---|---|
| `GET /health` | readiness, record/vector counts, whether the LLM is loaded |
| `POST /query` | retrieve → answer; returns answer, citations, mode, path, trace |
| `POST /diagnose` | stateful walk: start with `code_full`, continue with `session_id` + `answer` |

Verified live:

```
$ curl -s localhost:8000/health
{"status":"ok","records":311,"vectors":314,"bm25_docs":314,"model_loaded":false}

$ curl -s -X POST localhost:8000/query -d '{"query":"how do I fix P0192-00"}'
mode=exact_code  path=deterministic  citations=[{"code_full":"P0192-00","page":8}]

$ curl -s -X POST localhost:8000/query -d '{"query":"how do I change a tyre"}'
path=deterministic_gate  "That is not covered in this manual."
```

A full `/diagnose` session on P0192-00 answering no,no,no,no,yes walked
`1 → 2 → 3 → 4 → 5 → 12 → 13` and terminated at "Check DTC" with the path trace,
clamps and inferences attached. `model_loaded:false` on `/health` confirms the
fast path never loads the LLM.

## 7. LLM prose cleanup (no model change)

`max_tokens` 320 → **120**, stop sequences added, and the prompt tightened to
"2–4 sentences; state the code, what it means, and the first thing to check; do not
restate field names or say a field is NA."

| | before | after |
|---|---|---|
| Typical answer | 148 tokens, 9.07 s | **30–116 tokens, 6.9–8.5 s** |
| Sample output | *"…The DTC also mentions that the system is coolant, and the effect on the vehicle is NA."* | *"(DTC P0117-00) Coolant temperature sensor signal Short circuit to ground. First thing to check: Check Battery Voltage."* |

Still Qwen2.5-0.5B, as instructed.

---

## Evidence & Artifacts

- [src/evaluate.py](../../src/evaluate.py) · [data/gold_queries.json](../../data/gold_queries.json) · `data/evaluation_results.json`
- [app.py](../../app.py) — FastAPI service
- Suite: **30 passed, 1 xfail, 0 failed** (`PYTHONPATH=src .venv/bin/python src/smoke_index.py`)

## Issues Found & Fixed

1. **Non-reproducible evaluation numbers.** Consecutive runs of the same
   deterministic honesty check returned 27/31, 28/31 and 29/31. Embeddings were
   verified **byte-identical across three separate processes**, and HNSW was
   verified to match a brute-force nearest-neighbour search — so the variance came
   from Chroma's approximate index state, not the model. Ranking tolerates that; a
   **threshold** must not. `is_relevant()` now computes similarity by **exact
   brute force** over all 314 stored vectors (314 × 384 floats ≈ 482 KB — trivially
   cheap). Verified stable across three consecutive runs.
2. **Terminal step was re-presented** after the walk finished; `state.current` is
   now cleared.
3. LLM rambling — capped and constrained, above.

## Limitations

- **`skip_true_branch` is right 24/25 sampled, wrong in 6 identified corpus cases.**
  Listed in §1 for hand-correction.
- **Symptom retrieval is weak (27.3% hit@1)** — a vocabulary gap, not a ranking bug.
  A synonym/query-expansion layer is the clear next work item, deliberately not done
  here so the metric stays honest.
- **The relevance gate leaks vehicle-adjacent commercial questions** and blocks
  heavily paraphrased in-scope ones. Same root cause.
- **The gold set is v1 and self-authored** (38 queries). It should be reviewed, and
  ideally extended by someone who has not seen the retrieval internals.
- **`/diagnose` sessions are in-process memory** — a demo surface, not a service.
- **No `/ingest` endpoint.** The pipeline is run as scripts; wiring ingestion behind
  HTTP was not needed for the demo and is not built.
