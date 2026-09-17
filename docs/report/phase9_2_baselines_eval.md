# Phase 9.2 — comparative evaluation against named baselines

_2026-09-17 · branch `phase8-limitations` · additive: production code, indexes and gate are unchanged_

**Headline.** On the discriminating modes, the structure-aware hybrid is best among the five
methods on both evaluation sets:

- **Near-duplicate discrimination (DEV):** hybrid scores MRR 1.000. The best baseline is
  dense-only at 0.643, and naive chunking scores 0.310.
- **Symptom (DEV):** hybrid scores MRR 0.711. The best baseline is naive-chunk at 0.340.
- **Auto-generated paraphrases:** hybrid scores MRR 0.875, against keyword 0.792, dense-only
  0.775 and naive-chunk 0.383.

Exact-code lookup is 100% for every method that has a regex or code token. Naive
fixed-size chunking is the weakest retriever on every stratum except DEV symptom, where it
is second.

Caveats that bound these claims (details in §6):
- DEV was used during Phase 8 development, so hybrid's DEV numbers are optimistic.
- The auto-generated set is not human-verified.
- Auto-gen (a) and (b) are coverage tests, not discrimination tests.
- The spent held-out TEST could not be used for the baselines.

## 1. Methods

All methods except naive-chunk rank the same 314 records. Every method returns its top 5.
Ranking is exact brute force with id tie-breaks. The whole run was repeated under a second
hash seed (PYTHONHASHSEED=1) and produced byte-identical output files.

| # | method | what it is |
|---|---|---|
| i | **keyword** | BM25Okapi over `build_index.bm25_text(record)`. Plain tokenizer: no lexicon aliases, no cylinder token, no router. |
| ii | **rule-based** | DTC-code regex → code dictionary. **A query without a code returns nothing.** This is the traditional code-lookup tool: exact and reliable for codes, useless for symptoms or descriptions. |
| iii | **dense-only** | MiniLM, exact cosine over the production record vectors. These are alias-free, which the script asserts. No BM25, no router. |
| iv | **naive-chunk** | Flat `pdfplumber` text of pages 8–545 (470,250 chars), split into fixed 500-char chunks with 50-char overlap (1,045 chunks). Indexed with MiniLM in a **separate** index `index_naive/`, with no per-DTC structure. For scoring only, each chunk is mapped back to the DTC owning most of its characters (all 314 DTC starts located, 0 unowned chunks). Ranked chunks collapse to their DTCs. A hit means a chunk maps back to the correct DTC. |
| v | **hybrid** (production) | `Retriever()`: router (exact code → subsystem group → hybrid) + dense/BM25 RRF + BM25 lexicon aliases + cylinder token (C4b). Gate v2 is applied exactly where `answer()` applies it (hybrid route only); a refusal counts as returning nothing. |

Metrics are computed at `code_full` level: rank = first position whose code is expected.

Scripts:
- `scripts/baselines_9_2.py build-naive` builds the naive index (~70 s).
- `scripts/baselines_9_2.py eval` runs the evaluation (~35 s).

Results are in `data/experiments/9_2/results.json`, with per-case rows in `autogen_rows.json`.

## 2. Auto-generated evaluation set — `data/gold_autogen.jsonl`

> **Label (also in the file header and on every case):** auto-generated; ground truth = OEM
> manual; NOT human-expert-verified (technician verification is future work).

Built by `scripts/gen_autogen_gold.py`, deterministically, without reading any retrieval
output. **935 cases**:

| kind | n | what | difficulty |
|---|---|---|---|
| (a) code | 311 | `code_full`, e.g. `P0192-00` | easy, coverage |
| (b) description | 312 | the manual's description verbatim | easy for lexical retrieval; **overlaps manual wording 100%**; a coverage test |
| (c) paraphrase | 312 | the description with the "DFC for" prefix dropped, fixed synonyms substituted, and a question frame added (e.g. "what should I check for rail pressure Sensor short to the negative side?") | moderate; still derived from the description |

More detail on how the set was built:

