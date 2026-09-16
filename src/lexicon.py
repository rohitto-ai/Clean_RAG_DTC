"""
Domain lexicon (Phase 8.2, limitation L1): colloquial technician vocabulary ->
the manual's formal ECU terminology. Loaded from data/domain_lexicon.json.

Two uses, both deterministic and auditable:
  * record_aliases(record)  - index side. Subsystem-level aliases for the record's
    system + description-triggered synonyms. NEVER from step text: steps are
    shared boilerplate, and aliasing them would re-collapse near-duplicates.
  * expand_query(query)     - query side. Appends the manual terms of every
    colloquial phrase found in the query.

`provenance_filter` lets an evaluation drop entries by provenance or by the
computed matches_test_query flag (the 8.5 ablation).
"""
from __future__ import annotations

import json
import re

LEXICON_PATH = "data/domain_lexicon.json"


def _has(phrase, text):
    """Word-boundary, case-insensitive phrase match; tolerates a plural 's'."""
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"s?(?![a-z0-9])",
                     text.lower()) is not None


class Lexicon:
    def __init__(self, path=LEXICON_PATH, exclude_provenance=(), exclude_test_matching=False,
                 gold_path="data/gold_v2.json"):
        data = json.load(open(path))
        self.path, self.version = path, data.get("version")
        self.system_aliases = dict(data["system_aliases"])
        self.term_synonyms = list(data["term_synonyms"])
        self.excluded = []

        if exclude_test_matching:
            test_q = [q["query"] for q in json.load(open(gold_path))["queries"]
                      if q["split"] == "TEST"]
        keep_sys, keep_terms = {}, []
        for name, e in self.system_aliases.items():
            drop = e["provenance"] in exclude_provenance or (
                exclude_test_matching and any(_has(c, t) for c in e["colloquial"] for t in test_q))
            (self.excluded.append(f"system:{name}") if drop else keep_sys.__setitem__(name, e))
        for e in self.term_synonyms:
            drop = e["provenance"] in exclude_provenance or (
                exclude_test_matching and any(_has(c, t) for c in e["colloquial"] for t in test_q))
            (self.excluded.append(f"term:{e['manual'][0]}") if drop else keep_terms.append(e))
        self.system_aliases, self.term_synonyms = keep_sys, keep_terms

    # ---------------- index side ----------------
    def record_aliases(self, rec):
        out = []
        sa = self.system_aliases.get(rec["system"])
        if sa:
            out += sa["colloquial"]
        desc = rec["description"]
        for e in self.term_synonyms:
            if e.get("systems") and rec["system"] not in e["systems"]:
                continue
            if any(_has(m, desc) for m in e["manual"]):
                out += e["colloquial"]
        seen, uniq = set(), []
        for a in out:
            if a not in seen:
                seen.add(a)
                uniq.append(a)
        return uniq

    # ---------------- query side ----------------
    def expand_query(self, query):
        """Returns (expanded_query, matched_colloquial_terms)."""
        added, matched = [], []
        entries = [(c, e["manual"]) for e in self.system_aliases.values() for c in e["colloquial"]]
        entries += [(c, e["manual"]) for e in self.term_synonyms for c in e["colloquial"]]
        for c, manual in sorted(entries, key=lambda x: -len(x[0])):
            if _has(c, query):
                matched.append(c)
                added += [m for m in manual if m not in added]
        if not added:
            return query, []
        return f"{query} {' '.join(added)}", matched


def audit(path=LEXICON_PATH, gold_path="data/gold_v2.json"):
    """Computed provenance flags: which entries match DEV / TEST query wording.
    Reads gold query TEXT only - never system output."""
    data = json.load(open(path))
    qs = json.load(open(gold_path))["queries"]
    dev = [q["query"] for q in qs if q["split"] == "DEV"]
    test = [q["query"] for q in qs if q["split"] == "TEST"]
    rows = []
    for name, e in data["system_aliases"].items():
        rows.append((f"system:{name}", e["provenance"], e["colloquial"]))
    for e in data["term_synonyms"]:
        rows.append((f"term:{'/'.join(e['manual'])}", e["provenance"], e["colloquial"]))
    out = []
    for key, prov, colloq in rows:
        md = sorted({c for c in colloq for t in dev if _has(c, t)})
        mt = sorted({c for c in colloq for t in test if _has(c, t)})
        out.append({"entry": key, "provenance": prov,
                    "matches_dev_query": md, "matches_test_query": mt})
    return out
