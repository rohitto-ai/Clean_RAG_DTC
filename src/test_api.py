"""
Phase 10.3 — FastAPI service tests (TestClient). Every endpoint, the refusal and
clarification paths, ambiguity, transposition MISMATCH, replay, the audit log and
the 404s. Also measures per-endpoint p50/p95 latency, excluding startup.

    PYTHONPATH=src .venv/bin/python src/test_api.py
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# app.py lives at the repo root, which is the working directory for every path in
# this project; add it so `import app` works when run as src/test_api.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

RESULTS = []
WHY_KEYS = {"route", "ladder", "retrieval", "gate", "citations", "severity_reasons",
            "steps", "codes"}


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def has_why(body):
    w = body.get("why")
    return isinstance(w, dict) and WHY_KEYS <= set(w) and all(
        s.get("label") in ("RULE", "AI") for s in w["steps"])


def main():
    from fastapi.testclient import TestClient
    import app as M

    audit_path = M.AUDIT_PATH
    if os.path.exists(audit_path):
        os.remove(audit_path)

    t0 = time.perf_counter()
    client = TestClient(M.app)
    with client:
        startup = time.perf_counter() - t0
        scen = json.load(open("data/demo/scenarios.json"))["scenarios"]
        lat = {}

        def bucket(method, url):
            """One latency bucket per ENDPOINT, not per path parameter."""
            path = url.split("?")[0]
            if path.startswith("/vehicle/"):
                path = "/vehicle/{id}"
            return f"{method.upper()} {path.rstrip('/') or '/'}"

        def call(method, url, **kw):
            t = time.perf_counter()
            r = getattr(client, method)(url, **kw)
            lat.setdefault(bucket(method, url), []).append((time.perf_counter() - t) * 1000)
            return r

        # ---------------- health + scenarios ----------------
        print("\n== health / scenarios ==")
        h = call("get", "/health")
        b = h.json()
        check("GET /health 200 with versions, hash and counts",
              h.status_code == 200 and b["status"] == "ok"
              and b["determinism_hash"] == "ffff9bc707d8754d"
              and b["counts"]["records"] == 311 and b["counts"]["log_rows_total"] == 1000,
              str(b.get("determinism_hash")))
        check("/health reports startup_seconds (models loaded once)",
              isinstance(b["startup_seconds"], (int, float)) and b["startup_seconds"] > 0,
              f"{b['startup_seconds']}s")
        check("/health states lexicon v2 is NOT adopted",
              b["versions"]["lexicon_v2_adopted"] is False
              and b["versions"]["index_dir"].startswith("index (production"))
        check("/health carries a why block", has_why(b))
        s = call("get", "/scenarios").json()
        check("GET /scenarios returns the presets and the synthetic label",
              len(s["scenarios"]) == 14 and s["_meta"]["label"] == "synthetic - illustrative"
              and has_why(s))

        # ---------------- fleet ----------------
        print("\n== fleet ==")
        f = call("get", "/fleet").json()
        check("GET /fleet summarises every vehicle",
              f["vehicles"] == 199 and f["episodes"] > 800 and has_why(f),
              f"{f['vehicles']} vehicles, {f['episodes']} episodes")
        check("/fleet exposes the illustrative cost label",
              f["illustrative_cost_tat"]["label"].startswith("Illustrative"))
        crit = call("get", "/fleet?severity=CRITICAL").json()
        check("?severity=CRITICAL filters to critical vehicles only",
              crit["filters"]["severity"] == "CRITICAL" and crit["per_vehicle"]
              and all(v["worst_severity"] == "CRITICAL" for v in crit["per_vehicle"].values()),
              f"{len(crit['per_vehicle'])} vehicles")
        reg = call("get", "/fleet?region=North").json()
        check("?region filters by region", reg["filters"]["region"] == "North"
              and 0 < reg["rows_in_scope"] < f["rows_in_scope"],
              f"{reg['rows_in_scope']} rows")
        amb = call("get", "/fleet?outcome=AMBIGUOUS_MAPPING_CANDIDATES").json()
        check("?outcome filters to vehicles with that outcome",
              amb["per_vehicle"] and all("AMBIGUOUS_MAPPING_CANDIDATES" in v["outcomes"]
                                         for v in amb["per_vehicle"].values()),
              f"{len(amb['per_vehicle'])} vehicles")
        check("an unknown severity is rejected 422",
              call("get", "/fleet?severity=NOPE").status_code == 422)
        check("an unknown outcome is rejected 422",
              call("get", "/fleet?outcome=NOPE").status_code == 422)

        # ---------------- vehicle ----------------
        print("\n== vehicle ==")
        vid = scen["normal_advisory"]["vehicle_id"]
        v = call("get", f"/vehicle/{vid}").json()
        e = v["episodes"][0]
        check("GET /vehicle returns an ADVISORY episode with fix blocks",
              e["outcome"] == "ADVISORY" and e["resolved_code"] == "P0192-00"
              and e["fix_blocks"] and has_why(v))
        check("citations carry the code and the manual page",
              v["why"]["citations"][0]["manual_page"] == 8
              and v["why"]["citations"][0]["code_full"] == "P0192-00")
        check("severity reasons are returned", v["why"]["severity_reasons"][0]["reasons"])
        check("every why step is labelled RULE for the telematics path",
              all(s["label"] == "RULE" for s in v["why"]["steps"]))
        check("cost/TAT sits under illustrative_cost_tat with the right label",
              e["illustrative_cost_tat"]["label"] == M.COST_LABEL
              and "cost_tat" not in e and e["illustrative_cost_tat"]["figures"])
        check("lookup by registration works too",
              call("get", f"/vehicle/{scen['normal_advisory']['registration']}")
              .json()["vehicle_id"] == vid)
        check("unknown vehicle -> 404", call("get", "/vehicle/DEMO-MAT-9999").status_code == 404)
        check("unknown registration -> 404", call("get", "/vehicle/ZZ99ZZ9999").status_code == 404)

        amb_v = call("get", f"/vehicle/{scen['ambiguous_key']['vehicle_id']}").json()
        ae = amb_v["episodes"][0]
        check("ambiguous key -> candidates, no fix blocks, never auto-advised",
              ae["outcome"] == "AMBIGUOUS_MAPPING_CANDIDATES" and not ae["fix_blocks"]
              and {c["code_full"] for c in ae["candidates"]} == {"P042E-00", "P042F-00"})
        ref = call("get", f"/vehicle/{scen['code_not_in_manual']['vehicle_id']}").json()
        check("a mapped code absent from the manual is refused",
              ref["episodes"][0]["outcome"] == "REFUSED_NOT_IN_MANUAL"
              and not ref["episodes"][0]["fix_blocks"])
        cl = call("get", f"/vehicle/{scen['low_byte_not_in_manual']['vehicle_id']}").json()
        check("an absent low byte clarifies with known variants",
              cl["episodes"][0]["outcome"] == "CLARIFY_LOW_BYTE"
              and cl["episodes"][0]["known_variants"] == ["P0116-00"])

        # ---------------- verify-code ----------------
        print("\n== verify-code ==")
        for key, typed, truth in (("transposition_P1000", "P0100-00", "P1000-00"),
                                  ("transposition_P1675", "P1657-00", "P1675-00")):
            r = call("post", "/verify-code", json={"vehicle_id": scen[key]["vehicle_id"],
                                                   "reported_code": typed}).json()
            check(f"typing {typed} -> MISMATCH + possible transposition {truth}",
                  r["status"] == "MISMATCH" and r["possible_transposition"] == [truth]
                  and r["auto_replaced"] is False and has_why(r),
                  f"{r['status']} {r.get('possible_transposition')}")
        r = call("post", "/verify-code", json={"vehicle_id": scen["transposition_P1000"]["vehicle_id"],
                                               "reported_code": "P1000-00"}).json()
        check("the correct code -> MATCH", r["status"] == "MATCH")
        check("empty body fields -> 400",
              call("post", "/verify-code", json={"vehicle_id": "", "reported_code": ""})
              .status_code == 400)

        # ---------------- symptom ----------------
        print("\n== symptom ==")
        sy = call("post", "/symptom", json={"query": "rail pressure sensor short to ground"}).json()
        check("POST /symptom returns top-3 with ranks and citations",
              len(sy["results"]) == 3 and sy["why"]["retrieval"]["ranks"]
              and sy["why"]["citations"] and has_why(sy))
        check("/symptom uses the production config, not lexicon v2",
              sy["config"]["lexicon_v2_adopted"] is False
              and sy["config"]["index"].startswith("index (production"))
        check("illustrative cost/TAT is attached per result",
              sy["results"][0]["illustrative_cost_tat"]["label"] == M.COST_LABEL)
        check("without --summary every step is RULE (no AI step)",
              all(s["label"] == "RULE" for s in sy["why"]["steps"]))
        oos = call("post", "/symptom", json={"query": "what is the capital of France"}).json()
        check("an out-of-scope query is REFUSED with a reason",
              oos["mode"] == "refused" and not oos["results"]
              and oos["why"]["gate"]["decision"] == "refuse"
              and oos["why"]["gate"]["reasons"], str(oos.get("refusal_reasons")))
        clar = call("post", "/symptom", json={"query": "P1000-9C"}).json()
        check("a known base with an unknown suffix clarifies, with no fix blocks",
              clar["mode"] == "clarify_code" and not clar["results"])
        check("empty query -> 400", call("post", "/symptom", json={"query": " "}).status_code == 400)

        # ---------------- replay ----------------
        print("\n== replay ==")
        st = call("get", "/replay/status").json()
        check("status before any replay", st["active"] is False and st["replay_started"] is False
              and st["rows_in_scope"] == 1000)
        start = call("post", "/replay/start", json={"rows_per_tick": 40,
                                                    "tick_seconds": 0.05}).json()
        check("POST /replay/start begins a replay", start["started"] is True
              and start["rows_total"] == 1000)
        time.sleep(0.35)
        mid = call("get", "/replay/status").json()
        check("rows are replayed progressively, not all at once",
              0 < mid["rows_replayed"] < 1000 and mid["progress"] > 0,
              f"{mid['rows_replayed']}/1000")
        check("a second start while running -> 409",
              call("post", "/replay/start", json={}).status_code == 409)
        stop = call("post", "/replay/stop").json()
        check("POST /replay/stop halts it", stop["stopped"] is True
              and call("get", "/replay/status").json()["active"] is False)
        after = call("get", "/replay/status").json()
        time.sleep(0.2)
        check("no rows arrive after stop",
              call("get", "/replay/status").json()["rows_replayed"] == after["rows_replayed"])
        # with the replay halted the comparison is exact
        fl = call("get", "/fleet").json()
        check("/fleet reflects EXACTLY the rows replayed so far, not the full log",
              fl["replay_active"] is True and fl["rows_in_scope"] == after["rows_replayed"]
              and fl["rows_in_scope"] < 1000,
              f"fleet sees {fl['rows_in_scope']}, replayed {after['rows_replayed']}")
        vfl = call("get", "/fleet").json()
        check("the replayed fleet has fewer vehicles than the full log",
              vfl["vehicles"] <= 199, f"{vfl['vehicles']}")
        rs = call("post", "/replay/reset").json()
        check("POST /replay/reset restores the full log",
              rs["reset"] is True and rs["rows_in_scope"] == 1000
              and call("get", "/fleet").json()["rows_in_scope"] == 1000)
        check("stop without a replay -> 409", call("post", "/replay/stop").status_code == 409)

        # ---------------- audit ----------------
        print("\n== audit ==")
        a = call("get", "/audit?limit=200").json()
        entries = a["entries"]
        check("GET /audit returns the trail", a["count"] > 0 and has_why(a))
        need = {"/health", "/scenarios", "/fleet", "/vehicle", "/verify-code", "/symptom",
                "/replay/start", "/replay/stop", "/replay/reset"}
        seen = {e["endpoint"] for e in entries}
        check("one audit line per audited request, covering every endpoint",
              need <= seen, str(need - seen))
        ok_fields = all({"timestamp", "endpoint", "request", "route", "codes", "decision",
                         "latency_ms", "git_commit", "determinism_hash"} <= set(e)
                        for e in entries)
        check("every entry has timestamp, endpoint, request, route, codes, decision, "
              "latency, commit and hash", ok_fields)
        check("decisions use the documented vocabulary",
              {d for e in entries for d in str(e["decision"]).split(",")}
              <= {"answer", "refuse", "clarify", "candidates", "mismatch", "match",
                  "not_found", "no_code_detected"},
              str({e["decision"] for e in entries}))
        refusals = [e for e in entries if e["endpoint"] == "/symptom" and e["decision"] == "refuse"]
        check("the out-of-scope refusal is audited as a refusal", len(refusals) >= 1)
        mism = [e for e in entries if e["endpoint"] == "/verify-code" and e["decision"] == "mismatch"]
        check("the transposition mismatches are audited", len(mism) >= 2, f"{len(mism)}")
        check("audit lines record the determinism hash and git commit",
              all(e["determinism_hash"] == "ffff9bc707d8754d" for e in entries)
              and all(e["git_commit"] for e in entries))
        before = len(entries)
        call("get", "/health")
        check("a further request appends exactly one more line",
              len(M.read_audit(500)) == before + 1, f"{len(M.read_audit(500))} vs {before + 1}")
        check("the audit file is on disk and gitignored",
              os.path.exists(audit_path)
              and "data/demo/audit.jsonl" in open(".gitignore").read())

        # ---------------- static ----------------
        print("\n== static ==")
        r = call("get", "/")
        check("GET / serves the Phase 10.4 placeholder from web/",
              r.status_code == 200 and "Demo UI — Phase 10.4" in r.text
              and "text/html" in r.headers.get("content-type", ""))
        check("an unknown static path -> 404", client.get("/nope.html").status_code == 404)

        # ---------------- latency ----------------
        print("\n== latency (excluding startup) ==")
        for ep in ("GET /health", "GET /fleet", "GET /vehicle", "POST /verify-code",
                   "POST /symptom", "GET /audit"):
            for _ in range(6):
                if ep == "GET /health":
                    call("get", "/health")
                elif ep == "GET /fleet":
                    call("get", "/fleet")
                elif ep == "GET /vehicle":
                    call("get", f"/vehicle/{vid}")
                elif ep == "POST /verify-code":
                    call("post", "/verify-code",
                         json={"vehicle_id": vid, "reported_code": "P0192-00"})
                elif ep == "POST /symptom":
                    call("post", "/symptom",
                         json={"query": "rail pressure sensor short to ground"})
                else:
                    call("get", "/audit?limit=20")
        table = {}
        for ep, xs in sorted(lat.items()):
            xs = sorted(xs)
            table[ep] = {"n": len(xs), "p50": round(statistics.median(xs), 1),
                         "p95": round(xs[int(0.95 * (len(xs) - 1))], 1)}
            print(f"  {ep:22s} n={len(xs):3d}  p50 {table[ep]['p50']:7.1f} ms  "
                  f"p95 {table[ep]['p95']:7.1f} ms")
        check("every measured endpoint has p95 under 2 s",
              all(v["p95"] < 2000 for v in table.values()),
              str({k: v["p95"] for k, v in table.items() if v["p95"] >= 2000}))
        os.makedirs("data/experiments/10_3", exist_ok=True)
        json.dump({"startup_seconds_testclient": round(startup, 2),
                   "health_startup_seconds": M.STATE["startup_seconds"],
                   "latency_ms": table},
                  open("data/experiments/10_3/api_latency.json", "w"), indent=1)

    passed = sum(RESULTS)
    print(f"\n==== API: {passed}/{len(RESULTS)} passed ====")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
