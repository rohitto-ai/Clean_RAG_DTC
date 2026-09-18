"""
Phase 9.4 — generator for SYNTHETIC SPN/FMI data. synthetic - illustrative.

    PYTHONPATH=src .venv/bin/python scripts/gen_synthetic_telematics.py

Writes
  data/synthetic/spn_fmi_dictionary.json
  data/synthetic/telematics_log.jsonl

DATA & CONFIDENTIALITY. The real SPN/FMI -> DTC dictionary and real telematics logs
are TATA Motors proprietary and are NOT used, read or reproduced here. Everything
below is fabricated:
  * every SPN is taken from the SAE J1939 MANUFACTURER-PROPRIETARY range
    (520192-524287) and invented, so no value can be mistaken for a real SAE SPN
    or a real OEM mapping;
  * FMI meanings are the PUBLIC SAE J1939-73 failure-mode definitions;
  * vehicle ids, timestamps and occurrence counts are invented;
  * the TARGET P-codes are real codes from the 3.3L DTC manual, so the downstream
    manual retrieval is genuine. The SPN/FMI -> P-code pairing itself is fictitious.

The data is schema-faithful (the field layout a telematics feed would carry) and is
designed to exercise every branch of the normalization ladder (src/normalize.py).
It demonstrates the METHOD. It says nothing about the accuracy of any real mapping.
"""
from __future__ import annotations

import json
import os

LABEL = "synthetic - illustrative"
OUT_DIR = "data/synthetic"

# Public SAE J1939-73 FMI definitions (subset used below).
FMI_MEANING = {
    0: "data valid but above normal operating range - most severe",
    1: "data valid but below normal operating range - most severe",
    2: "data erratic, intermittent or incorrect",
    3: "voltage above normal, or shorted to high source",
    4: "voltage below normal, or shorted to low source",
    5: "current below normal or open circuit",
    8: "abnormal frequency or pulse width or period",
    9: "abnormal update rate",
    16: "data valid but above normal operating range - moderately severe",
    31: "condition exists",
}

# (spn, fmi, component (fictitious naming), p_code base, dtc_low_byte, branch exercised)
ENTRIES = [
    (520210, 4, "rail pressure sensor (synthetic SPN)", "P0192", "00", "complete"),
    (520210, 3, "rail pressure sensor (synthetic SPN)", "P0193", "00", "complete"),
    (520210, 2, "rail pressure sensor (synthetic SPN)", "P0194", "00", "complete"),
    (520220, 4, "coolant temperature sensor (synthetic SPN)", "P0117", "00", "complete"),
    (520220, 3, "coolant temperature sensor (synthetic SPN)", "P0118", "00", "complete"),
    (520220, 2, "coolant temperature sensor (synthetic SPN)", "P0116", "00", "complete"),
    # base P0116 is in the manual, low byte 13 is not -> suffix clarification
    (520220, 16, "coolant temperature sensor (synthetic SPN)", "P0116", "13", "low_byte_not_in_manual"),
    (520230, 8, "camshaft position sensor (synthetic SPN)", "P0340", "00", "complete"),
    (520230, 2, "camshaft position sensor (synthetic SPN)", "P0341", "00", "complete"),
    (520240, 9, "air mass sensor SENT line (synthetic SPN)", "P0100", "00", "complete"),
    (520240, 0, "air mass sensor (synthetic SPN)", "P0100", "9B", "complete"),
    (520240, 1, "air mass sensor (synthetic SPN)", "P0100", "9C", "complete"),
    (520250, 0, "battery voltage (synthetic SPN)", "P0562", "00", "complete"),
    (520250, 1, "battery voltage (synthetic SPN)", "P0563", "00", "complete"),
    # P0195 has no entry anywhere in the manual -> 9.3b explicit refusal
    (520260, 4, "fuel rail pressure sensor B (synthetic SPN)", "P0195", "00", "p_code_not_in_manual"),
]

