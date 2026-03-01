"""Tests for evaluate_badges() achievement tier system."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure project root is on path (mirrors conftest.py convention)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scoring import (
    MAX_ADAPTATION,
    MAX_CONSISTENCY,
    MAX_EXECUTION,
    MAX_PACE,
    MAX_ROBUSTNESS,
    TOTAL_MAX,
    evaluate_badges,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CATEGORY_MAX = {
    "pace":        MAX_PACE,
    "consistency": MAX_CONSISTENCY,
    "execution":   MAX_EXECUTION,
    "robustness":  MAX_ROBUSTNESS,
    "adaptation":  MAX_ADAPTATION,
}


def _make_score_result(
    *,
    pace_frac: float = 0.0,
    consistency_frac: float = 0.0,
    execution_frac: float = 0.0,
    robustness_frac: float = 0.0,
    adaptation_frac: float = 0.0,
) -> dict[str, Any]:
    """Build a minimal ``score_session()``-shaped dict from category fractions.

    Each ``*_frac`` is a fraction of the category maximum (0.0 -- 1.0).
    ``total_score`` is derived as the sum of all sub-scores.
    """
    sub_scores: dict[str, dict[str, float]] = {}
    mapping = {
        "pace":        (pace_frac,        MAX_PACE),
        "consistency": (consistency_frac, MAX_CONSISTENCY),
        "execution":   (execution_frac,   MAX_EXECUTION),
        "robustness":  (robustness_frac,  MAX_ROBUSTNESS),
        "adaptation":  (adaptation_frac,  MAX_ADAPTATION),
    }
    total = 0.0
    for key, (frac, mx) in mapping.items():
        score = frac * mx
        sub_scores[key] = {"score": score, "max": mx}
        total += score

    return {
        "total_score": total,
        "grade":       "C",
        "sub_scores":  sub_scores,
        "strengths":   [],
        "weaknesses":  [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEvaluateBadges:
    """Unit tests for the badge evaluation system."""

    def test_no_badges_below_threshold(self) -> None:
        """All categories at 30 % -- no badge should be awarded."""
        result = _make_score_result(
            pace_frac=0.30,
            consistency_frac=0.30,
            execution_frac=0.30,
            robustness_frac=0.30,
            adaptation_frac=0.30,
        )
        badges = evaluate_badges(result)
        assert badges == []

    def test_bronze_at_60_pct(self) -> None:
        """Pace at exactly 60 % should earn a bronze badge."""
        result = _make_score_result(pace_frac=0.60)
        badges = evaluate_badges(result)
        pace_badges = [b for b in badges if b["id"] == "pace_master"]
        assert len(pace_badges) == 1
        assert pace_badges[0]["tier"] == "bronze"

    def test_silver_at_75_pct(self) -> None:
        """Consistency at exactly 75 % should earn a silver badge."""
        result = _make_score_result(consistency_frac=0.75)
        badges = evaluate_badges(result)
        cons_badges = [b for b in badges if b["id"] == "consistency_champion"]
        assert len(cons_badges) == 1
        assert cons_badges[0]["tier"] == "silver"

    def test_gold_at_90_pct(self) -> None:
        """Execution at 92 % should earn a gold badge."""
        result = _make_score_result(execution_frac=0.92)
        badges = evaluate_badges(result)
        exec_badges = [b for b in badges if b["id"] == "execution_expert"]
        assert len(exec_badges) == 1
        assert exec_badges[0]["tier"] == "gold"

    def test_flow_state_badge_uses_total(self) -> None:
        """All categories at 80 % → total = 80 % → silver Flow State badge."""
        result = _make_score_result(
            pace_frac=0.80,
            consistency_frac=0.80,
            execution_frac=0.80,
            robustness_frac=0.80,
            adaptation_frac=0.80,
        )
        badges = evaluate_badges(result)
        flow = [b for b in badges if b["id"] == "flow_state"]
        assert len(flow) == 1
        assert flow[0]["tier"] == "silver"
        assert flow[0]["category"] == "total"

    def test_highest_tier_wins(self) -> None:
        """92 % pace should yield exactly one gold badge, not bronze+silver+gold."""
        result = _make_score_result(pace_frac=0.92)
        badges = evaluate_badges(result)
        pace_badges = [b for b in badges if b["id"] == "pace_master"]
        assert len(pace_badges) == 1
        assert pace_badges[0]["tier"] == "gold"

    def test_badge_shape(self) -> None:
        """Each badge dict must have exactly {id, label, tier, category, criteria}."""
        result = _make_score_result(pace_frac=0.70)
        badges = evaluate_badges(result)
        assert len(badges) >= 1
        expected_keys = {"id", "label", "tier", "category", "criteria"}
        for badge in badges:
            assert set(badge.keys()) == expected_keys
