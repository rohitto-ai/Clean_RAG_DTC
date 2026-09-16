"""
Phase 3 — Canonical DTC record schema.

Normalises data/dtc_enriched.jsonl into one typed record per DTC and emits both
data/dtc_records.jsonl and the JSON Schema they are validated against.

POLARITY DESIGN (the governing decision): model branch polarity CONSERVATIVELY and
NEVER fabricate a route. Where the manual states a route explicitly, it is recorded
with confidence "high". Where the route is implicit, ambiguous, or the document is
self-inconsistent, `on_true`/`on_false` are left null and the step is marked "low" -
a null means "fall through to n+1", which is the document's own default, not a guess.

`goto[]` is copied BYTE-IDENTICALLY from the Phase 1 parse. This module never edits
an edge; out-of-range targets stay verbatim and are clamped later, in Phase 6.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

SCHEMA_PATH = "data/dtc_record.schema.json"

# Positional scan of jump phrases, so "then GOTO a else GOTO b" can be split on
# which side of the `else` each target falls.
GOTO_ITER = re.compile(
    r"go\s*to\s*step\s*(?:no\.?\s*)?(\d+(?:\s*(?:&|and|,)\s*\d+)*)", re.I)
ELSE_RE = re.compile(r"\b(else|otherwise)\b", re.I)

# The condition clause, captured VERBATIM from the step text.
CONDITION_RE = re.compile(
    r"(if\s+(?:not|yes|no|ok|true)\b|\bif\b)(.*?)"
    r"(?=\bthen\b|\bgo\s*to\s*step\b|\belse\b|\botherwise\b|$)", re.I)

TERMINAL_RE = re.compile(
    r"^\s*(clear\s+and\s+)?check\s*(the\s*|and\s+clear\s+the\s*)?dtc\s*\.?\s*$", re.I)
CHECK_VERB_RE = re.compile(r"^\s*(check|verify|measure|inspect|ensure|test)\b", re.I)


def extract_condition(text):
    """The IF / 'if yes' clause, verbatim. None when the step states no condition."""
    m = CONDITION_RE.search(text)
    if not m:
        return None
    cond = (m.group(1) + m.group(2)).strip()
    cond = re.sub(r"[\s,;&]+$", "", cond)
    return cond or None


def jump_positions(text):
    """[(char_offset, [targets...])] for each 'go to Step N' phrase, in order."""
    out = []
    for m in GOTO_ITER.finditer(text):
        out.append((m.start(), [int(n) for n in re.findall(r"\d+", m.group(1))]))
    return out


def derive_routes(text, goto, valid_steps):
    """
    Return (on_true, on_false, confidence).

    Never invents a target. A side with multiple simultaneous targets
    ("go to Step 9 & 11" means do both) is NOT a route, so it stays null.
    """
    jumps = jump_positions(text)
    has_condition = extract_condition(text) is not None

    if not jumps:
        # "IF X" with no jump - the else is an implicit fall-through to n+1.
        return None, None, ("low" if has_condition else "high")

    m_else = ELSE_RE.search(text)
    if m_else:
        before = [t for pos, t in jumps if pos < m_else.start()]
        after = [t for pos, t in jumps if pos > m_else.start()]
        if before and after:
            t_side, f_side = before[-1], after[0]
            on_true = t_side[0] if len(t_side) == 1 else None
            on_false = f_side[0] if len(f_side) == 1 else None
            conf = "high" if (on_true is not None and on_false is not None) else "low"
            if on_true is not None and on_true not in valid_steps:
                conf = "low"
            if on_false is not None and on_false not in valid_steps:
                conf = "low"
            return on_true, on_false, conf

    # Single jump phrase: the target is the taken branch; the untaken branch falls
    # through to n+1, which the document leaves implicit.
    targets = jumps[0][1]
    if len(jumps) > 1 or len(targets) != 1:
        # several unrelated jumps, or one phrase naming several simultaneous
        # targets - not expressible as a two-way route.
        return None, None, "low"

    tgt = targets[0]
    # Out-of-range target: kept verbatim (it is what the manual says), but the
    # route is not trustworthy. Phase 6 clamps it to the terminal step.
    conf = "high" if tgt in valid_steps else "low"
    return tgt, None, conf


def classify(text, goto, is_last):
    if TERMINAL_RE.match(text) or (is_last and TERMINAL_RE.match(text)):
        return "terminal"
    if goto:
        return "branch"
    if extract_condition(text) is not None or CHECK_VERB_RE.match(text):
        return "check"
    return "action"


def build_steps(src_steps):
    valid = {s["n"] for s in src_steps}
    out = []
    for i, s in enumerate(src_steps):
        text = s["text"]
        goto = list(s["goto"])                 # verbatim, never modified
        is_last = (i == len(src_steps) - 1)
        kind = classify(text, goto, is_last)
        if kind == "terminal":
            on_true = on_false = None
            conf = "high"
        else:
            on_true, on_false, conf = derive_routes(text, goto, valid)
        out.append({
            "n": s["n"],
            "text": text,
            "kind": kind,
            "condition": extract_condition(text),
            "on_true": on_true,
            "on_false": on_false,
            "goto": goto,
            "polarity_confidence": conf,
        })
    return out


def build_record(r):
    return {
        "dtc_code": r["dtc_code"],
        "suffix": r["suffix"],
        "code_full": r["code_full"],
        "description": r["description"],
        "system": r["system"],
        "template_variant": r["template_variant"],
        "fault_code": r.get("fault_code"),
        "MIL": r.get("MIL"),
        "CEL": r.get("CEL"),
        "immo_lamp": r.get("immo_lamp"),
        "ic_message": r.get("ic_message"),
        "effect": r.get("effect"),
        "cause": list(r.get("cause") or []),
        "checkpoints": list(r.get("checkpoints") or []),
        "steps": build_steps(r["steps"]),
        "specifications": list(r.get("specifications") or []),
        "circuit_description": r.get("circuit_description"),
        "pin_map": [{"pin": p["pin"], "net": p.get("net"),
                     "confidence": p["confidence"]} for p in r.get("pin_map") or []],
        "image_refs": list(r.get("image_refs") or []),
        "page": r["page"],
        "occurrence": r["occurrence"],
    }


NULLABLE_STR = {"type": ["string", "null"]}

RECORD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DTC record (3.3L_NGE_BSVI MD1CS018)",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "dtc_code", "suffix", "code_full", "description", "system",
        "template_variant", "fault_code", "MIL", "CEL", "immo_lamp", "ic_message",
        "effect", "cause", "checkpoints", "steps", "specifications",
        "circuit_description", "pin_map", "image_refs", "page", "occurrence",
    ],
    "properties": {
        "dtc_code": {"type": "string", "pattern": "^[PUBC][0-9A-F]{4}$"},
        "suffix": {"type": "string", "pattern": "^[0-9A-F]{2}$"},
        "code_full": {"type": "string", "pattern": "^[PUBC][0-9A-F]{4}-[0-9A-F]{2}$"},
        "description": {"type": "string", "minLength": 1},
        "system": {"type": "string", "minLength": 1},
        "template_variant": {"enum": ["full_7_section", "reduced_4_section", "partial"]},
        "fault_code": NULLABLE_STR,
        "MIL": NULLABLE_STR,
        "CEL": NULLABLE_STR,
        "immo_lamp": NULLABLE_STR,
        "ic_message": NULLABLE_STR,
        "effect": NULLABLE_STR,
        "cause": {"type": "array", "items": {"type": "string"}},
        "checkpoints": {"type": "array", "items": {"type": "string"}},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["n", "text", "kind", "condition", "on_true",
                             "on_false", "goto", "polarity_confidence"],
                "properties": {
                    "n": {"type": "integer", "minimum": 1},
                    "text": {"type": "string"},
                    "kind": {"enum": ["action", "check", "branch", "terminal"]},
                    "condition": NULLABLE_STR,
                    "on_true": {"type": ["integer", "null"], "minimum": 1},
                    "on_false": {"type": ["integer", "null"], "minimum": 1},
                    "goto": {"type": "array", "items": {"type": "integer", "minimum": 1}},
                    "polarity_confidence": {"enum": ["high", "low"]},
                },
            },
        },
        "specifications": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["n", "spec"],
                "properties": {"n": {"type": "integer"}, "spec": {"type": "string"}},
            },
        },
        "circuit_description": NULLABLE_STR,
        "pin_map": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["pin", "net", "confidence"],
                "properties": {
                    "pin": {"type": "string"},
                    "net": NULLABLE_STR,
                    "confidence": {"enum": ["high", "low"]},
                },
            },
        },
        "image_refs": {"type": "array", "items": {"type": "object"}},
        "page": {"type": "integer", "minimum": 1},
        "occurrence": {"type": "integer", "minimum": 1},
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/dtc_enriched.jsonl")
    ap.add_argument("--out", default="data/dtc_records.jsonl")
    args = ap.parse_args()

    src = [json.loads(l) for l in open(args.inp)]
    recs = [build_record(r) for r in src]

    with open(args.out, "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(SCHEMA_PATH, "w") as f:
        json.dump(RECORD_SCHEMA, f, indent=2)

    kinds = Counter(s["kind"] for r in recs for s in r["steps"])
    conf = Counter(s["polarity_confidence"] for r in recs for s in r["steps"])
    routed = sum(1 for r in recs for s in r["steps"] if s["on_true"] is not None)
    two_way = sum(1 for r in recs for s in r["steps"] if s["on_false"] is not None)
    print(f"wrote {len(recs)} records -> {args.out}")
    print(f"wrote schema -> {SCHEMA_PATH}")
    print(f"  kind: {dict(kinds)}")
    print(f"  polarity_confidence: {dict(conf)}")
    print(f"  steps with on_true set: {routed}   with on_false set: {two_way}")


if __name__ == "__main__":
    main()
