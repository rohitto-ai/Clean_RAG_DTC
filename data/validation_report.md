# Phase 1 Validation & Anomaly Report

- Records parsed: **314**
- TOC entries (pp. 1-7): **304**
- Pages covered: 8-545

## 1. Coverage vs the Table of Contents

- Distinct codes in TOC: **301**
- Distinct codes parsed: **311**
- TOC entries with NO record: **0**
- Records NOT in the TOC: **10**

### Records with no TOC entry

- `P0425-64` (parsed p.457) — DFC for Model based plausibility check of exhaust-gas temperature sensor T4
- `P042A-64` (parsed p.458) — DFC for Model based plausibility check of exhaust-gas temperature sensor T5
- `P10FF-00` (parsed p.466) — DFC for frozen DEF
- `P202E-84` (parsed p.461) — DFC for SCR System Model Pressure Error due to negative pressure offset
- `P202E-85` (parsed p.460) — DFC for SCR System Model Pressure Error due to positive pressure offset
- `P20A0-13` (parsed p.462) — DFC for SCR Open load error of the external relay
- `P20A1-4B` (parsed p.463) — DFC for SCR Over temperature error of the external relay
- `P20A2-11` (parsed p.465) — DFC for SCR Short circuit to ground of the external relay
- `P20A3-12` (parsed p.464) — DFC for SCR Short circuit to battery of the external relay
- `P242A-64` (parsed p.459) — DFC for Model based plausibility check of exhaust-gas temperature sensor T6

### Duplicate codes (code alone is not a unique key)

| code_full | records | pages | occurrences |
|---|---|---|---|
| `P0180-11` | 2 | 100, 195 | 1, 2 |
| `P0180-12` | 2 | 102, 197 | 1, 2 |
| `P061C-00` | 2 | 217, 472 | 1, 2 |

- Duplicates already visible in the TOC: `P0180-11`x2, `P0180-12`x2, `P061C-00`x2

## 2. Template deviations (the fixed 7-section layout)

| Section | Present | Missing | % present |
|---|---|---|---|
| header | 314 | 0 | 100.0% |
| overview | 314 | 0 | 100.0% |
| checkpoints | 312 | 2 | 99.4% |
| steps | 314 | 0 | 100.0% |
| circuit_schematic | 135 | 179 | 43.0% |
| circuit_description | 132 | 182 | 42.0% |
| location_image | 118 | 196 | 37.6% |

- Records with the full 7 sections: **111** / 314
- Records deviating from the template: **203**

### Template variants

| Variant | Records | Meaning |
|---|---|---|
| `full_7_section` | 111 | all 7 sections present |
| `reduced_4_section` | 173 | header + overview + checkpoints + steps only; no schematic/description/location at all |
| `partial` | 30 | some but not all visual sections — the genuinely mixed cases |

### Deviation shapes (grouped)

| Missing sections | Count | Example DTCs |
|---|---|---|
| circuit_description, circuit_schematic, location_image | 173 | `P0071-00@p369`, `P0089-00@p88`, `P0089-92@p85`, `P0184-00@p486` … +169 |
| location_image | 17 | `P00C6-00@p86`, `P0108-00@p51`, `P0120-11@p90`, `P0120-12@p92` … +13 |
| circuit_description, location_image | 5 | `P2047-00@p295`, `P2047-4B@p297`, `P2047-7F@p303`, `P2048-00@p301` … +1 |
| circuit_description, circuit_schematic | 4 | `P0194-00@p12`, `P206A-13@p281`, `P206A-86@p280`, `P2BA9-00@p282` |
| checkpoints | 2 | `P0004-00@p134`, `P0087-00@p81` |
| circuit_schematic, location_image | 1 | `P2135-00@p98` |
| circuit_schematic | 1 | `P0704-29@p205` |

### P16xx FCCU alarm family (56 records)

| Missing sections | Count |
|---|---|
| circuit_description, circuit_schematic, location_image | 56 |

- Step-count distribution: 4 steps x56
- Pages spanned: Counter({1: 56})

### Single-page records (176)

