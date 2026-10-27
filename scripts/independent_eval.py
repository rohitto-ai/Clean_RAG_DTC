"""
Phase 10.6 step 3 — ONE-SHOT evaluation on the independent symptom set.

    PYTHONPATH=src .venv/bin/python scripts/independent_eval.py

Runs every pre-registered configuration exactly once and REFUSES to run again if
its results file exists. The protocol — configurations, metrics, subsets,
bootstrap settings and the adoption rule — is fixed in
data/experiments/10_6/preregistration.json, which was committed and pushed before
this file was written.

The system is given q["query"] and nothing else: never lamp_reported, notes,
confidence or expected.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import Counter

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

SUBSETS = {
    "ALL": lambda r: True,
    "HIGH": lambda r: r["confidence"] == "high",
    "HIGH+MEDIUM": lambda r: r["confidence"] in ("high", "medium"),
}

PREREG = "data/experiments/10_6/preregistration.json"
OUT = "data/experiments/10_6/results.json"
K = 5
RESAMPLES = 10_000
SEED = 1006


# ------------------------------------------------------------------ scoring
def serve(R, A, query, gate, rerank=None):
    """
    One query through the production path, minus the LLM phrasing.

    Mirrors answer.answer(): the gate applies on the hybrid route only; the
    exact-code and system_group routes answer deterministically. Returns the
    codes the user would see, the route, and the gate decision.
    """
    out = R.retrieve(query, k=max(K, 20 if rerank else K))
    route = out["mode"]
    results = out["results"]
    gate_passed, gate_signals = None, None

    if route == "hybrid":
        gate_passed, gate_signals = A.is_relevant(R, query, gate=gate)
        if not gate_passed:
            return {"route": route, "codes": [], "declined": True,
                    "gate_passed": False, "gate_reasons": gate_signals.get("refusal_reasons"),
                    "reranked": False}

    if rerank is not None and route == "hybrid" and results:
        results = rerank(query, results)

    codes, seen = [], set()
    for item in results:
        c = item["record"]["code_full"]
        if c not in seen:
            seen.add(c)
            codes.append(c)
        if len(codes) >= K:
            break
    return {"route": route, "codes": codes, "declined": not codes,
            "gate_passed": gate_passed,
            "gate_reasons": (gate_signals or {}).get("refusal_reasons"),
            "reranked": rerank is not None and route == "hybrid"}


def make_reranker(cfg):
    """CPU cross-encoder over the top-20, scoring (query, the record's dense text)."""
    from sentence_transformers import CrossEncoder
    from build_index import embedding_text
    model = CrossEncoder(cfg["model"], device=cfg["device"], max_length=512)
    top_k = cfg["top_k"]

    def rerank(query, results):
        pool = results[:top_k]
        pairs = [(query, embedding_text(i["record"])) for i in pool]
        scores = model.predict(pairs, show_progress_bar=False)
        order = sorted(range(len(pool)),
                       key=lambda i: (-float(scores[i]), i, pool[i]["record"]["code_full"]))
        return [pool[i] for i in order] + results[top_k:]
    return rerank


def score_rows(rows):
    """Symptom metrics over scored rows. A declined row scores zero, by design."""
    n = len(rows)
    if not n:
        return {}
    ranks = [r["rank"] for r in rows]
    hit = lambda k: sum(1 for x in ranks if x and x <= k) / n
    return {"n": n, "hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5),
            "MRR": sum((1.0 / x) if x else 0.0 for x in ranks) / n,
            "gate_pass_rate": sum(1 for r in rows if r["gate_passed"] is not False) / n,
            "declined": sum(1 for r in rows if r["declined"])}


def score_no_dtc(rows):
    n = len(rows)
    if not n:
        return {}
    answered = [r for r in rows if not r["declined"]]
    return {"n": n, "decline_rate": (n - len(answered)) / n,
            "declined": n - len(answered), "answered": len(answered),
            "codes_when_answered": {r["id"]: r["codes"][:3] for r in answered},
            "routes": dict(Counter(r["route"] for r in rows))}


# --------------------------------------------------------------- bootstrap
def boot_ci(values, stat, resamples=RESAMPLES, seed=SEED):
    """Percentile 95% CI of `stat` over a bootstrap of the row list."""
    rng = random.Random(seed)
    n = len(values)
    if n == 0:
        return None
    point = stat(values)
    draws = []
    for _ in range(resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        draws.append(stat(sample))
    draws.sort()
    lo = draws[int(0.025 * (resamples - 1))]
    hi = draws[int(0.975 * (resamples - 1))]
    return {"point": point, "lo": lo, "hi": hi}


def paired_boot(a_ranks, b_ranks, resamples=RESAMPLES, seed=SEED):
    """
    Paired bootstrap of the symptom-MRR difference (a - b). The SAME resampled row
    indices are applied to both configurations, which is what makes it paired.
    """
    rng = random.Random(seed)
    n = len(a_ranks)
    rr = lambda x: (1.0 / x) if x else 0.0
    point = (sum(rr(x) for x in a_ranks) - sum(rr(x) for x in b_ranks)) / n
    draws = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        da = sum(rr(a_ranks[i]) for i in idx) / n
        db = sum(rr(b_ranks[i]) for i in idx) / n
        draws.append(da - db)
    draws.sort()
    lo = draws[int(0.025 * (resamples - 1))]
    hi = draws[int(0.975 * (resamples - 1))]
    return {"diff": point, "lo": lo, "hi": hi,
            "excludes_zero": bool(lo > 0 or hi < 0)}


def main():
    if os.path.exists(OUT):
        print(f"REFUSING TO RUN: {OUT} already exists.")
        print("This evaluation is ONE SHOT; re-running it would make the independent")
        print("set as spent as the TEST split. Delete it only if you intend to void")
        print("the result and say so in the report.")
        return 1

    prereg = json.load(open(PREREG))
    print(f"pre-registration {prereg['registered_utc']} "
          f"(commit {prereg['git_commit_at_registration'][:8]})")

    gold = json.load(open("data/gold_independent.json"))
    rows_all = gold["queries"]
    records = [json.loads(l) for l in open("data/dtc_records.jsonl")]

    from cli import quiet_stderr
    with quiet_stderr():
        import answer as A
        from gate import Gate
        from lexicon import Lexicon
        from retrieve import Retriever

    results = {}
    for cfg in prereg["configurations"]:
        key = cfg["key"]
        if cfg.get("rerank") and not prereg["rerank_config_e"]["will_run"]:
            results[key] = {"config": cfg, "status": "NOT RUN",
                            "reason": prereg["rerank_config_e"]["reason"]}
            print(f"\n[{key}] NOT RUN — {prereg['rerank_config_e']['reason']}")
            continue

        print(f"\n[{key}] {cfg['name']}")
        t0 = time.perf_counter()
        with quiet_stderr():
            lex = None
            if cfg["lexicon"] == "auto":
                lex = "auto"
            elif cfg["lexicon"]:
                lex = Lexicon(cfg["lexicon"])
            R = Retriever(index_dir=cfg["index_dir"], lexicon=lex, expand=cfg["expand"])
            gate = None if cfg["gate"] == "legacy" else (
                "default" if cfg["gate"] == "default" else Gate(cfg["gate"]))
            rerank = make_reranker(cfg["rerank"]) if cfg.get("rerank") else None

            scored = []
            for q in rows_all:
                served = serve(R, A, q["query"], gate, rerank)   # q["query"] ONLY
                exp = set(q["expected"])
                rank = next((i for i, c in enumerate(served["codes"], 1) if c in exp), None)
                scored.append({"id": q["id"], "mode": q["mode"],
                               "confidence": q["confidence"], "rank": rank, **served})
        secs = time.perf_counter() - t0

        sym = [r for r in scored if r["mode"] == "symptom"]
        nod = [r for r in scored if r["mode"] == "no_dtc"]
        subsets = SUBSETS
        block = {"config": cfg, "status": "RUN", "seconds": round(secs, 1), "rows": scored,
                 "symptom": {}, "no_dtc": {}}
        for name, keep in subsets.items():
            s = [r for r in sym if keep(r)]
            d = [r for r in nod if keep(r)]
            block["symptom"][name] = score_rows(s)
            block["no_dtc"][name] = score_no_dtc(d)
            if s:
                ranks = [r["rank"] for r in s]
                block["symptom"][name]["MRR_ci"] = boot_ci(
                    ranks, lambda v: sum((1.0 / x) if x else 0.0 for x in v) / len(v))
                block["symptom"][name]["hit@1_ci"] = boot_ci(
                    ranks, lambda v: sum(1 for x in v if x == 1) / len(v))
            if d:
                flags = [1 if r["declined"] else 0 for r in d]
                block["no_dtc"][name]["decline_rate_ci"] = boot_ci(
                    flags, lambda v: sum(v) / len(v))
        results[key] = block
        m = block["symptom"]["ALL"]
        nd = block["no_dtc"]["ALL"]
        print(f"     symptom  n={m['n']}  hit@1={m['hit@1']:.3f}  hit@3={m['hit@3']:.3f}  "
              f"hit@5={m['hit@5']:.3f}  MRR={m['MRR']:.4f}  gate pass={m['gate_pass_rate']:.3f}")
        print(f"     no_dtc   n={nd['n']}  decline={nd['decline_rate']:.3f} "
              f"({nd['declined']}/{nd['n']})  routes={nd['routes']}")
        print(f"     {secs:.1f}s")

    # ------------------------------------------------- paired tests vs (b)
    print("\n== paired bootstrap of symptom MRR vs (b), 10,000 resamples, seed 1006 ==")
    base = results.get("b")
    paired = {}
    for key, block in results.items():
        if key == "b" or block.get("status") != "RUN":
            continue
        for subset in ("ALL", "HIGH", "HIGH+MEDIUM"):
            keep = SUBSETS[subset]
            a_by = {r["id"]: r["rank"] for r in block["rows"]
                    if r["mode"] == "symptom" and keep(r)}
            b_by = {r["id"]: r["rank"] for r in base["rows"]
                    if r["mode"] == "symptom" and keep(r)}
            ids = sorted(set(a_by) & set(b_by))
            paired.setdefault(key, {})[subset] = paired_boot(
                [a_by[i] for i in ids], [b_by[i] for i in ids])
        p = paired[key]["ALL"]
        print(f"  {key} vs b  ALL: diff={p['diff']:+.4f}  95% CI [{p['lo']:+.4f}, {p['hi']:+.4f}]"
              f"  excludes 0: {p['excludes_zero']}")

    # ------------------------------------------- the pre-registered verdict
    verdicts = {}
    b_decline = base["no_dtc"]["ALL"]["decline_rate"]
    for key, block in results.items():
        if key == "b" or block.get("status") != "RUN":
            continue
        gain = paired[key]["ALL"]
        decline = block["no_dtc"]["ALL"]["decline_rate"]
        cond1 = gain["lo"] > 0                      # gain CI excludes 0 ON THE UPSIDE
        cond2 = decline >= b_decline
        verdicts[key] = {
            "mrr_gain": gain["diff"], "ci": [gain["lo"], gain["hi"]],
            "ci_excludes_zero": gain["excludes_zero"],
            "ci_shows_gain": cond1,
            "decline_rate": decline, "b_decline_rate": b_decline,
            "decline_not_lower": cond2,
            "replaces_b": bool(cond1 and cond2),
        }
        print(f"  verdict {key}: replaces (b)? {verdicts[key]['replaces_b']}  "
              f"(CI shows gain: {cond1}, decline not lower: {cond2})")

    json.dump({"preregistration": PREREG,
               "preregistered_utc": prereg["registered_utc"],
               "gold_sha256": prereg["gold"]["sha256"],
               "results": results, "paired_vs_b": paired, "verdicts": verdicts,
               "adoption_rule": prereg["adoption_rule"],
               "ran_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
              open(OUT, "w"), indent=1, default=str)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
