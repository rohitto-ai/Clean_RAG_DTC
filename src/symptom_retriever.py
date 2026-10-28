"""
Phase 12.1 — the third ranker: dense + BM25 + SYMPTOM-dense, fused with RRF.

`SymptomRetriever` subclasses the production `Retriever` and overrides only the
hybrid route. It does not modify `src/retrieve.py`, which is covered by the Phase
11.1 freeze.

    from symptom_retriever import SymptomRetriever
    R = SymptomRetriever(index_dir="index_exp/minilm_sympexp")
    R.retrieve("it loses power on a long climb and the light came on")

The symptom ranker scores a record by the MAX cosine between the query and that
record's own expansions, so one well-matched paraphrase is enough and the others
do not dilute it. The three rankers are then fused with the same RRF the
production system uses, with the same total-order tiebreak.

The expansions are INDEX-ONLY: they are matched against, never returned. A result
carries the record, exactly as the production retriever returns it, so answers,
fix blocks and citations are unchanged.
"""
from __future__ import annotations

import json
import os

from retrieve import POOL_SIZE, RRF_K, Retriever, minmax


def rrf_fuse3(rankings, norm, k=RRF_K):
    """
    RRF over N rankings, with the production tiebreak.

    `rankings` is a list of (name, [ids]); `norm` maps id -> summed min-max
    normalised score across the rankers that retrieved it. Ties break by the
    normalised score and then by id, so the order is total and reproducible.
    """
    score, ranks = {}, {}
    for name, ids in rankings:
        for pos, doc in enumerate(ids, 1):
            score[doc] = score.get(doc, 0.0) + 1.0 / (k + pos)
            ranks.setdefault(doc, {})[name] = pos
    out = [(doc, s, norm.get(doc, 0.0), ranks.get(doc, {})) for doc, s in score.items()]
    out.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return out


class SymptomRetriever(Retriever):
    """Production retriever plus a symptom-expansion ranker on the hybrid route."""

    def __init__(self, index_dir="index_exp/minilm_sympexp", *args,
                 symptom_weight=1.0, **kwargs):
        super().__init__(index_dir, *args, **kwargs)
        # the parent does not keep index_dir, so hold on to it here
        self.index_dir = index_dir
        self.symptom_weight = float(symptom_weight)
        meta_path = os.path.join(index_dir, "symptom_meta.json")
        vec_path = os.path.join(index_dir, "symptom_vectors.npy")
        self.symptom_ready = os.path.exists(meta_path) and os.path.exists(vec_path)
        if not self.symptom_ready:
            raise FileNotFoundError(
                f"{meta_path} not found - build it with scripts/build_symptom_index.py")
        import numpy as np
        meta = json.load(open(meta_path))
        self.exp_owner = meta["owner_ids"]
        self.exp_texts = meta["texts"]
        self.exp_vectors = np.load(vec_path)
        # record id -> the rows of exp_vectors that belong to it
        self.exp_rows = {}
        for row, rid in enumerate(self.exp_owner):
            self.exp_rows.setdefault(rid, []).append(row)

    def symptom_topk(self, query, n):
        """[(record_id, max cosine over its expansions)], best first, id tiebreak."""
        import numpy as np
        qv = np.asarray(self._embed(query), dtype="float32")[0]
        sims = self.exp_vectors @ qv
        best = {}
        for rid, rows in self.exp_rows.items():
            best[rid] = float(max(sims[r] for r in rows))
        order = sorted(best, key=lambda r: (-best[r], r))[:n]
        return [(r, best[r]) for r in order]

    def _top_expansions(self, query, pairs):
        """For the trace: which expansion actually matched, per candidate."""
        if not pairs:
            return []
        import numpy as np
        qv = np.asarray(self._embed(query), dtype="float32")[0]
        out = []
        for rid, v in pairs:
            row = max(self.exp_rows[rid], key=lambda r: float(self.exp_vectors[r] @ qv))
            out.append({"code": self._rec(rid)["code_full"], "similarity": round(v, 4),
                        "expansion": self.exp_texts[row]})
        return out

    def _hybrid(self, query, k, soft_system):
        expanded, matched = query, []
        if self.lexicon is not None and self.expand != "none":
            expanded, matched = self.lexicon.expand_query(query)
        dense_q = expanded if self.expand == "both" else query
        bm25_q = expanded if self.expand in ("bm25", "both") else query

        n_pool = min(POOL_SIZE, len(self.vec_ids))
        pool = self._exact_dense_topk(dense_q, n_pool)
        dense_ids = [rid for rid, _ in pool]
        dense_sims = [s for _, s in pool]

        scores = self.bm25.get_scores(self._tokenize(bm25_q))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:POOL_SIZE]
        order = [i for i in order if scores[i] > 0]
        bm25_ids = [self.bm25_ids[i] for i in order]
        bm25_vals = [float(scores[i]) for i in order]

        sym = self.symptom_topk(query, n_pool)
        sym_ids = [rid for rid, _ in sym]
        sym_vals = [v for _, v in sym]

        norm = {}
        for ids_, vals in ((dense_ids, dense_sims), (bm25_ids, bm25_vals),
                           (sym_ids, sym_vals)):
            if vals:
                for rid, v in zip(ids_, minmax(vals)):
                    norm[rid] = norm.get(rid, 0.0) + v

        rankings = [("dense", dense_ids), ("bm25", bm25_ids)]
        if self.symptom_weight > 0:
            rankings.append(("symptom", sym_ids))
        fused = rrf_fuse3(rankings, norm)

        trace = {
            "dense_pool": len(dense_ids), "bm25_pool": len(bm25_ids),
            "symptom_pool": len(sym_ids),
            "rankers": [n for n, _ in rankings],
            "rrf_k": RRF_K,
            "symptom_expansions": {
                "used": self.symptom_weight > 0,
                "vectors": len(self.exp_vectors),
                "scoring": "max cosine over a record's own expansions",
                "label": "index-only; expansions are never returned or cited",
                "top_match": self._top_expansions(query, sym[:3]),
            },
            "expansion": {"mode": self.expand, "matched": matched,
                          "expanded_query": expanded if matched else None},
            "soft_system_signal": soft_system,
            "fused_top": [{"code": self._rec(d)["code_full"], "rrf": round(s, 6),
                           "ranks": r} for d, s, _, r in fused[:max(k, 5)]],
        }
        out = []
        for doc, s, _tb, r in fused[:k]:
            item = {"record": self._rec(doc), "score": round(s, 6)}
            if "dense" in r:
                item["dense_rank"] = r["dense"]
            if "bm25" in r:
                item["bm25_rank"] = r["bm25"]
            if "symptom" in r:
                item["symptom_rank"] = r["symptom"]
            out.append(item)
        return out, trace
