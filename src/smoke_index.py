"""
Phase 4 smoke tests — sanity only. Full retrieval evaluation is Phase 7.

Checks that the three indexes are present, populated and behaving, without
building any router or fusion (that is Phase 5).
"""
from __future__ import annotations

import json
import resource
from collections import Counter

INDEX_DIR = "index"
COLLECTION = "dtc_records"

# (query, expected top-1, known_hard)
# known_hard: a near-duplicate pair MiniLM alone cannot separate. Recorded as
# XFAIL rather than softened, because the hybrid retrieval in Phase 5 is exactly
# the designed remedy - BM25 separates this pair decisively (see the Phase 4
# report). Do not tune the embedding to make it pass.
DENSE_CASES = [
    ("rail pressure sensor short to ground", "P0192-00", False),
    ("EGR valve stuck closed", "P042F-00", False),
    ("camshaft no signal", "P0340-00", True),
]

results = []


def check(name, ok, detail="", known_hard=False):
    if not ok and known_hard:
        results.append((name, None))
        print(f"  [XFAIL] {name}" + (f" — {detail}" if detail else ""))
        return
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    recs = {f"{r['code_full']}@p{r['page']}#{r['occurrence']}": r
            for r in (json.loads(l) for l in open("data/dtc_records.jsonl"))}

    import chromadb
    client = chromadb.PersistentClient(path=f"{INDEX_DIR}/chroma")
    coll = client.get_collection(COLLECTION)

    print("\n== 1. Chroma vector count ==")
    check("count == 314", coll.count() == 314, f"got {coll.count()}")

    print("\n== 2. Dense top-1 ==")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    for q, expect, hard in DENSE_CASES:
        qv = model.encode([q], normalize_embeddings=True).tolist()
        res = coll.query(query_embeddings=qv, n_results=3)
        top = res["metadatas"][0][0]["code_full"]
        dists = [round(d, 3) for d in res["distances"][0]]
        got3 = [m["code_full"] for m in res["metadatas"][0]]
        note = ""
        if hard and top != expect and expect in got3:
            note = f" | {expect} at rank {got3.index(expect)+1}; BM25 separates this pair"
        check(f'"{q}" -> {expect}', top == expect,
              f"top3={got3} cos_dist={dists}{note}", known_hard=hard)
    del model

    print("\n== 3. Exact-code index ==")
    idx = json.load(open(f"{INDEX_DIR}/code_index.json"))
    full, base = idx["by_code_full"], idx["by_dtc_code"]
    d = full.get("P0180-11", [])
    check("P0180-11 returns BOTH records", len(d) == 2,
          f"pages={[x['page'] for x in d]} occurrences={[x['occurrence'] for x in d]}")
    v = base.get("P0192", [])
    check("base P0192 returns its variant(s)", len(v) >= 1,
          f"{[x['code_full'] for x in v]}")
    v100 = base.get("P0100", [])
    check("base P0100 returns all suffixed variants", len(v100) > 1,
          f"{[x['code_full'] for x in v100]}")
    dups = {k: len(x) for k, x in full.items() if len(x) > 1}
    check("duplicate codes stored as lists, none overwritten",
          dups == {"P0180-11": 2, "P0180-12": 2, "P061C-00": 2}, f"{dups}")

    print("\n== 4. BM25 ==")
    from rank_bm25 import BM25Okapi
    from build_index import tokenize
    blob = json.load(open(f"{INDEX_DIR}/bm25_corpus.json"))
    bm25 = BM25Okapi(blob["corpus"])
    ids = blob["ids"]

    def bm_top(q, k=5):
        sc = bm25.get_scores(tokenize(q))
        order = sorted(range(len(sc)), key=lambda i: -sc[i])[:k]
        return [(ids[i].split("@")[0], round(sc[i], 2)) for i in order if sc[i] > 0]

    a71 = bm_top("A71")
    codes = [c for c, _ in a71]
    check("query 'A71' surfaces P0192-00 / P0193-00",
          "P0192-00" in codes and "P0193-00" in codes, f"{a71}")
    egr = bm_top("EGR", k=6)
    egr_codes = [c for c, _ in egr]
    egr_sys = sum(1 for c in egr_codes
                  if any(r["system"] == "egr" for k, r in recs.items()
                         if r["code_full"] == c))
    check("query 'EGR' surfaces the EGR group", egr_sys >= 4,
          f"{egr_sys}/{len(egr_codes)} of top hits are system=egr: {egr_codes}")
    tok = tokenize("P0192-00 and pin A71")
    check("tokenizer keeps DTC codes and pins intact",
          "p0192-00" in tok and "a71" in tok and "p0192" in tok, f"{tok}")

    print("\n== 5. Metadata filter ==")
    got = coll.get(where={"system": "egr"})
    n_egr = len(got["ids"])
    truth = sum(1 for r in recs.values() if r["system"] == "egr")
    check(f"system=='egr' filter returns {truth}", n_egr == truth, f"got {n_egr}")
    hist = Counter(r["system"] for r in recs.values())
    print("\n  systems histogram:")
    for s, n in hist.most_common():
        print(f"    {s:20s} {n}")

    npass = sum(1 for _, ok in results if ok is True)
    nxfail = sum(1 for _, ok in results if ok is None)
    nfail = sum(1 for _, ok in results if ok is False)
    print(f"\n==== SMOKE: {npass} passed, {nxfail} xfail (known-hard), "
          f"{nfail} failed ====")
    print(f"peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")
    raise SystemExit(main())
