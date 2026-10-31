"""
Phase 13.1 — tests for the conversational pre-filter.

    PYTHONPATH=src .venv/bin/python src/test_conversational.py

The filter sits in FRONT of routing, so the two sides of it are not equally
serious. A MUST-NOT-FIRE failure swallows a real fault report and answers a
technician with a pleasantry; a SHOULD-FIRE failure merely sends "hi" through
retrieval and gets a refusal. The must-not-fire block is therefore the larger
one, and every case in it was written to attack the rule, not to confirm it.

No retrieval, no index, no model: classify() is pure text.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------- should fire
SHOULD_FIRE = [
    ("hi", "GREETING"),
    ("Hello!", "GREETING"),
    ("hey", "GREETING"),
    ("good morning", "GREETING"),
    ("Good afternoon.", "GREETING"),
    ("hello there", "GREETING"),
    ("thanks a lot", "THANKS"),
    ("thank you", "THANKS"),
    ("Thanks!", "THANKS"),
    ("ok", "THANKS"),
    ("okay, great", "THANKS"),
    ("bye", "THANKS"),
    ("hello and thanks", "THANKS"),          # tie-break: acknowledgement wins
    ("all good, running fine", "NO_PROBLEM"),
    ("no issue vehicle is cranking and healthy", "NO_PROBLEM"),
    ("no issues", "NO_PROBLEM"),
    ("nothing wrong with it", "NO_PROBLEM"),
    ("the truck is working fine", "NO_PROBLEM"),
    ("engine running normally", "NO_PROBLEM"),
    ("starts fine", "NO_PROBLEM"),
    ("no complaints from the driver", "NO_PROBLEM"),
    ("no warning", "NO_PROBLEM"),            # healthy phrase holding a symptom word
    ("vehicle is healthy", "NO_PROBLEM"),
    # bare "all ok" is an acknowledgement, not a vehicle report: _pleasantry_only
    # is checked first. Both replies are non-diagnostic, so nothing unsafe turns on
    # it, but the precedence is pinned here so it cannot drift silently.
    ("all ok", "THANKS"),
    ("all ok with the truck", "NO_PROBLEM"),
    ("everything is working properly", "NO_PROBLEM"),
]

# ------------------------------------------------------------ must NOT fire
MUST_NOT_FIRE = [
    # a healthy phrase with a fault attached - the dangerous class
    "starts fine but black smoke under load",
    "no issue except a squeal on cold start",
    "healthy at idle, weak when climbing",
    "no warning light but loses power",
    "runs fine but sometimes stalls",
    "no problems although the lamp came on yesterday",
    "all good apart from a rattle at idle",
    "working fine, only when hot it derates",
    "no issues however it will not start when cold",
    "nothing wrong other than a diesel smell",
    # a plain fault report with no healthy phrase at all
    "vehicle not cranking",
    "engine knocking at full load",
    "loses power on a climb",
    "coolant gauge stuck at the bottom",
    "it overheats after an hour",
    # codes and telemetry
    "P0192-00",
    "p0192",
    "U011A-00 came up on the dash",
    "spn 520210 fmi 4",
    "no issue with SPN 520210",             # healthy phrase + a code reference
    # pleasantry plus content - the filter must stand down
    "hi, engine knocking at full load",
    "thanks, but the lamp came back",
    "hello, the truck will not start",
    "good morning, P0117-00 is active",
    "thanks - what does a derate mean",
    # out-of-scope questions, which belong to the gate, not to this filter
    "how do I change a tyre",
    "what is the warranty period on this engine",
    # near-misses that must not be read as healthy
    "is the vehicle healthy when the lamp is on",
    "please confirm there is a problem",
    "",
    "   ",
]


def main():
    import conversational as C

    print("\n-- should fire --")
    for q, want in SHOULD_FIRE:
        got = C.classify(q)
        check(f"{want:11s} {q!r}", got == want, f"got {got}")

    print("\n-- must NOT fire (a false positive swallows a fault report) --")
    for q in MUST_NOT_FIRE:
        got = C.classify(q)
        check(f"None        {q!r}", got is None, f"got {got}")

    print("\n-- responses and labelling --")
    for label in ("GREETING", "THANKS", "NO_PROBLEM"):
        msg = C.RESPONSES[label]
        check(f"{label} reply is a fixed non-empty string",
              isinstance(msg, str) and len(msg) > 20)
    check("exactly three replies exist", len(C.RESPONSES) == 3)
    check("decision label is 'conversational'", C.DECISION == "conversational")

    r = C.respond("hi")
    check("respond() carries mode, label, message and reasons",
          r is not None and r["mode"] == "conversational" and r["conversational"] == "GREETING"
          and r["message"] == C.RESPONSES["GREETING"] and bool(r["reasons"]))
    r = C.respond("all good, running fine")
    check("respond() names the healthy phrase it matched",
          r is not None and any("healthy" in x or "all good" in x for x in r["reasons"]),
          str(r["reasons"]) if r else "None")
    check("respond() returns None for a fault report",
          C.respond("starts fine but black smoke under load") is None)

    print("\n-- determinism --")
    probes = [q for q, _ in SHOULD_FIRE] + MUST_NOT_FIRE
    once = [C.classify(q) for q in probes]
    twice = [C.classify(q) for q in probes]
    check("identical output on repeat", once == twice)
    check("no model is imported by the module",
          not any(m in sys.modules for m in ("llama_cpp", "sentence_transformers")))

    n = sum(RESULTS)
    print(f"\n==== CONVERSATIONAL: {n}/{len(RESULTS)} passed "
          f"({len(SHOULD_FIRE)} should-fire, {len(MUST_NOT_FIRE)} must-not-fire) ====")
    return 0 if n == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