- **Deduplication.** Codes and descriptions are deduplicated. The 3 codes that appear twice in
  the manual give one code case each. Two descriptions are shared by two codes each, and those
  cases accept either code.
- **Size.** The brief estimated ~300–500 cases. The recipe itself (a + b + ≥ 1 paraphrase for
  each of 314 DTCs) yields 935, so all strata are reported separately.
- **Bias control.** The synonym table was written independently of the production lexicon. My
  first draft used "temp" and "volts", which are production-lexicon colloquial terms, so they
  were replaced by "heat reading" and "electrical level". Afterwards **13/312 paraphrases**
  still trigger a lexicon expansion. Twelve of those come from the manual's own words
  ("intermittent", "exhaust fluid", "disconnected", …) and one from the substitution
  "signal" → "output" ("no output").

## 3. Comparative table — auto-generated set (935)

| stratum | method | Hit@1 | Hit@3 | Hit@5 | MRR | empty |
|---|---|---|---|---|---|---|
| **(a) code** (311) | keyword | 100.0% | 100.0% | 100.0% | 1.000 | 0 |
| | rule-based | 100.0% | 100.0% | 100.0% | 1.000 | 0 |
| | dense-only | 14.1% | 25.4% | 32.8% | 0.204 | 0 |
| | naive-chunk | 5.5% | 10.9% | 13.8% | 0.084 | 0 |
| | **hybrid** | **100.0%** | **100.0%** | **100.0%** | **1.000** | 0 |
| **(b) description** (312) | keyword | 91.0% | 99.7% | 100.0% | 0.952 | 0 |
| | rule-based | 0.0% | 0.0% | 0.0% | 0.000 | 312 |
| | dense-only | 83.0% | 96.5% | 98.7% | 0.898 | 0 |
| | naive-chunk | 29.5% | 48.4% | 54.2% | 0.393 | 0 |
| | **hybrid** | **96.5%** | **99.7%** | **100.0%** | **0.981** | 0 |
| **(c) paraphrase** (312) | keyword | 68.9% | 89.7% | 93.9% | 0.792 | 0 |
| | rule-based | 0.0% | 0.0% | 0.0% | 0.000 | 312 |
| | dense-only | 65.4% | 89.1% | 94.6% | 0.775 | 0 |
| | naive-chunk | 27.2% | 47.1% | 57.4% | 0.383 | 0 |
| | **hybrid** | **80.1%** | **94.9%** | **97.8%** | **0.875** | 0 |
| **OVERALL** (935) | keyword | 86.6% | 96.5% | 98.0% | 0.914 | 0 |
| | rule-based | 33.3% | 33.3% | 33.3% | 0.333 | 624 |
| | dense-only | 54.2% | 70.4% | 75.4% | 0.626 | 0 |
| | naive-chunk | 20.7% | 35.5% | 41.8% | 0.287 | 0 |
| | **hybrid** | **92.2%** | **98.2%** | **99.3%** | **0.952** | 0 |

Gate v2 refused **none** of the 935 in-scope cases: hybrid with the gate off scores identically.

**Hybrid vs each baseline, per case** (win / tie / loss by reciprocal rank):

| baseline | (a) code | (b) description | (c) paraphrase |
|---|---|---|---|
| keyword | 0 / 311 / 0 | 21 / 286 / 5 | 73 / 217 / 22 |
| rule-based | 0 / 311 / 0 | 312 / 0 / 0 | 305 / 7 / 0 |
| dense-only | 267 / 44 / 0 | 51 / 259 / 2 | 73 / 222 / 17 |
| naive-chunk | 294 / 17 / 0 | 216 / 93 / 3 | 215 / 77 / 20 |

## 4. Comparative table — DEV (gold v2.2, 25 ranked queries)

