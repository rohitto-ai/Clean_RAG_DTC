# Phase 5 — Retrieval: Router + RRF Fusion

## Objective

Serve all four query modes over the three Phase-4 indexes with a priority-ordered
router and Reciprocal Rank Fusion, returning **full DTC records** plus a trace that
explains why each result surfaced. No LLM — that is Phase 6.

## Method

`src/retrieve.py` exposes `Retriever.retrieve(query, k=5)` →
`{mode, results, trace}`. The router inspects the query and dispatches:

| Priority | Mode | Trigger | Behaviour |
|---|---|---|---|
| 1 | `exact_code` | a DTC code matches `[PUBC]\d[0-9A-F]{2,3}(-[0-9A-F]{2})?` | full code → `by_code_full`; base only → `by_dtc_code` (all suffix variants). Returns a **list**. |
| 2 | `system_group` | grouping intent **AND** a subsystem keyword | Chroma metadata filter on `system`, ranked by dense cosine within the filter. Returns the whole group. |
| 3 | `hybrid` | everything else | dense top-50 + BM25 top-50, fused with RRF. |

The embedding model is loaded once in the constructor and stays resident for the
service lifetime — this is the query path, not a batch pass.

## Key Decisions

### Router priority, and why a subsystem keyword is not a filter

A DTC code is the least ambiguous signal a technician can give, so it pre-empts
everything. Crucially it does **not** collapse duplicates: `P0180-11` legitimately
returns two records and `P0100` returns three suffix variants. Those are answers, not
errors.

The distinction that actually matters is priority 2 vs 3. A subsystem keyword alone
is **not** enough to filter, because grouping intent and fault-specific intent share
vocabulary:

- `"list all EGR faults"` → grouping intent + `egr` → **system_group**, 14 records.
- `"EGR valve stuck closed"` → `egr` but no grouping intent → **hybrid**, returns
  `P042F-00` at rank 1.

Hard-filtering on the keyword would turn the second query into a 14-record dump and
bury the specific answer. So on the hybrid path the detected subsystem is recorded in
the trace as a **soft signal only** and never constrains the candidate pool.

### Tie-breaking: equal-weight RRF cannot break a symmetric rank swap

This is the substantive finding of the phase, and it directly governs the acceptance
case.

RRF scores a document as `Σ 1/(k + rank)`. If two documents **exchange ranks 1 and 2**
between the two rankers, their scores are `1/(k+1) + 1/(k+2)` and
`1/(k+2) + 1/(k+1)` — **identical by construction, for every k**:

| k | P0340-00 | P0341-00 |
|---|---|---|
| 1 | 0.83333333 | 0.83333333 |
| 10 | 0.17424242 | 0.17424242 |
| **60** | **0.03252247** | **0.03252247** |
| 1000 | 0.00199700 | 0.00199700 |

No choice of `k` helps; the tie is structural. Left unbroken, the winner would be
whatever order the set happened to iterate in — arbitrary, and unstable across runs.

Ranking discards magnitude, so the fix is to restore it **only when RRF ties**:
break by the **summed min-max-normalised score from each ranker**. In this case dense
is 0.011 cosine apart (noise) while BM25 is 54% apart (decisive), so the confident
ranker wins:

```
P0340-00  rrf 0.032522  dense_rank 2  bm25_rank 1  tiebreak 1.9742
P0341-00  rrf 0.032522  dense_rank 1  bm25_rank 2  tiebreak 1.6318
```

Equal-weight RRF at `k=60` remains the primary ordering exactly as specified; the
tiebreak is a secondary sort key that fires only on exact ties.

### Other decisions

| Decision | Rationale |
|---|---|
| `exact_code` and `system_group` ignore `k` | Both are *complete-answer* modes. Truncating "all EGR faults" to 5 would be wrong. |
| Absence from a ranker contributes **nothing** (not a penalty) | Standard RRF. A document strong in one ranker still competes. |
| `RRF_K=60`, `POOL_SIZE=50`, `DEFAULT_TOP_K=5` as module constants | Tunable in one place for Phase 7 sweeps. |
| Trace carries `fused_top` with per-ranker ranks and the tiebreak value | Any result can be explained without re-running retrieval. |

## Results & Metrics

**All 9 Phase-5 acceptance tests pass. Suite total: 20 passed, 1 xfail, 0 failed.**
Peak RSS 546 MB.

