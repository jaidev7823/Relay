# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server settings, read from the environment (and .env).

Phase 1 keeps the desktop AppConfig for library settings (pdf_dir, chunk
sizes, retrieval tuning, LLM provider) and adds env-driven server options
around it: Qdrant location, data dir, and CORS origins. Provider API keys
stay in the OS keyring / env vars exactly like the desktop app.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()  # reads .env next to the repo root if present


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RELEVANTR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Local paths. DATA_DIR holds the SQLite job ledger and the manifests.
    data_dir: Path = Path("./data")

    # Qdrant connection (docker compose up -d qdrant)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "lib_default"

    # Embedding backend for the server (local needs the models cached).
    embedding_backend: str = "local"

    # Dev CORS: the Next.js dev server origin. Set to "" to disable CORS.
    cors_origins: str = "http://localhost:3000"

    # How often the UI may poll; informational only.
    job_poll_seconds: float = 1.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> ServerSettings:
    return ServerSettings()
