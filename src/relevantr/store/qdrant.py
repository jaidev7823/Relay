# SPDX-License-Identifier: AGPL-3.0-or-later
"""Qdrant vector-store backend (the server backend for Phase 1+).

One Qdrant collection holds the chunks of one library. Every point carries
the chunk text, source file, page and chunk id as payload, so a hit can be
attributed exactly like the LanceDB rows are. The JSON manifest (what is
indexed, with which model and chunk settings) lives next to the Qdrant data
under ``<data_dir>/libraries/<collection>/manifest.json`` and keeps the same
rebuild-refusal guarantees as the desktop store.

Search: dense vectors + sparse BM25 vectors (Qdrant/bm25 via fastembed)
fused with reciprocal-rank fusion, mirroring the LanceDB hybrid search.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from collections import Counter

import numpy as np

from .base import VectorStore
from .lance import Manifest, _now, describe_unavailable

logger = logging.getLogger(__name__)

DEFAULT_QDRANT_URL = "http://localhost:6333"
BM25_MODEL = "Qdrant/bm25"


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    """Lowercase tokens; keeps hyphenated codes like 'CA5-10' intact."""
    return _TOKEN_RE.findall(text.lower())


def _point_id(chunk_id: str) -> str:
    """Deterministic UUID for a chunk id (stable across re-indexes)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"relevantr/chunk/{chunk_id}"))


def _to_row(point) -> dict:
    """Normalize a Qdrant scored point into the LanceDB-like row dict."""
    payload = point.payload or {}
    score = float(getattr(point, "score", None) or 0.0)
    return {
        "text": payload.get("text", ""),
        "source": payload.get("source", ""),
        "page": int(payload.get("page", 0)),
        "chunk_id": payload.get("chunk_id", ""),
        "_relevance_score": score,
    }


def _sparse(sparse) -> dict:
    """Convert a fastembed sparse embedding into Qdrant's dict shape."""
    return {"indices": list(sparse.indices), "values": list(sparse.values)}


