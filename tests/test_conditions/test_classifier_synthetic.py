"""Day-11 Phase D — classifier synthetic isolation tests.

Test-first per spec §5 (10 rules), §6 (mu_scale lookup), §2 (output
hierarchy). Tests run against mocked weather (no Open-Meteo network)
+ mocked centroid resolution (no gt geojson read).

Coverage matrix:

    9 rule-isolation tests (1, 2, 3, 4, 5, 5b, 6, 7, 8, 9)
    1 rule-priority test (5b > 6)
    4 mu_scale ladder tests (DRY, GREASY-std, GREASY-oilrejection, WET-film)
    1 mu_scale damp ladder
    3 user-override tests (skip-rules, oilrejection-aware, standard fallback)
    1 invalid user_condition raises
    2 fallback tests (API failure, no gt)
    3 schema tests (raw_inputs keys, version, spatial_modifier=None)

= 24 tests, all FAILING until classifier.py is implemented.

§4 P-numbering vs §5 rule-text P-numbering:
    §4: P1=1h precip, P2=6h precip, P3=24h precip, P4=48h precip,
        P5=air temp, P6=solar W/m², P7=cloud %, P8=wind km/h,
        P9=RH %, P10=dew point °C.
    §5 rule text uses P{hours} for precipitation (P1, P6, P24, P48)
        and P5 for air temp. Tests below use §5 rule-text naming in
        names + comments; classifier internals use descriptive
        ``precip_1h`` / ``precip_6h`` / etc. variables.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from telemetry_tool.conditions import (
    SessionInputs,
    WeatherCondition,
    classify_conditions,
)
from telemetry_tool.conditions.open_meteo import (
    OpenMeteoFetchError,
    WeatherFetchResult,
)


# ── Synthetic weather helpers ──────────────────────────────────────────


_WHEN = datetime(2026, 2, 7, 12, 0, tzinfo=timezone.utc)


def _make_weather(
    *,
    precip_hourly: list[float] | None = None,
    daily_precip: list[float] | None = None,
    t_air: float = 20.0,
    w_solar: float = 400.0,
    cloud_pct: float = 50.0,
    wind_kmh: float = 10.0,
    rh_pct: float = 70.0,
    t_dew: float = 15.0,
    wind_dir_deg: float = 180.0,
) -> WeatherFetchResult:
    """Build a 49-entry hourly + 30-entry daily WeatherFetchResult.

    All non-precip fields are broadcast as constants across the hourly
    window (sufficient for rule-isolation; real Open-Meteo varies these
    by hour but the rules only consume session-start values for P5-P10).
    """
    n_hourly = 49
    hourly_arr = precip_hourly if precip_hourly is not None else [0.0] * n_hourly
    daily_arr = daily_precip if daily_precip is not None else [0.0] * 30
    return WeatherFetchResult(
        hourly={
            "hourly": {
                "time": [
                    f"2026-02-{(5 + i // 24):02d}T{(i % 24):02d}:00"
                    for i in range(n_hourly)
                ],
                "temperature_2m": [t_air] * n_hourly,
                "precipitation": hourly_arr,
                "cloudcover": [cloud_pct] * n_hourly,
                "windspeed_10m": [wind_kmh] * n_hourly,
                "winddirection_10m": [wind_dir_deg] * n_hourly,
                "shortwave_radiation": [w_solar] * n_hourly,
                "relative_humidity_2m": [rh_pct] * n_hourly,
                "dewpoint_2m": [t_dew] * n_hourly,
            }
        },
        daily={
            "daily": {
                "time": [f"day{i:02d}" for i in range(30)],
                "precipitation_sum": daily_arr,
            }
        },
        source="api",
    )


def _hourly_array_with(
    p_1h: float = 0.0,
    p_at_hours_ago: dict[int, float] | None = None,
) -> list[float]:
    """Build a 49-entry hourly precipitation array.

    ``p_at_hours_ago = {3: 1.5}`` puts 1.5 mm at index ``-4`` (4th from
    last = 3 hours ago, since the LAST entry is the session-start hour).
    """
    arr = [0.0] * 49
    arr[-1] = p_1h
    if p_at_hours_ago:
        for hours, mm in p_at_hours_ago.items():
            arr[-1 - hours] = mm
    return arr


# ── Fixture: monkeypatch external deps ─────────────────────────────────


@pytest.fixture
def mock_deps(monkeypatch):
    """Patches fetch_weather + resolve_track_centroid for unit testing.

    Returns a (weather_holder, centroid_holder) tuple of dicts; tests
    set ``weather_holder['result']`` and ``centroid_holder['result']``
    before calling classify_conditions.
    """
    weather_holder = {"result": None, "exception": None}
    centroid_holder = {"result": (47.0, 0.0), "exception": None}

    def fake_centroid(track_id):
        if centroid_holder["exception"]:
            raise centroid_holder["exception"]
        return centroid_holder["result"]

    def fake_fetch(lat, lon, when, *, cache_dir=None):
        if weather_holder["exception"]:
            raise weather_holder["exception"]
        if weather_holder["result"] is None:
            raise AssertionError(
                "test must set weather_holder['result'] before classify_conditions"
            )
        return weather_holder["result"]

    monkeypatch.setattr(
        "telemetry_tool.conditions.classifier.resolve_track_centroid",
        fake_centroid,
    )
    monkeypatch.setattr(
        "telemetry_tool.conditions.classifier.fetch_weather",
        fake_fetch,
    )
    return weather_holder, centroid_holder


# ── 10 rule-isolation tests ────────────────────────────────────────────


def test_rule_1_wet_heavy(mock_deps):
    """Rule 1: P1 > 2.0 mm → WET, mu_scale < 0.65 (thick film)."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=2.5),
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "wet"
    assert wc.dominant_factor == "precip_1h_heavy"
    assert wc.mu_scale < 0.65, f"thick-film mu_scale should be < 0.65, got {wc.mu_scale}"
    assert wc.confidence == 0.95
    assert wc.source == "weather"


