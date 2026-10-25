# Phase 10.1 — Domain synonym layer v2

_2026-10-25 · branch `phase10-demo` · **production default unchanged** · frozen TEST not used · independent technician query set not read_

## Objective

Mid-sem feedback: free-text symptom retrieval is the weak mode. Phase 8.2 closed part of the
vocabulary gap with a 42-entry lexicon but left two limitations recorded in its own report:

1. coverage outside those 42 entries degrades to the baseline;
2. **"a lexicon cannot handle negation or implication"** — *"refuses to shut"* means stuck
   **open**, and word-level aliasing cannot express that.

This phase extends the lexicon from independent sources only and adds deterministic query-side
rewrite rules for the two cases a synonym list structurally cannot handle: cylinder ordinals and
valve/switch state negation.

**An independent test set written by workshop technicians arrives later. It was not read,
requested or received here, and no entry is derived from a DEV miss** (`dev_driven` = 0, as in
8.2). The headline below is therefore deliberately *not* a DEV win: v2 was built blind to DEV
feedback, and DEV says it is neutral-to-marginally-negative. The independent set is the real test.

## Headline

| gate | result |
|---|---|
| Entries | 42 → **88** (46 new), 0 `dev_driven` |
| DEV symptom MRR | 0.711 → **0.704** (−0.007; one query, d014, moved rank 3 → 4) |
| DEV overall MRR | 0.861 → **0.858** |
| Near-duplicate guardrails | **14/14, no regression** |
| Gate (DEV) | out-of-scope **6/6**, in-scope **28/28** — unchanged, thresholds untouched |
| Suite | **44 passed / 1 xfail / 0 failed** |
| Determinism `--defaults` | **`ffff9bc707d8754d`** — unchanged |
| New unit tests | `src/test_lexicon_v2.py` **79/79** |

The DEV delta (−0.007 MRR) is one rank position on 12 symptom queries, well inside the ±0.08
noise band that Phase 8.2 documented for cells this small. The honest reading is **"no
measurable DEV change"**, not "an improvement".

## Method

### 1. Lexicon v2 — `data/domain_lexicon_v2.json`

Built deterministically by `scripts/build_lexicon_v2.py`. Every Phase 8.2 entry is kept
**verbatim** on its manual side and re-tagged into the v2 provenance taxonomy; `provenance_v1`
is retained for audit.

| provenance | entries | what it is |
|---|---|---|
| `manual_term` | 30 | the manual's own terminology and abbreviations: system/component names, failure phrases (`jammed at open position`, `SRC high`), `DPF`, `ETV`, `PRV` |
| `sae_j1939` | 22 | SAE J1939 standard parameter-name vocabulary mapped to the manual's wording: accelerator pedal position, engine coolant temperature, intake manifold pressure, mass air flow, barometric pressure, aftertreatment, diesel exhaust fluid, EGT, delta pressure |
| `general_technician` | 36 | general workshop/driver language for **symptoms** (loss of power, limp mode, derate, will not start, stalls, overheating, black smoke, leaking, bunged up, jumpy) and for **components** (loom, plug, socket, blown fuse, mprop, starter, pre filter, clutch pedal switch) |
| `dev_driven` | **0** | none, by construction |

- 11 subsystem-level entries, 77 description-level. 282 colloquial terms, **174 authored in v2**.
- Aliases are **BM25-side only** (`--aliases bm25`). Phase 8.2 config C6 showed that aliasing the
  dense text merges near-duplicate families, so the dense side is untouched.
- Aliases are never derived from step text (8.2 rule).

**The Phase 8.2 scope rule, re-applied.** A subsystem-level alias must be correct for *every*
record in that subsystem. New subsystem aliases were added only for `scr_def` (50),
`dpf_regen` (18) and `o2_exhaust` (35), all three taking the SAE umbrella term *aftertreatment*,
which is true of every record in each. The mixed subsystems get **no** new subsystem alias and
keep description-level attachment: `engine_position` (cam + crank), `fuel_supply`,
`pedal_clutch_brake`, `intake_air` (intake + ambient), `electrical`, `sensor_generic`,
`level2_monitoring`, `ecu_internal`. A unit test asserts those eight stay absent.

