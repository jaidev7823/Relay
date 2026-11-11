# SPDX-License-Identifier: AGPL-3.0-or-later
"""Indexing jobs: run pipeline operations in a background thread.

The API handler creates a job row, then dispatches the work to a daemon
thread here. Progress callbacks from ``pipeline`` update the SQLite ledger
(and therefore GET /jobs/{id}) with a coarse, low-write frequency so the
database is not hammered during large rebuilds.

One indexing job runs at a time (Phase 1): the local models and the
Qdrant collection are single-user resources. Attempts to start another
job while one is active raise JobConflictError (surfaced as HTTP 409).
"""

from __future__ import annotations

import logging
import threading
import traceback

from relevantr import pipeline
from relevantr.embed import get_backend

from . import jobs as jobs_db
from .settings import get_settings

logger = logging.getLogger(__name__)


class JobConflictError(Exception):
    """Another indexing job is already running."""


class JobNotFound(Exception):
    pass


class JobRunner:
    def __init__(self, db_path, config, embedder_factory=None):
        self.db_path = db_path
        self.config = config
        # Called at job start; State passes its cached/injectable embedder
        # so tests can supply a fake and settings changes take effect.
        self.embedder_factory = embedder_factory or (
            lambda: get_backend(self.config)
        )
        self._active_id: str | None = None
        self._lock = threading.Lock()

    # -- state -------------------------------------------------------------

    def active_job(self) -> dict | None:
        """The currently running job, if any (recovered from the ledger)."""
        with self._lock:
            if not self._active_id:
                return None
            job = jobs_db.get_job(self.db_path, self._active_id)
            if job and job["status"] in ("queued", "running"):
                return job
            self._active_id = None
            return None

    def _claim(self) -> None:
        """Raise JobConflictError if a job is active (single-job Phase 1)."""
        if self.active_job() is not None:
            raise JobConflictError("An indexing job is already running.")

    # -- running -----------------------------------------------------------

    def start(self, job_type: str, pdf_dir: str | None = None,
              force_rebuild: bool = False, config=None) -> dict:
        """Create a job row and start the work in a background thread.

        job_type: "build" (create/overwrite), "update" (incremental),
        or "rebuild" (drop + full re-embed; same as build for now).
        ``config`` may be a per-project config copy; without it the
        global config is used.
        """
        self._claim()
        job = jobs_db.create_job(self.db_path, job_type)

        with self._lock:
            self._active_id = job["id"]

        thread = threading.Thread(
            target=self._run,
            args=(job, pdf_dir, force_rebuild, config),
            name=f"relevantr-job-{job['id'][:8]}",
            daemon=True,
        )
        thread.start()
        return job

    def _run(self, job: dict, pdf_dir: str | None, force_rebuild: bool,
             config=None) -> None:
        job_id = job["id"]
        import copy

        config = copy.copy(config if config is not None else self.config)
        if pdf_dir:
            config.pdf_dir = pdf_dir

        jobs_db.update_job(
            self.db_path, job_id, status="running",
            started_at=_now(), message="Starting...",
        )
        try:
            summary = self._run_pipeline(
                job_id, job["type"], config, force_rebuild
            )
            jobs_db.update_job(
                self.db_path, job_id,
                status="done", progress=1.0,
                message=summary.describe(),
                result=summary_to_dict(summary),
                finished_at=_now(),
            )
        except Exception as exc:  # noqa: BLE001 - user-facing error
            logger.exception("job %s (%s) failed", job_id, job["type"])
            jobs_db.update_job(
                self.db_path, job_id,
                status="failed",
                message="Failed",
                error=f"{exc}",
                finished_at=_now(),
            )
        finally:
            with self._lock:
                if self._active_id == job_id:
                    self._active_id = None

    def _run_pipeline(self, job_id: str, job_type: str, config,
                      force_rebuild: bool):
        progress = _ProgressReporter(self.db_path, job_id, job_type)
        embedder = self.embedder_factory()

        if job_type in ("build", "rebuild"):
            return pipeline.build_index(
                config, embedder, progress=progress.callback
            )
        if job_type == "update":
            return pipeline.update_index(
                config, embedder, progress=progress.callback
            )
        raise ValueError(f"unknown job type: {job_type}")


def _now() -> float:
    import time

    return time.time()


def summary_to_dict(summary) -> dict:
    return {
        "added": summary.added,
        "changed": summary.changed,
        "removed": summary.removed,
        "chunks_embedded": summary.chunks_embedded,
    }


class _ProgressReporter:
    """Throttled progress writer: at most one update per second, plus the
    final call, so big rebuilds do not hammer SQLite."""

    def __init__(self, db_path, job_id: str, job_type: str):
        self.db_path = db_path
        self.job_id = job_id
        self.job_type = job_type
        self._last_write = 0.0
        self._done = False

    def callback(self, current: int, total: int, message: str) -> None:
        now = _now()
        final = current >= total
        if not final and now - self._last_write < 1.0:
            return
        self._last_write = now
        progress = (current / total) if total else 1.0
        try:
            jobs_db.update_job(
                self.db_path, self.job_id,
                progress=progress, message=message,
            )
        except Exception:  # pragma: no cover - ledger must never kill work
            logger.exception("progress update failed")
