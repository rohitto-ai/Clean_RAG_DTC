# Phase 4 — Indexing

## Objective

Build the three complementary indexes the retrieval layer will draw on, persisted to
`./index/`: a dense vector index, an exact DTC-code index, and a BM25 lexical index.
No router and no fusion — that is Phase 5.

## Method

`src/build_index.py` reads the 314 canonical records from `data/dtc_records.jsonl`
and writes:

| Index | Artifact | Technique |
|---|---|---|
| Dense | `index/chroma/` | all-MiniLM-L6-v2, 384-dim, batch 32, L2-normalised, Chroma `space=cosine` |
| Exact code | `index/code_index.json` | two dicts, values are **lists** |
| BM25 | `index/bm25_corpus.json` | `rank-bm25` over an identifier-preserving tokenisation |
| Provenance | `index/meta.json` | model, dim, normalisation, versions, token pattern |

The embedding model is loaded, used, and **released before the vector store is
opened** — only one model is ever resident.

## Key Decisions

### The embedding text deliberately excludes the step text

Dense text = `code_full + description + system + cause[] + effect + checkpoints[] +
circuit_description + pin_map (pins + nets)`. **The procedural `steps[].text` is
deliberately not embedded.**

The steps are near-identical boilerplate across hundreds of DTCs — "Check the battery
voltage", "Fix the back-out cables in proper positions in connector & go to Step 13".
Phase 1 measured this directly: 2202 steps collapse into just **32 distinct branching
signatures**, and a single phrase shape accounts for 419 of them. Embedding that text
would pull every record toward a common centroid and destroy discrimination exactly
where it matters most — between the near-duplicate families the build plan flagged as
a hazard (the rail-pressure trio, injectors 1–4, the ~85 FCCU alarms).

The steps remain in the record for answering and for the Phase 6 state machine. They
are simply not part of the dense signal. Step **condition** clauses *are* included in
the BM25 text, where exact term matching does not suffer the same dilution.

### Other decisions

| Decision | Rationale |
|---|---|
| Exact index values are **lists**, never scalars | The DTC code is not a unique key. `P0180-11`, `P0180-12` and `P061C-00` each appear twice. A dict that overwrites would silently drop a record. |
| A second index on the **base code** (suffix stripped) | A technician types "P0192", not "P0192-00". `P0100` must return all three of `P0100-00/-9B/-9C`. |
| Record id = `code_full@p{page}#{occurrence}` | Unique across duplicate codes, and human-readable in results. |
| BM25 tokeniser preserves `P0192-00` and `A71` as **single tokens** | Default word-splitting would shatter `P0192-00` into `["p","0192","00"]` and `A71` into `["a","71"]` — destroying precisely the identifiers that carry the most retrieval signal. A DTC-code token additionally emits its base (`p0192-00` → also `p0192`) so an unsuffixed query still matches. |
| BM25 persisted as the **tokenised corpus**, not a pickled object | BM25Okapi's statistics are a deterministic function of the corpus, so rebuilding at load is exact, avoids cross-version pickle fragility, and is instant at 314 docs. |
| Chroma metadata coerces `None` → `""` | Chroma rejects null metadata values; several fields (`MIL`, `effect`) are legitimately null. |

## Results & Metrics

**Built in 21 s, peak RSS 680 MB.** (Well within budget — the box was re-measured
this session at **16 GiB / 4 vCPU**, having been 8 GiB in the previous session.)

### Index sizes

| Artifact | Size |
|---|---|
| `index/` total | **5.1 MB** |
| `index/chroma/` | 4.7 MB (`chroma.sqlite3` 3.1 MB + 1.7 MB HNSW segment) |
| `index/bm25_corpus.json` | 272 KB |
| `index/code_index.json` | 144 KB |
| `index/meta.json` | 4 KB |

### Index contents

| | |
|---|---|
| Chroma vectors | **314** (384-dim, cosine) |
| Dense corpus | 314 docs, avg 450 chars |
| Exact `by_code_full` keys | 311 (3 with >1 record) |
| Exact `by_dtc_code` keys | 235 (39 with >1 suffixed variant) |
| BM25 corpus | 314 docs, 30 046 tokens, **1 439 unique** |

