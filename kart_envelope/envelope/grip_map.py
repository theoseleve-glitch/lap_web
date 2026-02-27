"""
grip_map.py
-----------
Spatial grip-map ingestion with telemetry/session fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.ingest.columns import COL_ACCEL_LAT, COL_ACCEL_LONG, COL_DIST
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.track.geometry import TrackGeometry

_G = 9.80665


@dataclass
class GripMapMeta:
    """Metadata for grip-map source selection and quality."""

    enabled: bool = False
    source: str = "disabled"  # exact_asset | fallback_telemetry | disabled
    map_path: str = ""
    method: str = "none"  # distance_interp | xy_nearest | telemetry_combined_g | condition_prior
    blend: float = 0.0
    n_points: int = 0
    mu_scale_min: float = 1.0
    mu_scale_max: float = 1.0
    mu_scale_mean: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "source": self.source,
            "map_path": self.map_path,
            "method": self.method,
            "blend": round(float(self.blend), 4),
            "n_points": int(self.n_points),
            "mu_scale_min": round(float(self.mu_scale_min), 4),
            "mu_scale_max": round(float(self.mu_scale_max), 4),
            "mu_scale_mean": round(float(self.mu_scale_mean), 4),
        }


def resolve_grip_scale_profile(
    geometry: TrackGeometry,
    metadata: SessionMetadata,
    config: KartEnvelopeConfig,
    *,
    fallback_df: pd.DataFrame | None = None,
    tracks_dir: Path | None = None,
) -> tuple[np.ndarray, GripMapMeta]:
    """
    Resolve grip scaling profile on geometry distance grid.

    Returns a per-segment multiplicative scale close to 1.0.
    """
    n = int(len(geometry.distance_m))
    if n <= 0:
        return np.array([], dtype=float), GripMapMeta(enabled=False, source="disabled")

    blend = float(np.clip(config.grip_map_blend, 0.0, 1.0))
    base = np.ones(n, dtype=float)
    if not bool(config.grip_enable_spatial_map):
        return base, _meta(
            enabled=False,
            source="disabled",
            map_path="",
            method="none",
            blend=blend,
            values=base,
        )

    for cand in _candidate_paths(metadata=metadata, tracks_dir=tracks_dir):
        loaded = _load_map_csv(cand)
        if loaded is None:
            continue
        method, values = _project_asset_to_track(geometry, loaded)
        if values is None:
            continue
        values = _smooth_profile(values)
        out = np.clip((1.0 - blend) * base + blend * values, 0.65, 1.15)
        return out, _meta(
            enabled=True,
            source="exact_asset",
            map_path=str(cand),
            method=method,
            blend=blend,
            values=out,
        )

    telemetry_values = _telemetry_fallback(geometry.distance_m, fallback_df)
    if telemetry_values is None:
        cond_prior = _condition_prior_scale(metadata.condition_label)
        values = np.full(n, cond_prior, dtype=float)
        method = "condition_prior"
    else:
        values = telemetry_values
        method = "telemetry_combined_g"
    values = _smooth_profile(values)
    out = np.clip((1.0 - blend) * base + blend * values, 0.65, 1.15)
    return out, _meta(
        enabled=True,
        source="fallback_telemetry",
        map_path="",
        method=method,
        blend=blend,
        values=out,
    )


def _candidate_paths(*, metadata: SessionMetadata, tracks_dir: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if metadata.track_grip_map_path:
        candidates.append(Path(str(metadata.track_grip_map_path)))
    track_name = str(metadata.track_name or "").strip()
    if track_name and tracks_dir is not None:
        trk = Path(tracks_dir) / track_name
        candidates.extend([
            trk / "grip_map.csv",
            trk / "track_grip_map.csv",
            trk / "mu_map.csv",
        ])

    out: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        opts = [p] if p.is_absolute() else [Path.cwd() / p, p]
        for cand in opts:
            key = str(cand)
            if key not in seen:
                seen.add(key)
                out.append(cand)
    return out


def _load_map_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if df.empty:
        return None
    cols = {str(c).strip().lower(): str(c) for c in df.columns}
    mu_col = _find_col(cols, ["mu_scale", "mu", "grip_scale", "grip"])
    if mu_col is None:
        return None
    mode_ok = (
        _find_col(cols, ["s", "distance_m", "distance", "dist_m"]) is not None
        or (
            _find_col(cols, ["x", "x_m"]) is not None
            and _find_col(cols, ["y", "y_m"]) is not None
        )
    )
    if not mode_ok:
        return None
    return df


def _project_asset_to_track(
    geometry: TrackGeometry,
    df: pd.DataFrame,
) -> tuple[str, np.ndarray | None]:
    cols = {str(c).strip().lower(): str(c) for c in df.columns}
    mu_col = _find_col(cols, ["mu_scale", "mu", "grip_scale", "grip"])
    if mu_col is None:
        return "none", None
    mu = pd.to_numeric(df[mu_col], errors="coerce").to_numpy(dtype=float)

    s_col = _find_col(cols, ["s", "distance_m", "distance", "dist_m"])
    if s_col is not None:
        s = pd.to_numeric(df[s_col], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(s) & np.isfinite(mu)
        if np.sum(m) >= 3:
            s = s[m]
            mu_v = mu[m]
            order = np.argsort(s)
            s = s[order]
            mu_v = mu_v[order]
            s, keep = np.unique(s, return_index=True)
            mu_v = mu_v[keep]
            if len(s) >= 3 and np.all(np.diff(s) > 0):
                out = np.interp(
                    np.asarray(geometry.distance_m, dtype=float),
                    s,
                    mu_v,
                    left=float(mu_v[0]),
                    right=float(mu_v[-1]),
                )
                return "distance_interp", np.clip(out, 0.55, 1.25)

    x_col = _find_col(cols, ["x", "x_m"])
    y_col = _find_col(cols, ["y", "y_m"])
    if x_col is None or y_col is None:
        return "none", None
    x = pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(df[y_col], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(mu)
    if np.sum(m) < 5:
        return "none", None
    x = x[m]
    y = y[m]
    mu_v = mu[m]
    out = _nearest_xy(
        np.asarray(geometry.x_ref_m, dtype=float),
        np.asarray(geometry.y_ref_m, dtype=float),
        x,
        y,
        mu_v,
    )
    return "xy_nearest", np.clip(out, 0.55, 1.25)


def _nearest_xy(
    x_ref: np.ndarray,
    y_ref: np.ndarray,
    x_map: np.ndarray,
    y_map: np.ndarray,
    v_map: np.ndarray,
) -> np.ndarray:
    n = int(len(x_ref))
    out = np.empty(n, dtype=float)
    if n == 0:
        return out
    # Chunked nearest-neighbor projection to keep memory bounded.
    chunk = 256
    for i0 in range(0, n, chunk):
        i1 = min(i0 + chunk, n)
        dx = x_ref[i0:i1, None] - x_map[None, :]
        dy = y_ref[i0:i1, None] - y_map[None, :]
        d2 = dx * dx + dy * dy
        idx = np.argmin(d2, axis=1)
        out[i0:i1] = v_map[idx]
    return out


def _telemetry_fallback(distance: np.ndarray, lap_df: pd.DataFrame | None) -> np.ndarray | None:
    if lap_df is None or lap_df.empty:
        return None
    if COL_DIST not in lap_df.columns:
        return None
    if COL_ACCEL_LONG not in lap_df.columns and COL_ACCEL_LAT not in lap_df.columns:
        return None

    s = pd.to_numeric(lap_df[COL_DIST], errors="coerce").to_numpy(dtype=float)
    ax = (
        pd.to_numeric(lap_df[COL_ACCEL_LONG], errors="coerce").to_numpy(dtype=float)
        if COL_ACCEL_LONG in lap_df.columns
        else np.zeros_like(s)
    )
    ay = (
        pd.to_numeric(lap_df[COL_ACCEL_LAT], errors="coerce").to_numpy(dtype=float)
        if COL_ACCEL_LAT in lap_df.columns
        else np.zeros_like(s)
    )
    m = np.isfinite(s) & np.isfinite(ax) & np.isfinite(ay)
    if np.sum(m) < 20:
        return None
    s = s[m]
    ax = ax[m]
    ay = ay[m]
    order = np.argsort(s)
    s = s[order]
    ax = ax[order]
    ay = ay[order]

    cg = np.sqrt(np.maximum(ax * ax + ay * ay, 0.0)) / _G
    ref = float(np.nanpercentile(cg, 95.0))
    if not np.isfinite(ref) or ref <= 1e-6:
        ref = 1.0
    util = np.clip(cg / ref, 0.35, 1.35)
    mu_raw = np.clip(0.72 + 0.30 * util, 0.65, 1.12)

    # Robustly collapse duplicates.
    s_u, inv = np.unique(s, return_inverse=True)
    if len(s_u) < 3:
        return None
    mu_u = np.zeros_like(s_u, dtype=float)
    counts = np.zeros_like(s_u, dtype=float)
    for i, idx in enumerate(inv):
        mu_u[idx] += mu_raw[i]
        counts[idx] += 1.0
    mu_u = mu_u / np.maximum(counts, 1.0)

    out = np.interp(
        np.asarray(distance, dtype=float),
        s_u,
        mu_u,
        left=float(mu_u[0]),
        right=float(mu_u[-1]),
    )
    return np.clip(out, 0.65, 1.12)


def _condition_prior_scale(condition_label: str | None) -> float:
    c = str(condition_label or "").strip().lower()
    if "wet" in c:
        return 0.82
    if "damp" in c:
        return 0.90
    if "greasy" in c:
        return 0.88
    if "green" in c:
        return 0.94
    return 1.0


def _smooth_profile(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if len(arr) < 5:
        return arr
    kernel = np.array([1.0, 2.0, 3.0, 2.0, 1.0], dtype=float)
    kernel /= np.sum(kernel)
    pad = 2
    ext = np.pad(arr, (pad, pad), mode="edge")
    sm = np.convolve(ext, kernel, mode="same")[pad:-pad]
    return np.asarray(sm, dtype=float)


def _find_col(idx: dict[str, str], candidates: list[str]) -> str | None:
    for c in candidates:
        col = idx.get(str(c).lower())
        if col is not None:
            return col
    return None


def _meta(
    *,
    enabled: bool,
    source: str,
    map_path: str,
    method: str,
    blend: float,
    values: np.ndarray,
) -> GripMapMeta:
    vals = np.asarray(values, dtype=float)
    if vals.size == 0:
        return GripMapMeta(
            enabled=enabled,
            source=source,
            map_path=map_path,
            method=method,
            blend=blend,
            n_points=0,
        )
    return GripMapMeta(
        enabled=enabled,
        source=source,
        map_path=map_path,
        method=method,
        blend=blend,
        n_points=int(vals.size),
        mu_scale_min=float(np.nanmin(vals)),
        mu_scale_max=float(np.nanmax(vals)),
        mu_scale_mean=float(np.nanmean(vals)),
    )

