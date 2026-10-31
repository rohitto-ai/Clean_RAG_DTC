"""
FastAPI demo surface for the 3.3L DTC RAG system. Fully local, CPU-only.

    .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000

Models and indexes load ONCE at startup; the startup cost is reported by /health
as `startup_seconds`. Phase 10.3 adds the telematics surface, a `why` block on
every response, an append-only audit log, and a replay driver for the demo.

Endpoints
    GET  /health                       readiness, versions, determinism hash, counts
    GET  /scenarios                    data/demo/scenarios.json (website presets)
    GET  /fleet                        fleet summary, filters: severity, region, outcome
    GET  /vehicle/{id_or_registration} per-vehicle report (404 if unknown)
    POST /verify-code                  technician's code vs the telemetry-resolved code
    POST /symptom                      top-3 advise() + illustrative cost/TAT
    GET  /audit                        latest audit entries
    POST /replay/start|stop|reset      replay the demo log into a live store
    GET  /replay/status                replay progress
    POST /query  /diagnose  /advise     the Phase 7 / 9.1 surfaces, unchanged
    GET  /v2                           static files from web_v2/ (optional new UI)
    GET  /                             static files from web/

Phase 13.4 adds decision "invalid_code": a code-SHAPED token that cannot be a code
("P1023473efa...", "P99999999") never reaches symptom retrieval either.

Phase 13.3 adds decision "incomplete_code": a half-typed code ("P10", "P-10",
"p 019") never reaches symptom retrieval and never auto-selects; it returns the
format hint plus candidates taken from the code dictionary alone.

Phase 13.1 adds a rule-based conversational pre-filter in FRONT of routing on the
two free-text paths (/symptom and /query): a query that is nothing but a greeting,
a thanks, or a statement that the vehicle is healthy gets a fixed reply and never
reaches the router, the retriever or the gate. Retrieval, the gate, the indexes and
the records are unchanged - the filter only decides whether to call them.

PRODUCTION CONFIG ONLY. The symptom path uses the adopted default configuration
(C4b index + gate v2). Lexicon v2 (Phase 10.1/10.1b) is NOT adopted and is not
reachable from this service.

Diagnosis sessions and the replay store are in-memory: this is a single-process
demo surface, not a production service.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "src")

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import answer as A
import conversational as CONV
from diagnose import Diagnoser
from retrieve import Retriever

app = FastAPI(title="3.3L DTC Troubleshooting RAG", version="10.3")

AUDIT_PATH = "data/demo/audit.jsonl"
AUDIT_MAX_BYTES = 5 * 1024 * 1024
SCENARIOS_PATH = "data/demo/scenarios.json"
COST_LABEL = "Illustrative - owned by another team; not from the manual"

STATE = {"retriever": None, "phraser": None, "records": {}, "sessions": {},
         "pipeline": None, "log": [], "live": None, "replay": None,
         "startup_seconds": None, "git_commit": None, "determinism_hash": None}


# --------------------------------------------------------------------- startup
@app.on_event("startup")
def startup():
    t0 = time.perf_counter()
    import telematics as T

    STATE["retriever"] = Retriever()
    STATE["phraser"] = A.Phraser()           # the LLM itself loads on first use
    for line in open("data/dtc_records.jsonl"):
        r = json.loads(line)
        STATE["records"].setdefault(r["code_full"], []).append(r)
    # one Retriever for everything: the telematics pipeline reuses it rather than
    # loading a second copy of MiniLM and Chroma
    STATE["pipeline"] = T.Pipeline(retriever=STATE["retriever"])
    STATE["log"] = T.load_log()
    try:
        STATE["git_commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=10).stdout.strip() or None
    except Exception:
        STATE["git_commit"] = None
    try:
        cfg = json.load(open("data/production_config.json"))
        STATE["determinism_hash"] = cfg["determinism_hash_dev_defaults"]["value"]
    except Exception:
        STATE["determinism_hash"] = None
    STATE["startup_seconds"] = round(time.perf_counter() - t0, 2)


def _pipeline():
    return STATE["pipeline"]


def rows_in_scope():
    """The live store while a replay is active, else the whole demo log."""
    return STATE["log"] if STATE["live"] is None else STATE["live"]


# ----------------------------------------------------------------------- audit
_audit_lock = threading.Lock()


def audit(endpoint, payload, *, route, codes, decision, latency_ms, extra=None):
    """One JSON line per request. Rotates at 5 MB. Never fails a request."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "endpoint": endpoint, "request": payload, "route": route,
        "codes": codes, "decision": decision, "latency_ms": round(latency_ms, 1),
        "git_commit": STATE["git_commit"], "determinism_hash": STATE["determinism_hash"],
        "replay_active": STATE["live"] is not None,
    }
    if extra:
        entry.update(extra)
    try:
        with _audit_lock:
            os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
            if os.path.exists(AUDIT_PATH) and os.path.getsize(AUDIT_PATH) >= AUDIT_MAX_BYTES:
                os.replace(AUDIT_PATH, AUDIT_PATH + ".1")
            with open(AUDIT_PATH, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass                                  # auditing must never break the answer
    return entry


def read_audit(limit=50):
    if not os.path.exists(AUDIT_PATH):
        return []
    with open(AUDIT_PATH) as f:
        lines = f.readlines()[-max(1, min(limit, 1000)):]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


# ------------------------------------------------------------------ why blocks
def rule(step):
    return {"step": step, "label": "RULE"}


def ai(step):
    return {"step": step, "label": "AI"}


def why_telematics(episodes, *, route):
    """`why` for the telematics surfaces: everything here is rule-based."""
    cites, ladder, sev, codes = [], [], [], []
    for e in episodes:
        ladder.append({"spn": e["spn"], "fmi": e["fmi"], "outcome": e["outcome"],
                       "rungs": e["ladder"]})
        sev.append({"spn": e["spn"], "fmi": e["fmi"], "severity": e["severity"],
                    "reasons": e["severity_reasons"]})
        for b in e.get("fix_blocks") or []:
            cites.append({"code_full": b["code_full"], "manual_page": b["page"],
                          "citation": b["citation"]})
            codes.append(b["code_full"])
        for c in e.get("candidates") or []:
            codes.append(c["code_full"])
    return {
        "route": route,
        "ladder": ladder,
        "retrieval": {"used": False,
                      "note": "codes come from the SPN/FMI dictionary and an exact-code "
                              "lookup, never from similarity search"},
        "gate": {"applied": False,
                 "note": "the relevance gate guards free-text symptom queries only"},
        "citations": cites,
        "severity_reasons": sev,
        "steps": [rule("validate row fields (normalize.validate_row)"),
                  rule("drop exact duplicates on (Vehicle_Id, SPN, FMI, Event_Date)"),
                  rule("SPN+FMI -> P-code + DTC low byte -> manual suffix (hex)"),
                  rule("exact-code lookup in the manual index (9.3b refusal/clarification)"),
                  rule("deterministic severity from lamp states, occurrence and active time"),
                  rule("fix blocks rendered verbatim from the manual record")],
        "codes": sorted(set(codes)),
    }


def why_symptom(res, *, summary_requested):
    """`why` for /symptom. The ranked list is RULE; only phrasing is AI."""
    ranks, cites, codes = [], [], []
    for r in res.get("results") or []:
        fb = r["fix_block"]
        ranks.append({"rank": r["rank"], "code_full": r["code_full"],
                      "why_retrieved": r["why_retrieved"]})
        cites.append({"code_full": fb["code_full"], "manual_page": fb["page"],
                      "citation": fb["citation"]})
        codes.append(r["code_full"])
    trace = res.get("trace") or {}
    gate = trace.get("gate") or {}
    steps = [rule("router: exact code / subsystem group / hybrid search"),
             rule("hybrid retrieval: dense + BM25 fused with RRF (production C4b)"),
             rule("relevance gate v2 decides in-scope vs refuse"),
             rule("fix blocks rendered verbatim from the manual record")]
    if summary_requested:
        steps.append(ai("one-sentence summary per code (Qwen2.5-0.5B) - phrasing only, "
                        "never a repair step"))
    return {
        "route": res.get("mode"),
        "ladder": [],
        "retrieval": {"used": res.get("mode") in ("symptom", "system_group"),
                      "router_mode": trace.get("router_mode"),
                      "ranks": ranks},
        "gate": {"applied": bool(gate),
                 "decision": ("refuse" if res.get("mode") == "refused"
                              else "pass" if gate else "not applicable"),
                 "reasons": res.get("refusal_reasons") or gate.get("refusal_reasons") or [],
                 "signals": {k: gate.get(k) for k in ("dense_sim", "bm25_max",
                                                      "dense_min", "bm25_min")
                             if k in gate}},
        "citations": cites,
        "severity_reasons": [],
        "steps": steps,
        "codes": codes,
    }


def why_conversational(label, reasons):
    """
    `why` for a conversational reply. Every step is RULE: the filter is regex and
    set membership, and the reply is a fixed string, so no model is consulted and
    nothing is retrieved or cited.
    """
    return {
        "route": "conversational",
        "ladder": [],
        "retrieval": {"used": False, "router_mode": None, "ranks": []},
        "gate": {"applied": False, "decision": "not applicable", "reasons": reasons,
                 "signals": {}},
        "citations": [],
        "severity_reasons": [],
        "steps": [rule(f"conversational pre-filter: {label} - whole-query rule, applied "
                       f"BEFORE routing"),
                  rule("fixed reply returned; router, retriever, gate and manual are "
                       "never consulted")],
        "codes": [],
    }


def why_code_hint(res, route):
    """
    `why` for the two code-shaped replies, Phase 13.3 `incomplete_code` and Phase
    13.4 `invalid_code`. Every step is RULE: the detection is a regex, any
    candidates come from the code dictionary, and nothing is retrieved, ranked or
    auto-selected.
    """
    t = (res.get("trace") or {}).get("retrieval_trace") or {}
    if route == "invalid_code":
        bad = t.get("invalid") or {}
        detect = ("over-long or malformed code token"
                  + (", too long" if bad.get("too_long") else "")
                  + (f", illegal characters {','.join(bad.get('bad_characters') or [])}"
                     if bad.get("bad_characters") else ""))
        steps = [rule("normalise the typed code (space / underscore / letter-O forms)"),
                 rule("extract any valid code embedded in the text (9.3) - none found"),
                 rule(f"detect an invalid code token (13.4): {detect}"),
                 rule("offer the dictionary's variants only when the first five "
                      "characters are a base code this manual holds"),
                 rule("nothing is auto-selected and no repair procedure is asserted")]
    else:
        steps = [rule("normalise the typed code (space / underscore / letter-O forms)"),
                 rule("detect an incomplete code attempt: code letter + 1-3 hex digits, "
                      "at most 3 tokens (or named by code/DTC/fault), at least one real digit"),
                 rule("candidates from the code dictionary only: digit-prefix, "
                      "zero-padded, one digit-insertion away"),
                 rule("nothing is auto-selected and no repair procedure is asserted")]
    return {
        "route": route,
        "ladder": [{"rung": "code-token normalisation (9.3b)", "result": "no complete code"},
                   {"rung": f"{route} detection",
                    "result": (f"token {(t.get('invalid') or {}).get('token', '')[:20]}"
                               if route == "invalid_code" else
                               f"letter {(t.get('partial') or {}).get('letter')}, "
                               f"digits {(t.get('partial') or {}).get('digits')}")},
                   {"rung": "dictionary candidates", "result":
                    f"{len(res.get('candidates') or [])} shown"
                    + (f", {res['candidates_more']} more" if res.get("candidates_more") else "")}],
        "retrieval": {"used": False, "router_mode": route, "ranks": [],
                      "note": "symptom retrieval is NOT run for a code-shaped token"},
        "gate": {"applied": False, "decision": "not applicable",
                 "reasons": [res.get("no_candidates_reason")] if res.get("no_candidates_reason")
                            else [], "signals": {}},
        "citations": [],
        "severity_reasons": [],
        "steps": steps,
        "codes": [c["code"] for c in (res.get("candidates") or [])],
    }


def cost_for_system(system, code_full=None):
    """Illustrative cost/TAT, always returned under its own labelled key."""
    rule_ = _pipeline().cost_for(system, code_full) if system else None
    return {"label": COST_LABEL, "basis": "data/demo/cost_tat_rules.csv",
            "subsystem": system, "code_full": code_full, "figures": rule_}


# ------------------------------------------------------------------- schemas
class QueryIn(BaseModel):
    query: str
    k: int = 5


class AdviseIn(BaseModel):
    input: str
    summary: bool = False


class SymptomIn(BaseModel):
    query: str
    summary: bool = False


class VerifyIn(BaseModel):
    vehicle_id: str
    reported_code: str


class ReplayIn(BaseModel):
    rows_per_tick: int = 25
    tick_seconds: float = 1.0


class DiagnoseIn(BaseModel):
    code_full: str | None = None
    session_id: str | None = None
    answer: str | None = None
    occurrence: int = 1


# -------------------------------------------------------------------- health
@app.get("/health")
def health():
    t0 = time.perf_counter()
    R = STATE["retriever"]
    meta = R.meta or {}
    body = {
        "status": "ok",
        "startup_seconds": STATE["startup_seconds"],
        "versions": {"api": app.version, "phase": "10.3",
                     "embedder": meta.get("dense", {}).get("model"),
                     "index_dir": "index (production C4b)",
                     "lexicon": (meta.get("aliases") or {}).get("lexicon"),
                     "lexicon_v2_adopted": False,
                     "gate": "v2 (data/gate_c4b.json)",
                     "git_commit": STATE["git_commit"]},
        "determinism_hash": STATE["determinism_hash"],
        "counts": {"records": len(STATE["records"]),
                   "vectors": R.coll.count(),
                   "bm25_docs": len(R.bm25_ids),
                   "dictionary_keys": len(_pipeline().table),
                   "log_rows_total": len(STATE["log"]),
                   "log_rows_in_scope": len(rows_in_scope())},
        "llm_loaded": STATE["phraser"].llm is not None,
        "replay_active": STATE["live"] is not None,
        "demo_data": "synthetic - illustrative",
        "why": {"route": "health", "ladder": [], "retrieval": {"used": False},
                "gate": {"applied": False}, "citations": [], "severity_reasons": [],
                "steps": [rule("read in-memory state and index metadata")], "codes": []},
    }
    audit("/health", {}, route="health", codes=[], decision="answer",
          latency_ms=(time.perf_counter() - t0) * 1000)
    return body


@app.get("/scenarios")
def scenarios():
    t0 = time.perf_counter()
    if not os.path.exists(SCENARIOS_PATH):
        raise HTTPException(503, "demo scenarios not generated; run scripts/gen_demo_data.py")
    body = json.load(open(SCENARIOS_PATH))
    body["why"] = {"route": "scenarios", "ladder": [], "retrieval": {"used": False},
                   "gate": {"applied": False}, "citations": [], "severity_reasons": [],
                   "steps": [rule("read data/demo/scenarios.json")], "codes": []}
    audit("/scenarios", {}, route="scenarios", codes=[], decision="answer",
          latency_ms=(time.perf_counter() - t0) * 1000)
    return body


# -------------------------------------------------------------- telematics
@app.get("/fleet")
def fleet(severity: str | None = None, region: str | None = None,
          outcome: str | None = None):
    t0 = time.perf_counter()
    import telematics as T
    rows = rows_in_scope()
    if region:
        rows = [r for r in rows if str(r.get("Region") or "").lower() == region.lower()]
    summary = _pipeline().fleet_summary(log=rows)

    sev = (severity or "").upper() or None
    out = (outcome or "").upper() or None
    if sev and sev not in T.SEVERITIES:
        raise HTTPException(422, f"severity must be one of {T.SEVERITIES}")
    if out and out not in T.OUTCOMES:
        raise HTTPException(422, f"outcome must be one of {T.OUTCOMES}")
    per = summary["per_vehicle"]
    if sev:
        per = {k: v for k, v in per.items() if v["worst_severity"] == sev}
    if out:
        per = {k: v for k, v in per.items() if out in (v["outcomes"] or {})}
    summary["per_vehicle"] = per
    summary["filters"] = {"severity": sev, "region": region, "outcome": out,
                          "vehicles_after_filter": len(per)}
    summary["replay_active"] = STATE["live"] is not None
    summary["rows_in_scope"] = len(rows)
    summary["illustrative_cost_tat"] = {"label": COST_LABEL,
                                        "note": "per-vehicle figures are on /vehicle/{id}"}
    summary["why"] = {
        "route": "fleet_summary",
        "ladder": [], "citations": [], "severity_reasons": [],
        "retrieval": {"used": False, "note": "aggregation over per-vehicle ladder outcomes"},
        "gate": {"applied": False},
        "steps": [rule("select rows in scope (live replay store or the full demo log)"),
                  rule("per-vehicle ladder + severity"),
                  rule("aggregate worst severity, outcome and subsystem counts"),
                  rule("apply severity / region / outcome filters")],
        "codes": [],
    }
    audit("/fleet", {"severity": severity, "region": region, "outcome": outcome},
          route="fleet_summary", codes=[], decision="answer",
          latency_ms=(time.perf_counter() - t0) * 1000,
          extra={"vehicles": len(per), "rows_in_scope": len(rows)})
    return summary


@app.get("/vehicle/{ident}")
def vehicle(ident: str):
    t0 = time.perf_counter()
    rows = rows_in_scope()
    rep = _pipeline().vehicle_report(vehicle_id=ident, log=rows)
    if not rep["rows_seen"]:
        rep = _pipeline().vehicle_report(registration=ident, log=rows)
    if not rep["rows_seen"]:
        audit("/vehicle", {"ident": ident}, route="vehicle_report", codes=[],
              decision="not_found", latency_ms=(time.perf_counter() - t0) * 1000)
        raise HTTPException(404, f"no rows for vehicle or registration {ident!r} "
                                 f"in the {'replayed' if STATE['live'] is not None else 'demo'} log")
    eps = rep["episodes"]
    for e in eps:
        system = (e["fix_blocks"][0]["system"] if e.get("fix_blocks") else None)
        e["illustrative_cost_tat"] = cost_for_system(system, e.get("resolved_code"))
        e.pop("cost_tat", None)
    rep["why"] = why_telematics(eps, route="vehicle_report")
    decision = {"ADVISORY": "answer", "REFUSED_NOT_IN_MANUAL": "refuse",
                "CLARIFY_LOW_BYTE": "clarify", "AMBIGUOUS_MAPPING_CANDIDATES": "candidates",
                "FALLBACK_CANDIDATES": "candidates", "UNMAPPED": "refuse"}
    decisions = sorted({decision.get(e["outcome"], "answer") for e in eps})
    audit("/vehicle", {"ident": ident}, route="vehicle_report",
          codes=rep["why"]["codes"], decision=",".join(decisions) or "answer",
          latency_ms=(time.perf_counter() - t0) * 1000,
          extra={"episodes": len(eps), "worst_severity": rep["worst_severity"]})
    return rep


@app.post("/verify-code")
def verify_code(v: VerifyIn):
    t0 = time.perf_counter()
    if not v.vehicle_id.strip() or not v.reported_code.strip():
        raise HTTPException(400, "vehicle_id and reported_code are required")
    res = _pipeline().verify_reported_code(v.vehicle_id, v.reported_code, log=rows_in_scope())
    res["why"] = {
        "route": "verify_reported_code",
        "ladder": [{"rung": "normalise the typed code (9.3b)", "result": res["reported_code"]},
                   {"rung": "compare with the telemetry-resolved code(s)",
                    "result": res["status"]}],
        "retrieval": {"used": False,
                      "note": "exact-code lookup only; no similarity search"},
        "gate": {"applied": False},
        "citations": [], "severity_reasons": [],
        "steps": [rule("normalise the typed code (space / underscore / letter-O forms)"),
                  rule("exact-code lookup to say whether the typed code exists at all"),
                  rule("compare against the telemetry-resolved code"),
                  rule("edit distance 1 -> flag a possible transposition, NEVER substitute")],
        "codes": [c for c in [res.get("reported_code")] if c] + res["telemetry_resolved_codes"],
    }
    audit("/verify-code", v.model_dump(), route="verify_reported_code",
          codes=res["why"]["codes"],
          decision="mismatch" if res["status"] == "MISMATCH" else res["status"].lower(),
          latency_ms=(time.perf_counter() - t0) * 1000,
          extra={"possible_transposition": res.get("possible_transposition")})
    return res


# ----------------------------------------------------------------- symptom
@app.post("/symptom")
def symptom(s: SymptomIn):
    """
    Phase 9.1 advise() on the PRODUCTION default configuration (C4b + gate v2).
    A refusal is returned as a refusal, with its reason - never as an answer.
    """
    t0 = time.perf_counter()
    if not s.query.strip():
        raise HTTPException(400, "empty query")

    # Phase 13.1: non-diagnostic input never reaches the router or the retriever.
    conv = CONV.respond(s.query)
    if conv:
        body = {"mode": conv["mode"], "conversational": conv["conversational"],
                "message": conv["message"], "results": [],
                "config": {"index": "index (production C4b)", "gate": "v2",
                           "lexicon_v2_adopted": False},
                "why": why_conversational(conv["conversational"], conv["reasons"])}
        audit("/symptom", s.model_dump(), route="conversational", codes=[],
              decision=CONV.DECISION, latency_ms=(time.perf_counter() - t0) * 1000,
              extra={"conversational": conv["conversational"], "reasons": conv["reasons"]})
        return body

    from advise import advise
    res = advise(s.query, STATE["retriever"], phraser=STATE["phraser"], summary=s.summary)
    for r in res.get("results") or []:
        fb = r["fix_block"]
        r["illustrative_cost_tat"] = cost_for_system(fb["system"], fb["code_full"])
    res["config"] = {"index": "index (production C4b)", "gate": "v2",
                     "lexicon_v2_adopted": False}
    if res["mode"] in ("incomplete_code", "invalid_code"):
        res["why"] = why_code_hint(res, res["mode"])
    else:
        res["why"] = why_symptom(res, summary_requested=s.summary)
    decision = {"refused": "refuse", "clarify_code": "clarify",
                "incomplete_code": "incomplete_code",
                "invalid_code": "invalid_code"}.get(res["mode"], "answer")
    audit("/symptom", s.model_dump(), route=res["mode"], codes=res["why"]["codes"],
          decision=decision, latency_ms=(time.perf_counter() - t0) * 1000,
          extra={"refusal_reasons": res.get("refusal_reasons"),
                 "code_hint": res.get("candidates") and
                                    {"candidates": [c["code"] for c in res["candidates"]],
                                     "more": res.get("candidates_more", 0)} or None})
    return res


# ------------------------------------------------------------------- audit
@app.get("/audit")
def audit_tail(limit: int = 50):
    entries = read_audit(limit)
    return {"count": len(entries), "path": AUDIT_PATH,
            "rotates_at_bytes": AUDIT_MAX_BYTES, "entries": entries,
            "why": {"route": "audit", "ladder": [], "retrieval": {"used": False},
                    "gate": {"applied": False}, "citations": [], "severity_reasons": [],
                    "steps": [rule("tail data/demo/audit.jsonl")], "codes": []}}


# ------------------------------------------------------------------ replay
class _Replay:
    """Replays the demo log in Event_Date order into an in-memory live store."""

    def __init__(self, rows, rows_per_tick, tick_seconds):
        self.ordered = sorted(rows, key=lambda r: (str(r.get("Event_Date") or ""), r["_row"]))
        self.rows_per_tick = max(1, int(rows_per_tick))
        self.tick_seconds = max(0.05, float(tick_seconds))
        self.i = 0
        self.started = time.time()
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set() and self.i < len(self.ordered):
            nxt = self.ordered[self.i:self.i + self.rows_per_tick]
            self.i += len(nxt)
            STATE["live"] = (STATE["live"] or []) + nxt
            self._stop.wait(self.tick_seconds)

    def start(self):
        STATE["live"] = []
        self.thread.start()

    def stop(self):
        self._stop.set()

    def status(self):
        return {"active": self.thread.is_alive(), "rows_replayed": self.i,
                "rows_total": len(self.ordered),
                "progress": round(self.i / max(1, len(self.ordered)), 3),
                "rows_per_tick": self.rows_per_tick, "tick_seconds": self.tick_seconds,
                "last_event_date": (str(self.ordered[self.i - 1].get("Event_Date"))
                                    if self.i else None),
                "started_utc": datetime.fromtimestamp(self.started, timezone.utc)
                               .isoformat(timespec="seconds")}


@app.post("/replay/start")
def replay_start(r: ReplayIn):
    t0 = time.perf_counter()
    if STATE["replay"] and STATE["replay"].thread.is_alive():
        raise HTTPException(409, "a replay is already running; stop or reset it first")
    rp = _Replay(STATE["log"], r.rows_per_tick, r.tick_seconds)
    STATE["replay"] = rp
    rp.start()
    body = {"started": True, **rp.status(),
            "note": "/fleet and /vehicle now see only the rows replayed so far",
            "why": {"route": "replay_start", "ladder": [], "retrieval": {"used": False},
                    "gate": {"applied": False}, "citations": [], "severity_reasons": [],
                    "steps": [rule("sort the demo log by Event_Date"),
                              rule("feed rows_per_tick rows every tick_seconds into the "
                                   "live store")], "codes": []}}
    audit("/replay/start", r.model_dump(), route="replay_start", codes=[],
          decision="answer", latency_ms=(time.perf_counter() - t0) * 1000)
    return body


@app.post("/replay/stop")
def replay_stop():
    t0 = time.perf_counter()
    rp = STATE["replay"]
    if not rp:
        raise HTTPException(409, "no replay has been started")
    rp.stop()
    rp.thread.join(timeout=2)
    body = {"stopped": True, **rp.status(),
            "note": "the live store keeps the rows replayed so far; POST /replay/reset "
                    "restores the full log"}
    audit("/replay/stop", {}, route="replay_stop", codes=[], decision="answer",
          latency_ms=(time.perf_counter() - t0) * 1000)
    return body


@app.post("/replay/reset")
def replay_reset():
    t0 = time.perf_counter()
    rp = STATE["replay"]
    if rp:
        rp.stop()
        rp.thread.join(timeout=2)
    STATE["replay"] = None
    STATE["live"] = None
    body = {"reset": True, "replay_active": False,
            "rows_in_scope": len(rows_in_scope()),
            "note": "the full demo log is in scope again"}
    audit("/replay/reset", {}, route="replay_reset", codes=[], decision="answer",
          latency_ms=(time.perf_counter() - t0) * 1000)
    return body


@app.get("/replay/status")
def replay_status():
    rp = STATE["replay"]
    if not rp:
        return {"active": False, "rows_replayed": 0,
                "rows_total": len(STATE["log"]), "progress": 0.0,
                "replay_started": False, "rows_in_scope": len(rows_in_scope())}
    return {**rp.status(), "replay_started": True, "rows_in_scope": len(rows_in_scope())}


# ------------------------------------------- Phase 7 / 9.1 surfaces (unchanged)
@app.post("/advise")
def advise_endpoint(a: AdviseIn):
    """
    Phase 9.1: top-3 DTCs, each with a deterministic fix block.
    mode is "dtc_code", "symptom", "system_group", "refused" or "clarify_code"
    (9.3b: known base code, unknown suffix - variants listed, no fix blocks).
    """
    from advise import advise
    if not a.input.strip():
        raise HTTPException(400, "empty input")
    t0 = time.perf_counter()
    res = advise(a.input, STATE["retriever"], phraser=STATE["phraser"], summary=a.summary)
    audit("/advise", a.model_dump(), route=res["mode"],
          codes=[r["code_full"] for r in res.get("results") or []],
          decision={"refused": "refuse", "clarify_code": "clarify"}.get(res["mode"], "answer"),
          latency_ms=(time.perf_counter() - t0) * 1000)
    return res


@app.post("/query")
def query(q: QueryIn):
    if not q.query.strip():
        raise HTTPException(400, "empty query")
    t0 = time.perf_counter()

    # Phase 13.1: the same pre-filter, in front of the Phase 7 surface too.
    conv = CONV.respond(q.query)
    if conv:
        body = {"answer": conv["message"], "citations": [], "mode": conv["mode"],
                "path": "deterministic_conversational",
                "conversational": conv["conversational"],
                "trace": {"conversational": conv["conversational"],
                          "reasons": conv["reasons"],
                          "retrieval_run": False, "gate_applied": False},
                "llm_stats": None, "relevance": None,
                "why": why_conversational(conv["conversational"], conv["reasons"])}
        audit("/query", q.model_dump(), route="conversational", codes=[],
              decision=CONV.DECISION, latency_ms=(time.perf_counter() - t0) * 1000,
              extra={"conversational": conv["conversational"], "reasons": conv["reasons"]})
        return body

    out = A.answer(q.query, STATE["retriever"], STATE["phraser"], k=q.k)
    body = {
        "answer": out["text"],
        "citations": [{"code_full": c, "page": p} for c, p in out["citations"]],
        "mode": out["mode"],
        "path": out["path"],
        "trace": {k: v for k, v in out["trace"].items() if k != "fused_top"},
        "llm_stats": out.get("llm_stats"),
        "relevance": out.get("relevance"),
    }
    audit("/query", q.model_dump(), route=out["mode"],
          codes=[c for c, _ in out["citations"]],
          decision="refuse" if out["path"].startswith("deterministic_gate")
                   or out["path"] == "deterministic_refusal" else
                   "clarify" if out["path"] == "deterministic_clarification" else "answer",
          latency_ms=(time.perf_counter() - t0) * 1000)
    return body


def _present(diag, state):
    s = diag.current_step(state)
    if s is None:
        return None
    opts = ["yes", "no"] if diag.needs_answer(state) else None
    return {"n": s["n"], "text": s["text"], "kind": s["kind"],
            "condition": s["condition"], "options": opts,
            "prompt": (f"{s['condition']} — yes or no?" if opts
                       else "Perform this step, then continue.")}


@app.post("/diagnose")
def diagnose(d: DiagnoseIn):
    if d.session_id:
        sess = STATE["sessions"].get(d.session_id)
        if not sess:
            raise HTTPException(404, "unknown session_id")
        diag, state = sess["diag"], sess["state"]
        if state.finished:
            return {"session_id": d.session_id, "finished": True,
                    "current_step": None, "outcome": state.outcome,
                    "path_trace": diag.path_trace(state)}
        state = diag.advance(state, d.answer)
        sess["state"] = state
        return {"session_id": d.session_id, "finished": state.finished,
                "current_step": _present(diag, state),
                "outcome": state.outcome,
                "path_trace": diag.path_trace(state)}

    if not d.code_full:
        raise HTTPException(400, "provide code_full to start, or session_id to continue")
    recs = STATE["records"].get(d.code_full.upper())
    if not recs:
        raise HTTPException(404, f"unknown DTC {d.code_full}")
    rec = next((r for r in recs if r["occurrence"] == d.occurrence), recs[0])
    diag = Diagnoser(rec)
    state = diag.start()
    sid = str(uuid.uuid4())[:8]
    STATE["sessions"][sid] = {"diag": diag, "state": state}
    return {"session_id": sid, "finished": state.finished,
            "dtc": {"code_full": rec["code_full"], "page": rec["page"],
                    "description": rec["description"]},
            "current_step": _present(diag, state),
            "outcome": state.outcome, "path_trace": diag.path_trace(state)}


# ------------------------------------------------------- static demo UI (last)
# Mounted at "/" AFTER every route above, so the API paths keep priority.
# Phase 13.2 serves the optional redesigned UI at /v2, mounted BEFORE "/" because
# "/" is a catch-all. Both read the same endpoints; neither has an API of its own.
if os.path.isdir("web_v2"):
    from fastapi.staticfiles import StaticFiles as _StaticV2
    app.mount("/v2", _StaticV2(directory="web_v2", html=True), name="web_v2")

if os.path.isdir("web"):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory="web", html=True), name="web")
