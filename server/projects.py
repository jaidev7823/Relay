# SPDX-License-Identifier: AGPL-3.0-or-later
"""Projects: a user's named source library.

A project owns a set of uploaded PDFs (``<data_dir>/projects/<id>/pdfs``)
and its own Qdrant collection (``lib_<id[:8]>``). Chat sessions attach to
a project via ``chats.project_id``; two sessions on the same project share
sources but keep separate histories.
"""

from __future__ import annotations

import secrets
import shutil
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    name              TEXT NOT NULL,
    pdf_dir           TEXT NOT NULL,
    qdrant_collection TEXT NOT NULL,
    created_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects (user_id, created_at DESC);
"""

_write_lock = threading.Lock()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def projects_root(data_dir: Path) -> Path:
    return Path(data_dir) / "projects"


def create(db_path: Path, data_dir: Path, user_id: str, name: str) -> dict:
    name = (name or "").strip() or "Untitled sources"
    if len(name) > 120:
        name = name[:120]
    project_id = str(secrets.token_hex(8))
    pdf_dir = projects_root(data_dir) / project_id / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    row = {
        "id": project_id,
        "user_id": user_id,
        "name": name,
        "pdf_dir": str(pdf_dir),
        "qdrant_collection": f"lib_{project_id[:8]}",
        "created_at": now,
    }
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO projects (id, user_id, name, pdf_dir, qdrant_collection, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], row["user_id"], row["name"], row["pdf_dir"],
                 row["qdrant_collection"], row["created_at"]),
            )
            conn.commit()
        finally:
            conn.close()
    return row


def get(db_path: Path, project_id: str) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_for_user(db_path: Path, user_id: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM projects WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete(db_path: Path, data_dir: Path, project_id: str, qdrant_cleanup=None) -> bool:
    """Delete the project row, its uploaded PDFs, its chats, and (best
    effort, via ``qdrant_cleanup(collection)``) its vector collection."""
    row = get(db_path, project_id)
    if not row:
        return False
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute("DELETE FROM chats WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        finally:
            conn.close()
    if callable(qdrant_cleanup):
        try:
            qdrant_cleanup(row["qdrant_collection"])
        except Exception:
            pass
    shutil.rmtree(projects_root(data_dir) / project_id, ignore_errors=True)
    return True
