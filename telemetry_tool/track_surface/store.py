"""
track_surface/store.py
----------------------
Persistent cross-session track model storage.

Hybrid approach:
- 1D per-metre properties → PG ``track_surfaces_global`` (online averaging)
- Array data (centerline, Frenet, 2D grip) → Parquet sidecar per track

Every session enriches the model; the solver reads the accumulated model.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from track_surface.centerline import extract_centerline
from track_surface.frenet import FrenetFrame
from track_surface.geometry_gates import GateReport, run_geometry_gates
from track_surface.grip_2d import GripSurface
from track_surface.model import TrackSurface

logger = logging.getLogger(__name__)

_MAX_DIVERGENCE_M = 20.0
_MAX_LENGTH_RATIO = 0.10  # 10% length mismatch → reject


# -- Sidecar path resolution -------------------------------------------------


def _default_sidecar_root() -> Path:
    """Resolve sidecar root.

    Precedence:
      1. ``SIDECAR_ROOT`` env var (production layout — set in docker-compose
         to ``/data/sidecars``, a Docker-volume-backed directory).
      2. ``<repo>/data/sidecars`` via ``parent.parent.parent`` from this file
         (dev / desktop layout).

    The env-var path exists because the Docker runtime layout has
    ``__file__`` at ``/app/telemetry_tool/track_surface/store.py``, which
    resolves the dev fallback to ``/app/data/sidecars`` — but ``/app/`` is
    root-owned in the runtime image, so the unprivileged ``app`` user can't
    create the directory. SIDECAR_ROOT lets the deployment point at a
    pre-created, writable, volume-backed path matching the existing
    ``/data/uploads`` etc. pattern.
    """
    env_root = os.environ.get("SIDECAR_ROOT")
    if env_root:
        root = Path(env_root)
    else:
        root = Path(__file__).resolve().parent.parent.parent / "data" / "sidecars"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _track_model_dir(track_id: str, sidecar_root: str | None = None) -> Path:
    """Base directory for a track's geometry (shared across classes/conditions)."""
    root = Path(sidecar_root) if sidecar_root else _default_sidecar_root()
    d = root / "track_models" / track_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _grip_model_dir(
    track_id: str,
    vehicle_class: str = "generic",
    condition: str = "dry",
    sidecar_root: str | None = None,
) -> Path:
    """Directory for class+condition-specific grip data."""
    base = _track_model_dir(track_id, sidecar_root)
    d = base / vehicle_class / condition
    d.mkdir(parents=True, exist_ok=True)
    return d


# -- Vehicle class detection --------------------------------------------------

_CLASS_KEYWORDS: dict[str, list[str]] = {
    "gt3":     ["gt3", "488 gt3", "huracan gt3", "911 gt3", "amg gt3", "m4 gt3"],
    "gt4":     ["gt4", "cayman gt4", "alpine gt4"],
    "formula": ["formula", "f3", "f4", "ir-04", "w12", "w13", "sf-23", "dallara"],
    "lmp":     ["lmp1", "lmp2", "lmdh", "hypercar", "963", "499p", "9x8"],
    "touring": ["tcr", "btcc", "wtcr", "civic", "elantra"],
    "kart":    ["kart", "rotax", "x30", "ok", "shifter"],
    "road":    ["road", "street", "mx-5", "miata"],
}


def detect_vehicle_class(vehicle_name: str | None = None) -> str:
    """Detect vehicle class from car name string.

    Returns one of: gt3, gt4, formula, lmp, touring, kart, road, generic.
    """
    if not vehicle_name:
        return "generic"
    name_lower = vehicle_name.lower()
    for cls, keywords in _CLASS_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return cls
    return "generic"


def detect_track_condition(
    track_wetness: float | None = None,
    grip_multiplier: float | None = None,
) -> str:
    """Detect track condition from telemetry metadata.

    Returns one of: dry, damp, wet, heavy_wet.
    """
    if track_wetness is not None:
        if track_wetness > 0.7:
            return "heavy_wet"
        if track_wetness > 0.3:
            return "wet"
        if track_wetness > 0.05:
            return "damp"
    if grip_multiplier is not None:
        if grip_multiplier < 0.7:
            return "wet"
        if grip_multiplier < 0.9:
            return "damp"
    return "dry"


