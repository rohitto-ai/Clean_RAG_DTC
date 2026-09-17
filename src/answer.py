"""
Phase 6 — Answering.

DESIGN LAW: the LLM does PHRASING ONLY. Every fact and every route is
deterministic and grounded in the retrieved record. The model never supplies a
DTC code, a step, a pin or a page number - those are rendered from structured
fields before the model is consulted, and on the fast path the model is not
loaded at all.

Two paths:
  * FAST PATH (no LLM) - exact_code and system_group. A templated answer built
    straight from the record. Instant on CPU, and it cannot hallucinate.
  * LLM PATH - hybrid symptom queries. Qwen2.5-0.5B-Instruct Q4_K_M via
    llama-cpp-python, given ONLY the retrieved record fields and told to answer
    solely from them, cite the DTC code, and say so when the answer is absent.
"""
from __future__ import annotations

import os
import time

MODEL_PATH = "models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
N_CTX = 2048
N_THREADS = 4
MAX_TOKENS = 120        # capped: 0.5B rambles and pads past ~120 tokens

# Relevance gate. Deciding whether the manual covers a question AT ALL is a
# routing decision, so it is made deterministically from the retrieval signal -
# never delegated to the model. Measured separation on this corpus:
#   in-scope  queries: dense_sim 0.44-0.69, bm25_max 10.0-17.0
#   out-of-scope     : dense_sim 0.05-0.21, bm25_max  0.0-5.8
# Qwen2.5-0.5B cannot be trusted with this call: asked "how do I change a tyre"
# with irrelevant DTC context, it produced confident fabricated instructions
# including an invented tyre pressure. The gate stops the model being consulted.
DENSE_RELEVANCE_MIN = 0.30
BM25_RELEVANCE_MIN = 8.0
NOT_COVERED = "That is not covered in this manual."

SYSTEM_PROMPT = (
    "You are a diagnostic assistant for the TATA Motors 3.3L NGE BSVI engine "
    "(ECU MD1CS018) service manual.\n"
    "Rules you must follow exactly:\n"
    "1. Answer ONLY from the CONTEXT below. Use no outside knowledge.\n"
    "2. Always cite the DTC code(s) you used, e.g. (P0192-00).\n"
    "3. The CONTEXT has already been checked for relevance. Explain which DTC "
    "code(s) match the symptom and what to check, using only the CONTEXT. If the "
    "CONTEXT genuinely lacks the answer, reply exactly: "
    "\"That is not covered in this manual.\"\n"
    "4. Never invent a DTC code, step number, pin name or page number.\n"
    "5. Be concise: 2-4 sentences. State the DTC code, what it means, and the "
    "first thing to check. Do not restate field names or say a field is NA. "
    "Do not repeat yourself. Stop when you have answered."
)


# ---------------------------------------------------------------------------
# FAST PATH — deterministic, no model
# ---------------------------------------------------------------------------
def render_record(r, include_steps=True):
    """A complete, fully grounded answer for one DTC, from structured fields."""
    L = []
    L.append(f"{r['code_full']} — {r['description']}")
    L.append(f"  System: {r['system']}   |   Manual page {r['page']}"
             + (f" (occurrence {r['occurrence']})" if r["occurrence"] > 1 else ""))
    lamps = [f"MIL {r['MIL']}" if r.get("MIL") else None,
             f"CEL {r['CEL']}" if r.get("CEL") else None,
             f"Immo {r['immo_lamp']}" if r.get("immo_lamp") else None,
             f"IC message: {r['ic_message']}" if r.get("ic_message") else None]
    lamps = [x for x in lamps if x]
    if lamps:
        L.append("  Indicators: " + " | ".join(lamps))
    if r.get("effect"):
        L.append(f"  Effect on vehicle: {r['effect']}")

    if r.get("cause"):
        L.append("\nLikely causes:")
        L += [f"  {i}. {c}" for i, c in enumerate(r["cause"], 1)]

    if r.get("checkpoints"):
        L.append("\nCheckpoints:")
        L += [f"  {i}. {c}" for i, c in enumerate(r["checkpoints"], 1)]

    if include_steps and r.get("steps"):
        L.append("\nTroubleshooting steps:")
        specs = {s["n"]: s["spec"] for s in r.get("specifications") or []}
        for s in r["steps"]:
            line = f"  Step {s['n']}: {s['text']}"
            if s["n"] in specs:
                line += f"   [spec: {specs[s['n']]}]"
            L.append(line)
            branch = []
            if s["on_true"] is not None:
                # No condition means the jump is unconditional - labelling it
                # "if yes" would imply a decision the manual never poses.
                branch.append(f"if yes -> Step {s['on_true']}" if s["condition"]
                              else f"then go to Step {s['on_true']}")
            if s["on_false"] is not None:
                branch.append(f"if no -> Step {s['on_false']}")
            if branch:
                flag = "" if s["polarity_confidence"] == "high" else "  (inferred)"
                L.append(f"          -> {'; '.join(branch)}{flag}")

    pins = [p["pin"] for p in r.get("pin_map") or [] if p["confidence"] == "high"]
    if pins:
        L.append(f"\nPins referenced: {', '.join(pins)}")

    sch = [i for i in r.get("image_refs") or [] if i["kind"] == "circuit_schematic"]
    if sch:
        L.append(f"See circuit schematic, page {sch[0]['page']} of the manual.")
    if r.get("circuit_description"):
        L.append(f"\nCircuit description: {r['circuit_description']}")

    L.append(f"\nSource: {r['code_full']}, manual page {r['page']}.")
    return "\n".join(L)


