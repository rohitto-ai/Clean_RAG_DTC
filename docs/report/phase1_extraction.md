# Phase 1 — Extraction & Structuring

## Objective

Turn 545 pages of the TATA Motors 3.3L DTC manual into **one self-contained record
per DTC**, preserving each DTC's troubleshooting steps as an intact branching
decision tree. Fixed-size chunking is explicitly rejected: steps cross-reference
each other ("if lose, go to Step 13"), so splitting a DTC breaks the repair logic.

## Method

`src/parse_dtc.py` streams the PDF one page at a time (caches flushed per page),
splits the body at each `Pxxxx-xx:` header, stitches blocks across page breaks, and
parses the fixed 7-section template into typed fields.

The critical routine is **coordinate-based table repair**. The Sr.No / Steps /
Specifications table is rebuilt from `pdfplumber` word coordinates, never from flat
text: column boundaries come from the vertical rules spanning the table band, and a
row begins **only** when a word lands in the Sr.No x-band.

`src/validate.py` is a separate harness that reports coverage, template deviations,
step-tree integrity and a branching-phrase catalogue. It reports; it never fixes.

## Key Decisions

| Decision | Rationale |
|---|---|
| Row starts are decided **geometrically**, not lexically | A naive split on "Step N" over the flat text of P0192-00 yields **22 rows against a truth of 13**. Inline references ("go to Step 13") sit at x≥105 inside the Steps column; genuine row labels sit at x≈52 in the Sr.No column. The phantom "Step 9"/"Step 11" rows would *overwrite real steps* in any dict-keyed parser. |
| Column boundaries are clustered with a **wide tolerance + support threshold** | The manual draws tables as one filled rectangle *per cell*, so each logical boundary appears as a cluster of 3–4 nearby edges. Tight clustering invented 9 phantom columns instead of 3. |
| Boilerplate is stripped at **line level, never word level** | The footer rule `^\d+$` (for the orphaned "545" of a wrapped "Page N of 545") also deletes the bare numeral in "Step **1**", silently destroying every row label. Narrowed to the literal page-count token. |
| Section context is **sticky across page breaks** | A "Location & Component Image:" heading at the foot of one page routinely owns the images at the top of the next. |
| `goto[]` is left **verbatim**; defects are reported, not silently repaired | Rewriting source data at parse time hides it. Resolution belongs in Phase 6 with a Phase 7 check. |
| Retrieval key is **code + suffix + page/occurrence** | The DTC code is not unique. |

## Results & Metrics

**314 records from pages 8–545 in 68 s, 72 MB peak RSS.**

### Coverage vs the Table of Contents (pp. 1–7)

| | |
|---|---|
| TOC entries | 304 (301 distinct codes) |
| Records parsed | 314 (311 distinct codes) |
| **TOC entries with no record** | **0** |
| Records not in the TOC | 10 |

The 10 non-TOC records are genuine DTCs the TOC omits — a contiguous run at
pp. 457–466 (SCR relay faults, exhaust-gas temp sensors T4/T5/T6, frozen DEF),
verified against the source; their codes appear nowhere in the TOC text.

**Duplicate codes confirmed** — the code alone is not a unique key:

| code_full | pages | occurrences |
|---|---|---|
| `P0180-11` | 100, 195 | 1, 2 |
| `P0180-12` | 102, 197 | 1, 2 |
| `P061C-00` | 217, 472 | 1, 2 |

### Template variants — the manual is not one template

| Variant | Records |
|---|---|
| `full_7_section` | 113 |
| `reduced_4_section` (header + overview + checkpoints + steps only) | 173 |
| `partial` | 28 |

Verified on pp. 369, 46 and 510: the reduced form is **real document structure, not
extraction failure**. The 56-record P16xx FCCU alarm family is uniformly reduced,
4 steps, single page. P0401-00/P0402-00 are likewise reduced.

### Structural integrity

| Check | Result |
|---|---|
| Total steps | 2202 |
| Total `goto` references | 701 |
| Records with zero steps | **0** |
| Boilerplate leaks | **0** |
| `system='other'` (untagged) | **0** (was 61) |
| Non-contiguous step numbering | 7 records |
| Unresolved `goto` targets | 37 refs / 20 records |
| Self-referencing `goto` | 4 |

### Branching-phrase catalogue (instrumentation for Phase 6 polarity)

