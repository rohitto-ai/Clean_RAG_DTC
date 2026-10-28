"""
Phase 12.3 — the Round-3 one-shot check, exactly as pre-registered.

    PYTHONPATH=src .venv/bin/python scripts/eval_12_3.py --dry-run
    PYTHONPATH=src .venv/bin/python scripts/eval_12_3.py --run

The protocol is fixed in `docs/report/phase12_3_prereg.md`, committed before this
file existed. Nothing here may be changed after `data/eval/gold_r3.json` arrives;
this script's job is to make that protocol executable and to refuse anything
outside it.

  --dry-run  score `data/demo/gold_r3_dummy.json` (3 synthetic rows, gitignored).
             Touches no gold data, writes nothing to data/experiments/, and may
             be run as often as needed.
  --run      the single scoring run on `data/eval/gold_r3.json`. Writes
             `data/experiments/12_3/r3_results.json` and REFUSES if that file
             already exists.

ELIGIBILITY (addendum section 2), checked BEFORE any query is scored:
  (i)   mean query overlap with the record vocabulary <= 0.15, using the Phase 8
        function and ceiling imported unchanged from src/gold_overlap.py
  (ii)  rows at MiniLM cosine >= 0.85 to a Round-1 or R2 query are EXCLUDED and
        reported; exclusions are applied first, so (i) is judged on the rows that
        will actually be scored; no symptom rows left is an abort
  (iii) provenance must name the author AND state that no AI tool was used

CONFIGURATIONS (prereg section 1), and no others:
  a  production      Retriever() on index/ + answer.default_gate()
  b  12.2 v2_half    WeightedSymptomRetriever(index_exp/minilm_sympexp_v2, 0.5)
  c  prod + A-narrow config (a) with no_dtc_narrow in front - no_dtc rows ONLY

GUARDS, all of which abort the run rather than warn:
  * every sha256 in data/experiments/12_2/freeze.json must still match
  * config (a) must have subsystem_prior == 0.0 (the 11.1 knob, off in production)
  * the DEV determinism hash must be ffff9bc707d8754d, the value recorded for the
    tag v3-final-eval, so (a) is demonstrably the tagged system's behaviour
  * the gold file's schema must match gold_r2_colleague.json exactly

Nothing inside the 11.2, 12.1 or 12.2 freezes is imported-and-edited: A-narrow is
used through `no_dtc_narrow.detect` and (b) through `symptom_retriever_w`, both
unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import statistics
import sys
import time

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

GOLD = "data/eval/gold_r3.json"
DUMMY = "data/demo/gold_r3_dummy.json"
OUT_DIR = "data/experiments/12_3"
RESULTS = f"{OUT_DIR}/r3_results.json"
FREEZE_12_2 = "data/experiments/12_2/freeze.json"
V2_INDEX = "index_exp/minilm_sympexp_v2"
DEV_HASH = "ffff9bc707d8754d"          # recorded for tag v3-final-eval
K = 5
RESAMPLES = 10_000
SEED = 0
SCHEMA_REF = "data/gold_r2_colleague.json"
PRIOR_SETS = ["data/gold_independent.json", "data/gold_r2_colleague.json"]
PARAPHRASE_SIM = 0.85
EMBEDDER = "sentence-transformers/all-MiniLM-L6-v2"
AUTHOR_RE = re.compile(r"\b(written|authored|composed)\s+by\s+[A-Za-z]", re.I)
NO_AI_RE = re.compile(r"\bno\s+(ai|a\.i\.|llm|llms|language model|language models|"
                      r"generative(?:\s+ai)?)\b|\bwithout\s+(ai|llm|generative)\b", re.I)
QUERY_FIELDS = {"id", "query", "mode", "expected", "notes", "split"}
TOP_FIELDS = {"version", "created", "provenance", "queries"}
SCORED_MODES = ("symptom", "no_dtc")


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------
def check_freeze():
    frozen = json.load(open(FREEZE_12_2))
    drift = [p for p, h in frozen["sha256"].items()
             if hashlib.sha256(open(p, "rb").read()).hexdigest() != h]
    if drift:
        raise SystemExit(f"ABORT: the 12.2 freeze no longer holds for: {drift}")
    if frozen.get("chosen_variant") != "v2_half":
        raise SystemExit(f"ABORT: 12.2 chosen_variant is {frozen.get('chosen_variant')!r}, "
                         "not 'v2_half'; config (b) is not what was pre-registered.")
    return {"chosen_variant": frozen["chosen_variant"], "frozen_utc": frozen["frozen_utc"],
            "artefacts_verified": len(frozen["sha256"])}


def check_determinism():
    """
    Config (a) must reproduce the DEV canonical output recorded for v3-final-eval.
    Computed the same way scripts/determinism_proof.py computes it.
    """
    import answer as A
    import evaluate_v2 as EV
    from retrieve import Retriever

    gold = json.load(open("data/gold_v2.json"))
    dev = [q for q in gold["queries"] if q["split"] == "DEV"]
    records = [json.loads(l) for l in open("data/dtc_records.jsonl")]
    R = Retriever(index_dir="index")
    if R.subsystem_prior != 0.0:
        raise SystemExit(f"ABORT: subsystem_prior is {R.subsystem_prior}, not 0.0; "
                         "config (a) is not the production default.")
    res = EV.run(R, dev, records, A, A.default_gate())
    canon = {
        "rows": [{"id": r["id"], "mode": r["mode"], "rank": r["rank"], "got": r["got"]}
                 for r in res["_rows"]],
        "groups": [{"id": g["id"], "complete": g["complete"], "returned": g["returned"]}
                   for g in res["_groups"]],
        "gate": [{"id": h["id"], "passed": h["passed"],
                  "reasons": h["signals"].get("refusal_reasons")} for h in res["_honesty"]],
        "by_mode": res["by_mode"], "overall": res["overall"],
        "system_group": res["system_group"], "honesty": res["honesty"],
    }
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()
    got = hashlib.sha256(blob).hexdigest()[:16]
    if got != DEV_HASH:
        raise SystemExit(f"ABORT: DEV determinism hash is {got}, not {DEV_HASH}. Config (a) "
                         "is not behaving as the tagged system; fix that before scoring R3.")
    return got


def check_schema(path):
    d = json.load(open(path))
    if set(d.keys()) != TOP_FIELDS:
        raise SystemExit(f"ABORT: {path} top-level keys {sorted(d.keys())} != "
                         f"{sorted(TOP_FIELDS)} (schema of {SCHEMA_REF}).")
    if not d["queries"]:
        raise SystemExit(f"ABORT: {path} holds no queries.")
    for q in d["queries"]:
        if set(q.keys()) != QUERY_FIELDS:
            raise SystemExit(f"ABORT: query {q.get('id')!r} fields {sorted(q.keys())} != "
                             f"{sorted(QUERY_FIELDS)} (schema of {SCHEMA_REF}).")
        if not isinstance(q["expected"], list):
            raise SystemExit(f"ABORT: query {q['id']!r} 'expected' is not a list.")
    return d


class EligibilityError(Exception):
    """A pre-registered eligibility failure (addendum section 2)."""


def check_provenance(gold):
    """(iii) The claim must be made, by a named person. No program can verify how a
    sentence was produced; this puts the claim on the record and makes it falsifiable."""
    prov = (gold.get("provenance") or "").strip()
    if not prov:
        raise EligibilityError("provenance is empty; it must name who wrote the queries "
                               "and state that no AI tool was used (addendum 2.iii).")
    named, no_ai = bool(AUTHOR_RE.search(prov)), bool(NO_AI_RE.search(prov))
    if not (named and no_ai):
        missing = []
        if not named:
            missing.append("who wrote the queries ('written by <name>')")
        if not no_ai:
            missing.append("that no AI tool was used ('no AI tool was used')")
        raise EligibilityError("provenance does not state " + " and ".join(missing)
                               + f". Got: {prov[:160]!r}")
    return {"names_author": True, "disclaims_ai": True,
            "checked": "the CLAIM, not the fact - no program can verify how text was written",
            "provenance": prov}


def check_paraphrases(queries):
    """(ii) Exclude rows that merely restate an already-spent Round-1 or R2 query."""
    prior = []
    for path in PRIOR_SETS:
        for q in json.load(open(path))["queries"]:
            prior.append({"set": os.path.basename(path), "id": q["id"], "query": q["query"]})
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDER, device="cpu")
    new_v = model.encode([q["query"] for q in queries], normalize_embeddings=True,
                         convert_to_numpy=True, show_progress_bar=False)
    old_v = model.encode([p["query"] for p in prior], normalize_embeddings=True,
                         convert_to_numpy=True, show_progress_bar=False)
    del model
    sims = new_v @ old_v.T
    excluded, kept = [], []
    for i, q in enumerate(queries):
        j = int(sims[i].argmax())
        best = float(sims[i][j])
        if best >= PARAPHRASE_SIM:
            excluded.append({"id": q["id"], "mode": q["mode"], "cosine": round(best, 4),
                             "nearest_prior_set": prior[j]["set"],
                             "nearest_prior_id": prior[j]["id"]})
        else:
            kept.append(q)
    return kept, {"threshold": PARAPHRASE_SIM, "embedder": EMBEDDER,
                  "prior_queries_compared": len(prior),
                  "excluded_count": len(excluded), "excluded": excluded}


def check_overlap(symptom_queries):
    """(i) The Phase 8 word-overlap ceiling, on the rows that will be scored."""
    from gold_overlap import CEILING, load_descriptions, overlap, symptom_stats
    desc = load_descriptions()
    stats, rows = symptom_stats(symptom_queries, desc)
    worst = sorted(((q["id"], round(sc, 4), sorted(sh)) for q, sc, sh, _ in rows),
                   key=lambda r: -r[1])[:5]
    report = {"ceiling": CEILING, "mean": stats["mean"], "max": stats["max"],
              "zero_overlap": stats["zero_overlap"], "over_ceiling": stats["over_ceiling"],
              "n": stats["n"], "worst_rows": worst,
              "function": "src/gold_overlap.overlap (Phase 8.0), imported unchanged"}
    if stats["mean"] > CEILING:
        raise EligibilityError(
            f"mean symptom query overlap {stats['mean']:.4f} > ceiling {CEILING}: the queries "
            f"reuse the manual's own vocabulary, so the set cannot measure technician language "
            f"(addendum 2.i). Worst rows: {worst}")
    return report


def check_eligibility(gold):
    """All three checks, in the pre-registered order of operations."""
    prov = check_provenance(gold)
    kept, para = check_paraphrases(gold["queries"])
    sym_all = [q for q in gold["queries"] if q["mode"] == "symptom"]
    sym_kept = [q for q in kept if q["mode"] == "symptom"]
    if not sym_kept:
        raise EligibilityError("no symptom rows survive the paraphrase exclusion; there is "
                               "nothing left to measure (addendum 2.ii).")
    ov = check_overlap(sym_kept)
    from gold_overlap import load_descriptions, symptom_stats
    all_stats, _ = symptom_stats(sym_all, load_descriptions())
    ov["mean_before_exclusions"] = all_stats["mean"]
    return kept, {"provenance": prov, "paraphrases": para, "overlap": ov}


# --------------------------------------------------------------------------
# the three configurations
# --------------------------------------------------------------------------
def build(kind):
    from cli import quiet_stderr
    with quiet_stderr():
        import answer as A
        if kind == "b_v2_half":
            from symptom_retriever_w import WeightedSymptomRetriever
            R = WeightedSymptomRetriever(index_dir=V2_INDEX, symptom_weight=0.5)
        else:
            from retrieve import Retriever
            R = Retriever(index_dir="index")
    return R, A


def serve(R, A, query, narrow):
    """
    Production path, with A-narrow in front of it for config (c) only. Mirrors
    scripts/eval_11_2.py (the 11.2 freeze) rather than reimplementing the rule.
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


