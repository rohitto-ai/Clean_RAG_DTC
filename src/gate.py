"""
Relevance gate v2 (Phase 8.3, limitation L3) — two independent, interpretable
reasons to refuse a query:

  (a) LOW RETRIEVAL SIGNAL   nothing in the manual is similar enough
                             (dense_sim < dense_min AND bm25_max < bm25_min)
  (b) NON-DIAGNOSTIC INTENT  the query is about pricing / purchasing / scheduling /
                             warranty / comfort rather than a fault: at least one
                             intent term, NO diagnostic cue, NO DTC code

A query passes only if it clears (a) and does not trip (b).

Dense similarity is the EXACT brute-force max over all stored vectors
(Retriever.exact_max_sim) - a threshold must never depend on approximate search.

The gate is a CONFIG (data/gate_c4b.json), bound to the index it was calibrated
on. ADOPTED as the production default in Phase 8.5: answer.is_relevant() uses it
unless gate=None (legacy v1) is passed explicitly.
"""
from __future__ import annotations

import json
import re

from retrieve import DTC_CODE_RE


def _has(phrase, text):
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"s?(?![a-z0-9])",
                     text.lower()) is not None


class Gate:
    def __init__(self, config_path):
        cfg = json.load(open(config_path))
        self.config_path = config_path
        self.dense_min = float(cfg["dense_min"])
        self.bm25_min = float(cfg["bm25_min"])
        self.index_dir = cfg.get("calibrated_on_index")
        self.intent_enabled = bool(cfg.get("intent_filter", True))
        st = json.load(open(cfg["intent_stoplist"]))
        self.intents = {cat: [e["term"] for e in terms] for cat, terms in st["intents"].items()}
        self.cues = st["diagnostic_cues"]

    def intent(self, query):
        hits = {cat: [t for t in terms if _has(t, query)] for cat, terms in self.intents.items()}
        hits = {c: t for c, t in hits.items() if t}
        cues = [c for c in self.cues if _has(c, query)]
        has_code = DTC_CODE_RE.search(query) is not None
        dominant = bool(hits) and not cues and not has_code
        return {"intent_hits": hits, "diagnostic_cues": cues,
                "has_dtc_code": has_code, "non_diagnostic_dominant": dominant}

    def decide(self, retriever, query):
        dense_sim = retriever.exact_max_sim(query)
        scores = retriever.bm25.get_scores(retriever._tokenize(query))
        bm25_max = float(max(scores)) if len(scores) else 0.0
        low_signal = dense_sim < self.dense_min and bm25_max < self.bm25_min
        it = self.intent(query) if self.intent_enabled else {"non_diagnostic_dominant": False}
        reasons = []
        if low_signal:
            reasons.append("low_retrieval_signal")
        if it["non_diagnostic_dominant"]:
            reasons.append("non_diagnostic_intent")
        return (not reasons), {
            "dense_sim": round(dense_sim, 4), "bm25_max": round(bm25_max, 2),
            "dense_min": self.dense_min, "bm25_min": self.bm25_min,
            "refusal_reasons": reasons, "intent": it}


def audit_stoplist(stoplist_path="data/intent_stoplist.json",
                   records_path="data/dtc_records.jsonl"):
    """Automated safety rule: no intent term may occur in manual fault text."""
    st = json.load(open(stoplist_path))
    texts = []
    for line in open(records_path):
        r = json.loads(line)
        texts += [r["description"], r.get("effect") or ""]
        texts += list(r.get("cause") or []) + list(r.get("checkpoints") or [])
    collisions = {}
    for cat, terms in st["intents"].items():
        for e in terms:
            hit = [t for t in texts if _has(e["term"], t)]
            if hit:
                collisions[e["term"]] = hit[:2]
    return collisions
