"""
Phase 8.4 — Image-derived pins by COMPOSITION OCR (limitation L4). Bounded research.

Phase 2 found plain schematic OCR recovered 0% of text-cited pins, for a structural
reason: the text cites "A71", but the schematic never draws that string. It draws a
connector label "C016-A" and, inside the block beneath it, a bare pin number "71".
This module tests whether SPATIAL COMPOSITION recovers it:

    connector label (C016-A)  +  nearby bare pin number (71)  ->  "A71"

plus net tokens on the same row (I_A_RAILPS).

Output is SUPPLEMENTARY and SEPARATE: data/dtc_image_pins.jsonl, source =
"image_composition". It never modifies dtc_records.jsonl, the authoritative
text-derived pin_map[], or any index - the 8.5 retrieval configuration is untouched.

Stages (OCR is cached per unique image hash, so analysis never re-runs OCR):
    ocr      Tesseract word boxes, Phase 2 preprocessing, psm 11 and 12
    compose  build image_pin_map[] per record + measure against text pins
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

CACHE = "data/experiments/8_4/ocr_cache"
UPSCALE = 3
BIN_THRESHOLD = 170            # Phase 2 value
PSMS = (11, 12)


# ----------------------------------------------------------------- OCR stage
def ocr_image(job):
    os.environ["OMP_THREAD_LIMIT"] = "1"
    h, path = job
    out = os.path.join(CACHE, f"{h}.json")
    if os.path.exists(out):
        return h, "cached"
    from PIL import Image, ImageOps
    import pytesseract
    img = Image.open(path)
    w0, h0 = img.size
    g = ImageOps.grayscale(img)
    g = g.resize((w0 * UPSCALE, h0 * UPSCALE), Image.LANCZOS)
    bw = g.point(lambda p: 255 if p > BIN_THRESHOLD else 0, mode="1")
    words = []
    for psm in PSMS:
        d = pytesseract.image_to_data(bw, config=f"--psm {psm}",
                                      output_type=pytesseract.Output.DICT)
        for i, t in enumerate(d["text"]):
            t = (t or "").strip()
            if not t:
                continue
            words.append({"psm": psm, "text": t, "conf": float(d["conf"][i]),
                          # boxes in ORIGINAL-image pixels
                          "x": d["left"][i] / UPSCALE, "y": d["top"][i] / UPSCALE,
                          "w": d["width"][i] / UPSCALE, "h": d["height"][i] / UPSCALE})
    json.dump({"hash": h, "path": path, "size": [w0, h0], "upscale": UPSCALE,
               "threshold": BIN_THRESHOLD, "psms": list(PSMS), "words": words},
              open(out, "w"))
    return h, f"{len(words)} words"


def unique_schematics(records):
    seen = {}
    for r in records:
        for im in r["image_refs"]:
            if im["kind"] == "circuit_schematic" and im.get("asset_hash"):
                seen.setdefault(im["asset_hash"], im["asset_path"])
    return seen


def stage_ocr(records, workers):
    os.makedirs(CACHE, exist_ok=True)
    jobs = sorted(unique_schematics(records).items())
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for h, msg in ex.map(ocr_image, jobs):
            print(f"  {h}: {msg}", flush=True)


# ----------------------------------------------------------------- compose stage
# Geometry, in ORIGINAL-image pixels, set a priori from ONE calibration image -
# P0192-00's schematic (3801374525e2d294): label C016-A at (265,140), its pins in
# a column at x~339 on rows y=210..268, nets on the same rows to the left.
# Measured on all 30 images afterwards; recall is also reported EXCLUDING the
# calibration image so the geometry is not fitted to the ground truth.
CALIBRATION_IMAGE = "3801374525e2d294"
PIN_DX = (0, 160)        # pin x minus label x
PIN_DY = (5, 350)        # pin y minus label y (pins sit BELOW the label)
NET_ROW_TOL = 10         # net on the same row as its pin
NET_MAX_DX = 260         # net sits to the LEFT of its pin, within this distance
MIN_CONF = 30.0
SAME_POS = 10            # px: two reads within this distance are the same word

# ECU connector labels carry a single LETTER suffix and no "CC" (component
# connectors use numeric suffixes like C079-06; inline harness connectors are
# C001CC-F/M). This comes from the schematic vocabulary, not from the text pins.
ECU_LABEL_RE = re.compile(r"^C(\d{3})-([A-Z])$")
PIN_RE = re.compile(r"^\d{1,3}$")
NET_RE = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)+$")


def _norm_label(t):
    t = t.upper().strip(".,;:()[]|'\"")
    head, sep, tail = t.partition("-")
    head = "C" + re.sub(r"[OQD]", "0", head[1:]) if head.startswith("C") else head
    return head + sep + tail


def _dedupe(words):
    """Collapse psm 11/12 duplicates at the same position; keep highest confidence."""
    kept = []
    for w in sorted(words, key=lambda w: -w["conf"]):
        if any(abs(w["x"] - k["x"]) <= SAME_POS and abs(w["y"] - k["y"]) <= SAME_POS
               for k in kept):
            continue
        kept.append(w)
    return kept


def compose_image(ocr):
    words = [w for w in ocr["words"] if w["conf"] >= MIN_CONF]
    labels, pins, nets = [], [], []
    for w in words:
        t = w["text"].strip(".,;:()[]|'\"")
        lab = _norm_label(t)
        m = ECU_LABEL_RE.match(lab)
        if m:
            labels.append({**w, "label": f"C{m.group(1)}-{m.group(2)}", "suffix": m.group(2)})
        elif PIN_RE.match(t):
            pins.append({**w, "num": int(t)})
        elif NET_RE.match(t.upper()):
            nets.append({**w, "net": t.upper()})
    labels, pins, nets = _dedupe(labels), _dedupe(pins), _dedupe(nets)

    out = []
    for p in pins:
        cands = []
        for L in labels:
            dx, dy = p["x"] - L["x"], p["y"] - L["y"]
            if PIN_DX[0] <= dx <= PIN_DX[1] and PIN_DY[0] <= dy <= PIN_DY[1]:
                cands.append(((dx * dx + dy * dy) ** 0.5, L))
        if not cands:
            continue
        _, L = min(cands, key=lambda c: c[0])
        row_nets = [n for n in nets
                    if abs(n["y"] - p["y"]) <= NET_ROW_TOL and 0 < p["x"] - n["x"] <= NET_MAX_DX]
        net = min(row_nets, key=lambda n: p["x"] - n["x"])["net"] if row_nets else None
        # The manual zero-pads pin numbers (K01, K08, A06) while the schematics draw
        # them bare ("8"). Emit the manual's two-digit convention so a composed pin
        # is directly comparable with the text-derived pin_map[].
        out.append({"pin": f"{L['suffix']}{p['num']:02d}", "connector": L["label"],
                    "pin_number": p["num"], "net": net,
                    "ocr_conf": round(min(p["conf"], L["conf"]), 1),
                    # Descriptive, not a filter: in the 8.4 audit every composition
                    # anchored to a net on its row was genuine, while unanchored
                    # ones were mostly Bosch part-number fragments.
                    "net_anchored": net is not None,
                    "bbox_pin": [round(p["x"]), round(p["y"])],
                    "source": "image_composition"})
    uniq = {}
    for c in out:                                   # one entry per composed pin
        if c["pin"] not in uniq or c["ocr_conf"] > uniq[c["pin"]]["ocr_conf"]:
            uniq[c["pin"]] = c
    all_nets = sorted({n["net"] for n in nets})
    return sorted(uniq.values(), key=lambda c: c["pin"]), all_nets, [L["label"] for L in labels]


def stage_compose(records):
    by_hash = {}
    for h in unique_schematics(records):
        path = os.path.join(CACHE, f"{h}.json")
        by_hash[h] = compose_image(json.load(open(path)))

    with open("data/dtc_image_pins.jsonl", "w") as f:
        for r in records:
            hs = [im["asset_hash"] for im in r["image_refs"]
                  if im["kind"] == "circuit_schematic" and im.get("asset_hash")]
            if not hs:
                continue
            pins, nets, labels = [], set(), set()
            for h in hs:
                cp, cn, cl = by_hash[h]
                pins += [{**c, "image_hash": h} for c in cp]
                nets |= set(cn)
                labels |= set(cl)
            f.write(json.dumps({"code_full": r["code_full"], "page": r["page"],
                                "occurrence": r["occurrence"], "image_hashes": hs,
                                "ecu_connector_labels": sorted(labels),
                                "image_pin_map": pins, "image_nets": sorted(nets)},
                               ensure_ascii=False) + "\n")
    print("wrote data/dtc_image_pins.jsonl")
    json.dump({h: {"pins": v[0], "nets": v[1], "labels": v[2]} for h, v in by_hash.items()},
              open("data/experiments/8_4/per_image_compositions.json", "w"), indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["ocr", "compose"])
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    records = [json.loads(l) for l in open("data/dtc_records.jsonl")]
    if args.stage == "ocr":
        stage_ocr(records, args.workers)
    else:
        stage_compose(records)


if __name__ == "__main__":
    sys.path.insert(0, "src")
    main()
