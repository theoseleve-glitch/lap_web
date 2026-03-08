"""Tests for unified confidence score system."""
import numpy as np
import pandas as pd
import pytest


def test_confidence_assessment_fields():
    """ConfidenceAssessment has all required fields and to_dict()."""
    from confidence import ConfidenceAssessment

    ca = ConfidenceAssessment(
        confidence_score=72,
        confidence_level="medium",
        confidence_reasons=["Only 5 laps"],
        component_scores={"lap_count": 0.5},
        recommended_next_action="Record more laps",
    )
    assert ca.confidence_score == 72
    assert ca.confidence_level == "medium"
    d = ca.to_dict()
    assert "confidence_score" in d
    assert "recommended_next_action" in d


def test_high_confidence_all_good():
    """All components good -> high confidence score."""
    from confidence import compute_confidence

    result = compute_confidence(
        n_learning_laps=15,
        data_quality_confidence=0.9,
        distance_quality_status="good",
        cluster_purity=1.0,
        channel_coverage=0.95,
        solver_method="hybrid",
        curvature_reliability=0.9,
        fusion_confidence=0.8,
    )
    assert result.confidence_score >= 75
    assert result.confidence_level == "high"
    assert len(result.confidence_reasons) == 0  # no blockers


def test_low_confidence_bad_data():
    """Low lap count + missing channels -> low confidence with reasons."""
    from confidence import compute_confidence

    result = compute_confidence(
        n_learning_laps=2,
        data_quality_confidence=0.3,
        distance_quality_status="degraded",
        cluster_purity=0.5,
        channel_coverage=0.4,
        solver_method="percentile_envelope",
        curvature_reliability=0.3,
        fusion_confidence=-1.0,  # not computed
    )
    assert result.confidence_score < 45
    assert result.confidence_level == "low"
    assert len(result.confidence_reasons) >= 3
    assert result.recommended_next_action != ""


def test_confidence_reasons_sorted_by_impact():
    """Reasons should be sorted by impact (weight * deficit)."""
    from confidence import compute_confidence

    result = compute_confidence(
        n_learning_laps=2,      # weight=0.15, deficit high
        data_quality_confidence=0.1,  # weight=0.20, deficit very high
        distance_quality_status="good",
        cluster_purity=1.0,
        channel_coverage=0.1,   # weight=0.15, deficit very high
        solver_method="percentile_envelope",
        curvature_reliability=0.8,
        fusion_confidence=0.8,
    )
    # Data quality (weight=0.20) should be first or near first
    assert any("data quality" in r.lower() or "quality" in r.lower()
               for r in result.confidence_reasons[:2])
