# Phase 8.5 — Final One-Shot TEST Evaluation and Adoption

**Phase 8 capstone.** The frozen TEST split was evaluated **exactly once**, under a protocol
committed and pushed **before** the run, and the selected configuration was then adopted as
the production default.

## Headline

> **Conservative TEST result (both ablations, config d), gold v2.2, 36 queries:**
> overall **hit@1 46.2%, MRR 0.601** · symptom **hit@1 23.1%, MRR 0.368** ·
> out-of-scope refused **2/6** · in-scope passed **30/30**.
>
> Against the v1-phase7 system on the same TEST split: overall MRR **0.562 → 0.601**,
> symptom MRR **0.291 → 0.368**, symptom hit@1 **unchanged at 23.1%**,
> and out-of-scope refusal **worse: 3/6 → 2/6**.

The full, adopted configuration (a) scores much higher on TEST — symptom MRR **0.628**, gate
**6/6**. The ablations show how much of that gain depends on vocabulary shared with the TEST
queries. **Most of the Phase 8 symptom gain on TEST comes from lexicon entries whose wording
also appears in TEST.** That is the honest reading of this result.

---

## Protocol

1. **Determinism re-confirmed on this machine first.** `scripts/determinism_proof.py` ran three
   times, and the DEV hash was `76b16c2b9ab8f9f2` in all three, matching Phase 8.3b.
2. **Pre-registration.** Commit `16a03c6` recorded, before any TEST run: the five
   configurations, the one-shot script, and the sha256 of every input — gold set, records,
   both lexicons, both stoplists, all gate configs, and the three indexes' BM25 corpora
   (`data/experiments/8_5/preregistration.json`). It was pushed to origin before TEST was run.
3. **One shot, enforced in code.** `scripts/final_test_eval.py` evaluates DEV and then TEST in a
   single pass, and refuses to run if its results file already exists. It was run once.
4. **Nothing was changed after seeing TEST.** No threshold, lexicon entry, stoplist term or
   configuration was altered. After adoption, every pre-registered data and config file still
   matches its registered hash; `data/gate_c4b.json` was briefly annotated and then reverted to
   keep it so.

### Ablation design

| ablation | removed | how |
|---|---|---|
| lexicon | the **19** entries whose colloquial terms appear in TEST query wording | removed from **both** the index aliases **and** query expansion: a separate index was built from the ablated lexicon, since removing them only at query time would leave them inside the index |
| gate stoplist | the **8** intent terms appearing in TEST query wording (50 → 42) | ablated stoplist; DEV-calibrated thresholds unchanged |

Both counts match the audits recorded in 8.2 and 8.3.

---

## The four TEST tables

### (a) full lexicon + full gate stoplist — *the adopted production configuration*

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 42.9% | 85.7% | 100.0% | 0.679 |
| symptom | 13 | 53.8% | 69.2% | 84.6% | 0.628 |
| **overall** | 26 | **61.5%** | 80.8% | 92.3% | **0.728** |

system_group complete **4/4** · gate: out-of-scope refused **6/6**, in-scope passed **30/30**

### (b) lexicon ablated + full gate stoplist

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 42.9% | 100.0% | 100.0% | 0.690 |
| symptom | 13 | 23.1% | 46.2% | 61.5% | 0.368 |
| **overall** | 26 | **46.2%** | 73.1% | 80.8% | **0.601** |

system_group complete **4/4** · gate: out-of-scope refused **6/6**, in-scope passed **30/30**

### (c) full lexicon + gate stoplist ablated

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 42.9% | 85.7% | 100.0% | 0.679 |
| symptom | 13 | 53.8% | 69.2% | 84.6% | 0.628 |
| **overall** | 26 | **61.5%** | 80.8% | 92.3% | **0.728** |

system_group complete **4/4** · gate: out-of-scope refused **2/6**, in-scope passed **30/30**

### (d) BOTH ablated — **conservative headline**

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 42.9% | 100.0% | 100.0% | 0.690 |
| symptom | 13 | 23.1% | 46.2% | 61.5% | 0.368 |
| **overall** | 26 | **46.2%** | 73.1% | 80.8% | **0.601** |

system_group complete **4/4** · gate: out-of-scope refused **2/6**, in-scope passed **30/30**

