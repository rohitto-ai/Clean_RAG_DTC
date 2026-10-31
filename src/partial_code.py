"""
Phase 13.3 / 13.4 — code-shaped input that is not a usable code.

  13.3  an ATTEMPTED but incomplete code: "P10", "P-10", "p 019".
  13.4  an over-long or malformed code token: "P1023473efa234rgddhdhdfgddhy",
        "P99999999", "U0100zzzz". These used to reach symptom search and came
        back with a ranked list of unrelated DTCs.

    from partial_code import detect_partial, candidates, message_for
    detect_partial("P-10")      -> {"letter": "P", "digits": "10", ...}
    detect_partial("cylinder 3 misfire") -> None

WHY. Phase 9.3 found that a code with a digit dropped from the body - `P019`,
`P10`, `P-10` - is not a code the router can resolve, so it fell through to
**symptom retrieval** and came back with a ranked list of unrelated DTCs. 9.3b
closed the 4-digit case (`P019-00` is refused as an unknown code, with a
did-you-mean line), but a 1-3 digit attempt with no sub-code still reaches hybrid
search. A half-typed code is not a symptom, and answering it with a symptom search
is a confident answer to a question nobody asked.

WHAT THIS IS. A pure text rule: given a short query that looks like somebody began
typing a code and stopped, say so and offer candidates **from the code dictionary
only**. Nothing is auto-selected, no retrieval runs, and no model is consulted.

SAFETY. This sits in front of retrieval, so a false positive silently refuses a
real symptom query. Three rules keep it closed:

  * LENGTH. A standalone token, or a query of at most 3 whitespace tokens, is
    considered on its own. A LONGER query is considered only when the partial-code
    token sits directly beside the word "code", "DTC" or "fault" - the user has
    then said what the token is meant to be ("P10 code came up on the dash", "got
    code P019 today"). Without that neighbour a long sentence is never examined,
    so "after 10 km it stalls" and "after 10 km the code light comes on" are left
    alone - the latter has no code-shaped token at all.
  * A REAL DIGIT IS REQUIRED. The body must contain at least one 0-9. Every letter
    in "CAB" is a valid hex digit and C is a code letter, so without this rule the
    word "cab" would be read as an attempted code.
  * 1-3 DIGITS ONLY. Four digits is a well-formed code and belongs to the existing
    paths: exact match, the 9.3b unknown-code refusal, or the base-without-suffix
    clarification. This rule never touches them.
"""
from __future__ import annotations

import re

HEX = "0123456789ABCDEF"
CODE_LETTERS = "PUBC"

# the whole query is the attempt: "P-10", "p 019", "P01-00", "P019-"
_WHOLE_RE = re.compile(
    r"^([PUBC])[\s\-_.]{0,3}([0-9A-F]{1,3})(?:[\s\-_.]{1,3}([0-9A-F]{1,2}))?[\s\-_.]{0,3}$",
    re.I)
# one token inside a short query is the attempt: "code P10"
_TOKEN_RE = re.compile(
    r"^([PUBC])[\-_.]{0,2}([0-9A-F]{1,3})(?:[\-_.]{1,2}([0-9A-F]{1,2}))?[\-_.]{0,2}$", re.I)
# a complete 4-digit body anywhere means this is NOT an incomplete attempt
_FULL_RE = re.compile(r"\b[PUBC][0-9A-F]{4}\b", re.I)

# Phase 13.4: the longest a real code can be is "P0192-00" (8 characters), and a
# code body can only hold hex digits and the separator.
MAX_CODE_LEN = 8
CODE_CHARS = set("0123456789ABCDEF-_.")
TRUNCATE_AT = 20

MAX_TOKENS = 3
# Phase 13.3b: beyond MAX_TOKENS a partial-code token counts only when the user
# said what it is. "P10 code came up on the dash" is an attempted code; "after 10
# km the code light comes on" has no code token at all, and a sentence that merely
# contains a short alphanumeric is not an attempt.
CODE_WORDS = {"code", "codes", "dtc", "dtcs", "fault", "faults"}
MAX_CANDIDATES = 5
MIN_DIGITS_FOR_CANDIDATES = 2


