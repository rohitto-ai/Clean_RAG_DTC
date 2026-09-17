"""
Phase 9.3 — noisy-input robustness / failure modes. Additive; production untouched.

    PYTHONPATH=src .venv/bin/python scripts/robustness_9_3.py

A corrupted P-code stands in for a noisy telematics fault record; a corrupted symptom
stands in for a hurried technician note. Clean base cases are a seeded sample of
data/gold_autogen.jsonl `code` and `paraphrase` cases (ground truth = OEM manual, NOT
human-verified). Every transform is deterministic (random.Random seeded by a string).

System under test = production AS SERVED, minus the LLM: Retriever() router + gate v2
applied exactly where answer.answer() applies it (hybrid route only). The LLM only
phrases the hybrid answer; which DTCs are shown is decided here.

Outcome of every query (mutually exclusive, first match wins):
  refused         no results, or gate v2 refused (the user sees "not covered")
  correct@1       an expected code is ranked first
  correct@3       an expected code is in the top 3 (not first)
  correct_listed  exact-code route on a BASE code: all suffix variants are rendered and
                  the expected one is among them at rank > 3 (ambiguous, not wrong)
  HARMFUL         exact-code route answered with a DTC that is NOT expected: the user
                  gets a deterministic, unhedged repair procedure for the wrong fault.
                  For garbage input (nothing expected) any exact-code answer is harmful.
  wrong_hedged    hybrid/group route passed the gate but no expected code in the top 3
                  (a ranked candidate list is shown, not a single asserted fault).
                  For garbage input every non-refused hybrid answer lands here.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from collections import Counter

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

N_CODE, N_SYMPTOM, K = 80, 80, 5
OUT_DIR = "data/experiments/9_3"
OUTCOMES = ["correct@1", "correct@3", "correct_listed", "refused", "HARMFUL", "wrong_hedged"]


# ---------------------------------------------------------------- code noise
def _rng(case_id, noise):
    return random.Random(f"9.3:{case_id}:{noise}")


def code_noise(code, cid):
    """{noise_name: (class, query)} for a code like P0192-00."""
    base, suf = code.split("-")
    out = {
        "code_clean": ("clean", code),
        "code_lowercase": ("recoverable", code.lower()),
        "code_missing_suffix": ("recoverable", base),
        "code_spacing_punct": ("recoverable", _rng(cid, "sp").choice(
            [f"P {base[1:]}-{suf}", f"{base} - {suf}", f"{base}_{suf}", f"({code}).",
             f"{base}.{suf}", f"  {code} ;"])),
        "code_embedded_in_log": ("recoverable", _rng(cid, "log").choice([
            f"ts=1726570000 ecu=MD1CS018 dtc={code} cnt=3 lamp=1",
            f"[WARN] fault record: {code}, occurrences 4, odometer 18234 km",
            f"telematics pkt#8841 status=ACTIVE code:{code} freeze_frame=yes"])),
    }
    # letter O for a zero: prefer a zero in the suffix (P0192-O0), else in the base
    zs = [i for i, ch in enumerate(suf) if ch == "0"]
    if zs:
        s = list(suf); s[zs[0]] = "O"
        out["code_O_for_zero"] = ("recoverable", f"{base}-{''.join(s)}")
    else:
        zb = [i for i, ch in enumerate(base) if ch == "0"]
        if zb:
            b = list(base); b[zb[0]] = "O"
            out["code_O_for_zero"] = ("recoverable", f"{''.join(b)}-{suf}")
    digits = base[1:]
    r = _rng(cid, "tr")
    pairs = [i for i in range(len(digits) - 1) if digits[i] != digits[i + 1]]
    if pairs:
        i = r.choice(pairs)
        d = list(digits); d[i], d[i + 1] = d[i + 1], d[i]
        out["code_transposed_digit"] = ("unrecoverable", f"{base[0]}{''.join(d)}-{suf}")
    j = _rng(cid, "dr").randrange(len(digits))
    out["code_dropped_digit"] = ("unrecoverable", f"{base[0]}{digits[:j]}{digits[j+1:]}-{suf}")
    return out


# ---------------------------------------------------------------- symptom noise
ABBREV = [(r"\btemperature\b", "temp"), (r"\bsensor\b", "sens"), (r"\bpressure\b", "press"),
          (r"\bcircuit\b", "ckt"), (r"\bbattery\b", "batt"), (r"\bvoltage\b", "V"),
          (r"\bsignal\b", "sig"), (r"\binjector\b", "inj"), (r"\bcylinder\b", "cyl"),
          (r"\bturbocharger\b", "turbo"), (r"\bexhaust\b", "exh"), (r"\bconnection\b", "conn"),
          (r"\bheat reading\b", "temp"), (r"\belectrical level\b", "volts"),
          (r"\bpositive supply\b", "+ve"), (r"\bnegative side\b", "gnd"),
          (r"\bmaximum\b", "max"), (r"\bminimum\b", "min"), (r"\bcontrol\b", "ctrl")]


def typo_word(w, r):
    if len(w) < 5:
        return w
    i = r.randrange(1, len(w) - 2)
    op = r.choice(["swap", "drop", "double"])
    if op == "swap":
        return w[:i] + w[i + 1] + w[i] + w[i + 2:]
    if op == "drop":
        return w[:i] + w[i + 1:]
    return w[:i] + w[i] + w[i:]


def symptom_noise(q, cid):
    r = _rng(cid, "typo")
    words = q.split()
    idx = [i for i, w in enumerate(words) if len(w) >= 5]
    pick = set(r.sample(idx, max(1, round(0.2 * len(idx))))) if idx else set()
    typo = " ".join(typo_word(w, r) if i in pick else w for i, w in enumerate(words))
    ab = q
    for pat, rep in ABBREV:
        ab = re.sub(pat, rep, ab, flags=re.I)
    core = re.sub(r"^(what should I check for|troubleshooting help needed:)\s*", "", q, flags=re.I)
    trunc = " ".join(core.split()[:3])
    return {
        "symptom_clean": ("clean", q),
        "symptom_typos_20pct": ("recoverable", typo),
        "symptom_abbreviations": ("recoverable", ab),
        "symptom_truncated_3_words": ("degraded", trunc),
    }


# ---------------------------------------------------------------- garbage
def garbage_cases(records_codes):
    r = random.Random("9.3:garbage")
    alpha = "abcdefghijklmnopqrstuvwxyz"
    out = []
    for i in range(30):
        toks = ["".join(r.choice(alpha) for _ in range(r.randint(3, 9)))
                for _ in range(r.randint(2, 6))]
        out.append(("garbage_random_tokens", " ".join(toks)))
    for q in ["", " ", "?", "...", "-", "asdf", "qwerty", "123", "0000", "!!!!"]:
        out.append(("garbage_empty_ish", q))
    for q in ["what is the capital of France", "book a service appointment for tomorrow",
              "how much does a new windscreen cost", "play some music",
              "what is the weather in Pune today", "tell me a joke",
              "who won the cricket match", "convert 20 euros to rupees",
              "recommend a good restaurant nearby", "what is the warranty period"]:
        out.append(("garbage_out_of_domain", q))
    # well-formed codes that do not exist in this manual (telematics from another ECU)
    fake = []
    while len(fake) < 10:
        c = f"P{r.choice('0123')}{r.choice('0123456789ABCDEF')}{r.choice('0123456789ABCDEF')}" \
            f"{r.choice('0123456789ABCDEF')}-{r.choice('0123456789ABCDEF')}{r.choice('0123456789ABCDEF')}"
        if c not in records_codes and c.split("-")[0] not in {x.split("-")[0] for x in records_codes}:
            fake.append(c)
    out += [("garbage_nonexistent_code", c) for c in fake]
    return out


# ---------------------------------------------------------------- harness
def classify(R, A, query, expected):
    try:
        out = R.retrieve(query, k=K)
    except Exception as e:                          # a crash is a failure mode too
        return {"outcome": "error", "route": "error", "got": [], "error": repr(e)}
    route = out["mode"]
    # The exact-code route renders EVERY matched record (a base code lists all its
    # suffix variants), so it is scored on the full list; ranked routes on the top K.
    got = [i["record"]["code_full"] for i in out["results"]]
    if route != "exact_code":
        got = got[:K]
    gated = False
    if route == "hybrid" and got:
        ok, _ = A.is_relevant(R, query)
        gated = not ok
    rank = next((i for i, c in enumerate(got, 1) if c in expected), None)
    if not got or gated:
        o = "refused"
    elif rank == 1:
        o = "correct@1"
    elif rank and rank <= 3:
        o = "correct@3"
    elif rank and route == "exact_code":
        o = "correct_listed"                        # in the rendered variant list, rank > 3
    elif route == "exact_code":
        o = "HARMFUL"
    else:
        o = "wrong_hedged"
    return {"outcome": o, "route": route, "got": got, "rank": rank,
            "lookup": out["trace"].get("lookup"),
            "fallback": "fallback" in out["trace"]}


def main():
    from retrieve import Retriever
    import answer as A
    R = Retriever()
    lines = open("data/gold_autogen.jsonl").read().splitlines()
    cases = [json.loads(l) for l in lines[1:]]
    codes_all = {c["query"] for c in cases if c["kind"] == "code"}
    rs = random.Random("9.3:sample")
    code_base = sorted(rs.sample([c for c in cases if c["kind"] == "code"], N_CODE),
                       key=lambda c: c["id"])
    sym_base = sorted(rs.sample([c for c in cases if c["kind"] == "paraphrase"], N_SYMPTOM),
                      key=lambda c: c["id"])

    rows = []
    for c in code_base:
        for noise, (cls, q) in code_noise(c["query"], c["id"]).items():
            rows.append({"base": c["id"], "noise": noise, "class": cls, "query": q,
                         "expected": c["expected"]})
    for c in sym_base:
        for noise, (cls, q) in symptom_noise(c["query"], c["id"]).items():
            rows.append({"base": c["id"], "noise": noise, "class": cls, "query": q,
                         "expected": c["expected"]})
    for noise, q in garbage_cases(codes_all):
        rows.append({"base": None, "noise": noise, "class": "garbage", "query": q, "expected": []})

    for row in rows:
        row.update(classify(R, A, row["query"], row["expected"]))

    # transposed/dropped digits can produce ANOTHER valid code: record whether it did
    for row in rows:
        if row["noise"] in ("code_transposed_digit", "code_dropped_digit"):
            row["noisy_code_exists"] = row["query"] in codes_all

    order = list(dict.fromkeys(r["noise"] for r in rows))
    table = {}
    for n in order:
        sel = [r for r in rows if r["noise"] == n]
        cnt = Counter(r["outcome"] for r in sel)
        table[n] = {"class": sel[0]["class"], "n": len(sel),
                    **{o: cnt.get(o, 0) for o in OUTCOMES + ["error"]},
                    "routes": dict(Counter(r["route"] for r in sel))}
        if n in ("code_transposed_digit", "code_dropped_digit"):
            table[n]["noisy_code_is_real_code"] = sum(r["noisy_code_exists"] for r in sel)

    pct = lambda a, b: f"{100 * a / b:5.1f}%" if b else "  -  "
    print(f"{'noise':28s} {'class':13s} {'n':>4s} {'@1':>6s} {'@3':>6s} {'listed':>6s} {'refuse':>6s} "
          f"{'HARM':>6s} {'hedged':>6s} {'err':>4s}")
    for n, t in table.items():
        print(f"{n:28s} {t['class']:13s} {t['n']:4d} {pct(t['correct@1'], t['n'])} "
              f"{pct(t['correct@3'], t['n'])} {pct(t['correct_listed'], t['n'])} {pct(t['refused'], t['n'])} "
              f"{pct(t['HARMFUL'], t['n'])} {pct(t['wrong_hedged'], t['n'])} {t['error']:4d}"
              f"  routes={t['routes']}")

    by_class = {}
    for cls in ("clean", "recoverable", "degraded", "unrecoverable", "garbage"):
        sel = [r for r in rows if r["class"] == cls]
        cnt = Counter(r["outcome"] for r in sel)
        by_class[cls] = {"n": len(sel), **{o: cnt.get(o, 0) for o in OUTCOMES + ["error"]}}
    print("\nby class:", json.dumps(by_class, indent=1))

    harmful = [{k: r[k] for k in ("noise", "query", "expected", "got", "route")}
               for r in rows if r["outcome"] == "HARMFUL"]
    print(f"\nHARMFUL examples ({len(harmful)}):")
    for h in harmful[:25]:
        print(f"  {h['noise']:24s} {h['query']!r:28s} expected={h['expected']} got={h['got'][:4]}")
    hedged_garbage = [r for r in rows if r["class"] == "garbage" and r["outcome"] != "refused"]
    print(f"\ngarbage not refused ({len(hedged_garbage)}):")
    for r in hedged_garbage:
        print(f"  {r['noise']:24s} {r['query']!r} -> {r['route']} {r['got'][:3]}")

    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump({"config": {"n_code_base": N_CODE, "n_symptom_base": N_SYMPTOM, "k": K},
               "table": table, "by_class": by_class, "harmful": harmful, "rows": rows},
              open(f"{OUT_DIR}/results.json", "w"), indent=1, ensure_ascii=False)
    print(f"\nwrote {OUT_DIR}/results.json ({len(rows)} queries)")


if __name__ == "__main__":
    main()
