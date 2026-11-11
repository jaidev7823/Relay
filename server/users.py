# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite-backed users and sessions (Phase 2b auth).

Lives in the same app database as jobs/chats. Deliberately simple:
- scrypt password hashing (stdlib, no extra dependency)
- opaque session tokens stored in the DB, sent as an HttpOnly cookie
- revocable by deleting the session row

No email verification / rate limiting / password reset yet: this is a
local, single-machine deployment. Phase 3 may move to Postgres + proper
account flows.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SESSION_COOKIE = "relevantr_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);
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


# -- passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# -- users -------------------------------------------------------------------

def create_user(db_path: Path, username: str, password: str) -> dict:
    username = username.strip()
    if not username or len(username) > 64:
        raise ValueError("username must be 1-64 characters")
    if len(password) < 6:
        raise ValueError("password must be at least 6 characters")
    now = time.time()
    user_id = secrets.token_hex(8)
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, hash_password(password), now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"username '{username}' is taken") from exc
        finally:
            conn.close()
    return dict(row)


def get_user_by_username(db_path: Path, username: str) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def count_users(db_path: Path) -> int:
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def verify_login(db_path: Path, username: str, password: str) -> dict | None:
    user = get_user_by_username(db_path, username)
    if user and verify_password(password, user["password_hash"]):
        return user
    return None


# -- sessions ----------------------------------------------------------------

def create_session(db_path: Path, user_id: str) -> dict:
    token = secrets.token_urlsafe(32)
    now = time.time()
    expires = now + SESSION_TTL_SECONDS
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, user_id, now, expires),
            )
            conn.commit()
        finally:
            conn.close()
    return {"token": token, "user_id": user_id, "expires_at": expires}


def get_session_user(db_path: Path, token: str) -> dict | None:
    """Return the user for a live session token, or None."""
    if not token:
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > ?",
            (token, time.time()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_session(db_path: Path, token: str) -> None:
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        finally:
            conn.close()


def purge_expired_sessions(db_path: Path) -> None:
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
            conn.commit()
        finally:
            conn.close()
