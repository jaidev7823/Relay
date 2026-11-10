# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vector-store interface shared by every backend.

The desktop app ships with an embedded LanceDB store; the server talks to
Qdrant instead. Both implement this interface so ``pipeline`` stays
backend-agnostic. Manifest handling (the JSON record of what is indexed,
with which model and chunk settings) is part of the contract because the
pipeline refuses to mix vectors from different embedding models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..ingest import Chunk


class VectorStore(ABC):
    """Storage backend for chunk vectors, payloads and full-text search."""

    # -- lifecycle ---------------------------------------------------------

    @abstractmethod
    def exists(self) -> bool:
        """True if an index exists at this location."""

    @abstractmethod
    def create(self, manifest) -> None:
        """Create a fresh, empty index; drops anything that exists."""

    @abstractmethod
    def open_existing(self):
        """Open an existing index and return its manifest."""

    @abstractmethod
    def write_manifest(self, manifest) -> None:
        """Persist the manifest (updated_at is refreshed here)."""

    # -- data operations ---------------------------------------------------

    @abstractmethod
    def add_chunks(self, chunks: list[Chunk], vectors) -> None:
        """Store chunks with their embedding vectors."""

    @abstractmethod
    def delete_source(self, filename: str) -> None:
        """Drop every chunk belonging to one source file."""

    @abstractmethod
    def rebuild_fts(self) -> None:
        """(Re)build the full-text/keyword index over the chunk text."""

    @abstractmethod
    def search_hybrid(self, query: str, query_vector, k: int) -> list[dict]:
        """Return up to k rows as dicts with text/source/page/score keys."""

    @abstractmethod
    def count_chunks(self) -> int:
        """Number of stored chunks."""
