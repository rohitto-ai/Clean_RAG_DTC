# Phase 13.3 — partial / malformed code handling

_Branch `phase10-demo`, after `b3eef93`. Retrieval scoring, the relevance gate, the indexes and
the records are **unchanged**._

## Objective

Phase 9.3 found that a code with a digit missing is not a code the router can resolve, so it fell
through to **hybrid symptom retrieval** and came back with a ranked list of unrelated DTCs. Phase
9.3b closed half of that hole: a 4-digit body that maps to nothing (`P0199-00`) is now refused
explicitly with a did-you-mean line, and `P019-00` — a dropped digit *with* a sub-code — is refused
the same way, because `DTC_CODE_RE` accepts a 3-digit body and the suffix makes it look well-formed.

The other half stayed open. A 1–3 digit attempt with **no** sub-code — `P10`, `P-10`, `P019`,
`p 019` — matches no complete code, so nothing in the router claimed it and it reached symptom
search. Measured at `b3eef93`: **240 of 240** such forms were answered with a ranked list of fault
codes (see §3). A half-typed code is not a symptom, and answering it with a symptom search is a
confident answer to a question nobody asked.

## Method

`src/partial_code.py` is pure text; it is consulted by the router **before** the code branch,
because `DTC_CODE_RE` matches `P019` as a base and would otherwise take it.

**Detection** — `detect_partial(query)` returns the letter, the digits and any partial sub-code, or
`None`. Three rules keep it closed, because a false positive refuses a real symptom query:

| rule | why |
|---|---|
| at most **3 whitespace tokens**, or the whole query | "after 10 km it stalls" is never examined |
| the body must contain at least one **0–9 digit** | every letter of `CAB` is a valid hex digit and `C` is a code letter, so without this the word "cab" reads as a code attempt |
| **1–3 digits only** | four digits is well-formed and belongs to the existing paths — exact match, the 9.3b unknown-code refusal, the base-without-suffix clarification |

**Behaviour** — a new decision **`incomplete_code`**: no retrieval runs, nothing is auto-selected,
no repair procedure is asserted. The reply is the fixed sentence
`'<input>' is not a complete code in this manual. Codes look like P0192-00.` plus candidates drawn
from the **code dictionary only**, by three deterministic rules:

- **(a)** codes whose 4-digit part starts with the digits given;
- **(b)** the digits zero-padded on the left to 4 (`10` → `0010`);
- **(c)** codes one digit-**insertion** away — which can only reach a 4-digit part from 3 given
  digits, so in practice this is the dropped-digit case.

The union is de-duplicated, sorted by code, and capped at 5; beyond that the list ends with
`N more - please enter the full code`. **Fewer than 2 digits gives no candidates at all**, only the
format hint: one digit matches a sixteenth of the manual, which is a list, not a hint.

Every step is labelled **RULE** in the "Why this answer?" panel, and the decision is written to the
audit log as `incomplete_code` with the candidate codes it offered.

**Left unchanged**, as required: full codes (exact match), well-formed absent codes (9.3b refusal +
did-you-mean), a base code without its sub-code (9.3b clarification), and the Phase 13.1
conversational replies. Each is pinned by a test.

## Results

### Tests — `src/test_partial_codes.py`, 70/70

18 should-trigger (`P-10`, `P10`, `p 019`, `P019-`, `P01-00`, `B1`, `U01`, `P1`, `P_10`, `P.10`,
`C12`, `P11A`, `code P10`, …) and 28 must-not-trigger, including the whole dangerous class:

| query | result | why |
|---|---|---|
| `P0192-00`, `P0192`, `P0199-00`, `U011A-00`, `PO192-00` | `None` | complete codes own these paths |
| `P0192-00 and black smoke` | `None` | a complete code is present |
| `cylinder 3 misfire`, `3rd gear jerks`, `after 10 km it stalls` | `None` | no code letter + digits token |
| `cab`, `CAB`, `ace`, `bed`, `decade` | `None` | all-hex words, no real digit |
| `PM sensor`, `PTO switch`, `pressure` | `None` | the character after the letter is not hex |
| `P10 code came up on the dash this morning` | `None` | more than 3 tokens |

End-to-end through the router: `P-10`, `P019`, `P1`, `code P10` → `incomplete_code` with
`retrieval_run: false` and `auto_selected: false`; `P0192-00` → `exact_code`, `P0192` →
`exact_code`, `P0199-00` → `unknown_code`, `cylinder 3 misfire` → `hybrid`, `all coolant faults` →
`system_group`, all unchanged.

### 1,007-query robustness study — post-change re-run

Re-run of `scripts/robustness_9_3.py` → `data/experiments/9_3/results_13_3.json`, compared against
the published 9.3b "after" column (`results_9_3b.json`), the by-noise-type table of §2 of the 9.3b
report:

| | 9.3b | 13.3 re-run |
|---|---|---|
| recovered (@1 + @3 + listed) | 738 | **738** |
| refused | 211 | **211** |
| clarified | 4 | **4** |
| **HARMFUL (confident wrong answers)** | **2** | **2** |
| wrong (hedged) | 52 | **52** |

**Every aggregate count is identical**, and that is the correct outcome rather than a
disappointment: 9.3b already refused all 80 dropped-digit inputs, so there was no count left to
win. What changed is **which mechanism answers them and what the user sees**:

