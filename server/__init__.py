# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server package: FastAPI over the relevantr core (Phase 1).

The server exposes the pipeline operations (build/update/rebuild/query/
export) as HTTP endpoints. It runs on the host, not in Docker, because it
loads the local embedding and reranker models and reads the PDF folder.
"""

from __future__ import annotations

__version__ = "0.1.0"
