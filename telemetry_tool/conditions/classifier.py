"""Scalar conditions classifier (spec §5 + §6 + §8 + §2).

Public API:
    classify_conditions(session_inputs, track_id, *, cache_dir=None)
        → WeatherCondition

Algorithm:
    1. If user_condition is set → source = "user". Compute mu_scale via
       the Section-6 lookup for that label using D1 from fetched weather
       (Rule 5b lookup also applies when user="greasy" + Rule 5b weather
       conditions match per brief). Return WeatherCondition with full
       raw_inputs + rationale citing user override.
    2. Else:
       a. Resolve (lat, lon) from track_id via ``track_centroid``.
       b. fetch_weather(lat, lon, session_start_utc).
       c. Extract P1-P10 + winddirection_10m; compute D1-D5.
       d. Evaluate Rules 1, 2, 3, 4, 5, 5b, 6, 7, 8, 9 in that order;
          first match wins.
       e. Look up mu_scale per Section 6 given (label, D1, dominant_factor).
       f. Return WeatherCondition with source = "weather".
    3. If fetch_weather or track-centroid resolution raises → safe-dry
       fallback per Day-11 brief: source = "weather" (not "ml_fallback"
       — that path is retired), confidence = 0.0, label = "dry",
       mu_scale = 0.9.

Naming convention for precipitation windows:
    §4 names them P1=1h, P2=6h, P3=24h, P4=48h.
    §5 rule text uses P{hours_back} convention: P1=1h, P6=6h, P24=24h,
    P48=48h. The two conventions agree on P1 but diverge on the others.

    Internal code uses descriptive ``precip_1h`` / ``precip_6h`` /
    ``precip_24h`` / ``precip_48h`` to avoid the ambiguity. ``raw_inputs``
    on the output uses §4 P-numbering (P1=1h, P2=6h, P3=24h, P4=48h,
    P5=air temp, P6=solar W/m², P7=cloud %, P8=wind km/h, P9=RH %,
    P10=dew °C) for downstream debugging consistency.
"""
from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from .derived_metrics import (
    _D2_NO_RAIN_SENTINEL,
    compute_d1_track_temp_estimate_c,
    compute_d2_hours_since_significant_rain,
    compute_d3_cumulative_solar_since_rain,
    compute_d4_drying_rate,
    compute_d5_days_since_significant_rain,
)
from .open_meteo import OpenMeteoFetchError, WeatherFetchResult, fetch_weather
from .track_centroid import resolve_track_centroid
from .types import SessionInputs, WeatherCondition

# Spec §8: classifier version pinned per build day.
CLASSIFIER_VERSION: Final[str] = "weather-v1.0"

# Spec §8: user_condition allowed values.
_VALID_USER_CONDITIONS: Final[frozenset[str]] = frozenset(
    {"dry", "damp", "wet", "greasy"}
)

# Day-11 brief safe-dry fallback values when weather API or centroid fails.
_SAFE_DRY_MU_SCALE: Final[float] = 0.9


# ── Public entry point ─────────────────────────────────────────────────


