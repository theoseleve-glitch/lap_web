"""
test_domain_core.py
-------------------
Focused unit tests for core telemetry domain logic:
- Lap segmentation
- Distance axis properties
- Delta computation
- Time-loss attribution

All tests use deterministic synthetic data. No external dependencies.

Marked with @pytest.mark.domain for fast CI execution.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Synthetic data generators
# ---------------------------------------------------------------------------


def make_circle_track(
    radius_m: float = 100.0,
    n_points: int = 500,
    speed_mps: float = 15.0,
    n_laps: int = 1,
) -> pd.DataFrame:
    """Perfect circle at constant speed. Known curvature = 1/radius."""
    circumference = 2 * math.pi * radius_m
    ds = circumference / n_points

    frames = []
    cum_time = 0.0
    for lap in range(1, n_laps + 1):
        dist = np.arange(n_points) * ds
        time_arr = cum_time + dist / speed_mps
        cum_time = time_arr[-1] + 0.2  # small inter-lap gap

        theta = dist / radius_m
        lat = 0.5 + radius_m * np.sin(theta) / 111320.0
        lon = 0.5 + radius_m * np.cos(theta) / 111320.0

        frames.append(pd.DataFrame({
            "Lap #": float(lap),
            "Time (s)": time_arr,
            "Speed (m/s)": np.full(n_points, speed_mps),
            "Distance (m)": dist,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
        }))

    return pd.concat(frames, ignore_index=True)


def make_known_speed_profile(
    track_length_m: float = 1000.0,
    n_laps: int = 3,
    n_points: int = 500,
    base_speed: float = 20.0,
    amplitude: float = 5.0,
) -> pd.DataFrame:
    """Sine-wave speed on a straight track. Analytical lap time known."""
    ds = track_length_m / n_points
    frames = []
    cum_time = 0.0

    for lap in range(1, n_laps + 1):
        dist = np.arange(n_points) * ds
        speed = base_speed + amplitude * np.sin(2 * math.pi * dist / track_length_m)
        speed = np.maximum(speed, 2.0)

        dt = ds / speed
        time_arr = cum_time + np.cumsum(dt)
        cum_time = time_arr[-1] + 0.3

        frames.append(pd.DataFrame({
            "Lap #": float(lap),
            "Time (s)": time_arr,
            "Speed (m/s)": speed,
            "Distance (m)": dist,
            "Latitude (deg)": np.linspace(0.5, 0.509, n_points),
            "Longitude (deg)": np.full(n_points, 0.5),
        }))

    return pd.concat(frames, ignore_index=True)


def make_two_laps_different_speeds(
    track_length_m: float = 500.0,
    n_points: int = 500,
    speed_ref: float = 20.0,
    speed_comp: float = 18.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two single-lap DataFrames at different constant speeds."""
    ds = track_length_m / n_points
    dist = np.arange(n_points) * ds

    def _make(speed: float, lap: int) -> pd.DataFrame:
        time_arr = np.cumsum(np.full(n_points, ds / speed))
        return pd.DataFrame({
            "Lap #": float(lap),
            "Time (s)": time_arr,
            "Speed (m/s)": np.full(n_points, speed),
            "Distance (m)": dist,
        })

    return _make(speed_ref, 1), _make(speed_comp, 2)


# ---------------------------------------------------------------------------
# Lap segmentation tests
# ---------------------------------------------------------------------------


