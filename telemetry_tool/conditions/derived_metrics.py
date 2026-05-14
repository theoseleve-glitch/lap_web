"""Derived weather metrics D1-D5 (spec §4 derived).

All functions are PURE: they take primitive scalar/list inputs and
return primitive scalar outputs. No I/O, no Open-Meteo coupling. Phase
D consumes them in the classifier rule predicates.

Formulae verbatim from spec §4:

D1 — track temperature estimate (°C)
    T_track = T_air + α·(W_solar/1000)·(1 - 0.5·cloud_fraction) - β·windspeed_kmh
    α = 12.0, β = 0.15

D2 — hours since significant rain (≥ 1.0 mm cumulative)
    Scan hourly precipitation backwards from session-start; return hours
    until cumulative sum ≥ 1.0 mm. 999.0 if none found in 48h window.

D3 — cumulative solar since rain
    Integrate W_solar × (1 - cloud_fraction) over the last
    ``hours_since_rain`` hours; result in kWh/m².

D4 — drying rate estimate
    drying_rate ∝ max(T_track - T_dew, 0) × (W_solar/1000) × (1 - RH/100)
                  × √(windspeed_kmh)
    Simplified Penman-style index; threshold ≈ 0.3 fires Rule 8.

D5 — days since last significant rain (> 3.0 mm/day)
    Scan 30-day daily archive backwards; return days until the FIRST
    (= most recent) day with precipitation_sum > 3.0 mm. ``None`` if
    no day in the window passes the threshold.
"""
from __future__ import annotations

import math

# Spec §4 coefficients — treat as locked for V1 (driver-feedback
# calibration in V1.5 may retune).
_D1_ALPHA: float = 12.0
_D1_BETA: float = 0.15
_D2_SIGNIFICANT_RAIN_MM: float = 1.0
_D5_SIGNIFICANT_DAY_MM: float = 3.0
_D2_NO_RAIN_SENTINEL: float = 999.0


def compute_d1_track_temp_estimate_c(
    t_air_c: float,
    w_solar_wm2: float,
    cloud_frac: float,
    wind_kmh: float,
) -> float:
    """D1 — Linear surface-temperature model (spec §4)."""
    solar_lift = _D1_ALPHA * (w_solar_wm2 / 1000.0) * (1.0 - 0.5 * cloud_frac)
    wind_cooling = _D1_BETA * wind_kmh
    return t_air_c + solar_lift - wind_cooling


def compute_d2_hours_since_significant_rain(hourly_precip_mm: list[float]) -> float:
    """D2 — Backwards scan to ≥ 1.0 mm cumulative threshold (spec §4).

    Returns the number of hours (counted from the most recent entry
    backwards) at which cumulative precipitation first reaches 1.0 mm.
    ``999.0`` if the entire window is below threshold.

    Counting convention: h=0 means the most recent hour's precipitation
    alone meets the threshold; h=1 means the cumulative of (most-recent
    + previous) crosses 1.0 mm; etc.
    """
    cumulative = 0.0
    n = len(hourly_precip_mm)
    for h in range(n):
        cumulative += hourly_precip_mm[n - 1 - h]
        if cumulative >= _D2_SIGNIFICANT_RAIN_MM:
            return float(h)
    return _D2_NO_RAIN_SENTINEL


def compute_d3_cumulative_solar_since_rain(
    hourly_solar_wm2: list[float],
    hourly_cloud_frac: list[float],
    hours_since_rain: float,
) -> float:
    """D3 — Drying-budget integral (spec §4); returns kWh/m².

    Integrates ``W_solar × (1 - cloud_fraction)`` over the last
    ``hours_since_rain`` hours. Sum is in Wh/m² (each hourly W/m² value
    times one hour), divided by 1000 to yield kWh/m².

    If ``hours_since_rain`` exceeds the available hourly window (e.g.,
    the sentinel 999.0 from D2 when no rain found), the entire window
    is integrated.

    If ``hours_since_rain == 0`` (rain currently happening), the integral
    over a zero-width interval is 0.
    """
    n = len(hourly_solar_wm2)
    # Clamp into [0, n]; honors the sentinel and the rain-now case.
    h = min(int(hours_since_rain), n)
    if h <= 0:
        return 0.0
    total_wh_m2 = 0.0
    for i in range(h):
        idx = n - 1 - i
        total_wh_m2 += hourly_solar_wm2[idx] * (1.0 - hourly_cloud_frac[idx])
    return total_wh_m2 / 1000.0


def compute_d4_drying_rate(
    t_track_c: float,
    t_dew_c: float,
    w_solar_wm2: float,
    rh_pct: float,
    wind_kmh: float,
) -> float:
    """D4 — Simplified Penman-style drying-rate index (spec §4).

    Four factors multiplied:
        max(T_track - T_dew, 0)   — surface above dew point can dry; clamp at 0
        W_solar / 1000            — solar energy in kW/m²
        1 - RH/100                — atmospheric drying capacity
        √(wind_kmh)               — wind-driven evaporation enhancement

    Returns a relative-units index. Spec Rule 8 fires when D4 < 0.3.
    """
    temp_factor = max(t_track_c - t_dew_c, 0.0)
    solar_factor = w_solar_wm2 / 1000.0
    rh_factor = max(1.0 - rh_pct / 100.0, 0.0)
    wind_factor = math.sqrt(max(wind_kmh, 0.0))
    return temp_factor * solar_factor * rh_factor * wind_factor


def compute_d5_days_since_significant_rain(daily_precip_mm: list[float]) -> int | None:
    """D5 — Backwards scan over the 30-day daily archive (spec §4).

    Returns the number of days from session-start back to the most
    recent day with precipitation_sum > 3.0 mm. The day-of-session-start
    itself is index ``n-1``; a hit there returns 0.

    Returns ``None`` when no day in the window exceeds the threshold
    (i.e., the dry-spell is longer than the window itself — Rule 5b
    cannot fire).
    """
    n = len(daily_precip_mm)
    for i in range(n - 1, -1, -1):
        if daily_precip_mm[i] > _D5_SIGNIFICANT_DAY_MM:
            return n - 1 - i
    return None
