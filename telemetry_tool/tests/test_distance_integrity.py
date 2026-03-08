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


def test_rebuild_distance_from_xy_euclidean():
    """Rebuild distance from x/y columns using Euclidean method."""
    from distance_integrity import rebuild_distance_from_xy

    # Simple right-angle path: 100m east then 100m north
    n = 50
    x = np.concatenate([np.linspace(0, 100, n), np.full(n, 100)])
    y = np.concatenate([np.zeros(n), np.linspace(0, 100, n)])
    df = pd.DataFrame({"x": x, "y": y, "Distance (m)": np.zeros(2 * n)})

    result = rebuild_distance_from_xy(df)
    assert "Distance (m)" in result.columns
    # Total distance should be ~200m
    total = result["Distance (m)"].iloc[-1]
    assert total == pytest.approx(200.0, rel=0.01)
    # Must be monotonically increasing
    diffs = np.diff(result["Distance (m)"].values)
    assert np.all(diffs >= 0)


def test_rebuild_distance_from_latlon():
    """Rebuild distance from Latitude/Longitude columns using Haversine."""
    from distance_integrity import rebuild_distance_from_xy

    # ~111m per degree at equator for latitude
    lat = np.linspace(0.0, 0.001, 100)  # ~111m
    lon = np.zeros(100)
    df = pd.DataFrame({
        "Latitude (deg)": lat,
        "Longitude (deg)": lon,
        "Distance (m)": np.zeros(100),
    })
    result = rebuild_distance_from_xy(df)
    total = result["Distance (m)"].iloc[-1]
    assert 100 < total < 120  # Haversine ~111m for 0.001 deg


def test_rebuild_returns_none_no_coords():
    """No coordinate columns → returns None."""
    from distance_integrity import rebuild_distance_from_xy

    df = pd.DataFrame({"Distance (m)": np.linspace(0, 100, 50)})
    result = rebuild_distance_from_xy(df)
    assert result is None


def test_isotonic_repair():
    """Isotonic regression forces monotonicity."""
    from distance_integrity import repair_distance_isotonic

    d = np.array([0, 10, 20, 15, 30, 25, 40, 50])  # two backward jumps
    result = repair_distance_isotonic(d)
    diffs = np.diff(result)
    assert np.all(diffs >= 0), "Must be non-decreasing after repair"
    assert result[0] == pytest.approx(0.0, abs=1.0)
    assert result[-1] == pytest.approx(50.0, abs=5.0)


def test_isotonic_preserves_monotonic():
    """Already-monotonic input is unchanged (within tolerance)."""
    from distance_integrity import repair_distance_isotonic

    d = np.linspace(0, 500, 100)
    result = repair_distance_isotonic(d)
    np.testing.assert_allclose(result, d, atol=1e-6)


def test_run_integrity_ok_laps():
    """Clean laps -> status='ok', no repair, no gate."""
    from distance_integrity import run_distance_integrity

    laps = _make_lap_dict({
        1: np.linspace(0, 500, 200),
        2: np.linspace(0, 498, 200),
    })
    result_laps, dq = run_distance_integrity(laps)
    assert dq.status == "ok"
    assert dq.gate_advanced is False
    assert dq.repair_method is None
    assert len(result_laps) == 2


def test_run_integrity_repairs_with_xy():
    """Non-monotonic lap with XY columns -> repaired via xy_rebuild."""
    from distance_integrity import run_distance_integrity

    d_bad = np.linspace(0, 500, 100)
    for i in range(10, 100, 8):
        d_bad[i] = d_bad[i] - 80  # severe backward jumps
    x = np.linspace(0, 500, 100)
    y = np.zeros(100)
    df = pd.DataFrame({"Distance (m)": d_bad, "x": x, "y": y, "Speed (m/s)": np.ones(100)})
    laps = {1: pd.DataFrame({"Distance (m)": np.linspace(0, 500, 100), "x": x, "y": y, "Speed (m/s)": np.ones(100)}), 2: df}

    result_laps, dq = run_distance_integrity(laps)
    assert dq.status == "repaired"
    assert dq.repair_method == "xy_rebuild"
    assert 2 in dq.laps_repaired
    # Repaired lap should now be monotonic
    repaired_d = result_laps[2]["Distance (m)"].values
    assert np.all(np.diff(repaired_d) >= 0)


def test_run_integrity_isotonic_fallback():
    """Non-monotonic lap without XY -> repaired via isotonic_regression."""
    from distance_integrity import run_distance_integrity

    d_bad = np.linspace(0, 500, 100)
    for i in range(10, 100, 8):
        d_bad[i] = d_bad[i] - 80
    df = pd.DataFrame({"Distance (m)": d_bad, "Speed (m/s)": np.ones(100)})
    laps = {1: pd.DataFrame({"Distance (m)": np.linspace(0, 500, 100), "Speed (m/s)": np.ones(100)}), 2: df}

    result_laps, dq = run_distance_integrity(laps)
    assert dq.status == "repaired"
    assert dq.repair_method == "isotonic_regression"
    assert 2 in dq.laps_repaired


def test_run_integrity_gate_on_severe_damage():
    """Distance so corrupted that even repair fails -> gate_advanced=True."""
    from distance_integrity import run_distance_integrity

    # All-zeros distance can't be repaired without coordinates
    d_bad = np.zeros(100)
    df = pd.DataFrame({"Distance (m)": d_bad, "Speed (m/s)": np.ones(100)})
    laps = {1: df}

    result_laps, dq = run_distance_integrity(laps)
    assert dq.gate_advanced is True
    assert dq.status == "degraded"