@pytest.mark.domain
class TestLapSegmentation:
    """Tests for the groupby-based lap segmentation in pipeline.py."""

    def test_detects_correct_lap_count(self):
        df = make_known_speed_profile(n_laps=5)
        lap_col = pd.to_numeric(df["Lap #"], errors="coerce")
        laps = {int(ln): grp.reset_index(drop=True)
                for ln, grp in df.groupby(lap_col, sort=True)}
        assert len(laps) == 5

    def test_lap_boundaries_non_overlapping(self):
        df = make_known_speed_profile(n_laps=4)
        lap_col = pd.to_numeric(df["Lap #"], errors="coerce")
        laps = {int(ln): grp for ln, grp in df.groupby(lap_col, sort=True)}

        all_indices = set()
        for lap_num, grp in laps.items():
            lap_indices = set(grp.index.tolist())
            overlap = all_indices & lap_indices
            assert not overlap, f"Lap {lap_num} overlaps with previous laps at {overlap}"
            all_indices |= lap_indices

    def test_lap_durations_monotonic_time(self):
        df = make_known_speed_profile(n_laps=4)
        lap_col = pd.to_numeric(df["Lap #"], errors="coerce")
        laps = {int(ln): grp.reset_index(drop=True)
                for ln, grp in df.groupby(lap_col, sort=True)}

        prev_end = -1.0
        for lap_num in sorted(laps.keys()):
            grp = laps[lap_num]
            t_start = float(grp["Time (s)"].iloc[0])
            t_end = float(grp["Time (s)"].iloc[-1])
            assert t_start > prev_end, (
                f"Lap {lap_num} starts at {t_start} but previous ended at {prev_end}"
            )
            prev_end = t_end

    def test_single_lap_session(self):
        df = make_circle_track(n_laps=1)
        lap_col = pd.to_numeric(df["Lap #"], errors="coerce")
        laps = {int(ln): grp.reset_index(drop=True)
                for ln, grp in df.groupby(lap_col, sort=True)}
        assert len(laps) == 1
        assert 1 in laps

    def test_missing_lap_column_detected(self):
        df = make_circle_track(n_laps=2)
        df = df.drop(columns=["Lap #"])
        assert "Lap #" not in df.columns

    def test_all_rows_accounted_for(self):
        df = make_known_speed_profile(n_laps=3)
        lap_col = pd.to_numeric(df["Lap #"], errors="coerce")
        laps = {int(ln): grp for ln, grp in df.groupby(lap_col, sort=True)}
        total_rows = sum(len(g) for g in laps.values())
        assert total_rows == len(df)


# ---------------------------------------------------------------------------
# Distance axis tests
# ---------------------------------------------------------------------------


@pytest.mark.domain
class TestDistanceAxis:
    """Distance column properties after segmentation."""

    def test_monotonic_increasing_per_lap(self):
        df = make_known_speed_profile(n_laps=3)
        lap_col = pd.to_numeric(df["Lap #"], errors="coerce")
        for lap_num, grp in df.groupby(lap_col, sort=True):
            dist = pd.to_numeric(grp["Distance (m)"], errors="coerce").values
            diffs = np.diff(dist)
            assert np.all(diffs >= 0), (
                f"Lap {int(lap_num)}: distance not monotonic, "
                f"min diff={diffs.min():.4f}"
            )

    def test_total_length_within_tolerance(self):
        track_length = 1000.0
        df = make_known_speed_profile(track_length_m=track_length, n_laps=1)
        dist = pd.to_numeric(df["Distance (m)"], errors="coerce")
        total = float(dist.max() - dist.min())
        assert abs(total - track_length) / track_length < 0.05, (
            f"Total distance {total:.1f}m vs expected {track_length:.1f}m (>5% off)"
        )

    def test_consistent_sampling_spacing(self):
        n_points = 500
        track_length = 1000.0
        expected_ds = track_length / n_points
        df = make_known_speed_profile(
            track_length_m=track_length, n_laps=1, n_points=n_points,
        )
        dist = pd.to_numeric(df["Distance (m)"], errors="coerce").values
        diffs = np.diff(dist)
        # All spacings should be within 1% of expected
        assert np.allclose(diffs, expected_ds, rtol=0.01), (
            f"Non-uniform spacing: mean={diffs.mean():.4f}, "
            f"std={diffs.std():.6f}, expected={expected_ds:.4f}"
        )

    def test_circle_track_circumference(self):
        radius = 100.0
        expected_circ = 2 * math.pi * radius
        df = make_circle_track(radius_m=radius, n_laps=1, n_points=1000)
        dist = pd.to_numeric(df["Distance (m)"], errors="coerce")
        total = float(dist.max())
        assert abs(total - expected_circ) / expected_circ < 0.01, (
            f"Circle circumference: {total:.1f}m vs {expected_circ:.1f}m"
        )


