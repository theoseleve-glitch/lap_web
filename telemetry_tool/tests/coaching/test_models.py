"""Tests for coaching.models — all dataclasses and to_dict() serialization."""
import pytest
from coaching.models import (
    BrakingBlock, TrailBrakeAssessment, ExitSpeedCascade, TractionBudget,
    ThrottleLiftEvent, Symptom, SymptomDetection, WeightTransferInsight,
    CornerTrend, CornerCoachingDetail, WarmUpProtocol,
    FocusArea, Drill, ProgressionInsight, SessionCoaching,
)


class TestBrakingBlock:
    def test_creation(self):
        b = BrakingBlock(
            block_id=3, name="trail_brake", s_start=100.0, s_end=120.0,
            duration_s=0.8, peak_decel_mps2=-8.5, overlap_m=20.0,
            trail_pct_at_turnin=45.0, release_rate_mps3=-12.0,
            release_linearity=0.85, transition_duration_s=None,
        )
        assert b.block_id == 3
        assert b.name == "trail_brake"

    def test_to_dict_roundtrip(self):
        b = BrakingBlock(
            block_id=1, name="throttle_to_brake", s_start=80.0, s_end=85.0,
            duration_s=0.15, peak_decel_mps2=None, overlap_m=None,
            trail_pct_at_turnin=None, release_rate_mps3=None,
            release_linearity=None, transition_duration_s=None,
        )
        d = b.to_dict()
        assert d["block_id"] == 1
        assert d["peak_decel_mps2"] is None


class TestTrailBrakeAssessment:
    def test_creation_with_trail(self):
        blocks = [
            BrakingBlock(i, f"b{i}", 0, 10, 0.5,
                         None, None, None, None, None, None)
            for i in range(1, 5)
        ]
        t = TrailBrakeAssessment(
            corner_id=3, blocks=blocks, overall_score=72.0,
            has_trail_braking=True, theoretical_overlap_m=15.0,
            actual_overlap_m=10.0, time_loss_from_no_trail_s=0.12,
            primary_issue=None,
        )
        assert t.has_trail_braking is True
        d = t.to_dict()
        assert len(d["blocks"]) == 4


class TestExitSpeedCascade:
    def test_cascade_ratio(self):
        e = ExitSpeedCascade(
            corner_id=5,
            actual_exit_speed_mps=20.0, theoretical_exit_speed_mps=23.0,
            exit_speed_delta_mps=3.0,
            straight_length_m=300.0,
            straight_end_speed_actual_mps=45.0,
            straight_end_speed_theoretical_mps=47.5,
            time_loss_in_corner_s=0.18,
            time_loss_on_straight_s=0.22,
            total_cascade_time_s=0.40,
            exit_gain_needed_kmh=10.8,
            straight_gain_resulting_kmh=9.0,
            cascade_ratio=1.22,
        )
        assert e.total_cascade_time_s == pytest.approx(0.40)
        d = e.to_dict()
        assert d["cascade_ratio"] == pytest.approx(1.22)


class TestTractionBudget:
    def test_remaining_pct(self):
        tb = TractionBudget(
            corner_id=2,
            entry_lateral_pct=40.0, entry_longitudinal_pct=60.0,
            entry_total_pct=72.1, entry_remaining_pct=27.9,
            apex_lateral_pct=85.0, apex_longitudinal_pct=5.0,
            apex_total_pct=85.1, apex_remaining_pct=14.9,
            exit_lateral_pct=50.0, exit_longitudinal_pct=45.0,
            exit_total_pct=67.3, exit_remaining_pct=32.7,
            theoretical_apex_total_pct=92.0, grip_headroom_pct=6.9,
        )
        assert tb.apex_remaining_pct == pytest.approx(14.9)


class TestThrottleLiftEvent:
    def test_creation_defaults(self):
        tl = ThrottleLiftEvent(
            corner_id=4, s_position=150.0,
            throttle_before_pct=80.0, throttle_after_pct=30.0,
            drop_pct=50.0, drop_duration_s=0.2,
            lateral_grip_at_lift_pct=70.0, weight_shift_estimate_kg=15.0,
        )
        assert tl.severity == "benign"
        assert tl.resulted_in_correction is False
        assert tl.yaw_rate_change_dps is None

    def test_to_dict_with_severity(self):
        tl = ThrottleLiftEvent(
            corner_id=4, s_position=150.0,
            throttle_before_pct=80.0, throttle_after_pct=30.0,
            drop_pct=50.0, drop_duration_s=0.2,
            lateral_grip_at_lift_pct=70.0, weight_shift_estimate_kg=15.0,
            severity="critical", resulted_in_correction=True,
            yaw_rate_change_dps=5.5,
        )
        d = tl.to_dict()
        assert d["severity"] == "critical"
        assert d["resulted_in_correction"] is True
        assert d["yaw_rate_change_dps"] == pytest.approx(5.5)


