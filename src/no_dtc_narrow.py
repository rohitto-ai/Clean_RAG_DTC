"""
Phase 11.2 — A-narrow: the narrowed no-DTC-match rule recommended by Phase 11.1.

Phase 11.1 measured the broad rule (`src/no_dtc.py`) and found it declined 13 of
19 queries no DTC covers, but also wrongly declined 6 of 41 queries that DO have
a code. All six wrong declines came from three categories — **smoke colour,
mechanical noise and smell** — where the mechanical language is the *consequence*
of a coded fault: dark smoke is what an air-mass or EGR fault looks like from the
driver's seat. The categories that were reliable were the ones about fluid that
has gone somewhere it should not: leaks, levels, consumption and wear.

A-narrow therefore splits the mechanical categories in two:

  DECLINE   external leak / fluid loss, fluid level / condition, consumption /
            wear  ->  no code list at all, plus an inspection area
  ADVISORY  smoke colour, mechanical noise, smell  ->  the ranked codes ARE
            shown, with the inspection area alongside them as a hint

Electronic evidence (a lamp or message, a gauge, a named sensor or signal, a
fault code, limp/derate, a refusal to run) still overrides a decline entirely.

This module deliberately imports the term tables from `no_dtc` rather than
copying them: the Phase 11.1 freeze covers that file, and it must stay
verifiable. Only the DECISION changes here, never the vocabulary.

    from no_dtc_narrow import detect
    detect("there is a sweet coolant smell near the front")["action"]   # 'decline'
    detect("more dark smoke than usual when pulling away")["action"]    # 'advise'
    detect("rail pressure sensor short to ground")["action"]            # 'retrieve'
"""
from __future__ import annotations

import re

from no_dtc import ADVICE, ELECTRONIC_C, MECHANICAL_C

# "damp mornings" and "wet roads" are WEATHER, not a fluid leak. The broad rule
# never noticed, because those queries declined for other reasons anyway; under
# A-narrow a weather word would wrongly promote a noise complaint (a belt squeal
# on a damp morning) from advisory to a decline. Weather phrases are removed
# before the mechanical scan - and only the mechanical scan.
WEATHER_RE = re.compile(
    r"\b(?:damp|wet)\s+(?:morning|day|night|evening|weather|road|surface|condition)s?\b",
    re.I)

# Categories whose evidence is reliably NOT a coded fault: fluid where it should
# not be, or a level/consumption that has moved. Measured in Phase 11.1: all 13
# correct declines were of this kind.
DECLINE_CATEGORIES = {
    "external leak / fluid loss",
    "fluid level / condition",
    "consumption / wear",
}

# Categories that are just as often the SYMPTOM of a coded fault. These never
# withhold the codes; they add an inspection hint beside them. Measured in Phase
# 11.1: all 6 wrong declines were of this kind.
ADVISORY_CATEGORIES = {
    "smoke colour",
    "mechanical noise",
    "smell",
}

MESSAGE = ("No matching fault code in the 3.3L DTC manual - this looks mechanical; "
           "inspect: {areas}")
HINT = ("These codes are ranked by the manual. The wording also suggests a mechanical "
        "check: {areas}")


def detect(query):
    """
    -> {action, no_dtc_match, advisory, mechanical, electronic, areas, reasons,
        message, hint, advice}

    action is one of:
      'decline'   mechanical evidence of the reliable kind, no electronic
                  evidence -> no codes are shown
      'advise'    only smoke / noise / smell evidence, no electronic evidence ->
                  codes ARE shown, with an inspection hint
      'retrieve'  normal behaviour
    """
    text = query or ""
    mech_text, weather = WEATHER_RE.subn(" ", text)
    decline_hits, advisory_hits, decline_areas, advisory_areas = [], [], [], []
    for cat, items in MECHANICAL_C.items():
        for pat, area in items:
            m = pat.search(mech_text)
            if not m:
                continue
            hit = {"category": cat, "matched": m.group(0).strip().lower(), "area": area}
            if cat in DECLINE_CATEGORIES:
                decline_hits.append(hit)
                if area not in decline_areas:
                    decline_areas.append(area)
            elif cat in ADVISORY_CATEGORIES:
                advisory_hits.append(hit)
                if area not in advisory_areas:
                    advisory_areas.append(area)
            break                       # one hit per category is enough

    elec = []
    for kind, pat in ELECTRONIC_C.items():
        m = pat.search(text)
        if m:
            elec.append({"kind": kind, "matched": m.group(0).strip().lower()})

    if elec:
        action = "retrieve"
    elif decline_hits:
        action = "decline"
    elif advisory_hits:
        action = "advise"
    else:
        action = "retrieve"

    reasons = []
    if decline_hits:
        reasons.append("decline-grade mechanical evidence: "
                       + "; ".join(f"{h['category']} ({h['matched']!r})" for h in decline_hits))
    if advisory_hits:
        reasons.append("advisory-grade mechanical evidence (shown beside the codes, never "
                       "instead of them): "
                       + "; ".join(f"{h['category']} ({h['matched']!r})" for h in advisory_hits))
    if elec:
        reasons.append("electronic evidence present, so the normal search applies: "
                       + "; ".join(f"{e['kind']} ({e['matched']!r})" for e in elec))
    elif not decline_hits and not advisory_hits:
        reasons.append("no mechanical evidence found")
    if weather:
        reasons.append(f"ignored {weather} weather phrase(s) such as 'damp morning' - "
                       f"weather is not a fluid leak")

    areas = decline_areas if action == "decline" else advisory_areas
    return {
        "action": action,
        "no_dtc_match": action == "decline",
        "advisory": action == "advise",
        "mechanical": decline_hits + advisory_hits,
        "electronic": elec,
        "areas": areas,
        "reasons": reasons,
        "message": MESSAGE.format(areas=", ".join(areas)) if action == "decline" else None,
        "hint": HINT.format(areas=", ".join(areas)) if action == "advise" else None,
        "advice": ADVICE if action == "decline" else None,
        "rule": ("decline only on leak / level / consumption evidence; smoke, noise and "
                 "smell advise alongside the codes; any electronic evidence overrides"),
    }


if __name__ == "__main__":
    import sys
    v = detect(" ".join(sys.argv[1:]))
    print(f"action: {v['action']}")
    for r in v["reasons"]:
        print(f"  - {r}")
    print(v["message"] or v["hint"] or "(normal retrieval)")
