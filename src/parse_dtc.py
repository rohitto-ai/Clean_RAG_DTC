"""
Phase 1 — Extraction & structuring for the 3.3L DTC Troubleshooting Manual.

Produces ONE RECORD PER DTC. The troubleshooting steps are a branching decision
tree ("if lose, go to Step 13"), so they must stay together in a single record.

The critical routine here is `step_rows()`. Flat text extraction cannot be trusted
for the Sr.No / Steps / Specifications table: an inline cross-reference such as
"...fix is properly & go to Step 13" contains the literal token "Step 13" sitting
in the middle of the Steps column, and any line/text-based parser reads it as the
start of a new row. The Sr.No column is identified GEOMETRICALLY instead - a row
only begins when a word lands in the Sr.No x-band (left of the first vertical rule).

RAM discipline: the PDF is streamed one page at a time and each page's cache is
released immediately after use. No run ever holds all 545 pages.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field, asdict

import pdfplumber

PDF_PATH = "3.3L DTC Manual.pdf"
BODY_START_PAGE = 8          # pages 1-7 are the Table of Contents

# --- boilerplate repeated on all 545 pages -----------------------------------
BOILERPLATE = [
    re.compile(r"^3\.3L_NGE_BSVI\s*&\s*ECU\s*MD1CS018"),
    re.compile(r"^DTC Troubleshooting Data"),
    re.compile(r"^Ver\s*:\s*[\d.]+"),
    re.compile(r"^Date:\s*\d{2}/\d{2}/\d{4}"),
    re.compile(r"^Author:\s*ERC"),
    re.compile(r"^Page\s*\d*\s*(of)?\s*\d*$"),
    # The footer "Page N of 545" often wraps, orphaning a bare "545" on its own
    # line. Match ONLY that token - a generic ^\d+$ rule would also delete the
    # wrapped continuation of a Sr.No cell (a lone "10" under "Step").
    re.compile(r"^545$"),
    re.compile(r"^Copyright by TATA MOTORS"),
    re.compile(r"^This document must not be used"),
]

# Families: P (powertrain) and U (network/CAN). The manual carries 3 U-codes
# (U0102-00, U011A-00, U011A-89); matching only P silently folds them into the
# preceding record. B/C are included defensively.
DTC_HEADER = re.compile(r"^([PUBC][0-9A-F]{4})-([0-9A-F]{2})\s*:\s*(.+)$", re.I)
SR_NO = re.compile(r"^Step\s*\.?\s*(\d+)\s*$", re.I)
# "go to Step 9 & 11" / "go to Step 8 & 10" branch to BOTH targets, so the
# trailing "& N" list is captured too, not just the first number.
GOTO = re.compile(
    r"go\s*to\s*step\s*(?:no\.?\s*)?(\d+(?:\s*(?:&|and|,)\s*\d+)*)", re.I)

SECTIONS = {
    "overview":            re.compile(r"^Overview\s*:", re.I),
    "checkpoints":         re.compile(r"^Checkpoints\s*:", re.I),
    "steps":               re.compile(r"^Trouble\s*Shooting\s*Steps\s*:", re.I),
    "circuit_schematic":   re.compile(r"^Circuit\s*Schematic\s*Diagram\s*:", re.I),
    "circuit_description": re.compile(r"^Circuit\s*Description\s*:", re.I),
    "location_image":      re.compile(r"^Location\s*&?\s*Component\s*Image\s*:", re.I),
}

NUMBERED = re.compile(r"^(\d+)\s*[.)]\s*(.*)$")

# system tagging drives component/system queries (Phase 5 metadata filter)
BRANCH_CATALOGUE = {}   # signature -> {count, example, example_dtc, ...}

SYSTEM_RULES = [
    # Ordered most-specific-first; the first match wins. Hardware/subsystem rules
    # precede the broad level-2 monitoring rule, so "plausibility check of the
    # exhaust-gas temperature sensor" tags as exhaust, not as monitoring.
    ("scr_def",          r"reductant|\bdef\b|urea|adblue|\bscr\b|tank level|"
                         r"fluid property|concentration stuck|dosing"),
    ("dpf_regen",        r"particulate filter|\bdpf\b|soot|ash load|regeneration|"
                         r"\bdoc\b|diesel oxidation"),
    ("exhaust_throttle", r"exhaust throttle|\betv\b"),
    ("egr",              r"\begr\b|exhaust\s*gas\s*recirc"),
    ("turbo_boost",      r"turbo|boost|charge\s*air|waste\s*gate|wastegate"),
    ("rail_pressure",    r"rail\s*pressure|fuel\s*rail"),
    ("injector",         r"injector"),
    ("fuel_supply",      r"metering unit|pressure relief valve|fuel pressure regulator|"
                         r"water in fuel|fuel filter|hose line|fuel\s*(pump|supply|"
                         r"metering|temperature)|\bmprop\b|fuel cut off|fuel system"),
    ("engine_position",  r"crankshaft|camshaft"),
    ("pedal_clutch_brake", r"pedal|clutch|brake|accelerator"),
    ("vehicle_speed",    r"vehicle speed"),
    ("coolant",          r"coolant|engine\s*temp"),
    ("intake_air",       r"intake\s*air|\biat\b|air\s*temp|maf|mass\s*air|air mass|"
                         r"governor deviation|ambient temperature"),
    ("can_network",      r"can bus|can internal|\bcan\b"),
    ("o2_exhaust",       r"oxygen|lambda|\bo2\b|exhaust|\bnox\b"),
    ("level2_monitoring", r"energizing time|level 1|level 2|torque monitoring|"
                          r"engine speed|injection cut off|\bqwc\b|\bpoi\d|"
                          r"operating mode|remote app|post.build|plausibility|"
                          r"monitoring"),
    ("electrical",       r"battery|voltage|ground|short\s*circuit|open\s*circuit|relay"),
    ("sensor_generic",   r"sensor"),
    ("ecu_internal",     r"\becu\b|\bems\b|fccu|internal|checksum|watchdog"),
]


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def group_lines(words, tol=3.0):
    """Group words into visual lines by their `top` coordinate."""
    lines, cur, cur_top = [], [], None
    for w in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        if cur_top is None or abs(w["top"] - cur_top) <= tol:
            cur.append(w)
            cur_top = w["top"] if cur_top is None else cur_top
        else:
            lines.append(cur)
            cur, cur_top = [w], w["top"]
    if cur:
        lines.append(cur)
    return lines


def line_text(ws):
    return " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])).strip()


def is_boilerplate(text):
    t = text.strip()
    if not t:
        return True
    return any(p.match(t) for p in BOILERPLATE)


def column_bounds(page, y0, y1, cluster_tol=8.0, min_support=2, labels=None):
    """
    Column x-boundaries for the table occupying [y0, y1].

    The manual draws its tables as one filled rectangle PER CELL, so a single
    logical column boundary shows up as a tight cluster of 3-4 vertical edges
    (the left cell's right border, its inner padding edge, the right cell's
    padding edge, its left border). Clustering tightly would invent phantom
    columns, so nearby edges are merged with a wider tolerance and a boundary is
    kept only when several edges support it. `min_support` is deliberately low:
    a steps table continuing onto a new page can have a SINGLE row, and each
    boundary then draws only ~2 edges. The wide cluster tolerance is what
    suppresses phantom columns, not the support count.
    """
    xs = []
    for e in list(page.edges) + list(page.lines):
        if abs(e["x1"] - e["x0"]) > 1.0:              # not vertical
            continue
        top, bot = min(e["top"], e["bottom"]), max(e["top"], e["bottom"])
        if bot < y0 + 2 or top > y1 - 2:              # no overlap with the band
            continue
        if (bot - top) < 8:                            # too short to be a column rule
            continue
        xs.append((e["x0"] + e["x1"]) / 2.0)

    xs.sort()
    clusters = []
    for x in xs:
        if clusters and x - clusters[-1][0] <= cluster_tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    cols = [(sum(c) / len(c), len(c)) for c in clusters if len(c) >= min_support]
    if len(cols) < 3:                                  # need >= 2 outer + 1 interior
        return []
    interior = cols[1:-1]
    if labels and len(interior) != len(labels) - 1:
        # Header-anchored guard (Phase 9.1b). Each interior boundary must fall in
        # the gap between two adjacent header labels ("Sr." | "Steps" |
        # "Specifications"); when a gap holds several candidates, the one with
        # the most edge support wins. Surplus boundaries push step words into the
        # Specifications column, which is how p.13/86/211 were garbled.
        picked = []
        for left, right in zip(labels, labels[1:]):
            cand = [c for c in interior if left < c[0] < right]
            if not cand:
                return [c for c, _ in interior]        # cannot anchor: leave as is
            picked.append(max(cand, key=lambda c: (c[1], -c[0]))[0])
        return picked
    return [c for c, _ in interior]


def header_labels(page, y0):
    """x0 of the "Sr." / "Steps" / "Specification(s)" header labels just below
    the steps marker, or None when the header row is not on this page."""
    found = {}
    for w in page.extract_words():
        if not (y0 - 1 <= w["top"] <= y0 + 40):
            continue
        t = w["text"].rstrip(":")
        if t == "Sr." and "sr" not in found:
            found["sr"] = w["x0"]
        elif t == "Steps" and "steps" not in found:
            found["steps"] = w["x0"]
        elif t.startswith("Specification") and "spec" not in found:
            found["spec"] = w["x0"]
    if len(found) != 3 or not found["sr"] < found["steps"] < found["spec"]:
        return None
    return [found["sr"], found["steps"], found["spec"]]


def assign_columns(ws, bounds):
    """Split a line's words into columns using the x-boundaries."""
    cols = [[] for _ in range(len(bounds) + 1)]
    for w in ws:
        idx = 0
        for i, b in enumerate(bounds):
            if w["x0"] >= b - 1.0:
                idx = i + 1
        cols[idx].append(w)
    return [line_text(c) for c in cols]


