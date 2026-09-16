# Phase 8.3 — Recalibrating the Relevance Gate (L3)

**Scope: calibrated and reported on DEV only, against the C4b index**
(`index_exp/minilm_alias_bm25_cyl`, the selected 8.2b configuration). **The frozen TEST
split was not run.** The intent stoplist was built **without consulting TEST
out-of-scope queries** — see §Provenance for what that does and does not guarantee.

## Objective

The Phase 7 gate refused **4/6** DEV out-of-scope queries. The two it let through —
*"what is the warranty period on this engine"* and *"are replacement injectors in stock at
the dealer"* — are vehicle-adjacent commercial questions. A gate that answers those invites
the model to fabricate warranty terms or stock levels. Goal: **6/6 refused without blocking
a single in-scope query.**

---

## Design — two independent reasons to refuse

| reason | refuses when | catches |
|---|---|---|
| **(a) low retrieval signal** | `dense_sim < dense_min` **AND** `bm25_max < bm25_min` | nothing in the manual resembles the query — *capital of France, change a tyre* |
| **(b) non-diagnostic intent** | ≥1 intent term **AND** no diagnostic cue **AND** no DTC code | the query is about price, purchase, scheduling, warranty or comfort — even when it names a vehicle part |

**A query passes only if it clears (a) and does not trip (b).** Each refusal records which
reason(s) fired, so every decision is explainable.

Why two reasons instead of a stricter threshold: the vehicle-adjacent questions share real
vocabulary with the manual — *engine*, *injectors* — so on retrieval signal they sit among
genuine queries. A signal threshold *can* be forced to separate them on DEV, but only by
fitting to a single data point (next section). Intent separates them for a reason that holds
by construction.

Dense similarity remains the **exact brute-force** maximum over all stored vectors
(`Retriever.exact_max_sim`), preserving the Phase 7 reproducibility fix.

---

## 1. Retrieval-signal thresholds, recalibrated on C4b

### DEV score distributions

**dense_sim** (exact cosine, MiniLM)

| group | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| in-scope | 28 | 0.251 | 0.387 | 0.445 | 0.482 | 0.571 |
| out-of-scope | 6 | 0.060 | 0.099 | 0.213 | 0.322 | 0.323 |

**bm25_max** (C4b corpus with aliases + cylinder token; raw query)

| group | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| in-scope | 28 | 5.563 | 8.870 | 12.842 | 18.400 | 24.539 |
| out-of-scope | 6 | 2.179 | 3.567 | 5.631 | 8.743 | 10.607 |

### The queries that determine the thresholds

| id | in scope | dense_sim | bm25_max | query |
|---|---|---|---|---|
| d029 | **no** | 0.060 | 4.63 | how do I change a tyre |
| d032 | **no** | 0.099 | 2.18 | book me a service appointment |
| d034 | **no** | 0.110 | 5.63 | what is the capital of France |
| d031 | **no** | 0.213 | 3.57 | how much does this truck cost |
| d030 | **no** | 0.322 | 8.74 | what is the warranty period on this engine |
| d033 | **no** | 0.323 | 10.61 | are replacement injectors in stock at the dealer |
| d016 | yes | 0.251 | 11.75 | soot trap is completely blocked up |
| d021 | yes | 0.283 | 22.80 | alternator is overcharging and the battery sees far too many volts |
| d014 | yes | 0.313 | 11.55 | exhaust recirculation flap is seized shut |
| d017 | yes | 0.340 | 19.41 | the adblue reservoir is nearly empty and low warning is showing |
| d005 | yes | 0.351 | 18.06 | details for U0102-00 |
| d013 | yes | 0.375 | 14.27 | crank position reading is noisy and unstable |
| d024 | yes | 0.385 | 9.17 | loss of pulling power with the dash warning light on |
| d027 | yes | 0.387 | 6.37 | show me every injector related fault code |
| d028 | yes | 0.390 | 6.73 | what soot trap faults are there |
| d009 | yes | 0.396 | 12.84 | fuel rail sender pulled down to earth |
| d025 | yes | 0.398 | 10.26 | system voltage keeps sagging and the ecu drops out on cold starts |
| d002 | yes | 0.445 | 6.35 | P0340 |
| d006 | yes | 0.454 | 5.79 | fault code P2264 |
| d026 | yes | 0.459 | 5.93 | list all EGR faults |
| d004 | yes | 0.481 | 5.56 | P0100 |

