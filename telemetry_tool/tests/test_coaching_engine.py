"""Tests for the AI coaching engine — narrative synthesis and drill generation."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coaching_engine import (
    generate_session_coaching,
    _aggregate_focus_areas,
    _analyze_progression,
    _classify_session_theme,
    _generate_drills,
    SessionCoaching,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sample_corners():
    return [
        {"corner_id": 1, "primary_cause": "early_braking", "time_loss_total_s": 0.120, "s_start": 50},
        {"corner_id": 2, "primary_cause": "low_apex_speed", "time_loss_total_s": 0.080, "s_start": 150},
        {"corner_id": 3, "primary_cause": "slow_exit", "time_loss_total_s": 0.200, "s_start": 300},
        {"corner_id": 4, "primary_cause": "early_braking", "time_loss_total_s": 0.090, "s_start": 450},
        {"corner_id": 5, "primary_cause": "slow_exit", "time_loss_total_s": 0.150, "s_start": 600},
    ]


@pytest.fixture
def sample_scores():
    return {
        "total_score": 72,
        "grade": "B+",
        "sub_scores": {
            "pace": {"score": 20, "pct": 80},
            "consistency": {"score": 15, "pct": 60},
            "execution": {"score": 19, "pct": 76},
            "robustness": {"score": 18, "pct": 72},
        },
    }


@pytest.fixture
def sample_lap_metrics():
    return [
        {"lap_time_s": 65.2, "speed_max_mps": 42.0},
        {"lap_time_s": 64.8, "speed_max_mps": 42.1},
        {"lap_time_s": 64.1, "speed_max_mps": 42.3},
        {"lap_time_s": 63.5, "speed_max_mps": 42.5},
        {"lap_time_s": 63.2, "speed_max_mps": 42.4},
        {"lap_time_s": 63.0, "speed_max_mps": 42.6},
    ]


@pytest.fixture
def sample_coaching_v2():
    return {
        "confirmations": [
            {"corner_id": 2, "text": "Corner 2: excellent apex speed, well driven", "confidence": 0.9},
        ],
        "corrections": [
            {"corner_id": 3, "text": "Corner 3: get on throttle 5m earlier", "confidence": 0.85},
        ],
        "objectives": [
            {"rank": 1, "text": "Reduce exit time loss by 0.15s at corners 3 and 5"},
            {"rank": 2, "text": "Maintain brake point consistency within 2m"},
        ],
    }


@pytest.fixture
def sample_driving_style():
    return {
        "style_label": "Aggressive Attack",
        "style_confidence": 0.75,
        "strengths": ["Late braking commitment", "High apex speeds"],
        "weaknesses": ["Exit traction management"],
    }


# ── Focus area aggregation ────────────────────────────────────────

class TestFocusAreas:
    def test_groups_by_category(self, sample_corners):
        areas = _aggregate_focus_areas(sample_corners)
        cats = [a.category for a in areas]
        assert "exit_traction" in cats
        assert "braking" in cats

    def test_ranked_by_time_loss(self, sample_corners):
        areas = _aggregate_focus_areas(sample_corners)
        losses = [a.time_loss_s for a in areas]
        assert losses == sorted(losses, reverse=True)

    def test_exit_traction_highest(self, sample_corners):
        areas = _aggregate_focus_areas(sample_corners)
        assert areas[0].category == "exit_traction"
        assert abs(areas[0].time_loss_s - 0.350) < 0.001

    def test_corner_ids_collected(self, sample_corners):
        areas = _aggregate_focus_areas(sample_corners)
        exit_area = next(a for a in areas if a.category == "exit_traction")
        assert 3 in exit_area.corner_ids
        assert 5 in exit_area.corner_ids

    def test_tiny_losses_ignored(self):
        corners = [{"corner_id": 1, "primary_cause": "early_braking", "time_loss_total_s": 0.005}]
        areas = _aggregate_focus_areas(corners)
        assert len(areas) == 0

    def test_max_five_areas(self):
        corners = [
            {"corner_id": i, "primary_cause": cause, "time_loss_total_s": 0.1}
            for i, cause in enumerate(
                ["early_braking", "low_apex_speed", "slow_exit", "poor_line",
                 "grip_limited", "traction_limited", "late_braking"], 1
            )
        ]
        areas = _aggregate_focus_areas(corners)
        assert len(areas) <= 5


# ── Progression analysis ─────────────────────────────────────────

class TestProgression:
    def test_improving_trend_detected(self, sample_lap_metrics):
        insights = _analyze_progression(sample_lap_metrics)
        time_insight = next(p for p in insights if p.metric == "lap_time_s")
        assert time_insight.trend == "improving"
        assert time_insight.change_pct < 0

    def test_stable_trend(self):
        metrics = [{"lap_time_s": 60.0, "speed_max_mps": 40.0}] * 6
        insights = _analyze_progression(metrics)
        time_insight = next(p for p in insights if p.metric == "lap_time_s")
        assert time_insight.trend == "stable"

    def test_too_few_laps_returns_empty(self):
        insights = _analyze_progression([{"lap_time_s": 60.0}])
        assert len(insights) == 0

    def test_empty_input(self):
        assert _analyze_progression([]) == []
        assert _analyze_progression(None) == []


# ── Drill generation ──────────────────────────────────────────────

class TestDrills:
    def test_generates_drills_for_top_areas(self, sample_corners):
        areas = _aggregate_focus_areas(sample_corners)
        drills = _generate_drills(areas)
        assert len(drills) >= 1
        assert drills[0].rank == 1
        assert drills[0].focus_corners

    def test_max_three_drills(self):
        areas = [
            type("FA", (), {"category": c, "corner_ids": [1], "time_loss_s": 0.1})()
            for c in ["braking", "apex_speed", "exit_traction", "line", "consistency"]
        ]
        drills = _generate_drills(areas)
        assert len(drills) <= 3


# ── Session theme ─────────────────────────────────────────────────

class TestSessionTheme:
    def test_outstanding_session(self):
        scores = {"total_score": 90, "grade": "A+", "sub_scores": {
            "pace": {"score": 23}, "consistency": {"score": 23}
        }}
        theme = _classify_session_theme(scores, [], [])
        assert "Outstanding" in theme

    def test_fast_inconsistent(self):
        scores = {"total_score": 65, "grade": "B", "sub_scores": {
            "pace": {"score": 22}, "consistency": {"score": 12}
        }}
        theme = _classify_session_theme(scores, [], [])
        assert "inconsistent" in theme.lower()

    def test_consistent_slow(self):
        scores = {"total_score": 65, "grade": "B", "sub_scores": {
            "pace": {"score": 12}, "consistency": {"score": 22}
        }}
        theme = _classify_session_theme(scores, [], [])
        assert "pace" in theme.lower()


# ── Full coaching generation ──────────────────────────────────────

class TestGenerateSessionCoaching:
    def test_returns_session_coaching(self, sample_corners, sample_scores):
        result = generate_session_coaching(corners=sample_corners, scores=sample_scores)
        assert isinstance(result, SessionCoaching)

    def test_has_all_fields(self, sample_corners, sample_scores, sample_lap_metrics,
                            sample_coaching_v2, sample_driving_style):
        result = generate_session_coaching(
            corners=sample_corners,
            scores=sample_scores,
            lap_metrics=sample_lap_metrics,
            coaching_v2=sample_coaching_v2,
            driving_style=sample_driving_style,
        )
        assert result.session_theme
        assert result.narrative
        assert len(result.focus_areas) > 0
        assert len(result.drills) > 0
        assert len(result.next_session_goals) > 0
        assert result.confidence > 0

    def test_to_dict_serializable(self, sample_corners, sample_scores, sample_lap_metrics):
        result = generate_session_coaching(
            corners=sample_corners,
            scores=sample_scores,
            lap_metrics=sample_lap_metrics,
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "session_theme" in d
        assert "focus_areas" in d
        assert "drills" in d
        assert "progression" in d
        assert "next_session_goals" in d
        assert isinstance(d["focus_areas"], list)
        assert isinstance(d["drills"], list)

    def test_narrative_includes_score(self, sample_corners, sample_scores):
        result = generate_session_coaching(corners=sample_corners, scores=sample_scores)
        assert "72/100" in result.narrative

    def test_narrative_includes_driving_style(self, sample_corners, sample_scores, sample_driving_style):
        result = generate_session_coaching(
            corners=sample_corners,
            scores=sample_scores,
            driving_style=sample_driving_style,
        )
        assert "Aggressive Attack" in result.narrative

    def test_progression_included(self, sample_corners, sample_scores, sample_lap_metrics):
        result = generate_session_coaching(
            corners=sample_corners,
            scores=sample_scores,
            lap_metrics=sample_lap_metrics,
        )
        assert len(result.progression) > 0
        assert any(p.metric == "lap_time_s" for p in result.progression)

    def test_confidence_degrades_with_missing_data(self, sample_corners):
        # No coaching_v2, no lap_metrics, no driving_style
        result = generate_session_coaching(corners=sample_corners)
        assert result.confidence < 0.7

    def test_empty_corners(self):
        result = generate_session_coaching(corners=[])
        assert result.session_theme
        assert result.confidence < 0.5

    def test_goals_from_coaching_v2(self, sample_corners, sample_scores, sample_coaching_v2):
        result = generate_session_coaching(
            corners=sample_corners,
            scores=sample_scores,
            coaching_v2=sample_coaching_v2,
        )
        # Should include objectives from coaching_v2
        assert any("exit" in g.lower() or "brake" in g.lower() for g in result.next_session_goals)

    def test_strengths_include_high_scores(self, sample_corners, sample_scores):
        result = generate_session_coaching(corners=sample_corners, scores=sample_scores)
        # Pace is 80% → should be a strength
        assert any("Pace" in s for s in result.strengths)