| DTC | page | steps | chk | cause | missing sections |
|---|---|---|---|---|---|
| `P0401-00` | 46 | 8 | 3 | 0 | circuit_schematic, circuit_description, location_image |
| `P0402-00` | 47 | 3 | 2 | 0 | circuit_schematic, circuit_description, location_image |
| `P0089-92` | 85 | 8 | 2 | 3 | circuit_schematic, circuit_description, location_image |
| `P0089-00` | 88 | 7 | 2 | 3 | circuit_schematic, circuit_description, location_image |
| `P018F-00` | 89 | 5 | 2 | 2 | circuit_schematic, circuit_description, location_image |
| `P259F-00` | 182 | 8 | 4 | 4 | circuit_schematic, circuit_description, location_image |
| `P259E-00` | 183 | 8 | 4 | 4 | circuit_schematic, circuit_description, location_image |
| `P2229-00` | 214 | 2 | 2 | 1 | circuit_schematic, circuit_description, location_image |
| `P2228-00` | 215 | 2 | 2 | 1 | circuit_schematic, circuit_description, location_image |
| `P0219-00` | 216 | 3 | 1 | 1 | circuit_schematic, circuit_description, location_image |
| `P061C-00` | 217 | 2 | 1 | 1 | circuit_schematic, circuit_description, location_image |
| `P062B-00` | 218 | 2 | 1 | 1 | circuit_schematic, circuit_description, location_image |
| `P061A-00` | 219 | 2 | 1 | 1 | circuit_schematic, circuit_description, location_image |
| `P060A-49` | 220 | 2 | 1 | 1 | circuit_schematic, circuit_description, location_image |
| `U0102-00` | 221 | 3 | 1 | 1 | circuit_schematic, circuit_description, location_image |
| `U011A-00` | 222 | 3 | 3 | 1 | circuit_schematic, circuit_description, location_image |
| `U011A-89` | 223 | 3 | 3 | 1 | circuit_schematic, circuit_description, location_image |
| `P2200-86` | 260 | 6 | 3 | 3 | circuit_schematic, circuit_description, location_image |
| `P2200-13` | 261 | 6 | 3 | 3 | circuit_schematic, circuit_description, location_image |
| `P2201-76` | 262 | 6 | 3 | 3 | circuit_schematic, circuit_description, location_image |
| `P229E-86` | 263 | 6 | 3 | 3 | circuit_schematic, circuit_description, location_image |
| `P229E-13` | 264 | 6 | 3 | 3 | circuit_schematic, circuit_description, location_image |
| `P229F-76` | 265 | 6 | 3 | 3 | circuit_schematic, circuit_description, location_image |
| `P206A-86` | 280 | 6 | 3 | 3 | circuit_schematic, circuit_description |
| `P206A-13` | 281 | 6 | 3 | 3 | circuit_schematic, circuit_description |
| … +151 more | | | | | |

## 3. Structural integrity at scale

- Total steps parsed: **2202**
- Total `goto` references: **701**
- Records with zero steps: **0**
- Records with non-contiguous step numbering: **7**
- Unresolved `goto` targets: **37**
- Self-referencing `goto` (step N -> step N): **4**
- Records with boilerplate leakage: **0**

### Non-contiguous step numbering

- `P0116-00@p20` -> [1, 2, 3, 4, 5, 6, 7, 8, 9, 9]
- `P0088-00@p83` -> [1, 2, 3, 4, 5, 6, 7, 9]
- `P0089-92@p85` -> [1, 2, 3, 4, 5, 6, 7, 9]
- `P2452-85@p248` -> [1, 2, 3, 4, 6, 7, 8, 9]
- `P2452-84@p251` -> [1, 2, 3, 4, 6, 7, 8, 9]
- `P22CF-73@p390` -> [1, 2, 3, 4, 5, 6, 7, 8, 9, 9]
- `P22CF-72@p393` -> [1, 2, 3, 4, 5, 6, 7, 8, 9, 9]

### Unresolved goto targets — classification

- Records affected: **20** (37 references)
- Records where EVERY unresolved target points past the last step: **20/20**
- Records whose final step is a terminal "Check DTC" instruction: **20/20**
- Records not fitting that shape: **none**

> These are **source-document defects, not parse errors** — spot-checked against pp. 20, 22, 83, 248. The manual's step rows are mis-numbered (duplicated or skipped labels) while the prose consistently refers to the final check step. Recommendation for Phase 6: resolve an out-of-range `goto` to the terminal step, and record the repair in the Phase 7 harness rather than silently rewriting `goto[]` at parse time.

#### Full list

