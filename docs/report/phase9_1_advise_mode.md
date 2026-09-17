# Phase 9.1 — "Top-3 DTCs with Fix Steps" Advise Mode

**Additive.** No change to retrieval, the gate, the indexes or the records. The frozen TEST split was not used.

## Objective

A demo-ready answer mode: for any input, return **three** diagnostic trouble codes, each with its **complete fix procedure** rendered straight from the manual. The value is breadth: a technician sees the most likely code *and* its closest neighbours, rather than a single guess.

## Behaviour

| input | mode | the 3 results |
|---|---|---|
| contains a DTC code (`P0192-00`, or "my truck shows fault P0192-00…") | `dtc_code` | that code's record(s) first, then the nearest related codes until there are 3 |
| a natural-language symptom | `symptom` | the top-3 records from the production retriever (C4b hybrid) |
| grouping phrasing ("list all EGR faults") | `system_group` | the top-3 of the subsystem, ranked by dense similarity |
| out of scope ("capital of France", "warranty period…") | `refused` | none — gate v2 refuses, with its reason |

**Why refusal is kept, although the brief says "any input".** Returning three repair procedures for an unrelated question is exactly the fabrication the gate exists to stop. Symptom inputs therefore still pass through gate v2. An input containing a DTC code is in scope by definition and bypasses it. None of the four demo inputs is affected.

### "Nearest related codes"

The exact cosine similarity between the **stored record vectors** — record-to-record, not query-to-record — computed over the full matrix. Ties break by record id, so the order is deterministic. Records sharing a primary's code are excluded, so the second occurrence of a duplicated code is never reported as "related". Edge cases, both tested:

- **Duplicated code** `P0180-11` (pages 100 and 195): both occurrences are returned, then 1 related code (P0180-12).
- **Base code** `P0100`: its three suffix variants fill all three slots, so no related codes are added.

## The fix block

Rendered **deterministically from the record, with no model involved**. Each result carries both a structured block and its rendered text; the text comes from the same `answer.render_record` already used and tested for `/query`.

| field | content |
|---|---|
| `code_full`, `description`, `system` | identity |
| `effect`, `MIL` | effect on vehicle, lamp state |
| `cause[]`, `checkpoints[]` | from the Overview and Checkpoints sections |
| `steps[]` | `{n, text, spec, branch}` in manual order; `branch` is readable routing, e.g. `"if yes -> Step 12; if no -> Step 11"`, with `(inferred)` where polarity was not stated |
| `pins` | high-confidence, text-derived pins |
| `schematic_page`, `page`, `citation` | "see schematic, page N", and the manual page citation |
| `text` | the full human-readable block |

An **unconditional** jump is phrased "then go to Step N", never "if yes", because the manual poses no decision there.

**Optional LLM summary** (`--summary`, or `"summary": true` on the endpoint): one sentence per code, in a **separate** `llm_summary` field labelled *"LLM (Qwen2.5-0.5B), phrasing only - not a repair step"*. Off by default, and never mixed into the steps.

## Interfaces

**CLI**

```bash
PYTHONPATH=src .venv/bin/python src/advise.py "coolant gauge stuck at the bottom"
PYTHONPATH=src .venv/bin/python src/advise.py "P0192-00" --json
PYTHONPATH=src .venv/bin/python src/advise.py "P0192-00" --summary
```

**API** — `POST /advise`, body `{"input": "...", "summary": false}`:

```json
{"input": "...", "mode": "dtc_code|symptom|system_group|refused",
 "results": [{"rank": 1, "code_full": "P0340-00", "why_retrieved": "...", "fix_block": {...}}],
 "trace": {...}}
```

Verified live: the response keys match that shape exactly, and empty input returns HTTP 400.

### `why_retrieved`

Each result explains itself:

- **exact:** `DTC code P0192-00 matched in the code index (by_code_full)`
- **related:** `related to P0192-00: nearest record by embedding similarity (cosine 0.962), same system (rail_pressure)`
- **symptom:** `hybrid search rank 1: dense rank 2, keyword rank 1, RRF 0.032522; lexicon matched ['cam sensor']`

## Demo — the four required inputs

Full verbatim output (547 lines, all 12 fix blocks): [`phase9_1_demo_outputs.txt`](phase9_1_demo_outputs.txt).