def test_rule_2_wet(mock_deps):
    """Rule 2: 0.5 < P1 ≤ 2.0 mm → WET, mu_scale = 0.60 (thin film)."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather(precip_hourly=_hourly_array_with(p_1h=0.8))
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "wet"
    assert wc.dominant_factor == "precip_1h"
    assert wc.mu_scale == pytest.approx(0.60, abs=0.001)
    assert wc.confidence == 0.90


def test_rule_3_wet_dew(mock_deps):
    """Rule 3: P6 > 3.0 mm AND P5 ≤ T_dew + 2 → WET (dew-related).

    P6 in §5 rule text = §4 P2 = 6h precipitation total.
    """
    wx_h, _ = mock_deps
    # 6h total = 3.5 mm spread across hours 2-5; P1 = 0 (no current rain).
    # T_air = 7°C, T_dew = 6°C → P5 ≤ T_dew + 2.
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(
            p_1h=0.0,
            p_at_hours_ago={2: 1.0, 3: 1.0, 4: 1.0, 5: 0.5},
        ),
        t_air=7.0,
        t_dew=6.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "wet"
    assert wc.dominant_factor == "wet_dew"
    assert wc.confidence == 0.80


def test_rule_4_damp(mock_deps):
    """Rule 4: P6 > 1.0 mm AND P1 ≤ 0.5 mm → DAMP."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(
            p_1h=0.0,
            p_at_hours_ago={3: 1.5},
        ),
        t_air=15.0,
        t_dew=5.0,  # large gap to avoid Rule 3 / 5
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "damp"
    assert wc.dominant_factor == "precip_6h"
    assert wc.confidence == 0.80