### Before: v1-phase7 system on the same TEST split

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 42.9% | 100.0% | 100.0% | 0.690 |
| symptom | 13 | 23.1% | 30.8% | 46.2% | 0.291 |
| **overall** | 26 | **46.2%** | 65.4% | 73.1% | **0.562** |

system_group complete **4/4** · gate: out-of-scope refused **3/6**, in-scope passed **29/30**

*Re-measured in the same one-shot pass with the current exact ranking. The earlier recorded
figures (`data/baseline_v2_1.json`, measured with approximate HNSW ranking on the identical
TEST queries) were overall MRR 0.562 and symptom MRR 0.291, which agree.*

---

## Summary — TEST vs DEV

### TEST (one shot)

| config | symptom hit@1 | symptom MRR | near-dup MRR | overall hit@1 | overall MRR | OOS refused | in-scope passed |
|---|---|---|---|---|---|---|---|
| v1-phase7 (before) | 23.1% | 0.291 | 0.690 | 46.2% | 0.562 | 3/6 | 29/30 |
| (a) full + full | 53.8% | 0.628 | 0.679 | 61.5% | 0.728 | 6/6 | 30/30 |
| (b) lexicon ablated | 23.1% | 0.368 | 0.690 | 46.2% | 0.601 | 6/6 | 30/30 |
| (c) stoplist ablated | 53.8% | 0.628 | 0.679 | 61.5% | 0.728 | 2/6 | 30/30 |
| **(d) both ablated — HEADLINE** | 23.1% | 0.368 | 0.690 | 46.2% | 0.601 | 2/6 | 30/30 |

### DEV (deterministic, same pass)

| config | symptom hit@1 | symptom MRR | near-dup MRR | overall hit@1 | overall MRR | OOS refused | in-scope passed |
|---|---|---|---|---|---|---|---|
| v1-phase7 (before) | 16.7% | 0.278 | 0.821 | 52.0% | 0.603 | 4/6 | 27/28 |
| (a) full + full | 58.3% | 0.711 | 1.000 | 80.0% | 0.861 | 6/6 | 28/28 |
| (b) lexicon ablated | 33.3% | 0.542 | 0.893 | 64.0% | 0.750 | 6/6 | 28/28 |
| (c) stoplist ablated | 58.3% | 0.711 | 1.000 | 80.0% | 0.861 | 5/6 | 28/28 |
| **(d) both ablated — HEADLINE** | 33.3% | 0.542 | 0.893 | 64.0% | 0.750 | 5/6 | 28/28 |

---

## What the ablations show

### 1. The symptom gain largely depends on TEST-shared vocabulary

| TEST symptom | hit@1 | MRR |
|---|---|---|
| v1 (no lexicon) | 23.1% | 0.291 |
| (d) lexicon without TEST-matching entries | 23.1% | 0.368 |
| (a) full lexicon | 53.8% | 0.628 |

- Full lexicon over v1: **+0.337** MRR.
- Without the 19 TEST-matching entries: **+0.077** MRR, and **no gain at hit@1**.
- The general entries mostly move the correct DTC up *into* the top 5 (hit@5 46.2% → 61.5%) rather than to rank 1.

Per query:

| id | query | v1 | (a) | (d) |
|---|---|---|---|---|
| t048 | moisture got into the diesel and the separator warning keeps coming on | — | 1 | 1 |
| t049 | truck won't fire, quantity valve output lead is earthed | — | 3 | — |
| t050 | fuel lift switching unit coil wire has snapped | — | 1 | 2 |
| t051 | the adblue has turned to solid ice after a freezing night | — | 1 | — |
| t052 | scr nox cleaning brick has aged out and stopped working | 1 | 1 | 1 |
| t053 | engine screaming past the redline, rev needle in the red | 3 | 3 | 3 |
| t054 | burnt residue has packed the exhaust soot trap solid and it cannot be cleared by burning | 5 | 4 | 5 |
| t055 | the dash burn-off switch the driver presses seems jammed in | — | — | — |
| t056 | intercooler barely dropping intake air temps on climbs | 4 | 4 | 4 |
| t057 | speedo needle jumps about and does not match how fast we are really going | — | 1 | — |
| t058 | cranks on the starter but the injection side never comes up to strength | — | — | — |
| t059 | the clutch pedal contact tells the ECU nonsense about whether it is pressed | 1 | 1 | 1 |
| t060 | cranking solenoid trigger wire from the ECU to the starter has snapped | 1 | 1 | 2 |

