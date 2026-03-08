"""
friction_envelope.py
--------------------
Combined (lateral + longitudinal) friction envelope estimator.

Estimates per-speed-bin sqrt(ax^2 + ay^2) limits and separate
ax/ay bounds from observed laps. Provides feasibility checking
and ellipse-based max lateral under given longitudinal accel.

Falls back gracefully when data is sparse.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict

import numpy as np

logger = logging.getLogger(__name__)

_G = 9.80665  # m/s^2

# ── Column names ──────────────────────────────────────────────────
_COL_SPEED = "Speed (m/s)"
_COL_LAT_ACCEL_G = "Lateral acceleration (G) *calc"
_COL_LAT_ACCEL_MPS2 = "accel_lat_mps2"
_COL_LONG_ACCEL_MPS2 = "accel_long_mps2"

# ── Thresholds ────────────────────────────────────────────────────
_MIN_TOTAL_SAMPLES = 50
_MIN_SAMPLES_PER_BIN = 8
_N_SPEED_BINS = 15
_PERCENTILE = 95.0
_IQR_FENCE = 1.5


@dataclass
class FrictionBin:
    """Per-speed-bin friction envelope stats."""
    speed_center_mps: float
    combined_g_p95: float        # sqrt(ax^2+ay^2) 95th percentile [G]
    lat_max_g: float             # |ay| 95th percentile [G]
    accel_max_g: float           # ax (positive) 95th percentile [G]
    brake_max_g: float           # |ax| (negative) 95th percentile [G]
    sample_count: int
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FrictionEnvelope:
    """Combined acceleration envelope across speed range."""
    speed_bins: np.ndarray
    friction_bins: list[FrictionBin]
    global_combined_g: float
    is_reliable: bool
    warning: str | None

    def _get_bin(self, speed_mps: float) -> FrictionBin | None:
        """Find nearest speed bin."""
        if not self.friction_bins:
            return None
        idx = int(np.argmin(np.abs(self.speed_bins - speed_mps)))
        fb = self.friction_bins[idx]
        return fb if fb.sample_count >= _MIN_SAMPLES_PER_BIN else None

    def is_feasible(
        self, speed_mps: float, a_lat_g: float, a_long_g: float,
    ) -> bool:
        """Check if (a_lat, a_long) is within envelope at given speed.

        Parameters in G units.
        """
        fb = self._get_bin(speed_mps)
        if fb is None:
            # Fall back to global
            combined = np.sqrt(a_lat_g ** 2 + a_long_g ** 2)
            return bool(combined <= self.global_combined_g * 1.1)  # 10% margin

        combined = np.sqrt(a_lat_g ** 2 + a_long_g ** 2)
        return bool(combined <= fb.combined_g_p95 * 1.05)  # 5% margin

    def max_lat_at_long(
        self, speed_mps: float, a_long_g: float,
    ) -> float:
        """Max lateral accel given longitudinal accel (ellipse constraint).

        Returns max |a_lat| in G.
        """
        fb = self._get_bin(speed_mps)
        if fb is None:
            r = self.global_combined_g
            residual_sq = max(0.0, r ** 2 - a_long_g ** 2)
            return float(np.sqrt(residual_sq))

        # Ellipse: (a_long/a_long_max)^2 + (a_lat/a_lat_max)^2 <= 1
        if a_long_g >= 0:
            a_long_max = fb.accel_max_g if fb.accel_max_g > 0 else fb.combined_g_p95
        else:
            a_long_max = fb.brake_max_g if fb.brake_max_g > 0 else fb.combined_g_p95

        a_lat_max = fb.lat_max_g if fb.lat_max_g > 0 else fb.combined_g_p95

        long_frac_sq = min(1.0, (a_long_g / a_long_max) ** 2) if a_long_max > 0 else 0.0
        residual = max(0.0, 1.0 - long_frac_sq)
        return float(a_lat_max * np.sqrt(residual))

    def to_dict(self) -> dict:
        return {
            "speed_bins": self.speed_bins.tolist(),
            "friction_bins": [fb.to_dict() for fb in self.friction_bins],
            "global_combined_g": round(self.global_combined_g, 4),
            "is_reliable": self.is_reliable,
            "warning": self.warning,
        }


def _iqr_reject(samples: np.ndarray) -> np.ndarray:
    """Remove outliers using IQR fence."""
    if len(samples) < 4:
        return samples
    q1, q3 = np.percentile(samples, [25, 75])
    iqr = q3 - q1
    lo = q1 - _IQR_FENCE * iqr
    hi = q3 + _IQR_FENCE * iqr
    mask = (samples >= lo) & (samples <= hi)
    return samples[mask] if mask.sum() >= 3 else samples


def compute_friction_envelope(
    resampled_laps: dict[int, "pd.DataFrame"],
    *,
    learning_laps: list[int] | None = None,
    n_speed_bins: int = _N_SPEED_BINS,
    percentile: float = _PERCENTILE,
) -> FrictionEnvelope:
    """Compute combined friction envelope from observed laps.

    Parameters
    ----------
    resampled_laps : lap_number -> DataFrame
    learning_laps : restrict to these lap numbers
    n_speed_bins : number of speed bins
    percentile : percentile for envelope extraction

    Returns
    -------
    FrictionEnvelope with per-speed-bin limits.
    """
    import pandas as pd

    sorted_keys = sorted(resampled_laps.keys())
    if learning_laps is not None:
        learning_set = set(learning_laps)
        sorted_keys = [k for k in sorted_keys if k in learning_set]

    # Collect (speed, a_lat_g, a_long_g) triples
    all_speed: list[float] = []
    all_lat_g: list[float] = []
    all_long_g: list[float] = []

    for k in sorted_keys:
        df = resampled_laps[k]
        if _COL_SPEED not in df.columns:
            continue

        speed = pd.to_numeric(df[_COL_SPEED], errors="coerce").values

        # Lateral accel in G
        lat_g = None
        if _COL_LAT_ACCEL_G in df.columns:
            lat_g = pd.to_numeric(df[_COL_LAT_ACCEL_G], errors="coerce").values
        elif _COL_LAT_ACCEL_MPS2 in df.columns:
            lat_g = pd.to_numeric(df[_COL_LAT_ACCEL_MPS2], errors="coerce").values / _G
        if lat_g is None:
            continue

        # Longitudinal accel in G
        long_g = np.zeros(len(df))
        if _COL_LONG_ACCEL_MPS2 in df.columns:
            long_g = pd.to_numeric(df[_COL_LONG_ACCEL_MPS2], errors="coerce").values / _G

        valid = np.isfinite(speed) & np.isfinite(lat_g) & np.isfinite(long_g)
        all_speed.extend(speed[valid].tolist())
        all_lat_g.extend(lat_g[valid].tolist())
        all_long_g.extend(long_g[valid].tolist())

    total_samples = len(all_speed)
    if total_samples < _MIN_TOTAL_SAMPLES:
        return FrictionEnvelope(
            speed_bins=np.array([]),
            friction_bins=[],
            global_combined_g=1.0,
            is_reliable=False,
            warning=f"Only {total_samples} samples — need {_MIN_TOTAL_SAMPLES}+ for friction envelope",
        )

    speed_arr = np.array(all_speed)
    lat_arr = np.array(all_lat_g)
    long_arr = np.array(all_long_g)
    combined_arr = np.sqrt(lat_arr ** 2 + long_arr ** 2)

    # Global combined G
    clean_combined = _iqr_reject(combined_arr)
    global_combined = float(np.percentile(clean_combined, percentile))

    # Speed bins
    v_min, v_max = float(np.percentile(speed_arr, 2)), float(np.percentile(speed_arr, 98))
    if v_max - v_min < 2.0:
        v_max = v_min + 10.0
    bin_edges = np.linspace(v_min, v_max, n_speed_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    # Per-speed-bin stats
    bins_list: list[FrictionBin] = []
    speed_idx = np.digitize(speed_arr, bin_edges) - 1
    speed_idx = np.clip(speed_idx, 0, n_speed_bins - 1)

    for i in range(n_speed_bins):
        mask = speed_idx == i
        n_in_bin = int(mask.sum())
        if n_in_bin < _MIN_SAMPLES_PER_BIN:
            bins_list.append(FrictionBin(
                speed_center_mps=round(float(bin_centers[i]), 2),
                combined_g_p95=round(global_combined, 4),
                lat_max_g=round(global_combined, 4),
                accel_max_g=round(global_combined * 0.6, 4),
                brake_max_g=round(global_combined, 4),
                sample_count=n_in_bin,
                confidence=0.0,
            ))
            continue

        lat_in = np.abs(lat_arr[mask])
        long_in = long_arr[mask]
        comb_in = combined_arr[mask]

        clean_comb = _iqr_reject(comb_in)
        clean_lat = _iqr_reject(lat_in)

        accel_mask = long_in > 0.05
        brake_mask = long_in < -0.05
        accel_vals = _iqr_reject(long_in[accel_mask]) if accel_mask.sum() > 3 else np.array([0.0])
        brake_vals = _iqr_reject(np.abs(long_in[brake_mask])) if brake_mask.sum() > 3 else np.array([0.0])

        conf = min(1.0, n_in_bin / (_MIN_SAMPLES_PER_BIN * 4))

        bins_list.append(FrictionBin(
            speed_center_mps=round(float(bin_centers[i]), 2),
            combined_g_p95=round(float(np.percentile(clean_comb, percentile)), 4),
            lat_max_g=round(float(np.percentile(clean_lat, percentile)), 4),
            accel_max_g=round(float(np.percentile(accel_vals, percentile)), 4),
            brake_max_g=round(float(np.percentile(brake_vals, percentile)), 4),
            sample_count=n_in_bin,
            confidence=round(conf, 3),
        ))

    logger.info(
        "Friction envelope: %d speed bins, %d samples, global_combined=%.3fG",
        n_speed_bins, total_samples, global_combined,
    )

    return FrictionEnvelope(
        speed_bins=bin_centers,
        friction_bins=bins_list,
        global_combined_g=round(global_combined, 4),
        is_reliable=True,
        warning=None,
    )
