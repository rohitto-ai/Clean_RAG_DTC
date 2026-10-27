# Phase 10.6 — One-shot evaluation on the independent symptom set

_2026-10-27 · branch `phase10-demo` · pre-registered, run once · **nothing is adopted in this phase**_

## Headline

> **Production (b) on 41 independent symptom queries: hit@1 14.6%, hit@5 41.5%, symptom MRR
> 0.241 [95% CI 0.135–0.354].**
>
> **No configuration beats production.** Lexicon v2 (+0.004), lexicon v2 + lamp (+0.003) and the
> cross-encoder re-ranker (+0.000) all have paired 95% CIs that include 0. v1-phase7 is worse
> (−0.044), and even that CI includes 0.
>
> **Every configuration declined 0 of the 19 "no DTC in this manual" queries.** All 19 were
> answered with a confident list of DTCs. This is the most important result in the file, and it
> is a safety finding, not a ranking one.

Against the earlier numbers, the independent set is where the optimism goes:

| split | symptom hit@1 | symptom MRR | what it is |
|---|---|---|---|
| DEV (gold v2.2) | 58.3% | 0.711 | tuned against during Phase 8 — optimistic by construction |
| TEST (gold v2.2, 8.5, conservative ablation) | 23.1% | 0.368 | held out, but 19 lexicon entries matched its wording |
| **INDEPENDENT (this phase)** | **14.6%** | **0.241** | **written by other people, never seen before** |

Mean word-overlap with the manual is 0.050 here versus 0.090 (DEV) and 0.098 (TEST), and 22 of
41 rows share no content word at all with their expected description. This set is simply
harder, and it is the first measurement of this system that nothing was tuned against.

## Provenance (copied verbatim from `data/gold_independent.json`)

**queries**: 60 symptoms written in their own words by a pool of workshop technicians,
colleagues and non-engineer vehicle owners, not by the system designer; some may have been
phrased with AI assistance.

**ground_truth**: Drafted by an AI assistant from the manual's 314 DTC definitions WITHOUT
access to system outputs; reviewed by a second AI assistant under the author's supervision. Rule
applied: keep blind drafts; accept a reviewer change only if it was not taken from the reviewer
tool's retrieved candidate lists (accepted: Q26 +P22CF-72; rejected: Q14 +P0504-00, Q25
+P061C-00, Q20/Q46 +P243C-00); 'consider none' suggestions (Q09, Q16, Q23, Q58) kept as
low-confidence labels.

**query_field**: Only the 'query' text is given to the system. lamp_reported is metadata and
must not be appended to the query.

**scoring**: symptom rows: hit = any expected code; no_dtc rows: correct behaviour is to decline
(no DTC in this manual).

> **The queries are independent; the labels are not technician-verified.** They were drafted by
> an AI assistant from the manual and reviewed by a second one. The queries themselves — the
> part that matters most for measuring vocabulary mismatch — come from real people. Treat the
> absolute scores as indicative and the *comparisons between configurations* (same labels, same
> rows, paired) as the reliable part.

## Protocol

Pre-registered in `data/experiments/10_6/preregistration.json`, committed and pushed as
`2819d76` **before `scripts/independent_eval.py` was written or run**. It fixed the five
configurations, the metrics, the subsets, the bootstrap settings and the adoption rule, and
recorded the sha256 of 16 inputs.

- **Validation** (`scripts/validate_independent.py`, passes): sha256
  `266abff6…df6ecf4` matches the brief; schema sound; all 153 expected code slots exist among
  the 314 records; 41 symptom + 19 no_dtc; 14 high / 26 medium / 20 low. Word-overlap statistics
  were computed **for information only** — no query was dropped or edited, and no retrieval was
  run during validation.
- **One shot:** `scripts/independent_eval.py` refuses to run if its results file exists. It was
  run once. Nothing was tuned afterwards.
- **Input to the system:** `q["query"]` and nothing else. `lamp_reported`, `notes`, `confidence`
  and `expected` are never passed.
- **Scoring:** a gated (refused) symptom row scores 0 for hit and MRR. A refusal is right for a
  no_dtc row and wrong for a symptom row, and the metric must not hide that.
- The Phase 10.1b freeze was re-verified before the run: all six files matched.

