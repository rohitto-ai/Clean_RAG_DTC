"""
Phase 12.2 — fault-SPECIFIC symptom expansions, authored here (index-only).

    PYTHONPATH=src .venv/bin/python scripts/author_expansions_v2.py

WHY THIS EXISTS. Phase 12.1 had a 3B model write "how does this fault show up?"
for each record. It produced the same six lines for a rail-pressure fault, a
coolant fault, a camshaft fault and a urea-level fault - weak pulling, smoke,
rough idle, a warning light, a noise - because the model has no diagnostic
knowledge of these ECU faults. Adding that text ERASED the distinctions
retrieval depends on: near-duplicate MRR fell 1.000 -> 0.486 and seven injector
guardrails failed.

WHAT IS DIFFERENT HERE. Every line is built from three author-supplied pieces
and each record's own fields, so that a line cannot help carrying something its
family siblings do not have:

  COMPONENT  what a driver or fitter actually notices for THIS part - which
             gauge, which behaviour, which circuit - plus a driver-voice
             complaint written for that part alone.
  MODE       what THIS failure mode looks like, phrased in deliberately opposed
             pairs so siblings cannot collide: short-to-ground pins a reading at
             the bottom, short-to-battery pins it at the top, open circuit kills
             it, drift wanders, disturbed jumps about, stuck-open will not close,
             stuck-closed will not open, range-high goes above what is physical,
             range-low below it.
  MARKER     the record's own distinguishing token where it has one - cylinder 1,
             track 2, bank 1, upstream vs downstream, sensor A vs B, the FCCU id.

No line is a bare lamp, bare smoke, bare noise or bare "power drops". No fault
code appears in any line.

HONESTY ABOUT AUTHORSHIP. The lines are COMPOSED from vocabulary I wrote; they
are not 314 independently free-written paragraphs. The component phrasings, the
mode phrasings and the composition rules are mine, written against the manual's
own vocabulary; the component, mode, marker and effect chosen for each record
come from that record's own fields. The provenance string says exactly this.

WHAT THIS CANNOT DO. Where a record has no observable distinguisher - the 56
"EMM alarm FCCUnn" ECU-internal records differ only by an internal alarm number,
which no driver can perceive - the only honest distinguisher is that number
itself. Those lines are near-identical by nature and the mechanical filter in
step 4 is expected to remove them. That is a finding, not a bug.

NO EVALUATION FILE IS OPENED. The only input is data/dtc_records.jsonl.
"""
from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, "src")

RECORDS = "data/dtc_records.jsonl"
OUT = "data/symptom_expansions_v2.json"
PROVENANCE = ("authored by an AI assistant from each record's own fields and general "
              "automotive knowledge, blind to all evaluation files; index-only")

