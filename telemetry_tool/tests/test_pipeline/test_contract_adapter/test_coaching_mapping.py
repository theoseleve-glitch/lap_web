from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.coaching import (
    _reshape_corner_coaching,
    _reshape_global_focus,
    _reshape_next_run,
    _reshape_storyline,
    _reshape_validation_checks,
    build_coaching_contract,
)


class FakeFocusItem:
    def __init__(self, rank, weakness_key, title, severity, estimated_cost_ms, corners, phase, confidence):
        self.rank = rank
        self.weakness_key = weakness_key
        self.title = title
        self.severity = severity
        self.estimated_cost_ms = estimated_cost_ms
        self.corners = corners
        self.phase = phase
        self.confidence = confidence


def test_global_focus_drops_phase_and_confidence():
    items = (FakeFocusItem(1, "late_brake", "Release earlier", "high", 520.0, (3, 7), "brake_release", 0.9),)
    out = _reshape_global_focus(items)
    assert out[0].rank == 1
    assert out[0].corner_ids == ["3", "7"]
    assert out[0].cost_ms == 520.0


class FakeStoryline:
    def __init__(self, type, text, confidence):
        self.type = type
        self.text = text
        self.confidence = confidence


def test_storyline_maps_type_to_state():
    entries = (
        FakeStoryline("primary_focus", "You brake too late", 0.9),
        FakeStoryline("insufficient_data", "Not enough data", 1.0),
        FakeStoryline("unregistered_weakness", "Unknown pattern", 0.5),
        FakeStoryline("weird_new_type", "Bizarre", 0.3),
    )
    out = _reshape_storyline(entries, focus_items=[])
    assert [s.state for s in out] == ["Detected", "Insufficient", "Unregistered", "NotTriggered"]
    assert out[3].detail == "weird_new_type"


def test_next_run_concatenates_instruction_and_validation():
    class FakeNR:
        def __init__(self, rank, type, title, corners, instruction, validation):
            self.rank = rank
            self.type = type
            self.title = title
            self.corners = corners
            self.instruction = instruction
            self.validation = validation
    items = (FakeNR(1, "technical_focus", "Trail brake drill", (3,), "Do X", "Measure Y"),)
    out = _reshape_next_run(items)
    assert out[0].item_type == "technical_focus"
    assert out[0].title == "Trail brake drill"
    assert "Do X" in out[0].body and "Measure Y" in out[0].body


def test_corner_coaching_reshape_one_cue_per_weakness():
    class FakeCorner:
        def __init__(self, corner_id, applicable_weaknesses, time_delta_ms, summary):
            self.corner_id = corner_id
            self.applicable_weaknesses = applicable_weaknesses
            self.time_delta_ms = time_delta_ms
            self.summary = summary

    class FakePlayMatch:
        def __init__(self, weakness_key, driver_cues, severity):
            self.weakness_key = weakness_key
            self.driver_cues = driver_cues
            self.severity = severity

    corners = (FakeCorner(3, ("late_brake",), 280.0, "short summary"),)
    matches = (FakePlayMatch("late_brake", ("Release brake ~10m earlier",), "high"),)
    out = _reshape_corner_coaching(corners, matches)
    assert "3" in out
    assert len(out["3"].items) == 1
    cue = out["3"].items[0]
    assert cue.weakness_key == "late_brake"
    assert cue.cue_text == "Release brake ~10m earlier"
    assert cue.severity == "high"


def test_validation_check_first_corner_or_none():
    class FakeVC:
        def __init__(self, weakness_key, metric_name, target_description, corners, measurement_method):
            self.weakness_key = weakness_key
            self.metric_name = metric_name
            self.target_description = target_description
            self.corners = corners
            self.measurement_method = measurement_method
    single = FakeVC("k", "Peak G", "> 1.2 G", (3,), "IMU")
    multi = FakeVC("k", "Peak G", "> 1.2 G", (3, 7), "IMU")
    o1 = _reshape_validation_checks((single,))
    o2 = _reshape_validation_checks((multi,))
    assert o1[0].corner_id == "3"
    assert o2[0].corner_id is None


def test_build_coaching_contract_integration_with_empty_sheet():
    """Empty sheet should produce a valid, empty CoachingContract."""
    from track_surface.prescriptive.types import CoachingSheet, Limits
    empty_limits = Limits(
        sessions_analyzed=0, laps_analyzed=0,
        brake_data="n/a", throttle_data="n/a", steering_data="n/a",
        cross_track_portability="n/a", weather_conditions="n/a",
        reference_basis="n/a", confidence_floor="n/a",
    )
    sheet = CoachingSheet.empty(empty_limits)
    contract = build_coaching_contract(summary={"corners": []}, sheet=sheet)
    assert contract.version == "1.0"
    assert len(contract.global_focus) == 0
    assert len(contract.corner_coaching) == 0