### 2. Deterministic query-side rules — `src/lexicon.py`

Enabled only when the lexicon declares `"query_rules": true`. **The v1 production lexicon does
not, so the production query path is byte-identical** — which is why the determinism hash is
unchanged. The rules run *before* alias expansion, act on the **BM25 query only**, never touch
the dense query, and never touch the gate (the gate tokenises the raw query). Every rule emits a
trace.

**R1 — cylinder number words and ordinals.** The manual always writes a digit, and 8.2b folds
`cylinder N` into the compound token `cylinder_<N>`. R1 rewrites technician wording into that
digit form, so the existing fold applies:

| input | rewritten |
|---|---|
| `cylinder one`, `cyl two`, `cylinder number three`, `cyl. no four` | `cylinder 1/2/3/4` |
| `the first cylinder`, `second cylinder`, `3rd cylinder`, `sixth cylinder` | `cylinder 1/2/3/6` |
| `no.1 injector`, `#2 injector`, `injector 3`, `injector no 4` | `injector cylinder 1/2/3/4` |

`tokenize()` itself is unchanged, so index and query tokenisation cannot diverge. Already-digit
wording passes through untouched, and the rules do not fire on `four wheel drive` or
`one of the sensors is faulty`.

**R2 — valve/switch state negation and implication.** The manual's wording is *"jammed at open
position"* / *"jammed at closed position"* (P042E/P042F EGR, P04A4/P04A5 exhaust throttle,
P22CF-72/-73 boost actuator). R2 appends the implied manual phrase, leaving the technician's own
words in place for the other aliases to match:

| detected | appended |
|---|---|
| `refuses to shut`, `will not close`, `won't shut`, `does not close`, `not closing`, `stays (wide) open`, `stuck open`, `seized open`, `jammed open`, `held open` | `jammed at open position` |
| `refuses to open`, `will not open`, `not opening`, `stays shut/closed`, `stuck closed/shut`, `seized shut/closed`, `jammed shut`, `held closed` | `jammed at closed position` |
| `switch stuck on/off`, `switch stays on/off`, `won't turn off/on`, `button stuck on/off` | `switch stuck button stuck` |

The manual has only one stuck-switch record (`driver demand regeneration button stuck`,
P2458-09) and draws **no on/off distinction**, so both switch polarities normalise to the same
wording; the trace records which fired.

### 3. A compound token for actuator state (index-side, experimental index only)

R2 alone was **inert where it matters**, for a measurable reason: `open` is pervasive in this
corpus — `open circuit` / `open load` appear in 25+ records — so its IDF is near-worthless,
while `closed` is rare. The word that carries the state carries almost no weight.

This is exactly the problem Phase 8.2b solved for cylinder digits, so the same documented
mechanism is applied: fold the manual's own phrase `jammed|stuck at|in <open|closed> position`
into one token `jammed_open` / `jammed_closed`, at index and query time, behind a new
`--state-token` flag recorded in the index metadata and read back by the Retriever exactly as
`cylinder_compound` is. **Default off, so the production index and tokeniser are unaffected**
(asserted by a test).

Honest note: this fold produced **no DEV change at all** (0.704 either way). It is retained on
mechanism grounds — it makes the state match exactly instead of competing with stray
`open circuit` tokens — and is to be judged by the independent evaluation. The build without it
is one flag away.

## Key decisions

1. **Keep every 8.2 entry verbatim.** v2 is additive; the 8.5 TEST-matching ablation
   (`exclude_test_matching=True`) still works unchanged.
2. **No `dev_driven` entries, and no tuning against d014/d015.** When the state rule left d014
   one rank worse, I did **not** adjust the lexicon to recover it: that would be exactly the
   contamination this phase exists to avoid. The regression is reported as-is.
3. **Three symptom families were deliberately left unmapped**, because the manual has no
   vocabulary for them and an alias would expand to a term with zero postings:
   - **warning lamps** (`warning light`, `dash light`, `check engine`, `MIL`): the tokens
     `lamp`, `mil` and `warning` do not occur in the BM25 corpus at all — `bm25_text()` carries
     description/cause/effect/checkpoints/circuit text but **not** the MIL field. Adding the MIL
     field would change the production index, so it is logged as future work, not done here.
   - **abnormal noises** (`knocking`, `rattle`, `whistle`, `whine`): no such tokens in the corpus.
   - **white/blue smoke**: no smoke vocabulary at all. Only *black smoke* is mapped (to
     `soot` / `particulate filter`), and that is flagged in the file as a diagnostic inference
     rather than a synonym.