# ---------------------------------------------------------------------------
# COMPONENT vocabulary: (pattern, thing, reading, drive, complaint)
#   thing      what a fitter calls the part
#   reading    the gauge, display or signal someone would look at
#   drive      the driving behaviour this part's failure disturbs
#   complaint  how the driver would describe it at the counter
# First match wins, so the list runs specific -> general.
# ---------------------------------------------------------------------------
COMPONENTS = [
    (r"no rail pressure build-?up", "fuel rail pressure build-up", "pressure while cranking",
     "starting", "it cranks and cranks but never builds up fuel pressure to fire"),
    (r"pressure relief valve|over pressure relief", "fuel pressure relief valve",
     "rail pressure holding", "pulling power",
     "it suddenly goes flat as if the fuel pressure is being dumped"),
    (r"rail pressure", "fuel rail pressure sensor", "rail pressure reading",
     "pulling power under load", "it will not pull and the rail pressure reading looks wrong"),
    (r"metering unit|quantity control", "fuel metering unit", "fuel delivery to the rail",
     "pulling power", "it is hard to start and will not make full fuelling"),
    (r"fuel pump relay", "fuel pump relay", "the fuel pump running", "starting",
     "it turns over but the fuel pump does not come on"),
    (r"fuel temperature", "fuel temperature sensor", "fuel temperature reading",
     "cold-start fuelling", "it runs badly from cold and the fuel temperature reading is wrong"),
    (r"water in fuel", "water-in-fuel sensor", "the water warning in the filter",
     "running on poor fuel", "the water-in-fuel warning behaves oddly"),
    (r"fuel filter|strainer", "fuel filter", "fuel flow through the filter",
     "pulling power at high revs", "it runs out of breath at the top end"),
    (r"injector", "injector", "injection on that cylinder", "idle smoothness",
     "one cylinder is missing and it shakes at idle"),
    (r"camshaft|cam signal", "camshaft position sensor", "the cam signal",
     "starting and smooth running", "it is slow to start and the cam signal is not right"),
    (r"crankshaft|crank signal", "crankshaft position sensor", "the crank signal",
     "starting and stalling", "it cuts out and will not restart until it sits a while"),
    (r"coolant temperature|engine temp", "coolant temperature sensor",
     "the temperature gauge", "warm-up and fan behaviour",
     "the temperature gauge is telling lies and the fan runs at the wrong times"),
    (r"charge air cooler|intercooler", "charge air cooler", "the intake air temperature",
     "pulling power on a long climb", "it goes soft on a long climb and the intake air runs hot"),
    (r"intake air temperature|air temperature monitoring", "intake air temperature sensor",
     "the intake air temperature reading", "fuelling when hot or cold",
     "the intake air temperature reading does not match the weather"),
    (r"ambient temperature", "ambient air temperature sensor",
     "the outside temperature reading", "cold-start behaviour",
     "the outside temperature on the display is nowhere near right"),
    (r"ambient pressure|barometric", "ambient pressure sensor", "the altitude correction",
     "pulling power at altitude", "it fuels badly up in the hills"),
    (r"manifold pressure", "intake manifold pressure sensor", "the boost reading",
     "pulling power under load", "the boost reading is wrong and it will not pull properly"),
    (r"mass or volume air flow|air mass|mass air ?flow|\bmaf\b|air flow sensor",
     "air mass meter", "the airflow reading", "smoke and pulling power",
     "it smokes and will not pull, and the airflow figure looks wrong"),
    (r"turbocharger boost control|boost control|boost pressure|turbocharger|wastegate",
     "turbocharger boost control", "the boost pressure", "pulling power on a climb",
     "there is no boost and it will not pull up a gradient"),
    (r"exhaust throttle|\betv\b", "exhaust throttle valve", "the exhaust brake",
     "engine braking and warm-up", "the exhaust brake does nothing and it is slow to warm up"),
    (r"egr cooler", "EGR cooler", "EGR cooling", "coolant temperature under load",
     "it runs hot under load and the EGR side is not cooling"),
    (r"egr valve position", "EGR valve position sensor", "the EGR valve position",
     "idle quality and smoke", "the EGR valve position never matches what is asked for"),
    (r"\begr\b|exhaust gas recirculation", "EGR valve", "EGR flow", "idle quality and smoke",
     "it idles rough and puffs smoke, and the EGR is to blame"),
    (r"particulate filter|\bdpf\b|soot (?:load|trap|mass)|soot", "diesel particulate filter",
     "the soot loading", "regeneration and pulling power",
     "the soot filter keeps warning and it is losing power"),
    (r"oxidation catalyst|\bdoc\b", "oxidation catalyst",
     "the exhaust temperature after the catalyst", "regeneration",
     "the exhaust never gets hot enough to burn the filter clean"),
    (r"regeneration|regen", "regeneration cycle", "regeneration completing",
     "how often it regenerates", "it tries to regenerate again and again and never finishes"),
    (r"delta pressure|differential pressure", "soot-trap differential pressure sensor",
     "the pressure drop across the filter", "regeneration behaviour",
     "the filter pressure figure is wrong so it regenerates at the wrong times"),
    (r"urea dosing valve|dosing valve", "AdBlue dosing valve", "AdBlue injection",
     "inducement and speed limiting", "the AdBlue is not being injected and it is counting down"),
    (r"urea (?:main |backflow )?pump|urea supply", "AdBlue pump",
     "AdBlue pressure in the line", "inducement and speed limiting",
     "the AdBlue pump is not delivering and the countdown has started"),
    (r"urea (?:tank )?temperature", "AdBlue tank temperature sensor",
     "the AdBlue tank temperature reading", "dosing in cold weather",
     "it will not dose AdBlue and blames the tank temperature"),
    (r"urea (?:tank )?level", "AdBlue tank level sensor", "the AdBlue gauge",
     "inducement and speed limiting",
     "the AdBlue gauge reads nothing like what is actually in the tank"),
    (r"urea quality|reductant quality", "AdBlue quality monitor", "AdBlue quality",
     "inducement and speed limiting", "it says the AdBlue is wrong even after a fresh fill"),
    (r"urea|diesel exhaust fluid|\bdef\b|reductant", "AdBlue dosing system",
     "AdBlue dosing", "inducement and speed limiting",
     "the AdBlue system keeps warning and threatening to cut the speed"),
    (r"\bscr\b", "SCR catalyst", "exhaust treatment after the catalyst",
     "inducement and speed limiting", "the exhaust treatment is not working and it is derating"),
    (r"nox sensor|\bnox\b", "NOx sensor", "the NOx reading", "inducement and derate",
     "the emissions warning keeps coming up and the NOx figure looks wrong"),
    (r"lambda", "lambda sensor", "the lambda reading", "fuelling trim",
     "the mixture reading is off and it fuels badly"),
    (r"exhaust-?gas temperature|temperature sensor (?:upstream|downstream)|exhaust temp|"
     r"\begt\b", "exhaust gas temperature sensor", "the exhaust temperature reading",
     "regeneration behaviour", "the exhaust temperature reading is wrong and regens go bad"),
    (r"pedal sensor|pedal position|accelerator", "accelerator pedal sensor",
     "the pedal position", "throttle response",
     "the pedal does not answer properly and it goes to idle on its own"),
    (r"clutch switch", "clutch switch", "the clutch pedal signal", "cruise and gearshift",
     "cruise control will not set and the clutch signal is at fault"),
    (r"brake", "brake switch", "the brake pedal signal", "cruise cancelling",
     "the brake signal is wrong so cruise behaves oddly"),
    (r"vehicle speed", "road speed sensor", "the speedometer", "speed limiting",
     "the speedometer is wrong and the limiter cuts in when it should not"),
    (r"battery voltage|supply voltage|under ?voltage|over ?voltage", "battery supply voltage",
     "the system voltage", "starting and electrics",
     "the electrics are unreliable and the supply voltage is out of range"),
    (r"starter motor", "starter motor circuit", "cranking", "starting",
     "nothing happens on the key and the starter circuit is dead"),
    (r"glow plug", "glow plug circuit", "pre-heat", "cold starting",
     "it will not start on a cold morning and the pre-heat is not working"),
    (r"\bcan\b|network|data link", "CAN data link", "talking to the other control units",
     "warning lamps and limp behaviour",
     "the dash lights up and the units have stopped talking to each other"),
    (r"engine speed|\brpm\b|overspeed", "engine speed monitoring", "the rev counter",
     "rev limiting", "the rev counter misbehaves and it limits the revs"),
    (r"torque monitoring|energizing time|level 2|injection cut ?off|fuel cut ?off|"
     r"torque limitation", "ECU torque monitoring", "the torque the ECU allows",
     "sudden power limiting", "it pulls back the power for no reason the driver can see"),
    (r"emm alarm|fccu", "ECU internal monitor", "the ECU's internal self-check",
     "unexpected shutdown or derate",
     "it derates or shuts down with nothing obviously wrong on the engine"),
    (r"internal control module|control module|\becu\b|\bems\b", "engine control unit",
     "the ECU's internal processing", "unexpected derate",
     "the control unit itself is reporting a fault inside"),
    (r"governor deviation", "air governor control", "air delivery against target",
     "smoke and pulling power", "it smokes and will not pull to the governor setting"),
    (r"heater", "sensor heater circuit", "sensor warm-up",
     "readiness after a cold start", "it takes far too long to be ready after a cold start"),
    (r"relay", "control relay", "the relay switching", "intermittent dead circuit",
     "the circuit goes dead now and then as if a relay is not pulling in"),
    (r"sensor", "sensor circuit", "the sensor reading", "driveability",
     "the sensor reading is not believable"),
]

