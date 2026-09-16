# Phase 8.0 — Evaluation Foundation (+ 8.1 L2 fixes)

Phase 8 iterates on the limitations recorded in Phase 7. Before changing anything,
the working system was snapshotted and a stronger evaluation foundation was built,
so every later improvement is measured against a fixed, honest before-picture.

## Snapshot

`v1-phase7` is an annotated tag on commit `dbf944b` — the complete, evaluated Phase 7
system (MRR 0.685), pushed to origin and recoverable with `git checkout v1-phase7`.
All Phase 8 work is on the `phase8-limitations` branch.

---

## 8.0 — Gold set v2.1

### Objective

Replace the 38-query v1 set, too small to separate signal from noise on the weak
modes, with a larger set weighted toward those modes plus a held-out TEST split that
tuning never touches.

### Design

**70 queries** in `data/gold_v2.json` (version **v2.1**), schema
`{id, query, mode, expected, split, notes}` (+ `expected_system` for grouping).

| mode | DEV | TEST | total |
|---|---|---|---|
| exact_code | 6 | 6 | 12 |
| near_duplicate | 7 | 7 | 14 |
| **symptom** | 12 | 13 | **25** |
| system_group | 3 | 4 | 7 |
| **out_of_scope** | 6 | 6 | **12** |
| **total** | **34** | **36** | **70** |

Weighted toward **symptom** (weakest mode) and **out_of_scope**, which now includes
vehicle-adjacent commercial questions — warranty, price and resale value, service
booking and hours, parts availability — the class that leaked through the gate in
Phase 7.

### The word-overlap rule

**A symptom query may share at most 0.15 content-word overlap with its expected
DTC's description.** This **supersedes** the v2.0 whole-description substring check,
which proved too weak: it passed every original TEST query while those queries reused
2.5× more manual vocabulary than DEV's.

Definition (`src/gold_overlap.py`, the single source of truth):

```
overlap(query) = |content(query) ∩ content(description)| / |content(query)|
                 maximised over the query's expected codes
```

- `content()` lowercases, keeps alphanumeric tokens of length ≥ 2, and drops **English
  function words only**. Domain nouns — *sensor, circuit, signal, pressure* — are
  deliberately **not** stopwords: they are exactly the manual vocabulary a query must
  avoid.
- A crude stem (strip one of *-ing/-ed/-s*, then a trailing *-e*) merges
  *cranking/cranked*, *valve/valves*. It can only merge forms, so it makes the ceiling
  **stricter**, never looser.
- Taking the max over expected codes is the most lenient reading, so the ceiling is
  conservative.

Authors should prefer technician vocabulary — *speedo, intercooler, redline, soot
trap, earthed* — over manual nouns. `src/check_gold.py` enforces the rule: it **fails**
on any TEST symptom query over the ceiling and **warns** on DEV (see below). It uses
only the gold set and manual records, never retrieval, so it is safe to run while
authoring a frozen split.

### Other authoring rules

| rule | enforcement |
|---|---|
| Expected answers come from the manual, never from system output | every expected code asserted to exist (`check_gold.py`) |
| No duplicate ids or queries | asserted |
| Concepts already inspected in Phase 7 → **DEV only** | manual |
| TEST uses only DTCs **never** run through the system | manual |
| Retrieval **never** run on a TEST query while authoring it | manual, including the v2.1 rewrites |

### Why TEST is frozen

A held-out split measures generalisation only if no decision is ever made by looking
at it. Once a TEST miss informs a change, TEST becomes a second DEV set and its numbers
turn optimistic. Tuning therefore looks at **DEV only**; TEST is run only to record a
before-picture and a final after-picture. `src/evaluate_v2.py` enforces this at the
output level: per-query misses for DEV, **aggregates only** for TEST.

---

## The TEST split correction (v2.0 → v2.1)

### What was wrong