def test_rule_5_damp_dew(mock_deps):
    """Rule 5: P5 ≤ T_dew + 1 AND P1 == 0 → DAMP (dew formation)."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather(
        precip_hourly=[0.0] * 49,  # zero precip everywhere
        t_air=5.5,
        t_dew=5.0,  # T_air ≤ T_dew + 1
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "damp"
    assert wc.dominant_factor == "damp_dew"
    assert wc.confidence == 0.70


def test_rule_5b_oilrejection(mock_deps):
    """Rule 5b: D5 > 14 AND P24 > 1.0 AND P1 < 0.5 → GREASY (oilrejection).

    Long dry spell (D5=18 days) + recent rain in last 24h + dry-ish
    surface now → first-rain-after-long-dry-spell pavement-oil regime.
    """
    wx_h, _ = mock_deps
    # D5: 5 mm 18 days ago
    daily = [0.0] * 11 + [5.0] + [0.0] * 18  # daily[11]=5.0 → 30-1-11=18 days ago
    # P24 = 1.5 mm in last 24h (placed 10h ago)
    # P1 = 0 (dry now)
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={10: 1.5}),
        daily_precip=daily,
        t_air=22.0,  # > 20°C so Rule 5b lookup picks the 0.83 bucket
        t_dew=8.0,
        w_solar=600.0,
        wind_kmh=8.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "greasy"
    assert wc.dominant_factor == "oilrejection"
    assert wc.confidence == 0.85
    assert wc.mu_scale == pytest.approx(0.83, abs=0.001)


def test_rule_5b_takes_precedence_over_rule_6(mock_deps):
    """Both Rule 5b AND Rule 6 fire (P24 > 1, D2 ∈ [2,12], D5 > 14, P1 < 0.5).
    Per spec §5: 5b appears before 6 in evaluation order; 5b wins. The
    oilrejection mu_scale (0.83 at D1=22) is more pessimistic than the
    standard greasy 0.88 — so getting 0.83 confirms 5b fired.

    Rain placed 8h ago (outside 6h window) so Rule 4 (DAMP, P6>1.0) doesn't
    pre-empt — the 6h window is the early-precedence trap.
    """
    wx_h, _ = mock_deps
    daily = [0.0] * 11 + [5.0] + [0.0] * 18  # D5 = 18
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={8: 1.5}),  # D2 ≈ 8
        daily_precip=daily,
        t_air=22.0, t_dew=8.0, w_solar=600.0, wind_kmh=8.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.dominant_factor == "oilrejection"
    assert wc.mu_scale == pytest.approx(0.83, abs=0.001), (
        "Rule 5b should win and produce its lookup (0.83), not Rule 6's 0.88"
    )


def test_rule_6_greasy_recent(mock_deps):
    """Rule 6: P24 > 1.0 AND D2 ∈ [2, 12] → GREASY (recent rain).

    No long dry spell (D5 = None), so Rule 5b doesn't fire; standard
    greasy lookup applies.
    """
    wx_h, _ = mock_deps
    # Rain 8h ago, 1.5 mm. D2 = 8 (cumulative crosses 1.0 mm at h=8).
    # Rain outside 6h window so Rule 4 (P6>1.0) doesn't pre-empt.
    # No daily precip > 3 mm in 30-day window → D5 = None → Rule 5b skipped.
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={8: 1.5}),
        daily_precip=[0.0] * 30,  # no significant rain in 30 days
        t_air=22.0, t_dew=8.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "greasy"
    assert wc.dominant_factor == "greasy_recent"
    assert wc.mu_scale == pytest.approx(0.88, abs=0.001)  # D1 > 20 standard


def test_rule_7_greasy_cold(mock_deps):
    """Rule 7: D1 < 12°C AND P48 > 5 mm → GREASY (cold).

    Avoid earlier rules: P1 = 0, P6 < 1.0, P5 > T_dew+1, no Rule 5b
    conditions, D2 outside [2,12] (rain > 12h ago).
    """
    wx_h, _ = mock_deps
    # P48 total > 5 mm placed > 24h ago; P1=0; P6=0; D2 > 12; daily=0
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={36: 6.0}),
        daily_precip=[0.0] * 30,
        t_air=4.0, t_dew=-2.0,  # cold; T_air > T_dew + 1
        w_solar=50.0, cloud_pct=80.0, wind_kmh=10.0,  # → D1 ≈ 4 + 12·0.05·0.6 - 0.15·10 = 4 + 0.36 - 1.5 = 2.86°C
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "greasy"
    assert wc.dominant_factor == "greasy_cold"
    # D1 ≈ 2.86°C → < 12 → 0.82 (standard greasy < 12 bucket)
    assert wc.mu_scale == pytest.approx(0.82, abs=0.001)


def test_rule_8_greasy_slowdry(mock_deps):
    """Rule 8: D4 < 0.3 AND P48 > 0 → GREASY (slow drying).

    D4 < 0.3 means very slow drying. Avoid Rules 1-7. Cold + humid +
    low solar + no wind → D4 ≈ 0.
    """
    wx_h, _ = mock_deps
    # P48 = 0.5 mm placed 36h ago. P2/P3 = 0 (outside 6h + 24h windows).
    # Need: D1 > 12 (avoid Rule 7); D4 < 0.3; t_air > t_dew+1 (avoid Rule 5).
    # T_track ≈ 15.2°C, T_dew = 13°C (3°C gap, no Rule 5).
    # D4 ≈ 2.2 · 0.05 · 0.01 · 1 = 0.0011 < 0.3 (Rule 8 fires).
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={36: 0.5}),
        daily_precip=[0.0] * 30,
        t_air=15.0, t_dew=13.0, w_solar=50.0, cloud_pct=80.0,
        wind_kmh=1.0, rh_pct=99.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "greasy"
    assert wc.dominant_factor == "greasy_slowdry"
    # D1 ≈ 15.2 → 0.85 (standard greasy 12-20 bucket)
    assert wc.mu_scale == pytest.approx(0.85, abs=0.001)


def test_rule_9_dry_default(mock_deps):
    """Rule 9 (else): no precip, no dew, no slow-dry → DRY."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather(
        precip_hourly=[0.0] * 49,
        daily_precip=[0.0] * 30,
        t_air=25.0, t_dew=10.0,  # well above dew
        w_solar=800.0, cloud_pct=10.0, wind_kmh=8.0, rh_pct=40.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "dry"
    assert wc.dominant_factor == "dry_default"
    # D1 ≈ 25 + 12·0.8·0.95 - 0.15·8 = 25 + 9.12 - 1.2 = 32.92 → > 0.95 mu_scale
    assert wc.mu_scale > 0.95, f"hot+sunny dry should be > 0.95, got {wc.mu_scale}"