| DTC | from step | -> target | step text |
|---|---|---|---|
| `P0116-00@p20` | 3 | 10 | Fix the back-out cables in proper positions in connector & go to Step  |
| `P0116-00@p20` | 5 | 10 | If continuity is unavailable from Step 4 then check the signal line sh |
| `P0116-00@p20` | 6 | 10 | If Step 5 is true then replace the wire harness cable with new one & g |
| `P0116-00@p20` | 7 | 10 | Check the proper mounting of the sensor & for mechanical damage. If St |
| `P0116-00@p20` | 8 | 10 | If error still present, check if sensor itself is exposed to high temp |
| `P0116-00@p20` | 9 | 10 | If error still present then replace Coolant Temp sensor with new one & |
| `P0100-00@p22` | 3 | 10 | Fix the back-out cables in proper positions in connector & go to Step  |
| `P0100-00@p22` | 6 | 10 | If still error present replace PFM sensor with new one & go to Step 10 |
| `P0401-00@p46` | 7 | 10 | If Step 6 is true then replace the wire harness cable with new one & g |
| `P0109-00@p54` | 3 | 9 | Fix the back-out cables in proper positions in connector & go to Step  |
| `P0109-00@p54` | 7 | 9 | If still error present replace MAP sensor with new one & go to Step 9 |
| `P0088-00@p83` | 1 | 10 | Check whether the pump metering unit connector is connected properly,  |
| `P0088-00@p83` | 2 | 10 | Check whether the rail pressure sensor connector is connected properly |
| `P0089-92@p85` | 1 | 10 | Check whether the pump metering unit connector is connected properly,  |
| `P0089-92@p85` | 2 | 10 | Check whether the rail pressure sensor connector is connected properly |
| `P0089-00@p88` | 1 | 9 | Check whether the pump metering unit connector is connected properly,  |
| `P0089-00@p88` | 2 | 9 | Check whether the rail pressure sensor connector is connected properly |
| `P0089-00@p88` | 3 | 9 | Remove the pump and get it checked from the authorized dealer, go to s |
| `P0089-00@p88` | 4 | 9 | Change the fuel return lines , go to step 9 after rectification |
| `P0089-00@p88` | 5 | 9 | Change the fuel accumulator , go to step 9 after rectification |
| `P0500-1F@p176` | 3 | 13 | If connector found loose then fix it properly and go to step 13 |
| `P0500-1F@p176` | 5 | 13 | In case of non-conformity of step 4, fit the sensor properly, if found |
| `P0500-1F@p176` | 7 | 13 | Change the connector if required, fix the back-out cables in proper po |
| `P0500-1C@p179` | 3 | 13 | If connector found loose then fix it properly and go to step 13 |
| `P0500-1C@p179` | 5 | 13 | In case of non-conformity of step 4, fit the sensor properly, if found |
| `P0500-1C@p179` | 7 | 13 | Change the connector if required, fix the back-out cables in proper po |
| `P203B-85@p266` | 7 | 9 | If found damaged or failed change the sensor and go to step 9 |
| `P203B-84@p268` | 7 | 9 | If found damaged or failed change the sensor and go to step 9 |
| `P203F-00@p270` | 7 | 9 | If found damaged or failed change the sensor and go to step 9 |
| `P2043-85@p272` | 7 | 9 | If found damaged or failed change the sensor and go to step 9 |
| … +7 more | | | |

### Subsystem tagging (`system`)

| system | records |
|---|---|
| `ecu_internal` | 60 |
| `scr_def` | 50 |
| `o2_exhaust` | 35 |
| `fuel_supply` | 20 |
| `level2_monitoring` | 20 |
| `dpf_regen` | 18 |
| `turbo_boost` | 15 |
| `intake_air` | 14 |
| `injector` | 14 |
| `egr` | 14 |
| `electrical` | 10 |
| `exhaust_throttle` | 9 |
| `pedal_clutch_brake` | 8 |
| `rail_pressure` | 7 |
| `sensor_generic` | 7 |
| `coolant` | 4 |
| `engine_position` | 4 |
| `can_network` | 3 |
| `vehicle_speed` | 2 |

## 4. Branching-phrase catalogue (instrumentation for Phase 6 polarity)

- Distinct branching signatures: **32**
- Steps containing branching language: **1205** / 2202 (54.7%)
- Steps with no branching language: **997**

_`X` = free text, `GOTO` = a 'go to Step N' reference. `targets` shows how many goto targets that shape carries._

