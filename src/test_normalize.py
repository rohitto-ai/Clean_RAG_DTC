"""
Phase 9.4 — tests for the synthetic SPN/FMI normalization ladder.

    PYTHONPATH=src .venv/bin/python src/test_normalize.py

These check the METHOD's branch coverage and its safety rules on synthetic data.
They are not an accuracy measurement.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    from cli import quiet_stderr
    with quiet_stderr():
        from retrieve import Retriever
        import normalize as N
        R = Retriever()
        Z = N.Normalizer(R)

    row = lambda **kw: {"timestamp": "2026-03-02T08:00:00Z", "vehicle_id": "SYN-VEH-0001",
                        "spn": 520210, "fmi": 4, "occurrences": 1, **kw}

    # every outcome the ladder can produce, from the synthetic log
    results = {r["line"]: r for r in (dict(Z.normalize(x), line=x["line"]) for x in N.load_log())}
    got = {r["outcome"] for r in results.values()}
    check("synthetic log exercises every ladder outcome",
          got == set(N.OUTCOMES), f"missing={set(N.OUTCOMES) - got}")

    # R1 complete mapping -> advisory carrying real manual content
    Z.seen.clear()
    r = Z.normalize(row())
    check("R1 complete mapping -> ADVISORY for P0192-00",
          r["outcome"] == "ADVISORY" and r["resolved_code"] == "P0192-00", r["outcome"])
    fb = N.advisory_for(r, R)[0]
    check("advisory reuses the Phase 9.1 fix block (real manual steps + citation)",
          fb["code_full"] == "P0192-00" and len(fb["steps"]) > 5
          and fb["citation"] == "P0192-00, manual page 8", f"steps={len(fb['steps'])}")
    check("low byte is the manual suffix, not assumed 00",
          Z.normalize(row(fmi=1, spn=520240, timestamp="2026-03-02T08:00:01Z"))["resolved_code"]
          == "P0100-9C")

    # R1 -> 9.3b refusal / clarification, never fabrication
    r = Z.normalize(row(spn=520260, timestamp="2026-03-02T08:00:02Z"))
    check("mapped P-code absent from the manual -> explicit refusal, no advisory",
          r["outcome"] == "REFUSED_NOT_IN_MANUAL" and "not covered in this manual" in r["message"]
          and N.advisory_for(r, R) is None, r["outcome"])
    r = Z.normalize(row(spn=520220, fmi=16, timestamp="2026-03-02T08:00:03Z"))
    check("mapped low byte absent -> clarification listing known variants, no advisory",
          r["outcome"] == "CLARIFY_LOW_BYTE" and r["known_variants"] == ["P0116-00"]
          and N.advisory_for(r, R) is None, r["outcome"])

    # R2 fallback: candidates only, nearest marked, never auto-advised
    r = Z.normalize(row(fmi=5, timestamp="2026-03-02T08:00:04Z"))
    near = [c for c in r["candidates"] if c["nearest"]]
    check("R2 unmapped FMI -> FALLBACK_CANDIDATES, nearest FMI marked, no advisory",
          r["outcome"] == "FALLBACK_CANDIDATES" and len(near) == 1 and near[0]["fmi"] == 4
          and r["resolved_code"] is None and N.advisory_for(r, R) is None,
          f"{r['outcome']} nearest={near}")
    check("fallback policy is explicit and off", N.ADVISE_ON_FALLBACK is False)

    # R3 unknown SPN
    r = Z.normalize(row(spn=520299, timestamp="2026-03-02T08:00:05Z"))
    check("R3 unknown SPN -> UNMAPPED_NO_ADVISORY, logged",
          r["outcome"] == "UNMAPPED_NO_ADVISORY" and r["resolved_code"] is None, r["outcome"])

    # R0 validation and de-duplication
    bad = [("non-integer spn", row(spn="abc")), ("fmi out of range", row(fmi=40)),
           ("fmi missing", {k: v for k, v in row().items() if k != "fmi"}),
           ("spn beyond 19 bits", row(spn=600000)), ("negative occurrences", row(occurrences=-2)),
           ("impossible date", row(timestamp="2026-02-31T12:00:00Z")),
           ("empty vehicle_id", row(vehicle_id=""))]
    for name, br in bad:
        r = Z.normalize(br)
        check(f"R0 rejects {name}", r["outcome"] == "REJECTED_MALFORMED", r["outcome"])
    Z.seen.clear()
    first = Z.normalize(row(timestamp="2026-03-02T08:00:06Z"))
    dup = Z.normalize(row(timestamp="2026-03-02T08:00:06Z"))
    check("R0 skips an exact duplicate row",
          first["outcome"] == "ADVISORY" and dup["outcome"] == "DUPLICATE_SKIPPED")

    # determinism + full trace
    Z.seen.clear()
    a = Z.normalize(row())
    Z.seen.clear()
    b = Z.normalize(row())
    check("deterministic: identical trace on repeat", a == b)
    check("every result carries the ladder trace and the synthetic label",
          all(x["ladder"] and x["label"] == N.LABEL for x in results.values()))

    # dictionary validation
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "conflict.json")
        e = {"spn": 520210, "fmi": 4, "description": "x", "p_code": "P0192", "dtc_low_byte": "00"}
        json.dump({"entries": [e, {**e, "p_code": "P0193"}]}, open(p, "w"))
        try:
            N.load_dictionary(p)
            ok = False
        except N.DictionaryError:
            ok = True
        check("conflicting dictionary mappings are rejected", ok)
        p2 = os.path.join(d, "bad.json")
        json.dump({"entries": [{**e, "dtc_low_byte": "ZZ"}]}, open(p2, "w"))
        try:
            N.load_dictionary(p2)
            ok = False
        except N.DictionaryError:
            ok = True
        check("malformed dtc_low_byte is rejected", ok)

    passed = sum(RESULTS)
    print(f"\n==== NORMALIZE: {passed}/{len(RESULTS)} passed ====")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
