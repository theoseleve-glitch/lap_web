"""Tests for corner exit importance scoring."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from corner_focus import score_exit_importance


def test_long_straight_high_importance():
    """Corner followed by 400m straight → high exit importance."""
    assert score_exit_importance(400.0) > 0.8


def test_short_straight_low_importance():
    """Corner followed by 30m before next corner → low exit importance."""
    assert score_exit_importance(30.0) < 0.3


def test_no_straight_zero():
    """Corner immediately followed by another → near zero."""
    assert score_exit_importance(0.0) == pytest.approx(0.0, abs=0.05)


def test_medium_straight():
    """150m straight → moderate importance."""
    result = score_exit_importance(150.0)
    assert 0.4 < result < 0.7


def test_monotonic():
    """Longer straights always produce higher scores."""
    prev = 0.0
    for dist in [0, 50, 100, 200, 400, 800]:
        score = score_exit_importance(float(dist))
        assert score >= prev
        prev = score


def test_capped_at_one():
    """Score never exceeds 1.0."""
    assert score_exit_importance(2000.0) <= 1.0