# ── mu_scale ladder tests ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "d1_target,expected_min,expected_max",
    [
        (5.0, 0.91, 0.93),       # D1 < 10 → 0.92
        (10.0, 0.97, 1.0),        # boundary → 0.98
        (17.5, 1.0, 1.0),         # mid-range linear interp → close to 1.0
        (30.0, 0.99, 1.01),       # 25-35 plateau → 1.00
        (40.0, 0.97, 0.99),       # 35-45 falloff → 0.98
        (50.0, 0.91, 0.93),       # > 45 → 0.92
    ],
)
def test_mu_scale_dry_ladder(mock_deps, d1_target, expected_min, expected_max):
    """Spec §6 DRY ladder: 5 buckets across D1 range."""
    wx_h, _ = mock_deps
    # Reverse-engineer t_air to get the target D1 at w_solar=0, wind=0:
    # D1 = t_air + 0 - 0 = t_air.
    wx_h["result"] = _make_weather(
        precip_hourly=[0.0] * 49,
        daily_precip=[0.0] * 30,
        t_air=d1_target, t_dew=d1_target - 10.0,  # safely above dew
        w_solar=0.0, wind_kmh=0.0, cloud_pct=0.0, rh_pct=30.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "dry"
    assert expected_min <= wc.mu_scale <= expected_max, (
        f"D1={d1_target}: expected mu_scale ∈ [{expected_min}, {expected_max}], "
        f"got {wc.mu_scale}"
    )


@pytest.mark.parametrize(
    "d1_target,expected_mu",
    [
        (8.0, 0.82),     # < 12
        (16.0, 0.85),    # 12-20
        (25.0, 0.88),    # > 20
    ],
)
def test_mu_scale_greasy_standard_ladder(mock_deps, d1_target, expected_mu):
    """Spec §6 GREASY (standard, Rule 6/7/8) ladder: 3 buckets."""
    wx_h, _ = mock_deps
    # Force Rule 6 fire: P24 > 1.0 mm placed 8h ago (outside 6h to avoid Rule 4),
    # no D5 trigger (no Rule 5b), no Rule 4 (P2=0).
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={8: 1.5}),
        daily_precip=[0.0] * 30,  # no Rule 5b
        t_air=d1_target, t_dew=d1_target - 10.0,
        w_solar=0.0, wind_kmh=0.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "greasy"
    assert wc.dominant_factor == "greasy_recent"
    assert wc.mu_scale == pytest.approx(expected_mu, abs=0.001)


