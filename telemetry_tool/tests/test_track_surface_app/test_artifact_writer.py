"""Tests for ArtifactWriter — serializes PipelineResult to JSON DTOs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from track_surface_app.domain import SupportTier
from track_surface_app.gating import OutputGate
from track_surface_app.artifacts import ArtifactWriter


class TestArtifactWriter:
    def test_writes_summary_for_any_tier(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="r1", session_id=42)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.A))
        assert "summary" in index
        p = tmp_path / "42" / "r1" / "summary.json"
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["run_id"] == "r1"
        assert data["session_id"] == 42
        assert data["n_laps"] == 5
        assert data["best_lap_time_s"] == pytest.approx(88.123)

    def test_tier_d_writes_only_summary_and_diagnostics(self, tmp_path, tier_d_inputs_no_calibration):
        pr, _rr = tier_d_inputs_no_calibration
        writer = ArtifactWriter(tmp_path, run_id="rD", session_id=99)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.D))
        assert set(index.keys()) == {"summary", "diagnostics"}
        assert not (tmp_path / "99" / "rD" / "surface_field.json").exists()
        assert not (tmp_path / "99" / "rD" / "planner_nominal.json").exists()

    def test_tier_a_writes_all_kinds(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="rA", session_id=1)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.A))
        for k in ("summary", "surface_field", "confidence_heatmap",
                  "planner_nominal", "planner_robust", "planner_exploitable",
                  "racing_line_deltas", "diagnostics"):
            assert k in index, f"missing artifact {k}"
            p = tmp_path / "1" / "rA" / f"{k}.json"
            assert p.exists()

    def test_tier_b_skips_exploitable(self, tmp_path, tier_b_inputs_fallback):
        pr, _rr = tier_b_inputs_fallback
        writer = ArtifactWriter(tmp_path, run_id="rB", session_id=7)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.B))
        assert "planner_exploitable" not in index
        assert "planner_robust" in index
        assert "planner_nominal" in index

    def test_summary_has_no_numpy_or_nonjson(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="r", session_id=1)
        writer.write_all(pr, gate=OutputGate(SupportTier.A))
        # Round-trip every JSON file; if any non-serializable object leaked, json.loads
        # would have already failed on write. This also verifies files are valid UTF-8 JSON.
        for p in (tmp_path / "1" / "r").glob("*.json"):
            data = json.loads(p.read_text())
            _assert_json_only(data)

    def test_planner_summary_has_expected_fields(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="r", session_id=1)
        writer.write_all(pr, gate=OutputGate(SupportTier.A))
        p = tmp_path / "1" / "r" / "planner_nominal.json"
        data = json.loads(p.read_text())
        assert data["mode"] == "nominal"
        assert "mu_eff_mean" in data
        assert data["total_point_count"] == pr.planner_n_trusted + pr.planner_n_degraded

    def test_index_paths_are_relative(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="r", session_id=1)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.A))
        for kind, path_str in index.items():
            # Paths in the index are stored as POSIX-style relative to the base
            # for portability across OSes.
            assert not Path(path_str).is_absolute()


def _assert_json_only(obj):
    """Recursively confirm obj contains only JSON-native types."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return
    if isinstance(obj, list):
        for x in obj:
            _assert_json_only(x)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, str), f"non-string key: {k!r}"
            _assert_json_only(v)
        return
    raise AssertionError(f"non-JSON type leaked: {type(obj).__name__}")