# --------------------------------------------------------------------------
# metrics, exactly as pre-registered
# --------------------------------------------------------------------------
def rank_of(codes, expected):
    """Lenient, as in Round 1: the first rank holding ANY acceptable code."""
    exp = set(expected)
    return next((i for i, c in enumerate(codes, 1) if c in exp), None)


def symptom_metrics(rows):
    n = len(rows)
    if not n:
        return {}
    ranks = [r["rank"] for r in rows]
    hit = lambda k: sum(1 for x in ranks if x and x <= k) / n
    return {"n": n, "hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5),
            "MRR": sum((1.0 / x) if x else 0.0 for x in ranks) / n,
            "false_declines": sum(1 for r in rows if r["declined"]),
            "false_decline_ids": [r["id"] for r in rows if r["declined"]]}


def no_dtc_metrics(rows):
    n = len(rows)
    if not n:
        return {}
    dec = sum(1 for r in rows if r["declined"])
    return {"n": n, "declines": dec, "decline_rate": dec / n,
            "decline_ids": [r["id"] for r in rows if r["declined"]],
            "advisory_without_decline": sum(1 for r in rows
                                            if not r["declined"] and r.get("advisory_shown"))}


def paired_bootstrap(a_rows, b_rows):
    """
    (b - a) mean difference in symptom MRR. 10,000 resamples, seed 0, resampled
    query indices SHARED between the two configs, percentile interval 2.5/97.5.
    """
    a = {r["id"]: (1.0 / r["rank"] if r["rank"] else 0.0) for r in a_rows}
    b = {r["id"]: (1.0 / r["rank"] if r["rank"] else 0.0) for r in b_rows}
    ids = sorted(a)
    if set(a) != set(b):
        raise SystemExit("ABORT: configs (a) and (b) scored different query ids.")
    n = len(ids)
    delta = sum(b[i] - a[i] for i in ids) / n
    rng = random.Random(SEED)
    draws = []
    for _ in range(RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        draws.append(sum(b[ids[j]] - a[ids[j]] for j in idx) / n)
    draws.sort()
    lo, hi = draws[int(0.025 * RESAMPLES)], draws[int(0.975 * RESAMPLES) - 1]
    better = sum(1 for i in ids if b[i] > a[i])
    worse = sum(1 for i in ids if b[i] < a[i])
    return {"delta_MRR": delta, "ci95": [lo, hi], "excludes_zero": bool(lo > 0 or hi < 0),
            "resamples": RESAMPLES, "seed": SEED,
            "better": better, "worse": worse, "tied": n - better - worse,
            "per_query": {i: {"a": a[i], "b": b[i], "delta": b[i] - a[i]} for i in ids}}


def verdict(bs):
    """
    The ONLY conclusions this run may draw (prereg section 4).
      replicated  delta > 0 AND better > worse
      confirmed   replicated AND the paired CI excludes 0
      otherwise   not replicated
    """
    replicated = bs["delta_MRR"] > 0 and bs["better"] > bs["worse"]
    confirmed = replicated and bs["excludes_zero"]
    label = "confirmed" if confirmed else ("replicated" if replicated else "not replicated")
    return {"verdict": label,
            "replicated": replicated, "confirmed": confirmed,
            "basis": {"delta_MRR_gt_0": bs["delta_MRR"] > 0,
                      "better_gt_worse": bs["better"] > bs["worse"],
                      "ci_excludes_zero": bs["excludes_zero"]},
            "adoption": "none - no adoption decision follows from this run (prereg section 4)"}


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------
def score(path, guards):
    gold = check_schema(path)
    qs, eligibility = check_eligibility(gold)   # aborts before anything is scored
    print(f"   provenance: author named, no-AI claim present")
    print(f"   paraphrase exclusions: {eligibility['paraphrases']['excluded_count']} "
          f"(cosine >= {PARAPHRASE_SIM} vs {eligibility['paraphrases']['prior_queries_compared']} "
          f"spent queries)")
    print(f"   word overlap: mean {eligibility['overlap']['mean']:.4f} "
          f"<= ceiling {eligibility['overlap']['ceiling']} "
          f"(max {eligibility['overlap']['max']:.4f}, "
          f"{eligibility['overlap']['over_ceiling']} row(s) over ceiling)")
    by_mode = {}
    for q in qs:
        by_mode.setdefault(q["mode"], []).append(q)
    unscored = {m: len(v) for m, v in by_mode.items() if m not in SCORED_MODES}

    out = {"gold_file": path, "gold_provenance": gold.get("provenance"),
           "gold_version": gold.get("version"), "gold_created": gold.get("created"),
           "queries_total": len(gold["queries"]),
           "queries_scored": len(qs),
           "eligibility": eligibility,
           "modes": {m: len(v) for m, v in sorted(by_mode.items())},
           "unscored_modes": unscored,
           "scoring": "lenient (any code in 'expected' counts), depth 5, as in Round 1",
           "guards": guards, "configs": {}}
    out["modes_scored_after_exclusions"] = {m: len([q for q in qs if q["mode"] == m])
                                            for m in sorted({q["mode"] for q in qs})}

    rows_by_config = {}
    for kind, narrow, modes in (("a_production", False, SCORED_MODES),
                                ("b_v2_half", False, SCORED_MODES),
                                ("c_prod_a_narrow", True, ("no_dtc",))):
        print(f"\n[{kind}]" + ("   (no_dtc rows only)" if modes == ("no_dtc",) else ""))
        R, A = build(kind)
        sym, nod, lat = [], [], []
        for q in qs:
            if q["mode"] not in modes:
                continue
            t = time.perf_counter()
            s = serve(R, A, q["query"], narrow)
            lat.append((time.perf_counter() - t) * 1000)
            row = {"id": q["id"], "rank": rank_of(s["codes"], q["expected"]),
                   "declined": s["declined"], "decline_by": s.get("decline_by"),
                   "advisory_shown": s.get("advisory_shown", False),
                   "codes": s["codes"][:K], "route": s.get("route"),
                   "reasons": s.get("reasons")}
            (sym if q["mode"] == "symptom" else nod).append(row)
        lat.sort()
        rows_by_config[kind] = {"symptom": sym, "no_dtc": nod}
        cfg = {"symptom": symptom_metrics(sym), "no_dtc": no_dtc_metrics(nod),
               "latency_ms": {"p50": round(statistics.median(lat), 1) if lat else None,
                              "p95": round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None},
               "rows": rows_by_config[kind]}
        out["configs"][kind] = cfg
        if sym:
            s = cfg["symptom"]
            print(f"   symptom n={s['n']} hit@1={s['hit@1']:.3f} hit@3={s['hit@3']:.3f} "
                  f"hit@5={s['hit@5']:.3f} MRR={s['MRR']:.4f} "
                  f"false declines {s['false_declines']}")
        if nod:
            d = cfg["no_dtc"]
            print(f"   no_dtc  n={d['n']} declines {d['declines']}/{d['n']} "
                  f"advisory-without-decline {d['advisory_without_decline']}")

    a_sym = rows_by_config["a_production"]["symptom"]
    b_sym = rows_by_config["b_v2_half"]["symptom"]
    if a_sym:
        bs = paired_bootstrap(a_sym, b_sym)
        out["paired_bootstrap_b_minus_a"] = bs
        out["conclusion"] = verdict(bs)
        print(f"\n(b - a) symptom MRR {bs['delta_MRR']:+.4f}  95% CI "
              f"[{bs['ci95'][0]:+.4f}, {bs['ci95'][1]:+.4f}]  "
              f"{'EXCLUDES' if bs['excludes_zero'] else 'includes'} zero")
        print(f"per-query: better {bs['better']}, worse {bs['worse']}, tied {bs['tied']}")
        print(f"VERDICT: {out['conclusion']['verdict'].upper()}  "
              f"(no adoption decision follows)")
    else:
        out["conclusion"] = {"verdict": "not scored - no symptom rows"}
    return out


def abort_demos():
    """
    Show every eligibility abort path firing, on variants built IN MEMORY so that no
    gold text is ever written to disk. Each case is a deliberate failure: the dry run
    is only honest if the guards are seen refusing, not merely seen passing.
    """
    base = json.load(open(DUMMY))
    ok_prov = base["provenance"]
    cases = []

    # (iii) provenance: no author named, and no AI disclaimer
    v = dict(base, provenance="Collected from the service desk.")
    cases.append(("(iii) provenance names no author and makes no AI claim", v))

    # (iii) provenance: author named but the AI claim missing
    v = dict(base, provenance="Written by A. Mehta, workshop foreman.")
    cases.append(("(iii) provenance names an author but omits the no-AI claim", v))

    # (i) overlap: queries lifted straight out of the manual's own descriptions
    recs = [json.loads(l) for l in open("data/dtc_records.jsonl")]
    by_code = {r["code_full"]: r["description"] for r in recs}
    picked = ["P0192-00", "P0117-00", "P0340-00"]
    v = dict(base, provenance=ok_prov, queries=[
        {"id": f"o{i}", "query": by_code[c], "mode": "symptom", "expected": [c],
         "notes": "synthetic - illustrative", "split": "R3_DUMMY"}
        for i, c in enumerate(picked, 1)])
    cases.append(("(i) queries copied from the manual's own descriptions", v))

    # (ii) every row is a verbatim already-spent query -> nothing left to score
    prior = [q["query"] for q in json.load(open(PRIOR_SETS[1]))["queries"]
             if q["mode"] == "symptom"][:3]
    v = dict(base, provenance=ok_prov, queries=[
        {"id": f"p{i}", "query": q, "mode": "symptom", "expected": ["P0192-00"],
         "notes": "synthetic - illustrative", "split": "R3_DUMMY"}
        for i, q in enumerate(prior, 1)])
    cases.append(("(ii) every row is an already-spent query", v))

    print("\n=== abort paths (deliberate failures, in-memory variants) ===")
    for label, variant in cases:
        try:
            check_eligibility(variant)
            print(f"  [!!] {label}: NO ABORT - the guard did not fire")
        except EligibilityError as e:
            print(f"  [ABORT as designed] {label}\n        {str(e)[:150]}")

    # (ii) again, as an EXCLUSION rather than an abort: one spent query among good ones
    mixed = dict(base, provenance=ok_prov,
                 queries=base["queries"] + [
                     {"id": "p9", "query": prior[0], "mode": "symptom",
                      "expected": ["P0192-00"], "notes": "synthetic - illustrative",
                      "split": "R3_DUMMY"}])
    kept, rep = check_eligibility(mixed)
    ex = rep["paraphrases"]["excluded"]
    print(f"  [EXCLUDED, not aborted] one spent query among good rows: "
          f"{len(ex)} excluded, {len(kept)} rows kept")
    for e in ex:
        print(f"        {e['id']} cosine {e['cosine']} vs {e['nearest_prior_set']}:"
              f"{e['nearest_prior_id']}")

    # schema guard, on a file-shaped variant
    bad = dict(base)
    bad["queries"] = [dict(q) for q in base["queries"]]
    bad["queries"][0].pop("notes")
    tmp = "data/demo/_schema_probe.json"
    json.dump(bad, open(tmp, "w"))
    try:
        check_schema(tmp)
        print("  [!!] schema guard did not fire")
    except SystemExit as e:
        print(f"  [ABORT as designed] schema: {str(e)[:120]}")
    finally:
        os.remove(tmp)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help=f"score the synthetic dummy at {DUMMY}; writes nothing")
    g.add_argument("--run", action="store_true",
                   help=f"the single scoring run on {GOLD}")
    a = ap.parse_args()

    if a.run:
        if os.path.exists(RESULTS):
            print(f"REFUSING: {RESULTS} exists. Round 3 is one shot (prereg section 5).")
            return 1
        if not os.path.exists(GOLD):
            print(f"REFUSING: {GOLD} does not exist yet.")
            return 1
    path = GOLD if a.run else DUMMY
    if a.dry_run and not os.path.exists(path):
        print(f"REFUSING: {path} missing. Create the 3-row synthetic dummy first.")
        return 1

    print(f"verifying the 12.2 freeze and config (a) against the tag ...")
    guards = {"freeze_12_2": check_freeze(), "dev_determinism_hash": check_determinism(),
              "schema_reference": SCHEMA_REF}
    print(f"   12.2 freeze: {guards['freeze_12_2']['artefacts_verified']} artefacts verified, "
          f"chosen_variant={guards['freeze_12_2']['chosen_variant']}")
    print(f"   DEV determinism hash: {guards['dev_determinism_hash']} (as recorded for "
          f"v3-final-eval)")

    try:
        out = score(path, guards)
    except EligibilityError as e:
        print(f"\nABORT - eligibility (addendum section 2): {e}")
        return 1

    if a.run:
        os.makedirs(OUT_DIR, exist_ok=True)
        json.dump(out, open(RESULTS, "w"), indent=1, default=str)
        print(f"\nwrote {RESULTS} - this file now blocks any re-run")
    else:
        abort_demos()
        out["label"] = ("DRY RUN on synthetic dummy data - NOT a result, NOT Round 3. "
                        "Nothing is written to data/experiments/.")
        print("\nDRY RUN complete; nothing written. Dummy rows are synthetic - illustrative.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
