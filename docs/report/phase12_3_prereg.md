# Phase 12.3 — pre-registration of the Round-3 one-shot check

_Written and committed **before** `data/eval/gold_r3.json` exists. Branch `phase12-symptom-bridge`,
from `8e5d222`. Production unchanged; nothing inside the 12.1, 12.2 or 11.2 freezes is touched._

## Why this document exists first

Phase 12.2 produced a result that cannot be settled with the data this project holds. The authored
symptom expansions (`v2_half`) **regress** development retrieval — DEV symptom MRR 0.7111 → 0.5208,
hit@1 0.583 → 0.250 — yet **improve** both spent independent sets: Round-1 MRR +0.0496 and R2
+0.1167. Both post-hoc confidence intervals include zero, and on Round-1 exactly as many queries
got worse as got better (8 and 8). Every evaluation set this project owns is now spent, so the
question "is the post-hoc gain real?" cannot be answered without new, unseen language.

Round 3 is that new language. Because the 12.2 post-hoc numbers are already known, there is an
obvious way to fool ourselves: run the comparison, dislike the answer, adjust something, run it
again. This document removes that option by fixing the configurations, the metrics and the
permitted conclusions **before** a single Round-3 query is visible.

## 1. Configurations — frozen here, not chosen later

Exactly three, and no others. No knob outside this table may be set.

| | config | how it is constructed | provenance |
|---|---|---|---|
| **a** | **production** | `Retriever()` on `index/` with the default gate (`answer.default_gate()`); `subsystem_prior = 0.0`, `exact_dense = True`, lexicon/expansion at their production defaults | the system preserved as tag **`v3-final-eval`** |
| **b** | **12.2 `v2_half`** | `WeightedSymptomRetriever(index_dir="index_exp/minilm_sympexp_v2", symptom_weight=0.5)`, same gate as (a) | `data/experiments/12_2/freeze.json`, `chosen_variant: "v2_half"` |
| **c** | **production + A-narrow** | config (a), with `no_dtc_narrow` consulted in front of retrieval — **`no_dtc` rows only** | `data/experiments/11_2/freeze.json` |

**On (a) and the tag.** `src/retrieve.py` at `HEAD` is *not* byte-identical to `v3-final-eval`: Phase
11.1 added the function `detect_systems` and the constructor argument `subsystem_prior`. Both are
inert at their defaults — `detect_systems` is called by nothing on the production path and
`subsystem_prior` defaults to `0.0` — so config (a) is **behaviourally** the tagged system. The
evaluator asserts this rather than trusting it: it checks `subsystem_prior == 0.0` and requires the
DEV determinism hash **`ffff9bc707d8754d`**, the value recorded for the tag, before it will score
anything.

**On (b) and the freeze.** The evaluator recomputes the sha256 of every artefact listed in
`data/experiments/12_2/freeze.json` and **refuses to run** if any has changed. The expansions remain
index-only: matched against, never returned, never cited.

**On (c) and its scope.** A-narrow is a refusal rule, so it can only affect rows where refusing is
the right answer or the feared mistake. It is therefore applied to **`no_dtc` rows only**, and
configs (a) and (b) are the only ones scored on symptom rows. (c) contributes no symptom metric and
takes no part in the (b − a) comparison.

## 2. Data

- **File:** `data/eval/gold_r3.json`, delivered later by a colleague. It does not exist at this
  commit and is not created by this phase.
- **Schema:** identical to `data/gold_r2_colleague.json` — top level `version`, `created`,
  `provenance`, `queries`; each query carries `id`, `query`, `mode`, `expected` (list), `notes`,
  `split`. The evaluator validates the schema and **stops** on any mismatch rather than coercing it.
- **Modes scored:** `symptom` (retrieval metrics) and `no_dtc` (decline metrics). Any other mode —
  R2 contained one `inconclusive` row — is **counted and reported but not scored**, under either
  metric.
- **Scoring: lenient**, as in Round 1. A query is correct at rank *i* if the code at rank *i* is in
  that query's `expected` list; any acceptable code counts, and `expected` may hold more than one.