# ---------------------------------------------------------------------------
# MODE vocabulary. Order matters: specific electrical faults first, then the
# range checks, then the softer plausibility and performance modes.
# ---------------------------------------------------------------------------
MODES = [
    ("short_gnd", r"short circuit to ground|shorted to ground|short to ground|"
                  r"signal range check low|src low|under ?voltage",
     ["{reading} sits at the very bottom of the scale and stays there",
      "{reading} reads zero even when it plainly should not",
      "the {thing} line is shorted down to earth"]),
    ("short_bat", r"short circuit to battery|shorted to battery|short to battery|"
                  r"signal range check high|src high|over ?voltage",
     ["{reading} sits pinned right at the top of the scale",
      "{reading} reads full scale even from stone cold",
      "the {thing} line is shorted up to battery voltage"]),
    ("short_both_sides", r"short circuit high and low side",
     ["both the feed and the return of the {thing} are shorted together",
      "the {thing} is shorted on its high side and its low side at the same time"]),
    ("short_supply", r"short circuit high side and main supply|high side and main supply",
     ["the {thing} high side is shorted across to the main supply",
      "the {thing} feed is shorted to the supply rail rather than to earth"]),
    ("short_any", r"short circuit|shorted",
     ["the {thing} is shorted and draws current where it should not",
      "the {thing} circuit is shorted rather than broken open"]),
    ("open", r"open circuit|open load|circuit open|disconnect|not connected|wire break|"
             r"wire diagnosis",
     ["{reading} is completely dead, nothing registers at all",
      "the {thing} wiring is broken so no reading ever arrives",
      "{reading} disappears altogether rather than reading wrong"]),
    ("overheat", r"overheat|control overheated|thermal",
     ["the {thing} driver cooks itself and shuts down once it has been working a while",
      "the fault comes back as the {thing} gets hot, not when it is cold"]),
    ("drift", r"drift",
     ["{reading} slowly wanders away from the true value",
      "the {thing} still looks believable but has crept out of calibration"]),
    ("no_signal", r"no signal|signal not received|not received|signal missing|"
                  r"availability diagnosis|readiness diagnosis",
     ["nothing at all arrives from the {thing}",
      "the {thing} never reports in, so there is no value to work with"]),
    ("disturbed", r"disturbed signal|intermittent|gradient|erratic|noisy",
     ["{reading} jumps about and cuts in and out",
      "the {thing} signal is unsteady rather than absent altogether"]),
    ("range_hi", r"range (?:check )?high|physical range high|too high|above (?:max|limit)|"
                 r"max(?:imum)? (?:limit|threshold)|high error|range max|\(maximum\)|"
                 r"offset max|above threshold|exceed|circuit high|signal high|high input",
     ["{reading} climbs higher than is physically possible",
      "{reading} goes above the highest sensible figure"]),
    ("range_lo", r"range (?:check )?low|physical range low|too low|below (?:min|limit)|"
                 r"min(?:imum)? (?:limit|threshold)|low error|range min|\(minimum\)|"
                 r"offset min|circuit low|signal low|low input",
     ["{reading} falls lower than is physically possible",
      "{reading} drops below the lowest sensible figure"]),
    ("stuck_open", r"jammed at open|stuck.{0,8}open|valve open\b|relief valve open",
     ["the {thing} stays open and will not close",
      "the {thing} is jammed wide open"]),
    ("stuck_closed", r"jammed at closed|stuck.{0,8}closed|stuck.{0,8}shut",
     ["the {thing} stays shut and will not open",
      "the {thing} is jammed closed"]),
    ("destroyed", r"destroyed|removed|gutted",
     ["the {thing} has been gutted or taken out altogether, not just blocked",
      "there is no working {thing} in the system at all any more"]),
    ("clogged", r"clogged|blocked|plugged|deteriorat|aged|efficiency",
     ["the {thing} is blocked or worn out rather than electrically faulty",
      "the {thing} no longer does its job well enough to pass its own check"]),
    ("comm", r"communication|sent line|received network data|network data|bus off|"
             r"hardware failed|hardware connection failed|disconnection to can",
     ["the {thing} stops reporting to the engine control unit",
      "messages from the {thing} stop arriving on the bus"]),
    ("locked", r"locked|inhibit|not released|blocked by",
     ["the {thing} is locked out and refuses to run at all",
      "the {thing} is held off, so it never even attempts the job"]),
    ("frequent", r"frequent activation|too often|repeated",
     ["the {thing} keeps triggering over and over instead of settling down"]),
    ("plaus", r"plausibilit|not plausible|implausible|incorrect|deviation|rationality|"
              r"incompatible|not compatible|performance|monitoring of",
     ["{reading} disagrees with what the other readings say",
      "the {thing} looks believable on its own but does not match the rest"]),
    ("leak", r"leak|hose line",
     ["the {thing} is leaking rather than reading wrong"]),
]
MODES_C = [(n, re.compile(p, re.I), t) for n, p, t in MODES]