**32 distinct signatures** over **1205 / 2202 steps (54.7%)** containing branching
language. `X` = free text, `GOTO` = a "go to Step N" reference.

| # | Signature | Count | Example |
|---|---|---|---|
| 1 | `IF X` | 419 | If the error is present check the connector pins from both side… |
| 2 | `IF X GOTO` | 256 | If error still present go to Step 7 |
| 3 | `X GOTO` | 134 | Fix the back-out cables in proper positions in connector & go to Step 13 |
| 4 | `IF X THEN X GOTO` | 101 | If connector found lose in step 2 then fix is properly & go to Step 13 |
| 5 | `X IF_YES GOTO` | 63 | …if yes go to Step 8 |
| 6 | `IF X THEN X` | 36 | If Step 4 & Step 5 fails then check signal (A97) short circuit to ground |
| 7 | `X IF X GOTO` | 32 | Check if Pin 2(A39) is shorted to supply(A34) or open circuit, go to step 9 |
| 8 | `X IF X` | 24 | Check connector if rail pressure sensor is connected properly… |

**Key finding for polarity modelling:** the head of the distribution is `IF X` with
**zero** goto targets (419 steps) — a condition whose "else" is an implicit
fall-through to the next step. Only **two** signatures carry an explicit two-way
branch (`IF X THEN GOTO ELSE GOTO`, 2 occurrences; `IF X THEN GOTO X ELSE GOTO`, 3).
An explicit `else` is rare, so polarity must mostly be inferred from the condition
plus fall-through rather than read off an `else` clause.

## Evidence & Artifacts

- [src/parse_dtc.py](../../src/parse_dtc.py), [src/validate.py](../../src/validate.py)
- [data/dtc_raw.jsonl](../../data/dtc_raw.jsonl) — 314 records
- [data/validation_report.md](../../data/validation_report.md) — full generated report
- [data/branch_patterns.json](../../data/branch_patterns.json) — all 32 signatures

## Issues Found & Fixed

Validating at scale found five real parser bugs:

1. **U-codes were invisible.** The header regex matched only `P[0-9A-F]{4}`, so the
   three CAN DTCs (`U0102-00`, `U011A-00`, `U011A-89`) were folded into the
   preceding P-record (`P060A-49` came out with steps `[1,2,1,2,3,1,2,3,1,2,3]`).
   Coverage reported "0 missing" only because the **TOC regex shared the identical
   blind spot** — both sides were checking the same wrong thing.
2. **Wrapped Sr.No cells** — the original decoupling hazard, and it is real. A
   two-digit "Step 10" does not fit the narrow Sr.No column, so it renders as
   `"Step"` on one line and `"10"` on the next, sharing that line with the second
   line of the row's text. On p.137, steps 10–13 were invisible and their text was
   swallowed by step 9. Rows are now stitched before assembly (**+28 steps**).
3. **Thin continuation bands** — a steps table continuing onto a new page can have a
   single row, drawing only ~2 edges per boundary; `min_support=3` rejected it, and
   a band start of y=60 pulled the page header's own rules into the clustering.
4. **Multi-target gotos** — "go to Step 9 **& 11**" branches to both; only the first
   was captured.
5. **Word-level boilerplate stripping** destroyed row labels (see Key Decisions).

Subsystem map extended to 19 ordered categories, most-specific-first, so
"plausibility check of the exhaust-gas temperature sensor" tags as exhaust rather
than monitoring.

## Limitations

**The remaining anomalies are source-document defects, not parse errors** — verified
directly against pp. 20, 22, 83, 248 and 390:

- p.20 and p.390 literally print **"Step 9" twice** (the second should be 10);
  p.390's step 9 reads "…change the ECU/EVGT & go to step 9", which is where the
  self-referencing gotos come from.
- p.83 jumps 7 → 9; p.248 jumps 4 → 6.
- **All 20/20** records with unresolved gotos point *past* their last step, and in
  **20/20** the final step is a terminal "Check DTC" / "Clear and check DTC".

**Open decision for Phase 6:** resolve an out-of-range `goto` to the terminal step
and log the repair in the Phase 7 harness. `goto[]` is currently left verbatim.

Branch **polarity is deliberately not modelled yet** — the catalogue above is the
evidence base for designing it from the corpus rather than from one example.
