# SPDX-License-Identifier: AGPL-3.0-or-later
"""LLM provider helpers for the API layer."""

from __future__ import annotations

from relevantr.config import AppConfig
from relevantr.llm import LLMClient


def test_connection(config: AppConfig) -> tuple[bool, str]:
    """Ping the configured provider without needing our pipeline."""
    client = LLMClient.from_config(config)
    return client.test_connection()


def list_models(config: AppConfig) -> list[str]:
    client = LLMClient.from_config(config)
    return client.list_models()
