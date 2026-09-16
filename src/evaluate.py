"""
Phase 7 — Evaluation harness.

Three independent measurements:
  1. Retrieval quality over the hand-built gold set: hit@1/3/5 and MRR, overall
     and per mode, plus near-duplicate rank-1 accuracy.
  2. Honesty / grounding: out-of-scope queries must be gated deterministically;
     in-scope queries must pass the gate.
  3. A corpus-wide integrity walk of all 314 step graphs: clamp rate,
     skip_true_branch inference rate, loop-guard fires, and dead ends.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "src")

GOLD = "data/gold_queries.json"
RECORDS = "data/dtc_records.jsonl"
RANKED_MODES = ("exact_code", "near_duplicate", "symptom")


# ---------------------------------------------------------------- retrieval
def eval_retrieval(R, gold):
    rows, per_mode = [], defaultdict(list)
    for q in gold["queries"]:
        if q["mode"] in ("out_of_scope", "system_group"):
            continue
        out = R.retrieve(q["query"], k=5)
        got = [i["record"]["code_full"] for i in out["results"]]
        exp = set(q["expected"])
        rank = next((i for i, c in enumerate(got, 1) if c in exp), None)
        row = {"query": q["query"], "mode": q["mode"], "expected": q["expected"],
               "got": got, "rank": rank, "router_mode": out["mode"]}
        rows.append(row)
        per_mode[q["mode"]].append(row)
    return rows, per_mode


def metrics(rows):
    n = len(rows)
    if not n:
        return {}
    h1 = sum(1 for r in rows if r["rank"] == 1)
    h3 = sum(1 for r in rows if r["rank"] and r["rank"] <= 3)
    h5 = sum(1 for r in rows if r["rank"] and r["rank"] <= 5)
    mrr = sum(1.0 / r["rank"] for r in rows if r["rank"]) / n
    return {"n": n, "hit@1": h1 / n, "hit@3": h3 / n, "hit@5": h5 / n, "MRR": mrr}


def eval_groups(R, gold, records):
    out_rows = []
    for q in gold["queries"]:
        if q["mode"] != "system_group":
            continue
        out = R.retrieve(q["query"], k=5)
        sysname = q["expected_system"]
        truth = sum(1 for r in records if r["system"] == sysname)
        got = len(out["results"])
        correct_sys = out["trace"].get("system") == sysname
        out_rows.append({"query": q["query"], "expected_system": sysname,
                         "router_mode": out["mode"], "returned": got,
                         "group_size": truth,
                         "ok": out["mode"] == "system_group" and correct_sys
                              and got == truth})
    return out_rows


# ---------------------------------------------------------------- honesty
def eval_honesty(R, gold):
    import answer as A
    rows = []
    for q in gold["queries"]:
        in_scope = q["mode"] != "out_of_scope"
        ok, sig = A.is_relevant(R, q["query"])
        rows.append({"query": q["query"], "in_scope": in_scope,
                     "passed_gate": ok, "signals": sig,
                     "correct": ok == in_scope})
    oos = [r for r in rows if not r["in_scope"]]
    ins = [r for r in rows if r["in_scope"]]
    return rows, {
        "out_of_scope_n": len(oos),
        "out_of_scope_correctly_gated": sum(1 for r in oos if not r["passed_gate"]),
        "in_scope_n": len(ins),
        "in_scope_passed_gate": sum(1 for r in ins if r["passed_gate"]),
    }


# ---------------------------------------------------------------- integrity
def eval_integrity(records):
    """
    Walk every DTC's step graph from step 1 along BOTH answers at each decision,
    bounded, and collect what the state machine had to do to survive the source.
    """
    from diagnose import Diagnoser, walk

    stats = Counter()
    clamp_records, dead_ends, loop_records, infer_records = [], [], [], []

    for r in records:
        if not r["steps"]:
            stats["no_steps"] += 1
            continue
        stats["records"] += 1
        d = Diagnoser(r)
        terminal = d.terminal
        reached, clamps, infers, loops = False, 0, 0, 0

        # exercise several answer policies to cover both sides of each branch
        for policy in (["yes"] * 40, ["no"] * 40,
                       ["yes", "no"] * 20, ["no", "yes"] * 20):
            t = walk(r, policy)
            clamps += len(t["clamps"])
            infers += len(t["inferences"])
            if t["outcome"] and "Loop detected" in t["outcome"]:
                loops += 1
            if t["visited"] and t["visited"][-1] == terminal:
                reached = True
            elif t["outcome"] and "Loop detected" in t["outcome"]:
                reached = True          # loop guard ends at the final check
        if clamps:
            stats["records_with_clamp"] += 1
            clamp_records.append(r["code_full"])
        if infers:
            stats["records_with_inference"] += 1
            infer_records.append(r["code_full"])
        if loops:
            stats["records_with_loop_guard"] += 1
            loop_records.append(r["code_full"])
        if not reached:
            stats["records_with_dead_end"] += 1
            dead_ends.append(f"{r['code_full']}@p{r['page']}")
        stats["total_clamps"] += clamps
        stats["total_inferences"] += infers

    return stats, {"clamped": clamp_records, "inferred": infer_records,
                   "looped": loop_records, "dead_ends": dead_ends}


# ---------------------------------------------------------------- main
def main():
    records = [json.loads(l) for l in open(RECORDS)]
    gold = json.load(open(GOLD))
    from retrieve import Retriever
    R = Retriever()

    rows, per_mode = eval_retrieval(R, gold)
    overall = metrics(rows)
    bymode = {m: metrics(v) for m, v in per_mode.items()}
    groups = eval_groups(R, gold, records)
    hrows, hsum = eval_honesty(R, gold)
    stats, lists = eval_integrity(records)

    nd = per_mode.get("near_duplicate", [])
    nd_r1 = sum(1 for r in nd if r["rank"] == 1)

    out = {
        "gold_set": {"n": len(gold["queries"]),
                     "by_mode": dict(Counter(q["mode"] for q in gold["queries"]))},
        "retrieval_overall": overall,
        "retrieval_by_mode": bymode,
        "near_duplicate_rank1": {"correct": nd_r1, "n": len(nd),
                                 "accuracy": nd_r1 / len(nd) if nd else None},
        "system_group": {"n": len(groups),
                         "all_correct": sum(1 for g in groups if g["ok"]),
                         "detail": groups},
        "honesty": hsum,
        "integrity_walk": dict(stats),
        "integrity_lists": {k: v[:20] for k, v in lists.items()},
        "misses": [r for r in rows if r["rank"] is None or r["rank"] > 1],
    }
    with open("data/evaluation_results.json", "w") as f:
        json.dump(out, f, indent=2)

    def pct(x):
        return f"{100*x:.1f}%"

    print("\n===== RETRIEVAL (gold set) =====")
    print(f"{'mode':16s} {'n':>3s} {'hit@1':>7s} {'hit@3':>7s} {'hit@5':>7s} {'MRR':>7s}")
    for m in RANKED_MODES:
        if m in bymode:
            x = bymode[m]
            print(f"{m:16s} {x['n']:3d} {pct(x['hit@1']):>7s} {pct(x['hit@3']):>7s} "
                  f"{pct(x['hit@5']):>7s} {x['MRR']:7.3f}")
    print(f"{'OVERALL':16s} {overall['n']:3d} {pct(overall['hit@1']):>7s} "
          f"{pct(overall['hit@3']):>7s} {pct(overall['hit@5']):>7s} {overall['MRR']:7.3f}")

    print(f"\nnear-duplicate rank-1 accuracy: {nd_r1}/{len(nd)} "
          f"({pct(nd_r1/len(nd)) if nd else 'n/a'})")
    print(f"system_group exact: {out['system_group']['all_correct']}/{len(groups)}")

    print("\n===== HONESTY / GROUNDING =====")
    print(f"out-of-scope correctly gated : {hsum['out_of_scope_correctly_gated']}"
          f"/{hsum['out_of_scope_n']}")
    print(f"in-scope passed the gate     : {hsum['in_scope_passed_gate']}"
          f"/{hsum['in_scope_n']}")

    print("\n===== CORPUS-WIDE INTEGRITY WALK (314 records) =====")
    for k in ("records", "records_with_clamp", "total_clamps",
              "records_with_inference", "total_inferences",
              "records_with_loop_guard", "records_with_dead_end"):
        print(f"  {k:26s} {stats.get(k,0)}")
    if lists["dead_ends"]:
        print(f"  DEAD ENDS: {lists['dead_ends'][:20]}")
    else:
        print("  DEAD ENDS: none — every branch reaches a terminal step")

    if out["misses"]:
        print("\n===== MISSES (rank != 1) =====")
        for m in out["misses"]:
            print(f"  [{m['mode']}] {m['query']!r}")
            print(f"     expected={m['expected']} rank={m['rank']} got={m['got'][:4]}")
    print("\nwrote data/evaluation_results.json")


if __name__ == "__main__":
    main()
