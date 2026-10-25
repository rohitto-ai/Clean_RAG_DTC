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

Phase 10.1 adds deterministic QUERY-SIDE REWRITE RULES, enabled only when the
lexicon file declares `"query_rules": true` (v2 does; the v1 production lexicon
does not, so the production path is byte-identical). They run BEFORE alias
expansion, act on the BM25 query only, and never touch the dense query or the
relevance gate:

  R1 cylinder ordinals  "cylinder one", "first cylinder", "no.1 injector"
                        -> the canonical "cylinder <N>" wording that
                        build_index.tokenize() folds into the 8.2b compound
                        token cylinder_<N>. Index and query tokenisation stay
                        IDENTICAL: the rule only produces the digit form the
                        manual already uses, and tokenize() is unchanged.
  R2 valve/switch state negation and implication
                        "refuses to shut" / "will not close" / "stays open"
                        -> the manual's "jammed at open position"
                        "will not open" / "seized shut" / "stays closed"
                        -> the manual's "jammed at closed position"
                        A lexicon maps words, not negation (8.2 limitation);
                        these rules do, explicitly and with a trace.
"""
from __future__ import annotations

import json
import re

LEXICON_PATH = "data/domain_lexicon.json"

# --------------------------------------------------------------------------
# Phase 10.1 R1 - cylinder number words and ordinals
# --------------------------------------------------------------------------
# The manual always writes a DIGIT ("Injector open circuit for cylinder 1"), and
# Phase 8.2b folds "cylinder N" into the single BM25 token cylinder_<N>. A
# technician may write "number one injector" or "the first cylinder", which the
# fold never sees. These rules rewrite such wording to the manual's digit form;
# tokenize() itself is untouched, so index and query tokenisation cannot diverge.
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7, "8th": 8,
}
_NW = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
# "cylinder one" / "cyl. no two" / "cylinder number three"
_CYL_WORD_RE = re.compile(
    r"\b(cylinder|cyl)\s*\.?\s*(?:no\.?\s*|number\s*)?(" + _NW + r")\b", re.I)
# "first cylinder" / "1st injector" / "number one injector"
# NB: "#" is not a word character, so the \b must sit INSIDE the word-prefixed
# alternatives, never in front of the "#" one, or "#2 injector" never matches.
_PREFIX = r"(?:\b(?:no\.?|number)\s*|#\s*)"
_ORD_UNIT_RE = re.compile(
    _PREFIX + r"?\b(" + _NW + r")\s+(cylinder|cyl|injector)\b", re.I)
# "no.1 injector" / "#2 injector" / "injector 3"
_NUM_UNIT_RE = re.compile(_PREFIX + r"(\d{1,2})\s+(cylinder|cyl|injector)\b", re.I)
_UNIT_NUM_RE = re.compile(r"\b(injector)\s+" + _PREFIX + r"?(\d{1,2})\b", re.I)


def normalize_cylinder_words(query):
    """Rewrite cylinder number words / ordinals to the manual's "cylinder <N>".
    Returns (rewritten, trace_steps)."""
    trace = []
    out = query

    def rec(rule, before, after):
        trace.append({"rule": rule, "before": before, "after": after})

    def cyl_word(m):
        n = NUMBER_WORDS[m.group(2).lower()]
        new = f"cylinder {n}"
        rec("R1a_cylinder_number_word", m.group(0), new)
        return new
    out2 = _CYL_WORD_RE.sub(cyl_word, out)
    out = out2

    def ord_unit(m):
        n = NUMBER_WORDS[m.group(1).lower()]
        unit = m.group(2).lower()
        new = f"cylinder {n}" if unit in ("cylinder", "cyl") else f"injector cylinder {n}"
        rec("R1b_ordinal_before_unit", m.group(0), new)
        return new
    out = _ORD_UNIT_RE.sub(ord_unit, out)

    def num_unit(m):
        n, unit = int(m.group(1)), m.group(2).lower()
        new = f"cylinder {n}" if unit in ("cylinder", "cyl") else f"injector cylinder {n}"
        rec("R1c_numbered_unit", m.group(0), new)
        return new
    out = _NUM_UNIT_RE.sub(num_unit, out)

    def unit_num(m):
        n = int(m.group(2))
        new = f"injector cylinder {n}"
        rec("R1d_unit_then_number", m.group(0), new)
        return new
    out = _UNIT_NUM_RE.sub(unit_num, out)
    return out, trace


# --------------------------------------------------------------------------
# Phase 10.1 R2 - valve / switch state negation and implication
# --------------------------------------------------------------------------
# The manual's own wording for a stuck actuator is "jammed at open position" /
# "jammed at closed position" (P042E/P042F, P04A4/P04A5, P22CF-72/-73). These
# pairs are near-duplicates separated ONLY by the words open/closed, so a query
# that expresses the state by negation ("refuses to shut" = stuck OPEN) cannot be
# resolved by word-level aliasing. Each pattern below is an explicit, ordered,
# unit-tested rewrite; the manual phrase is APPENDED, leaving the technician's
# own words in the query for the other aliases to match.
STATE_RULES = [
    # (rule id, pattern, appended manual wording)
    ("R2a_stuck_open", r"refuses?\s+to\s+(?:shut|close)"
                       r"|(?:will\s+not|won'?t|does\s+not|doesn'?t|cannot|can'?t)\s+(?:shut|close)"
                       r"|not\s+(?:shutting|closing)"
                       r"|stays?\s+(?:wide\s+)?open|stuck\s+(?:wide\s+)?open|seized\s+open"
                       r"|jammed\s+open|held\s+open|stuck\s+at\s+open",
     "jammed at open position"),
    ("R2b_stuck_closed", r"refuses?\s+to\s+open"
                         r"|(?:will\s+not|won'?t|does\s+not|doesn'?t|cannot|can'?t)\s+open"
                         r"|not\s+opening"
                         r"|stays?\s+(?:shut|closed)|stuck\s+(?:shut|closed)"
                         r"|seized\s+(?:shut|closed)|jammed\s+(?:shut|closed)|held\s+closed"
                         r"|stuck\s+at\s+closed",
     "jammed at closed position"),
    # The manual does NOT distinguish switch on/off: its only stuck-switch record
    # is "driver demand regeneration button stuck" (P2458-09). Both polarities
    # therefore normalise to the same wording; the trace records which fired.
    ("R2c_switch_stuck_on", r"switch\s+stuck\s+on|switch\s+stays?\s+on"
                            r"|(?:will\s+not|won'?t)\s+switch\s+off"
                            r"|(?:will\s+not|won'?t)\s+turn\s+off|button\s+stuck\s+on",
     "switch stuck button stuck"),
    ("R2d_switch_stuck_off", r"switch\s+stuck\s+off|switch\s+stays?\s+off"
                             r"|(?:will\s+not|won'?t)\s+switch\s+on"
                             r"|(?:will\s+not|won'?t)\s+turn\s+on|button\s+stuck\s+off",
     "switch stuck button stuck"),
]
STATE_RULES = [(rid, re.compile(pat, re.I), add) for rid, pat, add in STATE_RULES]


def rewrite_state(query):
    """Append the manual's jammed/stuck wording implied by a negated state.
    Returns (rewritten, trace_steps). The query text itself is never deleted."""
    trace, added = [], []
    for rid, pat, add in STATE_RULES:
        m = pat.search(query)
        if m:
            trace.append({"rule": rid, "matched": m.group(0), "added": add})
            for tok in add.split("  "):
                if tok not in added:
                    added.append(tok)
    if not added:
        return query, trace
    return query + " " + " ".join(added), trace


def apply_query_rules(query):
    """R1 then R2. Deterministic, order-fixed. Returns (rewritten, trace)."""
    q1, t1 = normalize_cylinder_words(query)
    q2, t2 = rewrite_state(q1)
    return q2, t1 + t2


def _has(phrase, text):
    """Word-boundary, case-insensitive phrase match; tolerates a plural 's'."""
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"s?(?![a-z0-9])",
                     text.lower()) is not None


class Lexicon:
    def __init__(self, path=LEXICON_PATH, exclude_provenance=(), exclude_test_matching=False,
                 gold_path="data/gold_v2.json"):
        data = json.load(open(path))
        self.path, self.version = path, data.get("version")
        # Phase 10.1: query-side rewrite rules run only for a lexicon that asks for
        # them. The v1 production lexicon does not, so its behaviour is unchanged.
        self.query_rules = bool(data.get("query_rules", False))
        self.lexicon_version = data.get("lexicon_version", "v1")
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
    def expand_query(self, query, trace=False):
        """
        Returns (expanded_query, matched_colloquial_terms), or
        (expanded_query, matched, trace_dict) when trace=True.

        With query_rules enabled (v2), the deterministic rewrite rules run FIRST,
        and a manual term already present in the rewritten query is not appended
        again (it would double-count that term in the BM25 query). Both behaviours
        are gated on query_rules, so the v1 production path is byte-identical.
        """
        rule_trace, base = [], query
        if self.query_rules:
            base, rule_trace = apply_query_rules(query)
        added, matched = [], []
        entries = [(c, e["manual"]) for e in self.system_aliases.values() for c in e["colloquial"]]
        entries += [(c, e["manual"]) for e in self.term_synonyms for c in e["colloquial"]]
        for c, manual in sorted(entries, key=lambda x: -len(x[0])):
            if _has(c, base):
                matched.append(c)
                for m in manual:
                    if m in added:
                        continue
                    if self.query_rules and _has(m, base):
                        continue        # already in the query - do not double-count
                    added.append(m)
        out = f"{base} {' '.join(added)}" if added else base
        if trace:
            return out, matched, {"input": query, "after_rules": base,
                                  "rules_fired": rule_trace, "aliases_matched": matched,
                                  "manual_terms_added": added, "expanded": out}
        return out, matched


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
