"""
Phase 13.4 — tests for over-long / malformed code tokens.

    PYTHONPATH=src .venv/bin/python src/test_invalid_codes.py

The rule sits in front of retrieval but BEHIND the 9.3 extraction of an embedded
valid code, so the must-not-trigger block is mostly about proving that the
existing paths still own what they owned: every log-embedded form, every valid
code, every 13.3 partial, and ordinary text.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


SHOULD_TRIGGER = [
    "P1023473efa234rgddhdhdfgddhy",      # the reported bug
    "P99999999",                         # all hex, but too long
    "U0100zzzz",                         # illegal characters
    "code P1023473efa",                  # named, long query scope
    "P0192abcdefgh",                     # first five ARE a base -> variants offered
    "B1234567890",
    "C0001xxxx",
    "U011Azzz",
    "P1023473efa234rgddhdhdfgddhy please",
    "fault P99999999",
    "P0000000000000000000000000000",
    "p1023473EFA",                       # lowercase
    "P12#34",                            # illegal character, short
]

MUST_NOT_TRIGGER = [
    # 9.3 embedded-log forms: a valid code IS extracted, so these keep exact_code
    "DTC=P0192-00;ts=1230",
    "P0192-00@08:15",
    "2026-03-03 10:14 P0192-00 active",
    "[ECU] P0192-00 | MIL=ON",
    "code:P0192-00,count=3",
    "P0192-00xyz123abc",                 # base P0192 IS extracted by 9.3 -> exact_code
    "P0192-00-00-00",                    # P0192-00 IS extracted (word boundary at the
                                         # second "-"), so the existing path owns it
    # valid codes of every shape
    "P0192-00", "p0192-00", "P0192", "U011A-00", "P203B-85", "PO192-00", "P0192_00",
    # 13.3 partials still belong to incomplete_code
    "P10", "P-10", "P019", "P1", "code P019 today",
    # ordinary text
    "P10 came up on the dash", "PM sensor", "cylinder 3 misfire", "1500 rpm surge",
    "after 10 km it stalls", "no issue, the vehicle is running fine",
    "", "   ",
]


def main():
    import partial_code as PC

    by_dtc = json.load(open("index/code_index.json"))["by_dtc_code"]

    print("\n-- should trigger (detector level) --")
    for q in SHOULD_TRIGGER:
        d = PC.detect_invalid(q)
        check(f"{q[:34]!r} -> invalid token", d is not None, f"got {d}")

    print("\n-- must NOT trigger (detector level) --")
    for q in MUST_NOT_TRIGGER:
        # the detector alone cannot know whether 9.3 extracted a code, so forms that
        # carry a valid code are checked end-to-end below instead
        if any(v in q for v in ("P0192-00", "P0192", "U011A-00", "P203B-85", "PO192-00")):
            continue
        check(f"{q[:34]!r} -> None", PC.detect_invalid(q) is None, f"got {PC.detect_invalid(q)}")

    print("\n-- the assembled reply --")
    r = PC.resolve_invalid("P1023473efa234rgddhdhdfgddhy", by_dtc)
    check("message truncates the token to 20 characters",
          r["message"].startswith("'P1023473efa234rgddhd…' is not a valid fault code."),
          r["message"])
    check("message gives the format", "look like P0192-00" in r["message"])
    check("P1023 is not a base in this manual -> no candidates, reason given",
          not r["candidates"] and "not a code base" in r["no_candidates_reason"],
          str(r["no_candidates_reason"]))
    r2 = PC.resolve_invalid("P0192abcdefgh", by_dtc)
    check("first five ARE a base -> its variants are offered with descriptions",
          [c["code"] for c in r2["candidates"]] == ["P0192-00"]
          and r2["candidates_note"] == "Codes starting with P0192:"
          and all(c["description"] for c in r2["candidates"]),
          str(r2["candidates"]))
    check("candidates are capped at 5", len(r2["candidates"]) <= 5)
    r3 = PC.resolve_invalid("U0100zzzz", by_dtc)
    check("illegal characters are recorded", r3["invalid"]["bad_characters"] == ["Z"],
          str(r3["invalid"]))

    print("\n-- end to end through the router --")
    from cli import quiet_stderr
    with quiet_stderr():
        import answer as A
        from advise import advise
        from retrieve import Retriever
        R = Retriever()

    for q in SHOULD_TRIGGER:
        o = R.retrieve(q, k=3)
        check(f"router: {q[:30]!r} -> invalid_code, nothing retrieved",
              o["mode"] == "invalid_code" and o["results"] == []
              and o["trace"]["retrieval_run"] is False, o["mode"])

    expected = {
        "DTC=P0192-00;ts=1230": "exact_code", "P0192-00@08:15": "exact_code",
        "2026-03-03 10:14 P0192-00 active": "exact_code",
        "[ECU] P0192-00 | MIL=ON": "exact_code", "code:P0192-00,count=3": "exact_code",
        "P0192-00xyz123abc": "exact_code", "P0192-00-00-00": "exact_code",
        "P0192-00": "exact_code", "P0192": "exact_code",
        "U011A-00": "exact_code", "P203B-85": "exact_code", "PO192-00": "exact_code",
        "P0192_00": "exact_code",
        "P10": "incomplete_code", "P-10": "incomplete_code", "P019": "incomplete_code",
        "P1": "incomplete_code", "code P019 today": "incomplete_code",
        "PM sensor": "hybrid", "cylinder 3 misfire": "hybrid", "1500 rpm surge": "hybrid",
        "after 10 km it stalls": "hybrid", "P10 came up on the dash": "hybrid",
    }
    for q, want in expected.items():
        got = R.retrieve(q, k=3)["mode"]
        check(f"unchanged: {q[:32]!r} -> {want}", got == want, got)

    a = advise("P99999999", R, phraser=None, summary=False)
    check("advise(): mode invalid_code, no fix blocks",
          a["mode"] == "invalid_code" and not a["results"] and a["message"])
    ans = A.answer("P99999999", R, None, k=3)
    check("answer(): deterministic_invalid_code path, no citations",
          ans["path"] == "deterministic_invalid_code" and not ans["citations"], ans["path"])

    print("\n-- determinism --")
    probes = SHOULD_TRIGGER + MUST_NOT_TRIGGER
    check("identical output on repeat",
          [PC.detect_invalid(q) for q in probes] == [PC.detect_invalid(q) for q in probes])

    n = sum(RESULTS)
    print(f"\n==== INVALID CODES: {n}/{len(RESULTS)} passed "
          f"({len(SHOULD_TRIGGER)} should-trigger, {len(MUST_NOT_TRIGGER)} must-not-trigger) ====")
    return 0 if n == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
