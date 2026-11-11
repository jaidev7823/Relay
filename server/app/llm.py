# SPDX-License-Identifier: AGPL-3.0-or-later
"""LLM provider helpers for the API layer."""

from __future__ import annotations

from relevantr.config import AppConfig
from relevantr.llm import LLMClient


def _client(config: AppConfig, user_id: str | None) -> LLMClient:
    if not user_id:
        return LLMClient.from_config(config)
    from ..deps import get_state

    st = get_state()
    api_key, key_source = st.api_key_resolve(user_id, config.llm_provider)
    return LLMClient.from_config(config, api_key=api_key, key_source=key_source)


def test_connection(config: AppConfig, user_id: str | None = None) -> tuple[bool, str]:
    """Ping the configured provider without needing our pipeline."""
    client = _client(config, user_id)
    return client.test_connection()


def list_models(config: AppConfig, user_id: str | None = None) -> list[str]:
    client = _client(config, user_id)
    return client.list_models()
