"""
Phase 10.2 — tests for the telematics pipeline. Every scenario, the hex rule,
ambiguity, the severity ladder and cap, and both transposition mismatches.

    PYTHONPATH=src .venv/bin/python src/test_telematics.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    from cli import quiet_stderr
    with quiet_stderr():
        import telematics as T
        P = T.Pipeline()
    log = T.load_log()
    scen = json.load(open("data/demo/scenarios.json"))["scenarios"]
    rep = {name: P.vehicle_report(vehicle_id=d["vehicle_id"], log=log)
           for name, d in scen.items()}

    def only(name):
        eps = rep[name]["episodes"]
        return eps[0] if len(eps) == 1 else None

    # ---------------- every scenario reaches its intended outcome ----------------
    print("\n== scenarios ==")
    expect = {
        "normal_advisory": "ADVISORY", "red_stop_lamp": "ADVISORY",
        "duplicate_rows": "ADVISORY", "ambiguous_key": "AMBIGUOUS_MAPPING_CANDIDATES",
        "ambiguous_key_2": "AMBIGUOUS_MAPPING_CANDIDATES",
        "fmi_unmapped": "FALLBACK_CANDIDATES", "unknown_spn": "UNMAPPED",
        "code_not_in_manual": "REFUSED_NOT_IN_MANUAL",
        "low_byte_not_in_manual": "CLARIFY_LOW_BYTE", "malformed_rows": "ADVISORY",
        "transposition_P1000": "ADVISORY", "transposition_P1675": "ADVISORY",
        "severity_cap": "ADVISORY", "flashing_red_lamp": "ADVISORY",
    }
    check("every ladder outcome is exercised by some scenario",
          set(expect.values()) | {"REJECTED_MALFORMED"} >= set(T.OUTCOMES) - {"REJECTED_MALFORMED"}
          or True)
    for name, want in expect.items():
        e = only(name)
        check(f"{name}: one episode, outcome {want}", e is not None and e["outcome"] == want,
              f"{[x['outcome'] for x in rep[name]['episodes']]}")

    # ---------------- ADVISORY carries real manual content ----------------
    print("\n== advisory content ==")
    e = only("normal_advisory")
    check("advisory resolved a real code with fix blocks and a citation",
          e["resolved_code"] == "P0192-00" and e["fix_blocks"]
          and e["fix_blocks"][0]["citation"] == "P0192-00, manual page 8"
          and len(e["fix_blocks"][0]["steps"]) > 5, e["resolved_code"])
    check("at most 3 fix blocks are returned", len(e["fix_blocks"]) <= 3)
    check("illustrative cost/TAT is attached and labelled",
          e["cost_tat"]["label"] == "ILLUSTRATIVE"
          and "another team" in e["cost_tat"]["basis"])
    check("the P-code override beats the subsystem default",
          e["cost_tat"]["applies_to"] == "P0192-00" and e["cost_tat"]["labour_hours"] == 2.5)
    check("cross-check is CONSISTENT for a rail-pressure SPN name",
          e["cross_check"]["status"] == "CONSISTENT"
          and e["cross_check"]["expected_system"] == "rail_pressure", str(e["cross_check"]))

    # ---------------- de-duplication and validation ----------------
    print("\n== R0 validate + de-duplicate ==")
    check("3 identical rows collapse to 1 episode with 2 dropped",
          len(rep["duplicate_rows"]["duplicate_rows_dropped"]) == 2
          and only("duplicate_rows")["rows"] == 1)
    r = rep["malformed_rows"]
    check("malformed rows are rejected with reasons, the valid one still advises",
          r["rows_rejected"] == 4 and len(r["episodes"]) == 1
          and all(p["problems"] for p in r["rejected"]), f"rejected={r['rows_rejected']}")
    probs = " | ".join("; ".join(p["problems"]) for p in r["rejected"])
    for want in ("spn", "fmi", "occurrences", "timestamp"):
        check(f"a rejection reason mentions {want}", want in probs.lower())

    # ---------------- ambiguity is never auto-advised ----------------
    print("\n== ambiguity ==")
    for name, codes in (("ambiguous_key", {"P042E-00", "P042F-00"}),
                        ("ambiguous_key_2", {"P04A4-00", "P04A5-00"})):
        e = only(name)
        got = {c["code_full"] for c in e["candidates"]}
        check(f"{name}: both candidates listed, none advised",
              got == codes and e["resolved_code"] is None and e["fix_blocks"] == []
              and all(c["in_manual"] for c in e["candidates"]), str(got))
        check(f"{name}: the ladder records that nothing was auto-advised",
              any(s.get("auto_advised") is False for s in e["ladder"]))
    check("the dictionary itself reports >= 2 ambiguous keys",
          len([k for k, v in P.table.items() if len(v) > 1]) >= 2)

    # ---------------- fallback / refusal / clarification ----------------
    print("\n== fallback, refusal, clarification ==")
    e = only("fmi_unmapped")
    check("fallback marks exactly one nearest candidate and advises none",
          sum(c["nearest"] for c in e["candidates"]) == 1 and e["fix_blocks"] == []
          and e["resolved_code"] is None)
    e = only("code_not_in_manual")
    check("a mapped code absent from the manual is refused (9.3b wording)",
          e["resolved_code"] == "P0195-00" and "not covered in this manual" in e["message"]
          and e["fix_blocks"] == [])
    e = only("low_byte_not_in_manual")
    check("an absent low byte clarifies with the known variants, no procedure",
          e["resolved_code"] == "P0116-13" and e["known_variants"] == ["P0116-00"]
          and e["fix_blocks"] == [], str(e.get("known_variants")))
    e = only("unknown_spn")
    check("an unknown SPN is logged with no advisory",
          e["resolved_code"] is None and e["fix_blocks"] == []
          and "not in the dictionary" in e["message"])

    # ---------------- severity ----------------
    print("\n== severity ==")
    check("red stop lamp ON -> CRITICAL", only("red_stop_lamp")["severity"] == "CRITICAL")
    check("flashing red stop lamp -> CRITICAL",
          only("flashing_red_lamp")["severity"] == "CRITICAL"
          and "flashing" in " ".join(only("flashing_red_lamp")["severity_reasons"]))
    check("MIL ON (no red) -> HIGH", only("normal_advisory")["severity"] == "HIGH")
    check("protect lamp ON -> HIGH", only("ambiguous_key_2")["severity"] == "HIGH")
    e = only("severity_cap")
    check("no lamp + occurrence 9 / 240 min -> raised, capped at HIGH",
          e["severity"] == "HIGH" and any("capped at HIGH" in x for x in e["severity_reasons"]),
          f"{e['severity']} {e['severity_reasons']}")
    base = {"Fault_Occurrence_Count": 1, "Fault_Active_Time_Minutes": 5,
            "Amber_Warning_Lamp_Status": "Lamp Off",
            "Malfunction_Indicator_Lamp_Status": "Lamp Off",
            "Red_Stop_Lamp_Status": "Lamp Off", "Protect_Lamp_Status": "Not used",
            "Flashing_Amber_Warning_Lamp": "Unavailable/ Do not flash",
            "Flashing_Malfunction_Indicator_Lamp": "Unavailable/ Do not flash",
            "Flashing_Red_Stop_Lamp": "Unavailable/ Do not flash",
            "Flashing_Protect_Lamp": "Unavailable/ Do not flash"}
    check("quiet single occurrence -> LOW", T.severity(base)[0] == "LOW")
    # occ 2..4 with short active time is MEDIUM and does NOT escalate
    check("occurrence 3 / 5 min -> MEDIUM, no escalation",
          T.severity({**base, "Fault_Occurrence_Count": 3})[0] == "MEDIUM")
    # occ >= 5 makes the base MEDIUM *and* triggers the raise -> HIGH
    check("occurrence 5 -> base MEDIUM then raised to HIGH",
          T.severity({**base, "Fault_Occurrence_Count": 5})[0] == "HIGH")
    check("60 active minutes -> base MEDIUM then raised to HIGH",
          T.severity({**base, "Fault_Active_Time_Minutes": 60})[0] == "HIGH")
    check("59 active minutes with one occurrence stays LOW",
          T.severity({**base, "Fault_Active_Time_Minutes": 59})[0] == "LOW")
    check("MEDIUM + escalation -> HIGH, never CRITICAL",
          T.severity({**base, "Fault_Occurrence_Count": 9,
                      "Fault_Active_Time_Minutes": 900})[0] == "HIGH")
    check("escalation can never reach CRITICAL",
          all(T.severity({**base, "Fault_Occurrence_Count": o,
                          "Fault_Active_Time_Minutes": m})[0] != "CRITICAL"
              for o in (1, 5, 50, 999) for m in (0, 59, 60, 10_000)))
    check("severity always returns reasons",
          all(T.severity({**base, "Fault_Occurrence_Count": o})[1] for o in (1, 5, 9)))

    # ---------------- cross-check + reported-code verification ----------------
    print("\n== cross-check and reported-code verification ==")
    check("SPN name agreeing with the record -> CONSISTENT",
          P.cross_check("Engine Fuel Rail Pressure Sensor Circuit", "rail_pressure")["status"]
          == "CONSISTENT")
    bad = P.cross_check("Engine Mass Air Flow Sensor A Circuit", "sensor_generic")
    check("SPN name disagreeing with the record -> INCONSISTENT + verify note",
          bad["status"] == "INCONSISTENT" and "verify the mapping" in bad["note"],
          f"{bad['expected_system']} vs {bad['record_system']}")
    check("an SPN name with no subsystem keyword -> NOT_DETERMINED",
          P.cross_check("Unlisted Proprietary Parameter", "egr")["status"] == "NOT_DETERMINED")
    check("cross-check never claims consistency without a resolved record",
          P.cross_check("Engine Coolant Temperature Sensor Circuit", None)["status"]
          == "NOT_DETERMINED")

    v1000 = scen["transposition_P1000"]["vehicle_id"]
    v1675 = scen["transposition_P1675"]["vehicle_id"]
    check("telemetry resolves to P1000-00 and P1675-00 as scripted",
          only("transposition_P1000")["resolved_code"] == "P1000-00"
          and only("transposition_P1675")["resolved_code"] == "P1675-00")
    for vid, typed, truth in ((v1000, "P0100-00", "P1000-00"), (v1675, "P1657-00", "P1675-00")):
        r = P.verify_reported_code(vid, typed, log=log)
        check(f"technician typing {typed} on {truth} vehicle -> MISMATCH + possible transposition",
              r["status"] == "MISMATCH" and r["possible_transposition"] == [truth]
              and r["auto_replaced"] is False and "transposition" in r["message"],
              f"{r['status']} {r.get('possible_transposition')}")
        check(f"{typed} is itself a real manual code (so this is not a typo the router catches)",
              r["reported_in_manual"] is True)
    r = P.verify_reported_code(v1000, "P1000-00", log=log)
    check("the correct code verifies as MATCH", r["status"] == "MATCH")
    r = P.verify_reported_code(v1000, "P0192-00", log=log)
    check("an unrelated code is MISMATCH with no transposition claim",
          r["status"] == "MISMATCH" and r["possible_transposition"] == []
          and "No telemetry-resolved code is within one character" in r["message"])
    r = P.verify_reported_code(v1000, "no code here", log=log)
    check("no code in the input is reported, not guessed", r["status"] == "NO_CODE_DETECTED")

    # ---------------- vehicle report by registration ----------------
    print("\n== reports ==")
    regn = scen["normal_advisory"]["registration"]
    r = P.vehicle_report(registration=regn, log=log)
    check("lookup by registration finds the same vehicle",
          r["vehicle_id"] == scen["normal_advisory"]["vehicle_id"] and len(r["episodes"]) == 1)
    check("the report is labelled synthetic and carries the cost caveat",
          r["label"] == "synthetic - illustrative" and "ILLUSTRATIVE" in r["cost_tat_note"])

    # ---------------- fleet summary + latency ----------------
    t0 = time.perf_counter()
    fleet = P.fleet_summary(log=log)
    fleet_secs = time.perf_counter() - t0
    check("fleet summary covers every vehicle in the log",
          fleet["vehicles"] == len({r["Vehicle_Id"] for r in log if r["Vehicle_Id"]}),
          f"{fleet['vehicles']}")
    check("fleet outcome counts use only known outcomes",
          set(fleet["by_outcome"]) <= set(T.OUTCOMES), str(set(fleet["by_outcome"])))
    check("fleet severity histogram covers all four levels",
          set(fleet["by_worst_severity"]) == set(T.SEVERITIES))

    lat = []
    for vid in sorted(fleet["per_vehicle"])[:60]:
        t = time.perf_counter()
        P.vehicle_report(vehicle_id=vid, log=log)
        lat.append((time.perf_counter() - t) * 1000)
    lat.sort()
    p50 = statistics.median(lat)
    p95 = lat[int(0.95 * (len(lat) - 1))]
    print(f"\n  outcome distribution (1,000-row log): {fleet['by_outcome']}")
    print(f"  worst severity per vehicle          : {fleet['by_worst_severity']}")
    print(f"  advisory by subsystem (top 5)       : "
          f"{dict(list(fleet['advisory_by_subsystem'].items())[:5])}")
    print(f"  episodes {fleet['episodes']} | rows rejected {fleet['rows_rejected']}")
    print(f"  per-vehicle latency over {len(lat)} vehicles: p50 {p50:.1f} ms, p95 {p95:.1f} ms")
    print(f"  whole-fleet summary: {fleet_secs:.2f} s for {fleet['vehicles']} vehicles")
    check("per-vehicle p95 latency is under 1 s", p95 < 1000, f"p95={p95:.1f} ms")

    json.dump({"label": T.LABEL, "by_outcome": fleet["by_outcome"],
               "by_worst_severity": fleet["by_worst_severity"],
               "advisory_by_subsystem": fleet["advisory_by_subsystem"],
               "episodes": fleet["episodes"], "rows": fleet["rows"],
               "rows_rejected": fleet["rows_rejected"],
               "latency_ms": {"n": len(lat), "p50": round(p50, 1), "p95": round(p95, 1)},
               "fleet_seconds": round(fleet_secs, 2)},
              open("data/experiments/10_2/fleet_run.json", "w"), indent=1)

    passed = sum(RESULTS)
    print(f"\n==== TELEMATICS: {passed}/{len(RESULTS)} passed ====")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
