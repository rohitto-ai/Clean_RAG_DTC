# Phase 9.3 — noisy-input robustness and failure modes

_2026-09-17 · branch `phase8-limitations` · additive: production code, indexes and gate are unchanged · TEST not used_

This answers the supervisor's request for "failure modes (noisy telematics data)". A corrupted
P-code stands in for a noisy telematics fault record, and a corrupted symptom stands in for a
hurried technician note.

**Headline.**

- **Recoverable noise.** Case changes and a code embedded in log text recover 100%. Symptom
  typos and abbreviations recover 94–95% within the top 3 (clean: 97.5%). Missing-suffix codes
  always return the correct DTC inside the listed variants.
- **Confident wrong answers are rare.** **HARMFUL = 6 of 1,007 queries (0.6%)**, all
  transposed-digit codes, where the corrupted code is itself a valid code in the manual.
  No recoverable, degraded or garbage input produced one.
- **The main weakness is not refusal but fallback.** When the code regex cannot parse a
  corrupted code, or the code is not in this manual, the router falls back to hybrid search
  and gate v2 lets it through. The user then gets a ranked list of unrelated DTCs instead of
  "code not recognised". Two numbers show the size of it:
  - well-formed codes that don't exist in the manual: **10/10 not refused**;
  - transposed or dropped digits: 82.5% land here.

## 1. Setup — `scripts/robustness_9_3.py`

- **Base cases.** A seeded sample of 80 `code` cases and 80 `paraphrase` cases from
  `data/gold_autogen.jsonl` (ground truth = the OEM manual's code ↔ description pairing,
  not human-verified).
- **Noise and garbage.** Each base case gets every applicable noise transform. Garbage adds
  60 inputs, for **1,007 queries** in total. Transforms are deterministic, seeded by string.
  Re-running under a different PYTHONHASHSEED gives a byte-identical `results.json`.
- **System under test.** Production as served, minus the LLM:
  - the `Retriever()` router;
  - gate v2 applied exactly where `answer.answer()` applies it (hybrid route only).

  The LLM only phrases a hybrid answer; which DTCs the user sees is decided here.

**Outcomes.** Each query gets exactly one; the first match wins.

| outcome | meaning |
|---|---|
| correct@1 | expected DTC ranked first |
| correct@3 | expected DTC ranked 2–3 |
| correct_listed | exact-code route on a **base** code: every suffix variant is rendered, and the expected one is among them at rank > 3. Ambiguous, not wrong. |
| refused | no result, or gate v2 refused ("not covered in this manual") |
| **HARMFUL** | exact-code route answered with a DTC that is **not** the expected one. The user receives a deterministic, unhedged repair procedure for the wrong fault. |
| wrong_hedged | hybrid route passed the gate, but the expected DTC is not in the top 3. The user sees a ranked candidate list with LLM phrasing, not a single asserted fault. For garbage input, every non-refused answer lands here: an unsafe non-refusal. |

**Rates used in the headline:**
- RECOVERY = correct@1 + correct@3 + correct_listed
- SAFE-REFUSAL = refused (for garbage)
- HARMFUL = HARMFUL

## 2. Robustness table

| noise type | class | n | @1 | @3 | listed | **RECOVERY** | refused | **HARMFUL** | wrong (hedged) |
|---|---|---|---|---|---|---|---|---|---|
| code — clean | clean | 80 | 100.0% | – | – | **100.0%** | 0% | **0%** | 0% |
| code — lowercase `p0192-00` | recoverable | 80 | 100.0% | – | – | **100.0%** | 0% | **0%** | 0% |
| code — embedded in log text | recoverable | 80 | 100.0% | – | – | **100.0%** | 0% | **0%** | 0% |
| code — missing suffix `P0192` | recoverable | 80 | 67.5% | 20.0% | 12.5% | **100.0%** | 0% | **0%** | 0% |
| code — spacing / punctuation | recoverable | 80 | 56.2% | 11.2% | 2.5% | **70.0%** | 0% | **0%** | 30.0% |
| code — letter O for zero | recoverable | 67 ¹ | 67.2% | 4.5% | 1.5% | **73.1%** | 0% | **0%** | 26.9% |
| code — transposed digit | unrecoverable | 80 | 5.0% | 5.0% | – | 10.0% | 0% | **7.5%** | 82.5% |
| code — dropped digit | unrecoverable | 80 | 12.5% | 5.0% | – | 17.5% | 0% | **0%** | 82.5% |
| symptom — clean | clean | 80 | 85.0% | 12.5% | – | **97.5%** | 0% | **0%** | 2.5% |
| symptom — typos (20% of words ≥ 5 chars) | recoverable | 80 | 80.0% | 13.8% | – | **93.8%** | 0% | **0%** | 6.2% |
| symptom — abbreviations (sens, ckt, gnd, inj…) | recoverable | 80 | 85.0% | 10.0% | – | **95.0%** | 0% | **0%** | 5.0% |
| symptom — truncated to 3 words | degraded | 80 | 23.8% | 28.8% | – | 52.5% | 2.5% | **0%** | 45.0% |
| garbage — random tokens | garbage | 30 | – | – | – | – | **86.7%** | **0%** | 13.3% |
| garbage — empty-ish (`""`, `?`, `0000`…) | garbage | 10 | – | – | – | – | **90.0%** | **0%** | 10.0% |
| garbage — out-of-domain sentences | garbage | 10 | – | – | – | – | **100.0%** | **0%** | 0% |
| garbage — well-formed code not in manual | garbage | 10 | – | – | – | – | **0.0%** | **0%** | **100.0%** |

¹ 13 sampled codes contain no zero.

No query raised an exception, including the empty string.

**By class:**

