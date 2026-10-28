# Phase 12.2 — fault-specific symptom expansions, authored rather than generated

**Branch** `phase12-symptom-bridge` · **production unchanged** · expansions are **index-only**
(matched against, never returned, never cited)

## Objective

Phase 12.1 asked a 3B model to write "how does this fault show up?" for each of the 314
records and the result **erased** the distinctions retrieval depends on: near-duplicate MRR
fell 1.000 → 0.486 and seven injector guardrails failed. Its conclusion named the cause as
the *source of the text*, not the filtering — a small model has no diagnostic knowledge of
these ECU faults, so it writes the same six lines for a rail-pressure fault and a urea-level
fault.

Phase 12.2 tests that diagnosis directly: keep the mechanism (a third ranker over per-record
symptom text) and **replace the author**. The lines here are written from each record's own
fields plus general automotive knowledge, under one hard requirement — **every line must carry
at least one element that distinguishes it from its near-duplicate siblings**.

## Method

**1. Families.** The 314 records group into **150 near-duplicate families** by component key
(the description with failure-mode words and numbers stripped): 54 families have more than one
member, the largest has 42. Authoring was done per family, so siblings were always written
against each other rather than in isolation.

**2. Three authored vocabularies.** Each line is composed from:

| piece | what it supplies | example |
|---|---|---|
| **COMPONENT** (52 entries) | the gauge or behaviour a driver notices for *this* part, plus a driver-voice complaint written for that part alone | coolant temperature sensor → "the temperature gauge", "the temperature gauge is telling lies and the fan runs at the wrong times" |
| **MODE** (20 entries, opposed pairs) | what *this* failure mode looks like | short-to-ground pins a reading at the **bottom**; short-to-battery pins it at the **top**; open circuit kills it; stuck-open will not close; stuck-closed will not open |
| **MARKER** | the record's own distinguishing token | cylinder 1, pedal track 2, bank 1, sensor 1, upstream/downstream, sensor A/B, the T4/T5/T6 probe, the FCCU id |

The opposed mode phrasings are the point: a short-to-ground line *cannot* read like a
short-to-battery line, so the two siblings that differ only in that respect cannot collapse
together. Mode classification comes from the record's own description, the effect line from its
own `effect`/`MIL` fields.

**3. Self-checks, applied to the authored set before any evaluation.** Four were written and
all four pass: no line contains a fault code (0/1310); no line names neither a component nor a
marker (0/1310); no bare lamp, smoke, noise or power line; and **no line is shared verbatim
with a family sibling**. The last one failed badly at first — 139 lines, because the complaint
and effect lines carried the component but not the mode — and drove three fixes: a short mode
tag stamped onto both lines, markers collected rather than first-match-wins (a record saying
both "NOx sensor 1" and "Bank 1" needs both, or it collides with sensor 2), and a line built
from each record's own leftover description words.

**4. Family-level collision removal.** The 12.1 lesson applied mechanically: a line held by two
records in one family separates neither, so it is removed from **both**. 39 distinct lines, 79
removals. Removal only — nothing is reworded.

**5. The specified filter.** Embed every line; drop one shared at cosine ≥ 0.90 by **more than
5** other records; **no restoration floor**, as specified.

**6. Index and variants.** Built with `scripts/build_symptom_index.py` unchanged from 12.1
(one dense vector per expansion, record score = max cosine; expansions appended to the BM25
text). Two variants were evaluated: **equal RRF weight** and **symptom weight 0.5**.

## Key decisions

- **Authored by composition, stated plainly.** The component and mode phrasings and the
  composition rules are mine; the component, mode, marker and effect for each record come from
  that record's fields. These are **not** 314 independently free-written paragraphs, and the
  provenance string in the data file says so. Composition is what makes the distinctiveness
  guarantee mechanical rather than a matter of my own care over 1,300 lines.
- **A true RRF weight.** In 12.1 `symptom_weight` only decided whether the symptom ranking
  joined the fusion. A 0.5 variant needs the weight to reach the fusion, so a weighted
  `rrf_fuse_weighted` contributes `w / (k + pos)`. `--stage check` verifies that `w = 1.0`
  reproduces the 12.1 fusion exactly (10/10 probes) rather than assuming it.