def _has_digit(s):
    return any(c.isdigit() for c in s)


def _full_code_present(query):
    return any(_has_digit(m.group(0)[1:]) for m in _FULL_RE.finditer(query))


def detect_partial(query):
    """
    {"letter", "digits", "sub", "matched", "via"} for an attempted incomplete code,
    else None. Returns None whenever anything is ambiguous.
    """
    if not query or not query.strip():
        return None
    q = query.strip()
    if _full_code_present(q):
        return None                      # a complete code is somebody else's job

    tokens = q.split()
    m = _WHOLE_RE.match(q) if len(tokens) <= MAX_TOKENS else None
    via = "whole query"
    if not m:
        hits = [i for i, t in enumerate(tokens) if _TOKEN_RE.match(t)]
        if len(hits) != 1:
            return None                  # nothing, or more than one - stand down
        i = hits[0]
        if len(tokens) <= MAX_TOKENS:
            via = "single token in a short query"
        else:
            # a long query needs the user to have named the token
            neighbours = [tokens[j].strip(".,;:!?()[]'\"").lower()
                          for j in (i - 1, i + 1) if 0 <= j < len(tokens)]
            near = [w for w in neighbours if w in CODE_WORDS]
            if not near:
                return None
            via = f"token adjacent to {near[0]!r} in a long query"
        m = _TOKEN_RE.match(tokens[i])

    letter, digits, sub = m.group(1).upper(), m.group(2).upper(), m.group(3)
    if not _has_digit(digits):
        return None                      # "CAB" is a word, not a code attempt
    return {"letter": letter, "digits": digits, "sub": (sub or "").upper() or None,
            "matched": m.group(0), "via": via}


_GARBAGE_START_RE = re.compile(r"^([PUBC])\d", re.I)


def _garbage_token(token):
    """
    The token, stripped of trailing punctuation, if it is code-SHAPED but cannot be
    a code: it opens with a code letter and a digit, and it is either longer than
    any real code or holds a character a code body cannot contain.
    """
    t = token.strip(".,;:!?()[]'\"")
    if not _GARBAGE_START_RE.match(t):
        return None
    body = t[1:].upper()
    if len(t) <= MAX_CODE_LEN and all(c in CODE_CHARS for c in body):
        return None                      # the right shape and length - not garbage
    return t


def detect_invalid(query):
    """
    The over-long or malformed code token, or None.

    The caller must already have established that the existing 9.3 logic extracts
    NO valid code from the query - that is what keeps "DTC=P0192-00;ts=1230" and
    "P0192-00xyz123abc" (from which a base IS extracted) on their existing paths.
    Scope is the same as Phase 13.3: at most 3 tokens, or the token sits directly
    beside code / DTC / fault.
    """
    if not query or not query.strip():
        return None
    q = query.strip()
    tokens = q.split()
    hits = [i for i, t in enumerate(tokens) if _garbage_token(t)]
    if len(hits) != 1:
        return None
    i = hits[0]
    if len(tokens) > MAX_TOKENS:
        neighbours = [tokens[j].strip(".,;:!?()[]'\"").lower()
                      for j in (i - 1, i + 1) if 0 <= j < len(tokens)]
        near = [w for w in neighbours if w in CODE_WORDS]
        if not near:
            return None
        via = f"token adjacent to {near[0]!r} in a long query"
    else:
        via = "short query"
    token = _garbage_token(tokens[i])
    return {"token": token, "letter": token[0].upper(), "via": via,
            "too_long": len(token) > MAX_CODE_LEN,
            "bad_characters": sorted({c for c in token[1:].upper() if c not in CODE_CHARS})}


def invalid_message(token):
    shown = token if len(token) <= TRUNCATE_AT else token[:TRUNCATE_AT] + "\u2026"
    return (f"'{shown}' is not a valid fault code. "
            f"Codes in this manual look like P0192-00.")