# -- Load ---------------------------------------------------------------------


def load_track_model(
    track_id: str,
    sidecar_root: str | None = None,
    vehicle_class: str = "generic",
    condition: str = "dry",
) -> TrackSurface | None:
    """Load an accumulated TrackSurface from the Parquet sidecar.

    Geometry (centerline, boundaries, elevation) is shared across classes.
    Grip data is keyed by (vehicle_class, condition).

    Returns None if no model exists for this track.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError:
        logger.debug("pyarrow not available, cannot load track model sidecar")
        return None

    model_dir = _track_model_dir(track_id, sidecar_root)
    model_path = model_dir / "track_model.parquet"

    if not model_path.exists():
        return None

    try:
        table = pq.read_table(model_path)
        df = table.to_pandas()

        centerline_xy = np.column_stack([
            df["centerline_x"].to_numpy(),
            df["centerline_y"].to_numpy(),
        ])

        frenet = FrenetFrame.from_centerline(centerline_xy)

        n_laps = int(df["n_laps_accumulated"].iloc[0]) if "n_laps_accumulated" in df.columns else 1
        sim_sources = df["sim_sources"].iloc[0] if "sim_sources" in df.columns else []
        if isinstance(sim_sources, str):
            sim_sources = [s.strip() for s in sim_sources.split(",") if s.strip()]

        surface = TrackSurface(
            track_id=track_id,
            frenet=frenet,
            n_laps=n_laps,
            sim_sources=sim_sources,
        )

        # Load optional 1D arrays if present
        for col, attr in [
            ("width_left_m", "width_left"),
            ("width_right_m", "width_right"),
            ("elevation_m", "elevation_m"),
            ("slope_pct", "slope_pct"),
            ("vert_curvature_1pm", "vert_curvature_1pm"),
            ("camber_rad", "camber_rad"),
        ]:
            if col in df.columns:
                arr = df[col].to_numpy()
                if np.any(np.isfinite(arr)):
                    setattr(surface, attr, arr)

        # Load the 2D elevation surface z(s,n) — the quasi-3D geometry field's
        # source. Absent on pre-persistence / insufficient-lateral-coverage
        # tracks, in which case the solver honestly falls back to 2D.
        elev_path = model_dir / "elevation_surface.parquet"
        if elev_path.exists():
            surface.elevation_surface = _load_elevation_surface(elev_path)

        # Load 2D grip from class+condition-keyed directory
        grip_dir = _grip_model_dir(track_id, vehicle_class, condition, sidecar_root)
        grip_path = grip_dir / "grip_2d.parquet"
        if grip_path.exists():
            surface.grip_2d = _load_grip_2d(grip_path)
        else:
            # Fall back to base dir (legacy or generic grip)
            legacy_grip = model_dir / "grip_2d.parquet"
            if legacy_grip.exists():
                surface.grip_2d = _load_grip_2d(legacy_grip)

        logger.info("Loaded track model: track=%s, class=%s, cond=%s, laps=%d, tier=%s",
                     track_id, vehicle_class, condition, n_laps, surface.quality_tier)
        return surface

    except Exception as exc:
        logger.warning("Failed to load track model for %s: %s", track_id, exc)
        return None


def _load_grip_2d(path: Path) -> GripSurface | None:
    """Load a 2D grip grid from Parquet."""
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        df = table.to_pandas()

        s_bins = df["s_bins"].to_numpy()
        n_bins = df["n_bins"].to_numpy()
        M = int(df["grid_shape_m"].iloc[0])
        K = int(df["grid_shape_k"].iloc[0])
        mu_flat = df["mu_grid"].to_numpy()
        count_flat = df["count_grid"].to_numpy()

        mu_grid = mu_flat[:M * K].reshape(M, K)
        count_grid = count_flat[:M * K].reshape(M, K).astype(int)
        confidence = np.clip(count_grid / 50.0, 0.0, 1.0)

        if "mu_limit_grid" in df.columns:
            lim_flat = df["mu_limit_grid"].to_numpy()
            mu_limit_grid = lim_flat[:M * K].reshape(M, K)
            if np.isnan(mu_limit_grid).all():
                mu_limit_grid = None     # a written-but-empty limit == no limit
        else:
            mu_limit_grid = None

        return GripSurface(
            s_bins=s_bins[:M],
            n_bins=n_bins[:K],
            mu_grid=mu_grid,
            count_grid=count_grid,
            confidence=confidence,
            mu_limit_grid=mu_limit_grid,
        )
    except Exception as exc:
        logger.warning("Failed to load grip_2d: %s", exc)
        return None


# -- Merge --------------------------------------------------------------------


def merge_track_model(
    track_id: str,
    new_surface: TrackSurface,
    sidecar_root: str | None = None,
    vehicle_class: str = "generic",
    condition: str = "dry",
    on_geometry_rejected: Callable[[GateReport], None] | None = None,
) -> bool:
    """Merge a session's TrackSurface into the accumulated sidecar.

    Geometry (centerline, elevation, boundaries) merges into the shared
    base directory.  Grip data merges into the class+condition subdirectory.

    Creates the sidecar from scratch if none exists (bootstrap).
    Returns True on success, False if rejected or failed.

    Before the geometry parquet is written (either the bootstrap path or the
    merged path), the surface actually being written runs through
    ``run_geometry_gates`` (spec A3). A failing surface withholds ONLY that
    parquet write — grip/global persistence and the return value are
    unaffected — and, if given, ``on_geometry_rejected`` is invoked exactly
    once with the ``GateReport``. Callback exceptions are swallowed+logged so
    a broken caller can never break persistence.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        logger.debug("pyarrow not available, cannot save track model")
        return False

    model_dir = _track_model_dir(track_id, sidecar_root)
    model_path = model_dir / "track_model.parquet"
    grip_dir = _grip_model_dir(track_id, vehicle_class, condition, sidecar_root)

    existing = load_track_model(track_id, sidecar_root, vehicle_class, condition)

    if existing is None:
        # Bootstrap: save geometry to shared dir, grip to keyed dir
        report = run_geometry_gates(new_surface)
        if report.passed:
            _save_surface_parquet(model_path, new_surface)
            es = getattr(new_surface, "elevation_surface", None)
            if es is not None:
                _save_elevation_surface(model_dir / "elevation_surface.parquet", es)
        else:
            _reject_geometry(track_id, report, on_geometry_rejected)
        if new_surface.grip_2d is not None:
            _save_grip_2d(grip_dir / "grip_2d.parquet", new_surface.grip_2d)
        logger.info("Bootstrapped track model: track=%s, class=%s, cond=%s, laps=%d",
                     track_id, vehicle_class, condition, new_surface.n_laps)
        return True

    # Validate compatibility
    if not _validate_merge(existing, new_surface):
        return False

    # Merge centerline
    merged_cl, merged_length = _merge_centerlines(
        existing.frenet.centerline_xy, existing.n_laps,
        new_surface.frenet.centerline_xy, new_surface.n_laps,
    )
    merged_frenet = FrenetFrame.from_centerline(merged_cl)
    n_merged = existing.n_laps + new_surface.n_laps

    # Merge 1D properties via weighted average
    merged = TrackSurface(
        track_id=track_id,
        frenet=merged_frenet,
        n_laps=n_merged,
        sim_sources=list(set(existing.sim_sources + new_surface.sim_sources)),
    )

    n_old = existing.n_laps
    n_new = new_surface.n_laps

    for attr in ("elevation_m", "slope_pct", "vert_curvature_1pm", "camber_rad"):
        old_arr = getattr(existing, attr, None)
        new_arr = getattr(new_surface, attr, None)
        if old_arr is not None and new_arr is not None:
            # Resample new to merged grid length
            new_resampled = np.interp(
                np.linspace(0, 1, merged_frenet.n_points),
                np.linspace(0, 1, len(new_arr)),
                new_arr,
            )
            old_resampled = np.interp(
                np.linspace(0, 1, merged_frenet.n_points),
                np.linspace(0, 1, len(old_arr)),
                old_arr,
            )
            setattr(merged, attr, (old_resampled * n_old + new_resampled * n_new) / n_merged)
        elif old_arr is not None:
            setattr(merged, attr, np.interp(
                np.linspace(0, 1, merged_frenet.n_points),
                np.linspace(0, 1, len(old_arr)), old_arr,
            ))
        elif new_arr is not None:
            setattr(merged, attr, np.interp(
                np.linspace(0, 1, merged_frenet.n_points),
                np.linspace(0, 1, len(new_arr)), new_arr,
            ))

    # Width: running max (track doesn't shrink)
    for attr in ("width_left", "width_right"):
        old_arr = getattr(existing, attr, None)
        new_arr = getattr(new_surface, attr, None)
        if old_arr is not None and new_arr is not None:
            old_r = np.interp(np.linspace(0, 1, merged_frenet.n_points),
                              np.linspace(0, 1, len(old_arr)), old_arr)
            new_r = np.interp(np.linspace(0, 1, merged_frenet.n_points),
                              np.linspace(0, 1, len(new_arr)), new_arr)
            setattr(merged, attr, np.maximum(old_r, new_r))
        elif old_arr is not None:
            setattr(merged, attr, np.interp(
                np.linspace(0, 1, merged_frenet.n_points),
                np.linspace(0, 1, len(old_arr)), old_arr,
            ))
        elif new_arr is not None:
            setattr(merged, attr, np.interp(
                np.linspace(0, 1, merged_frenet.n_points),
                np.linspace(0, 1, len(new_arr)), new_arr,
            ))

    # Merge 2D grip grids
    if existing.grip_2d is not None and new_surface.grip_2d is not None:
        merged.grip_2d = _merge_grip_2d(existing.grip_2d, new_surface.grip_2d)
    elif new_surface.grip_2d is not None:
        merged.grip_2d = new_surface.grip_2d
    elif existing.grip_2d is not None:
        merged.grip_2d = existing.grip_2d

    # Merge 2D elevation surface (quasi-3D geometry source), mirroring grip.
    old_es = getattr(existing, "elevation_surface", None)
    new_es = getattr(new_surface, "elevation_surface", None)
    if old_es is not None and new_es is not None:
        merged.elevation_surface = _merge_elevation_surface(old_es, new_es)
    elif new_es is not None:
        merged.elevation_surface = new_es
    elif old_es is not None:
        merged.elevation_surface = old_es

    # Save
    report = run_geometry_gates(merged)
    if report.passed:
        _save_surface_parquet(model_path, merged)
        if getattr(merged, "elevation_surface", None) is not None:
            _save_elevation_surface(
                model_dir / "elevation_surface.parquet", merged.elevation_surface,
            )
    else:
        _reject_geometry(track_id, report, on_geometry_rejected)
    if merged.grip_2d is not None:
        _save_grip_2d(grip_dir / "grip_2d.parquet", merged.grip_2d)

    logger.info("Merged track model: track=%s, laps=%d→%d, tier=%s",
                track_id, existing.n_laps, n_merged, merged.quality_tier)
    return True


