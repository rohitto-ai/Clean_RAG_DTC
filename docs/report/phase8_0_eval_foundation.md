# Phase 8.0 — Evaluation Foundation (+ 8.1 L2 fixes)

Phase 8 iterates on the limitations recorded in Phase 7. Before changing anything,
the working system was snapshotted and a stronger evaluation foundation was built,
so every later improvement is measured against a fixed before-picture.

## Snapshot

`v1-phase7` is an annotated tag on commit `dbf944b` — the complete, evaluated Phase 7
system (MRR 0.685), pushed to origin and permanently recoverable with
`git checkout v1-phase7`. All Phase 8 work happens on the `phase8-limitations`
branch.

---

## 8.0 — Gold set v2

### Objective

Replace the 38-query v1 set, which was too small to separate signal from noise on the
weak modes, with a larger set weighted toward exactly those modes, and a held-out
TEST split that tuning can never touch.

### Design

**70 queries** in `data/gold_v2.json`, schema `{id, query, mode, expected, split,
notes}` (+ `expected_system` for grouping queries).

| mode | DEV | TEST | total |
|---|---|---|---|
| exact_code | 6 | 6 | 12 |
| near_duplicate | 7 | 7 | 14 |
| **symptom** | 12 | 13 | **25** |
| system_group | 3 | 4 | 7 |
| **out_of_scope** | 6 | 6 | **12** |
| **total** | **34** | **36** | **70** |

Weighted toward **symptom** (the weakest mode, 27.3% hit@1 in Phase 7) and
**out_of_scope**, now including the vehicle-adjacent commercial questions that leaked
through the gate in Phase 7: warranty, price and resale value, service booking and
hours, parts availability.

### Authoring rules — and how each is enforced

| rule | enforcement |
|---|---|
| Expected answers come from the manual, never from system output | Authored from the records; every expected code **asserted to exist** in the manual |
| Symptoms paraphrased, never copied from the manual | **Automated check**: no query may contain any manual description (>25 chars) as a substring |
| No duplicate queries | Asserted |
| Concepts already inspected in Phase 7 go to **DEV only** | Manual: the flap/soot-trap/camshaft/rail-trio concepts are all DEV |
| TEST uses only DTCs **never** run through the system | Manual: authored from the record survey alone |

### Why TEST is frozen

A held-out split only measures generalisation if no decision is ever made by looking
at it. The moment a TEST miss informs a change — even an innocent synonym added
because a TEST query failed — TEST becomes a second DEV set and its numbers become
optimistic.

So: tuning looks at **DEV only**; TEST is run only to record a before-picture and a
final after-picture. `src/evaluate_v2.py` enforces that at the output level: it
prints per-query misses for DEV but **only aggregates for TEST**.

---

## Baselines — the unchanged v1-phase7 system

Recorded on the retrieval stack exactly as tagged (`git diff` against `v1-phase7` on
`retrieve.py`, `answer.py` and `build_index.py` is empty). The 8.1 changes below touch
`diagnose.py` only, so they cannot move these numbers.

### DEV (34 queries)

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 71.4% | 85.7% | 100.0% | 0.821 |
| symptom | 12 | 25.0% | 58.3% | 66.7% | 0.396 |
| **OVERALL** | 25 | **56.0%** | 76.0% | 84.0% | **0.660** |

- system_group complete: **3/3**
- out-of-scope correctly gated: **4/6**
- in-scope passed the gate: **26/28**

### TEST (36 queries, frozen — aggregates only)

| mode | n | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| exact_code | 6 | 100.0% | 100.0% | 100.0% | 1.000 |
| near_duplicate | 7 | 42.9% | 100.0% | 100.0% | 0.690 |
| symptom | 13 | 76.9% | 92.3% | 92.3% | 0.821 |
| **OVERALL** | 26 | **73.1%** | 96.2% | 96.2% | **0.827** |

- system_group complete: **4/4**
- out-of-scope correctly gated: **3/6**
- in-scope passed the gate: **30/30**

---

## ⚠ Finding: TEST symptom queries are easier than DEV's — an authoring bias

The baselines disagree sharply on the one mode Phase 8 exists to improve: **symptom
hit@1 is 25.0% on DEV but 76.9% on TEST.**

