"""Derived weather metrics D1-D5 (spec §4 derived).

All functions are PURE: they take primitive scalar/list inputs and
return primitive scalar outputs. No I/O, no Open-Meteo coupling. Phase
C wires them up; Phase D consumes them in the classifier rule predicates.

Formulae verbatim from spec §4:

D1 — track temperature estimate (°C)
    T_track = T_air + α·(W_solar/1000)·(1 - 0.5·cloud_fraction) - β·windspeed_kmh
    α = 12.0, β = 0.15

D2 — hours since significant rain (≥ 1.0 mm cumulative)
    Scan hourly precipitation backwards from session-start; return hours
    until cumulative sum ≥ 1.0 mm. 999.0 if none found in 48h window.

D3 — cumulative solar since rain
    Integrate W_solar × (1 - cloud_fraction) over hours from D2 to
    session start; units kWh/m² accumulated.

D4 — drying rate estimate
    drying_rate ∝ max(T_track - T_dew, 0) × (W_solar/1000) × (1 - RH/100)
                  × √(windspeed_kmh)
    Units: simplified Penman-style; treated as a relative index.

D5 — days since last significant rain (> 3.0 mm/day)
    Scan 30-day daily archive backwards; return days until first day
    with precipitation_sum > 3.0 mm. None if window contains no
    significant-rain day (= "dry spell longer than 30 days").

Implementation lands at Phase C; this module is stubs until
``test_derived_metrics.py`` is committed FAILING.
"""
from __future__ import annotations

# Spec §4 D1 coefficients (treat as locked spec for V1).
_D1_ALPHA: float = 12.0
_D1_BETA: float = 0.15

# Spec §4 D2 threshold for "significant rain" (hourly cumulative).
_D2_SIGNIFICANT_RAIN_MM: float = 1.0

# Spec §4 D5 threshold for "significant rain day" (daily total).
_D5_SIGNIFICANT_DAY_MM: float = 3.0

# Cap returned when no rain found in 48h window (spec §4 D2 wording).
_D2_NO_RAIN_SENTINEL: float = 999.0


def compute_d1_track_temp_estimate_c(
    t_air_c: float,
    w_solar_wm2: float,
    cloud_frac: float,
    wind_kmh: float,
) -> float:
    """D1 — Linear surface-temperature model (spec §4)."""
    raise NotImplementedError("Phase C — implement after test_derived_metrics.py FAILS")


def compute_d2_hours_since_significant_rain(hourly_precip_mm: list[float]) -> float:
    """D2 — Backwards scan to ≥ 1.0 mm cumulative threshold (spec §4).

    Args:
        hourly_precip_mm: 48 entries, oldest-first. ``hourly_precip_mm[-1]``
            is the hour ending at session start.
    """
    raise NotImplementedError("Phase C — implement after test_derived_metrics.py FAILS")


def compute_d3_cumulative_solar_since_rain(
    hourly_solar_wm2: list[float],
    hourly_cloud_frac: list[float],
    hours_since_rain: float,
) -> float:
    """D3 — Drying-budget integral (spec §4).

    If ``hours_since_rain >= len(hourly_solar_wm2)`` (no rain in window),
    integrates over the full window.
    """
    raise NotImplementedError("Phase C — implement after test_derived_metrics.py FAILS")


def compute_d4_drying_rate(
    t_track_c: float,
    t_dew_c: float,
    w_solar_wm2: float,
    rh_pct: float,
    wind_kmh: float,
) -> float:
    """D4 — Simplified Penman drying-rate index (spec §4)."""
    raise NotImplementedError("Phase C — implement after test_derived_metrics.py FAILS")


def compute_d5_days_since_significant_rain(daily_precip_mm: list[float]) -> int | None:
    """D5 — Backwards scan over 30-day daily archive (spec §4).

    Args:
        daily_precip_mm: 30 entries, oldest-first. ``daily_precip_mm[-1]``
            is the day of session start.

    Returns:
        Days since last day with precipitation > 3.0 mm, or ``None``
        if the entire 30-day window is below threshold.
    """
    raise NotImplementedError("Phase C — implement after test_derived_metrics.py FAILS")
