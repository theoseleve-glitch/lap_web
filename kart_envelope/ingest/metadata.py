"""
metadata.py
-----------
Parse a sidecar metadata file (CSV, JSON, or YAML) that maps session
files to kart/driver/condition information.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MetadataError(ValueError):
    """Raised when the metadata file cannot be parsed."""


@dataclass
class SessionMetadata:
    """Metadata for a single telemetry session file."""

    session_file: str
    kart_id: str = "unknown_kart"
    kart_class: str = "4t"           # "2t" or "4t"
    driver_weight_kg: float = 80.0
    kart_weight_kg: float | None = None
    track_name: str | None = None
    condition_label: str | None = None  # dry / damp / wet / green
    track_record_s: float | None = None
    notes: str = ""


def parse_metadata(path: str | Path) -> list[SessionMetadata]:
    """Auto-detect format (CSV / JSON / YAML) and parse.

    Returns
    -------
    list[SessionMetadata]
        One entry per session described in the metadata file.

    Raises
    ------
    MetadataError
        If the file is missing, empty, or has an unsupported format.
    """
    path = Path(path)
    if not path.exists():
        raise MetadataError(f"Metadata file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _parse_csv(path)
    if suffix == ".json":
        return _parse_json(path)
    if suffix in {".yaml", ".yml"}:
        return _parse_yaml(path)

    raise MetadataError(f"Unsupported metadata format: {suffix}")


# ---------------------------------------------------------------------------
# Format-specific parsers
# ---------------------------------------------------------------------------

def _row_to_meta(d: dict[str, Any]) -> SessionMetadata:
    """Convert a flat dict to a SessionMetadata, coercing types."""
    # Normalise key names (lowercase, strip whitespace, underscores)
    nd: dict[str, Any] = {}
    for k, v in d.items():
        nk = str(k).strip().lower().replace(" ", "_")
        # common aliases
        if nk in ("file_name", "file", "filename", "csv"):
            nk = "session_file"
        if nk in ("kart_model", "kart_model_name", "kart"):
            nk = "kart_id"
        if nk in ("class", "engine_type"):
            nk = "kart_class"
        if nk in ("driver_weight", "weight_kg", "weight"):
            nk = "driver_weight_kg"
        if nk in ("kart_weight", "kart_mass_kg"):
            nk = "kart_weight_kg"
        if nk in ("track", "circuit"):
            nk = "track_name"
        if nk in ("condition", "conditions", "weather"):
            nk = "condition_label"
        if nk in ("track_record", "record", "record_time", "record_s",
                   "track_record_seconds"):
            nk = "track_record_s"
        nd[nk] = v

    # Coerce floats
    for fld in ("driver_weight_kg", "kart_weight_kg", "track_record_s"):
        if fld in nd and nd[fld] is not None:
            try:
                nd[fld] = float(nd[fld])
            except (ValueError, TypeError):
                nd[fld] = None

    # Filter to valid fields
    valid_fields = {f.name for f in SessionMetadata.__dataclass_fields__.values()}
    filtered = {k: v for k, v in nd.items() if k in valid_fields and v is not None}

    if "session_file" not in filtered:
        raise MetadataError(f"Row missing 'session_file' (or alias): {d}")

    return SessionMetadata(**filtered)


def _parse_csv(path: Path) -> list[SessionMetadata]:
    results: list[SessionMetadata] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        # auto-detect delimiter
        sample = fh.read(4096)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        reader = csv.DictReader(fh, dialect=dialect)
        for row in reader:
            results.append(_row_to_meta(row))
    logger.info("Loaded %d session entries from CSV %s", len(results), path.name)
    return results


def _parse_json(path: Path) -> list[SessionMetadata]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        # support {"sessions": [...]} wrapper
        data = data.get("sessions", [data])
    if not isinstance(data, list):
        raise MetadataError(f"Expected JSON array or object with 'sessions' key: {path}")
    results = [_row_to_meta(d) for d in data]
    logger.info("Loaded %d session entries from JSON %s", len(results), path.name)
    return results


def _parse_yaml(path: Path) -> list[SessionMetadata]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise MetadataError("PyYAML is required to parse YAML metadata") from exc

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict):
        data = data.get("sessions", [data])
    if not isinstance(data, list):
        raise MetadataError(f"Expected YAML list or mapping with 'sessions': {path}")
    results = [_row_to_meta(d) for d in data]
    logger.info("Loaded %d session entries from YAML %s", len(results), path.name)
    return results
