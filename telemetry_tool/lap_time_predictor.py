"""Conditions-based lap time predictor.

Predicts expected lap times for a driver at a track given current conditions
(grip, weather, tire state) using historical session data as training examples.

The model is a **weighted k-nearest-neighbor regression** over historical
sessions — no external ML framework required. Feature similarity is computed
across grip, temperature, and driver performance dimensions. The model also
estimates a confidence interval based on historical variance.

Public API
~~~~~~~~~~
- ``predict_lap_time(driver_id, track_id, conditions, history)``
- ``predict_from_partial_session(completed_laps, conditions, history)``
- ``estimate_improvement_potential(prediction, theoretical_time)``

Usage::

    from lap_time_predictor import predict_lap_time, SessionConditions
    prediction = predict_lap_time(
        driver_id=42,
        track_id=7,
        conditions=SessionConditions(grip_mu=0.85, air_temp_c=22.0),
        history=historical_sessions,
    )
    print(f"Predicted: {prediction.predicted_time_s:.2f}s")
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SessionConditions:
    """Current or target session conditions for prediction."""

    grip_mu: float = 1.0           # Grip scale (0.5 = very wet, 1.0 = dry, 1.3 = sticky)
    air_temp_c: float = 20.0       # Air temperature
    humidity_pct: float = 50.0     # Relative humidity
    track_temp_c: float = 30.0     # Track surface temperature (estimated)
    wind_speed_mps: float = 0.0    # Wind speed
    rain_mm: float = 0.0           # Rainfall
    session_type: str = "practice"  # practice | qualifying | race
    tire_compound: str = "medium"   # soft | medium | hard | wet


@dataclass
class HistoricalSession:
    """A past session used as a training example for prediction."""

    session_id: str
    driver_id: int
    track_id: int
    best_lap_time_s: float
    mean_lap_time_s: float
    n_laps: int
    grip_mu: float = 1.0
    air_temp_c: float = 20.0
    humidity_pct: float = 50.0
    track_temp_c: float = 30.0
    session_type: str = "practice"
    total_score: float = 0.0       # 0-100 performance score
    consistency_cv_pct: float = 2.0  # Coefficient of variation


@dataclass
class LapTimePrediction:
    """Prediction result with confidence interval."""

    predicted_time_s: float         # Expected best lap time
    predicted_mean_s: float         # Expected average lap time
    confidence: float               # 0.0-1.0 prediction confidence
    lower_bound_s: float            # Optimistic estimate (1-sigma)
    upper_bound_s: float            # Pessimistic estimate (1-sigma)
    contributing_sessions: int      # Number of historical sessions used
    grip_adjustment_s: float        # Time delta from grip conditions
    temp_adjustment_s: float        # Time delta from temperature
    driver_trend_s: float           # Improvement trend adjustment
    conditions_summary: str         # Human-readable conditions description
    explanation: str                # Human-readable prediction explanation

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_time_s": round(self.predicted_time_s, 3),
            "predicted_mean_s": round(self.predicted_mean_s, 3),
            "confidence": round(self.confidence, 2),
            "lower_bound_s": round(self.lower_bound_s, 3),
            "upper_bound_s": round(self.upper_bound_s, 3),
            "contributing_sessions": self.contributing_sessions,
            "adjustments": {
                "grip_s": round(self.grip_adjustment_s, 3),
                "temperature_s": round(self.temp_adjustment_s, 3),
                "driver_trend_s": round(self.driver_trend_s, 3),
            },
            "conditions_summary": self.conditions_summary,
            "explanation": self.explanation,
        }


@dataclass
class ImprovementPotential:
    """Gap analysis between predicted and theoretical performance."""

    predicted_time_s: float
    theoretical_time_s: float
    gap_s: float                    # predicted - theoretical
    gap_pct: float                  # gap as percentage of theoretical
    achievable_target_s: float      # Realistic near-term target
    improvement_areas: list[str]    # Where time can be found

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_time_s": round(self.predicted_time_s, 3),
            "theoretical_time_s": round(self.theoretical_time_s, 3),
            "gap_s": round(self.gap_s, 3),
            "gap_pct": round(self.gap_pct, 1),
            "achievable_target_s": round(self.achievable_target_s, 3),
            "improvement_areas": self.improvement_areas,
        }


# ---------------------------------------------------------------------------
# Feature distance computation
# ---------------------------------------------------------------------------

# Feature weights for similarity computation
_WEIGHTS = {
    "same_driver": 3.0,     # Strong preference for same driver's history
    "same_track": 5.0,      # Must be same track (effectively required)
    "grip_mu": 2.0,         # Grip conditions strongly affect lap time
    "air_temp_c": 0.5,      # Temperature has moderate effect
    "humidity_pct": 0.2,    # Humidity has small effect
    "session_type": 1.0,    # Session type affects driver behavior
    "recency": 0.5,         # More recent sessions are more relevant
}

# Normalization scales for each feature
_SCALES = {
    "grip_mu": 0.3,         # 0.3 grip units = "very different"
    "air_temp_c": 15.0,     # 15 degrees = "very different"
    "humidity_pct": 40.0,   # 40% difference = "very different"
}


def _compute_similarity(
    conditions: SessionConditions,
    hist: HistoricalSession,
    target_driver_id: int,
    target_track_id: int,
) -> float:
    """Compute similarity score between target conditions and a historical session.

    Returns a value in [0, 1] where 1 = identical conditions.
    """
    if hist.track_id != target_track_id:
        return 0.0  # Different track → not comparable

    distance = 0.0
    total_weight = 0.0

    # Grip similarity
    grip_diff = abs(conditions.grip_mu - hist.grip_mu)
    grip_sim = max(0, 1 - grip_diff / _SCALES["grip_mu"])
    distance += _WEIGHTS["grip_mu"] * (1 - grip_sim)
    total_weight += _WEIGHTS["grip_mu"]

    # Temperature similarity
    temp_diff = abs(conditions.air_temp_c - hist.air_temp_c)
    temp_sim = max(0, 1 - temp_diff / _SCALES["air_temp_c"])
    distance += _WEIGHTS["air_temp_c"] * (1 - temp_sim)
    total_weight += _WEIGHTS["air_temp_c"]

    # Humidity
    hum_diff = abs(conditions.humidity_pct - hist.humidity_pct)
    hum_sim = max(0, 1 - hum_diff / _SCALES["humidity_pct"])
    distance += _WEIGHTS["humidity_pct"] * (1 - hum_sim)
    total_weight += _WEIGHTS["humidity_pct"]

    # Same driver bonus
    if hist.driver_id == target_driver_id:
        total_weight += _WEIGHTS["same_driver"]
        # distance += 0 (no penalty for same driver)
    else:
        distance += _WEIGHTS["same_driver"] * 0.5  # Partial penalty

    # Session type
    if conditions.session_type == hist.session_type:
        total_weight += _WEIGHTS["session_type"]
    else:
        distance += _WEIGHTS["session_type"] * 0.3
        total_weight += _WEIGHTS["session_type"]

    if total_weight == 0:
        return 0.0

    similarity = max(0, 1 - distance / total_weight)
    return similarity


# ---------------------------------------------------------------------------
# Condition adjustments
# ---------------------------------------------------------------------------

def _grip_time_adjustment(
    base_time_s: float,
    base_grip: float,
    target_grip: float,
) -> float:
    """Estimate lap time change from grip difference.

    Based on the empirical relationship: ~1% grip change → ~0.3% lap time change.
    Lower grip = slower (positive adjustment), higher grip = faster (negative).
    """
    if base_grip <= 0 or target_grip <= 0:
        return 0.0
    grip_ratio = target_grip / base_grip
    # Grip sensitivity: 1% grip → 0.3% time
    time_factor = 1 + (1 - grip_ratio) * 0.3
    return base_time_s * (time_factor - 1)


def _temperature_time_adjustment(
    base_time_s: float,
    base_temp_c: float,
    target_temp_c: float,
) -> float:
    """Estimate lap time change from temperature difference.

    Tire grip improves with moderate warmth but degrades in extreme heat.
    Optimal ~25-35C. Below optimal → slower, above optimal → slightly slower.
    """
    optimal = 30.0
    base_delta = abs(base_temp_c - optimal) / 30.0    # Normalize to ~1 at 0C or 60C
    target_delta = abs(target_temp_c - optimal) / 30.0

    # Each 1 unit of normalized delta adds ~0.2% to lap time
    base_penalty = base_delta * 0.002
    target_penalty = target_delta * 0.002

    return base_time_s * (target_penalty - base_penalty)


def _driver_trend_adjustment(
    history: list[HistoricalSession],
    driver_id: int,
    track_id: int,
) -> float:
    """Estimate improvement trend from driver's recent sessions at this track.

    Returns a negative value (faster) if driver is improving, positive if degrading.
    """
    driver_sessions = [
        h for h in history
        if h.driver_id == driver_id and h.track_id == track_id and h.n_laps >= 3
    ]

    if len(driver_sessions) < 2:
        return 0.0

    # Compare first half vs second half of sessions (chronological by session_id)
    driver_sessions.sort(key=lambda s: s.session_id)
    mid = len(driver_sessions) // 2
    early_avg = sum(s.best_lap_time_s for s in driver_sessions[:mid]) / mid
    late_avg = sum(s.best_lap_time_s for s in driver_sessions[mid:]) / (len(driver_sessions) - mid)

    # The trend continuation: extrapolate by 50% of observed improvement
    trend = (late_avg - early_avg) * 0.5
    return trend


# ---------------------------------------------------------------------------
# Conditions summary
# ---------------------------------------------------------------------------

def _conditions_summary(conditions: SessionConditions) -> str:
    """Generate a human-readable conditions description."""
    parts = []

    if conditions.grip_mu >= 1.1:
        parts.append("high grip")
    elif conditions.grip_mu >= 0.9:
        parts.append("normal grip")
    elif conditions.grip_mu >= 0.7:
        parts.append("reduced grip")
    else:
        parts.append("low grip (wet)")

    parts.append(f"{conditions.air_temp_c:.0f}C")

    if conditions.rain_mm > 0:
        parts.append(f"rain {conditions.rain_mm:.1f}mm")

    if conditions.wind_speed_mps > 5:
        parts.append(f"wind {conditions.wind_speed_mps:.0f}m/s")

    parts.append(conditions.session_type)

    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Core prediction
# ---------------------------------------------------------------------------

def predict_lap_time(
    driver_id: int,
    track_id: int,
    conditions: SessionConditions,
    history: list[HistoricalSession],
    *,
    k: int = 5,
    min_similarity: float = 0.2,
) -> LapTimePrediction:
    """Predict expected lap time based on conditions and historical data.

    Uses weighted k-nearest-neighbor regression over historical sessions.
    Neighbors are weighted by condition similarity. Grip and temperature
    adjustments are applied to account for condition differences.

    Parameters
    ----------
    driver_id : int
        Target driver.
    track_id : int
        Target track.
    conditions : SessionConditions
        Current/expected conditions.
    history : list[HistoricalSession]
        Historical sessions to learn from.
    k : int
        Number of nearest neighbors to use.
    min_similarity : float
        Minimum similarity threshold for inclusion.

    Returns
    -------
    LapTimePrediction
        Predicted lap time with confidence interval and explanation.
    """
    # Filter to same track and compute similarities
    scored: list[tuple[float, HistoricalSession]] = []
    for h in history:
        sim = _compute_similarity(conditions, h, driver_id, track_id)
        if sim >= min_similarity:
            scored.append((sim, h))

    if not scored:
        return _fallback_prediction(conditions)

    # Sort by similarity descending, take top k
    scored.sort(key=lambda x: x[0], reverse=True)
    neighbors = scored[:k]

    # Weighted average of best lap times with condition adjustments
    total_weight = 0.0
    weighted_best = 0.0
    weighted_mean = 0.0
    adjusted_times: list[float] = []

    for sim, h in neighbors:
        # Apply condition adjustments to historical time
        grip_adj = _grip_time_adjustment(h.best_lap_time_s, h.grip_mu, conditions.grip_mu)
        temp_adj = _temperature_time_adjustment(h.best_lap_time_s, h.air_temp_c, conditions.air_temp_c)
        adjusted_best = h.best_lap_time_s + grip_adj + temp_adj
        adjusted_mean = h.mean_lap_time_s + grip_adj + temp_adj

        weighted_best += sim * adjusted_best
        weighted_mean += sim * adjusted_mean
        total_weight += sim
        adjusted_times.append(adjusted_best)

    if total_weight == 0:
        return _fallback_prediction(conditions)

    predicted_best = weighted_best / total_weight
    predicted_mean = weighted_mean / total_weight

    # Driver improvement trend
    trend_adj = _driver_trend_adjustment(history, driver_id, track_id)
    predicted_best += trend_adj
    predicted_mean += trend_adj

    # Aggregate condition adjustments (from the most similar neighbor for reporting)
    best_match = neighbors[0][1]
    grip_adj_report = _grip_time_adjustment(best_match.best_lap_time_s, best_match.grip_mu, conditions.grip_mu)
    temp_adj_report = _temperature_time_adjustment(best_match.best_lap_time_s, best_match.air_temp_c, conditions.air_temp_c)

    # Confidence based on similarity spread and sample size
    avg_similarity = total_weight / len(neighbors)
    sample_confidence = min(1.0, len(neighbors) / k)
    same_driver_count = sum(1 for _, h in neighbors if h.driver_id == driver_id)
    driver_confidence = min(1.0, same_driver_count / max(1, len(neighbors)))

    confidence = avg_similarity * 0.4 + sample_confidence * 0.3 + driver_confidence * 0.3
    confidence = max(0.1, min(1.0, confidence))

    # Standard deviation for bounds
    if len(adjusted_times) >= 2:
        mean_adj = sum(adjusted_times) / len(adjusted_times)
        variance = sum((t - mean_adj) ** 2 for t in adjusted_times) / len(adjusted_times)
        std_dev = math.sqrt(variance)
    else:
        std_dev = predicted_best * 0.02  # Default 2% uncertainty

    lower = predicted_best - std_dev
    upper = predicted_best + std_dev

    # Build explanation
    cond_desc = _conditions_summary(conditions)
    same_driver_sessions = sum(1 for _, h in neighbors if h.driver_id == driver_id)
    explanation = (
        f"Based on {len(neighbors)} similar sessions "
        f"({same_driver_sessions} from this driver). "
        f"Conditions: {cond_desc}. "
    )
    if abs(grip_adj_report) > 0.01:
        direction = "faster" if grip_adj_report < 0 else "slower"
        explanation += f"Grip adjustment: {abs(grip_adj_report):.3f}s {direction}. "
    if abs(temp_adj_report) > 0.01:
        direction = "faster" if temp_adj_report < 0 else "slower"
        explanation += f"Temperature adjustment: {abs(temp_adj_report):.3f}s {direction}. "
    if abs(trend_adj) > 0.01:
        direction = "improvement" if trend_adj < 0 else "regression"
        explanation += f"Driver trend: {abs(trend_adj):.3f}s {direction}. "

    return LapTimePrediction(
        predicted_time_s=predicted_best,
        predicted_mean_s=predicted_mean,
        confidence=confidence,
        lower_bound_s=lower,
        upper_bound_s=upper,
        contributing_sessions=len(neighbors),
        grip_adjustment_s=grip_adj_report,
        temp_adjustment_s=temp_adj_report,
        driver_trend_s=trend_adj,
        conditions_summary=cond_desc,
        explanation=explanation,
    )


def _fallback_prediction(conditions: SessionConditions) -> LapTimePrediction:
    """Return a low-confidence fallback when no history is available."""
    return LapTimePrediction(
        predicted_time_s=0.0,
        predicted_mean_s=0.0,
        confidence=0.0,
        lower_bound_s=0.0,
        upper_bound_s=0.0,
        contributing_sessions=0,
        grip_adjustment_s=0.0,
        temp_adjustment_s=0.0,
        driver_trend_s=0.0,
        conditions_summary=_conditions_summary(conditions),
        explanation="No historical data available for this driver/track/conditions combination.",
    )


# ---------------------------------------------------------------------------
# Partial session prediction
# ---------------------------------------------------------------------------

def predict_from_partial_session(
    completed_laps: list[float],
    conditions: SessionConditions,
    history: list[HistoricalSession],
    *,
    driver_id: int = 0,
    track_id: int = 0,
) -> LapTimePrediction:
    """Update prediction using laps already completed in the current session.

    Blends historical prediction with observed data — as more laps complete,
    observed data dominates the prediction.

    Parameters
    ----------
    completed_laps : list[float]
        Lap times already driven (seconds).
    conditions : SessionConditions
        Current session conditions.
    history : list[HistoricalSession]
        Historical sessions for baseline.
    """
    if not completed_laps:
        return predict_lap_time(driver_id, track_id, conditions, history)

    # Observed statistics
    valid_laps = [t for t in completed_laps if t > 0 and not math.isnan(t)]
    if not valid_laps:
        return predict_lap_time(driver_id, track_id, conditions, history)

    observed_best = min(valid_laps)
    observed_mean = sum(valid_laps) / len(valid_laps)
    n_laps = len(valid_laps)

    # Historical prediction
    hist_pred = predict_lap_time(driver_id, track_id, conditions, history)

    # Blend weight: more laps → trust observed more
    obs_weight = min(0.9, n_laps / 10)  # Full trust after ~10 laps
    hist_weight = 1 - obs_weight

    if hist_pred.confidence == 0 or hist_pred.predicted_time_s == 0:
        # No history — rely entirely on observed
        std_dev = 0.0
        if len(valid_laps) >= 2:
            mean_t = sum(valid_laps) / len(valid_laps)
            variance = sum((t - mean_t) ** 2 for t in valid_laps) / len(valid_laps)
            std_dev = math.sqrt(variance)
        else:
            std_dev = observed_best * 0.02

        return LapTimePrediction(
            predicted_time_s=observed_best,
            predicted_mean_s=observed_mean,
            confidence=min(0.8, n_laps / 5),
            lower_bound_s=observed_best - std_dev,
            upper_bound_s=observed_best + std_dev,
            contributing_sessions=0,
            grip_adjustment_s=0.0,
            temp_adjustment_s=0.0,
            driver_trend_s=0.0,
            conditions_summary=_conditions_summary(conditions),
            explanation=f"Based on {n_laps} completed laps. No historical baseline.",
        )

    # Blended prediction
    blended_best = obs_weight * observed_best + hist_weight * hist_pred.predicted_time_s
    blended_mean = obs_weight * observed_mean + hist_weight * hist_pred.predicted_mean_s

    # Tighter confidence as more laps complete
    confidence = min(0.95, hist_pred.confidence * 0.5 + obs_weight)

    std_dev = abs(observed_best - hist_pred.predicted_time_s) * 0.5 * hist_weight

    return LapTimePrediction(
        predicted_time_s=blended_best,
        predicted_mean_s=blended_mean,
        confidence=confidence,
        lower_bound_s=blended_best - std_dev,
        upper_bound_s=blended_best + std_dev,
        contributing_sessions=hist_pred.contributing_sessions,
        grip_adjustment_s=hist_pred.grip_adjustment_s,
        temp_adjustment_s=hist_pred.temp_adjustment_s,
        driver_trend_s=hist_pred.driver_trend_s,
        conditions_summary=_conditions_summary(conditions),
        explanation=(
            f"Blended: {obs_weight:.0%} observed ({n_laps} laps, best {observed_best:.2f}s) + "
            f"{hist_weight:.0%} historical ({hist_pred.contributing_sessions} sessions). "
            f"{hist_pred.conditions_summary}."
        ),
    )


# ---------------------------------------------------------------------------
# Improvement potential
# ---------------------------------------------------------------------------

def estimate_improvement_potential(
    prediction: LapTimePrediction,
    theoretical_time_s: float,
) -> ImprovementPotential:
    """Estimate how much faster the driver could realistically go.

    Uses the theoretical minimum and the current prediction to establish
    a gap, then sets an achievable target at 60% of the gap (i.e., recover
    60% of time lost to theoretical).

    Parameters
    ----------
    prediction : LapTimePrediction
        The driver's predicted lap time.
    theoretical_time_s : float
        Physics-based theoretical minimum for the track+conditions.
    """
    if prediction.predicted_time_s <= 0 or theoretical_time_s <= 0:
        return ImprovementPotential(
            predicted_time_s=prediction.predicted_time_s,
            theoretical_time_s=theoretical_time_s,
            gap_s=0,
            gap_pct=0,
            achievable_target_s=0,
            improvement_areas=[],
        )

    gap = prediction.predicted_time_s - theoretical_time_s
    gap_pct = (gap / theoretical_time_s) * 100

    # Achievable target: close 60% of the gap
    achievable = prediction.predicted_time_s - gap * 0.6

    # Improvement areas based on gap size
    areas: list[str] = []
    if gap_pct > 5:
        areas.append("Significant braking optimization opportunity (brake later, more efficiently)")
    if gap_pct > 3:
        areas.append("Apex speed improvement — carry more speed through corners")
    if gap_pct > 2:
        areas.append("Exit traction — earlier and more progressive throttle application")
    if gap_pct > 1:
        areas.append("Racing line precision — tighter line reduces distance and time")
    if gap_pct <= 1:
        areas.append("Fine-tuning — marginal gains through micro-adjustments")

    return ImprovementPotential(
        predicted_time_s=prediction.predicted_time_s,
        theoretical_time_s=theoretical_time_s,
        gap_s=gap,
        gap_pct=gap_pct,
        achievable_target_s=achievable,
        improvement_areas=areas,
    )