# ---------------------------------------------------------------------------
# the critical routine: coordinate-based step-table repair
# ---------------------------------------------------------------------------
def step_rows(page, y0, y1, bounds):
    """
    Rebuild Sr.No <-> Steps <-> Specifications from word coordinates.

    A new row starts ONLY when a word lands in the Sr.No column (column 0).
    Inline references like "go to Step 13" sit inside the Steps column, so they
    are appended to the current row's text instead of spawning a phantom row -
    which is exactly what flat-text parsing gets wrong.
    """
    if not bounds:
        return []
    # NB: boilerplate is a LINE-level concept - never filter individual words here.
    # The footer rule `^\d+$` would otherwise eat the bare numeral in "Step 1".
    words = [w for w in page.extract_words() if y0 - 1 <= w["top"] <= y1 + 1]
    # Build per-line column splits first, so a Sr.No cell that WRAPS across two
    # lines can be stitched before rows are assembled. In a narrow Sr.No column
    # "Step 10" can render as "Step" on one line and "10" on the next (seen on
    # p.37, p.40, p.43, p.203); without this the final row is invisible and its
    # text is swallowed by the previous step.
    split = []
    for ln in group_lines(words):
        if is_boilerplate(line_text(ln)):
            continue
        split.append(assign_columns(ln, bounds))

    merged, skip = [], False
    for i, cols in enumerate(split):
        if skip:
            skip = False
            continue
        nxt = split[i + 1] if i + 1 < len(split) else None
        # A bare integer alone in the Sr.No column can only be the tail of a
        # wrapped "Step NN" cell - a real row always carries "Step" and its
        # number together. The number usually shares a line with the SECOND line
        # of that row's step text, so that text is folded in as a continuation.
        if (re.fullmatch(r"Step\s*\.?", cols[0].strip(), re.I) and nxt
                and re.fullmatch(r"\d+", nxt[0].strip())):
            cols = list(cols)
            cols[0] = f"Step {nxt[0].strip()}"
            for c in range(1, min(len(cols), len(nxt))):
                if nxt[c].strip():
                    cols[c] = (cols[c] + " " + nxt[c]).strip()
            skip = True
        merged.append(cols)

    rows = []
    for cols in merged:
        sr = cols[0].strip()
        if SR_NO.match(sr) or re.match(r"^Sr\.?\s*No", sr, re.I):
            rows.append([sr, cols[1] if len(cols) > 1 else "",
                         cols[2] if len(cols) > 2 else ""])
        elif rows:                                   # wrapped continuation line
            if len(cols) > 1 and cols[1]:
                rows[-1][1] = (rows[-1][1] + " " + cols[1]).strip()
            if len(cols) > 2 and cols[2]:
                rows[-1][2] = (rows[-1][2] + " " + cols[2]).strip()
        elif sr:                                     # stray col-0 text, keep it
            rows.append([sr, cols[1] if len(cols) > 1 else "",
                         cols[2] if len(cols) > 2 else ""])
    return [r for r in rows if not re.match(r"^Sr\.?\s*No", r[0], re.I)]