def classify_conditions(
    session_inputs: SessionInputs,
    track_id: str,
    *,
    cache_dir: Path | None = None,
) -> WeatherCondition:
    """Classify the track conditions for one session per spec §5 + §6.

    See module docstring for the full algorithm. Returns a frozen
    WeatherCondition with all 14 §8 fields populated.
    """
    # 0. Validate user_condition if supplied.
    if session_inputs.user_condition is not None:
        if session_inputs.user_condition not in _VALID_USER_CONDITIONS:
            raise ValueError(
                f"user_condition {session_inputs.user_condition!r} not in "
                f"{sorted(_VALID_USER_CONDITIONS)}"
            )

    # 1. Resolve track centroid + fetch weather. Either failure → safe-dry.
    try:
        lat, lon = resolve_track_centroid(track_id)
    except (FileNotFoundError, NotImplementedError) as e:
        return _safe_dry_fallback(reason=f"no gt centroid for {track_id!r}: {e}")
    try:
        wx = fetch_weather(lat, lon, session_inputs.started_at_utc, cache_dir=cache_dir)
    except OpenMeteoFetchError as e:
        return _safe_dry_fallback(reason=f"open-meteo failure: {e}")

    # 2. Extract raw P-inputs + compute derived D-inputs.
    raw = _extract_raw_inputs(wx)
    d1 = compute_d1_track_temp_estimate_c(
        t_air_c=raw["P5"],
        w_solar_wm2=raw["P6"],
        cloud_frac=raw["P7"] / 100.0,
        wind_kmh=raw["P8"],
    )
    hourly_precip = wx.hourly["hourly"]["precipitation"]
    hourly_solar = wx.hourly["hourly"]["shortwave_radiation"]
    hourly_cloud_frac = [c / 100.0 for c in wx.hourly["hourly"]["cloudcover"]]
    d2 = compute_d2_hours_since_significant_rain(hourly_precip)
    d3 = compute_d3_cumulative_solar_since_rain(hourly_solar, hourly_cloud_frac, d2)
    d4 = compute_d4_drying_rate(
        t_track_c=d1,
        t_dew_c=raw["P10"],
        w_solar_wm2=raw["P6"],
        rh_pct=raw["P9"],
        wind_kmh=raw["P8"],
    )
    daily_precip = wx.daily["daily"]["precipitation_sum"]
    d5 = compute_d5_days_since_significant_rain(daily_precip)

    raw["D1"] = d1
    raw["D2"] = d2
    raw["D3"] = d3
    raw["D4"] = d4
    raw["D5"] = d5

    # 3. User override → skip rule evaluation; still use D1 + Rule 5b
    #    eligibility check for greasy mu_scale.
    if session_inputs.user_condition is not None:
        return _user_override(session_inputs.user_condition, raw)

    # 4. Evaluate Rules 1-9 in spec order; first match wins.
    label, dominant_factor, confidence = _evaluate_rules(raw)

    # 5. Section 6 mu_scale lookup.
    mu_scale = _lookup_mu_scale(label, d1=raw["D1"], dominant_factor=dominant_factor,
                                 precip_1h=raw["P1"])

    # 6. Assemble WeatherCondition.
    return WeatherCondition(
        label=label,
        mu_scale=mu_scale,
        confidence=confidence,
        track_temp_estimate_c=raw["D1"],
        water_film_estimate=_water_film_class(raw["P1"]),
        hours_since_rain=(
            raw["D2"] if raw["D2"] < _D2_NO_RAIN_SENTINEL else None
        ),
        days_since_significant_rain=raw["D5"],
        drying_rate_estimate=raw["D4"],
        dominant_factor=dominant_factor,
        rationale=_compose_rationale(label, dominant_factor, raw),
        source="weather",
        spatial_modifier=None,
        raw_inputs=raw,
        classifier_version=CLASSIFIER_VERSION,
    )


# ── Raw-input extraction ──────────────────────────────────────────────


def _extract_raw_inputs(wx: WeatherFetchResult) -> dict:
    """Pull §4 P1-P10 + winddirection_10m from WeatherFetchResult.

    Convention: ``raw[P1]`` = sum of last 1h precipitation (mm).
                ``raw[P2]`` = sum of last 6h precipitation.
                ``raw[P3]`` = sum of last 24h precipitation.
                ``raw[P4]`` = sum of last 48h precipitation.
                ``raw[P5]`` = air temp at session start (°C).
                ``raw[P6]`` = solar radiation at session start (W/m²).
                ``raw[P7]`` = cloud cover at session start (%).
                ``raw[P8]`` = wind speed at session start (km/h).
                ``raw[P9]`` = relative humidity at session start (%).
                ``raw[P10]`` = dew point at session start (°C).
                ``raw[winddirection_10m]`` = wind direction (°) for spatial.
    """
    h = wx.hourly["hourly"]
    precip = h["precipitation"]
    return {
        "P1": float(sum(precip[-1:])) if len(precip) >= 1 else 0.0,
        "P2": float(sum(precip[-6:])) if len(precip) >= 1 else 0.0,
        "P3": float(sum(precip[-24:])) if len(precip) >= 1 else 0.0,
        "P4": float(sum(precip[-48:])) if len(precip) >= 1 else 0.0,
        "P5": float(h["temperature_2m"][-1]),
        "P6": float(h["shortwave_radiation"][-1]),
        "P7": float(h["cloudcover"][-1]),
        "P8": float(h["windspeed_10m"][-1]),
        "P9": float(h["relative_humidity_2m"][-1]),
        "P10": float(h["dewpoint_2m"][-1]),
        "winddirection_10m": float(h["winddirection_10m"][-1]),
    }