The first baseline showed symptom hit@1 of **25.0% on DEV but 76.9% on TEST** — on the
very mode Phase 8 exists to improve. The cause was authoring bias: DEV inherited Phase
7's deliberately hard paraphrases (*flap, seized, soot trap*), while the freshly
written TEST queries kept manual nouns (*metering unit, fuel pump relay, clutch
switch*). A synonym layer would have looked weak on that TEST split because TEST barely
needed synonyms.

It was diagnosed and fixed **without inspecting any TEST system output** — only by
measuring each query against its own expected description.

> **Correction to the earlier figures:** v2.0 of this report gave DEV's mean overlap
> as 0.12 and 5/12 zero-overlap. That used an ad-hoc stoplist that silently excluded
> manual nouns (*signal, sensor, circuit*). Under the documented metric DEV is **0.168,
> 4/12 zero**. TEST's figure is essentially unchanged (0.412). The conclusion stands —
> TEST was ~2.5× easier — but the numbers above are the correct ones.

### What was changed

Decision: rewrite **only the 13 TEST symptom queries** (t048–t060) under the ceiling,
keeping the same expected DTCs. No other TEST item was touched — the near-duplicate
set (NOx upstream/downstream heater, urea main/return pump) is legitimately hard and
fair. Retrieval was not run on any rewrite; each was scored by the overlap metric alone.

| id | old query (biased) | old overlap | new query (v2.1) | new overlap | expected |
|---|---|---|---|---|---|
| t048 | there is water contamination in the diesel filter | 0.500 | moisture got into the diesel and the separator warning keeps coming on | **0.000**  | P2264-00, P2264-12 |
| t049 | truck refuses to fire up and the metering unit output is grounded | 0.571 | truck won't fire, quantity valve output lead is earthed | **0.125** ['output'] | P0003-00 |
| t050 | the fuel pump relay coil has an open circuit | 0.833 | fuel lift switching unit coil wire has snapped | **0.143** ['fuel'] | P0627-13 |
| t051 | the diesel exhaust fluid has frozen solid | 0.200 | the adblue has turned to solid ice after a freezing night | **0.000**  | P10FF-00 |
| t052 | the reduction catalyst has worn out and lost its efficiency | 0.200 | scr nox cleaning brick has aged out and stopped working | **0.143** ['scr'] | P20EE-00 |
| t053 | engine is spinning faster than its permitted maximum | 0.200 | engine screaming past the redline, rev needle in the red | **0.143** ['engin'] | P0219-00 |
| t054 | too much ash has built up in the particulate filter | 0.250 | burnt residue has packed the exhaust soot trap solid and it cannot be cleared by burning | **0.000**  | P242F-00 |
| t055 | the regeneration request switch on the dash is stuck down | 0.400 | the dash burn-off switch the driver presses seems jammed in | **0.143** ['driver'] | P2458-09 |
| t056 | intake charge cooler is not cooling effectively | 0.400 | intercooler barely dropping intake air temps on climbs | **0.143** ['air'] | P026A-00 |
| t057 | road speed reading does not make sense | 0.200 | speedo needle jumps about and does not match how fast we are really going | **0.000**  | P0500-1F |
| t058 | no fuel pressure builds up while cranking the engine | 0.600 | cranks on the starter but the injection side never comes up to strength | **0.143** ['crank'] | P00C6-00 |
| t059 | clutch switch signal does not make sense | 0.400 | the clutch pedal contact tells the ECU nonsense about whether it is pressed | **0.143** ['clutch'] | P0704-29 |
| t060 | the starter motor control line is broken | 0.600 | cranking solenoid trigger wire from the ECU to the starter has snapped | **0.143** ['starter'] | P0A1B-13 |

### Symptom word-overlap audit (per split)

| split | symptom n | mean overlap | zero-overlap | max | over ceiling (0.15) |
|---|---|---|---|---|---|
| DEV | 12 | **0.168** | 4/12 | 0.400 | 8 ⚠ |
| TEST v2.0 (biased) | 13 | 0.412 | 0/13 | 0.833 | 13 |
| **TEST v2.1** | 13 | **0.098** | **4/13** | 0.143 | **0** |

