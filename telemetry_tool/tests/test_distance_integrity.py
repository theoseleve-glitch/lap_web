"""Tests for distance_integrity module."""
import numpy as np
import pandas as pd
import pytest


def test_perfect_monotonic_distance():
    """Perfectly monotonic distance → ratio=1.0, jump_count=0."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 1000)
    m = compute_lap_metrics(d, lap_number=1)
    assert m.monotonic_ratio == 1.0
    assert m.jump_count == 0
    assert m.lap_length == pytest.approx(500.0)


def test_non_monotonic_distance():
    """Backward jumps reduce monotonic_ratio and increase jump_count."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 100)
    d[30] = d[20]  # backward jump
    d[60] = d[50]  # another
    m = compute_lap_metrics(d, lap_number=1)
    assert m.monotonic_ratio < 1.0
    assert m.jump_count >= 2


def test_compression_ratio_uniform():
    """Uniform spacing → compression_ratio close to 0."""
    from distance_integrity import compute_lap_metrics

    d = np.linspace(0, 500, 1000)
    m = compute_lap_metrics(d, lap_number=1)
    assert m.compression_ratio < 0.01


def test_compression_ratio_irregular():
    """Irregular spacing → higher compression_ratio."""
    from distance_integrity import compute_lap_metrics

    d = np.array([0, 1, 2, 3, 100, 101, 102, 200, 201, 500])
    m = compute_lap_metrics(d, lap_number=1)
    assert m.compression_ratio > 0.5


def test_lap_length():
    """lap_length = max - min."""
    from distance_integrity import compute_lap_metrics

    d = np.array([10, 20, 30, 40, 50])
    m = compute_lap_metrics(d, lap_number=1)
    assert m.lap_length == pytest.approx(40.0)


def _make_lap_dict(distances: dict[int, np.ndarray]) -> dict[int, pd.DataFrame]:
    """Helper: build lap_dict from {lap_num: distance_array}."""
    result = {}
    for lap_num, d in distances.items():
        df = pd.DataFrame({"Distance (m)": d, "Speed (m/s)": np.ones(len(d))})
        result[lap_num] = df
    return result


def test_assess_all_laps_ok():
    """All laps with perfect distance -> status='ok', gate_advanced=False."""
    from distance_integrity import assess_all_laps

    laps = _make_lap_dict({
        1: np.linspace(0, 500, 100),
        2: np.linspace(0, 502, 100),
        3: np.linspace(0, 498, 100),
    })
    dq = assess_all_laps(laps)
    assert dq.status == "ok"
    assert dq.gate_advanced is False
    assert len(dq.metrics) == 3


def test_assess_all_laps_zscore():
    """One lap with very different length gets flagged with high zscore."""
    from distance_integrity import assess_all_laps

    laps = _make_lap_dict({
        1: np.linspace(0, 500, 100),
        2: np.linspace(0, 500, 100),
        3: np.linspace(0, 500, 100),
        4: np.linspace(0, 1500, 100),  # 3x longer
    })
    dq = assess_all_laps(laps)
    # Lap 4 should have a high zscore
    lap4 = [m for m in dq.metrics if m["lap_number"] == 4][0]
    assert lap4["lap_length_zscore"] > 2.0


def test_assess_flags_non_monotonic():
    """Lap with backward jumps -> needs_repair list populated."""
    from distance_integrity import assess_all_laps

    d_bad = np.linspace(0, 500, 100)
    # Introduce 10 backward jumps
    for i in range(10, 100, 9):
        d_bad[i] = d_bad[i] - 50
    laps = _make_lap_dict({
        1: np.linspace(0, 500, 100),
        2: d_bad,
    })
    dq = assess_all_laps(laps)
    assert 2 in dq.laps_repaired or 2 in dq.laps_degraded or dq.status != "ok"
