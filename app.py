"""
FastAPI demo surface for the 3.3L DTC RAG system. Fully local, CPU-only.

    .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000

Endpoints
    GET  /health              readiness + index sizes
    POST /query               retrieve -> answer (deterministic or LLM-phrased)
    POST /diagnose            stateful step-wise walk of a DTC's decision tree
    POST /advise              top-3 DTCs, each with a deterministic fix block (Phase 9.1)

Diagnosis sessions are held in memory: this is a single-process demo surface,
not a production service.
"""
from __future__ import annotations

import json
import sys
import uuid

sys.path.insert(0, "src")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import answer as A
from diagnose import Diagnoser
from retrieve import Retriever

app = FastAPI(title="3.3L DTC Troubleshooting RAG", version="1.0")

STATE = {"retriever": None, "phraser": None, "records": {}, "sessions": {}}


@app.on_event("startup")
def startup():
    STATE["retriever"] = Retriever()
    STATE["phraser"] = A.Phraser()          # model loaded lazily, on first LLM use
    for line in open("data/dtc_records.jsonl"):
        r = json.loads(line)
        STATE["records"].setdefault(r["code_full"], []).append(r)


class QueryIn(BaseModel):
    query: str
    k: int = 5


class AdviseIn(BaseModel):
    input: str
    summary: bool = False                # optional one-sentence LLM summary per code


class DiagnoseIn(BaseModel):
    code_full: str | None = None
    session_id: str | None = None
    answer: str | None = None            # "yes" / "no"
    occurrence: int = 1


@app.get("/health")
def health():
    R = STATE["retriever"]
    return {"status": "ok", "records": len(STATE["records"]),
            "vectors": R.coll.count(), "bm25_docs": len(R.bm25_ids),
            "model_loaded": STATE["phraser"].llm is not None}


@app.post("/advise")
def advise_endpoint(a: AdviseIn):
    """
    Phase 9.1: top-3 DTCs, each with a deterministic fix block.
    Returns {input, mode, results: [{rank, code_full, why_retrieved, fix_block}], trace}.
    mode is "dtc_code", "symptom", "system_group" or "refused".
    """
    from advise import advise
    if not a.input.strip():
        raise HTTPException(400, "empty input")
    return advise(a.input, STATE["retriever"], phraser=STATE["phraser"], summary=a.summary)


@app.post("/query")
def query(q: QueryIn):
    if not q.query.strip():
        raise HTTPException(400, "empty query")
    out = A.answer(q.query, STATE["retriever"], STATE["phraser"], k=q.k)
    return {
        "answer": out["text"],
        "citations": [{"code_full": c, "page": p} for c, p in out["citations"]],
        "mode": out["mode"],
        "path": out["path"],
        "trace": {k: v for k, v in out["trace"].items() if k != "fused_top"},
        "llm_stats": out.get("llm_stats"),
        "relevance": out.get("relevance"),
    }


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
    # --- continue an existing session ---
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

    # --- start a new session ---
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