This was diagnosed **without inspecting any TEST system output**, by measuring each
query against its own expected answer in the manual — the share of the query's
content words that appear in the expected DTC's description. That is a property of
the gold set and the records alone.

| split | symptom n | mean word overlap with expected description | queries sharing **zero** terms |
|---|---|---|---|
| DEV | 12 | **0.12** | **5 / 12** |
| TEST | 13 | **0.41** | **0 / 13** |

TEST symptom queries share **3.4× more vocabulary** with the manual.

**Cause:** DEV inherited Phase 7's deliberately aggressive paraphrases (*flap*,
*seized*, *soot trap*). Writing TEST fresh, the author kept key manual nouns —
*"metering unit"*, *"fuel pump relay"*, *"clutch switch"*, *"starter motor"*. One TEST
query (*"clutch switch signal does not make sense"*) shares 100% of its content words
with its expected description. The anti-copy check only catches **whole description
substrings**, so every one of these passed it.

**Why it matters:** Phase 8's next step is a synonym layer for symptom retrieval.
Against this split it would likely show a large DEV gain and a small TEST gain — not
because it fails to generalise, but because TEST barely needs synonyms. The
before/after comparison would understate the real effect and could lead to the wrong
conclusion.

**Not fixed here**, because TEST is frozen by instruction. Options for review:

1. **Re-author the 13 TEST symptom queries** to match DEV's overlap profile, re-freeze,
   re-baseline. Legitimate *now*, because no decision has yet been made using TEST;
   once tuning starts, it no longer is.
2. **Add a hard overlap ceiling** to the authoring check (e.g. ≤ 0.25 content-word
   overlap per symptom query), so the bias cannot recur.
3. **Keep TEST as is** and report symptom metrics stratified by overlap band.

Recommended: 1 + 2, before any retrieval tuning.

---

## 8.1 — Fixing the `skip_true_branch` mismatches (L2)

### Objective

Phase 7 audited the `skip_true_branch` inference at 96% correct and listed six
corpus-wide mismatches. Fix them with an explicit, auditable override — without
weakening the general rule anywhere else.

### Correction to the Phase 7 count: 5 genuine mismatches, not 6

Verifying each case against the actual steps before changing anything showed that
**five fit the mismatch shape and one does not.**

**The five genuine mismatches** share one shape:

```
s6: "If error still present go to Step 7"      <- the step
s7: "Check the wire harness for ... back-out"  <- true target is a CHECK
s8: "Fix the back-out cables ..."              <- where the old rule landed
```

Answering *no* means the error is **gone**, so the walk must terminate. The old rule
skipped to s8 and applied a fix for a check never performed.

**P0194-00 step 7 is not a mismatch.** Its true target s8 is the **fix**, not a check,
and the skip lands on s9, *"Change the rail pressure sensor with new one."* Crucially,
s8 jumps straight to s10 — so **s9 is reachable only via "no back-out found."** That is
the manual's intended remedy when the wiring is fine. Overriding it to terminate would
end the procedure before its actual repair step: a regression.

It was a **false positive from the Phase 7 detector**, which flagged any skip landing
on a step beginning with a fix *verb* ("Change…"). It has been pinned by a regression
test instead of overridden. The Phase 7 corpus figure should read **5 cases (2.0%)**,
not 6 (2.3%); the 25-sample audit's 24/25 = 96% match rate is unaffected, since that
sample's only mismatch was P0194-00 s6.

### Implementation

`MANUAL_CORRECTIONS` in `src/diagnose.py` — an explicit map keyed by
`(code_full, step)`:

| code_full | step | page | on "no" |
|---|---|---|---|
| P0192-00 | 6 | 8 | → terminal |
| P0193-00 | 6 | 10 | → terminal |
| P0194-00 | 6 | 12 | → terminal |
| P0627-11 | 4 | 184 | → terminal |
| P0627-13 | 4 | 186 | → terminal |

- Checked **before** the general rule, which runs unchanged for every other step.
- The **page is recorded and asserted**. The DTC code is not a unique key in this
  manual (P0180-11 etc. appear twice), so an override must never silently attach to a
  same-coded record on a different page.
- Every firing is logged in the trace as `manual_correction` — the same visibility as a
  clamp or an inference.

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

