# SPDX-License-Identifier: AGPL-3.0-or-later
"""LLM layer: prompt assembly, and the retrieval-only path with a mock client."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from relevantr.config import AppConfig
from relevantr.llm import LLMClient, build_prompt
from relevantr.rerank import Passage

PASSAGES = [
    Passage("Hydrogen lowers the barrier.", "smith2020.pdf", 4),
    Passage("Vacancies cluster near the tip.", "jones2021.pdf", 12),
]


def test_prompt_contains_question_context_and_sources():
    prompt = build_prompt("What does hydrogen do?", PASSAGES)
    assert "What does hydrogen do?" in prompt
    assert "smith2020.pdf (Page: 4)" in prompt
    assert "jones2021.pdf (Page: 12)" in prompt
    assert "Hydrogen lowers the barrier." in prompt
    assert "CONTEXT_ITEM_1" in prompt and "CONTEXT_ITEM_2" in prompt
    assert "STRICTLY" in prompt  # the strict v1 attribution instructions
    assert "[n]" in prompt  # inline citation markers are the attribution mechanism
    assert "Full Source References:" not in prompt  # attribution is inline [n], not a sources block


def make_mock_client(answer="mocked answer"):
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]
    )
    client.models.list.return_value = SimpleNamespace(
        data=[SimpleNamespace(id="model-b"), SimpleNamespace(id="model-a")]
    )
    return client


def test_answer_uses_mocked_client():
    mock = make_mock_client()
    llm = LLMClient(base_url="http://example.invalid/v1", api_key="k",
                    model="test-model", client=mock)
    answer = llm.answer("What does hydrogen do?", PASSAGES)
    assert answer == "mocked answer"
    call = mock.chat.completions.create.call_args
    assert call.kwargs["model"] == "test-model"
    sent_prompt = call.kwargs["messages"][0]["content"]
    assert "smith2020.pdf (Page: 4)" in sent_prompt


def test_list_models_sorted():
    llm = LLMClient(base_url="http://example.invalid/v1", api_key="k",
                    model="m", client=make_mock_client())
    assert llm.list_models() == ["model-a", "model-b"]


def test_retrieval_only_path_never_calls_llm(tmp_path, fake_embedder):
    """With llm_enabled False, query_index returns passages and no LLM client
    is ever involved."""
    from relevantr import pipeline
    from relevantr.ingest import Chunk
    from relevantr.store import IndexStore, Manifest

    store = IndexStore(tmp_path / "db")
    manifest = Manifest(
        pdf_dir=str(tmp_path), embedding_model=fake_embedder.name,
        embedding_dim=fake_embedder.dim, chunk_size=800, chunk_overlap=150,
    )
    store.create(manifest)
    chunks = [Chunk("The zirconium result is planted here.", "z.pdf", 7,
                    "z.pdf::p7::c0")]
    store.add_chunks(chunks, fake_embedder.embed_documents([c.text for c in chunks]))
    store.rebuild_fts()

    config = AppConfig(db_dir=str(tmp_path / "db"), llm_enabled=False,
                       use_reranker=False)
    passages = pipeline.query_index(config, fake_embedder, "zirconium result")
    assert passages
    assert passages[0].source == "z.pdf"
    assert passages[0].page == 7
