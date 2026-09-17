"""
Phase 9.2 — auto-generated evaluation set: data/gold_autogen.jsonl

    PYTHONPATH=src .venv/bin/python scripts/gen_autogen_gold.py

AUTO-GENERATED; ground truth = OEM manual; NOT human-expert-verified (technician
verification is future work).

For every DTC record the ground truth is its code_full. Three query kinds:
  (a) code         the code itself, e.g. "P0192-00"                 (coverage test)
  (b) description  the manual's description verbatim                (coverage test,
                   maximal word overlap with the manual - BM25 is favoured by design)
  (c) paraphrase   one deterministic template paraphrase of the description: the
                   "DFC for" boilerplate prefix is dropped, fixed technical synonyms
                   are substituted, and a question frame is added.

Duplicates are merged: a description shared by several codes becomes ONE case whose
`expected` lists every such code (any of them counts as a hit). Nothing here reads a
retrieval result, so the set cannot be tuned against any method.

The synonym table is written independently of the production lexicon
(data/domain_lexicon.json). Overlap is measured, not assumed: the script reports how
many paraphrases still trigger a production lexicon expansion.
"""
from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, "src")

LABEL = ("auto-generated; ground truth = OEM manual; NOT human-expert-verified "
         "(technician verification is future work)")
OUT = "data/gold_autogen.jsonl"

PREFIX = re.compile(r"^\s*(DFC|Diagnostic Fault Check)\s+(for|to report|to)\s+(the\s+)?", re.I)

# Ordered: longer phrases first. Deliberately generic wording. "temp" and "volts" were
# tried first and dropped: both are production lexicon colloquial terms (bias).
SYNONYMS = [
    (r"short circuit to battery", "short to the positive supply"),
    (r"shorted to battery", "short to the positive supply"),
    (r"short circuit to ground", "short to the negative side"),
    (r"shorted to ground", "short to the negative side"),
    (r"open circuit", "broken connection"),
    (r"open load", "broken connection"),
    (r"plausibility", "consistency"),
    (r"implausible|not plausible", "inconsistent"),
    (r"temperature", "heat reading"),
    (r"voltage", "electrical level"),
    (r"signal", "output"),
    (r"\berror\b", "fault"),
    (r"\bcheck\b", "test"),
    (r"too high|\bhigh\b", "above limit"),
    (r"too low|\blow\b", "below limit"),
    (r"upstream", "before the catalyst"),
    (r"downstream", "after the catalyst"),
    (r"\bmaximum\b", "upper"),
    (r"\bminimum\b", "lower"),
]
FRAMES = ["what should I check for {x}?", "troubleshooting help needed: {x}"]


def paraphrase(desc, i):
    x = PREFIX.sub("", desc).strip()
    for pat, rep in SYNONYMS:
        x = re.sub(pat, rep, x, flags=re.I)
    x = re.sub(r"\s+", " ", x).strip().rstrip(".")
    x = x[0].lower() + x[1:] if x[:2] != x[:2].upper() else x
    return FRAMES[i % len(FRAMES)].format(x=x)


def main():
    recs = [json.loads(l) for l in open("data/dtc_records.jsonl")]
    recs.sort(key=lambda r: (r["page"], r["code_full"], r["occurrence"]))

    cases, seen = [], {}

    def add(kind, query, code):
        key = (kind, query.strip().lower())
        if key in seen:
            c = seen[key]
            if code not in c["expected"]:
                c["expected"].append(code)
            return
        c = {"id": None, "kind": kind, "query": query, "expected": [code],
             "provenance": LABEL}
        seen[key] = c
        cases.append(c)

    frame_of = {}                       # one frame per distinct description
    for r in recs:
        d = r["description"].strip()
        frame_of.setdefault(d.lower(), len(frame_of))
        add("code", r["code_full"], r["code_full"])
        add("description", d, r["code_full"])
        add("paraphrase", paraphrase(d, frame_of[d.lower()]), r["code_full"])

    for n, c in enumerate(cases, 1):
        c["id"] = f"ag{n:04d}"
        c["expected"].sort()

    from lexicon import Lexicon
    lex = Lexicon("data/domain_lexicon.json")
    counts = {}
    for c in cases:
        counts.setdefault(c["kind"], {"n": 0, "multi_expected": 0, "lexicon_triggered": 0})
        s = counts[c["kind"]]
        s["n"] += 1
        s["multi_expected"] += len(c["expected"]) > 1
        s["lexicon_triggered"] += bool(lex.expand_query(c["query"])[1])

    meta = {"_meta": {
        "label": LABEL, "phase": "9.2", "n_cases": len(cases), "by_kind": counts,
        "ground_truth": "code_full of the record the query was generated from",
        "notes": ["(a) code and (b) description are high-overlap coverage tests, not "
                  "discriminating tests; (b) reuses manual wording verbatim, which favours "
                  "lexical retrieval.",
                  "The discriminating held-out comparison is the symptom set (gold v2.2).",
                  "lexicon_triggered = paraphrases for which the production lexicon expands "
                  "the query (a potential bias toward the production system)."]}}
    with open(OUT, "w") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(json.dumps(meta, indent=1))
    for c in cases[:6] + [c for c in cases if c["kind"] == "paraphrase"][10:16]:
        print(c["id"], c["kind"], c["expected"], "|", c["query"])


if __name__ == "__main__":
    main()
