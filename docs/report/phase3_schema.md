# Phase 3 — Canonical Record Schema

## Objective

Normalise `data/dtc_enriched.jsonl` into one typed, validated record per DTC
(`data/dtc_records.jsonl`, all 314), and make each troubleshooting step's control
flow explicit enough for the Phase 6 diagnosis state machine to walk — **without
inventing routes the manual does not state**.

## Method

`src/schema.py` maps every enriched record onto a fixed field set and derives a
typed `steps[]` from the verbatim step text. It also emits the JSON Schema
(`data/dtc_record.schema.json`) that `src/validate.py` enforces.

Route derivation scans jump phrases **positionally**, so a two-way branch can be
split on which side of the `else` each target falls. This matters: for
`"If continuity is OK in Step 9 then go to Step 12 else go to Step 11"` the parsed
`goto[]` is the sorted `[11, 12]`, but the correct routing is `on_true=12`,
`on_false=11`. Reading polarity off the sorted list would invert the branch.

## Key Decisions

**The governing decision: model polarity conservatively; never fabricate a route.**

| Decision | Rationale |
|---|---|
| `null` on `on_true`/`on_false` means **fall through to n+1** | That is the document's own default, not a guess. A null is an honest "not stated", never a silent invention. |
| Single-target jump → `on_true=target`, `on_false=null`, **high** | The manual states where the taken branch goes; the untaken branch is left implicit, so it falls through. |
| Explicit two-way (`THEN GOTO a ELSE GOTO b`) → `on_true=a`, `on_false=b`, **high** | Both routes are stated. Split positionally on the `else`, not by sorting. |
| `IF X` with no jump → condition captured, both routes `null`, **low** | 419 steps take this shape. The "else" is an implicit fall-through; marking it low flags that the polarity was inferred, not read. |
| Multi-target jump (`go to Step 9 & 11`) → both routes `null`, **low** | "Go to 9 **and** 11" means *do both*; that is not a two-way route. Picking one would be fabrication. 6 steps. |
| Out-of-range target → kept **verbatim** in `on_true`, marked **low** | Recording what the manual says is faithful; clamping it to the terminal step here would be fabrication. Phase 6 clamps, Phase 7 logs it. 37 steps. |
| `goto[]` copied **byte-identically** from Phase 1 | The raw edge list stays the auditable ground truth. Phase 3 adds an interpretation layer beside it, never over it. |
| Steps with neither condition nor jump are trivially **high** | There is no route to get wrong. Reported separately so it does not inflate the meaningful number. |

`kind` is assigned by priority: `terminal` (a final "Check DTC") → `branch` (carries a
`goto`) → `check` (states a condition or opens with a checking verb) → `action`.

## Results & Metrics

**314/314 records written and schema-valid. `goto[]` verified byte-identical to the
Phase 1 parse — no edges altered.** Peak RSS 17 MB.

### Step `kind`

| kind | steps | % |
|---|---|---|
| `check` | 1068 | 48.5% |
| `branch` | 692 | 31.4% |
| `terminal` | 298 | 13.5% |
| `action` | 144 | 6.5% |
| **total** | **2202** | |

### `polarity_confidence`

| scope | high | low | total |
|---|---|---|---|
| all steps | 1648 | 554 | 2202 |
| **steps with a condition or a goto** | **649** | **554** | **1203** |

The second row is the meaningful measure — a step with no condition and no jump is
trivially "high" because it has no route to get wrong. Among steps that actually
carry branching language, **54% have a confidently-derived route and 46% do not**,
which is a direct consequence of the Phase 1 finding that the manual's dominant
branch shape is `IF X` with no stated target.

### Routing

| | |
|---|---|
| Steps with `on_true` set | **686** |
| Steps with `on_false` set (explicit two-way) | **5** |
| Steps with both | 2 |
| Steps carrying a `goto` edge | 692 |
| Steps with a `goto` but **deliberately no** route | 6 |
| Steps with a verbatim `condition` captured | 1047 |
| `on_true` pointing outside the step list | 37 (all `low`) |

Only **5 steps in the entire 545-page manual state an explicit `else`.** Everything
else is single-target-plus-fall-through. That is the headline constraint for Phase 6:
the state machine will be walking implicit fall-throughs far more often than stated
two-way branches.

### Carried-through fields

- `template_variant` on **314/314** — 113 full_7_section, 173 reduced_4_section, 28 partial
- `pin_map` — 427 entries, **all** carrying a valid `confidence` (383 high, 44 low)
- `pin_map.net` — 0 populated, by design (Phase 2 skipped OCR)

## Evidence & Artifacts

- [src/schema.py](../../src/schema.py) — derivation + JSON Schema
- [data/dtc_records.jsonl](../../data/dtc_records.jsonl) — 314 canonical records
- [data/dtc_record.schema.json](../../data/dtc_record.schema.json)
- [data/validation_report.md](../../data/validation_report.md) §5

Worked example — `P0192-00` step 10, the one explicit two-way branch in that DTC:

```json
{"n": 10,
 "text": "If continuity is OK in Step 9 then go to Step 12 else go to Step 11",
 "kind": "branch",
 "condition": "If continuity is OK in Step 9",
 "on_true": 12, "on_false": 11,
 "goto": [11, 12],
 "polarity_confidence": "high"}
```

And `P0627-11` step 8, where the schema correctly declines to guess:

```json
{"n": 8,
 "text": "If continuity in Step 7 is unavailable then go to Step 9 & 11 else go to Step 9",
 "kind": "branch", "on_true": null, "on_false": 9,
 "goto": [9, 11], "polarity_confidence": "low"}
```

The true side names two simultaneous targets, so it stays `null` rather than
arbitrarily picking 9 or 11.

## Issues Found & Fixed

1. **Sorted `goto[]` inverts polarity.** `goto` is a sorted set, so the two-way case
   would have yielded `on_true=11, on_false=12` — backwards. Fixed by scanning jump
   phrases positionally and splitting on the `else` offset.
2. **Validator proven to fail loudly**, not pass vacuously. Negative-tested with
   seven deliberate mutations — bad `kind` enum, missing required field, `goto`
   containing a string, bad `pin_map.confidence`, malformed `code_full`, an extra
   undeclared property, and a string `on_true`. All seven were caught.
3. `jsonschema==4.23.0` added to `requirements.txt`.

## Limitations

- **`condition` is verbatim, so it is sometimes a whole sentence rather than a tight
  predicate.** For `"Check connector if rail pressure sensor is connected properly…"`
  the captured clause is grammatical filler, not a real branch condition. These are
  all marked `low`, so Phase 6 can ignore low-confidence conditions. Tightening the
  clause boundary would mean paraphrasing, which the verbatim requirement forbids.
- **46% of branching steps have no derived route.** This is a property of the source,
  not a parser shortfall — the manual usually states only the taken branch.
- **Out-of-range `on_true` values are live in the data** (37 of them). Any consumer
  that follows `on_true` without checking membership will dereference a non-existent
  step. Phase 6 must clamp; the schema deliberately does not.
- `kind` classification is heuristic (verb-based for `check` vs `action`). It is a
  retrieval/UX convenience, not load-bearing for the state machine, which keys off
  `on_true`/`on_false`/`goto`.
