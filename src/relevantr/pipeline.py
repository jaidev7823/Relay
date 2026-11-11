# SPDX-License-Identifier: AGPL-3.0-or-later
"""High-level operations shared by the GUI and the CLI:
build/rebuild, incremental update, rebuild-needed checks, info, and query.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig
from .embed import EmbeddingBackend
from .ingest import (
    Chunk,
    TokenSplitter,
    chunk_pdf,
    content_hash,
    file_fingerprint,
    list_pdfs,
)
from .rerank import Passage, Reranker
from .store import (
    IndexStore,
    LocationUnavailableError,
    Manifest,
    RebuildRequiredError,
    StoreError,
    describe_unavailable,
    ensure_pdf_dir_available,
    get_store,
)

logger = logging.getLogger(__name__)

# Fallback embed-rate guess (seconds per file) before any rate was observed.
DEFAULT_SECONDS_PER_FILE = 5.0


@dataclass
class UpdateSummary:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    chunks_embedded: int = 0

    @property
    def nothing_to_do(self) -> bool:
        return not (self.added or self.changed or self.removed)

    def describe(self) -> str:
        if self.nothing_to_do:
            return "Index is up to date - no new, changed, or removed PDFs."
        return (
            f"{len(self.added)} new, {len(self.changed)} changed, "
            f"{len(self.removed)} removed PDF(s); "
            f"{self.chunks_embedded} chunks embedded."
        )


def _embed_files(
    store: IndexStore,
    manifest: Manifest,
    pdf_dir: Path,
    filenames: list[str],
    embedder: EmbeddingBackend,
    splitter: TokenSplitter,
    progress=None,
) -> int:
    """Chunk + embed the given files and add them to the store.
    Returns the number of chunks embedded and updates the manifest records."""
    total_chunks = 0
    started = time.monotonic()
    for i, filename in enumerate(filenames):
        if progress:
            progress(i, len(filenames), f"Embedding {filename}")
        path = pdf_dir / filename
        chunks: list[Chunk] = chunk_pdf(path, splitter)
        if chunks:
            vectors = embedder.embed_documents([c.text for c in chunks])
            store.add_chunks(chunks, vectors)
        record = file_fingerprint(path)
        record["chunks"] = len(chunks)
        manifest.files[filename] = record
        total_chunks += len(chunks)
    if filenames:
        elapsed = time.monotonic() - started
        rate = elapsed / len(filenames)
        prev = manifest.avg_seconds_per_file
        manifest.avg_seconds_per_file = rate if prev is None else 0.5 * (prev + rate)
    if progress:
        progress(len(filenames), len(filenames), "Embedding complete")
    return total_chunks


def build_index(config: AppConfig, embedder: EmbeddingBackend, progress=None) -> UpdateSummary:
    """Create (or fully rebuild) the index from scratch."""
    pdf_dir = ensure_pdf_dir_available(config.pdf_dir)
    db_dir = Path(config.db_dir)
    if not db_dir.parent.exists():
        raise LocationUnavailableError(describe_unavailable(db_dir, "database"))

    store = get_store(config)
    manifest = Manifest(
        pdf_dir=str(pdf_dir),
        embedding_model=embedder.name,
        embedding_dim=embedder.dim,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
    )
    store.create(manifest)

    filenames = [p.name for p in list_pdfs(pdf_dir)]
    splitter = TokenSplitter(config.chunk_size, config.chunk_overlap)
    summary = UpdateSummary(added=filenames)
    summary.chunks_embedded = _embed_files(
        store, manifest, pdf_dir, filenames, embedder, splitter, progress
    )
    store.rebuild_fts()
    store.write_manifest(manifest)
    return summary


def open_for_query(config: AppConfig, embedder: EmbeddingBackend) -> tuple[IndexStore, Manifest]:
    """Open the configured index, verifying it matches the current settings."""
    store = get_store(config)
    manifest = store.open_existing()
    store.check_compatible(manifest, embedder, config.chunk_size, config.chunk_overlap)
    return store, manifest


def check_rebuild_needed(config: AppConfig, embedder_name: str) -> str | None:
    """Return a human-readable reason if the index needs a rebuild, else None.
    Does not need the embedding model loaded (compares names only)."""
    store = IndexStore(config.db_dir)
    if not Path(config.db_dir).exists():
        return None  # nothing there yet - first build, not a rebuild
    try:
        manifest = store.open_existing()
    except RebuildRequiredError as exc:
        return exc.reason
    except StoreError:
        # unavailable or legacy locations are reported elsewhere,
        # not as a rebuild prompt
        return None
    if manifest.embedding_model != embedder_name:
        return (
            f"the embedding backend changed (index: "
            f"'{manifest.embedding_model}', current: '{embedder_name}')."
        )
    if (manifest.chunk_size, manifest.chunk_overlap) != (
        config.chunk_size,
        config.chunk_overlap,
    ):
        return (
            f"the chunk settings changed (index: "
            f"{manifest.chunk_size}/{manifest.chunk_overlap}, current: "
            f"{config.chunk_size}/{config.chunk_overlap})."
        )
    return None


def estimate_rebuild_seconds(config: AppConfig) -> float:
    """files x observed embed rate; used when offering a rebuild."""
    try:
        n_files = len(list_pdfs(ensure_pdf_dir_available(config.pdf_dir)))
    except LocationUnavailableError:
        return 0.0
    rate = DEFAULT_SECONDS_PER_FILE
    store = get_store(config)
    if store.exists():
        try:
            manifest = store.open_existing()
            if manifest.avg_seconds_per_file:
                rate = manifest.avg_seconds_per_file
        except Exception:
            pass
    return n_files * rate


def update_index(config: AppConfig, embedder: EmbeddingBackend, progress=None) -> UpdateSummary:
    """Incremental update: embed only new/changed files, drop removed ones."""
    store, manifest = open_for_query(config, embedder)
    pdf_dir = ensure_pdf_dir_available(manifest.pdf_dir)

    on_disk = {p.name: p for p in list_pdfs(pdf_dir)}
    summary = UpdateSummary()

    for filename, path in on_disk.items():
        record = manifest.files.get(filename)
        if record is None:
            summary.added.append(filename)
            continue
        stat = path.stat()
        if stat.st_size == record.get("size") and stat.st_mtime == record.get("mtime"):
            continue  # cheap check says unchanged
        if content_hash(path) == record.get("sha256"):
            # touched but identical content: refresh the cheap fields only
            record["size"], record["mtime"] = stat.st_size, stat.st_mtime
        else:
            summary.changed.append(filename)

    summary.removed = [f for f in manifest.files if f not in on_disk]

    for filename in summary.changed + summary.removed:
        store.delete_source(filename)
    for filename in summary.removed:
        del manifest.files[filename]

    to_embed = summary.added + summary.changed
    summary.chunks_embedded = _embed_files(
        store, manifest, pdf_dir, to_embed, embedder,
        TokenSplitter(config.chunk_size, config.chunk_overlap), progress,
    )
    if not summary.nothing_to_do:
        store.rebuild_fts()
    store.write_manifest(manifest)
    return summary


def index_info(config: AppConfig) -> dict:
    """Manifest summary for 'info' displays; no embedding model needed."""
    store = get_store(config)
    manifest = store.open_existing()
    n_chunks = sum(rec.get("chunks", 0) for rec in manifest.files.values())
    return {
        "db_dir": store.location,
        "pdf_dir": manifest.pdf_dir,
        "pdf_dir_available": Path(manifest.pdf_dir).is_dir(),
        "embedding_model": manifest.embedding_model,
        "embedding_dim": manifest.embedding_dim,
        "chunk_size": manifest.chunk_size,
        "chunk_overlap": manifest.chunk_overlap,
        "documents": len(manifest.files),
        "chunks": n_chunks,
        "created_at": manifest.created_at,
        "updated_at": manifest.updated_at,
    }


def repoint_pdf_dir(config: AppConfig, new_pdf_dir: str) -> None:
    """After moving a library, confirm/update the PDF directory in the manifest."""
    store = get_store(config)
    manifest = store.open_existing()
    manifest.pdf_dir = str(ensure_pdf_dir_available(new_pdf_dir))
    store.write_manifest(manifest)


def query_index(
    config: AppConfig,
    embedder: EmbeddingBackend,
    question: str,
    reranker: Reranker | None = None,
) -> list[Passage]:
    """Hybrid retrieval (vector + BM25), optionally reranked; returns the
    final passages with source attribution. No LLM involved."""
    store, _manifest = open_for_query(config, embedder)
    qvec = embedder.embed_query(question)
    rows = store.search_hybrid(question, qvec, k=config.retrieve_k)
    passages = [
        Passage(
            text=row["text"],
            source=row["source"],
            page=int(row["page"]),
            score=float(row.get("_relevance_score") or row.get("_distance") or 0.0),
        )
        for row in rows
    ]
    if reranker and passages:
        passages = reranker.rerank(question, passages, top_n=config.final_n)
    else:
        passages = passages[: config.final_n]
    return passages
