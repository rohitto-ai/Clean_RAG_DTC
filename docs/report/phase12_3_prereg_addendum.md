# Phase 12.3 — addendum to the Round-3 pre-registration

_Written and committed **before** `data/eval/gold_r3.json` exists. Branch `phase12-symptom-bridge`.
The original pre-registration (`docs/report/phase12_3_prereg.md`, commit `e8b5c7d`) is **not edited**;
this document adds to it. Where the two touch the same subject, this addendum is the stricter one
and governs._

## 1. Blindness, stated precisely

The original prereg said the gold file "is opened for the first time by the single scoring run".
That was too loose to be useful, because somebody obviously has to read the queries in order to
label them. The actual requirement is narrower and is about **output**, not about text:

- The labeller **does** read each query in order to assign its `expected` codes, and uses the manual
  to do so. That is the job, and it is not a breach of blindness.
- The labeller — and everyone else — **never sees any system output for any Round-3 query** before
  the single scoring run: no ranked list, no retrieved record, no score, no gate verdict, for any of
  the three configurations.
- **Nobody runs retrieval on a Round-3 query before the scoring run.** Not to sanity-check a label,
  not to see whether a query is "too hard", not through the demo website, not through `/symptom`,
  not through the CLI.
- It follows that no Round-3 query may be edited in response to how the system behaves on it, since
  nobody will have seen how the system behaves on it. Labels may be corrected against the **manual**
  at any time before delivery; they may never be corrected against **output**.

The practical test: if a query or a label changed because of something a retriever printed, Round 3
is spent and must be reported as such.

## 2. Eligibility, checked before scoring

`scripts/eval_12_3.py` runs these three checks **before** any query is scored, and **aborts** on
failure. They exist because a set that fails them cannot answer the question Round 3 is for.

### (i) Query overlap with the manual's own vocabulary — abort if mean > 0.15

Measured with the **Phase 8 function and ceiling**, imported unchanged from `src/gold_overlap.py`:
`overlap(query, expected, desc) = |content(query) ∩ content(description)| / |content(query)|`, taken
as the max over the query's expected codes, with the Phase 8 content/stemming rules and
`CEILING = 0.15`.

The check is on the **mean** over the scored symptom rows, as specified. A set whose queries reuse
the manual's nouns is matched trivially by BM25 and stops measuring technician language, which is
the only thing Round 3 is for. Per-row maximum, the count over ceiling, and the worst offenders are
**reported** for transparency but do not themselves abort — the mean is the pre-registered criterion.

### (ii) Near-paraphrases of already-spent queries — excluded and reported

Every Round-3 query is embedded with MiniLM (`all-MiniLM-L6-v2`, the production embedder) and
compared against every query in the two spent sets, `data/gold_independent.json` (Round 1) and
`data/gold_r2_colleague.json` (R2). Any row reaching **cosine ≥ 0.85** against any of them is
**excluded from scoring and listed in the results** with its nearest match and that match's score.

Exclusion, not abort: one recycled query does not spoil a set, but it is not new language either,
and leaving it in would let an already-measured query be counted as independent evidence. If the
exclusions leave **no symptom rows**, that *is* an abort — there is nothing left to measure.

**Order of operations:** exclusions are applied **first**, and the overlap mean in (i) is then
computed on exactly the rows that will be scored. The mean over all delivered rows is also reported,
so the effect of the exclusions on that number is visible rather than hidden.

### (iii) Provenance — abort unless it names the author and disclaims AI authorship

The `provenance` string must state **both**:

1. **who wrote the queries** — matched by `written by <name>`, `authored by <name>` or
   `composed by <name>`; and
2. **that no AI tool was used to write them** — matched by a phrase such as `no AI tool was used`,
   `no AI tools were used`, `without AI assistance`, `no LLM was used`, or `no generative AI`.

A conforming example: *"Written by A. Mehta, workshop foreman, from his own service experience; no
AI tool was used to write or reword any query."*

This is a check on the **claim**, and the evaluator says so in its output. No program can verify how
a sentence was produced; what the check guarantees is that the claim was made explicitly by a named
person, and is therefore on the record, falsifiable, and attributable. A set delivered without that
claim is not scored.

## 3. What this addendum does not change

The three configurations, the data contract, the metrics, the paired-bootstrap parameters
(10,000 resamples, seed 0, shared indices, 2.5/97.5), the permitted verdicts
(**replicated** / **confirmed** / **not replicated**), the one-run rule, and the statement that
**no adoption decision follows from this run** are all unchanged from `phase12_3_prereg.md`.

The eligibility checks are gates on the **input**, not on the result: they can stop Round 3 from
being scored, and they can exclude rows, but no outcome of this run may be reinterpreted because of
them after the fact.
