"""
Phase 12.1 — generate symptom-side expansions for every DTC record ("doc2query").

    PYTHONPATH=src .venv/bin/python scripts/gen_symptom_expansions.py

The manual says "Rail pressure Sensor Short circuit to ground". A driver says
"it loses power on a climb and the light came on". Phases 10.6 and 11.2 both
measured symptom MRR at about 0.24 on language the system had never seen, and the
error analysis blamed that gap. This script attacks it from the INDEX side:
for each record, a local model writes a few plain-language descriptions of how the
fault SHOWS UP, and those become extra searchable text.

RULES OBSERVED HERE
  * The only input is the record itself: description, effect, MIL, causes,
    checkpoints and system. One fixed prompt template, temperature 0, fixed seed.
  * NO gold or evaluation file is opened - not DEV, TEST, the independent set or
    R2. The only file read is data/dtc_records.jsonl.
  * Post-filtering is MECHANICAL ONLY: drop lines containing a fault code, empty
    lines, and duplicates. Nothing is hand-edited or hand-picked.
  * The output is INDEX-ONLY. It is never shown to a user, never rendered in a
    fix block, and never cited. It exists to be matched against, not read.

Resumable: progress is written after every record, so a long run can be stopped
and restarted without losing work.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, "src")

RECORDS = "data/dtc_records.jsonl"
OUT = "data/symptom_expansions.json"
MODEL = "models/qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct-GGUF (q4_k_m)"
SEED = 12101
TEMPERATURE = 0.0
MAX_TOKENS = 220
N_CTX = 2048
N_THREADS = 4
WANT_MIN, WANT_MAX = 4, 6

PROMPT_TEMPLATE = """You are a service advisor writing search aids for a workshop \
diagnostic tool.

Below is one diagnostic trouble code from a heavy diesel engine manual.

Fault: {description}
Subsystem: {system}
Effect on vehicle: {effect}
Warning lamp (MIL): {mil}
Likely causes: {causes}
What a technician checks: {checkpoints}

Write exactly {want} SHORT lines describing how this fault SHOWS UP to a driver \
or a technician in ordinary workshop English.

Rules:
- Put each symptom on its OWN line. Never join them into a paragraph.
- One symptom per line, 6 to 16 words, no numbering, no bullet characters.
- Describe what is SEEN, HEARD or FELT: behaviour on the road, starting, pulling \
power, idle, smoke, noise, a gauge reading or a warning lamp.
- Use plain words a driver would use. Do not use the manual's wording.
- Never mention a fault code, a pin number or a wire colour.
- Do not invent a symptom that this fault could not cause.

