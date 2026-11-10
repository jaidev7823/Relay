# SPDX-License-Identifier: AGPL-3.0-or-later
"""QdrantStore behaviour, tested against an in-memory Qdrant (no Docker)."""

from pathlib import Path

import pytest

from relevantr.ingest import Chunk
from relevantr.store import Manifest, QdrantStore, RebuildRequiredError


def make_store(tmp_path: Path) -> QdrantStore:
    from qdrant_client import QdrantClient

    return QdrantStore(
        collection="lib_test",
        data_dir=tmp_path,
        client=QdrantClient(":memory:"),
    )


def make_manifest(embedder) -> Manifest:
    return Manifest(
        pdf_dir=str(tmp_dir()),
        embedding_model=embedder.name,
        embedding_dim=embedder.dim,
        chunk_size=800,
        chunk_overlap=150,
    )


def tmp_dir():
    import tempfile

    return tempfile.gettempdir()


def make_chunks(source: str = "paper.pdf", n: int = 3) -> list[Chunk]:
    texts = [
        "Hydrogen lowers the diffusion barrier in zirconium alloys.",
        "Vacancy clusters form near the crack tip under load.",
        "The experiment used a 200 kV transmission electron microscope.",
    ]
    return [
        Chunk(text=texts[i % len(texts)], source=source, page=i + 1,
              chunk_id=f"{source}::p{i + 1}::c0")
        for i in range(n)
    ]


def test_create_add_count_roundtrip(tmp_path, fake_embedder):
    store = make_store(tmp_path)
    manifest = make_manifest(fake_embedder)
    store.create(manifest)

    chunks = make_chunks(n=3)
    vectors = fake_embedder.embed_documents([c.text for c in chunks])
    store.add_chunks(chunks, vectors)

    assert store.count_chunks() == 3
    # reopen by manifest
    reopened = store.open_existing()
    assert reopened.embedding_model == fake_embedder.name
    assert reopened.embedding_dim == fake_embedder.dim
    assert reopened.files == {}


def test_manifest_written_to_disk(tmp_path, fake_embedder):
    store = make_store(tmp_path)
    store.create(make_manifest(fake_embedder))
    assert store.manifest_path.exists()
    manifest = store.open_existing()
    manifest.files["paper.pdf"] = {"size": 1, "mtime": 2.0, "sha256": "x", "chunks": 3}
    store.write_manifest(manifest)
    assert store.open_existing().files["paper.pdf"]["chunks"] == 3


def test_delete_source_removes_only_that_file(tmp_path, fake_embedder):
    store = make_store(tmp_path)
    store.create(make_manifest(fake_embedder))

    chunks_a = make_chunks("a.pdf", 2)
    chunks_b = make_chunks("b.pdf", 2)
    all_chunks = chunks_a + chunks_b
    vectors = fake_embedder.embed_documents([c.text for c in all_chunks])
    store.add_chunks(all_chunks, vectors)
    assert store.count_chunks() == 4

    store.delete_source("a.pdf")
    assert store.count_chunks() == 2

    rows = store.search_hybrid("zirconium", fake_embedder.embed_query("zirconium"), 10)
    assert rows
    assert all(r["source"] == "b.pdf" for r in rows)


def test_search_hybrid_returns_rows_with_payload(tmp_path, fake_embedder):
    store = make_store(tmp_path)
    store.create(make_manifest(fake_embedder))

    chunks = make_chunks("smith2020.pdf", 3)
    vectors = fake_embedder.embed_documents([c.text for c in chunks])
    store.add_chunks(chunks, vectors)

    rows = store.search_hybrid(
        "vacancy clusters near the crack tip",
        fake_embedder.embed_query("vacancy clusters near the crack tip"),
        k=3,
    )
    assert rows
    top = rows[0]
    assert set(top) >= {"text", "source", "page", "chunk_id", "_relevance_score"}
    assert top["source"] == "smith2020.pdf"
    assert isinstance(top["page"], int)


def test_check_compatible_rejects_model_mismatch(tmp_path, fake_embedder):
    store = make_store(tmp_path)
    manifest = make_manifest(fake_embedder)
    store.check_compatible(manifest, fake_embedder, 800, 150)  # same settings

    class Other:
        name = "fake:other"
        dim = fake_embedder.dim

    from relevantr.store import EmbeddingMismatchError, RebuildRequiredError

    with pytest.raises(EmbeddingMismatchError):
        store.check_compatible(manifest, Other(), 800, 150)
    with pytest.raises(RebuildRequiredError):
        store.check_compatible(manifest, fake_embedder, 400, 100)


def test_open_existing_missing_manifest_raises(tmp_path):
    store = make_store(tmp_path)
    store.data_dir.mkdir(parents=True)  # dir exists, manifest missing
    with pytest.raises(RebuildRequiredError):
        store.open_existing()


def test_open_existing_missing_dir_raises(tmp_path):
    store = make_store(tmp_path)
    from relevantr.store import LocationUnavailableError

    with pytest.raises(LocationUnavailableError):
        store.open_existing()
