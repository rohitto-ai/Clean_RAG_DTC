"""
Phase 10.2 — generator for the SYNTHETIC telematics demo data. Fixed seed.

    PYTHONPATH=src .venv/bin/python scripts/gen_demo_data.py

Writes, under data/demo/ (both .xlsx and .csv for the two feeds):
    synthetic_spn_fmi_dictionary.xlsx / .csv   Fault Name | P Code | DTC_LB | SPN | FMI | SPN_Name
    synthetic_fleet_log.xlsx / .csv            the real telematics column names (see LOG_COLUMNS)
    cost_tat_rules.csv                         ILLUSTRATIVE labour/parts/TAT, owned by another team
    scenarios.json                             which vehicle exercises which ladder outcome

=========================  DATA & CONFIDENTIALITY  =========================
Everything here is **synthetic - illustrative**. No real TATA Motors data exists
in this repository and none is used:

  * SPNs are invented inside the SAE J1939 **manufacturer-proprietary** range
    520192-524287, so no value can be mistaken for a real SAE or OEM assignment.
  * FMI numbers and their descriptions are the **public** SAE J1939-73 definitions.
  * Fault names are invented mnemonics (RAILP_SNSR_STG), not OEM fault names.
  * Vehicle ids and registrations are obviously fake: DEMO-MAT-0001.., DM01AA0001..
  * Cost / TAT figures are illustrative placeholders. That data is owned by another
    team; these numbers must not be read as real labour rates or part prices.
  * The **P-codes are real codes from the 3.3L DTC manual**, so the downstream
    manual retrieval and the advisory text are genuine. The SPN/FMI -> P-code
    pairing itself is fictitious.

The COLUMN NAMES are the real ones from the production telematics feed, so the
same pipeline (src/telematics.py) can later be pointed at a real export offline
without code changes. Only the VALUES are synthetic.

DTC_LB is the DECIMAL failure-type byte, exactly as a real dictionary carries it.
The manual's suffix is its 2-digit uppercase HEX form: 19 -> 13, 155 -> 9B,
156 -> 9C, 243 -> F3. telematics.suffix_from_lb() does that conversion.

Deliberate edge cases, because a real dictionary is messy:
  * two AMBIGUOUS keys - one (SPN, FMI) mapping to two different P-codes
    (EGR valve jammed open/closed, exhaust-throttle valve jammed open/closed:
    one sensor, one failure mode, two possible faults);
  * a mapped P-code that is NOT in this manual (P0195-00);
  * a mapped low byte that is not in the manual (P0116 + LB 19 -> P0116-13);
  * an SPN present with some FMIs mapped and others not;
  * an SPN absent from the dictionary entirely;
  * malformed log rows and ~12% exact duplicate rows.
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, "src")

LABEL = "synthetic - illustrative"
OUT_DIR = "data/demo"
SEED = 1002
SPN_BASE = 520192          # SAE J1939 manufacturer-proprietary range starts here
SPN_MAX = 524287
N_VEHICLES, N_ROWS, N_DAYS = 200, 1000, 30
DUP_FRACTION = 0.12
START_DATE = date(2026, 3, 1)

# Public SAE J1939-73 FMI definitions (only the ones used below).
FMI_MEANING = {
    0: "Data valid but above normal operational range - most severe level",
    1: "Data valid but below normal operational range - most severe level",
    2: "Data erratic, intermittent or incorrect",
    3: "Voltage above normal or shorted to high source",
    4: "Voltage below normal or shorted to low source",
    5: "Current below normal or open circuit",
    6: "Current above normal or grounded circuit",
    7: "Mechanical system not responding or out of adjustment",
    8: "Abnormal frequency or pulse width or period",
    9: "Abnormal update rate",
    10: "Abnormal rate of change",
    11: "Root cause not known",
    13: "Out of calibration",
    15: "Data valid but above normal operating range - least severe level",
    16: "Data valid but above normal operating range - moderately severe level",
    17: "Data valid but below normal operating range - least severe level",
    18: "Data valid but below normal operating range - moderately severe level",
    19: "Received network data in error",
    31: "Condition exists",
}

# (P-code with suffix, FMI, SPN group key, SPN_Name, mnemonic fault name)
# The SPN group key gives every entry of one component the SAME synthetic SPN,
# which is what makes "SPN known, this FMI unmapped" and the ambiguous keys real.
SPEC = [
    # ---- rail_pressure ----
    ("P0192-00", 4, "RAILP", "Engine Fuel Rail Pressure Sensor Circuit", "RAILP_SNSR_STG"),
    ("P0193-00", 3, "RAILP", "Engine Fuel Rail Pressure Sensor Circuit", "RAILP_SNSR_STB"),
    ("P0194-00", 2, "RAILP", "Engine Fuel Rail Pressure Sensor Circuit", "RAILP_SNSR_DRIFT"),
    ("P0087-00", 1, "RAILDEV", "Engine Fuel Rail Pressure Deviation", "RAILP_DEV_POS"),
    ("P0088-00", 0, "RAILDEV", "Engine Fuel Rail Pressure Deviation", "RAILP_DEV_NEG"),
    # ---- coolant ----
    ("P0117-00", 4, "COOLT", "Engine Coolant Temperature Sensor Circuit", "COOLT_SNSR_STG"),
    ("P0118-00", 3, "COOLT", "Engine Coolant Temperature Sensor Circuit", "COOLT_SNSR_STB"),
    ("P0119-00", 2, "COOLT", "Engine Coolant Temperature Sensor Circuit", "COOLT_SNSR_INTERM"),
    ("P0116-00", 11, "COOLT", "Engine Coolant Temperature Sensor Circuit", "COOLT_SNSR_PLAUS"),
    # ---- engine_position ----
    ("P0335-00", 5, "CRANK", "Engine Crankshaft Position Sensor Circuit", "CRANK_SNSR_OPEN"),
    ("P0336-00", 2, "CRANK", "Engine Crankshaft Position Sensor Circuit", "CRANK_SIG_DIST"),
    ("P0340-00", 8, "CAM", "Engine Camshaft Position Sensor Circuit", "CAM_SIG_NONE"),
    ("P0341-00", 2, "CAM", "Engine Camshaft Position Sensor Circuit", "CAM_SIG_DIST"),
    # ---- injector (per-cylinder SPNs) ----
    ("P0201-00", 5, "INJ1", "Engine Injector Cylinder 1 Circuit", "INJ1_OPEN"),
    ("P0202-00", 5, "INJ2", "Engine Injector Cylinder 2 Circuit", "INJ2_OPEN"),
    ("P0203-00", 5, "INJ3", "Engine Injector Cylinder 3 Circuit", "INJ3_OPEN"),
    ("P0204-00", 5, "INJ4", "Engine Injector Cylinder 4 Circuit", "INJ4_OPEN"),
    ("P1201-00", 6, "INJ1", "Engine Injector Cylinder 1 Circuit", "INJ1_SC_HILO"),
    ("P1202-00", 6, "INJ2", "Engine Injector Cylinder 2 Circuit", "INJ2_SC_HILO"),
    # ---- egr : AMBIGUOUS KEY 1 (same SPN+FMI -> two P-codes) ----
    ("P042E-00", 7, "EGRV", "Engine EGR Valve Position", "EGRV_JAM_OPEN"),
    ("P042F-00", 7, "EGRV", "Engine EGR Valve Position", "EGRV_JAM_CLOSED"),
    ("P0405-00", 4, "EGRV", "Engine EGR Valve Position", "EGRV_POS_SRC_LO"),
    ("P0406-00", 3, "EGRV", "Engine EGR Valve Position", "EGRV_POS_SRC_HI"),
    # ---- exhaust_throttle : AMBIGUOUS KEY 2 ----
    ("P04A4-00", 7, "ETVV", "Engine Exhaust Throttle Valve Position", "ETV_JAM_OPEN"),
    ("P04A5-00", 7, "ETVV", "Engine Exhaust Throttle Valve Position", "ETV_JAM_CLOSED"),
    ("P048B-11", 17, "ETVV", "Engine Exhaust Throttle Valve Position", "ETV_POS_SRC_LO"),
    ("P048B-12", 18, "ETVV", "Engine Exhaust Throttle Valve Position", "ETV_POS_SRC_HI"),
    # ---- turbo_boost ----
    ("P0047-00", 4, "TURBOA", "Engine Turbocharger Boost Control A Circuit", "TURBO_A_LOW"),
    ("P0048-00", 3, "TURBOA", "Engine Turbocharger Boost Control A Circuit", "TURBO_A_HIGH"),
    ("P006E-00", 4, "TURBOS", "Engine Turbocharger Boost Control Supply Voltage", "TURBO_SPLY_LOW"),
    ("P006F-00", 3, "TURBOS", "Engine Turbocharger Boost Control Supply Voltage", "TURBO_SPLY_HIGH"),
    # ---- intake_air ----
    ("P0100-9B", 0, "MAFS", "Engine Intake Air Mass Flow Sensor", "MAF_RANGE_HI"),
    ("P0100-9C", 1, "MAFS", "Engine Intake Air Mass Flow Sensor", "MAF_RANGE_LO"),
    ("P0100-00", 9, "MAFS", "Engine Intake Air Mass Flow Sensor", "MAF_SENT_COMM"),
    ("P1000-00", 11, "AMBT", "Engine Intake Air Ambient Temperature Monitor", "AMBT_PLAUS"),
    ("P0401-00", 1, "EGRFLOW", "Engine Intake Air Mass Governor Deviation", "AIRMASS_GOV_POS"),
    # ---- sensor_generic (MAF A/B circuits) ----
    ("P0102-00", 1, "MAFA", "Engine Mass Air Flow Sensor A Circuit", "MAFA_CKT_LOW"),
    ("P0103-00", 0, "MAFA", "Engine Mass Air Flow Sensor A Circuit", "MAFA_CKT_HIGH"),
    ("P010C-00", 1, "MAFB", "Engine Mass Air Flow Sensor B Circuit", "MAFB_CKT_LOW"),
    ("P010D-00", 0, "MAFB", "Engine Mass Air Flow Sensor B Circuit", "MAFB_CKT_HIGH"),
    # ---- dpf_regen ----
    ("P0425-85", 0, "DOCT", "Aftertreatment DOC Inlet Gas Temperature", "DOC_TEMP_HIGH"),
    ("P0425-84", 1, "DOCT", "Aftertreatment DOC Inlet Gas Temperature", "DOC_TEMP_LOW"),
    ("P0428-00", 3, "DOCT", "Aftertreatment DOC Inlet Gas Temperature", "DOC_TEMP_STB"),
    ("P0427-00", 4, "DOCT", "Aftertreatment DOC Inlet Gas Temperature", "DOC_TEMP_STG"),
    ("P2452-95", 31, "DPFDP", "Aftertreatment DPF Delta Pressure", "DPF_DP_HOSE"),
    # ---- scr_def ----
    ("P203B-85", 0, "UREAL", "Aftertreatment Urea DEF Tank Level", "UREA_LVL_HIGH"),
    ("P242A-85", 0, "SCRT", "Aftertreatment SCR Inlet Gas Temperature", "SCR_TEMP_HIGH"),
    ("P242D-00", 3, "SCRT", "Aftertreatment SCR Inlet Gas Temperature", "SCR_TEMP_STB"),
    ("P206A-F3", 31, "DEFQ", "Aftertreatment DEF Concentration Quality", "DEF_CONC_STUCK"),
    # ---- o2_exhaust ----
    ("P2200-13", 19, "NOXU", "Aftertreatment NOx Sensor Upstream", "NOXU_NET_ERR"),
    ("P2200-86", 16, "NOXU", "Aftertreatment NOx Sensor Upstream", "NOXU_SIG_INCORR"),
    ("P229E-13", 19, "NOXD", "Aftertreatment NOx Sensor Downstream", "NOXD_NET_ERR"),
    # ---- fuel_supply ----
    ("P0180-11", 17, "FUELT", "Engine Fuel Temperature Sensor Circuit", "FUELT_SNSR_STG"),
    ("P0180-12", 18, "FUELT", "Engine Fuel Temperature Sensor Circuit", "FUELT_SNSR_STB"),
    ("P0089-00", 7, "PRV", "Engine Fuel Pressure Relief Valve", "PRV_OPEN"),
    ("P0627-13", 19, "FPRELAY", "Engine Fuel Pump Relay Circuit", "FPRELAY_OPEN"),
    ("P2264-12", 18, "WIF", "Engine Water In Fuel Indicator", "WIF_SNSR_OPEN"),
    # ---- pedal_clutch_brake ----
    ("P0120-11", 17, "APP1", "Accelerator Pedal Position Sensor 1", "APP1_STG"),
    ("P0220-11", 17, "APP2", "Accelerator Pedal Position Sensor 2", "APP2_STG"),
    ("P2135-00", 31, "APP1", "Accelerator Pedal Position Sensor 1", "APP_INCOMPAT"),
    # ---- vehicle_speed ----
    ("P0500-1F", 31, "VSPD", "Wheel Based Vehicle Speed Sensor", "VSPD_PLAUS"),
    ("P0500-1C", 0, "VSPD", "Wheel Based Vehicle Speed Sensor", "VSPD_MAX_THRESH"),
    # ---- can_network ----
    ("U0102-00", 19, "CANBUS", "CAN Bus Network Communication", "CAN_DISCONNECT"),
    ("U011A-89", 19, "CANHW", "CAN Bus Network Internal Hardware", "CAN_HW_CONN"),
    # ---- electrical ----
    ("P0107-00", 4, "MAPS", "Engine Intake Manifold Pressure Sensor Circuit", "MAP_SNSR_STG"),
    ("P0108-00", 3, "MAPS", "Engine Intake Manifold Pressure Sensor Circuit", "MAP_SNSR_STB"),
    ("P0A1B-12", 18, "STARTM", "Engine Starter Motor Control Circuit", "STARTM_STB"),
    ("P2229-00", 0, "BAROS", "Barometric Pressure Sensor Circuit", "BARO_OVERVOLT"),
    # ---- ecu_internal (P1675-00 backs the P1657 transposition scenario) ----
    ("P1675-00", 31, "EMM22", "Engine ECU Internal EMM Alarm FCCU22", "ECU_EMM_FCCU22"),
    ("P061C-00", 11, "ECURPM", "Engine ECU Internal Engine Speed Performance", "ECU_RPM_PERF"),
    # ---- level2_monitoring ----
    ("P0219-00", 0, "OVRSPD", "Engine Speed Level 2 Monitoring Overspeed", "L2_OVERSPEED"),
    # ---- deliberate edge cases ----
    # P0195-00 is NOT in this manual -> REFUSED_NOT_IN_MANUAL
    ("P0195-00", 4, "FUELTB", "Engine Fuel Temperature Sensor 2 Circuit", "FUELT2_SNSR_STG"),
    # low byte 19 (hex 13) does not exist for P0116 -> CLARIFY_LOW_BYTE
    ("P0116-13", 16, "COOLT2", "Engine Coolant Temperature Sensor Rationality", "COOLT_RATIONALITY"),
]

# Illustrative only - this data is owned by another team.
COST_RULES = [
    # key (subsystem), p_code override, labour_hours, parts_min, parts_max, tat_hours
    ("rail_pressure", "", 3.5, 8500, 24000, 24),
    ("rail_pressure", "P0192-00", 2.5, 7200, 11000, 16),
    ("coolant", "", 1.5, 1200, 3500, 8),
    ("engine_position", "", 2.0, 2600, 6400, 12),
    ("injector", "", 4.0, 9500, 38000, 36),
    ("egr", "", 3.0, 6800, 21000, 24),
    ("exhaust_throttle", "", 3.0, 7400, 19500, 24),
    ("turbo_boost", "", 5.0, 18000, 74000, 48),
    ("intake_air", "", 1.5, 1800, 5200, 8),
    ("sensor_generic", "", 1.5, 1600, 4800, 8),
    ("dpf_regen", "", 6.0, 24000, 145000, 72),
    ("scr_def", "", 4.5, 14000, 96000, 48),
    ("o2_exhaust", "", 3.5, 16500, 42000, 36),
    ("fuel_supply", "", 2.5, 3400, 15500, 16),
    ("pedal_clutch_brake", "", 1.5, 2400, 7200, 8),
    ("vehicle_speed", "", 1.0, 1400, 3800, 6),
    ("can_network", "", 2.5, 1500, 9500, 16),
    ("electrical", "", 2.0, 900, 6500, 12),
    ("ecu_internal", "", 2.0, 0, 185000, 48),
    ("level2_monitoring", "", 1.5, 0, 2500, 8),
]

LOG_COLUMNS = ["Vehicle_Id", "Registration_Number", "Event_Date", "Engine_Crank_State",
               "Amber_Warning_Lamp_Status", "Malfunction_Indicator_Lamp_Status",
               "Red_Stop_Lamp_Status", "Protect_Lamp_Status", "Flashing_Amber_Warning_Lamp",
               "Flashing_Malfunction_Indicator_Lamp", "Flashing_Red_Stop_Lamp",
               "Flashing_Protect_Lamp", "SPN_Number", "SPN_Name",
               "Failure_Mode_Identifier_Code", "Failure_Mode_Identifier_Description",
               "Fault_Occurrence_Count", "Fault_Active_Time_Minutes", "Region", "LOB", "PL"]
DICT_COLUMNS = ["Fault Name", "P Code", "DTC_LB", "SPN", "FMI", "SPN_Name"]

LAMP_ON, LAMP_OFF, LAMP_NA = "Lamp ON", "Lamp Off", "Not used"
FLASH_NA = "Unavailable/ Do not flash"
REGIONS = ["North", "South", "East", "West", "Central"]
LOBS = ["M&HCV", "I&LCV", "SCV", "Bus"]
PLS = ["LPT 1918", "LPT 2821", "Ultra 1918", "Signa 2823", "Starbus 4x2"]
CRANK = ["Engine Running", "Key On Engine Off", "Cranking"]


def suffix_from_lb(lb):
    """Decimal failure-type byte -> the manual's 2-digit uppercase hex suffix."""
    return f"{int(lb):02X}"


