"""
Phase 9.1 — "top-3 DTCs with fix steps" advise mode (additive).

For any in-scope input, return THREE diagnostic trouble codes, each with a full
deterministic fix block rendered from the manual record:

  * input contains a DTC code  -> that code's record(s) first, then the nearest
    related codes until there are 3: same-system records preferred, then
    cross-system, each by exact cosine between stored record vectors
  * natural-language symptom   -> the top-3 records from the production retriever

Nothing here changes retrieval, the gate or the indexes. The fix steps come from
the record, never from a model. An optional one-sentence LLM summary per code is
returned in a separate, clearly labelled field and is off by default.

Out-of-scope symptom input is still refused by gate v2: returning repair steps
for "what is the capital of France" would be exactly the fabrication the gate
exists to prevent. An input containing a DTC code is in scope by definition and
bypasses the gate.

    PYTHONPATH=src .venv/bin/python src/advise.py "coolant gauge stuck at the bottom"
    PYTHONPATH=src .venv/bin/python src/advise.py "P0192-00" --json
    PYTHONPATH=src .venv/bin/python src/advise.py "P0192-00" --summary
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

TOP_N = 3


# ---------------------------------------------------------------- fix block
def _branch_text(step):
    """Readable branch logic. Mirrors answer.render_record: an unconditional jump
    is never phrased as "if yes", which would invent a decision."""
    parts = []
    if step["on_true"] is not None:
        parts.append(f"if yes -> Step {step['on_true']}" if step["condition"]
                     else f"then go to Step {step['on_true']}")
    if step["on_false"] is not None:
        parts.append(f"if no -> Step {step['on_false']}")
    if not parts:
        return None
    flag = "" if step["polarity_confidence"] == "high" else " (inferred)"
    return "; ".join(parts) + flag


def fix_block(rec):
    """Structured, deterministic fix block + its rendered text (answer.render_record)."""
    from answer import render_record
    specs = {s["n"]: s["spec"] for s in rec.get("specifications") or []}
    sch = [i for i in rec.get("image_refs") or [] if i["kind"] == "circuit_schematic"]
    return {
        "code_full": rec["code_full"],
        "description": rec["description"],
        "system": rec["system"],
        "effect": rec.get("effect"),
        "MIL": rec.get("MIL"),
        "cause": list(rec.get("cause") or []),
        "checkpoints": list(rec.get("checkpoints") or []),
        "steps": [{"n": s["n"], "text": s["text"], "spec": specs.get(s["n"]),
                   "branch": _branch_text(s)} for s in rec["steps"]],
        "pins": [p["pin"] for p in rec.get("pin_map") or [] if p["confidence"] == "high"],
        "schematic_page": sch[0]["page"] if sch else None,
        "page": rec["page"],
        "occurrence": rec["occurrence"],
        "citation": f"{rec['code_full']}, manual page {rec['page']}",
        "text": render_record(rec),
    }


# ---------------------------------------------------------------- related codes
def related_records(R, primary_ids, n):
    """
    Nearest records to the FIRST primary by exact cosine over the stored vectors,
    excluding every record that shares a primary's code (so the second occurrence
    of a duplicated code is not reported as "related"). Ties break by record id.

    Ranking preference (Phase 9.1b), not a hard filter: records in the SAME
    `system` as the anchor come first, ordered by cosine; cross-system records
    fill any remaining slots, also by cosine. E.g. P0192-00 (rail_pressure) ->
    P0193-00, P0194-00 rather than the slightly closer fuel_supply P0180-11.
    """
    exclude = {R._rec(i)["code_full"] for i in primary_ids}
    anchor = R.vec_ids.index(primary_ids[0])
    anchor_system = R._rec(primary_ids[0])["system"]
    sims = R.vectors @ R.vectors[anchor]

    def key(i):
        other = R._rec(R.vec_ids[i])["system"] != anchor_system
        return (other, -float(sims[i]), R.vec_ids[i])

    out = []
    for i in sorted(range(len(R.vec_ids)), key=key):
        rec = R._rec(R.vec_ids[i])
        if rec["code_full"] in exclude:
            continue
        out.append((R.vec_ids[i], float(sims[i])))
        exclude.add(rec["code_full"])
        if len(out) >= n:
            break
    return out


def _id(rec):
    return f"{rec['code_full']}@p{rec['page']}#{rec['occurrence']}"


# ---------------------------------------------------------------- core
def advise(query, R, phraser=None, summary=False, top_n=TOP_N):
    import answer as A
    out = R.retrieve(query, k=top_n)
    trace = {"router_mode": out["mode"], "retrieval_trace": out["trace"]}
    results = []

    if out["mode"] == "invalid_code":
        # Phase 13.4: no fix blocks for a token that cannot be a code.
        t = out["trace"]
        return {"input": query, "mode": "invalid_code", "results": [],
                "message": t["message"], "candidates": t.get("candidates", []),
                "candidates_more": t.get("candidates_more", 0),
                "candidates_note": t.get("candidates_note"),
                "more_note": t.get("more_note"),
                "no_candidates_reason": t.get("no_candidates_reason"),
                "known_variants": [], "did_you_mean": [], "trace": trace}

    if out["mode"] == "incomplete_code":
        # Phase 13.3: no fix blocks for a code that was never finished.
        t = out["trace"]
        return {"input": query, "mode": "incomplete_code", "results": [],
                "message": t["message"], "candidates": t.get("candidates", []),
                "candidates_more": t.get("candidates_more", 0),
                "more_note": t.get("more_note"),
                "no_candidates_reason": t.get("no_candidates_reason"),
                "known_variants": [], "did_you_mean": [], "trace": trace}

    if out["mode"] in ("unknown_code", "suffix_not_found"):
        # Phase 9.3b: never return fix blocks for a code the manual does not contain.
        t = out["trace"]
        return {"input": query, "mode": "refused" if out["mode"] == "unknown_code"
                else "clarify_code", "results": [], "message": t["message"],
                "known_variants": t.get("known_variants", []),
                "did_you_mean": t.get("did_you_mean", []), "trace": trace}

    if out["mode"] == "exact_code" and out["results"]:
        mode = "dtc_code"
        primaries = [item["record"] for item in out["results"]][:top_n]
        code = out["trace"].get("detected_code")
        for rec in primaries:
            results.append((rec, f"DTC code {code} matched in the code index "
                                 f"({out['trace'].get('lookup')})"))
        if len(results) < top_n:
            anchor = primaries[0]
            for rid, sim in related_records(R, [_id(r) for r in primaries], top_n - len(results)):
                rec = R._rec(rid)
                same = "same system" if rec["system"] == anchor["system"] else "different system"
                results.append((rec, f"related to {anchor['code_full']}: nearest record by "
                                     f"embedding similarity (cosine {sim:.3f}), {same} "
                                     f"({rec['system']})"))
        trace["related_by"] = ("same-system records first, then cross-system; "
                               "each ordered by exact cosine between stored record vectors")
    else:
        ok, signals = A.is_relevant(R, query)
        trace["gate"] = signals
        if not ok:
            return {"input": query, "mode": "refused", "results": [],
                    "message": A.NOT_COVERED,
                    "refusal_reasons": signals.get("refusal_reasons"), "trace": trace}
        mode = "symptom" if out["mode"] == "hybrid" else out["mode"]
        fused = {f["code"]: f for f in out["trace"].get("fused_top", [])}
        matched = (out["trace"].get("expansion") or {}).get("matched") or []
        for rank, item in enumerate(out["results"][:top_n], 1):
            rec = item["record"]
            if out["mode"] == "system_group":
                why = (f"listed in subsystem '{out['trace'].get('system')}', ranked "
                       f"{item.get('dense_rank')} by dense similarity to the query")
            else:
                f = fused.get(rec["code_full"], {})
                why = (f"hybrid search rank {rank}: dense rank {f.get('dense_rank', '-')}, "
                       f"keyword rank {f.get('bm25_rank', '-')}, RRF {item['score']}")
                if matched:
                    why += f"; lexicon matched {matched}"
            results.append((rec, why))

    rendered = []
    for rank, (rec, why) in enumerate(results, 1):
        entry = {"rank": rank, "code_full": rec["code_full"], "why_retrieved": why,
                 "fix_block": fix_block(rec)}
        if summary:
            entry["llm_summary"] = one_sentence_summary(rec, phraser)
        rendered.append(entry)
    return {"input": query, "mode": mode, "results": rendered, "trace": trace}


def one_sentence_summary(rec, phraser):
    """Optional, clearly separated from the deterministic fix block."""
    import answer as A
    if phraser is None:
        phraser = A.Phraser()
    ctx = A.build_context([{"record": rec}], max_records=1)
    text, stat = phraser.answer(
        f"In one sentence: what does {rec['code_full']} mean and what is the first thing to check?",
        ctx, max_tokens=60)
    return {"text": text, "source": "LLM (Qwen2.5-0.5B), phrasing only - not a repair step",
            "tokens_per_sec": stat.get("tokens_per_sec")}


# ---------------------------------------------------------------- CLI
def print_report(res):
    print("=" * 78)
    print(f"INPUT: {res['input']}")
    print(f"MODE : {res['mode']}")
    if res["mode"] in ("refused", "clarify_code"):
        why = ", ".join(res.get("refusal_reasons") or [])
        print(f"\n{res['message']}" + (f"  (reason: {why})" if why else ""))
        if res.get("did_you_mean"):
            print(f"Did you mean (not selected): {', '.join(res['did_you_mean'])}")
        print("=" * 78)
        return
    for r in res["results"]:
        fb = r["fix_block"]
        print("-" * 78)
        print(f"#{r['rank']}  {fb['code_full']}  —  {fb['description']}")
        print(f"    why: {r['why_retrieved']}")
        if r.get("llm_summary"):
            print(f"    [AI summary, not a repair step] {r['llm_summary']['text']}")
        print()
        print(fb["text"])
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser(description="Top-3 DTCs with deterministic fix steps")
    ap.add_argument("input", help='a DTC code, a sentence containing one, or a symptom')
    ap.add_argument("--json", action="store_true", help="print the JSON response")
    ap.add_argument("--summary", action="store_true",
                    help="add a one-sentence LLM summary per code (slower)")
    args = ap.parse_args()

    from cli import quiet_stderr
    with quiet_stderr():
        from retrieve import Retriever
        R = Retriever()
        res = advise(args.input, R, summary=args.summary)
    if args.json:
        print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    else:
        print_report(res)


if __name__ == "__main__":
    main()
