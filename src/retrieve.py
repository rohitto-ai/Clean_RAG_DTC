"""
Phase 5 — Retrieval: priority-ordered router + Reciprocal Rank Fusion.

No LLM here (that is Phase 6). Returns full DTC records plus a trace explaining
why each result surfaced.

Router priority (first match wins):
  1. exact_code   — a DTC code appears in the query
  2. system_group — explicit grouping intent AND a subsystem keyword
  3. hybrid       — everything else: dense + BM25 fused with RRF

A subsystem keyword WITHOUT grouping intent stays on the hybrid path and is
reported in the trace as a soft signal only. Hard-filtering there would break
specific-fault queries: "EGR valve stuck closed" must return P042F-00, not all
14 EGR records.

TIE-BREAKING (see docs/report/phase5_retrieval.md): equal-weight RRF cannot break
a symmetric rank swap. If two documents exchange ranks 1 and 2 between the two
rankers, their RRF sums are identical *by construction*, for every value of k.
That is exactly the "camshaft no signal" case. Ties are therefore broken by the
summed min-max-normalised ranker scores, which restores the magnitude information
that ranking discards - dense is 0.011 cosine apart there (noise) while BM25 is
54% apart (decisive).
"""
from __future__ import annotations

import json
import os
import re

INDEX_DIR = "index"
RECORDS = "data/dtc_records.jsonl"
COLLECTION = "dtc_records"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

RRF_K = 60          # RRF damping constant
POOL_SIZE = 50      # candidates taken from each ranker
DEFAULT_TOP_K = 5

DTC_CODE_RE = re.compile(r"\b([PUBC]\d[0-9A-F]{2,3})(-([0-9A-F]{2}))?\b", re.I)

GROUPING_INTENT_RE = re.compile(
    r"\b(all|list|every|each)\b"
    r"|\brelated to\b"
    r"|\b(what|which)\b[^?]*\b(faults?|codes?|dtcs?|errors?|issues?)\b",
    re.I)

# Query-side subsystem keywords, most specific first. These map a user's words
# onto the `system` tag assigned in Phase 1; they are not the same patterns,
# which run against manual descriptions.
SYSTEM_KEYWORDS = [
    ("scr_def",            r"\bscr\b|\bdef\b|urea|adblue|reductant"),
    ("dpf_regen",          r"\bdpf\b|particulate|soot|regenerat|\bdoc\b"),
    ("exhaust_throttle",   r"exhaust throttle|\betv\b"),
    ("egr",                r"\begr\b|exhaust gas recirc"),
    ("rail_pressure",      r"rail pressure|fuel rail"),
    ("injector",           r"injector"),
    ("turbo_boost",        r"turbo|boost|charge air|waste ?gate"),
    ("engine_position",    r"camshaft|crankshaft|cam sensor|crank sensor"),
    ("fuel_supply",        r"fuel pump|metering unit|fuel supply|pressure relief|"
                           r"fuel filter|water in fuel"),
    ("coolant",            r"coolant|engine temp"),
    ("intake_air",         r"intake air|air mass|mass air|\bmaf\b|\biat\b|ambient temp"),
    ("pedal_clutch_brake", r"pedal|clutch|brake|accelerator"),
    ("vehicle_speed",      r"vehicle speed"),
    ("can_network",        r"can bus|\bcan\b network"),
    ("o2_exhaust",         r"oxygen|lambda|\bo2\b|exhaust temp|\bnox\b"),
    ("level2_monitoring",  r"torque monitoring|energizing time|level 2"),
    ("electrical",         r"battery|relay|short circuit|open circuit"),
    ("ecu_internal",       r"\becu\b|\bems\b|fccu"),
    ("sensor_generic",     r"\bsensor\b"),
]


def detect_code(query):
    """(code_full, base_code) - either may be None."""
    m = DTC_CODE_RE.search(query)
    if not m:
        return None, None
    base = m.group(1).upper()
    return (f"{base}-{m.group(3).upper()}" if m.group(3) else None), base


def detect_system(query):
    for name, pat in SYSTEM_KEYWORDS:
        if re.search(pat, query, re.I):
            return name
    return None


