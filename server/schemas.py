# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pydantic request/response models for the Phase 1 API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    qdrant: str
    version: str


class ConfigOut(BaseModel):
    pdf_dir: str
    db_dir: str
    vector_backend: str
    qdrant_url: str
    qdrant_collection: str
    embedding_backend: str
    chunk_size: int
    chunk_overlap: int
    retrieve_k: int
    final_n: int
    use_reranker: bool
    llm_enabled: bool
    llm_provider: str
    llm_base_url: str
    llm_model: str


class ConfigIn(BaseModel):
    """Fields the client may change. Vector backend/Qdrant/env-owned
    settings are read-only via the API (they come from the server env);
    unknown fields are rejected with 422 by the schema itself."""

    model_config = {"extra": "forbid"}

    pdf_dir: str | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=8000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=4000)
    retrieve_k: int | None = Field(default=None, ge=1, le=200)
    final_n: int | None = Field(default=None, ge=1, le=50)
    use_reranker: bool | None = None
    llm_enabled: bool | None = None
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None


class JobOut(BaseModel):
    id: str
    type: str
    status: str
    progress: float
    message: str | None = None
    error: str | None = None
    result: dict | None = None
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None


class JobListOut(BaseModel):
    jobs: list[JobOut]


class IndexInfoOut(BaseModel):
    db_dir: str
    pdf_dir: str
    pdf_dir_available: bool
    embedding_model: str
    embedding_dim: int
    chunk_size: int
    chunk_overlap: int
    documents: int
    chunks: int
    created_at: str
    updated_at: str


class DocumentOut(BaseModel):
    name: str
    state: str  # ready | new | embedding | failed
    chunks: int | None = None
    pages: int | None = None
    size: int | None = None


class DocumentListOut(BaseModel):
    pdf_dir: str
    pdf_dir_available: bool
    documents: list[DocumentOut]


class StartJobIn(BaseModel):
    pdf_dir: str | None = None


class PassageOut(BaseModel):
    text: str
    source: str
    page: int
    score: float


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    use_llm: bool | None = None  # None = follow config
    retrieve_k: int | None = Field(default=None, ge=1, le=200)
    final_n: int | None = Field(default=None, ge=1, le=50)


class QueryOut(BaseModel):
    question: str
    answer: str | None
    passages: list[PassageOut]
    mode: str  # "llm answer" | "retrieval only"


class LlmTestOut(BaseModel):
    ok: bool
    message: str


class LlmModelsOut(BaseModel):
    models: list[str]


class KeyStatusOut(BaseModel):
    provider: str
    set: bool
    source: str


class KeyIn(BaseModel):
    key: str


class ExportOut(BaseModel):
    filename: str
    content: str


class ChatMessageIn(BaseModel):
    id: str | None = None
    role: str
    content: str = ""
    sources: list[dict] | None = None
    error: str | None = None
    created_at: float | None = None


class ChatMessageOut(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    sources: list[dict] | None = None
    error: str | None = None
    created_at: float


class ChatSummaryOut(BaseModel):
    id: str
    project_id: str
    title: str
    created_at: float
    updated_at: float


class ChatOut(ChatSummaryOut):
    messages: list[ChatMessageOut] = []


class ChatSaveIn(BaseModel):
    project_id: str = "default"
    title: str | None = None
    messages: list[ChatMessageIn] = []


class ChatListOut(BaseModel):
    chats: list[ChatSummaryOut]


class UserOut(BaseModel):
    id: str
    username: str
    created_at: float


class RegisterIn(BaseModel):
    username: str
    password: str


class LoginIn(BaseModel):
    username: str
    password: str


class AuthOut(BaseModel):
    user: UserOut