@pytest.mark.parametrize(
    "d1_target,expected_mu",
    [
        (8.0, 0.77),     # < 12 → standard 0.82 - 0.05 = 0.77
        (16.0, 0.80),    # 12-20 → standard 0.85 - 0.05 = 0.80
        (25.0, 0.83),    # > 20 → standard 0.88 - 0.05 = 0.83
    ],
)
def test_mu_scale_greasy_oilrejection_offset_minus_005(mock_deps, d1_target, expected_mu):
    """Spec §6 GREASY-oilrejection: −0.05 vs standard greasy."""
    wx_h, _ = mock_deps
    # Force Rule 5b: D5 > 14, P24 > 1.0, P1 < 0.5
    daily = [0.0] * 11 + [5.0] + [0.0] * 18
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={10: 1.5}),
        daily_precip=daily,
        t_air=d1_target, t_dew=d1_target - 10.0,
        w_solar=0.0, wind_kmh=0.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "greasy"
    assert wc.dominant_factor == "oilrejection"
    assert wc.mu_scale == pytest.approx(expected_mu, abs=0.001)


@pytest.mark.parametrize(
    "d1_target,expected_mu",
    [
        (10.0, 0.70),    # < 15
        (20.0, 0.75),    # 15-25
        (28.0, 0.78),    # > 25
    ],
)
def test_mu_scale_damp_ladder(mock_deps, d1_target, expected_mu):
    """Spec §6 DAMP ladder: 3 buckets."""
    wx_h, _ = mock_deps
    # Force Rule 4: P6 > 1.0, P1 ≤ 0.5
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={3: 1.5}),
        daily_precip=[0.0] * 30,
        t_air=d1_target, t_dew=d1_target - 10.0,  # avoid dew rules
        w_solar=0.0, wind_kmh=0.0,
    )
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "damp"
    assert wc.mu_scale == pytest.approx(expected_mu, abs=0.001)


@pytest.mark.parametrize(
    "p1_value,expected_mu",
    [
        (0.8, 0.60),   # thin film (P1 ≤ 2.0)
        (3.0, 0.55),   # thick film (P1 > 2.0)
    ],
)
def test_mu_scale_wet_film_threshold(mock_deps, p1_value, expected_mu):
    """Spec §6 WET: P1 threshold at 2.0 mm divides thin (0.60) from thick (0.55)."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather(precip_hourly=_hourly_array_with(p_1h=p1_value))
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "wet"
    assert wc.mu_scale == pytest.approx(expected_mu, abs=0.001)


# ── User-override tests ────────────────────────────────────────────────


def test_user_override_dry_skips_rule_evaluation(mock_deps):
    """User says dry → label='dry', source='user', mu_scale from DRY ladder.
    Rules don't fire even with weather suggesting wet."""
    wx_h, _ = mock_deps
    # Heavy rain weather, but user override = "dry"
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=3.0),  # would be Rule 1 WET-heavy
        t_air=20.0, t_dew=5.0,
    )
    si = SessionInputs(started_at_utc=_WHEN, user_condition="dry")
    wc = classify_conditions(si, "ok")
    assert wc.source == "user"
    assert wc.label == "dry"
    assert wc.dominant_factor.startswith("user")
    # D1 ≈ 22.1 → DRY ladder 10-25 interp ≈ 1.012 (well within < 1.02 cap).
    assert 0.98 <= wc.mu_scale <= 1.02


