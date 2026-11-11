# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user API keys, encrypted at rest.

Lives in the same SQLite ledger (Postgres later). Plaintext keys only
exist in memory during the provider call; the database holds Fernet
ciphertext decryptable only by the server master key.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from . import crypto

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    user_id     TEXT NOT NULL,
    provider    TEXT NOT NULL,
    ciphertext  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (user_id, provider)
);
"""

_write_lock = threading.Lock()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
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


def set_key(db_path: Path, data_dir: Path, user_id: str, provider: str, plaintext: str) -> None:
    ciphertext = crypto.encrypt(data_dir, plaintext)
    now = time.time()
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO api_keys (user_id, provider, ciphertext, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (user_id, provider) DO UPDATE SET "
                "ciphertext=excluded.ciphertext, updated_at=excluded.updated_at",
                (user_id, provider, ciphertext, now, now),
            )
            conn.commit()
        finally:
            conn.close()


def get_key(db_path: Path, data_dir: Path, user_id: str, provider: str) -> str | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT ciphertext FROM api_keys WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return crypto.decrypt(data_dir, row["ciphertext"])


def has_key(db_path: Path, user_id: str, provider: str) -> bool:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM api_keys WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def delete_key(db_path: Path, user_id: str, provider: str) -> None:
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "DELETE FROM api_keys WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            )
            conn.commit()
        finally:
            conn.close()
