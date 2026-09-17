"""
Phase 9.1b - garbled-step detector (table-parse column bleed).

A wrong column boundary in the Trouble Shooting Steps table pushes words of the
Steps column into the Specifications column. The step text is then truncated and
its remainder sits in `spec`. Two independent checks:

  content  (records, fast)  a step is flagged when
     S1  its spec starts with a lower-case word (a real spec is a value, "Pin ..",
         "Air gap ..", "Should be .." - never a sentence continuation), or
     S2  its spec contains branch language ("go to step"), which belongs to the
         step text, or
     S3  its spec has no digit and >= 2 sentence function words, or
     S4  its step text ends on a dangling word ("and", "the", "for", ...) while a
         spec is present - the sentence was cut at the column boundary.

  geometry (PDF, ~60 s)  a page is flagged when the steps table does not resolve
     to exactly 2 interior column boundaries, or the boundaries do not fall
     between the "Sr." | "Steps" | "Specifications" header labels.

    PYTHONPATH=src .venv/bin/python scripts/detect_step_bleed.py [--records FILE] [--geometry]
Exit status 1 when anything is flagged.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

FUNCTION_WORDS = {"the", "of", "to", "for", "and", "if", "is", "in", "then", "check",
                  "found", "from", "with", "or", "go", "step"}
DANGLING = {"the", "of", "to", "for", "and", "if", "is", "in", "then", "or", "a", "an",
            "&", "from", "with", "found", "check", "between"}
GOTO = re.compile(r"\bgo\s*to\b", re.I)


def spec_flags(text, spec):
    flags = []
    words = re.findall(r"[A-Za-z&]+", spec)
    if re.match(r"^[a-z]", spec):
        flags.append("S1_lowercase_start")
    if GOTO.search(spec):
        flags.append("S2_branch_language")
    if not re.search(r"\d", spec) and sum(w.lower() in FUNCTION_WORDS for w in words) >= 2:
        flags.append("S3_sentence_fragment")
    last = re.findall(r"[A-Za-z&]+|\S$", text.strip())
    if last and last[-1].lower() in DANGLING:
        flags.append("S4_truncated_text")
    return flags


def scan_records(path):
    hits = []
    for line in open(path):
        r = json.loads(line)
        text = {s["n"]: s["text"] for s in r["steps"]}
        for s in r.get("specifications") or []:
            f = spec_flags(text.get(s["n"], ""), s["spec"])
            if f:
                hits.append({"id": f"{r['code_full']}@p{r['page']}#{r['occurrence']}",
                             "step": s["n"], "flags": f, "spec": s["spec"],
                             "text": text.get(s["n"], "")})
    return hits


def scan_geometry():
    import pdfplumber
    import parse_dtc as P
    bad = []
    with pdfplumber.open(P.PDF_PATH) as pdf:
        for pno in range(P.BODY_START_PAGE, len(pdf.pages) + 1):
            pg = pdf.pages[pno - 1]
            pd = P.extract_page(pg, pno)
            if pd.steps and "steps" in pd.markers:
                sy0 = pd.markers["steps"]
                later = [t for n, t in pd.markers.items() if n != "steps" and t > sy0 + 2]
                sy1 = min(min(later) - 2 if later else 10_000, P.FTR_BAND)
                labels = P.header_labels(pg, sy0)
                b = P.column_bounds(pg, sy0, sy1, labels=labels)
                ok = len(b) == 2 and (labels is None or
                                      (labels[0] < b[0] < labels[1] < b[1] < labels[2]))
                if not ok:
                    bad.append({"page": pno, "bounds": [round(x, 1) for x in b],
                                "labels": labels and [round(x, 1) for x in labels]})
            pg.flush_cache()
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="data/dtc_records.jsonl")
    ap.add_argument("--geometry", action="store_true", help="also check page geometry (PDF)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    hits = scan_records(a.records)
    recs = sorted({h["id"] for h in hits})
    out = {"records_flagged": len(recs), "steps_flagged": len(hits), "records": recs, "steps": hits}
    if a.geometry:
        out["pages_flagged"] = scan_geometry()
    if a.json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        for h in hits:
            print(f"{h['id']} step {h['step']:>2} {','.join(h['flags'])}\n"
                  f"    text: {h['text']!r}\n    spec: {h['spec']!r}")
        print(f"\nflagged: {len(recs)} records, {len(hits)} steps -> {recs}")
        if a.geometry:
            print(f"geometry: {len(out['pages_flagged'])} pages flagged {out['pages_flagged']}")
    bad = hits or out.get("pages_flagged")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
