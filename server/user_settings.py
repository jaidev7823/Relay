# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user settings: a sparse JSON overlay on the server config.

Only fields the user explicitly changed are stored; everything else is
inherited live from the global (operator-managed) config, so changing the
operator default affects users who have not overridden the field, and
overrides are never silently overwritten by config-file changes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_settings (
    user_id     TEXT PRIMARY KEY,
    settings    TEXT NOT NULL DEFAULT '{}',
    updated_at  REAL NOT NULL
);
"""

# Fields a user may override for themselves. Anything else (vector backend,
# Qdrant, embedding model, chunking, pdf_dir) is operator-managed.
USER_FIELDS = (
    "llm_enabled",
    "llm_provider",
    "llm_base_url",
    "llm_model",
    "retrieve_k",
    "final_n",
    "use_reranker",
)

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


def get(db_path: Path, user_id: str) -> dict:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT settings FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    try:
        data = json.loads(row["settings"])
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in data.items() if k in USER_FIELDS}


def patch(db_path: Path, user_id: str, updates: dict) -> dict:
    updates = {k: v for k, v in updates.items() if k in USER_FIELDS}
    current = get(db_path, user_id)
    current.update(updates)
    payload = json.dumps(current)
    now = time.time()
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO user_settings (user_id, settings, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET settings=excluded.settings, "
                "updated_at=excluded.updated_at",
                (user_id, payload, now),
            )
            conn.commit()
        finally:
            conn.close()
    return current
