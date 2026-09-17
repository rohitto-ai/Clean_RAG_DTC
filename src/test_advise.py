"""
Phase 9.1 advise-mode tests. Kept separate from src/smoke_index.py so the main
suite's counts stay stable. DEV/TEST gold queries are not used.

    PYTHONPATH=src .venv/bin/python src/test_advise.py
"""
import sys

sys.path.insert(0, "src")

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    from cli import quiet_stderr
    with quiet_stderr():
        from retrieve import Retriever
        from advise import advise
        R = Retriever()

    def run(q):
        with quiet_stderr():
            return advise(q, R)

    FIELDS = {"code_full", "description", "system", "effect", "MIL", "cause", "checkpoints",
              "steps", "pins", "schematic_page", "page", "citation", "text"}

    for q, mode, first in [("P0192-00", "dtc_code", "P0192-00"),
                           ("my truck shows fault P0192-00, how do I fix it?", "dtc_code", "P0192-00"),
                           ("coolant gauge stuck at the bottom", "symptom", None),
                           ("cam sensor gives no signal", "symptom", "P0340-00")]:
        res = run(q)
        codes = [r["code_full"] for r in res["results"]]
        full = all(FIELDS <= set(r["fix_block"]) and r["fix_block"]["steps"]
                   and all(s["text"] for s in r["fix_block"]["steps"]) for r in res["results"])
        check(f"{q!r}: mode={mode}, 3 codes, full fix blocks",
              res["mode"] == mode and len(codes) == 3 and len(set(codes)) == 3 and full
              and (first is None or codes[0] == first),
              f"mode={res['mode']} codes={codes}")

    res = run("P0192-00")
    fb = res["results"][0]["fix_block"]
    s10 = next(s for s in fb["steps"] if s["n"] == 10)
    check("fix block keeps branch logic and page citation",
          s10["branch"] == "if yes -> Step 12; if no -> Step 11" and fb["page"] == 8
          and fb["schematic_page"] == 9 and fb["citation"] == "P0192-00, manual page 8"
          and "A71" in fb["pins"], f"step10={s10['branch']!r} page={fb['page']}")

    res = run("P0180-11")
    codes = [r["code_full"] for r in res["results"]]
    check("duplicated code returns both occurrences, then one related code",
          codes[:2] == ["P0180-11", "P0180-11"] and codes[2] != "P0180-11"
          and len({r["fix_block"]["page"] for r in res["results"][:2]}) == 2,
          f"codes={codes} pages={[r['fix_block']['page'] for r in res['results']]}")

    res = run("P0100")
    check("base code with 3 variants returns the 3 variants",
          sorted(r["code_full"] for r in res["results"]) == ["P0100-00", "P0100-9B", "P0100-9C"],
          f"{[r['code_full'] for r in res['results']]}")

    for q in ("what is the capital of France", "what is the warranty period on this engine"):
        res = run(q)
        check(f"out-of-scope {q!r} is refused, not given fix steps",
              res["mode"] == "refused" and res["results"] == [],
              f"reasons={res.get('refusal_reasons')}")

    a, b = run("cam sensor gives no signal"), run("cam sensor gives no signal")
    check("deterministic: identical output on repeat",
          [r["code_full"] for r in a["results"]] == [r["code_full"] for r in b["results"]]
          and a["results"][0]["fix_block"]["text"] == b["results"][0]["fix_block"]["text"])

    n = sum(results)
    print(f"\n==== ADVISE: {n}/{len(results)} passed ====")
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
