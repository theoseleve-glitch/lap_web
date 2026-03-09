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
    """Immutable representation of a track's curvilinear geometry."""

    distance_m: np.ndarray       # s grid [m]
    curvature_1pm: np.ndarray    # κ(s) [1/m]
    heading_rad: np.ndarray      # θ(s) [rad]
    x_ref_m: np.ndarray          # X(s) [m]
    y_ref_m: np.ndarray          # Y(s) [m]
    lap_length_m: float
    track_id: str = ""

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "1.0",
            "track_id": self.track_id,
            "lap_length_m": round(self.lap_length_m, 4),
            "distance_m": np.round(self.distance_m, 4).tolist(),
            "curvature_1pm": np.round(self.curvature_1pm, 6).tolist(),
            "heading_rad": np.round(self.heading_rad, 6).tolist(),
            "x_ref_m": np.round(self.x_ref_m, 4).tolist(),
            "y_ref_m": np.round(self.y_ref_m, 4).tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrackGeometry:
        return cls(
            distance_m=np.asarray(d["distance_m"], dtype=float),
            curvature_1pm=np.asarray(d["curvature_1pm"], dtype=float),
            heading_rad=np.asarray(d["heading_rad"], dtype=float),
            x_ref_m=np.asarray(d["x_ref_m"], dtype=float),
            y_ref_m=np.asarray(d["y_ref_m"], dtype=float),
            lap_length_m=float(d["lap_length_m"]),
            track_id=d.get("track_id", ""),
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

    geom = TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=lap_length,
        track_id=track_id,
    )
    logger.info(
        "Track geometry built: %.0f m, %d points, mean κ=%.5f 1/m.",
        lap_length, len(dist), float(np.mean(kappa)),
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
