"""
Normalization module for deterministic, comparable output between
CLI pipeline and webapp API.

Ensures floats are rounded, NaN/Inf become None, keys are sorted,
and non-serializable pipeline artefacts are stripped from summaries.
"""

import json
import math
import re
from typing import Any

PRECISION = 4

# ISO 8601 timestamp pattern — matches with optional fractional seconds
_ISO_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)

# Keys that hold non-serializable pipeline artefacts (DataFrames, model
# objects, large intermediate structures) and must be stripped from summaries.
_STRIP_KEYS = frozenset({
    "raw_df",
    "filtered_df",
    "enriched_df",
    "trimmed_df",
    "best_lap",
    "resampled_laps",
    "lap_dict",
    "reference_line",
    "curvature_profile",
    "theoretical_lap",
    "feature_df",
    "friction_model",
    "vehicle_params",
    "data_quality",
    "phases_df",
    "weather_timeline",
    "context",
})


def normalize_value(v: Any) -> Any:
    """Normalize a single value for deterministic comparison.

    Rules (in evaluation order):
    - None:          passthrough
    - bool:          passthrough (checked before int — bool is subclass of int)
    - float:         NaN/Inf → None; otherwise round to PRECISION decimals
    - int:           passthrough
    - str:           ISO timestamps stripped to second precision; else passthrough
    - dict:          recurse via normalize_dict
    - list / tuple:  normalize each element, preserve order (returns list)
    - Anything else: return None (DataFrames, model objects, etc.)
    """
    if v is None:
        return None

    if isinstance(v, bool):
        return v

    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, PRECISION)

    if isinstance(v, int):
        return v

    if isinstance(v, str):
        if _ISO_TS_RE.match(v):
            # Strip sub-second precision: keep up to "...HH:MM:SS"
            # Find the 'T' or space separator, then truncate after seconds
            sep_idx = max(v.find("T"), v.find(" "))
            if sep_idx != -1:
                time_part_start = sep_idx + 1
                # Seconds end at position time_part_start + 8 (HH:MM:SS)
                sec_end = time_part_start + 8
                base = v[:sec_end]
                # Preserve timezone suffix if present
                remainder = v[sec_end:]
                # Strip fractional seconds, keep timezone
                tz_match = re.search(r"(Z|[+-]\d{2}:?\d{2})$", remainder)
                if tz_match:
                    return base + tz_match.group(0)
                return base
        return v

    if isinstance(v, dict):
        return normalize_dict(v)

    if isinstance(v, (list, tuple)):
        return [normalize_value(elem) for elem in v]

    # Anything else (DataFrame, model objects, etc.)
    return None


def normalize_dict(d: dict) -> dict:
    """Sort keys alphabetically and normalize values recursively."""
    return {k: normalize_value(v) for k, v in sorted(d.items())}


def normalize_summary(raw: dict) -> dict:
    """Filter out non-serializable keys and normalize the rest.

    Strips keys listed in _STRIP_KEYS (DataFrames, model objects,
    large intermediate structures), then applies normalize_dict.
    """
    filtered = {k: v for k, v in raw.items() if k not in _STRIP_KEYS}
    return normalize_dict(filtered)


def normalize_json_file(path: str) -> dict:
    """Read a JSON file and return its normalized contents."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return normalize_dict(data)
    return normalize_value(data)
