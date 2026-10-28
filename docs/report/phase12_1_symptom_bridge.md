# Phase 12.1 — Symptom-side document expansion (doc2query): a negative result

_2026-10-28 · branch `phase12-symptom-bridge` · **rejected by the no-regression gate; nothing adopted, no variant promoted**_

## Objective

Phases 10.6 and 11.2 both measured symptom MRR at about **0.24** on language the system had
never seen, from two independently-written sets. The error analysis blamed vocabulary: the
manual says *"Rail pressure Sensor Short circuit to ground"*, a driver says *"it loses power on
a climb"*. Phases 10.1/10.1b attacked that from the query side (a lexicon) and failed to
generalise. This phase attacks it from the **index** side: have a local model write, for each
record, a few plain-language descriptions of how the fault *shows up*, and make those
searchable as a third ranker.

**The hypothesis was refuted.** Both variants degraded retrieval severely on development data
and on both spent sets, and neither came close to the required guardrail score.

## Headline

| | DEV symptom MRR | DEV near-dup MRR | guardrails | Round-1 MRR (post-hoc) | R2 MRR (post-hoc) | latency p50 |
|---|---|---|---|---|---|---|
| **production (base)** | **0.7111** | **1.0000** | **14/14** | **0.2447** | **0.2467** | **30.5 ms** |
| + expansions (unfiltered) | 0.3403 | 0.4857 | **7/14** | 0.1707 | 0.0222 | 92.5 ms |
| + expansions (filtered) | 0.2639 | 0.4929 | **9/14** | 0.2102 | 0.0356 | 55.5 ms |

The gate required **guardrails 14/14**. Neither variant reached it, so **neither was chosen**
and `chosen_variant` is recorded as `null` in the freeze. Production is untouched: suite
**44 passed / 1 xfail / 0 failed**, determinism `--defaults` **`ffff9bc707d8754d`**.

## Method

### 1. Generation (`scripts/gen_symptom_expansions.py`)

- **Model:** Qwen2.5-**3B**-Instruct GGUF Q4_K_M — the brief's first choice. Measured at ~5
  tok/s and ~14 s/record on this 4-vCPU box, so no fallback to 1.5B was needed.
- **Determinism:** temperature 0, seed 12101, one fixed prompt template.
- **Inputs:** that record's `description`, `system`, `effect`, `MIL`, `cause`, `checkpoints` —
  nothing else. **No gold or evaluation file is opened by the generator.**
- **Post-filter: mechanical only.** Drop lines containing a fault code, empty lines, lines
  under 12 characters or over 24 words, headings, and duplicates. No hand-editing, no
  hand-picking.
- **Output:** `data/symptom_expansions.json`, labelled *"index-only, never shown to users"*,
  carrying the model, prompt, seed and per-record outputs including every dropped line.

**Generation statistics:** 314 records, **1,515 expansions**, mean **4.8 per record**, median
14 s/record, **75 minutes of model time**. Per-record counts: 227 records got 6, 15 got 5, 2 got
4, and **70 records got only 1**.

Two bugs were found and fixed before the real run, both visible in the first few records:
the model ignored "one per line" and returned a paragraph, which the length filter then
discarded wholesale (first attempt kept **zero** expansions for most records). The prompt was
strengthened and a **mechanical sentence split** added — a split, not an edit; no wording is
changed.

### 2. The distinctiveness filter (addendum, `scripts/filter_expansions.py`)

Removal only; nothing is reworded.

| rule | effect |
|---|---|
| **1 · over-shared** | embed every expansion; drop it when more than **10 other records** hold a line at cosine ≥ 0.90 |
| **2 · generic-only** | drop a line that is nothing but a generic behaviour (lamp / smoke / noise / power / start) **unless** the record's own fields mention that behaviour |
| **floor** | keep ≥ 2 per record where available; least-shared lines are restored if filtering goes below, and each restoration is recorded |

**Result: 1,515 → 608 expansions, 60% dropped.** Kept-count histogram: 70 records with 1, 214
with 2, 15 with 3, 11 with 4, 3 with 5, 1 with 6. **232 of 314 records needed a restoration** to
meet the floor of 2 — i.e. for most records the filter wanted to drop nearly everything.

**The 20 most-shared removed expansions (distinct texts)** — "shared with N other records" is
the rule-1 count; "removed from N" is how many records carried that exact line:

| shared with | removed from | text |
|---|---|---|
| 130 | 43 | Warning light is off |
| 118 | 46 | Pulling power is weak |
| 118 | 46 | Warning light stays off |
| 115 | 9 | Smoke pours out of the exhaust |
| 115 | 65 | Pulling power weak |
| 115 | 5 | Weak pulling power |
| 112 | 24 | Warning light stays on |
| 105 | 6 | Warning light off |
| 102 | 6 | Smoke coming out of exhaust |
| 97 | 47 | Smoke pours out of exhaust |
| 91 | 35 | Smoke pours from exhaust |
| 91 | 1 | Smoke pours from the exhaust |
| 87 | 83 | Warning light on dashboard |
| 86 | 4 | Warning light flashes on dashboard |
| 84 | 1 | Warning light on dashboard stays on |
| 72 | 3 | Car won't start |
| 72 | 70 | Vehicle won't start |
| 60 | 6 | Warning light comes on |
| 59 | 5 | Warning light on |
| 56 | 8 | Smoke comes out of the exhaust |