- **Nothing frozen was edited.** `src/symptom_retriever.py`, `scripts/build_symptom_index.py`,
  `scripts/filter_expansions.py` and `scripts/eval_12_1.py` are all inside the 12.1 freeze, so
  12.2 adds files beside them: `src/symptom_retriever_w.py`, `scripts/author_expansions_v2.py`,
  `scripts/filter_expansions_v2.py`, `scripts/eval_12_2.py`.
- **No evaluation file was opened** during authoring or filtering. The only input is
  `data/dtc_records.jsonl`.

## Results

### The authored set

| | value |
|---|---|
| lines authored | 1310 (4.17 per record) |
| after the cosine filter | **988** (dropped 322, 25%) |
| records with 3–5 lines (before filter) | 294 / 314 |
| per-record kept after filter | 5 lines ×122, 4 ×52, 3 ×39, 2 ×14, 1 ×25, **0 ×62** |

The 62 emptied records are the honest limit of the method: **56** are the
`Status of the EMM alarm FCCUnn` ECU-internal records, which differ *only* by an internal alarm
number no driver can perceive, so their only distinguisher is that number — and MiniLM cannot
tell `fccu0` from `fccu103`, scoring those lines as shared with 55 other records. The other six
are two pairs whose manual descriptions are byte-identical (`P2200-F0`/`P229E-F0`,
`P2200-84`/`P229E-84` — the manual says "upstream" for both of each pair), plus `P061A-00`
("DFC for torque monitoring", no distinguishing content at all) and `P2201-76`.

### The DEV gate

| variant | DEV symptom hit@1 / hit@5 / MRR | DEV near-dup MRR | exact | guardrails | gate |
|---|---|---|---|---|---|
| **base** (production) | 0.583 / 0.917 / **0.7111** | **1.0000** | 1.0000 | **14/14** | PASS |
| v2_equal (weight 1.0) | 0.250 / 1.000 / 0.5347 | 0.9286 | 1.0000 | 12/14 | **FAIL** |
| **v2_half** (weight 0.5) | 0.250 / **1.000** / 0.5208 | 0.9286 | 1.0000 | **14/14** | **PASS** |

v2_equal fails on two guardrails: *injector short circuit high and low side cylinder 3* and
*cylinder 4*. v2_half passes all three pre-specified checks (guardrails 14/14, DEV in-scope
28/28, DEV out-of-scope 6/6) and is therefore the frozen variant.

### Authoring vs generation, on exactly what 12.1 broke

| | near-dup MRR | guardrails | DEV symptom MRR |
|---|---|---|---|
| base | 1.0000 | 14/14 | 0.7111 |
| 12.1 generated | 0.4857 | 7/14 | 0.3403 |
| 12.1 generated + filtered | 0.4929 | 9/14 | 0.2639 |
| **12.2 authored (v2_half)** | **0.9286** | **14/14** | **0.5208** |

The diagnosis in 12.1 was right. Changing the author repaired almost the whole near-duplicate
collapse (0.486 → 0.929) and all of the guardrail damage (7/14 → 14/14). The symptom-side DEV
metric recovered by roughly half but **still sits well below base**.

### The same five records as 12.1