# --- branching-phrase instrumentation ---------------------------------------
# Phase 6 will need to model branch POLARITY (which target is the pass case and
# which the fail case). Rather than guess the schema from one example, the full
# parse catalogues every distinct branching phrase shape with counts + examples,
# so the model can be designed from corpus evidence. Raw step text is never
# altered - this only derives a signature alongside it.
BRANCH_MARKERS = re.compile(
    r"(go\s*to\s*step\s*(?:no\.?\s*)?\d+"
    r"|if\s+not\b|if\s+yes\b|if\s+no\b|if\s+ok\b|if\s+true\b"
    r"|\bif\b|\bthen\b|\belse\b|\botherwise\b|\brepeat\b)", re.I)


def branch_signature(text):
    """
    Collapse a step into a structural skeleton, e.g.
      "If continuity is OK in Step 9 then go to Step 12 else go to Step 11"
        -> "IF X THEN GOTO ELSE GOTO"
    Returns None when the step contains no branching language at all.
    """
    hits = list(BRANCH_MARKERS.finditer(text))
    if not hits:
        return None
    parts, prev_end = [], 0
    for m in hits:
        gap = text[prev_end:m.start()].strip()
        if len(gap) > 2:
            parts.append("X")
        tok = re.sub(r"\s+", " ", m.group(0).strip().lower())
        if tok.startswith("go to"):
            tok = "GOTO"
        else:
            tok = tok.upper().replace(" ", "_")
        parts.append(tok)
        prev_end = m.end()
    if len(text[prev_end:].strip()) > 2:
        parts.append("X")
    return " ".join(parts)


