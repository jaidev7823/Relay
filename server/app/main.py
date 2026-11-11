# SPDX-License-Identifier: AGPL-3.0-or-later
"""Relevantr Phase 1 API: the desktop pipeline over HTTP.

Run locally:
    uvicorn server.app.main:app --reload --port 8000
Interactive docs: http://localhost:8000/docs

Nothing here is deployed anywhere: this runs on the same machine as the
PDF folder, the local models, and the Qdrant Docker container.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from relevantr import __version__ as core_version, pipeline
from relevantr.config import LLM_PRESETS, resolve_api_key, store_api_key
from relevantr.llm import LLMClient, LLMError
from relevantr.store import StoreError

from .. import __version__ as server_version
from ..deps import State, get_state
from ..ingest_jobs import JobConflictError
from ..schemas import (
    ChatListOut,
    ChatOut,
    ChatSaveIn,
    ChatSummaryOut,
    ConfigIn,
    ConfigOut,
    DocumentListOut,
    DocumentOut,
    ExportOut,
    HealthOut,
    IndexInfoOut,
    JobListOut,
    JobOut,
    KeyIn,
    KeyStatusOut,
    LlmModelsOut,
    LlmTestOut,
    ProjectCreateIn,
    ProjectListOut,
    ProjectOut,
    QueryIn,
    QueryOut,
    StartJobIn,
)
from . import keys, llm
from .auth import current_user, require_user, router as auth_router

logger = logging.getLogger(__name__)


def state() -> State:
    return get_state()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    get_state().init_jobs_db()
    logger.info("Relevantr server %s (core %s) ready", server_version, core_version)
    yield


app = FastAPI(
    title="Relevantr API",
    description=(
        "Scientific PDF RAG: index a PDF folder into Qdrant and query it "
        "with optional LLM answers and strict source attribution. "
        "Phase 1 = local machine, single user, no auth."
    ),
    version=server_version,
    lifespan=lifespan,
)

_settings = get_state().settings
if _settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ------------------------------------------------------------------ auth guard
#
# Everything under /api requires a logged-in session, except the auth
# endpoints themselves and the health check. The authenticated user is
# attached to request.state.user for downstream dependencies.

_OPEN_PATHS = ("/api/health",)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/auth/"):
        if path not in _OPEN_PATHS:
            user = current_user(request)
            if user is None:
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            request.state.user = user
    return await call_next(request)


app.include_router(auth_router)


# --------------------------------------------------------------------- health


@app.get("/api/health", response_model=HealthOut, tags=["system"])
def health(st: State = Depends(state)) -> HealthOut:
    qdrant = _qdrant_status(st)
    return HealthOut(status="ok", qdrant=qdrant, version=core_version)


def _qdrant_status(st: State) -> str:
    try:
        store = st.store()
        client = store._get_client()  # noqa: SLF001 - diagnostic endpoint
        client.get_collections()
        return "ok"
    except Exception as exc:
        return f"unreachable: {exc}"


# --------------------------------------------------------------------- config

_SAFE_CONFIG_FIELDS = (
    "pdf_dir", "chunk_size", "chunk_overlap", "retrieve_k", "final_n",
    "use_reranker", "llm_enabled", "llm_provider", "llm_base_url", "llm_model",
)


@app.get("/api/config", response_model=ConfigOut, tags=["system"])
def get_config(st: State = Depends(state)) -> ConfigOut:
    c = st.config
    return ConfigOut(
        pdf_dir=c.pdf_dir,
        db_dir=c.db_dir,
        vector_backend=c.vector_backend,
        qdrant_url=c.qdrant_url,
        qdrant_collection=c.qdrant_collection,
        embedding_backend=c.embedding_backend,
        chunk_size=c.chunk_size,
        chunk_overlap=c.chunk_overlap,
        retrieve_k=c.retrieve_k,
        final_n=c.final_n,
        use_reranker=c.use_reranker,
        llm_enabled=c.llm_enabled,
        llm_provider=c.llm_provider,
        llm_base_url=c.llm_base_url,
        llm_model=c.llm_model,
    )


@app.put("/api/config", response_model=ConfigOut, tags=["system"])
def put_config(body: ConfigIn, st: State = Depends(state)) -> ConfigOut:
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    changed_backend = any(
        f in updates for f in ("chunk_size", "chunk_overlap")
    )
    for field, value in updates.items():
        if field not in _SAFE_CONFIG_FIELDS:
            raise HTTPException(400, f"field '{field}' is not settable here")
        setattr(st.config, field, value)
    st.config.save()
    if changed_backend:
        st.invalidate_models()
    return get_config(st)


# --------------------------------------------------------------------- index


@app.post("/api/index/build", response_model=JobOut, tags=["index"])
def build_index(body: StartJobIn | None = None,
                user: dict = Depends(require_user),
                st: State = Depends(state)) -> JobOut:
    project = _require_project(st, user, body.project_id if body else None)
    return _start_job(st, "build", body.pdf_dir if body else None, project)


@app.post("/api/index/update", response_model=JobOut, tags=["index"])
def update_index(body: StartJobIn | None = None,
                 user: dict = Depends(require_user),
                 st: State = Depends(state)) -> JobOut:
    project = _require_project(st, user, body.project_id if body else None)
    return _start_job(st, "update", body.pdf_dir if body else None, project)


@app.post("/api/index/rebuild", response_model=JobOut, tags=["index"])
def rebuild_index(body: StartJobIn | None = None,
                  user: dict = Depends(require_user),
                  st: State = Depends(state)) -> JobOut:
    project = _require_project(st, user, body.project_id if body else None)
    return _start_job(st, "rebuild", body.pdf_dir if body else None, project)


def _require_project(st: State, user: dict, project_id: str | None) -> dict | None:
    if not project_id:
        return None
    project = st.project(project_id, user["id"])
    if project is None:
        raise HTTPException(404, f"project '{project_id}' not found")
    return project


def _start_job(st: State, job_type: str, pdf_dir: str | None,
               project: dict | None = None) -> JobOut:
    import copy
    import pathlib

    config = None
    if project:
        config = st.project_config(project)
        pdf_dir = project["pdf_dir"]
    elif pdf_dir:
        if not pathlib.Path(pdf_dir).is_dir():
            raise HTTPException(400, f"pdf_dir '{pdf_dir}' does not exist")
    try:
        job = st.job_runner.start(job_type, pdf_dir=pdf_dir, config=config)
    except JobConflictError as exc:
        raise HTTPException(409, str(exc))
    return JobOut(**job)


@app.get("/api/index/info", response_model=IndexInfoOut, tags=["index"])
def index_info(project_id: str | None = None, user: dict = Depends(require_user),
               st: State = Depends(state)) -> IndexInfoOut:
    config = st.config
    if project_id:
        project = _require_project(st, user, project_id)
        config = st.project_config(project)
    try:
        info = pipeline.index_info(config)
    except StoreError as exc:
        raise HTTPException(404, str(exc))
    return IndexInfoOut(**info)


@app.get("/api/index/documents", response_model=DocumentListOut, tags=["index"])
def index_documents(project_id: str | None = None, user: dict = Depends(require_user),
                    st: State = Depends(state)) -> DocumentListOut:
    import pathlib
    from relevantr.ingest import list_pdfs

    config = st.config
    if project_id:
        project = _require_project(st, user, project_id)
        config = st.project_config(project)

    pdf_dir = pathlib.Path(config.pdf_dir) if config.pdf_dir else None
    available = bool(pdf_dir and pdf_dir.is_dir())

    manifest_files: dict = {}
    try:
        store = st.store(config)
        manifest = store.open_existing()
        manifest_files = manifest.files or {}
    except StoreError:
        manifest_files = {}

    active = st.job_runner.active_job()
    active_msg = (active or {}).get("message") or ""

    docs: list[DocumentOut] = []
    seen = set()

    # Indexed / known files
    for name, rec in sorted(manifest_files.items()):
        seen.add(name)
        state = "ready"
        if active and active.get("status") in ("queued", "running") and name in active_msg:
            state = "embedding"
        docs.append(DocumentOut(
            name=name,
            state=state,
            chunks=rec.get("chunks"),
            pages=None,
            size=rec.get("size"),
        ))

    # PDFs in folder but not in manifest
    if available and pdf_dir:
        for p in list_pdfs(pdf_dir):
            if p.name in seen:
                continue
            state = "new"
            if active and active.get("status") in ("queued", "running") and p.name in active_msg:
                state = "embedding"
            try:
                size = p.stat().st_size
            except OSError:
                size = None
            docs.append(DocumentOut(name=p.name, state=state, chunks=None, pages=None, size=size))

    return DocumentListOut(
        pdf_dir=str(pdf_dir) if pdf_dir else "",
        pdf_dir_available=available,
        documents=docs,
    )


# ---------------------------------------------------------------------- jobs


@app.get("/api/jobs", response_model=JobListOut, tags=["index"])
def list_jobs(st: State = Depends(state)) -> JobListOut:
    return JobListOut(jobs=[JobOut(**j) for j in st.jobs_list()])


@app.get("/api/jobs/{job_id}", response_model=JobOut, tags=["index"])
def get_job(job_id: str, st: State = Depends(state)) -> JobOut:
    job = st.job(job_id)
    if job is None:
        raise HTTPException(404, f"job '{job_id}' not found")
    return JobOut(**job)


# --------------------------------------------------------------------- query


@app.post("/api/query", response_model=QueryOut, tags=["query"])
async def query(body: QueryIn, user: dict = Depends(require_user),
                st: State = Depends(state)) -> QueryOut:
    """Hybrid retrieval (+ optional LLM answer). Runs in a worker thread
    because embedding and reranking are CPU-bound."""
    import anyio
    import copy

    if body.project_id:
        project = _require_project(st, user, body.project_id)
        config = st.project_config(project)
        persist = False
    else:
        config = st.config
        persist = True

    if body.use_llm is not None:
        config.llm_enabled = body.use_llm  # request-level override only
    if body.retrieve_k is not None:
        config.retrieve_k = body.retrieve_k
    if body.final_n is not None:
        config.final_n = body.final_n

    def work():
        return _run_query(config, body.question)

    try:
        passages, answer = await anyio.to_thread.run_sync(work)
    except StoreError as exc:
        raise HTTPException(409, str(exc))
    except LLMError as exc:
        raise HTTPException(502, f"LLM request failed: {exc}")
    finally:
        if persist:
            config.save()  # persist any overrides (global config only)

    mode = "llm answer" if answer else "retrieval only"
    return QueryOut(
        question=body.question,
        answer=answer,
        passages=[
            {"text": p.text, "source": p.source, "page": p.page, "score": p.score}
            for p in passages
        ],
        mode=mode,
    )


def _run_query(config, question: str):
    from relevantr.rerank import Passage

    from ..deps import get_state

    st = get_state()
    reranker = st.reranker()
    passages = pipeline.query_index(config, st.embedder(), question,
                                    reranker=reranker)
    answer = None
    if config.llm_enabled and passages:
        client = LLMClient.from_config(config)
        answer = client.answer(question, passages)
    return passages, answer


# ------------------------------------------------------------------- projects


@app.post("/api/projects", response_model=ProjectOut, tags=["projects"],
          status_code=201)
def create_project(body: ProjectCreateIn, user: dict = Depends(require_user),
                   st: State = Depends(state)) -> ProjectOut:
    return ProjectOut(**st.project_create(user["id"], body.name))


@app.get("/api/projects", response_model=ProjectListOut, tags=["projects"])
def list_projects(user: dict = Depends(require_user),
                  st: State = Depends(state)) -> ProjectListOut:
    return ProjectListOut(projects=[ProjectOut(**p) for p in st.projects_list(user["id"])])


@app.delete("/api/projects/{project_id}", tags=["projects"])
def delete_project(project_id: str, user: dict = Depends(require_user),
                   st: State = Depends(state)) -> dict:
    if not st.project_delete(project_id, user["id"]):
        raise HTTPException(404, f"project '{project_id}' not found")
    return {"ok": True}


@app.post("/api/projects/{project_id}/upload", response_model=DocumentListOut,
          tags=["projects"])
async def upload_files(project_id: str, request: Request,
                       user: dict = Depends(require_user),
                       st: State = Depends(state)) -> DocumentListOut:
    """Save uploaded PDFs into the project's source folder and kick off
    an index build for its own collection."""
    import pathlib

    project = _require_project(st, user, project_id)
    pdf_dir = pathlib.Path(project["pdf_dir"])
    pdf_dir.mkdir(parents=True, exist_ok=True)

    from starlette.requests import ClientDisconnect

    try:
        form = await request.form()
    except ClientDisconnect:
        # Browser closed the connection mid-upload (navigation, refresh,
        # cancelled request). Nothing was saved; tell the client instead of 500.
        raise HTTPException(400, "Upload aborted before the files arrived")
    saved: list[str] = []
    for _field, content in form.multi_items():
        if not hasattr(content, "read"):
            continue
        # Only keep the basename; browsers may send relative paths.
        name = pathlib.PurePath(content.filename or "").name
        if not name.lower().endswith(".pdf"):
            continue
        if "/" in name or ".." in name or not name:
            continue
        try:
            (pdf_dir / name).write_bytes(await content.read())
        except ClientDisconnect:
            raise HTTPException(400, "Upload aborted mid-transfer")
        if name not in saved:
            saved.append(name)

    if saved:
        try:
            st.job_runner.start("build", pdf_dir=str(pdf_dir),
                                config=st.project_config(project))
        except JobConflictError:
            pass  # a build is already running; it picks the files up next time

    # Reuse the documents listing for the response shape.
    return index_documents(project_id=project_id, user=user, st=st)


# --------------------------------------------------------------------- chats


@app.get("/api/projects/{project_id}/chats", response_model=ChatListOut, tags=["chats"])
def list_project_chats(project_id: str, user: dict = Depends(require_user),
                       st: State = Depends(state)) -> ChatListOut:
    return ChatListOut(chats=[ChatSummaryOut(**c) for c in st.list_chats(project_id, user_id=user["id"])])


@app.get("/api/chats/{chat_id}", response_model=ChatOut, tags=["chats"])
def get_chat(chat_id: str, user: dict = Depends(require_user),
             st: State = Depends(state)) -> ChatOut:
    chat = st.get_chat(chat_id)
    if chat is None or chat.get("user_id") != user["id"]:
        raise HTTPException(404, f"chat '{chat_id}' not found")
    return ChatOut(**chat)


@app.put("/api/chats/{chat_id}", response_model=ChatOut, tags=["chats"])
def save_chat(chat_id: str, body: ChatSaveIn, user: dict = Depends(require_user),
              st: State = Depends(state)) -> ChatOut:
    existing = st.get_chat(chat_id)
    if existing and existing.get("user_id") != user["id"]:
        raise HTTPException(404, f"chat '{chat_id}' not found")
    if body.project_id and st.project(body.project_id, user["id"]) is None:
        raise HTTPException(404, f"project '{body.project_id}' not found")
    messages = [m.model_dump() for m in body.messages]
    chat = st.save_chat(chat_id, body.project_id, body.title, messages, user_id=user["id"])
    return ChatOut(**chat)


@app.delete("/api/chats/{chat_id}", tags=["chats"])
def delete_chat(chat_id: str, user: dict = Depends(require_user),
                st: State = Depends(state)) -> dict:
    existing = st.get_chat(chat_id)
    if existing is None or existing.get("user_id") != user["id"]:
        raise HTTPException(404, f"chat '{chat_id}' not found")
    if not st.delete_chat(chat_id):
        raise HTTPException(404, f"chat '{chat_id}' not found")
    return {"ok": True}


# ----------------------------------------------------------------- documents


@app.get("/api/documents/file", tags=["index"])
def document_file(name: str, project_id: str | None = None,
                  user: dict = Depends(require_user), st: State = Depends(state)):
    """Serve a PDF from the project's pdf_dir (for the browser's native viewer)."""
    from fastapi.responses import FileResponse

    path = _resolve_pdf(st, user, name, project_id)
    name = path.name
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=name,
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


def _resolve_pdf(st: State, user: dict, name: str, project_id: str | None) -> Path:
    """Resolve a document name to a PDF path on disk, scoped to the project
    (or the global config). Raises 400/404 on anything suspicious."""
    import pathlib

    config = st.config
    if project_id:
        project = _require_project(st, user, project_id)
        config = st.project_config(project)

    if not name or "/" in name or "\\" in name or ".." in name or name != pathlib.Path(name).name:
        raise HTTPException(400, "invalid document name")
    pdf_dir = pathlib.Path(config.pdf_dir) if config.pdf_dir else None
    if not pdf_dir or not pdf_dir.is_dir():
        raise HTTPException(404, "pdf_dir not configured or unavailable")
    path = (pdf_dir / name).resolve()
    try:
        path.relative_to(pdf_dir.resolve())
    except ValueError:
        raise HTTPException(400, "invalid document name")
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise HTTPException(404, "document not found")
    return path


@app.get("/api/documents/page", tags=["index"])
def document_page(name: str, project_id: str | None = None, page: int = 1,
                  user: dict = Depends(require_user), st: State = Depends(state)):
    """Render one PDF page to PNG (used by the cited-page preview)."""
    path = _resolve_pdf(st, user, name, project_id)
    try:
        import fitz  # pymupdf
    except ImportError:
        raise HTTPException(501, "page rendering unavailable (pymupdf not installed)")

    doc = fitz.open(path)
    try:
        if page < 1 or page > doc.page_count:
            raise HTTPException(404, f"page {page} out of range (1-{doc.page_count})")
        pix = doc[page - 1].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
        png = pix.tobytes("png")
    finally:
        doc.close()
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


# -------------------------------------------------------------------- export


@app.get("/api/export", response_model=ExportOut, tags=["query"])
def export(question: str = "", project_id: str | None = None,
           user: dict = Depends(require_user), st: State = Depends(state)) -> ExportOut:
    """Re-run the last question (or the given one) and export Markdown."""
    if not question:
        raise HTTPException(400, "question query parameter is required")
    config = st.config
    if project_id:
        project = _require_project(st, user, project_id)
        config = st.project_config(project)
    passages, _ = _run_query(config, question)
    lines = [
        f"# Relevantr export",
        "",
        f"**Question:** {question}",
        "",
    ]
    for i, p in enumerate(passages, 1):
        lines += [
            f"## [{i}] {p.source} (Page: {p.page})",
            "",
            p.text.strip(),
            "",
        ]
    from datetime import datetime

    content = "\n".join(lines)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ExportOut(filename=f"relevantr-{stamp}.md", content=content)


# ------------------------------------------------------------------------ llm


@app.post("/api/llm/test", response_model=LlmTestOut, tags=["llm"])
def llm_test(st: State = Depends(state)) -> LlmTestOut:
    ok, message = llm.test_connection(st.config)
    return LlmTestOut(ok=ok, message=message)


@app.get("/api/llm/models", response_model=LlmModelsOut, tags=["llm"])
def llm_models(st: State = Depends(state)) -> LlmModelsOut:
    try:
        models = llm.list_models(st.config)
    except LLMError as exc:
        raise HTTPException(502, str(exc))
    return LlmModelsOut(models=models)


# ---------------------------------------------------------------------- keys


@app.get("/api/keys/{provider}", response_model=KeyStatusOut, tags=["keys"])
def key_status(provider: str, st: State = Depends(state)) -> KeyStatusOut:
    if provider not in LLM_PRESETS and provider != "gwdg":
        raise HTTPException(404, f"unknown provider '{provider}'")
    key, source = resolve_api_key(provider)
    return KeyStatusOut(provider=provider, set=key is not None, source=source)


@app.put("/api/keys/{provider}", response_model=KeyStatusOut, tags=["keys"])
def set_key(provider: str, body: KeyIn,
            st: State = Depends(state)) -> KeyStatusOut:
    if provider not in LLM_PRESETS and provider != "gwdg":
        raise HTTPException(404, f"unknown provider '{provider}'")
    note = store_api_key(provider, body.key)
    return KeyStatusOut(provider=provider, set=True, source=note)


@app.delete("/api/keys/{provider}", response_model=KeyStatusOut, tags=["keys"])
def delete_key(provider: str,
              st: State = Depends(state)) -> KeyStatusOut:
    from relevantr.config import delete_api_key

    if provider not in LLM_PRESETS and provider != "gwdg":
        raise HTTPException(404, f"unknown provider '{provider}'")
    delete_api_key(provider)
    return KeyStatusOut(provider=provider, set=False, source="removed")


# ------------------------------------------------------------------ downloads


@app.get(
    "/api/export.md",
    tags=["query"],
    response_class=Response,
    responses={200: {"content": {"text/markdown": {}},
                     "description": "Markdown file download"}},
)
def export_md(question: str = "", st: State = Depends(state)) -> Response:
    result = export(question=question, st=st)
    return Response(
        content=result.content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"'
        },
    )
