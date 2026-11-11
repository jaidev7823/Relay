# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server master key for encrypting per-user secrets at rest.

The Fernet key comes from (in order):
  1. the RELEVANTR_SECRET_KEY environment variable (use this in production),
  2. a 0600 ``<data_dir>/secret.key`` file, generated on first use.

The key is NOT stored in the database; losing/replacing it makes stored
ciphertexts unreadable (by design).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

_ENV_VAR = "RELEVANTR_SECRET_KEY"


def get_fernet(data_dir: Path) -> Fernet:
    raw = os.environ.get(_ENV_VAR)
    if raw:
        key = raw.encode()
    else:
        path = Path(data_dir) / "secret.key"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            path.write_bytes(key)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass  # best effort on filesystems without chmod
        else:
            key = path.read_bytes()
    return Fernet(key)


def encrypt(data_dir: Path, plaintext: str) -> str:
    return get_fernet(data_dir).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(data_dir: Path, token: str) -> str | None:
    try:
        return get_fernet(data_dir).decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        return None
