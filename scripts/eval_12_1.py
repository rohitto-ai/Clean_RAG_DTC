"""
Phase 12.1 — evaluate the symptom-expansion third ranker.

    PYTHONPATH=src .venv/bin/python scripts/eval_12_1.py --stage dev
    PYTHONPATH=src .venv/bin/python scripts/eval_12_1.py --stage posthoc

  dev      DEV (gold v2.2) + the spent TEST + the 14 near-duplicate guardrails.
           The no-regression gate. Run and pass this BEFORE the freeze.
  posthoc  the spent independent set and the spent R2 colleague set, plus
           latency. POST-HOC and optimistic by construction - both sets were
           used once already. Run only AFTER the freeze.

Configurations:
  base     production C4b + gate v2 (dense + BM25)
  sympexp  index_exp/minilm_sympexp with the third ranker (dense + BM25 +
           symptom-dense), same gate
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

OUT_DIR = "data/experiments/12_1"
SYMP_INDEX = "index_exp/minilm_sympexp"
SYMP_INDEX_FILTERED = "index_exp/minilm_sympexp_filtered"
VARIANTS = {"base": None, "sympexp": SYMP_INDEX, "sympexp_filtered": SYMP_INDEX_FILTERED}
K = 5


def build(kind):
    from cli import quiet_stderr
    with quiet_stderr():
        import answer as A
        if kind == "base":
            from retrieve import Retriever
            R = Retriever()
        else:
            from symptom_retriever import SymptomRetriever
            R = SymptomRetriever(index_dir=VARIANTS[kind])
    return R, A


def serve(R, A, query):
    out = R.retrieve(query, k=K)
    if out["mode"] == "hybrid":
        ok, sig = A.is_relevant(R, query)
        if not ok:
            return {"codes": [], "declined": True, "route": out["mode"],
                    "reasons": sig.get("refusal_reasons")}
    codes, seen = [], set()
    for item in out["results"]:
        c = item["record"]["code_full"]
        if c not in seen:
            seen.add(c)
            codes.append(c)
    limit = len(codes) if out["mode"] == "system_group" else K
    return {"codes": codes[:limit], "declined": not codes, "route": out["mode"]}


def metrics(rows):
    n = len(rows)
    if not n:
        return {}
    ranks = [r["rank"] for r in rows]
    hit = lambda k: sum(1 for x in ranks if x and x <= k) / n
    return {"n": n, "hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5),
            "MRR": sum((1.0 / x) if x else 0.0 for x in ranks) / n,
            "declines": sum(1 for r in rows if r["declined"]),
            "decline_ids": [r["id"] for r in rows if r["declined"]]}


def run_gold_v2(split, R, A):
    qs = [q for q in json.load(open("data/gold_v2.json"))["queries"] if q["split"] == split]
    ranked, groups, oos, ins = [], [], 0, 0
    for q in qs:
        s = serve(R, A, q["query"])
        exp = set(q["expected"])
        rank = next((i for i, c in enumerate(s["codes"], 1) if c in exp), None)
        if q["mode"] in ("exact_code", "near_duplicate", "symptom"):
            ranked.append({"id": q["id"], "mode": q["mode"], "rank": rank,
                           "declined": s["declined"]})
        elif q["mode"] == "system_group":
            groups.append(set(s["codes"]) == exp)
        if q["mode"] == "out_of_scope":
            oos += s["declined"]
        else:
            ins += not s["declined"]
    return {"symptom": metrics([r for r in ranked if r["mode"] == "symptom"]),
            "near_duplicate": metrics([r for r in ranked if r["mode"] == "near_duplicate"]),
            "exact_code": metrics([r for r in ranked if r["mode"] == "exact_code"]),
            "overall": metrics(ranked),
            "groups": f"{sum(groups)}/{len(groups)}",
            "oos": f"{oos}/{sum(1 for q in qs if q['mode'] == 'out_of_scope')}",
            "in_scope": f"{ins}/{sum(1 for q in qs if q['mode'] != 'out_of_scope')}"}


def run_set(path, R, A):
    qs = json.load(open(path))["queries"]
    sym, nod, lat = [], [], []
    for q in qs:
        t = time.perf_counter()
        s = serve(R, A, q["query"])
        lat.append((time.perf_counter() - t) * 1000)
        rank = next((i for i, c in enumerate(s["codes"], 1) if c in set(q["expected"])), None)
        row = {"id": q["id"], "rank": rank, "declined": s["declined"], "codes": s["codes"][:5]}
        if q["mode"] == "symptom":
            sym.append(row)
        elif q["mode"] == "no_dtc":
            nod.append(row)
    lat.sort()
    dec = sum(1 for r in nod if r["declined"])
    return {"symptom": metrics(sym),
            "no_dtc": {"n": len(nod), "declined": dec,
                       "decline_rate": dec / len(nod) if nod else 0.0},
            "latency_ms": {"p50": round(statistics.median(lat), 1),
                           "p95": round(lat[int(0.95 * (len(lat) - 1))], 1)},
            "rows": {"symptom": sym, "no_dtc": nod}}


def stage_dev():
    import bench_8_2 as B
    from cli import quiet_stderr
    out = {"configs": {}}
    for kind in [k for k in VARIANTS if k == "base" or os.path.isdir(VARIANTS[k])]:
        print(f"\n[{kind}]")
        R, A = build(kind)
        dev, test = run_gold_v2("DEV", R, A), run_gold_v2("TEST", R, A)
        with quiet_stderr():
            g = B.guardrails(R)
        gr = f"{sum(x['pass'] for x in g)}/{len(g)}"
        out["configs"][kind] = {"DEV": dev, "TEST_post_hoc": test, "guardrails": gr,
                                "guardrails_failing": [x.get("query") for x in g
                                                       if not x["pass"]]}
        for name, r in (("DEV", dev), ("TEST", test)):
            print(f"   {name:4s} symptom hit@1={r['symptom']['hit@1']:.3f} "
                  f"MRR={r['symptom']['MRR']:.4f} | near-dup MRR={r['near_duplicate']['MRR']:.4f}"
                  f" | exact MRR={r['exact_code']['MRR']:.4f} | overall MRR={r['overall']['MRR']:.4f}"
                  f" | groups {r['groups']} | oos {r['oos']} | in-scope {r['in_scope']}")
        print(f"   guardrails {gr}" + (f"  FAILING {out['configs'][kind]['guardrails_failing']}"
                                       if out["configs"][kind]["guardrails_failing"] else ""))
    json.dump(out, open(f"{OUT_DIR}/dev_test_results.json", "w"), indent=1, default=str)
    print(f"\nwrote {OUT_DIR}/dev_test_results.json")


def stage_posthoc():
    freeze = f"{OUT_DIR}/freeze.json"
    if not os.path.exists(freeze):
        print(f"REFUSING: {freeze} missing. Freeze before measuring on spent sets.")
        return 1
    import hashlib
    frozen = json.load(open(freeze))
    drift = [p for p, h in frozen["sha256"].items()
             if hashlib.sha256(open(p, "rb").read()).hexdigest() != h]
    if drift:
        print("REFUSING: the freeze no longer holds for:", drift)
        return 1

    out = {"label": "POST-HOC (development) - both sets were spent before this run. "
                    "Optimistic; not an independent measurement.", "configs": {}}
    # Neither variant passed the DEV gate, so there is no "chosen" one: measure
    # both, clearly labelled, rather than silently promoting the less-bad one.
    chosen = json.load(open(freeze)).get("chosen_variant")
    kinds = ("base", chosen) if chosen else ("base", "sympexp", "sympexp_filtered")
    for kind in kinds:
        print(f"\n[{kind}]   (POST-HOC)")
        R, A = build(kind)
        ind = run_set("data/gold_independent.json", R, A)
        r2 = run_set("data/gold_r2_colleague.json", R, A)
        out["configs"][kind] = {"ROUND1_independent": ind, "R2_colleague": r2}
        for name, r in (("ROUND1", ind), ("R2", r2)):
            s = r["symptom"]
            print(f"   {name:7s} symptom n={s['n']} hit@1={s['hit@1']:.3f} "
                  f"hit@3={s['hit@3']:.3f} hit@5={s['hit@5']:.3f} MRR={s['MRR']:.4f} | "
                  f"no_dtc declined {r['no_dtc']['declined']}/{r['no_dtc']['n']} | "
                  f"latency p50 {r['latency_ms']['p50']} ms p95 {r['latency_ms']['p95']} ms")
    json.dump(out, open(f"{OUT_DIR}/posthoc_results.json", "w"), indent=1, default=str)
    print(f"\nwrote {OUT_DIR}/posthoc_results.json")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["dev", "posthoc"], required=True)
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    return stage_dev() if a.stage == "dev" else stage_posthoc()


if __name__ == "__main__":
    sys.exit(main() or 0)
