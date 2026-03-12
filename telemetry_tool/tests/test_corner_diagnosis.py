"""Tests for corner diagnosis classifier and prerequisites."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestCornerEventsToDict:
    """Prerequisite: CornerEvents.to_dict() must exist for MRP serialisation."""

    def test_to_dict_returns_plain_dict(self):
        from mrp_detector import CornerEvents

        ev = CornerEvents(
            corner_id=1,
            brake_point_m=100.0,
            turn_in_m=110.0,
            trail_brake_end_m=120.0,
            mrp_m=130.0,
            mrp_speed_mps=25.0,
            mrp_yaw_rate=0.05,
            throttle_application_m=135.0,
            track_out_m=160.0,
            geometric_apex_m=125.0,
            mrp_apex_delta_m=5.0,
        )
        d = ev.to_dict()
        assert isinstance(d, dict)
        assert d["mrp_m"] == 130.0
        assert d["mrp_apex_delta_m"] == 5.0
        assert d["corner_id"] == 1

    def test_to_dict_handles_none_fields(self):
        from mrp_detector import CornerEvents

        ev = CornerEvents(
            corner_id=2,
            brake_point_m=None,
            turn_in_m=50.0,
            trail_brake_end_m=None,
            mrp_m=60.0,
            mrp_speed_mps=20.0,
            mrp_yaw_rate=0.03,
            throttle_application_m=None,
            track_out_m=80.0,
            geometric_apex_m=55.0,
            mrp_apex_delta_m=5.0,
        )
        d = ev.to_dict()
        assert d["brake_point_m"] is None
        assert d["throttle_application_m"] is None


class TestThresholdsAndTier:
    """Vehicle class thresholds and tier auto-detection."""

    def test_car_thresholds(self):
        from coaching.corner_diagnosis import _get_thresholds

        t = _get_thresholds("car")
        assert t["v_entry_delta_kmh"] == 3.0
        assert t["yaw_residual_dps"] == 10.0
        assert t["coast_gap_s"] == 0.3
        assert t["late_rotation_m"] == 8.0

    def test_kart_thresholds(self):
        from coaching.corner_diagnosis import _get_thresholds

        t = _get_thresholds("kart")
        assert t["v_entry_delta_kmh"] == 2.0
        assert t["yaw_residual_dps"] == 8.0
        assert t["coast_gap_s"] == 0.2
        assert t["late_rotation_m"] == 4.0

    def test_unknown_class_defaults_to_car(self):
        from coaching.corner_diagnosis import _get_thresholds

        t = _get_thresholds("unknown")
        assert t["v_entry_delta_kmh"] == 3.0

    def test_detect_tier_full(self):
        from coaching.corner_diagnosis import _detect_tier

        cols = {"Speed (m/s)", "Heading (rad)", "accel_lat_mps2", "Brake (%)"}
        assert _detect_tier(cols) == "full"

    def test_detect_tier_accel(self):
        from coaching.corner_diagnosis import _detect_tier

        cols = {"Speed (m/s)", "Heading (rad)", "accel_lat_mps2"}
        assert _detect_tier(cols) == "accel"

    def test_detect_tier_gps(self):
        from coaching.corner_diagnosis import _detect_tier

        cols = {"Speed (m/s)", "Heading (rad)"}
        assert _detect_tier(cols) == "gps"


def _make_lap_df(
    n=100, s_start=50.0, s_end=150.0, v_min_at=100.0,
    v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0,
    has_accel=False, has_pedals=False,
    yaw_residual_entry_dps=0.0,
    yaw_residual_apex_dps=0.0,
):
    """Build a synthetic lap DataFrame for a single corner segment."""
    dist = np.linspace(s_start, s_end, n)
    mid_idx = int(n * (v_min_at - s_start) / (s_end - s_start))
    mid_idx = max(1, min(n - 2, mid_idx))

    speed = np.concatenate([
        np.linspace(v_entry_mps, v_min_mps, mid_idx),
        np.linspace(v_min_mps, v_exit_mps, n - mid_idx),
    ])

    heading = np.linspace(0.0, np.pi / 2, n)

    data = {
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "Heading (rad)": heading,
    }

    if has_accel:
        dt = 0.1
        lon_g = np.gradient(speed, dt) / 9.81
        lat_g = np.full(n, 0.5)
        data["accel_long_mps2"] = lon_g * 9.81
        data["accel_lat_mps2"] = lat_g * 9.81

    if has_pedals:
        brake = np.zeros(n)
        brake[:mid_idx] = np.linspace(80, 0, mid_idx)
        throttle = np.zeros(n)
        throttle[mid_idx:] = np.linspace(0, 90, n - mid_idx)
        data["Brake (%)"] = brake
        data["Throttle (%)"] = throttle

    return pd.DataFrame(data)


def _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1):
    """Build a user corner dict."""
    return {
        "corner_index": corner_index,
        "s_entry": s_entry,
        "s_apex": s_apex,
        "s_exit": s_exit,
    }


def _make_curvature_profile(s_start=0.0, s_end=200.0, n=200):
    """Build a curvature profile DataFrame (left turn, positive curvature)."""
    dist = np.linspace(s_start, s_end, n)
    curv = np.full(n, 0.01)
    return pd.DataFrame({"distance_m": dist, "curvature_1pm": curv})


class TestSegmentExtraction:
    """Test _extract_corner_metrics: slicing + metric computation."""

    def test_basic_metrics(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        corner = _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0)
        curv = _make_curvature_profile()

        m = _extract_corner_metrics(lap_df, corner, curv, mrp_event=None)
        assert m is not None
        assert abs(m["v_entry_mps"] - 30.0) < 1.0
        assert abs(m["v_min_mps"] - 20.0) < 1.0
        assert abs(m["s_vmin"] - 100.0) < 10.0
        assert m["kappa_sign"] == 1.0

    def test_kappa_sign_from_heading_fallback(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df()
        corner = _make_corner()
        m = _extract_corner_metrics(lap_df, corner, curvature_profile=None, mrp_event=None)
        assert m["kappa_sign"] == 1.0

    def test_right_turn_kappa_sign(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df()
        lap_df["Heading (rad)"] = np.linspace(0.0, -np.pi / 2, len(lap_df))
        corner = _make_corner()
        m = _extract_corner_metrics(lap_df, corner, curvature_profile=None, mrp_event=None)
        assert m["kappa_sign"] == -1.0

    def test_mrp_event_fields_passed_through(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df()
        corner = _make_corner()
        mrp = {"mrp_m": 105.0, "mrp_apex_delta_m": 10.0, "geometric_apex_m": 95.0}
        m = _extract_corner_metrics(lap_df, corner, None, mrp_event=mrp)
        assert m["mrp_m"] == 105.0
        assert m["mrp_apex_delta_m"] == 10.0

    def test_empty_segment_returns_none(self):
        from coaching.corner_diagnosis import _extract_corner_metrics

        lap_df = _make_lap_df(s_start=50.0, s_end=150.0)
        corner = _make_corner(s_entry=500.0, s_apex=550.0, s_exit=600.0)
        m = _extract_corner_metrics(lap_df, corner, None, mrp_event=None)
        assert m is None


class TestEntryPhase:
    """Entry phase label detection."""

    def test_entry_overspeed(self):
        from coaching.corner_diagnosis import _check_entry_phase

        metrics = {"v_entry_mps": 30.0, "s_apex": 100.0, "s_entry": 50.0,
                   "kappa_sign": 1.0, "yaw_residual": None,
                   "lon_g": None, "lat_g": None, "brake": None, "d": np.linspace(50, 150, 100)}
        theo = {"v_entry_mps": 28.6}  # 30 - 28.6 = 1.4 m/s = 5.04 km/h
        thresholds = {"v_entry_delta_kmh": 3.0, "yaw_residual_dps": 10.0}
        labels = _check_entry_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "entry_overspeed" for c in labels)

    def test_entry_underspeed(self):
        from coaching.corner_diagnosis import _check_entry_phase

        metrics = {"v_entry_mps": 25.0, "s_apex": 100.0, "s_entry": 50.0,
                   "kappa_sign": 1.0, "yaw_residual": None,
                   "lon_g": None, "lat_g": None, "brake": None, "d": np.linspace(50, 150, 100)}
        theo = {"v_entry_mps": 27.0}  # 27 - 25 = 2 m/s = 7.2 km/h > 5 threshold
        thresholds = {"v_entry_delta_kmh": 3.0, "v_underspeed_delta_kmh": 5.0,
                      "yaw_residual_dps": 10.0}
        labels = _check_entry_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "entry_underspeed" for c in labels)

    def test_entry_oversteer_via_yaw(self):
        from coaching.corner_diagnosis import _check_entry_phase

        n = 100
        yaw_res = np.zeros(n)
        yaw_res[:50] = 15.0  # oversteer in entry half
        metrics = {"v_entry_mps": 28.0, "s_apex": 100.0, "s_entry": 50.0,
                   "kappa_sign": 1.0, "yaw_residual": yaw_res,
                   "lon_g": None, "lat_g": None, "brake": None,
                   "d": np.linspace(50, 150, n)}
        theo = {"v_entry_mps": 28.0}
        thresholds = {"v_entry_delta_kmh": 3.0, "v_underspeed_delta_kmh": 5.0,
                      "yaw_residual_dps": 10.0}
        labels = _check_entry_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "entry_oversteer" for c in labels)

    def test_no_labels_when_within_tolerance(self):
        from coaching.corner_diagnosis import _check_entry_phase

        metrics = {"v_entry_mps": 28.0, "s_apex": 100.0, "s_entry": 50.0,
                   "kappa_sign": 1.0, "yaw_residual": np.zeros(100),
                   "lon_g": None, "lat_g": None, "brake": None,
                   "d": np.linspace(50, 150, 100)}
        theo = {"v_entry_mps": 28.0}
        thresholds = {"v_entry_delta_kmh": 3.0, "v_underspeed_delta_kmh": 5.0,
                      "yaw_residual_dps": 10.0}
        labels = _check_entry_phase(metrics, theo, thresholds, "gps")
        assert len(labels) == 0


class TestApexPhase:
    """Apex/mid-corner phase label detection."""

    def test_low_min_speed(self):
        from coaching.corner_diagnosis import _check_apex_phase

        metrics = {"v_min_mps": 18.0, "s_vmin": 100.0, "s_apex": 100.0,
                   "s_entry": 50.0, "s_exit": 150.0, "v": np.full(100, 20.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None, "brake": None,
                   "throttle": None}
        theo = {"v_min_mps": 20.0}  # 20 - 18 = 2 m/s = 7.2 km/h > 4 threshold
        thresholds = {"v_min_delta_kmh": 4.0, "apex_offset_m": 5.0,
                      "yaw_residual_dps": 10.0, "coast_gap_s": 0.3}
        labels = _check_apex_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "low_min_speed" for c in labels)

    def test_early_apex(self):
        from coaching.corner_diagnosis import _check_apex_phase

        metrics = {"v_min_mps": 20.0, "s_vmin": 90.0, "s_apex": 100.0,
                   "s_entry": 50.0, "s_exit": 150.0, "v": np.full(100, 20.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None, "brake": None,
                   "throttle": None}
        theo = {"v_min_mps": 20.0}
        thresholds = {"v_min_delta_kmh": 4.0, "apex_offset_m": 5.0,
                      "yaw_residual_dps": 10.0, "coast_gap_s": 0.3}
        labels = _check_apex_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "early_apex" for c in labels)

    def test_late_apex(self):
        from coaching.corner_diagnosis import _check_apex_phase

        metrics = {"v_min_mps": 20.0, "s_vmin": 112.0, "s_apex": 100.0,
                   "s_entry": 50.0, "s_exit": 150.0, "v": np.full(100, 20.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None, "brake": None,
                   "throttle": None}
        theo = {"v_min_mps": 20.0}
        thresholds = {"v_min_delta_kmh": 4.0, "apex_offset_m": 5.0,
                      "yaw_residual_dps": 10.0, "coast_gap_s": 0.3}
        labels = _check_apex_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "late_apex" for c in labels)

    def test_coast_hesitation_gps_tier(self):
        from coaching.corner_diagnosis import _check_apex_phase

        n = 100
        d = np.linspace(50, 150, n)
        v = np.concatenate([
            np.linspace(30, 20, 30),
            np.full(40, 20.0),
            np.linspace(20, 28, 30),
        ])
        metrics = {"v_min_mps": 20.0, "s_vmin": 100.0, "s_apex": 100.0,
                   "s_entry": 50.0, "s_exit": 150.0, "v": v, "d": d,
                   "kappa_sign": 1.0, "yaw_residual": None,
                   "lon_g": None, "brake": None, "throttle": None}
        theo = {"v_min_mps": 20.0}
        thresholds = {"v_min_delta_kmh": 4.0, "apex_offset_m": 5.0,
                      "yaw_residual_dps": 10.0, "coast_gap_s": 0.3}
        labels = _check_apex_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "coast_hesitation" for c in labels)


class TestExitPhase:
    """Exit phase label detection."""

    def test_late_rotation_from_mrp(self):
        from coaching.corner_diagnosis import _check_exit_phase

        metrics = {"s_apex": 100.0, "s_exit": 150.0, "s_vmin": 100.0,
                   "v_exit_mps": 28.0, "v": np.full(100, 25.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None,
                   "brake": None, "throttle": None,
                   "mrp_m": 115.0, "mrp_apex_delta_m": 10.0}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "late_rotation_m": 8.0,
                      "yaw_residual_dps": 10.0, "exit_yaw_understeer_dps": 8.0}
        labels = _check_exit_phase(metrics, theo, thresholds, "gps")
        assert any(c.label == "late_rotation" for c in labels)

    def test_late_rotation_not_fired_below_threshold(self):
        from coaching.corner_diagnosis import _check_exit_phase

        metrics = {"s_apex": 100.0, "s_exit": 150.0, "s_vmin": 100.0,
                   "v_exit_mps": 28.0, "v": np.full(100, 25.0),
                   "d": np.linspace(50, 150, 100), "kappa_sign": 1.0,
                   "yaw_residual": None, "lon_g": None,
                   "brake": None, "throttle": None,
                   "mrp_m": 105.0, "mrp_apex_delta_m": 5.0}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "late_rotation_m": 8.0,
                      "yaw_residual_dps": 10.0, "exit_yaw_understeer_dps": 8.0}
        labels = _check_exit_phase(metrics, theo, thresholds, "gps")
        assert not any(c.label == "late_rotation" for c in labels)

    def test_early_throttle_with_mrp_reference(self):
        from coaching.corner_diagnosis import _check_exit_phase

        n = 100
        d = np.linspace(50, 150, n)
        throttle = np.zeros(n)
        throttle_start_idx = np.searchsorted(d, 95.0)
        throttle[throttle_start_idx:] = 60.0

        metrics = {"s_apex": 100.0, "s_exit": 150.0, "s_vmin": 100.0,
                   "v_exit_mps": 28.0, "v": np.full(n, 25.0), "d": d,
                   "kappa_sign": 1.0, "yaw_residual": None, "lon_g": None,
                   "brake": None, "throttle": throttle,
                   "mrp_m": 110.0, "mrp_apex_delta_m": 5.0}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "late_rotation_m": 8.0,
                      "yaw_residual_dps": 10.0, "exit_yaw_understeer_dps": 8.0}
        labels = _check_exit_phase(metrics, theo, thresholds, "full")
        assert any(c.label == "early_throttle" for c in labels)

    def test_throttle_lift(self):
        from coaching.corner_diagnosis import _check_exit_phase

        n = 100
        d = np.linspace(50, 150, n)
        throttle = np.zeros(n)
        throttle[50:70] = 80
        throttle[70:80] = 50  # 30% drop
        throttle[80:] = 80

        metrics = {"s_apex": 100.0, "s_exit": 150.0, "s_vmin": 100.0,
                   "v_exit_mps": 28.0, "v": np.full(n, 25.0), "d": d,
                   "kappa_sign": 1.0, "yaw_residual": None, "lon_g": None,
                   "brake": None, "throttle": throttle,
                   "mrp_m": None, "mrp_apex_delta_m": None}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "late_rotation_m": 8.0,
                      "yaw_residual_dps": 10.0, "exit_yaw_understeer_dps": 8.0}
        labels = _check_exit_phase(metrics, theo, thresholds, "full")
        assert any(c.label == "throttle_lift" for c in labels)


class TestOverallPhase:
    """Overall label detection: good, slow_exit, scrappy."""

    def test_slow_exit(self):
        from coaching.corner_diagnosis import _check_overall

        metrics = {"v_exit_mps": 22.0, "yaw_residual": np.zeros(100),
                   "throttle": None}
        theo = {"v_exit_mps": 24.0}  # 2 m/s = 7.2 km/h > 5 threshold
        thresholds = {"v_exit_delta_kmh": 5.0, "good_time_tol_s": 0.15,
                      "yaw_residual_dps": 10.0}
        existing = []
        labels = _check_overall(metrics, theo, thresholds, existing)
        assert any(c.label == "slow_exit" for c in labels)

    def test_slow_exit_suppressed_when_entry_cause_exists(self):
        from coaching.corner_diagnosis import _check_overall, Candidate

        metrics = {"v_exit_mps": 22.0, "yaw_residual": np.zeros(100),
                   "throttle": None}
        theo = {"v_exit_mps": 24.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "good_time_tol_s": 0.15,
                      "yaw_residual_dps": 10.0}
        existing = [Candidate("entry_overspeed", 2, "entry")]
        labels = _check_overall(metrics, theo, thresholds, existing)
        assert not any(c.label == "slow_exit" for c in labels)

    def test_scrappy(self):
        from coaching.corner_diagnosis import _check_overall

        yaw = np.zeros(100)
        yaw[10:20] = 15
        yaw[20:30] = -15
        yaw[30:40] = 15
        yaw[40:50] = -15
        metrics = {"v_exit_mps": 28.0, "yaw_residual": yaw, "throttle": None}
        theo = {"v_exit_mps": 28.0}
        thresholds = {"v_exit_delta_kmh": 5.0, "good_time_tol_s": 0.15,
                      "yaw_residual_dps": 10.0}
        labels = _check_overall(metrics, theo, thresholds, [])
        assert any(c.label == "scrappy" for c in labels)


class TestCausalResolution:
    """Causal chain resolution and dominant label picking."""

    def test_entry_overspeed_is_root_of_entry_understeer(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("entry_overspeed", 2, "entry"),
            Candidate("entry_understeer", 2, "entry"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "entry_overspeed"

    def test_safety_label_wins_over_time_loss(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("entry_overspeed", 2, "entry"),
            Candidate("exit_oversteer", 1, "exit"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "exit_oversteer"

    def test_good_when_no_candidates(self):
        from coaching.corner_diagnosis import _resolve_and_pick

        label = _resolve_and_pick([])
        assert label == "good"

    def test_early_apex_is_root_over_slow_exit(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("early_apex", 2, "apex"),
            Candidate("slow_exit", 3, "overall"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "early_apex"

    def test_late_rotation_is_root_over_slow_exit(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("late_rotation", 2, "exit"),
            Candidate("slow_exit", 3, "overall"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "late_rotation"

    def test_early_throttle_is_root_of_exit_understeer(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("early_throttle", 2, "exit"),
            Candidate("exit_understeer", 2, "exit"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "early_throttle"

    def test_coast_hesitation_chain(self):
        from coaching.corner_diagnosis import _resolve_and_pick, Candidate

        candidates = [
            Candidate("coast_hesitation", 3, "apex"),
            Candidate("late_throttle", 3, "exit"),
        ]
        label = _resolve_and_pick(candidates)
        assert label == "coast_hesitation"


class TestClassifyAllCorners:
    """End-to-end classify_all_corners tests."""

    def test_basic_grid_shape(self):
        from coaching.corner_diagnosis import classify_all_corners

        lap_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        corners = [_make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1)]
        theo_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)

        result = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=theo_df,
            user_corners=corners,
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        assert "2" in result
        assert "1" in result["2"]
        assert isinstance(result["2"]["1"], str)

    def test_multiple_laps_and_corners(self):
        from coaching.corner_diagnosis import classify_all_corners

        lap_df_fast = _make_lap_df(v_entry_mps=33.0, v_min_mps=20.0, v_exit_mps=28.0)
        lap_df_good = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        theo = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)

        corners = [
            _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1),
        ]
        result = classify_all_corners(
            resampled_laps={2: lap_df_fast, 3: lap_df_good},
            theoretical_lap=theo,
            user_corners=corners,
            vehicle_class="car",
            valid_lap_numbers=[2, 3],
        )
        assert "2" in result and "3" in result
        assert result["2"]["1"] == "entry_overspeed"

    def test_empty_corners_returns_empty(self):
        from coaching.corner_diagnosis import classify_all_corners

        result = classify_all_corners(
            resampled_laps={2: _make_lap_df()},
            theoretical_lap=_make_lap_df(),
            user_corners=[],
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        assert result == {}

    def test_no_theoretical_returns_null_labels(self):
        from coaching.corner_diagnosis import classify_all_corners

        corners = [_make_corner()]
        result = classify_all_corners(
            resampled_laps={2: _make_lap_df()},
            theoretical_lap=None,
            user_corners=corners,
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        assert "2" in result

    def test_kart_thresholds_applied(self):
        from coaching.corner_diagnosis import classify_all_corners

        v_over = 30.0 + 2.5 / 3.6
        lap_df = _make_lap_df(v_entry_mps=v_over, v_min_mps=20.0, v_exit_mps=28.0)
        theo = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        corners = [_make_corner()]

        result_kart = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=theo,
            user_corners=corners,
            vehicle_class="kart",
            valid_lap_numbers=[2],
        )
        result_car = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=theo,
            user_corners=corners,
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        assert result_kart["2"]["1"] == "entry_overspeed"