Configuration (a) is the **v1-phase7 retrieval configuration rebuilt on today's records**
(`index_exp/minilm_v1`: no aliases, no cylinder or state compounds, legacy gate), not a
byte-identical replay of the tag — the 9.1b parser fix changed 3 records. Every configuration
sees the same data, so the comparison is like-for-like.

## Results — symptom rows (41)

| cfg | configuration | subset | n | hit@1 | hit@3 | hit@5 | MRR | MRR 95% CI |
|---|---|---|---|---|---|---|---|---|
| a | v1-phase7 | ALL | 41 | 12.2% | 24.4% | 31.7% | 0.197 | 0.098–0.307 |
| **b** | **production C4b + gate v2** | ALL | 41 | **14.6%** | **29.3%** | **41.5%** | **0.241** | **0.135–0.354** |
| c | lexicon v2 | ALL | 41 | 14.6% | 34.1% | 41.5% | 0.245 | 0.140–0.358 |
| d | lexicon v2 + lamp | ALL | 41 | 14.6% | 34.1% | 41.5% | 0.244 | 0.139–0.357 |
| e | lexicon v2 + cross-encoder | ALL | 41 | 17.1% | 24.4% | 41.5% | 0.241 | 0.132–0.362 |
| a | v1-phase7 | HIGH | 6 | 16.7% | 33.3% | 33.3% | 0.250 | 0.000–0.583 |
| b | production | HIGH | 6 | 16.7% | 50.0% | 50.0% | 0.306 | 0.056–0.639 |
| c | lexicon v2 | HIGH | 6 | 33.3% | 50.0% | 50.0% | 0.417 | 0.083–0.833 |
| d | lexicon v2 + lamp | HIGH | 6 | 33.3% | 50.0% | 50.0% | 0.417 | 0.083–0.833 |
| e | cross-encoder | HIGH | 6 | 16.7% | 33.3% | 83.3% | 0.339 | 0.139–0.625 |
| a | v1-phase7 | HIGH+MED | 21 | 19.0% | 28.6% | 38.1% | 0.254 | 0.103–0.429 |
| b | production | HIGH+MED | 21 | 19.0% | 38.1% | 47.6% | 0.294 | 0.143–0.468 |
| c | lexicon v2 | HIGH+MED | 21 | 19.0% | 38.1% | 42.9% | 0.290 | 0.135–0.468 |
| d | lexicon v2 + lamp | HIGH+MED | 21 | 19.0% | 38.1% | 42.9% | 0.290 | 0.135–0.468 |
| e | cross-encoder | HIGH+MED | 21 | 28.6% | 38.1% | 52.4% | 0.359 | 0.180–0.548 |

Gate pass rate on symptom rows: **100%** for (b)–(e), 97.6% for (a) — the legacy gate refused
one genuine symptom query.

The HIGH subset has **n = 6**. Its intervals are enormous (e.g. 0.083–0.833) and nothing in that
column should be read as a result.

## Paired bootstrap vs (b) — 10,000 resamples, seed 1006

| comparison | subset | MRR difference | paired 95% CI | excludes 0 |
|---|---|---|---|---|
| a − b | ALL | −0.0435 | [−0.1012, +0.0061] | no |
| c − b | ALL | **+0.0041** | [−0.0488, +0.0589] | **no** |
| d − b | ALL | **+0.0028** | [−0.0492, +0.0565] | **no** |
| e − b | ALL | **+0.0000** | [−0.0947, +0.1000] | **no** |
| a − b | HIGH | −0.0556 | [−0.1667, +0.0000] | no |
| c − b, d − b | HIGH | +0.1111 | [+0.0000, +0.3333] | no (lower bound touches 0) |
| e − b | HIGH | +0.0333 | [−0.3333, +0.3667] | no |
| a − b | HIGH+MED | −0.0397 | [−0.0952, +0.0119] | no |
| c − b, d − b | HIGH+MED | −0.0040 | [−0.0833, +0.0873] | no |
| e − b | HIGH+MED | +0.0651 | [−0.0913, +0.2381] | no |

## Results — no_dtc rows (19): the safety finding