| # | input | mode | #1 | #2 | #3 |
|---|---|---|---|---|---|
| 1 | `P0192-00` | dtc_code | **P0192-00** (13 steps) — exact | P0193-00 (13) — related, cos 0.962, same system | P0180-11 (9) — related, cos 0.826, different system |
| 2 | `my truck shows fault P0192-00, how do I fix it?` | dtc_code | **P0192-00** (13) | P0193-00 (13) | P0180-11 (9) |
| 3 | `coolant gauge stuck at the bottom` | symptom | P0116-00 (10 steps) | **P0117-00** (11) | P0119-00 (9) |
| 4 | `cam sensor gives no signal` | symptom | **P0340-00** (10) | P0341-00 (6) | P0336-00 (13) |

**All four return 3 distinct codes, each with a complete fix block** — with the data-quality exception in §Findings.

## Findings

### 1. A pre-existing parse defect — step text leaked into the Specifications column

The demo made **P0117-00** visibly wrong. In steps 1–6, words from the step text were split into the spec column:

```
Step 1: Check the battery              [spec: voltage]
Step 3: If connector found Step 11     [spec: lose in step 2 then fix is properly & go to]
```

Because the goto text was split, branches for steps 3–5 are also missing. This is a **Phase 1 column-boundary error**, not an advise-mode bug. Phase 1 validated P0117-00's step count and its page-13→14 stitch, but never which column each word landed in.

A corpus-wide scan for instruction words inside `specifications` flags 4 records / 26 steps:

| record | affected steps | assessment |
|---|---|---|
| **P0117-00** @p13 | 1–6 | broken (step 1's `voltage` not flagged by the scan) |
| **P00C6-00** @p86 | 1, 3–5, 7–13 | broken |
| **P0A1B-12** @p211 | 2–8, 11, 14 | broken |
| P1203-00 @p122 | 7 | probably a genuine expected-result spec (*"No continuity between Pin 1 to A01…"*) |

The scan is keyword-based and **a lower bound**. **Not fixed here:** re-parsing changes the records, and therefore the BM25 index, which 9.1 must not touch. Recommended as **Phase 9.2**: detect column-boundary failures from word geometry, re-parse the affected pages, validate against the PDF, and re-baseline on DEV.

### 2. "Related" means similar failure mode, not necessarily the same subsystem

For P0192-00 (rail pressure sensor **short to ground**), #2 is its sibling P0193-00 (cosine 0.962). But #3 is **P0180-11, a fuel-temperature sensor short to ground** (cosine 0.826), not the third rail-pressure code P0194-00 (*circuit drift*). Record embeddings weigh the failure mode as heavily as the component. That is defensible — a technician with a shorted sensor line benefits from seeing another shorted-sensor procedure — but it is a characteristic, not a guarantee of same-system neighbours. A same-system preference would be a one-line change if that is wanted.

### 3. Top-3 recovers answers that rank-1 misses

For *"coolant gauge stuck at the bottom"*, **P0117-00** (short to ground — the fault that pins a temperature gauge low) comes back at rank **2**. A single-answer mode would not have shown it.

### 4. Source-document defects stay visible

P0116-00 shows `9. Check DTC` twice and routes marked `-> Step 10 (inferred)`: the manual's own mis-numbering, flagged in Phase 3 and clamped by the diagnosis state machine. The fix block renders the record faithfully, and the `(inferred)` marker makes the uncertainty visible.

## Tests

`src/test_advise.py` is kept separate so the main suite's counts stay stable — **10/10 pass**:

- the 4 demo inputs: correct mode, 3 distinct codes, every fix-block field present, non-empty steps
- branch logic and citation preserved (P0192-00 step 10 → `if yes -> Step 12; if no -> Step 11`; page 8; schematic page 9)
- duplicated code `P0180-11` → both occurrences (pages 100 and 195), then P0180-12
- base code `P0100` → its 3 variants
- `capital of France` and `warranty period` → refused, no fix steps
- deterministic on repeat

**Main suite: 44 passed, 1 xfail, 0 failed** — unchanged.

## Artifacts

- `src/advise.py` — advise mode + CLI
- `app.py` — `POST /advise`
- `src/test_advise.py` — 10 tests
- `docs/report/phase9_1_demo_outputs.txt` — verbatim output of the four demos