# markers that separate siblings inside a family
MARKERS = [
    (re.compile(r"\bcylinder\s*(\d)\b", re.I), "on cylinder {0}"),
    (re.compile(r"\bcyl\s*(\d)\b", re.I), "on cylinder {0}"),
    (re.compile(r"\btrack\s*(\d)\b", re.I), "on pedal track {0}"),
    (re.compile(r"\bsensor\s*(\d)\b", re.I), "on sensor {0}"),
    (re.compile(r"\bbank\s*(\d)\b", re.I), "on bank {0}"),
    (re.compile(r"\blevel\s*(\d)\b", re.I), "at stage {0} of the warning"),
    (re.compile(r"\b(upstream)\b", re.I), "on the sensor before the catalyst"),
    (re.compile(r"\b(downstream)\b", re.I), "on the sensor after the catalyst"),
    (re.compile(r'\bsensor\s*"?([AB])"?\b', re.I), "on the {0} sensor"),
    (re.compile(r"\b(fccu\s*\d+)\b", re.I), "logged internally as {0}"),
    (re.compile(r"\bout\s*(\d)\b", re.I), "on output {0}"),
    (re.compile(r"\b(high and low side)\b", re.I), "on both sides of the injector"),
    (re.compile(r"\b(high side|low side)\b", re.I), "on the {0}"),
    (re.compile(r"\b(backflow|main)\s*pump\b", re.I), "on the {0} pump"),
    (re.compile(r"\b([Tt]\d)\b"), "on the {0} probe"),
    (re.compile(r"-\s*(\d)\s*$"), "on channel {0}"),
    # a late catch-all for the manual's own internal identifiers (PoI2, Out1, FCCU12)
    (re.compile(r"\b([A-Za-z]{2,5}\d{1,3})\b"), "on the item the manual calls {0}"),
]

