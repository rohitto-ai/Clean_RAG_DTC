"""
Phase 8.3b determinism proof — DEV ONLY (TEST filtered out before loading).

Runs the full DEV evaluation (C4b retrieval + gate v2) and writes a CANONICAL JSON
of everything a reported metric depends on: every ranked query's rank and top-5,
every system_group result, every gate decision with its reasons, and all
aggregate metrics. Its sha256 is printed. Run it in several separate processes
(with different PYTHONHASHSEED values): identical hashes = byte-identical results.

    PYTHONHASHSEED=0 PYTHONPATH=src .venv/bin/python scripts/determinism_proof.py --exact 1 --tag p0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, "src")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exact", type=int, choices=[0, 1], default=1)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--index-dir", default="index_exp/minilm_alias_bm25_cyl")
    ap.add_argument("--defaults", action="store_true",
                    help="construct exactly as production does: Retriever(index_dir) with auto "
                         "config, and the default gate (Phase 8.5 adoption check)")
    args = ap.parse_args()

    import answer as A
    import evaluate_v2 as EV
    from gate import Gate
    from lexicon import Lexicon
    from retrieve import Retriever

    gold = json.load(open("data/gold_v2.json"))
    dev = [q for q in gold["queries"] if q["split"] == "DEV"]
    assert dev and all(q["split"] == "DEV" for q in dev)
    records = [json.loads(l) for l in open("data/dtc_records.jsonl")]

    if args.defaults:
        R = Retriever(index_dir=args.index_dir)
        gate = A.default_gate()
    else:
        R = Retriever(index_dir=args.index_dir, lexicon=Lexicon(),
                      expand="bm25", exact_dense=bool(args.exact))
        gate = Gate("data/gate_c4b.json")
    res = EV.run(R, dev, records, A, gate)

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
    digest = hashlib.sha256(blob).hexdigest()
    mode = ("prod_defaults" if args.defaults else "exact") if args.exact else "hnsw"
    out = f"data/experiments/8_3b/dev_{mode}_{args.tag}.json"
    open(out, "wb").write(blob)
    s = res["by_mode"]["symptom"]
    print(f"[{mode:5s} {args.tag} PYTHONHASHSEED={os.environ.get('PYTHONHASHSEED','unset')}] "
          f"sha256={digest[:16]} symptom MRR={s['MRR']:.4f} overall MRR={res['overall']['MRR']:.4f} "
          f"gate oos {res['honesty']['oos_gated']}/{res['honesty']['oos_n']} "
          f"in {res['honesty']['in_scope_passed']}/{res['honesty']['in_scope_n']}", flush=True)


if __name__ == "__main__":
    main()
