# Phase 11.1 — Two refinements, measured honestly

_2026-10-27 · branch `phase11-refine` (from tag `v3-final-eval`) · **nothing adopted into production**_

## Summary

| | improvement A — no-DTC-match | improvement B — subsystem prior |
|---|---|---|
| what it does | declines queries that are mechanical evidence with no electronic evidence | softly boosts records whose subsystem the query's words point at |
| DEV (gold v2.2) | **no change** (symptom MRR 0.7111) | symptom MRR **0.7111 → 0.7833** |
| TEST (spent, post-hoc) | no change (0.6282) | **no change** (0.6282) |
| guardrails | 14/14 | 14/14 |
| independent, **post-hoc** | no_dtc decline **0/19 → 13/19**, at the cost of **6 false declines** on 41 symptom rows; symptom MRR 0.2447 → 0.2203 | **no effect at all** (0.2447 → 0.2447) |
| recommendation | **adopt, but only after narrowing it** (see below) | **do not adopt on this evidence** |

Two findings matter more than the numbers:

1. **A fixes most of the Phase 10.6 safety hole**: 13 of the 19 "no DTC covers this" queries are
   now declined instead of being answered with a confident code list. It costs 6 false declines
   out of 41 symptom rows, and all six fall in three identifiable categories.
2. **B's DEV gain does not transfer at all.** +0.072 MRR on DEV, exactly 0.000 on the
   independent set. The diagnostic below explains why, and it is a caution about every
   DEV-measured gain in this project.

> **Every independent-set number on this page is POST-HOC and optimistic.** The set was spent
> once, under pre-registration, in Phase 10.6. These refinements were written *after* reading
> its error analysis. The numbers are development feedback, not an independent measurement.
> `data/gold_independent.json` is unchanged and is marked SPENT in `RESUME.md`.

## A. Preservation

The evaluated system is preserved as the annotated tag **`v3-final-eval`** (pushed), with the
message *"System evaluated in Phase 10.6 — all reported numbers come from this tag"*. Branch
`phase11-refine` starts there. Production — `index/`, the gate, the records and the Retriever
defaults — is untouched by everything below: suite **44 passed / 1 xfail / 0 failed**,
determinism `--defaults` **`ffff9bc707d8754d`**, `src/test_api.py` **61/61**.

## B. Improvement A — "no matching fault code in this manual"

`src/no_dtc.py`. **The rule, in one line: mechanical evidence with no electronic evidence is
not a fault code.**

| MECHANICAL — what a human sees, smells, hears or measures | ELECTRONIC — what the ECU can see |
|---|---|
| external leak / fluid loss (leak, seep, weep, drip, wet, damp, oily film, puddle) | warning lamp or message (warning, lamp, check engine, MIL, telltale, message, alert) |
| smell (smell, odour, fumes, burning smell) | gauge or reading (gauge, reading, needle, display, reads high/low) |
| smoke colour (white / blue / black / pale smoke, smoky) | named sensor or signal (sensor, signal, circuit, voltage, wiring, harness, connector, relay, fuse, ECU, CAN bus) |
| mechanical noise (squeal, rattle, knock, flutter, whistle, whine, grind, clunk, tapping, vibration) | fault code (a P/U/B/C code, "fault code", DTC) |
| fluid level / condition (level dropping, dipstick, topping up, oil smells of diesel, milky) | limp / derate (limp, derate, torque reduction, creep mode, inducement) |
| consumption / wear (using more diesel, worn, frayed, cracked, loose, corroded) | will not run / start (won't start, stalls, cuts out, dies, cranks but…) |

Output is never a code list:

> **No matching fault code in the 3.3L DTC manual — this looks mechanical; inspect: the belt,
> tensioner and pulleys.**
> If a warning lamp or a fault code is present, enter the code and ask again.

Every verdict carries its `reasons`, naming the category and the exact phrase that fired, so it
renders straight into the existing `why` block.

**How the term lists were written.** From general workshop complaint categories — the kinds of
thing an owner brings in that no ECU has a sensor for — not from the wording of any gold row.
**Honest caveat:** I had already read the independent set while writing the Phase 10.6 error
analysis. Nothing was copied from it, but that exposure cannot be undone, which is exactly why
the independent numbers here are labelled post-hoc.

**Two terms were weakened during development**, both for principled reasons and both found on
*development* data:

- A bare deposit word (`residue`, `crust`) no longer declines on its own. It describes both a
  leak trace at a joint and **combustion residue inside a DPF — which is a coded fault**. Found
  on TEST row `t054` ("burnt residue has packed the exhaust soot trap solid").
- A reported **`warning`** of any kind now counts as electronic evidence even without the word
  "lamp", because the ECU raised it. Found on DEV row `d017` ("low warning is showing").

Both fixes removed the only DEV/TEST false declines; after them, A changes DEV and TEST not at all.

## C. Improvement B — soft subsystem prior

`retrieve.detect_systems(query, lexicon)` returns **every** subsystem the query's own words
point at, using the existing keyword map plus the lexicon's manual terms (so "adblue" reaches
`scr_def`). `Retriever(subsystem_prior=w)` then adds `w / (RRF_K + 1)` to the fused score of
matching records — at most one RRF rank-1 vote.