def parse_goto(text):
    """Extract branch targets from 'go to Step N' / 'go to Step No. N'."""
    out = set()
    for grp in GOTO.findall(text):
        out.update(int(n) for n in re.findall(r"\d+", grp))
    return sorted(out)


# ---------------------------------------------------------------------------
# per-page extraction (streamed, one page resident at a time)
# ---------------------------------------------------------------------------
@dataclass
class PageData:
    page_no: int
    header: tuple | None          # (code, suffix, description, top)
    lines: list                   # [(top, text)] boilerplate-stripped
    markers: dict                 # section name -> top
    steps: list                   # [[sr, steps, spec]] with tops
    images: list                  # [{bbox, page}]


HDR_BAND, FTR_BAND = 72.0, 712.0   # repeated page header / footer bands


def extract_page(page, page_no):
    raw_lines = group_lines(page.extract_words())

    lines, markers, header = [], {}, None
    for ln in raw_lines:
        t = line_text(ln)
        if is_boilerplate(t):
            continue
        top = min(w["top"] for w in ln)
        lines.append((top, t))
        for name, pat in SECTIONS.items():
            if pat.match(t) and name not in markers:
                markers[name] = top
        m = DTC_HEADER.match(t)
        if m and header is None:
            header = (m.group(1).upper(), m.group(2).upper(), m.group(3).strip(), top)

    # --- steps table band: from the "Trouble Shooting Steps:" marker (or the top
    #     of the page, for a table continuing from the previous page) down to the
    #     next section marker.
    page_bottom = max((t for t, _ in lines), default=page.height) + 30
    if "steps" in markers:
        sy0 = markers["steps"]
    else:
        # Continuation page: the table resumes just below the repeated header.
        # Starting any higher pulls the header table's own rules into the column
        # clustering and destroys the boundaries.
        sy0 = HDR_BAND + 2.0
    later = [t for n, t in markers.items() if n != "steps" and t > sy0 + 2]
    sy1 = min(later) - 2 if later else page_bottom
    # Never let the band run into the repeated footer (Phase 9.1b): the footer box
    # draws its own vertical rules (x~182, x~515) which otherwise cluster into
    # phantom column boundaries. Bands past 712 occurred on p.12/13/86/137/140/211/360.
    sy1 = min(sy1, FTR_BAND)

    labels = header_labels(page, sy0) if "steps" in markers else None
    bounds = column_bounds(page, sy0, sy1, labels=labels)
    steps = step_rows(page, sy0, sy1, bounds) if bounds else []

    # The TATA logo sits in the repeated header band on all 545 pages - it is
    # boilerplate imagery, not a schematic, so drop anything in the header/footer.
    images = [{"page": page_no, "bbox": [round(v, 1) for v in
              (im["x0"], im["top"], im["x1"], im["bottom"])]}
              for im in page.images
              if im["bottom"] > HDR_BAND and im["top"] < FTR_BAND]

    return PageData(page_no, header, lines, markers, steps, images)


