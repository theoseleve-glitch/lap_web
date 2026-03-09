"""Shared helper functions used across repository modules."""

from __future__ import annotations

import json
import math
from typing import Any, Optional


def _safe_float(v: Any) -> Optional[float]:
    """Convert to float; return None for NaN / None / missing."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _json_dumps(obj: Any) -> Optional[str]:
    """Serialize to JSON string, or None."""
    if obj is None:
        return None
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return None


def _np_to_json(arr) -> str:
    """Convert a numpy array (or list) to a JSON list of floats."""
    if hasattr(arr, "tolist"):
        lst = arr.tolist()
    else:
        lst = list(arr)
    # Replace NaN/inf with null for JSON safety.
    clean = [x if (isinstance(x, (int, float)) and math.isfinite(x)) else None
             for x in lst]
    return json.dumps(clean)


def _parse_json_or_list(val):
    """Parse a JSON string or return a native list as-is.

    PostgreSQL JSONB columns are returned as Python lists by psycopg2,
    while SQLite stores them as text requiring ``json.loads()``.
    """
    if val is None:
        return []
    if isinstance(val, (list, dict)):
        return val
    return json.loads(val)
