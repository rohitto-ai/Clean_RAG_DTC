"""
Phase 13.4 — measurements for the invalid-code rule.

    PYTHONPATH=src .venv/bin/python scripts/measure_13_4.py             # both
    PYTHONPATH=src .venv/bin/python scripts/measure_13_4.py --probe --out X

A) GARBAGE PROBE. 200 code-SHAPED tokens built deterministically (seeded) from
   the dictionary's own codes: trailing junk, illegal characters, over-long digit
   runs. Synthetic; no gold file. Records which route answers each one and how
   many come back with a ranked list of codes. Runs at the old commit too, which
   is how the BEFORE column is produced.

B) INTERCEPTION COUNT, POST-HOC, COUNTS ONLY. detect_invalid() alone, no
   retrieval, over DEV, TEST, the spent independent set and the spent R2 set.
   The only acceptable answer on a symptom or coded row is zero.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

OUT = "data/experiments/13_4/measurements.json"
R2_REF = "phase12-symptom-bridge:data/gold_r2_colleague.json"
N_PROBE = 200
FAULT_MODES = {"symptom", "near_duplicate", "exact_code", "system_group", "no_dtc",
               "inconclusive"}
JUNK = "efazrgddhdhdfgddhyxqwkmnpv"


def probe_forms():
    by_full = json.load(open("index/code_index.json"))["by_code_full"]
    rs = random.Random("13.4:garbage")
    codes = sorted(by_full)
    forms = []
    while len(forms) < N_PROBE:
        c = codes[rs.randrange(len(codes))]
        base = c.split("-")[0]                      # e.g. P0192
        kind = len(forms) % 4
        if kind == 0:                               # base + long junk tail
            tok = base + "".join(rs.choice(JUNK) for _ in range(rs.randint(6, 18)))
        elif kind == 1:                             # over-long digit run
            tok = base[0] + "".join(rs.choice("0123456789") for _ in range(rs.randint(8, 14)))
        elif kind == 2:                             # illegal characters inside
            tok = base + rs.choice("zz#@$%") + "".join(rs.choice(JUNK) for _ in range(4))
        else:                                       # full code + junk, no boundary
            tok = c.replace("-", "") + "".join(rs.choice(JUNK) for _ in range(rs.randint(5, 10)))
        forms.append({"source_code": c, "form": tok, "kind": ["tail", "digits", "illegal",
                                                              "nodash"][kind]})
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
        rows.append({**f, "mode": out["mode"], "returned": got})
        by_kind[f["kind"]][out["mode"]] += 1
    modes = Counter(r["mode"] for r in rows)
    ranked = sum(1 for r in rows if r["returned"])
    print("\nA) garbage code-token probe (synthetic, 200 forms):")
    for kind, counts in sorted(by_kind.items()):
        print(f"   {kind:9s} {dict(counts)}")
    print(f"   all {len(rows)} forms: {dict(modes)}")
    print(f"   forms answered with a RANKED LIST of codes: {ranked}/{len(rows)}")
    return {"n_forms": len(rows), "by_kind": {k: dict(v) for k, v in by_kind.items()},
            "by_mode": dict(modes), "forms_answered_with_a_ranked_list": ranked,
            "rows": rows}


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
        print(f"NOTE: R2 unavailable ({e.__class__.__name__}).")
    return sets


def run_interception():
    import partial_code as PC
    out, bugs = {}, []
    print("\nB) interception count (POST-HOC, counts only; detect_invalid alone):")
    for name, qs in load_sets().items():
        per = defaultdict(lambda: {"rows": 0, "intercepted": 0, "ids": []})
        for q in qs:
            hit = PC.detect_invalid(q["query"])
            m = per[q["mode"]]
            m["rows"] += 1
            if hit:
                m["intercepted"] += 1
                m["ids"].append(q["id"])
                if q["mode"] in FAULT_MODES:
                    bugs.append({"set": name, "id": q["id"], "mode": q["mode"],
                                 "query": q["query"], "detected": hit})
        total = sum(v["rows"] for v in per.values())
        hits = sum(v["intercepted"] for v in per.values())
        out[name] = {"rows": total, "intercepted": hits,
                     "by_mode": {k: {"rows": v["rows"], "intercepted": v["intercepted"],
                                     "intercepted_ids": v["ids"]} for k, v in sorted(per.items())}}
        print(f"   {name}: {hits}/{total} intercepted")
    return out, bugs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    report = {"label": "Phase 13.4. (A) synthetic garbage code-token probe. (B) POST-HOC "
                       "interception count, counts only - detect_invalid() alone.",
              "probe": run_probe()}
    if a.probe and a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump(report, open(a.out, "w"), indent=1, default=str)
        print(f"wrote {a.out}")
    if not a.probe:
        sets, bugs = run_interception()
        report["interception"] = sets
        report["bugs"] = bugs
        report["verdict"] = ("PASS - no symptom or coded row is intercepted" if not bugs
                             else f"FAIL - {len(bugs)} row(s) intercepted")
        print(f"\n{report['verdict']}")
        for b in bugs:
            print(f"   {b['set']} {b['id']} [{b['mode']}]: {b['query']!r}")
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump(report, open(OUT, "w"), indent=1, default=str)
        print(f"wrote {OUT}")
    return 1 if report.get("bugs") else 0


if __name__ == "__main__":
    sys.exit(main())
