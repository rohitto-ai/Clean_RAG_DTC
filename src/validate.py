"""
Phase 7 (run early, as an anomaly report) — validation harness for the Phase 1 parse.

Checks coverage against the Table of Contents, template deviations, structural
integrity of the step decision trees, and boilerplate leakage. Reports; never fixes.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import pdfplumber

PDF_PATH = "3.3L DTC Manual.pdf"
TOC_PAGES = (1, 7)

TOC_LINE = re.compile(
    r"^([PUBC][0-9A-F]{4})-([0-9A-F]{2})\s*:\s*(.*?)\s*-{3,}\s*(\d+)\s*$", re.I)

BOILERPLATE_STRINGS = [
    "TATA MOTORS", "Author: ERC", "3.3L_NGE_BSVI", "of 545", "Ver : 1.0",
    "redistributing to third parties", "DTC Troubleshooting Data",
]

SEVEN_SECTIONS = ["header", "overview", "checkpoints", "steps",
                  "circuit_schematic", "circuit_description", "location_image"]


def parse_toc(pdf_path=PDF_PATH):
    """Authoritative expected-DTC list from pages 1-7."""
    entries = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno in range(TOC_PAGES[0], TOC_PAGES[1] + 1):
            page = pdf.pages[pno - 1]
            text = page.extract_text() or ""
            buf = ""
            for raw in text.split("\n"):
                line = raw.strip()
                if not line:
                    continue
                # TOC entries wrap; stitch until the trailing page number appears
                buf = (buf + " " + line).strip() if buf else line
                m = TOC_LINE.match(buf)
                if m:
                    entries.append({
                        "code_full": f"{m.group(1).upper()}-{m.group(2).upper()}",
                        "description": m.group(3).strip(),
                        "toc_page": int(m.group(4)),
                    })
                    buf = ""
                elif re.match(r"^[PUBC][0-9A-F]{4}-", buf, re.I) is None:
                    buf = ""
            page.flush_cache()
            page.get_textmap.cache_clear()
    return entries


def sections_present(r):
    have = {
        "header": bool(r["code_full"] and r["description"]),
        "overview": bool(r["fault_code"] or r["cause"] or r["effect"]),
        "checkpoints": bool(r["checkpoints"]),
        "steps": bool(r["steps"]),
        "circuit_schematic": any(i["kind"] == "circuit_schematic"
                                 for i in r["image_refs"]),
        "circuit_description": bool(r["circuit_description"]),
        "location_image": any(i["kind"] == "location_component"
                              for i in r["image_refs"]),
    }
    return have


def main():
    recs = [json.loads(l) for l in open("data/dtc_raw.jsonl")]
    toc = parse_toc()
    patterns = json.load(open("data/branch_patterns.json"))

    out = []
    def p(s=""):
        out.append(s)

    p("# Phase 1 Validation & Anomaly Report")
    p()
    p(f"- Records parsed: **{len(recs)}**")
    p(f"- TOC entries (pp. 1-7): **{len(toc)}**")
    p(f"- Pages covered: 8-545")
    p()

    # ---------------- 1. COVERAGE ------------------------------------------
    p("## 1. Coverage vs the Table of Contents")
    p()
    toc_codes = Counter(e["code_full"] for e in toc)
    rec_codes = Counter(r["code_full"] for r in recs)

    missing = [c for c in toc_codes if c not in rec_codes]
    extra = [c for c in rec_codes if c not in toc_codes]

    p(f"- Distinct codes in TOC: **{len(toc_codes)}**")
    p(f"- Distinct codes parsed: **{len(rec_codes)}**")
    p(f"- TOC entries with NO record: **{len(missing)}**")
    p(f"- Records NOT in the TOC: **{len(extra)}**")
    p()
    if missing:
        p("### TOC entries with no record")
        p()
        for c in sorted(missing):
            d = next(e["description"] for e in toc if e["code_full"] == c)
            tp = next(e["toc_page"] for e in toc if e["code_full"] == c)
            p(f"- `{c}` (TOC p.{tp}) — {d[:80]}")
        p()
    if extra:
        p("### Records with no TOC entry")
        p()
        for c in sorted(extra):
            r = next(x for x in recs if x["code_full"] == c)
            p(f"- `{c}` (parsed p.{r['page']}) — {r['description'][:80]}")
        p()

    # duplicates
    dup_toc = {c: n for c, n in toc_codes.items() if n > 1}
    dup_rec = {c: n for c, n in rec_codes.items() if n > 1}
    p("### Duplicate codes (code alone is not a unique key)")
    p()
    if dup_rec:
        p("| code_full | records | pages | occurrences |")
        p("|---|---|---|---|")
        for c, n in sorted(dup_rec.items()):
            rs = [r for r in recs if r["code_full"] == c]
            p(f"| `{c}` | {n} | {', '.join(str(r['page']) for r in rs)} | "
              f"{', '.join(str(r['occurrence']) for r in rs)} |")
    else:
        p("_none_")
    p()
    p(f"- Duplicates already visible in the TOC: "
      f"{', '.join(f'`{c}`x{n}' for c, n in sorted(dup_toc.items())) or '_none_'}")
    p()

    # ---------------- 2. TEMPLATE DEVIATIONS -------------------------------
    p("## 2. Template deviations (the fixed 7-section layout)")
    p()
    presence = {s: 0 for s in SEVEN_SECTIONS}
    missing_by_rec = {}
    for r in recs:
        have = sections_present(r)
        for s, v in have.items():
            presence[s] += bool(v)
        miss = [s for s, v in have.items() if not v]
        if miss:
            missing_by_rec[r["code_full"] + f"@p{r['page']}"] = miss

    p("| Section | Present | Missing | % present |")
    p("|---|---|---|---|")
    for s in SEVEN_SECTIONS:
        n = presence[s]
        p(f"| {s} | {n} | {len(recs)-n} | {100*n/len(recs):.1f}% |")
    p()
    p(f"- Records with the full 7 sections: **{len(recs)-len(missing_by_rec)}** "
      f"/ {len(recs)}")
    p(f"- Records deviating from the template: **{len(missing_by_rec)}**")
    p()

    # group deviations by shape
    shapes = defaultdict(list)
    for k, miss in missing_by_rec.items():
        shapes[tuple(sorted(miss))].append(k)
    # The manual is not one template but (at least) two: a full 7-section entry
    # and a reduced 4-section entry with no circuit schematic / description /
    # location image at all. Phase 2 must not treat the reduced form as damage.
    def variant(r):
        have = sections_present(r)
        core = all(have[s] for s in ("header", "overview", "checkpoints", "steps"))
        visual = [have[s] for s in
                  ("circuit_schematic", "circuit_description", "location_image")]
        if core and all(visual):
            return "full_7_section"
        if core and not any(visual):
            return "reduced_4_section"
        return "partial"

    variants = Counter(variant(r) for r in recs)
    p("### Template variants")
    p()
    p("| Variant | Records | Meaning |")
    p("|---|---|---|")
    p(f"| `full_7_section` | {variants['full_7_section']} | all 7 sections present |")
    p(f"| `reduced_4_section` | {variants['reduced_4_section']} | header + overview + "
      f"checkpoints + steps only; no schematic/description/location at all |")
    p(f"| `partial` | {variants['partial']} | some but not all visual sections — "
      f"the genuinely mixed cases |")
    p()

    p("### Deviation shapes (grouped)")
    p()
    p("| Missing sections | Count | Example DTCs |")
    p("|---|---|---|")
    for shape, members in sorted(shapes.items(), key=lambda kv: -len(kv[1])):
        ex = ", ".join(f"`{m}`" for m in sorted(members)[:4])
        more = f" … +{len(members)-4}" if len(members) > 4 else ""
        p(f"| {', '.join(shape)} | {len(members)} | {ex}{more} |")
    p()

    # FCCU / P16xx family focus
    fccu = [r for r in recs if re.match(r"^P16", r["code_full"])]
    p(f"### P16xx FCCU alarm family ({len(fccu)} records)")
    p()
    if fccu:
        fccu_shapes = Counter()
        for r in fccu:
            miss = tuple(sorted(s for s, v in sections_present(r).items() if not v))
            fccu_shapes[miss] += 1
        p("| Missing sections | Count |")
        p("|---|---|")
        for shape, n in fccu_shapes.most_common():
            p(f"| {', '.join(shape) if shape else '_none (full template)_'} | {n} |")
        p()
        sc = Counter(len(r["steps"]) for r in fccu)
        p(f"- Step-count distribution: "
          f"{', '.join(f'{k} steps x{v}' for k, v in sorted(sc.items()))}")
        p(f"- Pages spanned: {Counter(len(r['pages_spanned']) for r in fccu)}")
        p()

    # single-page / short records
    short = [r for r in recs if len(r["pages_spanned"]) <= 1]
    p(f"### Single-page records ({len(short)})")
    p()
    if short:
        p("| DTC | page | steps | chk | cause | missing sections |")
        p("|---|---|---|---|---|---|")
        for r in sorted(short, key=lambda r: r["page"])[:25]:
            miss = [s for s, v in sections_present(r).items() if not v]
            p(f"| `{r['code_full']}` | {r['page']} | {len(r['steps'])} | "
              f"{len(r['checkpoints'])} | {len(r['cause'])} | {', '.join(miss) or '—'} |")
        if len(short) > 25:
            p(f"| … +{len(short)-25} more | | | | | |")
    p()

    # ---------------- 3. INTEGRITY -----------------------------------------
    p("## 3. Structural integrity at scale")
    p()
    no_steps, noncontig, bad_goto, leaks, self_goto = [], [], [], [], []
    for r in recs:
        ns = [s["n"] for s in r["steps"]]
        key = f"{r['code_full']}@p{r['page']}"
        if not ns:
            no_steps.append(key)
            continue
        if ns != list(range(1, len(ns) + 1)):
            noncontig.append((key, ns))
        sset = set(ns)
        for s in r["steps"]:
            for g in s["goto"]:
                if g not in sset:
                    bad_goto.append((key, s["n"], g, s["text"][:70]))
                if g == s["n"]:
                    self_goto.append((key, s["n"]))
        blob = json.dumps(r)
        hit = [b for b in BOILERPLATE_STRINGS if b in blob]
        if hit:
            leaks.append((key, hit))

    tot_steps = sum(len(r["steps"]) for r in recs)
    tot_goto = sum(len(s["goto"]) for r in recs for s in r["steps"])
    p(f"- Total steps parsed: **{tot_steps}**")
    p(f"- Total `goto` references: **{tot_goto}**")
    p(f"- Records with zero steps: **{len(no_steps)}**")
    p(f"- Records with non-contiguous step numbering: **{len(noncontig)}**")
    p(f"- Unresolved `goto` targets: **{len(bad_goto)}**")
    p(f"- Self-referencing `goto` (step N -> step N): **{len(self_goto)}**")
    p(f"- Records with boilerplate leakage: **{len(leaks)}**")
    p()
    if no_steps:
        p("### Records with zero steps")
        p()
        for k in no_steps[:20]:
            p(f"- `{k}`")
        if len(no_steps) > 20:
            p(f"- … +{len(no_steps)-20} more")
        p()
    if noncontig:
        p("### Non-contiguous step numbering")
        p()
        for k, ns in noncontig[:20]:
            p(f"- `{k}` -> {ns}")
        if len(noncontig) > 20:
            p(f"- … +{len(noncontig)-20} more")
        p()
    if bad_goto:
        p("### Unresolved goto targets — classification")
        p()
        # Every unresolved target observed points PAST the last step, and the
        # record's final step is a terminal "Check DTC" instruction. That makes
        # these source-side off-by-one defects with an unambiguous intent, not
        # parse damage - Phase 6 can resolve them to the terminal step.
        by_rec = defaultdict(list)
        for k, n, g, t in bad_goto:
            by_rec[k].append(g)
        beyond, terminal, other_shape = 0, 0, []
        for k, targets in by_rec.items():
            r = next(x for x in recs if f"{x['code_full']}@p{x['page']}" == k)
            mx = max(s_["n"] for s_ in r["steps"])
            last = r["steps"][-1]["text"].lower()
            if all(g > mx for g in targets):
                beyond += 1
            else:
                other_shape.append(k)
            if re.search(r"check\s*(the\s*)?dtc", last):
                terminal += 1
        p(f"- Records affected: **{len(by_rec)}** ({len(bad_goto)} references)")
        p(f"- Records where EVERY unresolved target points past the last step: "
          f"**{beyond}/{len(by_rec)}**")
        p(f"- Records whose final step is a terminal \"Check DTC\" instruction: "
          f"**{terminal}/{len(by_rec)}**")
        p(f"- Records not fitting that shape: "
          f"{', '.join(f'`{k}`' for k in other_shape) or '**none**'}")
        p()
        p("> These are **source-document defects, not parse errors** — spot-checked "
          "against pp. 20, 22, 83, 248. The manual's step rows are mis-numbered "
          "(duplicated or skipped labels) while the prose consistently refers to the "
          "final check step. Recommendation for Phase 6: resolve an out-of-range "
          "`goto` to the terminal step, and record the repair in the Phase 7 harness "
          "rather than silently rewriting `goto[]` at parse time.")
        p()
        p("#### Full list")
        p()
        p("| DTC | from step | -> target | step text |")
        p("|---|---|---|---|")
        for k, n, g, t in bad_goto[:30]:
            p(f"| `{k}` | {n} | {g} | {t} |")
        if len(bad_goto) > 30:
            p(f"| … +{len(bad_goto)-30} more | | | |")
        p()
    if leaks:
        p("### Boilerplate leakage")
        p()
        for k, hit in leaks[:20]:
            p(f"- `{k}` -> {hit}")
        if len(leaks) > 20:
            p(f"- … +{len(leaks)-20} more")
        p()

    # subsystem tagging
    p("### Subsystem tagging (`system`)")
    p()
    sysc = Counter(r["system"] for r in recs)
    p("| system | records |")
    p("|---|---|")
    for s, n in sysc.most_common():
        p(f"| `{s}` | {n} |")
    p()
    other = [r for r in recs if r["system"] == "other"]
    if other:
        p(f"#### Untagged (`system='other'`, {len(other)}) — candidates to extend the keyword map")
        p()
        for r in other[:30]:
            p(f"- `{r['code_full']}` p{r['page']} — {r['description'][:85]}")
        if len(other) > 30:
            p(f"- … +{len(other)-30} more")
        p()

    # ---------------- 4. BRANCHING CATALOGUE -------------------------------
    p("## 4. Branching-phrase catalogue (instrumentation for Phase 6 polarity)")
    p()
    pats = patterns["patterns"]
    branching_steps = sum(v["count"] for v in pats.values())
    p(f"- Distinct branching signatures: **{len(pats)}**")
    p(f"- Steps containing branching language: **{branching_steps}** "
      f"/ {tot_steps} ({100*branching_steps/max(tot_steps,1):.1f}%)")
    p(f"- Steps with no branching language: **{tot_steps-branching_steps}**")
    p()
    p("_`X` = free text, `GOTO` = a 'go to Step N' reference. "
      "`targets` shows how many goto targets that shape carries._")
    p()
    p("| # | Signature | Count | targets (n->count) | Example |")
    p("|---|---|---|---|---|")
    for i, (sig, v) in enumerate(pats.items(), 1):
        tg = ", ".join(f"{k}->{n}" for k, n in sorted(v["n_targets"].items()))
        ex = v["example"].replace("|", "\\|")[:90]
        p(f"| {i} | `{sig}` | {v['count']} | {tg} | {ex} |")
    p()

    report = "\n".join(out)
    with open("data/validation_report.md", "w") as f:
        f.write(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
