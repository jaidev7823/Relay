# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared dependencies: settings, config, embedder, stores, job runner.

Mirrors the GUI's lazy caching (embedder/reranker are expensive to load);
invalidation happens when settings change via PUT /config.
"""

from __future__ import annotations

import threading
from pathlib import Path

from relevantr import pipeline
from relevantr.config import AppConfig
from relevantr.embed import EmbeddingBackend, get_backend
from relevantr.rerank import Reranker
from relevantr.store import VectorStore, get_store

from . import chats as chats_db
from . import jobs as jobs_db
from . import keys_db
from . import projects as projects_db
from . import user_settings as user_settings_db
from . import users as users_db
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

    def store(self, config: AppConfig | None = None) -> VectorStore:
        return get_store(config or self.config)

    # -- projects ----------------------------------------------------------

    def user_providers(self, user_id: str) -> list[dict]:
        """Effective LLM provider list for the UI: preset metadata plus the
        base_url/model this user would actually use (their stored bucket,
        the operator default, or the preset default)."""
        from relevantr.config import LLM_PRESETS

        data = user_settings_db.get(self.jobs_db_path, user_id)
        buckets = data.get("llm_providers", {})
        default_provider = self.config.llm_provider

        def effective(provider_id: str, field: str, preset_value: str, global_value: str) -> str:
            bucket = buckets.get(provider_id, {})
            if bucket.get(field):
                return bucket[field]
            if provider_id == default_provider and global_value:
                return global_value
            return preset_value

        out = []
        for pid, preset in LLM_PRESETS.items():
            out.append({
                "id": pid,
                "label": preset.label,
                "env_var": preset.env_var,
                "needs_key": preset.needs_key,
                "note": preset.note,
                "base_url": effective(pid, "base_url", preset.base_url, self.config.llm_base_url),
                "default_model": effective(pid, "model", preset.default_model, self.config.llm_model),
            })
        return out

    def user_config(self, user_id: str) -> AppConfig:
        """Global config + the user's per-field overrides. Never persisted."""
        import dataclasses

        data = user_settings_db.get(self.jobs_db_path, user_id)
        active = data.get("llm_provider") or self.config.llm_provider

        kwargs: dict = {k: v for k, v in data.items()
                        if k in user_settings_db._SCALAR_FIELDS}

        from relevantr.config import LLM_PRESETS

        preset = LLM_PRESETS.get(active)
        bucket = data.get("llm_providers", {}).get(active, {})
        global_match = active == self.config.llm_provider

        kwargs["llm_base_url"] = (
            bucket.get("base_url")
            or (self.config.llm_base_url if global_match else None)
            or (preset.base_url if preset else None)
            or ""
        )
        kwargs["llm_model"] = (
            bucket.get("model")
            or (self.config.llm_model if global_match else None)
            or (preset.default_model if preset else None)
            or ""
        )
        kwargs["llm_provider"] = active

        return dataclasses.replace(self.config, **kwargs)

    def user_patch_settings(self, user_id: str, updates: dict) -> dict:
        return user_settings_db.patch(
            self.jobs_db_path, user_id, updates,
            default_provider=self.config.llm_provider,
        )

    # -- per-user API keys --------------------------------------------------

    def api_key_set(self, user_id: str, provider: str, plaintext: str) -> None:
        keys_db.set_key(self.jobs_db_path, self.settings.data_dir, user_id, provider, plaintext)

    def api_key_status(self, user_id: str, provider: str) -> tuple[bool, str]:
        import os

        from relevantr.config import GENERIC_KEY_ENV_VAR, LLM_PRESETS

        preset = LLM_PRESETS.get(provider)
        for var in ([preset.env_var] if preset else []) + [GENERIC_KEY_ENV_VAR]:
            if os.environ.get(var):
                return True, f"environment variable {var} (server-wide)"
        if keys_db.has_key(self.jobs_db_path, user_id, provider):
            return True, "stored in this account"
        return False, "not set"

    def api_key_resolve(self, user_id: str, provider: str) -> tuple[str | None, str]:
        """Effective key for a provider call: env override > per-user store."""
        import os

        from relevantr.config import GENERIC_KEY_ENV_VAR, LLM_PRESETS

        preset = LLM_PRESETS.get(provider)
        for var in ([preset.env_var] if preset else []) + [GENERIC_KEY_ENV_VAR]:
            value = os.environ.get(var)
            if value:
                return value, f"environment variable {var}"
        value = keys_db.get_key(self.jobs_db_path, self.settings.data_dir, user_id, provider)
        if value is not None:
            return value, "stored in this account"
        return None, "not set"

    def api_key_delete(self, user_id: str, provider: str) -> None:
        keys_db.delete_key(self.jobs_db_path, user_id, provider)

    def project_config(self, project: dict) -> AppConfig:
        """A copy of the global config pointed at the project's sources
        and its own Qdrant collection. Never persisted."""
        import dataclasses

        return dataclasses.replace(
            self.config,
            pdf_dir=project["pdf_dir"],
            qdrant_collection=project["qdrant_collection"],
        )

    def project(self, project_id: str, user_id: str) -> dict | None:
        row = projects_db.get(self.jobs_db_path, project_id)
        if row is None or row["user_id"] != user_id:
            return None
        return row

    def projects_list(self, user_id: str) -> list[dict]:
        return projects_db.list_for_user(self.jobs_db_path, user_id)

    def project_create(self, user_id: str, name: str) -> dict:
        return projects_db.create(
            self.jobs_db_path, self.settings.data_dir, user_id, name
        )

    def project_delete(self, project_id: str, user_id: str) -> bool:
        import dataclasses

        if self.project(project_id, user_id) is None:
            return False

        def cleanup(collection: str) -> None:
            import shutil as _shutil

            cfg = dataclasses.replace(self.config, qdrant_collection=collection)
            try:
                client = self.store(cfg)._get_client()  # noqa: SLF001
                client.delete_collection(collection)
            except Exception:
                pass
            _shutil.rmtree(
                Path(self.settings.data_dir) / "libraries" / collection,
                ignore_errors=True,
            )

        from .projects import delete as delete_project

        return delete_project(
            self.jobs_db_path, self.settings.data_dir, project_id,
            qdrant_cleanup=cleanup,
        )

    def init_jobs_db(self) -> None:
        jobs_db.init_db(self.jobs_db_path)
        # Any job left queued/running from a previous process is dead.
        jobs_db.interrupt_stale(self.jobs_db_path)
        chats_db.init_db(self.jobs_db_path)
        users_db.init_db(self.jobs_db_path)
        projects_db.init_db(self.jobs_db_path)
        keys_db.init_db(self.jobs_db_path)
        user_settings_db.init_db(self.jobs_db_path)
        users_db.purge_expired_sessions(self.jobs_db_path)
        # Pre-auth chats belong to the first registered user, not to everyone.
        first = users_db.first_user(self.jobs_db_path)
        if first:
            chats_db.assign_orphan_chats(self.jobs_db_path, first["id"])

    # -- jobs --------------------------------------------------------------

    def job(self, job_id: str) -> dict | None:
        return jobs_db.get_job(self.jobs_db_path, job_id)

    def jobs_list(self, limit: int = 50) -> list[dict]:
        return jobs_db.list_jobs(self.jobs_db_path, limit=limit)

    # -- chats -------------------------------------------------------------

    def list_chats(self, project_id: str, user_id: str | None = None) -> list[dict]:
        return chats_db.list_chats(self.jobs_db_path, project_id, user_id=user_id)

    def get_chat(self, chat_id: str) -> dict | None:
        return chats_db.get_chat(self.jobs_db_path, chat_id)

    def save_chat(self, chat_id: str, project_id: str, title: str | None, messages: list[dict],
                  user_id: str | None = None) -> dict | None:
        return chats_db.save_messages(self.jobs_db_path, chat_id, project_id, title, messages,
                                      user_id=user_id)

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
