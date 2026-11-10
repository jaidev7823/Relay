# SPDX-License-Identifier: AGPL-3.0-or-later
"""Storage layer: vector stores behind one interface.

``lance`` is the embedded desktop store; ``qdrant`` is the server store.
Both keep the same JSON manifest contract, so the pipeline, GUI and CLI
stay backend-agnostic (see ``store.base.VectorStore``).
"""

from __future__ import annotations

from .base import VectorStore
from .lance import (
    EmbeddingMismatchError,
    IndexStore,
    LegacyIndexError,
    LocationUnavailableError,
    Manifest,
    RebuildRequiredError,
    StoreError,
    describe_unavailable,
    detect_legacy_chroma,
    ensure_pdf_dir_available,
)
from .qdrant import QdrantStore, DEFAULT_QDRANT_URL

__all__ = [
    "VectorStore",
    "IndexStore",
    "QdrantStore",
    "DEFAULT_QDRANT_URL",
    "Manifest",
    "StoreError",
    "LocationUnavailableError",
    "EmbeddingMismatchError",
    "RebuildRequiredError",
    "LegacyIndexError",
    "describe_unavailable",
    "detect_legacy_chroma",
    "ensure_pdf_dir_available",
]


def get_store(config) -> VectorStore:
    """Return the store backend named by ``config.vector_backend``.

    Accepts either an ``AppConfig`` (``vector_backend``/``db_dir``/
    ``qdrant_*`` fields) or the legacy bare db_dir behaviour via
    ``embedding_backend`` (kept for the desktop default, which is lance).
    """
    backend = getattr(config, "vector_backend", None) or "lance"

    if backend == "lance":
        return IndexStore(getattr(config, "db_dir", None))

    if backend == "qdrant":
        return QdrantStore(
            collection=getattr(config, "qdrant_collection", None) or "lib_default",
            data_dir=getattr(config, "data_dir", None) or getattr(
                config, "db_dir", "."
            ),
            url=getattr(config, "qdrant_url", None) or DEFAULT_QDRANT_URL,
            api_key=getattr(config, "qdrant_api_key", None),
        )

    raise ValueError(f"Unknown vector backend: {backend!r}")
