"""
pace_estimator.py
-----------------
Two-tier weather-pace lap time estimator.

Tier 1 (physics): Uses wet_physics grip scaling + meteo track conditions.
Tier 2 (data-driven): Linear model from driver's session history (5+ sessions).
Blended output when both available.

Public API
~~~~~~~~~~
``estimate_physics_lap_time(weather, dry_reference_s)``
``estimate_data_driven_lap_time(conn, track_id, driver_id, weather)``
``estimate_pace(conn, track_id, driver_id, weather)``
``estimate_weather_lap_delta(weather, track_id, driver_id, base_time, conn)``
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DATA_WEIGHT = 0.7
_PHYSICS_WEIGHT = 0.3


def estimate_physics_lap_time(
    weather: dict[str, Any],
    dry_reference_s: Optional[float] = None,
) -> dict[str, Any]:
    """
    Tier 1: Physics-based lap time estimate.
    Formula: estimated = dry_reference / grip_factor
    """
    if dry_reference_s is None or not math.isfinite(dry_reference_s):
        return {"error": "No dry reference lap time available", "tier": "physics"}

    try:
        from meteo_service import estimate_track_conditions
        from wet_physics import get_grip_factor
    except ImportError as e:
        return {"error": f"Missing module: {e}", "tier": "physics"}

    conditions = estimate_track_conditions(weather)
    if "error" in conditions:
        return {"error": conditions["error"], "tier": "physics"}

    track_state = conditions.get("track_state", "dry")
    grip = get_grip_factor(track_state)

    estimated = dry_reference_s / grip if grip > 0 else dry_reference_s
    delta = estimated - dry_reference_s
    delta_pct = (delta / dry_reference_s) * 100 if dry_reference_s > 0 else 0

    return {
        "estimated_s": round(estimated, 3),
        "delta_s": round(delta, 3),
        "delta_pct": round(delta_pct, 2),
        "grip_factor": grip,
        "track_state": track_state,
        "grip_level": conditions.get("grip_level", "unknown"),
        "tier": "physics",
    }


def _get_dry_reference(conn, track_id, driver_id):
    """Get the best dry lap time for a driver on a track."""
    row = conn.execute(
        "SELECT MIN(s.best_lap_time_s) as best "
        "FROM sessions s "
        "WHERE s.track_id = :tid AND s.driver_id = :did "
        "AND s.best_lap_time_s IS NOT NULL",
        {"tid": track_id, "did": driver_id},
    ).fetchone()
    if row and row["best"] is not None:
        return float(row["best"])
    return None


def _get_weather_sessions(conn, track_id, driver_id):
    rows = conn.execute(
        """SELECT sw.air_temp_c, sw.humidity_pct, sw.wind_speed_mps,
                  s.best_lap_time_s, s.session_date
           FROM session_weather sw
           JOIN sessions s ON sw.session_id = s.session_id
           WHERE s.track_id = :tid AND s.driver_id = :did
             AND s.best_lap_time_s IS NOT NULL
           ORDER BY s.session_date""",
        {"tid": track_id, "did": driver_id},
    ).fetchall()
    return [dict(r) for r in rows]


def estimate_data_driven_lap_time(conn, track_id, driver_id, weather):
    """Tier 2: Data-driven pace estimate. Returns dict or None if <5 sessions."""
    sessions = _get_weather_sessions(conn, track_id, driver_id)
    if len(sessions) < 5:
        return None

    try:
        from weather_correlation import compute_weather_pace_correlation
    except ImportError:
        return None

    result = compute_weather_pace_correlation(sessions)
    correlations = result.get("correlations", {})

    import numpy as np
    paces = np.array([s["best_lap_time_s"] for s in sessions])
    mean_pace = float(np.mean(paces))
    std_pace = float(np.std(paces, ddof=1)) if len(paces) > 1 else 0

    predicted_delta = 0.0
    for var_key in ("air_temp_c", "humidity_pct", "wind_speed_mps"):
        corr_info = correlations.get(var_key, {})
        r = corr_info.get("r")
        if r is None:
            continue
        vals = [s.get(var_key) for s in sessions if s.get(var_key) is not None]
        if not vals:
            continue
        arr = np.array(vals, dtype=float)
        mean_x = float(np.mean(arr))
        std_x = float(np.std(arr, ddof=1))
        if std_x < 1e-9:
            continue
        current_x = weather.get(var_key)
        if current_x is None:
            continue
        predicted_delta += r * (std_pace / std_x) * (float(current_x) - mean_x)

    estimated = mean_pace + predicted_delta
    delta = estimated - min(s["best_lap_time_s"] for s in sessions)

    return {
        "estimated_s": round(estimated, 3),
        "delta_s": round(delta, 3),
        "n_sessions": len(sessions),
        "tier": "data",
    }


def estimate_pace(conn, track_id, driver_id, weather):
    """Full two-tier blended pace estimate."""
    dry_ref = _get_dry_reference(conn, track_id, driver_id)
    physics = estimate_physics_lap_time(weather, dry_reference_s=dry_ref)
    data = estimate_data_driven_lap_time(conn, track_id, driver_id, weather)

    if data and "estimated_s" in data and "estimated_s" in physics:
        blended = _DATA_WEIGHT * data["estimated_s"] + _PHYSICS_WEIGHT * physics["estimated_s"]
        tier = "physics+data"
        confidence = min(0.95, 0.5 + data["n_sessions"] * 0.05)
        components = {
            "physics_estimate_s": physics["estimated_s"],
            "data_estimate_s": data["estimated_s"],
            "blend_weight_data": _DATA_WEIGHT,
        }
    elif "estimated_s" in physics:
        blended = physics["estimated_s"]
        tier = "physics"
        confidence = 0.5
        components = {"physics_estimate_s": physics["estimated_s"]}
    else:
        return {
            "weather": weather,
            "estimate": {"error": physics.get("error", "No estimate available"), "tier": "none"},
            "context": {},
        }

    delta = blended - dry_ref if dry_ref else 0
    delta_pct = (delta / dry_ref * 100) if dry_ref and dry_ref > 0 else 0

    optimal = None
    if data and data.get("n_sessions", 0) >= 5:
        try:
            from weather_correlation import compute_optimal_conditions
            sessions = _get_weather_sessions(conn, track_id, driver_id)
            optimal = compute_optimal_conditions(sessions)
        except ImportError:
            pass

    return {
        "weather": weather,
        "estimate": {
            "expected_lap_time_s": round(blended, 3),
            "delta_vs_dry_s": round(delta, 3),
            "delta_pct": round(delta_pct, 2),
            "tier": tier,
            "confidence": round(confidence, 2),
            "grip_factor": physics.get("grip_factor", 1.0),
            "components": components,
        },
        "context": {
            "dry_reference_s": round(dry_ref, 3) if dry_ref else None,
            "n_weather_sessions": data["n_sessions"] if data else 0,
            "optimal_conditions": optimal,
        },
    }
