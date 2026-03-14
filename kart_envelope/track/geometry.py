"""
geometry.py
-----------
Track geometry model: curvature κ(s), heading, reference XY, and
serialisation to/from JSON.

Wraps ``telemetry_tool.reference_line`` for the heavy lifting.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from kart_envelope.config import KartEnvelopeConfig  # noqa: E402
from kart_envelope.ingest.columns import CANONICAL_TO_RAW  # noqa: E402
from telemetry_tool.reference_line import (  # noqa: E402
    compute_curvature_profile,
    compute_reference_line,
)

logger = logging.getLogger(__name__)


class TrackGeometryError(ValueError):
    """Raised when track geometry cannot be built."""


@dataclass
class TrackGeometry:
    """Immutable representation of a track's curvilinear geometry.

    Supports elevation-aware curvature: when altitude data is available,
    ``curvature_1pm`` contains the **lateral** (plan-view) curvature with
    elevation-induced false curvature removed.  ``vertical_curvature_1pm``
    holds the vertical curvature (crests/compressions) separately.

    ``signed_curvature_1pm`` preserves the turn direction (positive = left,
    negative = right) for corner classification.
    """

    distance_m: np.ndarray       # s grid [m]
    curvature_1pm: np.ndarray    # |κ_lateral|(s) [1/m], unsigned
    heading_rad: np.ndarray      # θ(s) [rad]
    x_ref_m: np.ndarray          # X(s) [m]
    y_ref_m: np.ndarray          # Y(s) [m]
    lap_length_m: float
    track_id: str = ""

    # Elevation-aware fields (optional, zero-length if unavailable)
    signed_curvature_1pm: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    elevation_m: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    vertical_curvature_1pm: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    grade_pct: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))

    @property
    def has_elevation(self) -> bool:
        """Whether elevation data is available."""
        return len(self.elevation_m) == len(self.distance_m) and len(self.elevation_m) > 0

    @property
    def has_signed_curvature(self) -> bool:
        """Whether signed curvature is available."""
        return len(self.signed_curvature_1pm) == len(self.distance_m) and len(self.signed_curvature_1pm) > 0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "version": "1.1",
            "track_id": self.track_id,
            "lap_length_m": round(self.lap_length_m, 4),
            "distance_m": np.round(self.distance_m, 4).tolist(),
            "curvature_1pm": np.round(self.curvature_1pm, 6).tolist(),
            "heading_rad": np.round(self.heading_rad, 6).tolist(),
            "x_ref_m": np.round(self.x_ref_m, 4).tolist(),
            "y_ref_m": np.round(self.y_ref_m, 4).tolist(),
        }
        if self.has_signed_curvature:
            d["signed_curvature_1pm"] = np.round(self.signed_curvature_1pm, 6).tolist()
        if self.has_elevation:
            d["elevation_m"] = np.round(self.elevation_m, 2).tolist()
            d["vertical_curvature_1pm"] = np.round(self.vertical_curvature_1pm, 6).tolist()
            d["grade_pct"] = np.round(self.grade_pct, 3).tolist()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrackGeometry:
        n = len(d["distance_m"])
        return cls(
            distance_m=np.asarray(d["distance_m"], dtype=float),
            curvature_1pm=np.asarray(d["curvature_1pm"], dtype=float),
            heading_rad=np.asarray(d["heading_rad"], dtype=float),
            x_ref_m=np.asarray(d["x_ref_m"], dtype=float),
            y_ref_m=np.asarray(d["y_ref_m"], dtype=float),
            lap_length_m=float(d["lap_length_m"]),
            track_id=d.get("track_id", ""),
            signed_curvature_1pm=np.asarray(d.get("signed_curvature_1pm", []), dtype=float),
            elevation_m=np.asarray(d.get("elevation_m", []), dtype=float),
            vertical_curvature_1pm=np.asarray(d.get("vertical_curvature_1pm", []), dtype=float),
            grade_pct=np.asarray(d.get("grade_pct", []), dtype=float),
        )

    def save(self, path: Path) -> None:
        """Write geometry to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        logger.info("Saved track geometry to %s", path)

    @classmethod
    def load(cls, path: Path) -> TrackGeometry:
        """Load geometry from JSON."""
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def build_track_geometry(
    resampled_laps: dict[int, pd.DataFrame],
    config: KartEnvelopeConfig,
    track_id: str = "",
) -> TrackGeometry:
    """Build track geometry from resampled laps.

    Wraps ``reference_line.compute_reference_line`` and
    ``reference_line.compute_curvature_profile``.

    Parameters
    ----------
    resampled_laps : dict[int, pd.DataFrame]
        Output of ``resampler.resample_laps_by_ds``.
    config : KartEnvelopeConfig
    track_id : str
        Identifier for this track.

    Returns
    -------
    TrackGeometry

    Raises
    ------
    TrackGeometryError
        If geometry cannot be computed (too few laps, missing XY/GPS data).
    """
    if not resampled_laps:
        raise TrackGeometryError("No resampled laps provided.")

    # Bridge canonical → raw column names for telemetry_tool functions
    raw_laps = {k: _to_raw_names(v) for k, v in resampled_laps.items()}

    # compute_reference_line expects a dict of DataFrames with raw names
    try:
        ref_line = compute_reference_line(
            raw_laps,
            method=config.reference_line_method,
        )
    except Exception as exc:
        raise TrackGeometryError(f"Reference line computation failed: {exc}") from exc

    try:
        curv_df = compute_curvature_profile(
            ref_line,
            smooth_window=config.curvature_smooth_hw,
        )
    except Exception as exc:
        raise TrackGeometryError(f"Curvature computation failed: {exc}") from exc

    # Extract arrays from the curvature profile DataFrame
    dist = _get_col(curv_df, ["distance_m", "Distance (m)"])
    kappa = _get_col(curv_df, ["curvature_1pm", "curvature"])
    heading = _get_col(curv_df, ["heading_rad", "heading"])
    x = _get_col(curv_df, ["x_ref_m", "x_m", "X (m)"])
    y = _get_col(curv_df, ["y_ref_m", "y_m", "Y (m)"])

    if dist is None or kappa is None:
        raise TrackGeometryError("Curvature profile missing distance/curvature columns.")

    # Clip curvature to physical bounds (min radius ~1 m)
    kappa = np.clip(np.abs(kappa), 0.0, 1.0)

    lap_length = float(dist[-1] - dist[0]) if len(dist) > 1 else 0.0

    # Fallback for missing columns
    if heading is None:
        heading = np.zeros_like(dist)
    if x is None:
        x = np.zeros_like(dist)
    if y is None:
        y = np.zeros_like(dist)

    # Signed curvature (for corner direction detection)
    signed_kappa = _get_col(curv_df, ["signed_curvature_1pm", "signed_curvature"])
    if signed_kappa is None and heading is not None and len(heading) > 2:
        # Derive signed curvature from heading: κ = dθ/ds
        ds = np.diff(dist)
        dtheta = np.diff(heading)
        # Unwrap heading jumps
        dtheta = np.where(dtheta > np.pi, dtheta - 2 * np.pi, dtheta)
        dtheta = np.where(dtheta < -np.pi, dtheta + 2 * np.pi, dtheta)
        signed_kappa_raw = np.zeros(len(dist))
        signed_kappa_raw[:-1] = np.where(ds > 0.01, dtheta / ds, 0.0)
        signed_kappa_raw[-1] = signed_kappa_raw[-2]
        signed_kappa = _smooth_1d(signed_kappa_raw, hw=config.curvature_smooth_hw)

    # Elevation data (if available)
    alt = _get_col(curv_df, ["elevation_m", "altitude_m", "Altitude (m)", "z_m"])
    if alt is None:
        # Try to extract from resampled laps
        alt = _extract_altitude_from_laps(resampled_laps, dist)

    elevation_m = np.array([], dtype=float)
    vertical_kappa = np.array([], dtype=float)
    grade = np.array([], dtype=float)

    if alt is not None and len(alt) == len(dist) and np.isfinite(alt).sum() > len(alt) * 0.5:
        # Smooth altitude to reduce GPS noise
        alt_smooth = _smooth_1d(alt, hw=max(config.curvature_smooth_hw, 3))
        elevation_m = alt_smooth

        # Compute grade (slope %)
        grade = _compute_grade(dist, alt_smooth)

        # Compute vertical curvature (d²z/ds²)
        vertical_kappa = _compute_vertical_curvature(dist, alt_smooth, config.curvature_smooth_hw)

        # Correct lateral curvature by removing elevation-induced false curvature
        kappa = _correct_lateral_curvature(kappa, dist, alt_smooth)

        logger.info(
            "Elevation data: range %.1f m, max grade %.1f%%, vertical κ range [%.5f, %.5f] 1/m.",
            float(np.ptp(alt_smooth)), float(np.max(np.abs(grade))),
            float(np.min(vertical_kappa)), float(np.max(vertical_kappa)),
        )

    geom = TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=lap_length,
        track_id=track_id,
        signed_curvature_1pm=signed_kappa if signed_kappa is not None else np.array([], dtype=float),
        elevation_m=elevation_m,
        vertical_curvature_1pm=vertical_kappa,
        grade_pct=grade,
    )
    logger.info(
        "Track geometry built: %.0f m, %d points, mean κ=%.5f 1/m, "
        "elevation=%s, signed_curvature=%s.",
        lap_length, len(dist), float(np.mean(kappa)),
        "yes" if geom.has_elevation else "no",
        "yes" if geom.has_signed_curvature else "no",
    )
    return geom


