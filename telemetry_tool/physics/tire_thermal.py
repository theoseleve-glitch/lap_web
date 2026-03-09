"""Tire thermal analysis module for motorsport telemetry.

Provides grip-temperature modelling, cross-car balance checks,
camber inference from 3-zone temps, and degradation prediction.
All functions are defensive: empty/NaN inputs return sensible defaults.
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Grip-temperature model
# ---------------------------------------------------------------------------

def compute_grip_factor(
    tire_temp: float,
    optimal_low: float = 80.0,
    optimal_high: float = 100.0,
    k_cold: float = 0.005,
    k_hot: float = 0.008,
) -> float:
    """Grip multiplier based on tire temperature.

    Returns 1.0 inside the optimal window, decays exponentially outside.
    Uses ``grip = 1.0 - k * (delta)^2`` then clamps to [0.0, 1.0].

    Parameters
    ----------
    tire_temp : float
        Measured tire surface temperature in degrees C.
    optimal_low, optimal_high : float
        Lower/upper bounds of the optimal grip window.
    k_cold, k_hot : float
        Decay constants for the cold and hot sides respectively.

    Returns
    -------
    float
        Grip factor in [0.0, 1.0].
    """
    if np.isnan(tire_temp):
        return 0.0

    if optimal_low <= tire_temp <= optimal_high:
        return 1.0

    if tire_temp < optimal_low:
        delta = optimal_low - tire_temp
        grip = 1.0 - k_cold * delta ** 2
    else:
        delta = tire_temp - optimal_high
        grip = 1.0 - k_hot * delta ** 2

    return float(np.clip(grip, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Optimal-window detection
# ---------------------------------------------------------------------------

def detect_optimal_window(
    tire_temps: np.ndarray,
    grip_proxy: np.ndarray,
    bin_width: float = 5.0,
) -> tuple[float, float]:
    """Find the temperature range that maximises grip.

    Bins *tire_temps* into ``bin_width``-degree buckets, computes the mean
    *grip_proxy* (typically |lateral accel|) in each bucket, and returns the
    contiguous range whose mean grip is within 95% of the peak bucket.

    Parameters
    ----------
    tire_temps : np.ndarray
        1-D array of tire temperatures (C).
    grip_proxy : np.ndarray
        1-D array of grip quality (e.g. |lateral acceleration| in m/s^2).
    bin_width : float
        Width of each temperature bucket in degrees C.

    Returns
    -------
    tuple[float, float]
        ``(optimal_low, optimal_high)`` in degrees C.
    """
    tire_temps = np.asarray(tire_temps, dtype=float)
    grip_proxy = np.asarray(grip_proxy, dtype=float)

    # Remove NaNs
    valid = np.isfinite(tire_temps) & np.isfinite(grip_proxy)
    if valid.sum() < 2:
        return (80.0, 100.0)  # fallback defaults

    temps = tire_temps[valid]
    grips = grip_proxy[valid]

    t_min = np.floor(temps.min() / bin_width) * bin_width
    t_max = np.ceil(temps.max() / bin_width) * bin_width
    edges = np.arange(t_min, t_max + bin_width, bin_width)

    if len(edges) < 2:
        return (80.0, 100.0)

    bin_indices = np.digitize(temps, edges) - 1
    bin_indices = np.clip(bin_indices, 0, len(edges) - 2)

    # Mean grip per bin
    bin_means = np.full(len(edges) - 1, np.nan)
    for i in range(len(edges) - 1):
        mask = bin_indices == i
        if mask.sum() > 0:
            bin_means[i] = grips[mask].mean()

    finite_mask = np.isfinite(bin_means)
    if not finite_mask.any():
        return (80.0, 100.0)

    peak = np.nanmax(bin_means)
    threshold = 0.95 * peak

    # Find contiguous bins above threshold
    good_bins = np.where(finite_mask & (bin_means >= threshold))[0]
    if len(good_bins) == 0:
        return (80.0, 100.0)

    optimal_low = float(edges[good_bins[0]])
    optimal_high = float(edges[good_bins[-1]] + bin_width)

    return (optimal_low, optimal_high)


# ---------------------------------------------------------------------------
# Cross-car thermal balance
# ---------------------------------------------------------------------------

def compute_thermal_balance(
    fl: float, fr: float, rl: float, rr: float,
) -> dict:
    """Compute cross-car and front/rear thermal balance.

    Parameters
    ----------
    fl, fr, rl, rr : float
        Average tire temperatures for front-left, front-right,
        rear-left, rear-right.

    Returns
    -------
    dict
        ``lr_front_delta``, ``lr_rear_delta``, ``fr_delta``,
        ``worst_imbalance``, ``balance_rating`` ('good'|'marginal'|'poor').
    """
    values = [fl, fr, rl, rr]
    if any(np.isnan(v) for v in values):
        return {
            "lr_front_delta": np.nan,
            "lr_rear_delta": np.nan,
            "fr_delta": np.nan,
            "worst_imbalance": np.nan,
            "balance_rating": "unknown",
        }

    lr_front = fl - fr
    lr_rear = rl - rr
    fr_delta = (fl + fr) / 2.0 - (rl + rr) / 2.0
    worst = max(abs(lr_front), abs(lr_rear), abs(fr_delta))

    if worst < 5.0:
        rating = "good"
    elif worst < 10.0:
        rating = "marginal"
    else:
        rating = "poor"

    return {
        "lr_front_delta": lr_front,
        "lr_rear_delta": lr_rear,
        "fr_delta": fr_delta,
        "worst_imbalance": worst,
        "balance_rating": rating,
    }


# ---------------------------------------------------------------------------
# Camber inference from 3-zone temps
# ---------------------------------------------------------------------------

def analyze_camber_from_zones(
    inner: float, mid: float, outer: float,
    threshold: float = 5.0,
) -> dict:
    """Classify camber setting from inner/mid/outer tire zone temps.

    Parameters
    ----------
    inner, mid, outer : float
        Zone temperatures in degrees C.
    threshold : float
        Minimum inner-outer delta to consider non-optimal (default 5 C).

    Returns
    -------
    dict
        ``classification`` ('optimal'|'too_much'|'too_little'),
        ``delta`` (inner - outer).
    """
    if any(np.isnan(v) for v in [inner, mid, outer]):
        return {"classification": "unknown", "delta": np.nan}

    delta = inner - outer

    if abs(delta) < threshold:
        classification = "optimal"
    elif delta > 0:
        classification = "too_much"
    else:
        classification = "too_little"

    return {"classification": classification, "delta": float(delta)}


# ---------------------------------------------------------------------------
# Degradation prediction
# ---------------------------------------------------------------------------

def predict_tire_degradation(
    lap_temps: list[dict],
    optimal_low: float = 80.0,
    optimal_high: float = 100.0,
) -> dict:
    """Predict tire degradation rate from per-lap average temperatures.

    Each entry in *lap_temps* should be
    ``{'lap': int, 'fl': float, 'fr': float, 'rl': float, 'rr': float}``.

    Returns
    -------
    dict
        ``temp_rise_per_lap`` (C/lap), ``estimated_grip_window_laps`` (int),
        ``degradation_rate`` ('low'|'moderate'|'high').
    """
    if not lap_temps or len(lap_temps) < 2:
        return {
            "temp_rise_per_lap": 0.0,
            "estimated_grip_window_laps": 0,
            "degradation_rate": "unknown",
        }

    laps_arr = np.array([e["lap"] for e in lap_temps], dtype=float)
    avg_temps = np.array(
        [(e["fl"] + e["fr"] + e["rl"] + e["rr"]) / 4.0 for e in lap_temps],
        dtype=float,
    )

    valid = np.isfinite(laps_arr) & np.isfinite(avg_temps)
    if valid.sum() < 2:
        return {
            "temp_rise_per_lap": 0.0,
            "estimated_grip_window_laps": 0,
            "degradation_rate": "unknown",
        }

    # Linear fit: avg_temp = slope * lap + intercept
    coeffs = np.polyfit(laps_arr[valid], avg_temps[valid], 1)
    slope = float(coeffs[0])  # C per lap

    # Estimate how many laps until the average temp exceeds the optimal window
    current_avg = float(avg_temps[valid][-1])
    if slope <= 0 or current_avg >= optimal_high:
        window_laps = 0
    else:
        window_laps = max(0, int((optimal_high - current_avg) / slope))

    if abs(slope) < 0.5:
        rate = "low"
    elif abs(slope) < 1.5:
        rate = "moderate"
    else:
        rate = "high"

    return {
        "temp_rise_per_lap": round(slope, 3),
        "estimated_grip_window_laps": window_laps,
        "degradation_rate": rate,
    }


# ---------------------------------------------------------------------------
# Column helpers
# ---------------------------------------------------------------------------

_TIRE_TEMP_COLS = {
    "fl": ["tire_temp_fl", "Tire Temp FL (C)"],
    "fr": ["tire_temp_fr", "Tire Temp FR (C)"],
    "rl": ["tire_temp_rl", "Tire Temp RL (C)"],
    "rr": ["tire_temp_rr", "Tire Temp RR (C)"],
}

_ZONE_COLS = {
    "fl_i": ["tire_temp_fl_i", "Tire Temp FL Inner (C)"],
    "fl_m": ["tire_temp_fl_m", "Tire Temp FL Mid (C)"],
    "fl_o": ["tire_temp_fl_o", "Tire Temp FL Outer (C)"],
}

_GRIP_PROXY_COLS = ["accel_lat_mps2", "Acceleration Y (m/s2)"]


def _resolve_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


# ---------------------------------------------------------------------------
# Session-level master function
# ---------------------------------------------------------------------------

def analyze_tire_session(
    resampled_laps: dict,
    corners: list[dict] | None = None,
) -> dict:
    """Run all tire-thermal analyses for a session.

    Parameters
    ----------
    resampled_laps : dict
        ``{lap_number: pd.DataFrame}`` — each DataFrame has distance-indexed
        telemetry rows with optional tire-temp and acceleration columns.
    corners : list[dict] | None
        Corner descriptors (not required for thermal analysis but accepted
        for API consistency).

    Returns
    -------
    dict
        Keys: ``has_tire_data``, ``balance`` (per-lap), ``degradation``,
        ``optimal_window``, ``camber`` (if 12-zone data available).
    """
    result: dict = {
        "has_tire_data": False,
        "balance": [],
        "degradation": {},
        "optimal_window": (80.0, 100.0),
        "camber": [],
    }

    if not resampled_laps:
        return result

    # Pick the first lap to probe available columns
    first_df = next(iter(resampled_laps.values()))
    cols = {pos: _resolve_col(first_df, cands) for pos, cands in _TIRE_TEMP_COLS.items()}

    if not all(cols.values()):
        # No 4-corner tire temp data available
        return result

    result["has_tire_data"] = True
    grip_col = _resolve_col(first_df, _GRIP_PROXY_COLS)

    # Collect per-lap data
    all_temps: list[float] = []
    all_grips: list[float] = []
    lap_temp_records: list[dict] = []

    for lap_num, df in sorted(resampled_laps.items()):
        fl_mean = float(df[cols["fl"]].mean())
        fr_mean = float(df[cols["fr"]].mean())
        rl_mean = float(df[cols["rl"]].mean())
        rr_mean = float(df[cols["rr"]].mean())

        # Balance per lap
        result["balance"].append({
            "lap": lap_num,
            **compute_thermal_balance(fl_mean, fr_mean, rl_mean, rr_mean),
        })

        lap_temp_records.append({
            "lap": lap_num, "fl": fl_mean, "fr": fr_mean,
            "rl": rl_mean, "rr": rr_mean,
        })

        # Collect for optimal-window detection
        all_temps.extend(df[cols["fl"]].dropna().values.tolist())
        if grip_col and grip_col in df.columns:
            all_grips.extend(np.abs(df[grip_col].dropna().values).tolist())

    # Degradation
    result["degradation"] = predict_tire_degradation(lap_temp_records)

    # Optimal window (only if we have grip data)
    if all_temps and all_grips and len(all_temps) == len(all_grips):
        result["optimal_window"] = detect_optimal_window(
            np.array(all_temps), np.array(all_grips),
        )

    # 12-zone camber analysis (check first lap for zone cols)
    zone_i = _resolve_col(first_df, _ZONE_COLS.get("fl_i", []))
    zone_m = _resolve_col(first_df, _ZONE_COLS.get("fl_m", []))
    zone_o = _resolve_col(first_df, _ZONE_COLS.get("fl_o", []))

    if zone_i and zone_m and zone_o:
        for lap_num, df in sorted(resampled_laps.items()):
            result["camber"].append({
                "lap": lap_num,
                "fl": analyze_camber_from_zones(
                    float(df[zone_i].mean()),
                    float(df[zone_m].mean()),
                    float(df[zone_o].mean()),
                ),
            })

    return result