def _reject_geometry(
    track_id: str,
    report: GateReport,
    on_geometry_rejected: Callable[[GateReport], None] | None,
) -> None:
    """Log a gate rejection and fire the callback at most once.

    The callback is user/caller-supplied (e.g. pipeline audit recording) and
    must never be allowed to break persistence — exceptions are swallowed
    and logged, never propagated.
    """
    logger.warning("geometry gates rejected %s: %s", track_id,
                    [f.gate for f in report.failures])
    if on_geometry_rejected is None:
        return
    try:
        on_geometry_rejected(report)
    except Exception as exc:
        logger.warning("on_geometry_rejected callback raised for %s: %s", track_id, exc)


def _validate_merge(existing: TrackSurface, new: TrackSurface) -> bool:
    """Check that two surfaces are compatible for merging."""
    len_old = existing.frenet.total_length_m
    len_new = new.frenet.total_length_m

    if len_old > 0 and abs(len_new - len_old) / len_old > _MAX_LENGTH_RATIO:
        logger.warning(
            "Track length mismatch: existing=%.0fm, new=%.0fm (>%.0f%% diff) — rejecting merge",
            len_old, len_new, _MAX_LENGTH_RATIO * 100,
        )
        return False

    # Check max positional divergence
    n_check = min(existing.frenet.n_points, new.frenet.n_points, 200)
    old_sample = existing.frenet.centerline_xy[
        np.linspace(0, existing.frenet.n_points - 1, n_check, dtype=int)
    ]
    new_sample = new.frenet.centerline_xy[
        np.linspace(0, new.frenet.n_points - 1, n_check, dtype=int)
    ]
    dists = np.sqrt(np.sum((old_sample - new_sample) ** 2, axis=1))
    max_div = float(np.max(dists))

    if max_div > _MAX_DIVERGENCE_M:
        logger.warning(
            "Centerline divergence %.1fm > %.1fm — rejecting merge (wrong track?)",
            max_div, _MAX_DIVERGENCE_M,
        )
        return False

    return True


