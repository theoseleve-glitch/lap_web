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
