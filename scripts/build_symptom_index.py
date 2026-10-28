"""
Phase 12.1 — build the symptom-expansion index (the third ranker).

    PYTHONPATH=src .venv/bin/python scripts/build_symptom_index.py \
        --index-dir index_exp/minilm_sympexp

Starts from the production configuration (C4b: aliases on the BM25 side, cylinder
and state compound tokens) and adds the Phase 12.1 symptom expansions:

  * DENSE, a separate vector PER EXPANSION, not one per record. A record's
    symptom score is the MAX over its own expansions, so one well-matched
    paraphrase is enough and the rest do not dilute it.
  * BM25, the expansions appended to the record's lexical text.

It writes a NEW index directory and does not touch `src/build_index.py`, which is
covered by the Phase 10.1b freeze - it imports from it instead.

The expansions are INDEX-ONLY. Nothing here changes the records, so answers, fix
blocks and citations still come from the manual alone.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import shutil
import sys

sys.path.insert(0, "src")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

EXPANSIONS = "data/symptom_expansions.json"
BATCH = 32


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", default="index_exp/minilm_sympexp")
    ap.add_argument("--expansions", default=EXPANSIONS)
    ap.add_argument("--records", default="data/dtc_records.jsonl")
    ap.add_argument("--lexicon", default="data/domain_lexicon.json")
    a = ap.parse_args()

    from build_index import (COLLECTION, MODEL_NAME, bm25_text, chroma_metadata,
                             embedding_text, record_id, tokenize)
    from lexicon import Lexicon

    recs = [json.loads(l) for l in open(a.records)]
    ids = [record_id(r) for r in recs]
    blob = json.load(open(a.expansions))
    exp_by_id = {k: v["expansions"] for k, v in blob["records"].items()}
    missing = [i for i in ids if not exp_by_id.get(i)]
    n_exp = sum(len(exp_by_id.get(i, [])) for i in ids)
    print(f"{len(recs)} records | {n_exp} expansions | {len(missing)} records with none")

    lex = Lexicon(a.lexicon)
    alias = {i: ("\nAlso known as: " + "; ".join(lex.record_aliases(r))) if lex else ""
             for i, r in zip(ids, recs)}

    if os.path.isdir(a.index_dir):
        shutil.rmtree(a.index_dir)
    os.makedirs(a.index_dir, exist_ok=True)

    # ---------------- dense: the record vectors, exactly as production ----------
    from sentence_transformers import SentenceTransformer
    print(f"loading {MODEL_NAME} ...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    dense_texts = [embedding_text(r) for r in recs]
    vecs = model.encode(dense_texts, batch_size=BATCH, normalize_embeddings=True,
                        convert_to_numpy=True, show_progress_bar=False)

    # ---------------- dense: one vector PER EXPANSION --------------------------
    flat, owner = [], []
    for i in ids:
        for e in exp_by_id.get(i, []):
            flat.append(e)
            owner.append(i)
    print(f"encoding {len(flat)} expansion vectors ...")
    svecs = model.encode(flat, batch_size=BATCH, normalize_embeddings=True,
                         convert_to_numpy=True, show_progress_bar=False) if flat else []
    del model
    gc.collect()

    import numpy as np
    np.save(f"{a.index_dir}/symptom_vectors.npy", np.asarray(svecs, dtype="float32"))
    with open(f"{a.index_dir}/symptom_meta.json", "w") as f:
        json.dump({"owner_ids": owner, "texts": flat,
                   "label": "index-only, never shown to users",
                   "scoring": "a record's symptom score is the MAX cosine over its own "
                              "expansions",
                   "source": a.expansions, "model": blob["model"], "seed": blob["seed"]}, f)

    # ---------------- chroma collection (records only) -------------------------
    import chromadb
    client = chromadb.PersistentClient(path=f"{a.index_dir}/chroma")
    coll = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(recs), BATCH):
        sl = slice(i, i + BATCH)
        coll.add(ids=ids[sl], embeddings=[v.tolist() for v in vecs[sl]],
                 documents=dense_texts[sl],
                 metadatas=[chroma_metadata(r) for r in recs[sl]])
    print(f"chroma: {coll.count()} record vectors")

    # ---------------- exact-code index ----------------------------------------
    from collections import defaultdict
    by_full, by_base = defaultdict(list), defaultdict(list)
    for r, rid in zip(recs, ids):
        ref = {"id": rid, "code_full": r["code_full"], "page": r["page"],
               "occurrence": r["occurrence"], "description": r["description"],
               "system": r["system"]}
        by_full[r["code_full"]].append(ref)
        by_base[r["dtc_code"]].append(ref)
    json.dump({"by_code_full": dict(by_full), "by_dtc_code": dict(by_base)},
              open(f"{a.index_dir}/code_index.json", "w"), indent=1)

    # ---------------- BM25: production text + aliases + expansions -------------
    corpus = []
    for r, rid in zip(recs, ids):
        extra = "\n".join(exp_by_id.get(rid, []))
        corpus.append(tokenize(bm25_text(r) + alias[rid] + ("\n" + extra if extra else ""),
                               cylinder_compound=True, state_compound=True))
    json.dump({"ids": ids, "corpus": corpus,
               "tokenizer": {"pattern": "[A-Za-z0-9][A-Za-z0-9_\\-\\.]*", "lowercase": True,
                             "dtc_base_expansion": True, "cylinder_compound": True,
                             "state_compound": True, "lamp_field": False,
                             "symptom_expansions": True}},
              open(f"{a.index_dir}/bm25_corpus.json", "w"))
    print(f"bm25: {len(corpus)} docs, {sum(len(c) for c in corpus)} tokens")

    json.dump({"built_for": "Phase 12.1 symptom-expansion third ranker",
               "records": len(recs), "expansions": len(flat),
               "dense": {"model": MODEL_NAME, "passage_prefix": ""},
               "aliases": {"mode": "bm25", "lexicon": a.lexicon},
               "bm25": {"cylinder_compound": True, "state_compound": True},
               "symptom_expansions": {"source": a.expansions, "vectors": len(flat),
                                      "label": "index-only, never shown to users"}},
              open(f"{a.index_dir}/meta.json", "w"), indent=1)
    print(f"wrote {a.index_dir}")


if __name__ == "__main__":
    main()