def build_dictionary():
    """SPEC -> dictionary rows. SPNs are assigned per component group, in order."""
    spn_of, rows = {}, []
    for code, fmi, group, spn_name, fault in SPEC:
        if group not in spn_of:
            spn = SPN_BASE + 17 * (len(spn_of) + 1)      # deterministic, spread out
            assert SPN_BASE <= spn <= SPN_MAX
            spn_of[group] = spn
        base, suffix = code.split("-")
        rows.append({"Fault Name": fault, "P Code": base, "DTC_LB": int(suffix, 16),
                     "SPN": spn_of[group], "FMI": fmi, "SPN_Name": spn_name})
    return rows, spn_of


def write_csv(path, columns, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def write_xlsx(path, columns, rows, sheet):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(columns)
    for r in rows:
        ws.append([r[c] for c in columns])
    wb.save(path)


def main():
    rng = random.Random(SEED)
    os.makedirs(OUT_DIR, exist_ok=True)
    drows, spn_of = build_dictionary()
    mapped = {}                      # (spn, fmi) -> [code_full, ...]
    for r in drows:
        key = (r["SPN"], r["FMI"])
        mapped.setdefault(key, []).append(f"{r['P Code']}-{suffix_from_lb(r['DTC_LB'])}")
    name_of_spn = {r["SPN"]: r["SPN_Name"] for r in drows}

    # ---------------- vehicles ----------------
    vehicles = [f"DEMO-MAT-{i:04d}" for i in range(1, N_VEHICLES + 1)]
    regs = {v: f"DM{rng.randint(1, 49):02d}{chr(65 + rng.randrange(26))}"
               f"{chr(65 + rng.randrange(26))}{rng.randint(1, 9999):04d}" for v in vehicles}
    meta = {v: {"Region": rng.choice(REGIONS), "LOB": rng.choice(LOBS), "PL": rng.choice(PLS)}
            for v in vehicles}

    def lamps(kind):
        """Lamp columns in the feed's own vocabulary."""
        off = {"Amber_Warning_Lamp_Status": LAMP_OFF, "Malfunction_Indicator_Lamp_Status": LAMP_OFF,
               "Red_Stop_Lamp_Status": LAMP_OFF, "Protect_Lamp_Status": LAMP_OFF,
               "Flashing_Amber_Warning_Lamp": FLASH_NA, "Flashing_Malfunction_Indicator_Lamp": FLASH_NA,
               "Flashing_Red_Stop_Lamp": FLASH_NA, "Flashing_Protect_Lamp": FLASH_NA}
        if kind == "red":
            off["Red_Stop_Lamp_Status"] = LAMP_ON
        elif kind == "amber":
            off["Amber_Warning_Lamp_Status"] = LAMP_ON
        elif kind == "mil":
            off["Malfunction_Indicator_Lamp_Status"] = LAMP_ON
        elif kind == "protect":
            off["Protect_Lamp_Status"] = LAMP_ON
        elif kind == "flash_red":
            off["Flashing_Red_Stop_Lamp"] = "Lamp ON"
        elif kind == "none":
            off["Amber_Warning_Lamp_Status"] = LAMP_NA
        return off

    def row(vid, spn, spn_name, fmi, day, *, lamp="amber", occ=1, active=5, crank=None):
        d = (START_DATE + timedelta(days=day)).isoformat()
        return {"Vehicle_Id": vid, "Registration_Number": regs[vid], "Event_Date": d,
                "Engine_Crank_State": crank or rng.choice(CRANK),
                **lamps(lamp),
                "SPN_Number": spn, "SPN_Name": spn_name,
                "Failure_Mode_Identifier_Code": fmi,
                "Failure_Mode_Identifier_Description": FMI_MEANING.get(fmi, "Condition exists"),
                "Fault_Occurrence_Count": occ, "Fault_Active_Time_Minutes": active,
                **meta[vid]}

    rows, scen = [], {}

    # ---------------- scripted scenario vehicles ----------------
    def scripted(name, vid, items, note):
        scen[name] = {"vehicle_id": vid, "registration": regs[vid], "note": note}
        rows.extend(items)

    v = vehicles[0]      # normal advisory: rail pressure short to ground
    spn = spn_of["RAILP"]
    scripted("normal_advisory", v,
             [row(v, spn, name_of_spn[spn], 4, 2, lamp="mil", occ=3, active=22)],
             "single unambiguous mapping -> ADVISORY with fix blocks")

    v = vehicles[1]      # red stop lamp -> CRITICAL
    spn = spn_of["INJ1"]
    scripted("red_stop_lamp", v,
             [row(v, spn, name_of_spn[spn], 5, 4, lamp="red", occ=2, active=9)],
             "Red stop lamp ON -> severity CRITICAL")

    v = vehicles[2]      # exact duplicates
    spn = spn_of["COOLT"]
    dup = row(v, spn, name_of_spn[spn], 4, 6, lamp="amber", occ=1, active=3)
    scripted("duplicate_rows", v, [dict(dup), dict(dup), dict(dup)],
             "3 identical rows -> 1 episode after de-duplication")

    v = vehicles[3]      # ambiguous key 1 (EGR valve jammed open/closed)
    spn = spn_of["EGRV"]
    scripted("ambiguous_key", v,
             [row(v, spn, name_of_spn[spn], 7, 8, lamp="amber", occ=4, active=51)],
             "one (SPN,FMI) mapped to P042E-00 and P042F-00 -> AMBIGUOUS_MAPPING_CANDIDATES")

    v = vehicles[4]      # ambiguous key 2 (exhaust throttle valve)
    spn = spn_of["ETVV"]
    scripted("ambiguous_key_2", v,
             [row(v, spn, name_of_spn[spn], 7, 9, lamp="protect", occ=1, active=4)],
             "second ambiguous key -> P04A4-00 and P04A5-00")

    v = vehicles[5]      # FMI unmapped for a known SPN
    spn = spn_of["RAILP"]
    scripted("fmi_unmapped", v,
             [row(v, spn, name_of_spn[spn], 10, 11, lamp="amber", occ=1, active=6)],
             "SPN known, FMI 10 not mapped -> FALLBACK_CANDIDATES (never auto-advised)")

    v = vehicles[6]      # unknown SPN
    unknown_spn = SPN_MAX - 3
    assert all(unknown_spn != s for s in spn_of.values())
    scripted("unknown_spn", v,
             [row(v, unknown_spn, "Unlisted Proprietary Parameter", 4, 12, lamp="amber")],
             "SPN not in the dictionary -> UNMAPPED, logged, no advisory")

    v = vehicles[7]      # mapped code absent from the manual
    spn = spn_of["FUELTB"]
    scripted("code_not_in_manual", v,
             [row(v, spn, name_of_spn[spn], 4, 13, lamp="mil", occ=2, active=14)],
             "maps to P0195-00, which this manual does not cover -> REFUSED_NOT_IN_MANUAL")

    v = vehicles[8]      # low byte absent for a known base code
    spn = spn_of["COOLT2"]
    scripted("low_byte_not_in_manual", v,
             [row(v, spn, name_of_spn[spn], 16, 14, lamp="amber", occ=1, active=7)],
             "maps to P0116-13; base P0116 exists, that low byte does not -> CLARIFY_LOW_BYTE")

    v = vehicles[9]      # malformed rows
    spn = spn_of["CAM"]
    bad1 = row(v, spn, name_of_spn[spn], 8, 15)
    bad1["SPN_Number"] = "not-a-number"
    bad2 = row(v, spn, name_of_spn[spn], 8, 16)
    bad2["Failure_Mode_Identifier_Code"] = 99                      # outside 0..31
    bad3 = row(v, spn, name_of_spn[spn], 8, 17)
    bad3["Fault_Occurrence_Count"] = -4                            # must be >= 1
    bad4 = row(v, spn, name_of_spn[spn], 8, 18)
    bad4["Event_Date"] = "2026-02-31"                              # impossible date
    bad5 = row(v, spn, name_of_spn[spn], 8, 19)
    bad5["Vehicle_Id"] = ""                                        # empty id
    good = row(v, spn, name_of_spn[spn], 8, 20, lamp="amber", occ=6, active=75)
    scripted("malformed_rows", v, [bad1, bad2, bad3, bad4, bad5, good],
             "6 rows: 4 malformed ones are rejected on this vehicle's report, a 5th has an "
             "empty Vehicle_Id so it cannot be attributed to any vehicle and is counted in "
             "fleet_summary's rows_rejected, and the 6th is valid and still advises")

    v = vehicles[10]     # telemetry resolves to P1000-00 (technician may type P0100-00)
    spn = spn_of["AMBT"]
    scripted("transposition_P1000", v,
             [row(v, spn, name_of_spn[spn], 11, 21, lamp="amber", occ=1, active=5)],
             "telemetry -> P1000-00; a technician typing P0100-00 must be flagged MISMATCH "
             "with 'possible transposition'")

    v = vehicles[11]     # telemetry resolves to P1675-00 (technician may type P1657-00)
    spn = spn_of["EMM22"]
    scripted("transposition_P1675", v,
             [row(v, spn, name_of_spn[spn], 31, 22, lamp="mil", occ=2, active=31)],
             "telemetry -> P1675-00; a technician typing P1657-00 must be flagged MISMATCH "
             "with 'possible transposition'")

    v = vehicles[12]     # severity cap: occurrence/active raise, but never to CRITICAL
    spn = spn_of["MAFA"]
    scripted("severity_cap", v,
             [row(v, spn, name_of_spn[spn], 1, 23, lamp="none", occ=9, active=240)],
             "no lamp but occurrence 9 / 240 min -> raised to HIGH, never CRITICAL")

    v = vehicles[13]     # flashing red stop lamp -> CRITICAL
    spn = spn_of["PRV"]
    scripted("flashing_red_lamp", v,
             [row(v, spn, name_of_spn[spn], 7, 24, lamp="flash_red", occ=1, active=2)],
             "Flashing red stop lamp -> severity CRITICAL")

    scripted_count = len(rows)

    # ---------------- bulk random rows ----------------
    keys = sorted(mapped)
    scenario_vehicles = {d["vehicle_id"] for d in scen.values()}
    bulk_vehicles = [v for v in vehicles if v not in scenario_vehicles]
    while len(rows) < int(N_ROWS * (1 - DUP_FRACTION)):
        vid = rng.choice(bulk_vehicles)
        spn, fmi = rng.choice(keys)
        # a slice of rows get an unmapped FMI or an unknown SPN, as real feeds do
        roll = rng.random()
        if roll < 0.04:
            fmi = rng.choice([10, 13, 11, 31])
        elif roll < 0.06:
            spn, _ = (SPN_MAX - rng.randint(5, 60), None)
        lamp = rng.choices(["amber", "mil", "protect", "red", "none", "off"],
                           weights=[34, 26, 12, 4, 12, 12])[0]
        rows.append(row(vid, spn, name_of_spn.get(spn, "Unlisted Proprietary Parameter"), fmi,
                        rng.randrange(N_DAYS), lamp=lamp,
                        occ=rng.choices([1, 2, 3, 5, 8, 14], weights=[40, 22, 14, 12, 8, 4])[0],
                        active=rng.choice([1, 3, 8, 20, 45, 61, 120, 300])))

    # ---------------- ~12% exact duplicate rows ----------------
    n_dup = N_ROWS - len(rows)
    for _ in range(n_dup):
        rows.append(dict(rng.choice(rows[scripted_count:])))
    rng.shuffle(rows)
    # The log carries EXACTLY the production feed's columns - no extra marker column,
    # so a real export can be dropped in unchanged. The synthetic label lives in
    # data/demo/README.md and in scenarios.json instead.
    log_cols = LOG_COLUMNS

    # ---------------- write ----------------
    write_csv(f"{OUT_DIR}/synthetic_spn_fmi_dictionary.csv", DICT_COLUMNS, drows)
    write_xlsx(f"{OUT_DIR}/synthetic_spn_fmi_dictionary.xlsx", DICT_COLUMNS, drows, "dictionary")
    write_csv(f"{OUT_DIR}/synthetic_fleet_log.csv", log_cols, rows)
    write_xlsx(f"{OUT_DIR}/synthetic_fleet_log.xlsx", log_cols, rows, "fleet_log")
    write_csv(f"{OUT_DIR}/cost_tat_rules.csv",
              ["subsystem", "p_code", "labour_hours", "parts_cost_min_inr",
               "parts_cost_max_inr", "tat_hours"],
              [{"subsystem": s, "p_code": p, "labour_hours": lh, "parts_cost_min_inr": pmin,
                "parts_cost_max_inr": pmax, "tat_hours": tat}
               for s, p, lh, pmin, pmax, tat in COST_RULES])

    ambiguous = {f"{k[0]}:{k[1]}": v for k, v in sorted(mapped.items()) if len(v) > 1}
    scenarios = {
        "_meta": {
            "label": LABEL, "phase": "10.2", "seed": SEED,
            "confidentiality": "Synthetic. No real TATA Motors telematics data or SPN/FMI "
                               "dictionary is used or reproduced. Column names are the real "
                               "ones so the pipeline can later run on a real export offline; "
                               "only the values are invented.",
            "cost_tat": "ILLUSTRATIVE placeholders - that data is owned by another team.",
            "dictionary_entries": len(drows),
            "subsystems_covered": len({r["SPN_Name"] for r in drows}),
            "log_rows": len(rows), "vehicles": N_VEHICLES, "days": N_DAYS,
            "duplicate_fraction_target": DUP_FRACTION,
            "ambiguous_keys": ambiguous,
        },
        "scenarios": scen,
    }
    with open(f"{OUT_DIR}/scenarios.json", "w") as f:
        json.dump(scenarios, f, indent=1)
        f.write("\n")

    with open(f"{OUT_DIR}/README.md", "w") as f:
        f.write(f"""# data/demo — {LABEL}

**Every file in this directory is {LABEL}.** No real TATA Motors telematics data or
SPN/FMI dictionary exists in this repository, and none is used or reproduced.

| file | what it is |
|---|---|
| `synthetic_spn_fmi_dictionary.xlsx` / `.csv` | {len(drows)} invented SPN/FMI -> P-code mappings. Columns are the real ones: `Fault Name | P Code | DTC_LB | SPN | FMI | SPN_Name`. `DTC_LB` is the DECIMAL failure-type byte; the manual's suffix is its 2-digit uppercase HEX form (19 -> 13, 155 -> 9B, 156 -> 9C). |
| `synthetic_fleet_log.xlsx` / `.csv` | {len(rows)} rows, {N_VEHICLES} fake vehicles, {N_DAYS} days, with the production feed's exact column names and lamp vocabulary ("Lamp ON" / "Lamp Off" / "Not used", flashing "{FLASH_NA}"). ~{DUP_FRACTION:.0%} exact duplicate rows, plus malformed rows. |
| `cost_tat_rules.csv` | **ILLUSTRATIVE ONLY.** Labour hours, parts cost range (INR) and turnaround per subsystem. This data is owned by another team; these numbers are placeholders and must not be read as real rates or prices. |
| `scenarios.json` | which fake vehicle exercises which ladder outcome. |

What is invented, and what is real:

* **Invented:** SPNs (inside the SAE J1939 manufacturer-proprietary range
  {SPN_BASE}-{SPN_MAX}, so no value can be mistaken for a real SAE or OEM
  assignment), fault-name mnemonics, vehicle ids (`DEMO-MAT-0001`..),
  registrations (`DM01AA0001`..), dates, lamp states, counts, region/LOB/PL, and
  every cost or TAT figure.
* **Public standard:** the FMI numbers and their descriptions (SAE J1939-73).
* **Real:** the P-codes are real codes from the 3.3L DTC manual, so the manual
  retrieval and advisory text downstream are genuine. The SPN/FMI -> P-code
  pairing itself is fictitious.

Regenerate deterministically (seed {SEED}):

```bash
PYTHONPATH=src .venv/bin/python scripts/gen_demo_data.py
PYTHONPATH=src .venv/bin/python scripts/validate_demo_data.py
```
""")
    print(f"[{LABEL}] wrote {OUT_DIR}/")
    print(f"  dictionary : {len(drows)} entries, {len(spn_of)} synthetic SPNs, "
          f"{len({r['SPN_Name'] for r in drows})} SPN names")
    print(f"  ambiguous keys: {ambiguous}")
    print(f"  fleet log  : {len(rows)} rows, {N_VEHICLES} vehicles, {N_DAYS} days, "
          f"{n_dup} duplicate rows ({n_dup / len(rows):.1%})")
    print(f"  scenarios  : {len(scen)}")


if __name__ == "__main__":
    main()
