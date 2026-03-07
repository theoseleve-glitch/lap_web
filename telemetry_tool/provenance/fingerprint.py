"""Input fingerprinting for provenance tracking.

Provides two hash functions:
- ``compute_file_hash`` -- SHA-256 of raw file bytes.
- ``compute_data_fingerprint`` -- SHA-256 of normalised column structure +
  a fixed-size numeric sample.  Resistant to encoding/formatting differences.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_READ_BLOCK: int = 8 * 1024 * 1024  # 8 MB


def compute_file_hash(path: str) -> str:
    """Return SHA-256 hex digest of the raw file bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_READ_BLOCK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_data_fingerprint(df: pd.DataFrame) -> str:
    """Return SHA-256 hex digest of the DataFrame's normalised structure + sample.

    The fingerprint covers:
    - Sorted column names
    - Shape (rows, cols)
    - First 8 bytes of each numeric column (cast to float64), sorted by
      column name

    This is fast even for very large DataFrames because only the header
    structure and a fixed-size sample are hashed.
    """
    h = hashlib.sha256()

    # 1. Sorted column names
    cols = sorted(df.columns.tolist())
    h.update("|".join(str(c) for c in cols).encode("utf-8"))

    # 2. Shape
    h.update(f"|shape={df.shape[0]}x{df.shape[1]}".encode("utf-8"))

    # 3. Per-column numeric digest, sorted by column name
    for col in cols:
        series = df[col]
        try:
            vals = series.astype(np.float64).values
        except (ValueError, TypeError):
            # Non-numeric column: hash string repr of all values
            for v in series:
                h.update(str(v).encode("utf-8"))
            continue
        if len(vals) > 0:
            h.update(vals.tobytes())

    return h.hexdigest()
