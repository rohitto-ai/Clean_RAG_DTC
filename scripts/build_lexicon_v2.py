"""
Phase 10.1 — deterministic builder for data/domain_lexicon_v2.json.

    PYTHONPATH=src .venv/bin/python scripts/build_lexicon_v2.py

v2 = every Phase 8.2 entry, kept verbatim and re-tagged into the v2 provenance
taxonomy, plus new entries from INDEPENDENT sources only:

  manual_term         the manual's own terminology: system names, component names,
                      failure phrases, and its own abbreviations (DPF, ETV, SRC)
  sae_j1939           SAE J1939 standard parameter-name vocabulary mapped to the
                      manual's wording (accelerator pedal position, engine coolant
                      temperature, intake manifold pressure, mass air flow, ...)
  general_technician  general workshop / driver language for SYMPTOMS (power loss,
                      starting trouble, stalling, overheating, derate) and for
                      COMPONENTS (colloquial names for sensors, valves, filters,
                      pumps, relays, wiring faults), mapped to the manual's terms

NO entry is derived from a DEV miss: provenance "dev_driven" stays 0, as in 8.2.
No entry was authored from the frozen TEST split or from the forthcoming
independent technician query set, neither of which was read in this phase.

Phase 8.2 scope rule, re-applied: a SUBSYSTEM-level alias must be correct for
EVERY record in that subsystem, else it is attached at DESCRIPTION level. Mixed
subsystems therefore get no new subsystem aliases: engine_position (cam + crank),
fuel_supply (pump/relay/metering/fuel-temp/water), pedal_clutch_brake (pedal +
clutch + brake), intake_air (intake + ambient), electrical, sensor_generic,
level2_monitoring, ecu_internal.

Aliases are BM25-side only at build time (--aliases bm25). Phase 8.2 config C6
showed that aliasing the DENSE text merges near-duplicate families.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

V1_PATH = "data/domain_lexicon.json"
OUT = "data/domain_lexicon_v2.json"

# --- Phase 8.2 entries: re-tag only, wording untouched ----------------------
SAE_V1 = {"system:vehicle_speed", "term:vehicle speed", "term:charge air cooler",
          "term:engine speed", "term:urea", "term:nox sensor", "term:lambda",
          "term:battery voltage", "system:can_network"}
MANUAL_V1 = {"system:egr", "system:exhaust_throttle", "system:rail_pressure",
             "term:particulate filter", "term:soot", "term:metering unit",
             "term:plausibility", "term:open circuit", "term:short circuit to battery",
             "term:short circuit to ground", "term:no signal", "term:disturbed signal",
             "term:camshaft", "term:crankshaft", "term:water in fuel", "term:regeneration",
             "term:temperature", "term:pedal"}

# --- NEW subsystem-level aliases (verified correct for EVERY record) --------
# "aftertreatment" is the SAE J1939 umbrella term; every record of these three
# subsystems is an aftertreatment component (SCR/DEF dosing, DPF/DOC/regen,
# NOx + exhaust-gas temperature sensing).
NEW_SYSTEM = {
    "scr_def":   {"colloquial": ["aftertreatment", "after treatment", "exhaust aftertreatment"],
                  "manual": ["scr", "urea", "def"], "provenance": "sae_j1939"},
    "dpf_regen": {"colloquial": ["aftertreatment", "after treatment", "exhaust aftertreatment"],
                  "manual": ["dpf", "particulate filter", "doc"], "provenance": "sae_j1939"},
    "o2_exhaust": {"colloquial": ["aftertreatment", "after treatment", "exhaust sensor"],
                   "manual": ["nox", "exhaust-gas temperature", "lambda"],
                   "provenance": "sae_j1939"},
}
# Extra colloquial terms added to EXISTING subsystem entries.
EXTEND_SYSTEM = {
    "egr":              (["exhaust gas recirc", "egr circuit"], "sae_j1939"),
    "turbo_boost":      (["turbo charger", "boost control"], "sae_j1939"),
    "coolant":          (["engine coolant temperature", "coolant sender"], "sae_j1939"),
    "rail_pressure":    (["fuel rail pressure", "rail press"], "sae_j1939"),
    "vehicle_speed":    (["wheel based vehicle speed"], "sae_j1939"),
    "injector":         (["fuel injector", "injectors"], "sae_j1939"),
    "exhaust_throttle": (["etv valve", "back pressure valve"], "manual_term"),
    "can_network":      (["j1939 bus", "data bus", "communication bus"], "sae_j1939"),
}

# --- NEW description-level term synonyms ------------------------------------
# (manual terms, colloquial terms, provenance, systems|None)
NEW_TERMS = [
    # ---- SAE J1939 standard parameter names -> the manual's wording ----
    (["pedal position", "accelerator"], ["accelerator pedal position", "app sensor",
     "throttle position sensor", "tps"], "sae_j1939", ["pedal_clutch_brake"]),
    (["manifold pressure", "intake manifold"], ["intake manifold pressure", "map sensor",
     "inlet manifold", "boost pressure sensor"], "sae_j1939", None),
    (["air mass", "mass air flow"], ["maf", "maf sensor", "mass airflow", "air flow meter",
     "air mass meter"], "sae_j1939", None),
    (["ambient pressure"], ["barometric pressure", "baro sensor", "atmospheric pressure"],
     "sae_j1939", None),
    (["delta pressure"], ["differential pressure sensor", "dp sensor", "pressure difference"],
     "sae_j1939", None),
    (["boost pressure"], ["charge pressure", "manifold boost", "turbo pressure"],
     "sae_j1939", None),
    (["exhaust-gas temperature", "temperature sensor upstream"], ["egt", "egt sensor",
     "exhaust temp", "exhaust gas temp"], "sae_j1939", None),
    (["catalyst"], ["catalytic converter", "cat brick"], "sae_j1939", None),
    (["glow plug"], ["heater plug", "starting aid"], "sae_j1939", None),
    (["quality sensor"], ["def quality", "fluid quality", "urea quality"], "sae_j1939",
     ["scr_def"]),
    # ---- the manual's own abbreviations / failure phrases ----
    (["src", "physical range", "signal range"], ["out of range", "range check",
     "signal out of range"], "manual_term", None),
    (["physical range high", "range high", "src high"], ["reading too high", "over range",
     "maxed out", "reads high"], "manual_term", None),
    (["physical range low", "range low", "src low"], ["reading too low", "under range",
     "reads low"], "manual_term", None),
    (["jammed at open position"], ["stuck open", "jammed open", "seized open",
     "held open"], "manual_term", None),
    (["jammed at closed position"], ["stuck closed", "stuck shut", "jammed closed",
     "jammed shut", "seized closed"], "manual_term", None),
    (["pressure relief valve"], ["prv", "relief valve", "overflow valve"], "manual_term", None),
    (["position sensor"], ["feedback sensor", "position feedback"], "manual_term", None),
    (["drift"], ["drifting", "out of calibration", "reading wandering"], "manual_term", None),
    (["over voltage"], ["overvoltage", "too many volts", "volts too high"], "manual_term", None),
    (["under voltage"], ["undervoltage", "low volts", "volts too low"], "manual_term", None),
    (["heater"], ["heating element", "sensor heater"], "manual_term", None),
    (["inducement"], ["derate", "derated", "power derate", "inducement strategy"],
     "manual_term", None),
    # ---- general workshop / driver SYMPTOM language ----
    (["torque reduction", "torque limitation"], ["loss of power", "lost power", "no power",
     "down on power", "lacks power", "will not pull", "wont pull", "gutless", "sluggish",
     "limp mode", "limp home", "reduced power"], "general_technician", None),
    (["vehicle will not start"], ["will not start", "wont start", "no start",
     "fails to start", "turns over but will not fire", "cranks but will not start"],
     "general_technician", None),
    (["vehicle will halt"], ["stalls", "stalling", "cuts out", "shuts down", "engine dies",
     "cuts off"], "general_technician", None),
    (["creep mode", "speed limitation"], ["crawl mode", "speed capped", "speed limited"],
     "general_technician", None),
    (["overheat", "coolant temperature"], ["overheating", "running hot", "boiling over"],
     "general_technician", None),
    (["soot", "particulate filter"], ["black smoke", "sooting up", "smoky exhaust"],
     "general_technician", None),
    (["leak", "leakage"], ["leaking", "weeping", "air leak", "blowing air"],
     "general_technician", None),
    (["clogged", "blocked"], ["bunged up", "restricted", "plugged up"],
     "general_technician", None),
    (["gradient", "intermittent"], ["jumpy", "spiking", "cutting in and out", "flickering"],
     "general_technician", None),
    # ---- general workshop COMPONENT language ----
    (["harness", "connector"], ["loom", "wiring loom", "plug", "socket", "terminal",
     "chafed wire", "corroded pin"], "general_technician", None),
    (["fuse"], ["blown fuse", "fuse blown"], "general_technician", None),
    (["relay"], ["switching relay", "solenoid relay"], "general_technician", None),
    (["switch"], ["micro switch", "contact switch"], "general_technician", None),
    (["clutch switch"], ["clutch pedal switch", "clutch sensor"], "general_technician",
     ["pedal_clutch_brake"]),
    (["brake"], ["brake switch", "brake pedal signal"], "general_technician",
     ["pedal_clutch_brake"]),
    (["strainer", "fuel filter"], ["pre filter", "fuel screen", "filter gauze"],
     "general_technician", None),
    (["water in fuel"], ["water in diesel", "wet fuel", "diesel bug"],
     "general_technician", None),
    (["metering unit"], ["mprop", "fuel control valve"], "general_technician", None),
    (["starter motor"], ["starter", "cranking circuit"], "general_technician", None),
    (["regeneration"], ["forced regen", "parked regen", "dpf burn"],
     "general_technician", None),
    (["level too low", "level"], ["low level", "tank low", "fluid low"],
     "general_technician", None),
]


def main():
    v1 = json.load(open(V1_PATH))

    def retag(key, _old):
        return ("sae_j1939" if key in SAE_V1 else
                "manual_term" if key in MANUAL_V1 else "general_technician")

    system_aliases = {}
    for name, e in v1["system_aliases"].items():
        colloq = list(e["colloquial"])
        manual = list(e["manual"])
        prov = retag(f"system:{name}", e["provenance"])
        entry = {"colloquial": colloq, "manual": manual, "provenance": prov,
                 "provenance_v1": e["provenance"], "origin": "phase8.2"}
        if name in EXTEND_SYSTEM:
            add, add_prov = EXTEND_SYSTEM[name]
            entry["colloquial"] = colloq + [c for c in add if c not in colloq]
            entry["added_in_v2"] = list(add)
            entry["added_provenance"] = add_prov
        system_aliases[name] = entry
    for name, e in NEW_SYSTEM.items():
        assert name not in system_aliases, name
        system_aliases[name] = {**e, "origin": "phase10.1"}

    term_synonyms = []
    for e in v1["term_synonyms"]:
        ne = {"manual": list(e["manual"]), "colloquial": list(e["colloquial"]),
              "provenance": retag(f"term:{e['manual'][0]}", e["provenance"]),
              "provenance_v1": e["provenance"], "origin": "phase8.2"}
        if e.get("systems"):
            ne["systems"] = list(e["systems"])
        term_synonyms.append(ne)
    for manual, colloq, prov, systems in NEW_TERMS:
        ne = {"manual": list(manual), "colloquial": list(colloq), "provenance": prov,
              "origin": "phase10.1"}
        if systems:
            ne["systems"] = list(systems)
        term_synonyms.append(ne)

    out = {
        "version": 3,
        "lexicon_version": "v2",
        "phase": "10.1",
        "query_rules": True,
        "purpose": "Map technician/driver/SAE J1939 vocabulary to the manual's formal ECU "
                   "terminology, to close the free-text symptom-retrieval gap (mid-sem "
                   "feedback). Extends the Phase 8.2 lexicon; v1 entries are kept verbatim.",
        "provenance_values": ["manual_term", "sae_j1939", "general_technician"],
        "rules": [
            "Aliases are SUBSYSTEM-level (system_aliases) or DESCRIPTION-level "
            "(term_synonyms). A subsystem-level alias must be correct for EVERY record in "
            "that subsystem; otherwise it is description-level (Phase 8.2 rule).",
            "Aliases are NEVER derived from step text: step boilerplate is shared across "
            "hundreds of DTCs and aliasing it would re-collapse near-duplicate families.",
            "Index side: BM25 ONLY (--aliases bm25). Phase 8.2 config C6 showed that "
            "aliasing the dense text merges near-duplicate families.",
            "provenance dev_driven is 0 by construction: no entry is derived from a DEV "
            "miss. The frozen TEST split and the forthcoming independent technician query "
            "set were not read when authoring v2.",
            "Query-side rewrite rules (cylinder ordinals, valve/switch state negation) live "
            "in src/lexicon.py and are enabled by query_rules=true; they run BEFORE BM25 "
            "expansion and never touch the dense query or the gate.",
        ],
        "not_covered": [
            "Warning-lamp language (warning light, dash light, check engine, MIL): the "
            "tokens 'lamp', 'mil' and 'warning' do not occur in the BM25 corpus at all, "
            "because bm25_text() carries description/cause/effect/checkpoints/circuit "
            "text but not the MIL field. An alias here would expand to a term with no "
            "postings, so none was added.",
            "Abnormal-noise language (knocking, rattle, whistle, whine): 'noise', 'knock', "
            "'rattle' and 'whistle' do not occur in the corpus.",
            "White/blue smoke: no smoke vocabulary exists in the corpus. Only black smoke "
            "is mapped, to soot/particulate filter, and that mapping is a diagnostic "
            "inference rather than a synonym.",
        ],
        "system_aliases": system_aliases,
        "term_synonyms": term_synonyms,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")

    import collections
    prov = collections.Counter([e["provenance"] for e in system_aliases.values()]
                              + [e["provenance"] for e in term_synonyms])
    origin = collections.Counter([e["origin"] for e in system_aliases.values()]
                                + [e["origin"] for e in term_synonyms])
    print(f"wrote {OUT}")
    print(f"  entries: {len(system_aliases)} system + {len(term_synonyms)} term "
          f"= {len(system_aliases) + len(term_synonyms)}")
    print(f"  by provenance: {dict(prov)}")
    print(f"  by origin: {dict(origin)}")
    print(f"  colloquial terms: "
          f"{sum(len(e['colloquial']) for e in system_aliases.values()) + sum(len(e['colloquial']) for e in term_synonyms)}")


if __name__ == "__main__":
    main()
