# Phase 9.1b — garbled troubleshooting steps (table column bleed): detection and fix

_2026-09-17 · branch `phase8-limitations`_

**Result:** a systematic scan finds **3 affected records** containing **34 garbled steps**, all on
pages whose steps table runs past the page footer. After the parser fix, the same detector finds
**0 records and 0 pages**. Only those 3 records changed; the other 311 are byte-identical.
DEV metrics are unchanged. The determinism hash changed because the data changed. The new
production hash is **`ffff9bc707d8754d`**, identical under PYTHONHASHSEED 0 and 1.

> **Data-quality correction; TEST not re-run.** The Phase 8.5 one-shot TEST evaluation predates
> this fix. The fix changes only the 3 records below. Two TEST queries involve them: `t058`
> expects a code whose neighbourhood includes P00C6-00, and `t063` ("which coolant faults
> exist") lists P0117-00. The TEST split is spent and was **not** re-run. The Phase 8.5 TEST
> numbers stand as recorded, against the pre-fix data.

## 1. Root cause

Column boundaries are clustered from vertical ruling edges inside the steps-table band
(`column_bounds`). The band ran from the "Trouble Shooting Steps:" marker down to the next
section marker, or to the page bottom if there was none. On 7 pages this band extended below
the repeated footer (y > 712). The footer box draws its own vertical rules at x≈182 and x≈515.

On pages 12, 137, 140 and 360 those extra rules had too little support to form a cluster, so
the band overrun did no harm. On **pages 13, 86 and 211** they did form clusters, giving 4–5
interior boundaries instead of 2. For example, page 13 got `[100.2, 182.3, 419.7, 515.4]`
instead of `[100.2, 419.7]`. Every Steps-column word right of x=182 was then assigned to
column 2 (Specifications). The step text was cut after its first few words and the rest landed
in `spec`.

## 2. Detector — `scripts/detect_step_bleed.py`

Two independent checks. The exit status is 1 if either flags anything.

**Content (records).** A step's `spec` is flagged when any of these holds:

| rule | meaning |
|---|---|
| S1 | the spec starts with a lower-case word. A real spec is a value or a label ("12.5±3 volts", "Pin 1 to A31", "Air gap – 0.5 to 1.5mm", "Should be less than 6 hPa"), never a sentence continuation. |
| S2 | the spec contains branch language ("go to"), which belongs in the step text |
| S3 | the spec has no digit and contains ≥ 2 sentence function words |
| S4 | the step text ends on a dangling word ("and", "the", "found", "check", …) while a spec is present |

**Geometry (PDF).** A page is flagged when its steps table does not resolve to exactly 2
interior boundaries, or when those boundaries do not fall between the `Sr.` | `Steps` |
`Specifications` header labels.

**Calibration against the pre-fix data.** Every non-numeric spec in the corpus (43) was reviewed
by hand. The detector flags exactly the 34 bled ones. It does not flag the 9 genuine textual
specs: P018F-00 s4, P1203-00 s6/s7, P0335-00 s4, P0336-00 s4, P0500-1F s8, P0500-1C s8,
P0704-29 s6, P244A-00 s9.

## 3. Full affected list (pre-fix)

| record | steps | garbled steps | count |
|---|---|---|---|
| `P0117-00@p13#1` — Coolant temperature sensor signal short circuit to ground | 11 | 1, 2, 3, 4, 5, 6 | 6 |
| `P00C6-00@p86#1` | 14 | 1–14 (all) | 14 |
| `P0A1B-12@p211#1` | 15 | 1–14 | 14 |
| **total** | | | **3 records, 34 steps** |

The Phase 9.1 keyword scan had flagged 26 steps and a false positive (P1203-00 s7, a genuine
spec). It missed P0117-00 s1 ("voltage"), among others.

Collateral damage, also repaired:

| record | goto edges before → after | spec fields before → after |
|---|---|---|
| P0117-00 | 4 → 8 | 6 → 1 (`12.5±3 volts`) |
| P00C6-00 | 0 → 6 | 14 → 0 |
| P0A1B-12 | 2 → 6 | 14 → 2 (`12.5±3 volts`, `86 to A_B2`) |

Corpus-wide goto references went from 701 to **715**. Unresolved goto targets are unchanged
at 37.

## 4. Fix — `src/parse_dtc.py`

Both changes are coordinate-based and extend the existing repair:

1. **Footer clamp.** In `extract_page`, `sy1 = min(sy1, FTR_BAND)`. The steps band can no longer
   reach the footer's ruling. This alone fixes all 3 pages.
2. **Header-anchored guard.** `header_labels(page, y0)` locates the x0 of the `Sr.`, `Steps`
   and `Specification(s)` labels. If `column_bounds` then finds a number of interior boundaries
   other than 2, it keeps one boundary per label gap, choosing the cluster with the most edge
   support. This is defence in depth against any other stray rule. It is not triggered on the
   current corpus once the clamp is in place. If a gap has no candidate, the boundaries are left
   unchanged rather than guessed.

The fix was verified on the full re-parse of pages 8–545. Record keys are unchanged (314). Only
3 records differ, in `steps` and `specifications`. P0117-00 also differs in `pin_map` confidence:
A28 is now read from the repaired step 6.

## 5. P0117-00 before / after (`render_record`)

Before:

```
Troubleshooting steps:
  Step 1: Check the battery   [spec: voltage]
  Step 2: Check connector properly to the wire   [spec: of coolant temperature sensor is connected harness connector]
  Step 3: If connector found Step 11   [spec: lose in step 2 then fix is properly & go to]
  Step 4: Check the wire connector, if yes   [spec: harness for any pin / wire back-out from go to step 5]
  Step 5: Fix the back-out Step 11   [spec: cables in proper positions in connector & go to]
  Step 6: If error still present, & A51, & continuity   [spec: check the continuity between sensor pin1 between sensor pin2 & A28. Go to Step 7]
  Step 7: If continuity is unavailable from Step 6 then check the signal line short to ground & go to Step 11
  ...
Pins referenced: A51
```

After:

```
Troubleshooting steps:
  Step 1: Check the battery voltage   [spec: 12.5±3 volts]
  Step 2: Check connector of coolant temperature sensor is connected properly to the wire harness connector
  Step 3: If connector found lose in step 2 then fix is properly & go to Step 11
          -> if yes -> Step 11
  Step 4: Check the wire harness for any pin / wire back-out from connector, if yes go to step 5
          -> if yes -> Step 5
  Step 5: Fix the back-out cables in proper positions in connector & go to Step 11
          -> then go to Step 11
  Step 6: If error still present, check the continuity between sensor pin1 & A51, & continuity between sensor pin2 & A28. Go to Step 7
          -> if yes -> Step 7
  Step 7: If continuity is unavailable from Step 6 then check the signal line short to ground & go to Step 11
  ...
Pins referenced: A28, A51
```

Steps 7–11 were unaffected in both versions. Before the fix, steps 3–6 had lost their branch
edges. The manual's wording, including "fix is properly", is kept verbatim.

P00C6-00 and P0A1B-12 now read cleanly as well: every step is a complete sentence. Their only
specs are real values (P0A1B-12: `12.5±3 volts`, `86 to A_B2`).

## 6. Regeneration and validation

`parse_dtc.py` → `enrich_images.py` → `schema.py` → `validate.py` →
`build_index.py --rebuild --aliases bm25 --cylinder-token`

| check | result |
|---|---|
| boilerplate leakage | 0 records |
| JSON-schema conformance | 314/314, failing 0 |
| goto integrity | 715 refs; unresolved 37 (unchanged, all marked low-confidence) |
| garbled-step detector, content | **0 records, 0 steps** |
| garbled-step detector, geometry | **0 pages** |

## 7. Regression runs

| run | before 9.1b | after |
|---|---|---|
| smoke suite | 44 / 1 xfail / 0 | **44 / 1 / 0** |
| advise tests | 10/10 | **13/13** (3 new tests: same-system preference, cross-system fallback, P0117-00 bleed regression) |
| guardrails | 14/14 | **14/14** |
| determinism `--defaults` | `76b16c2b9ab8f9f2` | **`ffff9bc707d8754d`** (seed 0 and seed 1 identical) |

**Why the hash changed.** Dense text excludes steps, but the BM25 text includes step
*condition* clauses, and those changed for the 3 records. The proof output differs from 8.5 in
exactly two DEV rows, both below rank 2:

- `d007` (near-duplicate): rank 5 changed from P0335-00 to P0192-00.
- `d009` (near-duplicate): ranks 3–5 changed from [P0087-00, P0003-00, P0194-00] to
  [P0194-00, P0087-00, P0003-00].

Gold stays at rank 1 in both.

**DEV eval (gold v2.2, 34 queries).** Every metric is identical:

| mode | hit@1 | MRR |
|---|---|---|
| exact code | 100.0% | 1.000 |
| near-duplicate | 100.0% | 1.000 |
| symptom | 58.3% | 0.711 |
| overall | 80.0% | 0.861 |

System group 3/3, gate out-of-scope 6/6, in-scope 28/28. `d018` still ranks P0117-00 2nd.
Outputs are in `data/experiments/9_1b/`.

## 8. Advise: same-system preference for related codes (optional item)

`advise.related_records` now orders candidates by (different system from the anchor, −cosine,
id). Same-system records fill the related slots first, then cross-system records by
similarity. This is a ranking preference, not a filter.

| input | before | after |
|---|---|---|
| P0192-00 (rail_pressure) | P0193-00, P0180-11 (fuel_supply) | **P0193-00, P0194-00** |
| P00C6-00 (rail_pressure) | P0089-92, P0089-00 (fuel_supply) | **P0088-00, P0087-00** (rail_pressure) |
| P0500-1F (vehicle_speed, 2 records) | not measured | P0500-1C, then P0120-12 (cross-system fallback) |

Retrieval, the gate and the indexes are unaffected, so the suite, guardrails and determinism
results above do not depend on this change.