def resolve_invalid(query, by_dtc_code):
    """
    Everything the router needs for an invalid code token, or None.

    If the first five characters happen to be a base code the manual holds
    ("P0192abcdef" -> P0192), its variants are offered; otherwise the format hint
    stands alone. The reported string's prefix, P1023, is NOT in this manual, so
    that case gets the hint only.
    """
    found = detect_invalid(query)
    if found is None:
        return None
    token = found["token"]
    base = token[:5].upper()
    rows, note = [], None
    if len(token) >= 5 and base in by_dtc_code:
        for ref in by_dtc_code[base]:
            rows.append({"code": ref["code_full"], "description": ref["description"],
                         "page": ref["page"]})
        rows = sorted({r["code"]: r for r in rows}.values(), key=lambda r: r["code"])
        note = f"Codes starting with {base}:"
    kept = rows[:MAX_CANDIDATES]
    return {"invalid": found, "message": invalid_message(token),
            "candidates": kept, "candidates_more": max(0, len(rows) - len(kept)),
            "candidates_note": note,
            "more_note": more_note(max(0, len(rows) - len(kept))),
            "candidate_rules": ("the first five characters, when they are a base code this "
                                "manual holds; dictionary only, never auto-selected"),
            "no_candidates_reason": (None if kept else
                                     f"the first five characters ({base}) are not a code base "
                                     f"in this manual, so only the format hint is given")}


def candidates(letter, digits, by_dtc_code, limit=MAX_CANDIDATES):
    """
    ([{code, description, page}], n_more) from the code dictionary ONLY.

    Three deterministic rules, union-ed, de-duplicated, sorted by code:
      (a) codes whose 4-digit part STARTS WITH the digits given;
      (b) the digits zero-padded on the left to 4 ("10" -> "0010");
      (c) codes one digit-INSERTION away (this can only reach a 4-digit part from
          3 given digits, so in practice it is the dropped-digit case).

    Fewer than 2 digits gives no candidates at all: one digit matches a sixteenth
    of the manual, which is a list, not a hint.
    """
    letter, digits = letter.upper(), digits.upper()
    if len(digits) < MIN_DIGITS_FOR_CANDIDATES:
        return [], 0

    bases = set()
    for base in by_dtc_code:
        if base[:1].upper() == letter and base[1:].upper().startswith(digits):
            bases.add(base)                                            # (a)
    padded = letter + digits.zfill(4)
    if padded in by_dtc_code:
        bases.add(padded)                                              # (b)
    for i in range(len(digits) + 1):
        for ch in HEX:
            cand = letter + digits[:i] + ch + digits[i:]
            if len(cand) == 5 and cand in by_dtc_code:
                bases.add(cand)                                        # (c)

    rows = {}
    for base in bases:
        for ref in by_dtc_code[base]:
            rows.setdefault(ref["code_full"], {"code": ref["code_full"],
                                               "description": ref["description"],
                                               "page": ref["page"]})
    out = sorted(rows.values(), key=lambda r: r["code"])
    return out[:limit], max(0, len(out) - limit)


def message_for(query):
    """The fixed sentence, quoting the user's own input."""
    return (f"'{query.strip()}' is not a complete code in this manual. "
            f"Codes look like P0192-00.")


def more_note(n_more):
    return f"{n_more} more - please enter the full code" if n_more else None


def resolve(query, by_dtc_code):
    """
    Everything the router needs, or None: the detection, the message, the capped
    candidate list and the overflow note.
    """
    part = detect_partial(query)
    if part is None:
        return None
    cands, n_more = candidates(part["letter"], part["digits"], by_dtc_code)
    return {"partial": part, "message": message_for(query), "candidates": cands,
            "candidates_more": n_more, "more_note": more_note(n_more),
            "candidate_rules": ("(a) 4-digit part starts with the digits given; "
                                "(b) digits zero-padded left to 4; "
                                "(c) one digit-insertion away. Dictionary only, "
                                "never auto-selected."),
            "no_candidates_reason": (None if cands else
                                     ("fewer than 2 digits were given, so only the format "
                                      "hint is shown" if len(part["digits"]) < 2
                                      else "no dictionary code matches the digits given"))}
