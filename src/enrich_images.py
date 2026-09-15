"""
Phase 2 — Multimodal enrichment, fully local, CPU-only, no network.

OCR-FALLBACK PATH. The OCR spike (see docs/report/phase2_enrichment.md) scored
0/6 pin-recall on three schematics. The cause is structural, not OCR quality:
the manual's step text cites a pin as "A71", but the schematic draws it as the
connector block "C016-A" with the bare pin number "71" inside. The literal token
"A71" is never rendered, so no amount of OCR tuning can recover it.

So pin_map[] is anchored on the TEXT LAYER - the pins each DTC's own steps cite -
which is authoritative and lossless. Images are still extracted and hash-deduped
so a UI can display them and a future pass can revisit them.

RAM discipline: pages are streamed one at a time; only one image is decoded at a
time, and raw bytes are released immediately after hashing/writing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict

import fitz

PDF_PATH = "3.3L DTC Manual.pdf"
IMAGE_DIR = "images"

# "A71", "A83", "A_B1", "B_D4" - a connector letter (optionally letter_letter)
# followed by a pin number. Four-digit DTC codes (P0192) cannot match: \b fails
# with a 4th digit following.
PIN_RE = re.compile(r"\b([A-Z](?:_[A-Z])?\d{1,3})\b")

# "P1"/"P2" are the DPF differential-pressure taps described in prose
# ("P2 represents the upstream (intake) side of the filter"), not ECU pins.
PIN_STOPWORDS = {"P1", "P2", "P3", "P0"}

HDR_BAND, FTR_BAND = 72.0, 712.0


def cited_pins(rec):
    """Pins referenced by this DTC's own text, with where each was cited."""
    found = defaultdict(set)
    for s in rec["steps"]:
        for m in PIN_RE.findall(s["text"]):
            if m not in PIN_STOPWORDS:
                found[m].add(f"step {s['n']}")
    for i, c in enumerate(rec["checkpoints"], 1):
        for m in PIN_RE.findall(c):
            if m not in PIN_STOPWORDS:
                found[m].add(f"checkpoint {i}")
    if rec.get("circuit_description"):
        for m in PIN_RE.findall(rec["circuit_description"]):
            if m not in PIN_STOPWORDS:
                found[m].add("circuit_description")
    out = []
    for pin, where in sorted(found.items()):
        w = sorted(where)
        # A pin cited in an actual diagnostic instruction is high confidence; one
        # appearing only in the prose circuit description is weaker evidence.
        strong = any(x.startswith(("step", "checkpoint")) for x in w)
        out.append({"pin": pin, "cited_in": w,
                    "source": "step_text" if strong else "circuit_description",
                    "confidence": "high" if strong else "low"})
    return out


def template_variant(rec):
    core = bool(rec["code_full"] and rec["cause"] or rec["fault_code"]) and bool(rec["steps"])
    kinds = {i["kind"] for i in rec["image_refs"]}
    visual = [("circuit_schematic" in kinds), bool(rec.get("circuit_description")),
              ("location_component" in kinds)]
    if core and all(visual):
        return "full_7_section"
    if core and not any(visual):
        return "reduced_4_section"
    return "partial"


