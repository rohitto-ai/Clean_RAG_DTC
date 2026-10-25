# Phase 10.2 — Synthetic demo data + end-to-end telematics pipeline

_2026-10-25 · branch `phase10-demo` · additive, **production default unchanged** · frozen TEST not used_

## Data & confidentiality

**No real TATA Motors data exists in this repository and none is used.** Everything generated
here is labelled **`synthetic - illustrative`** (in `data/demo/README.md`, in `scenarios.json`,
and on every pipeline report):

| element | provenance |
|---|---|
| SPNs | invented inside the SAE J1939 **manufacturer-proprietary** range 520192–524287, so no value can be mistaken for a real SAE or OEM assignment |
| FMI numbers and descriptions | the **public** SAE J1939-73 definitions |
| Fault names | invented mnemonics (`RAILP_SNSR_STG`), not OEM fault names |
| Vehicle ids / registrations | obviously fake: `DEMO-MAT-0001`…, `DM01AA0001`… |
| Lamp states, dates, counts, Region/LOB/PL | invented |
| Cost / TAT figures | **ILLUSTRATIVE placeholders.** That data is owned by another team; these are not real labour rates or part prices, and every report repeats the caveat |
| SPN/FMI → P-code pairing | **fictitious** |
| P-codes | **real** codes from the 3.3L DTC manual, so manual retrieval and advisory text downstream are genuine |

**The COLUMN NAMES are the production feed's real ones**, so `src/telematics.py` can later be
pointed at a real export offline with no code change. Only the values are synthetic. The log
carries exactly the 21 required columns — no extra marker column — precisely so a real export
drops in unchanged.

## A. Generator — `scripts/gen_demo_data.py` (seed 1002)

Outputs committed under `data/demo/`:

### 1. `synthetic_spn_fmi_dictionary.xlsx` / `.csv` — 73 entries

Columns exactly: `Fault Name | P Code | DTC_LB | SPN | FMI | SPN_Name`.

- **73 entries** (≥ 60 required) across **42 SPN names** spanning **19 manual subsystems**
  (≥ 12 required): rail_pressure, coolant, engine_position, injector, egr, exhaust_throttle,
  turbo_boost, intake_air, sensor_generic, dpf_regen, scr_def, o2_exhaust, fuel_supply,
  pedal_clutch_brake, vehicle_speed, can_network, electrical, ecu_internal, level2_monitoring.
- **`DTC_LB` is DECIMAL**; the manual's suffix is its 2-digit uppercase **HEX** form.
  `telematics.suffix_from_lb()` does the conversion and is unit-tested on the brief's own
  examples: **19 → `13`, 155 → `9B`, 156 → `9C`**, plus 0 → `00`, 31 → `1F`, 133 → `85`,
  243 → `F3`, and rejection of −1 / 256 / 999.
- Every intended target **resolves in the manual** — asserted entry by entry against the real
  index by `scripts/validate_demo_data.py`.
- **Two ambiguous keys**, as required, because real OEM dictionaries are not one-to-one:

  | key (SPN : FMI) | maps to | why it is genuinely ambiguous |
  |---|---|---|
  | `520362 : 7` | **P042E-00** and **P042F-00** | one EGR valve position sensor, one failure mode ("mechanical system not responding"), two possible faults: jammed **open** or jammed **closed** |
  | `520379 : 7` | **P04A4-00** and **P04A5-00** | the same, for the exhaust throttle valve |

- Deliberate non-resolving entries: `P0195-00` (absent from the manual) and `P0116` + LB 19
  → `P0116-13` (base exists, that low byte does not).

### 2. `synthetic_fleet_log.xlsx` / `.csv` — 1,000 rows

All 21 production column names; **200 vehicles**, **30 days** (2026-03-01 onward), **122 exact
duplicate rows (12.2%)**. Lamp columns use only the real vocabulary `Lamp ON` / `Lamp Off` /
`Not used`; flashing columns only `Unavailable/ Do not flash` / `Lamp ON`. The 14 scenario
vehicles carry **only** their scripted rows, so each scenario stays legible; bulk traffic goes
to the other 186.

