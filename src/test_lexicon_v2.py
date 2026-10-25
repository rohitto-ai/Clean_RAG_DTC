"""
Phase 10.1 — tests for domain lexicon v2 and the query-side rewrite rules.

    PYTHONPATH=src .venv/bin/python src/test_lexicon_v2.py

Covers: cylinder ordinals (R1), valve/switch negation rewrites (R2), index/query
tokenisation parity, provenance tags, and the contamination audit (no entry from a
DEV miss; the frozen TEST split and the forthcoming independent technician query
set were not read when authoring v2).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

V1 = "data/domain_lexicon.json"
V2 = "data/domain_lexicon_v2.json"
EXP_INDEX = "index_exp/minilm_lexv2"

# Frozen expectations: the only v2-authored colloquial terms that happen to
# coincide with wording in the spent TEST split. Standard-vocabulary coincidences,
# ablatable via Lexicon(exclude_test_matching=True). A new entry that silently
# matches TEST wording makes this test fail.
EXPECTED_TEST_COINCIDENCE = {("term:position sensor", "position feedback"),
                             ("term:starter motor", "starter")}
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    from build_index import tokenize
    from lexicon import Lexicon, apply_query_rules, audit, _has, NUMBER_WORDS

    lx = json.load(open(V2))
    L2 = Lexicon(V2)
    L1 = Lexicon(V1)

    # ---------------- R1: cylinder number words and ordinals ----------------
    print("\n== R1 cylinder ordinals / number words ==")
    cases = [
        ("cylinder one injector open circuit", "cylinder 1"),
        ("cyl two has no injection", "cylinder 2"),
        ("cylinder number three dead", "cylinder 3"),
        ("cyl. no four injector", "cylinder 4"),
        ("the first cylinder is misfiring", "cylinder 1"),
        ("second cylinder injector fault", "cylinder 2"),
        ("3rd cylinder broken wire", "cylinder 3"),
        ("sixth cylinder", "cylinder 6"),
        ("no.1 injector is open", "injector cylinder 1"),
        ("#2 injector", "injector cylinder 2"),
        ("injector 3 open circuit", "injector cylinder 3"),
        ("injector no 4 short", "injector cylinder 4"),
    ]
    for q, want in cases:
        got, tr = apply_query_rules(q)
        check(f"{q!r} -> contains {want!r}", want in got, f"got={got!r}")
    check("every number word maps to 1..8",
          set(NUMBER_WORDS.values()) <= set(range(1, 9)) and NUMBER_WORDS["2nd"] == 2)
    # already-canonical digit wording must be left exactly as it is
    for q in ("cylinder 1 injector open circuit", "injector open circuit for cylinder 4"):
        check(f"digit form unchanged: {q!r}", apply_query_rules(q)[0] == q)
    # must not fire on unrelated text
    for q in ("rail pressure sensor short to ground", "one of the sensors is faulty",
              "the second opinion", "four wheel drive"):
        got, tr = apply_query_rules(q)
        check(f"no cylinder rule on {q!r}",
              not any(t["rule"].startswith("R1a") or t["rule"].startswith("R1c") for t in tr)
              and "cylinder" not in got.lower() or q == got, f"got={got!r}")

    # ---------------- R2: valve / switch state negation ----------------
    print("\n== R2 valve / switch state negation ==")
    OPEN, CLOSED = "jammed at open position", "jammed at closed position"
    open_cases = ["the flap refuses to shut", "egr valve will not close", "valve won't shut",
                  "it does not close", "flap not closing", "valve stays open",
                  "valve stays wide open", "stuck wide open", "seized open", "jammed open",
                  "held open"]
    closed_cases = ["the valve refuses to open", "egr valve will not open", "valve won't open",
                    "it does not open", "flap not opening", "valve stays closed",
                    "valve stays shut", "seized shut", "seized closed", "jammed shut",
                    "stuck closed", "held closed"]
    for q in open_cases:
        got, tr = apply_query_rules(q)
        check(f"stuck-OPEN: {q!r}", OPEN in got and CLOSED not in got,
              f"rules={[t['rule'] for t in tr]}")
    for q in closed_cases:
        got, tr = apply_query_rules(q)
        check(f"stuck-CLOSED: {q!r}", CLOSED in got and OPEN not in got,
              f"rules={[t['rule'] for t in tr]}")
    # the manual's wording is APPENDED - the technician's own words survive
    got, _ = apply_query_rules("the flap refuses to shut")
    check("original wording is preserved, not replaced", "refuses to shut" in got)
    # switch polarity: both normalise to the manual's only stuck-switch wording
    for q in ("clutch switch stuck on", "switch stays on", "brake switch won't turn off"):
        got, tr = apply_query_rules(q)
        check(f"switch-ON: {q!r}", "switch stuck" in got and
              any(t["rule"] == "R2c_switch_stuck_on" for t in tr))
    for q in ("clutch switch stuck off", "switch stays off", "switch won't switch on"):
        got, tr = apply_query_rules(q)
        check(f"switch-OFF: {q!r}", "switch stuck" in got and
              any(t["rule"] == "R2d_switch_stuck_off" for t in tr))
    # no state rule on a query with no state language
    for q in ("rail pressure sensor short to ground", "adblue tank level low"):
        got, tr = apply_query_rules(q)
        check(f"no state rule on {q!r}", got == q and not tr)
    # determinism + trace
    a, ta = apply_query_rules("cylinder one valve refuses to shut")
    b, tb = apply_query_rules("cylinder one valve refuses to shut")
    check("rules are deterministic and traced", a == b and ta == tb and len(ta) == 2,
          f"rules={[t['rule'] for t in ta]}")

    # ---------------- tokenisation parity ----------------
    print("\n== tokenisation parity (index vs query) ==")
    blob = json.load(open(f"{EXP_INDEX}/bm25_corpus.json"))
    tok_meta = blob["tokenizer"]
    check("experimental index records both compound flags",
          tok_meta["cylinder_compound"] is True and tok_meta["state_compound"] is True, str(tok_meta))
    from retrieve import Retriever
    R = Retriever(index_dir=EXP_INDEX, lexicon=L2, expand="bm25")
    check("retriever reads the flags from the index, not from defaults",
          R.cylinder_compound is True and R.state_compound is True)
    for text in ("EGR valve jammed at closed position", "Injector open circuit for cylinder 3",
                 "Exhaust throttle Valve jammed at Open position"):
        idx = tokenize(text, cylinder_compound=tok_meta["cylinder_compound"],
                       state_compound=tok_meta["state_compound"])
        check(f"query tokeniser == index tokeniser on {text[:38]!r}...", R._tokenize(text) == idx,
              f"{R._tokenize(text)} vs {idx}")
    check("state fold produces jammed_open / jammed_closed",
          tokenize("jammed at open position", state_compound=True) == ["jammed_open"]
          and tokenize("stuck in closed position", state_compound=True) == ["jammed_closed"])
    check("production tokeniser is unaffected when the flag is off",
          tokenize("EGR valve jammed at closed position") ==
          ["egr", "valve", "jammed", "at", "closed", "position"])
    prod = json.load(open("index/bm25_corpus.json"))["tokenizer"]
    check("production index does NOT use the state fold",
          prod.get("state_compound", False) is False, str(prod))

    # ---------------- provenance + structure ----------------
    print("\n== provenance and structure ==")
    allowed = {"manual_term", "sae_j1939", "general_technician"}
    entries = ([("system:" + n, e) for n, e in lx["system_aliases"].items()]
               + [("term:" + e["manual"][0], e) for e in lx["term_synonyms"]])
    check("every entry carries an allowed provenance",
          all(e["provenance"] in allowed for _, e in entries),
          str({e["provenance"] for _, e in entries} - allowed))
    check("provenance dev_driven is 0",
          not any(e["provenance"] == "dev_driven" for _, e in entries)
          and not any(e.get("provenance_v1") == "dev_driven" for _, e in entries))
    check("declared provenance_values match what is used",
          set(lx["provenance_values"]) == allowed)
    check("every entry has manual + colloquial terms",
          all(e["manual"] and e["colloquial"] for _, e in entries))
    check("v2 declares query_rules; v1 does not",
          L2.query_rules is True and L1.query_rules is False)
    # every Phase 8.2 entry survives verbatim on its manual side
    v1 = json.load(open(V1))
    v1_terms = {tuple(e["manual"]) for e in v1["term_synonyms"]}
    v2_terms = {tuple(e["manual"]) for e in lx["term_synonyms"]}
    check("all 8.2 term entries are still present", v1_terms <= v2_terms,
          str(v1_terms - v2_terms))
    check("all 8.2 subsystem entries are still present",
          set(v1["system_aliases"]) <= set(lx["system_aliases"]))
    # subsystem aliases must be correct for EVERY record of that subsystem: assert
    # the mixed subsystems identified in 8.2 still have no subsystem-level alias
    for mixed in ("engine_position", "fuel_supply", "pedal_clutch_brake", "intake_air",
                  "electrical", "sensor_generic", "level2_monitoring", "ecu_internal"):
        check(f"mixed subsystem {mixed!r} has no subsystem alias",
              mixed not in lx["system_aliases"])

    # ---------------- contamination audit ----------------
    print("\n== contamination audit ==")
    qs = json.load(open("data/gold_v2.json"))["queries"]
    test_q = [q["query"] for q in qs if q["split"] == "TEST"]
    v2_authored = []
    for n, e in lx["system_aliases"].items():
        if e["origin"] == "phase10.1":
            v2_authored += [(f"system:{n}", c) for c in e["colloquial"]]
        else:
            v2_authored += [(f"system:{n}", c) for c in e.get("added_in_v2", [])]
    for e in lx["term_synonyms"]:
        if e["origin"] == "phase10.1":
            v2_authored += [(f"term:{e['manual'][0]}", c) for c in e["colloquial"]]
    coincide = {(k, c) for k, c in v2_authored if any(_has(c, t) for t in test_q)}
    check("v2-authored terms coinciding with TEST wording match the frozen expectation",
          coincide == EXPECTED_TEST_COINCIDENCE,
          f"unexpected={coincide - EXPECTED_TEST_COINCIDENCE}")
    check("the TEST-matching ablation still works on v2",
          len(Lexicon(V2, exclude_test_matching=True).excluded) > 0)
    check("audit() computes both gold-overlap flags for v2",
          all({"matches_dev_query", "matches_test_query"} <= set(r) for r in audit(V2)))
    # the independent technician query set must not be in the repo
    present = [p for p in ("data/gold_independent.json", "data/gold_technician.json",
                           "data/independent_queries.json", "data/gold_v3.json")
               if os.path.exists(p)]
    check("no independent technician query set is present in the repo", not present, str(present))

    passed = sum(RESULTS)
    print(f"\n==== LEXICON V2: {passed}/{len(RESULTS)} passed ====")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
