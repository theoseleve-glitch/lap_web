"""Canonical JSON serialisation for deterministic hashing.

Normalises floats, NaN/Inf, and dict ordering so that identical
analysis results always produce the same hash.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def _normalise(obj: Any, precision: int) -> Any:
    """Recursively normalise an object for canonical JSON."""
    if isinstance(obj, dict):
        return {k: _normalise(v, precision) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_normalise(v, precision) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj):
            return "__NaN__"
        if math.isinf(obj):
            return "__-Inf__" if obj < 0 else "__Inf__"
        return round(obj, precision)
    return obj


def canonicalize(obj: Any, float_precision: int = 6) -> str:
    """Return a deterministic JSON string with sorted keys and normalised floats."""
    normalised = _normalise(obj, float_precision)
    return json.dumps(normalised, sort_keys=True, separators=(", ", ": "))


def canonical_hash(obj: Any, float_precision: int = 6) -> str:
    """Return the SHA-256 hex digest of the canonical JSON form."""
    payload = canonicalize(obj, float_precision)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
