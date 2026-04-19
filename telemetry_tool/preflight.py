"""Preflight validation — fast checks before expensive pipeline analysis.

Runs in the upload request thread (not Celery) to give instant feedback.
Catches common user-fixable issues before queueing work.

Usage::

    from preflight import run_preflight
    result = run_preflight("/tmp/upload/session.csv")
    if not result.ok:
        return result.failure.to_dict()
"""
from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from telemetry_tool.import_errors import (
    ImportErrorCode,
    ImportFailure,
    make_support_ref,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known binary signatures (magic bytes)
# ---------------------------------------------------------------------------

_BINARY_SIGNATURES: dict[bytes, tuple[str, ImportErrorCode]] = {
    # iRacing IBT header
    b"\x01\x00\x00\x00": ("iRacing IBT", ImportErrorCode.IRACING_NON_CSV_EXPORT),
    # MoTeC LD header (starts with "LDTN" or similar)
    b"LDTN": ("MoTeC LD", ImportErrorCode.MOTEC_BINARY_NOT_SUPPORTED),
    b"\x40\x00\x00\x00": ("MoTeC LD (variant)", ImportErrorCode.MOTEC_BINARY_NOT_SUPPORTED),
}

# Known text-based header sentinels (any of these in the first column → valid header)
_HEADER_SENTINELS = {
    "time (s)", "time", "utc time", "timestamp", "time_s", "elapsed time",
    "time(s)", "lap time", "elapsed_time", "t(s)", "sampletime",
}

# GPS column indicators
_GPS_LAT_PATTERNS = {"latitude", "lat", "latitude (deg)", "gps_lat", "gps latitude"}
_GPS_LON_PATTERNS = {"longitude", "lon", "lng", "longitude (deg)", "gps_lon", "gps longitude"}

# Speed column indicators
_SPEED_PATTERNS = {"speed", "speed (m/s)", "speed (km/h)", "speed (mph)", "gps speed", "speed_ms", "v (m/s)"}

# Time column indicators
_TIME_PATTERNS = {"time", "time (s)", "utc time", "timestamp", "time_s", "elapsed time", "sampletime", "t(s)"}

# Distance column indicators
_DISTANCE_PATTERNS = {"distance", "distance (m)", "distance_m", "odometer", "total distance"}

# Minimum rows for a usable session
_MIN_DATA_ROWS = 50

# Max file size to attempt text reading (500 MB; larger files go straight to pipeline)
_MAX_PREFLIGHT_BYTES = 500 * 1024 * 1024


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PreflightResult:
    ok: bool
    failure: ImportFailure | None = None
    detected_format: str | None = None
    detected_source: str | None = None
    columns: list[str] | None = None
    row_count: int | None = None
    delimiter: str | None = None
    has_gps: bool | None = None
    has_speed: bool | None = None
    has_time: bool | None = None


def _ok(**kwargs: Any) -> PreflightResult:
    return PreflightResult(ok=True, **kwargs)


def _fail(failure: ImportFailure, **kwargs: Any) -> PreflightResult:
    return PreflightResult(ok=False, failure=failure, **kwargs)


# ---------------------------------------------------------------------------
# Exporter/source detection
# ---------------------------------------------------------------------------

def _detect_source_from_content(header_area: str, columns: list[str], ext: str) -> str | None:
    """Try to identify the source logger/exporter from file content."""
    header_lower = header_area.lower()
    cols_lower = [c.lower().strip() for c in columns]
    cols_joined = " ".join(cols_lower)

    # RaceChrono
    if any(k in header_lower for k in ["racechrono", "rc pro"]):
        return "RaceChrono"
    if "lap #" in cols_joined and "speed (m/s)" in cols_joined:
        return "RaceChrono"

    # RaceBox
    if "racebox" in header_lower:
        return "RaceBox"
    if "speed(km/h)" in cols_joined and "latitude" in cols_joined:
        return "RaceBox"

    # iRacing CSV export
    if "iracing" in header_lower:
        return "iRacing"
    if "sessionnum" in cols_joined or "sessiontime" in cols_joined:
        return "iRacing"

    # AiM
    if any(k in header_lower for k in ["aim", "race studio"]):
        return "AiM"

    # MoTeC CSV export
    if any(k in header_lower for k in ["motec", "i2 pro"]):
        return "MoTeC"

    # VBOX
    if "vbox" in header_lower or ext == ".vbo":
        return "VBOX"

    # Qstarz
    if "qstarz" in header_lower:
        return "Qstarz"

    # ACC (Assetto Corsa Competizione)
    if "acc" in header_lower or "assetto" in header_lower:
        return "ACC"

    return None


# ---------------------------------------------------------------------------
# Core preflight logic
# ---------------------------------------------------------------------------

def run_preflight(file_path: str) -> PreflightResult:
    """Run fast validation checks on an uploaded file.

    Returns PreflightResult with ok=True if the file passes all checks,
    or ok=False with a structured ImportFailure if validation fails.
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    support_ref = make_support_ref()

    # ── 1. File existence and size ────────────────────────────────
    if not path.exists():
        return _fail(ImportFailure.from_code(
            ImportErrorCode.EMPTY_FILE,
            support_ref=support_ref,
            message_override="The uploaded file could not be found on the server.",
        ))

    file_size = path.stat().st_size
    if file_size == 0:
        return _fail(ImportFailure.from_code(
            ImportErrorCode.EMPTY_FILE,
            support_ref=support_ref,
        ))

    # ── 2. Binary format detection (check magic bytes) ────────────
    try:
        with open(file_path, "rb") as f:
            head = f.read(16)
    except OSError:
        return _fail(ImportFailure.from_code(
            ImportErrorCode.CORRUPTED_FILE,
            support_ref=support_ref,
            message_override="Could not read the uploaded file.",
        ))

    for magic, (fmt_name, err_code) in _BINARY_SIGNATURES.items():
        if head.startswith(magic):
            return _fail(ImportFailure.from_code(
                err_code,
                support_ref=support_ref,
                detected_format=fmt_name,
            ), detected_format=fmt_name)

    # Extension-based binary detection for known non-text formats
    _KNOWN_BINARY_EXTS = {
        ".ibt": ("iRacing IBT", ImportErrorCode.IRACING_NON_CSV_EXPORT),
        ".ld": ("MoTeC LD", ImportErrorCode.MOTEC_BINARY_NOT_SUPPORTED),
        ".ldx": ("MoTeC LDX", ImportErrorCode.MOTEC_BINARY_NOT_SUPPORTED),
    }
    # NOTE: .ibt, .ld, .ldx are actually supported via adapters, so we
    # only flag them if the adapter-based detection later fails.
    # For preflight, we skip this — let the adapter system try first.

    # ── 3. Text readability check ─────────────────────────────────
    # Only do text-level checks for files small enough
    if file_size > _MAX_PREFLIGHT_BYTES:
        # Large file — skip text checks, let the pipeline handle it
        return _ok()

    text_content = None
    encoding = None
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                text_content = f.read(64 * 1024)  # First 64 KB
            encoding = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if text_content is None:
        # Check if this is a known binary format that adapters handle
        if ext in (".ibt", ".ld", ".ldx", ".vbo", ".xrk", ".drk"):
            # These are handled by binary adapters — skip text checks
            return _ok(detected_format=ext.lstrip(".").upper())

        return _fail(ImportFailure.from_code(
            ImportErrorCode.UNREADABLE_ENCODING,
            support_ref=support_ref,
        ))

    # ── 4. Delimiter detection ────────────────────────────────────
    lines = text_content.split("\n")
    non_empty_lines = [l for l in lines if l.strip()]

    if len(non_empty_lines) < 2:
        return _fail(ImportFailure.from_code(
            ImportErrorCode.NO_DATA_ROWS,
            support_ref=support_ref,
        ))

    # Try to detect delimiter from first few data-like lines
    delimiter = None
    for delim in [",", ";", "\t"]:
        # Count delimiters in the first few non-empty lines
        counts = [l.count(delim) for l in non_empty_lines[:5]]
        if all(c > 0 for c in counts) and len(set(counts)) <= 2:
            delimiter = delim
            break

    if delimiter is None:
        # Try pipe as last resort
        for l in non_empty_lines[:5]:
            if "|" in l:
                delimiter = "|"
                break

    if delimiter is None:
        return _fail(ImportFailure.from_code(
            ImportErrorCode.CSV_DELIMITER_NOT_RECOGNIZED,
            support_ref=support_ref,
        ))

    # ── 5. Header detection ───────────────────────────────────────
    header_row = None
    header_row_index = None
    header_area = "\n".join(non_empty_lines[:20])

    for i, line in enumerate(non_empty_lines[:100]):
        try:
            reader = csv.reader(StringIO(line), delimiter=delimiter)
            cells = next(reader)
        except Exception:
            continue

        # Check if any cell matches a known header sentinel
        for cell in cells:
            if cell.strip().lower() in _HEADER_SENTINELS:
                header_row = cells
                header_row_index = i
                break
        if header_row:
            break

    if header_row is None:
        # For binary-supported formats, don't fail on missing text header
        if ext in (".ibt", ".ld", ".ldx", ".vbo", ".xrk", ".drk"):
            return _ok(detected_format=ext.lstrip(".").upper())

        return _fail(ImportFailure.from_code(
            ImportErrorCode.HEADER_NOT_FOUND,
            support_ref=support_ref,
        ))

    columns = [c.strip() for c in header_row if c.strip()]
    columns_lower = [c.lower() for c in columns]

    # ── 6. Source detection ───────────────────────────────────────
    detected_source = _detect_source_from_content(header_area, columns, ext)

    # ── 7. Data row count check ───────────────────────────────────
    data_lines = non_empty_lines[header_row_index + 1:] if header_row_index is not None else []
    data_row_count = len(data_lines)
    if data_row_count < _MIN_DATA_ROWS:
        # For the 64KB sample, estimate total rows from file size
        if file_size > 64 * 1024:
            avg_line_len = len(text_content) / max(len(non_empty_lines), 1)
            estimated_total = int(file_size / avg_line_len)
            if estimated_total >= _MIN_DATA_ROWS:
                data_row_count = estimated_total  # Estimate passes
            else:
                return _fail(ImportFailure.from_code(
                    ImportErrorCode.NO_DATA_ROWS,
                    support_ref=support_ref,
                    detected_format=detected_source,
                    extra_context={"row_count": data_row_count},
                ), detected_source=detected_source)
        else:
            return _fail(ImportFailure.from_code(
                ImportErrorCode.NO_DATA_ROWS,
                support_ref=support_ref,
                detected_format=detected_source,
                extra_context={"row_count": data_row_count},
            ), detected_source=detected_source)

    # ── 8. Required channel checks ────────────────────────────────
    has_time = any(c in _TIME_PATTERNS for c in columns_lower)
    has_distance = any(c in _DISTANCE_PATTERNS for c in columns_lower)
    has_gps_lat = any(c in _GPS_LAT_PATTERNS for c in columns_lower)
    has_gps_lon = any(c in _GPS_LON_PATTERNS for c in columns_lower)
    has_gps = has_gps_lat and has_gps_lon
    has_speed = any(c in _SPEED_PATTERNS for c in columns_lower)

    if not has_time and not has_distance:
        return _fail(ImportFailure.from_code(
            ImportErrorCode.MISSING_TIME_COLUMN,
            support_ref=support_ref,
            detected_format=detected_source,
            extra_context={"available_columns": columns[:20]},
        ), detected_source=detected_source, columns=columns)

    if not has_gps and not has_speed:
        # Need at least GPS or speed to do anything useful
        return _fail(ImportFailure.from_code(
            ImportErrorCode.MISSING_GPS_LAT_LON,
            support_ref=support_ref,
            detected_format=detected_source,
            message_override="No GPS or speed channels found. LAP needs at least GPS coordinates or speed data.",
            extra_context={"available_columns": columns[:20]},
        ), detected_source=detected_source, columns=columns)

    # ── 9. Channel coverage check ─────────────────────────────────
    useful_channels = sum([has_time, has_distance, has_gps, has_speed])
    if useful_channels < 2 and len(columns) < 3:
        return _fail(ImportFailure.from_code(
            ImportErrorCode.INSUFFICIENT_CHANNEL_COVERAGE,
            support_ref=support_ref,
            detected_format=detected_source,
            extra_context={"channel_count": len(columns), "available_columns": columns[:20]},
        ), detected_source=detected_source, columns=columns)

    # ── All checks passed ─────────────────────────────────────────
    return _ok(
        detected_format=detected_source,
        detected_source=detected_source,
        columns=columns,
        row_count=data_row_count,
        delimiter=delimiter,
        has_gps=has_gps,
        has_speed=has_speed,
        has_time=has_time,
    )
