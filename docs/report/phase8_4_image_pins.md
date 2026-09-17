# Phase 8.4 — Image-Derived Pins by Composition OCR (L4)

**Bounded research step: implement, measure honestly, accept the result.** The retrieval
index, the authoritative text-derived `pin_map[]`, and the 8.5 retrieval configuration were
not touched. TEST was not run (this phase does not use the gold set).

## Verdict — a characterized limitation, not a usable data source

Composition OCR **works mechanically**. It lifts recall of text-cited pins from Phase 2's
**0%** to **31%**, and the pins it confirms are genuine. But **62% of everything it emits is
wrong**, and across all 30 schematics it finds **3 genuine pins the text never mentions**,
against 61 false ones. Pin data that is wrong more often than right is worse than no pin data
for a repair procedure, so it must not be shown to technicians or fed into retrieval. The
output stays as a clearly-labelled supplementary file.

The one part that is both new and reliable: **net names** (49 distinct, none in the manual text).
They survive only where anchored to a pin row, and OCR corrupts some of their characters.

## Background

Phase 2 scored plain schematic OCR at 0% recall. The cause was structural: the text cites
**A71**, but the schematic never draws that string. It draws a connector label **`C016-A`** and,
inside the pin block beneath it, a bare number **`71`**. This phase tests whether **spatial
composition** — connector suffix + nearby bare pin number — recovers it.

## Method — `src/enrich_images_pins.py`

1. **OCR** each unique schematic once (135 records share **30** unique images), using the Phase 2
   preprocessing: grayscale, 3× upscale, binarize at 170, Tesseract `--psm 11` and `--psm 12`.
   Word boxes are cached per image hash (46 s, 4 workers).
2. **Connector labels.** Only `C<ddd>-<LETTER>` with no `CC` is composed. This rule comes from
   the schematics' own naming, not from the text pins. Component connectors use numeric
   suffixes (`C079-06`), inline harness connectors contain `CC` (`C001CC-F/M`), and the ECU's
   two connectors are **`C016-A`** (48 reads) and **`C016-K`** (30 reads). C016-K explains the
   text's 90 K-prefixed pins (K01 = C016-**K** pin 1).
3. **Composition.** A bare 1–3 digit number is attached to the nearest ECU label that sits above
   it and to its left. Nets matching `X_Y_…` on the same row to the left are attached to that pin.
4. **Output** — `data/dtc_image_pins.jsonl`, separate from `dtc_records.jsonl`, with
   `source="image_composition"`, the connector, pin number, net, OCR confidence, image hash and
   a descriptive `net_anchored` flag.

### Guarding against fitting to the answer

The geometric thresholds (how far below and right of a label a pin may lie) were set **a priori
from one calibration image** — P0192-00's schematic, where the layout was visually verified.
They were **never re-tuned** against the recall result. Recall is also reported excluding that
image.

## Results

### Recall of text-cited pins (ground truth = authoritative `pin_map[]`, high confidence)

| scope | found | recall |
|---|---|---|
| record level (135 schematic records) | 111 / 324 | 34.3% |
| **unique (schematic, pin) pairs** | **35 / 112** | **31.2%** |
| unique pairs, excluding the calibration image | 33 / 109 | 30.3% |
| unique pairs, composable A/K form only | 35 / 106 | 33.0% |

Unique pairs is the honest figure: many records share one schematic, so record-level counting
weights repeated images. Excluding the calibration image changes recall by under a point, so the
geometry was not fitted to the answer.

**Why the rest were missed (112 unique pairs):**

| outcome | n |
|---|---|
| found | 35 |
| **label read, but pin number not attached to it** | **36** |
| C016-K label not read in the image | 17 |
| no ECU connector label read at all | 9 |
| near-miss — right connector, one digit misread (A71 → 72, A29 → 28, A97 → 93) | 8 |
| not a composable A/K pin form (e.g. `A_B1`) | 6 |
| C016-A label not read | 1 |

The largest miss category is geometric, not OCR. Layouts differ between schematics — on the K
connector the net sits to the **right** of the pin — so geometry calibrated on one image
generalises poorly.

### Precision and new-information yield

| | n |
|---|---|
| compositions emitted (unique per image) | 99 |
| confirmed by the text of a record using that image | 35 |
| **not in the text — new-information candidates** | **64** |

The text cannot verify those 64, so **every one was checked visually**:

- **44** sit on the **Bosch part-number row**. The schematics also contain a *connector drawing*
  carrying the **same** `C016-A`/`C016-K` label, with "Bosch : 1 928 405 **455**" printed
  directly beneath it. The composition rule reads those digits as pins, producing A455, K452,
  A405, K01 (from "1 928"). All wrong; 7 were also inspected visually in a random audit.
