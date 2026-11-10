# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration and API-key handling for Relevantr.

The configuration is a plain JSON file in the platformdirs user-config
directory. API keys are never written to that file: they live in the OS
credential store (via ``keyring``) or in environment variables, with an
in-memory session fallback when no keyring backend is usable.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import platformdirs

APP_NAME = "Relevantr"
KEYRING_SERVICE = "relevantr"

logger = logging.getLogger(__name__)

# Embedding backends
LOCAL_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
GWDG_EMBEDDING_MODEL = "qwen3-embedding-4b"
GWDG_BASE_URL = "https://chat-ai.academiccloud.de/v1"

# Vector store defaults (server/backend config; desktop stays embedded)
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_QDRANT_COLLECTION = "lib_default"

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


@dataclass
class ProviderPreset:
    id: str
    label: str
    base_url: str
    default_model: str
    env_var: str
    needs_key: bool = True
    note: str = ""


LLM_PRESETS: dict[str, ProviderPreset] = {
    p.id: p
    for p in [
        ProviderPreset(
            id="gwdg",
            label="GWDG Chat AI",
            base_url=GWDG_BASE_URL,
            default_model="openai-gpt-oss-120b",
            env_var="GWDG_API_KEY",
            note="Free for German academic users (Academic Cloud / KISSKI).",
        ),
        ProviderPreset(
            id="openai",
            label="OpenAI",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o-mini",
            env_var="OPENAI_API_KEY",
        ),
        ProviderPreset(
            id="gemini",
            label="Google Gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            default_model="gemini-2.5-flash",
            env_var="GEMINI_API_KEY",
        ),
        ProviderPreset(
            id="ollama",
            label="Ollama (local)",
            base_url="http://localhost:11434/v1",
            default_model="llama3.1",
            env_var="OLLAMA_API_KEY",
            needs_key=False,
            note="Runs on your own machine; no API key needed.",
        ),
        ProviderPreset(
            id="custom",
            label="Custom (any OpenAI-compatible endpoint)",
            base_url="",
            default_model="",
            env_var="RELEVANTR_API_KEY",
        ),
    ]
}

GENERIC_KEY_ENV_VAR = "RELEVANTR_API_KEY"


def default_db_dir() -> str:
    return str(Path(platformdirs.user_data_dir(APP_NAME)) / "index")


def config_file_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME)) / "config.json"


@dataclass
class AppConfig:
    """All persisted settings. API keys are deliberately NOT part of this."""

    pdf_dir: str = ""
    db_dir: str = field(default_factory=default_db_dir)

    # Embeddings: "local" (sentence-transformers) or "gwdg" (Chat AI API)
    embedding_backend: str = "local"

    # Vector store: "lance" (embedded, desktop default) or "qdrant" (server).
    # When "qdrant", db_dir is the data_dir that holds the manifests, and
    # the vectors live in the Qdrant collection.
    vector_backend: str = "lance"
    qdrant_url: str = DEFAULT_QDRANT_URL
    qdrant_collection: str = "lib_default"
    qdrant_api_key: str = ""
    # Root for server-side state (SQLite jobs, manifests). Empty = use db_dir.
    data_dir: str = ""

    # Chunking (token counts)
    chunk_size: int = 800
    chunk_overlap: int = 150

    # Retrieval
    retrieve_k: int = 30
    final_n: int = 8
    use_reranker: bool = True

    # LLM answer layer (default OFF: retrieval-only)
    llm_enabled: bool = False
    llm_provider: str = "gwdg"
    llm_base_url: str = GWDG_BASE_URL
    llm_model: str = "openai-gpt-oss-120b"

    def save(self, path: Path | None = None) -> Path:
        path = path or config_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or config_file_path()
        cfg = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cfg
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in known:
                setattr(cfg, key, value)
        return cfg


# ---------------------------------------------------------------------------
# API keys: env var > keyring > session-only memory
# ---------------------------------------------------------------------------

_session_keys: dict[str, str] = {}


def _keyring_usable() -> bool:
    try:
        import keyring
        import keyring.backends.fail

        backend = keyring.get_keyring()
        return not isinstance(backend, keyring.backends.fail.Keyring)
    except Exception:
        return False


def resolve_api_key(provider_id: str) -> tuple[str | None, str]:
    """Return (key, source) for a provider; source describes where it came from."""
    preset = LLM_PRESETS.get(provider_id)
    env_vars = []
    if preset:
        env_vars.append(preset.env_var)
    if GENERIC_KEY_ENV_VAR not in env_vars:
        env_vars.append(GENERIC_KEY_ENV_VAR)
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            return value, f"environment variable {var}"
    if _keyring_usable():
        try:
            import keyring

            value = keyring.get_password(KEYRING_SERVICE, provider_id)
            if value:
                return value, "system keyring"
        except Exception as exc:
            logger.warning("Keyring lookup failed: %s", exc)
    value = _session_keys.get(provider_id)
    if value:
        return value, "this session only"
    return None, "not set"


def store_api_key(provider_id: str, key: str) -> str:
    """Store a key; returns a human-readable note on where it was stored."""
    key = key.strip()
    if not key:
        return delete_api_key(provider_id)
    if _keyring_usable():
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, provider_id, key)
            return "Stored in the system keyring."
        except Exception as exc:
            logger.warning("Keyring store failed: %s", exc)
    _session_keys[provider_id] = key
    return (
        "No usable system keyring found - the key is kept for this session "
        "only and must be re-entered next launch."
    )


def delete_api_key(provider_id: str) -> str:
    _session_keys.pop(provider_id, None)
    if _keyring_usable():
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, provider_id)
        except Exception:
            pass
    return "Key removed."
