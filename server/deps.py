# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared dependencies: settings, config, embedder, stores, job runner.

Mirrors the GUI's lazy caching (embedder/reranker are expensive to load);
invalidation happens when settings change via PUT /config.
"""

from __future__ import annotations

import threading

from relevantr import pipeline
from relevantr.config import AppConfig
from relevantr.embed import EmbeddingBackend, get_backend
from relevantr.rerank import Reranker
from relevantr.store import VectorStore, get_store

from . import chats as chats_db
from . import jobs as jobs_db
from .ingest_jobs import JobRunner
from .settings import get_settings


class State:
    """Process-wide singletons for the Phase 1 server."""

    def __init__(self):
        self.settings = get_settings()
        self.config = self._load_config()
        self._embedder: EmbeddingBackend | None = None
        self._reranker: Reranker | None = None
        self._embed_lock = threading.Lock()
        self.jobs_db_path = self.settings.data_dir / "jobs.db"
        self.job_runner = JobRunner(
            self.jobs_db_path, self.config, embedder_factory=lambda: self.embedder()
        )

    def _load_config(self) -> AppConfig:
        """Load the desktop AppConfig, then apply server env overrides.

        The env wins for the fields the server owns (Qdrant location,
        data dir) so the same ~/.config JSON can serve both app modes.
        """
        config = AppConfig.load()
        settings = self.settings
        config.vector_backend = "qdrant"
        config.qdrant_url = settings.qdrant_url
        config.qdrant_collection = settings.qdrant_collection
        config.qdrant_api_key = settings.qdrant_api_key
        config.data_dir = str(settings.data_dir)
        config.db_dir = str(settings.data_dir)
        if settings.embedding_backend:
            config.embedding_backend = settings.embedding_backend
        return config

    def reload_config(self) -> None:
        """Re-read config.json and apply env overrides; drops cached models."""
        self.config = self._load_config()
        self._embedder = None
        self._reranker = None
        self.job_runner.config = self.config

    # -- models ------------------------------------------------------------

    def embedder(self) -> EmbeddingBackend:
        if self._embedder is None:
            with self._embed_lock:
                if self._embedder is None:
                    self._embedder = get_backend(self.config)
        return self._embedder

    def reranker(self) -> Reranker | None:
        if self.config.use_reranker and self._reranker is None:
            self._reranker = Reranker()
        return self._reranker if self.config.use_reranker else None

    def invalidate_models(self) -> None:
        self._embedder = None
        self._reranker = None

    # -- stores ------------------------------------------------------------

    def store(self) -> VectorStore:
        return get_store(self.config)

    def init_jobs_db(self) -> None:
        jobs_db.init_db(self.jobs_db_path)
        chats_db.init_db(self.jobs_db_path)

    # -- jobs --------------------------------------------------------------

    def job(self, job_id: str) -> dict | None:
        return jobs_db.get_job(self.jobs_db_path, job_id)

    def jobs_list(self, limit: int = 50) -> list[dict]:
        return jobs_db.list_jobs(self.jobs_db_path, limit=limit)

    # -- chats -------------------------------------------------------------

    def list_chats(self, project_id: str) -> list[dict]:
        return chats_db.list_chats(self.jobs_db_path, project_id)

    def get_chat(self, chat_id: str) -> dict | None:
        return chats_db.get_chat(self.jobs_db_path, chat_id)

    def save_chat(self, chat_id: str, project_id: str, title: str | None, messages: list[dict]) -> dict | None:
        return chats_db.save_messages(self.jobs_db_path, chat_id, project_id, title, messages)

    def delete_chat(self, chat_id: str) -> bool:
        return chats_db.delete_chat(self.jobs_db_path, chat_id)


_state: State | None = None
_state_lock = threading.Lock()


def get_state() -> State:
    global _state
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = State()
    return _state
