# Phase 6 — Answering & Conversational Diagnosis

## Objective

Turn retrieved records into answers, and walk a DTC's branching steps as an
interactive diagnosis — under one design law: **the LLM does phrasing only. Every
fact and every route is deterministic and grounded in the retrieved record.**

## Method

- `src/answer.py` — a **fast path** (no LLM) for `exact_code` and `system_group`,
  rendering a templated answer from structured fields; and an **LLM path** for
  hybrid symptom queries, using Qwen2.5-0.5B-Instruct Q4_K_M via llama-cpp-python.
- `src/diagnose.py` — a deterministic state machine over `steps[]`. It imports no
  model and consults none. Transitions are computed from `on_true`/`on_false`/`goto`.

## Key Decisions

### The LLM is never trusted with a decision — including "is this covered?"

The first build handed the model the scope decision via a prompt rule ("if the
CONTEXT does not contain the answer, say it is not covered"). Qwen2.5-0.5B failed
it **in both directions**:

- Asked *"how do I change a tyre"* with irrelevant DTC context, it produced
  confident fabricated instructions — including an invented tyre pressure
  *"typically between 30-40 psi for a 3.3L NGE BSVI engine."*
- Asked a **valid** rail-pressure symptom question, it wrongly refused.

Deciding whether the manual covers a question is a **routing** decision, so under
the design law it must be deterministic. `is_relevant()` gates on the retrieval
signal before the model is consulted at all. The separation is wide and measured:

| | dense_sim | bm25_max |
|---|---|---|
| in-scope queries (6 measured) | 0.44 – 0.69 | 10.0 – 17.0 |
| out-of-scope queries (5 measured) | 0.05 – 0.21 | 0.0 – 5.8 |
| **thresholds** | **≥ 0.30** | **or ≥ 8.0** |

Out-of-scope queries now never reach the model. This is the single most important
guard in the phase: a fabricated repair instruction is worse than no answer.

### Other decisions

| Decision | Rationale |
|---|---|
| Fast path renders **before** any model exists | `exact_code` is the primary technician workflow and needs no generation. It is instant, and it *cannot* hallucinate. |
| The model sees **only** `build_context()` — description, system, effect, MIL, causes, checkpoints, circuit description, pins | No step text, no page numbers to paraphrase, no outside context. Citations are attached deterministically from the records, not parsed out of the model's output. |
| `temperature=0.0` | Reproducible phrasing. |
| An unconditional jump is not a question | A step with a target but no condition ("Fix the back-out cables … & go to Step 13") is an instruction. Asking yes/no there would invent a decision the manual never poses. Rendering says "then go to Step 13", not "if yes". |

### Handling three source-data defects in the state machine

| Defect | Count | Handling |
|---|---|---|
| `on_true`/`goto` target outside the step list | 37 | **Clamped to the terminal step**, each clamp logged in the trace |
| `on_false` null (no explicit else) | all but 5 steps | **Fall through to n+1** — the document's own default |
| Self-referencing goto / any cycle | 4 + guard | Visited-set **loop guard** + `MAX_STEPS=64` cap; treated as terminal |
| Multi-target goto ("go to Step 9 & 11") | 6 | **Sequenced, not branched** — queued via `state.pending` |

### The inference I had to add, and why

Plain fall-through produced a walk in which **P0192-00 steps 9–12 are unreachable**.
The cause: step 7 says *"…if yes go to Step **8**"* — its true target **is** the next
step. So "yes" and "no" both land on step 8, making the manual's own condition a
no-op.

This is not a one-off: **256 conditional steps (24% of all 1047) have
`on_true == n+1`.**

So the false branch **skips the step the true branch occupies** (`n+2`). This is the
only reading under which the stated condition has any effect. It is an *inference*,
not stated text, so it is logged in the trace as `skip_true_branch` exactly like a
clamp — visible, auditable, and never silent.

## Results & Metrics

**All 9 Phase-6 acceptance tests pass. Suite total: 30 passed, 1 xfail, 0 failed.**
Peak RSS 1116 MB (model + index + records all resident).

| # | Acceptance test | Result |
|---|---|---|
| 1 | P0192-00 deterministic answer renders all sections, cites page 8 | ✅ 2293 chars |
| 2 | exact_code uses the fast path, **no LLM called** | ✅ `path=deterministic`, cites (P0192-00, 8) |
| 3 | Walk: continuity OK at step 10 → step 12 | ✅ `[1,2,3,4,5,6,7,9,10,12,13]` |
| 4 | Walk: continuity NOT ok at step 10 → step 11 | ✅ `[1,2,3,4,5,6,7,9,10,11,12,13]` |
| 5 | Both branches reach terminal "Check DTC" | ✅ step 13 |
| 6 | Out-of-range target clamps to terminal + logs | ✅ P0116-00 step 3 requested **10** → clamped to **9** |
| 7 | Synthetic cycle terminates via loop guard | ✅ visited `[1,2]`, "Loop detected" |
| 8 | Symptom query → LLM cites a correct DTC | ✅ P0088-00 / P0087-00 / P0194-00 |
| 9 | Out-of-scope → honest "not covered", no fabricated DTC | ✅ `deterministic_gate`, dense 0.0597 |

### LLM benchmark — Qwen2.5-0.5B-Instruct Q4_K_M, 4 vCPU, CPU-only

| Metric | Value |
|---|---|
| Model file | 491 MB (Q4_K_M) |
| **Load time** | **0.32 s** |
| **Throughput** | **16.3 tokens/sec** |
| Typical answer | 148 tokens in 9.07 s |
| Prompt size | ~590–680 tokens (3 records of context) |
| `n_ctx` / `n_threads` | 2048 / 4 |

### Is Qwen2.5-1.5B worth it? (noting only — not switched)

**Phrasing at 0.5B is serviceable but weak.** It cites correctly and stays inside the
context, but it rambles and pads with near-tautologies — *"The DTC also mentions that
the system is coolant, and the effect on the vehicle is NA."*

The trade: 1.5B is ~3× the compute, so expect **~5–6 tok/s and ~30 s per answer** on
these 4 vCPUs, versus 9 s now. RAM is no longer the constraint (the box is 16 GiB).

My read: **not clearly worth it yet.** The fast path already handles the primary
exact-DTC workflow with zero generation, and the relevance gate — not the model —
is what prevents fabrication. A 3× latency hit buys better prose on the secondary
path only. Worth benchmarking before adopting; your call.

## Evidence & Artifacts

- [src/answer.py](../../src/answer.py), [src/diagnose.py](../../src/diagnose.py)
- [src/smoke_index.py](../../src/smoke_index.py) §7 — the 9 acceptance tests
- `models/qwen2.5-0.5b-instruct-q4_k_m.gguf` — gitignored; re-download:
  ```bash
  .venv/bin/python -c "from huggingface_hub import hf_hub_download; \
    hf_hub_download('Qwen/Qwen2.5-0.5B-Instruct-GGUF', \
    'qwen2.5-0.5b-instruct-q4_k_m.gguf', local_dir='models')"
  ```

## Issues Found & Fixed

1. **Model fabricated an out-of-scope answer.** Fixed with the deterministic
   relevance gate (above), not a prompt tweak.
2. **Model wrongly refused a valid query.** Same root cause — the scope decision was
   delegated. The prompt now states the context is pre-checked and keeps refusal only
   as a backstop.
3. **Unconditional jumps were being posed as yes/no questions**, letting a "no"
   answer skip a mandatory instruction. `needs_answer()` now keys on `condition`.
4. **Steps 9–12 of P0192-00 were unreachable** — the `on_true == n+1` problem above.
   Fixed with the logged `skip_true_branch` inference.

## Limitations

- **`skip_true_branch` is an inference**, applied to 24% of conditional steps. It is
  logged on every use, but it is a reading of the manual's intent, not its text. If
  it proves wrong on some DTC, the trace will show exactly where.
- **Clamping assumes the terminal step is the intended target.** True for 20/20
  affected records (all end in "Check DTC"), but it is an assumption.
- **0.5B phrasing quality is modest** — see the benchmark note.
- **No FastAPI service yet.** `answer()` and `Diagnoser` are libraries; the
  `/ingest` and `/query` endpoints are still to be wired.
- **Diagnosis is not yet driven by retrieval** — `Diagnoser` takes a record; joining
  "symptom query → pick DTC → walk it" into one conversation is a UI concern.
- Retrieval quality is still only spot-checked; **hit@k / MRR over a gold set is
  Phase 7**.