def _merge_centerlines(
    cl_old: np.ndarray, n_old: int,
    cl_new: np.ndarray, n_new: int,
) -> tuple[np.ndarray, float]:
    """Weighted-average merge of two centerlines, then re-fit B-spline."""
    # Resample both to the same point count
    n_pts = max(len(cl_old), len(cl_new))

    old_resampled = np.column_stack([
        np.interp(np.linspace(0, 1, n_pts), np.linspace(0, 1, len(cl_old)), cl_old[:, 0]),
        np.interp(np.linspace(0, 1, n_pts), np.linspace(0, 1, len(cl_old)), cl_old[:, 1]),
    ])
    new_resampled = np.column_stack([
        np.interp(np.linspace(0, 1, n_pts), np.linspace(0, 1, len(cl_new)), cl_new[:, 0]),
        np.interp(np.linspace(0, 1, n_pts), np.linspace(0, 1, len(cl_new)), cl_new[:, 1]),
    ])

    total = n_old + n_new
    merged = (old_resampled * n_old + new_resampled * n_new) / total

    # Re-fit via extract_centerline for smoothing
    return extract_centerline([merged], ds_m=1.0)


def _merge_grip_2d(old: GripSurface, new: GripSurface) -> GripSurface:
    """Merge two 2D grip grids: mean by additive sum/count, LIMIT by NaN-aware MAX."""
    # Use the grid with more bins as the base
    if old.mu_grid.size >= new.mu_grid.size:
        base_s, base_n = old.s_bins, old.n_bins
        M, K = old.mu_grid.shape
        merged_sum = old.mu_grid * old.count_grid
        merged_count = old.count_grid.copy()

        has_any_limit = old.mu_limit_grid is not None or new.mu_limit_grid is not None
        merged_limit = (
            old.mu_limit_grid.copy() if old.mu_limit_grid is not None
            else np.full((M, K), np.nan)
        )

        # Add new grid's data, interpolating to base grid
        for si in range(len(new.s_bins)):
            for ni in range(len(new.n_bins)):
                if new.count_grid[si, ni] == 0:
                    continue
                # Find closest bin in base grid
                s_idx = int(np.argmin(np.abs(base_s - new.s_bins[si])))
                n_idx = int(np.argmin(np.abs(base_n - new.n_bins[ni])))
                if s_idx < M and n_idx < K:
                    merged_sum[s_idx, n_idx] += new.mu_grid[si, ni] * new.count_grid[si, ni]
                    merged_count[s_idx, n_idx] += new.count_grid[si, ni]
                if new.mu_limit_grid is not None:
                    merged_limit[s_idx, n_idx] = np.fmax(
                        merged_limit[s_idx, n_idx], new.mu_limit_grid[si, ni]
                    )
    else:
        return _merge_grip_2d(new, old)  # swap so larger is base (MAX is symmetric)

    has_data = merged_count > 0
    mu_grid = np.ones((M, K))
    mu_grid[has_data] = merged_sum[has_data] / merged_count[has_data]
    confidence = np.clip(merged_count / 50.0, 0.0, 1.0)

    return GripSurface(
        s_bins=base_s.copy(),
        n_bins=base_n.copy(),
        mu_grid=mu_grid,
        count_grid=merged_count,
        confidence=confidence,
        mu_limit_grid=(merged_limit if has_any_limit else None),
    )


