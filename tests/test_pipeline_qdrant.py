# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pipeline end-to-end against the Qdrant backend (in-memory Qdrant client).

Proves build/update/query work unchanged when vector_backend="qdrant", i.e.
the store refactor kept the pipeline backend-agnostic.
"""

from relevantr import pipeline
from relevantr.config import AppConfig
from relevantr.store import Manifest


def make_config(tmp_path, **overrides) -> AppConfig:
    from qdrant_client import QdrantClient

    # One client shared per store instance would be ideal; here we inject via
    # a patched factory that hands out separate :memory: clients per store,
    # because in-memory Qdrant state lives inside the client object.
    cfg = AppConfig(
        pdf_dir=str(tmp_path / "pdfs"),
        vector_backend="qdrant",
        qdrant_collection="lib_e2e",
        db_dir=str(tmp_path / "db"),
        data_dir=str(tmp_path / "db"),
        embedding_backend="fake",
        use_reranker=False,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    cfg.pdf_dir = str(tmp_path / "pdfs")
    return cfg


def test_build_and_query_with_qdrant(tmp_path, fake_embedder, monkeypatch):
    from pathlib import Path

    from qdrant_client import QdrantClient

    pdfs = Path(tmp_path) / "pdfs"
    pdfs.mkdir(parents=True)
    from tests.conftest import make_pdf

    make_pdf(pdfs / "one.pdf", ["The zirconium alloy resists corrosion.",
                                 "Hydrogen diffuses into the lattice."])
    make_pdf(pdfs / "two.pdf", ["Vacancy clusters form near crack tips."])

    # Share one in-memory Qdrant across all store instances the pipeline opens.
    shared = QdrantClient(":memory:")

    import relevantr.store as store_pkg

    real_get = store_pkg.get_store

    def patched_get(config):
        s = real_get(config)
        s._client = shared
        return s

    monkeypatch.setattr(store_pkg, "get_store", patched_get)
    monkeypatch.setattr(pipeline, "get_store", patched_get)

    config = make_config(tmp_path)

    summary = pipeline.build_index(config, fake_embedder)
    assert summary.chunks_embedded >= 2
    assert len(summary.added) == 2

    passages = pipeline.query_index(config, fake_embedder, "zirconium corrosion")
    assert passages
    assert passages[0].source == "one.pdf"

    # incremental: add a file, nothing re-embedded for old ones
    from tests.conftest import SpyEmbedder

    make_pdf(pdfs / "three.pdf", ["Neutron irradiation hardens the material."])
    spy = SpyEmbedder()
    summary = pipeline.update_index(config, spy)
    assert summary.added == ["three.pdf"]
    assert all("irradiation" in t for t in spy.embedded_texts)

    passages = pipeline.query_index(config, fake_embedder, "neutron irradiation")
    assert passages and passages[0].source == "three.pdf"

    info = pipeline.index_info(config)
    assert info["documents"] == 3
    assert info["embedding_model"] == fake_embedder.name


def test_df_filter_drops_corpus_common_tokens(tmp_path):
    """Sparse-lane query strips corpus-common words, keeps rare identifiers."""
    import uuid

    from qdrant_client import QdrantClient, models
    from relevantr.store.qdrant import QdrantStore, _tokenize

    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name="dftest",
        vectors_config={"dense": models.VectorParams(size=4, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))},
    )
    # 9 chunks mention "price", exactly 1 mentions "CA5-10"
    texts = [f"Electrification products price list page {i}" for i in range(9)]
    texts.append("Front mounted single pole add-on blocks CA5-10 1SBN010010R1010 350")
    for i, t in enumerate(texts):
        client.upsert(
            collection_name="dftest",
            points=[models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"chunk-{i}")),
                vector={"dense": [1.0, 0.0, 0.0, 0.0]},
                payload={"text": t, "source": "x.pdf", "page": i + 1, "chunk_id": f"c-{i}"},
            )],
        )

    store = QdrantStore("dftest", tmp_path, client=client)
    df, total = store._df_stats()
    assert total == 10
    assert df["price"] == 9

    filtered = store._filtered_query("CA5-10 price")
    tokens = _tokenize(filtered)
    assert "price" not in tokens
    assert "ca5-10" in tokens

    # corpus grabs everything -> fall back, never return empty
    assert store._filtered_query("price price price") != ""