| noise type | n | route in 9.3b | route in 13.3 |
|---|---|---|---|
| code — dropped digit | 80 | `unknown_code` 80 | **`incomplete_code` 80** |
| code — transposed digit | 80 | `unknown_code` 74, `suffix_not_found` 4, `exact_code` 2 | unchanged |

All other noise types keep their routes exactly. The two residual HARMFUL cases are the known
transposition collisions (`P0100-00` for `P1000-00`, `P1657-00` for `P1675-00`) — real codes typed
for other real codes, which no format rule can detect and which 10.2's telemetry cross-check is the
answer to.

### The case the 1,007-query corpus does not contain

That corpus only generates dropped digits **with** a sub-code. The regression this phase actually
fixes — a 1–3 digit attempt with no sub-code — is absent from it, so a separate probe was needed.
`scripts/measure_13_3.py` builds those forms deterministically from the code dictionary (synthetic,
no gold file: 80 sampled codes × 3 forms = 240) and records which route answers them. The "before"
column was produced by running the same probe in a `git worktree` at `b3eef93`:

| form | before (`b3eef93`) | after (13.3) |
|---|---|---|
| 3 digits, no suffix (`P019`) | `hybrid` 80 | **`incomplete_code` 80** |
| 2 digits, no suffix (`P10`) | `hybrid` 80 | **`incomplete_code` 80** |
| 2 digits, separator (`P-10`) | `hybrid` 80 | **`incomplete_code` 80** |
| **answered with a ranked list of codes** | **240 / 240** | **0 / 240** |

Artefacts: `data/experiments/13_3/measurements.json` (after) and
`data/experiments/13_3/probe_before_b3eef93.json` (before).

### Interception count — POST-HOC, counts only

`detect_partial()` alone, no retrieval, over every row of all four sets:

| set | rows | intercepted |
|---|---|---|
| DEV (gold_v2) | 34 | **0** (symptom 0/12, near-dup 0/7, exact 0/6, group 0/3, out-of-scope 0/6) |
| TEST (gold_v2, spent) | 36 | **0** (symptom 0/13, near-dup 0/7, exact 0/6, group 0/4, out-of-scope 0/6) |
| independent (spent) | 60 | **0** (symptom 0/41, no_dtc 0/19) |
| R2 colleague (spent) | 20 | **0** (symptom 0/15, no_dtc 0/4, inconclusive 0/1) |

**0 of 150**, as required, so no rule needed changing. R2 is not on this branch and was read
read-only with `git show`.

### Demo and regression

Three presets added (`P-10`, `P019`, `P1`); `./run.sh demo --check` extended from 49 to **55
checks** — the three presets (each asserting `mode == "incomplete_code"`, the format sentence, no
results, `retrieval.used == false`, every `why` step RULE, and candidates present only where ≥2
digits were given), plus three negatives (`P0192-00`, `P0192`, `cylinder 3 misfire`) — and reports
**DEMO CHECK PASSED**. The audit assertion now requires `incomplete_code` alongside `refuse`,
`mismatch` and `conversational`.

Suite `src/smoke_index.py` **44 passed / 1 xfail / 0 failed**; determinism
`--defaults --index-dir index` **`ffff9bc707d8754d`**; Phase 13.1 tests **67/67** unaffected.

## Files

| file | role |
|---|---|
| `src/partial_code.py` | detection, the three candidate rules, the fixed message |
| `src/test_partial_codes.py` | 70 cases, 28 of them must-not-trigger |
| `src/retrieve.py` | the router consults it before the code branch (mode `incomplete_code`) |
| `src/answer.py`, `src/advise.py` | surface it as a clarification; never fix blocks |
| `app.py` | `why_incomplete_code()` (all RULE), audit decision `incomplete_code` |
| `web/app.js` | renders it as a clarification, not an error; 3 presets |
| `scripts/measure_13_3.py` | the synthetic probe and the interception count |
| `data/experiments/13_3/` | both measurement artefacts |
| `data/experiments/9_3/results_13_3.json` | the post-change robustness re-run |

## Limitations

1. **Transposed digits remain undetectable.** `P0100-00` typed for `P1000-00` is a *valid* code, so
   no format rule can see the error. Both residual HARMFUL cases are of this kind; the telemetry
   cross-check (10.2) is the only defence and it needs telemetry.
2. **Candidate rules are lexical, not semantic.** For `P-10` they return `P1000-00 … P1004-00` plus
   "12 more" — the first five by code order, not the five most likely. With 2 digits the list is
   essentially arbitrary within the prefix, which is why the message asks for the full code rather
   than inviting a choice.
3. **The 3-token ceiling is a blunt instrument.** `P10 code came up on the dash this morning` is a
   genuine code attempt and is *not* intercepted; it falls through to hybrid as before. Widening the
   window would start catching ordinary sentences containing short alphanumerics, so the safe
   direction was chosen.
4. **Hex-letter collisions are only mostly handled.** The "must contain a real digit" rule saves
   `cab`, `ace` and `bed`, but a query like `C4b` (2 tokens or fewer) would be read as an attempt.
   No such query appears in any set measured here.
5. **`B` and `C` are connector letters in this manual** (`C001`). They are accepted as code letters
   for detection, as specified, so `C12` is treated as an incomplete code rather than a connector
   fragment. Connector ids with a full 4-character body still reach the existing hybrid fallback.
6. **0/150 is not a safety proof.** None of the four sets contains a partial-code row — they were
   written as diagnostic sets — so the count shows absence of harm on fault data, not correct
   behaviour on real mistyping at scale.
