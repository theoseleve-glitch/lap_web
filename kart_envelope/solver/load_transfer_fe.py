"""
load_transfer_fe.py
-------------------
FE load-transfer map interface with telemetry-driven fallback surrogate.
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
class LoadTransferMeta:
    """Metadata for FE/surrogate load-transfer usage."""

    enabled: bool = False
    source: str = "disabled"  # exact_asset | fallback_telemetry | disabled
    map_path: str = ""
    method: str = "none"  # fe_nearest | surrogate_latg | surrogate_const
    n_points: int = 0
    lateral_scale_min: float = 1.0
    lateral_scale_max: float = 1.0
    drive_scale_mean: float = 1.0
    brake_scale_mean: float = 1.0
    three_wheel_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "source": self.source,
            "map_path": self.map_path,
            "method": self.method,
            "n_points": int(self.n_points),
            "lateral_scale_min": round(float(self.lateral_scale_min), 4),
            "lateral_scale_max": round(float(self.lateral_scale_max), 4),
            "drive_scale_mean": round(float(self.drive_scale_mean), 4),
            "brake_scale_mean": round(float(self.brake_scale_mean), 4),
            "three_wheel_ratio": round(float(self.three_wheel_ratio), 4),
        }


def resolve_load_transfer_scale_profile(
    geometry: TrackGeometry,
    metadata: SessionMetadata,
    config: KartEnvelopeConfig,
    *,
    fallback_df: pd.DataFrame | None = None,
    tracks_dir: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, LoadTransferMeta]:
    """
    Resolve load-transfer scaling profiles for lateral/drive/brake capability.
    """
    n = int(len(geometry.distance_m))
    if n <= 0:
        empty = np.array([], dtype=float)
        return empty, empty, empty, LoadTransferMeta(enabled=False, source="disabled")

    ones = np.ones(n, dtype=float)
    if not bool(config.load_transfer_enable_fe_map):
        return ones, ones, ones, _meta(
            enabled=False,
            source="disabled",
            map_path="",
            method="none",
            lat=ones,
            drv=ones,
            brk=ones,
        )

    telem = _telemetry_arrays(geometry.distance_m, fallback_df)
    for cand in _candidate_paths(metadata=metadata, tracks_dir=tracks_dir):
        loaded = _load_fe_map(cand)
        if loaded is None:
            continue
        lat, drv, brk = _project_fe_map(loaded, telem, n)
        if lat is None or drv is None or brk is None:
            continue
        lat = _smooth(lat)
        drv = _smooth(drv)
        brk = _smooth(brk)
        return lat, drv, brk, _meta(
            enabled=True,
            source="exact_asset",
            map_path=str(cand),
            method="fe_nearest",
            lat=lat,
            drv=drv,
            brk=brk,
            three_wheel_ratio=_estimate_three_wheel_ratio(telem),
        )

    if bool(config.load_transfer_fallback_surrogate):
        lat, drv, brk, method = _fallback_surrogate(geometry.distance_m, telem)
        return lat, drv, brk, _meta(
            enabled=True,
            source="fallback_telemetry",
            map_path="",
            method=method,
            lat=lat,
            drv=drv,
            brk=brk,
            three_wheel_ratio=_estimate_three_wheel_ratio(telem),
        )

    return ones, ones, ones, _meta(
        enabled=True,
        source="fallback_telemetry",
        map_path="",
        method="surrogate_const",
        lat=ones,
        drv=ones,
        brk=ones,
    )


def _candidate_paths(*, metadata: SessionMetadata, tracks_dir: Path | None) -> list[Path]:
    cands: list[Path] = []
    if metadata.load_transfer_fe_map_path:
        cands.append(Path(str(metadata.load_transfer_fe_map_path)))
    track_name = str(metadata.track_name or "").strip()
    if track_name and tracks_dir is not None:
        trk = Path(tracks_dir) / track_name
        cands.extend([
            trk / "load_transfer_fe.csv",
            trk / "load_transfer_map.csv",
            trk / "fe_load_map.csv",
        ])
    out: list[Path] = []
    seen: set[str] = set()
    for p in cands:
        opts = [p] if p.is_absolute() else [Path.cwd() / p, p]
        for cand in opts:
            key = str(cand)
            if key not in seen:
                seen.add(key)
                out.append(cand)
    return out


def _load_fe_map(path: Path) -> pd.DataFrame | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if df.empty:
        return None
    cols = {str(c).strip().lower(): str(c) for c in df.columns}
    need = ["ax_g", "ay_g"]
    for n in need:
        if n not in cols:
            return None
    # Either explicit scales or wheel load ratio fields.
    explicit = (
        any(k in cols for k in ("lateral_scale", "lat_scale", "mu_scale"))
        and any(k in cols for k in ("drive_scale", "traction_scale", "ax_drive_scale"))
        and any(k in cols for k in ("brake_scale", "ax_brake_scale"))
    )
    wheel_ratio = all(k in cols for k in ("fl_ratio", "fr_ratio", "rl_ratio", "rr_ratio"))
    if not explicit and not wheel_ratio:
        return None
    return df


def _project_fe_map(
    df: pd.DataFrame,
    telem: dict[str, np.ndarray] | None,
    n: int,
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    if telem is None:
        return None, None, None
    ax = telem["ax_g"]
    ay = telem["ay_g"]
    if len(ax) != len(ay) or len(ax) < 3:
        return None, None, None

    cols = {str(c).strip().lower(): str(c) for c in df.columns}
    axm = pd.to_numeric(df[cols["ax_g"]], errors="coerce").to_numpy(dtype=float)
    aym = pd.to_numeric(df[cols["ay_g"]], errors="coerce").to_numpy(dtype=float)
    azm = (
        pd.to_numeric(df[cols["az_g"]], errors="coerce").to_numpy(dtype=float)
        if "az_g" in cols
        else np.ones_like(axm)
    )

    latm = _col_or_none(df, cols, ["lateral_scale", "lat_scale", "mu_scale"])
    drvm = _col_or_none(df, cols, ["drive_scale", "traction_scale", "ax_drive_scale"])
    brkm = _col_or_none(df, cols, ["brake_scale", "ax_brake_scale"])

    if latm is None or drvm is None or brkm is None:
        # Derive from wheel load distribution proxy.
        fl = _col_or_none(df, cols, ["fl_ratio"])
        fr = _col_or_none(df, cols, ["fr_ratio"])
        rl = _col_or_none(df, cols, ["rl_ratio"])
        rr = _col_or_none(df, cols, ["rr_ratio"])
        if fl is None or fr is None or rl is None or rr is None:
            return None, None, None
        front = np.clip(fl + fr, 0.1, 2.0)
        rear = np.clip(rl + rr, 0.1, 2.0)
        left = np.clip(fl + rl, 0.1, 2.0)
        right = np.clip(fr + rr, 0.1, 2.0)
        lr_imb = np.abs(left - right)
        fr_bias = front / np.maximum(front + rear, 1e-6)
        latm = np.clip(1.0 - 0.12 * lr_imb, 0.85, 1.04)
        drvm = np.clip(0.92 + 0.16 * (1.0 - fr_bias), 0.85, 1.08)
        brkm = np.clip(0.90 + 0.16 * fr_bias, 0.85, 1.10)

    m = (
        np.isfinite(axm)
        & np.isfinite(aym)
        & np.isfinite(azm)
        & np.isfinite(latm)
        & np.isfinite(drvm)
        & np.isfinite(brkm)
    )
    if np.sum(m) < 8:
        return None, None, None

    axm = axm[m]
    aym = aym[m]
    latm = np.clip(latm[m], 0.75, 1.15)
    drvm = np.clip(drvm[m], 0.75, 1.20)
    brkm = np.clip(brkm[m], 0.75, 1.20)

    idx = _nearest2d(ax, ay, axm, aym)
    lat_t = latm[idx]
    drv_t = drvm[idx]
    brk_t = brkm[idx]

    s_t = telem["s"]
    s_u, lat_u = _collapse_unique(s_t, lat_t)
    _, drv_u = _collapse_unique(s_t, drv_t)
    _, brk_u = _collapse_unique(s_t, brk_t)
    if len(s_u) < 3:
        return None, None, None
    s_geom = np.linspace(float(s_u[0]), float(s_u[-1]), n)
    lat = np.interp(s_geom, s_u, lat_u, left=float(lat_u[0]), right=float(lat_u[-1]))
    drv = np.interp(s_geom, s_u, drv_u, left=float(drv_u[0]), right=float(drv_u[-1]))
    brk = np.interp(s_geom, s_u, brk_u, left=float(brk_u[0]), right=float(brk_u[-1]))
    return lat, drv, brk


def _fallback_surrogate(
    distance: np.ndarray,
    telem: dict[str, np.ndarray] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    n = int(len(distance))
    ones = np.ones(n, dtype=float)
    if telem is None or len(telem.get("s", [])) < 3:
        return ones, ones, ones, "surrogate_const"

    s = telem["s"]
    ay_g = np.abs(telem["ay_g"])
    ax_g = telem["ax_g"]
    lat_raw = np.clip(1.0 - 0.06 * np.maximum(ay_g - 0.95, 0.0), 0.88, 1.03)
    drv_raw = np.clip(1.0 - 0.05 * np.maximum(ay_g - 1.00, 0.0) + 0.03 * np.maximum(-ax_g, 0.0), 0.88, 1.05)
    brk_raw = np.clip(1.0 - 0.03 * np.maximum(ay_g - 1.05, 0.0) + 0.04 * np.maximum(-ax_g, 0.0), 0.88, 1.08)
    s_u, lat_u = _collapse_unique(s, lat_raw)
    _, drv_u = _collapse_unique(s, drv_raw)
    _, brk_u = _collapse_unique(s, brk_raw)
    if len(s_u) < 3:
        return ones, ones, ones, "surrogate_const"
    lat = np.interp(distance, s_u, lat_u, left=float(lat_u[0]), right=float(lat_u[-1]))
    drv = np.interp(distance, s_u, drv_u, left=float(drv_u[0]), right=float(drv_u[-1]))
    brk = np.interp(distance, s_u, brk_u, left=float(brk_u[0]), right=float(brk_u[-1]))
    return _smooth(lat), _smooth(drv), _smooth(brk), "surrogate_latg"


def _telemetry_arrays(
    distance_grid: np.ndarray,
    lap_df: pd.DataFrame | None,
) -> dict[str, np.ndarray] | None:
    if lap_df is None or lap_df.empty:
        return None
    if COL_DIST not in lap_df.columns:
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
    if np.sum(m) < 10:
        return None
    s = s[m]
    ax = ax[m]
    ay = ay[m]
    order = np.argsort(s)
    s = s[order]
    ax = ax[order]
    ay = ay[order]

    # Reproject to analysis distance grid to keep profile lengths consistent.
    if len(np.unique(s)) < 3:
        return None
    ax_i = np.interp(distance_grid, s, ax, left=float(ax[0]), right=float(ax[-1]))
    ay_i = np.interp(distance_grid, s, ay, left=float(ay[0]), right=float(ay[-1]))
    return {
        "s": np.asarray(distance_grid, dtype=float),
        "ax_g": np.asarray(ax_i, dtype=float) / _G,
        "ay_g": np.asarray(ay_i, dtype=float) / _G,
    }


def _nearest2d(ax: np.ndarray, ay: np.ndarray, axm: np.ndarray, aym: np.ndarray) -> np.ndarray:
    n = len(ax)
    out = np.empty(n, dtype=int)
    chunk = 256
    for i0 in range(0, n, chunk):
        i1 = min(i0 + chunk, n)
        dx = ax[i0:i1, None] - axm[None, :]
        dy = ay[i0:i1, None] - aym[None, :]
        d2 = dx * dx + dy * dy
        out[i0:i1] = np.argmin(d2, axis=1)
    return out


def _collapse_unique(s: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    su, inv = np.unique(np.asarray(s, dtype=float), return_inverse=True)
    vu = np.zeros_like(su, dtype=float)
    cnt = np.zeros_like(su, dtype=float)
    for i, idx in enumerate(inv):
        vu[idx] += float(v[i])
        cnt[idx] += 1.0
    vu = vu / np.maximum(cnt, 1.0)
    return su, vu


def _col_or_none(df: pd.DataFrame, idx: dict[str, str], names: list[str]) -> np.ndarray | None:
    for n in names:
        col = idx.get(n)
        if col is not None:
            return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
    return None


def _smooth(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    if len(arr) < 5:
        return arr
    k = np.array([1.0, 2.0, 3.0, 2.0, 1.0], dtype=float)
    k /= np.sum(k)
    ext = np.pad(arr, (2, 2), mode="edge")
    out = np.convolve(ext, k, mode="same")[2:-2]
    return np.asarray(out, dtype=float)


def _estimate_three_wheel_ratio(telem: dict[str, np.ndarray] | None) -> float:
    if telem is None:
        return 0.0
    ay = np.abs(np.asarray(telem.get("ay_g", []), dtype=float))
    if ay.size == 0:
        return 0.0
    return float(np.mean(ay >= 1.20))


def _meta(
    *,
    enabled: bool,
    source: str,
    map_path: str,
    method: str,
    lat: np.ndarray,
    drv: np.ndarray,
    brk: np.ndarray,
    three_wheel_ratio: float = 0.0,
) -> LoadTransferMeta:
    lat = np.asarray(lat, dtype=float)
    drv = np.asarray(drv, dtype=float)
    brk = np.asarray(brk, dtype=float)
    if lat.size == 0:
        return LoadTransferMeta(
            enabled=enabled,
            source=source,
            map_path=map_path,
            method=method,
            n_points=0,
        )
    return LoadTransferMeta(
        enabled=enabled,
        source=source,
        map_path=map_path,
        method=method,
        n_points=int(lat.size),
        lateral_scale_min=float(np.nanmin(lat)),
        lateral_scale_max=float(np.nanmax(lat)),
        drive_scale_mean=float(np.nanmean(drv)) if drv.size else 1.0,
        brake_scale_mean=float(np.nanmean(brk)) if brk.size else 1.0,
        three_wheel_ratio=float(np.clip(three_wheel_ratio, 0.0, 1.0)),
    )

