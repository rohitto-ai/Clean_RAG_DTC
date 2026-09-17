"""
Phase 8.4 measurement. Ground truth = the authoritative TEXT-derived pin_map[]
(high-confidence pins). Reads data/dtc_image_pins.jsonl; changes nothing.
"""
import json
from collections import Counter, defaultdict

CAL = "3801374525e2d294"
recs = {(r["code_full"], r["page"], r["occurrence"]): r
        for r in (json.loads(l) for l in open("data/dtc_records.jsonl"))}
img = [json.loads(l) for l in open("data/dtc_image_pins.jsonl")]
per_image = json.load(open("data/experiments/8_4/per_image_compositions.json"))


def canon(pin):
    """Pin identity = connector letter + integer pin number: K08 == K8 == C016-K pin 8.
    The manual zero-pads ("K08"); the schematics draw bare numbers ("8")."""
    import re
    m = re.fullmatch(r"([A-Z])(\d{1,3})", pin)
    return f"{m.group(1)}{int(m.group(2))}" if m else pin


def near_miss(text_pin, composed):
    """Same connector letter, same length, exactly one digit differs."""
    t = canon(text_pin)
    for c0 in composed:
        c = canon(c0)
        if c[0] == t[0] and len(c) == len(t) and c != t:
            if sum(a != b for a, b in zip(c, t)) == 1:
                return c0
    return None


def recall_rows(exclude_cal=False):
    rows = []
    for e in img:
        if exclude_cal and CAL in e["image_hashes"]:
            continue
        r = recs[(e["code_full"], e["page"], e["occurrence"])]
        text = [p["pin"] for p in r["pin_map"] if p["confidence"] == "high"]
        comp = {canon(p["pin"]) for p in e["image_pin_map"]}
        comp_nums = {p["pin_number"] for p in e["image_pin_map"]}
        for t in text:
            if canon(t) in comp:
                why = "found"
            elif not t[0] in "AK" or not t[1:].isdigit():
                why = "not a C016-A/K pin form"
            elif not e["ecu_connector_labels"]:
                why = "no ECU connector label read in image"
            elif f"C016-{t[0]}" not in e["ecu_connector_labels"]:
                why = f"C016-{t[0]} label not read in image"
            elif near_miss(t, comp):
                why = "near-miss: one digit misread"
            else:
                why = "label read, pin number not attached"
            rows.append({"code": e["code_full"], "images": e["image_hashes"], "text_pin": t,
                         "outcome": why, "near": near_miss(t, comp)})
    return rows


def summarise(rows, label):
    n = len(rows); f = sum(r["outcome"] == "found" for r in rows)
    print(f"{label}: {f}/{n} = {100*f/n:.1f}%")
    return f, n


out = {}
print("===== RECALL of text-cited pins (ground truth) =====")
R = recall_rows()
out["record_level"] = summarise(R, "record-level (all 135 schematic records)")
R_ex = recall_rows(exclude_cal=True)
out["record_level_excl_calibration"] = summarise(R_ex, "record-level, EXCLUDING calibration image")

# unique (image, pin) level: records share images, so dedupe repeated schematics
uniq = {}
for r in R:
    key = (tuple(r["images"]), r["text_pin"])
    if key not in uniq or r["outcome"] == "found":
        uniq[key] = r
U = list(uniq.values())
out["unique_image_pin_level"] = summarise(U, "unique (schematic, pin) pairs")
U_ex = [u for u in U if CAL not in u["images"]]
out["unique_excl_calibration"] = summarise(U_ex, "unique pairs, EXCLUDING calibration image")

cform = [u for u in U if u["outcome"] != "not a C016-A/K pin form"]
out["unique_composable_form"] = summarise(cform, "unique pairs, composable A/K form only")

print("\n===== WHY pins were missed (unique pairs) =====")
reasons = Counter(u["outcome"] for u in U)
for k, v in reasons.most_common():
    print(f"  {v:3d}  {k}")
nm = [u for u in U if u["outcome"] == "near-miss: one digit misread"]
print("  near-miss examples:", [(u["text_pin"], u["near"]) for u in nm[:8]])

print("\n===== NEW-INFO YIELD =====")
text_by_image = defaultdict(set)
for e in img:
    r = recs[(e["code_full"], e["page"], e["occurrence"])]
    for h in e["image_hashes"]:
        text_by_image[h] |= {canon(p["pin"]) for p in r["pin_map"]}
confirmed, unconfirmed, nets_total, nets_with_pin = 0, [], 0, 0
all_text_tokens = {p["pin"] for r in recs.values() for p in r["pin_map"]}
for h, v in per_image.items():
    for p in v["pins"]:
        if canon(p["pin"]) in text_by_image[h]:
            confirmed += 1
        else:
            unconfirmed.append({"image": h, **p})
    nets_total += len(v["nets"])
    nets_with_pin += sum(1 for p in v["pins"] if p["net"])
comp_total = sum(len(v["pins"]) for v in per_image.values())
print(f"composed pins (unique per image): {comp_total}")
print(f"  confirmed by text of a record using that image: {confirmed} ({100*confirmed/comp_total:.1f}%)")
print(f"  NOT in text (new-info CANDIDATES, unverified): {len(unconfirmed)}")
print(f"  ...of which one digit away from a text pin on that image (likely misreads): "
      f"{sum(1 for u in unconfirmed if near_miss(u['pin'], text_by_image[u['image']]))}")
print(f"net tokens read (unique per image): {nets_total}; composed pins carrying a net: {nets_with_pin}")
print(f"images with >=1 composed pin: {sum(1 for v in per_image.values() if v['pins'])}/30")
out.update({"composed_total": comp_total, "confirmed": confirmed,
            "unconfirmed": len(unconfirmed), "nets_total": nets_total,
            "nets_with_pin": nets_with_pin, "miss_reasons": dict(reasons)})
json.dump(unconfirmed, open("data/experiments/8_4/unconfirmed_compositions.json", "w"), indent=1)
json.dump(out, open("data/experiments/8_4/measurement.json", "w"), indent=1)
print("\nwrote data/experiments/8_4/measurement.json")
