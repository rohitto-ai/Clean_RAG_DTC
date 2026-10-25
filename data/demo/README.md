# data/demo — synthetic - illustrative

**Every file in this directory is synthetic - illustrative.** No real TATA Motors telematics data or
SPN/FMI dictionary exists in this repository, and none is used or reproduced.

| file | what it is |
|---|---|
| `synthetic_spn_fmi_dictionary.xlsx` / `.csv` | 73 invented SPN/FMI -> P-code mappings. Columns are the real ones: `Fault Name | P Code | DTC_LB | SPN | FMI | SPN_Name`. `DTC_LB` is the DECIMAL failure-type byte; the manual's suffix is its 2-digit uppercase HEX form (19 -> 13, 155 -> 9B, 156 -> 9C). |
| `synthetic_fleet_log.xlsx` / `.csv` | 1000 rows, 200 fake vehicles, 30 days, with the production feed's exact column names and lamp vocabulary ("Lamp ON" / "Lamp Off" / "Not used", flashing "Unavailable/ Do not flash"). ~12% exact duplicate rows, plus malformed rows. |
| `cost_tat_rules.csv` | **ILLUSTRATIVE ONLY.** Labour hours, parts cost range (INR) and turnaround per subsystem. This data is owned by another team; these numbers are placeholders and must not be read as real rates or prices. |
| `scenarios.json` | which fake vehicle exercises which ladder outcome. |

What is invented, and what is real:

* **Invented:** SPNs (inside the SAE J1939 manufacturer-proprietary range
  520192-524287, so no value can be mistaken for a real SAE or OEM
  assignment), fault-name mnemonics, vehicle ids (`DEMO-MAT-0001`..),
  registrations (`DM01AA0001`..), dates, lamp states, counts, region/LOB/PL, and
  every cost or TAT figure.
* **Public standard:** the FMI numbers and their descriptions (SAE J1939-73).
* **Real:** the P-codes are real codes from the 3.3L DTC manual, so the manual
  retrieval and advisory text downstream are genuine. The SPN/FMI -> P-code
  pairing itself is fictitious.

Regenerate deterministically (seed 1002):

```bash
PYTHONPATH=src .venv/bin/python scripts/gen_demo_data.py
PYTHONPATH=src .venv/bin/python scripts/validate_demo_data.py
```