| mode | method | Hit@1 | Hit@3 | Hit@5 | MRR | empty |
|---|---|---|---|---|---|---|
| **exact code** (6) | keyword | 100.0% | 100.0% | 100.0% | 1.000 | 0 |
| | rule-based | 100.0% | 100.0% | 100.0% | 1.000 | 0 |
| | dense-only | 16.7% | 50.0% | 50.0% | 0.306 | 0 |
| | naive-chunk | 0.0% | 33.3% | 50.0% | 0.200 | 0 |
| | **hybrid** | **100.0%** | **100.0%** | **100.0%** | **1.000** | 0 |
| **near-duplicate** (7) | keyword | 42.9% | 85.7% | 85.7% | 0.571 | 0 |
| | rule-based | 0.0% | 0.0% | 0.0% | 0.000 | 7 |
| | dense-only | 28.6% | 100.0% | 100.0% | 0.643 | 0 |
| | naive-chunk | 14.3% | 57.1% | 57.1% | 0.310 | 0 |
| | **hybrid** | **100.0%** | **100.0%** | **100.0%** | **1.000** | 0 |
| **symptom** (12) | keyword | 16.7% | 25.0% | 33.3% | 0.225 | 0 |
| | rule-based | 0.0% | 0.0% | 0.0% | 0.000 | 12 |
| | dense-only | 8.3% | 50.0% | 66.7% | 0.315 | 0 |
| | naive-chunk | 25.0% | 41.7% | 50.0% | 0.340 | 0 |
| | **hybrid** | **58.3%** | **83.3%** | **91.7%** | **0.711** | 0 |
| **OVERALL** (25) | keyword | 44.0% | 60.0% | 64.0% | 0.508 | 0 |
| | rule-based | 24.0% | 24.0% | 24.0% | 0.240 | 19 |
| | dense-only | 16.0% | 64.0% | 72.0% | 0.405 | 0 |
| | naive-chunk | 16.0% | 44.0% | 52.0% | 0.298 | 0 |
| | **hybrid** | **80.0%** | **92.0%** | **96.0%** | **0.861** | 0 |

The hybrid row reproduces the production DEV evaluation exactly (Phase 9.1b).

**Non-ranked DEV behaviour:**

| check | keyword | rule-based | dense-only | naive-chunk | hybrid |
|---|---|---|---|---|---|
| out-of-scope queries returning nothing (6) | 0/6 | 6/6 ¹ | 0/6 | 0/6 | **6/6** (gate v2) |
| complete subsystem list (3; groups of 14/14/18) | 0/3 ² | 0/3 | 0/3 ² | 0/3 ² | **3/3** |

¹ Only because it returns nothing for *any* non-code query, including all 19 in-scope
non-code DEV queries. That is not relevance judgement.
² A fixed top-5 ranker cannot return a group of 14–18 DTCs. Only the hybrid router has a
grouping mode.

**Hybrid vs each baseline on DEV** (win / tie / loss):

| baseline | exact code | near-duplicate | symptom |
|---|---|---|---|
| keyword | 0 / 6 / 0 | 4 / 3 / 0 | 9 / 2 / 1 |
| rule-based | 0 / 6 / 0 | 7 / 0 / 0 | 11 / 1 / 0 |
| dense-only | 5 / 1 / 0 | 5 / 2 / 0 | 8 / 3 / 1 |
| naive-chunk | 6 / 0 / 0 | 6 / 1 / 0 | 7 / 5 / 0 |

## 5. Where each method wins or ties

- **Exact code.** Keyword, rule-based and hybrid tie at 100%. A code is a unique token, and
  anything that indexes it verbatim finds it. Dense-only (14–17% hit@1) and naive-chunk (0–6%)
  fail: an embedding does not preserve the identity of `P0193-00` versus `P0194-00`.
  This is why the production router sends codes to a dictionary, never to embeddings.
- **Rule-based.** Perfect and instant for codes. It returns **nothing** for 624/935 auto-gen
  cases and 19/25 DEV queries: every description, paraphrase, near-duplicate phrasing and
  symptom. That is the limitation of a traditional code-lookup tool. It cannot help a
  technician who has a symptom but no code.
- **Keyword.** Strong on (b) descriptions (0.952), because the query *is* the manual's wording
  (§6). It is the best baseline on paraphrases (0.792). It beats hybrid on 5 descriptions and 22
  paraphrases, typically where RRF lets a dense near-neighbour outrank a lexically exact match,
  as with P0401-00 vs P0402-00 and P00C6-00 vs P0192-00. It collapses on DEV symptoms (0.225),
  where technician wording shares few words with the manual.
