"""
Interactive command-line interface: type a question, get an answer.

    ./run.sh                      (recommended - checks setup first)
    PYTHONPATH=src .venv/bin/python src/cli.py

Uses exactly the production configuration adopted in Phase 8.5 (the same code
path as app.py): Retriever() with the lexicon read from the index, gate v2 by
default, and the local Qwen model only for free-text symptom questions.
"""
from __future__ import annotations

import contextlib
import os
import sys
import textwrap
import time

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")    # silence Chroma telemetry
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

BANNER = """
==============================================================
  3.3L DTC Troubleshooting Assistant  (fully local, CPU-only)
==============================================================
  Ask about a fault code or describe a symptom, for example:
    - how do I fix P0192-00
    - P0340
    - list all EGR faults
    - the adblue has turned to solid ice after a freezing night
  Type 'quit' (or press Ctrl+C) to exit.
"""


DESCRIPTIONS = {}      # (code_full, page) -> description, filled at start-up


@contextlib.contextmanager
def quiet_stderr():
    """Hide native-library noise (onnxruntime, llama.cpp) printed straight to fd 2."""
    try:
        saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
    except OSError:
        yield
        return
    try:
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)


def print_answer(out, seconds):
    mode_label = {
        "exact_code": "exact DTC lookup",
        "system_group": "subsystem list",
        "hybrid": "symptom search",
    }.get(out["mode"], out["mode"])
    path_label = {
        "deterministic": "answered from the manual (no AI model)",
        "llm": "phrased by the local AI model from the manual",
        "deterministic_gate": "refused - outside the manual",
    }.get(out["path"], out["path"])

    print(f"\n[{mode_label} | {path_label} | {seconds:.1f}s]\n")
    for para in out["text"].split("\n"):
        if para.strip() == "":
            print()
            continue
        indent = len(para) - len(para.lstrip())
        print(textwrap.fill(para, width=100, subsequent_indent=" " * (indent + 2)))

    if out["path"] == "llm" and out.get("citations"):
        # The small local model phrases the answer and can dwell on the wrong
        # record. The search's own ranking is the authoritative part, so always
        # show it next to the model's wording.
        print("\nTop matching DTCs (ranked by the search, most likely first):")
        for i, (code, page) in enumerate(out["citations"], 1):
            desc = DESCRIPTIONS.get((code, page), "")
            print(f"  {i}. {code}  (page {page})  {desc}")
    reasons = (out.get("relevance") or {}).get("refusal_reasons")
    if reasons:
        print(f"Why refused: {', '.join(r.replace('_', ' ') for r in reasons)}")
    print("-" * 62)


def main():
    print(BANNER)
    print("Loading the manual index and models (first start takes ~10 s)...", flush=True)
    t0 = time.time()
    with quiet_stderr():
        import answer as A
        from retrieve import Retriever
        retriever = Retriever()
        phraser = A.Phraser()           # the LLM itself loads on first symptom question
    DESCRIPTIONS.update({(r["code_full"], r["page"]): r["description"]
                         for r in retriever.records.values()})
    print(f"Ready in {time.time() - t0:.1f}s - {len(retriever.records)} DTC records loaded.\n")

    while True:
        try:
            query = input("Enter your query> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if not query:
            continue
        if query.lower() in {"quit", "exit", "q"}:
            print("Goodbye.")
            break
        t = time.time()
        try:
            with quiet_stderr():
                out = A.answer(query, retriever, phraser)
        except KeyboardInterrupt:
            print("\n(cancelled)")
            continue
        except Exception as e:                       # keep the session alive
            print(f"\nSorry, something went wrong answering that: {e}\n")
            continue
        print_answer(out, time.time() - t)


if __name__ == "__main__":
    main()