def render_group(results, system):
    L = [f"{len(results)} DTCs in the '{system}' subsystem:\n"]
    for i, item in enumerate(results, 1):
        r = item["record"]
        eff = f" — effect: {r['effect']}" if r.get("effect") else ""
        L.append(f"  {i:2d}. {r['code_full']:10s} p{r['page']:<4d} "
                 f"{r['description']}{eff}")
    L.append(f"\nSource: manual pages "
             f"{min(i['record']['page'] for i in results)}–"
             f"{max(i['record']['page'] for i in results)}.")
    return "\n".join(L)


def build_context(results, max_records=3):
    """The ONLY thing the model is allowed to see."""
    blocks = []
    for item in results[:max_records]:
        r = item["record"]
        b = [f"DTC {r['code_full']} (manual page {r['page']}): {r['description']}",
             f"System: {r['system']}"]
        if r.get("effect"):
            b.append(f"Effect on vehicle: {r['effect']}")
        if r.get("MIL"):
            b.append(f"MIL: {r['MIL']}")
        if r.get("cause"):
            b.append("Causes: " + "; ".join(r["cause"]))
        if r.get("checkpoints"):
            b.append("Checkpoints: " + "; ".join(r["checkpoints"]))
        if r.get("circuit_description"):
            b.append("Circuit: " + r["circuit_description"])
        pins = [p["pin"] for p in r.get("pin_map") or []]
        if pins:
            b.append("Pins: " + ", ".join(pins))
        blocks.append("\n".join(b))
    return "\n\n---\n\n".join(blocks)


# ---------------------------------------------------------------------------
# LLM PATH
# ---------------------------------------------------------------------------
class Phraser:
    """Wraps the local GGUF model. Loaded lazily - the fast path never triggers it."""

    def __init__(self, model_path=MODEL_PATH, n_ctx=N_CTX, n_threads=N_THREADS):
        self.model_path, self.n_ctx, self.n_threads = model_path, n_ctx, n_threads
        self.llm = None
        self.load_seconds = None
        self.stats = []

    def load(self):
        if self.llm is not None:
            return self.llm
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"{self.model_path} missing. Download with:\n"
                f"  .venv/bin/python -c \"from huggingface_hub import "
                f"hf_hub_download; hf_hub_download("
                f"'Qwen/Qwen2.5-0.5B-Instruct-GGUF',"
                f"'qwen2.5-0.5b-instruct-q4_k_m.gguf', local_dir='models')\"")
        from llama_cpp import Llama
        t0 = time.time()
        self.llm = Llama(model_path=self.model_path, n_ctx=self.n_ctx,
                         n_threads=self.n_threads, verbose=False)
        self.load_seconds = time.time() - t0
        return self.llm

    def answer(self, query, context, max_tokens=MAX_TOKENS):
        llm = self.load()
        t0 = time.time()
        out = llm.create_chat_completion(
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user",
                       "content": f"CONTEXT:\n{context}\n\nQUESTION: {query}"}],
            temperature=0.0, max_tokens=max_tokens,
            stop=["\n\n\n", "CONTEXT:", "QUESTION:", "---"])
        dt = time.time() - t0
        text = out["choices"][0]["message"]["content"].strip()
        usage = out.get("usage", {})
        n_out = usage.get("completion_tokens") or 0
        stat = {"seconds": round(dt, 2), "completion_tokens": n_out,
                "prompt_tokens": usage.get("prompt_tokens"),
                "tokens_per_sec": round(n_out / dt, 2) if dt > 0 else None}
        self.stats.append(stat)
        return text, stat