| class | n | RECOVERY | SAFE-REFUSAL | HARMFUL | wrong (hedged) |
|---|---|---|---|---|---|
| clean | 160 | 98.8% | – | 0 | 1.2% |
| recoverable | 547 | 88.3% | – | **0** | 11.7% |
| degraded | 80 | 52.5% | 2.5% | **0** | 45.0% |
| unrecoverable | 160 | 13.8% | 0% | **6 (3.8%)** | 82.5% |
| garbage | 60 | – | **75.0%** | **0** | 25.0% |

## 3. HARMFUL — every case (6)

All 6 are transposed digits:

| query (noisy) | true DTC | system answered | why |
|---|---|---|---|
| `P0100-00` | P1000-00 | P0100-00 | the corrupted code **is a real code** — no system can detect this |
| `P1657-00` | P1675-00 | P1657-00 | same: a real code |
| `P1000-9C` | P0100-9C | P1000-00 | `P1000-9C` does not exist; the base `P1000` does, so its variant is returned |
| `P0101-11` | P0110-11 | P0101-00 | same: base-code fallback onto a different real base |
| `P0102-11` | P0120-11 | P0102-00 | same |
| `P203A-12` | P20A3-12 | P203A-23 / -24 / -29 | same: all variants of the wrong base |

- **Two of the six** are inherent. A transposition that produces another valid code is
  indistinguishable from a correct report without extra evidence (freeze-frame data, SPN/FMI,
  vehicle symptoms).
- **Four of the six** are a design choice. When the full code is unknown but its base exists,
  the router silently answers with the base's variants, even though the suffix the user gave
  matches none of them. Refusing, or saying "suffix -9C not found for P1000; variants are …",
  would turn these into safe outcomes.

## 4. Where it degrades gracefully and where it fails

**Graceful:**

- **Case, surrounding text and punctuation around a code.** Handled: `p0192-00`,
  `ts=… dtc=P0192-00 cnt=3`, `(P0192-00).` and `P0192-00 ;` all recover 100%. This is the
  telematics-relevant case: a code inside a log line is found.
- **Missing suffix.** A base code lists every variant, so the true DTC is always shown (100%).
  Only 67.5% have it first, because the suffix is simply unknown. That is the honest answer.
- **Symptom typos and abbreviations.** Top-3 recovery drops 2.5–3.7 points from clean. The
  dense encoder tolerates misspellings, and BM25 still matches the untouched words.
- **Out-of-domain sentences.** 10/10 refused, both by the intent stoplist and by low signal.
- **Truncated symptoms.** Recovery halves (97.5% → 52.5%). The losses are wrong-but-hedged
  ranked lists, never HARMFUL. Three words like "short to the" genuinely match dozens of DTCs.

**Fails (in order of risk):**

1. **Codes that are not in this manual are not refused (0/10).** `P26FB-47` or `P3E94-89` falls
   back to hybrid search, and the code-shaped string scores just enough to pass gate v2's
   signal threshold. The user then sees a ranked list of unrelated DTCs, phrased by the LLM.

   For telematics this is the most important failure. A record from another ECU, or a code
   the manual doesn't cover, should get "code not in this manual", not a list of neighbours.
2. **Codes the regex can't parse fall through to the same fallback.**

   | noisy form | example | result |
   |---|---|---|
   | space after the letter | `P 0192-00` | 12/12 wrong (hedged) |
   | underscore separator | `P0192_00` | 12/16 wrong (hedged); `_` is a word character, so `\b` fails |
   | letter O inside the base | `PO192-00` | 18/22 wrong (hedged) |
   | letter O in the suffix | `P0192-O0` | 45/45 recovered: the base still parses, so the variant list includes the right code |
   | spaced hyphen | `P0192 - 00` | 20/20 recovered |
   | dot separator | `P0192.00` | 8/8 recovered |

3. **Transposed and dropped digits** (unrecoverable by definition). 82.5% end up as unrelated
   hedged lists and 6 are HARMFUL (§3). The ideal behaviour is refusal, or "did you mean"
   candidates at edit distance 1, never an asserted procedure.
4. **Keyboard-mash and empty-ish input.** 5 of 40 passed the gate (`0000`, and 4 random-token
   strings such as `ldpd uux`). These are low-risk because they are hedged lists, but they are
   still non-refusals.

**Candidate hardening (NOT implemented; production is untouched in 9.3):**

- normalise code-like tokens before the regex (`P 0192`, `_` and `.` separators, letter O in
  code positions);
- when a code-shaped token matches nothing, answer "code not in this manual" instead of
  falling back to hybrid;
- when the full code is unknown but the base exists, say so and list the variants, rather than
  presenting them as the answer;
- offer edit-distance-1 codes as "did you mean" candidates, never auto-selected.

Each of these would need its own DEV re-validation before adoption.

## 5. Scope and caveats

- **Telematics.** This is a *proxy* for noisy telematics input: a corrupted DTC string in text.
  True telematics ingestion (J1939 SPN/FMI decoding, freeze frames, occurrence counters) is
  **Phase 4 of the telematics roadmap**. That is not this repository's Phase 4 (indexing), and
  it is not built.
- **Sample.** 80 + 80 base cases sampled from an auto-generated, **not human-verified** set.
  The rates are indicative (±~10 points at n = 80), not tight estimates.
- **Symptom base.** The base symptom cases are description paraphrases, not real technician
  language. The held-out symptom evidence remains the Phase 8.5 TEST (not used here).
- **LLM excluded.** A wrong_hedged outcome shows the user a ranked list plus LLM phrasing. In
  practice the phrasing can make a wrong candidate sound more confident than the list does,
  so these outcomes are not harmless, only less harmful than an asserted procedure.
- **Outputs.** `data/experiments/9_3/results.json` holds every query, its noisy text, route,
  returned codes and outcome.