- **20** do not. Inspected individually, all 20: **3 genuine**, 17 wrong (part-number
  fragments, pin-out cavity art, blank space, and the A71 → **A72** misread).

| verdict | count | detail |
|---|---|---|
| **genuine pins the text never cites** | **3** | **A09** (`O_V_5VCAS`), **A35** (`I_F_CRSSHLD`), **A81** (`G_R_CAS`) |
| wrong | 61 | Bosch part-number fragments, cavity art, digit misreads |

A random sample of **6 text-confirmed** compositions was inspected as well: **6/6 genuine**
(A94 `O_T_EGRPOS`, A22 `O_P_INJVH12`, A16 `I_F_CRSPOS`, A104 `I_A_TEGR`, K08 `O_V_5VAPP1`,
A44 `O_P_INJVL12`). The 31% recall is real and not coincidental number matches.

**Audited precision: 38 / 99 = 38.4%.** New-pin yield: **3 genuine vs 61 false**, about 20
false for every real new pin.

### Nets — the one genuinely new category

- **49** distinct net names read; **0** appear anywhere in the manual's record text. This is
  wholly new information.
- They are **OCR-noisy**: `GLR_LETVA` for G_R_LETVA, `G_R_RAULS` for G_R_RAILPS,
  `O_V_SVRAILPS` for O_V_5VRAILPS, `0_S_PSP`.
- **20** compositions carry a net anchored on their pin row.

### Post-hoc observation — the net-anchored subset

| subset | emitted | genuine | recall of text pins |
|---|---|---|---|
| all compositions | 99 | 38 (38%) | 31% |
| **net-anchored only** | **20** | **20 (100%)** | **17%** |

Every net-anchored composition was genuine (19 confirmed by text, plus A09). This is flagged,
not claimed. The subset was identified **after** the audit, on the same 30 images, so 20/20 is a
description of this data, not a validated precision. It suggests the obvious next design —
accept a number only when it sits on a net row — but that would need an independent check. The
`net_anchored` flag is emitted so a consumer can apply the filter knowingly. It changes nothing
that is emitted.

## Guardrails

| check | result |
|---|---|
| `data/dtc_records.jsonl` and text `pin_map[]` | unchanged (authoritative) |
| `retrieve.py`, `build_index.py`, `enrich_images.py`, `answer.py` | unchanged |
| `index/`, `index_exp/` | not written |
| image pins in embedding / BM25 text | **no** — the 8.5 config is exactly as selected |
| suite | **44 passed, 1 xfail, 0 failed** |
| gold checker | PASS |

## Two fixes made during measurement

1. **Zero-padding.** The manual writes pins zero-padded (**K01, K08, A06**); the schematics draw
   bare numbers (`8`). Composing `K8` was being scored a miss against `K08`. Composed pins are now
   emitted in the manual's two-digit form, and matching compares connector letter + integer pin
   number. This is a formatting-equivalence fix, not tuning: it moved unique-pair recall from 28.6%
   to 31.2%, and the geometry was unchanged.
2. **Calibration held out.** Recall is reported with and without the calibration image.

## Limitations

- **Precision 38%.** Unsafe as a source of pin facts.
- **Layout-specific geometry.** Rules calibrated on one image miss 36 labelled-but-unattached pins.
- **The connector drawing reuses the ECU label** — a structural trap that no proximity rule
  avoids without detecting the pin-block rectangle.
- **Low-resolution rasters** (e.g. 1389×982) cause single-digit misreads that can't be detected
  from the image alone (A71 → 72).
- **One of 30 "schematics" is a 354×48 strip** that yields no words.
- **Audit by one reviewer**, on cropped images.

## Recommendation

Keep `pin_map[]` text-derived and authoritative, as it is. Treat `dtc_image_pins.jsonl` as a
research artifact. If image pins are ever revisited, the evidence points to a different design,
not more tuning: **detect the pin-block rectangle, and accept only numbers anchored to a net
on the same row**, then validate that on schematics held out from this audit.

## Artifacts

- `src/enrich_images_pins.py` — OCR + composition (`ocr`, `compose` stages)
- `scripts/measure_image_pins.py` — recall, miss reasons, new-info yield
- `data/dtc_image_pins.jsonl` — supplementary output (gitignored build artifact; regenerate with the two stages)
- `data/experiments/8_4/ocr_cache/` — Tesseract word boxes for the 30 images (measurement reproducible without re-OCR)
- `data/experiments/8_4/measurement.json`, `per_image_compositions.json`, `net_anchored_tradeoff.json`
- `data/experiments/8_4/visual_audit_verdicts.json` — every visual verdict with its reason