**Full suite: 37 passed, 1 xfail, 0 failed** (was 30 / 1 / 0 — seven new tests, zero
regressions).

**Corpus-wide walk re-run:** still **0 dead ends** across all 314 records. Inferences
fell 326 → **321** and manual corrections fired **5** times: each correction replaced
exactly one inference, so the change reconciles with no side effects.

## Evidence & Artifacts

- [data/gold_v2.json](../../data/gold_v2.json) — 70 queries, split field, TEST frozen
- [data/baseline_v2.json](../../data/baseline_v2.json) — DEV and TEST baselines
- [src/evaluate_v2.py](../../src/evaluate_v2.py) — split-aware evaluator (aggregates only for TEST)
- [src/diagnose.py](../../src/diagnose.py) — `MANUAL_CORRECTIONS`
- [src/smoke_index.py](../../src/smoke_index.py) §8 — the seven 8.1 regression tests
- `src/evaluate.py` left **byte-identical** so v1 numbers remain reproducible

## Limitations

- **TEST symptom queries are biased easy** — see the finding above. The TEST
  baseline should not be used to judge a synonym layer until this is resolved.
- **The gold set is self-authored.** The authoring bias is the concrete evidence that
  an independent author would improve it.
- **Small cells.** 6–7 queries per mode per split means one query moves hit@1 by
  ~14–17 points. Treat per-mode differences under ~2 queries as noise.
- **`MANUAL_CORRECTIONS` is a hand-maintained list of five.** It fixes the cases known
  today; a future parser change that renumbers steps would silently orphan an entry.
  The page assertion prevents mis-attachment, but not staleness.

## Full gold set (v2)

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

| id | query | expected | notes |
|---|---|---|---|
| d014 | exhaust recirculation flap is seized shut | P042F-00 | flap/seized vs valve/jammed |
| d015 | exhaust recirculation flap is seized wide open | P042E-00 | jammed open |
| d016 | soot trap is completely blocked up | P244B-00 | soot trap vs DPF |
| d017 | adblue tank has almost run dry | P203F-00, P203F-7B | urea level low |
| d018 | coolant gauge stuck reading at the bottom of the scale | P0117-00 | short to ground |
| d019 | the wire to the engine temperature sender has gone open | P0118-00 | open circuit |
| d020 | throttle pedal sensors do not agree with each other | P2135-00 | pedal plausibility |
| d021 | supply voltage is reading above the permitted ceiling | P0562-00 | battery max |
| d022 | charge pressure from the turbo is under target | P0047-00, P004C-00, P006E-00 | ambiguous; any boost-low code |
| d023 | engine will not crank up and there is no signal from the cam | P0340-00 | no-start effect |
| d024 | loss of pulling power with the dash warning light on | P0192-00, P0193-00, P0194-00, P0087-00, P0088-00 | torque loss + MIL; rail family |
| d025 | battery voltage keeps dipping under what the ECU will accept | P0563-00 | battery min; new |

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

### TEST — FROZEN

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

| id | query | expected | notes |
|---|---|---|---|
| t048 | there is water contamination in the diesel filter | P2264-00, P2264-12 | water in fuel |
| t049 | truck refuses to fire up and the metering unit output is grounded | P0003-00 | no-start |
| t050 | the fuel pump relay coil has an open circuit | P0627-13 | relay open |
| t051 | the diesel exhaust fluid has frozen solid | P10FF-00 | frozen DEF |
| t052 | the reduction catalyst has worn out and lost its efficiency | P20EE-00 | deteriorated SCR |
| t053 | engine is spinning faster than its permitted maximum | P0219-00 | overspeed |
| t054 | too much ash has built up in the particulate filter | P242F-00 | ash load |
| t055 | the regeneration request switch on the dash is stuck down | P2458-09 | regen button stuck |
| t056 | intake charge cooler is not cooling effectively | P026A-00 | CAC efficiency |
| t057 | road speed reading does not make sense | P0500-1F | speed plausibility |
| t058 | no fuel pressure builds up while cranking the engine | P00C6-00 | no rail build-up |
| t059 | clutch switch signal does not make sense | P0704-29 | clutch plausibility |
| t060 | the starter motor control line is broken | P0A1B-13 | starter open circuit |

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