Lines only, nothing else."""

CODE_RE = re.compile(r"\b[PUBC]\d[0-9A-F]{2,3}(?:-[0-9A-F]{2})?\b", re.I)
BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def clean(line):
    """Mechanical tidy-up only: strip bullets, quotes and trailing punctuation."""
    s = BULLET_RE.sub("", line.strip())
    s = s.strip().strip('"“”').strip()
    return re.sub(r"\s+", " ", s)


SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def candidates(raw):
    """
    Split the completion into candidate symptoms, mechanically.

    The model often ignores "one per line" and returns a paragraph of short
    sentences, so a line carrying several sentences is split on sentence
    boundaries. This is a split, not an edit: no wording is changed.
    """
    out = []
    for line in raw.splitlines():
        s = clean(line)
        if not s:
            continue
        parts = SENT_SPLIT_RE.split(s) if len(s.split()) > 16 else [s]
        for part in parts:
            part = clean(part).rstrip(".")
            if part:
                out.append(part)
    return out


def acceptable(s):
    """Mechanical filter. No judgement about content."""
    if not s or len(s) < 12:
        return False, "too short"
    if len(s.split()) > 24:
        return False, "too long"
    if CODE_RE.search(s):
        return False, "contains a fault code"
    if s.endswith(":"):
        return False, "looks like a heading"
    return True, None


def build_prompt(rec):
    return PROMPT_TEMPLATE.format(
        description=rec["description"],
        system=rec["system"],
        effect=rec.get("effect") or "not stated",
        mil=rec.get("MIL") or "not stated",
        causes="; ".join(rec.get("cause") or []) or "not stated",
        checkpoints="; ".join(rec.get("checkpoints") or []) or "not stated",
        want=WANT_MAX)


def main():
    records = [json.loads(l) for l in open(RECORDS)]
    done = {}
    if os.path.exists(OUT):
        blob = json.load(open(OUT))
        if blob.get("model") == MODEL_NAME and blob.get("seed") == SEED \
                and blob.get("prompt_template") == PROMPT_TEMPLATE:
            done = blob.get("records", {})
            print(f"resuming: {len(done)} records already generated")

    from llama_cpp import Llama
    print(f"loading {MODEL} ...")
    t0 = time.time()
    llm = Llama(model_path=MODEL, n_ctx=N_CTX, n_threads=N_THREADS, seed=SEED, verbose=False)
    print(f"loaded in {time.time() - t0:.1f}s")

    started = time.time()
    stats = {"kept": 0, "dropped": {}, "generated": 0}
    for i, rec in enumerate(records, 1):
        rid = f"{rec['code_full']}@p{rec['page']}#{rec['occurrence']}"
        if rid in done:
            continue
        t = time.time()
        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": build_prompt(rec)}],
            temperature=TEMPERATURE, seed=SEED, max_tokens=MAX_TOKENS)
        raw = out["choices"][0]["message"]["content"]
        kept, dropped, seen = [], [], set()
        for s in candidates(raw):
            ok, why = acceptable(s)
            if not ok:
                if s:
                    dropped.append({"text": s, "reason": why})
                    stats["dropped"][why] = stats["dropped"].get(why, 0) + 1
                continue
            key = s.lower()
            if key in seen:
                dropped.append({"text": s, "reason": "duplicate"})
                stats["dropped"]["duplicate"] = stats["dropped"].get("duplicate", 0) + 1
                continue
            seen.add(key)
            kept.append(s)
        kept = kept[:WANT_MAX]
        done[rid] = {"code_full": rec["code_full"], "system": rec["system"],
                     "expansions": kept, "dropped": dropped,
                     "completion_tokens": out["usage"]["completion_tokens"],
                     "seconds": round(time.time() - t, 2)}
        stats["kept"] += len(kept)
        stats["generated"] += 1

        blob = {"_label": "index-only, never shown to users",
                "purpose": "symptom-side document expansion (doc2query) for retrieval only",
                "model": MODEL_NAME, "seed": SEED, "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS, "n_ctx": N_CTX,
                "prompt_template": PROMPT_TEMPLATE,
                "post_filter": "mechanical only: drop fault codes, empty, too short/long, "
                               "headings and duplicates. No hand-editing.",
                "inputs_used": ["description", "system", "effect", "MIL", "cause",
                                "checkpoints"],
                "no_gold_read": "no DEV/TEST/independent/R2 file is opened by this script",
                "records": done}
        tmp = OUT + ".tmp"
        with open(tmp, "w") as f:
            json.dump(blob, f, indent=1, ensure_ascii=False)
        os.replace(tmp, OUT)

        if i % 10 == 0 or i == len(records):
            el = time.time() - started
            rate = stats["generated"] / el if el else 0
            left = (len(records) - len(done)) / rate / 60 if rate else 0
            print(f"  {len(done)}/{len(records)} records | "
                  f"{stats['kept'] / max(1, stats['generated']):.1f} kept/record | "
                  f"{el / 60:.1f} min elapsed | ~{left:.0f} min left", flush=True)

    print(f"\ndone: {len(done)} records, {stats['kept']} expansions kept, "
          f"dropped {stats['dropped']}")
    print(f"total {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