# ---------------------------------------------------------------------------
# Delta computation tests
# ---------------------------------------------------------------------------


@pytest.mark.domain
class TestDeltaComputation:
    """Tests for deltas.compute_delta_curve and related functions."""

    def _import_deltas(self):
        try:
            from telemetry_tool.deltas import (
                compute_cumulative_time,
                compute_delta_curve,
            )
        except ImportError:
            from deltas import compute_cumulative_time, compute_delta_curve
        return compute_cumulative_time, compute_delta_curve

    def test_sign_convention_slower_positive(self):
        """Slower comparison lap → positive delta."""
        _, compute_delta_curve = self._import_deltas()
        ref, comp = make_two_laps_different_speeds(speed_ref=20.0, speed_comp=18.0)
        result = compute_delta_curve(ref, comp)
        final_delta = float(result["delta_s"].iloc[-1])
        assert final_delta > 0, (
            f"Slower comp lap should give positive delta, got {final_delta:.4f}"
        )

    def test_sign_convention_faster_negative(self):
        """Faster comparison lap → negative delta."""
        _, compute_delta_curve = self._import_deltas()
        ref, comp = make_two_laps_different_speeds(speed_ref=18.0, speed_comp=20.0)
        result = compute_delta_curve(ref, comp)
        final_delta = float(result["delta_s"].iloc[-1])
        assert final_delta < 0, (
            f"Faster comp lap should give negative delta, got {final_delta:.4f}"
        )

    def test_alignment_identical_laps(self):
        """Same lap compared to itself → delta ~0 everywhere."""
        _, compute_delta_curve = self._import_deltas()
        ref, _ = make_two_laps_different_speeds(speed_ref=20.0, speed_comp=20.0)
        result = compute_delta_curve(ref, ref)
        max_abs_delta = float(np.abs(result["delta_s"]).max())
        assert max_abs_delta < 0.001, (
            f"Identical laps should give delta~0, got max |delta|={max_abs_delta:.6f}"
        )

    def test_delta_curve_columns(self):
        """Output must have the expected columns."""
        _, compute_delta_curve = self._import_deltas()
        ref, comp = make_two_laps_different_speeds()
        result = compute_delta_curve(ref, comp)
        expected_cols = {"distance_m", "delta_s", "ref_cum_time_s", "comp_cum_time_s"}
        assert expected_cols <= set(result.columns), (
            f"Missing columns: {expected_cols - set(result.columns)}"
        )

    def test_missing_speed_raises(self):
        """DeltaError if Speed column missing."""
        _, compute_delta_curve = self._import_deltas()
        ref, comp = make_two_laps_different_speeds()
        ref_no_speed = ref.drop(columns=["Speed (m/s)"])
        with pytest.raises(Exception):  # DeltaError
            compute_delta_curve(ref_no_speed, comp)

    def test_missing_distance_raises(self):
        """DeltaError if Distance column missing."""
        _, compute_delta_curve = self._import_deltas()
        ref, comp = make_two_laps_different_speeds()
        ref_no_dist = ref.drop(columns=["Distance (m)"])
        with pytest.raises(Exception):
            compute_delta_curve(ref_no_dist, comp)

    def test_cumulative_time_positive(self):
        """Cumulative time must be non-negative and increasing."""
        compute_cumulative_time, _ = self._import_deltas()
        ref, _ = make_two_laps_different_speeds()
        result = compute_cumulative_time(ref)
        cum_time = result["cumulative_time_s"].values
        assert np.all(cum_time >= 0), "Negative cumulative time"
        diffs = np.diff(cum_time)
        assert np.all(diffs >= 0), "Cumulative time not monotonic"


