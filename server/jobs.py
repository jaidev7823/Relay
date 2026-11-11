# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite job ledger for long-running indexing operations.

One table, one file (``<data_dir>/jobs.db``). A job row is created before the
work starts, updated with progress while it runs, and closed with a result
or an error. The FastAPI layer reads this table to answer GET /jobs/{id}.

Phase 1 runs jobs in a daemon thread inside the API process (single user,
local machine). Phase 3 moves the same table to Postgres + a real worker,
so the schema is deliberately plain and migration-friendly.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,          -- build | update | rebuild
    status      TEXT NOT NULL,           -- queued | running | done | failed | error
    progress    REAL NOT NULL DEFAULT 0, -- 0.0 .. 1.0
    message     TEXT,
    error       TEXT,
    result      TEXT,                    -- JSON summary, set on success
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs (created_at DESC);
"""

# SQLite module-level lock: every connection is opened per call and the
# database lives on local disk, but writes are serialized to keep the
# ledger consistent when the worker thread and API queries overlap.
_write_lock = threading.Lock()

_job_update_listeners: dict[str, list] = {}


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


def create_job(db_path: Path, job_type: str) -> dict:
    job = {
        "id": str(uuid.uuid4()),
        "type": job_type,
        "status": "queued",
        "progress": 0.0,
        "message": "Queued",
        "error": None,
        "result": None,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
    }
    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO jobs (id, type, status, progress, message, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (job["id"], job_type, job["status"], 0.0, job["message"],
                 job["created_at"]),
            )
            conn.commit()
        finally:
            conn.close()
    return job


def update_job(db_path: Path, job_id: str, **fields) -> None:
    if not fields:
        return
    allowed = {"status", "progress", "message", "error", "result",
               "started_at", "finished_at"}
    columns, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"unknown job field: {key}")
        if key == "result" and isinstance(value, (dict, list)):
            value = json.dumps(value)
        columns.append(f"{key} = ?")
        values.append(value)
    values.append(job_id)

    with _write_lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                f"UPDATE jobs SET {', '.join(columns)} WHERE id = ?", values
            )
            conn.commit()
        finally:
            conn.close()


def interrupt_stale(db_path: Path) -> int:
    """Mark any queued/running jobs as failed.

    Indexing runs in daemon threads; a server restart kills them mid-flight,
    leaving rows stuck in 'running' forever (and blocking the UI's
    active-job indicators). Called once on server startup.
    """
    now = time.time()
    with _write_lock:
        conn = _connect(db_path)
        try:
            cur = conn.execute(
                "UPDATE jobs SET status = 'failed', error = 'interrupted', "
                "message = 'Interrupted by server restart', finished_at = ? "
                "WHERE status IN ('queued', 'running')",
                (now,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def get_job(db_path: Path, job_id: str) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_job(row)


def list_jobs(db_path: Path, limit: int = 50) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_job(row) for row in rows]


def _row_to_job(row: sqlite3.Row) -> dict:
    job = dict(row)
    if job.get("result"):
        try:
            job["result"] = json.loads(job["result"])
        except (TypeError, json.JSONDecodeError):
            pass  # keep the raw string
    return job