# ---------------------------------------------------------------------------
# block assembly + section parsing
# ---------------------------------------------------------------------------
@dataclass
class Block:
    code: str
    suffix: str
    description: str
    page: int
    occurrence: int = 1
    pages: list = field(default_factory=list)   # PageData slices belonging to this DTC
    _split_top: float | None = None


def overview_from_page(page, y0, y1):
    """Overview is a single-row 3-column ruled table: Code | Cause | Effect."""
    bounds = column_bounds(page, y0, y1)
    if not bounds:
        return None
    words = [w for w in page.extract_words() if y0 - 1 <= w["top"] <= y1 + 1]
    cells = [[] for _ in range(len(bounds) + 1)]
    for ln in group_lines(words):
        if is_boilerplate(line_text(ln)):
            continue
        for i, c in enumerate(assign_columns(ln, bounds)):
            if c.strip():
                cells[i].append(c.strip())
    return cells


def tag_system(description):
    d = description.lower()
    for name, pat in SYSTEM_RULES:
        if re.search(pat, d):
            return name
    return "other"


def build_record(block, pdf):
    """Assemble one DTC record from its (possibly multi-page) block."""
    code_full = f"{block.code}-{block.suffix}"
    rec = {
        "code_full": code_full, "dtc_code": block.code, "suffix": block.suffix,
        "description": block.description, "system": tag_system(block.description),
        "page": block.page, "occurrence": block.occurrence,
        "pages_spanned": [p.page_no for p in block.pages],
        "fault_code": None, "MIL": None, "CEL": None, "immo_lamp": None,
        "ic_message": None, "cause": [], "effect": None, "checkpoints": [],
        "steps": [], "specifications": [], "circuit_description": None,
        "pin_map": [], "image_refs": [],
    }

    # --- Overview (section 2) -------------------------------------------------
    for pd in block.pages:
        if "overview" in pd.markers:
            y0 = pd.markers["overview"]
            later = [t for n, t in pd.markers.items() if t > y0 + 2]
            y1 = min(later) - 2 if later else y0 + 200
            pg = pdf.pages[pd.page_no - 1]
            cells = overview_from_page(pg, y0, y1)
            pg.flush_cache()
            if cells:
                code_lines = [c for c in cells[0] if not re.match(r"^Code$", c, re.I)]
                for c in code_lines:
                    if m := re.match(r"Fault\s*Code\s*:\s*(.+)", c, re.I):
                        rec["fault_code"] = m.group(1).strip()
                    elif m := re.match(r"MIL\s*[-–:]\s*(.+)", c, re.I):
                        rec["MIL"] = m.group(1).strip()
                    elif m := re.match(r"CEL\s*[-–:]\s*(.+)", c, re.I):
                        rec["CEL"] = m.group(1).strip()
                    elif m := re.match(r"Immo\s*Lamp\s*[-–:]\s*(.+)", c, re.I):
                        rec["immo_lamp"] = m.group(1).strip()
                    elif m := re.match(r"Message on IC\s*[-–:]\s*(.+)", c, re.I):
                        rec["ic_message"] = m.group(1).strip()
                if len(cells) > 1:
                    for c in cells[1]:
                        if re.match(r"^Cause$", c, re.I):
                            continue
                        if m := NUMBERED.match(c):
                            rec["cause"].append(m.group(2).strip())
                        elif rec["cause"]:
                            rec["cause"][-1] += " " + c
                if len(cells) > 2:
                    eff = [c for c in cells[2]
                           if not re.match(r"^Effect( on Vehicle)?$", c, re.I)]
                    rec["effect"] = " ".join(eff).strip() or None
            break

    # --- Checkpoints (section 3) ---------------------------------------------
    for pd in block.pages:
        if "checkpoints" in pd.markers:
            y0 = pd.markers["checkpoints"]
            later = [t for n, t in pd.markers.items() if t > y0 + 2]
            y1 = min(later) if later else 10_000
            for top, t in pd.lines:
                if not (y0 < top < y1):
                    continue
                if m := NUMBERED.match(t):
                    rec["checkpoints"].append(m.group(2).strip())
                elif rec["checkpoints"]:
                    rec["checkpoints"][-1] += " " + t
            break

    # --- Trouble Shooting Steps (section 4) ----------------------------------
    for pd in block.pages:
        for sr, txt, spec in pd.steps:
            m = SR_NO.match(sr)
            if not m:
                continue
            txt = re.sub(r"\s+", " ", txt).strip()
            sig = branch_signature(txt)
            rec["steps"].append({"n": int(m.group(1)), "text": txt,
                                 "goto": parse_goto(txt), "branch_sig": sig})
            if sig is not None:
                slot = BRANCH_CATALOGUE.setdefault(
                    sig, {"count": 0, "example": None, "example_dtc": None,
                          "with_goto": 0, "n_targets": {}})
                slot["count"] += 1
                g = parse_goto(txt)
                if g:
                    slot["with_goto"] += 1
                slot["n_targets"][str(len(g))] = slot["n_targets"].get(str(len(g)), 0) + 1
                if slot["example"] is None:
                    slot["example"] = txt
                    slot["example_dtc"] = f"{code_full} step {m.group(1)}"
            if spec.strip():
                rec["specifications"].append(
                    {"n": int(m.group(1)), "spec": re.sub(r"\s+", " ", spec).strip()})

    # --- Circuit Description (section 6) -------------------------------------
    for pd in block.pages:
        if "circuit_description" in pd.markers:
            y0 = pd.markers["circuit_description"]
            later = [t for n, t in pd.markers.items() if t > y0 + 2]
            y1 = min(later) if later else 10_000
            body = [t for top, t in pd.lines
                    if y0 < top < y1 and not SECTIONS["circuit_description"].match(t)]
            rec["circuit_description"] = re.sub(r"\s+", " ", " ".join(body)).strip() or None
            break

    # --- Images (sections 5 and 7) -------------------------------------------
    # Section context is STICKY across page breaks: a "Location & Component Image:"
    # heading at the foot of one page routinely owns the images at the top of the
    # next, so the last heading seen carries forward until another one overrides it.
    current = None
    for pd in block.pages:
        events = [(t, n) for n, t in pd.markers.items()
                  if n in ("circuit_schematic", "location_image")]
        events += [(im["bbox"][1], im) for im in pd.images]
        for _, item in sorted(events, key=lambda e: e[0]):
            if isinstance(item, str):
                current = item
            else:
                kind = {"circuit_schematic": "circuit_schematic",
                        "location_image": "location_component"}.get(current, "other")
                rec["image_refs"].append({**item, "kind": kind})

    return rec