# A short tag per failure mode, used to stamp the mode onto the complaint line and
# the effect line. Without it those two lines carry only the component, and so come
# out identical for two siblings that differ only in their failure mode.
TAGS = {
    "short_gnd": "the reading pinned at the bottom",
    "short_bat": "the reading pinned at the top",
    "short_both_sides": "both sides shorted together",
    "short_supply": "the high side shorted to the supply",
    "short_any": "it shorted",
    "open": "nothing coming through at all",
    "overheat": "the driver stage overheating",
    "drift": "the reading slowly drifting off",
    "no_signal": "no report arriving",
    "disturbed": "the reading jumping about",
    "range_hi": "the reading too high to be real",
    "range_lo": "the reading too low to be real",
    "stuck_open": "it stuck open",
    "stuck_closed": "it stuck shut",
    "clogged": "it blocked or worn out",
    "destroyed": "it missing or gutted",
    "comm": "it dropped off the bus",
    "locked": "it locked out",
    "frequent": "it triggering over and over",
    "plaus": "the reading not matching the others",
    "leak": "it leaking",
}

EFFECTS = [
    (re.compile(r"vehicle will halt", re.I), "the vehicle stops and will not go on"),
    (re.compile(r"will not start", re.I), "it will not start at all"),
    (re.compile(r"creep mode|speed limitation", re.I),
     "road speed is capped and it will only crawl"),
    (re.compile(r"torque (?:reduction|limitation)", re.I),
     "the engine is held back and will not make full power"),
    (re.compile(r"limp", re.I), "it drops into limp-home and barely pulls"),
]

FILLER = re.compile(r"\b(error|errors|check|signal|circuit|monitoring|diagnose|diagnosis|"
                    r"status|report|detection|all|the|of|for|in|a|an|is|and|or|to|which|"
                    r"read|out|dfc|fault|due|with|at|by|on|its)\b", re.I)


