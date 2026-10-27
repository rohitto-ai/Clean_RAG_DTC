# Phase 11.2 — A-narrow, and a one-shot check on a colleague-written set

_2026-10-27 · branch `phase11-refine` · A-narrow frozen `a45f053`, pre-registered `28ad310`, run once · **nothing adopted**_

## Summary

| | result |
|---|---|
| **A-narrow on DEV / TEST** | identical to production. DEV symptom hit@1 58.3% / MRR 0.7111, groups 3/3, OOS 6/6, in-scope 28/28; TEST MRR 0.6282; guardrails 14/14 |
| **A-narrow on Round-1 (post-hoc)** | false declines **6 → 1**; correct declines **13 → 7**; 6 further rows get advisory + codes |
| **R2 colleague set, symptom (15)** | **identical for both configurations**: hit@1 13.3%, hit@5 40.0%, MRR 0.2467 [95% CI 0.080–0.433], **0 false declines** |
| **R2 colleague set, no_dtc (4)** | production 0/4; A-narrow **1/4** — and that one row is **R16, the row flagged as not independent of A**. Excluding R16 and R18: **0/2** |
| **Recommendation** | **Do not adopt yet.** A-narrow is safe (it has never wrongly declined on an independent row) but this set gives no independent evidence that it helps |

The symptom numbers are the most useful thing here: **MRR 0.2467 on queries written by
colleagues, against 0.2447 on the Round-1 independent set.** Two differently-sourced sets
agree almost exactly, which is the strongest confirmation yet that **~0.24 is this system's
real symptom MRR** on language it has never seen.

## Step 1–2 — A-narrow (`src/no_dtc_narrow.py`), frozen before the run

Phase 11.1 recommended narrowing the broad rule before any adoption, because all six of its
false declines came from three categories and all thirteen of its correct declines from the
other three. A-narrow implements exactly that split:

| action | categories | what the user gets |
|---|---|---|
| **decline** | external leak / fluid loss, fluid level / condition, consumption / wear | no code list, plus an inspection area |
| **advise** | smoke colour, mechanical noise, smell | **the ranked codes ARE shown**, with the inspection area beside them |
| **retrieve** | any electronic evidence (lamp or message, gauge, sensor/signal, fault code, limp/derate, will-not-start) | untouched production behaviour |

It imports the term tables from `src/no_dtc.py` rather than copying them, so the Phase 11.1
freeze over that file stays verifiable — only the decision changed.

**One fix during development, found on a synthetic probe and not on any gold row:** weather
phrases (`damp morning`, `wet road`) are stripped before the mechanical scan, because weather
is not a fluid leak. Without it, a belt squeal on a damp morning was promoted from advisory to
a decline.

**No regression before freezing** (configurations: v3-final-eval production vs A-narrow):

| | DEV symptom hit@1 / MRR | DEV groups | DEV OOS | DEV in-scope | TEST symptom MRR | guardrails |
|---|---|---|---|---|---|---|
| production | 58.3% / 0.7111 | 3/3 | 6/6 | 28/28 | 0.6282 | 14/14 |
| **A-narrow** | **58.3% / 0.7111** | **3/3** | **6/6** | **28/28** | **0.6282** | **14/14** |

**Round-1 independent set, POST-HOC** (spent in Phase 10.6 — development feedback, optimistic):

| rule | no_dtc declined | false declines on 41 symptom rows | symptom MRR |
|---|---|---|---|
| broad A (11.1) | 13/19 | **6** | 0.2203 |
| **A-narrow** | **7/19** | **1** (Q19) | **0.2447** — equal to production |