# ── Rule evaluation (spec §5) ─────────────────────────────────────────


def _evaluate_rules(raw: dict) -> tuple[str, str, float]:
    """Apply Rules 1-9 + 5b in order; return (label, dominant_factor, confidence).

    §5 P-naming maps to §4 raw_inputs keys:
        P1 (rule text) = raw["P1"]  (1h precip)
        P6 (rule text) = raw["P2"]  (6h precip)
        P24 (rule text) = raw["P3"] (24h precip)
        P48 (rule text) = raw["P4"] (48h precip)
        P5 (rule text) = raw["P5"]  (air temp; same in both)
        T_dew = raw["P10"]
    """
    p1, p6, p24, p48 = raw["P1"], raw["P2"], raw["P3"], raw["P4"]
    p5, t_dew = raw["P5"], raw["P10"]
    d1, d2, d4, d5 = raw["D1"], raw["D2"], raw["D4"], raw["D5"]

    # Rule 1 — WET-heavy (P1 > 2.0 mm)
    if p1 > 2.0:
        return ("wet", "precip_1h_heavy", 0.95)
    # Rule 2 — WET (P1 > 0.5 mm)
    if p1 > 0.5:
        return ("wet", "precip_1h", 0.90)
    # Rule 3 — WET-dew (P6 > 3.0 mm AND P5 ≤ T_dew + 2)
    if p6 > 3.0 and p5 <= t_dew + 2:
        return ("wet", "wet_dew", 0.80)
    # Rule 4 — DAMP (P6 > 1.0 mm AND P1 ≤ 0.5 mm)
    if p6 > 1.0 and p1 <= 0.5:
        return ("damp", "precip_6h", 0.80)
    # Rule 5 — DAMP-dew (P5 ≤ T_dew + 1 AND P1 == 0)
    if p5 <= t_dew + 1 and p1 == 0:
        return ("damp", "damp_dew", 0.70)
    # Rule 5b — GREASY-oilrejection (precedes Rule 6)
    if _rule_5b_conditions_met(p1, p24, d5):
        return ("greasy", "oilrejection", 0.85)
    # Rule 6 — GREASY-recent (P24 > 1.0 mm AND D2 ∈ [2, 12])
    if p24 > 1.0 and 2.0 <= d2 <= 12.0:
        return ("greasy", "greasy_recent", 0.80)
    # Rule 7 — GREASY-cold (D1 < 12°C AND P48 > 5 mm)
    if d1 < 12.0 and p48 > 5.0:
        return ("greasy", "greasy_cold", 0.75)
    # Rule 8 — GREASY-slowdry (D4 < 0.3 AND P48 > 0)
    if d4 < 0.3 and p48 > 0:
        return ("greasy", "greasy_slowdry", 0.65)
    # Rule 9 — DRY (else)
    confidence_dry = max(0.5, min(0.95, d1 / 30.0))
    return ("dry", "dry_default", confidence_dry)


def _rule_5b_conditions_met(precip_1h: float, precip_24h: float, d5: int | None) -> bool:
    """Spec §5 Rule 5b trigger: D5 ≠ None AND D5 > 14 AND P24 > 1.0 AND P1 < 0.5."""
    return (d5 is not None) and (d5 > 14) and (precip_24h > 1.0) and (precip_1h < 0.5)