4. **Duplicate-term suppression is gated on v2.** With rules enabled, a manual term already
   present in the rewritten query is not appended again (it would double-count in the BM25
   query). v1 keeps its original behaviour so production stays bit-identical.
5. **One inherited defect left alone.** `system:egr` maps to `exhaust gas recirculation`, which
   has no postings (the manual writes `EGR`). It is a verbatim 8.2 entry; changing it would
   break the "8.2 entries kept verbatim" guarantee for no measured gain.

## Results

### DEV (gold v2.2, 34 queries; 25 ranked)

| mode | n | Hit@1 C4b → v2 | Hit@5 C4b → v2 | MRR C4b → v2 |
|---|---|---|---|---|
| exact_code | 6 | 100.0% → **100.0%** | 100.0% → **100.0%** | 1.000 → **1.000** |
| near_duplicate | 7 | 100.0% → **100.0%** | 100.0% → **100.0%** | 1.000 → **1.000** |
| symptom | 12 | 58.3% → **58.3%** | 91.7% → **91.7%** | 0.711 → **0.704** |
| **OVERALL** | 25 | 80.0% → **80.0%** | 96.0% → **96.0%** | 0.861 → **0.858** |

Hit@3 is the only other movement: symptom 83.3% → 75.0%, overall 92.0% → 88.0%.

**Exactly one query changed rank.** Per-query rows: `data/experiments/10_1/dev_rows.json`.

| id | query | expected | C4b | v2 |
|---|---|---|---|---|
| d014 | *exhaust recirculation flap is seized shut* | P042F-00 (EGR jammed closed) | **3** | **4** |

Cause: R2 correctly identifies the **state** (closed) and lifts all three jammed-closed records
— P04A5-00 (exhaust throttle), P22CF-73 (boost actuator), P042F-00 (EGR) — but it cannot pick
the **actuator**. The query's word *exhaust* ("exhaust recirculation") matches the exhaust-throttle
records lexically, so P22CF-73 moved ahead of the correct EGR record. The rules disambiguate
open-vs-closed, not which valve.

d015 (*"…seized and refuses to shut"* → P042E-00, jammed **open**) stayed at rank 2 in both
configurations. R2a fires and `jammed_open` matches P042E-00 exactly, but P042F-00 still wins on
**both** rankers (dense rank 1, BM25 rank 1) through other shared terms. Pushing past that would
have meant tuning on a DEV query, so it was left.

### Near-duplicate guardrails — 14/14, no regression

Both configurations pass all 14. `data/experiments/10_1/guardrails.json`. This is the gate that
rejected C5/C6 in Phase 8.2, and the one that matters most here, because v2 attaches aliases to
far more records (2,092 alias tokens across 314 records, averaging 6.7; 67 records receive none).

### Gate — unchanged, thresholds untouched

| check | C4b | v2 |
|---|---|---|
| out-of-scope refused | 6/6 | **6/6** |
| in-scope passed | 28/28 | **28/28** |

The gate tokenises the **raw** query, so the rewrite rules cannot move it either way.

### Contamination audit

| audit | result |
|---|---|
| `dev_driven` entries | **0** |
| v2-authored colloquial terms | 174 |
| …coinciding with **TEST** wording | **2**: `position feedback` (term:position sensor), `starter` (term:starter motor) |
| …coinciding with **DEV** wording | 3: `injectors`, `charge pressure`, `too many volts` |
| pre-existing 8.2 entries matching TEST wording | 20 (the known 8.5 ablation set) |
| independent technician query set present in repo | **no** (asserted by test) |

Both flags are *computed* from gold query text, never hand-set. The coincidences are standard
vocabulary, not copied queries, and all remain ablatable via `Lexicon(exclude_test_matching=True)`.

### Freeze — `data/experiments/10_1/freeze.json`

