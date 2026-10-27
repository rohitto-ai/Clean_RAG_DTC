"""
Phase 11.1 — measure the two refinements.

    PYTHONPATH=src .venv/bin/python scripts/refine_eval_11_1.py --stage dev
    PYTHONPATH=src .venv/bin/python scripts/refine_eval_11_1.py --stage independent

Two stages, deliberately separated by the freeze:

  dev          DEV (gold v2.2) + the spent TEST + the 14 near-duplicate
               guardrails. This is the no-regression gate, and DEV is where the
               prior weight was chosen.
  independent  the independent set, POST-HOC. Every number it produces is
               development data now: the set was spent once in Phase 10.6, and
               these refinements were written after reading its error analysis.

Configurations (production is never modified):
  base   production C4b + gate v2
  A      + the no-DTC-match detector (src/no_dtc.py)
  B      + the soft subsystem prior (Retriever(subsystem_prior=W))
  AB     both
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

PRIOR_W = 0.5          # chosen on DEV (see the report); saturates above this
OUT_DIR = "data/experiments/11_1"
K = 5

CONFIGS = [
    ("base", {"no_dtc": False, "prior": 0.0}, "production C4b + gate v2"),
    ("A", {"no_dtc": True, "prior": 0.0}, "+ no-DTC-match detector"),
    ("B", {"no_dtc": False, "prior": PRIOR_W}, f"+ subsystem prior (w={PRIOR_W})"),
    ("AB", {"no_dtc": True, "prior": PRIOR_W}, "+ both"),
]


def serve(R, A, ND, query, use_no_dtc):
    """
    Production path plus, optionally, the no-DTC-match check in front of it.

    The check runs BEFORE retrieval: if the query is mechanical evidence with no
    electronic evidence, no code list is produced at all.
    """
    if use_no_dtc:
        v = ND.detect(query)
        if v["no_dtc_match"]:
            return {"codes": [], "declined": True, "decline_by": "no_dtc_match",
                    "areas": v["areas"], "reasons": v["reasons"], "route": "no_dtc_match"}
    out = R.retrieve(query, k=K)
    if out["mode"] == "hybrid":
        ok, sig = A.is_relevant(R, query)
        if not ok:
            return {"codes": [], "declined": True, "decline_by": "gate",
                    "reasons": sig.get("refusal_reasons"), "route": out["mode"]}
    codes, seen = [], set()
    for item in out["results"]:
        c = item["record"]["code_full"]
        if c not in seen:
            seen.add(c)
            codes.append(c)
    # the subsystem-group route answers with the WHOLE group (14-18 codes); only
    # the ranked routes are a top-5 list
    limit = len(codes) if out["mode"] == "system_group" else K
    return {"codes": codes[:limit], "declined": not codes, "decline_by": None,
            "route": out["mode"]}


def ranked_metrics(rows):
    n = len(rows)
    if not n:
        return {}
    ranks = [r["rank"] for r in rows]
    hit = lambda k: sum(1 for x in ranks if x and x <= k) / n
    return {"n": n, "hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5),
            "MRR": sum((1.0 / x) if x else 0.0 for x in ranks) / n,
            "false_declines": sum(1 for r in rows if r["declined"]),
            "false_decline_ids": [r["id"] for r in rows if r["declined"]]}


def build(cfg):
    from cli import quiet_stderr
    with quiet_stderr():
        import answer as A
        import no_dtc as ND
        from retrieve import Retriever
        R = Retriever(subsystem_prior=cfg["prior"])
    return R, A, ND


def run_gold_v2(split, cfg):
    """DEV or TEST from gold v2.2, with the honesty accounting."""
    R, A, ND = build(cfg)
    gold = json.load(open("data/gold_v2.json"))
    qs = [q for q in gold["queries"] if q["split"] == split]
    ranked, groups, oos_declined, in_scope_passed, rows = [], [], 0, 0, []
    for q in qs:
        s = serve(R, A, ND, q["query"], cfg["no_dtc"])
        exp = set(q["expected"])
        rank = next((i for i, c in enumerate(s["codes"], 1) if c in exp), None)
        rows.append({"id": q["id"], "mode": q["mode"], "declined": s["declined"],
                     "decline_by": s["decline_by"], "rank": rank, "codes": s["codes"]})
        if q["mode"] in ("exact_code", "near_duplicate", "symptom"):
            ranked.append({"id": q["id"], "mode": q["mode"], "rank": rank,
                           "declined": s["declined"]})
        elif q["mode"] == "system_group":
            groups.append(set(s["codes"]) == exp)
        if q["mode"] == "out_of_scope":
            oos_declined += s["declined"]
        else:
            in_scope_passed += not s["declined"]
    by_mode = {m: ranked_metrics([r for r in ranked if r["mode"] == m])
               for m in ("exact_code", "near_duplicate", "symptom")}
    return {"by_mode": by_mode, "overall": ranked_metrics(ranked),
            "system_group_complete": sum(groups), "system_group_n": len(groups),
            "oos_declined": oos_declined,
            "oos_n": sum(1 for q in qs if q["mode"] == "out_of_scope"),
            "in_scope_passed": in_scope_passed,
            "in_scope_n": sum(1 for q in qs if q["mode"] != "out_of_scope"),
            "rows": rows}


def run_independent(cfg):
    R, A, ND = build(cfg)
    qs = json.load(open("data/gold_independent.json"))["queries"]
    sym, nod, rows = [], [], []
    for q in qs:
        s = serve(R, A, ND, q["query"], cfg["no_dtc"])      # q["query"] ONLY
        exp = set(q["expected"])
        rank = next((i for i, c in enumerate(s["codes"], 1) if c in exp), None)
        row = {"id": q["id"], "mode": q["mode"], "confidence": q["confidence"],
               "rank": rank, "declined": s["declined"], "decline_by": s["decline_by"],
               "codes": s["codes"], "areas": s.get("areas")}
        rows.append(row)
        (sym if q["mode"] == "symptom" else nod).append(row)
    declined = sum(1 for r in nod if r["declined"])
    return {"symptom": ranked_metrics(sym),
            "no_dtc": {"n": len(nod), "declined": declined,
                       "decline_rate": declined / len(nod) if nod else 0.0,
                       "declined_ids": [r["id"] for r in nod if r["declined"]],
                       "still_answered": {r["id"]: r["codes"][:3]
                                          for r in nod if not r["declined"]}},
            "rows": rows}


def guardrails(cfg):
    import bench_8_2 as B
    from cli import quiet_stderr
    with quiet_stderr():
        from retrieve import Retriever
        R = Retriever(subsystem_prior=cfg["prior"])
        g = B.guardrails(R)
    return {"passed": sum(x["pass"] for x in g), "n": len(g),
            "failing": [x.get("query") for x in g if not x["pass"]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["dev", "independent"], required=True)
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)

    if a.stage == "dev":
        out = {"prior_weight": PRIOR_W, "configs": {}}
        for key, cfg, desc in CONFIGS:
            print(f"\n[{key}] {desc}")
            dev = run_gold_v2("DEV", cfg)
            test = run_gold_v2("TEST", cfg)
            gr = guardrails(cfg)
            out["configs"][key] = {"description": desc, "cfg": cfg, "DEV": dev,
                                   "TEST_post_hoc": test, "guardrails": gr}
            for name, r in (("DEV", dev), ("TEST", test)):
                s = r["by_mode"]["symptom"]
                print(f"   {name:4s} symptom hit@1={s['hit@1']:.3f} MRR={s['MRR']:.4f} | "
                      f"overall MRR={r['overall']['MRR']:.4f} | groups "
                      f"{r['system_group_complete']}/{r['system_group_n']} | "
                      f"oos {r['oos_declined']}/{r['oos_n']} | "
                      f"in-scope {r['in_scope_passed']}/{r['in_scope_n']}"
                      + (f" | FALSE DECLINES {s['false_declines']} {s['false_decline_ids']}"
                         if s["false_declines"] else ""))
            print(f"   guardrails {gr['passed']}/{gr['n']}"
                  + (f"  FAILING: {gr['failing']}" if gr["failing"] else ""))
        path = f"{OUT_DIR}/dev_test_results.json"
    else:
        out = {"label": "POST-HOC (development) — the independent set was spent in "
                        "Phase 10.6 and these refinements were written after reading "
                        "its error analysis. Optimistic.",
               "prior_weight": PRIOR_W, "configs": {}}
        for key, cfg, desc in CONFIGS:
            print(f"\n[{key}] {desc}   (POST-HOC)")
            r = run_independent(cfg)
            out["configs"][key] = {"description": desc, "cfg": cfg, **r}
            s, n = r["symptom"], r["no_dtc"]
            print(f"   symptom  hit@1={s['hit@1']:.3f} hit@3={s['hit@3']:.3f} "
                  f"hit@5={s['hit@5']:.3f} MRR={s['MRR']:.4f}")
            print(f"   no_dtc   declined {n['declined']}/{n['n']} = {n['decline_rate']:.3f}")
            print(f"   FALSE DECLINES on symptom rows: {s['false_declines']} "
                  f"{s['false_decline_ids']}")
        path = f"{OUT_DIR}/independent_post_hoc.json"

    json.dump(out, open(path, "w"), indent=1, default=str)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
