"""
Phase 10.6 step 1 — validate the INDEPENDENT gold set. NO RETRIEVAL IS RUN HERE.

    PYTHONPATH=src .venv/bin/python scripts/validate_independent.py

Checks the file's sha256, its schema, and that every expected code exists in the
manual; then reports word-overlap statistics (src/gold_overlap.py) FOR INFORMATION
ONLY. Nothing is dropped or edited on the strength of those statistics: this set
is independent, and trimming it to suit the system would destroy the only
uncontaminated measurement available.

Exit 1 on any failure.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter

sys.path.insert(0, "src")

GOLD = "data/gold_independent.json"
EXPECTED_SHA = "266abff6aaf30078aafc15a0decfa3e1ced3014f8519eb7b15088d830df6ecf4"
FAILURES = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def main():
    raw = open(GOLD, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()

    print("== file ==")
    check("sha256 matches the brief", sha == EXPECTED_SHA, sha)

    g = json.loads(raw)
    qs = g["queries"]
    print("\n== schema ==")
    check("top-level keys", {"version", "created", "provenance", "queries"} <= set(g))
    check("60 queries", len(qs) == 60, str(len(qs)))
    check("ids are unique", len({q["id"] for q in qs}) == len(qs))
    required = {"id", "query", "mode", "expected", "confidence", "split"}
    check("every row has the required fields", all(required <= set(q) for q in qs))
    check("every split is INDEPENDENT", all(q["split"] == "INDEPENDENT" for q in qs))
    check("modes are symptom/no_dtc only", {q["mode"] for q in qs} == {"symptom", "no_dtc"},
          str(Counter(q["mode"] for q in qs)))
    check("41 symptom + 19 no_dtc",
          sum(q["mode"] == "symptom" for q in qs) == 41
          and sum(q["mode"] == "no_dtc" for q in qs) == 19)
    check("confidence is high/medium/low",
          {q["confidence"] for q in qs} <= {"high", "medium", "low"},
          str(Counter(q["confidence"] for q in qs)))
    check("every query text is non-empty", all(str(q["query"]).strip() for q in qs))
    check("symptom rows have at least one expected code",
          all(q["expected"] for q in qs if q["mode"] == "symptom"))
    check("no_dtc rows have an empty expected list",
          all(q["expected"] == [] for q in qs if q["mode"] == "no_dtc"))

    print("\n== ground truth exists in the manual ==")
    records = [json.loads(l) for l in open("data/dtc_records.jsonl")]
    known = {r["code_full"] for r in records}
    missing = sorted({c for q in qs for c in q["expected"]} - known)
    check("every expected code exists in the 314 records", not missing, str(missing))
    exp_counts = [len(q["expected"]) for q in qs if q["mode"] == "symptom"]
    print(f"       expected-set sizes: min {min(exp_counts)}, median "
          f"{sorted(exp_counts)[len(exp_counts) // 2]}, max {max(exp_counts)}; "
          f"{sum(exp_counts)} code slots over 41 rows")

    print("\n== leakage guard ==")
    # the system must only ever see q["query"]; make sure nothing else is needed
    check("lamp_reported is present but is metadata only",
          all("lamp_reported" in q for q in qs),
          "the evaluator passes q['query'] and nothing else")

    print("\n== word overlap with the manual (INFORMATION ONLY) ==")
    from gold_overlap import CEILING, load_descriptions, overlap, symptom_stats
    desc = load_descriptions()
    sym = [q for q in qs if q["mode"] == "symptom"]
    st, rows = symptom_stats(sym, desc)
    print(f"       n={st['n']}  mean={st['mean']:.3f}  max={st['max']:.3f}  "
          f"zero-overlap={st['zero_overlap']}  over ceiling {CEILING}={st['over_ceiling']}")
    by_conf = {}
    for q in sym:
        # overlap() returns (score, shared_terms, best_code)
        by_conf.setdefault(q["confidence"], []).append(
            overlap(q["query"], q["expected"], desc)[0])
    for c in ("high", "medium", "low"):
        v = by_conf.get(c, [])
        if v:
            print(f"       {c:6s} n={len(v):2d}  mean={sum(v) / len(v):.3f}  max={max(v):.3f}")
    worst = sorted(((overlap(q["query"], q["expected"], desc)[0], q["id"]) for q in sym),
                   reverse=True)[:5]
    print(f"       highest-overlap rows: "
          + ", ".join(f"{i} {o:.3f}" for o, i in worst))
    print("       NOTE: reported for information. No query is dropped or edited, and")
    print("       the DEV ceiling does not apply to an independent set.")

    print(f"\n==== INDEPENDENT GOLD: {'OK' if not FAILURES else str(len(FAILURES)) + ' FAILURE(S)'} ====")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
