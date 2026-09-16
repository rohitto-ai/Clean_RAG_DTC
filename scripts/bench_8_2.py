"""
Phase 8.2 benchmark driver — DEV ONLY. TEST queries are filtered out before
anything is loaded, so this script cannot evaluate the frozen split.

Part A: embedder comparison (dense side), with each model's query/passage
convention and, where the convention is uncertain, the variant without it.
Part C: lexicon configurations on top of a chosen embedder.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys

sys.path.insert(0, "src")

BGE_INSTR = "Represent this sentence for searching relevant passages: "

EMBEDDERS = [
    # name, index_dir, query_prefix, note
    ("all-MiniLM-L6-v2 (baseline)", "index", "", "no prefix"),
    ("bge-small-en-v1.5 (no instruction)", "index_exp/bge", "", "no query instruction"),
    ("bge-small-en-v1.5 (+instruction)", "index_exp/bge", BGE_INSTR, "BGE retrieval instruction on queries"),
    ("gte-small", "index_exp/gte", "", "no prefix (per model card)"),
    ("e5-small-v2 (query:/passage:)", "index_exp/e5_prefix", "query: ", "required e5 prefixes"),
    ("e5-small-v2 (no prefixes)", "index_exp/e5_noprefix", "", "prefixes omitted"),
]
RANKED = ("exact_code", "near_duplicate", "symptom")


def dense_only(R, queries):
    import evaluate as E
    rows = []
    for q in queries:
        if q["mode"] != "symptom":
            continue
        res = R.coll.query(query_embeddings=R._embed(q["query"]), n_results=5)
        got = [R._rec(i)["code_full"] for i in res["ids"][0]]
        rank = next((i for i, c in enumerate(got, 1) if c in set(q["expected"])), None)
        rows.append({"rank": rank})
    return E.metrics(rows)


def evaluate(cfg, dev, records, lexicon=None, expand="none"):
    import answer as A
    import evaluate_v2 as EV
    from retrieve import Retriever
    name, index_dir, qprefix = cfg[0], cfg[1], cfg[2]
    R = Retriever(index_dir=index_dir, query_prefix=qprefix, lexicon=lexicon, expand=expand)
    res = EV.run(R, dev, records, A)
    out = {"name": name, "index_dir": index_dir, "query_prefix": qprefix,
           "model": R.model_name, "expand": expand,
           "index_aliases": R.meta.get("aliases", {}).get("mode", "none"),
           "by_mode": res["by_mode"], "overall": res["overall"],
           "system_group": res["system_group"], "honesty": res["honesty"],
           "dense_only_symptom": dense_only(R, dev),
           "_rows": res["_rows"]}
    del R
    gc.collect()
    return out


# Near-duplicate discrimination guardrails. Manual-style AND colloquial phrasings:
# the colloquial ones trigger the SAME aliases on all four injector records, so they
# are exactly the queries that would expose aliasing re-collapsing near-duplicates.
GUARDRAILS = [("camshaft no signal", "P0340-00"),
              ("camshaft disturbed signal", "P0341-00")]
for n in range(1, 5):
    GUARDRAILS += [(f"injector open circuit cylinder {n}", f"P020{n}-00"),
                   (f"cylinder {n} injector has a broken wire", f"P020{n}-00"),
                   (f"injector short circuit high and low side cylinder {n}", f"P120{n}-00")]

PART_C = [
    # name, index_dir, expand
    ("C0 baseline (no lexicon)", "index", "none"),
    ("C1 aliases->BM25", "index_exp/minilm_alias_bm25", "none"),
    ("C2 expansion->BM25", "index", "bm25"),
    ("C3 expansion->BM25+dense", "index", "both"),
    ("C4 aliases->BM25 + expansion->BM25", "index_exp/minilm_alias_bm25", "bm25"),
    ("C5 aliases->BM25+dense + expansion->BM25", "index_exp/minilm_alias_both", "bm25"),
    ("C6 aliases->BM25+dense + expansion->BM25+dense", "index_exp/minilm_alias_both", "both"),
    ("C7 gte-small: aliases->BM25 + expansion->BM25", "index_exp/gte_alias_bm25", "bm25"),
]


def guardrails(R):
    out = []
    for q, exp in GUARDRAILS:
        got = [i["record"]["code_full"] for i in R.retrieve(q, k=5)["results"]]
        out.append({"query": q, "expected": exp, "top1": got[0] if got else None,
                    "rank": next((i for i, c in enumerate(got, 1) if c == exp), None),
                    "pass": bool(got) and got[0] == exp})
    return out


def part_c(dev, records):
    import answer as A
    import evaluate_v2 as EV
    from lexicon import Lexicon
    from retrieve import Retriever
    lex = Lexicon()
    results = []
    for name, index_dir, expand in PART_C:
        R = Retriever(index_dir=index_dir, lexicon=lex if expand != "none" else None,
                      expand=expand)
        res = EV.run(R, dev, records, A)
        g = guardrails(R)
        r = {"name": name, "index_dir": index_dir, "expand": expand,
             "index_aliases": R.meta.get("aliases", {}).get("mode", "none"),
             "by_mode": res["by_mode"], "overall": res["overall"],
             "system_group": res["system_group"], "honesty": res["honesty"],
             "guardrails": g, "guardrails_passed": sum(x["pass"] for x in g),
             "_rows": res["_rows"], "_honesty": res["_honesty"]}
        results.append(r)
        s, o = r["by_mode"]["symptom"], r["overall"]
        print(f"{name:48s} symptom hit@1={s['hit@1']:.3f} hit@5={s['hit@5']:.3f} MRR={s['MRR']:.3f}"
              f" | overall MRR={o['MRR']:.3f} | near_dup MRR={r['by_mode']['near_duplicate']['MRR']:.3f}"
              f" | guardrails {r['guardrails_passed']}/{len(g)}"
              f" | gate oos {r['honesty']['oos_gated']}/6 in {r['honesty']['in_scope_passed']}/28",
              flush=True)
        del R
        gc.collect()
    json.dump([{k: v for k, v in r.items() if not k.startswith("_")} for r in results],
              open("data/experiments/8_2/partC_lexicon_dev.json", "w"), indent=2)
    json.dump({r["name"]: {"rows": r["_rows"], "honesty": r["_honesty"]} for r in results},
              open("data/experiments/8_2/partC_lexicon_dev_rows.json", "w"), indent=1)
    print("wrote data/experiments/8_2/partC_lexicon_dev.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["A", "C"], default="A")
    args = ap.parse_args()
    gold = json.load(open("data/gold_v2.json"))
    dev = [q for q in gold["queries"] if q["split"] == "DEV"]      # TEST never loaded
    assert all(q["split"] == "DEV" for q in dev)
    records = [json.loads(l) for l in open("data/dtc_records.jsonl")]

    if args.part == "C":
        return part_c(dev, records)

    results = []
    for cfg in EMBEDDERS:
        r = evaluate(cfg, dev, records)
        results.append(r)
        s, o, d = r["by_mode"]["symptom"], r["overall"], r["dense_only_symptom"]
        print(f"{r['name']:38s} symptom hit@1={s['hit@1']:.3f} MRR={s['MRR']:.3f} | "
              f"overall MRR={o['MRR']:.3f} | dense-only symptom MRR={d['MRR']:.3f} | "
              f"gate oos {r['honesty']['oos_gated']}/{r['honesty']['oos_n']} "
              f"in {r['honesty']['in_scope_passed']}/{r['honesty']['in_scope_n']}", flush=True)
    json.dump([{k: v for k, v in r.items() if not k.startswith("_")} for r in results],
              open("data/experiments/8_2/partA_embedders_dev.json", "w"), indent=2)
    json.dump({r["name"]: r["_rows"] for r in results},
              open("data/experiments/8_2/partA_embedders_dev_rows.json", "w"), indent=1)
    print("wrote data/experiments/8_2/partA_embedders_dev.json")


if __name__ == "__main__":
    main()
