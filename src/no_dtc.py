"""
Phase 11.1, improvement A — recognise "no matching fault code in this manual".

The Phase 10.6 independent evaluation found the worst failure in the system:
**0 of 19 queries that no DTC covers were declined.** A coolant smell, a belt
squeal, oil wetness and a turbo flutter were each answered with a confident list
of trouble codes. Gate v2 cannot catch these — it refuses only when dense
similarity AND BM25 are both low, and those queries score 0.145-0.496 dense and
11.46-26.05 BM25, because they use real automotive vocabulary. They are in-domain
questions with no DTC answer, which is exactly the workshop case that matters.

THE RULE, in one line: mechanical evidence with no electronic evidence is not a
fault code.

Two terms were deliberately weakened after they fired on queries that DO have a
code: a bare deposit word ("residue", "crust") describes both a leak trace at a
joint and combustion residue inside a DPF, so it no longer declines on its own;
and a reported "warning" of any kind now counts as electronic evidence even
without the word "lamp", because the ECU raised it.

  * MECHANICAL evidence - what a human sees, smells, hears or measures with a
    dipstick: external leaks and fluid loss, smells, smoke colour, noises
    (squeal, rattle, knock, flutter, whistle), fluid-level changes, consumption
    changes, visible wear or damage.
  * ELECTRONIC evidence - what the ECU can see: a warning lamp, a gauge or
    reading, a named sensor or signal, a fault code, limp/derate behaviour, or a
    refusal to start or run.

A query dominated by the first with none of the second gets NO_DTC_MATCH and a
named inspection area. It never gets a code list.

HOW THE TERM LISTS WERE WRITTEN. From general workshop categories - the kinds of
complaint a vehicle owner brings in that an ECU has no sensor for - not from the
wording of any gold row. They are deliberately generic ("squeal", "rattle",
"seep", "weep", "residue") rather than tuned to particular phrasings.

HONEST CAVEAT. The author had already read the independent set while writing the
Phase 10.6 error analysis. Nothing here was copied from it, but prior exposure
cannot be undone, which is precisely why every independent-set number measured
after this point is labelled POST-HOC and optimistic.

    from no_dtc import detect
    verdict = detect("there is a sweet coolant smell near the front after parking")
    verdict["no_dtc_match"]   # True
    verdict["reasons"]        # why, in words
    verdict["areas"]          # what to inspect
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# MECHANICAL EVIDENCE - grouped by workshop category. Each entry is
# (regex, inspection area). The area is what a technician would go and look at.
# --------------------------------------------------------------------------
MECHANICAL = {
    "external leak / fluid loss": [
        (r"\bleak(?:s|ing|ed)?\b", "the leaking joint, hose or housing"),
        (r"\bseep(?:s|ing|age)?\b", "the seeping joint or seal"),
        (r"\bweep(?:s|ing)?\b", "the weeping joint or seal"),
        (r"\bdrip(?:s|ping|ped)?\b", "where the fluid is dripping from"),
        (r"\bwet(?:ness)?\b|\bdamp(?:ness)?\b", "the wet area and the joint above it"),
        (r"\boily film\b|\boil residue\b|\bfresh (?:oil|patch)\b", "the oily joint or seal"),
        (r"\bpuddle\b|\bpooling\b", "under the vehicle, at the source"),
        (r"\bsplit (?:hose|pipe)\b|\bperished\b|\bloose clamp\b", "the hose, pipe and clamps"),
    ],
    "smell": [
        (r"\bsmell(?:s|ing|ed)?\b|\bodou?r\b", "the area the smell comes from"),
        (r"\bfumes?\b", "the area the fumes come from"),
        (r"\bburning smell\b", "for contact between hot parts and trim, belts or wiring"),
    ],
    "smoke colour": [
        (r"\b(?:white|blue|blue-?grey|grey|black|dark|pale)\s+smoke\b", "exhaust smoke colour"),
        (r"\bsmok(?:e|ing|y)\b", "the exhaust and the breather system"),
        (r"\bsoot(?:ing)?\s+(?:up|deposit)\b", "soot deposits"),
    ],
    "mechanical noise": [
        (r"\bsqueal(?:s|ing|ed)?\b|\bsqueak(?:s|ing|y)?\b", "the belt, tensioner and pulleys"),
        (r"\brattl(?:e|es|ing|y)\b", "the rattling component and its mountings"),
        (r"\bknock(?:s|ing)?\b|\bpink(?:s|ing)\b", "the noise source under load"),
        (r"\bflutter(?:s|ing)?\b|\bchuff(?:s|ing)?\b", "the turbo, its hoses and the air path"),
        (r"\bwhistl(?:e|es|ing)\b|\bwhin(?:e|es|ing)\b|\bhiss(?:es|ing)?\b",
         "the air path for a leak or restriction"),
        (r"\bgrind(?:s|ing)\b|\bscrap(?:e|es|ing)\b|\bclunk(?:s|ing)?\b",
         "the noise source and its mountings"),
        (r"\btapp(?:et|ing)\b|\bticking\b", "the valve train"),
        (r"\bvibrat(?:e|es|ion|ing)\b|\bshak(?:e|es|ing)\b|\bjudder(?:s|ing)?\b",
         "mountings, balance and the drivetrain"),
    ],
    "fluid level / condition": [
        (r"\b(?:level|reservoir|tank)\b.{0,24}\b(?:drop(?:s|ping|ped)?|fall(?:s|ing|en)?|"
         r"low(?:er)?|down|up|ris(?:e|es|ing)|above|below)\b", "the fluid level and for leaks"),
        (r"\b(?:drop(?:s|ping|ped)?|fall(?:s|ing|en)?|ris(?:e|es|ing)|creep(?:s|ing|ed)?)\b"
         r".{0,24}\b(?:level|reservoir|tank|dipstick|mark)\b", "the fluid level and for leaks"),
        (r"\bdipstick\b|\bmax(?:imum)? mark\b|\bmin(?:imum)? mark\b", "the oil level and condition"),
        (r"\btopping up\b|\btop(?:ped)? up\b|\bkeeps? needing\b", "consumption and for leaks"),
        (r"\boil smells? (?:like|of) (?:diesel|fuel)\b|\bdilut(?:ed|ion)\b",
         "the oil for fuel dilution"),
        (r"\bmilky\b|\bemulsif(?:ied|ication)\b|\bmayonnaise\b", "the oil for coolant ingress"),
    ],
    "consumption / wear": [
        (r"\busing more (?:diesel|fuel|oil)\b|\b(?:fuel|oil) consumption\b|\bmileage\b|\bmpg\b|"
         r"\bkmpl\b", "fuel or oil consumption and for leaks"),
        (r"\bworn\b|\bwear(?:ing)?\b|\bfray(?:ed|ing)\b|\bcrack(?:ed|ing|s)\b|\bperished\b",
         "the worn or damaged part"),
        (r"\bloose\b|\bplay\b|\bslack\b", "the loose fitting or mounting"),
        (r"\bcorroded\b|\brust(?:y|ed)?\b", "corrosion at the joint or connector"),
    ],
}

# --------------------------------------------------------------------------
# ELECTRONIC EVIDENCE - anything the ECU could actually have recorded. Any one
# of these and the query stays on the normal retrieval path.
# --------------------------------------------------------------------------
ELECTRONIC = {
    # Any reported warning, message or indicator is something the ECU raised, so
    # it counts as electronic evidence even without the word "lamp".
    "warning lamp or message": r"\bwarning\b|\blamp\b|\bcheck engine\b|\bmil\b|"
                               r"\btelltale\b|\bmessage\b|\balert\b|\bindicator\b|"
                               r"\bdash(?:board)? light\b",
    "gauge or reading": r"\bgauge\b|\breading\b|\bneedle\b|\bdisplay\b|\bmessage on\b|"
                        r"\bshows? \d|\breads? (?:high|low|zero)\b",
    "named sensor or signal": r"\bsensor\b|\bsignal\b|\bcircuit\b|\bvoltage\b|\bvolts\b|"
                              r"\bshort(?:ed)? to\b|\bopen circuit\b|\bwiring\b|\bharness\b|"
                              r"\bconnector\b|\bpin\b|\brelay\b|\bfuse\b|\becu\b|\bcan bus\b",
    "fault code": r"\b[pubc]\d[0-9a-f]{2,3}(?:-[0-9a-f]{2})?\b|\bfault code\b|\bdtc\b|"
                  r"\berror code\b|\bcode (?:is|shows|came|appeared)\b",
    "limp / derate": r"\blimp\b|\bderate(?:d|s)?\b|\btorque (?:reduction|limitation)\b|"
                     r"\bpower (?:is )?(?:cut|limited|reduced)\b|\bcreep mode\b|\binducement\b|"
                     r"\bspeed (?:is )?(?:capped|limited)\b",
    "will not run / start": r"\bwon'?t start\b|\bwill not start\b|\bno start\b|\bcuts out\b|"
                            r"\bstalls?\b|\bshuts? down\b|\bdies\b|\bhalts?\b|\bcranks? but\b|"
                            r"\bfails? to start\b",
}

MECHANICAL_C = {cat: [(re.compile(p, re.I), area) for p, area in items]
                for cat, items in MECHANICAL.items()}
ELECTRONIC_C = {k: re.compile(v, re.I) for k, v in ELECTRONIC.items()}

MESSAGE = ("No matching fault code in the 3.3L DTC manual - this looks mechanical; "
           "inspect: {areas}")
ADVICE = "If a warning lamp or a fault code is present, enter the code and ask again."


def detect(query):
    """
    -> {no_dtc_match, mechanical, electronic, areas, reasons, message, advice}

    Deterministic, order-independent and explainable: every element of the
    verdict names the category and the phrase that produced it.
    """
    text = query or ""
    mech, areas = [], []
    for cat, items in MECHANICAL_C.items():
        for pat, area in items:
            m = pat.search(text)
            if m:
                mech.append({"category": cat, "matched": m.group(0).strip().lower()})
                if area not in areas:
                    areas.append(area)
                break                      # one hit per category is enough
    elec = []
    for kind, pat in ELECTRONIC_C.items():
        m = pat.search(text)
        if m:
            elec.append({"kind": kind, "matched": m.group(0).strip().lower()})

    decided = bool(mech) and not elec
    reasons = []
    if mech:
        reasons.append("mechanical evidence: "
                       + "; ".join(f"{m['category']} ({m['matched']!r})" for m in mech))
    else:
        reasons.append("no mechanical evidence found")
    if elec:
        reasons.append("electronic evidence present, so the normal search applies: "
                       + "; ".join(f"{e['kind']} ({e['matched']!r})" for e in elec))
    else:
        reasons.append("no electronic evidence (no lamp, gauge, sensor, signal, code, "
                       "derate or failure to run)")

    return {
        "no_dtc_match": decided,
        "mechanical": mech,
        "electronic": elec,
        "areas": areas,
        "reasons": reasons,
        "message": MESSAGE.format(areas=", ".join(areas)) if decided else None,
        "advice": ADVICE if decided else None,
        "rule": "mechanical evidence AND no electronic evidence -> no matching DTC",
    }


if __name__ == "__main__":
    import sys
    v = detect(" ".join(sys.argv[1:]))
    print(f"no_dtc_match: {v['no_dtc_match']}")
    for r in v["reasons"]:
        print(f"  - {r}")
    if v["message"]:
        print(f"\n{v['message']}\n{v['advice']}")