*(Out-of-scope queries, plus every in-scope query with dense < 0.40 or bm25 < 8.5.)*

### Why retrieval signal alone is the wrong tool for the vehicle-adjacent queries

The two vehicle-adjacent out-of-scope queries score **d030 0.322 / 8.74** and
**d033 0.323 / 10.61**, **inside** the in-scope range on each signal taken separately.
In-scope dense goes down to **0.251** (*soot trap*) and in-scope bm25 down to **5.56**
(*P0100*):

- a **dense-only** threshold high enough to refuse both would block **3** in-scope queries
  (d014, d016, d021);
- a **bm25-only** threshold would block **12**.

**A signal-only OR rule can separate DEV exactly — and was rejected.** No in-scope query
sits below *both* signals, so `dense ≥ 0.33 or bm25 ≥ 10.7` refuses 6/6 and passes 28/28 on
DEV. But it is fitted to one point: it refuses d033 by **0.007** on dense and **0.09** on
bm25, and passes genuine queries by similarly thin margins — d014 by 0.85 bm25 and d024 by
0.055 dense. Any in-scope paraphrase landing in that band would be refused, and any
commercial question scoring slightly higher than d033 would be answered. The separation is
coincidental, not structural.

The intent filter refuses d030 and d033 because they *ask about a warranty* and *ask about
stock* — a reason that does not depend on where their similarity scores happen to fall. That
is why reason (b) was chosen over a tighter signal threshold. (A correction to an earlier
draft of this report, which wrongly stated that the data ruled any signal threshold out.)

### Chosen thresholds — `data/gate_c4b.json`

| threshold | value | was (v1) | derivation |
|---|---|---|---|
| **dense_min** | **0.23** | 0.30 | midpoint of the max general out-of-scope dense (0.213, *truck cost*) and the min in-scope dense (0.251, *soot trap*) |
| **bm25_min** | **8.5** | 8.0 | midpoint of the max general out-of-scope bm25 (5.63, *capital of France*) and the lowest bm25 among in-scope queries nearest the dense threshold (~11.6), so BM25 stays a real second route for paraphrases |

Under (a) alone, the four general out-of-scope queries are refused and all 28 in-scope pass
— six of them via dense alone (the code-only and grouping queries, dense 0.39–0.48, well
clear). **The dense margin is thin:** 0.213 → 0.23 → 0.251 leaves ~0.02 on each side, set
from only 6 out-of-scope points. It is not load-bearing on its own — *truck cost*, the
closest out-of-scope query, is also refused by (b).

---

## 2. Non-diagnostic intent filter — `data/intent_stoplist.json`

### Taxonomy

| category | terms | provenance |
|---|---|---|
| commercial_pricing | price, pricing, cost, how much does, how much is, resale, discount, quote, quotation, finance, trade-in, trade in, cheaper, expensive | user 5, general 8, dev_oos 1 |
| purchasing_parts | buy, purchase, in stock, dealer, dealership, spare part, genuine part, part number, supplier, delivery time | user 4, general 6 |
| scheduling_service | book, booking, appointment, service centre, service center, opening hours, service appointment, service interval, next service, reschedule | user 5, general 4, dev_oos 1 |
| warranty_legal | warranty, guarantee, insurance, recall, claim, refund | user 2, general 4 |
| comfort_infotainment | bluetooth, infotainment, radio, speaker, navigation, sat nav, air conditioning, climate control, touchscreen, usb | user 4, general 6 |