# ---------------------------------------------------------------------------
RELEVANCE_PROBE_K = 5


DEFAULT_GATE_CONFIG = "data/gate_c4b.json"   # gate v2, adopted in Phase 8.5
_DEFAULT_GATE = None


def default_gate():
    global _DEFAULT_GATE
    if _DEFAULT_GATE is None:
        from gate import Gate
        _DEFAULT_GATE = Gate(DEFAULT_GATE_CONFIG)
    return _DEFAULT_GATE


def is_relevant(retriever, query, gate="default"):
    """
    gate="default" (Phase 8.5): the adopted two-reason gate v2. gate=None: the
    legacy v1 threshold-only gate, kept for reproducing v1 results.

    gate: a gate.Gate (Phase 8.3 two-reason gate). None = the legacy v1 gate below,
    so the production system is unchanged until a gate config is adopted.

    Deterministic in-scope check. Returns (bool, signals).

    The dense similarity is computed by EXACT brute force over all 314 stored
    vectors, not via Chroma. Chroma's HNSW is approximate, and early evaluation
    runs returned different top-1 distances for the same query (0.27 / 0.27 /
    0.39) while the embeddings were verified byte-identical across processes.
    Ranking tolerates that variance; a threshold decision must not.
    """
    if gate == "default":
        gate = default_gate()
    if gate is not None:
        return gate.decide(retriever, query)
    dense_sim = retriever.exact_max_sim(query)
    scores = retriever.bm25.get_scores(retriever._tokenize(query))
    bm25_max = float(max(scores)) if len(scores) else 0.0
    ok = dense_sim >= DENSE_RELEVANCE_MIN or bm25_max >= BM25_RELEVANCE_MIN
    return ok, {"dense_sim": round(dense_sim, 4), "bm25_max": round(bm25_max, 2),
                "dense_min": DENSE_RELEVANCE_MIN, "bm25_min": BM25_RELEVANCE_MIN}


def answer(query, retriever, phraser=None, k=5, gate="default"):
    """
    Route -> render. Returns {mode, path, text, citations, trace, llm_stats?}.
    """
    out = retriever.retrieve(query, k=k)
    mode, results = out["mode"], out["results"]

    if not results:
        return {"mode": mode, "path": "deterministic",
                "text": "That is not covered in this manual.",
                "citations": [], "trace": out["trace"]}

    if mode == "exact_code":
        text = "\n\n".join(render_record(i["record"]) for i in results)
        return {"mode": mode, "path": "deterministic", "text": text,
                "citations": [(i["record"]["code_full"], i["record"]["page"])
                              for i in results],
                "trace": out["trace"]}

    if mode == "system_group":
        return {"mode": mode, "path": "deterministic",
                "text": render_group(results, out["trace"]["system"]),
                "citations": [(i["record"]["code_full"], i["record"]["page"])
                              for i in results],
                "trace": out["trace"]}

    # hybrid -> gate first, THEN phrase. The model is never shown a question
    # the manual does not cover.
    ok, signals = is_relevant(retriever, query, gate=gate)
    if not ok:
        return {"mode": mode, "path": "deterministic_gate", "text": NOT_COVERED,
                "citations": [], "relevance": signals, "trace": out["trace"]}

    context = build_context(results)
    if phraser is None:
        phraser = Phraser()
    text, stat = phraser.answer(query, context)
    return {"mode": mode, "path": "llm", "text": text,
            "citations": [(i["record"]["code_full"], i["record"]["page"])
                          for i in results[:3]],
            "context_used": context, "llm_stats": stat,
            "relevance": signals, "trace": out["trace"]}
