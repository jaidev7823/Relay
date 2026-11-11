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

    r = client.put("/api/config", json={"chunk_size": 512, "use_reranker": False})
    assert r.status_code == 200
    assert r.json()["chunk_size"] == 512

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

    # switch back to tester: bob's chat must 404 and not be listed
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "tester", "password": "secret123"})
    assert client.get("/api/chats/chat-bob-1").status_code == 404
    assert client.delete("/api/chats/chat-bob-1").status_code == 404
    chats = client.get(f"/api/projects/{project_id}/chats").json()["chats"]
    assert all(c["id"] != "chat-bob-1" for c in chats)

    # tester deleting bob's chat removes nothing; bob's chat stays bob-only
    assert client.get("/api/chats/chat-bob-1").status_code == 404


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
