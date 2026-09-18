"""
Phase 9.4 — SPN/FMI -> P-code normalization ladder (demonstration of the METHOD).

    PYTHONPATH=src .venv/bin/python src/normalize.py            # run the synthetic log
    PYTHONPATH=src .venv/bin/python src/normalize.py --demo     # + full advisories

Operates on SYNTHETIC data (data/synthetic/, "synthetic - illustrative"). The real
SPN/FMI dictionary is TATA Motors proprietary and is not used. This is a functional
demonstration with edge-case coverage, NOT an accuracy result: a deterministic rule
applied to data built for it resolves "correctly" by construction.

Additive: production retrieval is not modified. The manual is reached only through
Retriever.retrieve(<code>), i.e. the exact-code router including the Phase 9.3b
refusal / clarification behaviour, and advisories reuse advise.fix_block (Phase 9.1).

LADDER (first rung that applies wins; every rung is recorded in the trace)

  R0  validate row     spn int 0..524287 (19-bit), fmi int 0..31, occurrences int >= 1,
                       ISO-8601 timestamp, non-empty vehicle_id
                         fail -> REJECTED_MALFORMED   (logged, no advisory)
      de-duplicate     identical (vehicle_id, timestamp, spn, fmi) already seen
                         -> DUPLICATE_SKIPPED        (logged, no advisory)
  R1  exact (spn, fmi) in dictionary -> p_code + dtc_low_byte -> code_full
                       -> Retriever.retrieve(code_full)
                         exact_code        -> ADVISORY          (deterministic fix block)
                         suffix_not_found  -> CLARIFY_LOW_BYTE  (9.3b: variants listed, no fix block)
                         unknown_code      -> REFUSED_NOT_IN_MANUAL (9.3b: explicit refusal)
  R2  spn known, fmi unmapped
                       SPN-only: every mapped entry of that SPN becomes a CANDIDATE,
                       ordered by nearest FMI (|fmi - mapped|, then lower fmi); the
                       nearest is marked. -> FALLBACK_CANDIDATES (no advisory)
  R3  spn unknown      -> UNMAPPED_NO_ADVISORY (logged)

WHY A FALLBACK NEVER BECOMES AN ADVISORY (ADVISE_ON_FALLBACK = False)
The FMI encodes the failure MODE, and numerically adjacent FMIs are often opposite
faults: FMI 3 is "shorted high", FMI 4 is "shorted low", and FMI 5 ("open circuit")
is numerically nearest to FMI 4 although an open circuit is described together with
short-to-battery (P0193-00), not short-to-ground (P0192-00). Serving the nearest-FMI
procedure would assert a repair for a fault that was not reported. The ladder
therefore surfaces candidates for a human to confirm, consistent with the 9.3b
"did you mean" policy (surfaced, never auto-selected).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

DICT_PATH = "data/synthetic/spn_fmi_dictionary.json"
LOG_PATH = "data/synthetic/telematics_log.jsonl"
LABEL = "synthetic - illustrative"
ADVISE_ON_FALLBACK = False
SPN_MAX, FMI_MAX = 524287, 31

P_CODE_RE = re.compile(r"^[PU][0-9A-F]{4}$")
LOW_BYTE_RE = re.compile(r"^[0-9A-F]{2}$")

OUTCOMES = ["ADVISORY", "CLARIFY_LOW_BYTE", "REFUSED_NOT_IN_MANUAL", "FALLBACK_CANDIDATES",
            "UNMAPPED_NO_ADVISORY", "REJECTED_MALFORMED", "DUPLICATE_SKIPPED"]


# ---------------------------------------------------------------- dictionary
class DictionaryError(ValueError):
    pass


def load_dictionary(path=DICT_PATH):
    """{(spn, fmi): entry}. Validates every entry and rejects conflicting mappings."""
    blob = json.load(open(path))
    table = {}
    for e in blob["entries"]:
        spn, fmi = e.get("spn"), e.get("fmi")
        if not (isinstance(spn, int) and 0 <= spn <= SPN_MAX and isinstance(fmi, int)
                and 0 <= fmi <= FMI_MAX):
            raise DictionaryError(f"bad spn/fmi in entry {e}")
        if not (P_CODE_RE.match(str(e.get("p_code", ""))) and
                LOW_BYTE_RE.match(str(e.get("dtc_low_byte", "")))):
            raise DictionaryError(f"bad p_code/dtc_low_byte in entry {e}")
        key = (spn, fmi)
        if key in table and (table[key]["p_code"], table[key]["dtc_low_byte"]) != \
                (e["p_code"], e["dtc_low_byte"]):
            raise DictionaryError(f"conflicting mappings for SPN {spn} FMI {fmi}")
        table[key] = e
    return table, blob.get("fmi_meaning", {})


# ---------------------------------------------------------------- row validation
def validate_row(row):
    """Returns a list of problems (empty = valid)."""
    problems = []
    spn, fmi, occ = row.get("spn"), row.get("fmi"), row.get("occurrences")
    if not isinstance(spn, int) or isinstance(spn, bool):
        problems.append(f"spn missing or not an integer ({spn!r})")
    elif not 0 <= spn <= SPN_MAX:
        problems.append(f"spn {spn} outside the 19-bit range 0..{SPN_MAX}")
    if not isinstance(fmi, int) or isinstance(fmi, bool):
        problems.append(f"fmi missing or not an integer ({fmi!r})")
    elif not 0 <= fmi <= FMI_MAX:
        problems.append(f"fmi {fmi} outside 0..{FMI_MAX}")
    if not isinstance(occ, int) or isinstance(occ, bool) or occ < 1:
        problems.append(f"occurrences must be an integer >= 1 ({occ!r})")
    if not str(row.get("vehicle_id") or "").strip():
        problems.append("vehicle_id empty")
    try:
        datetime.fromisoformat(str(row.get("timestamp")).replace("Z", "+00:00"))
    except ValueError:
        problems.append(f"timestamp not valid ISO-8601 ({row.get('timestamp')!r})")
    return problems


# ---------------------------------------------------------------- the ladder
class Normalizer:
    def __init__(self, retriever, dict_path=DICT_PATH):
        self.R = retriever
        self.table, self.fmi_meaning = load_dictionary(dict_path)
        self.by_spn = {}
        for (spn, fmi), e in sorted(self.table.items()):
            self.by_spn.setdefault(spn, []).append(e)
        self.seen = set()

    def _resolve_code(self, code_full):
        """Manual lookup through the production exact-code router (incl. 9.3b)."""
        out = self.R.retrieve(code_full)
        t = out["trace"]
        return out["mode"], [i["record"] for i in out["results"]], t

    def normalize(self, row):
        trace = {"input": {k: row.get(k) for k in ("timestamp", "vehicle_id", "spn", "fmi", "occurrences")},
                 "ladder": [], "label": LABEL}

        def step(rung, result, **kw):
            trace["ladder"].append({"rung": rung, "result": result, **kw})

        # R0 - validation and de-duplication
        problems = validate_row(row)
        if problems:
            step("R0 validate", "fail", problems=problems)
            return {**trace, "outcome": "REJECTED_MALFORMED", "resolved_code": None,
                    "message": "Row rejected (malformed): " + "; ".join(problems)}
        step("R0 validate", "ok")
        key = (row["vehicle_id"], row["timestamp"], row["spn"], row["fmi"])
        if key in self.seen:
            step("R0 de-duplicate", "duplicate")
            return {**trace, "outcome": "DUPLICATE_SKIPPED", "resolved_code": None,
                    "message": "Identical row already processed; skipped."}
        self.seen.add(key)
        step("R0 de-duplicate", "new")

        spn, fmi = row["spn"], row["fmi"]
        fmi_text = self.fmi_meaning.get(str(fmi), "undefined in this dictionary")

        # R1 - exact SPN + FMI
        e = self.table.get((spn, fmi))
        if e is not None:
            code_full = f"{e['p_code']}-{e['dtc_low_byte']}"
            step("R1 exact (spn,fmi)", "hit", p_code=e["p_code"], dtc_low_byte=e["dtc_low_byte"],
                 code_full=code_full, dictionary_description=e["description"])
            mode, recs, t = self._resolve_code(code_full)
            step("R1 manual lookup", mode, lookup=t.get("lookup"))
            if mode == "exact_code" and recs:
                return {**trace, "outcome": "ADVISORY", "resolved_code": code_full,
                        "records": [f"{r['code_full']}@p{r['page']}#{r['occurrence']}" for r in recs],
                        "message": f"SPN {spn} FMI {fmi} -> {code_full}: manual entry found."}
            if mode == "suffix_not_found":
                return {**trace, "outcome": "CLARIFY_LOW_BYTE", "resolved_code": code_full,
                        "known_variants": t.get("known_variants", []),
                        "did_you_mean": t.get("did_you_mean", []), "message": t["message"]}
            if mode == "unknown_code":
                return {**trace, "outcome": "REFUSED_NOT_IN_MANUAL", "resolved_code": code_full,
                        "did_you_mean": t.get("did_you_mean", []), "message": t["message"]}
            # defensive: any other router outcome is never served as an advisory
            return {**trace, "outcome": "UNMAPPED_NO_ADVISORY", "resolved_code": code_full,
                    "message": f"Unexpected router mode {mode!r} for {code_full}; no advisory."}
        step("R1 exact (spn,fmi)", "miss")

        # R2 - SPN known, FMI unmapped: candidates only
        mapped = self.by_spn.get(spn)
        if mapped:
            cands = sorted(mapped, key=lambda m: (abs(m["fmi"] - fmi), m["fmi"]))
            out = []
            for i, m in enumerate(cands):
                code_full = f"{m['p_code']}-{m['dtc_low_byte']}"
                mode, _, _ = self._resolve_code(code_full)
                out.append({"fmi": m["fmi"], "fmi_distance": abs(m["fmi"] - fmi),
                            "code_full": code_full, "in_manual": mode == "exact_code",
                            "nearest": i == 0})
            step("R2 spn-only / nearest-fmi", "candidates", n=len(out),
                 nearest_fmi=out[0]["fmi"], advise_on_fallback=ADVISE_ON_FALLBACK)
            return {**trace, "outcome": "FALLBACK_CANDIDATES", "resolved_code": None,
                    "candidates": out,
                    "message": (f"SPN {spn} is known but FMI {fmi} ({fmi_text}) has no mapping. "
                                f"No advisory is issued: an FMI is a failure mode and a "
                                f"neighbouring FMI may be a different fault. Candidates for a "
                                f"technician to confirm: "
                                + ", ".join(f"{c['code_full']} (FMI {c['fmi']}"
                                            + (", nearest" if c["nearest"] else "") + ")"
                                            for c in out) + ".")}
        step("R2 spn-only / nearest-fmi", "spn unknown")

        # R3 - nothing to map
        return {**trace, "outcome": "UNMAPPED_NO_ADVISORY", "resolved_code": None,
                "message": f"SPN {spn} FMI {fmi} is not in the dictionary; no advisory. Logged."}


def advisory_for(result, R):
    """Deterministic fix blocks (Phase 9.1) for an ADVISORY outcome only."""
    if result["outcome"] != "ADVISORY":
        return None
    import advise as V
    return [V.fix_block(R._rec(rid)) for rid in result["records"]]


def load_log(path=LOG_PATH):
    rows = []
    for n, line in enumerate(open(path), 1):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "_meta" in obj:
            continue
        rows.append({"line": n, **obj})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="print full advisories for demo rows")
    ap.add_argument("--out", default="data/experiments/9_4/normalization_run.json")
    a = ap.parse_args()

    from cli import quiet_stderr
    with quiet_stderr():
        from retrieve import Retriever
        R = Retriever()
    N = Normalizer(R)
    results = []
    print(f"[{LABEL}]")
    print(f"{'line':>4s}  {'vehicle':13s} {'SPN':>7s} {'FMI':>4s}  {'resolved':10s} outcome")
    for row in load_log():
        res = N.normalize(row)
        res["line"] = row["line"]
        results.append(res)
        i = res["input"]
        print(f"{row['line']:4d}  {str(i['vehicle_id']):13s} {str(i['spn']):>7s} "
              f"{str(i['fmi']):>4s}  {str(res['resolved_code'] or '-'):10s} {res['outcome']}")
    counts = {o: sum(r["outcome"] == o for r in results) for o in OUTCOMES}
    print("\noutcome counts:", counts)

    if a.demo:
        for r in results:
            if r["outcome"] in ("ADVISORY", "FALLBACK_CANDIDATES", "UNMAPPED_NO_ADVISORY",
                                "REFUSED_NOT_IN_MANUAL", "CLARIFY_LOW_BYTE"):
                print("\n" + "=" * 78)
                print(f"line {r['line']}: {r['input']}  [{LABEL}]")
                for s in r["ladder"]:
                    print(f"  {s}")
                print(f"OUTCOME: {r['outcome']}\n{r['message']}")
                adv = advisory_for(r, R)
                if adv:
                    print()
                    print(adv[0]["text"])

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"label": LABEL, "framing": "functional demonstration + edge-case coverage; "
               "NOT an accuracy result", "counts": counts, "results": results},
              open(a.out, "w"), indent=1, ensure_ascii=False)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
