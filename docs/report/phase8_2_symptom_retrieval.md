# Phase 8.2 — Closing the Symptom Vocabulary Gap (L1)

**Scope: tuned and reported on DEV only. The frozen TEST split was NOT evaluated in this
phase** — `src/evaluate_v2.py` now defaults to DEV and requires `--split TEST`
explicitly, and the benchmark driver filters TEST out before loading anything. TEST is
evaluated once, at Phase 8.5.

## Objective

Symptom retrieval was the weakest mode (Phase 7: 27.3% hit@1). The cause is vocabulary:
the manual writes formal ECU terminology while technicians describe symptoms in workshop
English. This phase tests two remedies — a stronger embedder and a curated domain
lexicon — without breaking near-duplicate discrimination.

---

## Preamble — a uniform overlap ceiling (gold v2.2)

The 0.15 word-overlap ceiling applied only to TEST in v2.1, leaving 8 grandfathered DEV
symptom queries above it. Those 8 were rewritten under the same rule, same expected
DTCs, scored by `src/gold_overlap.py` only — **retrieval was not run while authoring**.
`src/check_gold.py` now enforces the ceiling on **both** splits.

| id | old query | old | new query | new | expected |
|---|---|---|---|---|---|
| d015 | exhaust recirculation flap is seized wide open | 0.167 | the recirculation flap on the egr pipe has seized and refuses to shut | **0.143** | P042E-00 |
| d017 | adblue tank has almost run dry | 0.250 | the adblue reservoir is nearly empty and low warning is showing | **0.143** | P203F-00, P203F-7B |
| d018 | coolant gauge stuck reading at the bottom of the scale | 0.167 | water temp gauge pegged cold, the reading line looks shorted | **0.111** | P0117-00 |
| d019 | the wire to the engine temperature sender has gone open | 0.333 | the water temp sensor lead has come adrift and gauge is dead | **0.125** | P0118-00 |
| d020 | throttle pedal sensors do not agree with each other | 0.250 | the go pedal's two throttle tracks disagree and power is cut | **0.125** | P2135-00 |
| d021 | supply voltage is reading above the permitted ceiling | 0.200 | alternator is overcharging and the battery sees far too many volts | **0.143** | P0562-00 |
| d023 | engine will not crank up and there is no signal from the cam | 0.250 | turns over but never fires, no signal coming from the cam pickup | **0.143** | P0340-00 |
| d025 | battery voltage keeps dipping under what the ECU will accept | 0.400 | system voltage keeps sagging and the ecu drops out on cold starts | **0.143** | P0563-00 |

| symptom overlap | mean | zero-overlap | over ceiling |
|---|---|---|---|
| DEV v2.1 | 0.168 | 4/12 | 8 |
| **DEV v2.2** | **0.090** | 4/12 | **0** |
| TEST v2.1 (unchanged) | 0.098 | 4/13 | 0 |

DEV and TEST difficulty now match on both mean overlap and zero-overlap count.

### Re-recorded DEV before-picture

| DEV baseline | symptom hit@1 | hit@3 | hit@5 | MRR | overall hit@1 | overall MRR |
|---|---|---|---|---|---|---|
| v2.1 (before DEV rewrite) | 25.0% | 58.3% | 66.7% | 0.396 | 56.0% | 0.660 |
| **v2.2 (8.2 before-picture)** | 16.7% | 41.7% | 41.7% | 0.278 | 52.0% | 0.603 |

DEV symptom hit@1 fell 25.0% → **16.7%** and MRR 0.396 → **0.278** — the queries got
harder, not the system worse. Exact-code and near-duplicate figures reproduced exactly,
confirming the retriever refactor left the production path untouched. The v2.1 baseline
is kept as `data/baseline_v2_1.json`.

---

## Part A — Embedder benchmark (dense side)

Each candidate is 384-dim and CPU-friendly; each got its own index (`index_exp/`), built
with its passage convention and queried with its query convention. Where the convention
was uncertain, both variants were run. Built one model at a time: ~25 s and 715–780 MB
peak each.