# ── mu_scale lookup (spec §6) ─────────────────────────────────────────


def _lookup_mu_scale(
    label: str,
    *,
    d1: float,
    dominant_factor: str,
    precip_1h: float,
) -> float:
    """Section 6 lookup tables; takes (label, D1) and the dominant_factor
    string to disambiguate Rule 5b's oilrejection ladder from standard
    greasy."""
    if label == "dry":
        return _dry_ladder(d1)
    if label == "greasy":
        if dominant_factor == "oilrejection":
            return _greasy_oilrejection_ladder(d1)
        return _greasy_standard_ladder(d1)
    if label == "damp":
        return _damp_ladder(d1)
    if label == "wet":
        return _wet_film_lookup(precip_1h)
    raise ValueError(f"unknown label {label!r}")


def _dry_ladder(d1: float) -> float:
    """Spec §6 DRY: piecewise linear across the kart-tire grip window."""
    if d1 < 10.0:
        return 0.92
    if d1 < 25.0:
        return 0.98 + 0.04 * ((d1 - 10.0) / 15.0)  # → 1.02 at D1=25
    if d1 < 35.0:
        return 1.00
    if d1 < 45.0:
        return 1.00 - 0.04 * ((d1 - 35.0) / 10.0)  # → 0.96 at D1=45
    return 0.92


def _greasy_standard_ladder(d1: float) -> float:
    """Spec §6 GREASY (standard, Rule 6/7/8)."""
    if d1 < 12.0:
        return 0.82
    if d1 <= 20.0:
        return 0.85
    return 0.88


def _greasy_oilrejection_ladder(d1: float) -> float:
    """Spec §6 GREASY-oilrejection (Rule 5b): −0.05 vs standard greasy."""
    if d1 < 12.0:
        return 0.77
    if d1 <= 20.0:
        return 0.80
    return 0.83


def _damp_ladder(d1: float) -> float:
    """Spec §6 DAMP."""
    if d1 < 15.0:
        return 0.70
    if d1 <= 25.0:
        return 0.75
    return 0.78


def _wet_film_lookup(precip_1h: float) -> float:
    """Spec §6 WET: thin film (P1 ≤ 2.0) → 0.60; thick film (P1 > 2.0) → 0.55."""
    return 0.55 if precip_1h > 2.0 else 0.60


def _water_film_class(precip_1h: float) -> Literal["none", "thin", "thick"] | None:
    if precip_1h <= 0.0:
        return "none"
    if precip_1h <= 2.0:
        return "thin"
    return "thick"


# ── User-override path ───────────────────────────────────────────────


def _user_override(user_condition: str, raw: dict) -> WeatherCondition:
    """Per brief: user names the label; classifier still computes mu_scale
    via Section 6 with D1 from observed weather + Rule 5b eligibility
    check for user='greasy'."""
    d1 = raw["D1"]
    label = user_condition
    if label == "greasy":
        # Honor Rule 5b lookup when its weather conditions are met,
        # even though the LABEL came from the user.
        if _rule_5b_conditions_met(raw["P1"], raw["P3"], raw["D5"]):
            dominant_factor = "oilrejection"
        else:
            dominant_factor = "user_greasy"
        mu_scale = _lookup_mu_scale(
            "greasy", d1=d1, dominant_factor=dominant_factor, precip_1h=raw["P1"]
        )
    else:
        dominant_factor = f"user_{label}"
        mu_scale = _lookup_mu_scale(
            label, d1=d1, dominant_factor=dominant_factor, precip_1h=raw["P1"]
        )

    return WeatherCondition(
        label=label,  # type: ignore[arg-type]
        mu_scale=mu_scale,
        confidence=1.0,  # user metadata is ground truth
        track_temp_estimate_c=d1,
        water_film_estimate=_water_film_class(raw["P1"]),
        hours_since_rain=(
            raw["D2"] if raw["D2"] < _D2_NO_RAIN_SENTINEL else None
        ),
        days_since_significant_rain=raw["D5"],
        drying_rate_estimate=raw["D4"],
        dominant_factor=dominant_factor,
        rationale=(
            f"User-reported {label}; mu_scale={mu_scale:.2f} from "
            f"{'oilrejection' if dominant_factor == 'oilrejection' else 'standard'} "
            f"{label} ladder at track temp {d1:.1f}°C."
        ),
        source="user",
        spatial_modifier=None,
        raw_inputs=raw,
        classifier_version=CLASSIFIER_VERSION,
    )


