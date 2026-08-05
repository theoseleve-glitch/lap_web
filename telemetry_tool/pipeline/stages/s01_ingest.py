"""
Stage 01 -- CSV Ingest + Column Discovery + Adapter Compatibility.

Reads a telemetry CSV file via the adapter registry (preferred) or
the legacy RaceChrono reader, applies reverse canonical-to-RaceChrono
column mapping for downstream compatibility, and runs column discovery.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)

# Which of the two readers produced the frame. Recorded on `source_info` (and
# thence on the pipeline summary) because the choice is not cosmetic: the two
# readers hand downstream stages DIFFERENT COLUMN NAMES, and corner detection
# gives a different answer as a result. See `_ensure_package_root_on_path`.
INGEST_PATH_ADAPTER = "adapter_registry"
INGEST_PATH_LEGACY = "legacy_racechrono"


def _ensure_package_root_on_path() -> None:
    """Make ``telemetry_tool`` importable as a package from ANY launcher.

    THIS IS NOT HOUSEKEEPING. ``run_ingest`` selects the adapter registry with
    ``from telemetry_tool.adapters import parse_file`` -- an ABSOLUTE package
    import needing the REPO ROOT on ``sys.path``, not merely ``telemetry_tool/``
    (the registry's own modules import ``telemetry_tool.adapters.base`` in turn,
    so a bare ``from adapters import ...`` cannot substitute). Production
    supplies both (``Dockerfile``: ``PYTHONPATH=/app:/app/telemetry_tool``) and
    so does pytest (``telemetry_tool/tests/`` and ``telemetry_tool/`` are both
    packages, so pytest's basedir walk inserts the repo root, and
    ``tests/conftest.py`` inserts ``telemetry_tool/``). An ad-hoc script that
    adds only ``telemetry_tool/`` got an ImportError that this function's
    caller used to swallow with a bare ``pass``.

    The consequences were not subtle -- measured on ``data/raw/OK_R4.csv``,
    same file, same cwd, same track-registry isolation, ONLY sys.path differing:

        repo root present  -> adapter registry -> 8 corners, 72 corner-laps,
                              143 driving events; columns ``Speed (m/s)``,
                              ``Satellites``
        repo root absent   -> legacy reader    -> 6 corners, 42 corner-laps,
                              93 driving events; columns ``Speed (m/s) *calc``
                              AND ``Speed (m/s)``, ``Satellites (sats)``

    Blocking ``kart_envelope`` instead leaves 8/72/143 untouched, and blocking
    ``telemetry_tool.adapters`` with the repo root present reproduces 6/42/93
    exactly -- so the adapter import is the whole of the difference.

    Idempotent, and never removes or reorders an existing entry.

    APPENDED, never inserted at position 0 (fix round 2). The repo root holds
    top-level ``config/``, ``tools/``, ``tests/``, ``src/`` and ``data/``
    directories, and putting it first would let those shadow same-named
    installed packages for the rest of the process. Appending means an
    installed package still wins; the only thing this needs to achieve is that
    ``telemetry_tool`` becomes importable AT ALL, and for that, position is
    irrelevant. The early return keeps the blast radius to ad-hoc scripts
    anyway -- production and pytest both already supply the root.
    """
    try:
        import telemetry_tool  # noqa: F401
        return
    except ImportError:
        pass
    # .../<repo root>/telemetry_tool/pipeline/stages/s01_ingest.py
    root = str(Path(__file__).resolve().parents[3])
    if root not in sys.path:
        sys.path.append(root)
        logger.info(
            "Appended %s to sys.path so the adapter registry is importable "
            "(the launcher did not provide it)", root,
        )


# ── Adapter compatibility: canonical → RaceChrono column names ───
# The adapter registry renames columns to canonical names, but
# downstream modules still expect raw RaceChrono column names.
# Reverse-map the essential columns so the pipeline works with both.
_CANONICAL_TO_RAW: dict[str, str] = {
    "time_s": "Time (s)",
    "speed_mps": "Speed (m/s)",
    "distance_m": "Distance (m)",
    "lap_number": "Lap #",
    "lat_deg": "Latitude (deg)",
    "lon_deg": "Longitude (deg)",
    "altitude_m": "Altitude (m)",
    "heading_deg": "Bearing (deg)",
    "satellites": "Satellites",
    "accuracy_m": "Accuracy (m)",
}


def derive_missing_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Derive distance_m and lap_number when the source format lacks them.

    Called after canonical->RaceChrono reverse mapping, so column names are
    RaceChrono-style ("Distance (m)", "Lap #", etc.).

    Mutates *df* in-place and returns it.
    """
    # Derive distance from speed integration
    if "Distance (m)" not in df.columns and "Speed (m/s)" in df.columns and "Time (s)" in df.columns:
        try:
            from scipy.integrate import cumulative_trapezoid
            speed = pd.to_numeric(df["Speed (m/s)"], errors="coerce").fillna(0).values
            time = pd.to_numeric(df["Time (s)"], errors="coerce").ffill().fillna(0).values
            dist = cumulative_trapezoid(speed, time, initial=0)
            df["Distance (m)"] = dist
            logger.info("Derived Distance (m) from speed integration")
        except ImportError:
            logger.warning("scipy not available; cannot derive Distance (m)")

    # Sentinel lap number if not present (pipeline stages 3-5 derive real laps)
    if "Lap #" not in df.columns:
        df["Lap #"] = 0
        logger.info("Set sentinel Lap # = 0 (will be derived by track detection)")

    return df


