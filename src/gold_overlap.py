"""
Word-overlap metric for gold-set authoring (Phase 8.0 rule).

A symptom query must not lean on the manual's own wording, or lexical retrieval
matches it trivially and the metric stops measuring anything. This module is the
single definition of "how much manual vocabulary a query reuses", shared by the
authoring checker and the evaluator report.

    overlap(query, code) = |content(query) & content(description)| / |content(query)|

taken as the MAX over the query's expected codes (the most lenient reading, so the
ceiling is conservative).

content(text):
  * lowercase, split on non-alphanumerics, keep tokens of length >= 2
  * drop ENGLISH function words only - domain words ("sensor", "circuit",
    "signal") are deliberately NOT stopwords; they are exactly the manual nouns a
    query must avoid
  * crude stem: strip one of -ing / -ed / -s, then a trailing -e, so
    cranking/cranked/crank and valve/valves collapse. Crude on purpose: it can
    only merge forms, which makes the ceiling stricter, never looser.
"""
from __future__ import annotations

import json
import re

CEILING = 0.15

STOPWORDS = set("""
a about above after again against all almost also am an and any are as at be
because been before being below between both but by can cannot could did do does
doing down during each else ever every few for from further get gets getting got
had has have having he her here hers him his how i if in into is it its itself
just keep keeps kind let lot me more most much must my no nor not now of off on
once one only or other our out over own quite rather same she should so some such
than that the their them then there these they this those through to too under
until up very was we were what when where whether which while who whom why will
with would yet you your
""".split())


def _stem(w):
    for suf in ("ing", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3 and not w.endswith("ss"):
            w = w[: -len(suf)]
            break
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def content(text):
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(t) for t in toks if len(t) >= 2 and t not in STOPWORDS}


def load_descriptions(path="data/dtc_records.jsonl"):
    desc = {}
    for line in open(path):
        r = json.loads(line)
        desc.setdefault(r["code_full"], set()).update(content(r["description"]))
    return desc


def overlap(query, expected, desc):
    """Returns (score, shared_terms, best_code)."""
    q = content(query)
    if not q or expected == "none":
        return 0.0, set(), None
    best = (0.0, set(), None)
    for code in expected:
        shared = q & desc.get(code, set())
        score = len(shared) / len(q)
        if score > best[0]:
            best = (score, shared, code)
    return best


def symptom_stats(queries, desc):
    rows = [(q, *overlap(q["query"], q["expected"], desc)) for q in queries
            if q["mode"] == "symptom"]
    vals = [r[1] for r in rows]
    return {
        "n": len(vals),
        "mean": sum(vals) / len(vals) if vals else 0.0,
        "zero_overlap": sum(1 for v in vals if v == 0),
        "max": max(vals) if vals else 0.0,
        "over_ceiling": sum(1 for v in vals if v > CEILING),
    }, rows