### 3. `cost_tat_rules.csv` — illustrative

Keyed by subsystem with an optional P-code override (`rail_pressure` default 3.5 h /
INR 8,500–24,000 / 24 h TAT; `P0192-00` override 2.5 h / INR 7,200–11,000 / 16 h). Every loaded
rule carries `basis: "illustrative - owned by another team, not real rates"`.

### 4. `scenarios.json` — 14 scenarios

Names the fake vehicle for each required outcome, plus the ambiguous-key inventory.

### 5. Validators

`scripts/validate_demo_data.py` (data contract, 40+ checks, exit 1 on failure) and
`src/test_demo_data.py` (**22/22**: contract, deterministic regeneration under the fixed seed,
labelling, the hex rule, `.csv`/`.xlsx` interchangeability, no real-data leakage).

Two real data bugs were caught by the validator and fixed rather than papered over: FMI 28 is
"reserved for SAE assignment" with no public meaning (changed to FMI 0), and FMI 17 was missing
from my J1939 table (added).

## B. Pipeline — `src/telematics.py`

Pure functions plus a CLI. **Reuses rather than re-implements:** `normalize.validate_row` (the
Phase 9.4 R0 rules, applied after mapping each feed row onto normalize's canonical
`{spn, fmi, occurrences, timestamp, vehicle_id}` shape), `Retriever.retrieve` (the exact-code
router, carrying the Phase 9.3b refusal/clarification behaviour), `advise.fix_block` (Phase 9.1
deterministic fix blocks), `retrieve.did_you_mean` and `retrieve.detect_system`.

### The ladder

| rung | condition | outcome |
|---|---|---|
| **R0** | field rules fail | `REJECTED_MALFORMED` (logged with reasons) |
| **R0** | duplicate `(Vehicle_Id, SPN, FMI, Event_Date)` | dropped before episodes are built |
| **R1** | exactly **one** mapped P-code → manual lookup | `exact_code` → **`ADVISORY`** · `suffix_not_found` → `CLARIFY_LOW_BYTE` · `unknown_code` → `REFUSED_NOT_IN_MANUAL` |
| **R1b** | **more than one** mapped P-code | `AMBIGUOUS_MAPPING_CANDIDATES` — all candidates listed with their manual status, **never auto-advised** |
| **R2** | SPN known, this FMI unmapped | `FALLBACK_CANDIDATES`, nearest FMI marked, never auto-advised |
| **R3** | SPN not in the dictionary | `UNMAPPED`, logged |

Episodes are grouped per `(Vehicle_Id, SPN, FMI)`.

### Severity (deterministic, reasons always returned)

```
red stop lamp ON or flashing              -> CRITICAL
else amber / MIL / protect ON or flashing -> HIGH
else occurrence <= 1 and active < 60 min  -> LOW, otherwise MEDIUM
occurrence >= 5 or active >= 60 min raises LOW/MEDIUM one level, capped at HIGH
```

CRITICAL is reserved for the red stop lamp: escalation can never reach it, asserted across a
grid of occurrence × active-time values. Note the interaction the brief's wording implies and
the tests now pin: occurrence 5 makes the base **MEDIUM** *and* triggers the raise, so the
result is **HIGH**; occurrence 3 with a short active time stays MEDIUM; 59 minutes with one
occurrence stays LOW.

### Cross-check and reported-code verification

`cross_check` derives the expected subsystem from `SPN_Name` using the existing
`retrieve.detect_system` keyword map and compares it with the resolved record's `system`:
`CONSISTENT` / `INCONSISTENT` (with a "verify the mapping before acting" note) /
`NOT_DETERMINED` when the SPN name carries no subsystem keyword.

`verify_reported_code(vehicle_id, code)` compares a technician-entered code with the
telemetry-resolved one. It **never auto-replaces** either (`auto_replaced: false` in every
response) and flags an edit distance of 1 as a *possible transposition*.

## Results on the synthetic log

### Outcome distribution (1,000 rows → 847 episodes, 199 vehicles)