- **Dense-only.** Close to keyword on descriptions and paraphrases, better than keyword on DEV
  symptoms at hit@3/5, but poor at hit@1 on near-duplicates (28.6%). Records such as
  "short to battery" and "short to ground" of the same sensor embed almost identically. It puts
  the right record in the top 3 (100%) but cannot order siblings.
- **Naive-chunk.** The weakest method overall and on every auto-gen stratum; hybrid wins on
  725 of 935 auto-gen cases and loses on 23. Three effects compound:
  - boilerplate step text that repeats across hundreds of DTCs dominates many chunks;
  - chunks straddle DTC boundaries;
  - a DTC's identity (code + description) is one short line inside a 500-char window.

  One honest exception: on DEV symptoms, naive-chunk has the **best baseline hit@1 (25.0%)**,
  above dense-only (8.3%) and keyword (16.7%). Flat chunks include checkpoint and step wording
  ("check the fuel filter for clogging"), which the record embedding text deliberately
  excludes, and a few symptom queries match that wording. It still ranks far below hybrid
  (MRR 0.340 vs 0.711) and never beats hybrid on any DEV query.
- **Hybrid.**
  - Ties the best method on codes.
  - Best on every other stratum of both sets.
  - Wins decisively where discrimination matters: near-duplicates (1.000 vs ≤ 0.643) and
    symptoms (0.711 vs ≤ 0.340).
  - The only method that both lists subsystems completely and refuses out-of-scope queries for
    a relevance reason.

  Its losses are rank swaps between sibling DTCs (rank 2–3 instead of 1), not misses:
  hybrid hit@5 on paraphrases is 97.8%.

## 6. Reading these numbers honestly

1. **Auto-gen (a) and (b) are coverage tests.** (b) reuses the manual's exact wording, so BM25
   is structurally favoured, and every competent method scores ≥ 0.9 except naive-chunk. They
   show that each of the 314 records is reachable, not that the system understands technicians.
   (c) paraphrases are harder but still derived from the description, so they are not real
   technician language either.
2. **DEV is not held out for hybrid.** Phase 8 used DEV to develop the lexicon, gate and
   near-duplicate guardrails. Hybrid's DEV near-duplicate 1.000 and symptom 0.711 are therefore
   optimistic. The baselines have no tuned components, so on DEV they are, if anything, the
   fairer measurement.
3. **The discriminating held-out evidence is the Phase 8.5 one-shot TEST.** That run covered
   13 held-out symptom queries, but only for the production system and its ablations:

   | configuration (8.5 TEST, held out) | symptom hit@1 | symptom MRR |
   |---|---|---|
   | v1-phase7 | 23.1% | 0.291 |
   | conservative: TEST-matching lexicon entries and stoplist ablated | 23.1% | 0.368 |
   | adopted production | 53.8% | 0.628 |

   The held-out symptom performance to cite is therefore **0.368–0.628 MRR**, not DEV's 0.711.
   **The baselines were not run on TEST.** It is spent, and running five more methods on it
   would turn a one-shot evaluation into a tuning surface. So there is no held-out
   baseline-vs-hybrid symptom comparison. The hybrid-vs-baseline symptom gap above comes from
   DEV plus auto-generated paraphrases. The auto-generated paraphrases were not seen during
   development, but they are description-derived.
4. **The design claim that does survive these caveats:**
   - Structure (one record per DTC, plus a code dictionary) is what makes exact codes and
     near-duplicate siblings reliable.
   - Naive chunking loses to every structured method on codes, descriptions and paraphrases.
   - Neither lexical nor semantic ranking alone orders near-duplicate siblings well; the fusion
     does.

   Those results do not depend on the tuned lexicon: auto-gen (a)/(b) trigger it rarely
   (0 and 14 cases), and near-duplicate discrimination is a property of RRF over structured
   records.
5. **No human verification.** The auto-generated ground truth is the manual's own code ↔
   description pairing. It has not been checked by a technician; that is future work.