| # | Acceptance test | Result |
|---|---|---|
| 1 | **[was Phase-4 XFAIL]** "camshaft no signal" → P0340-00 rank 1 | ✅ |
| 2 | "camshaft disturbed signal" → P0341-00 rank 1 | ✅ top3 `P0341-00, P0340-00, P0336-00` |
| 3 | "how do I fix P0192-00" → `exact_code`, returns P0192-00 | ✅ |
| 4 | "P0180-11" → **both** duplicate records | ✅ pages 100 & 195 |
| 5 | "P0100" → all 3 suffix variants | ✅ `P0100-00, -9B, -9C` |
| 6 | "list all EGR faults" → `system_group`, 14 records | ✅ |
| 7 | "EGR valve stuck closed" → `hybrid`, P042F-00 in top-3 | ✅ rank 1; top3 `P042F-00, P042E-00, P0405-00` |
| 8 | "rail pressure sensor short to ground" → P0192-00 rank 1 | ✅ |
| 9 | code-free symptom query → sane top-5 | ✅ |

### The camshaft flip, before and after

| | dense-only (Phase 4) | hybrid + RRF (Phase 5) |
|---|---|---|
| **"camshaft no signal"** | ❌ P0341-00 @1, P0340-00 @2 (0.330 vs 0.341 cosine) | ✅ **P0340-00 @1**, P0341-00 @2 |
| **"camshaft disturbed signal"** | — | ✅ **P0341-00 @1**, P0340-00 @2 |

The pair flips correctly with the query wording, which is the real test: it is not
that P0340-00 was pinned to the top, but that the ranking *responds* to "no" vs
"disturbed" — the single word that distinguishes the two DTCs. Dense alone could not
(0.011 apart); BM25 supplies the discrimination and fusion carries it through.

### Code-free symptom query — eyeball

`"torque reduction, MIL on, low rail pressure"` → `hybrid`:

| # | code | system | effect | dense | bm25 |
|---|---|---|---|---|---|
| 1 | P0088-00 | rail_pressure | NA | 1 | 4 |
| 2 | P0192-00 | rail_pressure | **Torque reduction** | 3 | 2 |
| 3 | P0194-00 | rail_pressure | **Torque reduction** | 5 | 1 |
| 4 | P0087-00 | rail_pressure | NA | 2 | 6 |
| 5 | P0193-00 | rail_pressure | **Torque reduction** | 6 | 3 |

All five are rail-pressure faults and three carry exactly the stated effect. Note
every result draws on *both* rankers — the fusion is doing real work here, not
deferring to one side.

## Evidence & Artifacts

- [src/retrieve.py](../../src/retrieve.py) — router, RRF, trace
- [src/smoke_index.py](../../src/smoke_index.py) §6 — the 9 acceptance tests
- CLI for ad-hoc checks:
  `PYTHONPATH=src .venv/bin/python src/retrieve.py camshaft no signal`

## Issues Found & Fixed

1. **The RRF tie described above.** Found by computing the acceptance case by hand
   *before* writing the router, rather than discovering it as a flaky test. Fixed
   with the documented tiebreak; the trace exposes both the tie and its resolution.
2. **`k` must not truncate complete-answer modes.** An early cut of `system_group`
   returned 5 of 14 EGR records. Both `exact_code` and `system_group` now ignore `k`.
3. **Grouping intent needs a subsystem too.** Intent alone ("list all faults") has no
   group to return, so both conditions are required before leaving the hybrid path.

## Limitations

- **Grouping intent is regex-detected**, so phrasings outside the pattern
  (`all|list|every|each|related to|what/which … faults`) fall through to hybrid. That
  fails safe — the user still gets relevant records, just ranked rather than grouped.
- **The subsystem keyword map is hand-built** (19 systems) and query-side only. An
  unlisted synonym degrades to hybrid, which again fails safe.
- **The DTC-code regex can in principle match a non-code token** of the shape
  `[PUBC]\d[0-9A-F]{2,3}`. In practice a miss returns "no match in either code
  index" in the trace rather than wrong results, but a query mentioning a connector
  ID such as `C001` would route to `exact_code` and find nothing. Phase 7 should add
  a fallback: if `exact_code` yields zero matches, re-run as hybrid.
- **Retrieval quality is only spot-checked here**; hit@k / MRR over a ~30-query gold
  set is Phase 7's job.
- The tiebreak's min-max normalisation is computed **within the candidate pool**, so
  it is a relative signal, not a calibrated confidence.