def detect_grouping_intent(query):
    return bool(GROUPING_INTENT_RE.search(query))


def minmax(values):
    lo, hi = min(values), max(values)
    span = hi - lo
    return [1.0 if span == 0 else (v - lo) / span for v in values]


def rrf_fuse(dense_ids, bm25_ids, norm_scores, k=RRF_K):
    """
    score(d) = sum over rankers of 1/(k + rank_d), union of both pools.
    Absence from a ranker contributes nothing.

    Ties are broken by summed normalised ranker scores - see module docstring.
    """
    dr = {d: i + 1 for i, d in enumerate(dense_ids)}
    br = {d: i + 1 for i, d in enumerate(bm25_ids)}
    fused = []
    for doc in set(dr) | set(br):
        s = 0.0
        if doc in dr:
            s += 1.0 / (k + dr[doc])
        if doc in br:
            s += 1.0 / (k + br[doc])
        tiebreak = norm_scores.get(doc, 0.0)
        fused.append((doc, s, tiebreak, dr.get(doc), br.get(doc)))
    fused.sort(key=lambda x: (-x[1], -x[2]))
    return fused


class Retriever:
    def __init__(self, index_dir=INDEX_DIR, records=RECORDS, verbose=False):
        self.records = {}
        for line in open(records):
            r = json.loads(line)
            self.records[f"{r['code_full']}@p{r['page']}#{r['occurrence']}"] = r

        self.code_index = json.load(open(os.path.join(index_dir, "code_index.json")))

        blob = json.load(open(os.path.join(index_dir, "bm25_corpus.json")))
        self.bm25_ids = blob["ids"]
        from rank_bm25 import BM25Okapi
        self.bm25 = BM25Okapi(blob["corpus"])

        import chromadb
        client = chromadb.PersistentClient(path=os.path.join(index_dir, "chroma"))
        self.coll = client.get_collection(COLLECTION)

        # Exact vector matrix for threshold decisions. Chroma's HNSW is
        # APPROXIMATE, and early evaluation runs returned different top-1
        # distances for the same query while the embeddings were byte-identical
        # across processes. Ranking tolerates that; a threshold does not. At
        # 314 x 384 floats (~482 KB) an exact dot product is trivially cheap, so
        # the relevance gate never depends on approximate search.
        import numpy as _np
        _all = self.coll.get(include=["embeddings"])
        self.vec_ids = _all["ids"]
        self.vectors = _np.asarray(_all["embeddings"], dtype="float32")

        # One model, loaded once and kept resident for the service lifetime.
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(MODEL_NAME, device="cpu")
        if verbose:
            print(f"Retriever ready: {len(self.records)} records, "
                  f"{self.coll.count()} vectors")

    # ---------------- helpers -------------------------------------------
    def _embed(self, query):
        return self.model.encode([query], normalize_embeddings=True).tolist()

    def exact_max_sim(self, query):
        """Exact (brute-force) max cosine similarity over all records."""
        import numpy as np
        qv = np.asarray(self._embed(query), dtype="float32")[0]
        if self.vectors.size == 0:
            return 0.0
        return float((self.vectors @ qv).max())

    def _rec(self, rid):
        return self.records[rid]

    def _tokenize(self, text):
        from build_index import tokenize
        return tokenize(text)

    # ---------------- router branches -----------------------------------
    def _exact(self, code_full, base, k):
        trace = {"matched_code_full": code_full, "matched_base_code": base}
        refs = []
        if code_full and code_full in self.code_index["by_code_full"]:
            refs = self.code_index["by_code_full"][code_full]
            trace["lookup"] = "by_code_full"
        elif base and base in self.code_index["by_dtc_code"]:
            refs = self.code_index["by_dtc_code"][base]
            trace["lookup"] = "by_dtc_code (base; all suffix variants)"
        else:
            trace["lookup"] = "no match in either code index"
        trace["n_matches"] = len(refs)
        results = [{"record": self._rec(x["id"]), "score": 1.0} for x in refs]
        return results, trace

    def _system_group(self, system, query, k):
        got = self.coll.get(where={"system": system})
        n = len(got["ids"])
        trace = {"system": system, "group_size": n,
                 "ranked_by": "dense cosine within the metadata filter"}
        if n == 0:
            return [], trace
        res = self.coll.query(query_embeddings=self._embed(query),
                              n_results=n, where={"system": system})
        out = []
        for rank, (rid, dist) in enumerate(
                zip(res["ids"][0], res["distances"][0]), 1):
            out.append({"record": self._rec(rid), "score": round(1.0 - dist, 4),
                        "dense_rank": rank})
        return out, trace

    def _hybrid(self, query, k, soft_system):
        # dense pool
        res = self.coll.query(query_embeddings=self._embed(query),
                              n_results=min(POOL_SIZE, self.coll.count()))
        dense_ids = res["ids"][0]
        dense_sims = [1.0 - d for d in res["distances"][0]]

        # bm25 pool
        scores = self.bm25.get_scores(self._tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:POOL_SIZE]
        order = [i for i in order if scores[i] > 0]
        bm25_ids = [self.bm25_ids[i] for i in order]
        bm25_vals = [float(scores[i]) for i in order]

        # normalised scores per ranker, summed - the tiebreak signal
        norm = {}
        if dense_sims:
            for rid, v in zip(dense_ids, minmax(dense_sims)):
                norm[rid] = norm.get(rid, 0.0) + v
        if bm25_vals:
            for rid, v in zip(bm25_ids, minmax(bm25_vals)):
                norm[rid] = norm.get(rid, 0.0) + v

        fused = rrf_fuse(dense_ids, bm25_ids, norm)
        trace = {
            "dense_pool": len(dense_ids),
            "bm25_pool": len(bm25_ids),
            "union_pool": len(fused),
            "rrf_k": RRF_K,
            "soft_system_signal": soft_system,
            "fused_top": [
                {"code": self._rec(d)["code_full"], "rrf": round(s, 6),
                 "dense_rank": dr, "bm25_rank": br, "tiebreak": round(tb, 4)}
                for d, s, tb, dr, br in fused[:max(k, 5)]],
        }
        out = []
        for doc, s, tb, dr, br in fused[:k]:
            item = {"record": self._rec(doc), "score": round(s, 6)}
            if dr is not None:
                item["dense_rank"] = dr
            if br is not None:
                item["bm25_rank"] = br
            out.append(item)
        return out, trace

    # ---------------- public --------------------------------------------
    def retrieve(self, query, k=DEFAULT_TOP_K):
        code_full, base = detect_code(query)
        system = detect_system(query)
        grouping = detect_grouping_intent(query)

        base_trace = {"query": query, "detected_code": code_full or base,
                      "detected_system": system, "grouping_intent": grouping}

        if code_full or base:
            results, t = self._exact(code_full, base, k)
            mode = "exact_code"
            if not results:
                # The code regex can match a non-code token of the same shape -
                # a connector id like C001, say. Returning nothing would be a
                # dead end, so fall back to hybrid rather than fail closed.
                hyb, ht = self._hybrid(query, k, system)
                results, mode = hyb, "hybrid"
                t = {**t, **ht,
                     "fallback": f"exact_code found 0 records for "
                                 f"{code_full or base!r}; fell back to hybrid"}
        elif grouping and system:
            results, t = self._system_group(system, query, k)
            mode = "system_group"
        else:
            results, t = self._hybrid(query, k, system)
            mode = "hybrid"
            if system:
                t["note"] = ("subsystem detected but intent is not grouping - "
                             "kept hybrid, system is a soft signal only")

        return {"mode": mode, "results": results, "trace": {**base_trace, **t}}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")
    r = Retriever(verbose=True)
    q = " ".join(sys.argv[1:]) or "rail pressure sensor short to ground"
    out = r.retrieve(q)
    print(f"\nmode={out['mode']}  n={len(out['results'])}")
    for i, item in enumerate(out["results"], 1):
        rec = item["record"]
        print(f"  {i}. {rec['code_full']:10s} {rec['description'][:62]}")
    print(f"\ntrace: {json.dumps(out['trace'], indent=1)[:900]}")
