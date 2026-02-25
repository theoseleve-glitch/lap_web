"""
capability.py
-------------
``CapabilityEnvelope`` — the per-(track, kart) performance envelope learned
from telemetry via quantile extraction with smoothing and physical
constraints.

Satisfies the ``FrictionLike`` protocol from
``telemetry_tool.lap_simulation`` so it can be used interchangeably with
``FrictionCircle``.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig, default_config
from kart_envelope.envelope.combined_slip import fit_p_norm
from kart_envelope.ingest.columns import COL_ACCEL_LAT, COL_ACCEL_LONG, COL_SPEED

logger = logging.getLogger(__name__)

_G: float = 9.80665


class EnvelopeError(ValueError):
    """Raised when envelope training fails."""


# ---------------------------------------------------------------------------
# CapabilityEnvelope dataclass
# ---------------------------------------------------------------------------

@dataclass
class CapabilityEnvelope:
    """Speed-dependent grip/power/brake envelope with combined-slip model.

    Provides the ``FrictionLike`` protocol methods so it can be fed directly
    to ``lap_simulation.simulate_theoretical_lap`` or our own solver.

    Attributes
    ----------
    v_grid : np.ndarray
        Speed knots [m/s].
    ay_max : np.ndarray
        Max lateral acceleration [m/s²] at each knot.
    ax_drive_max : np.ndarray
        Max traction acceleration [m/s²] at each knot.
    ax_brake_max : np.ndarray
        Max braking deceleration [m/s²] (positive) at each knot.
    p_combined : float
        Combined-slip p-norm exponent.
    """

    v_grid: np.ndarray
    ay_max: np.ndarray
    ax_drive_max: np.ndarray
    ax_brake_max: np.ndarray
    p_combined: float = 1.6

    track_id: str = ""
    kart_id: str = ""
    n_sessions: int = 0
    n_laps: int = 0

    # Private interpolators
    _lat_fn: Any = field(init=False, repr=False, default=None)
    _trac_fn: Any = field(init=False, repr=False, default=None)
    _brake_fn: Any = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self._build_interpolators()

    def _build_interpolators(self) -> None:
        """Build piecewise-linear interpolators from grid arrays."""
        def _make(vals: np.ndarray) -> Any:
            m = np.isfinite(vals)
            if m.sum() < 2:
                c = float(np.nanmean(vals)) if m.any() else _G
                return lambda v, _c=c: np.full_like(np.asarray(v, dtype=float), _c)
            vg, yg = self.v_grid[m], vals[m]
            return lambda v, _vg=vg, _yg=yg: np.interp(
                np.asarray(v, dtype=float), _vg, _yg)

        self._lat_fn = _make(self.ay_max)
        self._trac_fn = _make(self.ax_drive_max)
        self._brake_fn = _make(self.ax_brake_max)

    # ------------------------------------------------------------------
    # FrictionLike protocol
    # ------------------------------------------------------------------
    def lateral_max(self, speed: float | np.ndarray) -> np.ndarray:
        """Max lateral accel [m/s²] at *speed*."""
        return self._lat_fn(speed)

    def traction_max(self, speed: float | np.ndarray) -> np.ndarray:
        """Max traction accel [m/s²] at *speed*."""
        return self._trac_fn(speed)

    def braking_max(self, speed: float | np.ndarray) -> np.ndarray:
        """Max braking deceleration [m/s²] (positive) at *speed*."""
        return self._brake_fn(speed)

    def max_lateral_accel(
        self, speed: float, longitudinal_accel: float = 0.0,
    ) -> float:
        """Available lateral accel under combined loading."""
        ay_max_v = float(self.lateral_max(speed))
        if longitudinal_accel == 0.0:
            return ay_max_v
        ax_max_v = (float(self.traction_max(speed)) if longitudinal_accel > 0
                     else float(self.braking_max(speed)))
        if ax_max_v <= 0:
            return ay_max_v
        p = self.p_combined
        ratio = min(abs(longitudinal_accel) / ax_max_v, 1.0)
        return ay_max_v * max(0.0, (1.0 - ratio ** p)) ** (1.0 / p)

    def max_longitudinal_accel(
        self, speed: float, lateral_accel: float = 0.0, *, braking: bool = False,
    ) -> float:
        """Available longitudinal accel under combined loading."""
        ax_max_v = float(self.braking_max(speed) if braking
                          else self.traction_max(speed))
        ay_max_v = float(self.lateral_max(speed))
        if lateral_accel == 0.0 or ay_max_v <= 0:
            return ax_max_v
        p = self.p_combined
        ratio = min(abs(lateral_accel) / ay_max_v, 1.0)
        return ax_max_v * max(0.0, (1.0 - ratio ** p)) ** (1.0 / p)

    def max_cornering_speed(
        self, curvature: float, longitudinal_accel: float = 0.0,
    ) -> float:
        """Max speed through corner of given curvature [1/m]."""
        if curvature <= 0.0:
            return float("inf")
        # Iterative: grip is speed-dependent
        a_lat = self.max_lateral_accel(5.0, longitudinal_accel)
        if a_lat <= 0:
            return 0.0
        v = math.sqrt(a_lat / curvature)
        for _ in range(5):
            a_lat = self.max_lateral_accel(v, longitudinal_accel)
            if a_lat <= 0:
                return 0.0
            v_new = math.sqrt(a_lat / curvature)
            if abs(v_new - v) < 0.01:
                break
            v = v_new
        return v

    # ------------------------------------------------------------------
    # Scaling for session conditions
    # ------------------------------------------------------------------
    def scaled(
        self,
        mu: float = 1.0,
        p_drive: float = 1.0,
        b_brake: float = 1.0,
    ) -> CapabilityEnvelope:
        """Return a new envelope with limits scaled by session scalars."""
        return CapabilityEnvelope(
            v_grid=self.v_grid.copy(),
            ay_max=self.ay_max * mu,
            ax_drive_max=self.ax_drive_max * p_drive,
            ax_brake_max=self.ax_brake_max * b_brake,
            p_combined=self.p_combined,
            track_id=self.track_id,
            kart_id=self.kart_id,
            n_sessions=self.n_sessions,
            n_laps=self.n_laps,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "1.0",
            "track_id": self.track_id,
            "kart_id": self.kart_id,
            "n_sessions": self.n_sessions,
            "n_laps": self.n_laps,
            "p_combined": round(self.p_combined, 4),
            "v_grid": np.round(self.v_grid, 4).tolist(),
            "ay_max": np.round(self.ay_max, 4).tolist(),
            "ax_drive_max": np.round(self.ax_drive_max, 4).tolist(),
            "ax_brake_max": np.round(self.ax_brake_max, 4).tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CapabilityEnvelope:
        return cls(
            v_grid=np.asarray(d["v_grid"], dtype=float),
            ay_max=np.asarray(d["ay_max"], dtype=float),
            ax_drive_max=np.asarray(d["ax_drive_max"], dtype=float),
            ax_brake_max=np.asarray(d["ax_brake_max"], dtype=float),
            p_combined=float(d.get("p_combined", 1.6)),
            track_id=d.get("track_id", ""),
            kart_id=d.get("kart_id", ""),
            n_sessions=int(d.get("n_sessions", 0)),
            n_laps=int(d.get("n_laps", 0)),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        logger.info("Saved envelope to %s", path)

    @classmethod
    def load(cls, path: Path) -> CapabilityEnvelope:
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


# ---------------------------------------------------------------------------
# Envelope training
# ---------------------------------------------------------------------------

def _gaussian_smooth(arr: np.ndarray, hw: int) -> np.ndarray:
    """Smooth 1-D array with Gaussian kernel of half-width *hw*."""
    if hw < 1 or len(arr) < 3:
        return arr.copy()
    n = 2 * hw + 1
    x = np.arange(-hw, hw + 1, dtype=float)
    kernel = np.exp(-0.5 * (x / max(hw / 2, 1)) ** 2)
    kernel /= kernel.sum()
    # Pad and convolve
    padded = np.pad(arr, hw, mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: len(arr)]


def _pava_isotone(arr: np.ndarray) -> np.ndarray:
    """Pool Adjacent Violators: make array non-decreasing."""
    out = arr.copy()
    n = len(out)
    i = 0
    while i < n - 1:
        if out[i] > out[i + 1]:
            # Pool
            j = i + 1
            while j < n and out[j] < out[i]:
                j += 1
            pool_mean = np.mean(out[i:j])
            out[i:j] = pool_mean
            # Back-track
            if i > 0:
                i -= 1
            else:
                i = j
        else:
            i += 1
    return out


def _pava_antitone(arr: np.ndarray) -> np.ndarray:
    """Pool Adjacent Violators: make array non-increasing."""
    return _pava_isotone(arr[::-1])[::-1].copy()


def train_capability_envelope(
    sessions: list[dict[int, pd.DataFrame]],
    config: KartEnvelopeConfig | None = None,
    track_id: str = "",
    kart_id: str = "",
) -> CapabilityEnvelope:
    """Learn a per-(track, kart) capability envelope from clean laps.

    Algorithm
    ---------
    1. Pool all (speed, a_long, a_lat) triplets.
    2. Build adaptive speed bins.
    3. Per bin: extract quantiles for lateral, traction, braking.
    4. Gaussian smoothing across bins.
    5. Monotonicity enforcement (PAVA).
    6. Floor values and GPS correction.
    7. Fit combined-slip p-norm exponent.

    Parameters
    ----------
    sessions : list[dict[int, pd.DataFrame]]
        Each element is a dict ``{lap_num: resampled_df}`` from one session.
    config : KartEnvelopeConfig | None
    track_id, kart_id : str

    Returns
    -------
    CapabilityEnvelope

    Raises
    ------
    EnvelopeError
        If insufficient data.
    """
    if config is None:
        config = default_config()

    # --- 1. Pool samples ---
    v_list, ax_list, ay_list = [], [], []
    total_laps = 0
    for sess in sessions:
        for lap_df in sess.values():
            total_laps += 1
            for col, lst in [(COL_SPEED, v_list), (COL_ACCEL_LONG, ax_list),
                              (COL_ACCEL_LAT, ay_list)]:
                if col in lap_df.columns:
                    lst.append(lap_df[col].values)
                else:
                    lst.append(np.full(len(lap_df), np.nan))

    if not v_list:
        raise EnvelopeError("No data to build envelope.")

    v_all = np.concatenate(v_list)
    ax_all = np.concatenate(ax_list)
    ay_all = np.concatenate(ay_list)

    # Drop NaN/inf
    valid = np.isfinite(v_all) & np.isfinite(ax_all) & np.isfinite(ay_all) & (v_all > 0.5)
    v_all, ax_all, ay_all = v_all[valid], ax_all[valid], ay_all[valid]

    if len(v_all) < 50:
        raise EnvelopeError(f"Only {len(v_all)} valid samples; need >= 50.")

    # --- 2. Speed bins ---
    n_bins = config.envelope_speed_bins
    v_lo = float(np.percentile(v_all, 1))
    v_hi = float(np.percentile(v_all, 99))
    v_grid = np.linspace(v_lo, v_hi, n_bins)
    bin_width = (v_hi - v_lo) / max(n_bins - 1, 1) * 0.6  # overlap width

    # --- 3. Per-bin quantiles ---
    ay_arr = np.full(n_bins, np.nan)
    ax_drive_arr = np.full(n_bins, np.nan)
    ax_brake_arr = np.full(n_bins, np.nan)

    min_samp = config.envelope_min_samples_per_bin
    q_lat = config.envelope_quantile_lat
    q_trac = config.envelope_quantile_trac
    q_brake = config.envelope_quantile_brake

    for i, vc in enumerate(v_grid):
        in_bin = np.abs(v_all - vc) <= bin_width
        if in_bin.sum() < min_samp:
            continue

        # Lateral: |ay| quantile
        ay_bin = np.abs(ay_all[in_bin])
        ay_bin = ay_bin[np.isfinite(ay_bin)]
        if len(ay_bin) >= min_samp:
            ay_arr[i] = float(np.percentile(ay_bin, q_lat * 100))

        # Traction: ax > 0.1 m/s² quantile
        ax_pos = ax_all[in_bin]
        ax_pos = ax_pos[ax_pos > 0.1]
        if len(ax_pos) >= min_samp:
            ax_drive_arr[i] = float(np.percentile(ax_pos, q_trac * 100))

        # Braking: |ax| for ax < -0.1 quantile
        ax_neg = ax_all[in_bin]
        ax_neg = np.abs(ax_neg[ax_neg < -0.1])
        if len(ax_neg) >= min_samp:
            ax_brake_arr[i] = float(np.percentile(ax_neg, q_brake * 100))

    # --- 4. Interpolate NaN gaps ---
    for arr in (ay_arr, ax_drive_arr, ax_brake_arr):
        _interp_nans(arr)

    # --- 5. Gaussian smoothing ---
    hw = config.envelope_smooth_hw
    ay_arr = _gaussian_smooth(ay_arr, hw)
    ax_drive_arr = _gaussian_smooth(ax_drive_arr, hw)
    ax_brake_arr = _gaussian_smooth(ax_brake_arr, hw)

    # --- 6. Monotonicity constraints ---
    # Braking should be non-decreasing with speed (aero-assisted)
    ax_brake_arr = _pava_isotone(ax_brake_arr)
    # Traction should be non-increasing at high speed (power limit)
    ax_drive_arr = _pava_antitone(ax_drive_arr)

    # --- 7. GPS correction + floor ---
    gps_corr = config.envelope_gps_correction
    ay_arr *= gps_corr
    ax_drive_arr *= gps_corr
    ax_brake_arr *= gps_corr

    ay_arr = np.maximum(ay_arr, config.envelope_lateral_floor_mps2)
    ax_drive_arr = np.maximum(ax_drive_arr, config.envelope_traction_floor_mps2)
    ax_brake_arr = np.maximum(ax_brake_arr, config.envelope_traction_floor_mps2)

    # --- 8. Fit p-norm ---
    # Build temporary interpolators for the fit
    env_temp = CapabilityEnvelope(
        v_grid=v_grid,
        ay_max=ay_arr,
        ax_drive_max=ax_drive_arr,
        ax_brake_max=ax_brake_arr,
        p_combined=config.envelope_combined_p_init,
    )

    p_fit = fit_p_norm(
        v_all, ax_all, ay_all,
        ax_max_fn=env_temp.traction_max,
        ay_max_fn=env_temp.lateral_max,
        braking_max_fn=env_temp.braking_max,
        p_lo=config.envelope_combined_p_lo,
        p_hi=config.envelope_combined_p_hi,
    )

    envelope = CapabilityEnvelope(
        v_grid=v_grid,
        ay_max=ay_arr,
        ax_drive_max=ax_drive_arr,
        ax_brake_max=ax_brake_arr,
        p_combined=p_fit,
        track_id=track_id,
        kart_id=kart_id,
        n_sessions=len(sessions),
        n_laps=total_laps,
    )

    logger.info(
        "Envelope trained: %d sessions, %d laps, %d bins, p=%.2f, "
        "ay_max=[%.1f..%.1f], ax_drive=[%.1f..%.1f], ax_brake=[%.1f..%.1f] m/s².",
        len(sessions), total_laps, n_bins, p_fit,
        float(np.nanmin(ay_arr)), float(np.nanmax(ay_arr)),
        float(np.nanmin(ax_drive_arr)), float(np.nanmax(ax_drive_arr)),
        float(np.nanmin(ax_brake_arr)), float(np.nanmax(ax_brake_arr)),
    )
    return envelope


def _interp_nans(arr: np.ndarray) -> None:
    """Linearly interpolate NaN gaps *in-place*."""
    idx = np.arange(len(arr))
    good = np.isfinite(arr)
    if good.sum() < 2:
        # Fill with a constant if < 2 good values
        val = float(np.nanmean(arr)) if good.any() else _G
        arr[:] = val
        return
    arr[~good] = np.interp(idx[~good], idx[good], arr[good])
