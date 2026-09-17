"""
Phase 9.3b — code-handling hardening tests.

    PYTHONPATH=src .venv/bin/python src/test_code_hardening.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    from cli import quiet_stderr
    with quiet_stderr():
        from retrieve import Retriever, normalize_code_tokens
        import advise as V
        import answer as A
        R = Retriever()

    codes = lambda o: [i["record"]["code_full"] for i in o["results"]]

    # 1. normalisation of unambiguous corrupted forms
    for q in ("P 0192-00", "P0192_00", "PO192-00", "P0192-O0", "P0192.00", "p0192-00"):
        o = R.retrieve(q)
        check(f"{q!r} normalises to the exact code", o["mode"] == "exact_code"
              and codes(o) == ["P0192-00"], f"mode={o['mode']} got={codes(o)[:3]}")
    for q in ("the pool", "POOF", "Upto 2000 rpm", "what does connector C001 do"):
        check(f"{q!r} is not rewritten", normalize_code_tokens(q)[0] == q)

    # never "correct" a transposed / dropped digit
    o = R.retrieve("P0912-00")
    check("transposed digit is NOT auto-corrected; refused with did-you-mean",
          o["mode"] == "unknown_code" and o["results"] == []
          and "P0192-00" in o["trace"]["did_you_mean"], f"{o['mode']} {o['trace'].get('did_you_mean')}")

    # 2. unknown well-formed P/U code -> explicit refusal
    for q in ("P3A7F-00", "P26FB-47", "U3FFF-00", "fault P3A7F"):
        o = R.retrieve(q)
        check(f"{q!r} -> unknown_code refusal", o["mode"] == "unknown_code" and not o["results"]
              and "not covered in this manual" in o["trace"]["message"], o["mode"])
    out = A.answer("P3A7F-00", R, phraser=None)
    check("answer() refuses deterministically, no LLM", out["path"] == "deterministic_refusal"
          and out["text"].startswith("DTC P3A7F-00 is not covered"), out["path"])

    # C/B connector tokens keep the hybrid fallback
    o = R.retrieve("what does connector C001 do")
    check("C001 connector token still falls back to hybrid", o["mode"] == "hybrid"
          and len(o["results"]) > 0 and "fallback" in o["trace"], o["mode"])

    # 3. base exists, suffix does not -> clarification, not an answer
    o = R.retrieve("P1000-9C")
    check("P1000-9C -> suffix_not_found listing known variants",
          o["mode"] == "suffix_not_found" and o["trace"]["known_variants"] == ["P1000-00"]
          and "P0100-9C" in o["trace"]["did_you_mean"], f"{o['mode']} {o['trace'].get('message')}")
    out = A.answer("P1000-9C", R, phraser=None)
    check("answer() gives a clarification with no procedure",
          out["path"] == "deterministic_clarification" and "Troubleshooting steps" not in out["text"]
          and out["citations"] == [], out["path"])
    res = V.advise("P1000-9C", R)
    check("advise() returns clarify_code with no fix blocks",
          res["mode"] == "clarify_code" and res["results"] == [], res["mode"])
    res = V.advise("P3A7F-00", R)
    check("advise() refuses an unknown code", res["mode"] == "refused" and res["results"] == [])

    # unchanged legitimate behaviour
    check("base code P0100 still lists its 3 variants",
          sorted(codes(R.retrieve("P0100"))) == ["P0100-00", "P0100-9B", "P0100-9C"])
    check("duplicated code P0180-11 still returns both records",
          len(R.retrieve("P0180-11")["results"]) == 2)

    passed = sum(RESULTS)
    print(f"\n==== CODE HARDENING: {passed}/{len(RESULTS)} passed ====")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