def test_user_override_greasy_uses_oilrejection_when_5b_conditions_met(mock_deps):
    """User says greasy, AND weather matches Rule 5b → oilrejection lookup.

    This is OK_R4's expected path per spec §12 + brief.
    """
    wx_h, _ = mock_deps
    daily = [0.0] * 11 + [5.0] + [0.0] * 18  # D5 = 18 > 14
    wx_h["result"] = _make_weather(
        precip_hourly=_hourly_array_with(p_1h=0.0, p_at_hours_ago={10: 1.5}),
        daily_precip=daily,
        t_air=22.0, t_dew=8.0,
        w_solar=0.0, wind_kmh=0.0,
    )
    si = SessionInputs(started_at_utc=_WHEN, user_condition="greasy")
    wc = classify_conditions(si, "ok")
    assert wc.source == "user"
    assert wc.label == "greasy"
    assert wc.dominant_factor == "oilrejection"
    # D1 = 22 → oilrejection > 20 bucket = 0.83
    assert wc.mu_scale == pytest.approx(0.83, abs=0.001)


def test_user_override_greasy_uses_standard_when_5b_not_met(mock_deps):
    """User says greasy, weather doesn't match Rule 5b → standard greasy lookup."""
    wx_h, _ = mock_deps
    # No long dry spell + no recent rain → Rule 5b NOT triggered.
    wx_h["result"] = _make_weather(
        precip_hourly=[0.0] * 49,
        daily_precip=[0.0] * 30,
        t_air=22.0, t_dew=8.0,
        w_solar=0.0, wind_kmh=0.0,
    )
    si = SessionInputs(started_at_utc=_WHEN, user_condition="greasy")
    wc = classify_conditions(si, "ok")
    assert wc.source == "user"
    assert wc.label == "greasy"
    assert wc.dominant_factor != "oilrejection"
    # D1 = 22 → standard greasy > 20 bucket = 0.88
    assert wc.mu_scale == pytest.approx(0.88, abs=0.001)


def test_user_override_invalid_label_raises(mock_deps):
    """Spec §8: label ∈ {dry, damp, wet, greasy}. Invalid → ValueError."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather()
    si = SessionInputs(started_at_utc=_WHEN, user_condition="very_wet")
    with pytest.raises(ValueError, match="user_condition"):
        classify_conditions(si, "ok")


# ── Fallback tests ─────────────────────────────────────────────────────


def test_api_failure_returns_safe_dry_fallback(mock_deps):
    """Open-Meteo failure → safe-dry per Day-11 brief: source='weather'
    (not ml_fallback — retired), confidence=0.0, label='dry', mu_scale=0.9."""
    wx_h, _ = mock_deps
    wx_h["exception"] = OpenMeteoFetchError("simulated API failure")
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.label == "dry"
    assert wc.mu_scale == pytest.approx(0.9, abs=0.001)
    assert wc.confidence == 0.0
    assert wc.source == "weather"


def test_no_gt_returns_safe_dry_fallback(mock_deps):
    """Track with no gt geojson → safe-dry (same as API failure)."""
    _, centroid_h = mock_deps
    centroid_h["exception"] = FileNotFoundError("no gt for unknown_track")
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "unknown_track")
    assert wc.label == "dry"
    assert wc.mu_scale == pytest.approx(0.9, abs=0.001)
    assert wc.confidence == 0.0


# ── Schema tests ──────────────────────────────────────────────────────


def test_raw_inputs_contains_p1_p10_plus_d1_d5(mock_deps):
    """raw_inputs should expose every §4 P + D key for debugging."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather()  # all defaults
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    expected = {
        # §4 P1-P10 + winddirection_10m
        "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10",
        "winddirection_10m",
        # D1-D5
        "D1", "D2", "D3", "D4", "D5",
    }
    missing = expected - set(wc.raw_inputs.keys())
    assert not missing, f"raw_inputs missing keys: {sorted(missing)}"


def test_classifier_version_is_weather_v1_0(mock_deps):
    """Day-11 ships v1.0 (scalar only)."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather()
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.classifier_version == "weather-v1.0"


def test_spatial_modifier_is_none_on_day_11(mock_deps):
    """Day-11 doesn't ship spatial layer."""
    wx_h, _ = mock_deps
    wx_h["result"] = _make_weather()
    si = SessionInputs(started_at_utc=_WHEN)
    wc = classify_conditions(si, "ok")
    assert wc.spatial_modifier is None
