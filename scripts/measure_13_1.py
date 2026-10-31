"""
Phase 13.1 — safety measurement for the conversational pre-filter.

    PYTHONPATH=src .venv/bin/python scripts/measure_13_1.py

POST-HOC, COUNTS ONLY. This runs `classify()` and nothing else: no retriever is
built, no index is opened, no answer is produced, no metric is computed. The only
question asked is "how many rows would this filter have intercepted before they
reached the pipeline?", and the only acceptable answer on a coded or symptom row
is zero.

Nothing here tunes anything. The filter's rules were written and frozen in
src/conversational.py and src/test_conversational.py before this script ran; if a
count comes back non-zero the fix belongs in the RULE, never in the data, and the
report must say so.

Sets covered: DEV and TEST (both splits of data/gold_v2.json), the spent
independent set, and the spent R2 colleague set. R2 lives on the 11.x/12.x branch,
so it is read read-only with `git show` rather than copied onto this branch.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "src")

OUT = "data/experiments/13_1/prefilter_safety.json"
R2_REF = "phase12-symptom-bridge:data/gold_r2_colleague.json"
# modes where an interception would be a BUG: the row reports a fault or names a code
FAULT_MODES = {"symptom", "near_duplicate", "exact_code", "system_group", "no_dtc",
               "inconclusive"}


def load_sets():
    sets = {}
    gold = json.load(open("data/gold_v2.json"))["queries"]
    sets["DEV (gold_v2)"] = [q for q in gold if q["split"] == "DEV"]
    sets["TEST (gold_v2, spent)"] = [q for q in gold if q["split"] == "TEST"]
    sets["independent (spent)"] = json.load(open("data/gold_independent.json"))["queries"]
    try:
        blob = subprocess.run(["git", "show", R2_REF], capture_output=True, text=True,
                              check=True).stdout
        sets["R2 colleague (spent)"] = json.loads(blob)["queries"]
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"NOTE: R2 unavailable ({e.__class__.__name__}); it is not on this branch.")
    return sets


def main():
    import conversational as C

    report = {"label": "POST-HOC, counts only. classify() alone - no retrieval, no index, "
                       "no answer, no metric. Expected 0 on every coded or symptom row.",
              "filter": "src/conversational.py", "sets": {}}
    bugs = []

    for name, qs in load_sets().items():
        per_mode = defaultdict(lambda: {"rows": 0, "intercepted": 0, "labels": Counter(),
                                        "ids": []})
        for q in qs:
            label = C.classify(q["query"])
            m = per_mode[q["mode"]]
            m["rows"] += 1
            if label:
                m["intercepted"] += 1
                m["labels"][label] += 1
                m["ids"].append({"id": q["id"], "label": label})
                if q["mode"] in FAULT_MODES:
                    bugs.append({"set": name, "id": q["id"], "mode": q["mode"],
                                 "label": label, "query": q["query"]})
        total = sum(v["rows"] for v in per_mode.values())
        hit = sum(v["intercepted"] for v in per_mode.values())
        report["sets"][name] = {
            "rows": total, "intercepted": hit,
            "by_mode": {k: {"rows": v["rows"], "intercepted": v["intercepted"],
                            "labels": dict(v["labels"]), "intercepted_ids": v["ids"]}
                        for k, v in sorted(per_mode.items())}}
        print(f"\n{name}: {hit}/{total} intercepted")
        for mode, v in sorted(per_mode.items()):
            flag = "  <-- BUG" if v["intercepted"] and mode in FAULT_MODES else ""
            print(f"   {mode:15s} rows {v['rows']:3d}  intercepted {v['intercepted']}{flag}")

    report["bugs"] = bugs
    report["verdict"] = ("PASS - no coded or symptom row is intercepted on any set"
                         if not bugs else
                         f"FAIL - {len(bugs)} fault-reporting row(s) intercepted; fix the RULE")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w"), indent=1, default=str)
    print(f"\n{report['verdict']}")
    for b in bugs:
        print(f"   {b['set']} {b['id']} [{b['mode']}] -> {b['label']}: {b['query']!r}")
    print(f"wrote {OUT}")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
