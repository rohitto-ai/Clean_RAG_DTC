"""
Phase 10.4 — drive every demo preset through the API and print PASS/FAIL.

    PYTHONPATH=src .venv/bin/python scripts/demo_smoke.py            # in-process
    PYTHONPATH=src .venv/bin/python scripts/demo_smoke.py --base http://127.0.0.1:8000

This is the pre-demo check: it exercises exactly what the website's "Demo presets"
menu triggers, so a failure here means the demo would break on stage. Exit 1 on
any failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, "src")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

RESULTS = []

SYMPTOM_PRESETS = [
    ("coolant gauge stuck at the bottom", "answer"),
    ("how do I change a tyre", "refuse"),
    ("what is the warranty period on this engine", "refuse"),
]
# Phase 13.1 - the conversational presets. Each must come back with mode
# "conversational", no results, no citations, and a why block whose steps are all
# RULE: the point of the filter is that nothing was retrieved.
CONVERSATIONAL_PRESETS = [
    ("hi", "GREETING"),
    ("thanks a lot", "THANKS"),
    ("no issue, the vehicle is running fine", "NO_PROBLEM"),
]
# A pleasantry with a fault attached must NOT be intercepted.
CONVERSATIONAL_NEGATIVE = [
    "hi, engine knocking at full load",
    "starts fine but black smoke under load",
]

VERIFY_PRESETS = [
    ("transposition_P1000", "P0100-00", "P1000-00"),
    ("transposition_P1675", "P1657-00", "P1675-00"),
]
EXPECTED_OUTCOME = {
    "normal_advisory": "ADVISORY", "red_stop_lamp": "ADVISORY",
    "duplicate_rows": "ADVISORY", "ambiguous_key": "AMBIGUOUS_MAPPING_CANDIDATES",
    "ambiguous_key_2": "AMBIGUOUS_MAPPING_CANDIDATES",
    "fmi_unmapped": "FALLBACK_CANDIDATES", "unknown_spn": "UNMAPPED",
    "code_not_in_manual": "REFUSED_NOT_IN_MANUAL",
    "low_byte_not_in_manual": "CLARIFY_LOW_BYTE", "malformed_rows": "ADVISORY",
    "transposition_P1000": "ADVISORY", "transposition_P1675": "ADVISORY",
    "severity_cap": "ADVISORY", "flashing_red_lamp": "ADVISORY",
}
WHY_KEYS = {"route", "ladder", "retrieval", "gate", "citations", "severity_reasons",
            "steps", "codes"}


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def why_ok(body):
    w = body.get("why")
    return isinstance(w, dict) and WHY_KEYS <= set(w) and all(
        s.get("label") in ("RULE", "AI") for s in w.get("steps", []))


class Client:
    """Either an in-process TestClient or a live server over HTTP."""

    def __init__(self, base=None):
        self.base = base
        if base:
            import urllib.request
            self._urllib = urllib.request
            self._ctx = None
        else:
            from fastapi.testclient import TestClient
            import app as M
            self._ctx = TestClient(M.app)
            self.app = M

    def __enter__(self):
        if self._ctx:
            self._ctx.__enter__()
        return self

    def __exit__(self, *a):
        if self._ctx:
            self._ctx.__exit__(*a)

    @staticmethod
    def _body(content_type, raw):
        """Static assets are not JSON, so only parse when the server says JSON."""
        if not raw:
            return {}
        if "json" not in (content_type or ""):
            return {"_bytes": len(raw)}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"detail": raw.decode(errors="replace")[:200]}

    def get(self, path):
        if self._ctx:
            r = self._ctx.get(path)
            return r.status_code, self._body(r.headers.get("content-type"), r.content)
        return self._http("GET", path, None)

    def post(self, path, body=None):
        if self._ctx:
            r = self._ctx.post(path, json=body or {})
            return r.status_code, self._body(r.headers.get("content-type"), r.content)
        return self._http("POST", path, body or {})

    def _http(self, method, path, body):
        import urllib.error
        data = json.dumps(body).encode() if body is not None else None
        req = self._urllib.Request(self.base.rstrip("/") + path, data=data, method=method,
                                   headers={"content-type": "application/json"}
                                   if data else {})
        try:
            with self._urllib.urlopen(req, timeout=60) as r:
                return r.status, self._body(r.headers.get("content-type"), r.read())
        except urllib.error.HTTPError as e:
            return e.code, self._body(e.headers.get("content-type"), e.read())
        except Exception as e:
            # a dead or unreachable server must read as a clean FAIL before a demo,
            # not as a traceback
            return 0, {"detail": f"cannot reach {self.base}: {e}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="drive a running server instead of an in-process app")
    a = ap.parse_args()

    t0 = time.perf_counter()
    with Client(a.base) as c:
        print(f"[demo smoke] {'live ' + a.base if a.base else 'in-process app'} "
              f"(ready in {time.perf_counter() - t0:.1f}s)\n")
        if a.base:
            st, probe = c.get("/health")
            if st != 200:
                print(f"  [FAIL] the server at {a.base} is not answering — "
                      f"{probe.get('detail', st)}")
                print("\n==== DEMO SMOKE: 0/1 passed ====")
                sys.exit(1)

        print("== service ==")
        st, h = c.get("/health")
        check("GET /health is ok", st == 200 and h.get("status") == "ok", str(st))
        check("determinism hash is the adopted one",
              h.get("determinism_hash") == "ffff9bc707d8754d", str(h.get("determinism_hash")))
        check("the service reports lexicon v2 NOT adopted",
              h.get("versions", {}).get("lexicon_v2_adopted") is False)
        for path in ("/", "/style.css", "/app.js"):
            stx, _ = c.get(path)
            check(f"static {path} is served", stx == 200, str(stx))

        print("\n== presets: scenarios ==")
        st, s = c.get("/scenarios")
        check("GET /scenarios is ok", st == 200 and len(s.get("scenarios", {})) == 14,
              f"{len(s.get('scenarios', {}))} scenarios")
        scen = s["scenarios"]
        for name, want in EXPECTED_OUTCOME.items():
            d = scen.get(name)
            if not d:
                check(f"preset {name} exists", False)
                continue
            stv, v = c.get(f"/vehicle/{d['vehicle_id']}")
            outs = [e["outcome"] for e in v.get("episodes", [])]
            check(f"preset {name:24s} -> {want}",
                  stv == 200 and want in outs and why_ok(v), f"{stv} {outs}")

        print("\n== presets: vehicle detail ==")
        stv, v = c.get(f"/vehicle/{scen['normal_advisory']['vehicle_id']}")
        e = v["episodes"][0]
        check("ADVISORY carries fix blocks with a manual page",
              e["fix_blocks"] and e["fix_blocks"][0]["page"] and v["why"]["citations"])
        check("illustrative cost sits under its own labelled key",
              e["illustrative_cost_tat"]["label"].startswith("Illustrative")
              and "cost_tat" not in e)
        stv2, v2 = c.get(f"/vehicle/{scen['normal_advisory']['registration']}")
        check("registration lookup resolves to the same vehicle",
              stv2 == 200 and v2["vehicle_id"] == scen["normal_advisory"]["vehicle_id"])
        sta, amb = c.get(f"/vehicle/{scen['ambiguous_key']['vehicle_id']}")
        ae = amb["episodes"][0]
        check("ambiguous preset lists candidates and advises none",
              len(ae["candidates"]) == 2 and not ae["fix_blocks"])

        print("\n== presets: technician-reported code ==")
        for key, typed, truth in VERIFY_PRESETS:
            vid = scen[key]["vehicle_id"]
            stc, r = c.post("/verify-code", {"vehicle_id": vid, "reported_code": typed})
            check(f"typing {typed} on {vid} -> MISMATCH + {truth}",
                  stc == 200 and r["status"] == "MISMATCH"
                  and r["possible_transposition"] == [truth]
                  and r["auto_replaced"] is False and why_ok(r),
                  f"{r.get('status')} {r.get('possible_transposition')}")
        vid = scen["transposition_P1000"]["vehicle_id"]
        stc, r = c.post("/verify-code", {"vehicle_id": vid, "reported_code": "P1000-00"})
        check("the correct code verifies as MATCH", r["status"] == "MATCH")

        print("\n== presets: service query ==")
        for q, want in SYMPTOM_PRESETS:
            sts, res = c.post("/symptom", {"query": q, "summary": False})
            decision = "refuse" if res.get("mode") == "refused" else "answer"
            ok = sts == 200 and decision == want and why_ok(res)
            if want == "answer":
                ok = ok and len(res.get("results", [])) == 3
            else:
                ok = ok and not res.get("results") and res.get("refusal_reasons")
            check(f"symptom {q!r} -> {want}", ok,
                  f"{sts} mode={res.get('mode')} reasons={res.get('refusal_reasons')}")

        print("\n== presets: conversational pre-filter (Phase 13.1) ==")
        for q, label in CONVERSATIONAL_PRESETS:
            sts, res = c.post("/symptom", {"query": q, "summary": False})
            w = res.get("why") or {}
            ok = (sts == 200 and res.get("mode") == "conversational"
                  and res.get("conversational") == label
                  and res.get("message") and not res.get("results")
                  and why_ok(res) and not w.get("citations")
                  and (w.get("retrieval") or {}).get("used") is False
                  and all(st.get("label") == "RULE" for st in w.get("steps", [])))
            check(f"conversational {q!r} -> {label}, nothing retrieved", ok,
                  f"{sts} mode={res.get('mode')} label={res.get('conversational')}")
        for q in CONVERSATIONAL_NEGATIVE:
            sts, res = c.post("/symptom", {"query": q, "summary": False})
            check(f"NOT intercepted: {q!r}", sts == 200 and res.get("mode") != "conversational",
                  f"mode={res.get('mode')}")
        sts, res = c.post("/query", {"query": "hi", "k": 3})
        check("/query also pre-filters a greeting",
              sts == 200 and res.get("mode") == "conversational"
              and res.get("path") == "deterministic_conversational"
              and not res.get("citations"),
              f"{sts} mode={res.get('mode')} path={res.get('path')}")

        print("\n== presets: fleet + filters ==")
        stf, f = c.get("/fleet")
        check("GET /fleet is ok", stf == 200 and f["vehicles"] > 0 and why_ok(f),
              f"{f.get('vehicles')} vehicles")
        stf, crit = c.get("/fleet?severity=CRITICAL")
        check("severity filter returns only CRITICAL vehicles",
              crit["per_vehicle"] and all(v["worst_severity"] == "CRITICAL"
                                          for v in crit["per_vehicle"].values()))
        stf, _ = c.get("/fleet?severity=NOPE")
        check("an invalid severity is rejected 422", stf == 422, str(stf))
        st404, _ = c.get("/vehicle/DEMO-MAT-9999")
        check("an unknown vehicle is a clean 404", st404 == 404, str(st404))

        print("\n== presets: replay ==")
        str_, start = c.post("/replay/start", {"rows_per_tick": 120, "tick_seconds": 0.05})
        check("replay starts", str_ == 200 and start["started"] is True)

        time.sleep(0.3)
        sts, status = c.get("/replay/status")
        check("replay reports progress", status["rows_replayed"] > 0, str(status["rows_replayed"]))
        stc, conflict = c.post("/replay/start", {})
        check("starting twice is a clean 409", stc == 409, str(stc))
        c.post("/replay/stop")
        sts, stopped = c.get("/replay/status")
        stf, during = c.get("/fleet")
        check("while replaying, /fleet sees only the replayed rows",
              during["replay_active"] is True
              and during["rows_in_scope"] == stopped["rows_replayed"],
              f"{during['rows_in_scope']} vs {stopped['rows_replayed']}")
        strs, reset = c.post("/replay/reset")
        check("reset restores the full log", reset["rows_in_scope"] == 1000,
              str(reset["rows_in_scope"]))

        print("\n== presets: audit ==")
        sta, aud = c.get("/audit?limit=80")
        check("audit returns recent entries", sta == 200 and aud["count"] > 0 and why_ok(aud),
              f"{aud.get('count')} entries")
        seen = {e["endpoint"] for e in aud["entries"]}
        check("the audit covers the endpoints the demo uses",
              {"/health", "/fleet", "/vehicle", "/verify-code", "/symptom", "/query"} <= seen,
              str(sorted(seen)))
        decisions = {d for e in aud["entries"] for d in str(e["decision"]).split(",")}
        check("audit decisions include a refusal, a mismatch and a conversational reply",
              {"refuse", "mismatch", "conversational"} <= decisions, str(sorted(decisions)))

    passed = sum(RESULTS)
    print(f"\n==== DEMO SMOKE: {passed}/{len(RESULTS)} passed ====")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
