"""Tests for progressive coach — goals, warm-up, late apex reset."""
import pytest
from telemetry_tool.coaching.composers.progressive_coach import (
    generate_warm_up, generate_next_session_goals, generate_late_apex_reset,
)
from telemetry_tool.coaching.models import FocusArea, WarmUpProtocol, CornerTrend


def _fa(rank, category, corners, steps=None):
    return FocusArea(
        rank=rank, category=category, time_loss_s=0.3,
        corner_ids=corners, summary=f"{category} issue", advice="Fix it",
        progressive_steps=steps,
    )


class TestWarmUp:
    def test_kart_warm_up(self):
        wp = generate_warm_up([_fa(1, "braking", [3, 7])], vehicle_class="kart")
        assert isinstance(wp, WarmUpProtocol)
        assert wp.phase_1_laps == 2
        assert "T3" in wp.phase_3_instruction

    def test_car_warm_up(self):
        wp = generate_warm_up([_fa(1, "exit", [5])], vehicle_class="car")
        assert wp.phase_1_laps == 3
        assert "T5" in wp.phase_3_instruction

    def test_no_focus_areas(self):
        wp = generate_warm_up([], vehicle_class="car")
        assert "clean" in wp.phase_3_instruction.lower() or "full" in wp.phase_3_instruction.lower()


class TestNextSessionGoals:
    def test_generates_goals_from_focus(self):
        areas = [_fa(1, "braking", [3], steps=["Brake 2m later", "Hold trail", "Full commit"])]
        goals = generate_next_session_goals(areas)
        assert len(goals) >= 1
        assert "braking" in goals[0].lower() or "Brake" in goals[0]

    def test_max_four_goals(self):
        areas = [_fa(i, f"cat{i}", [i], steps=[f"Step {i}"]) for i in range(5)]
        goals = generate_next_session_goals(areas)
        assert len(goals) <= 4

    def test_empty_areas_gives_baseline(self):
        goals = generate_next_session_goals([])
        assert len(goals) >= 1


class TestLateApexReset:
    def test_triggered_on_regression(self):
        trends = [
            CornerTrend(3, [20, 19, 18], 22, "regressing", "Apex speed dropping"),
            CornerTrend(3, [25, 24, 23], 27, "regressing", "Exit speed dropping"),
        ]
        reset = generate_late_apex_reset(trends)
        assert reset is not None
        assert "late" in reset.lower() or "Late" in reset

    def test_not_triggered_when_improving(self):
        trends = [
            CornerTrend(3, [18, 19, 20], 22, "improving", "Gaining speed"),
        ]
        reset = generate_late_apex_reset(trends)
        assert reset is None

    def test_not_triggered_on_empty(self):
        assert generate_late_apex_reset(None) is None
        assert generate_late_apex_reset([]) is None
