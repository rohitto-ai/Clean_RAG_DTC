"""
Phase 9.2 — comparative evaluation against named baselines. Additive: production
code, indexes and gate are untouched; the naive index is built in index_naive/.

    PYTHONPATH=src .venv/bin/python scripts/baselines_9_2.py build-naive
    PYTHONPATH=src .venv/bin/python scripts/baselines_9_2.py eval

Methods (all over the SAME 314 records, except naive-chunk which by design has no
records - only flat manual text):
  keyword      BM25Okapi over build_index.bm25_text(record), plain tokenizer
               (no lexicon aliases, no cylinder token), no router
  rule_based   DTC-code regex -> code dictionary lookup; any query without a code
               returns NOTHING (the traditional code-lookup tool's limitation)
  dense_only   MiniLM exact cosine over the production record vectors
               (embedding_text, which carries no aliases), no BM25, no router
  naive_chunk  flat pdfplumber text of pages 8-545, fixed 500-char chunks with
               50-char overlap, MiniLM exact cosine; each chunk is mapped back to
               the DTC owning most of its characters; ranked chunks are collapsed
               to their DTCs (first occurrence wins)
  hybrid       adopted production system: Retriever() router + RRF + lexicon (C4b),
               gate v2 applied exactly as answer.answer() applies it (hybrid route
               only); a gate refusal returns nothing

Ranking is always exact (no approximate search) and ties break by id, so every
number here is reproducible. MiniLM is the only model loaded, once.

Metrics are at code_full level: rank = first position whose code_full is expected.
TEST (gold v2.2) is spent and is NOT evaluated here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

NAIVE_DIR = "index_naive"
CHUNK, OVERLAP = 500, 50
FIRST_PAGE, K = 8, 5
OUT_DIR = "data/experiments/9_2"
METHODS = ["keyword", "rule_based", "dense_only", "naive_chunk", "hybrid"]


# ------------------------------------------------------------------ naive index
def build_naive(model=None):
    import numpy as np
    import pdfplumber
    import parse_dtc as P

    recs = [json.loads(l) for l in open("data/dtc_records.jsonl")]
    rec_by = {(r["code_full"], r["page"]): f"{r['code_full']}@p{r['page']}#{r['occurrence']}"
              for r in recs}

    text, owners = [], []           # owners: (char_offset, record_id) at each DTC start
    pos = 0
    with pdfplumber.open(P.PDF_PATH) as pdf:
        for pno in range(FIRST_PAGE, len(pdf.pages) + 1):
            pg = pdf.pages[pno - 1]
            page_text = (pg.extract_text() or "") + "\n"
            for m in re.finditer(r"^.*$", page_text, re.M):
                h = P.DTC_HEADER.match(m.group(0).strip())
                if h:
                    rid = rec_by.get((f"{h.group(1).upper()}-{h.group(2).upper()}", pno))
                    if rid and (not owners or owners[-1][1] != rid):
                        owners.append((pos + m.start(), rid))
            text.append(page_text)
            pos += len(page_text)
            pg.flush_cache()
    full = "".join(text)

    chunks, start = [], 0
    step = CHUNK - OVERLAP
    while start < len(full):
        end = min(start + CHUNK, len(full))
        share = {}
        for j, (o, rid) in enumerate(owners):
            o_end = owners[j + 1][0] if j + 1 < len(owners) else len(full)
            ov = min(end, o_end) - max(start, o)
            if ov > 0:
                share[rid] = share.get(rid, 0) + ov
        owner = max(sorted(share), key=lambda r: share[r]) if share else None
        chunks.append({"i": len(chunks), "start": start, "end": end, "owner": owner,
                       "text": full[start:end]})
        if end == len(full):
            break
        start += step

    if model is None:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    vecs = model.encode([c["text"] for c in chunks], batch_size=32,
                        normalize_embeddings=True, show_progress_bar=False)
    os.makedirs(NAIVE_DIR, exist_ok=True)
    np.save(f"{NAIVE_DIR}/vectors.npy", np.asarray(vecs, dtype="float32"))
    json.dump({"chunk_chars": CHUNK, "overlap": OVERLAP, "first_page": FIRST_PAGE,
               "n_chunks": len(chunks), "n_chars": len(full),
               "dtc_starts_found": len(owners), "records": len(recs),
               "unowned_chunks": sum(c["owner"] is None for c in chunks),
               "chunks": chunks}, open(f"{NAIVE_DIR}/chunks.json", "w"))
    print(f"naive index: {len(full)} chars -> {len(chunks)} chunks; "
          f"{len(owners)}/{len(recs)} DTC starts located; "
          f"{sum(c['owner'] is None for c in chunks)} chunks own no DTC")


# ------------------------------------------------------------------ methods
class Methods:
    def __init__(self):
        import numpy as np
        from rank_bm25 import BM25Okapi
        from build_index import bm25_text, tokenize
        from retrieve import Retriever
        import answer as A

        self.A, self.np = A, np
        self.R = Retriever()                      # production (C4b), loads MiniLM once
        assert self.R.meta.get("aliases", {}).get("mode") == "bm25", \
            "dense vectors must be alias-free for dense_only to be a clean baseline"
        self.recs = self.R.records
        self.kw_ids = sorted(self.recs)
        self.tokenize = lambda t: tokenize(t, cylinder_compound=False)
        self.kw = BM25Okapi([self.tokenize(bm25_text(self.recs[i])) for i in self.kw_ids])

        blob = json.load(open(f"{NAIVE_DIR}/chunks.json"))
        self.chunk_owner = [c["owner"] for c in blob["chunks"]]
        self.chunk_vecs = np.load(f"{NAIVE_DIR}/vectors.npy")
        self.naive_meta = {k: v for k, v in blob.items() if k != "chunks"}

    def code(self, rid):
        return self.recs[rid]["code_full"]

    def keyword(self, q, qv):
        s = self.kw.get_scores(self.tokenize(q))
        order = sorted(range(len(s)), key=lambda i: (-s[i], self.kw_ids[i]))
        return [self.code(self.kw_ids[i]) for i in order if s[i] > 0][:K]

    def rule_based(self, q, qv):
        from retrieve import detect_code
        code_full, base = detect_code(q)
        ci = self.R.code_index
        refs = (ci["by_code_full"].get(code_full) if code_full else None) or \
               (ci["by_dtc_code"].get(base) if base else None) or []
        return [self.code(x["id"]) for x in refs][:K]

    def dense_only(self, q, qv):
        sims = self.R.vectors @ qv
        order = sorted(range(len(sims)), key=lambda i: (-float(sims[i]), self.R.vec_ids[i]))
        return [self.code(self.R.vec_ids[i]) for i in order[:K]]

    def naive_chunk(self, q, qv):
        sims = self.chunk_vecs @ qv
        out = []
        for i in sorted(range(len(sims)), key=lambda i: (-float(sims[i]), i)):
            o = self.chunk_owner[i]
            if o is None:
                continue
            c = self.code(o)
            if c not in out:
                out.append(c)
            if len(out) == K:
                break
        return out

    def hybrid(self, q, qv, gate_on=True):
        out = self.R.retrieve(q, k=K)
        if gate_on and out["mode"] == "hybrid":         # exactly where answer() gates
            ok, _ = self.A.is_relevant(self.R, q)
            if not ok:
                return []
        return [i["record"]["code_full"] for i in out["results"]][:K]


def score(got, expected):
    exp = set(expected)
    return next((i for i, c in enumerate(got, 1) if c in exp), None)


def metrics(rows):
    import evaluate as E
    return E.metrics(rows)


def run_set(M, cases, extra_gate_off=False):
    qs = [c["query"] for c in cases]
    qvecs = M.R.model.encode(qs, batch_size=64, normalize_embeddings=True,
                             show_progress_bar=False)
    rows = {m: [] for m in METHODS + (["hybrid_gate_off"] if extra_gate_off else [])}
    for c, qv in zip(cases, qvecs):
        qv = M.np.asarray(qv, dtype="float32")
        for m in METHODS:
            got = getattr(M, m)(c["query"], qv)
            rows[m].append({"id": c["id"], "stratum": c["stratum"], "got": got,
                            "rank": score(got, c["expected"]), "empty": not got})
        if extra_gate_off:
            got = M.hybrid(c["query"], qv, gate_on=False)
            rows["hybrid_gate_off"].append({"id": c["id"], "stratum": c["stratum"], "got": got,
                                            "rank": score(got, c["expected"]), "empty": not got})
    return rows


def summarise(rows, strata):
    out = {}
    for m, rs in rows.items():
        out[m] = {}
        for s in strata + ["OVERALL"]:
            sel = rs if s == "OVERALL" else [r for r in rs if r["stratum"] == s]
            if sel:
                out[m][s] = {**metrics(sel), "empty": sum(r["empty"] for r in sel)}
    return out


def print_table(summary, strata, title):
    print(f"\n===== {title} =====")
    for s in strata + ["OVERALL"]:
        print(f"\n-- {s}")
        print(f"{'method':16s} {'n':>4s} {'hit@1':>7s} {'hit@3':>7s} {'hit@5':>7s} {'MRR':>6s} {'empty':>6s}")
        for m, by in summary.items():
            x = by.get(s)
            if x:
                print(f"{m:16s} {x['n']:4d} {100*x['hit@1']:6.1f}% {100*x['hit@3']:6.1f}% "
                      f"{100*x['hit@5']:6.1f}% {x['MRR']:6.3f} {x['empty']:6d}")


def evaluate():
    M = Methods()
    print("naive index:", M.naive_meta)
    os.makedirs(OUT_DIR, exist_ok=True)

    # auto-gen set
    lines = open("data/gold_autogen.jsonl").read().splitlines()
    ag = [json.loads(l) for l in lines[1:]]
    for c in ag:
        c["stratum"] = c["kind"]
    ag_strata = ["code", "description", "paraphrase"]
    ag_rows = run_set(M, ag, extra_gate_off=True)
    ag_sum = summarise(ag_rows, ag_strata)
    print_table(ag_sum, ag_strata, f"AUTO-GEN ({len(ag)} cases)")

    # DEV (gold v2.2) - TEST is spent and deliberately excluded
    gold = json.load(open("data/gold_v2.json"))
    dev = [q for q in gold["queries"] if q["split"] == "DEV"]
    ranked = [dict(q, stratum=q["mode"]) for q in dev
              if q["mode"] in ("exact_code", "near_duplicate", "symptom")]
    dev_strata = ["exact_code", "near_duplicate", "symptom"]
    dev_rows = run_set(M, ranked, extra_gate_off=True)
    dev_sum = summarise(dev_rows, dev_strata)
    print_table(dev_sum, dev_strata, f"DEV ranked ({len(ranked)} queries)")

    # DEV out-of-scope: a method "refuses" only by returning nothing
    oos = [q for q in dev if q["mode"] == "out_of_scope"]
    oos_res = {}
    for m in METHODS:
        empty = 0
        for q in oos:
            qv = M.np.asarray(M.R.model.encode([q["query"]], normalize_embeddings=True)[0],
                              dtype="float32")
            empty += not getattr(M, m)(q["query"], qv)
        oos_res[m] = {"returned_nothing": empty, "n": len(oos)}
    print("\nDEV out-of-scope returning nothing:", oos_res)

    # DEV system_group: only the hybrid router has a grouping mode
    grp = [q for q in dev if q["mode"] == "system_group"]
    grp_res = {}
    for m in METHODS:
        ok = 0
        for q in grp:
            if m == "hybrid":
                out = M.R.retrieve(q["query"], k=K)
                ok += out["mode"] == "system_group" and \
                    {i["record"]["code_full"] for i in out["results"]} == set(q["expected"])
            # fixed top-5 methods cannot return a complete group larger than 5
        grp_res[m] = {"complete": ok, "n": len(grp),
                      "group_sizes": [len(q["expected"]) for q in grp]}
    print("DEV system_group complete:", grp_res)

    # pairwise win/tie/loss of hybrid vs each baseline (per query, by reciprocal rank)
    def wtl(rows):
        rr = lambda r: 1.0 / r["rank"] if r["rank"] else 0.0
        res = {}
        for m in METHODS[:-1]:
            by = {}
            for h, b in zip(rows["hybrid"], rows[m]):
                s = by.setdefault(h["stratum"], {"hybrid_better": 0, "tie": 0, "baseline_better": 0})
                d = rr(h) - rr(b)
                s["hybrid_better" if d > 0 else "baseline_better" if d < 0 else "tie"] += 1
            res[m] = by
        return res

    ag_wtl, dev_wtl = wtl(ag_rows), wtl(dev_rows)
    print("\nAUTO-GEN hybrid vs baseline (win/tie/loss by reciprocal rank):")
    print(json.dumps(ag_wtl, indent=1))
    print("DEV hybrid vs baseline:")
    print(json.dumps(dev_wtl, indent=1))

    dev_misses = {m: [{"id": r["id"], "stratum": r["stratum"], "rank": r["rank"], "got": r["got"]}
                      for r in rows if r["rank"] != 1]
                  for m, rows in dev_rows.items()}
    json.dump({"naive_index": M.naive_meta,
               "autogen": {"summary": ag_sum, "win_tie_loss": ag_wtl},
               "dev": {"summary": dev_sum, "win_tie_loss": dev_wtl, "out_of_scope": oos_res,
                       "system_group": grp_res, "non_top1": dev_misses}},
              open(f"{OUT_DIR}/results.json", "w"), indent=1)
    json.dump({m: [{k: r[k] for k in ("id", "stratum", "rank", "got")} for r in rows]
               for m, rows in ag_rows.items()},
              open(f"{OUT_DIR}/autogen_rows.json", "w"))
    print(f"\nwrote {OUT_DIR}/results.json, {OUT_DIR}/autogen_rows.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build-naive", "eval"])
    a = ap.parse_args()
    build_naive() if a.cmd == "build-naive" else evaluate()


if __name__ == "__main__":
    main()
