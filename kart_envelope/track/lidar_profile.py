"""
lidar_profile.py
----------------
Track surface profile resolver:
- strict CSV profile ingestion for LiDAR-like assets
- telemetry fallback using altitude / bank channels
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.ingest.columns import COL_ALTITUDE, COL_BANK_ANGLE_DEG, COL_DIST
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.track.geometry import TrackGeometry


@dataclass
class TrackSurfaceMeta:
    """Track surface source and quality metadata."""

    enabled: bool = False
    source: str = "disabled"  # exact_asset | fallback_telemetry | disabled
    profile_path: str = ""
    n_points: int = 0
    elevation_min_m: float = 0.0
    elevation_max_m: float = 0.0
    bank_min_deg: float = 0.0
    bank_max_deg: float = 0.0
    grade_abs_mean_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "source": self.source,
            "profile_path": self.profile_path,
            "n_points": int(self.n_points),
            "elevation_min_m": round(float(self.elevation_min_m), 4),
            "elevation_max_m": round(float(self.elevation_max_m), 4),
            "bank_min_deg": round(float(self.bank_min_deg), 4),
            "bank_max_deg": round(float(self.bank_max_deg), 4),
            "grade_abs_mean_pct": round(float(self.grade_abs_mean_pct), 4),
        }


def resolve_track_surface_profile(
    geometry: TrackGeometry,
    metadata: SessionMetadata,
    config: KartEnvelopeConfig,
    *,
    fallback_df: pd.DataFrame | None = None,
    tracks_dir: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, TrackSurfaceMeta]:
    """
    Resolve elevation/bank profile for the track distance grid.

    Returns
    -------
    elevation_m : np.ndarray
    bank_deg : np.ndarray
    meta : TrackSurfaceMeta
    """
    distance = np.asarray(geometry.distance_m, dtype=float)
    if distance.size == 0:
        empty = np.array([], dtype=float)
        return empty, empty, TrackSurfaceMeta(enabled=False, source="disabled")

    if not bool(config.track_enable_lidar_profile):
        elevation = np.zeros_like(distance)
        bank = np.zeros_like(distance)
        return elevation, bank, _build_meta(
            enabled=False,
            source="disabled",
            profile_path="",
            distance=distance,
            elevation=elevation,
            bank=bank,
        )

    for cand in _candidate_profile_paths(metadata=metadata, tracks_dir=tracks_dir):
        profile = _load_profile_csv(cand)
        if profile is None:
            continue
        s_prof, z_prof, b_prof = profile
        elevation = np.interp(distance, s_prof, z_prof, left=float(z_prof[0]), right=float(z_prof[-1]))
        bank = np.interp(distance, s_prof, b_prof, left=float(b_prof[0]), right=float(b_prof[-1]))
        return elevation, bank, _build_meta(
            enabled=True,
            source="exact_asset",
            profile_path=str(cand),
            distance=distance,
            elevation=elevation,
            bank=bank,
        )

    if bool(config.track_lidar_fallback_to_telemetry):
        elevation, bank = _telemetry_fallback(distance, fallback_df)
        return elevation, bank, _build_meta(
            enabled=True,
            source="fallback_telemetry",
            profile_path="",
            distance=distance,
            elevation=elevation,
            bank=bank,
        )

    elevation = np.zeros_like(distance)
    bank = np.zeros_like(distance)
    return elevation, bank, _build_meta(
        enabled=True,
        source="fallback_telemetry",
        profile_path="",
        distance=distance,
        elevation=elevation,
        bank=bank,
    )


def _candidate_profile_paths(
    *,
    metadata: SessionMetadata,
    tracks_dir: Path | None,
) -> list[Path]:
    out: list[Path] = []
    if metadata.track_lidar_profile_path:
        out.append(Path(str(metadata.track_lidar_profile_path)))
    track_name = str(metadata.track_name or "").strip()
    if tracks_dir is not None and track_name:
        out.append(Path(tracks_dir) / track_name / "lidar_profile.csv")
        out.append(Path(tracks_dir) / track_name / "surface_profile.csv")
    # absolute + cwd-relative resolution.
    resolved: list[Path] = []
    seen: set[str] = set()
    for p in out:
        cands = [p] if p.is_absolute() else [Path.cwd() / p, p]
        for c in cands:
            k = str(c)
            if k not in seen:
                seen.add(k)
                resolved.append(c)
    return resolved


def _load_profile_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if df.empty:
        return None

    s_col = _find_col(df, ["s", "distance_m", "distance", "dist_m"])
    z_col = _find_col(df, ["elevation", "elevation_m", "z_m", "altitude_m"])
    b_col = _find_col(df, ["bank", "bank_deg", "bank_angle_deg"])
    if s_col is None or z_col is None or b_col is None:
        return None

    s = pd.to_numeric(df[s_col], errors="coerce").to_numpy(dtype=float)
    z = pd.to_numeric(df[z_col], errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(df[b_col], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(s) & np.isfinite(z) & np.isfinite(b)
    if np.sum(m) < 3:
        return None
    s = s[m]
    z = z[m]
    b = b[m]
    order = np.argsort(s)
    s = s[order]
    z = z[order]
    b = b[order]
    s, keep = np.unique(s, return_index=True)
    z = z[keep]
    b = b[keep]
    if s.size < 3:
        return None
    if np.any(np.diff(s) <= 0):
        return None
    return s, z, b


def _find_col(df: pd.DataFrame, names: list[str]) -> str | None:
    idx = {str(c).strip().lower(): str(c) for c in df.columns}
    for name in names:
        col = idx.get(name.lower())
        if col is not None:
            return col
    return None


def _telemetry_fallback(distance: np.ndarray, lap_df: pd.DataFrame | None) -> tuple[np.ndarray, np.ndarray]:
    if lap_df is None or lap_df.empty or COL_DIST not in lap_df.columns:
        return np.zeros_like(distance), np.zeros_like(distance)

    s = pd.to_numeric(lap_df[COL_DIST], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(s)
    if np.sum(m) < 3:
        return np.zeros_like(distance), np.zeros_like(distance)
    s = s[m]
    order = np.argsort(s)
    s = s[order]
    s, keep = np.unique(s, return_index=True)
    if s.size < 3:
        return np.zeros_like(distance), np.zeros_like(distance)

    if COL_ALTITUDE in lap_df.columns:
        z_raw = pd.to_numeric(lap_df[COL_ALTITUDE], errors="coerce").to_numpy(dtype=float)[m][order][keep]
        z = np.interp(distance, s, np.nan_to_num(z_raw, nan=float(np.nanmedian(z_raw))), left=float(z_raw[0]), right=float(z_raw[-1]))
    else:
        z = np.zeros_like(distance)

    if COL_BANK_ANGLE_DEG in lap_df.columns:
        b_raw = pd.to_numeric(lap_df[COL_BANK_ANGLE_DEG], errors="coerce").to_numpy(dtype=float)[m][order][keep]
        b_raw = np.nan_to_num(b_raw, nan=float(np.nanmedian(b_raw)))
        b = np.interp(distance, s, b_raw, left=float(b_raw[0]), right=float(b_raw[-1]))
    else:
        b = np.zeros_like(distance)
    return z.astype(float), b.astype(float)


def _build_meta(
    *,
    enabled: bool,
    source: str,
    profile_path: str,
    distance: np.ndarray,
    elevation: np.ndarray,
    bank: np.ndarray,
) -> TrackSurfaceMeta:
    if distance.size < 2:
        grade_abs = 0.0
    else:
        ds = np.maximum(np.diff(distance), 1e-6)
        grade = 100.0 * np.diff(elevation) / ds
        grade_abs = float(np.nanmean(np.abs(grade))) if grade.size else 0.0
    return TrackSurfaceMeta(
        enabled=enabled,
        source=source,
        profile_path=profile_path,
        n_points=int(distance.size),
        elevation_min_m=float(np.nanmin(elevation)) if elevation.size else 0.0,
        elevation_max_m=float(np.nanmax(elevation)) if elevation.size else 0.0,
        bank_min_deg=float(np.nanmin(bank)) if bank.size else 0.0,
        bank_max_deg=float(np.nanmax(bank)) if bank.size else 0.0,
        grade_abs_mean_pct=grade_abs,
    )
