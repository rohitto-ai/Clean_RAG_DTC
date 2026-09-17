"""
Phase 8.5 — the ONE-SHOT TEST evaluation (pre-registered).

Evaluates five pre-declared configurations, DEV first and then TEST, in a single
pass, and writes everything to data/experiments/8_5/final_eval_results.json.

ONE-SHOT ENFORCEMENT: refuses to run if the results file already exists. The
configurations, their input files and their sha256 hashes are recorded in
data/experiments/8_5/preregistration.json and committed BEFORE this runs, so git
history shows the protocol was fixed before TEST was seen.

Configurations
  v1   the v1-phase7 system (no lexicon, legacy gate), re-measured with the
       current exact ranking - the before-picture
  a    C4b + full lexicon + gate v2 full stoplist
  b    lexicon ablated (19 TEST-matching entries removed from BOTH the index
       aliases and query expansion) + full stoplist
  c    full lexicon + stoplist ablated (8 TEST-matching intent terms removed)
  d    BOTH ablated  <- the conservative headline
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "src")
OUT = "data/experiments/8_5/final_eval_results.json"

CONFIGS = [
    ("v1", "v1-phase7 system (no lexicon, legacy gate), exact ranking",
     "index", None, "none", None),
    ("a", "C4b full lexicon + gate v2 full stoplist",
     "index_exp/minilm_alias_bm25_cyl", "data/domain_lexicon.json", "bm25",
     "data/gate_c4b.json"),
    ("b", "lexicon ABLATED + gate v2 full stoplist",
     "index_exp/minilm_alias_bm25_cyl_lexablated",
     "data/experiments/8_5/domain_lexicon_ablated.json", "bm25",
     "data/experiments/8_5/gate_full_on_lexablated.json"),
    ("c", "C4b full lexicon + gate stoplist ABLATED",
     "index_exp/minilm_alias_bm25_cyl", "data/domain_lexicon.json", "bm25",
     "data/experiments/8_5/gate_stopablated.json"),
    ("d", "BOTH ablated (conservative headline)",
     "index_exp/minilm_alias_bm25_cyl_lexablated",
     "data/experiments/8_5/domain_lexicon_ablated.json", "bm25",
     "data/experiments/8_5/gate_stopablated_on_lexablated.json"),
]


def evaluate(split_queries, records):
    import answer as A
    import evaluate_v2 as EV
    from gate import Gate
    from lexicon import Lexicon
    from retrieve import Retriever
    out = {}
    for key, desc, index_dir, lex_path, expand, gate_path in CONFIGS:
        R = Retriever(index_dir=index_dir,
                      lexicon=Lexicon(lex_path) if lex_path else None,
                      expand=expand, exact_dense=True)
        gate = Gate(gate_path) if gate_path else None
        res = EV.run(R, split_queries, records, A, gate)
        out[key] = {
            "description": desc, "index_dir": index_dir, "lexicon": lex_path,
            "expand": expand, "gate": gate_path or "legacy v1",
            "by_mode": res["by_mode"], "overall": res["overall"],
            "system_group": res["system_group"], "honesty": res["honesty"],
            "rows": [{"id": r["id"], "mode": r["mode"], "rank": r["rank"], "got": r["got"]}
                     for r in res["_rows"]],
            "groups": res["_groups"],
            "gate_decisions": [{"id": h["id"], "in_scope": h["in_scope"], "passed": h["passed"],
                                "reasons": (h["signals"] or {}).get("refusal_reasons")}
                               for h in res["_honesty"]],
        }
        s, o, h = res["by_mode"]["symptom"], res["overall"], res["honesty"]
        print(f"  [{key}] symptom hit@1={s['hit@1']:.3f} MRR={s['MRR']:.4f} | overall "
              f"hit@1={o['hit@1']:.3f} MRR={o['MRR']:.4f} | gate oos {h['oos_gated']}/"
              f"{h['oos_n']} in {h['in_scope_passed']}/{h['in_scope_n']}", flush=True)
    return out


def main():
    if os.path.exists(OUT):
        raise SystemExit(f"REFUSING: {OUT} exists. TEST is evaluated exactly once.")
    gold = json.load(open("data/gold_v2.json"))
    records = [json.loads(l) for l in open("data/dtc_records.jsonl")]
    dev = [q for q in gold["queries"] if q["split"] == "DEV"]
    test = [q for q in gold["queries"] if q["split"] == "TEST"]
    print(f"gold {gold['version']}: DEV {len(dev)} | TEST {len(test)}")
    print("== DEV ==")
    dev_res = evaluate(dev, records)
    print("== TEST (one shot) ==")
    test_res = evaluate(test, records)
    json.dump({"gold_version": gold["version"], "DEV": dev_res, "TEST": test_res},
              open(OUT, "w"), indent=1)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