It is a **soft boost inside fusion, never a filter**: a strongly-ranked record from another
subsystem still wins, which is what keeps the near-duplicate guardrails at 14/14. The prior,
its evidence and the number of records boosted are recorded in the retrieval trace.
**Default `0.0` (off), so production is byte-identical.**

**Weight chosen on DEV** — the effect saturates at 0.5, and the smallest weight reaching the
plateau was taken:

| weight | DEV symptom hit@1 | DEV symptom MRR | guardrails | gate |
|---|---|---|---|---|
| 0.00 | 58.3% | 0.7111 | 14/14 | 6/6 · 28/28 |
| 0.25 | 58.3% | 0.7278 | 14/14 | 6/6 · 28/28 |
| **0.50** | **66.7%** | **0.7833** | **14/14** | **6/6 · 28/28** |
| 1.00 | 66.7% | 0.7833 | 14/14 | 6/6 · 28/28 |
| 2.00 | 66.7% | 0.7833 | 14/14 | 6/6 · 28/28 |

## D. Freeze

`data/experiments/11_1/freeze.json`, written and committed (`1502e42`) **before anything was
measured on the independent set**:

| sha256 | file |
|---|---|
| `67f5764fa13ba587…b5b4a5d4` | `src/no_dtc.py` |
| `b2a31aef47a297ec…93a480c3` | `src/retrieve.py` |
| `d550073b3525725d…1aa92f1506` | `scripts/refine_eval_11_1.py` |

Re-running the freeze script verifies rather than overwrites: all three match.

## E. Results

### No-regression gate — DEV and the spent TEST

| config | DEV symptom hit@1 / MRR | DEV groups | DEV OOS | DEV in-scope | TEST symptom MRR | guardrails |
|---|---|---|---|---|---|---|
| base | 58.3% / 0.7111 | 3/3 | 6/6 | **28/28** | 0.6282 | 14/14 |
| A | 58.3% / 0.7111 | 3/3 | 6/6 | **28/28** | 0.6282 | 14/14 |
| B | 66.7% / **0.7833** | 3/3 | 6/6 | **28/28** | 0.6282 | 14/14 |
| AB | 66.7% / **0.7833** | 3/3 | 6/6 | **28/28** | 0.6282 | 14/14 |

No regression anywhere, and **zero false declines on DEV or TEST**. Note that B's DEV gain of
+0.072 produces **no change at all on TEST** — the first sign that it does not generalise.

### Independent set — POST-HOC, optimistic

| config | symptom hit@1 | hit@3 | hit@5 | symptom MRR | no_dtc declined | false declines (of 41 symptom rows) |
|---|---|---|---|---|---|---|
| base | 14.6% | 29.3% | 41.5% | 0.2447 | **0/19** | 0 |
| **A** | 12.2% | 26.8% | 39.0% | 0.2203 | **13/19 (68.4%)** | **6 (14.6%)** |
| B | 14.6% | 29.3% | 41.5% | **0.2447** | 0/19 | 0 |
| AB | 12.2% | 26.8% | 39.0% | 0.2203 | 13/19 | 6 |

**One row differs from the Phase 10.6 figure and it is a measurement definition, not a code
change.** Phase 10.6 reported production symptom MRR 0.2407; this harness gives 0.2447 for the
same configuration. The single differing row is **Q52**, which takes the *subsystem-group*
route (its "every shift" wording triggers grouping intent). Phase 10.6 truncated every route to
5 codes, so the expected code at position 6 was missed; this harness renders the whole group,
as the user would actually see, so Q52 scores 1/6. That change was made before the freeze, to
fix a separate artifact where group rows scored 0/3. **The published Phase 10.6 number stands;
all four configurations here share one harness, so the comparisons on this page are internally
consistent.**

## Error analysis

### A — the 6 false declines, and what they have in common

| id | conf | query (abridged) | expected | A said inspect |
|---|---|---|---|---|
| Q03 | med | "sharper **tapping** from the injector side… slight **vibration**" | P0201/2/3-00 | the valve train |
| Q07 | med | "engine feels uneven and the exhaust **smells** stronger" | P042E-00, P0402-00 | the area the smell comes from |
| Q16 | low | "pale **smoke** puff and runs unevenly for half a minute" | P0116/7/8-00 | exhaust smoke colour |
| Q19 | low | "when the **tank is getting low**, it hesitates on a ramp" | P0087-00 | the fluid level and for leaks |
| Q23 | low | "slight **shake** and a **lumpy sound** when cold" | P0116/7/8-00 | mountings, balance |
| Q26 | med | "more dark **smoke** than usual when pulling away hard" | P0101-00, P0401-00 | exhaust smoke colour |