| embedder | symptom hit@1 | symptom hit@3 | symptom hit@5 | **symptom MRR** | overall MRR | dense-only symptom MRR | gate: OOS refused | gate: in-scope passed |
|---|---|---|---|---|---|---|---|---|
| all-MiniLM-L6-v2 (baseline) | 16.7% | 41.7% | 41.7% | **0.278** | 0.603 | 0.322 | 4/6 | 27/28 |
| bge-small-en-v1.5 (no instruction) | 16.7% | 25.0% | 33.3% | **0.229** | 0.557 | 0.315 | 0/6 | 28/28 |
| bge-small-en-v1.5 (+instruction) | 16.7% | 25.0% | 25.0% | **0.208** | 0.567 | 0.256 | 0/6 | 28/28 |
| gte-small | 16.7% | 33.3% | 33.3% | **0.250** | 0.590 | 0.294 | 0/6 | 28/28 |
| e5-small-v2 (query:/passage:) | 8.3% | 16.7% | 25.0% | **0.146** | 0.520 | 0.128 | 0/6 | 28/28 |
| e5-small-v2 (no prefixes) | 0.0% | 8.3% | 16.7% | **0.062** | 0.480 | 0.069 | 0/6 | 28/28 |

"Symptom MRR" is the full production system (dense + BM25 + RRF). "Dense-only" isolates the
embedder's own contribution.

### Findings

- **The baseline all-MiniLM-L6-v2 wins** on DEV symptom MRR and overall MRR, and also on
  dense-only symptom MRR. It is kept.
- **The margin over gte-small (0.028) is within noise** — about one query's worth on 12
  symptom queries. The defensible reading is "no candidate improved on MiniLM", not
  "MiniLM is clearly best".
- **Prefix conventions matter**, as expected: e5 without its `query:`/`passage:` prefixes
  collapses from 0.146 to 0.062. The BGE query instruction *hurt* here (0.229 → 0.208).
- **Every alternative embedder wrecks the relevance gate: 0/6 out-of-scope queries
  refused.** The dense threshold (0.30) is calibrated to MiniLM's similarity range; the
  others score everything higher. Swapping embedders would have silently reopened the
  fabrication hole from Phase 6. Not recalibrated here — that is Phase 8.3 — but it is a
  second, independent reason to keep MiniLM.

---

## Part B — The domain lexicon

`data/domain_lexicon.json`, loaded by `src/lexicon.py`. **42 entries** —
30 `general`, 12 `user`, 0 `dev_driven`.

### Structure

| section | scope | index side | query side |
|---|---|---|---|
| `system_aliases` | every record of one subsystem | colloquial names appended to the record | colloquial term in query → append manual terms |
| `term_synonyms` | records whose **description** contains the manual term (optionally restricted to listed subsystems) | colloquial synonyms appended | colloquial term in query → append manual terms |

Aliases are **never derived from step text.** Steps are boilerplate shared across hundreds
of DTCs; aliasing them would push near-duplicates back together.

### Design correction made before any evaluation (v1 → v2)

The first draft put aliases at subsystem level wherever it could. Auditing the resulting
per-record alias strings — before any retrieval run — showed that was wrong for **mixed
subsystems**: `engine_position` holds both crank and cam DTCs, so the camshaft record
P0340-00 received `crank pickup`/`crank sensor`. Likewise `lift pump` landed on fuel
*temperature* sensors, `soot trap` on DOC temperature sensors, and `nox probe` on the
exhaust-temperature sensor. That is the "injector aliases on EGR records" failure at a
finer grain.

**Rule added:** an alias stays subsystem-level only if it is correct for *every* record in
the subsystem; otherwise it is description-level. After v2, P0340-00 carries only cam
terms, P0336-00 only crank terms, and the clutch-switch record no longer receives pedal
aliases.

### Provenance and TEST-contamination audit

Each entry is tagged `general` (standard technician synonym), `user` (listed in the 8.2
brief), or `dev_driven` (added after a DEV miss — **none were added**). Two flags are
**computed** from gold query text, never hand-set: whether a colloquial term appears in a
DEV query, and whether it appears in a TEST query.