class TestSymptom:
    def test_to_dict_rounds_evidence(self):
        s = Symptom(
            symptom_id="early_brake", description="Braking too early",
            evidence={"delta_m": 12.3456, "ratio": 0.78912},
            confidence=0.915,
        )
        d = s.to_dict()
        assert d["evidence"]["delta_m"] == pytest.approx(12.346, abs=0.001)
        assert d["confidence"] == pytest.approx(0.92, abs=0.01)


class TestSymptomDetection:
    def test_nested_symptom_serialization(self):
        sd = SymptomDetection(
            corner_id=1,
            symptoms=[
                Symptom("s1", "test", {"x": 1.0}, 0.9),
                Symptom("s2", "test2", {"y": 2.0}, 0.8),
            ],
        )
        d = sd.to_dict()
        assert len(d["symptoms"]) == 2
        assert d["symptoms"][0]["symptom_id"] == "s1"


class TestWeightTransferInsight:
    def test_to_dict(self):
        wt = WeightTransferInsight(
            corner_id=3,
            entry_front_load_pct=62.0, entry_rear_load_pct=38.0,
            front_grip_bonus_pct=8.0, trail_brake_front_bonus_pct=12.0,
            exit_rear_load_pct=55.0, rear_grip_bonus_pct=6.0,
            insight_text="Trail braking loads the front tyres.",
        )
        d = wt.to_dict()
        assert d["entry_front_load_pct"] == 62.0
        assert d["insight_text"] == "Trail braking loads the front tyres."


class TestCornerTrend:
    def test_to_dict_with_estimate(self):
        ct = CornerTrend(
            sessions_tracked=5,
            apex_speed_history=[18.0, 18.5, 19.0, 19.2, 19.5],
            theoretical_apex=21.0,
            trend_direction="improving",
            trend_text="Gaining ~0.3 km/h per session",
            sessions_to_target_estimate=6,
        )
        d = ct.to_dict()
        assert len(d["apex_speed_history"]) == 5
        assert d["sessions_to_target_estimate"] == 6

    def test_to_dict_without_estimate(self):
        ct = CornerTrend(
            sessions_tracked=2,
            apex_speed_history=[18.0, 18.5],
            theoretical_apex=21.0,
            trend_direction="improving",
            trend_text="Too few sessions for projection",
        )
        d = ct.to_dict()
        assert d["sessions_to_target_estimate"] is None


class TestCornerCoachingDetail:
    def test_minimal_creation(self):
        ccd = CornerCoachingDetail(
            corner_id=1, corner_name="Turn 1",
            primary_cause="late_braking", cause_severity="moderate",
            cause_root="technique",
            symptom_evidence=["heavy braking at apex"],
            diagnosis_text="Braking too late causes understeer.",
            coaching_tip="Start braking 5m earlier.",
            progressive_steps=["Step 1", "Step 2", "Step 3"],
            symptom_check="Check apex speed > 50 km/h",
            time_loss_corner_s=0.15, time_loss_cascade_s=0.30,
        )
        d = ccd.to_dict()
        assert d["corner_id"] == 1
        assert d["traction_budget"] is None
        assert d["trail_brake"] is None
        assert d["trend"] is None

    def test_with_nested_physics(self):
        tb = TractionBudget(
            corner_id=1,
            entry_lateral_pct=40.0, entry_longitudinal_pct=60.0,
            entry_total_pct=72.0, entry_remaining_pct=28.0,
            apex_lateral_pct=85.0, apex_longitudinal_pct=5.0,
            apex_total_pct=85.0, apex_remaining_pct=15.0,
            exit_lateral_pct=50.0, exit_longitudinal_pct=45.0,
            exit_total_pct=67.0, exit_remaining_pct=33.0,
            theoretical_apex_total_pct=92.0, grip_headroom_pct=7.0,
        )
        ccd = CornerCoachingDetail(
            corner_id=1, corner_name="Turn 1",
            primary_cause="early_apex", cause_severity="mild",
            cause_root="line",
            symptom_evidence=["apex before geometric apex"],
            diagnosis_text="Turning in too early.",
            coaching_tip="Delay turn-in by 2m.",
            progressive_steps=["Step 1"],
            symptom_check="Watch for apex position",
            time_loss_corner_s=0.08, time_loss_cascade_s=0.12,
            traction_budget=tb,
        )
        d = ccd.to_dict()
        assert d["traction_budget"]["corner_id"] == 1
        assert d["traction_budget"]["apex_remaining_pct"] == 15.0


class TestWarmUpProtocol:
    def test_to_dict(self):
        wp = WarmUpProtocol(
            phase_1_laps=3, phase_1_instruction="Explore track at 70% pace",
            phase_2_laps=2, phase_2_instruction="Build to 85%",
            phase_3_instruction="Full push — focus on T3 and T7",
        )
        d = wp.to_dict()
        assert d["phase_1_laps"] == 3
        assert "70%" in d["phase_1_instruction"]


