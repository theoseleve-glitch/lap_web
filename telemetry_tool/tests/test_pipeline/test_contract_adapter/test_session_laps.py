from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.session import build_laps


def test_laps_preserve_order_and_mark_best():
    summary = {
        "lap_times": [60.1, 59.8, 60.3],
        "best_lap_key": 2,
        "invalid_lap_analysis": {"invalid_laps": [3]},
    }
    laps = build_laps(summary)
    assert [l.lap_number for l in laps] == [1, 2, 3]
    assert [l.lap_time_s for l in laps] == [60.1, 59.8, 60.3]
    assert [l.is_best for l in laps] == [False, True, False]
    assert [l.is_valid for l in laps] == [True, True, False]
    assert "invalid" in laps[2].flags


def test_lap_with_none_time_is_incomplete():
    summary = {"lap_times": [60.1, None], "best_lap_key": 1}
    laps = build_laps(summary)
    assert laps[1].lap_time_s is None
    assert "incomplete" in laps[1].flags
    assert laps[1].is_valid is False


def test_no_best_key_means_no_best():
    summary = {"lap_times": [60.1, 59.8], "best_lap_key": None}
    laps = build_laps(summary)
    assert not any(l.is_best for l in laps)