| cfg | declined | decline rate | 95% CI | routes |
|---|---|---|---|---|
| a | **0/19** | 0.000 | 0.000–0.000 | hybrid ×19 |
| b | **0/19** | 0.000 | 0.000–0.000 | hybrid ×19 |
| c | **0/19** | 0.000 | 0.000–0.000 | hybrid ×19 |
| d | **0/19** | 0.000 | 0.000–0.000 | hybrid ×19 |
| e | **0/19** | 0.000 | 0.000–0.000 | hybrid ×19 |

Every one of the 19 was answered with DTCs. Examples (production):

| id | query (abridged) | answered with |
|---|---|---|
| Q42 | "sweet coolant smell near the front after parking…" | P0117-00, P0119-00, P0118-00 |
| Q48 | "belt gives a short squeal just after the first start…" | P0110-12, P0110-11, P0A1B-12 |
| Q47 | "fresh oil wetness around the top cover area…" | P2458-09, P20A2-00, P208C-00 |
| Q30 | "turbo sound changes from a smooth whistle to a brief flutter…" | P0048-00, P0047-00, P003A-00 |
| Q27 | "rattly diesel knock when accelerating in a high gear…" | P0219-00, P061C-00, P0336-00 |

**Why the gate cannot catch these** (post-hoc diagnostic, no metric changed): gate v2 refuses
only when `dense_sim < 0.23` **and** `bm25_max < 8.5`. Across the 19 rows,
`dense_sim` ranges 0.145–0.496 (median 0.344) and `bm25_max` ranges **11.46–26.05** (median
16.38). **Not one row is below both thresholds**, so the gate is structurally incapable of
refusing any of them.

That is not a threshold that needs nudging. These queries use real automotive vocabulary —
coolant, turbo, oil, belt, exhaust — and describe real faults; they simply are not *diagnostic
trouble codes in this manual*. Gate v2 was calibrated on out-of-scope questions like "what is
the capital of France" and "what is the warranty period", which fail on both signals. A
mechanical complaint with no matching DTC looks, to a bag of words and an embedding, exactly
like a DTC symptom. **Distinguishing "no code covers this" from "here are the codes" needs
evidence the current gate does not have.**

## Error analysis — symptom rows

Production (b) misses **24 of 41** rows (no expected code in the top 5): 3 high, 8 medium,
13 low confidence.

**How far out are the misses?** (post-hoc, deeper retrieval): of the 24, **17 have an expected
code within the top 50** — ranks 6, 6, 7, 7, 10, 13, 13, 14, 15, 17, 18, 18, 22, 22, 33, 38, 49
— and **7 are not in the top 50 at all**. So roughly 70% of the failures are *ranking depth*,
not retrieval blindness, and 30% are genuine misses.

Four failure patterns, with examples:

1. **Vague, multi-cause driveability complaints (the largest group).** Q05 "a short flat spot
   before the engine picks up", Q31 "with a full load it feels flat", Q18 "on a long climb it
   gradually loses pull". The labels list 3–5 plausible codes across air, fuel and rail systems;
   the system returns a different plausible family. Nothing in the query selects between them —
   arguably no retrieval system can, from text alone.
2. **Symptom-to-subsystem leaps the manual's wording does not support.** Q13 "multiple warning
   lamps flicker over rough road, radio resets" → labelled as battery-voltage/CAN
   (P0563-00/P0562-00/U0102-00); the system returned engine-speed and ECU-internal codes. The
   link from "lamps flicker on bumps" to "supply voltage" is domain reasoning, not vocabulary
   overlap.
3. **Right family, wrong member.** Q12 (temperature reading jumps) returned DOC/SCR temperature
   codes instead of coolant-sensor codes; Q23 (cold shake) put P0119-00 at rank 1 while the
   label wanted P0116/P0117/P0118. Q08 and Q35 (both DPF, both HIGH confidence) returned DPF/DOC
   *temperature* codes instead of the soot-loading and regeneration codes. These are the
   near-duplicate discrimination cases the guardrails cover on crafted queries — and they fail
   here on real phrasing.
4. **Lexicon v2 helped exactly where it was designed to, and not elsewhere.** It moved hit@3
   from 29.3% to 34.1% (two rows), both vocabulary cases. It changed nothing on the vague or
   reasoning-dependent rows, which is why the overall gain is +0.004 and indistinguishable from
   noise.

