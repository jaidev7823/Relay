# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user settings: a sparse JSON overlay on the server config.

Only fields the user explicitly changed are stored; everything else is
inherited live from the global (operator-managed) config.

LLM connection details (``base_url``, ``model``) are stored **per provider**
under the ``llm_providers`` key so switching provider in the UI restores
that provider's own settings instead of leaking the previous one's.
On read, legacy top-level ``llm_base_url``/``llm_model`` entries are
migrated into the bucket of the stored ``llm_provider`` (once).
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

# Scalar fields a user may override for themselves. Vector backend, Qdrant,
# embeddings, chunking stay operator-managed.
USER_FIELDS = (
    "llm_enabled",
    "llm_provider",
    "llm_base_url",
    "llm_model",
    "retrieve_k",
    "final_n",
)

_SCALAR_FIELDS = tuple(
    f for f in USER_FIELDS if f not in ("llm_base_url", "llm_model")
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


def _migrate(data: dict) -> tuple[dict, bool]:
    """Move legacy top-level llm_base_url/llm_model into the per-provider
    bucket. Returns (data, migrated?)."""
    providers = data.setdefault("llm_providers", {})
    migrated = False
    for key, field in (("llm_base_url", "base_url"), ("llm_model", "model")):
        if key in data:
            value = data.pop(key)
            provider = data.get("llm_provider") or "custom"
            bucket = providers.setdefault(provider, {})
            bucket.setdefault(field, value)
            migrated = True
    return data, migrated


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
    if not isinstance(data, dict):
        return {}

    data, migrated = _migrate(data)
    if migrated:
        _put_raw(db_path, user_id, data)
    return data


def _put_raw(db_path: Path, user_id: str, data: dict) -> None:
    payload = json.dumps(data)
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


def patch(db_path: Path, user_id: str, updates: dict,
          default_provider: str = "custom") -> dict:
    """Merge a sparse update; routes base_url/model into the provider bucket."""
    data = get(db_path, user_id)
    updates = dict(updates)

    active_provider = updates.get("llm_provider") or data.get("llm_provider") or default_provider
    providers = data.setdefault("llm_providers", {})

    for key, field in (("llm_base_url", "base_url"), ("llm_model", "model")):
        if key in updates:
            providers.setdefault(active_provider, {})[field] = updates.pop(key)

    for key, value in updates.items():
        if key in _SCALAR_FIELDS:
            data[key] = value

    _put_raw(db_path, user_id, data)
    return data
