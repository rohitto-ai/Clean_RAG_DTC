"""
Phase 12.2 — the third ranker with a real RRF WEIGHT on the symptom ranking.

    from symptom_retriever_w import WeightedSymptomRetriever
    R = WeightedSymptomRetriever(index_dir="index_exp/minilm_sympexp_v2",
                                 symptom_weight=0.5)

In Phase 12.1 `symptom_weight` only decided whether the symptom ranking joined
the fusion at all; any value above zero gave it the same pull as dense and BM25.
Phase 12.2 has to evaluate a HALF-weight variant, so the weight has to reach the
fusion itself: a ranking of weight w contributes w / (k + position) instead of
1 / (k + position). At w = 1.0 that is arithmetically identical to 12.1, which
`scripts/eval_12_2.py --stage check` verifies rather than assumes.

`src/symptom_retriever.py` is covered by the Phase 12.1 freeze, so the hybrid
route is reimplemented here with the weighting rather than edited there. Only the
fusion differs; the pools, the min-max normalisation, the tiebreak and the trace
are the same, and `src/retrieve.py` (the Phase 11.1 freeze) is untouched.

The expansions stay INDEX-ONLY: matched against, never returned or cited.
"""
from __future__ import annotations

from retrieve import POOL_SIZE, RRF_K, minmax
from symptom_retriever import SymptomRetriever


def rrf_fuse_weighted(rankings, norm, k=RRF_K):
    """
    RRF over weighted rankings, with the production tiebreak.

    `rankings` is a list of (name, [ids], weight). Ties break by the summed
    min-max normalised score and then by id, so the order is total.
    """
    score, ranks = {}, {}
    for name, ids, weight in rankings:
        for pos, doc in enumerate(ids, 1):
            score[doc] = score.get(doc, 0.0) + weight / (k + pos)
            ranks.setdefault(doc, {})[name] = pos
    out = [(doc, s, norm.get(doc, 0.0), ranks.get(doc, {})) for doc, s in score.items()]
    out.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return out


class WeightedSymptomRetriever(SymptomRetriever):
    """SymptomRetriever whose symptom ranking carries an explicit RRF weight."""

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

        rankings = [("dense", dense_ids, 1.0), ("bm25", bm25_ids, 1.0)]
        if self.symptom_weight > 0:
            rankings.append(("symptom", sym_ids, self.symptom_weight))
        fused = rrf_fuse_weighted(rankings, norm)

        trace = {
            "dense_pool": len(dense_ids), "bm25_pool": len(bm25_ids),
            "symptom_pool": len(sym_ids),
            "rankers": [n for n, _, _ in rankings],
            "rrf_k": RRF_K,
            "rrf_weights": {n: w for n, _, w in rankings},
            "symptom_expansions": {
                "used": self.symptom_weight > 0,
                "weight": self.symptom_weight,
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
            for name in ("dense", "bm25", "symptom"):
                if name in r:
                    item[f"{name}_rank"] = r[name]
            out.append(item)
        return out, trace