**Why TEST sits slightly below DEV rather than on it.** A 0.15 ceiling on every query
caps the mean at 0.15, and holding ~4 zero-overlap queries (to match DEV's 4/12) caps
it near **0.10**. DEV's 0.168 is only reachable because **8 of its 12 queries exceed the
ceiling** — they predate the rule. TEST now matches DEV's zero-overlap count exactly
and is marginally harder on mean; the residual gap (0.07) is a quarter of the original
(0.31).

**DEV's 8 over-ceiling queries are grandfathered, not fixed** — DEV is unchanged by
decision. `check_gold.py` reports them as warnings: d015, d017, d018, d019, d020, d021,
d023, d025. Bringing them under the ceiling would make DEV and TEST difficulty match
exactly; it would also change the DEV baseline. Left open for review.

---

## Baselines — the unchanged v1-phase7 retrieval system

Retrieval stack exactly as tagged (`git diff v1-phase7` on `retrieve.py`, `answer.py`,
`build_index.py` is empty). The 8.1 changes touch `diagnose.py` only and cannot move
these numbers.

### DEV (34 queries) — unchanged by v2.1

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 71.4% | 85.7% | 100.0% | 0.821 |
| symptom | 12 | 25.0% | 58.3% | 66.7% | 0.396 |
| **OVERALL** | 25 | **56.0%** | 76.0% | 84.0% | **0.660** |

- system_group complete: **3/3**
- out-of-scope correctly gated: **4/6**
- in-scope passed the gate: **26/28**

Re-running on v2.1 reproduced every DEV figure **exactly** (by-mode, overall and gate
counts all identical to the v2.0 run), confirming the evaluation is deterministic and
DEV was untouched.

### TEST (36 queries, frozen v2.1 — aggregates only)

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 42.9% | 100.0% | 100.0% | 0.690 |
| symptom | 13 | 23.1% | 30.8% | 46.2% | 0.291 |
| **OVERALL** | 26 | **46.2%** | 65.4% | 73.1% | **0.562** |

- system_group complete: **4/4**
- out-of-scope correctly gated: **3/6**
- in-scope passed the gate: **29/30**

### What the correction did to TEST

| TEST symptom | v2.0 (biased) | **v2.1 (corrected)** | DEV (reference) |
|---|---|---|---|
| hit@1 | 76.9% | **23.1%** | 25.0% |
| hit@3 | 92.3% | **30.8%** | 58.3% |
| hit@5 | 92.3% | **46.2%** | 66.7% |
| MRR | 0.821 | **0.291** | 0.396 |

TEST symptom hit@1 now sits at **23.1%, level with DEV's 25.0%**.
Deeper in the ranking TEST is harder (hit@5 46.2% vs 66.7%), consistent
with its lower overlap. TEST overall moved 73.1% → **46.2%** hit@1 and MRR
0.827 → **0.562**. **This is the honest before-picture Phase 8 improves against.**

The in-scope gate count moved 30/30 → **29/30**: one rewritten symptom query is now
refused by the relevance gate — expected, since the gate also keys on lexical overlap.
Which query is deliberately not inspected.

The v2.0 baseline is kept as `data/baseline_v2_biased_test.json` for the audit trail.

---

## 8.1 — Fixing the `skip_true_branch` mismatches (L2)

### Objective

Phase 7 audited the `skip_true_branch` inference at 96% correct and listed six
corpus-wide mismatches. Fix them with an explicit, auditable override, without
weakening the general rule anywhere else.

### Correction to the Phase 7 count: 5 genuine mismatches, not 6

Each case was verified against the actual steps before any change. **Five fit the
mismatch shape; one does not.**

The five share one shape:

```
s6: "If error still present go to Step 7"      <- the step
s7: "Check the wire harness for ... back-out"  <- true target is a CHECK
s8: "Fix the back-out cables ..."              <- where the old rule landed
```

Answering *no* means the error is **gone**, so the walk must terminate. The old rule
skipped to s8 and applied a fix for a check never performed.

**P0194-00 step 7 is not a mismatch.** Its true target s8 is the **fix**, and the skip
lands on s9, *"Change the rail pressure sensor with new one."* Because s8 jumps to s10,
**s9 is reachable only via "no back-out found"** — the manual's intended remedy when the
wiring is fine. Overriding it would end the procedure before its repair step. It was a
false positive from the Phase 7 detector, which flagged any skip landing on a step
beginning with a fix *verb*, and is pinned by a regression test instead. Phase 7's
corpus figure is corrected to **5 cases (2.0%)**; its 24/25 audit match rate is
unaffected.

### Implementation

`MANUAL_CORRECTIONS` in `src/diagnose.py`, keyed by `(code_full, step)`:

| code_full | step | page | on "no" |
|---|---|---|---|
| P0192-00 | 6 | 8 | → terminal |
| P0193-00 | 6 | 10 | → terminal |
| P0194-00 | 6 | 12 | → terminal |
| P0627-11 | 4 | 184 | → terminal |
| P0627-13 | 4 | 186 | → terminal |

- Checked **before** the general rule, which runs unchanged for every other step.
- The **page is recorded and asserted**: codes are not unique keys in this manual, so an
  override must never attach to a same-coded record on another page.
- Each firing is logged as `manual_correction` — same visibility as a clamp or inference.

### Regression results

| test | result |
|---|---|
| P0192-00 s6: "no" → terminal s13 (old rule → s8) | ✅ correction logged |
| P0193-00 s6: "no" → terminal s13 (old rule → s8) | ✅ correction logged |
| P0194-00 s6: "no" → terminal s10 (old rule → s8) | ✅ correction logged |
| P0627-11 s4: "no" → terminal s11 (old rule → s6) | ✅ correction logged |
| P0627-13 s4: "no" → terminal s11 (old rule → s6) | ✅ correction logged |
| **P0194-00 s7 (not overridden)**: "no back-out" → s9 change sensor | ✅ no correction; inference fires |
| **General rule unweakened**: correction fires at none of the 251 other candidate steps | ✅ |

**Full suite: 37 passed, 1 xfail, 0 failed** (was 30/1/0). Corpus-wide walk: still
**0 dead ends**; inferences 326 → **321** and corrections fired **5** — each correction
replaced exactly one inference.

---

## Evidence & Artifacts

- [data/gold_v2.json](../../data/gold_v2.json) — v2.1, 70 queries, `revisions` block records every rewrite
- [src/gold_overlap.py](../../src/gold_overlap.py) — the overlap metric (single definition)
- [src/check_gold.py](../../src/check_gold.py) — authoring-rule validator
- [data/baseline_v2.json](../../data/baseline_v2.json) — v2.1 baselines + overlap stats
- `data/baseline_v2_biased_test.json` — the v2.0 baseline, kept for audit
- [src/evaluate_v2.py](../../src/evaluate_v2.py) — split-aware evaluator (TEST aggregates only)
- [src/diagnose.py](../../src/diagnose.py) — `MANUAL_CORRECTIONS`
- `src/evaluate.py` left byte-identical so v1 numbers remain reproducible

## Limitations

- **DEV has 8 grandfathered queries over the overlap ceiling**, so DEV is marginally
  *easier* than TEST on mean overlap (0.168 vs 0.098). Expect tuning gains measured on
  DEV to be slightly larger than on TEST for that reason alone.
- **The gold set is self-authored.** The v2.0 bias is concrete evidence that an
  independent author would improve it.
- **Small cells.** 6–13 queries per mode per split: one query moves hit@1 by 8–17
  points. Treat differences under ~2 queries as noise.
- **The overlap metric is lexical.** It stops manual-noun leakage but cannot detect a
  query that is easy for *semantic* reasons.
- **`MANUAL_CORRECTIONS` is a hand-maintained list of five.** The page assertion prevents
  mis-attachment, but a parser change that renumbers steps would orphan an entry.

## Full gold set (v2.1)

### DEV

**exact_code** (6)

| id | query | expected | notes |
|---|---|---|---|
| d001 | what does P0192-00 mean | P0192-00 | full code; seen in v1 |
| d002 | P0340 | P0340-00 | base code, no suffix |
| d003 | P0180-11 | P0180-11 | DUPLICATE: two records, pp.100 & 195 |
| d004 | P0100 | P0100-00, P0100-9B, P0100-9C | base code, 3 variants |
| d005 | details for U0102-00 | U0102-00 | U-family CAN code |
| d006 | fault code P2264 | P2264-00, P2264-11, P2264-12 | base code, 3 variants; new |

**near_duplicate** (7)

| id | query | expected | notes |
|---|---|---|---|
| d007 | the cam sensor gives no output whatsoever | P0340-00 | vs P0341-00 |
| d008 | cam position reading is erratic and noisy | P0341-00 | vs P0340-00 |
| d009 | fuel rail sender pulled down to earth | P0192-00 | rail trio |
| d010 | fuel rail sender reading has drifted off calibration | P0194-00 | rail trio |
| d011 | number three injector has a broken winding | P0203-00 | cylinder 1-4 |
| d012 | cylinder one injector is shorted to the main feed | P2147-00 | vs P0201-00 |
| d013 | crank position reading is noisy and unstable | P0336-00 | crank vs cam |

**symptom** (12)

| id | query | expected | overlap | notes |
|---|---|---|---|---|
| d014 | exhaust recirculation flap is seized shut | P042F-00 | 0.000 | flap/seized vs valve/jammed |
| d015 | exhaust recirculation flap is seized wide open | P042E-00 | 0.167 ⚠ | jammed open |
| d016 | soot trap is completely blocked up | P244B-00 | 0.000 | soot trap vs DPF |
| d017 | adblue tank has almost run dry | P203F-00, P203F-7B | 0.250 ⚠ | urea level low |
| d018 | coolant gauge stuck reading at the bottom of the scale | P0117-00 | 0.167 ⚠ | short to ground |
| d019 | the wire to the engine temperature sender has gone open | P0118-00 | 0.333 ⚠ | open circuit |
| d020 | throttle pedal sensors do not agree with each other | P2135-00 | 0.250 ⚠ | pedal plausibility |
| d021 | supply voltage is reading above the permitted ceiling | P0562-00 | 0.200 ⚠ | battery max |
| d022 | charge pressure from the turbo is under target | P0047-00, P004C-00, P006E-00 | 0.000 | ambiguous; any boost-low code |
| d023 | engine will not crank up and there is no signal from the cam | P0340-00 | 0.250 ⚠ | no-start effect |
| d024 | loss of pulling power with the dash warning light on | P0192-00, P0193-00, P0194-00, P0087-00, P0088-00 | 0.000 | torque loss + MIL; rail family |
| d025 | battery voltage keeps dipping under what the ECU will accept | P0563-00 | 0.400 ⚠ | battery min; new |

**system_group** (3)

| id | query | expected | notes |
|---|---|---|---|
| d026 | list all EGR faults | `egr` (14 codes) | grouping intent |
| d027 | show me every injector related fault code | `injector` (14 codes) | grouping intent |
| d028 | what soot trap faults are there | `dpf_regen` (18 codes) | paraphrased subsystem word |

**out_of_scope** (6)

| id | query | expected | notes |
|---|---|---|---|
| d029 | how do I change a tyre | none | previously produced a FABRICATED tyre-pressure answer |
| d030 | what is the warranty period on this engine | none | vehicle-adjacent commercial; leaked in Phase 7 |
| d031 | how much does this truck cost | none | price |
| d032 | book me a service appointment | none | service booking |
| d033 | are replacement injectors in stock at the dealer | none | parts availability; new |
| d034 | what is the capital of France | none | general knowledge |

### TEST — FROZEN (v2.1)

**exact_code** (6)

| id | query | expected | notes |
|---|---|---|---|
| t035 | what is P0627-12 | P0627-12 | full code |
| t036 | P0401 | P0401-00 | base code, single variant |
| t037 | P0180-12 | P0180-12 | DUPLICATE: two records, pp.102 & 197 |
| t038 | give me the procedure for P20EE-00 | P20EE-00 | code inside a sentence |
| t039 | P2458 | P2458-00, P2458-09 | base code, 2 variants |
| t040 | trouble code U011A-89 | U011A-89 | U-family, suffixed |

**near_duplicate** (7)

| id | query | expected | notes |
|---|---|---|---|
| t041 | EGR position feedback line reads too low or is broken | P0405-00 | vs P0406-00 high |
| t042 | EGR position feedback voltage is stuck too high | P0406-00 | vs P0405-00 low |
| t043 | the upstream NOx probe heater is not available | P2205-00 | vs P22A3-00 downstream |
| t044 | the downstream NOx probe heater is not available | P22A3-00 | vs P2205-00 upstream |
| t045 | urea main pump has come unplugged | P208A-00 | vs backflow pump P20A0-00 |
| t046 | urea return pump has come unplugged | P20A0-00 | vs main pump P208A-00 |
| t047 | exhaust brake valve stuck in the closed position | P04A5-00 | exhaust throttle vs EGR P042F-00 |

**symptom** (13)

| id | query | expected | overlap | notes |
|---|---|---|---|---|
| t048 | moisture got into the diesel and the separator warning keeps coming on | P2264-00, P2264-12 | 0.000 | water in fuel; colloquial moisture/separator |
| t049 | truck won't fire, quantity valve output lead is earthed | P0003-00 | 0.125 | no-start; quantity valve = metering unit |
| t050 | fuel lift switching unit coil wire has snapped | P0627-13 | 0.143 | relay open; lift switching unit = pump relay |
| t051 | the adblue has turned to solid ice after a freezing night | P10FF-00 | 0.000 | frozen DEF; adblue/ice |
| t052 | scr nox cleaning brick has aged out and stopped working | P20EE-00 | 0.143 | deteriorated SCR; nox cleaning brick |
| t053 | engine screaming past the redline, rev needle in the red | P0219-00 | 0.143 | overspeed; redline/rev needle |
| t054 | burnt residue has packed the exhaust soot trap solid and it cannot be cleared by burning | P242F-00 | 0.000 | ash load; burnt residue/soot trap |
| t055 | the dash burn-off switch the driver presses seems jammed in | P2458-09 | 0.143 | regen button stuck; burn-off switch |
| t056 | intercooler barely dropping intake air temps on climbs | P026A-00 | 0.143 | CAC efficiency; intercooler |
| t057 | speedo needle jumps about and does not match how fast we are really going | P0500-1F | 0.000 | speed plausibility; speedo needle |
| t058 | cranks on the starter but the injection side never comes up to strength | P00C6-00 | 0.143 | no rail build-up; injection side never comes up |
| t059 | the clutch pedal contact tells the ECU nonsense about whether it is pressed | P0704-29 | 0.143 | clutch plausibility; pedal contact |
| t060 | cranking solenoid trigger wire from the ECU to the starter has snapped | P0A1B-13 | 0.143 | starter control open; solenoid trigger wire |

**system_group** (4)

| id | query | expected | notes |
|---|---|---|---|
| t061 | list all exhaust throttle valve faults | `exhaust_throttle` (9 codes) | grouping intent |
| t062 | show every turbocharger related code | `turbo_boost` (15 codes) | grouping intent |
| t063 | which coolant faults exist | `coolant` (4 codes) | grouping intent |
| t064 | all CAN bus network faults | `can_network` (3 codes) | grouping intent |

**out_of_scope** (6)

| id | query | expected | notes |
|---|---|---|---|
| t065 | what is the resale value of a five year old truck | none | commercial / price |
| t066 | how long is the free service period after purchase | none | service terms |
| t067 | can I get a discount on the extended warranty | none | warranty, commercial |
| t068 | where can I buy a genuine air filter nearby | none | parts availability |
| t069 | what time does the service centre open on Sunday | none | service booking / hours |
| t070 | how do I pair bluetooth with the infotainment unit | none | vehicle-adjacent, not engine DTC |