| sha256 | file |
|---|---|
| `af18bedd591ea15ea83b03e91d3e242eadba411e9961b6aa6551ea39a245842b` | `data/domain_lexicon_v2.json` |
| `1d1d3ab832aae0806d6123e254cd0ce107dc52d46d2eff50bba33ecc6d7745ca` | `src/lexicon.py` |
| `c81f6d81d5ff072ad2e51516f05eda71ae63a7910821d846c01bf4059be9916a` | `src/build_index.py` |
| `e5c2b0ffac1d038025178abf4dc59a250252d8a25c88d8204c56fb20ac566d71` | `scripts/build_lexicon_v2.py` |
| `104824b2cea3451b769a81098a6ded30e379d3c6de70c1d5da65517534cef7a1` | `index_exp/minilm_lexv2/bm25_corpus.json` |

Re-running `scripts/freeze_10_1.py` verifies rather than overwrites and exits non-zero if any
file changed. **From this commit the lexicon and rules may not change until the independent
evaluation has been run.**

### Production integrity

| check | result |
|---|---|
| `index/bm25_corpus.json` md5 | unchanged across both experimental builds |
| suite | 44 passed / 1 xfail / 0 failed |
| determinism `--defaults` | `ffff9bc707d8754d` |
| advise / code-hardening / normalize tests | 13/13 · 23/23 · 21/21 |

## Files

| file | role |
|---|---|
| `data/domain_lexicon_v2.json` | the 88-entry lexicon (new) |
| `scripts/build_lexicon_v2.py` | deterministic builder (new) |
| `src/lexicon.py` | R1/R2 rules, `query_rules` gating, traced `expand_query` (modified) |
| `src/build_index.py` | `--state-token` and the `jammed_<state>` fold (modified, default off) |
| `src/retrieve.py` | reads `state_compound` from index metadata (modified) |
| `src/test_lexicon_v2.py` | 79 unit tests (new) |
| `scripts/freeze_10_1.py` | freeze + verify (new) |
| `index_exp/minilm_lexv2/` | the experimental index (gitignored, rebuildable) |
| `data/experiments/10_1/` | `dev_c4b.json`, `dev_lexv2.json`, `dev_rows.json`, `guardrails.json`, `freeze.json` |

Reproduce:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_lexicon_v2.py
PYTHONPATH=src .venv/bin/python src/build_index.py --rebuild \
  --index-dir index_exp/minilm_lexv2 --aliases bm25 --cylinder-token --state-token \
  --lexicon data/domain_lexicon_v2.json
PYTHONPATH=src .venv/bin/python src/evaluate_v2.py --split DEV \
  --index-dir index_exp/minilm_lexv2 --lexicon data/domain_lexicon_v2.json --expand bm25