All six come from exactly **three of the six mechanical categories: smoke colour, mechanical
noise, and smell** (plus one fluid-level case). The assumption behind the rule fails for these:
**smoke, noise and smell are as often the *consequence* of a coded fault as they are a purely
mechanical complaint.** Dark smoke is what an air-mass or EGR fault looks like from the
driver's seat.

By contrast the rule is reliable for the categories it was really designed for — **external
leaks, deposits, fluid loss, consumption and wear**: all 13 correct declines are of that kind
(coolant smell at a joint, oil wetness, belt squeal, diesel smell, oil dilution, consumption
change).

### A — the 6 no_dtc rows it still answers

Q22, Q36, Q41, Q43, Q45, Q60. Every one contains genuine **electronic evidence**, so A
correctly abstains: an oil-pressure *light* (Q45), a coolant-level *warning* (Q60), the
temperature *gauge* (Q41, Q43), idle/rev behaviour (Q22, Q36). These are the genuinely hard
cases — an ECU-raised indication for a condition this manual has no code for. A rule over query
words cannot settle them; it would need the manual's coverage model.

### B — why the DEV gain did not transfer

| set | prior fires on | of those, predicts a correct subsystem |
|---|---|---|
| DEV symptom | **11/12 (92%)** | **11/11 (100%)** |
| independent symptom | **17/41 (41%)** | **12/17 (71%)** |

On DEV the prior almost always applies and is never wrong, so it is pure gain. On the
independent set **59% of queries name no subsystem at all** — they describe behaviour ("it
feels flat on a climb"), not components — and when the prior does fire it is wrong 29% of the
time. The gains and losses cancel exactly, to 0.0000 MRR change.

This is the clearest illustration in the project of why DEV numbers overstate: DEV symptom
queries were written around manual vocabulary, so a vocabulary-keyed mechanism looks excellent
on them and does nothing on real phrasing.

## Recommendation

**Improvement A: adopt, but narrow it first — do not adopt as it stands.**

The safety gain is large and is exactly the Phase 10.6 hole: 0/19 → 13/19 declines on queries
no DTC covers. The cost is 6/41 symptom rows wrongly declined, and a wrong decline is a real
harm — the technician is told to go and look at a belt when a code exists. Proposed narrowing,
to be measured on a *fresh* set rather than this one:

1. Restrict the decline to the categories it is reliable for — **leak / fluid loss, deposits,
   consumption / wear** — and treat **smoke colour, mechanical noise and smell** as *advisory
   only*: still show the inspection area, but alongside the ranked codes rather than instead of
   them. On this evidence that removes 5 of the 6 false declines while keeping most correct
   declines.
2. Keep the "if a warning lamp or a code is present, enter the code" line, which already
   recovers the ambiguous cases.

**Improvement B: do not adopt on this evidence.** It is free (no regression anywhere, guardrails
intact, off by default) and it looks good on DEV, but it does precisely nothing on independent
queries. Adopting it would add a moving part and a tuned constant for a gain that exists only on
the set it was tuned on. It stays in the code, off by default, as a documented option.

**Nothing was adopted in this phase.** `index/`, the gate, the records and the Retriever
defaults are unchanged.

## Limitations

1. **The independent numbers are post-hoc.** The set was spent in Phase 10.6; these refinements
   were written after reading its failures. Treat them as development feedback. A genuine
   measurement of A needs a fresh set of "no DTC covers this" queries.
2. **n is small.** 41 symptom rows and 19 no_dtc rows; 6 false declines is ±1–2 rows of noise.
3. **A is a word-level rule.** It cannot know what the manual covers; it only distinguishes the
   *kind of evidence* a query offers. The 6 rows it still answers show the limit.
4. **B's weight was chosen on DEV**, which is exactly the set on which it works; that the
   plateau starts at 0.5 says nothing about any other set.
5. **The Q52 harness difference** means this page's base figures are not byte-identical to
   Phase 10.6's. The difference is one row and is explained above.
6. **Ground truth on the independent set is AI-drafted, not technician-verified** (Phase 10.6),
   so "false decline" means "disagrees with an AI-drafted label" — Q19 (`P0087-00` for a
   low-tank hesitation) is arguably a defensible decline.

## Files

| file | role |
|---|---|
| `src/no_dtc.py` | improvement A: categories, rule, reasons, message (new) |
| `src/retrieve.py` | improvement B: `detect_systems()` + `subsystem_prior` (default off) |
| `scripts/refine_eval_11_1.py` | the two-stage harness (`--stage dev` / `--stage independent`) |
| `scripts/freeze_11_1.py` → `data/experiments/11_1/freeze.json` | the pre-measurement freeze |
| `data/experiments/11_1/dev_test_results.json` | DEV + TEST + guardrails, all four configs |
| `data/experiments/11_1/independent_post_hoc.json` | the post-hoc run, every row |