**19 of 42 entries match TEST query wording.** Several of the brief's own
examples — *speedo, intercooler, redline, earthed, adblue, soot trap* — are words written
into the TEST v2.1 queries, which were visible in the Phase 8.0 report. Standard synonyms
or not, including them makes TEST optimistic. They are kept, and **Phase 8.5 will report
TEST twice: with the full lexicon, and with these 19 entries ablated**
(`Lexicon(exclude_test_matching=True)`), giving an uncontaminated lower bound.

| entry | provenance | colloquial term(s) matching TEST query wording |
|---|---|---|
| `system:vehicle_speed` | user | speedo |
| `system:exhaust_throttle` | general | exhaust brake |
| `system:can_network` | general | can bus |
| `term:ground` | user | earthed |
| `term:sensor` | user | probe |
| `term:vehicle speed` | user | speedo |
| `term:charge air cooler` | user | intercooler |
| `term:engine speed` | user | redline |
| `term:open circuit` | general | snapped |
| `term:plausibility/not plausible/incompatible` | general | nonsense |
| `term:frozen` | general | ice |
| `term:deteriorated` | general | aged |
| `term:temperature` | general | temp |
| `term:crankshaft` | general | crank |
| `term:particulate filter/dpf` | user | soot trap |
| `term:soot` | user | soot trap |
| `term:regeneration` | general | burn-off |
| `term:urea/def/reductant/diesel exhaust fluid` | user | adblue |
| `term:nox sensor` | general | nox probe |

---

## Part C — Combining, with guardrails

Lexicon configurations on MiniLM (plus one on gte-small for comparison). "Aliases" =
index side; "expansion" = query side.

| config | symptom hit@1 | hit@5 | **symptom MRR** | near-dup MRR | overall MRR | guardrails | degrades a baseline-passing guardrail? | gate OOS / in-scope |
|---|---|---|---|---|---|---|---|---|
| C0 baseline (no lexicon) | 16.7% | 41.7% | **0.278** | 0.821 | 0.603 | 11/14 | no | 4/6 · 27/28 |
| C1 aliases->BM25 | 41.7% | 91.7% | **0.600** | 0.905 | 0.781 | 12/14 | no | 4/6 · 28/28 |
| C2 expansion->BM25 | 41.7% | 75.0% | **0.531** | 0.893 | 0.745 | 12/14 | no | 4/6 · 27/28 |
| C3 expansion->BM25+dense | 41.7% | 83.3% | **0.576** | 0.905 | 0.770 | 12/14 | no | 4/6 · 27/28 |
| C4 aliases->BM25 + expansion->BM25 | 58.3% | 91.7% | **0.715** | 1.000 | 0.863 | 12/14 | no | 4/6 · 28/28 |
| C5 aliases->BM25+dense + expansion->BM25 | 50.0% | 100.0% | **0.722** | 1.000 | 0.867 | 13/14 | **YES** — injector short circuit high and low side cylinder 1 | 4/6 · 28/28 |
| C6 aliases->BM25+dense + expansion->BM25+dense | 58.3% | 100.0% | **0.778** | 1.000 | 0.893 | 13/14 | **YES** — injector short circuit high and low side cylinder 1 | 4/6 · 28/28 |
| C7 gte-small: aliases->BM25 + expansion->BM25 | 41.7% | 66.7% | **0.528** | 1.000 | 0.773 | 14/14 | no | 0/6 · 28/28 |

### Guardrail matrix — near-duplicate discrimination

Colloquial phrasings ("cylinder N injector has a broken wire") are included deliberately:
they trigger the *same* aliases on all four injector records, so they are the queries that
would expose aliasing re-collapsing a near-duplicate family.

