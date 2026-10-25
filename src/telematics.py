"""
Phase 10.2 — telematics -> P-code -> advisory pipeline (pure functions + CLI).

    PYTHONPATH=src .venv/bin/python src/telematics.py --vehicle DEMO-MAT-0001
    PYTHONPATH=src .venv/bin/python src/telematics.py --registration DM44FT4123 --json
    PYTHONPATH=src .venv/bin/python src/telematics.py --fleet
    PYTHONPATH=src .venv/bin/python src/telematics.py --vehicle DEMO-MAT-0011 --reported P0100-00

Runs on the SYNTHETIC demo feed in data/demo/ ("synthetic - illustrative"). The
COLUMN NAMES are the production feed's real ones, so the same code can later be
pointed at a real export offline; only the demo VALUES are invented. Cost and TAT
figures are ILLUSTRATIVE placeholders owned by another team.

Reuses, rather than re-implements:
  * normalize.validate_row  - the Phase 9.4 R0 field rules, applied to each row
    after it is mapped onto normalize's canonical {spn, fmi, occurrences,
    timestamp, vehicle_id} shape
  * Retriever.retrieve      - the exact-code router, which carries the Phase 9.3b
    behaviour: unknown_code -> explicit refusal, suffix_not_found -> clarification
  * advise.fix_block        - the deterministic Phase 9.1 fix block (no model)
  * retrieve.did_you_mean   - edit-distance-1 candidates, SURFACED, never selected
  * retrieve.detect_system  - the subsystem keyword map, for the cross-check

LADDER (first rung that applies wins; every rung is traced)
  R0  validate + de-duplicate   malformed -> REJECTED_MALFORMED (logged)
                                exact duplicate (Vehicle_Id, SPN, FMI, Event_Date)
                                -> dropped before episodes are built
  R1  exactly ONE mapped P-code for (SPN, FMI) -> resolve against the manual
          exact_code       -> ADVISORY
          suffix_not_found -> CLARIFY_LOW_BYTE
          unknown_code     -> REFUSED_NOT_IN_MANUAL
  R1b MORE THAN ONE mapped P-code -> AMBIGUOUS_MAPPING_CANDIDATES. Every candidate
      is listed with its manual status; NEVER auto-advised. Real OEM dictionaries
      are not one-to-one, and picking one silently would assert a repair for a
      fault that was not identified.
  R2  SPN known, this FMI unmapped -> FALLBACK_CANDIDATES (never auto-advised)
  R3  SPN not in the dictionary -> UNMAPPED
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

LABEL = "synthetic - illustrative"
DEMO_DIR = "data/demo"
DICT_PATH = f"{DEMO_DIR}/synthetic_spn_fmi_dictionary.csv"
LOG_PATH = f"{DEMO_DIR}/synthetic_fleet_log.csv"
COST_PATH = f"{DEMO_DIR}/cost_tat_rules.csv"
TOP_N = 3

OUTCOMES = ["ADVISORY", "AMBIGUOUS_MAPPING_CANDIDATES", "CLARIFY_LOW_BYTE",
            "REFUSED_NOT_IN_MANUAL", "FALLBACK_CANDIDATES", "UNMAPPED", "REJECTED_MALFORMED"]
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

LAMP_ON = "lamp on"
FLASH_NOT = "unavailable/ do not flash"
RED_COLS = ("Red_Stop_Lamp_Status",)
RED_FLASH = ("Flashing_Red_Stop_Lamp",)
WARN_COLS = ("Amber_Warning_Lamp_Status", "Malfunction_Indicator_Lamp_Status",
             "Protect_Lamp_Status")
WARN_FLASH = ("Flashing_Amber_Warning_Lamp", "Flashing_Malfunction_Indicator_Lamp",
              "Flashing_Protect_Lamp")
RAISE_OCCURRENCE, RAISE_MINUTES = 5, 60


# --------------------------------------------------------------------- loading
def _rows_from_xlsx(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in next(it)]
    out = []
    for r in it:
        if r is None or all(v is None for v in r):
            continue
        out.append({h: ("" if v is None else v) for h, v in zip(header, r)})
    wb.close()
    return out


def _read_table(path):
    """.csv or .xlsx -> list of dicts, values as strings where they came from CSV."""
    if path.lower().endswith((".xlsx", ".xlsm")):
        return _rows_from_xlsx(path)
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def suffix_from_lb(lb):
    """Decimal failure-type byte -> the manual's 2-digit uppercase HEX suffix.
    19 -> '13', 155 -> '9B', 156 -> '9C', 243 -> 'F3'."""
    n = int(str(lb).strip())
    if not 0 <= n <= 255:
        raise ValueError(f"DTC_LB {lb!r} outside 0..255")
    return f"{n:02X}"


def load_dictionary(path=DICT_PATH):
    """
    -> {(spn, fmi): [ {code_full, p_code, dtc_lb, fault_name, spn_name}, ... ]}

    A key may legitimately carry MORE THAN ONE mapping: real dictionaries are not
    one-to-one. Duplicate identical mappings are collapsed; genuinely different
    P-codes are all kept and surface as AMBIGUOUS_MAPPING_CANDIDATES.
    """
    table = defaultdict(list)
    for r in _read_table(path):
        spn, fmi = int(str(r["SPN"]).strip()), int(str(r["FMI"]).strip())
        code = f"{str(r['P Code']).strip().upper()}-{suffix_from_lb(r['DTC_LB'])}"
        entry = {"code_full": code, "p_code": str(r["P Code"]).strip().upper(),
                 "dtc_lb": int(str(r["DTC_LB"]).strip()),
                 "fault_name": str(r["Fault Name"]).strip(),
                 "spn_name": str(r["SPN_Name"]).strip()}
        if not any(e["code_full"] == code for e in table[(spn, fmi)]):
            table[(spn, fmi)].append(entry)
    return dict(table)


def load_log(path=LOG_PATH):
    """Raw feed rows, 1-based source line recorded for traceability."""
    return [{"_row": i, **r} for i, r in enumerate(_read_table(path), start=2)]


def load_cost_rules(path=COST_PATH):
    """ILLUSTRATIVE cost/TAT rules: {(subsystem, p_code|''): rule}."""
    out = {}
    for r in _read_table(path):
        out[(str(r["subsystem"]).strip(), str(r.get("p_code") or "").strip().upper())] = {
            "labour_hours": float(r["labour_hours"]),
            "parts_cost_min_inr": int(float(r["parts_cost_min_inr"])),
            "parts_cost_max_inr": int(float(r["parts_cost_max_inr"])),
            "tat_hours": float(r["tat_hours"]),
            "basis": "illustrative - owned by another team, not real rates",
        }
    return out


# ------------------------------------------------------------------ validation
def canonical_row(row):
    """Map the feed's columns onto normalize.validate_row's canonical shape."""
    def as_int(v):
        s = str(v).strip()
        try:
            return int(float(s))
        except ValueError:
            return s or None
    return {"timestamp": str(row.get("Event_Date") or "").strip(),
            "vehicle_id": str(row.get("Vehicle_Id") or "").strip(),
            "spn": as_int(row.get("SPN_Number")),
            "fmi": as_int(row.get("Failure_Mode_Identifier_Code")),
            "occurrences": as_int(row.get("Fault_Occurrence_Count"))}


def validate(row):
    """Phase 9.4 R0 rules, reused verbatim. -> list of problems ([] = valid)."""
    import normalize
    canon = canonical_row(row)
    problems = list(normalize.validate_row(canon))
    if not str(row.get("Registration_Number") or "").strip():
        problems.append("Registration_Number empty")
    return problems


def dedupe_key(row):
    c = canonical_row(row)
    return (c["vehicle_id"], c["spn"], c["fmi"], c["timestamp"])


# -------------------------------------------------------------------- severity
def _on(row, cols):
    return [c for c in cols if str(row.get(c) or "").strip().lower() == LAMP_ON]


def _flashing(row, cols):
    out = []
    for c in cols:
        v = str(row.get(c) or "").strip().lower()
        if v and v != FLASH_NOT and v != "not used":
            out.append(c)
    return out


def severity(row):
    """
    Deterministic severity with the reasons that produced it.

      Red stop lamp ON or flashing            -> CRITICAL
      else amber / MIL / protect ON or flashing -> HIGH
      else occurrence <= 1 and active < 60 min  -> LOW, otherwise MEDIUM
      occurrence >= 5 or active >= 60 min raises LOW/MEDIUM ONE level, capped at
      HIGH. CRITICAL is reserved for the red stop lamp and is never reached by
      escalation.
    """
    reasons = []
    occ_raw = str(row.get("Fault_Occurrence_Count") or "").strip()
    act_raw = str(row.get("Fault_Active_Time_Minutes") or "").strip()
    try:
        occ = int(float(occ_raw))
    except ValueError:
        occ = 0
    try:
        active = float(act_raw)
    except ValueError:
        active = 0.0

    red_on, red_flash = _on(row, RED_COLS), _flashing(row, RED_FLASH)
    if red_on or red_flash:
        reasons.append("red stop lamp " + ("flashing" if red_flash and not red_on else "ON"))
        return "CRITICAL", reasons

    warn_on, warn_flash = _on(row, WARN_COLS), _flashing(row, WARN_FLASH)
    if warn_on or warn_flash:
        for c in warn_on:
            reasons.append(f"{c} ON")
        for c in warn_flash:
            reasons.append(f"{c} flashing")
        return "HIGH", reasons

    base = "LOW" if (occ <= 1 and active < RAISE_MINUTES) else "MEDIUM"
    reasons.append(f"no lamp set; occurrence={occ}, active={active:g} min -> {base}")
    if occ >= RAISE_OCCURRENCE or active >= RAISE_MINUTES:
        raised = SEVERITIES[min(SEVERITIES.index(base) + 1, SEVERITIES.index("HIGH"))]
        reasons.append(f"occurrence >= {RAISE_OCCURRENCE} or active >= {RAISE_MINUTES} min "
                       f"-> raised to {raised} (capped at HIGH; CRITICAL is red-lamp only)")
        return raised, reasons
    return base, reasons


def worst(sevs):
    return max(sevs, key=SEVERITIES.index) if sevs else None


# ----------------------------------------------------------------- the pipeline
class Pipeline:
    def __init__(self, retriever=None, dict_path=DICT_PATH, cost_path=COST_PATH):
        from retrieve import Retriever
        self.R = retriever or Retriever()
        self.table = load_dictionary(dict_path)
        self.by_spn = defaultdict(list)
        for (spn, fmi), entries in sorted(self.table.items()):
            for e in entries:
                self.by_spn[spn].append({**e, "fmi": fmi})
        self.cost = load_cost_rules(cost_path)
        self._code_cache = {}

    # ---- manual resolution (9.3b behaviour, via the production router) ----
    def resolve(self, code_full):
        if code_full in self._code_cache:
            return self._code_cache[code_full]
        out = self.R.retrieve(code_full)
        res = {"mode": out["mode"],
               "records": [i["record"] for i in out["results"]],
               "message": out["trace"].get("message"),
               "known_variants": out["trace"].get("known_variants", []),
               "did_you_mean": out["trace"].get("did_you_mean", [])}
        self._code_cache[code_full] = res
        return res

    def cost_for(self, system, code_full):
        rule = self.cost.get((system, code_full)) or self.cost.get((system, ""))
        return dict(rule, applies_to=code_full if (system, code_full) in self.cost else system,
                    label="ILLUSTRATIVE") if rule else None

    # ---- cross-check: SPN_Name vs the resolved record's subsystem ----
    def cross_check(self, spn_name, system):
        from retrieve import detect_system
        expected = detect_system(spn_name or "")
        if expected is None:
            return {"status": "NOT_DETERMINED", "expected_system": None, "record_system": system,
                    "note": "no subsystem keyword in SPN_Name"}
        if system is None:
            return {"status": "NOT_DETERMINED", "expected_system": expected, "record_system": None}
        return {"status": "CONSISTENT" if expected == system else "INCONSISTENT",
                "expected_system": expected, "record_system": system,
                "note": None if expected == system else
                        "the SPN name and the resolved record disagree on subsystem - "
                        "verify the mapping before acting"}

    # ---- one episode = one (Vehicle_Id, SPN, FMI) ----
    def episode(self, rows):
        """rows: the de-duplicated valid rows of one (vehicle, spn, fmi)."""
        first = rows[0]
        spn = int(float(str(first["SPN_Number"]).strip()))
        fmi = int(float(str(first["Failure_Mode_Identifier_Code"]).strip()))
        occ = max(int(float(str(r["Fault_Occurrence_Count"]).strip())) for r in rows)
        active = max(float(str(r["Fault_Active_Time_Minutes"]).strip()) for r in rows)
        dates = sorted(str(r["Event_Date"]).strip() for r in rows)
        # severity of the episode = the most severe row, with that row's reasons
        best = max(rows, key=lambda r: SEVERITIES.index(severity(r)[0]))
        sev, sev_reasons = severity(best)

        ep = {"spn": spn, "fmi": fmi,
              "spn_name": str(first.get("SPN_Name") or "").strip(),
              "fmi_description": str(first.get("Failure_Mode_Identifier_Description") or "").strip(),
              "rows": len(rows), "source_rows": [r["_row"] for r in rows],
              "first_seen": dates[0], "last_seen": dates[-1],
              "occurrence_count": occ, "active_minutes": active,
              "severity": sev, "severity_reasons": sev_reasons,
              "ladder": [], "label": LABEL}

        def step(rung, result, **kw):
            ep["ladder"].append({"rung": rung, "result": result, **kw})

        step("R0 validate + de-duplicate", "ok", rows_kept=len(rows))
        mapped = self.table.get((spn, fmi))

        # ---- R1b ambiguity first: more than one P-code for this key ----
        if mapped and len(mapped) > 1:
            cands = []
            for e in sorted(mapped, key=lambda e: e["code_full"]):
                res = self.resolve(e["code_full"])
                cands.append({"code_full": e["code_full"], "fault_name": e["fault_name"],
                              "in_manual": res["mode"] == "exact_code",
                              "manual_status": res["mode"],
                              "description": res["records"][0]["description"]
                                             if res["records"] else None})
            step("R1b ambiguous key", "candidates", n=len(cands), auto_advised=False)
            ep.update({"outcome": "AMBIGUOUS_MAPPING_CANDIDATES", "resolved_code": None,
                       "candidates": cands, "fix_blocks": [],
                       "message": f"SPN {spn} FMI {fmi} maps to "
                                  f"{', '.join(c['code_full'] for c in cands)} in the dictionary. "
                                  f"No advisory is issued: the key is ambiguous and choosing one "
                                  f"would assert a repair for a fault that was not identified. "
                                  f"A technician must confirm which applies.",
                       "cross_check": self.cross_check(ep["spn_name"], None)})
            return ep

        # ---- R1 single mapping ----
        if mapped:
            e = mapped[0]
            code = e["code_full"]
            step("R1 exact (spn,fmi)", "hit", p_code=e["p_code"], dtc_lb=e["dtc_lb"],
                 suffix=code.split("-")[1], code_full=code, fault_name=e["fault_name"])
            res = self.resolve(code)
            step("R1 manual lookup", res["mode"])
            if res["mode"] == "exact_code" and res["records"]:
                import advise
                recs = res["records"][:TOP_N]
                blocks = [advise.fix_block(r) for r in recs]
                system = recs[0]["system"]
                ep.update({"outcome": "ADVISORY", "resolved_code": code,
                           "fix_blocks": blocks, "candidates": [],
                           "message": f"SPN {spn} FMI {fmi} -> {code}: manual entry found.",
                           "cost_tat": self.cost_for(system, code),
                           "cross_check": self.cross_check(ep["spn_name"], system)})
                return ep
            if res["mode"] == "suffix_not_found":
                ep.update({"outcome": "CLARIFY_LOW_BYTE", "resolved_code": code,
                           "fix_blocks": [], "candidates": [],
                           "known_variants": res["known_variants"],
                           "did_you_mean": res["did_you_mean"], "message": res["message"],
                           "cross_check": self.cross_check(ep["spn_name"], None)})
                return ep
            if res["mode"] == "unknown_code":
                ep.update({"outcome": "REFUSED_NOT_IN_MANUAL", "resolved_code": code,
                           "fix_blocks": [], "candidates": [],
                           "did_you_mean": res["did_you_mean"], "message": res["message"],
                           "cross_check": self.cross_check(ep["spn_name"], None)})
                return ep
            ep.update({"outcome": "UNMAPPED", "resolved_code": code, "fix_blocks": [],
                       "candidates": [],
                       "message": f"unexpected router mode {res['mode']!r} for {code}; "
                                  f"no advisory issued",
                       "cross_check": self.cross_check(ep["spn_name"], None)})
            return ep
        step("R1 exact (spn,fmi)", "miss")

        # ---- R2 SPN known, FMI unmapped ----
        known = self.by_spn.get(spn)
        if known:
            cands = sorted(known, key=lambda m: (abs(m["fmi"] - fmi), m["fmi"], m["code_full"]))
            out = []
            for i, m in enumerate(cands):
                res = self.resolve(m["code_full"])
                out.append({"fmi": m["fmi"], "fmi_distance": abs(m["fmi"] - fmi),
                            "code_full": m["code_full"], "fault_name": m["fault_name"],
                            "in_manual": res["mode"] == "exact_code", "nearest": i == 0})
            step("R2 spn-only / nearest-fmi", "candidates", n=len(out), auto_advised=False)
            ep.update({"outcome": "FALLBACK_CANDIDATES", "resolved_code": None,
                       "candidates": out, "fix_blocks": [],
                       "message": f"SPN {spn} is known but FMI {fmi} "
                                  f"({ep['fmi_description'] or 'no description'}) has no mapping. "
                                  f"No advisory: an FMI is a failure mode, and a neighbouring FMI "
                                  f"may be a different fault. Candidates for a technician to "
                                  f"confirm: " + ", ".join(
                                      f"{c['code_full']} (FMI {c['fmi']}"
                                      + (", nearest" if c["nearest"] else "") + ")" for c in out),
                       "cross_check": self.cross_check(ep["spn_name"], None)})
            return ep
        step("R2 spn-only / nearest-fmi", "spn unknown")

        # ---- R3 ----
        ep.update({"outcome": "UNMAPPED", "resolved_code": None, "candidates": [],
                   "fix_blocks": [],
                   "message": f"SPN {spn} FMI {fmi} is not in the dictionary; no advisory. Logged.",
                   "cross_check": self.cross_check(ep["spn_name"], None)})
        return ep

    # ------------------------------------------------------ vehicle / fleet
    def vehicle_report(self, vehicle_id=None, registration=None, log=None):
        rows = log if log is not None else load_log()
        reg = (registration or "").strip().upper()
        vid = (vehicle_id or "").strip().upper()
        mine = [r for r in rows
                if (vid and str(r.get("Vehicle_Id") or "").strip().upper() == vid)
                or (reg and str(r.get("Registration_Number") or "").strip().upper() == reg)]
        rejected, valid = [], []
        for r in mine:
            probs = validate(r)
            (rejected if probs else valid).append(
                {"row": r["_row"], "problems": probs} if probs else r)

        seen, deduped, dropped = set(), [], []
        for r in valid:
            k = dedupe_key(r)
            if k in seen:
                dropped.append(r["_row"])
                continue
            seen.add(k)
            deduped.append(r)

        groups = defaultdict(list)
        for r in deduped:
            c = canonical_row(r)
            groups[(c["spn"], c["fmi"])].append(r)
        episodes = [self.episode(g) for _, g in sorted(groups.items())]
        episodes.sort(key=lambda e: (-SEVERITIES.index(e["severity"]), e["spn"], e["fmi"]))

        ident = mine[0] if mine else {}
        return {
            "label": LABEL,
            "vehicle_id": str(ident.get("Vehicle_Id") or vehicle_id or ""),
            "registration": str(ident.get("Registration_Number") or registration or ""),
            "region": str(ident.get("Region") or ""), "lob": str(ident.get("LOB") or ""),
            "pl": str(ident.get("PL") or ""),
            "rows_seen": len(mine), "rows_rejected": len(rejected),
            "rejected": rejected, "duplicate_rows_dropped": dropped,
            "episodes": episodes,
            "worst_severity": worst([e["severity"] for e in episodes]),
            "outcome_counts": dict(Counter(e["outcome"] for e in episodes)),
            "cost_tat_note": "ILLUSTRATIVE figures owned by another team - not real rates",
        }

    def verify_reported_code(self, vehicle_id, reported, log=None):
        """
        Compare a technician-entered code with what the telemetry resolved to.
        Never auto-replaces either one; an edit distance of 1 is reported as a
        POSSIBLE TRANSPOSITION for a human to confirm.
        """
        from retrieve import did_you_mean, normalize_code_tokens, detect_code
        norm, _ = normalize_code_tokens(reported or "")
        code_full, base = detect_code(norm)
        typed = code_full or base
        rep = self.vehicle_report(vehicle_id=vehicle_id, log=log)
        resolved = [e["resolved_code"] for e in rep["episodes"] if e.get("resolved_code")]
        res = self.resolve(typed) if typed else {"mode": "no_code_detected"}
        out = {"label": LABEL, "vehicle_id": rep["vehicle_id"], "reported_input": reported,
               "reported_code": typed, "reported_in_manual": res["mode"] == "exact_code",
               "telemetry_resolved_codes": resolved,
               "auto_replaced": False}
        if not typed:
            out.update({"status": "NO_CODE_DETECTED",
                        "message": f"No DTC code found in {reported!r}."})
            return out
        if typed in resolved:
            out.update({"status": "MATCH",
                        "message": f"{typed} matches the code resolved from this vehicle's "
                                   f"telemetry."})
            return out
        near = [c for c in resolved if c in did_you_mean(typed, [c])]
        out.update({
            "status": "MISMATCH",
            "possible_transposition": near,
            "message": (f"{typed} does NOT match the telemetry-resolved code(s) "
                        f"{', '.join(resolved) or '(none)'}."
                        + (f" {', '.join(near)} is one character away - possible transposition. "
                           f"Not substituted: confirm the code on the vehicle."
                           if near else
                           " No telemetry-resolved code is within one character.")),
        })
        return out

    def fleet_summary(self, log=None):
        rows = log if log is not None else load_log()
        by_vehicle = defaultdict(list)
        for r in rows:
            by_vehicle[str(r.get("Vehicle_Id") or "").strip()].append(r)
        per_vehicle, sev_c, out_c, sys_c = {}, Counter(), Counter(), Counter()
        rejected = 0
        for vid, vrows in sorted(by_vehicle.items()):
            if not vid:
                rejected += len(vrows)
                continue
            rep = self.vehicle_report(vehicle_id=vid, log=vrows)
            rejected += rep["rows_rejected"]
            per_vehicle[vid] = {"registration": rep["registration"],
                                "worst_severity": rep["worst_severity"],
                                "episodes": len(rep["episodes"]),
                                "outcomes": rep["outcome_counts"]}
            if rep["worst_severity"]:
                sev_c[rep["worst_severity"]] += 1
            for e in rep["episodes"]:
                out_c[e["outcome"]] += 1
                if e["outcome"] == "ADVISORY" and e["fix_blocks"]:
                    sys_c[e["fix_blocks"][0]["system"]] += 1
        return {"label": LABEL, "vehicles": len(per_vehicle), "rows": len(rows),
                "rows_rejected": rejected,
                "episodes": sum(v["episodes"] for v in per_vehicle.values()),
                "by_outcome": dict(out_c.most_common()),
                "by_worst_severity": {s: sev_c.get(s, 0) for s in SEVERITIES},
                "advisory_by_subsystem": dict(sys_c.most_common()),
                "per_vehicle": per_vehicle}


# --------------------------------------------------------------------- CLI
def print_report(rep):
    print("=" * 78)
    print(f"[{rep['label']}]  VEHICLE {rep['vehicle_id']}  reg {rep['registration']}"
          f"  {rep['region']}/{rep['lob']}/{rep['pl']}")
    print(f"rows {rep['rows_seen']} | rejected {rep['rows_rejected']} | "
          f"duplicates dropped {len(rep['duplicate_rows_dropped'])} | "
          f"episodes {len(rep['episodes'])} | worst severity {rep['worst_severity']}")
    for p in rep["rejected"]:
        print(f"  row {p['row']} REJECTED: {'; '.join(p['problems'])}")
    for e in rep["episodes"]:
        print("-" * 78)
        print(f"SPN {e['spn']} FMI {e['fmi']} ({e['spn_name']}) x{e['rows']} row(s) "
              f"{e['first_seen']}..{e['last_seen']}")
        print(f"  OUTCOME: {e['outcome']}   severity {e['severity']}  "
              f"({'; '.join(e['severity_reasons'])})")
        for s in e["ladder"]:
            print(f"    {s}")
        print(f"  {e['message']}")
        cc = e.get("cross_check") or {}
        if cc:
            print(f"  cross-check: {cc['status']} (SPN name -> {cc['expected_system']}, "
                  f"record -> {cc['record_system']})")
        if e.get("cost_tat"):
            c = e["cost_tat"]
            print(f"  cost/TAT [{c['label']}]: labour {c['labour_hours']} h, parts INR "
                  f"{c['parts_cost_min_inr']}-{c['parts_cost_max_inr']}, TAT {c['tat_hours']} h")
        for b in e["fix_blocks"]:
            print()
            print(b["text"])
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser(description="Synthetic telematics -> P-code -> advisory")
    ap.add_argument("--vehicle")
    ap.add_argument("--registration")
    ap.add_argument("--fleet", action="store_true")
    ap.add_argument("--reported", help="a technician-entered code to cross-check")
    ap.add_argument("--log", default=LOG_PATH)
    ap.add_argument("--dictionary", default=DICT_PATH)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    from cli import quiet_stderr
    with quiet_stderr():
        P = Pipeline(dict_path=a.dictionary)
        rows = load_log(a.log)
        if a.fleet:
            res = P.fleet_summary(log=rows)
        elif a.reported:
            res = P.verify_reported_code(a.vehicle, a.reported, log=rows)
        elif a.vehicle or a.registration:
            res = P.vehicle_report(a.vehicle, a.registration, log=rows)
        else:
            ap.error("give --vehicle, --registration or --fleet")
    if a.json or a.fleet or a.reported:
        if a.fleet and not a.json:
            res = {k: v for k, v in res.items() if k != "per_vehicle"}
        print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    else:
        print_report(res)


if __name__ == "__main__":
    main()
