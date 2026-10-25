"""
Phase 10.1 — FREEZE the lexicon v2 artifacts before the independent evaluation.

    PYTHONPATH=src .venv/bin/python scripts/freeze_10_1.py

Writes data/experiments/10_1/freeze.json: sha256 of the lexicon, of every rule
code file, and of the experimental BM25 corpus, plus entry counts by provenance.

From the moment this is committed, the lexicon and the rules may NOT change until
the independent technician query set has been evaluated. Re-run this script to
verify: it reports PASS/FAIL per file against the frozen hashes when they already
exist, and refuses to overwrite unless --force is given.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys

sys.path.insert(0, "src")

OUT = "data/experiments/10_1/freeze.json"
FILES = [
    "data/domain_lexicon_v2.json",          # the lexicon itself
    "src/lexicon.py",                       # R1 + R2 query-side rules
    "src/build_index.py",                   # the compound-token folds (index side)
    "scripts/build_lexicon_v2.py",          # the deterministic lexicon builder
    "index_exp/minilm_lexv2/bm25_corpus.json",   # the experimental BM25 corpus
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def counts():
    lx = json.load(open("data/domain_lexicon_v2.json"))
    entries = ([("system:" + n, e) for n, e in lx["system_aliases"].items()]
               + [("term:" + e["manual"][0], e) for e in lx["term_synonyms"]])
    prov = collections.Counter(e["provenance"] for _, e in entries)
    origin = collections.Counter(e["origin"] for _, e in entries)
    colloq = sum(len(e["colloquial"]) for _, e in entries)
    v2_authored = sum(len(e["colloquial"]) if e["origin"] == "phase10.1"
                      else len(e.get("added_in_v2", [])) for _, e in entries)
    return {
        "entries_total": len(entries),
        "entries_system_level": len(lx["system_aliases"]),
        "entries_description_level": len(lx["term_synonyms"]),
        "by_provenance": dict(sorted(prov.items())),
        "by_origin": dict(sorted(origin.items())),
        "dev_driven": prov.get("dev_driven", 0),
        "colloquial_terms_total": colloq,
        "colloquial_terms_authored_in_v2": v2_authored,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite an existing freeze")
    a = ap.parse_args()

    hashes = {p: sha256(p) for p in FILES}
    if os.path.exists(OUT) and not a.force:
        old = json.load(open(OUT))
        print(f"freeze already exists ({old['frozen_utc']}) — verifying, not overwriting")
        bad = 0
        for p, h in hashes.items():
            was = old["sha256"].get(p)
            ok = was == h
            bad += not ok
            print(f"  [{'PASS' if ok else 'FAIL'}] {p}")
            if not ok:
                print(f"           frozen {was}\n           now    {h}")
        print(f"\n{'all files match the freeze' if not bad else f'{bad} FILE(S) CHANGED SINCE FREEZE'}")
        sys.exit(1 if bad else 0)

    from datetime import datetime, timezone
    blob = {
        "phase": "10.1",
        "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statement": "Domain lexicon v2 and its query-side rules are frozen. They may not "
                     "change until the independent technician query set has been evaluated. "
                     "The independent set was never read, requested or received in this phase.",
        "experimental_index": "index_exp/minilm_lexv2",
        "production_untouched": {
            "index": "index/ (C4b) unchanged",
            "determinism_hash_dev_defaults": "ffff9bc707d8754d",
            "suite": "44 passed / 1 xfail / 0 failed",
        },
        "counts": counts(),
        "sha256": hashes,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(blob, f, indent=1)
        f.write("\n")
    print(f"wrote {OUT}")
    print(json.dumps(blob["counts"], indent=1))
    for p, h in hashes.items():
        print(f"  {h}  {p}")


if __name__ == "__main__":
    main()
