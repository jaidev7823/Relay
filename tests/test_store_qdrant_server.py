# SPDX-License-Identifier: AGPL-3.0-or-later
"""QdrantStore against a real local Qdrant server (docker compose up -d qdrant).

Skipped unless QDRANT_URL is reachable, so CI without Docker still passes.
"""

from pathlib import Path

import pytest

from relevantr.store import QdrantStore

pytestmark = pytest.mark.skipif(
    not _qdrant_reachable(), reason="local Qdrant not running"
) if False else None  # resolved below


def _qdrant_reachable(url: str = "http://localhost:6333") -> bool:
    try:
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6333
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


from relevantr.ingest import Chunk  # noqa: E402
from relevantr.store import Manifest  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _qdrant_reachable(), reason="local Qdrant server not running"
)


def test_real_server_roundtrip(tmp_path, fake_embedder):
    store = QdrantStore(collection="lib_itest", data_dir=tmp_path,
                        url="http://localhost:6333")
    manifest = Manifest(
        pdf_dir=str(tmp_path),
        embedding_model=fake_embedder.name,
        embedding_dim=fake_embedder.dim,
        chunk_size=800,
        chunk_overlap=150,
    )
    store.create(manifest)
    try:
        chunks = [
            Chunk(text="Hydrogen embrittlement of zirconium occurs via diffusion.",
                  source="h.pdf", page=1, chunk_id="h.pdf::p1::c0"),
            Chunk(text="Vacancy clustering drives crack growth at the tip.",
                  source="h.pdf", page=2, chunk_id="h.pdf::p2::c0"),
            Chunk(text="The furnace reached 1800 degrees celsius today.",
                  source="h.pdf", page=3, chunk_id="h.pdf::p3::c0"),
        ]
        vectors = fake_embedder.embed_documents([c.text for c in chunks])
        store.add_chunks(chunks, vectors)
        assert store.count_chunks() == 3

        rows = store.search_hybrid(
            "vacancy clustering crack",
            fake_embedder.embed_query("vacancy clustering crack"),
            k=2,
        )
        assert rows
        assert rows[0]["source"] == "h.pdf"
        assert rows[0]["page"] == 2

        store.delete_source("h.pdf")
        assert store.count_chunks() == 0
    finally:
        from qdrant_client import QdrantClient

        client = QdrantClient(url="http://localhost:6333")
        if client.collection_exists("lib_itest"):
            client.delete_collection("lib_itest")
