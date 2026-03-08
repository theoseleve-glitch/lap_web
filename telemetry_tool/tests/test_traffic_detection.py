"""Tests for traffic detection module."""
import numpy as np
import pandas as pd
import pytest


def test_traffic_event_fields():
    """TrafficEvent has all required fields."""
    from traffic_detection import TrafficEvent

    ev = TrafficEvent(
        lap_number=3,
        s_start=100.0,
        s_end=200.0,
        speed_deficit_pct=8.5,
        max_decel_mps2=-1.2,
    )
    assert ev.lap_number == 3
    assert ev.s_end - ev.s_start == 100.0
    d = ev.to_dict()
    assert "lap_number" in d
    assert "speed_deficit_pct" in d


def test_traffic_result_fields():
    """TrafficResult has required fields and to_dict()."""
    from traffic_detection import TrafficEvent, TrafficResult

    ev = TrafficEvent(1, 50.0, 100.0, 6.0, -0.8)
    result = TrafficResult(
        straights=[{"s_start": 0.0, "s_end": 200.0, "length_m": 200.0}],
        events=[ev],
        per_lap_score={1: 0.25},
        n_laps_affected=1,
    )
    assert result.n_laps_affected == 1
    d = result.to_dict()
    assert "events" in d
    assert "per_lap_score" in d
    assert isinstance(d["events"], list)


def test_traffic_result_empty():
    """TrafficResult with no events."""
    from traffic_detection import TrafficResult

    result = TrafficResult(
        straights=[],
        events=[],
        per_lap_score={},
        n_laps_affected=0,
    )
    d = result.to_dict()
    assert d["n_laps_affected"] == 0
    assert len(d["events"]) == 0


def _make_oval_lap(n=500, straight_len=200.0, corner_radius=30.0, speed=20.0):
    """Synthetic oval: two straights + two corners.

    Layout: straight1 (0–200m) → corner1 (200–294m) → straight2 (294–494m)
    → corner2 (494–588m). Total ~588m.
    """
    rng = np.random.default_rng(42)

    # Straight 1: heading = 0 (east)
    s1_dist = np.linspace(0, straight_len, n // 4)
    s1_hdg = np.zeros(len(s1_dist))

    # Corner 1: 180° turn (pi radians over semi-circle)
    arc_len = np.pi * corner_radius
    c1_dist = np.linspace(0, arc_len, n // 4) + straight_len
    c1_hdg = np.linspace(0, np.pi, len(c1_dist))

    # Straight 2: heading = pi (west)
    s2_start = straight_len + arc_len
    s2_dist = np.linspace(0, straight_len, n // 4) + s2_start
    s2_hdg = np.full(len(s2_dist), np.pi)

    # Corner 2: 180° turn back
    c2_start = s2_start + straight_len
    c2_dist = np.linspace(0, arc_len, n // 4) + c2_start
    c2_hdg = np.linspace(np.pi, 2 * np.pi, len(c2_dist))

    all_dist = np.concatenate([s1_dist, c1_dist, s2_dist, c2_dist])
    all_hdg = np.concatenate([s1_hdg, c1_hdg, s2_hdg, c2_hdg])

    df = pd.DataFrame({
        "Distance (m)": all_dist,
        "Speed (m/s)": np.full(len(all_dist), speed) + rng.normal(0, 0.2, len(all_dist)),
        "Bearing (deg)": np.degrees(all_hdg) % 360,
        "accel_long_mps2": rng.normal(0, 0.1, len(all_dist)),
        "yaw_rate_dps": np.zeros(len(all_dist)),
    })
    # Compute yaw_rate from heading changes
    dt = np.diff(all_dist) / speed
    dhdg = np.diff(all_hdg)
    yr = np.concatenate([[0], dhdg / np.where(dt > 0, dt, 0.01)])
    df["yaw_rate_dps"] = np.degrees(yr)

    return df


def test_detect_straights_oval():
    """Oval track with 2 straights → detects 2 straight segments."""
    from traffic_detection import detect_straights

    df = _make_oval_lap()
    straights = detect_straights(df)
    assert len(straights) >= 2
    for s in straights:
        assert s["length_m"] >= 30.0
        assert s["s_end"] > s["s_start"]


def test_detect_straights_circle():
    """Constant-radius circle → no straights detected."""
    from traffic_detection import detect_straights

    n = 300
    radius = 50.0
    speed = 15.0
    omega = speed / radius
    t = np.arange(n) * 0.1
    theta = omega * t
    dist = speed * t

    df = pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": np.full(n, speed),
        "Bearing (deg)": np.degrees(theta) % 360,
        "accel_long_mps2": np.zeros(n),
        "yaw_rate_dps": np.full(n, np.degrees(omega)),
    })
    straights = detect_straights(df)
    assert len(straights) == 0


def test_traffic_flag_injected_lift():
    """Lap with injected speed lift on straight → flagged as traffic."""
    from traffic_detection import run_traffic_detection

    # Create 5 identical laps on an oval
    base = _make_oval_lap(speed=25.0)
    laps = {}
    for i in range(1, 6):
        laps[i] = base.copy()

    # Inject traffic lift on lap 3: drop speed by 30% on first straight (50-150m)
    lap3 = laps[3].copy()
    dist = lap3["Distance (m)"].values
    mask = (dist >= 50) & (dist <= 150)
    lap3.loc[mask, "Speed (m/s)"] = lap3.loc[mask, "Speed (m/s)"] * 0.7
    lap3.loc[mask, "accel_long_mps2"] = -2.0  # hard decel
    laps[3] = lap3

    result = run_traffic_detection(laps)
    assert result.n_laps_affected >= 1
    assert 3 in result.per_lap_score
    assert result.per_lap_score[3] > 0.0

    # Other laps should have low/zero traffic scores
    for lap_num in [1, 2, 4, 5]:
        assert result.per_lap_score.get(lap_num, 0.0) < 0.1


def test_clean_laps_no_traffic():
    """All identical laps → zero traffic on all."""
    from traffic_detection import run_traffic_detection

    base = _make_oval_lap(speed=20.0)
    laps = {i: base.copy() for i in range(1, 6)}

    result = run_traffic_detection(laps)
    assert result.n_laps_affected == 0
    for score in result.per_lap_score.values():
        assert score == 0.0
