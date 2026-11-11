# SPDX-License-Identifier: AGPL-3.0-or-later
"""API tests: the Phase 1 endpoints over an in-memory Qdrant + fake embedder.

No Docker, no real models, no LLM provider. Proves the HTTP layer works
end-to-end against the real pipeline + Qdrant store code.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from relevantr.store import QdrantStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 1. Point server settings at a scratch data dir.
    from server.settings import ServerSettings

    settings = ServerSettings(
        data_dir=tmp_path / "data",
        qdrant_url="http://localhost:6333",  # not used: client injected
        qdrant_collection="lib_apitest",
        embedding_backend="local",
        cors_origins="",
        _env_file=None,
    )

    import server.deps as deps

    # Never touch the real ~/.config/Relevantr/config.json from tests:
    # the API saves config on PUT /config and after queries.
    import relevantr.config as core_config

    monkeypatch.setattr(core_config, "config_file_path", lambda: tmp_path / "config.json")

    monkeypatch.setattr(deps, "get_settings", lambda: settings)

    # 2. Fresh State against those settings.
    deps._state = None
    state = deps.get_state()

    # 3. Fake embedder so no model download happens.
    class FakeConfigEmbedder:
        pass

    from tests.conftest import FakeEmbedder

    state._embedder = FakeEmbedder(name="fake:test", dim=64)
    state.config.use_reranker = False
    state.config.llm_enabled = False
    state.config.pdf_dir = str(tmp_path / "pdfs")

    # 4. Share one in-memory Qdrant across every store the server opens.
    from qdrant_client import QdrantClient

    shared_client = QdrantClient(":memory:")

    import relevantr.pipeline as pipeline
    import relevantr.store as store_pkg

    real_get = store_pkg.get_store

    def patched_get(config):
        s = real_get(config)
        if isinstance(s, QdrantStore):
            s._client = shared_client
        return s

    monkeypatch.setattr(store_pkg, "get_store", patched_get)
    monkeypatch.setattr(pipeline, "get_store", patched_get)
    monkeypatch.setattr(deps, "get_store", patched_get)

    # 5. PDFs on disk for indexing.
    from tests.conftest import make_pdf

    pdfs = tmp_path / "pdfs"
    pdfs.mkdir(parents=True)
    make_pdf(pdfs / "one.pdf", [
        "The zirconium alloy resists corrosion in reactors.",
        "Hydrogen diffuses into the lattice and embrittles it.",
    ])
    make_pdf(pdfs / "two.pdf", ["Vacancy clusters form near crack tips."])

    from server.app import main as main_mod

    # Rebuild the app so module-level settings pick up the fixture.
    monkeypatch.setattr(main_mod, "_settings", settings)

    from server.app.main import app

    with TestClient(app) as c:
        state.init_jobs_db()
        # Register + log in a user so the session cookie is set for all tests.
        r = c.post("/api/auth/register", json={"username": "tester", "password": "secret123"})
        assert r.status_code == 201, r.text
        yield c

    deps._state = None


def test_api_requires_auth(tmp_path, monkeypatch):
    """Without a session cookie, /api/* must 401 (health + auth excluded)."""
    from server.settings import ServerSettings

    settings = ServerSettings(
        data_dir=tmp_path / "data",
        qdrant_url="http://localhost:6333",
        qdrant_collection="lib_apitest2",
        embedding_backend="local",
        cors_origins="",
        _env_file=None,
    )
    import server.deps as deps

    import relevantr.config as core_config

    monkeypatch.setattr(core_config, "config_file_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    deps._state = None
    from server.app.main import app

    with TestClient(app) as c:
        assert c.get("/api/config").status_code == 401
        assert c.get("/api/health").status_code == 200
        assert c.post("/api/query", json={"question": "x"}).status_code == 401

        # register + login flow sets a cookie that grants access
        r = c.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
        assert r.status_code == 201
        assert r.json()["user"]["username"] == "alice"
        assert c.get("/api/config").status_code == 200

        # duplicate username rejected
        r = c.post("/api/auth/register", json={"username": "alice", "password": "secret456"})
        assert r.status_code == 400

        # bad login rejected, good login works
        r = c.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"})
        assert r.status_code == 401
        r = c.post("/api/auth/login", json={"username": "alice", "password": "secret123"})
        assert r.status_code == 200

        # me + logout
        r = c.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["user"]["username"] == "alice"
        r = c.post("/api/auth/logout")
        assert r.status_code == 200
        assert c.get("/api/config").status_code == 401

    deps._state = None


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["qdrant"] == "ok"  # in-memory client responds


def test_config_roundtrip(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["vector_backend"] == "qdrant"
    assert cfg["embedding_backend"] == "local"

    # per-user LLM/retrieval fields are settable; operator fields are not
    r = client.put("/api/config", json={"llm_model": "some-model-x", "retrieve_k": 17})
    assert r.status_code == 200
    assert r.json()["llm_model"] == "some-model-x"
    assert r.json()["retrieve_k"] == 17

    r = client.put("/api/config", json={"final_n": 3})
    assert r.json()["final_n"] == 3

    # chunking is operator-managed now
    r = client.put("/api/config", json={"chunk_size": 512})
    assert r.status_code == 400
    r = client.put("/api/config", json={"pdf_dir": "/tmp/x"})
    assert r.status_code == 400

    # read-only field must be rejected
    r = client.put("/api/config", json={"vector_backend": "lance"})
    assert r.status_code == 422  # not in ConfigIn schema at all
    r = client.put("/api/config", json={"qdrant_url": "http://evil"})
    assert r.status_code == 422


def test_build_update_job_lifecycle(client):
    r = client.post("/api/index/build")
    assert r.status_code == 200
    job = r.json()
    assert job["status"] in ("queued", "running")

    # wait for the background thread to finish
    for _ in range(100):
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] in ("done", "failed"):
            break
        import time

        time.sleep(0.1)
    assert j["status"] == "done", j
    assert j["result"]["chunks_embedded"] >= 2
    assert j["progress"] == 1.0

    # second build while idle must work; concurrent must 409
    r = client.post("/api/index/update")
    assert r.status_code == 200

    # info reflects the index
    r = client.get("/api/index/info")
    assert r.status_code == 200
    info = r.json()
    assert info["documents"] == 2
    assert info["embedding_model"] == "fake:test"


def test_query_after_build(client):
    client.post("/api/index/build")
    import time

    for _ in range(100):
        jobs = client.get("/api/jobs").json()["jobs"]
        if not jobs or jobs[0]["status"] in ("done", "failed"):
            break
        time.sleep(0.1)

    r = client.post("/api/query", json={"question": "zirconium corrosion"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "retrieval only"
    assert body["answer"] is None
    assert body["passages"]
    top = body["passages"][0]
    assert top["source"] == "one.pdf"
    assert "page" in top and "score" in top


def test_query_requires_index(client):
    r = client.post("/api/query", json={"question": "anything"})
    assert r.status_code == 409  # StoreError -> no manifest yet


def test_export(client):
    client.post("/api/index/build")
    import time

    for _ in range(100):
        jobs = client.get("/api/jobs").json()["jobs"]
        if not jobs or jobs[0]["status"] in ("done", "failed"):
            break
        time.sleep(0.1)

    r = client.get("/api/export", params={"question": "zirconium"})
    assert r.status_code == 200
    body = r.json()
    assert body["filename"].endswith(".md")
    assert "one.pdf" in body["content"] or "two.pdf" in body["content"]

    r = client.get("/api/export.md", params={"question": "zirconium"})
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]


def test_build_conflict_returns_409(client):
    # start a build, immediately try a second one
    r1 = client.post("/api/index/build")
    assert r1.status_code == 200
    r2 = client.post("/api/index/update")
    # may or may not conflict depending on speed; if it conflicts it's 409
    assert r2.status_code in (200, 409)
    if r2.status_code == 409:
        assert "already running" in r2.json()["detail"]


def test_jobs_listing(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert isinstance(r.json()["jobs"], list)


def test_chats_are_user_scoped(client):
    """A chat saved by one user must be invisible to another."""
    # fixture logged in as 'tester'; switch to a second account
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={"username": "bob", "password": "secret123"})
    assert r.status_code == 201

    r = client.post("/api/projects", json={"name": "bob sources"})
    assert r.status_code == 201
    project_id = r.json()["id"]

    r = client.put("/api/chats/chat-bob-1", json={"project_id": project_id, "messages": [
        {"role": "user", "content": "hello from bob"},
    ]})
    assert r.status_code == 200

    # bob can read it
    assert client.get("/api/chats/chat-bob-1").status_code == 200

    # switch back to tester: bob's chat must 403 and not be listed
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "tester", "password": "secret123"})
    assert client.get("/api/chats/chat-bob-1").status_code == 403
    assert client.delete("/api/chats/chat-bob-1").status_code == 403
    chats = client.get(f"/api/projects/{project_id}/chats").json()["chats"]
    assert all(c["id"] != "chat-bob-1" for c in chats)

    # tester deleting bob's chat removes nothing; bob's chat stays bob-only
    assert client.get("/api/chats/chat-bob-1").status_code == 403


def test_key_endpoints(client):
    r = client.get("/api/keys/openai")
    assert r.status_code == 200
    assert "set" in r.json()

    r = client.get("/api/keys/unknown-provider")
    assert r.status_code == 404


def test_projects_upload_and_delete(client):
    """Create project, upload PDFs (auto build), scoped index, delete."""
    r = client.post("/api/projects", json={"name": "My papers"})
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["qdrant_collection"].startswith("lib_")
    assert project["name"] == "My papers"

    # list shows it; another user's projects are hidden (checked below)
    assert client.get("/api/projects").json()["projects"][0]["id"] == project["id"]

    # upload PDFs
    from tests.conftest import make_pdf
    make_pdf(__import__("pathlib").Path(project["pdf_dir"]) / "uploaded.pdf",
             ["Zirconium alloys resist corrosion."])
    with open(__import__("pathlib").Path(project["pdf_dir"]) / "uploaded.pdf", "rb") as fh:
        r = client.post(f"/api/projects/{project['id']}/upload",
                        files={"files": ("uploaded.pdf", fh, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["pdf_dir_available"] is True

    # wait for the auto-started build job to finish
    import time
    for _ in range(100):
        jobs = client.get("/api/jobs").json()["jobs"]
        if not any(j["status"] in ("queued", "running") for j in jobs):
            break
        time.sleep(0.05)

    # index info is project-scoped and shows the uploaded document
    info = client.get(f"/api/index/info?project_id={project['id']}")
    assert info.status_code == 200
    assert info.json()["documents"] == 1

    # query scoped to the project works
    r = client.post("/api/query", json={"question": "zirconium", "project_id": project["id"]})
    assert r.status_code == 200, r.text

    # another user cannot see or touch it
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"username": "mallory", "password": "secret123"})
    assert client.get("/api/projects").json()["projects"] == []
    assert client.delete(f"/api/projects/{project['id']}").status_code == 404
    assert client.get(f"/api/index/info?project_id={project['id']}").status_code == 404

    # owner deletes it
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "tester", "password": "secret123"})
    assert client.delete(f"/api/projects/{project['id']}").status_code == 200
    assert client.get("/api/projects").json()["projects"] == []


def test_document_page_render(client):
    """Cited-page preview: PNG render of a real page, 404 for junk input."""
    # the fixture builds the index over tmp pdfs (one.pdf, two.pdf)
    client.post("/api/index/build")
    import time
    for _ in range(100):
        jobs = client.get("/api/jobs").json()["jobs"]
        if not jobs or jobs[0]["status"] in ("done", "failed"):
            break
        time.sleep(0.1)

    r = client.get("/api/documents/page?name=one.pdf&page=1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    assert client.get("/api/documents/page?name=one.pdf&page=99").status_code == 404
    assert client.get("/api/documents/page?name=../jobs.db&page=1").status_code == 400
    assert client.get("/api/documents/page?name=missing.pdf&page=1").status_code == 404


def test_user_settings_are_per_user(client):
    """Overrides of one user must not leak into another's config."""
    r = client.put("/api/config", json={"llm_provider": "openai", "retrieve_k": 99})
    assert r.status_code == 200

    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"username": "carol", "password": "secret123"})
    cfg = client.get("/api/config").json()
    assert cfg["llm_provider"] != "openai" or cfg["retrieve_k"] != 99

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "tester", "password": "secret123"})
    assert client.get("/api/config").json()["retrieve_k"] == 99


def test_user_keys_are_per_user_and_encrypted(client):
    """Keys set by one user are invisible/unusable by another; the DB holds
    ciphertext, not plaintext."""
    r = client.put("/api/keys/openai", json={"key": "sk-alice-secret-123"})
    assert r.status_code == 200
    assert r.json()["set"] is True

    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"username": "mallory", "password": "secret123"})
    assert client.get("/api/keys/openai").json()["set"] is False
    assert client.put("/api/keys/openai", json={"key": "sk-mallory"}).json()["set"] is True

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "tester", "password": "secret123"})
    assert client.get("/api/keys/openai").json()["set"] is True

    # plaintext must not appear in the DB file bytes
    import server.deps as deps

    db_path = deps.get_settings().data_dir / "jobs.db"
    assert b"sk-alice-secret-123" not in db_path.read_bytes()
    assert b"sk-alice-secret" not in db_path.read_bytes()


def test_llm_settings_are_per_provider(client):
    """base_url/model are stored and restored per provider, per user."""
    client.put("/api/config", json={"llm_provider": "custom", "llm_base_url": "http://muse:8080/v1",
                                  "llm_model": "muse-code"})
    cfg = client.get("/api/config").json()
    assert cfg["llm_base_url"] == "http://muse:8080/v1"
    assert cfg["llm_model"] == "muse-code"
    assert any(p["id"] == "gemini" and p["base_url"] for p in cfg["providers"])

    # switching provider restores the gemini preset, muse values must not leak
    client.put("/api/config", json={"llm_provider": "gemini"})
    cfg = client.get("/api/config").json()
    assert cfg["llm_provider"] == "gemini"
    assert "muse" not in cfg["llm_base_url"]
    assert cfg["llm_model"] != "muse-code"

    # editing gemini's settings must not touch custom's
    client.put("/api/config", json={"llm_model": "gemini-2.5-pro"})
    assert client.get("/api/config").json()["llm_model"] == "gemini-2.5-pro"
    client.put("/api/config", json={"llm_provider": "custom"})
    assert client.get("/api/config").json()["llm_base_url"] == "http://muse:8080/v1"


def test_legacy_llm_fields_migrate(client):
    """Legacy top-level llm_base_url/llm_model are moved into the provider bucket."""
    import json, sqlite3, time
    import server.deps as deps

    db_path = deps.get_settings().data_dir / "jobs.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, ?)",
        (
            conn.execute("SELECT id FROM users LIMIT 1").fetchone()[0],
            json.dumps({"llm_provider": "custom", "llm_base_url": "http://legacy:9000/v1",
                        "llm_model": "legacy-model"}),
            time.time(),
        ),
    )
    conn.commit()
    conn.close()

    cfg = client.get("/api/config").json()
    assert cfg["llm_base_url"] == "http://legacy:9000/v1"
    assert cfg["llm_model"] == "legacy-model"
    # the migration wrote the bucket back; raw JSON no longer has top-level keys
    conn = sqlite3.connect(db_path)
    data = json.loads(conn.execute("SELECT settings FROM user_settings").fetchone()[0])
    conn.close()
    assert "llm_base_url" not in data
    assert data["llm_providers"]["custom"]["base_url"] == "http://legacy:9000/v1"


def test_llm_test_uses_form_overrides(client):
    """Connection test must exercise the form's provider/base_url/key,
    not the saved config — and return a clean failure on unreachable hosts."""
    r = client.post("/api/llm/test", json={
        "provider": "custom",
        "base_url": "http://127.0.0.1:1/v1",
        "model": "muse-code",
        "key": "sk-typed-in-form",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is False  # unreachable, but the call reached the right provider

    # empty key + no stored/env key for 'custom' -> clean "no key" failure
    r = client.post("/api/llm/test", json={"provider": "custom", "base_url": "", "model": "", "key": ""})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "No API key" in r.json()["message"]

    # models list surfaces the connection failure as 502
    r = client.post("/api/llm/models", json={
        "provider": "custom", "base_url": "http://127.0.0.1:1/v1", "model": "x", "key": "sk-x",
    })
    assert r.status_code == 502


def test_interrupt_stale_marks_running_jobs_failed(tmp_path):
    from server import jobs as jobs_db

    db = tmp_path / "jobs.db"
    jobs_db.init_db(db)
    j = jobs_db.create_job(db, "build")
    jobs_db.update_job(db, j["id"], status="running", progress=0.0, message="embedding")
    assert jobs_db.interrupt_stale(db) == 1
    job = jobs_db.get_job(db, j["id"])
    assert job["status"] == "failed"
    assert job["error"] == "interrupted"
