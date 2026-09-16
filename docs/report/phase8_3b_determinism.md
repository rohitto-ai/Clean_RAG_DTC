# Phase 8.3b — Deterministic Retrieval Before the One-Shot TEST

**Scope: DEV only. TEST not run.**

## Finding

Phase 8.3 showed that the same system gave different DEV results in different processes:
symptom MRR **0.7153** in one run and **0.7111** in the next. Phase 8.5 measures the frozen TEST
split **once**, so a non-reproducible ranker would make that single number unrepeatable.

Two independent sources of cross-process variation were in the ranking path:

1. **Approximate dense search.** The hybrid dense candidate pool (top-50) came from Chroma's
   HNSW index, which is approximate. For the same query it returned a different *set* of
   neighbours in different processes. This is the Phase 7 root cause, fixed then for the gate
   threshold but never for ranking.
2. **Hash-order tie resolution.** RRF iterated the candidate union as a Python `set` and sorted
   on `(rrf, tiebreak)` only. An exact double tie therefore inherited set iteration order,
   which for strings varies between processes (`PYTHONHASHSEED`). Found by reading the code
   while fixing (1); not observed on DEV, but a latent source of drift.

## Principle

This extends the Phase 7 rule. **Approximate ranking is acceptable for a live user; a
reported benchmark metric must be reproducible.**

## Fix — `src/retrieve.py`

- **Exact dense ranking.** `Retriever._exact_dense_topk()` ranks by an exact dot product over
  the stored matrix (`Retriever.vectors`, 314 × 384). It is the same exact computation the gate
  already used. It is used for the hybrid dense pool and for `system_group` ordering. Chroma
  stays as storage.
- **Canonical matrix order.** Vectors are loaded sorted by record id, so row order, and every
  tie resolution, is the same in every process.
- **Total ordering.** Dense ties break by record id; RRF iterates the union in sorted order and
  sorts on `(rrf, tiebreak, record_id)`.
- `exact_dense=True` is the default. `exact_dense=False` reproduces the old approximate
  behaviour and exists only for the comparison below.

## Proof — 3 separate processes, different hash seeds

`scripts/determinism_proof.py` runs the full DEV evaluation (C4b retrieval + gate v2) and
writes a **canonical JSON** of everything a reported metric depends on: every ranked query's
rank and top-5 list, every system_group result, every gate decision with its reasons, and all
aggregate metrics. The file's sha256 is printed. Each process ran with a different
`PYTHONHASHSEED`.

| path | process | PYTHONHASHSEED | sha256 (16) | symptom MRR | overall MRR |
|---|---|---|---|---|---|
| approximate (HNSW), before | p0 | 0 | `9cc0bc8c8cc5f489` | 0.7153 | 0.8633 |
| approximate (HNSW), before | p1 | 1 | `4029279a13cc0a60` | 0.7153 | 0.8633 |
| approximate (HNSW), before | p2 | 2 | `76b16c2b9ab8f9f2` | 0.7111 | 0.8613 |
| **exact, after** | p0 | 0 | **`76b16c2b9ab8f9f2`** | **0.7111** | **0.8613** |
| **exact, after** | p1 | 1 | **`76b16c2b9ab8f9f2`** | **0.7111** | **0.8613** |
| **exact, after** | p2 | 2 | **`76b16c2b9ab8f9f2`** | **0.7111** | **0.8613** |

**Before: three different hashes in three processes. After: one byte-identical hash in all
three, regardless of hash seed.**

Note that approximate runs p0 and p1 agree on MRR yet still hash differently: one of their
top-5 lists differs below the rank that MRR counts. A matching metric does not prove a
reproducible system.

The exact result is byte-identical to approximate run p2. HNSW returned the *true*
neighbours in that process and drifted from them in the other two.

### Which query stabilised

Only **d017** varied — *"the adblue reservoir is nearly empty and low warning is showing"*:

