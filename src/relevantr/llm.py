# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional LLM answer layer over one OpenAI-compatible client.

The app is retrieval-only by default; when the user enables an LLM answer,
whichever provider is configured (GWDG Chat AI, OpenAI, Google Gemini,
Ollama, or any custom OpenAI-compatible endpoint) is reached through the
``openai`` package with a custom base URL. The strict source-attribution
prompt is carried over from v1.
"""

from __future__ import annotations

import logging

from .config import LLM_PRESETS, AppConfig, resolve_api_key
from .rerank import Passage

logger = logging.getLogger(__name__)


def build_context(passages: list[Passage]) -> tuple[str, str]:
    """Return (context block, source list) in the v1 structured format."""
    parts = []
    unique_sources = set()
    for i, p in enumerate(passages):
        context_id = f"CONTEXT_ITEM_{i + 1}"
        display_source = f"{p.source} (Page: {p.page})"
        unique_sources.add(display_source)
        parts.append(
            f"--- START {context_id}: Source File: {display_source} ---\n"
            f"{p.text}\n"
            f"--- END {context_id} ---"
        )
    context = "\n\n".join(parts)
    source_list = "Full Source References:\n" + "\n".join(sorted(unique_sources))
    return context, source_list


def build_prompt(question: str, passages: list[Passage]) -> str:
    """The strict source-attribution prompt from Relevantr v1."""
    context, sources = build_context(passages)
    return f"""
You are an AI assistant specialized in scientific document analysis. Your task is to answer the user's question STRICTLY by referencing the provided document excerpts.

**CRITICAL INSTRUCTIONS:**
1. For EVERY piece of information you provide, you MUST identify its source
2. Format your answer with explicit source attribution
3. Include direct quotes or very close paraphrases from the source material
4. If information is not present in the provided context, clearly state that

**Desired Format:**
Start with a brief overview, then for each specific point:
- State the source: "According to [filename] (Page: X)..."
- Include the relevant information: "The document states: '[quote or paraphrase]'"
- Continue with additional sources as needed

**Context Information:**
{context}

---
**User Question:** {question}

Please provide a comprehensive, well-attributed answer based ONLY on the provided context.

{sources}
"""


class LLMError(Exception):
    """User-facing LLM/provider error."""


# Sentinel: the caller did not pass an explicit key -> resolve the default
# way (env vars / keyring), so desktop behavior is unchanged. Passing an
# explicit ``api_key=None`` means "no key" (only OK for keyless providers).
_USE_RESOLVER = object()


class LLMClient:
    def __init__(self, base_url: str, api_key: str | None, model: str, client=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        if client is not None:
            self._client = client
        else:
            from openai import OpenAI

            # Some OpenAI-compatible servers (e.g. Ollama) need no key, but
            # the client requires a non-empty string.
            self._client = OpenAI(base_url=self.base_url, api_key=api_key or "none")

    @classmethod
    def from_config(cls, config: AppConfig, client=None, api_key=_USE_RESOLVER,
                    key_source: str = "provided") -> "LLMClient":
        preset = LLM_PRESETS.get(config.llm_provider)
        if api_key is _USE_RESOLVER:
            # Desktop path: env var > keyring > session memory.
            api_key, key_source = resolve_api_key(config.llm_provider)
        if api_key is None and preset is not None and preset.needs_key:
            raise LLMError(
                f"No API key found for provider '{preset.label}'. Enter one in "
                f"Settings, or set the {preset.env_var} (or RELEVANTR_API_KEY) "
                "environment variable."
            )
        logger.info("LLM provider %s, key from %s", config.llm_provider, key_source)
        return cls(
            base_url=config.llm_base_url,
            api_key=api_key,
            model=config.llm_model,
            client=client,
        )

    def list_models(self) -> list[str]:
        """Model ids from GET /v1/models; raises if the endpoint is missing."""
        models = self._client.models.list()
        return sorted(m.id for m in models.data)

    def test_connection(self) -> tuple[bool, str]:
        try:
            models = self.list_models()
            return True, f"Connected - {len(models)} models available."
        except Exception as exc:
            return False, f"Connection failed: {exc}"

    def answer(self, question: str, passages: list[Passage]) -> str:
        prompt = build_prompt(question, passages)
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
        except Exception as exc:
            raise LLMError(f"The LLM request failed: {exc}") from exc
        return response.choices[0].message.content or ""


def check_base_url_reachable(base_url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Simple connectivity check for the configured API base URL."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        return False, f"'{base_url}' is not a valid URL."
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} is reachable."
    except OSError as exc:
        return False, f"Cannot reach {host}:{port} ({exc})."