def component(desc):
    for pat, thing, reading, drive, complaint in COMPONENTS:
        if re.search(pat, desc, re.I):
            return thing, reading, drive, complaint
    return ("sensor circuit", "the sensor reading", "driveability",
            "the sensor reading is not believable")


def mode(desc):
    for name, pat, phr in MODES_C:
        if pat.search(desc):
            return name, phr
    return "other", []


def marker(desc):
    """Every marker the description carries, most specific first, de-duplicated."""
    out, tokens = [], set()
    for pat, tmpl in MARKERS:
        m = pat.search(desc)
        if m:
            tok = m.group(1).lower()
            if tok in tokens:
                continue
            tokens.add(tok)
            out.append(tmpl.format(tok))
    return ", ".join(out[:2]) or None


def effect(rec):
    text = " ".join([rec.get("effect") or "", rec.get("MIL") or ""])
    for pat, phrase in EFFECTS:
        if pat.search(text):
            return phrase
    return None


def own_words(desc, thing):
    """
    The record's OWN leftover words, for a record whose failure mode I could not
    classify. Keeps such a record separable from its siblings using nothing but
    its own description.
    """
    s = re.sub(r"^\s*(DFC|Diagnostic fault check)\s+(for|to report|to)?\s*", "", desc,
               flags=re.I)
    s = FILLER.sub(" ", s)
    thing_words = set(re.findall(r"[a-z]+", thing.lower()))
    words = [w for w in re.findall(r"[A-Za-z0-9\-]+", s)
             if (len(w) > 2 or w.isdigit()) and w.lower() not in thing_words]
    return " ".join(words[:7]).lower() or None


def expansions_for(rec):
    desc = rec["description"]
    thing, reading, drive, complaint = component(desc)
    mname, phrasings = mode(desc)
    mk, eff = marker(desc), effect(rec)
    # the mode tag, or for an unclassified record its own leftover description words
    tag = TAGS.get(mname) or (own_words(desc, thing) and
                              f"it reported as {own_words(desc, thing)}")
    out = []

    # 1-3: the failure mode as it presents, carrying the marker when there is one
    for p in phrasings[:3]:
        line = p.format(thing=thing, reading=reading)
        out.append(f"{line}, {mk}" if mk else line)

    # the driver's own words for this part, stamped with the mode and the marker so
    # that it cannot come out identical to a sibling's. Some complaints describe only
    # the behaviour ("it cuts out and will not restart") - those get the part named,
    # so no line can stand on behaviour alone.
    names_part = bool(set(re.findall(r"[a-z]+", thing.lower()))
                      & set(re.findall(r"[a-z]+", complaint.lower())))
    line = f"{complaint} - {tag}" if tag else complaint
    if not names_part:
        line = f"{line} on the {thing}"
    out.append(f"{line}, {mk}" if mk else line)

    # the record's own effect field, tied to this part and this mode
    if eff:
        line = f"{eff}, with {tag} on the {thing}" if tag else f"with the {thing} at fault, {eff}"
        out.append(f"{line} {mk}" if mk else line)
    elif tag:
        line = f"{drive} suffers, with {tag} on the {thing}"
        out.append(f"{line}, {mk}" if mk else line)

    # a line in the record's OWN words. Two records that the vocabulary above maps to
    # the same component and the same mode - "hardware failed" vs "hardware connection
    # failed" - still differ here, because this comes from their own description.
    own = own_words(desc, thing)
    if own and mname != "other":
        out.append(f"the complaint on the {thing} is written up as {own}")
    elif own:
        out.append(f"the only sign is what {reading} itself reports: {own}")

    seen, uniq = set(), []
    for line in out:
        line = re.sub(r"\s+", " ", line).strip()
        if line.lower() not in seen and 15 < len(line) < 200:
            seen.add(line.lower())
            uniq.append(line)
    return uniq[:5], {"component": thing, "reading": reading, "mode": mname, "marker": mk}


def family_key(desc):
    """
    Near-duplicate family: the component, with failure-mode words and any number
    stripped out. Siblings in one family are the records a retriever most easily
    confuses, so the self-check below runs per family.
    """
    s = desc.lower()
    s = re.sub(r"^\s*(dfc|diagnostic fault check)\s+(for|to report|to)?\s*", "", s)
    for _n, pat, _t in MODES_C:
        s = pat.sub(" ", s)
    s = re.sub(r"\d+|\b(error|errors|check|signal|circuit|monitoring|diagnose|diagnosis|"
               r"status|the|of|for|in|a|an|is|and|or|to|which|read|out|all|detection|track|"
               r"cylinder|cyl|bank|sensor|upstream|downstream)\b", " ", s)
    return " ".join(s.split())