| # | Signature | Count | targets (n->count) | Example |
|---|---|---|---|---|
| 1 | `IF X` | 419 | 0->419 | If the error is present check the connector pins from both side i.e. sensor side & wire ha |
| 2 | `IF X GOTO` | 256 | 1->256 | If error still present go to Step 7 |
| 3 | `X GOTO` | 134 | 1->134 | Fix the back-out cables in proper positions in connector & go to Step 13 |
| 4 | `IF X THEN X GOTO` | 101 | 1->101 | If connector found lose in step 2 then fix is properly & go to Step 13 |
| 5 | `X IF_YES GOTO` | 63 | 1->63 | Check the wire harness for any pin / wire back-out from connector, if yes go to Step 8 |
| 6 | `IF X THEN X` | 36 | 0->36 | If Step 4 & Step 5 fails then check signal (A97) short circuit to ground (A31) |
| 7 | `X IF X GOTO` | 32 | 1->32 | Check if Pin 2( A39) is shorted to supply(A34) or open circuit, go to step 9 |
| 8 | `X IF X` | 24 | 0->24 | Check connector if rail pressure sensor is connected properly to the wire harness connecto |
| 9 | `X GOTO X` | 22 | 1->22 | Remove the pump and get it checked from the authorized dealer, go to step 9 after rectific |
| 10 | `X IF X IF_YES X GOTO` | 15 | 1->15 | Check if DPF brick is damaged , if Yes, replace DPF & go to step 11 |
| 11 | `X IF X IF_NOT X GOTO` | 12 | 1->12 | Check if the wiring harness connector connected properly to 1st cylinder injector, if not  |
| 12 | `X IF X THEN GOTO` | 11 | 1->11 | Check the proper mounting of the sensor & for mechanical damage. If Step 9 is true then go |
| 13 | `X IF_YES X` | 11 | 0->11 | Check for back out terminals of wiring harness, If yes fix the connections |
| 14 | `IF X THEN X IF X` | 10 | 0->10 | If Step 4 & Step5 is true then check if sensor input (A53) is shorted to ground(A31) |
| 15 | `IF X THEN X GOTO X` | 8 | 1->8 | If continuity is unavailable from Step 4 then check the signal line short to ground & go t |
| 16 | `IF X IF X GOTO` | 7 | 1->7 | If error persists check the fitment of the connector on the sensor for any loose connectio |
| 17 | `IF X IF_NOT X GOTO` | 6 | 1->6 | If error still present check the mounting of the Pedal sensor is proper or not, if not mak |
| 18 | `IF X THEN GOTO` | 5 | 1->5 | If pins are damaged then go to Step No. 12 |
| 19 | `X IF_YES X GOTO` | 5 | 1->5 | Check the signal line for short to ground i.e. continuity between Pin2 of rail pressure se |
| 20 | `IF X IF_YES X` | 5 | 0->5 | If error persists, check the continuity between Pin 1 & Pin2, if yes, motor winding could  |
| 21 | `IF X IF X IF X` | 4 | 0->4 | If any Issues, check for battery connection, if loose connect & check if battery is chargi |
| 22 | `IF X THEN GOTO X ELSE GOTO` | 3 | 2->2, 3->1 | If continuity in Step 7 is unavailable then go to Step 9 & 11 else go to Step 9 |
| 23 | `X IF_YES THEN GOTO X` | 3 | 2->3 | Check the line from A_B1 for short circuit to ground. If yes then go to Step 10 & 11 |
| 24 | `IF X IF X IF_YES X GOTO` | 3 | 1->3 | If error persists, check if Input signal is shorted to battery, if yes arrest issue & go t |
| 25 | `IF X THEN GOTO ELSE GOTO` | 2 | 2->2 | If continuity is OK in Step 9 then go to Step 12 else go to Step 11 |
| 26 | `X THEN X` | 2 | 0->2 | Perform pressure preparation checks through diagnostic tool (ignition off and then pressur |
| 27 | `X IF_YES` | 1 | 0->1 | Check the wire connector, if yes |
| 28 | `IF X IF X GOTO X` | 1 | 1->1 | If error still present, check if sensor itself is exposed to high temperature source, go t |
| 29 | `X IF_YES X GOTO X` | 1 | 1->1 | Check for fuel leakage from rail return line in running condition, if yes get it checked f |
| 30 | `X IF X IF_YES X` | 1 | 0->1 | Check if Pressure relief valve counter or timer is exceeding the design limit, if yes chan |
| 31 | `IF X THEN X IF_YES GOTO` | 1 | 1->1 | If error still present then Check the wire harness for any pin / wire back-out from connec |
| 32 | `IF_YES X GOTO` | 1 | 1->1 | If yes , arrest all leakages & go to step 6 |

