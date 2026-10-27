"""
Phase 10.6 step 2 — write the PRE-REGISTRATION for the independent evaluation.

    PYTHONPATH=src .venv/bin/python scripts/preregister_10_6.py

Run and COMMIT AND PUSH this BEFORE scripts/independent_eval.py is run even once.
It fixes the configurations, the metrics, the uncertainty method and the adoption
rule in advance, and records the sha256 of every input, so the result cannot be
re-interpreted after the fact.

NO RETRIEVAL IS RUN HERE.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

OUT = "data/experiments/10_6/preregistration.json"

INPUTS = [
    "data/gold_independent.json",
    "data/dtc_records.jsonl",
    "data/domain_lexicon.json",
    "data/domain_lexicon_v2.json",
    "data/gate_c4b.json",
    "data/intent_stoplist.json",
    "data/experiments/10_1/freeze.json",
    "data/experiments/10_1b/freeze.json",
    "index/bm25_corpus.json",
    "index_exp/minilm_v1/bm25_corpus.json",
    "index_exp/minilm_lexv2/bm25_corpus.json",
    "index_exp/minilm_lexv2_lamp/bm25_corpus.json",
    "src/retrieve.py",
    "src/lexicon.py",
    "src/gate.py",
    "src/answer.py",
]

CONFIGS = [
    {"key": "a", "name": "v1-phase7 (no lexicon, legacy gate)",
     "index_dir": "index_exp/minilm_v1", "lexicon": None, "expand": "none",
     "gate": "legacy", "rerank": None,
     "note": "The v1 RETRIEVAL CONFIGURATION rebuilt on today's records, not a "
             "byte-identical time capsule of the v1-phase7 tag: the 9.1b parser fix "
             "changed 3 records. Same data for every configuration, so the comparison "
             "is like-for-like."},
    {"key": "b", "name": "production C4b + gate v2 (the incumbent)",
     "index_dir": "index", "lexicon": "auto", "expand": "auto",
     "gate": "default", "rerank": None,
     "note": "The adopted production default. Every other configuration is compared "
             "against this one."},
    {"key": "c", "name": "lexicon v2 (Phase 10.1, frozen)",
     "index_dir": "index_exp/minilm_lexv2", "lexicon": "data/domain_lexicon_v2.json",
     "expand": "bm25", "gate": "default", "rerank": None},
    {"key": "d", "name": "lexicon v2 + lamp token (Phase 10.1b, frozen)",
     "index_dir": "index_exp/minilm_lexv2_lamp", "lexicon": "data/domain_lexicon_v2.json",
     "expand": "bm25", "gate": "default", "rerank": None},
    {"key": "e", "name": "lexicon v2 + CPU cross-encoder re-rank of the top 20",
     "index_dir": "index_exp/minilm_lexv2", "lexicon": "data/domain_lexicon_v2.json",
     "expand": "bm25", "gate": "default",
     "rerank": {"model": "cross-encoder/ms-marco-MiniLM-L-6-v2", "top_k": 20,
                "device": "cpu", "pair": "(query, embedding_text(record))",
                "tie_break": "cross-encoder score desc, then original rank, then code_full"}},
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # the lexicon-v2 freeze must still hold before anything is measured with it
    freeze = json.load(open("data/experiments/10_1b/freeze.json"))
    drift = [p for p, h in freeze["sha256"].items() if sha256(p) != h]
    if drift:
        print("REFUSING: the 10.1b freeze no longer holds for:", drift)
        return 1

    rerank_available = True
    try:
        from sentence_transformers import CrossEncoder   # noqa: F401
        cached = os.path.isdir(os.path.expanduser(
            "~/.cache/huggingface/hub/models--cross-encoder--ms-marco-MiniLM-L-6-v2"))
        rerank_available = cached
    except Exception:
        rerank_available = False

    blob = {
        "phase": "10.6",
        "registered_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit_at_registration": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "statement": (
            "ONE SHOT. Every configuration below is evaluated exactly once on the "
            "independent set. Nothing is tuned after results are seen, no query is "
            "dropped or edited, and no configuration is adopted in this phase — the "
            "adoption rule is recorded here and its verdict is reported, nothing more."),
        "gold": {
            "path": "data/gold_independent.json",
            "sha256": sha256("data/gold_independent.json"),
            "rows": 60, "symptom": 41, "no_dtc": 19,
            "confidence": {"high": 14, "medium": 26, "low": 20},
            "input_to_system": "q['query'] ONLY. lamp_reported, notes, confidence and "
                               "expected are never shown to the system.",
            "validated_by": "scripts/validate_independent.py (schema, codes exist, sha256)",
        },
        "configurations": CONFIGS,
        "rerank_config_e": {
            "will_run": rerank_available,
            "reason": ("cross-encoder/ms-marco-MiniLM-L-6-v2 is present in the local "
                       "Hugging Face cache and runs on CPU, so it runs offline here"
                       if rerank_available else
                       "the cross-encoder is not available offline; config (e) will be "
                       "reported as NOT RUN"),
        },
        "metrics": {
            "symptom_rows": {
                "hit": "any expected code appears in the returned list",
                "reported": ["hit@1", "hit@3", "hit@5", "MRR", "gate_pass_rate"],
                "k": 5,
                "mrr": "1/rank of the first expected code in the top 5, else 0",
                "gated_rows_score_zero": True,
                "note": "A row refused by the gate scores 0 for hit and MRR: a refusal "
                        "is the right behaviour for no_dtc rows and the wrong one here, "
                        "and the metric must not hide that.",
            },
            "no_dtc_rows": {
                "reported": ["decline_rate", "codes_returned_when_answered"],
                "declined": "the gate refused, or the retriever returned nothing",
                "note": "The exact-code and system_group routes bypass the gate by "
                        "design; the route taken is recorded for every row so any "
                        "non-hybrid route is visible.",
            },
            "subsets": ["ALL", "HIGH only", "HIGH+MEDIUM"],
        },
        "uncertainty": {
            "method": "non-parametric bootstrap over rows",
            "resamples": 10000,
            "seed": 1006,
            "interval": "percentile 95% CI (2.5th, 97.5th)",
            "paired_test": ("paired bootstrap of symptom MRR difference vs configuration "
                            "(b): the same resampled row indices are applied to both "
                            "configurations, and the CI is over the per-resample "
                            "difference"),
        },
        "adoption_rule": {
            "fixed_before_running": True,
            "rule": ("A configuration replaces (b) only if BOTH hold: (1) its paired 95% "
                     "CI for symptom MRR gain over (b) excludes 0, AND (2) its no_dtc "
                     "decline rate is not lower than (b)'s."),
            "evaluated_on": "ALL rows (the headline subset)",
            "action_in_this_phase": "report the verdict only; adopt nothing",
        },
        "inputs_sha256": {p: sha256(p) for p in INPUTS if os.path.exists(p)},
        "environment": {
            "determinism_hash_dev_defaults": "ffff9bc707d8754d",
            "python": sys.version.split()[0],
            "exact_dense": True,
            "note": "All ranking is exact brute force with id tie-breaks, so results "
                    "are reproducible across processes.",
        },
        "one_shot_enforcement": ("scripts/independent_eval.py refuses to run if "
                                 "data/experiments/10_6/results.json already exists."),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(blob, f, indent=1)
        f.write("\n")
    print(f"wrote {OUT}")
    print(f"  gold sha256      {blob['gold']['sha256']}")
    print(f"  configurations   {[c['key'] for c in CONFIGS]}")
    print(f"  config (e) runs  {rerank_available}")
    print(f"  inputs recorded  {len(blob['inputs_sha256'])}")
    print(f"  10.1b freeze     verified, no drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
