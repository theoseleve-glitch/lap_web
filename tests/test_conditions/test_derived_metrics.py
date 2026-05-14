"""Day-11 Phase C — derived metrics D1-D5 tests.

Committed FAILING per test-first discipline: derived_metrics.py stubs
raise NotImplementedError at this point.

Spec formulae (§4):

    D1: T_track = T_air + α·(W/1000)·(1 - 0.5·cloud_frac) - β·wind_kmh
        α = 12.0, β = 0.15
    D2: backwards scan; cumulative ≥ 1.0 mm; 999.0 if none in 48h
    D3: integrate W_solar·(1 - cloud) over last `hours_since_rain` hours,
        return kWh/m²
    D4: ∝ max(T_track - T_dew, 0) · (W/1000) · (1 - RH/100) · √wind_kmh
    D5: 30-day daily archive; days until > 3.0 mm/day; None if none
"""
from __future__ import annotations

import math

import pytest

from telemetry_tool.conditions.derived_metrics import (
    compute_d1_track_temp_estimate_c,
    compute_d2_hours_since_significant_rain,
    compute_d3_cumulative_solar_since_rain,
    compute_d4_drying_rate,
    compute_d5_days_since_significant_rain,
)


# ── D1 — track temperature estimate ────────────────────────────────────


def test_d1_hot_sunny_lifts_above_air_temp():
    """Spec example: hot sunny day. T_air 30°C, 900 W/m² solar, 10% cloud,
    5 km/h wind → T_track ≈ 39.5°C (~10°C above air per Pirelli/F1 sources)."""
    t = compute_d1_track_temp_estimate_c(t_air_c=30.0, w_solar_wm2=900.0,
                                          cloud_frac=0.1, wind_kmh=5.0)
    # 30 + 12·(0.9)·(0.95) - 0.15·5 = 30 + 10.26 - 0.75 = 39.51
    assert t == pytest.approx(39.51, abs=0.05)


def test_d1_cold_cloudy_minimal_lift_or_drop():
    """Cold cloudy day. T_air 5°C, 100 W/m² solar, 90% cloud, 20 km/h wind.
    Solar lift is suppressed by cloud; wind cooling dominates → T_track
    below T_air."""
    t = compute_d1_track_temp_estimate_c(t_air_c=5.0, w_solar_wm2=100.0,
                                          cloud_frac=0.9, wind_kmh=20.0)
    # 5 + 12·(0.1)·(0.55) - 0.15·20 = 5 + 0.66 - 3.0 = 2.66
    assert t == pytest.approx(2.66, abs=0.05)


def test_d1_no_sun_no_wind_track_equals_air():
    """Pathological: zero solar, zero cloud (vacuous), zero wind. Formula
    reduces to T_track = T_air."""
    t = compute_d1_track_temp_estimate_c(t_air_c=20.0, w_solar_wm2=0.0,
                                          cloud_frac=0.0, wind_kmh=0.0)
    assert t == pytest.approx(20.0, abs=1e-6)


def test_d1_full_cloud_kills_solar_lift():
    """100% cloud → (1 - 0.5·1.0) = 0.5 attenuation of solar lift."""
    # Compare full-cloud vs no-cloud at same air/solar/wind:
    t_clear = compute_d1_track_temp_estimate_c(t_air_c=20.0, w_solar_wm2=500.0,
                                                cloud_frac=0.0, wind_kmh=0.0)
    t_cloudy = compute_d1_track_temp_estimate_c(t_air_c=20.0, w_solar_wm2=500.0,
                                                 cloud_frac=1.0, wind_kmh=0.0)
    # clear: 20 + 12·0.5·1.0 = 26.0
    # cloudy: 20 + 12·0.5·0.5 = 23.0
    # cloudy lift is exactly half of clear lift.
    assert t_clear == pytest.approx(26.0, abs=0.01)
    assert t_cloudy == pytest.approx(23.0, abs=0.01)


# ── D2 — hours since significant rain ──────────────────────────────────


def test_d2_no_rain_in_window_returns_sentinel():
    """Spec sentinel: 999.0 when no rain in 48h window."""
    result = compute_d2_hours_since_significant_rain([0.0] * 48)
    assert result == pytest.approx(999.0)


def test_d2_rain_in_current_hour_returns_zero():
    """Rain happening NOW (last hourly entry) → 0 hours since rain."""
    precip = [0.0] * 47 + [1.5]  # 48 entries
    result = compute_d2_hours_since_significant_rain(precip)
    assert result == pytest.approx(0.0)


def test_d2_cumulative_threshold_crosses_at_h17():
    """3 hours of 0.4 mm drizzle, 14 hours ago → cumulative reaches 1.2 mm
    at h=17 backwards-index, so D2 = 17."""
    precip = [0.0] * 30 + [0.4, 0.4, 0.4] + [0.0] * 15  # 48 entries
    result = compute_d2_hours_since_significant_rain(precip)
    # Backwards scan: h=0..14 cum=0; h=15: precip[32]=0.4 cum=0.4; h=16: cum=0.8;
    # h=17: precip[30]=0.4 cum=1.2 ≥ 1.0 → return 17.
    assert result == pytest.approx(17.0)


def test_d2_exactly_one_mm_one_hour_ago():
    """1.0 mm exactly 1 hour ago → D2 = 1."""
    precip = [0.0] * 46 + [1.0, 0.0]  # 48 entries
    result = compute_d2_hours_since_significant_rain(precip)
    # h=0: cum=0; h=1: cum=1.0 ≥ 1.0 → return 1.
    assert result == pytest.approx(1.0)


# ── D3 — cumulative solar since rain ──────────────────────────────────


