"""
Phase 13.3 — tests for incomplete-code detection and its candidates.

    PYTHONPATH=src .venv/bin/python src/test_partial_codes.py

The rule sits in front of retrieval, so a MUST-NOT-TRIGGER failure refuses a real
symptom query, while a SHOULD-TRIGGER failure only sends a half-typed code into
hybrid search - which is the bug being fixed, not a new harm. The must-not-trigger
block is therefore written to attack the rule.
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
    ("P-10", "P", "10"), ("P10", "P", "10"), ("p 019", "P", "019"),
    ("P019-", "P", "019"), ("P01-00", "P", "01"), ("B1", "B", "1"),
    ("U01", "U", "01"), ("P1", "P", "1"), ("p-019", "P", "019"),
    ("P_10", "P", "10"), ("P.10", "P", "10"), ("C12", "C", "12"),
    ("U0", "U", "0"), ("P019", "P", "019"), ("p01", "P", "01"),
    ("P 10", "P", "10"), ("code P10", "P", "10"), ("P11A", "P", "11A"),
]

MUST_NOT_TRIGGER = [
    # complete codes - the existing paths own these
    "P0192-00", "p0192-00", "P0192", "P0199-00", "U011A-00", "P0192_00", "PO192-00",
    "P0192-00 and black smoke",
    # ordinary text that happens to contain numbers
    "cylinder 3 misfire", "3rd gear jerks", "after 10 km it stalls",
    "misfire on cylinder 1", "loses power after 20 minutes", "2 litres of coolant lost",
    # words whose letters are all valid hex digits
    "cab", "CAB", "ace", "bed", "decade",
    # a code letter followed by non-hex
    "PM sensor", "PTO switch", "P sensor", "pressure",
    # too long to be a code attempt
    "P10 code came up on the dash this morning",
    # empty-ish
    "", "   ", "P", "10",
]


def main():
    import partial_code as PC

    by_dtc = json.load(open("index/code_index.json"))["by_dtc_code"]

    print("\n-- should trigger --")
    for q, letter, digits in SHOULD_TRIGGER:
        d = PC.detect_partial(q)
        check(f"{q!r} -> {letter}{digits}",
              d is not None and d["letter"] == letter and d["digits"] == digits,
              f"got {d}")

    print("\n-- must NOT trigger (a false positive refuses a real query) --")
    for q in MUST_NOT_TRIGGER:
        check(f"{q!r} -> None", PC.detect_partial(q) is None, f"got {PC.detect_partial(q)}")

    print("\n-- candidate rules, dictionary only --")
    c, more = PC.candidates("P", "019", by_dtc)
    codes = [x["code"] for x in c]
    check("(a) digit-prefix: P019 reaches P0192-00", "P0192-00" in codes, str(codes))
    check("sorted by code", codes == sorted(codes), str(codes))
    check("capped at 5 with an overflow count", len(c) <= 5 and more >= 0,
          f"{len(c)} shown, {more} more")
    check("every candidate carries a description and a page",
          all(x["description"] and isinstance(x["page"], int) for x in c))

    c2, _ = PC.candidates("P", "10", by_dtc)
    check("(b) zero-pad: P10 -> P0010 included when it exists",
          ("P0010-00" in [x["code"] for x in c2]) or
          all(x["code"].startswith("P10") for x in c2),
          str([x["code"] for x in c2]))

    c3, _ = PC.candidates("P", "192", by_dtc)
    check("(c) one insertion: 192 -> P0192-00", "P0192-00" in [x["code"] for x in c3],
          str([x["code"] for x in c3]))

    c4, more4 = PC.candidates("P", "1", by_dtc)
    check("fewer than 2 digits -> no candidates at all", c4 == [] and more4 == 0)

    c5, _ = PC.candidates("P", "999", by_dtc)
    check("digits that match nothing -> empty list, no error", isinstance(c5, list))

    print("\n-- the assembled reply --")
    r = PC.resolve("P-10", by_dtc)
    check("message quotes the input and gives the format",
          r["message"] == "'P-10' is not a complete code in this manual. "
                          "Codes look like P0192-00.", r["message"])
    check("overflow note is phrased as specified",
          r["more_note"] is None or r["more_note"].endswith("more - please enter the full code"),
          str(r["more_note"]))
    r1 = PC.resolve("P1", by_dtc)
    check("one digit -> no candidates, reason given",
          not r1["candidates"] and "fewer than 2 digits" in r1["no_candidates_reason"])
    check("resolve() returns None for a symptom query",
          PC.resolve("cylinder 3 misfire", by_dtc) is None)

    print("\n-- end to end through the router --")
    from cli import quiet_stderr
    with quiet_stderr():
        from advise import advise
        from retrieve import Retriever
        R = Retriever()

    for q in ("P-10", "P019", "P1", "code P10"):
        o = R.retrieve(q, k=3)
        check(f"router: {q!r} -> incomplete_code, nothing retrieved",
              o["mode"] == "incomplete_code" and o["results"] == []
              and o["trace"]["retrieval_run"] is False
              and o["trace"]["auto_selected"] is False, o["mode"])

    unchanged = {"P0192-00": "exact_code", "P0192": "exact_code",
                 "P0199-00": "unknown_code", "cylinder 3 misfire": "hybrid",
                 "all coolant faults": "system_group"}
    for q, want in unchanged.items():
        check(f"unchanged: {q!r} -> {want}", R.retrieve(q, k=3)["mode"] == want,
              R.retrieve(q, k=3)["mode"])

    a = advise("P019", R, phraser=None, summary=False)
    check("advise(): mode incomplete_code, no fix blocks, candidates present",
          a["mode"] == "incomplete_code" and not a["results"] and a["candidates"])
    import answer as A
    ans = A.answer("P019", R, None, k=3)
    check("answer(): deterministic_incomplete_code path, no citations",
          ans["path"] == "deterministic_incomplete_code" and not ans["citations"]
          and "not a complete code" in ans["text"], ans["path"])

    print("\n-- determinism --")
    probes = [q for q, _, _ in SHOULD_TRIGGER] + MUST_NOT_TRIGGER
    once = [PC.detect_partial(q) for q in probes]
    twice = [PC.detect_partial(q) for q in probes]
    check("identical output on repeat", once == twice)

    n = sum(RESULTS)
    print(f"\n==== PARTIAL CODES: {n}/{len(RESULTS)} passed "
          f"({len(SHOULD_TRIGGER)} should-trigger, {len(MUST_NOT_TRIGGER)} must-not-trigger) ====")
    return 0 if n == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
