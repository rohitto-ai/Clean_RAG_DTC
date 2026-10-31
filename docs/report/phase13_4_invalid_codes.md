# Phase 13.4 — over-long / garbage code tokens

_Branch `phase10-demo`, after `2696994`. Retrieval scoring, the relevance gate, the indexes and
the records are **unchanged**._

## Objective — the reported bug

```
query:  P1023473efa234rgddhdhdfgddhy
answer: P0001-00, P0219-00, P0089-92
```

The token is obviously a mistyped or pasted code, but it matches no code pattern, so nothing in
the router claimed it and it reached **hybrid symptom retrieval**, which dutifully returned three
unrelated faults. 13.3 closed the *too short* case (`P10`, `P019`); this closes the *too long or
malformed* one.

## Method

A new decision **`invalid_code`** fires when **all four** hold:

1. the token starts with `P`/`U`/`B`/`C` followed by a digit;
2. it is longer than any real code (`P0192-00`, 8 characters) **or** contains a character a code
   body cannot hold (anything outside hex and `-`, `_`, `.`);
3. **the existing 9.3 logic extracts no valid code from the query** — this is the ordering
   requirement, and it is what keeps every log-embedded form on its current path;
4. the Phase 13.3 scope rule: at most 3 tokens, or the token sits directly beside
   `code` / `codes` / `DTC` / `DTCs` / `fault` / `faults`.

The reply runs no retrieval and selects nothing:

> `'P1023473efa234rgddhd…' is not a valid fault code. Codes in this manual look like P0192-00.`

The token is truncated to 20 characters plus an ellipsis, so a pasted log line cannot flood the
message. If the first letter plus the next four characters happen to be a base code the manual
holds, its variants are listed with descriptions (capped at 5): `P0192abcdefgh` →
*"Codes starting with P0192:"* → `P0192-00 (page 8): Rail pressure Sensor Short circuit to ground`.
Otherwise the format hint stands alone. Every step is **RULE** in the why panel, and the decision
is audited as `invalid_code`.

### Two cases that go the other way, checked and documented

The task asked which way `P0192-00xyz123abc` falls. **It does not trigger**, and should not:
`DTC_CODE_RE` finds a word boundary at the `-` and extracts the base `P0192`, so condition 3 fails
and the query routes to `exact_code`, answering with that code's own variants. The same is true of
`P0192-00-00-00` (the second `-` is a boundary, so `P0192-00` is extracted) — this was a
must-not-trigger case I initially wrote the other way round, and the test was corrected rather than
the rule.

That is the right behaviour: when a real code can be read out of the junk, answering with **that
code's family** is more useful than refusing, and it is exactly what 9.3 built the extraction for.

## Results

### Tests — `src/test_invalid_codes.py`, 72/72

13 should-trigger (the reported string, `P99999999`, `U0100zzzz`, `code P1023473efa`,
`P0192abcdefgh`, `B1234567890`, `C0001xxxx`, `U011Azzz`, `P12#34`, lowercase `p1023473EFA`, …) and
27 must-not-trigger:

| class | examples | route |
|---|---|---|
| 9.3 log-embedded forms | `DTC=P0192-00;ts=1230`, `P0192-00@08:15`, `[ECU] P0192-00 \| MIL=ON`, `code:P0192-00,count=3`, `2026-03-03 10:14 P0192-00 active` | `exact_code` |
| junk appended, code still extractable | `P0192-00xyz123abc`, `P0192-00-00-00` | `exact_code` |
| every valid shape | `P0192-00`, `P0192`, `U011A-00`, `P203B-85`, `PO192-00`, `P0192_00` | `exact_code` |
| 13.3 partials | `P10`, `P-10`, `P019`, `P1`, `code P019 today` | `incomplete_code` |
| ordinary text | `P10 came up on the dash`, `PM sensor`, `cylinder 3 misfire`, `1500 rpm surge`, `after 10 km it stalls` | `hybrid` |

13.3 (96/96) and 13.1 (67/67) tests both still pass unchanged.

### Garbage probe — 200 synthetic code-shaped tokens

Built deterministically from the dictionary's own codes (seeded): base + junk tail, over-long digit
runs, illegal characters inside, and full codes with the dash stripped plus junk. The before column
was produced by running the same probe in a `git worktree` at `2696994`:

| | before (`2696994`) | after (13.4) |
|---|---|---|
| `hybrid` — **unrelated** symptom search | **159** | **0** |
| `invalid_code` — hint, no retrieval | 0 | **159** |
| `exact_code` — a real base was extractable | 41 | 41 |
| **answered with a ranked list** | **200 / 200** | **41 / 200** |
| **answered with an UNRELATED ranked list** | **159 / 200** | **0 / 200** |

The task's target was "N/200 → 0/200". The honest number is **41/200**, not zero, and the 41 are
not a miss: every one of them is a form like `P0192#abcd` where `#` is a word boundary, so 9.3
extracts `P0192` — and all **41/41 return the source code's own family**, never an unrelated list.
The bug was unrelated results, and that count is **159 → 0**.

### 1,007-query robustness study — post-change re-run

`data/experiments/9_3/results_13_4.json` versus the 13.3b re-run: **every row and every route is
identical**. Recovered 738, refused 211, clarified 4, **HARMFUL 2**, hedged 52. No explanation of
changes is needed because there are none — that corpus contains no over-long or malformed token,
which is why this bug survived it.

### 240-form partial-code probe (13.3) — unchanged

`incomplete_code` 240/240, **0/240** ranked lists. 13.4 does not disturb 13.3: the invalid check
runs only when the 13.3 check has already declined.

### Interception count — POST-HOC, counts only

`detect_invalid()` alone, no retrieval, over every row of all four sets: **0 of 150** — DEV 0/34,
TEST 0/36, independent 0/60, R2 0/20. No rule needed changing.

### Demo

Two presets added (`P1023473efa234rgddhdhdfgddhy`, `U0100zzzz`); `./run.sh demo --check` extended
from 55 to **61 checks** and reports **DEMO CHECK PASSED**. The new block asserts the format hint,
`retrieval.used == false`, all-RULE steps, that `P0192abcdefgh` lists exactly `P0192-00`, and that
the three log-embedded forms still route to the code path. The audit assertion now requires
`invalid_code` alongside `refuse`, `mismatch`, `conversational` and `incomplete_code`.

Suite `src/smoke_index.py` **44 passed / 1 xfail / 0 failed**; determinism
`--defaults --index-dir index` **`ffff9bc707d8754d`**.

## Files

| file | role |
|---|---|
| `src/partial_code.py` | `detect_invalid()`, `resolve_invalid()`, the 20-character truncation |
| `src/test_invalid_codes.py` | 72 cases, 27 of them must-not-trigger |
| `src/retrieve.py` | the router consults it only when 9.3 extracted nothing (mode `invalid_code`) |
| `src/answer.py`, `src/advise.py` | surface it; never fix blocks |
| `app.py` | `why_code_hint()` now serves 13.3 and 13.4; audit decision `invalid_code` |
| `web/app.js` | one renderer for both code-hint replies; 2 presets |
| `scripts/measure_13_4.py` | the garbage probe and the interception count |
| `data/experiments/13_4/` | `measurements.json` (after) and `probe_before_2696994.json` (before) |

## Limitations

1. **A code buried in junk still answers with that code.** `P0192-00xyz123abc` returns the P0192
   family. That is deliberate (condition 3) and matches 9.3's log-extraction design, but if the junk
   means the user actually typed something else, the answer is confidently about the wrong fault.
2. **The 8-character ceiling is manual-specific.** It is right for `P0192-00`; a manual with longer
   codes would need the constant changed.
3. **`B` and `C` are connector letters here** (`C001`). `C0001xxxx` is treated as an invalid code
   rather than a mangled connector id — the format hint is still the honest answer, but it names a
   P-code shape.
4. **Only the first five characters are tried as a base.** `P1023473efa` offers nothing because
   `P1023` is not in this manual; a smarter search (nearest base, edit distance) was deliberately
   not attempted, because guessing which code a corrupted token meant is exactly what 9.3b refused
   to do for transposed digits.
5. **0/150 is not a safety proof.** None of the four sets contains a malformed-code row, so the
   count shows absence of harm on fault data, not correct behaviour on real pasted logs.