def main():
    recs = [json.loads(l) for l in open(RECORDS)]
    out, modes, no_mk = {}, {}, 0
    for r in recs:
        rid = f"{r['code_full']}@p{r['page']}#{r['occurrence']}"
        lines, meta = expansions_for(r)
        out[rid] = {"code_full": r["code_full"], "system": r["system"],
                    "description": r["description"], "expansions": lines, **meta}
        modes[meta["mode"]] = modes.get(meta["mode"], 0) + 1
        no_mk += meta["marker"] is None

    # FAMILY-LEVEL COLLISION REMOVAL. The requirement is that every line carries
    # something its family siblings do not. A line two siblings share cannot
    # separate them - that is exactly how 12.1 failed - so it is removed from BOTH.
    # Removal only: no line is reworded.
    import collections
    fams = collections.defaultdict(list)
    for rid, v in out.items():
        fams[family_key(v["description"])].append(rid)
    collisions, removed = [], 0
    for key, ids in fams.items():
        if len(ids) < 2:
            continue
        holders = collections.defaultdict(list)
        for rid in ids:
            for e in out[rid]["expansions"]:
                holders[e].append(rid)
        for line, rids in holders.items():
            if len(rids) > 1:
                collisions.append({"family": key, "line": line, "records": rids})
                for rid in rids:
                    out[rid]["expansions"] = [e for e in out[rid]["expansions"] if e != line]
                    removed += 1
    for rid, v in out.items():
        v["expansions_kept"] = len(v["expansions"])
    empty = [rid for rid, v in out.items() if not v["expansions"]]
    multi = {k: v for k, v in fams.items() if len(v) > 1}

    total = sum(len(v["expansions"]) for v in out.values())
    blob = {"_label": "index-only, never shown to users",
            "provenance": PROVENANCE,
            "method": ("each line is composed from an author-written COMPONENT phrasing (gauge, "
                       "behaviour, driver complaint), an author-written FAILURE-MODE phrasing in "
                       "opposed pairs, and the record's own MARKER (cylinder, track, bank, "
                       "upstream/downstream, sensor A/B, FCCU id) and own effect field. No fault "
                       "codes; no bare lamp/smoke/noise/power lines."),
            "inputs_used": ["description", "effect", "MIL", "system"],
            "no_gold_read": "the only input file is data/dtc_records.jsonl",
            "records": len(out), "expansions": total,
            "mean_per_record": round(total / len(out), 2),
            "mode_histogram": dict(sorted(modes.items(), key=lambda kv: -kv[1])),
            "records_without_marker": no_mk,
            # the 12.1 index builder reads "records", "model" and "seed"; these lines
            # were authored rather than generated, so there is no model and no seed
            "model": "none - authored, not model-generated",
            "seed": None,
            "families": len(fams), "families_with_siblings": len(multi),
            "largest_family": max(len(v) for v in fams.values()),
            "family_collisions_removed": {
                "rule": "a line held by two or more records in the same near-duplicate family "
                        "is removed from all of them (removal only, nothing reworded)",
                "distinct_lines": len(collisions), "line_removals": removed,
                "records_left_with_no_expansion": empty,
                "examples": collisions[:10]},
            "lines_shared_verbatim_with_a_family_sibling": 0,
            "records": out}
    with open(OUT, "w") as f:
        json.dump(blob, f, indent=1, ensure_ascii=False)
    print(f"{len(out)} records, {total} expansions ({total / len(out):.1f} per record)")
    print("modes:", blob["mode_histogram"])
    print(f"records with no distinguishing marker: {no_mk}")
    print(f"families: {len(fams)} ({len(multi)} with siblings, largest "
          f"{max(len(v) for v in fams.values())})")
    print(f"family collisions removed: {len(collisions)} distinct lines, "
          f"{removed} removals; {len(empty)} records left with none")
    for x in collisions[:5]:
        print(f"   {x['records']}: {x['line'][:88]}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
