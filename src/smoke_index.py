"""
Phase 4 smoke tests — sanity only. Full retrieval evaluation is Phase 7.

Checks that the three indexes are present, populated and behaving, without
building any router or fusion (that is Phase 5).
"""
from __future__ import annotations

import json
import resource
from collections import Counter

INDEX_DIR = "index"
COLLECTION = "dtc_records"

# (query, expected top-1, known_hard)
# known_hard: a near-duplicate pair MiniLM alone cannot separate. Recorded as
# XFAIL rather than softened, because the hybrid retrieval in Phase 5 is exactly
# the designed remedy - BM25 separates this pair decisively (see the Phase 4
# report). Do not tune the embedding to make it pass.
DENSE_CASES = [
    ("rail pressure sensor short to ground", "P0192-00", False),
    ("EGR valve stuck closed", "P042F-00", False),
    ("camshaft no signal", "P0340-00", True),
]

results = []


def check(name, ok, detail="", known_hard=False):
    if not ok and known_hard:
        results.append((name, None))
        print(f"  [XFAIL] {name}" + (f" — {detail}" if detail else ""))
        return
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    recs = {f"{r['code_full']}@p{r['page']}#{r['occurrence']}": r
            for r in (json.loads(l) for l in open("data/dtc_records.jsonl"))}

    import chromadb
    client = chromadb.PersistentClient(path=f"{INDEX_DIR}/chroma")
    coll = client.get_collection(COLLECTION)

    print("\n== 1. Chroma vector count ==")
    check("count == 314", coll.count() == 314, f"got {coll.count()}")

    print("\n== 2. Dense top-1 ==")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    for q, expect, hard in DENSE_CASES:
        qv = model.encode([q], normalize_embeddings=True).tolist()
        res = coll.query(query_embeddings=qv, n_results=3)
        top = res["metadatas"][0][0]["code_full"]
        dists = [round(d, 3) for d in res["distances"][0]]
        got3 = [m["code_full"] for m in res["metadatas"][0]]
        note = ""
        if hard and top != expect and expect in got3:
            note = f" | {expect} at rank {got3.index(expect)+1}; BM25 separates this pair"
        check(f'"{q}" -> {expect}', top == expect,
              f"top3={got3} cos_dist={dists}{note}", known_hard=hard)
    del model

    print("\n== 3. Exact-code index ==")
    idx = json.load(open(f"{INDEX_DIR}/code_index.json"))
    full, base = idx["by_code_full"], idx["by_dtc_code"]
    d = full.get("P0180-11", [])
    check("P0180-11 returns BOTH records", len(d) == 2,
          f"pages={[x['page'] for x in d]} occurrences={[x['occurrence'] for x in d]}")
    v = base.get("P0192", [])
    check("base P0192 returns its variant(s)", len(v) >= 1,
          f"{[x['code_full'] for x in v]}")
    v100 = base.get("P0100", [])
    check("base P0100 returns all suffixed variants", len(v100) > 1,
          f"{[x['code_full'] for x in v100]}")
    dups = {k: len(x) for k, x in full.items() if len(x) > 1}
    check("duplicate codes stored as lists, none overwritten",
          dups == {"P0180-11": 2, "P0180-12": 2, "P061C-00": 2}, f"{dups}")

    print("\n== 4. BM25 ==")
    from rank_bm25 import BM25Okapi
    from build_index import tokenize
    blob = json.load(open(f"{INDEX_DIR}/bm25_corpus.json"))
    bm25 = BM25Okapi(blob["corpus"])
    ids = blob["ids"]

    def bm_top(q, k=5):
        sc = bm25.get_scores(tokenize(q))
        order = sorted(range(len(sc)), key=lambda i: -sc[i])[:k]
        return [(ids[i].split("@")[0], round(sc[i], 2)) for i in order if sc[i] > 0]

    a71 = bm_top("A71")
    codes = [c for c, _ in a71]
    check("query 'A71' surfaces P0192-00 / P0193-00",
          "P0192-00" in codes and "P0193-00" in codes, f"{a71}")
    egr = bm_top("EGR", k=6)
    egr_codes = [c for c, _ in egr]
    egr_sys = sum(1 for c in egr_codes
                  if any(r["system"] == "egr" for k, r in recs.items()
                         if r["code_full"] == c))
    check("query 'EGR' surfaces the EGR group", egr_sys >= 4,
          f"{egr_sys}/{len(egr_codes)} of top hits are system=egr: {egr_codes}")
    tok = tokenize("P0192-00 and pin A71")
    check("tokenizer keeps DTC codes and pins intact",
          "p0192-00" in tok and "a71" in tok and "p0192" in tok, f"{tok}")

    print("\n== 5. Metadata filter ==")
    got = coll.get(where={"system": "egr"})
    n_egr = len(got["ids"])
    truth = sum(1 for r in recs.values() if r["system"] == "egr")
    check(f"system=='egr' filter returns {truth}", n_egr == truth, f"got {n_egr}")
    hist = Counter(r["system"] for r in recs.values())
    print("\n  systems histogram:")
    for s, n in hist.most_common():
        print(f"    {s:20s} {n}")

    # ================= 6. PHASE 5 — router + RRF acceptance =================
    print("\n== 6. Phase 5 router + RRF acceptance ==")
    from retrieve import Retriever
    R = Retriever()

    def codes_of(out):
        return [i["record"]["code_full"] for i in out["results"]]

    # (a) the Phase-4 XFAIL must now PASS through fusion
    out = R.retrieve("camshaft no signal")
    c = codes_of(out)
    ft = out["trace"]["fused_top"][:2]
    check("[was XFAIL] 'camshaft no signal' -> P0340-00 rank 1",
          c and c[0] == "P0340-00",
          f"top3={c[:3]} | rrf tie {ft[0]['rrf']}=={ft[1]['rrf']} broken by "
          f"tiebreak {ft[0]['tiebreak']} vs {ft[1]['tiebreak']}")

    out = R.retrieve("camshaft disturbed signal")
    c = codes_of(out)
    check("'camshaft disturbed signal' -> P0341-00 rank 1",
          c and c[0] == "P0341-00", f"top3={c[:3]}")

    # (b) exact-code routing
    out = R.retrieve("how do I fix P0192-00")
    check("'how do I fix P0192-00' -> mode=exact_code, returns P0192-00",
          out["mode"] == "exact_code" and "P0192-00" in codes_of(out),
          f"mode={out['mode']} codes={codes_of(out)}")

    out = R.retrieve("P0180-11")
    pages = [i["record"]["page"] for i in out["results"]]
    check("'P0180-11' -> BOTH duplicate records",
          out["mode"] == "exact_code" and len(out["results"]) == 2,
          f"n={len(out['results'])} pages={pages}")

    out = R.retrieve("P0100")
    c = sorted(codes_of(out))
    check("'P0100' -> all 3 suffix variants",
          out["mode"] == "exact_code" and len(c) == 3,
          f"{c}")

    # (b2) code-shaped token that is not a real DTC -> fall back to hybrid
    out = R.retrieve("what does connector C001 do")
    check("C001-shaped token -> falls back to hybrid, non-empty",
          out["mode"] == "hybrid" and len(out["results"]) > 0,
          f"mode={out['mode']} n={len(out['results'])} "
          f"fallback={out['trace'].get('fallback')}")

    # (c) grouping vs specific-fault - the discrimination that matters
    out = R.retrieve("list all EGR faults")
    check("'list all EGR faults' -> mode=system_group, 14 records",
          out["mode"] == "system_group" and len(out["results"]) == 14,
          f"mode={out['mode']} n={len(out['results'])}")

    out = R.retrieve("EGR valve stuck closed")
    c = codes_of(out)
    check("'EGR valve stuck closed' -> mode=hybrid, P042F-00 in top-3 "
          "(NOT the whole group)",
          out["mode"] == "hybrid" and "P042F-00" in c[:3],
          f"mode={out['mode']} top3={c[:3]} "
          f"soft_system={out['trace'].get('soft_system_signal')}")

    out = R.retrieve("rail pressure sensor short to ground")
    c = codes_of(out)
    check("'rail pressure sensor short to ground' -> P0192-00 rank 1",
          c and c[0] == "P0192-00", f"top3={c[:3]}")

    # (d) code-free symptom query - eyeball
    q = "torque reduction, MIL on, low rail pressure"
    out = R.retrieve(q, k=5)
    print(f"\n  code-free symptom query: {q!r} -> mode={out['mode']}")
    for i, item in enumerate(out["results"], 1):
        r_ = item["record"]
        print(f"    {i}. {r_['code_full']:10s} [{r_['system']:14s}] "
              f"{r_['description'][:58]}")
        print(f"       effect={str(r_['effect'])[:52]!r} "
              f"dense_rank={item.get('dense_rank')} bm25_rank={item.get('bm25_rank')}")
    check("symptom query returns 5 sane results", len(out["results"]) == 5,
          f"n={len(out['results'])}")

    # ================= 7. PHASE 6 — answer + diagnose ======================
    print("\n== 7. Phase 6 answering + deterministic diagnosis ==")
    import answer as A
    from diagnose import walk, Diagnoser
    by_code = {}
    for r in recs.values():
        by_code.setdefault(r["code_full"], []).append(r)

    # (a) deterministic answer, no LLM
    p0192 = by_code["P0192-00"][0]
    txt = A.render_record(p0192)
    needed = ["P0192-00", "Rail pressure Sensor Short circuit to ground",
              "Torque reduction", "Likely causes", "Checkpoints",
              "Troubleshooting steps", "Step 13", "A71", "A83",
              "circuit schematic, page 9", "manual page 8"]
    missing = [n for n in needed if n not in txt]
    check("P0192-00 deterministic answer renders all sections, cites page 8",
          not missing, f"missing={missing}" if missing else f"{len(txt)} chars")
    out = A.answer("how do I fix P0192-00", R, phraser=None)
    check("exact_code answer uses the fast path (no LLM called)",
          out["path"] == "deterministic" and ("P0192-00", 8) in out["citations"],
          f"path={out['path']} citations={out['citations']}")

    # (b) simulated walk, both branches at step 10
    t_yes = walk(p0192, ["no", "no", "no", "no", "yes", "no", "no", "yes"])
    t_no = walk(p0192, ["no", "no", "no", "no", "yes", "no", "no", "no"])
    step10 = lambda t: next((x["to"] for x in t["transitions"] if x["from"] == 10), None)
    check("P0192-00 walk: continuity OK at step 10 -> step 12",
          step10(t_yes) == 12 and t_yes["visited"][-1] == 13,
          f"visited={t_yes['visited']}")
    check("P0192-00 walk: continuity NOT ok at step 10 -> step 11",
          step10(t_no) == 11 and t_no["visited"][-1] == 13,
          f"visited={t_no['visited']}")
    check("both branches reach the terminal 'Check DTC'",
          t_yes["visited"][-1] == t_no["visited"][-1] == 13
          and p0192["steps"][-1]["kind"] == "terminal",
          f"terminal step {p0192['steps'][-1]['n']}")

    # (c) out-of-range target is clamped to the terminal step, and logged
    oor = None
    for r in recs.values():
        valid = {x["n"] for x in r["steps"]}
        if any(x["on_true"] is not None and x["on_true"] not in valid
               for x in r["steps"]):
            oor = r
            break
    d = Diagnoser(oor)
    st = d.start()
    bad = next(x for x in oor["steps"]
               if x["on_true"] is not None and x["on_true"] not in {y["n"] for y in oor["steps"]})
    st.current = bad["n"]
    st = d.advance(st, "yes")
    check(f"out-of-range target in {oor['code_full']} clamps to terminal + logs",
          st.clamps and st.clamps[0]["clamped_to"] == d.terminal,
          f"step {bad['n']} requested {bad['on_true']} -> clamped to {d.terminal}; "
          f"{len(st.clamps)} clamp(s) logged")

    # (d) synthetic cycle must terminate
    cyc = {"code_full": "TEST-00", "page": 0, "occurrence": 1,
           "specifications": [], "image_refs": [], "pin_map": [],
           "steps": [
               {"n": 1, "text": "A", "kind": "branch", "condition": "If x",
                "on_true": 2, "on_false": None, "goto": [2],
                "polarity_confidence": "high"},
               {"n": 2, "text": "B", "kind": "branch", "condition": "If y",
                "on_true": 1, "on_false": None, "goto": [1],
                "polarity_confidence": "high"},
               {"n": 3, "text": "Check DTC", "kind": "terminal", "condition": None,
                "on_true": None, "on_false": None, "goto": [],
                "polarity_confidence": "high"}]}
    tc = walk(cyc, ["yes"] * 50)
    check("synthetic cycle terminates via loop guard",
          tc["finished"] and len(tc["visited"]) < 10,
          f"visited={tc['visited']} outcome={tc['outcome']!r}")

    # (e) LLM grounding, both directions
    ph = A.Phraser()
    ph.load()
    a_in = A.answer("my truck has torque reduction and the MIL is on with "
                    "low rail pressure", R, ph)
    cited = [c for c, _ in a_in["citations"]]
    check("symptom query -> LLM answer citing a correct DTC",
          a_in["path"] == "llm" and any(c in a_in["text"] for c in cited),
          f"cited={cited} tok/s={a_in['llm_stats']['tokens_per_sec']}")
    a_out = A.answer("how do I change a tyre", R, ph)
    check("out-of-scope query -> honest 'not covered', NOT a fabricated DTC",
          a_out["text"] == A.NOT_COVERED and a_out["path"] == "deterministic_gate",
          f"path={a_out['path']} rel={a_out['relevance']}")
    print(f"\n  LLM benchmark: load {ph.load_seconds:.2f}s | "
          f"{a_in['llm_stats']['tokens_per_sec']} tok/s | "
          f"{a_in['llm_stats']['completion_tokens']} tokens in "
          f"{a_in['llm_stats']['seconds']}s on 4 vCPU")

    # ================= 8. PHASE 8.1 — skip_true_branch corrections (L2) ======
    print("\n== 8. Phase 8.1 skip_true_branch manual corrections ==")
    from diagnose import MANUAL_CORRECTIONS

    def step_no(rec, n):
        """Advance from step n with answer 'no'; return (landed_on, state)."""
        dg = Diagnoser(rec)
        st = dg.start()
        st.current = n
        st = dg.advance(st, "no")
        return st.current, st, dg

    for (code, n), corr in sorted(MANUAL_CORRECTIONS.items()):
        rec = next(r for r in by_code[code] if r["page"] == corr["page"])
        order = [x["n"] for x in rec["steps"]]
        skipped_fix = order[order.index(n) + 2]          # where the old rule landed
        landed, st, dg = step_no(rec, n)
        logged = [c for c in st.corrections if c["rule"] == "manual_correction"]
        check(f"{code} s{n}: 'no' -> terminal, not the skipped fix",
              landed == dg.terminal and landed != skipped_fix and len(logged) == 1
              and not st.inferences,
              f"landed={landed} terminal={dg.terminal} (old rule -> s{skipped_fix}); "
              f"manual_correction logged={len(logged)}")

    # P0194-00 s7 was flagged in Phase 7 but is CORRECT - pin it, do not override
    rec = by_code["P0194-00"][0]
    landed, st, dg = step_no(rec, 7)
    s9 = next(x for x in rec["steps"] if x["n"] == 9)
    check("P0194-00 s7 (not overridden): 'no back-out' -> s9 change sensor",
          landed == 9 and not st.corrections
          and any(i["rule"] == "skip_true_branch" for i in st.inferences),
          f"landed={landed} {s9['text'][:40]!r}; corrections={len(st.corrections)}")

    # the general rule must be untouched at EVERY other candidate step
    fired_elsewhere, candidates = [], 0
    for r in recs.values():
        order = [x["n"] for x in r["steps"]]
        for i, x in enumerate(r["steps"]):
            nxt = order[i + 1] if i + 1 < len(order) else None
            if not (x["condition"] and nxt and x["on_true"] == nxt
                    and x["on_false"] is None):
                continue
            if (r["code_full"], x["n"]) in MANUAL_CORRECTIONS:
                continue
            candidates += 1
            _, st2, _ = step_no(r, x["n"])
            if st2.corrections:
                fired_elsewhere.append(f"{r['code_full']}@p{r['page']} s{x['n']}")
    check("manual_correction fires at NO other step (general rule unweakened)",
          not fired_elsewhere,
          f"{candidates} other skip_true_branch candidates checked; "
          f"stray corrections={fired_elsewhere[:5]}")

    npass = sum(1 for _, ok in results if ok is True)
    nxfail = sum(1 for _, ok in results if ok is None)
    nfail = sum(1 for _, ok in results if ok is False)
    print(f"\n==== SMOKE: {npass} passed, {nxfail} xfail (known-hard), "
          f"{nfail} failed ====")
    print(f"peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")
    raise SystemExit(main())
