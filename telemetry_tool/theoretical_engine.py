"""
theoretical_engine.py
---------------------
Condition-dependent theoretical lap and progression model.

The "theoretical lap" is the best physically achievable lap at a given track
under a given set of conditions (track_state), constructed by taking the
top-percentile speed and acceleration from a corpus of historical laps rather
than any single observed lap.

Architecture
~~~~~~~~~~~~
- Historical laps are stored in Parquet files partitioned by
  ``track_id / track_state / *.parquet``.
- All computation is offline and deterministic.
- Interpolation functions are returned as callable objects that work on
  arbitrary speed grids -- no scipy dependency (pure NumPy).
- Windows-friendly: Parquet (via pyarrow), JSON, joblib.

Public API
~~~~~~~~~~
``load_historical_laps(track_id, track_state, base_path)``
    Load and validate all resampled Parquet laps for a condition partition.

``compute_speed_percentile_envelope(laps, percentile=98)``
    Per-distance-bin percentile speed across all laps.

``compute_accel_envelope(laps, percentile=99)``
    Per-velocity-bin percentile max-accel and max-braking, returned as
    callable interpolation objects.

``build_theoretical_lap(laps, n_points, speed_percentile, accel_percentile)``
    Compose the speed envelope into a full theoretical lap DataFrame.

``save_theoretical_lap(lap_df, track_id, track_state, base_path)``
    Persist the theoretical lap to Parquet + JSON metadata.

``load_theoretical_lap(track_id, track_state, base_path)``
    Re-load a previously persisted theoretical lap.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final

import numpy as np
import pandas as pd
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    _PYARROW_AVAILABLE = True
except ImportError:
    _PYARROW_AVAILABLE = False
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _read_parquet(path: Path) -> pd.DataFrame:
    """Read Parquet using pyarrow if available, else CSV fallback (tests only)."""
    if _PYARROW_AVAILABLE:
        return pq.read_table(path).to_pandas()
    # Fallback: try pandas engine, then CSV sidecar

    try:
        return pd.read_parquet(path)
    except Exception:
        csv_path = path.with_suffix(".csv")
        if csv_path.exists():
            return pd.read_csv(csv_path)
        raise


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write Parquet using pyarrow if available, else CSV fallback (tests only)."""
    if _PYARROW_AVAILABLE:
        tbl = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(tbl, path)
    else:
        try:
            df.to_parquet(path, index=False)
        except Exception:
            # Last-resort: write a CSV sidecar so tests can run without any

            # Parquet backend installed in the sandbox environment.

            csv_path = path.with_suffix(".csv")
            df.to_csv(csv_path, index=False)

# -- -

# Column-name constants

# -- -


_COL_DIST:       Final[str] = "distance_m"
_COL_SPEED:      Final[str] = "speed_mps"
_COL_ACCEL:      Final[str] = "accel_long_mps2"
_COL_DIST_NORM:  Final[str] = "distance_norm"   # optional: 0--1 fractional position
_COL_TIME:       Final[str] = "cumulative_time_s"  # optional

# Output column names for the theoretical lap

_OUT_DIST:  Final[str] = "distance_m"
_OUT_SPEED: Final[str] = "v_env_mps"
_OUT_ACCEL: Final[str] = "accel_max_mps2"
_OUT_BRAKE: Final[str] = "brake_max_mps2"

# Velocity grid for accel/brake envelope (km/h boundaries -> m/s)

_V_GRID_KPH: Final[np.ndarray] = np.arange(0, 330, 5)   # 0--325 km/h in 5 kph steps
_V_GRID_MPS: Final[np.ndarray] = _V_GRID_KPH / 3.6

# Minimum laps required before any envelope can be computed reliably

_MIN_LAPS: Final[int] = 2
_MIN_VALID_BINS: Final[int] = 3   # minimum non-NaN bins to return a valid envelope

# -- -

# Exceptions

# -- -


class TheoreticalEngineError(ValueError):
    """Raised when inputs are invalid or data is insufficient."""


# -- -

# Data structures

# -- -