# ── Safe-dry fallback (Day-11 brief override of spec §2 ml_fallback) ──


def _safe_dry_fallback(reason: str) -> WeatherCondition:
    """When Open-Meteo or centroid resolution fails: return a safe
    dry-conditions result. Day-11 brief: source='weather' (not
    'ml_fallback' — that path is retired), confidence=0.0."""
    return WeatherCondition(
        label="dry",
        mu_scale=_SAFE_DRY_MU_SCALE,
        confidence=0.0,
        track_temp_estimate_c=None,
        water_film_estimate=None,
        hours_since_rain=None,
        days_since_significant_rain=None,
        drying_rate_estimate=None,
        dominant_factor="safe_dry_fallback",
        rationale=f"Weather lookup unavailable ({reason}); defaulted to dry.",
        source="weather",
        spatial_modifier=None,
        raw_inputs={"fallback_reason": reason},
        classifier_version=CLASSIFIER_VERSION,
    )


# ── Rationale composition ─────────────────────────────────────────────


def _compose_rationale(label: str, dominant_factor: str, raw: dict) -> str:
    p1, p6, p24, p48 = raw["P1"], raw["P2"], raw["P3"], raw["P4"]
    p5, t_dew = raw["P5"], raw["P10"]
    d1, d2, d4, d5 = raw["D1"], raw["D2"], raw["D4"], raw["D5"]
    if dominant_factor == "precip_1h_heavy":
        return f"Heavy precipitation: {p1:.2f} mm in last hour. Hydroplaning risk above 0.5 mm/h."
    if dominant_factor == "precip_1h":
        return f"Wet surface: {p1:.2f} mm in last hour."
    if dominant_factor == "wet_dew":
        return (
            f"Dew-related wet: {p6:.1f} mm 6h precip at {p5:.1f}°C air vs "
            f"{t_dew:.1f}°C dew point."
        )
    if dominant_factor == "precip_6h":
        return f"Damp from recent precipitation: {p6:.1f} mm in last 6h, no current rain."
    if dominant_factor == "damp_dew":
        return (
            f"Dew formation likely: air {p5:.1f}°C at dew point {t_dew:.1f}°C, "
            "no precipitation."
        )
    if dominant_factor == "oilrejection":
        d5_str = str(d5) if d5 is not None else "N/A"
        return (
            f"Oil-rejection: {d5_str}-day dry spell + {p24:.1f} mm in last 24h "
            f"on {d1:.1f}°C pavement. First-rain pavement oils emulsifying."
        )
    if dominant_factor == "greasy_recent":
        d2_str = f"{d2:.0f}h" if d2 < _D2_NO_RAIN_SENTINEL else "N/A"
        return f"Greasy from recent rain: {p24:.1f} mm in last 24h, {d2_str} since."
    if dominant_factor == "greasy_cold":
        return f"Greasy cold: {p48:.1f} mm in last 48h, track {d1:.1f}°C (below cold threshold)."
    if dominant_factor == "greasy_slowdry":
        return f"Slow drying: D4 index {d4:.2f}, {p48:.1f} mm in last 48h still drying."
    if dominant_factor == "dry_default":
        return f"Dry conditions: track {d1:.1f}°C, no significant precipitation in 48h window."
    return f"Classified as {label}."