The narrowing did what it was predicted to do: it removed five of the six false declines, at the
cost of roughly half the correct declines, and six further no_dtc rows now receive *advisory +
codes* instead of a decline. The single remaining false decline, Q19 ("when the tank is getting
low, it hesitates on a sharp turn"), is arguably a defensible decline.

Frozen in `data/experiments/11_2/freeze.json`:

| sha256 | file |
|---|---|
| `0900d87e74e9e936…4767528eb` | `src/no_dtc_narrow.py` |
| `67f5764fa13ba587…b5b4a5d4` | `src/no_dtc.py` (term tables, unchanged) |
| `6142c98932376c56…c00694349` | `scripts/eval_11_2.py` |

## Step 3 — the pre-registered one shot

`data/experiments/11_2/preregistration.json`, committed and pushed as `28ad310` **before** the
run. The harness re-verifies every frozen sha256 and refuses to run on drift, and refuses a
second run outright. Input sha256 `87c3d966…47f5353` matches the brief. The system was given
`q["query"]` and nothing else.

### Provenance (copied verbatim from `data/gold_r2_colleague.json`)

**queries**: 20 symptoms written by colleagues working with the author, each with the writer's
own label. Whether the writers had seen Round-1 material, or used writing tools, was not
recorded; several topics overlap Round 1. No version of the system had been run on these
queries before the pre-registered evaluation.

**labels**: Writer's labels used unchanged (mostly a single DTC per row, so scoring is strict).
Modes: 15 symptom (DTC expected), 4 no_dtc (mechanical, correct behaviour = decline), 1
inconclusive (excluded from scoring). Flags on R16 and R18 in notes.

**scoring**: symptom rows: hit = any expected code, any decline is an error; no_dtc rows:
decline is correct; inconclusive rows: reported, not scored. Report all-rows and a sensitivity
analysis excluding R16 and R18.

### Results — symptom rows (15)

| subset | config | hit@1 | hit@3 | hit@5 | MRR | 95% CI | false declines |
|---|---|---|---|---|---|---|---|
| ALL | production | 13.3% | 33.3% | 40.0% | 0.2467 | 0.080–0.433 | 0 |
| ALL | **A-narrow** | 13.3% | 33.3% | 40.0% | **0.2467** | 0.080–0.433 | **0** |
| excl. R16/R18 | production | 13.3% | 33.3% | 40.0% | 0.2467 | 0.080–0.433 | 0 |
| excl. R16/R18 | **A-narrow** | 13.3% | 33.3% | 40.0% | **0.2467** | 0.080–0.433 | **0** |

Paired bootstrap of symptom MRR, A-narrow minus production: **+0.0000, CI [+0.0000, +0.0000]**.
The two configurations returned *identical* code lists on every symptom row — A-narrow declined
none of them. (R16 and R18 are both no_dtc rows, so excluding them does not change this table.)

**A-narrow's advisory fired on one symptom row, R03** ("sharper tapping from the injector
side"), where it showed the inspection hint *beside* the codes — and the expected code
`P0201-00` was still returned at rank 2. Under the broad rule from Phase 11.1 that row would
have been declined outright. This is the narrowing working exactly as intended.

### Results — no_dtc rows (4)

| id | query (abridged) | production | A-narrow |
|---|---|---|---|
| **R16** | "oil level is **rising** between services, oil **smells strongly of diesel**" | 3 codes | **DECLINED** — inspect the fluid level and for leaks |
| R17 | "temperature rises on long climbs, returns to normal on level roads" | 3 codes | 3 codes (no advisory) |
| R18 | "loud **hissing**, **black smoke**, weak pulling" | 3 codes | 3 codes **+ advisory** (exhaust smoke colour; the air path) |
| R19 | "metallic **knocking** under heavy load, idle and starting normal" | 3 codes | 3 codes **+ advisory** (the noise source under load) |

| subset | production decline rate | A-narrow decline rate |
|---|---|---|
| ALL (n=4) | 0/4 = 0.000 | **1/4 = 0.250** |
| excl. R16/R18 (n=2) | 0/2 = 0.000 | **0/2 = 0.000** |

### The inconclusive row (reported, not scored)

**R20** — "cranks at normal speed but starts only after repeated attempts; fuel supply and
electrical connections appear intact." Both configurations answer it with
`P0336-00, P0A1B-12, P0335-00`; A-narrow shows no advisory, because "cranks… starts" is
electronic evidence (will-not-run) and overrides. The writer marked it inconclusive precisely
because it needs compression and fuel-quality checks before a code can be assigned — so
answering with crank/starter codes is at best premature.

### Word overlap (information only)

15 symptom rows: mean **0.055**, max 0.222, **9 of 15 with zero overlap** — close to Round-1
(mean 0.050, 22/41 zero) and well below DEV (0.090). Nothing was dropped or edited.

## Honest reading

1. **The symptom result is a genuine, independent confirmation.** MRR 0.2467 here against
   0.2447 on Round-1, from a different set of writers, with similarly low manual-word overlap.
   The value of this run is that corroboration, not any configuration comparison.
2. **A-narrow is safe.** Zero false declines on 15 symptom rows here, and one on 41 Round-1
   rows. Over 56 independent symptom rows it has wrongly withheld codes once. That is the
   property that matters most: a wrong decline sends a technician to inspect a belt when a code
   exists.
3. **But this set gives no independent evidence that A-narrow helps.** It declined exactly one
   no_dtc row, **R16 — the row the set's own notes flag as overlapping Round-1 Q46 (oil
   dilution), which informed A's development.** On the two unflagged no_dtc rows it declined
   neither. The sensitivity analysis the brief asked for is the decisive one: **0/2.**