### 3. The third ranker

`scripts/build_symptom_index.py` builds a separate index directory from the production C4b
configuration plus the expansions:

- **dense:** one vector **per expansion**; a record's symptom score is the **max** cosine over
  its own expansions, so one good paraphrase is enough and the rest do not dilute it;
- **BM25:** the expansions appended to the record's lexical text.

`src/symptom_retriever.py` subclasses the production `Retriever` and overrides only the hybrid
route, fusing **dense + BM25 + symptom-dense** with the same RRF and the same total-order
tiebreak. Expansions are matched against but never returned: answers, fix blocks and citations
still come from the manual alone.

## Key decisions

1. **Nothing in the frozen path was edited.** `src/build_index.py` is covered by the Phase 10.1b
   freeze and `src/retrieve.py` by the Phase 11.1 freeze, so the new code **imports** from them
   and adds a separate builder plus a subclass. Every earlier freeze still verifies.
2. **Both variants were evaluated, and the gate was applied as written.** Guardrails 14/14 was a
   hard requirement, not a tie-breaker. Neither variant met it, so neither was selected —
   rather than promoting the less-bad one.
3. **The freeze records a failure.** `data/experiments/12_1/freeze.json` has
   `chosen_variant: null` and states the verdict, so the artefacts stay reproducible without
   implying a candidate exists.
4. **The post-hoc step was still run, on both variants.** The approach was already rejected, but
   the interesting question — *does the bridge help on the independent language it was built
   for, even while hurting development data?* — deserved an answer. It does not.

## Results

### The no-regression gate (DEV + the spent TEST + 14 guardrails)

| config | DEV symptom hit@1 / MRR | DEV near-dup MRR | DEV exact | DEV overall | groups | OOS | in-scope | guardrails |
|---|---|---|---|---|---|---|---|---|
| base | 58.3% / **0.7111** | **1.0000** | 1.0000 | 0.8613 | 3/3 | 6/6 | 28/28 | **14/14** |
| sympexp | 16.7% / 0.3403 | 0.4857 | 1.0000 | 0.5393 | 3/3 | 6/6 | 28/28 | **7/14** |
| sympexp_filtered | 8.3% / 0.2639 | 0.4929 | 1.0000 | 0.5047 | 3/3 | 6/6 | 28/28 | **9/14** |

Spent TEST (post-hoc): base symptom MRR 0.6282 → 0.3769 (unfiltered) / 0.3833 (filtered);
near-duplicate MRR 0.6786 → 0.1405 / 0.2833.

**The failing guardrails are the injector family** — "injector open circuit cylinder 1/2/3/4",
"cylinder N injector has a broken wire", "injector short circuit high and low side cylinder
N" — plus "camshaft no signal" under the filtered variant. These are precisely the
near-duplicate families the guardrails exist to protect.

### Post-hoc on the spent sets (labelled optimistic; both were already used once)

| config | Round-1 hit@1 / hit@5 / MRR | R2 hit@1 / hit@5 / MRR | no_dtc declined | latency p50 / p95 |
|---|---|---|---|---|
| base | 14.6% / 41.5% / **0.2447** | 13.3% / 40.0% / **0.2467** | 0/19, 0/4 | **30.5 / 34.1 ms** |
| sympexp | 9.8% / 24.4% / 0.1707 | 0.0% / 6.7% / **0.0222** | 0/19, 0/4 | 92.5 / 178.4 ms |
| sympexp_filtered | 12.2% / 34.1% / 0.2102 | 0.0% / 13.3% / **0.0356** | 0/19, 0/4 | 55.5 / 65.2 ms |

**The bridge fails hardest on exactly the queries it was built for.** On R2 the unfiltered
variant scores 0.0222 — it finds the right code in the top 5 for one query in fifteen — against
0.2467 for plain production. Latency triples.

### Five records, as generated and as filtered