| outcome | episodes |
|---|---|
| `ADVISORY` | 753 |
| `FALLBACK_CANDIDATES` | 24 |
| `AMBIGUOUS_MAPPING_CANDIDATES` | 22 |
| `UNMAPPED` | 21 |
| `REFUSED_NOT_IN_MANUAL` | 20 |
| `CLARIFY_LOW_BYTE` | 7 |
| rows rejected as malformed | 5 |

Worst severity per vehicle: **CRITICAL 34, HIGH 163, MEDIUM 0, LOW 2**. Advisories by
subsystem (top 5): injector 69, fuel_supply 63, intake_air 56, rail_pressure 52, electrical 51.

MEDIUM is 0 at vehicle level because `worst_severity` takes the maximum across a vehicle's
episodes, and most vehicles have at least one lamp-ON episode (HIGH). MEDIUM does occur at
episode level and is unit-tested directly.

### Latency (CPU-only, this Codespace)

| measure | value |
|---|---|
| per-vehicle report, p50 | **0.4 ms** |
| per-vehicle report, p95 | **0.6 ms** |
| whole-fleet summary, 199 vehicles | **0.08 s** |

Measured over 60 vehicles with the log already in memory and the Retriever constructed once
(construction itself, which loads MiniLM and Chroma, is ~10 s and excluded — it is a
once-per-process cost, not per vehicle). Code resolution is memoised per process.
Raw figures: `data/experiments/10_2/fleet_run.json`.

### Worked example — ambiguity (vehicle DEMO-MAT-0004)

```
SPN 520362 FMI 7 (Engine EGR Valve Position) x1 row  2026-03-09
  OUTCOME: AMBIGUOUS_MAPPING_CANDIDATES   severity HIGH  (Amber_Warning_Lamp_Status ON)
    {'rung': 'R0 validate + de-duplicate', 'result': 'ok', 'rows_kept': 1}
    {'rung': 'R1b ambiguous key', 'result': 'candidates', 'n': 2, 'auto_advised': False}
  SPN 520362 FMI 7 maps to P042E-00, P042F-00 in the dictionary. No advisory is issued:
  the key is ambiguous and choosing one would assert a repair for a fault that was not
  identified. A technician must confirm which applies.
```

### Worked example — transposition (vehicle DEMO-MAT-0011)

```
$ src/telematics.py --vehicle DEMO-MAT-0011 --reported P0100-00
 "reported_code": "P0100-00",  "reported_in_manual": true,
 "telemetry_resolved_codes": ["P1000-00"],
 "auto_replaced": false,
 "status": "MISMATCH",
 "possible_transposition": ["P1000-00"],
 "message": "P0100-00 does NOT match the telemetry-resolved code(s) P1000-00.
             P1000-00 is one character away - possible transposition.
             Not substituted: confirm the code on the vehicle."
```

Both scripted transpositions are flagged, and both typed codes (`P0100-00`, `P1657-00`) are
themselves **real manual codes** — which is exactly why the Phase 9.3b router cannot catch them
and why this telemetry cross-check earns its place. These are the two residual HARMFUL cases
from Phase 9.3b, now detectable when telemetry is available.

### Scenario coverage — 14/14

| scenario | vehicle | outcome |
|---|---|---|
| normal_advisory | DEMO-MAT-0001 | ADVISORY, P0192-00, HIGH |
| red_stop_lamp | DEMO-MAT-0002 | ADVISORY, **CRITICAL** |
| duplicate_rows | DEMO-MAT-0003 | ADVISORY; 3 rows → 1 episode, 2 dropped |
| ambiguous_key | DEMO-MAT-0004 | AMBIGUOUS_MAPPING_CANDIDATES (P042E/P042F) |
| ambiguous_key_2 | DEMO-MAT-0005 | AMBIGUOUS_MAPPING_CANDIDATES (P04A4/P04A5) |
| fmi_unmapped | DEMO-MAT-0006 | FALLBACK_CANDIDATES |
| unknown_spn | DEMO-MAT-0007 | UNMAPPED |
| code_not_in_manual | DEMO-MAT-0008 | REFUSED_NOT_IN_MANUAL (P0195-00) |
| low_byte_not_in_manual | DEMO-MAT-0009 | CLARIFY_LOW_BYTE (P0116-13 → P0116-00) |
| malformed_rows | DEMO-MAT-0010 | 4 rejected here + 1 unattributable (empty `Vehicle_Id`, counted in the fleet summary); the 6th advises |
| transposition_P1000 | DEMO-MAT-0011 | ADVISORY P1000-00; typing P0100-00 → MISMATCH |
| transposition_P1675 | DEMO-MAT-0012 | ADVISORY P1675-00; typing P1657-00 → MISMATCH |
| severity_cap | DEMO-MAT-0013 | ADVISORY, no lamp, occurrence 9 / 240 min → **HIGH**, capped |
| flashing_red_lamp | DEMO-MAT-0014 | ADVISORY, **CRITICAL** (flashing) |