- **Depth:** top **5** codes per query, de-duplicated by `code_full`, as production returns them.
- **Blindness:** the file is opened for the first time by the single scoring run. Nobody reads,
  inspects or summarises its queries beforehand.

## 3. Metrics — fixed here

On **`symptom`** rows, for configs (a) and (b):

- **Hit@1, Hit@3, Hit@5** and **MRR** (a query the system declines, or that returns no acceptable
  code in the top 5, contributes reciprocal rank 0).
- **Paired comparison (b − a) of MRR:** a paired bootstrap, **10,000 resamples**, **seed 0**,
  resampled query indices **shared** between the two configs, percentile interval at **2.5 / 97.5**.
- **Per-query counts:** how many queries **better**, how many **worse**, how many **tied** under (b)
  against (a), by reciprocal rank.

On **`no_dtc`** rows, for configs (a), (b) and (c):

- **declines** — rows where the system returns no codes. On a `no_dtc` row this is the correct
  behaviour.
- **false declines** — rows on which the system declines but should not have: any **`symptom`** row
  that is declined. Reported per config, with the query ids.

Also recorded, for the record and not as a success criterion: latency p50/p95, the decline reasons,
and for (c) how many `no_dtc` rows received an advisory without a decline.

## 4. The only conclusions this run may draw

Let **Δ** be the mean (b − a) difference in symptom MRR.

| verdict | condition — both parts required |
|---|---|
| **"replicated"** | Δ **> 0** *and* **better > worse** on the per-query counts |
| **"confirmed"** | the paired bootstrap CI **excludes 0** (in addition to "replicated") |
| **"not replicated"** | anything else — including Δ > 0 with better ≤ worse, and any Δ ≤ 0 |

A one-sided improvement in Hit@5 alone, or a gain that rests on magnitude while more queries get
worse than better, is **"not replicated"**. That is deliberate: it is precisely the pattern 12.2
produced, and this run exists to test it, not to re-describe it.

**No adoption decision follows from this run, whatever it says.** A "confirmed" result would make
`v2_half` a candidate for a later, separate adoption phase with its own gate — nothing more.
Production stays as it is in this phase regardless of the outcome.

## 5. One run, and what stops a second

- The evaluator writes `data/experiments/12_3/r3_results.json` and **refuses to run again** if that
  file already exists. Re-running requires deleting a committed result, which is visible in git.
- No configuration may change after the gold file arrives. The three configs in §1 are fixed by this
  commit; the frozen-artefact sha256 check and the determinism-hash check enforce the parts of that
  which code can enforce.
- If the run reveals a **bug** rather than a disappointing result, the honest remedy is to say so in
  the report, keep the spoiled run on the record, and treat Round 3 as spent. A corrected re-run on
  the same file would no longer be a one-shot test, and must not be presented as one.
- Dry-running the evaluator on a **dummy** file is expected and allowed, because it touches no gold
  data: `data/demo/gold_r3_dummy.json` (3 synthetic rows, `synthetic - illustrative`, gitignored).

## 6. What would make this run uninformative

Stated in advance so it cannot be used as an excuse afterwards:

- **n.** R2 held 15 symptom rows. At that size the paired CI will be wide and "confirmed" is
  unlikely on any effect this project has yet measured. "Not replicated" at small n means *not
  demonstrated*, not *disproven*.
- **62 records carry no symptom expansion** (56 of them the `EMM alarm FCCUnn` ECU-internal faults).
  If Round 3 happens to target those, (b) cannot differ from (a) and the comparison is empty for
  those rows.
- **Lenient scoring** makes both configs look better than strict scoring would; it is used only
  because Round 1 used it, so the numbers remain comparable.

## Files

| file | role |
|---|---|
| `docs/report/phase12_3_prereg.md` | this pre-registration — committed before any Round-3 file exists |
| `scripts/eval_12_3.py` | the implementation; `--dry-run` for the dummy file, `--run` for the single scoring run |
| `data/experiments/12_3/r3_results.json` | written once by the scoring run; its existence blocks a second |