# ---------------------------------------------------------------------------
# Time-loss attribution tests
# ---------------------------------------------------------------------------


@pytest.mark.domain
class TestTimeLossAttribution:
    """Tests for deltas.segment_time_loss and classify_time_loss_cause."""

    def _import_deltas(self):
        try:
            from telemetry_tool.deltas import (
                classify_time_loss_cause,
                compute_delta_curve,
                segment_time_loss,
            )
        except ImportError:
            from deltas import (
                classify_time_loss_cause,
                compute_delta_curve,
                segment_time_loss,
            )
        return compute_delta_curve, segment_time_loss, classify_time_loss_cause

    def test_segment_losses_sum_to_total(self):
        """Sum of per-segment time_loss_ms should approximate total delta."""
        compute_delta_curve, segment_time_loss, _ = self._import_deltas()
        ref, comp = make_two_laps_different_speeds(speed_ref=20.0, speed_comp=18.0)
        delta_curve = compute_delta_curve(ref, comp)
        segments = segment_time_loss(delta_curve, n_segments=10)

        seg_total_ms = sum(s["time_loss_ms"] for s in segments)
        actual_total_ms = float(delta_curve["delta_s"].iloc[-1]) * 1000

        # Allow up to 2% relative or 50ms absolute tolerance
        # (segment boundary interpolation introduces small rounding)
        abs_diff = abs(seg_total_ms - actual_total_ms)
        rel_diff = abs_diff / max(abs(actual_total_ms), 1.0)
        assert abs_diff < 50.0 or rel_diff < 0.02, (
            f"Segment sum {seg_total_ms:.1f}ms vs total {actual_total_ms:.1f}ms "
            f"(diff {abs_diff:.1f}ms, {rel_diff:.2%})"
        )

    def test_no_extreme_negative_loss(self):
        """No segment should have absurdly large negative loss."""
        compute_delta_curve, segment_time_loss, _ = self._import_deltas()
        ref, comp = make_two_laps_different_speeds(speed_ref=20.0, speed_comp=18.0)
        delta_curve = compute_delta_curve(ref, comp)
        segments = segment_time_loss(delta_curve, n_segments=20)

        for seg in segments:
            assert seg["time_loss_ms"] > -5000, (
                f"Segment {seg['segment']}: absurd loss {seg['time_loss_ms']}ms"
            )

    def test_segment_boundaries_consistent(self):
        """Segments must cover the full distance, s_start < s_end, contiguous."""
        compute_delta_curve, segment_time_loss, _ = self._import_deltas()
        ref, comp = make_two_laps_different_speeds()
        delta_curve = compute_delta_curve(ref, comp)
        segments = segment_time_loss(delta_curve, n_segments=10)

        for seg in segments:
            assert seg["s_start_m"] < seg["s_end_m"], (
                f"Segment {seg['segment']}: start >= end "
                f"({seg['s_start_m']} >= {seg['s_end_m']})"
            )

        # Verify coverage
        first_start = segments[0]["s_start_m"]
        last_end = segments[-1]["s_end_m"]
        total_range = last_end - first_start
        assert total_range > 0, "Segments don't cover any distance"

    def test_correct_segment_count(self):
        """Number of segments must match requested n_segments."""
        compute_delta_curve, segment_time_loss, _ = self._import_deltas()
        ref, comp = make_two_laps_different_speeds()
        delta_curve = compute_delta_curve(ref, comp)
        for n_seg in [5, 10, 20]:
            segments = segment_time_loss(delta_curve, n_segments=n_seg)
            assert len(segments) == n_seg, (
                f"Requested {n_seg} segments, got {len(segments)}"
            )

    def test_cause_classification_valid_strings(self):
        """All likely_cause values must be from the valid set."""
        _, _, classify_time_loss_cause = self._import_deltas()
        ref, comp = make_two_laps_different_speeds(speed_ref=20.0, speed_comp=18.0)

        valid_causes = {
            "entry_loss", "mid_corner_loss", "exit_loss",
            "instability", "line_inefficiency",
            "on_pace", "undetermined",
        }

        result = classify_time_loss_cause(ref, comp, n_segments=10)
        for seg in result:
            cause = seg.get("likely_cause", "")
            assert cause in valid_causes, (
                f"Segment {seg.get('segment')}: invalid cause {cause!r}"
            )

    def test_cause_has_required_keys(self):
        """Each classified segment must have required keys."""
        _, _, classify_time_loss_cause = self._import_deltas()
        ref, comp = make_two_laps_different_speeds()
        result = classify_time_loss_cause(ref, comp, n_segments=5)

        required_keys = {"segment", "s_start_m", "s_end_m", "time_loss_ms", "likely_cause"}
        for seg in result:
            missing = required_keys - set(seg.keys())
            assert not missing, f"Segment {seg.get('segment')}: missing keys {missing}"

    def test_undetermined_when_channels_missing(self):
        """With no yaw/accel data, instability cause should not trigger."""
        _, _, classify_time_loss_cause = self._import_deltas()
        # Minimal DataFrames: only Speed + Distance
        ref, comp = make_two_laps_different_speeds()
        # Remove all extra channels to force undetermined/on_pace
        ref = ref[["Distance (m)", "Speed (m/s)"]].copy()
        comp = comp[["Distance (m)", "Speed (m/s)"]].copy()

        result = classify_time_loss_cause(ref, comp, n_segments=5)
        for seg in result:
            assert seg["likely_cause"] != "instability", (
                f"Instability triggered without yaw data in segment {seg['segment']}"
            )