class QdrantStore(VectorStore):
    def __init__(
        self,
        collection: str,
        data_dir: str | Path,
        url: str = DEFAULT_QDRANT_URL,
        api_key: str | None = None,
        client=None,
        sparse_model: str = BM25_MODEL,
        sparse_df_threshold: float = 0.5,
    ):
        self.collection = collection
        self.data_dir = Path(data_dir) / "libraries" / collection
        self.url = url
        self._api_key = api_key
        self._client = client  # injectable for tests (":memory:" or fakes)
        self._sparse_model_name = sparse_model
        self._sparse_model = None
        self._sparse_is_bm25 = None
        self._sparse_df_threshold = sparse_df_threshold
        self._df_stats_cache = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    @property
    def location(self) -> str:
        """Human-readable storage location for status displays."""
        return f"qdrant:{self.url}/{self.collection}"

    def exists(self) -> bool:
        return self.manifest_path.exists()

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self.url, api_key=self._api_key,
                                        timeout=30)
        return self._client

    def _get_sparse_model(self):
        """Lazily load the sparse (BM25) model used for keyword search."""
        if self._sparse_model is None:
            try:
                from fastembed.sparse.bm25 import Bm25

                self._sparse_model = Bm25(model_name=self._sparse_model_name)
                self._sparse_is_bm25 = True
            except Exception as exc:  # model missing, offline, etc.
                logger.warning(
                    "Sparse BM25 model unavailable (%s); hybrid search "
                    "falls back to dense-only.", exc,
                )
                self._sparse_model = None
                self._sparse_is_bm25 = False
        return self._sparse_model

    def _df_stats(self) -> tuple[Counter, int]:
        """Document frequency of tokens over payload['text'], cached per store.

        Used to strip corpus-common tokens from the sparse query lane so rare
        identifiers (e.g. part codes) dominate keyword scoring. One scroll
        pass; invalidated on index mutations.
        """
        if self._df_stats_cache is not None:
            return self._df_stats_cache
        df: Counter = Counter()
        total = 0
        offset = None
        client = self._get_client()
        while True:
            points, offset = client.scroll(
                collection_name=self.collection,
                limit=500,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            if not points:
                break
            total += len(points)
            for point in points:
                text = (point.payload or {}).get("text") or ""
                for token in set(_tokenize(text)):
                    df[token] += 1
            if offset is None:
                break
        self._df_stats_cache = (df, total)
        return self._df_stats_cache

    def _filtered_query(self, query: str) -> str:
        """Sparse-lane query with corpus-common tokens removed.

        Falls back to the untouched query if stats are unavailable or nothing
        would remain (both better than an empty sparse query).
        """
        try:
            df, total = self._df_stats()
        except Exception as exc:  # collection missing/unreadable
            logger.warning("DF stats unavailable; sparse lane unfiltered (%s)", exc)
            return query
        if total == 0:
            return query
        kept = [
            token
            for token in _tokenize(query)
            if df.get(token, 0) / total <= self._sparse_df_threshold
        ]
        if not kept:
            return query
        return " ".join(kept)

    def open_existing(self) -> Manifest:
        from .lance import LocationUnavailableError, RebuildRequiredError

        if not self.data_dir.exists():
            raise LocationUnavailableError(
                describe_unavailable(self.data_dir, "database")
            )
        if not self.manifest_path.exists():
            raise RebuildRequiredError(
                f"no index manifest was found in '{self.data_dir}'."
            )
        return Manifest.from_json(self.manifest_path.read_text(encoding="utf-8"))

    def check_compatible(self, manifest: Manifest, embedder, chunk_size: int,
                        chunk_overlap: int) -> None:
        """Same refusal rules as the desktop store."""
        from .lance import EmbeddingMismatchError, RebuildRequiredError

        if manifest.embedding_model != embedder.name:
            raise EmbeddingMismatchError(
                f"This index was built with embedding model "
                f"'{manifest.embedding_model}' but the current setting is "
                f"'{embedder.name}'. Vectors from different models cannot be "
                "mixed - rebuild the index with the new backend, or switch "
                "the setting back."
            )
        if (manifest.chunk_size, manifest.chunk_overlap) != (chunk_size, chunk_overlap):
            raise RebuildRequiredError(
                f"the chunk settings changed (index: size "
                f"{manifest.chunk_size}/overlap {manifest.chunk_overlap}, "
                f"current: size {chunk_size}/overlap {chunk_overlap}); mixing "
                "them would silently degrade retrieval."
            )

    def create(self, manifest: Manifest) -> None:
        from qdrant_client import models

        self._df_stats_cache = None
        client = self._get_client()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if client.collection_exists(self.collection):
            client.delete_collection(self.collection)
        client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=manifest.embedding_dim, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False)
                )
            },
        )
        # Payload indexes make source filtering (deletes, updates) fast.
        for field, schema in [
            ("source", models.PayloadSchemaType.KEYWORD),
            ("page", models.PayloadSchemaType.INTEGER),
            ("chunk_id", models.PayloadSchemaType.KEYWORD),
        ]:
            try:
                client.create_payload_index(
                    self.collection, field_name=field, field_schema=schema
                )
            except Exception as exc:  # pragma: no cover - server dependent
                logger.warning("payload index %s failed: %s", field, exc)
        self.write_manifest(manifest)

    def write_manifest(self, manifest: Manifest) -> None:
        manifest.updated_at = _now()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(manifest.to_json(), encoding="utf-8")

    # -- data operations ---------------------------------------------------

    def add_chunks(self, chunks, vectors) -> None:
        self._df_stats_cache = None
        if len(chunks) == 0:
            return
        from qdrant_client import models

        sparse = self._get_sparse_model()
        texts = [c.text for c in chunks]
        if sparse is not None:
            sparse_vectors = [_sparse(s) for s in sparse.embed(texts)]
        else:
            sparse_vectors = [None] * len(chunks)

        points = [
            models.PointStruct(
                id=_point_id(chunk.chunk_id),
                vector={
                    "dense": np.asarray(vec, dtype=np.float32).tolist(),
                    **({"bm25": sv} if sv else {}),
                },
                payload={
                    "text": chunk.text,
                    "source": chunk.source,
                    "page": chunk.page,
                    "chunk_id": chunk.chunk_id,
                },
            )
            for chunk, vec, sv in zip(chunks, vectors, sparse_vectors)
        ]
        client = self._get_client()
        batch = 256
        for start in range(0, len(points), batch):
            client.upsert(
                collection_name=self.collection,
                points=points[start : start + batch],
                wait=True,
            )

    def delete_source(self, filename: str) -> None:
        self._df_stats_cache = None
        from qdrant_client import models

        self._get_client().delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source",
                            match=models.MatchValue(value=filename),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def rebuild_fts(self) -> None:
        """No-op: keyword search runs through the sparse vectors at query
        time (BM25), so there is no separate index to rebuild."""

    def search_hybrid(self, query: str, query_vector, k: int) -> list[dict]:
        """Dense + sparse BM25 fused with RRF via Qdrant's Query API."""
        from qdrant_client import models

        client = self._get_client()
        dense = np.asarray(query_vector, dtype=np.float32).tolist()
        sparse = self._get_sparse_model()
        sparse_query = self._filtered_query(query)

        prefetch = [
            models.Prefetch(query=dense, using="dense", limit=k),
        ]
        if sparse is not None:
            prefetch.append(
                models.Prefetch(
                    query=_sparse(next(iter(sparse.embed([sparse_query])))),
                    using="bm25",
                    limit=k,
                )
            )

        results = client.query_points(
            collection_name=self.collection,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        )
        return [_to_row(p) for p in results.points]

    def count_chunks(self) -> int:
        client = self._get_client()
        info = client.get_collection(self.collection)
        return info.points_count