def _get_col(df: pd.DataFrame, names: list[str]) -> np.ndarray | None:
    """Return the first matching column as a numpy array, or None."""
    for name in names:
        if name in df.columns:
            return df[name].values.astype(float)
    return None


def _to_raw_names(df: pd.DataFrame) -> pd.DataFrame:
    """Rename canonical columns back to RaceChrono raw names for telemetry_tool."""
    rename = {canon: raw for canon, raw in CANONICAL_TO_RAW.items()
              if canon in df.columns}
    return df.rename(columns=rename) if rename else df


# ── Elevation-aware curvature helpers ───────────────────────────────────


def _smooth_1d(arr: np.ndarray, hw: int) -> np.ndarray:
    """Gaussian smooth a 1D array with half-width hw."""
    if hw < 1 or len(arr) < 3:
        return arr.copy()
    n = 2 * hw + 1
    x = np.arange(-hw, hw + 1, dtype=float)
    kernel = np.exp(-0.5 * (x / max(hw / 2.0, 1.0)) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(arr, hw, mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: len(arr)]


def _compute_grade(dist: np.ndarray, alt: np.ndarray) -> np.ndarray:
    """Compute road grade (slope) in percent from distance and altitude."""
    ds = np.diff(dist)
    dz = np.diff(alt)
    grade = np.zeros(len(dist))
    grade[:-1] = np.where(ds > 0.1, 100.0 * dz / ds, 0.0)
    grade[-1] = grade[-2] if len(grade) > 1 else 0.0
    return np.clip(grade, -30.0, 30.0)


def _compute_vertical_curvature(
    dist: np.ndarray,
    alt: np.ndarray,
    smooth_hw: int,
) -> np.ndarray:
    """Compute vertical curvature κ_v = d²z/ds².

    Positive = crest (convex up), negative = compression (concave up).
    """
    if len(dist) < 5:
        return np.zeros(len(dist))

    ds = np.diff(dist)
    dz = np.diff(alt)

    # First derivative: dz/ds (grade as ratio, not %)
    dz_ds = np.zeros(len(dist))
    dz_ds[:-1] = np.where(ds > 0.01, dz / ds, 0.0)
    dz_ds[-1] = dz_ds[-2]

    # Second derivative: d²z/ds²
    d2z = np.diff(dz_ds)
    kv = np.zeros(len(dist))
    kv[:-1] = np.where(ds > 0.01, d2z / ds, 0.0)
    kv[-1] = kv[-2] if len(kv) > 1 else 0.0

    # Smooth to reduce noise
    kv = _smooth_1d(kv, max(smooth_hw, 2))
    return np.clip(kv, -0.1, 0.1)


def _correct_lateral_curvature(
    kappa_2d: np.ndarray,
    dist: np.ndarray,
    alt: np.ndarray,
) -> np.ndarray:
    """Remove elevation-induced false curvature from 2D curvature.

    On hills, the GPS path projects to 2D with apparent curvature from
    elevation changes.  The true lateral curvature is:

        κ_lateral = κ_2D / cos(grade_angle)

    where grade_angle = atan(dz/ds).  On steep hills (>10% grade),
    this correction is significant.  On flat tracks, cos(θ) ≈ 1.

    Additionally, crests/compressions create apparent lateral curvature
    spikes when the path curves vertically.  We subtract the vertical
    curvature contribution scaled by the grade.
    """
    if len(alt) != len(dist) or len(alt) < 3:
        return kappa_2d

    ds = np.diff(dist)
    dz = np.diff(alt)

    # Grade angle at each point
    grade_ratio = np.zeros(len(dist))
    grade_ratio[:-1] = np.where(ds > 0.01, dz / ds, 0.0)
    grade_ratio[-1] = grade_ratio[-2]
    cos_grade = np.cos(np.arctan(grade_ratio))

    # Correct: divide by cos(grade) to get true plan-view curvature
    kappa_corrected = kappa_2d / np.maximum(cos_grade, 0.95)

    # Clip to physical bounds
    return np.clip(kappa_corrected, 0.0, 1.0)


def _extract_altitude_from_laps(
    resampled_laps: dict[int, pd.DataFrame],
    dist_grid: np.ndarray,
) -> np.ndarray | None:
    """Try to extract altitude from lap data and interpolate to distance grid."""
    alt_col_names = ["altitude_m", "Altitude (m)", "elevation_m", "alt_m"]

    for lap_df in resampled_laps.values():
        for col_name in alt_col_names:
            if col_name in lap_df.columns:
                alt = pd.to_numeric(lap_df[col_name], errors="coerce").to_numpy(dtype=float)
                if np.isfinite(alt).sum() > len(alt) * 0.5:
                    # Get distance column
                    dist_col = None
                    for dc in ["distance_m", "Distance (m)"]:
                        if dc in lap_df.columns:
                            dist_col = pd.to_numeric(lap_df[dc], errors="coerce").to_numpy(dtype=float)
                            break
                    if dist_col is not None:
                        valid = np.isfinite(dist_col) & np.isfinite(alt)
                        if valid.sum() >= 10:
                            return np.interp(
                                dist_grid,
                                dist_col[valid],
                                alt[valid],
                                left=float(alt[valid][0]),
                                right=float(alt[valid][-1]),
                            )
        break  # Only try the first lap

    return None
