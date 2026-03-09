"""Fuel strategy module for motorsport telemetry.

Provides fuel-corrected pace, consumption statistics, remaining-fuel
prediction, and fuel-saving opportunity detection.  Designed for
endurance / stint-based racing where fuel weight affects lap time.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Fuel-corrected pace
# ---------------------------------------------------------------------------

def compute_fuel_corrected_pace(
    lap_times: list[float],
    fuel_levels: list[float],
    fuel_weight_factor: float = 0.035,
) -> list[float]:
    """Normalise lap times to remove the effect of changing fuel load.

    A lighter car is inherently faster.  This function adds back the time
    a driver *would* have lost had they been at maximum fuel.

    ``corrected = raw + fuel_weight_factor * (max_fuel - current_fuel)``

    Parameters
    ----------
    lap_times : list[float]
        Raw lap times in seconds.
    fuel_levels : list[float]
        Fuel remaining at the *start* of each lap (kg).
    fuel_weight_factor : float
        Seconds per lap per kg of fuel. Default 0.035 s/kg.

    Returns
    -------
    list[float]
        Fuel-corrected lap times (normalised to max fuel level).
    """
    if not lap_times or not fuel_levels:
        return []

    n = min(len(lap_times), len(fuel_levels))
    lt = np.array(lap_times[:n], dtype=float)
    fl = np.array(fuel_levels[:n], dtype=float)

    valid = np.isfinite(lt) & np.isfinite(fl)
    if valid.sum() == 0:
        return list(lt)

    max_fuel = float(np.nanmax(fl))
    corrected = lt.copy()
    corrected[valid] = lt[valid] + fuel_weight_factor * (max_fuel - fl[valid])

    return [round(float(t), 4) for t in corrected]


# ---------------------------------------------------------------------------
# Fuel remaining prediction
# ---------------------------------------------------------------------------

def predict_fuel_remaining(
    fuel_history: list[float],
    target_laps: int,
) -> float:
    """Linearly extrapolate fuel consumption to predict remaining fuel.

    Parameters
    ----------
    fuel_history : list[float]
        Fuel level at the start of each completed lap.
    target_laps : int
        Number of future laps to predict for.

    Returns
    -------
    float
        Predicted fuel remaining after *target_laps* additional laps.
        Can be negative (meaning the car would run out).
    """
    if not fuel_history or len(fuel_history) < 2:
        return 0.0

    arr = np.array(fuel_history, dtype=float)
    valid = np.isfinite(arr)
    if valid.sum() < 2:
        return 0.0

    arr = arr[valid]
    laps = np.arange(len(arr), dtype=float)
    coeffs = np.polyfit(laps, arr, 1)
    slope = coeffs[0]  # fuel change per lap (should be negative)

    current = float(arr[-1])
    predicted = current + slope * target_laps
    return round(float(predicted), 3)


# ---------------------------------------------------------------------------
# Consumption statistics
# ---------------------------------------------------------------------------

def compute_consumption_stats(fuel_levels: list[float]) -> dict:
    """Compute fuel consumption statistics from per-lap fuel levels.

    Parameters
    ----------
    fuel_levels : list[float]
        Fuel remaining at the start of each lap (kg).

    Returns
    -------
    dict
        ``total_consumed``, ``avg_per_lap``, ``min_per_lap``, ``max_per_lap``,
        ``variance``, ``laps_remaining`` (at current average rate).
    """
    if not fuel_levels or len(fuel_levels) < 2:
        current = fuel_levels[0] if fuel_levels else 0.0
        return {
            "total_consumed": 0.0,
            "avg_per_lap": 0.0,
            "min_per_lap": 0.0,
            "max_per_lap": 0.0,
            "variance": 0.0,
            "laps_remaining": 0.0,
        }

    arr = np.array(fuel_levels, dtype=float)
    valid = np.isfinite(arr)
    arr = arr[valid]

    if len(arr) < 2:
        return {
            "total_consumed": 0.0,
            "avg_per_lap": 0.0,
            "min_per_lap": 0.0,
            "max_per_lap": 0.0,
            "variance": 0.0,
            "laps_remaining": 0.0,
        }

    # Per-lap consumption (positive values = fuel used)
    per_lap = np.diff(arr) * -1.0  # negate because fuel decreases
    # Clamp negatives (refuelling or sensor glitch) to zero
    per_lap = np.where(per_lap >= 0, per_lap, 0.0)

    total_consumed = float(arr[0] - arr[-1])
    avg = float(per_lap.mean()) if len(per_lap) > 0 else 0.0

    laps_remaining = float(arr[-1] / avg) if avg > 0 else 0.0

    return {
        "total_consumed": round(max(total_consumed, 0.0), 3),
        "avg_per_lap": round(avg, 3),
        "min_per_lap": round(float(per_lap.min()), 3) if len(per_lap) > 0 else 0.0,
        "max_per_lap": round(float(per_lap.max()), 3) if len(per_lap) > 0 else 0.0,
        "variance": round(float(per_lap.var()), 4) if len(per_lap) > 0 else 0.0,
        "laps_remaining": round(laps_remaining, 1),
    }


# ---------------------------------------------------------------------------
# Fuel-saving opportunity detection
# ---------------------------------------------------------------------------

def detect_fuel_saving_opportunities(
    lap_times: list[float],
    fuel_per_lap: list[float],
    threshold_factor: float = 1.15,
) -> list[dict]:
    """Identify laps with excessive fuel use that didn't gain pace.

    A lap is flagged when its fuel consumption is more than
    ``threshold_factor`` times the average AND its lap time is not
    faster than average.

    Parameters
    ----------
    lap_times : list[float]
        Lap times in seconds.
    fuel_per_lap : list[float]
        Fuel consumed during each lap (kg).
    threshold_factor : float
        Multiplier above average consumption to flag (default 1.15 = 15%).

    Returns
    -------
    list[dict]
        ``{lap, excess_fuel, pace_delta}`` for each flagged lap.
        ``excess_fuel`` = consumption - average.
        ``pace_delta`` = lap_time - average_time (positive = slower).
    """
    if not lap_times or not fuel_per_lap:
        return []

    n = min(len(lap_times), len(fuel_per_lap))
    lt = np.array(lap_times[:n], dtype=float)
    fp = np.array(fuel_per_lap[:n], dtype=float)

    valid = np.isfinite(lt) & np.isfinite(fp)
    if valid.sum() < 2:
        return []

    avg_fuel = float(fp[valid].mean())
    avg_time = float(lt[valid].mean())
    fuel_threshold = avg_fuel * threshold_factor

    opportunities: list[dict] = []
    for i in range(n):
        if not valid[i]:
            continue
        if fp[i] > fuel_threshold and lt[i] >= avg_time:
            opportunities.append({
                "lap": i + 1,
                "excess_fuel": round(float(fp[i] - avg_fuel), 3),
                "pace_delta": round(float(lt[i] - avg_time), 3),
            })

    return opportunities


# ---------------------------------------------------------------------------
# Session-level master function
# ---------------------------------------------------------------------------

def analyze_fuel_session(
    lap_times: list[float],
    fuel_levels: list[float],
    fuel_weight_factor: float = 0.035,
) -> dict:
    """Run all fuel analyses for a session.

    Parameters
    ----------
    lap_times : list[float]
        Lap times in seconds.
    fuel_levels : list[float]
        Fuel remaining at the start of each lap (kg).
    fuel_weight_factor : float
        Seconds per lap per kg of fuel (default 0.035).

    Returns
    -------
    dict
        ``consumption_stats``, ``corrected_pace``, ``predictions``,
        ``saving_opportunities``.
    """
    result: dict = {
        "consumption_stats": {},
        "corrected_pace": [],
        "predictions": {},
        "saving_opportunities": [],
    }

    if not lap_times or not fuel_levels:
        return result

    result["consumption_stats"] = compute_consumption_stats(fuel_levels)
    result["corrected_pace"] = compute_fuel_corrected_pace(
        lap_times, fuel_levels, fuel_weight_factor,
    )

    # Predictions: 5, 10, 20 laps out
    result["predictions"] = {}
    for target in [5, 10, 20]:
        result["predictions"][f"fuel_after_{target}_laps"] = predict_fuel_remaining(
            fuel_levels, target,
        )

    # Per-lap consumption for saving opportunities
    if len(fuel_levels) >= 2:
        arr = np.array(fuel_levels, dtype=float)
        per_lap_consumption = list(np.diff(arr) * -1.0)
        # Clamp negatives
        per_lap_consumption = [max(0.0, c) for c in per_lap_consumption]
        # Match length with lap_times (per_lap consumption has len-1 entries)
        n = min(len(lap_times), len(per_lap_consumption))
        result["saving_opportunities"] = detect_fuel_saving_opportunities(
            lap_times[:n], per_lap_consumption[:n],
        )

    return result
