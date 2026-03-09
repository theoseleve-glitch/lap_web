"""Adaptation score parity tests — verify consistent output between paths."""
import pytest

from scoring import (
    ADAPT_V2_STABLE_DEFAULT_FRAC,
    MAX_ADAPTATION,
    score_session,
)


def _base_metrics():
    """Minimal metrics dict for scoring."""
    return {
        "best_s": 52.0,
        "n_laps": 10,
        "cv_pct": 1.2,
        "best_to_median_s": 0.8,
        "speed_mean_mps": 25.0,
        "accel_max_mps2": 8.0,
        "braking_max_mps2": 12.0,
        "early_mean_s": 53.0,
        "late_mean_s": 53.2,
        "early_yaw_var": 0.01,
        "late_yaw_var": 0.012,
    }


def _base_theory():
    """Minimal theoretical metrics."""
    return {"best_s": 50.0}


def test_default_adaptation_is_75_pct():
    """When no phase data, adaptation defaults to 75% of its effective max.

    Session-type weights may rescale the raw MAX_ADAPTATION budget, so the
    invariant is that the *percentage* equals ADAPT_V2_STABLE_DEFAULT_FRAC
    (75%), not the absolute score value.
    """
    result = score_session(_base_metrics(), _base_theory(), "practice")
    adapt = result["sub_scores"]["adaptation"]
    assert adapt["pct"] == round(ADAPT_V2_STABLE_DEFAULT_FRAC * 100, 2), (
        f"Default adaptation pct should be "
        f"{round(ADAPT_V2_STABLE_DEFAULT_FRAC * 100, 2)}%, got {adapt['pct']}%"
    )
    # Also verify score / max ratio matches the fraction
    assert adapt["max"] > 0
    ratio = adapt["score"] / adapt["max"]
    assert abs(ratio - ADAPT_V2_STABLE_DEFAULT_FRAC) < 1e-4, (
        f"score/max ratio should be {ADAPT_V2_STABLE_DEFAULT_FRAC}, got {ratio:.6f}"
    )


def test_adaptation_display_rounds_cleanly():
    """Adaptation score rounds to an integer without ugly decimals."""
    result = score_session(_base_metrics(), _base_theory(), "practice")
    raw = result["sub_scores"]["adaptation"]["score"]
    display = round(raw)
    assert isinstance(display, int)
    assert display in range(0, 16)


def test_adaptation_deterministic():
    """Same input produces same adaptation score (no randomness)."""
    r1 = score_session(_base_metrics(), _base_theory(), "practice")
    r2 = score_session(_base_metrics(), _base_theory(), "practice")
    assert r1["sub_scores"]["adaptation"]["score"] == r2["sub_scores"]["adaptation"]["score"]


def test_total_score_rounds_cleanly():
    """Total score should round to a clean integer for display."""
    result = score_session(_base_metrics(), _base_theory(), "practice")
    display = round(result["total_score"])
    assert isinstance(display, int)
    assert 0 <= display <= 100
