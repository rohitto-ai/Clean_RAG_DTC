"""
Phase 11.2 — measure A-narrow, then the one-shot check on the colleague set.

    PYTHONPATH=src .venv/bin/python scripts/eval_11_2.py --stage dev
    PYTHONPATH=src .venv/bin/python scripts/eval_11_2.py --stage r2

  dev  DEV (gold v2.2) + the spent TEST + the 14 guardrails + the Round-1
       independent set POST-HOC. This is the no-regression gate and the evidence
       that the narrowing does what Phase 11.1 predicted. Run before freezing.
  r2   data/gold_r2_colleague.json, ONE SHOT. Refuses to run a second time.
       Requires the freeze and the pre-registration to exist first.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

OUT_DIR = "data/experiments/11_2"
FREEZE = f"{OUT_DIR}/freeze.json"
PREREG = f"{OUT_DIR}/preregistration.json"
R2_OUT = f"{OUT_DIR}/r2_results.json"
R2_GOLD = "data/gold_r2_colleague.json"
K = 5
RESAMPLES = 10_000
SEED = 1102


def serve(R, A, query, narrow):
    """
    Production path, optionally with A-narrow in front of it.

    'decline'  -> no codes at all, plus an inspection area
    'advise'   -> the ranked codes ARE returned, with an inspection hint
    'retrieve' -> untouched production behaviour
    """
    advisory = None
    if narrow:
        import no_dtc_narrow as NN
        v = NN.detect(query)
        if v["action"] == "decline":
            return {"codes": [], "declined": True, "decline_by": "a_narrow",
                    "areas": v["areas"], "advisory_shown": True,
                    "reasons": v["reasons"], "route": "no_dtc_match"}
        if v["action"] == "advise":
            advisory = {"areas": v["areas"], "hint": v["hint"]}
    out = R.retrieve(query, k=K)
    if out["mode"] == "hybrid":
        ok, sig = A.is_relevant(R, query)
        if not ok:
            return {"codes": [], "declined": True, "decline_by": "gate",
                    "advisory_shown": bool(advisory), "areas": (advisory or {}).get("areas"),
                    "reasons": sig.get("refusal_reasons"), "route": out["mode"]}
    codes, seen = [], set()
    for item in out["results"]:
        c = item["record"]["code_full"]
        if c not in seen:
            seen.add(c)
            codes.append(c)
    limit = len(codes) if out["mode"] == "system_group" else K
    return {"codes": codes[:limit], "declined": not codes, "decline_by": None,
            "advisory_shown": bool(advisory), "areas": (advisory or {}).get("areas"),
            "route": out["mode"]}


def metrics(rows):
    n = len(rows)
    if not n:
        return {}
    ranks = [r["rank"] for r in rows]
    hit = lambda k: sum(1 for x in ranks if x and x <= k) / n
    return {"n": n, "hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5),
            "MRR": sum((1.0 / x) if x else 0.0 for x in ranks) / n,
            "false_declines": sum(1 for r in rows if r["declined"]),
            "false_decline_ids": [r["id"] for r in rows if r["declined"]]}


def boot_ci(values, stat, resamples=RESAMPLES, seed=SEED):
    rng = random.Random(seed)
    n = len(values)
    if not n:
        return None
    draws = []
    for _ in range(resamples):
        draws.append(stat([values[rng.randrange(n)] for _ in range(n)]))
    draws.sort()
    return {"point": stat(values), "lo": draws[int(0.025 * (resamples - 1))],
            "hi": draws[int(0.975 * (resamples - 1))]}


def paired_boot(a_ranks, b_ranks, resamples=RESAMPLES, seed=SEED):
    """Paired bootstrap of MRR(b_cfg) - MRR(a_cfg); same resampled indices both sides."""
    rng = random.Random(seed)
    n = len(a_ranks)
    rr = lambda x: (1.0 / x) if x else 0.0
    point = (sum(rr(x) for x in b_ranks) - sum(rr(x) for x in a_ranks)) / n
    draws = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        draws.append((sum(rr(b_ranks[i]) for i in idx)
                      - sum(rr(a_ranks[i]) for i in idx)) / n)
    draws.sort()
    lo, hi = draws[int(0.025 * (resamples - 1))], draws[int(0.975 * (resamples - 1))]
    return {"diff": point, "lo": lo, "hi": hi, "excludes_zero": bool(lo > 0 or hi < 0)}


def build():
    from cli import quiet_stderr
    with quiet_stderr():
        import answer as A
        from retrieve import Retriever
        R = Retriever()
    return R, A


# ------------------------------------------------------------------ stage dev
def run_gold_v2(split, narrow, R, A):
    gold = json.load(open("data/gold_v2.json"))
    qs = [q for q in gold["queries"] if q["split"] == split]
    ranked, groups, oos_declined, in_scope_passed = [], [], 0, 0
    for q in qs:
        s = serve(R, A, q["query"], narrow)
        exp = set(q["expected"])
        rank = next((i for i, c in enumerate(s["codes"], 1) if c in exp), None)
        if q["mode"] in ("exact_code", "near_duplicate", "symptom"):
            ranked.append({"id": q["id"], "mode": q["mode"], "rank": rank,
                           "declined": s["declined"]})
        elif q["mode"] == "system_group":
            groups.append(set(s["codes"]) == exp)
        if q["mode"] == "out_of_scope":
            oos_declined += s["declined"]
        else:
            in_scope_passed += not s["declined"]
    return {"symptom": metrics([r for r in ranked if r["mode"] == "symptom"]),
            "overall": metrics(ranked),
            "groups": f"{sum(groups)}/{len(groups)}",
            "oos": f"{oos_declined}/{sum(1 for q in qs if q['mode'] == 'out_of_scope')}",
            "in_scope": f"{in_scope_passed}/{sum(1 for q in qs if q['mode'] != 'out_of_scope')}"}


def run_round1(narrow, R, A):
    qs = json.load(open("data/gold_independent.json"))["queries"]
    sym, nod = [], []
    for q in qs:
        s = serve(R, A, q["query"], narrow)
        rank = next((i for i, c in enumerate(s["codes"], 1) if c in set(q["expected"])), None)
        row = {"id": q["id"], "rank": rank, "declined": s["declined"],
               "advisory_shown": s.get("advisory_shown", False)}
        (sym if q["mode"] == "symptom" else nod).append(row)
    declined = sum(1 for r in nod if r["declined"])
    return {"symptom": metrics(sym),
            "no_dtc": {"n": len(nod), "declined": declined,
                       "decline_rate": declined / len(nod),
                       "advisory_without_decline": sum(
                           1 for r in nod if not r["declined"] and r["advisory_shown"])}}


def stage_dev():
    import bench_8_2 as B
    from cli import quiet_stderr
    R, A = build()
    with quiet_stderr():
        g = B.guardrails(R)
    out = {"guardrails": f"{sum(x['pass'] for x in g)}/{len(g)}", "configs": {}}
    for key, narrow in (("a_v3_production", False), ("b_a_narrow", True)):
        print(f"\n[{key}]")
        dev = run_gold_v2("DEV", narrow, R, A)
        test = run_gold_v2("TEST", narrow, R, A)
        r1 = run_round1(narrow, R, A)
        out["configs"][key] = {"DEV": dev, "TEST_post_hoc": test, "ROUND1_post_hoc": r1}
        for name, r in (("DEV", dev), ("TEST", test)):
            print(f"   {name:4s} symptom hit@1={r['symptom']['hit@1']:.3f} "
                  f"MRR={r['symptom']['MRR']:.4f} | groups {r['groups']} | oos {r['oos']} | "
                  f"in-scope {r['in_scope']}"
                  + (f" | FALSE DECLINES {r['symptom']['false_decline_ids']}"
                     if r["symptom"]["false_declines"] else ""))
        print(f"   ROUND1 (post-hoc) symptom MRR={r1['symptom']['MRR']:.4f} "
              f"false declines={r1['symptom']['false_declines']} "
              f"{r1['symptom']['false_decline_ids']} | no_dtc declined "
              f"{r1['no_dtc']['declined']}/{r1['no_dtc']['n']}"
              f" | advisory-only on no_dtc {r1['no_dtc']['advisory_without_decline']}")
    print(f"\n   guardrails {out['guardrails']}")
    json.dump(out, open(f"{OUT_DIR}/dev_test_results.json", "w"), indent=1, default=str)
    print(f"\nwrote {OUT_DIR}/dev_test_results.json")


# ------------------------------------------------------------------- stage r2
def stage_r2():
    if os.path.exists(R2_OUT):
        print(f"REFUSING TO RUN: {R2_OUT} already exists.")
        print("The colleague set is ONE SHOT. Delete the file only if you intend to void")
        print("the result and say so in the report.")
        return 1
    for need in (FREEZE, PREREG):
        if not os.path.exists(need):
            print(f"REFUSING TO RUN: {need} is missing. A-narrow must be frozen and the")
            print("protocol pre-registered (and pushed) before the colleague set is touched.")
            return 1
    import hashlib
    frozen = json.load(open(FREEZE))
    drift = [p for p, h in frozen["sha256"].items()
             if hashlib.sha256(open(p, "rb").read()).hexdigest() != h]
    if drift:
        print("REFUSING TO RUN: the A-narrow freeze no longer holds for:", drift)
        return 1

    gold = json.load(open(R2_GOLD))
    qs = gold["queries"]
    R, A = build()
    results = {}
    for key, narrow in (("a_v3_production", False), ("b_a_narrow", True)):
        rows = []
        for q in qs:
            s = serve(R, A, q["query"], narrow)          # q["query"] ONLY
            rank = next((i for i, c in enumerate(s["codes"], 1)
                         if c in set(q["expected"])), None)
            rows.append({"id": q["id"], "mode": q["mode"], "rank": rank,
                         "declined": s["declined"], "decline_by": s["decline_by"],
                         "advisory_shown": s.get("advisory_shown", False),
                         "areas": s.get("areas"), "codes": s["codes"][:5]})
        results[key] = rows

    def block(rows, keep):
        sym = [r for r in rows if r["mode"] == "symptom" and keep(r["id"])]
        nod = [r for r in rows if r["mode"] == "no_dtc" and keep(r["id"])]
        dec = sum(1 for r in nod if r["declined"])
        m = metrics(sym)
        m["MRR_ci"] = boot_ci([r["rank"] for r in sym],
                              lambda v: sum((1.0 / x) if x else 0.0 for x in v) / len(v))
        return {"symptom": m,
                "no_dtc": {"n": len(nod), "declined": dec,
                           "decline_rate": dec / len(nod) if nod else 0.0,
                           "decline_rate_ci": boot_ci(
                               [1 if r["declined"] else 0 for r in nod],
                               lambda v: sum(v) / len(v)) if nod else None,
                           "answered": {r["id"]: {"codes": r["codes"][:3],
                                                  "advisory_shown": r["advisory_shown"],
                                                  "areas": r["areas"]}
                                        for r in nod if not r["declined"]}}}

    subsets = {"ALL": lambda i: True,
               "EXCL_R16_R18": lambda i: i not in ("R16", "R18")}
    out = {"gold_sha256": hashlib.sha256(open(R2_GOLD, "rb").read()).hexdigest(),
           "preregistration": PREREG, "freeze": FREEZE,
           "subsets": {}, "rows": results,
           "inconclusive": {r["id"]: {"declined": r["declined"], "codes": r["codes"][:3],
                                      "advisory_shown": r["advisory_shown"]}
                            for r in results["b_a_narrow"] if r["mode"] == "inconclusive"},
           "inconclusive_production": {r["id"]: {"declined": r["declined"],
                                                 "codes": r["codes"][:3]}
                                       for r in results["a_v3_production"]
                                       if r["mode"] == "inconclusive"}}
    for sub, keep in subsets.items():
        out["subsets"][sub] = {k: block(v, keep) for k, v in results.items()}
        a_sym = [r["rank"] for r in results["a_v3_production"]
                 if r["mode"] == "symptom" and keep(r["id"])]
        b_sym = [r["rank"] for r in results["b_a_narrow"]
                 if r["mode"] == "symptom" and keep(r["id"])]
        out["subsets"][sub]["paired_b_minus_a"] = paired_boot(a_sym, b_sym)

    # word overlap, information only
    from gold_overlap import load_descriptions, overlap
    desc = load_descriptions()
    sym_q = [q for q in qs if q["mode"] == "symptom"]
    ov = [overlap(q["query"], q["expected"], desc)[0] for q in sym_q]
    out["word_overlap_info_only"] = {"n": len(ov), "mean": sum(ov) / len(ov),
                                     "max": max(ov), "zero": sum(1 for x in ov if x == 0)}

    json.dump(out, open(R2_OUT, "w"), indent=1, default=str)
    for sub in subsets:
        print(f"\n===== {sub} =====")
        for key in results:
            b = out["subsets"][sub][key]
            s, n = b["symptom"], b["no_dtc"]
            print(f"  {key:18s} symptom n={s['n']} hit@1={s['hit@1']:.3f} "
                  f"hit@3={s['hit@3']:.3f} hit@5={s['hit@5']:.3f} MRR={s['MRR']:.4f} "
                  f"[{s['MRR_ci']['lo']:.4f},{s['MRR_ci']['hi']:.4f}] "
                  f"false_declines={s['false_declines']}{s['false_decline_ids']}")
            print(f"  {'':18s} no_dtc  n={n['n']} declined={n['declined']} "
                  f"rate={n['decline_rate']:.3f}")
        p = out["subsets"][sub]["paired_b_minus_a"]
        print(f"  paired MRR (b - a): {p['diff']:+.4f} CI [{p['lo']:+.4f}, {p['hi']:+.4f}] "
              f"excludes 0: {p['excludes_zero']}")
    print(f"\ninconclusive row: {out['inconclusive']}")
    print(f"word overlap (info only): {out['word_overlap_info_only']}")
    print(f"\nwrote {R2_OUT}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["dev", "r2"], required=True)
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    return stage_dev() if a.stage == "dev" else stage_r2()


if __name__ == "__main__":
    sys.exit(main() or 0)
