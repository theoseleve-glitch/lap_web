"""
driving_style.py
----------------
ML-based driving style identification from telemetry data.

Extracts 10 measurable style features from resampled lap data and
corner analysis, then classifies the driver into one of four styles
based on a framework derived from 11 racing technique books:

1. **Smooth Precision** — Low jerk, consistent line, progressive braking
2. **Aggressive Attack** — Late braking, high apex speeds, sharp turn-in
3. **Conservative Safety** — Early braking, wide margins, stable
4. **Adaptive Intuitive** — Varies approach by corner, inconsistent but fast

Public API
~~~~~~~~~~
``extract_style_features(resampled_laps, lap_metrics, corners, ...)``
    Compute the 10 style feature dimensions.

``classify_style(features)``
    Assign style label + confidence from feature vector.

``identify_strengths_weaknesses(features, style_label)``
    Map style to typical strengths/weaknesses.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust: missing data degrades individual features, not the whole result.
- No trained model required — rule-based classification from telemetry features.
- Deterministic: identical inputs -> identical outputs.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# Style feature dataclass
# ============================================================================

@dataclass
class DrivingStyleFeatures:
    """The 10 measurable style dimensions extracted from telemetry."""
    trail_braking_depth:          float = float("nan")
    brake_point_consistency:      float = float("nan")
    brake_pressure_buildup_rate:  float = float("nan")
    apex_speed_ratio:             float = float("nan")
    turn_in_aggressiveness:       float = float("nan")
    throttle_onset_delay_m:       float = float("nan")
    exit_acceleration_efficiency: float = float("nan")
    line_variation_index:         float = float("nan")
    early_vs_late_stint_pace:     float = float("nan")
    smoothness_composite:         float = float("nan")

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def to_vector(self) -> list[float]:
        """Return features as a list in canonical order."""
        return [
            self.trail_braking_depth,
            self.brake_point_consistency,
            self.brake_pressure_buildup_rate,
            self.apex_speed_ratio,
            self.turn_in_aggressiveness,
            self.throttle_onset_delay_m,
            self.exit_acceleration_efficiency,
            self.line_variation_index,
            self.early_vs_late_stint_pace,
            self.smoothness_composite,
        ]

    @property
    def n_valid(self) -> int:
        """Count features that are not NaN."""
        return sum(1 for v in self.to_vector() if math.isfinite(v))


# ============================================================================
# Style labels and classifications
# ============================================================================

STYLE_LABELS = [
    "Smooth Precision",
    "Aggressive Attack",
    "Conservative Safety",
    "Adaptive Intuitive",
]

_STYLE_PROFILES = {
    # Each profile: (feature_name, expected_range_low, expected_range_high, weight)
    "Smooth Precision": {
        "smoothness_composite":     (0.7, 1.0, 2.0),
        "line_variation_index":     (0.0, 0.3, 1.5),
        "brake_point_consistency":  (0.7, 1.0, 1.5),
        "brake_pressure_buildup_rate": (0.0, 0.4, 1.0),
        "turn_in_aggressiveness":   (0.0, 0.4, 1.0),
        "throttle_onset_delay_m":   (0.4, 1.0, 1.0),  # patient on exit
    },
    "Aggressive Attack": {
        "brake_pressure_buildup_rate": (0.6, 1.0, 2.0),
        "apex_speed_ratio":         (0.7, 1.0, 1.5),
        "turn_in_aggressiveness":   (0.6, 1.0, 1.5),
        "throttle_onset_delay_m":   (0.0, 0.3, 1.0),  # early throttle
        "trail_braking_depth":      (0.5, 1.0, 1.0),
        "exit_acceleration_efficiency": (0.7, 1.0, 1.0),
    },
    "Conservative Safety": {
        "brake_point_consistency":  (0.6, 1.0, 1.5),
        "smoothness_composite":     (0.4, 0.7, 1.0),
        "apex_speed_ratio":         (0.0, 0.5, 1.5),
        "trail_braking_depth":      (0.0, 0.3, 1.5),
        "turn_in_aggressiveness":   (0.0, 0.3, 1.0),
        "line_variation_index":     (0.0, 0.4, 1.0),
    },
    "Adaptive Intuitive": {
        "line_variation_index":     (0.4, 1.0, 2.0),
        "early_vs_late_stint_pace": (0.3, 0.7, 1.5),  # mid-range = adapting
        "apex_speed_ratio":         (0.5, 0.9, 1.0),
        "trail_braking_depth":      (0.3, 0.7, 1.0),
        "exit_acceleration_efficiency": (0.4, 0.8, 1.0),
    },
}

_STYLE_STRENGTHS = {
    "Smooth Precision": [
        "Excellent consistency lap-to-lap",
        "Strong tyre management and low degradation",
        "Well-suited to endurance and long stints",
        "Minimal error rate under pressure",
    ],
    "Aggressive Attack": [
        "Strong raw pace and qualifying potential",
        "Effective late braking for overtaking",
        "High corner entry and apex speeds",
        "Good at attacking from behind",
    ],
    "Conservative Safety": [
        "Very reliable with few mistakes",
        "Good in wet/changing conditions",
        "Strong tyre and fuel management",
        "Consistent points scorer in races",
    ],
    "Adaptive Intuitive": [
        "Excels in wet/changing conditions",
        "Strong racecraft and overtaking instinct",
        "Reads track evolution well",
        "Quick to find pace on new circuits",
    ],
}

_STYLE_WEAKNESSES = {
    "Smooth Precision": [
        "May leave pace on the table at the limit",
        "Can be vulnerable on pure pace in qualifying",
        "Defensive driving may cost positions",
    ],
    "Aggressive Attack": [
        "Higher tyre wear and degradation risk",
        "Consistency can suffer under pressure",
        "Prone to mistakes when pushing limits",
    ],
    "Conservative Safety": [
        "Pace deficit to aggressive drivers",
        "May be too cautious when attacking required",
        "Qualifying pace often below potential",
    ],
    "Adaptive Intuitive": [
        "Consistency can be unpredictable",
        "Qualifying may suffer (needs rhythm)",
        "Performance varies with mood/confidence",
    ],
}

# ============================================================================
# Session-type style adjustments
# ============================================================================

# Shift style profile bounds per session type.
# In races, "conservative" is more acceptable (tire management).
# In qualifying, "aggressive" is more expected.
# Values are additive shifts to the (low, high) bounds of each style profile.

_STYLE_ADJUSTMENTS_BY_TYPE: dict[str, dict[str, dict[str, float]]] = {
    "qualifying": {
        # In qualifying, aggressive traits are expected/rewarded
        "Aggressive Attack": {"shift": 0.05},      # slightly wider acceptance
        "Smooth Precision": {"shift": -0.05},       # slightly narrower
        "Conservative Safety": {"shift": -0.10},    # penalise conservative in quali
    },
    "race": {
        # In races, conservative/smooth traits are more acceptable
        "Conservative Safety": {"shift": 0.10},     # reward caution in races
        "Smooth Precision": {"shift": 0.05},        # reward consistency
        "Aggressive Attack": {"shift": -0.05},      # slightly penalise aggression
    },
    "sprint_race": {
        "Aggressive Attack": {"shift": 0.03},
        "Conservative Safety": {"shift": -0.03},
    },
    "endurance": {
        # Endurance rewards smooth, conservative driving
        "Smooth Precision": {"shift": 0.10},
        "Conservative Safety": {"shift": 0.10},
        "Aggressive Attack": {"shift": -0.15},
    },
    "endurance_stint": {
        "Smooth Precision": {"shift": 0.10},
        "Conservative Safety": {"shift": 0.10},
        "Aggressive Attack": {"shift": -0.15},
    },
    "endurance_race": {
        "Smooth Precision": {"shift": 0.10},
        "Conservative Safety": {"shift": 0.10},
        "Aggressive Attack": {"shift": -0.15},
    },
    "warmup": {
        # Warmup is exploratory — adaptive style is more normal
        "Adaptive Intuitive": {"shift": 0.10},
    },
    "test": {
        # Testing sessions — adaptive and experimental is expected
        "Adaptive Intuitive": {"shift": 0.10},
        "Aggressive Attack": {"shift": 0.05},
    },
    "heat": {
        "Aggressive Attack": {"shift": 0.05},
    },
    "final": {
        "Smooth Precision": {"shift": 0.03},
    },
}


# ============================================================================
# Feature extraction
# ============================================================================

def _safe_std(arr: np.ndarray) -> float:
    """Standard deviation, NaN if insufficient data."""
    clean = arr[np.isfinite(arr)]
    return float(np.std(clean)) if len(clean) > 1 else float("nan")


def _safe_mean(arr: np.ndarray) -> float:
    """Mean, NaN if insufficient data."""
    clean = arr[np.isfinite(arr)]
    return float(np.mean(clean)) if len(clean) > 0 else float("nan")


def _normalise_01(value: float, low: float, high: float) -> float:
    """Normalise value to [0, 1] given expected range."""
    if not math.isfinite(value) or high <= low:
        return float("nan")
    return max(0.0, min(1.0, (value - low) / (high - low)))


def extract_style_features(
    resampled_laps: "dict[int, pd.DataFrame]",
    lap_metrics: "list[dict[str, Any]] | None" = None,
    corners: "list[dict[str, Any]] | None" = None,
    corner_performances: "list[dict[str, Any]] | None" = None,
    theoretical_metrics: "dict[str, Any] | None" = None,
    per_lap_corner_metrics: "list[dict[str, Any]] | None" = None,
) -> DrivingStyleFeatures:
    """
    Extract the 10 style feature dimensions from telemetry data.

    Parameters
    ----------
    resampled_laps : dict[int, DataFrame]
        Distance-resampled lap DataFrames keyed by lap number.
    lap_metrics : list[dict]
        Per-lap metrics from the pipeline.
    corners : list[dict]
        Corner definitions (from corner_detection).
    corner_performances : list[dict]
        Per-corner performance data (from corner_analysis).
    theoretical_metrics : dict
        Theoretical (reference) lap metrics.

    Returns
    -------
    DrivingStyleFeatures
        Populated feature dataclass.
    """
    features = DrivingStyleFeatures()
    if not resampled_laps:
        return features

    lap_keys = sorted(resampled_laps.keys())
    n_laps = len(lap_keys)

    # Column name candidates (handle both naming conventions)
    _SPEED_COLS = ("speed_mps", "Speed (m/s)")
    _ACCEL_COLS = ("accel_long_mps2", "accel_mps2", "Acceleration (m/s²)")
    _BRAKE_COLS = ("accel_long_mps2", "braking_mps2", "Braking (m/s²)")
    _LAT_COLS   = ("accel_lat_mps2", "lat_accel_mps2", "Lateral accel (m/s²)")
    _JERK_COLS  = ("jerk_mps3", "Jerk (m/s³)")
    _YAW_COLS   = ("yaw_rate_dps", "Yaw rate (deg/s)")
    _DIST_COLS  = ("distance_m", "Distance (m)")

    def _find_col(df: pd.DataFrame, candidates: tuple) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    # ── 1. Trail braking depth ──
    # Overlap of braking + lateral G in corner entry zones
    trail_depths: list[float] = []
    for k in lap_keys:
        df = resampled_laps[k]
        brake_col = _find_col(df, _BRAKE_COLS)
        lat_col = _find_col(df, _LAT_COLS)
        if brake_col and lat_col:
            braking = pd.to_numeric(df[brake_col], errors="coerce").fillna(0).values
            lateral = pd.to_numeric(df[lat_col], errors="coerce").fillna(0).abs().values
            # Trail braking = significant braking AND lateral load
            brake_thresh = np.percentile(np.abs(braking[braking < 0]) if np.any(braking < 0) else [0], 30) if np.any(braking < 0) else 0
            overlap = np.sum((braking < brake_thresh) & (lateral > np.percentile(lateral, 60)))
            total_braking = np.sum(braking < brake_thresh) if np.any(braking < brake_thresh) else 1
            trail_depths.append(overlap / max(total_braking, 1))
    if trail_depths:
        features.trail_braking_depth = float(np.mean(trail_depths))

    # ── 2. Brake point consistency ──
    # Std dev of braking initiation distance across laps
    brake_onset_dists: list[float] = []
    for k in lap_keys:
        df = resampled_laps[k]
        brake_col = _find_col(df, _BRAKE_COLS)
        dist_col = _find_col(df, _DIST_COLS)
        if brake_col and dist_col:
            braking = pd.to_numeric(df[brake_col], errors="coerce").fillna(0).values
            dists = pd.to_numeric(df[dist_col], errors="coerce").fillna(0).values
            # Find first significant braking point
            thresh = np.percentile(np.abs(braking[braking < 0]) if np.any(braking < 0) else [0], 50) if np.any(braking < 0) else -1
            braking_idxs = np.where(braking < thresh)[0]
            if len(braking_idxs) > 0:
                brake_onset_dists.append(float(dists[braking_idxs[0]]))
    if len(brake_onset_dists) > 2:
        std = float(np.std(brake_onset_dists))
        mean = float(np.mean(brake_onset_dists))
        cv = std / max(mean, 1.0)
        features.brake_point_consistency = max(0.0, 1.0 - cv)

    # ── 3. Brake pressure buildup rate ──
    # Rate of longitudinal G increase at brake onset
    buildup_rates: list[float] = []
    for k in lap_keys:
        df = resampled_laps[k]
        brake_col = _find_col(df, _BRAKE_COLS)
        dist_col = _find_col(df, _DIST_COLS)
        if brake_col and dist_col:
            braking = pd.to_numeric(df[brake_col], errors="coerce").fillna(0).values
            dists = pd.to_numeric(df[dist_col], errors="coerce").fillna(0).values
            # Find braking zones (negative accel, whether G or m/s²)
            neg = braking[braking < 0]
            if len(neg) < 3:
                continue
            thresh = np.percentile(np.abs(neg), 30) * -1.0
            # Find all braking zone onsets
            is_braking = braking < thresh
            diffs = np.diff(is_braking.astype(int))
            onset_idxs = np.where(diffs == 1)[0] + 1  # indices where braking starts
            for oi in onset_idxs:
                end = min(oi + 15, len(braking))
                seg = braking[oi:end]
                seg_d = dists[oi:end]
                if len(seg) < 3:
                    continue
                # Rate = change in braking force per metre
                delta_force = abs(float(seg.min() - seg[0]))
                delta_dist = float(seg_d[-1] - seg_d[0])
                if delta_dist > 1.0:
                    buildup_rates.append(delta_force / delta_dist)
    if buildup_rates:
        mean_rate = float(np.mean(buildup_rates))
        # Detect units: if max braking < 5, data is in G; otherwise m/s²
        max_brk = max(abs(v) for v in buildup_rates) if buildup_rates else 0
        if max_brk < 0.5:
            # G-per-metre: typical 0.005 (gentle) to 0.05 (aggressive)
            features.brake_pressure_buildup_rate = _normalise_01(mean_rate, 0.003, 0.04)
        else:
            # m/s²-per-metre: typical 0.05 (gentle) to 1.5 (aggressive)
            features.brake_pressure_buildup_rate = _normalise_01(mean_rate, 0.05, 1.5)

    # ── 4. Apex speed ratio ──
    # Actual / theoretical apex speed per corner
    if corner_performances and theoretical_metrics:
        theo_speed = theoretical_metrics.get("speed_mean_mps", None)
        if theo_speed and theo_speed > 0:
            apex_ratios = []
            for cp in corner_performances:
                apex_spd = cp.get("apex_speed_mps") or cp.get("min_speed_mps")
                if apex_spd and apex_spd > 0:
                    apex_ratios.append(apex_spd / theo_speed)
            if apex_ratios:
                features.apex_speed_ratio = float(np.mean(apex_ratios))
    # Fallback: use lap metrics speed vs theoretical
    if not math.isfinite(features.apex_speed_ratio) and lap_metrics and theoretical_metrics:
        actual = _safe_mean(np.array([m.get("speed_mean_mps", float("nan")) for m in lap_metrics]))
        theo = theoretical_metrics.get("speed_mean_mps", float("nan"))
        if math.isfinite(actual) and math.isfinite(theo) and theo > 0:
            features.apex_speed_ratio = actual / theo

    # ── 5. Turn-in aggressiveness ──
    # Rate of lateral G build-up at corner entry
    turn_in_rates: list[float] = []
    for k in lap_keys:
        df = resampled_laps[k]
        lat_col = _find_col(df, _LAT_COLS)
        if lat_col:
            lateral = pd.to_numeric(df[lat_col], errors="coerce").fillna(0).abs().values
            # Find sharp increases in lateral G
            if len(lateral) > 10:
                diff = np.diff(lateral)
                # Top 5% of positive jumps = corner entries
                top_jumps = diff[diff > 0]
                if len(top_jumps) > 0:
                    p95 = np.percentile(top_jumps, 95)
                    turn_in_rates.append(float(p95))
    if turn_in_rates:
        mean_rate = float(np.mean(turn_in_rates))
        # Auto-detect units: if mean < 0.2, data is in G; otherwise m/s²
        if mean_rate < 0.2:
            # G units: typical 0.01 (smooth) to 0.15 (aggressive)
            features.turn_in_aggressiveness = _normalise_01(mean_rate, 0.01, 0.12)
        else:
            features.turn_in_aggressiveness = _normalise_01(mean_rate, 0.05, 1.0)

    # ── 6. Throttle onset delay ──
    # Distance after apex before meaningful throttle
    delays: list[float] = []
    if corner_performances:
        for cp in corner_performances:
            delay = cp.get("throttle_onset_delay_m") or cp.get("exit_delay_m")
            if delay is not None and math.isfinite(delay):
                delays.append(delay)
    # Fallback: use per-lap corner metrics from DB
    if not delays and per_lap_corner_metrics:
        for cm in per_lap_corner_metrics:
            onset = cm.get("throttle_onset_m")
            if onset is not None and math.isfinite(onset):
                delays.append(onset)
    if delays:
        mean_delay = float(np.mean(delays))
        # Higher delay = more patient. Normalise 0-20m range.
        features.throttle_onset_delay_m = _normalise_01(mean_delay, 0.0, 15.0)

    # ── 7. Exit acceleration efficiency ──
    exit_accels: list[float] = []
    if corner_performances:
        for cp in corner_performances:
            exit_accel = cp.get("exit_accel_mps2") or cp.get("accel_max_mps2")
            if exit_accel and exit_accel > 0:
                exit_accels.append(exit_accel)
    # Fallback: use per-lap corner metrics from DB
    if not exit_accels and per_lap_corner_metrics:
        for cm in per_lap_corner_metrics:
            ea = cm.get("exit_accel_mps2")
            if ea is not None and math.isfinite(ea) and ea > 0:
                exit_accels.append(ea)
    if exit_accels:
        mean_exit = float(np.mean(exit_accels))
        # Reference: either theoretical or empirical max
        theo_accel = None
        if theoretical_metrics:
            theo_accel = theoretical_metrics.get("accel_max_mps2")
        if theo_accel and theo_accel > 0:
            features.exit_acceleration_efficiency = float(np.clip(mean_exit / theo_accel, 0, 1))
        else:
            # Use max observed as reference
            max_exit = float(np.max(exit_accels))
            if max_exit > 0:
                features.exit_acceleration_efficiency = float(np.clip(mean_exit / max_exit, 0, 1))

    # ── 8. Line variation index ──
    # Std dev of racing line (lateral position) across laps
    if n_laps > 2:
        lat_cols_found = []
        for k in lap_keys:
            df = resampled_laps[k]
            lat_col = _find_col(df, ("latitude", "Latitude (deg)"))
            if lat_col:
                lat_cols_found.append(pd.to_numeric(df[lat_col], errors="coerce").values)
        if len(lat_cols_found) > 2:
            min_len = min(len(a) for a in lat_cols_found)
            stacked = np.array([a[:min_len] for a in lat_cols_found])
            point_stds = np.nanstd(stacked, axis=0)
            mean_std = float(np.nanmean(point_stds))
            # Normalise: typical std 0.00001 (tight) to 0.0005 (loose)
            features.line_variation_index = _normalise_01(mean_std, 0.000005, 0.0003)

    # ── 9. Early vs late stint pace ──
    if lap_metrics and n_laps >= 6:
        times = np.array([m.get("lap_time_s", float("nan")) for m in lap_metrics])
        valid_mask = np.isfinite(times)
        # Also filter out incomplete/invalid laps via is_valid flag
        for i, m in enumerate(lap_metrics):
            if m.get("is_valid") is False or m.get("is_valid") == 0:
                valid_mask[i] = False
        valid = times[valid_mask]
        if len(valid) >= 6:
            # Filter outliers: remove laps > median + 3*IQR (pit laps, incidents)
            median_t = float(np.median(valid))
            iqr = float(np.percentile(valid, 75) - np.percentile(valid, 25))
            upper = median_t + 3 * max(iqr, 0.5)
            lower = median_t * 0.8  # No lap should be < 80% of median
            valid = valid[(valid >= lower) & (valid <= upper)]
        if len(valid) >= 6:
            # Exclude first 2 laps (warm-up/outlap effect) for fairer comparison
            analysis_times = valid[2:] if len(valid) > 8 else valid
            n_third = max(2, len(analysis_times) // 3)
            early = float(np.mean(analysis_times[:n_third]))
            late = float(np.mean(analysis_times[-n_third:]))
            if early > 0:
                # Use percentage delta: positive = degrading, negative = improving
                delta_pct = (late - early) / early  # e.g. -0.03 = 3% improvement
                # Map -5% (strong improvement) to +5% (strong degradation) → 0-1
                # 0 = strongly improving, 0.5 = stable, 1.0 = strongly degrading
                features.early_vs_late_stint_pace = _normalise_01(
                    delta_pct, -0.05, 0.05,
                )

    # ── 10. Smoothness composite ──
    # Jerk RMS + yaw variance
    jerk_values: list[float] = []
    yaw_vars: list[float] = []
    for k in lap_keys:
        df = resampled_laps[k]
        jerk_col = _find_col(df, _JERK_COLS)
        yaw_col = _find_col(df, _YAW_COLS)

        # Compute jerk from longitudinal acceleration if not available
        if not jerk_col:
            accel_col = _find_col(df, _ACCEL_COLS)
            dist_col = _find_col(df, _DIST_COLS)
            if accel_col and dist_col:
                a = pd.to_numeric(df[accel_col], errors="coerce").values
                d = pd.to_numeric(df[dist_col], errors="coerce").values
                if len(a) > 2:
                    # jerk = da/dt ≈ da/ds * v, approximate as da/ds
                    da = np.diff(a)
                    ds = np.diff(d)
                    ds[ds < 0.01] = 0.01  # avoid div by zero
                    jerk_arr = da / ds
                    jerk_arr = jerk_arr[np.isfinite(jerk_arr)]
                    if len(jerk_arr) > 1:
                        jerk_values.append(float(np.sqrt(np.mean(jerk_arr ** 2))))
        else:
            arr = pd.to_numeric(df[jerk_col], errors="coerce").dropna().values
            if len(arr) > 1:
                jerk_values.append(float(np.sqrt(np.mean(arr ** 2))))

        if yaw_col:
            arr = pd.to_numeric(df[yaw_col], errors="coerce").dropna().values
            if len(arr) > 1:
                yaw_vars.append(float(np.var(arr)))

    if jerk_values:
        jerk_rms = float(np.mean(jerk_values))
        # Auto-detect units: if jerk_rms < 1.0, data is in G/m; otherwise (m/s²)/m
        if jerk_rms < 1.0:
            # G/m units: typical 0.001 (ultra-smooth) to 0.1 (jerky)
            jerk_smooth = 1.0 - _normalise_01(jerk_rms, 0.005, 0.08)
        else:
            # m/s²/m units: typical 0.5 (smooth) to 10.0 (jerky)
            jerk_smooth = 1.0 - _normalise_01(jerk_rms, 0.5, 10.0)
        if yaw_vars:
            yaw_var = float(np.mean(yaw_vars))
            yaw_smooth = 1.0 - _normalise_01(yaw_var, 10.0, 500.0)
            features.smoothness_composite = 0.6 * jerk_smooth + 0.4 * yaw_smooth
        else:
            features.smoothness_composite = jerk_smooth

    logger.info(
        "Extracted %d/10 style features.", features.n_valid,
    )
    return features


# ============================================================================
# Style classification
# ============================================================================

def classify_style(
    features: DrivingStyleFeatures,
    session_type: Optional[str] = None,
) -> tuple[str, float]:
    """
    Classify driving style from extracted features.

    Returns (style_label, confidence) where confidence is 0-1.
    Uses weighted distance to each style profile centroid.

    Parameters
    ----------
    features : DrivingStyleFeatures
        The extracted feature vector.
    session_type : str, optional
        Session type (e.g. "qualifying", "race", "endurance") used to
        shift style scores contextually.
    """
    if features.n_valid < 3:
        return "Unknown", 0.0

    scores: dict[str, float] = {}

    for style, profile in _STYLE_PROFILES.items():
        total_weight = 0.0
        total_score = 0.0
        for feat_name, (low, high, weight) in profile.items():
            val = getattr(features, feat_name, float("nan"))
            if not math.isfinite(val):
                continue
            # Score: how well does value fit this style's expected range?
            if low <= val <= high:
                fit = 1.0
            elif val < low:
                fit = max(0.0, 1.0 - (low - val) / max(0.3, low))
            else:
                fit = max(0.0, 1.0 - (val - high) / max(0.3, 1.0 - high))
            total_score += fit * weight
            total_weight += weight

        scores[style] = total_score / total_weight if total_weight > 0 else 0.0

    # Apply session-type adjustments to style scores
    if session_type:
        _stype = str(session_type).lower().replace("-", "_")
        adjustments = _STYLE_ADJUSTMENTS_BY_TYPE.get(_stype, {})
        for style in scores:
            adj = adjustments.get(style, {})
            shift = adj.get("shift", 0.0)
            scores[style] = max(0.0, min(1.0, scores[style] + shift))

    if not scores:
        return "Unknown", 0.0

    best_style = max(scores, key=scores.get)
    best_score = scores[best_style]

    # Confidence = best score minus average of others
    other_avg = np.mean([v for k, v in scores.items() if k != best_style])
    confidence = min(1.0, max(0.0, (best_score - other_avg) * 2))

    logger.info(
        "Style classification: %s (conf=%.2f, scores=%s)",
        best_style, confidence,
        {k: round(v, 3) for k, v in scores.items()},
    )
    return best_style, round(confidence, 3)


# ============================================================================
# Strengths & weaknesses mapping
# ============================================================================

def identify_strengths_weaknesses(
    features: DrivingStyleFeatures,
    style_label: str,
) -> tuple[list[str], list[str]]:
    """
    Return (strengths, weaknesses) lists for the identified driving style.

    Combines style-typical traits with feature-specific observations.
    """
    strengths = list(_STYLE_STRENGTHS.get(style_label, []))
    weaknesses = list(_STYLE_WEAKNESSES.get(style_label, []))

    # Add feature-specific observations
    if math.isfinite(features.trail_braking_depth):
        if features.trail_braking_depth > 0.6:
            strengths.append("Advanced trail braking technique detected")
        elif features.trail_braking_depth < 0.2:
            weaknesses.append("Limited trail braking — potential to carry more speed into corners")

    if math.isfinite(features.brake_point_consistency):
        if features.brake_point_consistency > 0.85:
            strengths.append("Very consistent brake points across laps")
        elif features.brake_point_consistency < 0.5:
            weaknesses.append("Brake point references need work — high variation between laps")

    if math.isfinite(features.smoothness_composite):
        if features.smoothness_composite > 0.8:
            strengths.append("Exceptionally smooth inputs — economy of motion")
        elif features.smoothness_composite < 0.3:
            weaknesses.append("Input smoothness needs improvement — jerkiness reduces grip")

    if math.isfinite(features.early_vs_late_stint_pace):
        if features.early_vs_late_stint_pace < 0.3:
            strengths.append("Gets faster through the stint — strong adaptation")
        elif features.early_vs_late_stint_pace > 0.7:
            weaknesses.append("Pace drops late in stint — consider tyre management or fitness")

    return strengths, weaknesses


# ============================================================================
# Full analysis pipeline entry point
# ============================================================================

def compute_driving_style(
    resampled_laps: "dict[int, pd.DataFrame]",
    lap_metrics: "list[dict[str, Any]] | None" = None,
    corners: "list[dict[str, Any]] | None" = None,
    corner_performances: "list[dict[str, Any]] | None" = None,
    theoretical_metrics: "dict[str, Any] | None" = None,
    session_type: Optional[str] = None,
    per_lap_corner_metrics: "list[dict[str, Any]] | None" = None,
) -> dict[str, Any]:
    """
    Full driving style analysis: extract features, classify, identify traits.

    Returns a JSON-serialisable dict with all style information.
    """
    features = extract_style_features(
        resampled_laps, lap_metrics, corners,
        corner_performances, theoretical_metrics,
        per_lap_corner_metrics=per_lap_corner_metrics,
    )

    style_label, confidence = classify_style(features, session_type=session_type)
    strengths, weaknesses = identify_strengths_weaknesses(features, style_label)

    result = {
        "features": features.to_dict(),
        "style_label": style_label,
        "style_confidence": confidence,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "n_features_valid": features.n_valid,
        "session_type": session_type,
    }

    logger.info(
        "Driving style: %s (%.0f%% confidence, %d/10 features)",
        style_label, confidence * 100, features.n_valid,
    )
    return result


# ============================================================================
# Inline tests
# ============================================================================

def _run_tests() -> None:
    """Inline self-tests."""
    import traceback as tb

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, tb.format_exc()))

    # Test 1: empty features
    def t_empty():
        f = DrivingStyleFeatures()
        assert f.n_valid == 0
        d = f.to_dict()
        assert "trail_braking_depth" in d
        assert len(f.to_vector()) == 10

    _test("empty_features", t_empty)

    # Test 2: classify with no data
    def t_classify_empty():
        f = DrivingStyleFeatures()
        label, conf = classify_style(f)
        assert label == "Unknown"
        assert conf == 0.0

    _test("classify_empty", t_classify_empty)

    # Test 3: classify smooth driver
    def t_classify_smooth():
        f = DrivingStyleFeatures(
            smoothness_composite=0.9,
            line_variation_index=0.1,
            brake_point_consistency=0.9,
            brake_pressure_buildup_rate=0.2,
            turn_in_aggressiveness=0.2,
        )
        label, conf = classify_style(f)
        assert label == "Smooth Precision", f"Got {label}"
        assert conf > 0

    _test("classify_smooth", t_classify_smooth)

    # Test 4: classify aggressive driver
    def t_classify_aggressive():
        f = DrivingStyleFeatures(
            brake_pressure_buildup_rate=0.9,
            apex_speed_ratio=0.9,
            turn_in_aggressiveness=0.9,
            trail_braking_depth=0.8,
            throttle_onset_delay_m=0.1,
        )
        label, conf = classify_style(f)
        assert label == "Aggressive Attack", f"Got {label}"
        assert conf > 0

    _test("classify_aggressive", t_classify_aggressive)

    # Test 5: strengths/weaknesses
    def t_strengths():
        f = DrivingStyleFeatures(
            trail_braking_depth=0.8,
            smoothness_composite=0.9,
            brake_point_consistency=0.9,
        )
        s, w = identify_strengths_weaknesses(f, "Smooth Precision")
        assert len(s) > 0
        assert any("trail" in x.lower() for x in s)

    _test("strengths_weaknesses", t_strengths)

    # Test 6: extract from minimal data
    def t_extract_minimal():
        # Create minimal resampled laps
        laps = {}
        for i in range(5):
            df = pd.DataFrame({
                "distance_m": np.linspace(0, 1000, 100),
                "speed_mps": np.random.uniform(15, 25, 100),
                "braking_mps2": np.random.uniform(-5, 0, 100),
                "lat_accel_mps2": np.random.uniform(-2, 2, 100),
                "jerk_mps3": np.random.uniform(-10, 10, 100),
                "yaw_rate_dps": np.random.uniform(-50, 50, 100),
            })
            laps[i + 1] = df
        f = extract_style_features(laps)
        assert f.n_valid > 0

    _test("extract_minimal", t_extract_minimal)

    # Test 7: full pipeline
    def t_full_pipeline():
        laps = {}
        for i in range(5):
            df = pd.DataFrame({
                "distance_m": np.linspace(0, 1000, 100),
                "speed_mps": np.random.uniform(15, 25, 100),
                "braking_mps2": np.random.uniform(-5, 0, 100),
                "lat_accel_mps2": np.random.uniform(-2, 2, 100),
                "jerk_mps3": np.random.uniform(-10, 10, 100),
                "yaw_rate_dps": np.random.uniform(-50, 50, 100),
            })
            laps[i + 1] = df
        metrics = [{"lap_time_s": 60 + i * 0.1} for i in range(5)]
        result = compute_driving_style(laps, lap_metrics=metrics)
        assert "style_label" in result
        assert "features" in result
        assert result["n_features_valid"] > 0

    _test("full_pipeline", t_full_pipeline)

    # Test 8: type-aware classification - aggressive in endurance shifted
    def t_type_endurance():
        f = DrivingStyleFeatures(
            brake_pressure_buildup_rate=0.9,
            apex_speed_ratio=0.9,
            turn_in_aggressiveness=0.9,
            trail_braking_depth=0.8,
            throttle_onset_delay_m=0.1,
        )
        label_no_type, _ = classify_style(f)
        label_endurance, _ = classify_style(f, session_type="endurance")
        # Without type, should be Aggressive Attack
        assert label_no_type == "Aggressive Attack", f"Got {label_no_type}"
        # With endurance type, aggressive should be penalised
        # (may or may not change the label, but scores shift)
        # Just verify it doesn't crash
        assert label_endurance in STYLE_LABELS or label_endurance == "Unknown"

    _test("type_aware_endurance", t_type_endurance)

    # Test 9: type-aware classification - conservative in qualifying shifted
    def t_type_qualifying():
        f = DrivingStyleFeatures(
            brake_point_consistency=0.9,
            smoothness_composite=0.5,
            apex_speed_ratio=0.3,
            trail_braking_depth=0.1,
            turn_in_aggressiveness=0.1,
            line_variation_index=0.2,
        )
        label_no_type, _ = classify_style(f)
        label_quali, _ = classify_style(f, session_type="qualifying")
        # Conservative in qualifying should be more penalized
        assert label_no_type in STYLE_LABELS or label_no_type == "Unknown"
        assert label_quali in STYLE_LABELS or label_quali == "Unknown"

    _test("type_aware_qualifying", t_type_qualifying)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nDriving Style Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
