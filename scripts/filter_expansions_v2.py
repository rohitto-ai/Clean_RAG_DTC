"""
Phase 12.2 step 4 — mechanical over-sharing filter for the authored expansions.

    PYTHONPATH=src .venv/bin/python scripts/filter_expansions_v2.py

REMOVAL ONLY, ONE RULE. Embed every expansion. For expansion e of record r, count
the OTHER records that hold at least one expansion with cosine >= 0.90 to e. Drop
e when that count is greater than 5.

This is stricter than the 12.1 addendum (which allowed 10) and, as the task
specifies, there is NO restoration floor: a record that loses everything loses
everything, and that is reported rather than papered over. The 12.1 generic-only
rule is not needed here - the authored lines carry no bare lamp, smoke, noise or
power text for it to catch.

`scripts/filter_expansions.py` is covered by the Phase 12.1 freeze, so this is a
separate file rather than an edit to it.

Development data only: the inputs are the authored expansions and nothing else.
No gold or evaluation file is opened.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

IN = "data/symptom_expansions_v2.json"
OUT = "data/symptom_expansions_v2_filtered.json"
REPORT = "data/experiments/12_2/filter_report.json"
SIM_THRESHOLD = 0.90
MAX_OTHER_RECORDS = 5
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    blob = json.load(open(IN))
    per_record = blob["records"]

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

    print(f"counting near-duplicates at cosine >= {SIM_THRESHOLD} ...")
    sims = vecs @ vecs.T
    owner_arr = np.array(owner)
    shared = []
    for i in range(len(flat)):
        close = np.where(sims[i] >= SIM_THRESHOLD)[0]
        shared.append(len({owner_arr[j] for j in close if owner_arr[j] != owner[i]}))

    kept, dropped = {}, {}
    for rid, v in per_record.items():
        idx = [i for i, o in enumerate(owner) if o == rid]
        kept[rid] = [flat[i] for i in idx if shared[i] <= MAX_OTHER_RECORDS]
        dropped[rid] = [{"text": flat[i], "shared_with_other_records": shared[i]}
                        for i in idx if shared[i] > MAX_OTHER_RECORDS]

    n_before, n_after = len(flat), sum(len(v) for v in kept.values())
    hist = Counter(len(v) for v in kept.values())
    emptied = [rid for rid, v in kept.items() if not v]

    # distinct texts, so the table is not twenty copies of one sentence
    worst = {}
    for rid, ds in dropped.items():
        for d in ds:
            cur = worst.setdefault(d["text"], {"text": d["text"],
                                               "shared_with_other_records": 0,
                                               "removed_from_n_records": 0,
                                               "example_record": rid})
            cur["shared_with_other_records"] = max(cur["shared_with_other_records"],
                                                   d["shared_with_other_records"])
            cur["removed_from_n_records"] += 1
    top = sorted(worst.values(), key=lambda x: -x["shared_with_other_records"])[:20]

    out = dict(blob)
    out["_label"] = "index-only, never shown to users"
    out["filter"] = {
        "applied": "Phase 12.2 step 4, mechanical over-sharing filter (removal only)",
        "rule": f"drop an expansion shared with MORE THAN {MAX_OTHER_RECORDS} other records "
                f"at cosine >= {SIM_THRESHOLD}",
        "restoration_floor": "none, as specified",
        "embedder": MODEL_NAME,
        "expansions_before": n_before, "expansions_after": n_after,
        "dropped": n_before - n_after,
        "records_emptied": len(emptied),
    }
    out["records"] = {rid: {**per_record[rid], "expansions": kept[rid],
                            "expansions_kept": len(kept[rid]),
                            "filtered_out": dropped[rid]}
                      for rid in per_record}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    json.dump({"summary": out["filter"],
               "per_record_kept_histogram": dict(sorted(hist.items())),
               "records_emptied": emptied,
               "dropped_per_record": {rid: len(ds) for rid, ds in dropped.items() if ds},
               "top_20_most_shared_removed": top},
              open(REPORT, "w"), indent=1, ensure_ascii=False)

    print(f"\nexpansions {n_before} -> {n_after} (dropped {n_before - n_after}, "
          f"{(n_before - n_after) / n_before:.0%})")
    print(f"per-record kept histogram: {dict(sorted(hist.items()))}")
    print(f"records left with none: {len(emptied)}")
    print("\nthe most-shared removed expansions (distinct texts):")
    for t in top[:12]:
        print(f"  shared with {t['shared_with_other_records']:3d} others, removed from "
              f"{t['removed_from_n_records']:3d}: {t['text'][:86]}")
    print(f"\nwrote {OUT} and {REPORT}")


if __name__ == "__main__":
    main()
