"""
Phase 13.3 — two measurements for the incomplete-code rule.

    PYTHONPATH=src .venv/bin/python scripts/measure_13_3.py            # both
    PYTHONPATH=src .venv/bin/python scripts/measure_13_3.py --probe    # A only

A) PARTIAL-CODE PROBE. The 1,007-query robustness corpus only contains dropped
   digits WITH a sub-code ("P019-00"), which Phase 9.3b already refused. It
   contains no 1-3 digit attempt WITHOUT a sub-code ("P019", "P10"), which is the
   case that used to fall through to hybrid SYMPTOM retrieval. This probe builds
   those forms deterministically from the code dictionary - synthetic, no gold file
   - and records which route answers them. Run it at the old commit for the
   "before" column; it works there too, because it only reads routes.

B) INTERCEPTION COUNT, POST-HOC, COUNTS ONLY. detect_partial() alone, no
   retrieval, over every row of DEV, TEST, the spent independent set and the spent
   R2 colleague set. The only acceptable answer on a symptom row is zero.

Nothing here tunes anything: the rule was written and frozen in src/partial_code.py
before this ran.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

OUT = "data/experiments/13_3/measurements.json"
R2_REF = "phase12-symptom-bridge:data/gold_r2_colleague.json"
N_PROBE = 80
FAULT_MODES = {"symptom", "near_duplicate", "exact_code", "system_group", "no_dtc",
               "inconclusive"}


def probe_forms():
    """The partial forms, built deterministically from the dictionary itself."""
    import random
    by_full = json.load(open("index/code_index.json"))["by_code_full"]
    rs = random.Random("13.3:probe")
    codes = sorted(rs.sample(sorted(by_full), N_PROBE))
    forms = []
    for c in codes:                                   # c like "P0192-00"
        base, letter, digits = c.split("-")[0], c[0], c[1:5]
        forms.append({"code": c, "form": f"{letter}{digits[:3]}", "kind": "3 digits, no suffix"})
        forms.append({"code": c, "form": f"{letter}{digits[:2]}", "kind": "2 digits, no suffix"})
        forms.append({"code": c, "form": f"{letter}-{digits[:2]}", "kind": "2 digits, separator"})
    return forms


def run_probe():
    from cli import quiet_stderr
    with quiet_stderr():
        from retrieve import Retriever
        R = Retriever(index_dir="index")
    rows, by_kind = [], defaultdict(Counter)
    for f in probe_forms():
        out = R.retrieve(f["form"], k=3)
        got = [i["record"]["code_full"] for i in out["results"]]
        rows.append({**f, "mode": out["mode"], "returned": got,
                     "n_candidates": len(out["trace"].get("candidates") or [])})
        by_kind[f["kind"]][out["mode"]] += 1
    summary = {k: dict(v) for k, v in by_kind.items()}
    modes = Counter(r["mode"] for r in rows)
    print("\nA) partial-code probe (synthetic, from the dictionary):")
    for kind, counts in summary.items():
        print(f"   {kind:24s} {dict(counts)}")
    print(f"   all {len(rows)} forms: {dict(modes)}")
    ranked = sum(1 for r in rows if r["returned"])
    print(f"   forms answered with a RANKED LIST of codes: {ranked}/{len(rows)}")
    return {"n_forms": len(rows), "by_kind": summary, "by_mode": dict(modes),
            "forms_answered_with_a_ranked_list": ranked, "rows": rows}


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


def run_interception():
    import partial_code as PC
    out, bugs = {}, []
    print("\nB) interception count (POST-HOC, counts only; detect_partial alone):")
    for name, qs in load_sets().items():
        per = defaultdict(lambda: {"rows": 0, "intercepted": 0, "ids": []})
        for q in qs:
            p = PC.detect_partial(q["query"])
            m = per[q["mode"]]
            m["rows"] += 1
            if p:
                m["intercepted"] += 1
                m["ids"].append(q["id"])
                if q["mode"] in FAULT_MODES:
                    bugs.append({"set": name, "id": q["id"], "mode": q["mode"],
                                 "query": q["query"], "detected": p})
        total = sum(v["rows"] for v in per.values())
        hit = sum(v["intercepted"] for v in per.values())
        out[name] = {"rows": total, "intercepted": hit,
                     "by_mode": {k: {"rows": v["rows"], "intercepted": v["intercepted"],
                                     "intercepted_ids": v["ids"]} for k, v in sorted(per.items())}}
        print(f"   {name}: {hit}/{total} intercepted")
        for mode, v in sorted(per.items()):
            flag = "  <-- BUG" if v["intercepted"] and mode in FAULT_MODES else ""
            print(f"      {mode:15s} rows {v['rows']:3d}  intercepted {v['intercepted']}{flag}")
    return out, bugs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="run measurement A only")
    ap.add_argument("--out", default=None,
                    help="with --probe: where to write the probe result (used to capture the "
                         "BEFORE column from a worktree at the pre-change commit)")
    a = ap.parse_args()
    report = {"label": "Phase 13.3. (A) synthetic partial-code probe. (B) POST-HOC "
                       "interception count, counts only - detect_partial() alone, no retrieval.",
              "probe": run_probe()}
    if a.probe and a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump(report, open(a.out, "w"), indent=1, default=str)
        print(f"wrote {a.out}")
    if not a.probe:
        sets, bugs = run_interception()
        report["interception"] = sets
        report["bugs"] = bugs
        report["verdict"] = ("PASS - no symptom or coded row is intercepted"
                             if not bugs else f"FAIL - {len(bugs)} row(s) intercepted")
        print(f"\n{report['verdict']}")
        for b in bugs:
            print(f"   {b['set']} {b['id']} [{b['mode']}]: {b['query']!r}")
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump(report, open(OUT, "w"), indent=1, default=str)
        print(f"wrote {OUT}")
    return 1 if report.get("bugs") else 0


if __name__ == "__main__":
    sys.exit(main())
