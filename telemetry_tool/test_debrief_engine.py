"""
tests/test_debrief_engine.py
----------------------------
Pytest unit tests for debrief_engine.py.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from debrief_engine import (
    classify_mistakes,
    generate_next_session_drills,
    summarize_session,
    top_time_loss_segments,
)
from session_context import (
    SessionContext,
    SessionType,
    TrackState,
    WeatherObs,
)

# ============================================================================

# Fixtures

# ============================================================================


@pytest.fixture()
def ctx_dry() -> SessionContext:
    return SessionContext(
        session_id="test-dry-001",
        track_id="monza",
        session_type=SessionType.PRACTICE,
        baseline_track_state=TrackState.DRY,
    )


@pytest.fixture()
def ctx_wet() -> SessionContext:
    return SessionContext(
        session_id="test-wet-001",
        track_id="spa",
        session_type=SessionType.SPRINT_RACE,
        baseline_track_state=TrackState.WET,
        weather=WeatherObs(air_temp_c=12.0, humidity_pct=92.0),
    )


@pytest.fixture()
def lap_metrics() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 15
    return pd.DataFrame({
        "lap_number":       list(range(1, n + 1)),
        "lap_time_s":       [55.0 + rng.normal(0, 0.4) for _ in range(n)],
        "speed_mean_mps":   [40.0 + rng.normal(0, 0.5) for _ in range(n)],
        "braking_max_mps2": [14.0 + rng.normal(0, 0.3) for _ in range(n)],
        "jerk_rms_mps3":    [3.0 + rng.normal(0, 0.2) for _ in range(n)],
        "lat_accel_rms_mps2": [8.0 + rng.normal(0, 0.3) for _ in range(n)],
    })


@pytest.fixture()
def deltas_df() -> pd.DataFrame:
    """Simulated delta/segment metrics for 10 laps × 10 segments."""
    rng = np.random.default_rng(7)
    causes = ["entry_loss", "mid_corner_loss", "exit_loss", "instability", "on_pace"]
    rows: list[dict[str, Any]] = []
    for lap in range(2, 12):
        for seg in range(1, 11):
            rows.append({
                "lap_number":          lap,
                "segment":             seg,
                "time_loss_ms":        max(0, rng.normal(50, 25)),
                "likely_cause":        causes[seg % len(causes)],
                "entry_speed_diff_mps":  rng.normal(-1.5, 0.8),
                "min_speed_diff_mps":    rng.normal(-1.0, 0.5),
                "exit_accel_diff_mps2":  rng.normal(-0.4, 0.3),
                "yaw_var_ratio":         rng.uniform(0.8, 1.4),
            })
    return pd.DataFrame(rows)


# ============================================================================

# summarize_session

# ============================================================================


class TestSummarizeSession:

    def test_basic_structure(
        self, ctx_dry: SessionContext, lap_metrics: pd.DataFrame
    ) -> None:
        result = summarize_session(ctx_dry, lap_metrics)
        assert "summary_sentence" in result
        assert "best_lap" in result
        assert "median_lap_time_s" in result
        assert "pace_trend" in result
        assert "n_laps" in result

    def test_n_laps_correct(
        self, ctx_dry: SessionContext, lap_metrics: pd.DataFrame
    ) -> None:
        result = summarize_session(ctx_dry, lap_metrics)
        assert result["n_laps"] == 15

    def test_best_lap_is_int(
        self, ctx_dry: SessionContext, lap_metrics: pd.DataFrame
    ) -> None:
        result = summarize_session(ctx_dry, lap_metrics)
        assert isinstance(result["best_lap"], int)

    def test_pace_trend_valid(
        self, ctx_dry: SessionContext, lap_metrics: pd.DataFrame
    ) -> None:
        result = summarize_session(ctx_dry, lap_metrics)
        assert result["pace_trend"] in ("stable", "improving", "degrading")

    def test_summary_sentence_nonempty(
        self, ctx_dry: SessionContext, lap_metrics: pd.DataFrame
    ) -> None:
        result = summarize_session(ctx_dry, lap_metrics)
        assert len(result["summary_sentence"]) > 20

    def test_empty_input(self, ctx_dry: SessionContext) -> None:
        result = summarize_session(ctx_dry, pd.DataFrame())
        assert "Insufficient" in result["summary_sentence"]
        assert result["n_laps"] == 0

    def test_with_phases(
        self, ctx_dry: SessionContext, lap_metrics: pd.DataFrame
    ) -> None:
        phases = pd.DataFrame({
            "phase_id": [0, 1],
            "lap_start": [1, 8],
            "lap_end": [7, 15],
            "n_laps": [7, 8],
            "confidence": [0.9, 0.8],
            "signature_json": ["{}"] * 2,
            "phase_track_state": ["dry", "rubbered"],
        })
        result = summarize_session(ctx_dry, lap_metrics, phases)
        assert len(result["phases_summary"]) == 2
        assert result["phases_summary"][0]["phase_id"] == 0

    def test_wet_session_type_in_summary(
        self, ctx_wet: SessionContext, lap_metrics: pd.DataFrame
    ) -> None:
        result = summarize_session(ctx_wet, lap_metrics)
        assert "Sprint Race" in result["summary_sentence"]
        assert "wet" in result["summary_sentence"].lower()


# ============================================================================

# top_time_loss_segments

# ============================================================================


class TestTopTimeLossSegments:

    def test_returns_k_rows(self, deltas_df: pd.DataFrame) -> None:
        result = top_time_loss_segments(deltas_df, k=3)
        assert len(result) <= 3

    def test_output_columns(self, deltas_df: pd.DataFrame) -> None:
        result = top_time_loss_segments(deltas_df, k=5)
        expected = {"segment", "mean_loss_ms", "std_loss_ms",
                    "n_observations", "likely_cause"}
        assert expected.issubset(set(result.columns))

    def test_excludes_on_pace(self, deltas_df: pd.DataFrame) -> None:
        result = top_time_loss_segments(deltas_df, k=10)
        if "likely_cause" in result.columns and len(result) > 0:
            assert "on_pace" not in result["likely_cause"].values

    def test_sorted_descending(self, deltas_df: pd.DataFrame) -> None:
        result = top_time_loss_segments(deltas_df, k=5, stability_filter=False)
        losses = result["mean_loss_ms"].values
        # Should be roughly descending (stability_filter=False → strict sort)

        assert losses[0] >= losses[-1]

    def test_empty_input(self) -> None:
        result = top_time_loss_segments(pd.DataFrame(), k=5)
        assert len(result) == 0

    def test_stability_filter_off(self, deltas_df: pd.DataFrame) -> None:
        with_filter = top_time_loss_segments(deltas_df, k=5, stability_filter=True)
        without_filter = top_time_loss_segments(deltas_df, k=5, stability_filter=False)
        # Both should return valid DataFrames (order may differ)

        assert len(with_filter) > 0
        assert len(without_filter) > 0

    def test_all_on_pace(self) -> None:
        """If every segment is on_pace, result should be empty."""
        df = pd.DataFrame({
            "segment": [1, 2, 3],
            "time_loss_ms": [0.5, 0.3, 0.1],
            "likely_cause": ["on_pace", "on_pace", "on_pace"],
        })
        result = top_time_loss_segments(df, k=3)
        assert len(result) == 0


# ============================================================================

# classify_mistakes

# ============================================================================


class TestClassifyMistakes:

    def test_output_columns(self, deltas_df: pd.DataFrame) -> None:
        result = classify_mistakes(deltas_df)
        expected = {"segment", "dominant_cause", "confidence",
                    "supporting_metrics", "coaching_hint"}
        assert expected.issubset(set(result.columns))

    def test_one_row_per_segment(self, deltas_df: pd.DataFrame) -> None:
        result = classify_mistakes(deltas_df)
        # 10 unique segments in fixture

        assert len(result) == 10

    def test_confidence_bounded(self, deltas_df: pd.DataFrame) -> None:
        result = classify_mistakes(deltas_df)
        assert (result["confidence"] >= 0.0).all()
        assert (result["confidence"] <= 1.0).all()

    def test_supporting_metrics_valid_json(self, deltas_df: pd.DataFrame) -> None:
        result = classify_mistakes(deltas_df)
        for _, row in result.iterrows():
            parsed = json.loads(row["supporting_metrics"])
            assert isinstance(parsed, dict)

    def test_coaching_hints_nonempty(self, deltas_df: pd.DataFrame) -> None:
        result = classify_mistakes(deltas_df)
        real = result[result["dominant_cause"] != "on_pace"]
        if len(real) > 0:
            assert all(len(h) > 5 for h in real["coaching_hint"])

    def test_empty_input(self) -> None:
        result = classify_mistakes(pd.DataFrame())
        assert len(result) == 0

    def test_valid_cause_values(self, deltas_df: pd.DataFrame) -> None:
        valid_causes = {
            "entry_loss", "mid_corner_loss", "exit_loss",
            "instability", "line_inefficiency", "on_pace", "undetermined",
        }
        result = classify_mistakes(deltas_df)
        for cause in result["dominant_cause"]:
            assert cause in valid_causes


# ============================================================================

# generate_next_session_drills

# ============================================================================


class TestGenerateNextSessionDrills:

    def test_returns_list_of_strings(
        self, deltas_df: pd.DataFrame, ctx_dry: SessionContext
    ) -> None:
        mistakes = classify_mistakes(deltas_df)
        drills = generate_next_session_drills(mistakes, ctx_dry, max_drills=4)
        assert isinstance(drills, list)
        assert all(isinstance(d, str) for d in drills)

    def test_respects_max_drills(
        self, deltas_df: pd.DataFrame, ctx_dry: SessionContext
    ) -> None:
        mistakes = classify_mistakes(deltas_df)
        for max_d in (2, 4, 6):
            drills = generate_next_session_drills(mistakes, ctx_dry, max_drills=max_d)
            assert len(drills) <= max_d

    def test_at_least_one_drill(
        self, deltas_df: pd.DataFrame, ctx_dry: SessionContext
    ) -> None:
        mistakes = classify_mistakes(deltas_df)
        drills = generate_next_session_drills(mistakes, ctx_dry)
        assert len(drills) >= 1

    def test_wet_includes_wet_drill(
        self, deltas_df: pd.DataFrame, ctx_wet: SessionContext
    ) -> None:
        mistakes = classify_mistakes(deltas_df)
        drills = generate_next_session_drills(mistakes, ctx_wet, max_drills=6)
        wet_drills = [d for d in drills if "wet" in d.lower() or "drying" in d.lower()]
        assert len(wet_drills) >= 1

    def test_includes_consistency_drill(
        self, deltas_df: pd.DataFrame, ctx_dry: SessionContext
    ) -> None:
        mistakes = classify_mistakes(deltas_df)
        drills = generate_next_session_drills(mistakes, ctx_dry, max_drills=6)
        consistency = [d for d in drills if "consistency" in d.lower()]
        assert len(consistency) >= 1

    def test_empty_mistakes(self, ctx_dry: SessionContext) -> None:
        drills = generate_next_session_drills(pd.DataFrame(), ctx_dry)
        assert len(drills) >= 1

    def test_drills_are_sentences(
        self, deltas_df: pd.DataFrame, ctx_dry: SessionContext
    ) -> None:
        """Each drill should be at least a short sentence."""
        mistakes = classify_mistakes(deltas_df)
        drills = generate_next_session_drills(mistakes, ctx_dry)
        for d in drills:
            assert len(d) > 15, f"Drill too short: {d!r}"