def _merge_elevation_surface(old: Any, new: Any) -> Any:
    """Merge two elevation surfaces: count-weighted mean of z(s,n) and kv(s,n),
    mirroring _merge_grip_2d (the larger grid is the base). Cells with no samples
    in EITHER surface keep the base surface's gap-filled/interpolated value."""
    from track_surface.elevation import ElevationSurface
    if old.z_grid.size < new.z_grid.size:
        return _merge_elevation_surface(new, old)   # keep the larger grid as base

    base_s, base_n = old.s_bins, old.n_bins
    M, K = old.z_grid.shape
    z_sum = old.z_grid * old.count_grid
    kv_sum = old.kv_grid * old.count_grid
    merged_count = old.count_grid.copy()

    for si in range(len(new.s_bins)):
        for ni in range(len(new.n_bins)):
            c = new.count_grid[si, ni]
            if c == 0:
                continue
            s_idx = int(np.argmin(np.abs(base_s - new.s_bins[si])))
            n_idx = int(np.argmin(np.abs(base_n - new.n_bins[ni])))
            if s_idx < M and n_idx < K:
                z_sum[s_idx, n_idx] += new.z_grid[si, ni] * c
                kv_sum[s_idx, n_idx] += new.kv_grid[si, ni] * c
                merged_count[s_idx, n_idx] += c

    has_data = merged_count > 0
    z_grid = old.z_grid.copy()      # preserve gap-fills where no samples merged
    kv_grid = old.kv_grid.copy()
    z_grid[has_data] = z_sum[has_data] / merged_count[has_data]
    kv_grid[has_data] = kv_sum[has_data] / merged_count[has_data]
    confidence = np.clip(merged_count / 20.0, 0.0, 1.0)

    return ElevationSurface(
        s_bins=base_s.copy(),
        n_bins=base_n.copy(),
        z_grid=z_grid,
        kv_grid=kv_grid,
        count_grid=merged_count,
        confidence=confidence,
    )