| record | 12.1 (generated) | 12.2 (authored) |
|---|---|---|
| **P0192-00** rail pressure, short to ground | "Engine pulls weakly at start / Smoke pours from exhaust / Idle unstable, jerky / Warning light flashes / Pulling power drops / Noise from engine increases" | "rail pressure reading sits at the very bottom of the scale and stays there / … reads zero even when it plainly should not / the fuel rail pressure sensor line is shorted down to earth / …" |
| **P0117-00** coolant temp, short to ground | "Warning light on dashboard / Engine starts with difficulty / Idle rough, stutters / Smoke pours from exhaust / Engine makes unusual noise / **Temperature gauge climbs**" | "the temperature gauge sits at the very bottom of the scale and stays there / … reads zero even when it plainly should not / the coolant temperature sensor line is shorted down to earth / …" |
| **P0340-00** camshaft, no signal | "Vehicle won't start / Warning light stays on / Noisy when trying to start / Smoke comes out of exhaust / Pulling power is weak / Idling is shaky and rough" | "nothing at all arrives from the camshaft position sensor / … never reports in, so there is no value to work with / it will not start at all, with no report arriving on the camshaft position sensor" |
| **P203B-85** urea level, too high | "Engine starts with difficulty / Pulling power is weak / Idle is rough / Smoke pours from exhaust / Noise is unusual / Warning light flashes" | "the AdBlue gauge climbs higher than is physically possible / … goes above the highest sensible figure / … reads nothing like what is actually in the tank / road speed is capped and it will only crawl …" |
| **P0201-00** injector open circuit, **cylinder 1** | "Engine starts but stalls quickly" (cylinder 1 never mentioned) | "injection on that cylinder is completely dead, nothing registers at all, **on cylinder 1** / the injector wiring is broken so no reading ever arrives, **on cylinder 1** / …" |

Note P0117-00: the 3B model wrote "temperature gauge **climbs**" for a sensor **shorted to
ground**, which reads at the bottom of the scale. That line is not merely generic, it is wrong
in the one respect that matters.

### Family-level comparison

The four-member injector family *short circuit high and low side, cylinders 1–4* — the family
that broke 12.1's guardrails — now reads, per member:

> "both the feed and the return of the injector are shorted together, **on cylinder 3**, on both
> sides of the injector" · "… shorted on its high side and its low side at the same time, **on
> cylinder 3** …" · "the complaint on the injector is written up as **short high low side
> cylinder 3**"

Every line names the cylinder. In 12.1 the corresponding expansions never mentioned it. This is
also where authoring caught a real classification bug: "short circuit **high** and low side" was
first classed as *range-high* (a reading that reads high) because of the words "circuit high",
which is wrong — it is a short. Specific short-circuit wordings now match first.

### POST-HOC on the spent sets — **optimistic, not an independent measurement**

Both sets were spent before this run (independent set in 10.6, R2 in 11.2). The expansions were
authored blind to both files and the variant was chosen on DEV alone, so these numbers are less
contaminated than a typical post-hoc — but they are still not a clean independent measurement.

| set | base symptom MRR | v2_half symptom MRR | ΔMRR | 95% CI (paired bootstrap) | better / worse / tied |
|---|---|---|---|---|---|
| Round-1 independent (n=41) | 0.2447 | 0.2943 | **+0.0496** | [−0.0484, +0.1524] | 8 / 8 / 25 |
| R2 colleague (n=15) | 0.2467 | 0.3633 | **+0.1167** | [−0.0167, +0.2833] | 3 / 1 / 11 |

Both intervals **include zero**, and on Round-1 exactly as many queries got worse as got better
(8 and 8) — the mean gain comes from magnitude on a handful of queries, not from breadth. This
is the fourth consecutive refinement in this project to land inside noise on independent data.

`no_dtc` declines stay at **0/19** and **0/4**: the third ranker does not touch the known safety
finding. Latency roughly doubles, p50 **29.5 → 55.3 ms**, p95 **39.1 → 64.5 ms** (CPU, 314
records, 988 expansion vectors).

## Verdict

**Do not adopt**, despite the gate pass, and production is unchanged.

The pre-specified gate contained no DEV-metric floor, so v2_half passes it while regressing the
very metric the phase set out to improve: DEV symptom hit@1 0.583 → 0.250 and MRR 0.7111 →
0.5208. What it actually does is **re-rank rather than retrieve better**: DEV symptom hit@5
*improves* to 1.000 (the right record reaches the top five more often) while hit@1 halves (it is
demoted from first). On n=12 DEV symptom queries that is four queries moving off rank 1 — small
in absolute terms, which is itself a reason not to read much into either direction.

The post-hoc gains on both spent sets point the other way and are the first movement in the
honest ≈0.24 figure this project has seen, but both CIs include zero. The defensible next step is
a **newly written, unspent symptom set** to settle it — not adoption on a post-hoc signal.