**50 intent terms** in 5 categories, plus **50 diagnostic cue words**
(*fault, error, code, warning, light, stuck, broken, leak, sensor, gauge, won't start, …*).

### Dominance — how a real fault query is protected

The filter fires only when non-diagnostic intent **dominates**: an intent term **and zero
diagnostic cues and no DTC code.** Any cue or code vetoes it, so
*"the dealer says my egr valve is stuck, what is the fault"* passes despite *dealer*.

### Safety rule, enforced automatically

**No intent term may occur in any manual DTC description, cause, effect or checkpoint**
(`gate.audit_stoplist()`; a suite test asserts **0 collisions**). A query that echoes the
manual can therefore never trip the filter. Ambiguous words are left out on purpose:
*available/availability* (the manual has *"heater unavailability"* as a fault), bare *seat*
(valve seat), bare *ac* (AC voltage), *supply* (supply voltage), *order* (firing order).

### Provenance

Each term is tagged `general`, `user` (named in the 8.3 brief) or `dev_oos` (taken from a
DEV out-of-scope query). **TEST out-of-scope queries were not consulted while building the
list.**

That statement is about process; it is not a guarantee of independence. The stoplist was
frozen (sha256 `736ea4205e04100d`, recorded in `gate_c4b.json`), and only **then** checked
against TEST query **text** — no gate or retrieval was run on TEST.
**8 of 50 terms match TEST wording, and all 8 are `user`-provenance** — words named in the
8.3 brief, which were in turn visible in earlier reports:

| category | term | provenance |
|---|---|---|
| commercial_pricing | resale | user |
| commercial_pricing | discount | user |
| purchasing_parts | buy | user |
| purchasing_parts | purchase | user |
| scheduling_service | service centre | user |
| warranty_legal | warranty | user |
| comfort_infotainment | bluetooth | user |
| comfort_infotainment | infotainment | user |

Same treatment as the lexicon: **8.5 will report TEST twice**, with the full stoplist and
with these 8 terms removed. The ablated figure is the conservative headline.

---

## 3. DEV validation

### Gate — before / after

| DEV (C4b index) | legacy v1 gate | **gate v2** |
|---|---|---|
| **out-of-scope refused** | 4/6 | **6/6** |
| **in-scope passed** | 28/28 | **28/28** |
| in-scope newly blocked | — | **none** |

### Every out-of-scope decision

| id | query | legacy v1 gate | **gate v2** | refusal reason(s) | evidence |
|---|---|---|---|---|---|
| d029 | how do I change a tyre | refused | **refused** | low_retrieval_signal | dense 0.060 < 0.23 and bm25 4.63 < 8.5 |
| d030 | what is the warranty period on this engine | passed ✗ | **refused** | non_diagnostic_intent | intent: warranty_legal=['warranty'] |
| d031 | how much does this truck cost | refused | **refused** | low_retrieval_signal, non_diagnostic_intent | intent: commercial_pricing=['cost', 'how much does'] · dense 0.213 < 0.23 and bm25 3.57 < 8.5 |
| d032 | book me a service appointment | refused | **refused** | low_retrieval_signal, non_diagnostic_intent | intent: scheduling_service=['book', 'appointment', 'service appointment'] · dense 0.099 < 0.23 and bm25 2.18 < 8.5 |
| d033 | are replacement injectors in stock at the dealer | passed ✗ | **refused** | non_diagnostic_intent | intent: purchasing_parts=['in stock', 'dealer'] |
| d034 | what is the capital of France | refused | **refused** | low_retrieval_signal | dense 0.110 < 0.23 and bm25 5.63 < 8.5 |

d030 and d033 — the two that previously leaked — are now refused for intent alone. d031 and
d032 are refused for **both** reasons, so there is a backup.

### Gate v2 does not affect ranking — verified in one process

Running the legacy and v2 gates **in the same process** gives **identical results on all 25
ranked DEV queries** (same rank, same top-5 list), confirmed in 3/3 processes. That follows
from the design: `answer.is_relevant()` decides answer-or-refuse and never touches
`Retriever.retrieve()`.

| DEV retrieval (C4b) | n | hit@1 | hit@5 | MRR |
|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 100.0% | 100.0% | 1.000 |
| symptom | 12 | 58.3% | 91.7% | 0.711 |

system_group complete **3/3**.

---

## ⚠ Finding — retrieval ranking is not reproducible across processes

The first separate-process runs showed symptom MRR **0.715** under the legacy gate and
**0.711** under gate v2. **The gate is not the cause.** The *legacy* gate alone produced
**0.7153 in one process and 0.7111 in the next**, because d017 ranked 4 in one run and 5 in
the other.

**Root cause: Chroma's HNSW dense search is approximate, and its top-50 pool differs between
processes.** For d017, in **2 of 3** fresh processes the HNSW pool differed from an exact
brute-force search — a different *set* of vectors, first diverging at rank 17 or 21. In the
third it matched exactly. The difference flows through RRF into the final ranking.

This is the **same root cause found in Phase 7**, which was fixed *for the gate threshold*
(exact brute-force similarity) but never for ranking, which still takes its dense pool from
HNSW.

**Impact:** every reported DEV MRR carries roughly one rank position of run-to-run noise
(here ±0.004). More importantly, **Phase 8.5 measures TEST exactly once**, and on this basis
that one number could differ from a re-run.

**Recommended fix — not applied, because it changes ranking and 8.3 is gate-only:** take the
hybrid dense pool from the exact brute-force matrix (`Retriever.vectors`) instead of Chroma.
At 314 × 384 it is trivially cheap and makes retrieval fully deterministic. It should land
**before 8.5**, followed by a DEV re-run. Figures in this report are from the gate-v2 run
(0.711); the legacy figure of 0.715 is the same system in a different process.

---

## Tests

Gate v2's cue veto is **never exercised by DEV**: no in-scope DEV query contains an intent
term. To keep it from going unverified, 7 unit tests were added, using **synthetic queries
from neither split**:

| query | expected | result |
|---|---|---|
| how much would a replacement turbo cost | refuse (pricing) | ✅ |
| can I pair bluetooth with my phone | refuse (comfort) | ✅ |
| the dealer says my egr valve is stuck, what is the fault | **pass** — cues veto *dealer* | ✅ |
| warning light came on right after the warranty service | **pass** — cues veto *warranty* | ✅ |
| P0192-00 what is the price of that sensor | **pass** — DTC code (and cue) veto *price* | ✅ |
| rail pressure sensor shorted to ground | pass — no intent term | ✅ |
| no intent term occurs in manual fault text | 0 collisions | ✅ |

**Suite: 44 passed, 1 xfail, 0 failed** (was 37).

## What has NOT changed

- **Production is unchanged.** `answer.is_relevant()` without a gate config is the legacy v1
  gate, and `app.py` still uses it. Gate v2 is *selected*, bound to the C4b index through
  `calibrated_on_index`, and adopted together with C4b after 8.5.
- **TEST has not been run.**

## Evidence & Artifacts

- `src/gate.py` — `Gate` (two-reason decision, per-reason trace) and `audit_stoplist()`
- `data/gate_c4b.json` — thresholds, rationale, stoplist hash
- `data/intent_stoplist.json` — taxonomy, cues, provenance, authoring rules
- `data/experiments/8_3_gate_signals_dev.json` — DEV score distributions
- `data/experiments/8_3_gate_dev_per_query.json` — every DEV decision with reasons
- `data/experiments/8_3_dev_{legacy_gate,gate_v2}.json` — DEV evals
- `data/experiments/8_3_stoplist_test_matching.json` — post-freeze TEST-wording audit
- `src/answer.py` (`gate=` opt-in), `src/evaluate_v2.py` (`--gate`)

## Limitations

- **Only 6 out-of-scope DEV queries.** Thresholds and the stoplist rest on very few negative
  examples. 6/6 is a necessary result, not a demonstration of generalisation — that is 8.5's job.
- **The dense threshold has a ~0.02 margin** on each side.
- **A stoplist is lexical.** Out-of-scope intent phrased outside it (*"what will it set me
  back"*) is not caught by (b), and falls back to (a) — which the vehicle-adjacent case
  typically clears.
- **The cue veto is permissive by design.** A commercial question that happens to contain a
  cue word (*"how much does a new sensor cost"* — *sensor* is a cue) passes. The trade-off
  deliberately favours never blocking a real fault query.
- **Ranking non-determinism** (above) is unresolved.