# -- Save helpers -------------------------------------------------------------


def _save_surface_parquet(path: Path, surface: TrackSurface) -> None:
    """Save TrackSurface geometry + 1D arrays to Parquet."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    n = surface.frenet.n_points
    data = {
        "centerline_x": surface.frenet.centerline_xy[:, 0],
        "centerline_y": surface.frenet.centerline_xy[:, 1],
        "s_grid": surface.frenet.s_grid,
        "heading_rad": surface.frenet.heading_rad,
        "curvature_1pm": surface.frenet.curvature_1pm,
        "n_laps_accumulated": np.full(n, surface.n_laps),
        "sim_sources": np.full(n, ",".join(surface.sim_sources), dtype=object),
    }

    # Add optional 1D arrays
    for col, attr in [
        ("width_left_m", "width_left"),
        ("width_right_m", "width_right"),
        ("elevation_m", "elevation_m"),
        ("slope_pct", "slope_pct"),
        ("vert_curvature_1pm", "vert_curvature_1pm"),
        ("camber_rad", "camber_rad"),
    ]:
        arr = getattr(surface, attr, None)
        if arr is not None:
            # Resample to match centerline point count
            if len(arr) != n:
                arr = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(arr)), arr)
            data[col] = arr

    table = pa.table(data)
    pq.write_table(table, path, compression="snappy")


def _save_grip_2d(path: Path, grip: GripSurface) -> None:
    """Save 2D grip grid to Parquet."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    M, K = grip.mu_grid.shape

    # Pad bins to match flattened grid length
    max_len = M * K
    s_padded = np.zeros(max_len)
    s_padded[:len(grip.s_bins)] = grip.s_bins
    n_padded = np.zeros(max_len)
    n_padded[:len(grip.n_bins)] = grip.n_bins

    data = {
        "s_bins": s_padded,
        "n_bins": n_padded,
        "mu_grid": grip.mu_grid.flatten(),
        "count_grid": grip.count_grid.flatten().astype(float),
        "grid_shape_m": np.full(max_len, M),
        "grid_shape_k": np.full(max_len, K),
        "mu_limit_grid": (
            grip.mu_limit_grid.flatten()
            if grip.mu_limit_grid is not None
            else np.full(max_len, np.nan)
        ),
    }
    table = pa.table(data)
    pq.write_table(table, path, compression="snappy")