V1, V2, V3 = "SYN-VEH-0001", "SYN-VEH-0002", "SYN-VEH-0003"
# (row, note) - notes are for the generator/report only and are NOT written into rows
LOG = [
    ({"timestamp": "2026-03-02T08:14:05Z", "vehicle_id": V1, "spn": 520210, "fmi": 4, "occurrences": 3}, "complete -> P0192-00"),
    ({"timestamp": "2026-03-02T08:20:41Z", "vehicle_id": V1, "spn": 520220, "fmi": 4, "occurrences": 1}, "complete -> P0117-00"),
    ({"timestamp": "2026-03-02T09:02:10Z", "vehicle_id": V2, "spn": 520240, "fmi": 1, "occurrences": 5}, "complete -> P0100-9C (non-00 low byte)"),
    ({"timestamp": "2026-03-02T09:05:55Z", "vehicle_id": V2, "spn": 520230, "fmi": 8, "occurrences": 7}, "complete -> P0340-00"),
    ({"timestamp": "2026-03-02T09:40:00Z", "vehicle_id": V3, "spn": 520250, "fmi": 1, "occurrences": 2}, "complete -> P0563-00"),
    ({"timestamp": "2026-03-02T10:11:12Z", "vehicle_id": V1, "spn": 520210, "fmi": 5, "occurrences": 2}, "SPN known, FMI 5 unmapped -> fallback candidates"),
    ({"timestamp": "2026-03-02T10:15:30Z", "vehicle_id": V2, "spn": 520240, "fmi": 31, "occurrences": 1}, "SPN known, FMI 31 unmapped -> fallback candidates"),
    ({"timestamp": "2026-03-02T10:30:00Z", "vehicle_id": V3, "spn": 520299, "fmi": 4, "occurrences": 4}, "unknown SPN -> unmapped, logged"),
    ({"timestamp": "2026-03-02T11:00:00Z", "vehicle_id": V3, "spn": 520260, "fmi": 4, "occurrences": 1}, "mapped P0195-00 not in manual -> refusal"),
    ({"timestamp": "2026-03-02T11:05:00Z", "vehicle_id": V1, "spn": 520220, "fmi": 16, "occurrences": 1}, "mapped P0116-13, low byte not in manual -> clarification"),
    ({"timestamp": "2026-03-02T08:14:05Z", "vehicle_id": V1, "spn": 520210, "fmi": 4, "occurrences": 3}, "exact duplicate of row 1 -> skipped"),
    ({"timestamp": "2026-03-02T12:00:00Z", "vehicle_id": V2, "spn": "abc", "fmi": 4, "occurrences": 1}, "malformed: non-integer SPN"),
    ({"timestamp": "2026-03-02T12:01:00Z", "vehicle_id": V2, "spn": 520210, "fmi": 40, "occurrences": 1}, "malformed: FMI outside 0-31"),
    ({"timestamp": "2026-03-02T12:02:00Z", "vehicle_id": V2, "spn": 520210, "occurrences": 1}, "malformed: FMI missing"),
    ({"timestamp": "2026-03-02T12:03:00Z", "vehicle_id": V3, "spn": 600000, "fmi": 4, "occurrences": 1}, "malformed: SPN outside 19-bit range"),
    ({"timestamp": "2026-03-02T12:04:00Z", "vehicle_id": V3, "spn": 520220, "fmi": 3, "occurrences": -2}, "malformed: negative occurrences"),
    ({"timestamp": "2026-02-31T12:05:00Z", "vehicle_id": V1, "spn": 520220, "fmi": 3, "occurrences": 1}, "malformed: impossible date"),
    ({"timestamp": "2026-03-02T12:06:00Z", "vehicle_id": "", "spn": 520220, "fmi": 3, "occurrences": 1}, "malformed: empty vehicle_id"),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    dictionary = {
        "_meta": {
            "label": LABEL,
            "confidentiality": "Fabricated values. The real SPN/FMI dictionary is TATA Motors "
                               "proprietary and is not used or reproduced.",
            "spn_range": "SAE J1939 manufacturer-proprietary range 520192-524287, invented values",
            "fmi_definitions": "public SAE J1939-73",
            "p_codes": "real codes from the 3.3L DTC manual (except P0195, deliberately absent); "
                       "the SPN/FMI -> P-code pairing is fictitious",
            "dtc_low_byte": "failure-type byte = the manual's suffix (P0192 + 00 -> P0192-00)",
        },
        "fmi_meaning": {str(k): v for k, v in FMI_MEANING.items()},
        "entries": [
            {"spn": spn, "fmi": fmi,
             "description": f"{comp}: {FMI_MEANING[fmi]}",
             "p_code": p, "dtc_low_byte": lb, "exercises": branch, "label": LABEL}
            for spn, fmi, comp, p, lb, branch in ENTRIES],
    }
    with open(f"{OUT_DIR}/spn_fmi_dictionary.json", "w") as f:
        json.dump(dictionary, f, indent=1)
        f.write("\n")
    with open(f"{OUT_DIR}/telematics_log.jsonl", "w") as f:
        f.write(json.dumps({"_meta": {"label": LABEL, "rows": len(LOG),
                                      "notes": [n for _, n in LOG]}}) + "\n")
        for row, _ in LOG:
            f.write(json.dumps({**row, "_label": LABEL}) + "\n")
    print(f"wrote {len(ENTRIES)} dictionary entries and {len(LOG)} log rows to {OUT_DIR}/ ({LABEL})")


if __name__ == "__main__":
    main()
