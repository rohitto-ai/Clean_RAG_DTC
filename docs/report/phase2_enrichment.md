# Phase 2 — Multimodal Enrichment (local, CPU-only)

## Objective

Give each DTC record a usable `pin_map[]` and durable references to its schematic
and component images, entirely on-box: no cloud vision, no GPU, no network.

Steps cite pins that are defined only in the schematic images ("check the continuity
between pin 2 of rail pressure sensor to **A71**"), so the goal was to anchor those
pin references to something structured.

## Method

**Step A — OCR spike (gated).** Before committing to a full OCR pass, three
schematics were extracted and OCR'd: P0192-00 (p.9), P0193-00 (p.11), P0117-00
(p.15). Preprocessing: clip the schematic bbox → render at 300 DPI → grayscale →
binarize. Tesseract run at `--psm 11` and `--psm 12`.

**Spike pin-recall** = of the pins those DTCs cite in their own step text
(P0192-00: A71, A83 · P0193-00: A71, A11 · P0117-00: A51, A28), how many appear in
the OCR output.

**Step B (taken) — fallback path.** `src/enrich_images.py` extracts and hash-dedupes
every non-boilerplate image, binds assets to `image_refs` by page + bbox overlap,
and builds `pin_map[]` from the **text layer** — the pins each DTC's own steps,
checkpoints and circuit description cite.

## Results & Metrics

### Spike result: 0/6 = **0% pin-recall**

| DTC | Cited pins | Found by OCR |
|---|---|---|
| P0192-00 | A71, A83 | none |
| P0193-00 | A71, A11 | none |
| P0117-00 | A51, A28 | none |

Confirmed not to be a tuning artifact: repeated at **300 / 600 / 900 DPI**, binarize
thresholds 150 and 190, and `--psm 6 / 11 / 12`. `A71` and `A83` were absent from
every combination. There is also **no text layer behind the schematic** — pdfplumber
finds 0 words inside the image bbox; it is pure raster.

### Why OCR fails here — the decisive finding

**The pin token the text cites is never drawn in the schematic.**

Visual inspection of the P0192-00 schematic shows the ECU block labelled **`C016-A`**
with its pins drawn as **bare numbers** — `11`, `71`, `83` — beside net names
`O_V_5VRAILPS`, `I_A_RAILPS`, `G_R_RAILPS`.

So **"A71" means "connector C016-**A**, pin 71"**. It is a *composition* of the
connector suffix and the pin number, not a string present in the image. OCR was
being scored against a target that does not exist in the raster. Tesseract did in
fact recover the useful fragments — `71`, `C016-A`, `C001CC-F/M`, `_A_RAILPS` — but
it can never emit the literal `A71`.

A secondary factor: the source rasters are low-resolution (the P0192-00 schematic is
**1389×982 px** rendered into a 454×321 pt box, ~220 DPI effective) and visibly
JPEG-blurred, which shatters small labels into fragments like `asa 3 71 A`.

### Decision: **STEP B-FALLBACK**

0% is far below the ~60% gate, so the full OCR pass was skipped. Per instruction, no
VLM was attempted — it is deferred and off on this 8 GB box.

### Enrichment output

| Metric | Value |
|---|---|
| Records enriched | 314 |
| Image instances | 342 |
| **Unique images after hash dedup** | **64** |
| **Dedup ratio** | **81.3% duplicates removed** |
| Most-reused single image | 26 DTCs share it |
| Records with ≥1 pin in `pin_map` | 158 / 314 (50.3%) |
| Total pin citations | 427 (**383 high confidence**, 44 low) |
| Runtime / peak RSS | seconds / **241 MB** |

**Pin coverage on the spike set: 6/6 = 100%** — every pin OCR missed is recovered
from the text layer, which is authoritative and lossless.

Pin-count distribution: 156 records with 0 pins (mostly the 173 `reduced_4_section`
FCCU-style alarms, which cite no pins at all), 17 with 1, 72 with 2, 35 with 3,
22 with 4, and 12 with 5–7.

The 81.3% dedup ratio strongly validates the build plan's prediction that DTCs reuse
schematics (the rail-pressure trio, injectors 1–4, the ~85 FCCU alarms).

## Evidence & Artifacts

- [src/enrich_images.py](../../src/enrich_images.py)
- [data/dtc_enriched.jsonl](../../data/dtc_enriched.jsonl) — 314 enriched records
- [data/enrichment_stats.json](../../data/enrichment_stats.json) — dedup + pin stats
- `images/` — 64 unique assets, 6.3 MB (gitignored)

Example (`P0192-00`):

```json
"pin_map": [
  {"pin": "A71", "cited_in": ["step 9"],  "source": "step_text", "confidence": "high"},
  {"pin": "A83", "cited_in": ["step 11"], "source": "step_text", "confidence": "high"}
],
"schematic_pointer": "See Circuit Schematic Diagram, page 9 of the manual.",
"ocr_status": "skipped_structural_mismatch"
```

## Issues Found & Fixed

1. **`P1`/`P2` false positives.** The pin regex matched the DPF differential-pressure
   taps described in prose ("P2 represents the upstream (intake) side of the
   filter") — pressure points, not ECU pins. Added to a stopword set.
2. **Weak-evidence pins.** 44 tokens appear *only* in the prose circuit description
   rather than in a diagnostic instruction. Rather than drop them, each pin now
   carries `confidence: high|low` so retrieval can weight them.
3. **Header-band logos excluded** from extraction, as required — the repeated TATA
   logo is boilerplate imagery, not a schematic.

## Limitations

- **`pin_map[]` is text-derived, not image-derived.** It records which pins a DTC
  cites, not the full pin-out of its connector. Pins present in the schematic but
  never mentioned in the steps are not captured.
- **156 records have an empty `pin_map`** — correct, not a gap: they are
  predominantly reduced-template alarms with no schematic and no pin references.
- **The schematic images are not machine-readable.** They are retained as assets and
  pointed at (`schematic_pointer`), so a UI can display them, but their content does
  not enter the retrieval index.

### Recommended next attempt (open decision)

If image-derived pins are wanted later, **do not retry plain OCR** — retry with the
composition rule this spike uncovered: OCR the connector block label (`C016-A`,
which Tesseract *does* read) and the bare pin numbers near it, then synthesise
`A` + `71` → `A71`. That is a genuinely different technique from the one that scored
0%, and it would also yield net names (`I_A_RAILPS`) that the text layer lacks. It
needs the schematic's internal geometry parsed, so it is a real piece of work, not a
parameter tweak.
