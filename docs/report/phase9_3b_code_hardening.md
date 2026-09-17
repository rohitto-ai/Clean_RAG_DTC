# Phase 9.3b — hardening DTC code handling (noisy and unknown codes)

_2026-09-17 · branch `phase8-limitations` · **changes production** (exact-code router path) · adopted as default · rollback: tag `v1-phase7` or revert this commit · TEST not used_

**Result.** On the unchanged Phase 9.3 harness (1,007 queries):

- **HARMFUL falls from 6 to 2.** The 2 left are the inherent collisions, where a transposed code
  is itself a real code in the manual.
- **Codes not in the manual:** refused 10/10 (was 0/10).
- **Unparseable corrupted codes** (`P 0192-00`, `P0192_00`, `PO192-00`): recovery 70–73% → **100%**.
- **Transposed and dropped digits** are now refused (or answered with a clarification) instead of
  producing unrelated hedged lists. The refusal's "did you mean" contains the true code in
  **78/80** and **74/80** of those cases.
- **Legitimate retrieval is unaffected:**
  - DEV evaluation output is byte-identical to Phase 9.1b.
  - Suite 44/1/0, advise 13/13, guardrails 14/14.
  - Determinism hash **unchanged, `ffff9bc707d8754d`**, under PYTHONHASHSEED 0 and 1.

## 1. Changes

All changes are in `src/retrieve.py`. The rendering of the two new modes is in `answer.py`,
`advise.py`, `cli.py` and `app.py`.

1. **Code-token normalisation, before code detection** (`normalize_code_tokens`). Only forms
   that are unambiguously a fault code are rewritten, and only for the fault-code letters **P and U**:

   | noisy | normalised | rule |
   |---|---|---|
   | `P 0192-00` | `P0192-00` | space after the letter, when 4 code characters follow |
   | `P0192_00`, `P0192.00`, `P0192 - 00` | `P0192-00` | `_` / `.` / spaced `-` before a 2-character suffix |
   | `PO192-00`, `P0192-O0` | `P0192-00` | letter O in a code position. O is never a hex digit, so this cannot collide with a real code. The body must also contain at least one real digit, so words like `POOF` are left alone. |

   Normalisation is used **only to detect the code**. Hybrid search and the gate still see the
   original query. Transposed or dropped digits are **never** corrected: that would silently
   choose a different fault.
2. **Unknown code → explicit refusal** (mode `unknown_code`).
   - **What triggers it:** a P/U code matching nothing in either code index. The code must be
     either a full base with 4 characters after the letter, or have a suffix.
   - **What the user gets:** "DTC P3A7F-00 is not covered in this manual." No hybrid fallback.
     `answer()` returns path `deterministic_refusal`; `advise()` returns mode `refused`.
   - **C/B tokens keep the hybrid fallback** (`what does connector C001 do` → hybrid, verified).
     So does a bare 3-character P/U token without a suffix, such as `P092`, which is too
     ambiguous to call a code.
3. **Base-suffix honesty** (mode `suffix_not_found`). When the base exists but the suffix does
   not, the user gets:

   > Exact code P1000-9C was not found in this manual. Known variants of P1000: P1000-00.
   > Please confirm the full code.

   The variants are listed with their descriptions and pages, but **no procedure is rendered**,
   and there are no citations or fix blocks. `answer()` returns path
   `deterministic_clarification`; `advise()` returns mode `clarify_code`.
4. **"Did you mean" (optional item, done).** Known codes within Damerau–Levenshtein distance 1
   (substitution, insertion, deletion, adjacent swap), at most 5. They are **surfaced in the text
   only, never auto-selected**. The risk is low because nothing is retrieved or rendered from a
   suggestion. Example: `P0912-00` → refused, with "one character away: P0192-00".

A missing suffix (`P0192`) is unchanged: it lists every variant, as before.

## 2. Robustness: before (9.3) vs after (9.3b)

Same harness, same seeds, same 1,007 queries. One addition to the harness: the new outcome
`clarified` for the `suffix_not_found` route (a safe outcome, neither a recovery nor HARMFUL).

- Before: `data/experiments/9_3/results.json`
- After: `data/experiments/9_3/results_9_3b.json`

| noise type | class | n | RECOVERY before → after | refused before → after | clarified | **HARMFUL before → after** | wrong (hedged) before → after |
|---|---|---|---|---|---|---|---|
| code — clean | clean | 80 | 100% → 100% | 0 → 0 | – | 0 → 0 | 0 → 0 |
| code — lowercase | recoverable | 80 | 100% → 100% | 0 → 0 | – | 0 → 0 | 0 → 0 |
| code — embedded in log text | recoverable | 80 | 100% → 100% | 0 → 0 | – | 0 → 0 | 0 → 0 |
| code — missing suffix | recoverable | 80 | 100% → 100% ¹ | 0 → 0 | – | 0 → 0 | 0 → 0 |
| code — spacing / punctuation | recoverable | 80 | 70.0% → **100%** | 0 → 0 | – | 0 → 0 | 30.0% → **0%** |
| code — letter O for zero | recoverable | 67 | 73.1% → **100%** | 0 → 0 | – | 0 → 0 | 26.9% → **0%** |
| code — transposed digit | unrecoverable | 80 | 10.0% → 0% ² | 0% → **92.5%** | 5.0% | **7.5% → 2.5%** | 82.5% → **0%** |
| code — dropped digit | unrecoverable | 80 | 17.5% → 0% ² | 0% → **100%** | – | 0 → 0 | 82.5% → **0%** |
| symptom — clean | clean | 80 | 97.5% → 97.5% | 0 → 0 | – | 0 → 0 | 2.5% → 2.5% |
| symptom — typos | recoverable | 80 | 93.8% → 93.8% | 0 → 0 | – | 0 → 0 | 6.2% → 6.2% |
| symptom — abbreviations | recoverable | 80 | 95.0% → 95.0% | 0 → 0 | – | 0 → 0 | 5.0% → 5.0% |
| symptom — truncated to 3 words | degraded | 80 | 52.5% → 52.5% | 2.5% → 2.5% | – | 0 → 0 | 45.0% → 45.0% |
| garbage — random tokens | garbage | 30 | – | 86.7% → 86.7% | – | 0 → 0 | 13.3% → 13.3% |
| garbage — empty-ish | garbage | 10 | – | 90.0% → 90.0% | – | 0 → 0 | 10.0% → 10.0% |
| garbage — out-of-domain | garbage | 10 | – | 100% → 100% | – | 0 → 0 | 0 → 0 |
| garbage — **code not in manual** | garbage | 10 | – | **0% → 100%** | – | 0 → 0 | **100% → 0%** |

