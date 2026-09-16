"""
Phase 8.0 — Evaluation on gold_v2 with a frozen DEV/TEST split.

Reuses the Phase 7 metric functions unchanged (src/evaluate.py is left
byte-identical so v1 numbers stay reproducible).

TEST DISCIPLINE: TEST results are reported as AGGREGATES ONLY. Per-query output
is printed for DEV and never for TEST - looking at individual TEST misses is
exactly how a frozen split gets tuned against.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, "src")

RANKED = ("exact_code", "near_duplicate", "symptom")


def run(R, queries, records, A):
    import evaluate as E
    ranked_rows, groups, honesty = [], [], []
    for q in queries:
        in_scope = q["mode"] != "out_of_scope"
        ok, sig = A.is_relevant(R, q["query"])
        honesty.append({"id": q["id"], "in_scope": in_scope, "passed": ok})

        if q["mode"] in RANKED:
            out = R.retrieve(q["query"], k=5)
            got = [i["record"]["code_full"] for i in out["results"]]
            exp = set(q["expected"])
            rank = next((i for i, c in enumerate(got, 1) if c in exp), None)
            ranked_rows.append({"id": q["id"], "query": q["query"], "mode": q["mode"],
                                "expected": q["expected"], "got": got, "rank": rank})
        elif q["mode"] == "system_group":
            out = R.retrieve(q["query"], k=5)
            got = {i["record"]["code_full"] for i in out["results"]}
            exp = set(q["expected"])
            groups.append({"id": q["id"], "query": q["query"],
                           "router_mode": out["mode"],
                           "detected_system": out["trace"].get("system"),
                           "expected_system": q.get("expected_system"),
                           "complete": out["mode"] == "system_group" and got == exp,
                           "returned": len(got), "expected_n": len(exp)})
    by_mode = {}
    for m in RANKED:
        rows = [r for r in ranked_rows if r["mode"] == m]
        by_mode[m] = E.metrics(rows) if rows else None
    overall = E.metrics(ranked_rows) if ranked_rows else None
    oos = [h for h in honesty if not h["in_scope"]]
    ins = [h for h in honesty if h["in_scope"]]
    return {
        "by_mode": by_mode, "overall": overall,
        "system_group": {"complete": sum(g["complete"] for g in groups),
                         "n": len(groups)},
        "honesty": {"oos_gated": sum(1 for h in oos if not h["passed"]),
                    "oos_n": len(oos),
                    "in_scope_passed": sum(1 for h in ins if h["passed"]),
                    "in_scope_n": len(ins)},
        "_rows": ranked_rows, "_groups": groups, "_honesty": honesty,
    }


def table(res, label):
    pct = lambda x: f"{100*x:5.1f}%"
    print(f"\n===== {label} =====")
    print(f"{'mode':16s} {'n':>3s} {'hit@1':>7s} {'hit@3':>7s} {'hit@5':>7s} {'MRR':>6s}")
    for m in RANKED:
        x = res["by_mode"][m]
        if x:
            print(f"{m:16s} {x['n']:3d} {pct(x['hit@1']):>7s} {pct(x['hit@3']):>7s} "
                  f"{pct(x['hit@5']):>7s} {x['MRR']:6.3f}")
    o = res["overall"]
    print(f"{'OVERALL':16s} {o['n']:3d} {pct(o['hit@1']):>7s} {pct(o['hit@3']):>7s} "
          f"{pct(o['hit@5']):>7s} {o['MRR']:6.3f}")
    g, h = res["system_group"], res["honesty"]
    print(f"system_group complete : {g['complete']}/{g['n']}")
    print(f"out-of-scope gated    : {h['oos_gated']}/{h['oos_n']}")
    print(f"in-scope passed gate  : {h['in_scope_passed']}/{h['in_scope_n']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="data/gold_v2.json")
    ap.add_argument("--out", default="data/baseline_v2.json")
    ap.add_argument("--label", default="baseline")
    args = ap.parse_args()

    gold = json.load(open(args.gold))
    records = [json.loads(l) for l in open("data/dtc_records.jsonl")]
    from retrieve import Retriever
    import answer as A
    R = Retriever()

    dev = [q for q in gold["queries"] if q["split"] == "DEV"]
    test = [q for q in gold["queries"] if q["split"] == "TEST"]
    rd, rt = run(R, dev, records, A), run(R, test, records, A)

    table(rd, f"DEV ({len(dev)} queries) — {args.label}")
    table(rt, f"TEST ({len(test)} queries, FROZEN, aggregates only) — {args.label}")

    print("\n----- DEV per-query misses (rank != 1) -----")
    for r in rd["_rows"]:
        if r["rank"] != 1:
            print(f"  {r['id']} [{r['mode']}] {r['query']!r}")
            print(f"       expected={r['expected'][:3]} rank={r['rank']} got={r['got'][:3]}")
    for g in rd["_groups"]:
        if not g["complete"]:
            print(f"  {g['id']} [system_group] {g['query']!r} router={g['router_mode']} "
                  f"detected={g['detected_system']} returned={g['returned']}/{g['expected_n']}")
    for h in rd["_honesty"]:
        if h["passed"] == (not h["in_scope"]):
            kind = "LEAKED" if not h["in_scope"] else "WRONGLY GATED"
            q = next(x for x in dev if x["id"] == h["id"])
            print(f"  {h['id']} [gate {kind}] {q['query']!r}")
    print("\n(TEST per-query output intentionally withheld — frozen split.)")

    strip = lambda r: {k: v for k, v in r.items() if not k.startswith("_")}
    json.dump({"label": args.label, "gold": args.gold,
               "DEV": strip(rd), "TEST": strip(rt)},
              open(args.out, "w"), indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