def _save_elevation_surface(path: Path, es: Any) -> None:
    """Save the 2D elevation surface z(s,n) grid to Parquet (mirrors _save_grip_2d).

    Persists the source of the quasi-3D geometry field. Without this the surface
    was rebuilt in-session and dropped, so a loaded/prod track had no elevation
    surface and the solver always honest-fell-back to 2D.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    M, K = es.z_grid.shape
    max_len = M * K
    s_padded = np.zeros(max_len)
    s_padded[:len(es.s_bins)] = es.s_bins
    n_padded = np.zeros(max_len)
    n_padded[:len(es.n_bins)] = es.n_bins

    data = {
        "s_bins": s_padded,
        "n_bins": n_padded,
        "z_grid": es.z_grid.flatten(),
        "kv_grid": es.kv_grid.flatten(),
        "count_grid": es.count_grid.flatten().astype(float),
        "grid_shape_m": np.full(max_len, M),
        "grid_shape_k": np.full(max_len, K),
    }
    table = pa.table(data)
    pq.write_table(table, path, compression="snappy")


def _load_elevation_surface(path: Path) -> Any:
    """Load the 2D elevation surface from Parquet (mirrors _load_grip_2d).

    Returns an ElevationSurface, or None on any read/shape error (the caller
    then leaves surface.elevation_surface at its None default -> honest 2D).
    """
    try:
        import pyarrow.parquet as pq

        from track_surface.elevation import ElevationSurface
        table = pq.read_table(path)
        df = table.to_pandas()

        s_bins = df["s_bins"].to_numpy()
        n_bins = df["n_bins"].to_numpy()
        M = int(df["grid_shape_m"].iloc[0])
        K = int(df["grid_shape_k"].iloc[0])
        z_grid = df["z_grid"].to_numpy()[:M * K].reshape(M, K)
        kv_grid = df["kv_grid"].to_numpy()[:M * K].reshape(M, K)
        count_grid = df["count_grid"].to_numpy()[:M * K].reshape(M, K).astype(int)
        # confidence divisor mirrors build_elevation_surface (count / 20).
        confidence = np.clip(count_grid / 20.0, 0.0, 1.0)

        return ElevationSurface(
            s_bins=s_bins[:M],
            n_bins=n_bins[:K],
            z_grid=z_grid,
            kv_grid=kv_grid,
            count_grid=count_grid,
            confidence=confidence,
        )
    except Exception as exc:
        logger.warning("Failed to load elevation_surface: %s", exc)
        return None


# -- PG upsert ----------------------------------------------------------------


def _grip_lat_stats_at(grip_2d: Any, s: float) -> tuple[float | None, float | None]:
    """Day-15 denorm helper: per-arclength mu_lat (p95, mean) from grip_2d.

    ``GripSurface`` stores a (M_s, K_n) grid of friction coefficient + sample
    counts per cell. To populate ``track_surfaces_global.mu_lat_*`` (which are
    per-arclength scalars), we aggregate the lateral slice at the nearest
    s-bin, weighted by per-cell sample count. Returns ``(None, None)`` when
    the slice has no observed samples — the loop then leaves mu_lat unset and
    the column default (0.0 from migration 059) covers the NOT NULL row.
    """
    if grip_2d is None:
        return None, None
    if not hasattr(grip_2d, "mu_grid") or not hasattr(grip_2d, "count_grid"):
        return None, None
    if grip_2d.mu_grid.size == 0:
        return None, None
    si = int(np.argmin(np.abs(grip_2d.s_bins - s)))
    counts = grip_2d.count_grid[si, :]
    mus = grip_2d.mu_grid[si, :]
    mask = (counts > 0) & np.isfinite(mus)
    if not mask.any():
        return None, None
    mus_w = mus[mask]
    counts_w = counts[mask].astype(float)
    total = float(counts_w.sum())
    if total <= 0:
        return None, None
    mu_mean = float((mus_w * counts_w).sum() / total)
    # Weighted 95th-percentile via sample-count expansion (cheap, M_n is small).
    order = np.argsort(mus_w)
    sorted_mus = mus_w[order]
    sorted_counts = counts_w[order]
    cum = np.cumsum(sorted_counts)
    threshold = 0.95 * cum[-1]
    idx = int(np.searchsorted(cum, threshold))
    idx = min(idx, len(sorted_mus) - 1)
    mu_p95 = float(sorted_mus[idx])
    return mu_p95, mu_mean


def upsert_global_surface(
    conn: Any,
    track_id: str,
    surface: TrackSurface,
    *,
    vehicle_class: str = "car",
    condition: str = "dry",
) -> int:
    """Upsert 1D surface properties into track_surfaces_global.

    Extends the existing grip data with elevation, width, camber,
    vertical curvature, and slope.

    Day-14 fix: ``ON CONFLICT`` was previously ``(track_id, distance_m)``
    — but the table's unique constraint is
    ``uq_track_surface_global_bin (track_id, distance_m, vehicle_class, condition)``.
    The mismatch raised ``InvalidColumnReference`` on every INSERT, leaving
    the connection in failed-txn state and zero bins written. The fix:
    (a) accept vehicle_class + condition kwargs to satisfy the constraint
    columns; (b) match the 4-column ON CONFLICT exactly; (c) keep mu_lat
    NOT NULL satisfied via the column defaults added in migration 059
    (this function doesn't carry mu_lat per bin — that's the grip path's
    job via ``upsert_global_grip``).

    Returns number of bins upserted.
    """
    if not track_id or track_id == "unknown_track":
        return 0

    frenet = surface.frenet
    grip_2d = getattr(surface, "grip_2d", None)
    updated = 0
    now = datetime.now(timezone.utc).isoformat()

    for i in range(frenet.n_points):
        s = frenet.s_grid[i]

        params: dict[str, Any] = {
            "track_id": track_id,
            "distance_m": round(float(s), 1),
            "vehicle_class": vehicle_class,
            "condition": condition,
            "last_updated": now,
        }

        # Collect available values
        col_updates = []
        for col, attr, merge in [
            ("elevation_m", "elevation_m", "avg"),
            ("slope_pct", "slope_pct", "avg"),
            ("vert_curvature_1pm", "vert_curvature_1pm", "avg"),
            ("camber_rad", "camber_rad", "avg"),
            ("width_left_m", "width_left", "max"),
            ("width_right_m", "width_right", "max"),
        ]:
            arr = getattr(surface, attr, None)
            if arr is not None and i < len(arr) and np.isfinite(arr[i]):
                params[col] = round(float(arr[i]), 6)
                col_updates.append((col, merge))

        # Day-15 denorm: pull mu_lat (p95, mean) from grip_2d for this bin.
        # avg merge mirrors the elevation/slope online-weighted-average pattern.
        mu_p95, mu_mean = _grip_lat_stats_at(grip_2d, float(s))
        if mu_p95 is not None:
            params["mu_lat_p95"] = round(mu_p95, 6)
            col_updates.append(("mu_lat_p95", "avg"))
        if mu_mean is not None:
            params["mu_lat_mean"] = round(mu_mean, 6)
            col_updates.append(("mu_lat_mean", "avg"))

        if not col_updates:
            continue

        # Build dynamic SET clause
        set_parts = ["last_updated = EXCLUDED.last_updated"]
        for col, merge in col_updates:
            if merge == "max":
                set_parts.append(
                    f"{col} = GREATEST(COALESCE(track_surfaces_global.{col}, EXCLUDED.{col}), EXCLUDED.{col})"
                )
            else:  # avg
                set_parts.append(
                    f"{col} = COALESCE("
                    f"(track_surfaces_global.{col} * track_surfaces_global.session_count + EXCLUDED.{col})"
                    f" / NULLIF(track_surfaces_global.session_count + 1, 0),"
                    f" EXCLUDED.{col})"
                )

        insert_cols = ", ".join(params.keys())
        insert_vals = ", ".join(f"%({k})s" for k in params.keys())
        set_clause = ", ".join(set_parts)

        sql = f"""
            INSERT INTO track_surfaces_global ({insert_cols})
            VALUES ({insert_vals})
            ON CONFLICT (track_id, distance_m, vehicle_class, condition)
            DO UPDATE SET {set_clause}
        """

        try:
            conn.execute(sql, params)
            updated += 1
        except Exception as exc:
            # Day-14: was DEBUG-level — escalated to WARNING. This pattern
            # has now hidden 4 critical bugs in 48h (column-name mismatch,
            # filesystem perms, track-detection mis-keying, ON CONFLICT
            # mismatch); silent swallows stop here too.
            logger.warning("Global surface upsert skip d=%.1f: %s", s, exc)

    if updated > 0:
        logger.info("Global surface upserted: track=%s, bins=%d", track_id, updated)

    return updated
