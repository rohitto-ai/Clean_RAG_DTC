"""
Phase 10.2 — tests for the synthetic demo data contract.

    PYTHONPATH=src .venv/bin/python src/test_demo_data.py

The heavy contract checks live in scripts/validate_demo_data.py; this file runs
them and adds the determinism and labelling checks a test suite should own.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

DEMO = "data/demo"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    import telematics as T

    # the full data contract
    env = {**os.environ, "PYTHONPATH": "src"}
    r = subprocess.run([sys.executable, "scripts/validate_demo_data.py"],
                       capture_output=True, text=True, env=env)
    check("scripts/validate_demo_data.py passes", r.returncode == 0,
          r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr[-200:])

    # deterministic regeneration: the generator has a fixed seed
    # the .xlsx files are included deliberately: an .xlsx embeds save-time stamps,
    # so a committed artifact would churn on every regeneration unless they are pinned
    before = {f: sha(f"{DEMO}/{f}") for f in ("synthetic_spn_fmi_dictionary.csv",
                                              "synthetic_spn_fmi_dictionary.xlsx",
                                              "synthetic_fleet_log.csv",
                                              "synthetic_fleet_log.xlsx", "scenarios.json")}
    r = subprocess.run([sys.executable, "scripts/gen_demo_data.py"],
                       capture_output=True, text=True, env=env)
    after = {f: sha(f"{DEMO}/{f}") for f in before}
    check("regenerating with the fixed seed reproduces byte-identical files (incl. .xlsx)",
          r.returncode == 0 and before == after,
          str([f for f in before if before[f] != after[f]]))

    # labelling: every artifact is marked synthetic
    check("README.md marks the directory synthetic - illustrative",
          "synthetic - illustrative" in open(f"{DEMO}/README.md").read())
    scen = json.load(open(f"{DEMO}/scenarios.json"))
    check("scenarios.json carries the label and the confidentiality note",
          scen["_meta"]["label"] == "synthetic - illustrative"
          and "No real TATA" in scen["_meta"]["confidentiality"])
    check("cost/TAT is marked as owned by another team",
          "another team" in scen["_meta"]["cost_tat"]
          and all("illustrative" in v["basis"] for v in T.load_cost_rules().values()))

    # the hex rule, which is the one easy thing to get wrong
    for lb, suffix in ((0, "00"), (17, "11"), (19, "13"), (31, "1F"), (133, "85"),
                       (155, "9B"), (156, "9C"), (243, "F3"), (255, "FF")):
        check(f"DTC_LB {lb} -> suffix {suffix}", T.suffix_from_lb(lb) == suffix)
    for bad in (-1, 256, 999):
        try:
            T.suffix_from_lb(bad)
            ok = False
        except ValueError:
            ok = True
        check(f"DTC_LB {bad} is rejected", ok)

    # .xlsx and .csv must be interchangeable inputs
    d_csv = T.load_dictionary(f"{DEMO}/synthetic_spn_fmi_dictionary.csv")
    d_xl = T.load_dictionary(f"{DEMO}/synthetic_spn_fmi_dictionary.xlsx")
    check("load_dictionary gives the same table from .csv and .xlsx", d_csv == d_xl)
    l_csv, l_xl = T.load_log(f"{DEMO}/synthetic_fleet_log.csv"), T.load_log(f"{DEMO}/synthetic_fleet_log.xlsx")
    check("load_log gives the same row count from .csv and .xlsx", len(l_csv) == len(l_xl))
    check("load_log canonicalises .xlsx rows to the same keys",
          T.canonical_row(l_csv[0]) == T.canonical_row(l_xl[0]),
          f"{T.canonical_row(l_csv[0])} vs {T.canonical_row(l_xl[0])}")

    # no real-data leakage in the demo directory
    rows = list(csv.DictReader(open(f"{DEMO}/synthetic_fleet_log.csv")))
    check("every vehicle id is a DEMO- id",
          all(r["Vehicle_Id"].startswith("DEMO-MAT-") or r["Vehicle_Id"] == "" for r in rows))
    check("every registration is a DM demo plate",
          all(r["Registration_Number"].startswith("DM") or r["Registration_Number"] == ""
              for r in rows))

    passed = sum(RESULTS)
    print(f"\n==== DEMO DATA TESTS: {passed}/{len(RESULTS)} passed ====")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