def _try_import_discover():
    """Import column discovery; returns ``discover_columns`` or None."""
    try:
        from telemetry_tool.column_discovery import discover_columns
        return discover_columns
    except ImportError:
        pass
    try:
        from column_discovery import discover_columns  # type: ignore[import-untyped]
        return discover_columns
    except ImportError:
        logger.warning("column_discovery module unavailable")
        return None


def run_ingest(
    csv_path: str,
    *,
    progress_callback: Any = None,
) -> tuple[Optional[pd.DataFrame], dict[str, Any]]:
    """Ingest CSV file via adapter registry or RaceChrono reader.

    Parameters
    ----------
    csv_path:
        Path to the CSV (or supported) telemetry file.
    progress_callback:
        Optional progress callback forwarded to the adapter.

    Returns
    -------
    (raw_df, source_info)
        *raw_df* is the ingested DataFrame (None on total failure).
        *source_info* is a dict with keys: ``source_format``,
        ``available_channels``, ``data_tier``, ``source_metadata``,
        ``channel_discovery``.  Empty dict on failure.
    """
    source_info: dict[str, Any] = {}
    raw_df: Optional[pd.DataFrame] = None

    # ── 1. Try adapter registry (handles all formats) ────────────
    #
    # The import and the parse are caught SEPARATELY, and both are logged.
    # They are different events with different fixes: "no registered adapter
    # recognised this file" is ordinary and expected for an unsupported
    # format, while "the registry itself could not be imported" means this
    # process is about to silently ingest via a different reader that yields
    # different column names and a different corner count. Collapsing the two
    # into one bare `except ... : pass` is what let that divergence run
    # unnoticed -- see `_ensure_package_root_on_path` for the measurements.
    _ensure_package_root_on_path()
    _parse_file = None
    try:
        from telemetry_tool.adapters import parse_file as _parse_file
    except ImportError as exc:
        logger.warning(
            "Adapter registry could not be imported (%s) -- falling back to "
            "the legacy RaceChrono reader. Column names and corner detection "
            "WILL differ from a production run.", exc,
        )

    if _parse_file is not None:
        try:
            _df, _adapter = _parse_file(csv_path, progress_cb=progress_callback)
            source_info["source_format"] = _adapter.FORMAT_NAME
            source_info["available_channels"] = _adapter.available_channels()
            source_info["data_tier"] = _adapter.data_tier()
            source_info["source_metadata"] = _adapter.metadata()
            source_info["ingest_path"] = INGEST_PATH_ADAPTER
            raw_df = _df
        except (ValueError, ImportError) as exc:
            logger.info(
                "No registered adapter parsed %s (%s) -- using the legacy "
                "RaceChrono reader", csv_path, exc,
            )

    # ── 2. Fallback to original RaceChrono reader ────────────────
    if raw_df is None:
        source_info["ingest_path"] = INGEST_PATH_LEGACY
        io_mod = lazy_import("io_racechrono")
        if io_mod is None:
            try:
                io_mod = lazy_import("telemetry_tool.io_racechrono")
            except Exception:
                pass
        if io_mod is None:
            logger.error("No adapter matched and io_racechrono unavailable")
            return None, {}
        raw_df = io_mod.read_racechrono_csv(csv_path)

    if raw_df is None or raw_df.empty:
        logger.error("Ingest produced empty or None DataFrame.")
        return None, {}

    # ── 3. Reverse canonical → RaceChrono column names ───────────
    _reverse = {
        k: v
        for k, v in _CANONICAL_TO_RAW.items()
        if k in raw_df.columns and v not in raw_df.columns
    }
    if _reverse:
        raw_df = raw_df.rename(columns=_reverse)
        logger.info(
            "Reversed canonical→RaceChrono names: %s",
            list(_reverse.values()),
        )

    # ── 3b. Derive missing columns (distance, lap) ────────────────
    raw_df = derive_missing_columns(raw_df)

    # ── 4. Column discovery ──────────────────────────────────────
    _discover = _try_import_discover()
    if _discover is not None:
        try:
            _channel_discovery = _discover(raw_df)
            source_info["channel_discovery"] = _channel_discovery.to_dict()
            logger.info(
                "Column discovery: %d channels (%d custom), format=%s",
                len(_channel_discovery.channels),
                len(_channel_discovery.custom_channels),
                _channel_discovery.format,
            )
        except Exception as exc:
            logger.warning("Column discovery failed: %s — raw names preserved", exc)

    return raw_df, source_info