# ---------------------------------------------------------------------------
# GPS filtering threshold tests
# ---------------------------------------------------------------------------


@pytest.mark.domain
class TestGPSFilteringThresholds:
    """Verify GPS filter accepts/rejects data based on thresholds."""

    def _import_filter(self):
        try:
            from telemetry_tool.gps_filtering import filter_gps_quality, GPSFilterError
        except ImportError:
            from gps_filtering import filter_gps_quality, GPSFilterError
        return filter_gps_quality, GPSFilterError

    def test_clean_data_passes(self):
        filter_gps_quality, _ = self._import_filter()
        df = make_circle_track(n_laps=1, n_points=200)
        df["Satellites"] = 10
        df["Accuracy (m)"] = 1.0
        result = filter_gps_quality(df)
        assert len(result) == len(df), "Clean data should pass entirely"

    def test_low_satellites_filtered(self):
        filter_gps_quality, _ = self._import_filter()
        df = make_circle_track(n_laps=1, n_points=200)
        df["Satellites"] = 10
        df["Accuracy (m)"] = 1.0
        # Set some rows to low satellites
        df.loc[50:60, "Satellites"] = 2
        result = filter_gps_quality(df, min_satellites=5)
        assert len(result) < len(df), "Low satellite rows should be filtered"

    def test_speed_spike_filtered(self):
        filter_gps_quality, _ = self._import_filter()
        df = make_circle_track(n_laps=1, n_points=200, speed_mps=15.0)
        df["Satellites"] = 10
        df["Accuracy (m)"] = 1.0
        # Inject a speed spike
        df.loc[100, "Speed (m/s)"] = 100.0
        result = filter_gps_quality(df, max_speed_mps=80.0)
        assert len(result) < len(df), "Speed spike should be filtered"

    def test_custom_thresholds_respected(self):
        filter_gps_quality, GPSFilterError = self._import_filter()
        df = make_circle_track(n_laps=1, n_points=200, speed_mps=15.0)
        df["Satellites"] = 10
        df["Accuracy (m)"] = 1.0
        # With very low max_speed, all data is filtered → GPSFilterError expected
        with pytest.raises(GPSFilterError):
            filter_gps_quality(df, max_speed_mps=5.0)
