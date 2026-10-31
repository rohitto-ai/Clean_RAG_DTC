"""
Phase 13.1 — conversational pre-filter for non-diagnostic input.

    from conversational import classify, respond
    classify("hi")                      -> "GREETING"
    classify("all good, running fine")  -> "NO_PROBLEM"
    classify("starts fine but black smoke under load") -> None

Why: the demo takes free text, so people type "hi", "thanks" and "no issues, the
truck is healthy". Routing those into retrieval produces a confident-looking list
of fault codes for a vehicle that has no fault, which is the worst failure mode
this project has. A short rule-based answer is both more honest and more useful.

DESIGN LAW: decide by rule, phrase by model. Nothing here is a model: every
decision is a regex or a set membership test, and the three replies are fixed
strings. No language model is consulted, so the filter cannot invent a diagnosis.

SAFETY POSTURE: this filter sits in FRONT of routing, so a false positive silently
swallows a real fault report - far worse than a false negative, which merely sends
a pleasantry through the normal pipeline and gets a refusal. Every rule is
therefore written to fail CLOSED (return None when unsure):

  * GREETING / THANKS fire only when the WHOLE query is pleasantry. One unknown
    word ("hi, engine knocking at full load") and the filter stands down.
  * NO_PROBLEM needs an explicit healthy phrase AND no problem signal of any kind:
    no code, no contrast word, no negated action, no symptom term.
  * Healthy phrases are MASKED OUT before the problem scan, because they contain
    words that are themselves problem signals - "no warning" holds "warning" and
    "no complaint" holds a negation. Masking is what lets "no warning" pass while
    "no warning light but loses power" is rejected.

Retrieval, the relevance gate, the indexes and the records are untouched: this
module only decides whether to call them at all.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# vocabulary - the whole query must consist of these (plus punctuation)
# --------------------------------------------------------------------------
GREETING_WORDS = {"hi", "hello", "hey", "good_morning", "good_afternoon", "good_evening",
                  "good_day", "greetings"}
THANKS_WORDS = {"thanks", "thank_you", "thankyou", "ok", "okay", "great", "bye",
                "goodbye", "cheers", "thx"}
# words that carry no content of their own and so may appear alongside a pleasantry
FILLER_WORDS = {"a", "lot", "very", "much", "so", "there", "all", "you", "again",
                "then", "and", "the", "for", "it", "that", "is", "im", "i", "am",
                "we", "my", "friend", "team", "sir", "madam", "mate", "please"}

MULTIWORD = [("good morning", "good_morning"), ("good afternoon", "good_afternoon"),
             ("good evening", "good_evening"), ("good day", "good_day"),
             ("thank you", "thank_you")]

# --------------------------------------------------------------------------
# NO_PROBLEM - an explicit statement that the vehicle is healthy
# --------------------------------------------------------------------------
HEALTHY_RE = re.compile(
    r"\bno\s+issues?\b|\bno\s+problems?\b|\bno\s+faults?\b|\bnothing\s+wrong\b|"
    r"\bno\s+complaints?\b|\bno\s+warnings?\b|\ball\s+good\b|\ball\s+fine\b|"
    r"\bworking\s+(?:fine|normally|properly|ok|okay)\b|"
    r"\brunning\s+(?:fine|smoothly|normally|properly|ok|okay)\b|"
    r"\bstarts\s+fine\b|\bstarting\s+fine\b|\bhealthy\b|\ball\s+ok(?:ay)?\b",
    re.I)

# a fault code, in any of the shapes the router accepts
CODE_RE = re.compile(r"\b[PUBC]\s?[0-9]{3}[0-9A-F]\b|\b(?:spn|fmi)\b\s*[:#]?\s*\d*", re.I)

# a contrast word turns a healthy statement into a fault report
CONTRAST_RE = re.compile(
    r"\bbut\b|\bexcept\b|\bhowever\b|\balthough\b|\bthough\b|\bsometimes\b|"
    r"\boccasionally\b|\bonly\s+when\b|\bapart\s+from\b|\bother\s+than\b|"
    r"\bunless\b|\bwhereas\b", re.I)

# a negated action, once the healthy phrases are masked out
NEGATION_RE = re.compile(
    r"\bnot\b|\bwon'?t\b|\bdoes\s?n'?t\b|\bdid\s?n'?t\b|\bca\s?n'?t\b|\bcannot\b|"
    r"\bis\s?n'?t\b|\bare\s?n'?t\b|\bwas\s?n'?t\b|\bfails?\b|\bfailed\b|\bfailing\b|"
    r"\bunable\b|\brefuses?\b|\brefusing\b|\bnever\b|\bstopped\b", re.I)

# any symptom or fault term at all
SYMPTOM_RE = re.compile(
    r"\blamps?\b|\blights?\b|\bwarnings?\b|\bsmok(?:e|y|ing)\b|\bnois(?:e|y)\b|"
    r"\bknock(?:ing|s)?\b|\brattl(?:e|ing)\b|\bwhin(?:e|ing)\b|\bsqueal(?:ing|s)?\b|"
    r"\bleak(?:s|ing|age)?\b|\bsmell(?:s|ing)?\b|\bstall(?:s|ing|ed)?\b|"
    r"\bcut\s*out\b|\bcutting\s*out\b|\bmisfir(?:e|ing|es)\b|\bvibrat(?:ion|ing|es)\b|"
    r"\boverheat(?:ing|s|ed)?\b|\bhot\b|\bpower\s*loss\b|\blos(?:e|es|ing)\s+power\b|"
    r"\bweak\b|\bslow\b|\bhard\b|\berrors?\b|\bfaults?\b|\bcodes?\b|\balarms?\b|"
    r"\bderat(?:e|es|ing|ion)\b|\blimp\b|\bjerk(?:s|ing|y)?\b|\brough\b|\bsurg(?:e|ing)\b|"
    r"\bblack\b|\bwhite\b|\bblue\b|\bcrank(?:s|ing)?\s+but\b", re.I)

RESPONSES = {
    "GREETING": "Hello! Describe a symptom, enter a P-code (e.g. P0192-00), or give an "
                "SPN/FMI pair.",
    "THANKS": "You're welcome. Ask again whenever a fault code or symptom appears.",
    "NO_PROBLEM": "Good to hear the vehicle is healthy - no fault lookup is needed. If a "
                  "warning lamp or a symptom appears, describe it or enter the code.",
}

DECISION = "conversational"


def _tokens(query):
    """Lowercase, fold the fixed multi-word pleasantries, split on non-letters."""
    s = query.lower()
    for phrase, token in MULTIWORD:
        s = s.replace(phrase, token)
    return [t for t in re.split(r"[^a-z_]+", s) if t]


def _pleasantry_only(query):
    """
    GREETING / THANKS. The whole query must be pleasantry: every token is a
    greeting, a thanks/acknowledgement or pure filler. One content word stands the
    filter down.

    Tie-break, applied in this order so it is deterministic: if any thanks or
    acknowledgement word is present the reply is THANKS ("hello and thanks" is an
    acknowledgement), otherwise GREETING. A query of nothing but filler ("all",
    "please") is NOT a pleasantry.
    """
    toks = _tokens(query)
    if not toks:
        return None
    if not all(t in GREETING_WORDS or t in THANKS_WORDS or t in FILLER_WORDS
               for t in toks):
        return None
    if any(t in THANKS_WORDS for t in toks):
        return "THANKS"
    if any(t in GREETING_WORDS for t in toks):
        return "GREETING"
    return None                      # filler only - no pleasantry was actually said


def _problem_signals(query):
    """
    Every problem signal in the query, with the healthy phrases masked out first.

    Masking matters: "no warning" is a healthy phrase that contains the symptom
    term "warning", and "no complaint" contains a negation. Scanning the raw text
    would reject every healthy statement; scanning the masked remainder rejects
    only statements that say something ELSE as well.
    """
    found = []
    if CODE_RE.search(query):
        found.append("fault code or SPN/FMI reference")
    rest = HEALTHY_RE.sub(" ", query)
    if CONTRAST_RE.search(rest):
        found.append("contrast word")
    if NEGATION_RE.search(rest):
        found.append("negated action")
    if SYMPTOM_RE.search(rest):
        found.append("symptom or fault term")
    return found


def classify(query):
    """
    GREETING | THANKS | NO_PROBLEM | None, by rule only.

    PRECEDENCE: the pleasantry test runs first, so a bare "ok" or "all ok" is an
    acknowledgement (THANKS) rather than a statement about the vehicle, while
    "all ok with the truck" carries a content word and so reaches the NO_PROBLEM
    rule. Both replies are non-diagnostic, so nothing unsafe turns on the order;
    it is fixed here only so the behaviour is defined rather than incidental.

    None means "not conversational - run the normal pipeline", and is the answer
    whenever anything is ambiguous.
    """
    if not query or not query.strip():
        return None
    p = _pleasantry_only(query)
    if p:
        return p
    if HEALTHY_RE.search(query) and not _problem_signals(query):
        return "NO_PROBLEM"
    return None


def respond(query):
    """
    The fixed reply for a conversational query, or None.

    Returns a dict shaped for the API: the label, the fixed message, and the
    reasons, so the "Why this answer?" panel can show the rule that fired.
    """
    label = classify(query)
    if label is None:
        return None
    return {
        "mode": DECISION,
        "conversational": label,
        "message": RESPONSES[label],
        "decision": DECISION,
        "reasons": _reasons(label, query),
    }


def _reasons(label, query):
    if label in ("GREETING", "THANKS"):
        return [f"the whole query is a {label.lower()} / acknowledgement, with no symptom, "
                f"code or fault term in it"]
    healthy = sorted({m.group(0).strip().lower() for m in HEALTHY_RE.finditer(query)})
    return [f"the query states the vehicle is healthy ({', '.join(healthy)})",
            "no fault code, contrast word, negated action or symptom term is present"]