| guardrail | expected | C0 | C1 | C2 | C3 | C4 | C5 | C6 | C7 |
|---|---|---|---|---|---|---|---|---|---|
| camshaft no signal | P0340-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| camshaft disturbed signal | P0341-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| injector open circuit cylinder 1 | P0201-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| cylinder 1 injector has a broken wire | P0201-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| injector short circuit high and low side cylinder 1 | P1201-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✗ r2 | ✗ r2 | ✅ |
| injector open circuit cylinder 2 | P0202-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| cylinder 2 injector has a broken wire | P0202-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| injector short circuit high and low side cylinder 2 | P1202-00 | ✗ r2 | ✗ r2 | ✗ r2 | ✗ r2 | ✗ r2 | ✅ | ✅ | ✅ |
| injector open circuit cylinder 3 | P0203-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| cylinder 3 injector has a broken wire | P0203-00 | ✗ r2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| injector short circuit high and low side cylinder 3 | P1203-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| injector open circuit cylinder 4 | P0204-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| cylinder 4 injector has a broken wire | P0204-00 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| injector short circuit high and low side cylinder 4 | P1204-00 | ✗ r2 | ✗ r2 | ✗ r2 | ✗ r2 | ✗ r2 | ✅ | ✅ | ✅ |

`✗ rN` = the expected code ranked N instead of 1.

### Selection: C4 — aliases → BM25, expansion → BM25, dense side untouched

- **C5 and C6 are rejected.** C6 has the best DEV symptom MRR (0.778) but **breaks a
  guardrail that passes in the baseline**: "injector short circuit high and low side
  cylinder 1" drops P1201-00 to rank 2. Cause: appending the lexicon to the **dense** text
  gives all four injector records an identical alias string, and embedding it pulls their
  vectors together — the very collapse the per-record rule was meant to prevent, arriving
  through the embedding instead of BM25. Under the brief's rule, a lexicon that breaks a
  guardrail does not ship. The 0.063 MRR it gives up is also within noise.
- **C7 (gte-small) is rejected** despite passing 14/14 guardrails: lower symptom MRR
  (0.528) and a broken gate (0/6).
- **C4 degrades no guardrail**, fixes one, and keeps the dense representation exactly as
  it was — which is what makes it safe.

### DEV before / after — C4 vs baseline

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% → **100.0%** | 100.0% → **100.0%** | 100.0% → **100.0%** | 1.000 → **1.000** |
| near_duplicate | 7 | 71.4% → **100.0%** | 85.7% → **100.0%** | 100.0% → **100.0%** | 0.821 → **1.000** |
| symptom | 12 | 16.7% → **58.3%** | 41.7% → **83.3%** | 41.7% → **91.7%** | 0.278 → **0.715** |
| **OVERALL** | 25 | 52.0% → **80.0%** | 68.0% → **92.0%** | 72.0% → **96.0%** | 0.603 → **0.863** |

- system_group complete: 3/3 → 3/3
- Gate — out-of-scope refused: 4/6 → 4/6; in-scope passed: 27/28 → **28/28**

**Symptom MRR 0.278 → 0.715 (+0.437); hit@1 16.7% → 58.3%; hit@5 41.7% → 91.7%.**
Near-duplicate hit@1 also rose 71.4% → 100%. No mode regressed.

### Per-query symptom movement

| id | query | C0 rank | C4 rank |
|---|---|---|---|
| d014 | exhaust recirculation flap is seized shut | — | **3** |
| d015 | the recirculation flap on the egr pipe has seized and refuses to shut | 2 | **2** |
| d016 | soot trap is completely blocked up | — | **—** |
| d017 | the adblue reservoir is nearly empty and low warning is showing | — | **4** |
| d018 | water temp gauge pegged cold, the reading line looks shorted | — | **2** |
| d019 | the water temp sensor lead has come adrift and gauge is dead | — | **1** |
| d020 | the go pedal's two throttle tracks disagree and power is cut | — | **1** |
| d021 | alternator is overcharging and the battery sees far too many volts | 1 | **1** |
| d022 | charge pressure from the turbo is under target | 1 | **1** |
| d023 | turns over but never fires, no signal coming from the cam pickup | 2 | **1** |
| d024 | loss of pulling power with the dash warning light on | 3 | **1** |
| d025 | system voltage keeps sagging and the ecu drops out on cold starts | — | **1** |

7 of 12 symptom queries improved, none got worse.

### Remaining DEV misses, and why

- **d015** *"…seized and refuses to shut"* → P042F-00 (jammed **closed**) at rank 1, the
  correct P042E-00 (jammed **open**) at rank 2. "Refuses to shut" means *stuck open*, but a
  lexicon maps words, not negation. The EGR jammed-open/closed pair is effectively a
  near-duplicate the lexicon cannot resolve.
