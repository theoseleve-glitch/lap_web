from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.events import extract_events


def test_invalid_laps_emit_events():
    summary = {"invalid_lap_analysis": {"invalid_laps": [3, 7], "reasons": {"3": "short", "7": "outlier"}}}
    evts = extract_events(summary)
    types = [e.event_type for e in evts]
    assert types.count("lap.invalid") == 2


def test_joker_detection_emits_event():
    summary = {"joker_detection_result": {"joker_lap": 5, "confidence": 0.82}}
    evts = extract_events(summary)
    joker_evts = [e for e in evts if e.event_type == "lap.joker"]
    assert len(joker_evts) == 1
    assert joker_evts[0].lap_number == 5
    assert joker_evts[0].payload.get("confidence") == 0.82


def test_unexpected_channel_emits_event():
    summary = {
        "available_channels": [
            "Latitude (deg)", "Longitude (deg)", "Speed (m/s)", "Throttle (%)",
        ],
    }
    evts = extract_events(summary)
    chan_evts = [e for e in evts if e.event_type == "capability.unexpected_channel"]
    assert len(chan_evts) == 1
    assert chan_evts[0].payload["channel"].lower().startswith("throttle")


def test_empty_summary_returns_empty_list():
    assert extract_events({}) == []