## Files

| file | role |
|---|---|
| `scripts/author_expansions_v2.py` | the vocabularies, the composition, the four self-checks and the family collision removal |
| `data/symptom_expansions_v2.json` | 1310 authored lines + provenance, mode histogram, collision record |
| `scripts/filter_expansions_v2.py` | the specified cosine filter (> 5 other records, no floor) |
| `data/symptom_expansions_v2_filtered.json` | 988 lines, what is indexed |
| `data/experiments/12_2/filter_report.json` | per-record histogram, emptied records, most-shared removed texts |
| `src/symptom_retriever_w.py` | weighted RRF fusion (12.1's retriever is frozen) |
| `scripts/eval_12_2.py` | `--stage check / dev / posthoc` |
| `data/experiments/12_2/dev_test_results.json` | the gate run |
| `data/experiments/12_2/freeze.json` | `chosen_variant: "v2_half"`, gate verdict, adoption recommendation, sha256 of 8 artefacts |
| `data/experiments/12_2/posthoc_results.json`, `posthoc_bootstrap.json` | the spent-set measurement and its CIs |
| `index_exp/minilm_sympexp_v2/` | the index (gitignored) |

## Limitations

1. **Composed, not free-written.** The guarantee is mechanical: every line carries a component,
   a mode and (where the record has one) a marker. That makes the lines reliably *distinct*, not
   reliably *natural*. Some read stiffly — "inducement and derate suffers, with no report
   arriving on the NOx sensor" — and real technician phrasing is more varied than 52 component
   complaints.
2. **My automotive knowledge is the ceiling.** The lines are only as correct as my reading of
   each description. I caught one wrong classification (short-circuit-high read as range-high);
   others may remain, and nobody with the vehicle in front of them has reviewed this text.
3. **62 records carry no symptom text at all** after filtering, 56 of them ECU-internal alarms.
   For those the third ranker contributes nothing, and no authoring could fix it — the records
   are not distinguishable by symptom.
4. **DEV symptom n = 12.** Both the regression and the hit@5 improvement rest on twelve queries.
5. **The post-hoc figures are optimistic by construction** and both CIs include zero.
6. **Latency roughly doubles**, which matters for the demo's p95 budget if this were ever
   adopted.
7. **The filter threshold (> 5) was specified, not tuned.** No sensitivity analysis was run, and
   the choice visibly decides whether the 56 FCCU records keep their lines.

## Verification

- Suite **44 passed / 1 xfail / 0 failed** (`src/smoke_index.py`) — unchanged.
- Production retrieval, gate, indexes and records untouched; all 12.2 artefacts are new files.
- **Determinism hash `ffff9bc707d8754d`** — unchanged, reproduced exactly:

  ```
  PYTHONHASHSEED=0 PYTHONPATH=src .venv/bin/python scripts/determinism_proof.py \
      --defaults --index-dir index
  [prod_defaults PYTHONHASHSEED=0] sha256=ffff9bc707d8754d symptom MRR=0.7111
      overall MRR=0.8613 gate oos 6/6 in 28/28
  ```

  **`--index-dir index` matters.** The script's default is
  `index_exp/minilm_alias_bm25_cyl`, a stale experimental copy built 2026-09-16, and run against
  that it prints **`76b16c2b9ab8f9f2`** — which is the *pre-9.1b* hash recorded in RESUME. The
  reason is that Phase 9.1b fixed garbled troubleshooting steps in the records, and the BM25 text
  includes the step **condition** clauses, so an index built before that fix still reproduces the
  old canonical output. Nothing has drifted and nothing regressed: the two canonical outputs
  differ only in the 3rd–5th positions of `d007` and `d009`, below the hit, with every metric and
  every correct answer's rank identical. Anyone verifying this project should point the proof at
  `index/`, or rebuild `index_exp/minilm_alias_bm25_cyl`.
- The suite figure comes from `PYTHONPATH=src .venv/bin/python src/smoke_index.py`, **not**
  pytest: pytest is not a dependency, and the project's test files are hand-rolled scripts with
  their own `main()`, so pytest collects nothing.
