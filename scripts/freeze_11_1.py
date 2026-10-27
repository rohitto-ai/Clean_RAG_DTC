"""
Phase 11.1 — freeze both refinements BEFORE anything is measured on the
independent set.

    PYTHONPATH=src .venv/bin/python scripts/freeze_11_1.py            # write
    PYTHONPATH=src .venv/bin/python scripts/freeze_11_1.py            # verify (second run)

Writes data/experiments/11_1/freeze.json with the sha256 of the rule code, the
chosen prior weight and the configuration list. Re-running verifies instead of
overwriting and exits non-zero if any file changed, so the independent-set
numbers in the report provably came from this code and not from a later edit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

OUT = "data/experiments/11_1/freeze.json"
FILES = [
    "src/no_dtc.py",                      # improvement A: the rule and its term lists
    "src/retrieve.py",                    # improvement B: detect_systems + the soft prior
    "scripts/refine_eval_11_1.py",        # the measurement harness
]
PRIOR_W = 0.5


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    hashes = {p: sha256(p) for p in FILES}
    if os.path.exists(OUT) and not a.force:
        old = json.load(open(OUT))
        print(f"freeze exists ({old['frozen_utc']}) — verifying")
        bad = 0
        for p, h in hashes.items():
            ok = old["sha256"].get(p) == h
            bad += not ok
            print(f"  [{'PASS' if ok else 'FAIL'}] {p}")
        print("\n" + ("all files match the freeze" if not bad
                      else f"{bad} FILE(S) CHANGED SINCE THE FREEZE"))
        return 1 if bad else 0

    blob = {
        "phase": "11.1",
        "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip(),
        "statement": ("Both refinements are frozen here, BEFORE anything is measured on "
                      "the independent set. The independent set was spent in Phase 10.6, "
                      "so every number measured on it after this point is POST-HOC "
                      "(development) and optimistic, and is labelled so in the report."),
        "improvement_A": {
            "name": "no-DTC-match recognition",
            "file": "src/no_dtc.py",
            "rule": "mechanical evidence AND no electronic evidence -> no matching DTC",
            "mechanical_categories": ["external leak / fluid loss", "smell", "smoke colour",
                                      "mechanical noise", "fluid level / condition",
                                      "consumption / wear"],
            "electronic_categories": ["warning lamp or message", "gauge or reading",
                                      "named sensor or signal", "fault code",
                                      "limp / derate", "will not run / start"],
            "authored_from": "general workshop complaint categories, not from the wording "
                             "of any gold row",
            "adjusted_during_development": [
                "a bare deposit word ('residue', 'crust') no longer declines on its own: it "
                "describes both a leak trace and combustion residue inside a DPF, and the "
                "latter IS a coded fault (found on TEST row t054)",
                "a reported 'warning' of any kind now counts as electronic evidence even "
                "without the word 'lamp', because the ECU raised it (found on DEV row d017)",
            ],
        },
        "improvement_B": {
            "name": "soft subsystem prior",
            "file": "src/retrieve.py (detect_systems + Retriever(subsystem_prior=w))",
            "weight": PRIOR_W,
            "weight_chosen_on": "DEV (gold v2.2); the effect saturates at 0.5, and the "
                                "smallest weight reaching the plateau was taken",
            "mechanism": "adds w/(RRF_K+1) to the fused score of records whose system the "
                         "query's words point at - at most one RRF rank-1 vote. A soft "
                         "boost inside fusion, never a filter.",
            "default": "OFF (subsystem_prior=0.0), so production is byte-identical",
        },
        "configurations": ["base", "A", "B", "AB"],
        "no_regression_gate": {
            "measured_before_freezing": True,
            "DEV": "in-scope 28/28, out-of-scope 6/6, groups 3/3 for all four configs",
            "guardrails": "14/14 for all four configs",
            "determinism_hash_dev_defaults": "ffff9bc707d8754d",
        },
        "sha256": hashes,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(blob, f, indent=1)
        f.write("\n")
    print(f"wrote {OUT}")
    for p, h in hashes.items():
        print(f"  {h}  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