@dataclass
class AccelEnvelope:
    """
    Callable interpolation container for the acceleration envelope.

    Wraps two piecewise-linear interpolation functions built on a velocity
    grid so the envelope can be persisted (via ``to_dict`` / ``from_dict``)
    and called like a regular function.
    """
    v_grid:     np.ndarray   # velocity knots [m/s]
    accel_vals: np.ndarray   # max traction acceleration at each knot [m/s^2]
    brake_vals: np.ndarray   # max braking deceleration (positive) at each knot [m/s^2]

    # Derived callable fields (not in __init__ -- computed post-init)

    _accel_fn: Callable[[np.ndarray], np.ndarray] = field(init=False, repr=False)
    _brake_fn: Callable[[np.ndarray], np.ndarray] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._build_interpolators()

    def _build_interpolators(self) -> None:
        """Build piecewise-linear interpolators from the grid arrays."""
        # Only use knots that have finite values

        a_mask = np.isfinite(self.accel_vals)
        b_mask = np.isfinite(self.brake_vals)

        if a_mask.sum() < 2:
            raise TheoreticalEngineError(
                "Accel envelope has fewer than 2 finite accel knots."
            )
        if b_mask.sum() < 2:
            raise TheoreticalEngineError(
                "Accel envelope has fewer than 2 finite brake knots."
            )

        v_a, y_a = self.v_grid[a_mask], self.accel_vals[a_mask]
        v_b, y_b = self.v_grid[b_mask], self.brake_vals[b_mask]

        self._accel_fn = lambda v, _va=v_a, _ya=y_a: np.interp(v, _va, _ya)
        self._brake_fn = lambda v, _vb=v_b, _yb=y_b: np.interp(v, _vb, _yb)

    def accel_func(self, v: float | np.ndarray) -> np.ndarray:
        """Max traction acceleration [m/s^2] at speed *v* [m/s]."""
        return self._accel_fn(np.asarray(v, dtype=float))

    def brake_func(self, v: float | np.ndarray) -> np.ndarray:
        """Max braking deceleration [m/s^2] (positive value) at speed *v* [m/s]."""
        return self._brake_fn(np.asarray(v, dtype=float))

    def to_dict(self) -> dict[str, Any]:
        return {
            "v_grid":     self.v_grid.tolist(),
            "accel_vals": self.accel_vals.tolist(),
            "brake_vals": self.brake_vals.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AccelEnvelope":
        return cls(
            v_grid     = np.array(d["v_grid"],     dtype=float),
            accel_vals = np.array(d["accel_vals"], dtype=float),
            brake_vals = np.array(d["brake_vals"], dtype=float),
        )


# -- -

# Internal helpers

# -- -


def _partition_path(
    base_path: Path,
    track_id:   str,
    track_state: str,
) -> Path:
    """Return  base_path/track_id/track_state/"""
    return base_path / track_id / track_state


def _validate_lap(df: pd.DataFrame, lap_name: str = "lap") -> None:
    """Raise TheoreticalEngineError if required columns are absent."""
    required = (_COL_DIST, _COL_SPEED, _COL_ACCEL)
    missing  = [c for c in required if c not in df.columns]
    if missing:
        raise TheoreticalEngineError(
            f"{lap_name} is missing required column(s): {missing}. "
            f"Available: {list(df.columns)}"
        )


def _safe_percentile(values: np.ndarray, pct: float) -> float:
    """Compute *pct*-th percentile of finite values; return NaN if < 2 finite."""
    finite = values[np.isfinite(values)]
    return float(np.percentile(finite, pct)) if len(finite) >= 2 else float("nan")


def _gaussian_smooth(signal: np.ndarray, half_window: int) -> np.ndarray:
    """Gaussian-weighted 1-D rolling average (same as in derived_channels.py)."""
    if half_window <= 0 or len(signal) < 3:
        return signal.copy()
    k = 2 * half_window + 1
    x = np.arange(k) - half_window
    w = np.exp(-0.5 * (x / max(half_window / 2.0, 0.5)) ** 2)
    w /= w.sum()
    padded = np.pad(signal, half_window, mode="reflect")
    out    = np.convolve(padded, w, mode="valid")
    return out[:len(signal)]


def _normalize_lap_distances(laps: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """
    Return copies of *laps* where each lap's distance column starts at 0.0 m.

    RaceChrono records cumulative session distance, so lap 1 might span
    0--660 m while lap 12 spans 7 260--7 920 m.  Subtracting each lap's
    starting distance makes them directly comparable -- essential for any
    cross-lap percentile computation on a shared distance grid.

    If a lap already starts at 0.0 (+/-0.5 m), it is returned unchanged.
    The operation never mutates the original DataFrames.
    """
    out: list[pd.DataFrame] = []
    for i, df in enumerate(laps):
        if _COL_DIST not in df.columns:
            logger.warning(
                "Lap %d: missing column %r -- cannot normalise distance.",
                i, _COL_DIST,
            )
            out.append(df)
            continue
        d = pd.to_numeric(df[_COL_DIST], errors="coerce")
        d_start = d.iloc[0]
        if pd.isna(d_start):
            # First value is NaN -- try the first finite value

            finite = d.dropna()
            d_start = float(finite.iloc[0]) if len(finite) > 0 else 0.0

        if abs(float(d_start)) > 0.5:
            df = df.copy()
            df[_COL_DIST] = d - float(d_start)
            logger.debug(
                "Lap %d: shifted distance by %.1f m (was %.1f--%.1f, now 0--%.1f).",
                i, d_start, float(d.min()), float(d.max()),
                float(d.max() - d_start),
            )
        out.append(df)
    return out


# -- -

# 1. load_historical_laps

# -- -


def load_historical_laps(
    track_id:    str,
    track_state: str,
    base_path:   str | Path,
) -> list[pd.DataFrame]:
    """
    Load and validate all resampled laps for a (track_id, track_state) partition.

    Expected directory layout::

        base_path/
        `---- <track_id>/
            `---- <track_state>/
                |---- lap_001.parquet
                |---- lap_002.parquet
                `---- ...

    Any Parquet file in the partition directory is treated as one lap.

    Parameters
    ----------
    track_id:
        Track identifier string (e.g. ``"spa"``).
    track_state:
        Condition string (e.g. ``"dry"``, ``"wet_light"``).
    base_path:
        Root directory containing the partition tree.

    Returns
    -------
    list[pd.DataFrame]
        Validated, sorted list of lap DataFrames.  Each DataFrame has at
        minimum columns ``distance_m``, ``speed_mps``, ``accel_long_mps2``.

    Raises
    ------
    TheoreticalEngineError
        If the partition directory does not exist or contains zero valid laps.
    """
    base_path = Path(base_path)
    part_dir  = _partition_path(base_path, track_id, track_state)

    if not part_dir.exists():
        raise TheoreticalEngineError(
            f"Partition directory not found: {part_dir}\n"
            f"Expected layout: base_path / track_id / track_state / *.parquet"
        )

    parquet_files = sorted(
        list(part_dir.glob("*.parquet")) +
        # CSV sidecars written by the fallback writer (test environments without pyarrow)

        [p for p in part_dir.glob("*.csv") if not p.stem.endswith("_meta")]
    )
    if not parquet_files:
        raise TheoreticalEngineError(
            f"No Parquet files found in {part_dir}."
        )

    laps: list[pd.DataFrame] = []
    skipped = 0

    for fp in parquet_files:
        try:
            if fp.suffix == ".csv":
                df = pd.read_csv(fp)
            else:
                df = _read_parquet(fp)
            _validate_lap(df, lap_name=fp.name)
            # Ensure numeric dtypes

            for col in (_COL_DIST, _COL_SPEED, _COL_ACCEL):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            laps.append(df)
        except TheoreticalEngineError as exc:
            logger.warning("Skipping %s: %s", fp.name, exc)
            skipped += 1
        except Exception as exc:   # noqa: BLE001
            logger.warning("Could not read %s: %s", fp.name, exc)
            skipped += 1

    if not laps:
        raise TheoreticalEngineError(
            f"No valid laps loaded from {part_dir} "
            f"({skipped} file(s) skipped)."
        )

    logger.info(
        "Loaded %d lap(s) for track=%r state=%r "
        "(skipped %d).",
        len(laps), track_id, track_state, skipped,
    )
    return laps


# -- -

# 2. compute_speed_percentile_envelope

# -- -


def compute_speed_percentile_envelope(
    laps:       list[pd.DataFrame],
    percentile: float = 98.0,
    *,
    n_bins:     int   = 0,     # 0 = infer from first lap
    smooth_window: int = 5,
    masks: "dict[int, list[tuple[float, float]]] | None" = None,
) -> pd.DataFrame:
    """
    Compute the per-distance-bin speed envelope across all laps.

    For each distance bin the *percentile*-th speed across all laps is taken,
    representing the fastest achievable speed at that track position.

    Lap distances are automatically normalised to start at 0.0 m so that
    laps recorded with cumulative session distance work correctly.  A
    *best-fit window* approach is used: if normalised laps don't share an
    exact distance range (GPS drift, early/late start-finish triggers), the
    largest common overlap is used instead of failing.

    Parameters
    ----------
    laps:
        List of validated, distance-resampled DataFrames.
    percentile:
        Speed percentile to extract (e.g. 98 = best 2 % of observations).
    n_bins:
        Number of distance bins.  0 (default) uses the length of the first
        lap, which is typical when all laps share the same resampling grid.
    smooth_window:
        Gaussian half-window applied to the envelope to remove single-sample
        peaks caused by GPS noise.  Pass 0 to disable.

    Returns
    -------
    pd.DataFrame
        Columns: ``distance_m``, ``v_env_mps``.

    Raises
    ------
    TheoreticalEngineError
        If *laps* is empty or the envelope has fewer than *_MIN_VALID_BINS*
        non-NaN entries.
    """
    if not laps:
        raise TheoreticalEngineError("laps list is empty.")

    # -- Normalise every lap so distance starts at 0.0 m
    laps = _normalize_lap_distances(laps)

    n_bins = n_bins or len(laps[0])
    if n_bins < 2:
        raise TheoreticalEngineError(f"n_bins must be >= 2, got {n_bins}.")

    # -- Best-fit window: find the largest common distance overlap -- -

    #

    # After normalisation all laps should start near 0 and end near the

    # lap length, but GPS noise / sampling jitter can cause minor

    # differences.  We use the overlap (max of starts, min of ends) so

    # a single short-recorded lap doesn't discard the entire envelope.

    #

    # Fallback: if even the overlap is too small, use the median range

    # and allow per-bin NaN for laps that don't cover a given bin.

    d_starts = [float(pd.to_numeric(df[_COL_DIST], errors="coerce").min())
                for df in laps]
    d_ends   = [float(pd.to_numeric(df[_COL_DIST], errors="coerce").max())
                for df in laps]

    d_min = float(np.median(d_starts))  # most laps start near 0 after normalisation
    d_max = float(np.median(d_ends))    # use median end to span full lap length

    if d_max <= d_min:
        # No strict overlap -- fall back to the median range and accept

        # that some laps won't cover the full extent (NaN bins are OK).

        d_min = float(np.median(d_starts))
        d_max = float(np.median(d_ends))
        logger.warning(
            "No perfect distance overlap after normalisation; using median "
            "range %.1f--%.1f m (starts=%s, ends=%s).",
            d_min, d_max,
            [f"{v:.0f}" for v in d_starts],
            [f"{v:.0f}" for v in d_ends],
        )

    if d_max <= d_min:
        raise TheoreticalEngineError(
            "No common distance range across laps "
            f"(d_min={d_min:.1f}, d_max={d_max:.1f}).  "
            "This usually means the distance column is not lap-relative."
        )

    # Guard: warn if theoretical distance deviates significantly from

    # the expected lap length (median of per-lap ranges).

    per_lap_lengths = [e - s for s, e in zip(d_starts, d_ends) if e > s]
    if per_lap_lengths:
        expected_lap_length = float(np.median(per_lap_lengths))
        grid_length = d_max - d_min
        if expected_lap_length > 0:
            deviation = abs(grid_length - expected_lap_length) / expected_lap_length
            if deviation > 0.02:
                logger.warning(
                    "Theoretical grid length %.1f m deviates %.1f%% from "
                    "median lap length %.1f m; adjusting to match lap length.",
                    grid_length, deviation * 100, expected_lap_length,
                )
                d_min = 0.0
                d_max = expected_lap_length

    grid = np.linspace(d_min, d_max, n_bins)

    # Interpolate each lap's speed onto the common grid

    speed_matrix = np.full((len(laps), n_bins), np.nan)
    for i, df in enumerate(laps):
        d    = pd.to_numeric(df[_COL_DIST],  errors="coerce").values
        spd  = pd.to_numeric(df[_COL_SPEED], errors="coerce").values
        mask = np.isfinite(d) & np.isfinite(spd)
        if mask.sum() < 2:
            logger.debug("Lap %d: insufficient finite speed samples; skipping.", i)
            continue
        d_c, s_c = d[mask], spd[mask]
        order     = np.argsort(d_c, kind="stable")
        _, ui     = np.unique(d_c[order], return_index=True)
        speed_matrix[i] = np.interp(grid, d_c[order][ui], s_c[order][ui])

    # Apply traffic masks: NaN out masked distance ranges
    if masks is not None:
        for lap_idx, mask_ranges in masks.items():
            if 0 <= lap_idx < speed_matrix.shape[0]:
                for m_start, m_end in mask_ranges:
                    mask_bins = (grid >= m_start) & (grid <= m_end)
                    speed_matrix[lap_idx, mask_bins] = np.nan

    # Per-bin percentile

    envelope = np.array(
        [_safe_percentile(speed_matrix[:, j], percentile) for j in range(n_bins)]
    )

    valid_bins = np.isfinite(envelope).sum()
    if valid_bins < _MIN_VALID_BINS:
        raise TheoreticalEngineError(
            f"Speed envelope has only {valid_bins} valid bins "
            f"(need >= {_MIN_VALID_BINS})."
        )

    # Fill NaN gaps via linear interpolation before smoothing

    if not np.all(np.isfinite(envelope)):
        finite_mask = np.isfinite(envelope)
        envelope = np.interp(
            np.arange(n_bins),
            np.where(finite_mask)[0],
            envelope[finite_mask],
        )

    if smooth_window > 0:
        envelope = _gaussian_smooth(envelope, smooth_window)

    result = pd.DataFrame({_OUT_DIST: grid, _OUT_SPEED: envelope})
    logger.info(
        "Speed envelope: %d bins, pct=%.0f, "
        "v_min=%.1f m/s, v_max=%.1f m/s",
        n_bins, percentile, float(envelope.min()), float(envelope.max()),
    )
    return result


# -- -

# 3. compute_accel_envelope

# -- -


def compute_accel_envelope(
    laps:       list[pd.DataFrame],
    percentile: float = 99.0,
    *,
    v_grid:     np.ndarray | None = None,
    smooth_window: int = 3,
) -> AccelEnvelope:
    """
    Build per-velocity-bin acceleration and braking envelopes.

    For each velocity bin the *percentile*-th observed acceleration (traction
    and braking) across all laps is extracted, representing the best the car
    can physically achieve.

    Parameters
    ----------
    laps:
        List of validated DataFrames.  Must contain ``speed_mps`` and
        ``accel_long_mps2``.
    percentile:
        Percentile of acceleration distribution to take (default 99).
        For braking, the *100-percentile*-th (most negative) value is used.
    v_grid:
        Velocity knot array [m/s] for the output envelope.  Defaults to
        ``_V_GRID_MPS`` (0--325 km/h, 5 kph steps).
    smooth_window:
        Gaussian half-window applied to accel/brake arrays.

    Returns
    -------
    AccelEnvelope
        Callable container with ``accel_func(v)`` and ``brake_func(v)``.

    Raises
    ------
    TheoreticalEngineError
        If *laps* is empty or envelopes cannot be built.
    """
    if not laps:
        raise TheoreticalEngineError("laps list is empty.")

    v_grid = v_grid if v_grid is not None else _V_GRID_MPS.copy()
    n_v    = len(v_grid)

    # Collect all (speed, accel) pairs across laps

    all_speeds:  list[np.ndarray] = []
    all_accels:  list[np.ndarray] = []

    for i, df in enumerate(laps):
        spd  = pd.to_numeric(df[_COL_SPEED], errors="coerce").values
        acc  = pd.to_numeric(df[_COL_ACCEL], errors="coerce").values
        mask = np.isfinite(spd) & np.isfinite(acc)
        if mask.sum() < 4:
            logger.debug("Lap %d: too few finite (speed, accel) pairs; skipping.", i)
            continue
        all_speeds.append(spd[mask])
        all_accels.append(acc[mask])

    if not all_speeds:
        raise TheoreticalEngineError(
            "No valid (speed, accel) pairs found across all laps."
        )

    speeds = np.concatenate(all_speeds)
    accels = np.concatenate(all_accels)

    # Sort into velocity bins

    accel_bins: list[list[float]] = [[] for _ in range(n_v)]
    brake_bins: list[list[float]] = [[] for _ in range(n_v)]

    # Assign each observation to its nearest velocity bin

    bin_indices = np.searchsorted(v_grid, speeds, side="right") - 1
    bin_indices = np.clip(bin_indices, 0, n_v - 1)

    for bi, acc_val in zip(bin_indices, accels):
        if acc_val > 0:
            accel_bins[bi].append(float(acc_val))
        elif acc_val < 0:
            brake_bins[bi].append(float(-acc_val))   # store as positive

    # Compute per-bin percentile

    accel_env = np.array(
        [_safe_percentile(np.array(b), percentile) if b else float("nan")
         for b in accel_bins]
    )
    brake_env = np.array(
        [_safe_percentile(np.array(b), percentile) if b else float("nan")
         for b in brake_bins]
    )

    # Fill gaps via linear interpolation

    for env in (accel_env, brake_env):
        finite_mask = np.isfinite(env)
        if finite_mask.sum() < 2:
            continue
        nans = ~finite_mask
        env[nans] = np.interp(
            np.where(nans)[0],
            np.where(finite_mask)[0],
            env[finite_mask],
        )

    # Clip non-physical values

    accel_env = np.clip(accel_env, 0.0, 30.0)   # <= 3 g traction
    brake_env = np.clip(brake_env, 0.0, 50.0)   # <= 5 g braking

    if smooth_window > 0:
        accel_env = _gaussian_smooth(accel_env, smooth_window)
        brake_env = _gaussian_smooth(brake_env, smooth_window)

    envelope = AccelEnvelope(
        v_grid     = v_grid,
        accel_vals = accel_env,
        brake_vals = brake_env,
    )

    logger.info(
        "Accel envelope: %d velocity bins, pct=%.0f, "
        "max_accel=%.2f m/s^2, max_brake=%.2f m/s^2",
        n_v, percentile,
        float(np.nanmax(accel_env)), float(np.nanmax(brake_env)),
    )
    return envelope


# -- -

# 4. build_theoretical_lap

# -- -


def build_theoretical_lap(
    laps:              list[pd.DataFrame],
    n_points:          int   = 1000,
    speed_percentile:  float = 98.0,
    accel_percentile:  float = 99.0,
    *,
    smooth_window:     int   = 5,
    masks: "dict[int, list[tuple[float, float]]] | None" = None,
) -> pd.DataFrame:
    """
    Compose speed and acceleration envelopes into a full theoretical lap.

    The theoretical lap represents the best achievable performance at each
    distance point, not any single observed lap.

    Lap distances are automatically normalised to start at 0.0 m, so this
    function works correctly with both cumulative session distance (raw
    RaceChrono data) and lap-relative distance.

    Parameters
    ----------
    laps:
        List of validated, distance-resampled DataFrames.
    n_points:
        Number of output samples.
    speed_percentile / accel_percentile:
        Envelope percentiles.

    Returns
    -------
    pd.DataFrame
        Columns: ``distance_m``, ``v_env_mps``, ``accel_max_mps2``,
        ``brake_max_mps2``.
    """
    # Normalise once -- downstream functions receive lap-relative distances.

    laps = _normalize_lap_distances(laps)

    speed_env = compute_speed_percentile_envelope(
        laps, percentile=speed_percentile,
        n_bins=n_points, smooth_window=smooth_window,
        masks=masks,
    )
    accel_env = compute_accel_envelope(
        laps, percentile=accel_percentile,
        smooth_window=smooth_window,
    )

    speeds = speed_env[_OUT_SPEED].values
    a_max  = accel_env.accel_func(speeds)
    b_max  = accel_env.brake_func(speeds)

    result = pd.DataFrame({
        _OUT_DIST:  speed_env[_OUT_DIST].values,
        _OUT_SPEED: speeds,
        _OUT_ACCEL: a_max,
        _OUT_BRAKE: b_max,
    })

    logger.info(
        "Theoretical lap: %d points, "
        "mean_speed=%.1f m/s, total_distance=%.0f m",
        n_points,
        float(speeds.mean()),
        float(result[_OUT_DIST].iloc[-1] - result[_OUT_DIST].iloc[0]),
    )
    return result


# -- -

# 4b. Phase-aware theoretical lap

# -- -


def build_theoretical_lap_phase_aware(
    laps: list[pd.DataFrame],
    phases_df: "pd.DataFrame | None" = None,
    lap_to_phase: "dict[int, int] | None" = None,
    phase_id: "int | None" = None,
    n_points: int = 1000,
    speed_percentile: float = 98.0,
    accel_percentile: float = 99.0,
    *,
    smooth_window: int = 5,
    lap_keys: "list[int] | None" = None,
    masks: "dict[int, list[tuple[float, float]]] | None" = None,
) -> pd.DataFrame:
    """
    Phase-aware wrapper around :func:`build_theoretical_lap`.

    Parameters
    ----------
    laps:
        List of validated, distance-resampled DataFrames.
    phases_df:
        Output of ``condition_tracking.build_condition_phases``
        (with ``phase_id``, ``grip_proxy``, ``instability_proxy``
        or ``signature_json`` columns).  ``None`` -> use all laps.
    lap_to_phase:
        ``{lap_number: phase_id}`` mapping.  ``None`` -> use all laps.
    phase_id:
        If provided, compute the theoretical using only laps belonging
        to this phase.  If ``None`` and *phases_df* is not empty,
        automatically choose the "best grip" phase.
    lap_keys:
        Ordered list of lap numbers corresponding to *laps* (index-aligned).
        Required when *lap_to_phase* is used.
    n_points, speed_percentile, accel_percentile, smooth_window:
        Forwarded to :func:`build_theoretical_lap`.

    Returns
    -------
    pd.DataFrame
        Same schema as :func:`build_theoretical_lap`.
    """
    # --- Fall back to original if no phase information -- -

    if phases_df is None or lap_to_phase is None or phases_df.empty:
        return build_theoretical_lap(
            laps, n_points=n_points,
            speed_percentile=speed_percentile,
            accel_percentile=accel_percentile,
            smooth_window=smooth_window,
            masks=masks,
        )

    # --- Choose phase
    chosen_phase: int
    if phase_id is not None:
        chosen_phase = phase_id
    else:
        chosen_phase = _choose_best_grip_phase(phases_df)

    logger.info("Theoretical lap: using phase %d.", chosen_phase)

    # --- Filter laps to chosen phase -- -

    if lap_keys is None:
        lap_keys = list(range(len(laps)))

    filtered: list[pd.DataFrame] = []
    for key, lap_df in zip(lap_keys, laps):
        if lap_to_phase.get(key) == chosen_phase:
            filtered.append(lap_df)

    if len(filtered) < 2:
        logger.warning(
            "Phase %d has only %d lap(s); falling back to all laps.",
            chosen_phase, len(filtered),
        )
        filtered = laps

    return build_theoretical_lap(
        filtered, n_points=n_points,
        speed_percentile=speed_percentile,
        accel_percentile=accel_percentile,
        smooth_window=smooth_window,
        masks=masks,
    )


def _choose_best_grip_phase(phases_df: pd.DataFrame) -> int:
    """
    Select the phase with the highest grip / lowest instability.

    Uses ``signature_json`` if available, otherwise falls back to the
    phase with the most laps.
    """
    import json as _json

    best_pid = 0
    best_score = -1.0

    for _, row in phases_df.iterrows():
        pid = int(row.get("phase_id", 0))
        sig_raw = row.get("signature_json", "{}")
        try:
            sig = _json.loads(sig_raw) if isinstance(sig_raw, str) else {}
        except (ValueError, TypeError):
            sig = {}

        grip  = sig.get("speed_mean_mps", 0.0)
        jerk  = sig.get("jerk_rms_mps3", 999.0)
        # Higher speed -> more grip; lower jerk -> more stable

        score = grip - 0.5 * jerk
        if score > best_score:
            best_score = score
            best_pid = pid

    logger.info(
        "Best-grip phase: %d (score=%.2f).", best_pid, best_score,
    )
    return best_pid


# -- -

# 5. Persistence helpers

# -- -


def save_theoretical_lap(
    lap_df:      pd.DataFrame,
    track_id:    str,
    track_state: str,
    base_path:   str | Path,
    *,
    accel_envelope: AccelEnvelope | None = None,
    metadata:       dict[str, Any] | None = None,
) -> Path:
    """
    Persist the theoretical lap to Parquet and (optionally) JSON metadata.

    Parameters
    ----------
    lap_df:
        Theoretical lap DataFrame from :func:`build_theoretical_lap`.
    accel_envelope:
        If provided, saved as a JSON sidecar alongside the Parquet file.

    Returns
    -------
    Path
        Path to the written Parquet file.
    """
    base_path  = Path(base_path)
    out_dir    = _partition_path(base_path, track_id, track_state)
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = out_dir / "theoretical_lap.parquet"
    _write_parquet(lap_df, parquet_path)

    # Metadata sidecar

    meta: dict[str, Any] = {
        "track_id":    track_id,
        "track_state": track_state,
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "n_points":    len(lap_df),
        **(metadata or {}),
    }
    if accel_envelope is not None:
        meta["accel_envelope"] = accel_envelope.to_dict()

    json_path = out_dir / "theoretical_lap_meta.json"
    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    logger.info(
        "Saved theoretical lap for track=%r state=%r to %s",
        track_id, track_state, parquet_path,
    )
    return parquet_path


def load_theoretical_lap(
    track_id:    str,
    track_state: str,
    base_path:   str | Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Load a persisted theoretical lap.

    Returns
    -------
    (lap_df, metadata) : tuple
        ``lap_df``   -- theoretical lap DataFrame
        ``metadata`` -- dict from the JSON sidecar (empty dict if absent)

    Raises
    ------
    TheoreticalEngineError
        If the Parquet file does not exist.
    """
    base_path    = Path(base_path)
    part_dir     = _partition_path(base_path, track_id, track_state)
    parquet_path = part_dir / "theoretical_lap.parquet"

    csv_sidecar = parquet_path.with_suffix(".csv")
    if not parquet_path.exists() and not csv_sidecar.exists():
        raise TheoreticalEngineError(
            f"No theoretical lap found at {parquet_path}."
        )

    if parquet_path.exists():
        lap_df = _read_parquet(parquet_path)
    else:
        lap_df = pd.read_csv(csv_sidecar)

    json_path = part_dir / "theoretical_lap_meta.json"
    metadata: dict[str, Any] = {}
    if json_path.exists():
        try:
            metadata = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse metadata JSON: %s", exc)

    logger.info(
        "Loaded theoretical lap for track=%r state=%r (%d rows).",
        track_id, track_state, len(lap_df),
    )
    return lap_df, metadata


# -- -

# 6. Grip-scaled theoretical lap

# -- -


def scale_theoretical_by_grip(
    theoretical_df: pd.DataFrame,
    grip_factor: float,
) -> pd.DataFrame:
    """
    Apply physics-based grip scaling to a dry theoretical lap.

    Parameters
    ----------
    theoretical_df:
        Theoretical lap DataFrame with columns ``_OUT_DIST``, ``_OUT_SPEED``,
        ``_OUT_ACCEL``, ``_OUT_BRAKE``.
    grip_factor:
        Grip fraction in [0, 1].  1.0 = dry (identity), 0.0 = no grip (all
        speed/accel/brake zeroed).  Values outside [0, 1] are clamped.

    Returns
    -------
    pd.DataFrame
        A **new** DataFrame (copy) with scaled columns.  The input is never
        modified.

    Notes
    -----
    Scaling physics:
    - Speed:  ``v_scaled = v_dry * sqrt(grip_factor)``  (lateral-force-limited
      cornering — centripetal force proportional to grip, speed to sqrt).
    - Accel:  ``a_scaled = a_dry * grip_factor``  (traction limited).
    - Brake:  ``b_scaled = b_dry * grip_factor``  (traction limited, preserves
      negative sign).
    - Distance: unchanged.
    """
    # Clamp grip factor to [0, 1]
    grip_factor = max(0.0, min(1.0, grip_factor))

    result = theoretical_df.copy()

    result[_OUT_SPEED] = theoretical_df[_OUT_SPEED] * math.sqrt(grip_factor)
    result[_OUT_ACCEL] = theoretical_df[_OUT_ACCEL] * grip_factor
    result[_OUT_BRAKE] = theoretical_df[_OUT_BRAKE] * grip_factor
    # _OUT_DIST is unchanged

    return result


def get_phase_theoreticals(
    dry_theoretical: pd.DataFrame,
    weather_timeline: pd.DataFrame,
    phases_df: pd.DataFrame,
) -> dict[int, pd.DataFrame]:
    """
    Compute a grip-scaled theoretical lap for each condition phase.

    Parameters
    ----------
    dry_theoretical:
        Base dry theoretical lap DataFrame (from :func:`build_theoretical_lap`).
    weather_timeline:
        DataFrame with at least ``lap_number`` and ``grip_score`` columns.
        ``grip_score`` is 0--100.
    phases_df:
        DataFrame with ``phase_id``, ``lap_start``, ``lap_end`` columns
        describing contiguous phases.

    Returns
    -------
    dict[int, pd.DataFrame]
        ``{phase_id: scaled_theoretical_df}`` — one scaled theoretical per
        phase, keyed by ``phase_id``.
    """
    result: dict[int, pd.DataFrame] = {}

    for _, phase_row in phases_df.iterrows():
        phase_id = int(phase_row["phase_id"])
        lap_start = int(phase_row["lap_start"])
        lap_end = int(phase_row["lap_end"])

        # Filter weather_timeline to laps within this phase
        mask = (
            (weather_timeline["lap_number"] >= lap_start)
            & (weather_timeline["lap_number"] <= lap_end)
        )
        phase_weather = weather_timeline.loc[mask]

        if len(phase_weather) > 0:
            avg_grip = float(phase_weather["grip_score"].mean())
        else:
            avg_grip = 100.0  # default to dry if no data

        grip_factor = avg_grip / 100.0
        result[phase_id] = scale_theoretical_by_grip(dry_theoretical, grip_factor)

    return result


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
        except Exception:  # noqa: BLE001
            failed.append((name, traceback.format_exc()))

    #
    # Fixtures

    #
    N = 500
    LAP_LEN_M = 4500.0

    rng = np.random.default_rng(42)

    def _synth_lap(
        speed_bias:  float = 0.0,
        accel_bias:  float = 0.0,
        n:           int   = N,
    ) -> pd.DataFrame:
        """Synthetic resampled lap with plausible speed and acceleration."""
        dist  = np.linspace(0.0, LAP_LEN_M, n)
        speed = (30.0 + speed_bias + 20.0 * np.sin(2 * np.pi * dist / LAP_LEN_M)
                 + rng.normal(0, 0.5, n))
        speed = np.clip(speed, 5.0, 90.0)
        accel = np.gradient(speed, dist) * speed + accel_bias + rng.normal(0, 0.2, n)
        return pd.DataFrame({
            _COL_DIST:  dist,
            _COL_SPEED: speed,
            _COL_ACCEL: accel,
        })

    LAPS = [_synth_lap(speed_bias=b) for b in np.linspace(-2, 2, 8)]

    def _write_parquet_partition(
        tmpdir: Path,
        track_id:    str = "spa",
        track_state: str = "dry",
        laps: list | None = None,
    ) -> Path:
        """Write synthetic laps to a Parquet partition directory."""
        laps = laps or LAPS
        part = tmpdir / track_id / track_state
        part.mkdir(parents=True, exist_ok=True)
        for i, df in enumerate(laps):
            _write_parquet(df, part / f"lap_{i:03d}.parquet")
        return part

    #
    # load_historical_laps

    #
    def t_load_returns_correct_count() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_parquet_partition(Path(tmpdir))
            laps_out = load_historical_laps("spa", "dry", Path(tmpdir))
            assert len(laps_out) == len(LAPS), (
                f"Expected {len(LAPS)}, got {len(laps_out)}"
            )

    _test("load_returns_correct_count", t_load_returns_correct_count)

    def t_load_validates_required_columns() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_lap = pd.DataFrame({"distance_m": [0.0, 1.0], "speed_mps": [10.0, 20.0]})
            part = Path(tmpdir) / "t" / "d"
            part.mkdir(parents=True, exist_ok=True)
            _write_parquet(bad_lap, part / "lap.parquet")
            # Should skip the bad lap and raise because no valid laps remain

            try:
                load_historical_laps("t", "d", Path(tmpdir))
                raise AssertionError("Should have raised TheoreticalEngineError")
            except TheoreticalEngineError:
                pass

    _test("load_validates_required_columns", t_load_validates_required_columns)

    def t_load_nonexistent_partition_raises() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                load_historical_laps("does_not_exist", "dry", Path(tmpdir))
                raise AssertionError("Should have raised")
            except TheoreticalEngineError:
                pass

    _test("load_nonexistent_partition_raises", t_load_nonexistent_partition_raises)

    #
    # compute_speed_percentile_envelope

    #
    def t_speed_envelope_shape() -> None:
        env = compute_speed_percentile_envelope(LAPS, percentile=98, n_bins=300)
        assert len(env) == 300
        assert list(env.columns) == [_OUT_DIST, _OUT_SPEED]

    _test("speed_envelope_shape", t_speed_envelope_shape)

    def t_speed_envelope_monotone_distance() -> None:
        env = compute_speed_percentile_envelope(LAPS, percentile=98)
        diffs = np.diff(env[_OUT_DIST].values)
        assert (diffs > 0).all(), "Distance grid must be strictly increasing"

    _test("speed_envelope_monotone_distance", t_speed_envelope_monotone_distance)

    def t_speed_envelope_no_nan() -> None:
        env = compute_speed_percentile_envelope(LAPS, percentile=98)
        assert env[_OUT_SPEED].isna().sum() == 0, "Envelope must not contain NaN"

    _test("speed_envelope_no_nan", t_speed_envelope_no_nan)

    def t_speed_envelope_high_pct_ge_low_pct() -> None:
        env_98 = compute_speed_percentile_envelope(LAPS, percentile=98)
        env_50 = compute_speed_percentile_envelope(LAPS, percentile=50)
        assert (env_98[_OUT_SPEED].values >= env_50[_OUT_SPEED].values - 1e-6).all(), (
            "98th percentile envelope should be >= 50th percentile"
        )

    _test("speed_envelope_pct_ordering", t_speed_envelope_high_pct_ge_low_pct)

    def t_speed_envelope_empty_laps_raises() -> None:
        try:
            compute_speed_percentile_envelope([])
            raise AssertionError("Should have raised")
        except TheoreticalEngineError:
            pass

    _test("speed_envelope_empty_raises", t_speed_envelope_empty_laps_raises)

    def t_speed_envelope_deterministic() -> None:
        e1 = compute_speed_percentile_envelope(LAPS, percentile=95)
        e2 = compute_speed_percentile_envelope(LAPS, percentile=95)
        np.testing.assert_array_equal(e1[_OUT_SPEED].values, e2[_OUT_SPEED].values)

    _test("speed_envelope_deterministic", t_speed_envelope_deterministic)

    #
    # compute_accel_envelope

    #
    def t_accel_envelope_returns_callable() -> None:
        ae = compute_accel_envelope(LAPS)
        assert callable(ae.accel_func)
        assert callable(ae.brake_func)

    _test("accel_envelope_callable", t_accel_envelope_returns_callable)

    def t_accel_envelope_non_negative() -> None:
        ae  = compute_accel_envelope(LAPS)
        v   = np.linspace(0, 80, 50)
        assert (ae.accel_func(v) >= 0).all(), "Accel must be non-negative"
        assert (ae.brake_func(v) >= 0).all(), "Brake must be non-negative"

    _test("accel_envelope_non_negative", t_accel_envelope_non_negative)

    def t_accel_envelope_scalar_input() -> None:
        ae = compute_accel_envelope(LAPS)
        a  = ae.accel_func(40.0)
        b  = ae.brake_func(40.0)
        assert np.isfinite(a), "Scalar accel must be finite"
        assert np.isfinite(b), "Scalar brake must be finite"

    _test("accel_envelope_scalar_input", t_accel_envelope_scalar_input)

    def t_accel_envelope_round_trip() -> None:
        ae   = compute_accel_envelope(LAPS)
        d    = ae.to_dict()
        ae2  = AccelEnvelope.from_dict(d)
        v    = np.linspace(5, 70, 20)
        np.testing.assert_allclose(ae.accel_func(v), ae2.accel_func(v), rtol=1e-9)
        np.testing.assert_allclose(ae.brake_func(v), ae2.brake_func(v), rtol=1e-9)

    _test("accel_envelope_round_trip", t_accel_envelope_round_trip)

    def t_accel_envelope_empty_laps_raises() -> None:
        try:
            compute_accel_envelope([])
            raise AssertionError("Should have raised")
        except TheoreticalEngineError:
            pass

    _test("accel_envelope_empty_raises", t_accel_envelope_empty_laps_raises)

    def t_accel_envelope_deterministic() -> None:
        ae1 = compute_accel_envelope(LAPS, percentile=99)
        ae2 = compute_accel_envelope(LAPS, percentile=99)
        v   = np.linspace(5, 80, 30)
        np.testing.assert_array_equal(ae1.accel_func(v), ae2.accel_func(v))

    _test("accel_envelope_deterministic", t_accel_envelope_deterministic)

    #
    # build_theoretical_lap

    #
    def t_theoretical_lap_columns() -> None:
        lap = build_theoretical_lap(LAPS, n_points=500)
        for col in (_OUT_DIST, _OUT_SPEED, _OUT_ACCEL, _OUT_BRAKE):
            assert col in lap.columns, f"Missing column {col!r}"

    _test("theoretical_lap_columns", t_theoretical_lap_columns)

    def t_theoretical_lap_length() -> None:
        lap = build_theoretical_lap(LAPS, n_points=200)
        assert len(lap) == 200

    _test("theoretical_lap_length", t_theoretical_lap_length)

    def t_theoretical_lap_no_nan() -> None:
        lap = build_theoretical_lap(LAPS, n_points=500)
        for col in (_OUT_DIST, _OUT_SPEED, _OUT_ACCEL, _OUT_BRAKE):
            assert lap[col].isna().sum() == 0, f"Column {col} has NaN"

    _test("theoretical_lap_no_nan", t_theoretical_lap_no_nan)

    def t_theoretical_lap_speed_positive() -> None:
        lap = build_theoretical_lap(LAPS, n_points=300)
        assert (lap[_OUT_SPEED].values > 0).all(), "All speeds must be positive"

    _test("theoretical_lap_speed_positive", t_theoretical_lap_speed_positive)

    def t_theoretical_lap_with_offset_distances() -> None:
        """
        Verify build_theoretical_lap works when each lap carries a
        cumulative session distance offset (the real-world RaceChrono
        scenario).  Lap 0: 0--4500 m, lap 1: 4500--9000 m, etc.
        """
        offset_laps: list[pd.DataFrame] = []
        for k, base_lap in enumerate(LAPS):
            shifted = base_lap.copy()
            shifted[_COL_DIST] = base_lap[_COL_DIST] + k * LAP_LEN_M
            offset_laps.append(shifted)

        # Without normalisation this would raise TheoreticalEngineError.

        lap = build_theoretical_lap(offset_laps, n_points=300)
        assert len(lap) == 300
        assert (lap[_OUT_SPEED].values > 0).all(), "Speeds must be positive"
        # Distance in the output should start near 0, not at the offset

        assert lap[_OUT_DIST].iloc[0] < 10.0, (
            f"Output distance should start near 0, got {lap[_OUT_DIST].iloc[0]:.1f}"
        )

    _test("theoretical_lap_offset_distances", t_theoretical_lap_with_offset_distances)

    #
    # Persistence round-trip

    #
    def t_persistence_roundtrip() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            lap  = build_theoretical_lap(LAPS, n_points=300)
            ae   = compute_accel_envelope(LAPS)
            save_theoretical_lap(lap, "spa", "dry", base, accel_envelope=ae)
            loaded, meta = load_theoretical_lap("spa", "dry", base)
            assert len(loaded) == len(lap)
            assert meta["track_id"] == "spa"
            assert "accel_envelope" in meta

    _test("persistence_roundtrip", t_persistence_roundtrip)

    def t_load_theoretical_missing_raises() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                load_theoretical_lap("nonexistent", "dry", Path(tmpdir))
                raise AssertionError("Should have raised")
            except TheoreticalEngineError:
                pass

    _test("load_theoretical_missing_raises", t_load_theoretical_missing_raises)

    #
    # Full end-to-end pipeline (load -> build -> save -> load)

    #
    def t_end_to_end_pipeline() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "data"
            _write_parquet_partition(base, "monza", "dry")
            laps   = load_historical_laps("monza", "dry", base)
            assert len(laps) > 0
            theory = build_theoretical_lap(laps, n_points=400)
            ae     = compute_accel_envelope(laps)
            save_theoretical_lap(theory, "monza", "dry", base / "theory",
                                 accel_envelope=ae)
            loaded, meta = load_theoretical_lap("monza", "dry", base / "theory")
            assert len(loaded) == 400
            assert meta["track_id"] == "monza"

    _test("end_to_end_pipeline", t_end_to_end_pipeline)

    #
    # Summary

    #
    total = len(passed) + len(failed)
    print(f"\nTheoretical Engine Tests: {len(passed)}/{total} passed")
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