- **d014** *"flap is seized shut"* reaches rank 3; the exhaust-throttle valve pair
  (P04A5/P04A4) outranks it, since `flap` legitimately aliases both EGR and exhaust-throttle
  valves.
- **d016** *"soot trap is completely blocked up"* — still not in the top 5, though every
  result is a DPF-family code.
- **d017** (AdBlue low) rank 4; **d018** (coolant short to ground) rank 2 behind its own
  open-circuit sibling.

No `dev_driven` entries were added to chase these. With 12 symptom queries, entries
targeted at individual misses would mostly measure overfitting, and TEST would pay for it.

### Soot-trap gate over-block — noted, not fixed (8.3)

d016 *"soot trap is completely blocked up"* was **wrongly refused** by the relevance gate at
baseline and **now passes** under C4 (in-scope 27/28 → 28/28). This is a side effect: BM25
aliases put `soot trap` into the corpus, lifting the query's `bm25_max` over the gate
threshold. The gate logic itself is unchanged; recalibrating it is Phase 8.3.

---

## A pre-existing discrimination failure (not caused by the lexicon)

The **unchanged baseline already fails 3 of 14 guardrails**, all in the injector
short-circuit family, all ranking **P1203-00** first. Under C4, two remain (cylinders 2 and
4). The lexicon did not cause this, but "the injector guardrails pass" would be false, so
it is recorded here.

**Root cause:** the only token separating P1201–P1204 is a single cylinder digit, and
digits are pervasive noise in BM25 text — pin and step numbers. P1203-00's BM25 text
contains the token `2` twice although its description says *cylinder 3*, so BM25 ranks it
first for "cylinder 2"; dense has P1202-00 first, and RRF resolves the tie the wrong way.
A likely fix is a compound token (e.g. `cylinder_2`) at index and query time. It is out of
scope for a vocabulary lexicon and not attempted here.

---

## What has NOT changed

- **Production retrieval is unchanged.** `index/` and `Retriever()` defaults are exactly as
  tagged in `v1-phase7`; C4 is a *selected configuration*, reproducible via
  `--index-dir index_exp/minilm_alias_bm25 --lexicon data/domain_lexicon.json --expand bm25`.
  Adopting it as the default is deferred until the gate work (8.3) and the TEST evaluation
  (8.5) are done.
- **TEST has not been run.**
- **Test suite: 37 passed, 1 xfail, 0 failed** — unchanged, confirming the refactor preserved
  production behaviour.

## Evidence & Artifacts

- `data/domain_lexicon.json` (v2), `src/lexicon.py` — lexicon + audit
- `scripts/bench_8_2.py` — DEV-only benchmark driver (Parts A and C)
- `data/experiments/8_2/` — full results and per-query rows for Parts A and C
- `data/baseline_v2_2_dev.json` — the 8.2 DEV before-picture; `data/baseline_v2_1.json` kept
- `src/build_index.py` — new `--index-dir --model --passage-prefix --aliases --lexicon`
  (defaults reproduce production)
- `src/retrieve.py` — new `query_prefix`, `lexicon`, `expand`; the model is now read from
  the index's `meta.json`, so query and index encoders cannot silently diverge
- `src/evaluate_v2.py` — `--split` (DEV default; TEST opt-in), configurable retriever

## Limitations

- **Selection bias on DEV.** Eight configurations were compared on the same 25 ranked DEV
  queries and the best non-degrading one chosen. The C4 DEV lift is an **upper bound**; the
  8.5 TEST run is the real estimate.
- **Small cells.** 12 symptom queries: one query moves hit@1 by 8.3 points and MRR by up to
  0.083. Differences below ~0.08 MRR are noise.
- **TEST contamination risk.** 19 lexicon entries match TEST wording — see the ablation plan.
- **A lexicon cannot handle negation or implication** ("refuses to shut" = stuck open).
- **The lexicon is hand-curated and English-only**; coverage outside its 42 entries degrades
  to baseline behaviour, which fails safe.
- **Pre-existing injector short-circuit confusion** (P1203-00 hub) remains.
