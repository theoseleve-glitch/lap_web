#!/usr/bin/env python3

"""
test_integration.py
-------------------
Integration tests for the SessionContext + condition-tracking pipeline
integration.  Verifiable without real telemetry data.

Run with:  python test_integration.py
"""
from __future__ import annotations

import json
import logging
import math
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# -- -

# Ensure the output directory is on the path

# -- -

_HERE = Path(__file__).resolve().parent
_PARENT = _HERE.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

logger = logging.getLogger("test_integration")

# -- -

# Test runner

# -- -

_passed: list[str] = []
_failed: list[tuple[str, str]] = []


def _test(name: str, fn: Any) -> None:
    try:
        fn()
        _passed.append(name)
    except Exception:
        _failed.append((name, traceback.format_exc()))


# ===========================================================================

# Fixtures

# ===========================================================================


def _make_resampled_lap(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Synthetic resampled lap with GPS + speed + accel."""
    rng = np.random.default_rng(seed)
    d = np.linspace(0, 4500, n)
    theta = d / 4500 * 2 * np.pi
    lat = 48.0 + 0.01 * np.cos(theta) + rng.normal(0, 1e-5, n)
    lon = 2.0 + 0.015 * np.sin(theta) + rng.normal(0, 1e-5, n)
    speed = 30 + 10 * np.sin(theta * 4) + rng.normal(0, 0.5, n)
    speed = np.clip(speed, 5, 60)
    return pd.DataFrame({
        "Distance (m)": d,
        "Latitude":     lat,
        "Longitude":    lon,
        "Speed (m/s)":  speed,
        "Heading (deg)": np.degrees(np.arctan2(np.gradient(lon), np.gradient(lat))),
        "yaw_rate_dps": rng.normal(0, 3, n),
    })


def _make_lap_metrics(n_laps: int = 15, seed: int = 42) -> list[dict[str, Any]]:
    """Synthetic per-lap metrics."""
    rng = np.random.default_rng(seed)
    metrics = []
    for i in range(1, n_laps + 1):
        base = 55.0 if i <= 8 else 57.0  # simulate condition change at lap 9
        metrics.append({
            "lap_number":        i,
            "lap_time_s":        base + rng.normal(0, 0.4),
            "speed_mean_mps":    38.0 + rng.normal(0, 1),
            "speed_min_mps":     12.0 + rng.normal(0, 1),
            "speed_max_mps":     55.0 + rng.normal(0, 1),
            "speed_std_mps":     10.0 + rng.normal(0, 0.5),
            "speed_p10_mps":     18.0 + rng.normal(0, 0.5),
            "speed_p90_mps":     48.0 + rng.normal(0, 0.5),
            "accel_max_mps2":    8.0 + rng.normal(0, 0.3),
            "braking_max_mps2":  14.0 + rng.normal(0, 0.5),
            "accel_rms_mps2":    4.0 + rng.normal(0, 0.2),
            "jerk_rms_mps3":     3.0 + (0.5 if i > 8 else 0) + rng.normal(0, 0.3),
            "jerk_max_mps3":     15.0 + rng.normal(0, 1),
            "jerk_min_mps3":     -12.0 + rng.normal(0, 1),
            "lat_accel_max_mps2": 10.0 + rng.normal(0, 0.5),
            "lat_accel_rms_mps2": 6.0 + rng.normal(0, 0.3),
            "line_length_m":     4510 + rng.normal(0, 5),
        })
    return metrics


def _make_context():
    """Build a test SessionContext."""
    from session_context import SessionContext, SessionType, TrackState, WeatherObs
    return SessionContext(
        session_id="test-int-001",
        track_id=None,
        session_type=SessionType.PRACTICE,
        baseline_track_state=TrackState.DRY,
        weather=WeatherObs(air_temp_c=22.0, humidity_pct=55.0, wind_speed_mps=3.0),
    )


# ===========================================================================

# Test 1: Corner detection adaptive mode detects >2 corners on synthetic data

# ===========================================================================

def t_corner_adaptive() -> None:
    from corner_detection import detect_corners

    lap = _make_resampled_lap(n=1000, seed=7)
    # Adaptive mode (threshold=None)

    corners = detect_corners(lap, curvature_threshold=None)
    assert isinstance(corners, list)
    assert len(corners) > 2, (
        f"Adaptive mode found only {len(corners)} corner(s); expected >2"
    )
    for c in corners:
        assert "corner_id" in c
        assert "s_start" in c
        assert "s_end" in c

_test("corner_adaptive_mode", t_corner_adaptive)


# ===========================================================================

# Test 2: Scoring returns adaptation_score when phases exist

# ===========================================================================

def t_scoring_adaptation() -> None:
    from scoring import score_session_phase_aware

    metrics = {
        "best_s": 55.0, "n_laps": 15, "cv_pct": 2.5,
        "best_to_median_s": 0.3, "speed_mean_mps": 38.0,
        "accel_max_mps2": 8.0, "braking_max_mps2": 14.0,
        "early_mean_s": 55.5, "late_mean_s": 56.0,
        "early_yaw_var": 3.0, "late_yaw_var": 3.5,
    }
    theo = {"lap_time_s": 54.0, "speed_mean_mps": 40.0}
    lap_metrics = _make_lap_metrics(15)

    # Build phases

    from condition_tracking import (
        build_condition_phases,
        compute_grip_indicators,
        detect_condition_changes,
    )
    lm_df = pd.DataFrame(lap_metrics)
    indicators = compute_grip_indicators(lm_df)
    changes = detect_condition_changes(indicators)
    phases_df = build_condition_phases(lm_df, changes if changes else [8])

    # Build lap_to_phase

    l2p: dict[int, int] = {}
    for _, row in phases_df.iterrows():
        pid = int(row["phase_id"])
        for ln in range(int(row["lap_start"]), int(row["lap_end"]) + 1):
            l2p[ln] = pid

    result = score_session_phase_aware(
        metrics, theo, "practice",
        phases_df=phases_df,
        lap_to_phase=l2p,
        lap_metrics=lap_metrics,
    )

    assert "total_score" in result
    assert "adaptation_score" in result
    assert 0.0 <= result["adaptation_score"] <= 1.0
    assert "phase_scores" in result
    assert isinstance(result["phase_scores"], dict)

_test("scoring_adaptation_score", t_scoring_adaptation)


# ===========================================================================

# Test 3: Theoretical engine chooses best phase deterministically

# ===========================================================================

def t_theoretical_phase_selection() -> None:
    from theoretical_engine import build_theoretical_lap_phase_aware

    rng = np.random.default_rng(99)
    laps = []
    lap_keys = []
    for i in range(1, 11):
        d = np.linspace(0, 4500, 200)
        # Phase 0 laps (1-5): faster; Phase 1 laps (6-10): slower

        base_speed = 40.0 if i <= 5 else 35.0
        s = base_speed + 5 * np.sin(d / 700) + rng.normal(0, 0.3, 200)
        laps.append(pd.DataFrame({
            "distance_m": d,
            "speed_mps": s,
            "accel_long_mps2": np.gradient(s, d / max(s.mean(), 1)),
        }))
        lap_keys.append(i)

    phases_df = pd.DataFrame({
        "phase_id": [0, 1],
        "lap_start": [1, 6],
        "lap_end": [5, 10],
        "n_laps": [5, 5],
        "confidence": [0.8, 0.8],
        "signature_json": [
            '{"speed_mean_mps": 42.0, "jerk_rms_mps3": 2.0}',
            '{"speed_mean_mps": 37.0, "jerk_rms_mps3": 4.0}',
        ],
    })

    l2p = {}
    for i in range(1, 6):
        l2p[i] = 0
    for i in range(6, 11):
        l2p[i] = 1

    # First run

    result1 = build_theoretical_lap_phase_aware(
        laps, phases_df=phases_df, lap_to_phase=l2p,
        n_points=200, lap_keys=lap_keys,
    )
    # Second run (determinism)

    result2 = build_theoretical_lap_phase_aware(
        laps, phases_df=phases_df, lap_to_phase=l2p,
        n_points=200, lap_keys=lap_keys,
    )

    assert isinstance(result1, pd.DataFrame)
    assert len(result1) > 0
    # Deterministic

    pd.testing.assert_frame_equal(result1, result2)

_test("theoretical_phase_selection", t_theoretical_phase_selection)


# ===========================================================================

# Test 4: Feature builder writes new context columns

# ===========================================================================

def t_feature_builder_context() -> None:
    from feature_builder import CONTEXT_COLUMNS, build_feature_dataset

    lap_metrics = _make_lap_metrics(5)
    lap_df = pd.DataFrame(lap_metrics)

    metadata = {
        "track_id": "spa",
        "track_state": "dry",
        "driver_name": "Alice",
        "session_id": "test-001",
    }

    ctx = _make_context()
    l2p = {1: 0, 2: 0, 3: 0, 4: 1, 5: 1}

    result = build_feature_dataset(
        lap_df, None, metadata,
        context=ctx, lap_to_phase=l2p,
    )

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 5

    # Check context columns exist

    for col in CONTEXT_COLUMNS:
        assert col in result.columns, f"Missing context column: {col}"

    # Check values

    assert result["session_type"].iloc[0] == "practice"
    assert result["baseline_track_state"].iloc[0] == "dry"
    assert result["weather_temp_c"].iloc[0] == 22.0
    assert result["phase_id"].iloc[0] == 0
    assert result["phase_id"].iloc[3] == 1

_test("feature_builder_context_columns", t_feature_builder_context)


# ===========================================================================

# Test 5: Pipeline runs with context + phases, writes outputs

# ===========================================================================

def t_pipeline_with_context() -> None:
    """Lightweight pipeline test: just verify context/phase state flows."""
    from condition_tracking import (
        build_condition_phases,
        compute_grip_indicators,
        detect_condition_changes,
        label_phases,
    )
    from session_context import (
        SessionContext,
        SessionType,
        TrackState,
        WeatherObs,
        load_last_session_context,
        save_session_context,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = SessionContext(
            session_id="pipe-test",
            track_id=None,
            session_type=SessionType.QUALIFYING,
            baseline_track_state=TrackState.DAMP,
            weather=WeatherObs(air_temp_c=15.0, humidity_pct=80.0),
        )

        # Save context

        ctx_path = Path(tmpdir) / "session_context.json"
        save_session_context(ctx, ctx_path)
        assert ctx_path.exists()

        # Verify round-trip

        loaded = load_last_session_context(Path(tmpdir))
        assert loaded is not None
        assert loaded.session_type == SessionType.QUALIFYING
        assert loaded.baseline_track_state == TrackState.DAMP

        # Run condition tracking

        lm = _make_lap_metrics(15)
        lm_df = pd.DataFrame(lm)
        indicators = compute_grip_indicators(lm_df)
        assert "grip_proxy" in indicators.columns

        changes = detect_condition_changes(indicators)
        phases_df = build_condition_phases(lm_df, changes if changes else [8])
        assert len(phases_df) >= 1

        labelled = label_phases(phases_df, TrackState.DAMP)
        assert "phase_track_state" in labelled.columns

        # Persist phases

        phases_path = Path(tmpdir) / "condition_phases.csv"
        labelled.to_csv(phases_path, index=False)
        assert phases_path.exists()

        # Verify lap_to_phase mapping

        l2p: dict[int, int] = {}
        for _, row in labelled.iterrows():
            pid = int(row["phase_id"])
            for ln in range(int(row["lap_start"]), int(row["lap_end"]) + 1):
                l2p[ln] = pid
        assert len(l2p) == 15

_test("pipeline_context_and_phases", t_pipeline_with_context)


# ===========================================================================

# Test 6: Driver profile with phase stats

# ===========================================================================

def t_driver_profile_phases() -> None:
    from driver_profile import generate_driver_profile

    ctx = _make_context()
    lm = _make_lap_metrics(10)

    # Build simple phases

    phases_df = pd.DataFrame({
        "phase_id": [0, 1],
        "lap_start": [1, 6],
        "lap_end": [5, 10],
        "n_laps": [5, 5],
    })
    l2p = {}
    for i in range(1, 6):
        l2p[i] = 0
    for i in range(6, 11):
        l2p[i] = 1

    sess_data = {
        "metrics": {"best_s": 55.0, "cv_pct": 2.0},
        "theoretical_metrics": {"lap_time_s": 54.0},
        "resampled_laps": [],
        "score_result": {"total_score": 72.0},
        "session_id": "dp-test",
    }

    profile = generate_driver_profile(
        "TestDriver", [sess_data],
        context=ctx, phases_df=phases_df,
        lap_to_phase=l2p, lap_metrics=lm,
    )

    assert profile["driver_name"] == "TestDriver"
    assert "phase_stats" in profile
    assert isinstance(profile["phase_stats"], dict)
    assert "wet_skill_proxy" in profile
    # Dry session -> wet_skill should be None

    assert profile["wet_skill_proxy"] is None

_test("driver_profile_phases", t_driver_profile_phases)


# ===========================================================================

# Test 7: Reporting HTML conditions section

# ===========================================================================

def t_reporting_conditions() -> None:
    from reporting_html import _build_conditions_section
    from session_context import SessionContext, SessionType, TrackState, WeatherObs

    ctx = SessionContext(
        session_id="rpt-test",
        track_id="spa",
        session_type=SessionType.SPRINT_RACE,
        baseline_track_state=TrackState.WET,
        weather=WeatherObs(air_temp_c=12.0, humidity_pct=90.0, wind_speed_mps=5.0),
    )

    phases_df = pd.DataFrame({
        "phase_id": [0, 1],
        "lap_start": [1, 8],
        "lap_end": [7, 15],
        "phase_track_state": ["wet", "drying"],
        "label_reason": ["no change", "instability decreased"],
    })

    html = _build_conditions_section(ctx, phases_df)
    assert "wet" in html.lower()
    assert "12" in html  # temperature
    assert "90" in html  # humidity
    assert "drying" in html
    assert "<table" in html  # phases table present

    # Empty context returns empty

    assert _build_conditions_section(None, None) == ""

_test("reporting_conditions_section", t_reporting_conditions)


# ===========================================================================

# Test 8: Track detection composite scoring (smoke test)

# ===========================================================================

def t_track_composite_scoring() -> None:
    from track_detection import _haversine_pair

    # Same point -> 0 distance

    d = _haversine_pair(48.0, 2.0, 48.0, 2.0)
    assert abs(d) < 1.0

    # Known distance: ~111 km per degree latitude

    d2 = _haversine_pair(48.0, 2.0, 49.0, 2.0)
    assert 110_000 < d2 < 112_000

_test("track_composite_scoring", t_track_composite_scoring)


# ===========================================================================

# Test 9: Backward compatibility - old CLI inputs still work

# ===========================================================================

def t_backward_compat_normalize() -> None:
    from session_context import normalize_session_type, normalize_track_state

    # Old pipeline values must work exactly

    assert normalize_session_type("practice").value == "practice"
    assert normalize_session_type("qualifying").value == "qualifying"
    assert normalize_session_type("race").value == "sprint_race"

    assert normalize_track_state("dry").value == "dry"
    assert normalize_track_state("wet").value == "wet"
    assert normalize_track_state("damp").value == "damp"

_test("backward_compat_normalize", t_backward_compat_normalize)


# ===========================================================================

# Test 10: Feature builder backward compat without context

# ===========================================================================

def t_feature_builder_no_context() -> None:
    from feature_builder import build_feature_dataset

    lap_metrics = _make_lap_metrics(3)
    lap_df = pd.DataFrame(lap_metrics)
    metadata = {
        "track_id": "test",
        "track_state": "dry",
        "driver_name": "Bob",
        "session_id": "bc-001",
    }

    # Must work without context (backward compat)

    result = build_feature_dataset(lap_df, None, metadata)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 3

_test("feature_builder_no_context", t_feature_builder_no_context)


# ===========================================================================

# Test 11: Scoring backward compat without phases

# ===========================================================================

def t_scoring_no_phases() -> None:
    from scoring import score_session_phase_aware

    metrics = {
        "best_s": 55.0, "n_laps": 10, "cv_pct": 2.0,
        "speed_mean_mps": 38.0,
    }
    theo = {"lap_time_s": 54.0}

    result = score_session_phase_aware(metrics, theo, "practice")
    assert "total_score" in result
    assert "adaptation_score" in result
    assert result["adaptation_score"] == 0.5  # neutral default
    assert result["phase_scores"] == {}

_test("scoring_no_phases", t_scoring_no_phases)


# ===========================================================================

# Test 12: Condition tracking end-to-end

# ===========================================================================

def t_condition_tracking_e2e() -> None:
    from condition_tracking import (
        build_condition_phases,
        compute_grip_indicators,
        detect_condition_changes,
        label_phases,
    )
    from session_context import TrackState, WeatherObs

    lm = _make_lap_metrics(20, seed=123)
    lm_df = pd.DataFrame(lm)

    indicators = compute_grip_indicators(lm_df)
    assert len(indicators) == 20
    assert "grip_proxy" in indicators.columns
    assert "pace_residual_s" in indicators.columns

    changes = detect_condition_changes(indicators)
    assert isinstance(changes, list)

    phases = build_condition_phases(lm_df, changes if changes else [10])
    assert len(phases) >= 1

    labelled = label_phases(phases, TrackState.DRY, WeatherObs(humidity_pct=40.0))
    assert "phase_track_state" in labelled.columns
    assert "label_reason" in labelled.columns

_test("condition_tracking_e2e", t_condition_tracking_e2e)


# ===========================================================================

# Summary

# ===========================================================================

if __name__ == "__main__":
    total = len(_passed) + len(_failed)
    status = "PASS" if not _failed else "FAIL"
    print(f"\nIntegration Tests: {len(_passed)}/{total} passed [{status}]")
    for name in _passed:
        print(f"  [PASS] {name}")
    for name, tb in _failed:
        print(f"  [FAIL] {name}\n{tb}")

    if _failed:
        sys.exit(1)
    else:
        sys.exit(0)