## Tests and production integrity

| check | result |
|---|---|
| `src/test_telematics.py` | **66/66** |
| `src/test_demo_data.py` | **22/22** |
| `scripts/validate_demo_data.py` | **OK** |
| smoke suite | **44 passed / 1 xfail / 0 failed** |
| determinism `--defaults` | **`ffff9bc707d8754d`** |
| `src/test_lexicon_v2.py` · `src/test_normalize.py` | 102/102 · 21/21 |
| `index/` | untouched |

New dependency: `openpyxl==3.1.5`, pinned in `requirements.txt`, so the `.xlsx` form of the feed
can be read and written offline.

## Files

| file | role |
|---|---|
| `scripts/gen_demo_data.py` | seeded generator (new) |
| `scripts/validate_demo_data.py` | data-contract validator (new) |
| `src/telematics.py` | loaders, ladder, severity, cross-check, reports, CLI (new) |
| `src/test_telematics.py`, `src/test_demo_data.py` | 66 + 22 tests (new) |
| `data/demo/` | the committed synthetic artifacts + `README.md` |
| `data/experiments/10_2/fleet_run.json` | outcome distribution and latency |

```bash
PYTHONPATH=src .venv/bin/python scripts/gen_demo_data.py
PYTHONPATH=src .venv/bin/python scripts/validate_demo_data.py
PYTHONPATH=src .venv/bin/python src/telematics.py --vehicle DEMO-MAT-0001
PYTHONPATH=src .venv/bin/python src/telematics.py --vehicle DEMO-MAT-0011 --reported P0100-00
PYTHONPATH=src .venv/bin/python src/telematics.py --fleet
```

## Limitations

1. **Nothing here measures accuracy.** The dictionary is fictitious, so the ladder resolves
   "correctly" by construction. This is a functional demonstration with edge-case coverage, as
   in Phase 9.4 — not an accuracy result. Real-dictionary coverage and mapping accuracy can only
   be measured against a real export under NDA.
2. **Ambiguous keys are reported, not resolved.** 22 episodes end as
   `AMBIGUOUS_MAPPING_CANDIDATES` with no advisory. Resolving them needs evidence the code
   string does not carry (freeze frames, actuator position, observed behaviour).
3. **Severity is lamp-driven and coarse.** It uses only lamp states, occurrence count and active
   minutes. It knows nothing about road speed, load, or whether the vehicle is in service.
   MEDIUM is rare at vehicle level by construction (worst-of aggregation).
4. **The cross-check inherits the keyword map's blind spots.** `NOT_DETERMINED` whenever an SPN
   name carries no subsystem keyword (e.g. "Engine Starter Motor Control Circuit"), and it
   reports `INCONSISTENT` for honest naming mismatches such as a MAF "A" circuit SPN resolving
   to a `sensor_generic` record. Neither is an error; both need a human.
5. **No J1939 transport decoding.** The input is already-decoded rows. DM1/DM2 frame parsing,
   lamp-status bit fields, freeze frames and multi-fault prioritisation are not implemented.
6. **Cost and TAT are placeholders** owned by another team, and must not be quoted as real.
7. **Latency excludes process start-up** (~10 s to load MiniLM and Chroma) and assumes the log
   fits in memory; a 1,000-row log is trivial, and a multi-million-row real feed would need
   batching.
