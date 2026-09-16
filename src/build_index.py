"""
Phase 4 — Indexing (local, CPU-only).

Builds three complementary indexes into ./index/ from data/dtc_records.jsonl:

  1. DENSE   — all-MiniLM-L6-v2 (384-dim), L2-normalised, in a persistent Chroma
               collection with space=cosine.
  2. EXACT   — code_full -> [records] and base dtc_code -> [records]. Both map to
               LISTS: the DTC code is not a unique key (P0180-11, P0180-12 and
               P061C-00 each appear twice), so a dict that overwrites would
               silently lose a record.
  3. BM25    — lexical, over a tokenisation that keeps DTC codes and pin labels
               intact as single tokens.

No router and no fusion here - that is Phase 5.

EMBEDDING TEXT (the key decision): the dense text deliberately EXCLUDES the
procedural step text. The troubleshooting steps are near-identical boilerplate
across hundreds of DTCs ("Check the battery voltage", "Fix the back-out cables in
proper positions in connector & go to Step 13"), so embedding them pulls every
record toward the same centroid and destroys discrimination between the
near-duplicate families (rail-pressure trio, injectors 1-4, ~85 FCCU alarms). The
steps stay in the record for answering; they are simply not embedded.

RAM discipline: the embedding model is loaded, used, and released BEFORE the vector
store is opened. Only one model is ever resident.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import re
import resource
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone

RECORDS = "data/dtc_records.jsonl"
INDEX_DIR = "index"
CHROMA_DIR = f"{INDEX_DIR}/chroma"
COLLECTION = "dtc_records"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
BATCH_SIZE = 32

# Tokens must survive intact: "P0192-00" is one term, not ["p", "0192", "00"],
# and "A71" is one term, not ["a", "71"]. Default word-splitting would destroy
# exactly the identifiers that carry the most retrieval signal.
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-\.]*")
DTC_TOKEN = re.compile(r"^[pubc][0-9a-f]{4}-[0-9a-f]{2}$")


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def tokenize(text):
    """Lexical tokenizer that preserves DTC codes and pin/net labels."""
    out = []
    for raw in TOKEN_RE.findall(text.lower()):
        t = raw.strip(".-_")
        if not t:
            continue
        out.append(t)
        # Also index the bare code so a query "P0192" hits "P0192-00".
        if DTC_TOKEN.match(t):
            out.append(t.split("-")[0])
    return out


def embedding_text(r):
    """
    Dense text: identity + symptom + cause + effect + checks + circuit + pins.
    Deliberately NO step text - see the module docstring.
    """
    parts = [
        r["code_full"],
        r["description"],
        f"system: {r['system']}",
    ]
    if r.get("cause"):
        parts.append("Causes: " + "; ".join(r["cause"]))
    if r.get("effect"):
        parts.append("Effect on vehicle: " + r["effect"])
    if r.get("checkpoints"):
        parts.append("Checkpoints: " + "; ".join(r["checkpoints"]))
    if r.get("circuit_description"):
        parts.append(r["circuit_description"])
    pins = [p["pin"] for p in r.get("pin_map") or []]
    nets = [p["net"] for p in r.get("pin_map") or [] if p.get("net")]
    if pins:
        parts.append("Pins: " + " ".join(pins))
    if nets:
        parts.append("Nets: " + " ".join(nets))
    return "\n".join(parts)


def bm25_text(r):
    """Lexical text: as above, plus the step CONDITION clauses (not full steps)."""
    parts = [
        r["code_full"], r["dtc_code"], r["description"], r["system"],
        " ".join(r.get("cause") or []),
        r.get("effect") or "",
        " ".join(r.get("checkpoints") or []),
        r.get("circuit_description") or "",
        " ".join(p["pin"] for p in r.get("pin_map") or []),
        " ".join(p["net"] for p in r.get("pin_map") or [] if p.get("net")),
        " ".join(s["condition"] for s in r["steps"] if s.get("condition")),
    ]
    return "\n".join(x for x in parts if x)


def chroma_metadata(r):
    """Chroma rejects None; every value is coerced to a scalar."""
    def s(v):
        return "" if v is None else str(v)
    return {
        "code_full": r["code_full"],
        "dtc_code": r["dtc_code"],
        "suffix": r["suffix"],
        "system": r["system"],
        "template_variant": r["template_variant"],
        "MIL": s(r.get("MIL")),
        "effect": s(r.get("effect")),
        "page": int(r["page"]),
        "occurrence": int(r["occurrence"]),
    }


def record_id(r):
    """Unique even for repeated codes: P0180-11 appears on pages 100 and 195."""
    return f"{r['code_full']}@p{r['page']}#{r['occurrence']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=RECORDS)
    ap.add_argument("--rebuild", action="store_true",
                    help="delete the index dir first for a clean build")
    # Phase 8.2 experiment knobs. DEFAULTS reproduce the production index exactly
    # (MiniLM, no prefix, no aliases, ./index/), so v1 stays reproducible.
    ap.add_argument("--index-dir", default=INDEX_DIR)
    ap.add_argument("--model", default=MODEL_NAME)
    ap.add_argument("--passage-prefix", default="",
                    help='e.g. "passage: " for e5 models')
    ap.add_argument("--aliases", choices=["none", "bm25", "both"], default="none",
                    help="append lexicon aliases to BM25 text, or BM25 + dense text")
    ap.add_argument("--lexicon", default="data/domain_lexicon.json")
    args = ap.parse_args()
    index_dir, model_name = args.index_dir, args.model
    chroma_dir = f"{index_dir}/chroma"
    lex = None
    if args.aliases != "none":
        from lexicon import Lexicon
        lex = Lexicon(args.lexicon)

    recs = [json.loads(l) for l in open(args.records)]
    print(f"loaded {len(recs)} records")

    if args.rebuild and os.path.isdir(index_dir):
        shutil.rmtree(index_dir)
    os.makedirs(index_dir, exist_ok=True)

    ids = [record_id(r) for r in recs]
    assert len(set(ids)) == len(ids), "record ids are not unique"

    # ---------------- 1. DENSE -------------------------------------------
    def alias_str(r):
        return ("\nAlso known as: " + "; ".join(lex.record_aliases(r))) if lex else ""
    dense_texts = [embedding_text(r) + (alias_str(r) if args.aliases == "both" else "")
                   for r in recs]
    print(f"dense corpus: {len(dense_texts)} docs, "
          f"avg {sum(len(t) for t in dense_texts)//len(dense_texts)} chars")

    from sentence_transformers import SentenceTransformer
    print(f"loading {model_name} ...")
    model = SentenceTransformer(model_name, device="cpu")
    dim = model.get_sentence_embedding_dimension()
    vecs = model.encode([args.passage_prefix + t for t in dense_texts], batch_size=BATCH_SIZE,
                        normalize_embeddings=True,          # L2 -> cosine
                        convert_to_numpy=True,
                        show_progress_bar=False)
    print(f"encoded {vecs.shape} | peak RSS so far {rss_mb():.0f} MB")

    # release the model BEFORE opening the vector store - one model at a time
    del model
    gc.collect()
    print(f"model released | RSS now {rss_mb():.0f} MB (peak)")

    import chromadb
    client = chromadb.PersistentClient(path=chroma_dir)
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    coll = client.create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(recs), BATCH_SIZE):
        sl = slice(i, i + BATCH_SIZE)
        coll.add(ids=ids[sl],
                 embeddings=[v.tolist() for v in vecs[sl]],
                 documents=dense_texts[sl],
                 metadatas=[chroma_metadata(r) for r in recs[sl]])
    print(f"chroma collection '{COLLECTION}': {coll.count()} vectors")

    # ---------------- 2. EXACT-CODE --------------------------------------
    by_full, by_base = defaultdict(list), defaultdict(list)
    for r, rid in zip(recs, ids):
        ref = {"id": rid, "code_full": r["code_full"], "page": r["page"],
               "occurrence": r["occurrence"], "description": r["description"],
               "system": r["system"]}
        by_full[r["code_full"]].append(ref)
        by_base[r["dtc_code"]].append(ref)
    exact = {"by_code_full": dict(by_full), "by_dtc_code": dict(by_base)}
    with open(f"{index_dir}/code_index.json", "w") as f:
        json.dump(exact, f, indent=1)
    dup_full = {k: len(v) for k, v in by_full.items() if len(v) > 1}
    multi_base = {k: len(v) for k, v in by_base.items() if len(v) > 1}
    print(f"exact index: {len(by_full)} code_full keys "
          f"({len(dup_full)} with >1 record), {len(by_base)} base-code keys "
          f"({len(multi_base)} with >1 variant)")

    # ---------------- 3. BM25 --------------------------------------------
    # The tokenised corpus IS the index: BM25Okapi's statistics are a
    # deterministic function of it, so rebuilding at load is exact and avoids
    # pickling a library object across versions. 314 docs rebuild instantly.
    corpus = [tokenize(bm25_text(r) + (alias_str(r) if args.aliases in ("bm25", "both") else ""))
              for r in recs]
    with open(f"{index_dir}/bm25_corpus.json", "w") as f:
        json.dump({"ids": ids, "corpus": corpus,
                   "tokenizer": {"pattern": TOKEN_RE.pattern,
                                 "lowercase": True,
                                 "dtc_base_expansion": True}}, f)
    print(f"bm25 corpus: {len(corpus)} docs, "
          f"{sum(len(c) for c in corpus)} tokens, "
          f"{len(set(t for c in corpus for t in c))} unique")

    # ---------------- meta ------------------------------------------------
    import chromadb as _c
    import sentence_transformers as _st
    meta = {
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": len(recs),
        "dense": {
            "model": model_name,
            "passage_prefix": args.passage_prefix,
            "embedding_dim": int(dim),
            "normalization": "L2 (unit norm); Chroma space=cosine",
            "batch_size": BATCH_SIZE,
            "device": "cpu",
            "embedding_text_fields": [
                "code_full", "description", "system", "cause[]", "effect",
                "checkpoints[]", "circuit_description", "pin_map.pin",
                "pin_map.net"],
            "embedding_text_excludes": ["steps[].text"],
            "excludes_rationale":
                "step text is near-identical across DTCs and dilutes "
                "discrimination between near-duplicate families",
        },
        "aliases": {"mode": args.aliases,
                    "lexicon": args.lexicon if lex else None,
                    "lexicon_version": lex.version if lex else None},
        "chroma": {"version": _c.__version__, "path": chroma_dir,
                   "collection": COLLECTION, "space": "cosine"},
        "sentence_transformers_version": _st.__version__,
        "bm25": {"library": "rank-bm25 (BM25Okapi)",
                 "persisted": "tokenised corpus; scorer rebuilt at load",
                 "token_pattern": TOKEN_RE.pattern,
                 "preserves": ["DTC codes e.g. p0192-00", "pin labels e.g. a71"]},
        "exact": {"by_code_full_keys": len(by_full),
                  "by_dtc_code_keys": len(by_base),
                  "duplicate_code_full": dup_full},
        "peak_rss_mb": round(rss_mb()),
    }
    with open(f"{index_dir}/meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nwrote {index_dir}/meta.json | PEAK RSS {rss_mb():.0f} MB")
    print(f"systems histogram: {dict(Counter(r['system'] for r in recs).most_common())}")


if __name__ == "__main__":
    main()