| run | rank of expected | top-5 |
|---|---|---|
| HNSW p0 | 4 | P206A-F1, P206A-F2, P204F-7C, P203F-00, P20F4-00 |
| HNSW p1 | 4 | P206A-F1, P206A-F2, P204F-7C, P203F-00, P0425-84 |
| HNSW p2 | 5 | P206A-F1, **P2BA9-00**, P206A-F2, P204F-7C, P203F-00 |
| **exact** | **5** | P206A-F1, **P2BA9-00**, P206A-F2, P204F-7C, P203F-00 |

The true #2 candidate, P2BA9-00, was missing from HNSW's pool in two of three processes. The
exact rank is 5. System-group results and all gate decisions were already stable under HNSW.

## The fixed DEV baseline — C4b + gate v2

| DEV | before (non-deterministic) | **after (deterministic)** |
|---|---|---|
| symptom hit@1 / hit@5 | 58.3% / 91.7% | **58.3% / 91.7%** |
| symptom MRR | 0.7111 **or** 0.7153 | **0.7111** |
| near-duplicate MRR | 1.000 | **1.000** |
| exact-code MRR | 1.000 | **1.000** |
| overall hit@1 | 80.0% | **80.0%** |
| overall MRR | 0.8613 **or** 0.8633 | **0.8613** |
| system_group complete | 3/3 | **3/3** |
| gate: out-of-scope refused | 6/6 | **6/6** |
| gate: in-scope passed | 28/28 | **28/28** |

**Correction to earlier reports:** C4 and C4b symptom MRR were reported as **0.715** (overall
0.863) in 8.2 and 8.2b. That figure was an approximate-search artefact. The true value is
**0.711** (overall **0.861**). The DEV lift over baseline is therefore 0.278 → **0.711**. The C0
baseline (0.278 / 0.603) is unchanged under exact ranking.

### Other checks

| check | result |
|---|---|
| Guardrails, C4b, exact ranking | **14/14** (C0 11/14, C4 12/14 — unchanged) |
| Full suite | **44 passed, 1 xfail, 0 failed** |
| DEV hit@k ranks, C0 / C4 / C4b | all re-recorded under exact ranking (`data/experiments/8_2/partB2_cylinder_token_dev.json`) |

## Production `index/` — no rebuild needed

This is a **query-path change only**. The embeddings live in `index/chroma/chroma.sqlite3`,
unmodified since the original build, and exact ranking reads them from there. Nothing needs
re-embedding or re-indexing, and `app.py`'s default retriever now ranks exactly.

**Latency:** a dense top-50 costs **9.5 ms** exactly vs **13.0 ms** through Chroma HNSW (mean
of 200 calls on the production index, query embedding included). At 314 records the exact path
is faster, and the reason HNSW exists — sub-linear search over large collections — does not
apply here.

**Observation (not proven as a cause):** Chroma rewrites its HNSW segment files
(`data_level0.bin`, `link_lists.bin`, …) whenever the collection is opened. Their timestamps
change even though no rebuild ran. That is a plausible contributor to the cross-process
differences in the approximate graph. It is no longer relevant to ranking, which does not read
those files.

## Artifacts

- `src/retrieve.py` — `_exact_dense_topk`, canonical matrix order, total RRF order, `exact_dense`
- `scripts/determinism_proof.py` — the canonical-JSON hashing proof
- `data/experiments/8_3b/dev_{hnsw,exact}_p{0,1,2}.json` — the six canonical outputs
- `data/experiments/8_3b/unstable_queries.json` — queries that varied under HNSW
- `data/experiments/8_3b/partB2_before_hnsw.json` — pre-fix C0/C4/C4b results, kept for audit

## Limitation

Determinism is proven on this box with fixed library versions (numpy, torch CPU,
sentence-transformers). A different BLAS build or CPU instruction set can change the last bits
of a float dot product. Should that break an exact tie differently, the record-id tiebreak keeps
the order total, but ranks could still differ **across machines**. **Re-run
`scripts/determinism_proof.py` on any machine used for the 8.5 TEST measurement** before
trusting a comparison with these DEV numbers.
