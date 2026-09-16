"""
Validates a gold query set against the authoring rules (Phase 8.0).

    PYTHONPATH=src .venv/bin/python src/check_gold.py [data/gold_v2.json]

Hard failures (exit 1):
  * an expected code that does not exist in the manual
  * duplicate query text or duplicate id
  * a TEST symptom query above the word-overlap CEILING
Warnings (reported, not enforced):
  * DEV symptom queries above the ceiling - authored before the rule existed and
    grandfathered by decision (DEV is not frozen, but was deliberately left unchanged)

Uses only the gold set and the manual records. It never runs retrieval, so it is
safe to use while authoring a frozen split.
"""
from __future__ import annotations

import json
import sys

from gold_overlap import CEILING, load_descriptions, overlap, symptom_stats

ENFORCED_SPLITS = {"DEV", "TEST"}   # uniform since gold v2.2


def main(path="data/gold_v2.json"):
    g = json.load(open(path))
    desc = load_descriptions()
    codes = set(desc)
    errors, warnings = [], []

    ids = [q["id"] for q in g["queries"]]
    texts = [q["query"].strip().lower() for q in g["queries"]]
    if len(ids) != len(set(ids)):
        errors.append("duplicate ids")
    if len(texts) != len(set(texts)):
        errors.append("duplicate query text")

    for q in g["queries"]:
        if q["expected"] != "none":
            missing = [c for c in q["expected"] if c not in codes]
            if missing:
                errors.append(f"{q['id']}: expected codes not in manual {missing}")
        if q["mode"] == "symptom":
            sc, sh, _ = overlap(q["query"], q["expected"], desc)
            if sc > CEILING:
                msg = (f"{q['id']} [{q['split']}] overlap {sc:.3f} > {CEILING} "
                       f"shared={sorted(sh)} :: {q['query']!r}")
                (errors if q["split"] in ENFORCED_SPLITS else warnings).append(msg)

    print(f"gold set: {path}  version={g.get('version')}  queries={len(ids)}")
    for split in ("DEV", "TEST"):
        st, _ = symptom_stats([q for q in g["queries"] if q["split"] == split], desc)
        print(f"  {split:4s} symptom n={st['n']:2d}  mean overlap={st['mean']:.3f}  "
              f"zero-overlap={st['zero_overlap']}/{st['n']}  max={st['max']:.3f}  "
              f"over ceiling={st['over_ceiling']}")
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print("RESULT:", "PASS" if not errors else f"FAIL ({len(errors)} errors)")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
