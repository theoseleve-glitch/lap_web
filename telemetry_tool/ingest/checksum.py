"""
checksum.py
-----------
Fast and full SHA-256 checksums for integrity verification.

- ``sha256_partial(path)`` hashes the first 1 MB — sub-second even on
  spinning disks.  Used as the **fast pre-check** to detect file swaps
  or modifications between ingestion runs.

- ``sha256_full(path)`` hashes the entire file.  For a 10 GB file at
  ~400 MB/s sequential read speed this takes ~25 s.  Designed to run in
  a background thread via ``sha256_full_async``.

- ``sha256_full_async(path)`` returns a ``concurrent.futures.Future``
  that resolves to the full hex digest.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

_PARTIAL_BYTES: Final[int] = 1 * 1024 * 1024   # 1 MB
_READ_BLOCK: Final[int] = 8 * 1024 * 1024       # 8 MB read blocks

# Module-level thread pool for background checksums (max 1 thread —
# checksums are I/O-bound and we don't want to compete with the main
# ingestion reader for disk bandwidth).
_checksum_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cksum")
atexit.register(_checksum_pool.shutdown, wait=False)


def sha256_partial(path: Path, nbytes: int = _PARTIAL_BYTES) -> str:
    """Return hex SHA-256 of the first *nbytes* of *path*.

    If the file is smaller than *nbytes*, the entire file is hashed.
    """
    h = hashlib.sha256()
    remaining = nbytes
    with open(path, "rb") as f:
        while remaining > 0:
            chunk = f.read(min(_READ_BLOCK, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    digest = h.hexdigest()
    logger.debug("sha256_partial(%s, %d) = %s…", path.name, nbytes, digest[:16])
    return digest


def sha256_full(path: Path) -> str:
    """Return hex SHA-256 of the entire file (blocking)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_READ_BLOCK)
            if not chunk:
                break
            h.update(chunk)
    digest = h.hexdigest()
    logger.debug("sha256_full(%s) = %s…", path.name, digest[:16])
    return digest


def sha256_full_async(path: Path) -> Future[str]:
    """Submit a full-file checksum to a background thread.

    Returns a ``Future`` whose ``.result()`` is the hex digest.
    The caller can do other work while the hash is being computed.
    """
    return _checksum_pool.submit(sha256_full, path)
