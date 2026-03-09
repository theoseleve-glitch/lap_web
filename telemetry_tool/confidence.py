"""
confidence.py
-------------
Unified confidence score for theoretical + coaching outputs.

Computes a single confidence_score (0-100) from 8 weighted data quality
components and generates human-readable reasons explaining what limits
trust, sorted by impact. Includes a recommended_next_action for the
most impactful fix the user can make.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

# ── Component weights (must sum to 1.0) ──────────────────────────
_WEIGHTS = {
    "distance_quality":     0.15,
    "data_quality":         0.20,
    "lap_count":            0.15,
    "cluster_purity":       0.10,
    "channel_coverage":     0.15,
    "solver_convergence":   0.10,
    "curvature_reliability": 0.10,
    "fusion_confidence":    0.05,
}

# ── Reason templates ─────────────────────────────────────────────
_REASON_TEMPLATES = {
    "distance_quality": "Distance quality is {status} — lap distances may be inaccurate",
    "data_quality": "Low overall data quality ({score:.0%}) — noisy or missing sensor data",
    "lap_count": "Only {n} learning lap(s) — need 10+ for reliable envelope",
    "cluster_purity": "Mixed driving conditions (purity {score:.0%}) — results blend different grip levels",
    "channel_coverage": "Poor channel coverage ({score:.0%}) — significant data gaps",
    "solver_convergence": "Using {method} solver — less precise than physics-based simulation",
    "curvature_reliability": "Low curvature reliability ({score:.0%}) — corner detection may be imprecise",
    "fusion_confidence": "No IMU sensor fusion — position and speed less precise",
}

# ── Recommended actions (ordered by typical impact) ──────────────
_ACTIONS = {
    "lap_count": "Record at least 10 clean laps for reliable results",
    "data_quality": "Check sensor connections and ensure clean GPS signal",
    "channel_coverage": "Verify all telemetry channels are recording properly",
    "distance_quality": "Ensure GPS antenna has clear sky view for accurate distance",
    "cluster_purity": "Run a session in consistent conditions (same tyre, dry track)",
    "solver_convergence": "Add IMU data for physics-based simulation",
    "curvature_reliability": "Add yaw rate sensor for precise curvature estimation",
    "fusion_confidence": "Add an IMU sensor for better acceleration data",
}


@dataclass
class ConfidenceAssessment:
    """Unified confidence assessment for advanced outputs."""
    confidence_score: int            # 0-100
    confidence_level: str            # "high" | "medium" | "low"
    confidence_reasons: list[str]    # sorted by impact
    component_scores: dict[str, float]  # each 0-1
    recommended_next_action: str     # top actionable fix

    def to_dict(self) -> dict:
        return asdict(self)


def _lap_count_score(n: int) -> float:
    """Ramp: 1->0, 3->0.3, 5->0.5, 10->0.8, 20->1.0."""
    if n <= 1:
        return 0.0
    if n >= 20:
        return 1.0
    # Piecewise linear
    breakpoints = [(1, 0.0), (3, 0.3), (5, 0.5), (10, 0.8), (20, 1.0)]
    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i + 1]
        if x0 <= n <= x1:
            t = (n - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 1.0


def _solver_score(method: str) -> float:
    """Score solver convergence quality."""
    scores = {
        "hybrid": 1.0,
        "physics": 0.8,
        "percentile_envelope_phase_aware": 0.6,
        "percentile_envelope": 0.5,
    }
    return scores.get(method, 0.3)


def _distance_quality_score(status: str) -> float:
    """Score distance quality status."""
    scores = {"good": 1.0, "degraded": 0.3, "failed": 0.0}
    return scores.get(status, 0.5)


def compute_confidence(
    *,
    n_learning_laps: int,
    data_quality_confidence: float,
    distance_quality_status: str,
    cluster_purity: float,
    channel_coverage: float,
    solver_method: str,
    curvature_reliability: float,
    fusion_confidence: float,
) -> ConfidenceAssessment:
    """Compute unified confidence score from 8 components.

    Parameters
    ----------
    n_learning_laps : number of laps in learning set
    data_quality_confidence : DataQualityReport.overall_confidence (0-1)
    distance_quality_status : "good", "degraded", or "failed"
    cluster_purity : ClusteringResult.purity_score (0-1)
    channel_coverage : 1 - max(nan fractions) (0-1)
    solver_method : simulation method string
    curvature_reliability : curvature quality score (0-1)
    fusion_confidence : EKF fusion confidence (0-1), -1 if not computed

    Returns
    -------
    ConfidenceAssessment with score, level, reasons, and action.
    """
    # Compute component scores
    components = {
        "distance_quality": _distance_quality_score(distance_quality_status),
        "data_quality": max(0.0, min(1.0, data_quality_confidence)),
        "lap_count": _lap_count_score(n_learning_laps),
        "cluster_purity": max(0.0, min(1.0, cluster_purity)),
        "channel_coverage": max(0.0, min(1.0, channel_coverage)),
        "solver_convergence": _solver_score(solver_method),
        "curvature_reliability": max(0.0, min(1.0, curvature_reliability)),
        "fusion_confidence": 0.5 if fusion_confidence < 0 else max(0.0, min(1.0, fusion_confidence)),
    }

    # Weighted sum
    weighted = sum(
        components[k] * _WEIGHTS[k] for k in _WEIGHTS
    )
    score = round(weighted * 100)
    score = max(0, min(100, score))

    # Level
    if score >= 75:
        level = "high"
    elif score >= 45:
        level = "medium"
    else:
        level = "low"

    # Reasons: components below 0.5, sorted by impact (weight * deficit)
    reasons: list[tuple[float, str, str]] = []  # (impact, key, reason)
    for key, val in components.items():
        if val < 0.5:
            deficit = 0.5 - val
            impact = deficit * _WEIGHTS[key]
            template = _REASON_TEMPLATES[key]
            if key == "distance_quality":
                reason = template.format(status=distance_quality_status)
            elif key == "lap_count":
                reason = template.format(n=n_learning_laps)
            elif key == "solver_convergence":
                reason = template.format(method=solver_method)
            else:
                reason = template.format(score=val)
            reasons.append((impact, key, reason))

    reasons.sort(key=lambda x: -x[0])
    reason_strings = [r[2] for r in reasons]

    # Recommended action: from highest-impact blocker
    if reasons:
        top_key = reasons[0][1]
        action = _ACTIONS.get(top_key, "Improve data quality for more reliable results")
    else:
        action = ""

    logger.info(
        "Confidence: score=%d, level=%s, reasons=%d, action=%s",
        score, level, len(reason_strings),
        action[:50] if action else "none",
    )

    return ConfidenceAssessment(
        confidence_score=score,
        confidence_level=level,
        confidence_reasons=reason_strings,
        component_scores={k: round(v, 3) for k, v in components.items()},
        recommended_next_action=action,
    )