def test_d3_constant_solar_clear_sky_5h_window():
    """5 hours of 400 W/m² clear sky → 5·400/1000 = 2.0 kWh/m²."""
    solar = [400.0] * 48
    cloud = [0.0] * 48
    result = compute_d3_cumulative_solar_since_rain(solar, cloud, hours_since_rain=5.0)
    assert result == pytest.approx(2.0, abs=0.01)


def test_d3_overcast_halves_effective_solar():
    """50% cloud → solar contribution halved by (1 - cloud)."""
    solar = [400.0] * 48
    cloud = [0.5] * 48
    result = compute_d3_cumulative_solar_since_rain(solar, cloud, hours_since_rain=10.0)
    # 10·400·0.5/1000 = 2.0
    assert result == pytest.approx(2.0, abs=0.01)


def test_d3_sentinel_hours_uses_full_window():
    """If hours_since_rain == 999 (sentinel) → integrate whole 48h window."""
    solar = [800.0] * 48
    cloud = [0.0] * 48
    result = compute_d3_cumulative_solar_since_rain(solar, cloud, hours_since_rain=999.0)
    # All 48 entries summed: 48·800·1.0/1000 = 38.4
    assert result == pytest.approx(38.4, abs=0.01)


def test_d3_zero_hours_returns_zero():
    """Rain in current hour → hours_since_rain=0 → integral over 0 hours = 0."""
    solar = [400.0] * 48
    cloud = [0.0] * 48
    result = compute_d3_cumulative_solar_since_rain(solar, cloud, hours_since_rain=0.0)
    assert result == pytest.approx(0.0, abs=0.01)


# ── D4 — drying rate (Penman-style index) ─────────────────────────────


def test_d4_hot_dry_sunny_windy_high_drying():
    """T_track 30, T_dew 5, W 800, RH 30%, wind 20 → high drying."""
    d4 = compute_d4_drying_rate(t_track_c=30.0, t_dew_c=5.0, w_solar_wm2=800.0,
                                 rh_pct=30.0, wind_kmh=20.0)
    # 25 · 0.8 · 0.7 · √20 = 25·0.8·0.7·4.4721 ≈ 62.61
    assert d4 == pytest.approx(62.61, abs=0.5)


def test_d4_cold_humid_low_drying_under_threshold():
    """Cold humid: T_track 5, T_dew 4, W 100, RH 95%, wind 2 → near zero,
    well under Rule 8's < 0.3 threshold."""
    d4 = compute_d4_drying_rate(t_track_c=5.0, t_dew_c=4.0, w_solar_wm2=100.0,
                                 rh_pct=95.0, wind_kmh=2.0)
    # 1 · 0.1 · 0.05 · √2 = 0.0071
    assert d4 == pytest.approx(0.0071, abs=1e-3)
    assert d4 < 0.3  # Rule 8 fires


def test_d4_track_below_dew_clamps_to_zero():
    """Track temp below dew point → physically impossible to dry → 0."""
    d4 = compute_d4_drying_rate(t_track_c=5.0, t_dew_c=6.0, w_solar_wm2=100.0,
                                 rh_pct=99.0, wind_kmh=2.0)
    assert d4 == pytest.approx(0.0, abs=1e-9)


def test_d4_zero_wind_factor_uses_sqrt_zero():
    """√0 = 0 → D4 = 0 when wind is dead."""
    d4 = compute_d4_drying_rate(t_track_c=30.0, t_dew_c=5.0, w_solar_wm2=800.0,
                                 rh_pct=30.0, wind_kmh=0.0)
    assert d4 == pytest.approx(0.0, abs=1e-9)


# ── D5 — days since last significant rain ─────────────────────────────


def test_d5_no_rain_in_30_days_returns_none():
    """Empty 30-day window → None (the "dry spell longer than 30 days" case)."""
    daily = [0.0] * 30
    result = compute_d5_days_since_significant_rain(daily)
    assert result is None


def test_d5_rain_today_returns_zero():
    """daily[-1] = the day of session start. > 3 mm there → 0 days since."""
    daily = [0.0] * 29 + [5.0]
    result = compute_d5_days_since_significant_rain(daily)
    assert result == 0


def test_d5_rain_9_days_ago():
    """daily[20] > 3 mm; window length 30; days_since = 29 - 20 = 9."""
    daily = [0.0] * 20 + [5.0] + [0.0] * 9
    result = compute_d5_days_since_significant_rain(daily)
    assert result == 9


def test_d5_below_threshold_drizzle_does_not_count():
    """2 mm < 3 mm threshold → no day passes → None."""
    daily = [2.0] * 30
    result = compute_d5_days_since_significant_rain(daily)
    assert result is None


def test_d5_oil_rejection_trigger_window_14_days():
    """Spec Rule 5b: D5 > 14 (long dry spell). Test a 14-day exactly +
    a 15-day case to bracket the boundary."""
    # Rain exactly 14 days ago: not > 14, so Rule 5b would NOT fire.
    daily_14 = [0.0] * 15 + [5.0] + [0.0] * 14
    result_14 = compute_d5_days_since_significant_rain(daily_14)
    assert result_14 == 14

    # Rain 15 days ago: > 14, so Rule 5b WOULD fire.
    daily_15 = [0.0] * 14 + [5.0] + [0.0] * 15
    result_15 = compute_d5_days_since_significant_rain(daily_15)
    assert result_15 == 15


def test_d5_finds_most_recent_significant_rain():
    """If multiple days exceed threshold, return the MOST RECENT (smallest D5)."""
    # Heavy rain 25 days ago AND 5 days ago. Return 5.
    daily = [0.0] * 5 + [10.0] + [0.0] * 19 + [5.0] + [0.0] * 4
    result = compute_d5_days_since_significant_rain(daily)
    assert result == 4