def parse(pdf_path=PDF_PATH, first=BODY_START_PAGE, last=None, limit_dtcs=None):
    blocks, seen = [], {}
    with pdfplumber.open(pdf_path) as pdf:
        last = last or len(pdf.pages)
        cur = None
        for pno in range(first, last + 1):
            page = pdf.pages[pno - 1]
            pd = extract_page(page, pno)

            if pd.header:
                code, suffix, desc, htop = pd.header
                # content above the header still belongs to the previous DTC
                if cur is not None:
                    tail = PageData(pno, None,
                                    [(t, s) for t, s in pd.lines if t < htop],
                                    {n: t for n, t in pd.markers.items() if t < htop},
                                    [], [im for im in pd.images if im["bbox"][1] < htop])
                    if tail.lines or tail.images:
                        cur.pages.append(tail)
                key = f"{code}-{suffix}"
                seen[key] = seen.get(key, 0) + 1
                cur = Block(code, suffix, desc, pno, seen[key])
                blocks.append(cur)
                pd = PageData(pno, pd.header,
                              [(t, s) for t, s in pd.lines if t >= htop],
                              {n: t for n, t in pd.markers.items() if t >= htop},
                              pd.steps,
                              [im for im in pd.images if im["bbox"][1] >= htop])

            if cur is not None:
                cur.pages.append(pd)

            page.flush_cache()
            page.get_textmap.cache_clear()

            if limit_dtcs and len(blocks) > limit_dtcs:
                break

        if limit_dtcs:
            blocks = blocks[:limit_dtcs]
        records = [build_record(b, pdf) for b in blocks]
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", type=int, default=BODY_START_PAGE)
    ap.add_argument("--last", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None, help="stop after N DTCs (POC)")
    ap.add_argument("--out", default="data/dtc_raw.jsonl")
    ap.add_argument("--patterns", default="data/branch_patterns.json")
    args = ap.parse_args()

    recs = parse(first=args.first, last=args.last, limit_dtcs=args.limit)
    with open(args.out, "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(args.patterns, "w") as f:
        json.dump({"total_signatures": len(BRANCH_CATALOGUE),
                   "patterns": dict(sorted(BRANCH_CATALOGUE.items(),
                                           key=lambda kv: -kv[1]["count"]))},
                  f, indent=2, ensure_ascii=False)
    print(f"wrote {len(recs)} records -> {args.out}")
    print(f"wrote {len(BRANCH_CATALOGUE)} branching patterns -> {args.patterns}")
    for r in recs:
        print(f"  {r['code_full']:12s} p{r['page']:<4d} steps={len(r['steps']):3d} "
              f"cause={len(r['cause'])} chk={len(r['checkpoints'])} "
              f"sys={r['system']}")


if __name__ == "__main__":
    main()
