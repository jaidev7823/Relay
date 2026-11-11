# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression check: the CA5-10 price query must surface the answer row.

Runs the real retrieval path (dense + DF-filtered BM25 + RRF + cross-encoder
reranker) against the live qdrant collection. Not part of the unit suite.

Usage:  venv/bin/python scripts/regression_ca5_10.py [collection]
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root

from server.settings import get_settings
import server.deps as deps
from relevantr.embed import get_backend
from relevantr.rerank import Reranker
from relevantr.store.qdrant import QdrantStore
import numpy as np
import logging

logging.basicConfig(level=logging.WARNING)

PDF_DIR = "data/projects/da3841592b4f0fca/pdfs"
COLLECTION = sys.argv[1] if len(sys.argv) > 1 else "lib_da384159"
QUERY = "CA5-10 price"


def main() -> int:
    settings = get_settings()
    st = deps.get_state()
    settings = st.settings
    cfg = dataclasses.replace(
        st.config,
        pdf_dir=PDF_DIR,
        qdrant_collection=COLLECTION,
        retrieve_k=60,
        final_n=12,
    )
    embedder = get_backend(cfg)
    store, _manifest = __import__("relevantr.pipeline", fromlist=["open_for_query"]).open_for_query(cfg, embedder)

    qvec = embedder.embed_query(QUERY)
    rows = store.search_hybrid(QUERY, qvec, k=cfg.retrieve_k)
    from relevantr.rerank import Passage

    passages = [
        Passage(
            text=row["text"],
            source=row["source"],
            page=int(row["page"]),
            score=float(row.get("_relevance_score") or row.get("_distance") or 0.0),
        )
        for row in rows
    ]
    reranker = Reranker()
    passages = reranker.rerank(QUERY, passages, top_n=cfg.final_n)

    print(f"query: {QUERY!r}\ncollection: {COLLECTION}\n")
    for i, p in enumerate(passages[:3], 1):
        print(f"=== rank {i}  page {p.page}  rerank score {p.score:.4f}")
        print(p.text.strip()[:600])
        print()

    hit = any("CA5-10" in p.text for p in passages)
    print("PASS" if hit else "FAIL", "- page 105 / CA5-10 chunk in final passages")
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main())