| record | manual description | unfiltered (6) | filtered |
|---|---|---|---|
| **P0192-00** | Rail pressure Sensor Short circuit to ground | Engine pulls weakly at start · Smoke pours from exhaust · Idle unstable, jerky · Warning light flashes · Pulling power drops · Noise from engine increases | Pulling power drops · Noise from engine increases |
| **P0117-00** | Coolant temperature sensor signal Short circuit to ground | Warning light on dashboard · Engine starts with difficulty · Idle rough, stutters · Smoke pours from exhaust · Engine makes unusual noise · **Temperature gauge climbs** | Idle rough, stutters · **Temperature gauge climbs** |
| **P0340-00** | DFC for camshaft signal diagnose - no signal | Vehicle won't start · Warning light stays on · Noisy when trying to start · Smoke comes out of exhaust · Pulling power is weak · Idling is shaky and rough | Noisy when trying to start · Idling is shaky and rough |
| **P203B-85** | DFC for Urea Level signal incorrect: too high | Engine starts with difficulty · Pulling power is weak · Idle is rough · Smoke pours from exhaust · Noise is unusual · Warning light flashes | Idle is rough · Noise is unusual |
| **P0201-00** | Injector open circuit for **cylinder 1** | Engine starts but stalls quickly *(only 1 generated)* | Engine starts but stalls quickly |

**This table is the whole explanation.** A rail-pressure sensor fault, a coolant sensor fault, a
camshaft signal fault and a urea-level fault receive **the same six symptoms**: weak pulling,
smoke, rough idle, a warning light, a noise. A 3B model has no real diagnostic knowledge of
these ECU faults, so when asked "how does this show up?" it emits a generic *"the engine runs
badly"* template. Only one line in the five records above is genuinely fault-specific —
P0117-00's *"Temperature gauge climbs"*.

P0201-00 shows the damage directly: the expansion for *"Injector open circuit for **cylinder
1**"* never mentions cylinder 1. Adding that text to the index pushes the four injector records
together, which is exactly why seven injector guardrails fail.

**Why the filter could not rescue it.** The filter removes the worst offenders, but what remains
is the *next* most generic layer ("Idle is rough", "Noise is unusual"), and the floor of 2
forces 232 records to keep lines the rules had already condemned. Filtering improved the
guardrails from 7/14 to 9/14 and R2 MRR from 0.0222 to 0.0356 — better, still far below
production, and still a long way from the gate.

## Files

| file | role |
|---|---|
| `scripts/gen_symptom_expansions.py` | generation: fixed prompt, temp 0, seed 12101, mechanical post-filter, resumable |
| `data/symptom_expansions.json` | 1,515 expansions, index-only label, per-record dropped lines |
| `scripts/filter_expansions.py` | the addendum's distinctiveness filter (removal only) |
| `data/symptom_expansions_filtered.json` · `data/experiments/12_1/filter_report.json` | 608 expansions + the drop report |
| `scripts/build_symptom_index.py` | third-ranker index builder (per-expansion vectors + BM25 text) |
| `src/symptom_retriever.py` | `SymptomRetriever`: dense + BM25 + symptom-dense RRF |
| `scripts/eval_12_1.py` | `--stage dev` (gate) and `--stage posthoc` (spent sets, freeze-gated) |
| `data/experiments/12_1/freeze.json` | the freeze, with `chosen_variant: null` and the verdict |
| `data/experiments/12_1/dev_test_results.json` · `posthoc_results.json` | all measurements |
| `index_exp/minilm_sympexp*/` | the two experimental indexes (gitignored, rebuildable) |

## Limitations

1. **One model, one prompt.** A 3B instruct model at temperature 0 with a single template. A
   larger model, or a prompt seeded with the record's *steps* rather than its description, might
   produce fault-specific text. This result rejects **this** implementation, not doc2query as an
   idea.
2. **70 records produced only one expansion**, short of the 4–6 asked for, because the model
   returned a single line and the mechanical split had nothing to split. Those records are
   under-served even before filtering.
3. **The filter's floor fights its own rules.** Forcing 2 expansions per record restored
   condemned lines into 232 records, which weakens the filtered variant's purpose.
4. **Post-hoc numbers on spent sets.** Round-1 and R2 were each used once before; these figures
   are development feedback, optimistic by construction. They point the same way as DEV, which
   is what makes the conclusion safe.
5. **Latency was measured in-process** on an idle box; the 3× increase is the per-expansion
   dense scan plus the larger BM25 corpus, and would differ under load.
6. **The negative result is strong but narrow.** It says that generic LLM-written symptoms
   *hurt* a corpus of 314 near-identical ECU faults. It says nothing about domains where
   documents are already distinct.

## Conclusion and recommendation

**Do not adopt, and do not pursue this variant further.** The hypothesis — that plain-language
symptom text would bridge the vocabulary gap — is refuted on every axis measured: development
data, both spent evaluation sets, the near-duplicate guardrails, and latency. The cause is
specific and understood: on a corpus of 314 faults that differ by one sensor or one cylinder, a
small model's symptom text is near-identical across records, so adding it **erases** the
distinctions the retriever depends on.

If doc2query is revisited, the thing to change is the source of the text, not the filtering: the
expansions would have to be derived from each record's **own troubleshooting steps, pins and
checkpoints** — material that actually differs between near-duplicates — rather than from a
model's general notion of how a diesel engine misbehaves.
