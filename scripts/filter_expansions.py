"""
Phase 12.1 addendum — mechanical distinctiveness filter for the symptom expansions.

    PYTHONPATH=src .venv/bin/python scripts/filter_expansions.py

REMOVAL ONLY. No expansion is reworded, merged or rewritten; each one is either
kept exactly as generated or dropped, with the reason recorded.

Why: a small model asked "how does this fault show up?" answers "warning light
comes on" for almost any fault. Such a line is true but useless to retrieval -
it matches every query about a lamp and so separates nothing. Two mechanical
rules remove that class of text.

  RULE 1 - over-shared. Embed every expansion. For expansion e of record r,
           count the OTHER records holding at least one expansion with cosine
           >= 0.90 to e. Drop e when that count is greater than 10.

  RULE 2 - generic-only. An expansion whose content is nothing but a generic
           behaviour (a lamp on its own, smoke on its own, a noise on its own,
           power dropping on its own) is dropped UNLESS the record's own fields
           - description, effect, MIL, causes, checkpoints - mention that
           behaviour. The manual carries no smoke or noise vocabulary at all, so
           those are dropped everywhere; "MIL: On" is genuine lamp evidence and
           keeps a lamp line (rule 1 usually removes it anyway).

  FLOOR  - keep at least 2 expansions per record where the record has 2. If
           filtering would go below that, the least-shared dropped lines are
           restored until the floor is met, and the restoration is recorded.

Uses development data only (the records themselves). No gold or evaluation file
is opened.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

IN = "data/symptom_expansions.json"
OUT = "data/symptom_expansions_filtered.json"
REPORT = "data/experiments/12_1/filter_report.json"
SIM_THRESHOLD = 0.90
MAX_OTHER_RECORDS = 10
FLOOR = 2
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# A generic behaviour, plus the words in a record's own fields that would justify
# keeping a line that says only that.
GENERIC = {
    "lamp": (re.compile(r"\b(?:warning|dash(?:board)?|check[- ]engine|engine|amber|red)?\s*"
                        r"(?:light|lamp|mil|telltale)\b", re.I),
             re.compile(r"\bmil\b|\blamp\b|\blight\b|\bcel\b", re.I)),
    "smoke": (re.compile(r"\bsmoke|smoky|smoking\b", re.I),
              re.compile(r"\bsmoke|smoky|soot\b", re.I)),
    "noise": (re.compile(r"\bnoise|noisy|rattle|knock|whine|hiss|squeal|loud\b", re.I),
              re.compile(r"\bnoise|rattle|knock|whine|hiss|squeal\b", re.I)),
    "power": (re.compile(r"\b(?:power|pull(?:ing)?|torque|acceleration)\b", re.I),
              re.compile(r"\btorque\b|\bpower\b|\bderate|\blimp|\bhalt|\bcreep|"
                         r"\binducement|\blimitation|\breduction\b", re.I)),
    "start": (re.compile(r"\bstart(?:s|ing)?|crank(?:s|ing)?\b", re.I),
              re.compile(r"\bstart|crank\b", re.I)),
}

# Words that carry no distinguishing information on their own.
FILLER = set("""
a an and are as at be been but by can comes could did do does engine for from
gets getting go goes going had has have how in into is it its may might more most
much must no not of off on once only or our out over she should so some
such than that the their them then there these they this those through to too
under until up very was we were what when where which while who why will with
would yet you your car vehicle truck driver sometimes often during after before
feels feel seems seem appears appear becomes become gets get looks look
""".split())


def content_words(text):
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in FILLER and len(w) > 2]


def generic_only(text):
    """
    Which generic concepts does this line consist of, if any?

    A line is generic-only when every content word it has belongs to one or more
    generic concepts (plus filler). "Warning light flashes" is generic-only;
    "coolant gauge reads high" is not, because 'coolant' and 'gauge' survive.
    """
    words = content_words(text)
    if not words:
        return ["empty"]
    concepts, leftover = [], []
    for w in words:
        hit = [c for c, (pat, _) in GENERIC.items() if pat.fullmatch(w) or pat.search(w)]
        if hit:
            concepts.extend(hit)
        else:
            leftover.append(w)
    # allow one leftover verb-ish word ("flashes", "drops") before calling it specific
    return sorted(set(concepts)) if concepts and len(leftover) <= 1 else []


def record_text(rec):
    return " ".join([rec.get("description") or "", rec.get("effect") or "",
                     f"MIL {rec.get('MIL') or ''}", " ".join(rec.get("cause") or []),
                     " ".join(rec.get("checkpoints") or [])])


def main():
    blob = json.load(open(IN))
    per_record = blob["records"]
    records = {f"{r['code_full']}@p{r['page']}#{r['occurrence']}": r
               for r in (json.loads(l) for l in open("data/dtc_records.jsonl"))}

    flat, owner = [], []
    for rid, v in per_record.items():
        for e in v["expansions"]:
            flat.append(e)
            owner.append(rid)
    print(f"{len(per_record)} records, {len(flat)} expansions")

    from sentence_transformers import SentenceTransformer
    import numpy as np
    print("embedding ...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    vecs = model.encode(flat, batch_size=64, normalize_embeddings=True,
                        convert_to_numpy=True, show_progress_bar=False)
    del model

    # RULE 1: how many OTHER records hold a near-identical line?
    print(f"counting near-duplicates at cosine >= {SIM_THRESHOLD} ...")
    sims = vecs @ vecs.T
    owner_arr = np.array(owner)
    shared_counts, shared_with = [], []
    for i in range(len(flat)):
        close = np.where(sims[i] >= SIM_THRESHOLD)[0]
        others = sorted({owner_arr[j] for j in close if owner_arr[j] != owner[i]})
        shared_counts.append(len(others))
        shared_with.append(others)

    # decide
    kept, dropped, restored = {}, {}, {}
    for rid, v in per_record.items():
        idx = [i for i, o in enumerate(owner) if o == rid]
        rec_txt = record_text(records[rid]) if rid in records else ""
        decisions = []
        for i in idx:
            text = flat[i]
            reasons = []
            if shared_counts[i] > MAX_OTHER_RECORDS:
                reasons.append(f"shared with {shared_counts[i]} other records "
                               f"(cosine >= {SIM_THRESHOLD})")
            concepts = generic_only(text)
            if concepts:
                unsupported = [c for c in concepts
                               if c in GENERIC and not GENERIC[c][1].search(rec_txt)]
                if unsupported:
                    reasons.append("generic-only (" + ", ".join(concepts)
                                   + ") and the record's own fields do not mention "
                                   + ", ".join(unsupported))
            decisions.append({"i": i, "text": text, "shared": shared_counts[i],
                              "reasons": reasons})
        keep = [d for d in decisions if not d["reasons"]]
        drop = [d for d in decisions if d["reasons"]]
        # FLOOR: restore the least-shared dropped lines if we fell below it
        back = []
        if len(keep) < min(FLOOR, len(decisions)):
            for d in sorted(drop, key=lambda d: d["shared"]):
                if len(keep) >= min(FLOOR, len(decisions)):
                    break
                keep.append(d)
                back.append(d)
                drop = [x for x in drop if x is not d]
        kept[rid] = [d["text"] for d in sorted(keep, key=lambda d: d["i"])]
        dropped[rid] = [{"text": d["text"], "shared": d["shared"], "reasons": d["reasons"]}
                        for d in drop]
        if back:
            restored[rid] = [{"text": d["text"], "shared": d["shared"],
                              "reasons": d["reasons"]} for d in back]

    n_before = len(flat)
    n_after = sum(len(v) for v in kept.values())
    per_rec_after = Counter(len(v) for v in kept.values())
    # DISTINCT texts: the same generic line is removed from dozens of records, so a
    # raw top-20 would be twenty copies of one sentence and say nothing.
    worst = {}
    for rid, ds in dropped.items():
        for d in ds:
            cur = worst.get(d["text"])
            if cur is None or d["shared"] > cur["shared_with_other_records"]:
                worst[d["text"]] = {"shared_with_other_records": d["shared"],
                                    "text": d["text"], "example_record": rid,
                                    "removed_from_n_records": 0}
    for rid, ds in dropped.items():
        for d in ds:
            worst[d["text"]]["removed_from_n_records"] += 1
    top20 = sorted(worst.values(), key=lambda x: -x["shared_with_other_records"])[:20]

    out = dict(blob)
    out["_label"] = "index-only, never shown to users"
    out["filter"] = {
        "applied": "Phase 12.1 addendum, mechanical distinctiveness filter (removal only)",
        "rule_1": f"drop if shared with more than {MAX_OTHER_RECORDS} other records at "
                  f"cosine >= {SIM_THRESHOLD}",
        "rule_2": "drop generic-only lines (lamp / smoke / noise / power / start) unless the "
                  "record's own fields mention that behaviour",
        "floor": f"keep at least {FLOOR} expansions per record where available; restorations "
                 f"are recorded",
        "embedder": MODEL_NAME,
        "expansions_before": n_before, "expansions_after": n_after,
        "dropped": n_before - n_after,
        "records_with_restorations": len(restored),
    }
    out["records"] = {rid: {**per_record[rid], "expansions": kept[rid],
                            "filtered_out": dropped[rid],
                            "restored_to_meet_floor": restored.get(rid, [])}
                      for rid in per_record}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    json.dump({"summary": out["filter"],
               "per_record_kept_histogram": dict(sorted(per_rec_after.items())),
               "dropped_per_record": {rid: len(ds) for rid, ds in dropped.items() if ds},
               "top_20_most_shared_removed": top20,
               "restorations": restored},
              open(REPORT, "w"), indent=1, ensure_ascii=False)

    print(f"\nexpansions {n_before} -> {n_after} (dropped {n_before - n_after}, "
          f"{(n_before - n_after) / n_before:.0%})")
    print(f"per-record kept histogram: {dict(sorted(per_rec_after.items()))}")
    print(f"records needing a restoration to meet the floor: {len(restored)}")
    print("\nthe 20 most-shared removed expansions (distinct texts):")
    for t in top20:
        print(f"  shared with {t['shared_with_other_records']:3d} other records, "
              f"removed from {t['removed_from_n_records']:3d}: {t['text']}")
    print(f"\nwrote {OUT} and {REPORT}")


if __name__ == "__main__":
    main()
