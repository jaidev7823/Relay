# SPDX-License-Identifier: AGPL-3.0-or-later
"""LanceDB storage layer with a JSON manifest (the desktop backend).

The database directory is self-contained (LanceDB table + manifest.json), so
it can live on any drive and be moved by copying. The manifest records which
embedding model built the index, the chunk settings, and a per-file record
for incremental updates. Opening with a mismatched embedding backend or
chunk settings is refused with a RebuildRequiredError.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .base import VectorStore

logger = logging.getLogger(__name__)


TABLE_NAME = "chunks"
MANIFEST_NAME = "manifest.json"


class StoreError(Exception):
    """Base class for index-store errors; the message is user-facing."""


class LocationUnavailableError(StoreError):
    pass


class EmbeddingMismatchError(StoreError):
    pass


class RebuildRequiredError(StoreError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            f"The index must be rebuilt: {reason} "
            "Run a rebuild ('Rebuild index' in the GUI, or "
            "'python -m relevantr rebuild' on the CLI)."
        )


class LegacyIndexError(StoreError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Manifest:
    pdf_dir: str
    embedding_model: str
    embedding_dim: int
    chunk_size: int
    chunk_overlap: int
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    # filename -> {"size": int, "mtime": float, "sha256": str, "chunks": int}
    files: dict = field(default_factory=dict)
    # observed embedding throughput, for rebuild time estimates
    avg_seconds_per_file: float | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        data = json.loads(text)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def describe_unavailable(path: Path, kind: str) -> str:
    path = Path(path)
    msg = f"The {kind} location '{path}' is not available."
    parts = path.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        volume = Path("/Volumes") / parts[2]
        if not volume.exists():
            return (
                f"{msg} The external drive '{parts[2]}' does not appear to be "
                "mounted. Connect/mount the drive and try again."
            )
    return (
        f"{msg} If it lives on an external or network drive, make sure the "
        "drive is mounted, or point Relevantr at the correct location in "
        "Settings (or with --db-dir/--pdf-dir)."
    )


def ensure_pdf_dir_available(pdf_dir: str | Path) -> Path:
    pdf_dir = Path(pdf_dir)
    if not pdf_dir.is_dir():
        raise LocationUnavailableError(describe_unavailable(pdf_dir, "PDF (papers)"))
    return pdf_dir


def detect_legacy_chroma(*dirs: str | Path) -> Path | None:
    """Return the first directory that looks like a v1 ChromaDB index."""
    for d in dirs:
        if not d:
            continue
        d = Path(d)
        for candidate in (d, d / "vector_db"):
            if (candidate / "chroma.sqlite3").exists():
                return candidate
    return None


class IndexStore(VectorStore):
    def __init__(self, db_dir: str | Path):
        self.db_dir = Path(db_dir)
        self._db = None
        self._table = None

    # -- basic state -------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.db_dir / MANIFEST_NAME

    @property
    def location(self) -> str:
        """Human-readable storage location for status displays."""
        return str(self.db_dir)

    def exists(self) -> bool:
        return self.manifest_path.exists()

    def _connect(self):
        if self._db is None:
            import lancedb

            self._db = lancedb.connect(self.db_dir)
        return self._db

    def _get_table(self):
        if self._table is None:
            self._table = self._connect().open_table(TABLE_NAME)
        return self._table

    # -- opening / creating ------------------------------------------------

    def open_existing(self) -> Manifest:
        """Open an existing index for query/append. Never creates anything."""
        if not self.db_dir.exists():
            raise LocationUnavailableError(describe_unavailable(self.db_dir, "database"))
        legacy = detect_legacy_chroma(self.db_dir)
        if legacy:
            raise LegacyIndexError(
                f"'{legacy}' contains a Relevantr v1 (ChromaDB) index. "
                "Relevantr v2 uses LanceDB and cannot read it - the index "
                "must be rebuilt from your PDF folder (v1 data cannot be "
                "migrated)."
            )
        if not self.manifest_path.exists():
            raise RebuildRequiredError(
                f"no index manifest was found in '{self.db_dir}'."
            )
        try:
            manifest = Manifest.from_json(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise RebuildRequiredError(
                f"the index manifest in '{self.db_dir}' is corrupt ({exc})."
            ) from None
        return manifest

    def check_compatible(self, manifest: Manifest, embedder, chunk_size: int,
                         chunk_overlap: int) -> None:
        """Refuse to append/query with a mismatched backend or chunk settings."""
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
        """Create a fresh, empty index (drops any existing table)."""
        import pyarrow as pa

        self.db_dir.mkdir(parents=True, exist_ok=True)
        db = self._connect()
        schema = pa.schema(
            [
                pa.field("vector", pa.list_(pa.float32(), manifest.embedding_dim)),
                pa.field("text", pa.string()),
                pa.field("source", pa.string()),
                pa.field("page", pa.int32()),
                pa.field("chunk_id", pa.string()),
            ]
        )
        self._table = db.create_table(TABLE_NAME, schema=schema, mode="overwrite")
        self.write_manifest(manifest)

    def write_manifest(self, manifest: Manifest) -> None:
        manifest.updated_at = _now()
        self.manifest_path.write_text(manifest.to_json(), encoding="utf-8")

    # -- data operations ---------------------------------------------------

    def add_chunks(self, chunks, vectors: np.ndarray) -> None:
        if len(chunks) == 0:
            return
        rows = [
            {
                "vector": np.asarray(vec, dtype=np.float32),
                "text": chunk.text,
                "source": chunk.source,
                "page": chunk.page,
                "chunk_id": chunk.chunk_id,
            }
            for chunk, vec in zip(chunks, vectors)
        ]
        self._get_table().add(rows)

    def delete_source(self, filename: str) -> None:
        escaped = filename.replace("'", "''")
        self._get_table().delete(f"source = '{escaped}'")

    def rebuild_fts(self) -> None:
        """(Re)create the BM25 full-text-search index over the text column."""
        table = self._get_table()
        try:
            from lancedb.index import FTS

            table.create_index("text", config=FTS(), replace=True)
        except ImportError:  # older lancedb
            table.create_fts_index("text", use_tantivy=False, replace=True)

    def search_hybrid(self, query: str, query_vector: np.ndarray, k: int) -> list[dict]:
        """Hybrid search fusing vector and BM25 results (RRF reranker)."""
        table = self._get_table()
        results = (
            table.search(query_type="hybrid")
            .vector(np.asarray(query_vector, dtype=np.float32))
            .text(query)
            .limit(k)
            .to_list()
        )
        return results

    def count_chunks(self) -> int:
        return self._get_table().count_rows()
