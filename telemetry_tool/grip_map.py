"""
grip_map.py
-----------
Distance-binned lateral grip estimator.

Estimates per-distance-bin friction coefficient mu(s) from observed
laps using lateral acceleration (preferred) or v^2 * curvature (fallback).
Produces mu_mean(s), mu_pXX(s), and per-bin confidence scores.

Degrades gracefully: if curvature unreliable or bins sparse, reverts
to global mu with a warning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field

import numpy as np

logger = logging.getLogger(__name__)

_G = 9.80665  # m/s^2

# ── Column names ──────────────────────────────────────────────────
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_LAT_ACCEL_G = "Lateral acceleration (G) *calc"
_COL_LAT_ACCEL_MPS2 = "accel_lat_mps2"
_COL_CURVATURE = "curvature_1pm"

# ── Thresholds ────────────────────────────────────────────────────
_MIN_LAPS = 3
_MIN_SAMPLES_PER_BIN = 3
_CONFIDENCE_SAMPLE_TARGET = 8
_CONFIDENCE_VARIANCE_CAP = 0.1
_SPARSE_BIN_THRESHOLD = 0.5   # if <50% bins confident, global fallback
_IQR_FENCE = 1.5
_MIN_BIN_CONFIDENCE = 0.3


@dataclass
class GripBinStats:
    """Per-distance-bin grip statistics."""
    distance_m: float
    mu_mean: float
    mu_p50: float
    mu_p90: float
    mu_p95: float
    mu_p99: float
    sample_count: int
    variance: float
    confidence: float    # 0-1
    source: str          # "lat_accel" | "curvature_speed" | "global_fallback"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GripMap:
    """Distance-binned grip map for a session."""
    distance_bins: np.ndarray        # [m]
    mu_mean: np.ndarray              # per-bin mean mu
    mu_p90: np.ndarray               # per-bin 90th percentile
    mu_p95: np.ndarray               # per-bin 95th percentile
    bin_stats: list[GripBinStats]
    global_mu: float                 # session-wide median mu
    is_global_fallback: bool
    source: str                      # "lat_accel" | "curvature_speed"
    warning: str | None
    n_laps_used: int

    def mu_at(self, distance: float, percentile: str = "p95") -> float:
        """Interpolate mu at arbitrary distance.

        Parameters
        ----------
        distance : distance along track [m]
        percentile : "mean", "p90", or "p95"

        Returns
        -------
        Interpolated mu value.
        """
        if self.is_global_fallback or len(self.distance_bins) == 0:
            return self.global_mu

        arr_map = {"mean": self.mu_mean, "p90": self.mu_p90, "p95": self.mu_p95}
        arr = arr_map.get(percentile, self.mu_p95)

        # Clamp distance to range
        d = max(self.distance_bins[0], min(self.distance_bins[-1], distance))
        return float(np.interp(d, self.distance_bins, arr))

    def to_dict(self) -> dict:
        return {
            "distance_bins": self.distance_bins.tolist(),
            "mu_mean": self.mu_mean.tolist(),
            "mu_p90": self.mu_p90.tolist(),
            "mu_p95": self.mu_p95.tolist(),
            "global_mu": round(self.global_mu, 4),
            "is_global_fallback": self.is_global_fallback,
            "source": self.source,
            "warning": self.warning,
            "n_laps_used": self.n_laps_used,
            "bin_count": len(self.distance_bins),
        }


def _get_lat_accel_g(df: "pd.DataFrame") -> np.ndarray | None:
    """Extract lateral acceleration in G from a lap DataFrame."""
    import pandas as pd

    for col, scale in [(_COL_LAT_ACCEL_G, 1.0), (_COL_LAT_ACCEL_MPS2, 1.0 / _G)]:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").values * scale
            if np.isfinite(vals).sum() > 10:
                return vals
    return None


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


def _bin_confidence(sample_count: int, variance: float) -> float:
    """Compute per-bin confidence from sample count and variance."""
    count_score = min(1.0, sample_count / _CONFIDENCE_SAMPLE_TARGET)
    variance_score = max(0.0, 1.0 - variance / _CONFIDENCE_VARIANCE_CAP)
    return round(0.6 * count_score + 0.4 * variance_score, 3)


def compute_grip_map(
    resampled_laps: dict[int, "pd.DataFrame"],
    curvature_profile: "pd.DataFrame | None" = None,
    *,
    learning_laps: list[int] | None = None,
    n_bins: int = 0,
) -> GripMap:
    """Compute distance-binned grip map from observed laps.

    Parameters
    ----------
    resampled_laps : lap_number -> DataFrame
    curvature_profile : DataFrame with distance_m + curvature_1pm columns
    learning_laps : restrict to these lap numbers
    n_bins : number of distance bins (0 = auto from data)

    Returns
    -------
    GripMap with per-bin mu estimates and confidence.
    """
    import pandas as pd

    sorted_keys = sorted(resampled_laps.keys())
    if learning_laps is not None:
        learning_set = set(learning_laps)
        sorted_keys = [k for k in sorted_keys if k in learning_set]

    n_laps = len(sorted_keys)

    # Too few laps -> global fallback
    if n_laps < _MIN_LAPS:
        # Collect whatever mu samples we can
        all_mu = []
        for k in sorted_keys:
            g_vals = _get_lat_accel_g(resampled_laps[k])
            if g_vals is not None:
                all_mu.extend(np.abs(g_vals[np.isfinite(g_vals)]).tolist())
        global_mu = float(np.median(all_mu)) if all_mu else 1.0
        return GripMap(
            distance_bins=np.array([]),
            mu_mean=np.array([]),
            mu_p90=np.array([]),
            mu_p95=np.array([]),
            bin_stats=[],
            global_mu=round(global_mu, 4),
            is_global_fallback=True,
            source="lat_accel" if all_mu else "global_fallback",
            warning=f"Only {n_laps} lap(s) — need {_MIN_LAPS}+ for per-bin grip map",
            n_laps_used=n_laps,
        )

    # Determine distance grid
    first_df = resampled_laps[sorted_keys[0]]
    if _COL_DIST in first_df.columns:
        dist_col = _COL_DIST
    else:
        dist_col = "distance_m" if "distance_m" in first_df.columns else _COL_DIST

    dist_vals = first_df[dist_col].values
    d_min, d_max = float(dist_vals[0]), float(dist_vals[-1])
    if n_bins <= 0:
        n_bins = max(20, min(200, len(dist_vals) // 2))
    bin_edges = np.linspace(d_min, d_max, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    # Try lateral accel first
    has_lat_accel = False
    for k in sorted_keys[:3]:
        if _get_lat_accel_g(resampled_laps[k]) is not None:
            has_lat_accel = True
            break

    # Collect per-bin mu samples
    bin_samples: list[list[float]] = [[] for _ in range(n_bins)]

    if has_lat_accel:
        source = "lat_accel"
        for k in sorted_keys:
            df = resampled_laps[k]
            g_vals = _get_lat_accel_g(df)
            if g_vals is None:
                continue
            if dist_col not in df.columns:
                continue
            d = df[dist_col].values
            mu = np.abs(g_vals)
            valid = np.isfinite(mu) & np.isfinite(d) & (mu > 0.01)
            d_valid, mu_valid = d[valid], mu[valid]
            bin_idx = np.digitize(d_valid, bin_edges) - 1
            bin_idx = np.clip(bin_idx, 0, n_bins - 1)
            for i, m in zip(bin_idx, mu_valid):
                bin_samples[i].append(float(m))
    elif curvature_profile is not None and _COL_CURVATURE in curvature_profile.columns:
        source = "curvature_speed"
        # Build curvature interpolator
        cp_dist = curvature_profile["distance_m"].values
        cp_curv = curvature_profile[_COL_CURVATURE].values
        for k in sorted_keys:
            df = resampled_laps[k]
            if dist_col not in df.columns or _COL_SPEED not in df.columns:
                continue
            d = df[dist_col].values
            v = df[_COL_SPEED].values
            curv = np.interp(d, cp_dist, cp_curv)
            # mu = v^2 * |curv| / g
            mu = v ** 2 * np.abs(curv) / _G
            valid = np.isfinite(mu) & np.isfinite(d) & (mu > 0.01) & (np.abs(curv) > 0.001)
            d_valid, mu_valid = d[valid], mu[valid]
            bin_idx = np.digitize(d_valid, bin_edges) - 1
            bin_idx = np.clip(bin_idx, 0, n_bins - 1)
            for i, m in zip(bin_idx, mu_valid):
                bin_samples[i].append(float(m))
    else:
        source = "global_fallback"
        return GripMap(
            distance_bins=bin_centers,
            mu_mean=np.full(n_bins, 1.0),
            mu_p90=np.full(n_bins, 1.0),
            mu_p95=np.full(n_bins, 1.0),
            bin_stats=[],
            global_mu=1.0,
            is_global_fallback=True,
            source=source,
            warning="No lateral acceleration or curvature data available",
            n_laps_used=n_laps,
        )

    # Compute per-bin statistics
    stats_list: list[GripBinStats] = []
    mu_mean_arr = np.full(n_bins, np.nan)
    mu_p90_arr = np.full(n_bins, np.nan)
    mu_p95_arr = np.full(n_bins, np.nan)
    all_clean_mu: list[float] = []

    for i in range(n_bins):
        samples = np.array(bin_samples[i])
        if len(samples) < _MIN_SAMPLES_PER_BIN:
            stats_list.append(GripBinStats(
                distance_m=round(float(bin_centers[i]), 1),
                mu_mean=0.0, mu_p50=0.0, mu_p90=0.0,
                mu_p95=0.0, mu_p99=0.0,
                sample_count=len(samples),
                variance=0.0, confidence=0.0,
                source=source,
            ))
            continue

        clean = _iqr_reject(samples)
        all_clean_mu.extend(clean.tolist())

        mean_val = float(np.mean(clean))
        var_val = float(np.var(clean))
        conf = _bin_confidence(len(clean), var_val)

        p50 = float(np.percentile(clean, 50))
        p90 = float(np.percentile(clean, 90))
        p95 = float(np.percentile(clean, 95))
        p99 = float(np.percentile(clean, 99))

        mu_mean_arr[i] = mean_val
        mu_p90_arr[i] = p90
        mu_p95_arr[i] = p95

        stats_list.append(GripBinStats(
            distance_m=round(float(bin_centers[i]), 1),
            mu_mean=round(mean_val, 4),
            mu_p50=round(p50, 4),
            mu_p90=round(p90, 4),
            mu_p95=round(p95, 4),
            mu_p99=round(p99, 4),
            sample_count=len(clean),
            variance=round(var_val, 6),
            confidence=conf,
            source=source,
        ))

    # Global mu
    global_mu = float(np.median(all_clean_mu)) if all_clean_mu else 1.0

    # Fill NaN bins with global mu
    nan_mask = np.isnan(mu_mean_arr)
    mu_mean_arr[nan_mask] = global_mu
    mu_p90_arr[nan_mask] = global_mu
    mu_p95_arr[nan_mask] = global_mu

    # Check sparsity -> global fallback
    confident_bins = sum(1 for s in stats_list if s.confidence >= _MIN_BIN_CONFIDENCE)
    is_global = confident_bins < _SPARSE_BIN_THRESHOLD * n_bins
    warning = None
    if is_global:
        warning = (
            f"Only {confident_bins}/{n_bins} bins have sufficient confidence "
            f"— using global mu={global_mu:.2f}"
        )
        mu_mean_arr[:] = global_mu
        mu_p90_arr[:] = global_mu
        mu_p95_arr[:] = global_mu

    logger.info(
        "Grip map [%s]: %d bins, %d confident, global_mu=%.3f, fallback=%s",
        source, n_bins, confident_bins, global_mu, is_global,
    )

    return GripMap(
        distance_bins=bin_centers,
        mu_mean=np.round(mu_mean_arr, 4),
        mu_p90=np.round(mu_p90_arr, 4),
        mu_p95=np.round(mu_p95_arr, 4),
        bin_stats=stats_list,
        global_mu=round(global_mu, 4),
        is_global_fallback=is_global,
        source=source,
        warning=warning,
        n_laps_used=n_laps,
    )