4. **R18 and R19 show the trade-off working as designed, and its limit.** Both are noise/smoke
   complaints that the writer labelled mechanical. A-narrow deliberately does *not* decline
   them — it shows codes plus an inspection hint. That is the right call for R18 (the note
   itself says a charge-air leak often triggers air-mass/boost codes, and production returned
   exactly `P0047-00`/`P0048-00` boost codes), but it means A-narrow is, by construction, unable
   to decline the noise and smoke cases that make up half of this set's mechanical rows.
5. **n is tiny and the brief said so in advance.** 15 symptom rows and 4 no_dtc rows. The
   symptom CI is 0.080–0.433; one row moves MRR by up to 0.067. The no_dtc "rate" of 0.25 is
   one row. Nothing here is significant, and the pre-registration recorded that before the run.
6. **The 15 symptom rows are strict**: mostly a single expected code, so "hit = any expected
   code" is far less lenient than Round-1's median of 3. That the MRR still lands at 0.2467 is
   mildly reassuring about the Round-1 figure not being inflated by generous labels.

## Recommendation on adopting A-narrow

**Do not adopt yet — but it is the right shape, and the blocker is evidence, not design.**

- **For:** it costs nothing measurable (DEV, TEST and guardrails identical to production; zero
  false declines on 15 fresh symptom rows); it is rule-based, explainable and renders its
  reasons straight into the `why` block; and it addresses the single worst finding in the
  project (0/19 declines in Phase 10.6).
- **Against:** on genuinely independent no_dtc rows its demonstrated benefit is **0/2 here** and
  7/19 post-hoc on a spent set. Both of those are weak evidence, and the only clean win on this
  set is the row flagged as non-independent.

**What would settle it:** a set of **20–30 purpose-written "no DTC covers this" queries from
people who have not seen refinement A**, spread deliberately across the six categories, with
the leak/level/consumption rows and the smoke/noise/smell rows labelled separately. That is a
small authoring task and it is the only way to tell whether the decline categories generalise.
Until then A-narrow stays in the tree, off by default.

**Nothing was adopted in this task.** `index/`, the gate, the records and the Retriever defaults
are unchanged: suite **44 passed / 1 xfail / 0 failed**, determinism `--defaults`
**`ffff9bc707d8754d`**.

## Files

| file | role |
|---|---|
| `src/no_dtc_narrow.py` | A-narrow: the decision (term tables imported from `no_dtc.py`) |
| `scripts/eval_11_2.py` | `--stage dev` (regression + post-hoc Round-1), `--stage r2` (one shot) |
| `data/experiments/11_2/freeze.json` | A-narrow frozen before the R2 run |
| `data/experiments/11_2/preregistration.json` | the protocol, pushed before the run |
| `data/experiments/11_2/dev_test_results.json` | DEV, TEST, guardrails, post-hoc Round-1 |
| `data/experiments/11_2/r2_results.json` | the one-shot result, every row, both subsets |
