"""
track_detection.py
------------------
Identifies racing circuits from GPS telemetry by computing a lightweight
geometric fingerprint and matching it against a persisted track database.

Pipeline
~~~~~~~~
1. ``compute_track_fingerprint(df)``
   Extract lap length, bounding box, and start/finish coordinates from a
   telemetry DataFrame.

2. ``match_track(fingerprint, database)``
   Find the best-matching entry in the database, or declare a new track if
   no entry passes the similarity thresholds.

3. ``load_track_database(path)`` / ``save_track_database(database, path)``
   JSON persistence helpers.

4. ``register_or_match_track(df, db_path)``
   One-call convenience that loads the database, matches, auto-registers new
   tracks, saves, and returns the result.

Matching rules
~~~~~~~~~~~~~~
- Lap length within +/-``lap_length_tolerance`` (default 3 %).
- Bounding-box IoU (Intersection-over-Union) >= ``min_bbox_iou``
  (default 0.70) -- ensures boxes overlap substantially, not just partly.
- Both conditions must hold; the closest match by lap-length ratio is
  selected when multiple candidates pass.

Design principles
~~~~~~~~~~~~~~~~~
- All thresholds are keyword arguments; no magic numbers in logic paths.
- The database is a plain list[dict] so it serialises to JSON without a
  custom encoder.
- No global mutable state; the database dict is always loaded, modified, and
  saved within a single call scope.
- Structured logging only; zero print statements.
- All file I/O is isolated in two helpers so the rest is pure and testable.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from path_manager import get_models_dir

logger = logging.getLogger(__name__)

# -- -

# Column-name constants

# -- -


_COL_LAT:  Final[str] = "Latitude (deg)"
_COL_LON:  Final[str] = "Longitude (deg)"
_COL_DIST: Final[str] = "Distance (m)"
_COL_LAP:  Final[str] = "Lap #"
_COL_TIME: Final[str] = "Time (s)"

# -- -

# Defaults

# -- -


_DEFAULT_LAP_TOL:  Final[float] = 0.03   # +/-3 % lap-length tolerance
_DEFAULT_MIN_IOU:  Final[float] = 0.70   # minimum bounding-box IoU to match
_DB_FILENAME:      Final[str]   = "tracks.json"


# -- -

# Exceptions

# -- -


class TrackDetectionError(ValueError):
    """Raised when required data is missing or geometrically invalid."""


# -- -

# Data structures

# -- -


@dataclass
class BoundingBox:
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    #
    def area(self) -> float:
        """Area in (deg^2); only meaningful for IoU comparison, not physics."""
        w = max(0.0, self.lon_max - self.lon_min)
        h = max(0.0, self.lat_max - self.lat_min)
        return w * h

    def iou(self, other: "BoundingBox") -> float:
        """Intersection-over-Union with *other* bounding box."""
        inter_lat_min = max(self.lat_min, other.lat_min)
        inter_lat_max = min(self.lat_max, other.lat_max)
        inter_lon_min = max(self.lon_min, other.lon_min)
        inter_lon_max = min(self.lon_max, other.lon_max)

        inter_w = max(0.0, inter_lon_max - inter_lon_min)
        inter_h = max(0.0, inter_lat_max - inter_lat_min)
        inter   = inter_w * inter_h

        union = self.area() + other.area() - inter
        if union <= 0.0:
            return 0.0
        return inter / union

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> "BoundingBox":
        return cls(**d)


@dataclass
class TrackFingerprint:
    lap_length_m:    float          # median lap distance across all complete laps
    bbox:            BoundingBox    # GPS bounding box
    start_lat:       float          # mean latitude of start/finish line
    start_lon:       float          # mean longitude of start/finish line
    sample_count:    int            # total GPS samples used
    lap_count:       int            # number of complete laps analysed

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bbox"] = self.bbox.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrackFingerprint":
        bbox = BoundingBox.from_dict(d["bbox"])
        return cls(
            lap_length_m = d["lap_length_m"],
            bbox         = bbox,
            start_lat    = d["start_lat"],
            start_lon    = d["start_lon"],
            sample_count = d["sample_count"],
            lap_count    = d["lap_count"],
        )


@dataclass
class MatchResult:
    matched:      bool
    track_id:     str
    track_name:   str
    is_new:       bool            # True if this entry was just registered
    lap_length_m: float           # matched (or newly registered) lap length
    iou:          float           # bbox IoU with the matched entry (0 if new)
    length_ratio: float           # |new/stored - 1|; 0 if new

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -- -

# Internal helpers

# -- -


def _require_column(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        raise TrackDetectionError(
            f"Required column {col!r} not found. "
            f"Available: {list(df.columns)}"
        )


def _haversine_total_m(lat: np.ndarray, lon: np.ndarray) -> float:
    """
    Sum of point-to-point great-circle distances along a GPS trace (metres).

    Uses the haversine formula; accurate to <0.5 % for circuit-scale distances.
    """
    R = 6_371_000.0   # Earth radius in metres
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    dlat  = np.diff(lat_r)
    dlon  = np.diff(lon_r)
    a     = np.sin(dlat / 2) ** 2 + (
        np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2) ** 2
    )
    return float(2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1))).sum())


def _haversine_pair(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in metres."""
    R = 6_371_000.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + (
        math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def _default_db_path() -> Path:
    """Return Data/models/tracks.json via path_manager."""
    return get_models_dir() / _DB_FILENAME


# -- -

# Persistence

# -- -


def load_track_database(path: str | Path | None = None) -> list[dict[str, Any]]:
    """
    Load the track database from *path*.

    Returns an empty list if the file does not exist yet (first-run case).

    Parameters
    ----------
    path:
        JSON file path.  Defaults to ``Data/models/tracks.json``.

    Raises
    ------
    json.JSONDecodeError
        If the file exists but is not valid JSON.
    """
    path = Path(path) if path else _default_db_path()
    if not path.exists():
        logger.info("Track database not found at %s; starting empty.", path)
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    logger.info("Loaded %d track(s) from %s.", len(raw), path)
    return raw if isinstance(raw, list) else []


def save_track_database(
    database: list[dict[str, Any]],
    path: str | Path | None = None,
) -> None:
    """
    Persist *database* to *path* as pretty-printed JSON.

    Parameters
    ----------
    database:
        List of track entry dicts.
    path:
        JSON file path.  Defaults to ``Data/models/tracks.json``.
    """
    path = Path(path) if path else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(database, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved %d track(s) to %s.", len(database), path)


# -- -

# Core functions

# -- -


def compute_track_fingerprint(df: pd.DataFrame) -> TrackFingerprint:
    """
    Extract a geometric fingerprint from a telemetry DataFrame.

    Lap length
    ~~~~~~~~~~
    If ``Distance (m)`` is present, the median per-lap distance span is used
    (span = max_distance - min_distance within each lap group).  Fallback:
    haversine sum over the GPS trace of the longest complete lap.

    Bounding box
    ~~~~~~~~~~~~
    Derived from all GPS samples in *df* after NaN removal.

    Start/finish coordinate
    ~~~~~~~~~~~~~~~~~~~~~~~
    Mean lat/lon of the first 5 % of ``Time (s)`` samples (or first 5 % of
    rows if ``Time (s)`` is absent) -- approximates the location of the
    pit-exit / start-finish straight.

    Parameters
    ----------
    df:
        Telemetry DataFrame.  Must contain latitude and longitude columns.
        ``Lap #``, ``Distance (m)``, and ``Time (s)`` are used if present.

    Returns
    -------
    TrackFingerprint

    Raises
    ------
    TrackDetectionError
        If GPS columns are absent or contain insufficient valid data.
    """
    for col in (_COL_LAT, _COL_LON):
        _require_column(df, col)

    lat = pd.to_numeric(df[_COL_LAT], errors="coerce").dropna()
    lon = pd.to_numeric(df[_COL_LON], errors="coerce").dropna()

    valid_idx = lat.index.intersection(lon.index)
    lat = lat.loc[valid_idx].values
    lon = lon.loc[valid_idx].values

    if len(lat) < 10:
        raise TrackDetectionError(
            f"Insufficient valid GPS samples ({len(lat)}); need at least 10."
        )

    # --- Bounding box -- -

    bbox = BoundingBox(
        lat_min=float(lat.min()),
        lat_max=float(lat.max()),
        lon_min=float(lon.min()),
        lon_max=float(lon.max()),
    )

    # --- Lap length -- -

    lap_length_m: float
    lap_count    = 0

    if _COL_DIST in df.columns and _COL_LAP in df.columns:
        dist_numeric = pd.to_numeric(df[_COL_DIST], errors="coerce")
        lap_numeric  = pd.to_numeric(df[_COL_LAP],  errors="coerce")
        frame = pd.DataFrame({"lap": lap_numeric, "dist": dist_numeric}).dropna()
        # Only consider laps >= 1 (exclude outlap/lap-0)

        frame = frame[frame["lap"] >= 1]
        if not frame.empty:
            spans       = frame.groupby("lap")["dist"].apply(lambda s: s.max() - s.min())
            spans       = spans[spans > 0]
            lap_count   = int(len(spans))
            lap_length_m = float(spans.median()) if not spans.empty else 0.0
        else:
            lap_length_m = 0.0
    else:
        lap_length_m = 0.0

    # Fallback: haversine over the full GPS trace (approximates one lap

    # if the session is a single in-lap, or overestimates for multi-lap)

    if lap_length_m <= 0.0:
        logger.debug(
            "Distance column absent or zero; using haversine lap length estimate."
        )
        lap_length_m = _haversine_total_m(lat, lon)
        lap_count    = 1

    # --- Start/finish coordinate -- -

    n_sf = max(1, len(df) // 20)   # first 5 % of samples
    if _COL_TIME in df.columns:
        t_sorted = df.sort_values(_COL_TIME).head(n_sf)
    else:
        t_sorted = df.head(n_sf)

    sf_lat = pd.to_numeric(t_sorted[_COL_LAT], errors="coerce").dropna()
    sf_lon = pd.to_numeric(t_sorted[_COL_LON], errors="coerce").dropna()
    start_lat = float(sf_lat.mean()) if not sf_lat.empty else float(lat.mean())
    start_lon = float(sf_lon.mean()) if not sf_lon.empty else float(lon.mean())

    fp = TrackFingerprint(
        lap_length_m = round(lap_length_m, 1),
        bbox         = bbox,
        start_lat    = round(start_lat, 6),
        start_lon    = round(start_lon, 6),
        sample_count = len(lat),
        lap_count    = lap_count,
    )
    logger.info(
        "Fingerprint: lap_length=%.1f m  laps=%d  bbox=(%+.4f,%+.4f)--(%+.4f,%+.4f)",
        fp.lap_length_m, fp.lap_count,
        fp.bbox.lat_min, fp.bbox.lon_min,
        fp.bbox.lat_max, fp.bbox.lon_max,
    )
    return fp


def match_track(
    fingerprint: TrackFingerprint,
    database: list[dict[str, Any]],
    *,
    lap_length_tolerance: float = _DEFAULT_LAP_TOL,
    min_bbox_iou:         float = _DEFAULT_MIN_IOU,
) -> MatchResult:
    """
    Find the best-matching track in *database* for *fingerprint*.

    Selection criteria (both must pass)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. ``|candidate_length / query_length - 1| <= lap_length_tolerance``
    2. Bounding-box IoU >= ``min_bbox_iou``

    Among passing candidates the one with the smallest lap-length ratio
    difference is chosen.

    Parameters
    ----------
    fingerprint:
        Query fingerprint from :func:`compute_track_fingerprint`.
    database:
        List of stored track dicts (as returned by :func:`load_track_database`).
    lap_length_tolerance:
        Fractional tolerance on lap length.  Default: 0.03 (+/- 3 %).
    min_bbox_iou:
        Minimum bounding-box Intersection-over-Union.  Default: 0.70.

    Returns
    -------
    MatchResult
        If ``matched=True``, ``track_id`` and ``track_name`` identify the
        stored track.  If ``matched=False``, a new UUID ``track_id`` is
        suggested and ``is_new=True``.
    """
    best_entry:  dict[str, Any] | None = None
    best_ratio:  float = float("inf")
    best_iou:    float = 0.0
    best_composite: float = -1.0

    for entry in database:
        try:
            stored_fp = TrackFingerprint.from_dict(entry["fingerprint"])
        except (KeyError, TypeError):
            logger.warning("Skipping malformed database entry: %s", entry.get("track_id"))
            continue

        # Gate 1 -- lap length

        ratio = abs(stored_fp.lap_length_m / fingerprint.lap_length_m - 1.0)
        if ratio > lap_length_tolerance:
            continue

        # Gate 2 -- bounding box overlap

        iou = fingerprint.bbox.iou(stored_fp.bbox)
        if iou < min_bbox_iou:
            continue

        # Composite score: length similarity + bbox IoU + start/finish proximity

        length_sim = max(0.0, 1.0 - ratio / max(lap_length_tolerance, 1e-9))
        sf_dist = _haversine_pair(
            fingerprint.start_lat, fingerprint.start_lon,
            stored_fp.start_lat, stored_fp.start_lon,
        )
        sf_sim = max(0.0, 1.0 - sf_dist / 500.0)  # 500 m saturation
        composite = 0.40 * length_sim + 0.35 * iou + 0.25 * sf_sim

        # Guard: flag suspicious iou=1.0 + ratio=0.0 with low start/finish match

        if iou > 0.99 and ratio < 0.001 and sf_sim < 0.5:
            logger.warning(
                "Suspicious match for %r: iou=%.4f ratio=%.4f sf_dist=%.0f m "
                "-- start/finish mismatch may indicate different track configs.",
                entry.get("track_id"), iou, ratio, sf_dist,
            )

        if composite > best_composite:
            best_composite = composite
            best_ratio = ratio
            best_iou   = iou
            best_entry = entry

    if best_entry is not None:
        logger.info(
            "Track matched: %r (id=%s)  ratio=%.4f  iou=%.4f",
            best_entry["track_name"], best_entry["track_id"],
            best_ratio, best_iou,
        )
        return MatchResult(
            matched      = True,
            track_id     = best_entry["track_id"],
            track_name   = best_entry["track_name"],
            is_new       = False,
            lap_length_m = best_entry["fingerprint"]["lap_length_m"],
            iou          = round(best_iou, 4),
            length_ratio = round(best_ratio, 4),
        )

    # No match -- suggest a new track entry

    new_id = str(uuid.uuid4())
    logger.info(
        "No matching track found. New track suggested (id=%s).", new_id
    )
    return MatchResult(
        matched      = False,
        track_id     = new_id,
        track_name   = "Unknown Track",
        is_new       = True,
        lap_length_m = fingerprint.lap_length_m,
        iou          = 0.0,
        length_ratio = 0.0,
    )


def register_track(
    track_id:    str,
    track_name:  str,
    fingerprint: TrackFingerprint,
    database:    list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Add a new track entry to *database* and return the updated list.

    Does not persist to disk; call :func:`save_track_database` afterwards.

    Parameters
    ----------
    track_id:
        UUID string for the new entry.
    track_name:
        Human-readable name (e.g. ``"Spa-Francorchamps"``).
    fingerprint:
        Fingerprint to store.
    database:
        Existing database list (not mutated; a new list is returned).

    Returns
    -------
    list[dict]
        Updated database with the new entry appended.
    """
    entry: dict[str, Any] = {
        "track_id":   track_id,
        "track_name": track_name,
        "fingerprint": fingerprint.to_dict(),
    }
    updated = list(database) + [entry]
    logger.info(
        "Registered new track %r (id=%s)  lap_length=%.1f m.",
        track_name, track_id, fingerprint.lap_length_m,
    )
    return updated


def register_or_match_track(
    df:         pd.DataFrame,
    db_path:    str | Path | None = None,
    track_name: str = "Unknown Track",
    *,
    lap_length_tolerance: float = _DEFAULT_LAP_TOL,
    min_bbox_iou:         float = _DEFAULT_MIN_IOU,
) -> tuple[MatchResult, list[dict[str, Any]]]:
    """
    End-to-end convenience: fingerprint *df*, match against the database,
    auto-register if new, persist, and return the result.

    Parameters
    ----------
    df:
        Telemetry DataFrame.
    db_path:
        Path to the JSON database.  Defaults to ``Data/models/tracks.json``.
    track_name:
        Name to assign if a new track is registered.
    lap_length_tolerance / min_bbox_iou:
        Forwarded to :func:`match_track`.

    Returns
    -------
    (result, updated_database) : tuple
        ``result``           -- :class:`MatchResult`
        ``updated_database`` -- in-memory list (already saved to disk)
    """
    fingerprint = compute_track_fingerprint(df)
    database    = load_track_database(db_path)

    result = match_track(
        fingerprint,
        database,
        lap_length_tolerance=lap_length_tolerance,
        min_bbox_iou=min_bbox_iou,
    )

    if result.is_new:
        database = register_track(
            result.track_id, track_name, fingerprint, database
        )
        save_track_database(database, db_path)
        # Update the MatchResult to reflect the actual registered name
        # (match_track() defaults to "Unknown Track" for new tracks).
        result = MatchResult(
            matched      = result.matched,
            track_id     = result.track_id,
            track_name   = track_name,
            is_new       = result.is_new,
            lap_length_m = result.lap_length_m,
            iou          = result.iou,
            length_ratio = result.length_ratio,
        )
    else:
        logger.debug("Existing track matched; database not modified.")

    return result, database


# -- -

# Unit tests

# -- -


def _run_tests() -> None:
    import traceback
    import tempfile

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:   # type: ignore[type-arg]
        try:
            fn()
            passed.append(name)
        except Exception:   # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    #
    # Fixtures

    #

    def _circuit_df(
        lat0: float = 50.437,
        lon0: float = 6.025,
        radius_km: float = 1.0,
        laps: int = 3,
        hz: float = 10.0,
    ) -> pd.DataFrame:
        """
        Generate a synthetic circular circuit with `laps` complete loops.
        Lap length ~= 2pi x radius_km x 1000 metres.
        """
        circumference = 2 * np.pi * radius_km * 1000   # metres
        lap_time      = 90.0                            # seconds per lap
        total_time    = laps * lap_time
        n             = int(total_time * hz)

        t      = np.linspace(0, total_time, n)
        theta  = (2 * np.pi * t / lap_time)
        # Convert circle to lat/lon offset (approx 1 deg lat ~= 111 km)

        deg_km = 1 / 111.0
        lat    = lat0 + radius_km * deg_km * np.sin(theta)
        lon    = lon0 + radius_km * deg_km * np.cos(theta)
        dist   = (t / total_time) * circumference * laps   # cumulative distance

        lap_num = (t / lap_time).astype(int) + 1

        return pd.DataFrame({
            _COL_TIME:  t,
            _COL_LAT:   lat,
            _COL_LON:   lon,
            _COL_DIST:  dist,
            _COL_LAP:   lap_num,
        })

    #
    # Test 1 -- fingerprint: correct lap length (~= circumference)

    #
    def t_lap_length() -> None:
        radius_km     = 1.0
        expected_m    = 2 * np.pi * radius_km * 1000
        df = _circuit_df(radius_km=radius_km, laps=4)
        fp = compute_track_fingerprint(df)
        ratio = abs(fp.lap_length_m / expected_m - 1.0)
        assert ratio < 0.05, (
            f"Lap length {fp.lap_length_m:.1f} m deviates {ratio:.2%} from "
            f"expected {expected_m:.1f} m"
        )

    _test("fingerprint_lap_length", t_lap_length)

    #
    # Test 2 -- fingerprint: bounding box contains all points

    #
    def t_bounding_box() -> None:
        df = _circuit_df(lat0=51.5, lon0=-0.1, radius_km=0.5)
        fp = compute_track_fingerprint(df)
        lat = df[_COL_LAT].values
        lon = df[_COL_LON].values
        assert fp.bbox.lat_min <= lat.min() + 1e-9
        assert fp.bbox.lat_max >= lat.max() - 1e-9
        assert fp.bbox.lon_min <= lon.min() + 1e-9
        assert fp.bbox.lon_max >= lon.max() - 1e-9

    _test("fingerprint_bbox", t_bounding_box)

    #
    # Test 3 -- fingerprint: start/finish near circuit centre

    #
    def t_start_finish() -> None:
        lat0, lon0 = 48.862, 2.351
        df = _circuit_df(lat0=lat0, lon0=lon0, radius_km=0.8)
        fp = compute_track_fingerprint(df)
        # Start/finish should be within ~radius_km / 111 degrees of centre

        dist_deg = np.sqrt((fp.start_lat - lat0)**2 + (fp.start_lon - lon0)**2)
        assert dist_deg < 0.02, f"Start/finish too far from centre: {dist_deg:.4f} deg"

    _test("fingerprint_start_finish", t_start_finish)

    #
    # Test 4 -- matching: identical fingerprint -> same track

    #
    def t_match_identical() -> None:
        df = _circuit_df()
        fp = compute_track_fingerprint(df)
        db = [{"track_id": "abc-123", "track_name": "Test Circuit",
               "fingerprint": fp.to_dict()}]
        result = match_track(fp, db)
        assert result.matched
        assert result.track_id == "abc-123"
        assert not result.is_new

    _test("match_identical", t_match_identical)

    #
    # Test 5 -- matching: slightly different length (within 3 %) -> match

    #
    def t_match_within_tolerance() -> None:
        df = _circuit_df(radius_km=1.0)
        fp = compute_track_fingerprint(df)
        # Stored length is 2 % shorter

        stored_fp_dict         = fp.to_dict()
        stored_fp_dict["lap_length_m"] *= 0.98
        db = [{"track_id": "spa", "track_name": "Spa",
               "fingerprint": stored_fp_dict}]
        result = match_track(fp, db, lap_length_tolerance=0.03)
        assert result.matched, "2 % length diff should match within +/-3 % tolerance"

    _test("match_within_tolerance", t_match_within_tolerance)

    #
    # Test 6 -- matching: length differs by 5 % -> no match

    #
    def t_no_match_length() -> None:
        df = _circuit_df(radius_km=1.0)
        fp = compute_track_fingerprint(df)
        stored_fp_dict                = fp.to_dict()
        stored_fp_dict["lap_length_m"] *= 0.94   # 6 % shorter
        db = [{"track_id": "x", "track_name": "X",
               "fingerprint": stored_fp_dict}]
        result = match_track(fp, db, lap_length_tolerance=0.03)
        assert not result.matched, "6 % diff should not match +/-3 % tolerance"
        assert result.is_new

    _test("no_match_length", t_no_match_length)

    #
    # Test 7 -- matching: same length, different location -> no match (low IoU)

    #
    def t_no_match_location() -> None:
        df_spa  = _circuit_df(lat0=50.437, lon0=6.025,  radius_km=1.0)
        df_monz = _circuit_df(lat0=45.620, lon0=9.281,  radius_km=1.0)
        fp_spa  = compute_track_fingerprint(df_spa)
        fp_monz = compute_track_fingerprint(df_monz)
        db      = [{"track_id": "monza", "track_name": "Monza",
                    "fingerprint": fp_monz.to_dict()}]
        result  = match_track(fp_spa, db, min_bbox_iou=0.70)
        assert not result.matched, "Different location circuits should not match"

    _test("no_match_location", t_no_match_location)

    #
    # Test 8 -- BoundingBox IoU: same box -> 1.0

    #
    def t_iou_identical() -> None:
        bb = BoundingBox(50.0, 51.0, 6.0, 7.0)
        assert abs(bb.iou(bb) - 1.0) < 1e-9, f"IoU of identical boxes should be 1.0"

    _test("iou_identical_boxes", t_iou_identical)

    #
    # Test 9 -- BoundingBox IoU: non-overlapping -> 0.0

    #
    def t_iou_no_overlap() -> None:
        bb_a = BoundingBox(50.0, 51.0, 6.0,  7.0)
        bb_b = BoundingBox(52.0, 53.0, 8.0, 9.0)
        assert bb_a.iou(bb_b) == 0.0, "Non-overlapping boxes should have IoU = 0"

    _test("iou_no_overlap", t_iou_no_overlap)

    #
    # Test 10 -- auto-register: new track added and persisted

    #
    def t_register_new_track() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tracks.json"
            df = _circuit_df()
            result, db = register_or_match_track(df, db_path, track_name="Synthetic Circuit")
            assert result.is_new
            assert len(db) == 1
            assert db[0]["track_name"] == "Synthetic Circuit"
            assert db_path.exists(), "Database should have been persisted"

    _test("register_new_track", t_register_new_track)

    #
    # Test 11 -- auto-register: second call matches first registration

    #
    def t_second_call_matches() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tracks.json"
            df = _circuit_df(radius_km=1.0, laps=5)
            # First call -> registers

            r1, _ = register_or_match_track(df, db_path, track_name="Home Circuit")
            assert r1.is_new
            # Second call with same data -> should match

            r2, db2 = register_or_match_track(df, db_path)
            assert r2.matched, "Second call should match the first registration"
            assert r2.track_id == r1.track_id
            assert len(db2) == 1, "Database should still have one entry"

    _test("second_call_matches", t_second_call_matches)

    #
    # Test 12 -- two distinct circuits in one database

    #
    def t_two_distinct_circuits() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tracks.json"
            df_a = _circuit_df(lat0=50.0, lon0=6.0,  radius_km=1.0, laps=3)
            df_b = _circuit_df(lat0=45.0, lon0=9.0,  radius_km=1.5, laps=3)
            r_a, _ = register_or_match_track(df_a, db_path, track_name="Circuit A")
            r_b, _ = register_or_match_track(df_b, db_path, track_name="Circuit B")
            assert r_a.is_new
            assert r_b.is_new
            # Now query each again

            r_a2, _ = register_or_match_track(df_a, db_path)
            r_b2, _ = register_or_match_track(df_b, db_path)
            assert r_a2.track_id == r_a.track_id, "A should still match A"
            assert r_b2.track_id == r_b.track_id, "B should still match B"
            assert r_a2.track_id != r_b2.track_id, "A and B should not match each other"

    _test("two_distinct_circuits", t_two_distinct_circuits)

    #
    # Test 13 -- missing GPS columns raise TrackDetectionError

    #
    def t_missing_gps_columns() -> None:
        df = pd.DataFrame({"Time (s)": [0.0, 1.0], "Speed (m/s)": [10.0, 20.0]})
        try:
            compute_track_fingerprint(df)
            raise AssertionError("Should have raised TrackDetectionError")
        except TrackDetectionError:
            pass

    _test("missing_gps_raises", t_missing_gps_columns)

    #
    # Test 14 -- fingerprint serialisation round-trip

    #
    def t_fingerprint_roundtrip() -> None:
        df = _circuit_df()
        fp = compute_track_fingerprint(df)
        d  = fp.to_dict()
        fp2 = TrackFingerprint.from_dict(d)
        assert abs(fp.lap_length_m - fp2.lap_length_m) < 1e-3
        assert abs(fp.bbox.lat_min  - fp2.bbox.lat_min)  < 1e-9
        assert abs(fp.start_lat     - fp2.start_lat)     < 1e-9

    _test("fingerprint_roundtrip", t_fingerprint_roundtrip)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    print(f"\nTrack Detection Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()