¹ 67.5% ranked first, 20.0% at rank 2–3, 12.5% elsewhere in the rendered variant list. This is
unchanged: the suffix is genuinely unknown.

² **The trade-off, stated plainly.** Before the change, 8 transposed-digit and 14 dropped-digit
inputs fell back to hybrid search, and the true DTC happened to appear in the hedged candidate
list. Those inputs are now refused. However, the refusal's "did you mean" line names the true
code for **78/80** transposed and **74/80** dropped-digit inputs, never auto-selected. That is a
more useful and safer signal than an unrelated ranked list with the right code sometimes buried
inside.

**By class, HARMFUL / hedged-wrong:**

| class | n | HARMFUL before → after | wrong (hedged) before → after | refused before → after |
|---|---|---|---|---|
| recoverable | 547 | 0 → 0 | 51 → **9** | 0 → 0 |
| unrecoverable | 160 | **6 → 2** | 132 → **0** | 0 → **154** (+4 clarified) |
| garbage | 60 | 0 → 0 | 15 → **5** | 45 → **55** |

The remaining 9 hedged-wrong recoverable cases are all symptom-typo and abbreviation cases,
untouched by this phase.

### The HARMFUL cases

Four of the six are fixed. All were transposed digits where the base existed but the suffix did not:

| noisy query | true DTC | before 9.3b | after 9.3b |
|---|---|---|---|
| `P1000-9C` | P0100-9C | P1000-00 procedure | **clarified**: "P1000-9C not found; variants of P1000: P1000-00"; did you mean P0100-9C |
| `P0101-11` | P0110-11 | P0101-00 procedure | **clarified** |
| `P0102-11` | P0120-11 | P0102-00 procedure | **clarified** |
| `P203A-12` | P20A3-12 | P203A-23/-24/-29 procedures | **clarified** |
| `P0100-00` | P1000-00 | P0100-00 procedure | **still HARMFUL**: `P0100-00` is a real code |
| `P1657-00` | P1675-00 | P1657-00 procedure | **still HARMFUL**: `P1657-00` is a real code |

The two remaining cases are indistinguishable from a correct report using the code string alone.
Detecting them needs evidence beyond the code, such as freeze-frame data, SPN/FMI or observed
symptoms. That is telematics-roadmap Phase 4 work, not this repository's Phase 4 (indexing).

## 3. The C001 connector fallback still works

`what does connector C001 do` → mode `hybrid`, non-empty results, trace
`exact_code found 0 records for 'C001'; fell back to hybrid`. This is checked by both the
existing smoke test (still passing) and `src/test_code_hardening.py`.

## 4. Regression and validation

| check | before 9.3b | after 9.3b |
|---|---|---|
| DEV eval (gold v2.2) | exact 1.000 · near-dup 1.000 · symptom 58.3% / 0.711 · overall 80.0% / 0.861 · groups 3/3 · OOS 6/6 · in-scope 28/28 | **identical**: the result JSON equals the 9.1b run except for its label |
| smoke suite | 44 / 1 xfail / 0 | **44 / 1 / 0** |
| advise tests | 13/13 | **13/13** |
| guardrails | 14/14 | **14/14** |
| new `src/test_code_hardening.py` | – | **23/23** |
| determinism `--defaults` | `ffff9bc707d8754d` | **`ffff9bc707d8754d`** (seed 0 and 1) |

**Why the hash did not change.** The proof hashes the DEV evaluation output. An audit of the
gold query *texts* (a regex over strings only; no system was run on TEST) shows that **no DEV
or TEST query** is rewritten by the normaliser or reaches `unknown_code` or `suffix_not_found`.
The change is therefore invisible to every gold query by construction. This also means the
Phase 8.5 one-shot TEST numbers are unaffected. TEST was not re-run.

## 5. Adoption

- **Adopted as the production default.** There is no flag: the router change applies to
  `Retriever.retrieve`, `answer`, `/query`, `/advise` and the CLI.
- Recorded in `data/production_config.json` under `router_code_handling`, together with the
  determinism hash.
- **Rollback:** revert this commit, or tag `v1-phase7` for the pre-Phase-8 system.

**Remaining limitations:**

- Real-code transposition collisions (2/160 of the unrecoverable inputs).
- Garbage that passes the gate (5/60, all hedged lists: 4 keyboard-mash strings and `0000`).
- Truncated symptoms (45% hedged-wrong).