The same pattern is visible on DEV. There the gap between full and ablated lexicon is smaller
(symptom MRR 0.711 vs 0.542), because the ablation removes entries by *TEST* wording and some of them
also serve DEV.

**Why this happened.** The TEST-matching entries are largely standard technician synonyms
(*speedo, intercooler, redline, earthed, adblue, soot trap*). They are good lexicon content,
which is why they stay in production. But the TEST queries were written by the same author, in
the same technician register, and some brief-specified synonyms came from TEST wording visible
in earlier reports. The lexicon's TEST performance is therefore partly an echo of shared
authorship, not purely generalization, and the ablated number is what can be defended.

### 2. The gate's TEST success depended on the TEST-matching intent terms

| id | query | v1 | (a) full | (d) both ablated |
|---|---|---|---|---|
| t065 | what is the resale value of a five year old truck | **answered ✗** | refused (non_diagnostic_intent) | **answered ✗** |
| t066 | how long is the free service period after purchase | **answered ✗** | refused (non_diagnostic_intent) | **answered ✗** |
| t067 | can I get a discount on the extended warranty | refused | refused (low_retrieval_signal, non_diagnostic_intent) | refused (low_retrieval_signal) |
| t068 | where can I buy a genuine air filter nearby | refused | refused (non_diagnostic_intent) | **answered ✗** |
| t069 | what time does the service centre open on Sunday | refused | refused (non_diagnostic_intent) | refused (low_retrieval_signal) |
| t070 | how do I pair bluetooth with the infotainment unit | **answered ✗** | refused (low_retrieval_signal, non_diagnostic_intent) | **answered ✗** |

- With the full stoplist, gate v2 refuses **6/6**.
- With the 8 TEST-matching terms removed it refuses **2/6** — **one fewer than v1**. The cause is
  the recalibrated signal threshold: gate v2 lowered `dense_min` from 0.30 to **0.23** so that
  paraphrased in-scope queries pass. With intent terms missing, *"where can I buy a genuine air
  filter nearby"* scores **dense 0.261, bm25 7.13** — above gate v2's 0.23, below v1's 0.30 —
  so it now passes, where v1 refused it (verified post-hoc).
- The design deliberately traded signal strictness for the intent filter. On unfamiliar
  commercial phrasing, the trade is net negative.
- In-scope passing improved in every gate-v2 configuration: **29/30 → 30/30**.

### 3. One near-duplicate regression, caused by TEST-matching entries

Near-duplicate MRR on TEST: v1 **0.690**, (a) **0.679**, (d) **0.690**. One query moved:
*t046 "urea return pump has come unplugged"* went from rank 3 (v1) to **4** under the full
lexicon, and back to 3 when ablated. DEV showed near-duplicates rising to 1.000, so **DEV
overstated the near-duplicate gain**; on TEST it is flat to slightly negative.

### 4. What held up

- **Exact-code lookup: 100% hit@1 on every configuration**, DEV and TEST.
- **System grouping: complete on every configuration** (4/4 TEST, 3/3 DEV).
- **No in-scope query was wrongly refused** by gate v2 on TEST (30/30).
- **Determinism:** identical results across processes and hash seeds, on this machine.

---

## Before / after — Phase 7 → Phase 8

Phase 7's headline (MRR 0.685) was measured on gold **v1**, a different and easier set of 38
queries, so it is not comparable. The comparable before/after is v1-phase7 vs Phase 8 on
**gold v2.2 TEST**:

| TEST (gold v2.2) | v1-phase7 | Phase 8 conservative (d) | Phase 8 adopted (a) |
|---|---|---|---|
| exact-code hit@1 | 100% | 100% | 100% |
| near-duplicate MRR | 0.690 | 0.690 | 0.679 |
| symptom hit@1 | 23.1% | 23.1% | 53.8% |
| symptom MRR | 0.291 | 0.368 | 0.628 |
| **overall MRR** | **0.562** | **0.601** | **0.728** |
| out-of-scope refused | 3/6 | 2/6 | 6/6 |
| in-scope passed | 29/30 | 30/30 | 30/30 |
| reproducible across processes | no (HNSW) | yes | yes |

