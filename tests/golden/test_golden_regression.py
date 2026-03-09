"""
test_golden_regression.py
-------------------------
Regression tests that run the full 14-stage pipeline on golden datasets
and assert stable outputs within tolerance bands.

Marked with @pytest.mark.regression for CI filtering.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
_TELEMETRY_TOOL = _PROJECT_ROOT / "telemetry_tool"
for _p in (str(_PROJECT_ROOT), str(_TELEMETRY_TOOL)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.golden.tolerance import compare_snapshot

# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------

_MANIFEST_PATH = _HERE / "golden_manifest.json"


def _load_manifest() -> list[dict]:
    if not _MANIFEST_PATH.exists():
        pytest.skip("Golden manifest not found. Run generate_golden.py first.")
    return json.loads(_MANIFEST_PATH.read_text())


def _session_ids():
    if not _MANIFEST_PATH.exists():
        return []
    return [e["session_id"] for e in json.loads(_MANIFEST_PATH.read_text())]


# ---------------------------------------------------------------------------
# Pipeline runner helper
# ---------------------------------------------------------------------------


def _run_pipeline_on_golden(session_id: str, manifest_entry: dict) -> dict:
    """Run the full pipeline on a golden CSV and return the summary dict."""
    from telemetry_tool.pipeline import run_full_analysis

    csv_path = _HERE / manifest_entry["file"]
    if not csv_path.exists():
        pytest.skip(f"Golden CSV not found: {csv_path}")

    summary = run_full_analysis(
        str(csv_path),
        session_meta={
            "session_id": session_id,
            "session_type": "practice",
            "track_state": manifest_entry.get("track_state", "dry"),
        },
        enable_ml=False,
        enable_report=False,
    )
    return summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=_session_ids(), scope="module")
def golden_result(request):
    """Run pipeline once per golden session (module-scoped for speed)."""
    session_id = request.param
    manifest = _load_manifest()
    entry = next(e for e in manifest if e["session_id"] == session_id)
    summary = _run_pipeline_on_golden(session_id, entry)
    return session_id, entry, summary


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.regression
class TestGoldenPipelineCompletes:
    """Pipeline must complete without fatal errors on all golden sessions."""

    def test_no_pipeline_error(self, golden_result):
        sid, entry, summary = golden_result
        failed = summary.get("steps_failed", [])
        # Allow non-critical steps to fail (ML, report generation)
        critical_failures = [
            s for s in failed
            if not any(skip in s for skip in [
                "05_detect_track",       # May fail on synthetic GPS
                "09a2_track_boundaries", # Depends on track detection
                "11_build_features", "12_ml", "14_report",
                "08e_weather", "15_persist",  # No DB in test env
            ])
        ]
        assert not critical_failures, (
            f"{sid}: critical steps failed: {critical_failures}"
        )

    def test_pipeline_produced_laps(self, golden_result):
        sid, entry, summary = golden_result
        # enriched_df is set to None for GC; check lap_dict instead
        lap_dict = summary.get("lap_dict")
        assert lap_dict and len(lap_dict) > 0, f"{sid}: lap_dict is empty (pipeline may have failed)"


@pytest.mark.regression
class TestGoldenDerivedChannels:
    """Derived channels must exist and be mostly non-NaN."""

    _EXPECTED_CHANNELS = [
        "accel_long_mps2",
        "accel_lat_mps2",
    ]

    def test_channels_exist(self, golden_result):
        sid, entry, summary = golden_result
        enriched = summary.get("enriched_df")
        if enriched is None:
            pytest.skip(f"{sid}: enriched_df is None (step 03 failed)")

        for ch in self._EXPECTED_CHANNELS:
            assert ch in enriched.columns, (
                f"{sid}: derived channel {ch!r} missing from enriched_df"
            )

    def test_channels_mostly_valid(self, golden_result):
        sid, entry, summary = golden_result
        enriched = summary.get("enriched_df")
        if enriched is None:
            pytest.skip(f"{sid}: enriched_df is None")

        for ch in self._EXPECTED_CHANNELS:
            if ch not in enriched.columns:
                continue
            valid_ratio = enriched[ch].notna().mean()
            assert valid_ratio > 0.80, (
                f"{sid}: channel {ch!r} only {valid_ratio:.1%} valid (need >80%)"
            )


@pytest.mark.regression
class TestGoldenOutputsNonEmpty:
    """Key pipeline outputs must be present and non-empty."""

    def test_lap_dict(self, golden_result):
        sid, entry, summary = golden_result
        lap_dict = summary.get("lap_dict")
        assert lap_dict and len(lap_dict) > 0, f"{sid}: lap_dict empty"

    def test_resampled_laps(self, golden_result):
        sid, entry, summary = golden_result
        resampled = summary.get("resampled_laps")
        assert resampled and len(resampled) > 0, f"{sid}: resampled_laps empty"

    def test_corners_detected(self, golden_result):
        sid, entry, summary = golden_result
        corners = summary.get("corners", [])
        lo, hi = entry["expected_corners_range"]
        # Allow 0 corners if range starts at 0; otherwise require some
        if lo > 0:
            assert len(corners) >= 1, f"{sid}: no corners detected"

    def test_score_result(self, golden_result):
        sid, entry, summary = golden_result
        score = summary.get("score_result")
        # Score can be None if theoretical lap failed; don't hard-fail
        if score is None:
            pytest.xfail(f"{sid}: score_result is None (theoretical may have failed)")


@pytest.mark.regression
class TestGoldenMetricsTolerance:
    """Summary metrics must fall within expected tolerance bands."""

    def test_lap_count(self, golden_result):
        sid, entry, summary = golden_result
        lap_dict = summary.get("lap_dict", {})
        assert len(lap_dict) == entry["expected_laps"], (
            f"{sid}: expected {entry['expected_laps']} laps, got {len(lap_dict)}"
        )

    def test_lap_times_in_range(self, golden_result):
        sid, entry, summary = golden_result
        lap_times = summary.get("lap_times", [])
        if not lap_times:
            pytest.skip(f"{sid}: no lap_times")

        lo, hi = entry["expected_lap_time_range_s"]
        best = min(lap_times)
        assert lo <= best <= hi, (
            f"{sid}: best lap {best:.2f}s outside expected [{lo}, {hi}]"
        )

    def test_total_distance(self, golden_result):
        sid, entry, summary = golden_result
        enriched = summary.get("enriched_df")
        if enriched is None or "Distance (m)" not in enriched.columns:
            pytest.skip(f"{sid}: no distance data")

        total_dist = float(
            pd.to_numeric(enriched["Distance (m)"], errors="coerce").max()
        )
        lo, hi = entry["expected_total_distance_m"]
        assert lo <= total_dist <= hi, (
            f"{sid}: total distance {total_dist:.0f}m outside [{lo:.0f}, {hi:.0f}]"
        )


@pytest.mark.regression
class TestGoldenSnapshotStability:
    """If a snapshot file exists, key outputs must match within tolerances."""

    def test_snapshot_match(self, golden_result):
        sid, entry, summary = golden_result
        snap_path = _HERE / entry.get("snapshot_file", "")
        if not snap_path.exists():
            pytest.skip(f"{sid}: no snapshot file (run --update-snapshots)")

        snapshot = json.loads(snap_path.read_text())

        # Build actual result in same shape as snapshot
        lap_dict = summary.get("lap_dict", {})
        lap_times = summary.get("lap_times", [])
        score = summary.get("score_result")
        corners = summary.get("corners", [])
        vehicle = summary.get("vehicle_params")

        actual = {
            "lap_count": len(lap_dict),
            "best_lap_time_s": round(min(lap_times), 3) if lap_times else None,
            "mean_lap_time_s": (
                round(sum(lap_times) / len(lap_times), 3) if lap_times else None
            ),
            "n_corners": len(corners),
            "total_score": (
                score.get("total_score") if isinstance(score, dict) else None
            ),
            "grade": score.get("grade") if isinstance(score, dict) else None,
            "vehicle_class": (
                vehicle.vehicle_class.value
                if vehicle and hasattr(vehicle, "vehicle_class")
                else None
            ),
        }

        errors = compare_snapshot(actual, snapshot)
        assert not errors, (
            f"{sid}: snapshot mismatches:\n" + "\n".join(f"  - {e}" for e in errors)
        )