class TestFocusArea:
    def test_v1_compat_to_dict(self):
        fa = FocusArea(
            rank=1, category="braking", time_loss_s=0.45,
            corner_ids=[3, 7], summary="Late braking in T3, T7",
            advice="Brake 5m earlier",
        )
        d = fa.to_dict()
        assert "progressive_steps" not in d
        assert "symptom_diagnosis" not in d

    def test_v3_extensions_to_dict(self):
        fa = FocusArea(
            rank=1, category="braking", time_loss_s=0.45,
            corner_ids=[3, 7], summary="Late braking",
            advice="Brake earlier",
            progressive_steps=["Step 1", "Step 2", "Step 3"],
            symptom_diagnosis="Heavy trail braking detected",
        )
        d = fa.to_dict()
        assert d["progressive_steps"] == ["Step 1", "Step 2", "Step 3"]
        assert d["symptom_diagnosis"] == "Heavy trail braking detected"


class TestDrill:
    def test_v1_compat_to_dict(self):
        dr = Drill(
            rank=1, title="Brake Point Drill",
            description="Practice consistent brake points",
            focus_corners=[3], target_metric="brake_point_consistency",
            target_improvement="<5m variation", lap_count=5,
        )
        d = dr.to_dict()
        assert "difficulty" not in d
        assert "success_criteria" not in d

    def test_v3_extensions_to_dict(self):
        dr = Drill(
            rank=1, title="Brake Point Drill",
            description="Practice consistent brake points",
            focus_corners=[3], target_metric="brake_point_consistency",
            target_improvement="<5m variation", lap_count=5,
            difficulty="intermediate",
            success_criteria="3 consecutive laps within 2m",
            difficulty_progression={"beginner": "10m", "advanced": "1m"},
        )
        d = dr.to_dict()
        assert d["difficulty"] == "intermediate"
        assert d["success_criteria"] == "3 consecutive laps within 2m"


class TestProgressionInsight:
    def test_to_dict(self):
        pi = ProgressionInsight(
            metric="apex_speed", trend="improving",
            detail="Apex speed increased 2.5%",
            early_value=18.0, late_value=18.45, change_pct=2.5,
        )
        d = pi.to_dict()
        assert d["change_pct"] == pytest.approx(2.5)


class TestSessionCoaching:
    def test_backward_compat_to_dict(self):
        """Old fields must always be present; new fields appear only when set."""
        sc = SessionCoaching(
            session_theme="Good session",
            narrative="You drove well.",
            strengths=["pace"],
            weaknesses=["consistency"],
            focus_areas=[],
            drills=[],
            progression=[],
            next_session_goals=["Improve T3"],
            confidence=0.85,
        )
        d = sc.to_dict()
        # Old fields always present
        assert "session_theme" in d
        assert "narrative" in d
        assert "confidence" in d
        # New optional fields present but None
        assert d.get("corner_coaching") is None
        assert d.get("vehicle_class") is None

    def test_new_fields_serialized(self):
        sc = SessionCoaching(
            session_theme="t", narrative="n", strengths=[], weaknesses=[],
            focus_areas=[], drills=[], progression=[],
            next_session_goals=[], confidence=0.9,
            vehicle_class="kart",
            mental_imagery_prompts=["Imagine Turn 3..."],
        )
        d = sc.to_dict()
        assert d["vehicle_class"] == "kart"
        assert d["mental_imagery_prompts"] == ["Imagine Turn 3..."]

    def test_full_v3_session(self):
        """Full V3 session with nested objects serializes correctly."""
        wp = WarmUpProtocol(
            phase_1_laps=3, phase_1_instruction="Explore",
            phase_2_laps=2, phase_2_instruction="Build",
            phase_3_instruction="Push",
        )
        fa = FocusArea(
            rank=1, category="braking", time_loss_s=0.3,
            corner_ids=[1], summary="Late", advice="Earlier",
            progressive_steps=["A", "B"],
        )
        sc = SessionCoaching(
            session_theme="Focus on braking",
            narrative="Today's session showed...",
            strengths=["Good throttle control"],
            weaknesses=["Late braking"],
            focus_areas=[fa],
            drills=[],
            progression=[],
            next_session_goals=["Brake 5m earlier at T1"],
            confidence=0.88,
            warm_up_protocol=wp,
            vehicle_class="kart",
            deferred_focus_areas=[],
        )
        d = sc.to_dict()
        assert d["warm_up_protocol"]["phase_1_laps"] == 3
        assert d["focus_areas"][0]["progressive_steps"] == ["A", "B"]
        assert d["deferred_focus_areas"] == []
        assert d["vehicle_class"] == "kart"