Non-retrieval Phase 8 results, unaffected by TEST: **5 skip-branch routing corrections** (8.1),
**injector cylinder discrimination 11/14 → 14/14** guardrails (8.2b), **deterministic retrieval**
(8.3b), and a **characterized image-pin limitation** (8.4).

---

## Adoption

Adopted **after** TEST was measured, as instructed. Configuration (a) is adopted, not (d): the
ablations are a *measurement* device for estimating generalization, not a statement that the
TEST-matching synonyms are wrong. For real technicians, *speedo* and *intercooler* are exactly
the vocabulary the lexicon should hold. On TEST, (a) beats v1 on symptom, gate and in-scope
passing, and loses one near-duplicate rank position.

| step | result |
|---|---|
| Live `index/` rebuilt: `build_index.py --rebuild --aliases bm25 --cylinder-token` | 314 vectors |
| Identical to the evaluated C4b index? | **yes** — BM25 corpus sha256 identical, dense vectors byte-identical, metadata equal |
| `Retriever()` default | lexicon and BM25 expansion read from the **index's own metadata** (`lexicon="auto"`), `exact_dense=True`, cylinder token on |
| `answer.is_relevant()` / `answer()` / `app.py` default | **gate v2** (`data/gate_c4b.json`); `gate=None` still gives the legacy v1 gate |
| Determinism proof via the **production default construction path** | **`76b16c2b9ab8f9f2` × 3** — production is byte-for-byte the evaluated configuration |
| Full suite on the new default | **44 passed, 1 xfail, 0 failed** |
| 14 near-duplicate guardrails on the new default | **14/14** |
| Live FastAPI check | warranty question → refused (intent); *"adblue has turned to solid ice"* → **P10FF-00**; `P0192-00` → deterministic path |
| Previous system | preserved as git tag **`v1-phase7`** |

The configuration is recorded in `data/production_config.json`.

---

## Limitations (updated)

- **The TEST gain is mostly vocabulary shared with TEST.** Defensible symptom improvement over v1
  is +0.077 MRR, with no change in hit@1.
- **Gate v2 is weaker than v1 on unfamiliar commercial phrasing.** Without matching intent terms
  it refuses 2/6 vs v1's 3/6, a side effect of lowering `dense_min` to 0.23. Out-of-scope
  questions phrased outside the stoplist are a real risk; a broader, independently authored
  stoplist, or restoring a stricter signal floor for intent-free queries, is the next thing to test.
- **DEV overstated gains** — near-duplicates most visibly (DEV 1.000; TEST flat or slightly down).
  With 6–13 queries per mode per split, single queries swing results by 8–17 points.
- **The gold set, lexicon and stoplist share an author.** The biggest methodological weakness,
  and the reason the ablated number is the headline. An independent query author is the most
  valuable next investment.
- **Image-derived pins (8.4) are not usable:** 31% recall, 38% audited precision, 3 genuine new
  pins vs 61 false. `pin_map[]` stays text-derived; the image output is a labelled research file.
- **Determinism is proven on this machine and library stack only.**
- Carried forward: a lexicon cannot handle negation ("refuses to shut" = stuck open); number words
  and ordinals ("cylinder one", "3rd cylinder") are not normalized; `MANUAL_CORRECTIONS` is a
  hand-maintained list.

## Artifacts

- `data/experiments/8_5/preregistration.json` — protocol and input hashes, committed before the run
- `scripts/final_test_eval.py` — the one-shot evaluator
- `data/experiments/8_5/final_eval_results.json` — all five configurations × DEV and TEST, per-query
- `data/experiments/8_5/domain_lexicon_ablated.json`, `intent_stoplist_ablated.json`, gate variant configs
- `data/experiments/8_5/guardrails_production_default.json` — 14/14 on the adopted default
- `data/experiments/8_3b/dev_prod_defaults_adopted_p{0,1,2}.json` — adoption determinism proof
- `data/production_config.json` — the adopted configuration
