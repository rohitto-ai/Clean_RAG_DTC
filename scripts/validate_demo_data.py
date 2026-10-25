"""
Phase 10.2 — validate the generated synthetic demo data. Exit 1 on any failure.

    PYTHONPATH=src .venv/bin/python scripts/validate_demo_data.py

Checks the data CONTRACT, not the pipeline: exact column names, the decimal->hex
low-byte rule, SPN range, FMI range, that every intended target resolves in the
manual (and that the two deliberate edge entries do NOT), the ambiguous keys, the
lamp vocabulary, the duplicate fraction, and that .csv and .xlsx agree.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

DEMO = "data/demo"
FAILURES = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def main():
    import telematics as T
    from gen_demo_data import DICT_COLUMNS, LOG_COLUMNS, FMI_MEANING, SPN_BASE, SPN_MAX, LABEL

    print("== files ==")
    for f in ("synthetic_spn_fmi_dictionary.csv", "synthetic_spn_fmi_dictionary.xlsx",
              "synthetic_fleet_log.csv", "synthetic_fleet_log.xlsx",
              "cost_tat_rules.csv", "scenarios.json", "README.md"):
        check(f"{f} exists", os.path.exists(f"{DEMO}/{f}"))

    print("\n== dictionary contract ==")
    dcsv = list(csv.DictReader(open(f"{DEMO}/synthetic_spn_fmi_dictionary.csv")))
    check("columns are EXACTLY the required ones",
          list(dcsv[0].keys()) == DICT_COLUMNS, str(list(dcsv[0].keys())))
    check("at least 60 entries", len(dcsv) >= 60, f"{len(dcsv)}")
    check("at least 12 distinct SPN names (subsystems)",
          len({r["SPN_Name"] for r in dcsv}) >= 12, f"{len({r['SPN_Name'] for r in dcsv})}")
    check("every SPN is in the J1939 proprietary range",
          all(SPN_BASE <= int(r["SPN"]) <= SPN_MAX for r in dcsv))
    check("every FMI is 0..31 with a public J1939-73 meaning",
          all(0 <= int(r["FMI"]) <= 31 and int(r["FMI"]) in FMI_MEANING for r in dcsv))
    check("DTC_LB is decimal (not hex text)",
          all(str(r["DTC_LB"]).strip().isdigit() for r in dcsv))
    check("the decimal->hex suffix rule holds for 19/155/156/243",
          (T.suffix_from_lb(19), T.suffix_from_lb(155), T.suffix_from_lb(156),
           T.suffix_from_lb(243)) == ("13", "9B", "9C", "F3"))
    check("fault names are invented mnemonics (upper snake, no spaces)",
          all(r["Fault Name"] == r["Fault Name"].upper().replace(" ", "_") and
              " " not in r["Fault Name"] for r in dcsv))

    xl = T._read_table(f"{DEMO}/synthetic_spn_fmi_dictionary.xlsx")
    check(".xlsx matches .csv row for row", len(xl) == len(dcsv) and all(
        str(a["P Code"]) == str(b["P Code"]) and int(a["DTC_LB"]) == int(b["DTC_LB"])
        and int(a["SPN"]) == int(b["SPN"]) and int(a["FMI"]) == int(b["FMI"])
        for a, b in zip(xl, dcsv)))

    print("\n== ambiguous keys ==")
    table = T.load_dictionary(f"{DEMO}/synthetic_spn_fmi_dictionary.csv")
    amb = {k: [e["code_full"] for e in v] for k, v in table.items() if len(v) > 1}
    check("at least 2 ambiguous (SPN,FMI) keys", len(amb) >= 2, str(amb))
    check("each ambiguous key maps to DIFFERENT P-codes",
          all(len(set(v)) == len(v) >= 2 for v in amb.values()), str(amb))

    print("\n== every intended target resolves in the manual ==")
    from retrieve import Retriever
    R = Retriever()
    EDGE = {"P0195-00": "deliberately absent from the manual",
            "P0116-13": "deliberately absent low byte"}
    unresolved = []
    for key, entries in sorted(table.items()):
        for e in entries:
            mode = R.retrieve(e["code_full"])["mode"]
            if e["code_full"] in EDGE:
                check(f"edge entry {e['code_full']} does NOT resolve ({EDGE[e['code_full']]})",
                      mode != "exact_code", f"mode={mode}")
            elif mode != "exact_code":
                unresolved.append((e["code_full"], mode))
    check("every non-edge target resolves in the manual", not unresolved, str(unresolved))

    print("\n== fleet log contract ==")
    lcsv = list(csv.DictReader(open(f"{DEMO}/synthetic_fleet_log.csv")))
    check("columns are EXACTLY the production feed's columns",
          list(lcsv[0].keys()) == LOG_COLUMNS, str(list(lcsv[0].keys())))
    check("about 1,000 rows", 900 <= len(lcsv) <= 1100, f"{len(lcsv)}")
    check("about 200 vehicles", 150 <= len({r["Vehicle_Id"] for r in lcsv}) <= 200,
          f"{len({r['Vehicle_Id'] for r in lcsv})}")
    dates = {r["Event_Date"] for r in lcsv}
    check("30 distinct VALID event dates (plus the deliberate impossible one)",
          len(dates - {"2026-02-31"}) == 30 and "2026-02-31" in dates,
          f"{len(dates)} values: {len(dates - {'2026-02-31'})} valid, impossible present="
          f"{'2026-02-31' in dates}")
    lamp_vocab = {"Lamp ON", "Lamp Off", "Not used"}
    bad = {v for c in ("Amber_Warning_Lamp_Status", "Malfunction_Indicator_Lamp_Status",
                       "Red_Stop_Lamp_Status", "Protect_Lamp_Status")
           for v in {r[c] for r in lcsv}} - lamp_vocab
    check("lamp columns use only the real vocabulary", not bad, str(bad))
    flash_vocab = {"Unavailable/ Do not flash", "Lamp ON"}
    badf = {v for c in LOG_COLUMNS if c.startswith("Flashing_")
            for v in {r[c] for r in lcsv}} - flash_vocab
    check("flashing columns use only the real vocabulary", not badf, str(badf))
    check("vehicle ids are obviously fake",
          all(r["Vehicle_Id"].startswith("DEMO-MAT-") or r["Vehicle_Id"] == "" for r in lcsv))
    check("registrations are obviously fake",
          all(r["Registration_Number"].startswith("DM") or r["Registration_Number"] == ""
              for r in lcsv))
    dups = len(lcsv) - len({tuple(sorted(r.items())) for r in lcsv})
    check("about 12% exact duplicate rows", 0.08 <= dups / len(lcsv) <= 0.16,
          f"{dups} ({dups / len(lcsv):.1%})")
    xl = T._read_table(f"{DEMO}/synthetic_fleet_log.xlsx")
    check(".xlsx matches .csv row count and first row",
          len(xl) == len(lcsv) and str(xl[0]["Vehicle_Id"]) == lcsv[0]["Vehicle_Id"])

    print("\n== cost rules + scenarios ==")
    cost = T.load_cost_rules(f"{DEMO}/cost_tat_rules.csv")
    check("cost rules carry the illustrative basis",
          all("illustrative" in v["basis"] for v in cost.values()))
    check("a subsystem default and a P-code override both exist",
          ("rail_pressure", "") in cost and ("rail_pressure", "P0192-00") in cost)
    scen = json.load(open(f"{DEMO}/scenarios.json"))
    need = {"normal_advisory", "red_stop_lamp", "duplicate_rows", "ambiguous_key",
            "fmi_unmapped", "unknown_spn", "code_not_in_manual", "low_byte_not_in_manual",
            "malformed_rows", "transposition_P1000", "transposition_P1675"}
    check("every required scenario is present", need <= set(scen["scenarios"]),
          str(need - set(scen["scenarios"])))
    check("scenarios name real vehicles in the log",
          all(d["vehicle_id"] in {r["Vehicle_Id"] for r in lcsv}
              for d in scen["scenarios"].values()))
    check("the synthetic label is recorded", scen["_meta"]["label"] == LABEL
          and LABEL in open(f"{DEMO}/README.md").read())

    print(f"\n==== DEMO DATA: {'OK' if not FAILURES else str(len(FAILURES)) + ' FAILURE(S)'} ====")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