```

## Limitations

1. **No measured DEV gain.** v2 is −0.007 symptom MRR, i.e. one rank position. v2 was authored
   blind to DEV, so DEV cannot confirm it either way; this is a coverage and mechanism change
   whose value is an open question until the independent set is run. It is **not** evidence of
   improvement, and should not be reported as such.
2. **State rules disambiguate the state, not the actuator.** Three jammed pairs share the same
   state wording, so a query naming one actuator colloquially ("exhaust recirculation") still
   competes lexically with the others ("exhaust throttle"). This cost d014 one rank.
3. **`jammed_<state>` fold is unvalidated.** Zero DEV effect; retained on mechanism grounds only.
4. **Warning lamps, noises and smoke colour remain unreachable** (§Key decisions 3). Lamp
   queries in particular are a plausible technician phrasing with no lexical target at all —
   the most likely source of independent-set misses. Fixing it means adding the MIL field to
   `bm25_text()`, which changes the production index and so belongs to a later phase.
5. **Alias breadth is a precision risk not visible on 12 DEV symptom queries.** v2 attaches 6.7
   alias tokens per record on average. Guardrails cover only the injector and cam/crank
   families; other near-duplicate families have no guardrail.
6. **Hand-curated and English-only**, as in 8.2. 88 entries cannot cover an open vocabulary.
7. **Not adopted as production.** v2 lives in `index_exp/minilm_lexv2` as a selectable
   configuration, exactly as C4/C4b did before 8.5. Adoption needs the independent evaluation.

---

# Phase 10.1b — Making warning-lamp language reachable

_2026-10-25 · branch `phase10-demo` · additive, **production default still unchanged** · independent technician set still not read_

## Objective

10.1 limitation 4: the tokens `lamp`, `mil` and `warning` have **no postings** in the BM25
corpus, because `bm25_text()` omits the MIL field. "Check engine light on" — a very likely
technician phrasing — had no lexical target at all. 10.1b gives it one, as a selectable config.

## Headline

**The feature works mechanically and costs DEV accuracy.** Lamp wording now reaches a real
token, no guardrail or gate decision changes, and DEV symptom MRR drops 0.704 → **0.649**
because that token sits in 62% of the corpus. On this evidence I would **not** adopt it as the
default; it is frozen as a selectable config for the independent evaluation to judge.

## Method

### 1. Lamp state as an index property — `--lamp-field`

`build_index.lamp_token(r)` maps each record's MIL field to one compound token, appended to its
BM25 text: **`mil_on` for 195 records, `mil_off` for 119** (all 314 resolve; the `ON` spelling
variant is normalised). Recorded in `meta.json` and `bm25_corpus.json` as
`tokenizer.lamp_field` and read back by `Retriever.lamp_field`, exactly like
`cylinder_compound` and `state_compound`, so index and query tokenisation cannot diverge. The
token is literal, so it needs no query-side fold: the lexicon supplies it.

**Only the token is appended, not prose.** Writing "Lamp state: mil_on" would have given the
words *lamp* and *state* postings in all 314 records — pure noise with no discriminating value.
Lamp wording therefore reaches the corpus solely through the lexicon entries below.

Verified: the lamp corpus differs from the plain v2 corpus by **exactly one `mil_on`/`mil_off`
token per record and nothing else** (asserted by test). `index/` is untouched (md5 unchanged).

### 2. Lexicon entries — 88 → 91 entries

Three new description-level entries, `origin: phase10.1b`:

| provenance | colloquial → manual |
|---|---|
| `sae_j1939` | malfunction indicator lamp, malfunction lamp, MIL on, MIL illuminated, MIL is on → **`mil_on`** |
| `general_technician` | check engine light, engine light, engine management light, engine warning light, dashboard light, dash light, dash warning light, warning lamp, warning light, amber warning light, lamp glowing, lamp is on, light stays on, light on the dash, telltale lamp → **`mil_on`** |
| `general_technician` | no warning light, no warning lamp, light does not come on, lamp not glowing, no dash light → **`mil_off`** |

Counts: 30 `manual_term`, 23 `sae_j1939`, 38 `general_technician`, **0 `dev_driven`**.

These are the only entries whose manual side is a synthetic index token rather than manual
prose. Two consequences, both verified by test:

- **They are query-side only.** `record_aliases()` triggers on a record's *description*, and no
  description contains `mil_on`, so they attach to **no record**. The plain v2 corpus is
  token-identical with or without them.
- **They are inert on a non-lamp index**: `mil_on` simply has no postings, so the expansion is a
  no-op rather than a distortion.

### 3. Smoke colour and noises — still not added

Unchanged from 10.1 and logged as a limitation. The brief's condition ("only if correct for
EVERY record it attaches to") cannot be met: `noise`, `knock`, `rattle`, `whistle` and `smoke`
have no postings, and there is no field — unlike MIL — from which a smoke or noise token could
be derived. The one existing inference (*black smoke* → `soot`/`particulate filter`) stays
flagged as an inference.

## Results — DEV (gold v2.2), three configurations

| mode | n | metric | C4b (production) | v2 | **v2 + lamp** |
|---|---|---|---|---|---|
| exact_code | 6 | Hit@1 / Hit@5 / MRR | 100% / 100% / 1.000 | 100% / 100% / 1.000 | 100% / 100% / **1.000** |
| near_duplicate | 7 | Hit@1 / Hit@5 / MRR | 100% / 100% / 1.000 | 100% / 100% / 1.000 | 100% / 100% / **1.000** |
| symptom | 12 | Hit@1 | 58.3% | 58.3% | **50.0%** |
| | | Hit@5 | 91.7% | 91.7% | **91.7%** |
| | | MRR | 0.711 | 0.704 | **0.649** |
| **OVERALL** | 25 | Hit@1 | 80.0% | 80.0% | **76.0%** |
| | | Hit@5 | 96.0% | 96.0% | **96.0%** |
| | | MRR | 0.861 | 0.858 | **0.831** |

system_group 3/3 in all three. Per-query rows: `data/experiments/10_1b/dev_rows.json`.

**Exactly one query moved, and it explains the whole drop:**

| id | query | expected | v2 | v2+lamp |
|---|---|---|---|---|
| d024 | *loss of pulling power with the dash warning light on* | P0192-00 / P0193-00 / P0194-00 / P0087-00 / P0088-00 | **1** | **3** |

"dash warning light" now expands to `mil_on`, which matches 195 of 314 records. That near-uniform
boost **dilutes** the query's genuinely discriminating words ("pulling power") and lets
P0004-00 / P0003-00 (metering-unit records, MIL On) overtake the rail-pressure answers. This is
the predicted failure mode of a low-IDF token, measured rather than assumed.

Note the direction honestly: two lamp colloquialisms (`warning light`, `dash warning light`)
coincide with d024's wording, and the coincidence made that query **worse**, not better — which
is itself evidence the entries were not tuned against DEV.

### Guardrails — 14/14, no regression

| config | guardrails |
|---|---|
| v2 | 14/14 |
| **v2 + lamp** | **14/14** |

`data/experiments/10_1b/guardrails.json`. The lamp token is spread evenly across each
near-duplicate family, so it cannot re-collapse one.

### Gate — unchanged, thresholds untouched

DEV: out-of-scope refused **6/6**, in-scope passed **28/28** in all three configurations.

## The headlight test — outcome, honestly

Seven synthetic off-topic lamp queries, authored for this test and **not** from any gold set.
The decisive comparison is against production C4b:

| synthetic query | C4b | v2 | v2 + lamp | lamp alias matched? |
|---|---|---|---|---|
| my headlight bulb has fused | REFUSE d=0.170 b=1.2 | REFUSE | **REFUSE** | no |
| interior dome lamp flickering | REFUSE d=0.178 b=0.0 | REFUSE b=3.8 | **REFUSE** b=3.8 | no |
| i need a new indicator bulb | REFUSE d=0.213 | REFUSE | **REFUSE** | no |
| the dashboard light stays on | REFUSE d=0.200 b=2.9 | REFUSE | **REFUSE** b=2.9 | **yes → mil_on** |
| the number plate light is not working | PASS d=0.285 b=11.9 | PASS | **PASS** b=11.3 | no |
| check engine light is on | PASS d=0.360 b=8.1 | PASS | **PASS** b=8.1 | **yes → mil_on** |
| warning lamp glowing but engine runs fine | PASS d=0.304 b=7.5 | PASS | **PASS** b=7.3 | **yes → mil_on** |

**Every gate verdict is identical in all three configurations** (asserted by test). Three findings:

1. **The lamp token rescues nothing.** `my headlight bulb has fused` is still refused: *headlight*
   is not an alias, so no lamp token enters the query.
2. **A lamp-alias-only query is not answered from the lamp token alone.** `the dashboard light
   stays on` matches two lamp aliases and does inject `mil_on`, yet `bm25_max` stays at **2.9**
   and the gate still refuses. Because `mil_on` occupies 62% of the corpus, BM25Okapi floors its
   negative IDF, so it contributes almost no score. The token makes lamp wording *reachable*; it
   does not make it *persuasive*.
3. **Two probes do pass, and that is pre-existing, not caused by 10.1b.** `check engine light is
   on` (dense 0.360) and `the number plate light is not working` (dense 0.285, bm25 11.9) pass
   the gate identically under production C4b. They are carried by **dense** similarity to engine
   wording, not by the lamp token, and the answers returned are unrelated DTCs (P0335-00,
   P0340-00). This is an honest pre-existing gate weakness on body-electrical phrasing, outside
   10.1b's scope and not fixed by it.

## Freeze — `data/experiments/10_1b/freeze.json` (supersedes 10.1; 10.1 kept)

| sha256 | file |
|---|---|
| `c6c9fec5188dc2a85d3e2834dbe285b562bf63352fd349299a76b0ee1f61b6e9` | `data/domain_lexicon_v2.json` |
| `1d1d3ab832aae0806d6123e254cd0ce107dc52d46d2eff50bba33ecc6d7745ca` | `src/lexicon.py` |
| `971b8433351cd286f0d6641dbae46cd5f2cc6edc1a0e8e66176edf5947fb0492` | `src/build_index.py` |
| `02ea857e8b575e3d4cd8221a2dccbfe72cd3441b8100da00f5febcb53aa2d970` | `scripts/build_lexicon_v2.py` |
| `97e11150a63c3ae24a382b99f8871d81d8e86d902b58a2ecb67d8e6ad9e9964e` | `index_exp/minilm_lexv2/bm25_corpus.json` |
| `f0eec8cded1ddbd891db79f5fa7edca6a0b219841efd18caef46b2736509bd5b` | `index_exp/minilm_lexv2_lamp/bm25_corpus.json` |

`scripts/freeze_10_1.py` now writes/verifies the 10.1b file and names the 10.1 file it
supersedes. Re-running verifies instead of overwriting: all 6 PASS.

## Production integrity

| check | result |
|---|---|
| `index/bm25_corpus.json` md5 | unchanged |
| production index `lamp_field` | **false** (asserted by test) |
| suite | **44 passed / 1 xfail / 0 failed** |
| determinism `--defaults` | **`ffff9bc707d8754d`** |
| `src/test_lexicon_v2.py` | **102/102** (79 from 10.1 + 23 lamp tests) |

## Files added or changed in 10.1b

| file | change |
|---|---|
| `src/build_index.py` | `lamp_token()`, `--lamp-field`, `tokenizer.lamp_field` metadata |
| `src/retrieve.py` | reads `lamp_field` as an index property |
| `scripts/build_lexicon_v2.py` | 3 lamp entries, `origin: phase10.1b` |
| `data/domain_lexicon_v2.json` | 88 → 91 entries |
| `src/test_lexicon_v2.py` | +23 tests (lamp token, query-side-only, synthetic probes) |
| `scripts/freeze_10_1.py` | freezes both corpora, writes `10_1b/freeze.json` |
| `index_exp/minilm_lexv2_lamp/` | new experimental index (gitignored) |
| `data/experiments/10_1b/` | `dev_c4b.json`, `dev_v2.json`, `dev_v2lamp.json`, `dev_rows.json`, `guardrails.json`, `freeze.json` |

Reproduce:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_lexicon_v2.py
PYTHONPATH=src .venv/bin/python src/build_index.py --rebuild \
  --index-dir index_exp/minilm_lexv2_lamp --aliases bm25 --cylinder-token --state-token \
  --lamp-field --lexicon data/domain_lexicon_v2.json
PYTHONPATH=src .venv/bin/python src/evaluate_v2.py --split DEV \
  --index-dir index_exp/minilm_lexv2_lamp --lexicon data/domain_lexicon_v2.json --expand bm25
```

## Limitations added in 10.1b

1. **The lamp token cannot discriminate, by construction.** MIL is On for 195/314 records, so
   `mil_on` covers 62% of the corpus and its negative IDF is floored by BM25. It gives lamp
   wording a target; it cannot rank with it. A genuinely useful lamp signal needs a *combination*
   (lamp state + subsystem) or a structured filter, not a bag-of-words token.
2. **It measurably hurts mixed queries.** A query combining lamp wording with a real symptom
   (d024) loses precision because the lamp term dilutes the discriminating terms. On DEV that is
   −0.055 symptom MRR, worse than the −0.007 of v2 alone.
3. **CEL / Immo / IC-message fields are still unreachable.** The same mechanism would extend to
   `cel_on`/`cel_off` (On for 113, Off for 200), and `immo_lamp` / `ic_message` are `NA`/`None`
   for all 314 records and carry no information at all.
4. **Body-electrical questions can still pass the gate** (`check engine light is on`,
   `the number plate light is not working`) on dense similarity alone. Pre-existing, identical
   under production, and not addressed here.
5. **Smoke colour and abnormal noises remain unreachable** — no postings and no field to derive
   a token from.