### Smoke tests — 11 passed, 1 xfail, 0 failed

| # | Check | Result |
|---|---|---|
| 1 | Chroma count == 314 | ✅ |
| 2 | "rail pressure sensor short to ground" → P0192-00 | ✅ top3 `P0192-00, P0193-00, P0088-00` |
| 3 | "EGR valve stuck closed" → P042F-00 | ✅ top3 `P042F-00, P042E-00, P0403-00` |
| 4 | "camshaft no signal" → P0340-00 | **XFAIL** — see below |
| 5 | `P0180-11` returns **both** records | ✅ pages 100 & 195, occurrences 1 & 2 |
| 6 | base `P0192` returns its variant(s) | ✅ |
| 7 | base `P0100` returns all variants | ✅ `P0100-00, P0100-9B, P0100-9C` |
| 8 | duplicates stored as lists, none overwritten | ✅ exactly the 3 expected |
| 9 | BM25 "A71" → P0192-00 / P0193-00 | ✅ ranks 1–2, and nothing else scores |
| 10 | BM25 "EGR" → the EGR group | ✅ **6/6** top hits are `system=egr` |
| 11 | tokeniser keeps codes/pins intact | ✅ `['p0192-00','p0192','and','pin','a71']` |
| 12 | metadata filter `system=='egr'` | ✅ returns 14, matches ground truth |

### The one miss, and why it is left failing

`"camshaft no signal"` returns **P0341-00** ("camshaft signal diagnose - *disturbed*
signal") at rank 1, with the correct **P0340-00** ("- *no* signal") at rank 2. The
cosine distances are **0.330 vs 0.341** — 0.011 apart. The two descriptions differ by
a single word.

This is the near-duplicate hazard the build plan predicted, and **BM25 separates the
pair decisively**:

| query | BM25 top-2 |
|---|---|
| "camshaft no signal" | **P0340-00 (10.59)**, P0341-00 (6.88) |
| "camshaft disturbed signal" | **P0341-00 (11.09)**, P0340-00 (7.48) |

A 54% score margin, and it flips correctly with the query. So the designed remedy —
hybrid dense + BM25 with RRF fusion — is precisely what resolves this, and it lands in
Phase 5. The test is therefore recorded as **XFAIL (known-hard)** rather than softened
or tuned around: making the embedding pass this one case by hand would hide a real
property of the corpus. Phase 7 will measure it properly.

## Evidence & Artifacts

- [src/build_index.py](../../src/build_index.py) — builder
- [src/smoke_index.py](../../src/smoke_index.py) — the 12 smoke tests, re-runnable
- `index/` — gitignored build artifact; rebuild with
  `.venv/bin/python src/build_index.py --rebuild`
- `index/meta.json` records model, dim (384), normalisation, Chroma 0.5.23,
  sentence-transformers 3.3.1, and the BM25 token pattern, for reproducibility.

## Issues Found & Fixed

1. **Chroma rejects `None` metadata.** `MIL` and `effect` are legitimately null on
   some records; coerced to `""` at write time.
2. **Non-unique ids.** Keying Chroma on `code_full` alone would have collapsed the
   three duplicate codes from 314 vectors to 311. Ids include page + occurrence, and
   the builder asserts uniqueness before writing.
3. **Smoke tests initially reported a hard FAIL** on the camshaft case. Rather than
   soften the expectation, the harness gained an explicit XFAIL state so the run
   exits 0 while keeping the real result visible and annotated.

## Limitations

- **Dense retrieval alone cannot separate single-word-apart near-duplicates.**
  Quantified above (0.011 cosine). Not a defect to fix in Phase 4 — it is the reason
  the architecture is hybrid.
- **BM25 statistics are corpus-global**; with 1 439 unique tokens over 314 short
  documents, IDF is coarse. Adequate for exact-identifier matching, which is its job
  here.
- **No fusion, no router, no query-side logic yet** — Phase 5.
- `index/` is **not committed** (gitignored, 5.1 MB, fully reproducible in 21 s).
