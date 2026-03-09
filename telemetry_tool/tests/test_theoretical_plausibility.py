"""Tests for theoretical overfitting detection via cross-validation."""
import numpy as np
import pandas as pd
import pytest


def _make_lap(n_points: int, base_speed: float, noise_std: float = 0.5,
              rng=None) -> pd.DataFrame:
    """Create a synthetic lap DataFrame."""
    if rng is None:
        rng = np.random.default_rng(42)
    dist = np.linspace(0, 500, n_points)
    speed = np.full(n_points, base_speed) + rng.normal(0, noise_std, n_points)
    speed = np.clip(speed, 2.0, 100.0)
    return pd.DataFrame({"distance_m": dist, "speed_mps": speed})


def test_split_deterministic():
    """Same laps produce identical train/holdout split every time."""
    from theoretical_engine import split_laps_train_holdout

    rng = np.random.default_rng(99)
    laps = [_make_lap(100, 20.0, rng=rng) for _ in range(10)]

    train1, hold1, idx1 = split_laps_train_holdout(laps)
    train2, hold2, idx2 = split_laps_train_holdout(laps)

    assert idx1 == idx2
    assert len(train1) == len(train2)
    assert len(hold1) == len(hold2)
    # Holdout is ~30% (every 3rd lap)
    assert len(hold1) == 3  # indices 2, 5, 8
    assert len(train1) == 7


def test_split_few_laps_skips():
    """Fewer than 4 laps → holdout is empty, all laps returned as train."""
    from theoretical_engine import split_laps_train_holdout

    laps = [_make_lap(100, 20.0) for _ in range(3)]
    train, hold, idx = split_laps_train_holdout(laps)

    assert len(train) == 3
    assert len(hold) == 0
    assert idx == []


def test_healthy_envelope_passes():
    """8 realistic laps with achievable theoretical → no overfit flag."""
    from theoretical_engine import (
        build_theoretical_lap,
        compute_theoretical_plausibility,
        split_laps_train_holdout,
    )

    rng = np.random.default_rng(42)
    n_points = 200
    laps = []
    for i in range(8):
        dist = np.linspace(0, 500, n_points)
        # All laps centered around 20 m/s with small variation
        speed = np.full(n_points, 20.0) + rng.normal(0, 0.8, n_points)
        speed = np.clip(speed, 5.0, 40.0)
        laps.append(pd.DataFrame({
            "distance_m": dist,
            "speed_mps": speed,
            "accel_long_mps2": rng.normal(0, 1.0, n_points),
        }))

    train, holdout, _ = split_laps_train_holdout(laps)
    theo = build_theoretical_lap(laps, n_points=n_points)

    result = compute_theoretical_plausibility(theo, holdout)

    assert not result.overfit_suspected
    assert result.plausibility_score > 0.5
    assert result.best_approach_ratio > 0.80
    assert result.segments_never_approached < 5  # most segments reachable

    d = result.to_dict()
    assert "plausibility_score" in d
    assert "overfit_suspected" in d


def test_outlier_inflates_envelope():
    """7 normal laps + 1 outlier at 2x speed → overfit detected."""
    from theoretical_engine import (
        build_theoretical_lap,
        compute_theoretical_plausibility,
        split_laps_train_holdout,
    )

    rng = np.random.default_rng(42)
    n_points = 200
    laps = []
    for i in range(7):
        dist = np.linspace(0, 500, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 0.5, n_points)
        speed = np.clip(speed, 5.0, 40.0)
        laps.append(pd.DataFrame({
            "distance_m": dist,
            "speed_mps": speed,
            "accel_long_mps2": rng.normal(0, 1.0, n_points),
        }))

    # Outlier lap: 2x the normal speed
    dist = np.linspace(0, 500, n_points)
    speed = np.full(n_points, 40.0) + rng.normal(0, 0.5, n_points)
    speed = np.clip(speed, 5.0, 80.0)
    laps.append(pd.DataFrame({
        "distance_m": dist,
        "speed_mps": speed,
        "accel_long_mps2": rng.normal(0, 1.0, n_points),
    }))

    _, holdout, _ = split_laps_train_holdout(laps)
    # Build theoretical on ALL laps (including outlier) — this inflates envelope
    theo = build_theoretical_lap(laps, n_points=n_points)

    result = compute_theoretical_plausibility(theo, holdout)

    assert result.overfit_suspected
    assert result.plausibility_score < 0.5
    assert result.best_approach_ratio < 0.85