def extract_images(records, pdf_path=PDF_PATH, image_dir=IMAGE_DIR):
    """
    Extract every non-boilerplate image on pages owned by a DTC, deduplicated by
    content hash. Returns {(page, xref-ish key) -> asset} plus dedup stats.
    """
    os.makedirs(image_dir, exist_ok=True)
    wanted_pages = sorted({im["page"] for r in records for im in r["image_refs"]})
    by_page = defaultdict(list)
    seen_hash = {}
    n_total = 0

    doc = fitz.open(pdf_path)
    for pno in wanted_pages:
        page = doc.load_page(pno - 1)
        for info in page.get_images(full=True):
            xref = info[0]
            rects = page.get_image_rects(xref)
            if not rects:
                continue
            r0 = rects[0]
            if r0.y1 <= HDR_BAND or r0.y0 >= FTR_BAND:
                continue                      # repeated TATA logo / footer art
            try:
                raw = doc.extract_image(xref)
            except Exception:
                continue
            n_total += 1
            digest = hashlib.sha256(raw["image"]).hexdigest()[:16]
            if digest not in seen_hash:
                path = os.path.join(image_dir, f"{digest}.{raw['ext']}")
                with open(path, "wb") as f:
                    f.write(raw["image"])
                seen_hash[digest] = {"path": path, "w": raw["width"],
                                     "h": raw["height"], "ext": raw["ext"],
                                     "bytes": len(raw["image"]), "uses": 0}
            seen_hash[digest]["uses"] += 1
            by_page[pno].append({
                "hash": digest, "path": seen_hash[digest]["path"],
                "bbox": [round(v, 1) for v in (r0.x0, r0.y0, r0.x1, r0.y1)],
                "width": raw["width"], "height": raw["height"],
            })
            raw = None
        page = None
    doc.close()
    return by_page, seen_hash, n_total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/dtc_raw.jsonl")
    ap.add_argument("--out", default="data/dtc_enriched.jsonl")
    args = ap.parse_args()

    recs = [json.loads(l) for l in open(args.inp)]
    print(f"loaded {len(recs)} records")

    by_page, assets, n_total = extract_images(recs)
    n_unique = len(assets)
    ratio = (1 - n_unique / n_total) * 100 if n_total else 0
    print(f"images: {n_total} instances -> {n_unique} unique "
          f"({ratio:.1f}% duplicates removed)")

    pin_hist, with_pins, variants = Counter(), 0, Counter()
    for r in recs:
        r["template_variant"] = template_variant(r)
        variants[r["template_variant"]] += 1

        r["pin_map"] = cited_pins(r)
        if r["pin_map"]:
            with_pins += 1
        pin_hist[len(r["pin_map"])] += 1

        # bind extracted assets to this record's image_refs by page + bbox overlap
        for ref in r["image_refs"]:
            best, best_ov = None, 0.0
            for a in by_page.get(ref["page"], []):
                ax0, ay0, ax1, ay1 = a["bbox"]
                bx0, by0, bx1, by1 = ref["bbox"]
                ov = (max(0, min(ax1, bx1) - max(ax0, bx0))
                      * max(0, min(ay1, by1) - max(ay0, by0)))
                if ov > best_ov:
                    best, best_ov = a, ov
            if best:
                ref["asset_hash"] = best["hash"]
                ref["asset_path"] = best["path"]
                ref["pixels"] = [best["width"], best["height"]]

        sch = [i for i in r["image_refs"] if i["kind"] == "circuit_schematic"]
        r["schematic_pointer"] = (
            f"See Circuit Schematic Diagram, page {sch[0]['page']} of the manual."
            if sch else None)
        r["ocr_status"] = "skipped_structural_mismatch"

    with open(args.out, "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nwrote {len(recs)} enriched records -> {args.out}")
    print(f"template variants: {dict(variants)}")
    print(f"records with >=1 pin in pin_map: {with_pins}/{len(recs)} "
          f"({100*with_pins/len(recs):.1f}%)")
    print(f"total distinct pin citations: {sum(len(r['pin_map']) for r in recs)}")

    stats = {"image_instances": n_total, "unique_images": n_unique,
             "dedup_pct": round(ratio, 1),
             "records_with_pins": with_pins, "records": len(recs),
             "variants": dict(variants),
             "pin_count_histogram": {str(k): v for k, v in sorted(pin_hist.items())},
             "top_reused_images": sorted(
                 ({"hash": h, "uses": a["uses"], "px": [a["w"], a["h"]]}
                  for h, a in assets.items()), key=lambda x: -x["uses"])[:10]}
    with open("data/enrichment_stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print("wrote data/enrichment_stats.json")


if __name__ == "__main__":
    main()
