# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite-backed chat persistence (Phase 2b).

Chats and messages live in the same app database as jobs. This keeps the
per-chat URL meaningful across refreshes/browsers on the same server.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    user_id     TEXT,
    title       TEXT NOT NULL DEFAULT 'New chat',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chats_project ON chats (project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chats_user ON chats (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    chat_id     TEXT NOT NULL,
    role        TEXT NOT NULL,          -- user | assistant
    content     TEXT NOT NULL DEFAULT '',
    sources     TEXT,                   -- JSON array
    error       TEXT,
    created_at  REAL NOT NULL,
    FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, created_at ASC);
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
            # Migration: add user_id to pre-auth chats tables.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(chats)").fetchall()}
            if "user_id" not in cols:
                conn.execute("ALTER TABLE chats ADD COLUMN user_id TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_chats_user ON chats (user_id, updated_at DESC)")
            conn.commit()
        finally:
            conn.close()


def upsert_chat(db_path: Path, chat_id: str, project_id: str, title: str | None = None) -> dict:
    now = time.time()
    with _write_lock:
        conn = _connect(db_path)
        try:
            row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
            if row:
                if title is not None:
                    conn.execute("UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (title, now, chat_id))
                else:
                    conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
            else:
                conn.execute(
                    "INSERT INTO chats (id, project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (chat_id, project_id, title or "New chat", now, now),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        finally:
            conn.close()
    return dict(row)


def list_chats(db_path: Path, project_id: str, limit: int = 50, user_id: str | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        if user_id is None:
            rows = conn.execute(
                "SELECT * FROM chats WHERE project_id = ? ORDER BY updated_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chats WHERE project_id = ? AND (user_id = ? OR user_id IS NULL) "
                "ORDER BY updated_at DESC LIMIT ?",
                (project_id, user_id, limit),
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_chat(db_path: Path, chat_id: str) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not row:
            return None
        chat = dict(row)
        msgs = conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at ASC, rowid ASC",
            (chat_id,),
        ).fetchall()
    finally:
        conn.close()
    chat["messages"] = [_row_to_msg(m) for m in msgs]
    return chat


def save_messages(db_path: Path, chat_id: str, project_id: str, title: str | None, messages: list[dict],
                  user_id: str | None = None) -> dict | None:
    """Replace a chat's messages with the provided list (idempotent save from client)."""
    now = time.time()
    with _write_lock:
        conn = _connect(db_path)
        try:
            row = conn.execute("SELECT id FROM chats WHERE id = ?", (chat_id,)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO chats (id, project_id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (chat_id, project_id, user_id, title or "New chat", now, now),
                )
            else:
                conn.execute(
                    "UPDATE chats SET title = COALESCE(?, title), updated_at = ?, project_id = ?, "
                    "user_id = COALESCE(user_id, ?) WHERE id = ?",
                    (title, now, project_id, user_id, chat_id),
                )
            conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            for i, m in enumerate(messages):
                conn.execute(
                    "INSERT INTO messages (id, chat_id, role, content, sources, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        m.get("id") or f"{chat_id}-{i}",
                        chat_id,
                        m.get("role", "user"),
                        m.get("content", ""),
                        json.dumps(m.get("sources")) if m.get("sources") is not None else None,
                        m.get("error"),
                        float(m.get("created_at") or (now + i * 0.001)),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    return get_chat(db_path, chat_id)


def delete_chat(db_path: Path, chat_id: str) -> bool:
    with _write_lock:
        conn = _connect(db_path)
        try:
            cur = conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def _row_to_msg(row: sqlite3.Row) -> dict:
    m = dict(row)
    if m.get("sources"):
        try:
            m["sources"] = json.loads(m["sources"])
        except Exception:
            m["sources"] = None
    else:
        m["sources"] = None
    return m