**The cross-encoder is the most interesting non-result.** It improves hit@1 (14.6% → 17.1%) and
HIGH+MEDIUM MRR (0.294 → 0.359) while *lowering* hit@3 (29.3% → 24.4%): it is better at putting
one right answer first and worse at keeping the rest nearby. With n = 41 the paired CI
[−0.095, +0.100] cannot separate that from noise. It also costs ~60 s per run versus ~4 s. If
anything here deserves a follow-up on a larger set, it is this.

## Adoption decision under the pre-registered rule

> **Rule, fixed before the run:** a configuration replaces (b) only if **(1)** its paired 95% CI
> for symptom MRR gain over (b) excludes 0, **and (2)** its no_dtc decline rate is not lower
> than (b)'s. Evaluated on ALL rows.

| cfg | condition 1 — CI shows a gain | condition 2 — decline not lower | **replaces (b)?** |
|---|---|---|---|
| a | no (CI [−0.101, +0.006]) | yes (0.000 = 0.000) | **no** |
| c | no (CI [−0.049, +0.059]) | yes | **no** |
| d | no (CI [−0.049, +0.057]) | yes | **no** |
| e | no (CI [−0.095, +0.100]) | yes | **no** |

**Nothing replaces production.** Condition 2 is satisfied only in the trivial sense that every
configuration declines nothing, so condition 1 decided every case — and no configuration passed
it. **Nothing was adopted in this phase**, as the brief requires; `index/`, the gate and the
records are untouched.

This also settles Phase 10.1/10.1b honestly: **lexicon v2 and the lamp token were frozen
pending this evaluation, and this evaluation does not support adopting either.** Their DEV
numbers (−0.007 and −0.062) and their independent-set numbers (+0.004 and +0.003, both inside
noise) agree that neither is a measurable improvement.

## What this means

1. **The honest symptom number for this system is MRR ≈ 0.24, hit@5 ≈ 42%**, on queries written
   by other people. Every higher figure in this repository comes from a set that was either
   tuned against (DEV) or shares vocabulary with the lexicon (TEST).
2. **The refusal behaviour does not generalise.** 6/6 on DEV's out-of-scope queries and 0/19
   here. The DEV out-of-scope queries were off-domain; these are in-domain questions with no
   DTC answer, and that is the case that matters in a workshop.
3. **More vocabulary did not help.** Three separate attempts to improve symptom retrieval
   (lexicon v2, the lamp token, a cross-encoder re-ranker) all landed inside the noise band. The
   remaining failures are not vocabulary problems; they need either diagnostic reasoning over
   the manual's cause/effect fields or evidence beyond the text.

## Limitations

1. **n = 41 symptom rows.** Every CI is wide; the HIGH subset (n = 6) is uninformative. A
   difference smaller than about ±0.09 MRR cannot be resolved here.
2. **Ground truth is AI-drafted, not technician-verified.** The drafting was blind to system
   output and reviewer changes taken from retrieved candidates were rejected, but a human expert
   did not sign off the labels. Expected sets are generous (median 3, max 12 codes), which makes
   "hit = any expected code" lenient; a stricter rule would score lower.
3. **20 of 41 rows are low-confidence labels**, including four the drafter flagged as "consider
   none".
4. **Configuration (a) is a rebuild, not the tag.** Same configuration, today's records.
5. **The cross-encoder result is unreplicated** and based on one run of 41 rows.
6. **The independent set is now partly spent.** It has been used once, under a pre-registered
   protocol. Re-using it to choose between configurations would convert it into another DEV.

## Files

| file | role |
|---|---|
| `data/gold_independent.json` | the independent set (sha256 `266abff6…df6ecf4`) |
| `scripts/validate_independent.py` | schema, codes-exist, sha256, overlap statistics |
| `scripts/preregister_10_6.py` → `data/experiments/10_6/preregistration.json` | the protocol, fixed and pushed before the run |
| `scripts/independent_eval.py` | the one-shot evaluator (refuses to re-run) |
| `data/experiments/10_6/results.json` | every row, every configuration, all CIs and verdicts |
| `index_exp/minilm_v1/` | the v1-phase7 retrieval configuration (gitignored, rebuildable) |

Suite 44 passed / 1 xfail / 0 failed; determinism `--defaults` `ffff9bc707d8754d`.
