"""Tests for the release gate.

Covers:
  - ThresholdProfile overlay semantics (specific keys override, others inherit)
  - ReleaseThresholds.resolve (most-specific-wins resolution chain)
  - Per-session evaluation: planner invariants, lambda band, fallback,
    transition, racing line, residuals, bucket actives
  - Suite aggregation: PASS/WARN/FAIL escalation, top causes, exit codes
  - Markdown rendering produces a valid summary
  - Smoke mode flag propagation
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from track_surface.validation.metrics import SessionMetrics
from track_surface.validation.release_gate import (
    ReleaseDecision,
    ReleaseThresholds,
    ThresholdProfile,
    evaluate_session,
    evaluate_suite,
    render_markdown,
)


# ── Fixtures ─────────────────────────────────────────────────


def _healthy_metrics(**overrides) -> SessionMetrics:
    """A clean SessionMetrics that should PASS all default thresholds."""
    base = dict(
        dataset_id="test_clean",
        group="A_banked",
        track_name="Daytona",
        vehicle_name="McLaren GT4",
        # Physics
        lambda_median=1.20,
        lambda_mean=1.20,
        lambda_std=0.10,
        lambda_p5=1.00,
        lambda_p95=1.40,
        lambda_in_band_pct=80.0,
        fy_residual_std=1500.0,
        fx_residual_std=1200.0,
        accept_pct=60.0,
        # Field
        coverage_pct=20.0,
        cells_high_conf=100,
        cells_zero_conf=200,
        mean_confidence=0.30,
        max_obs_per_cell=300,
        # Bucket
        bucket_active_count=6,
        bucket_sparse_count=0,
        fallback_depth_distribution={0: 400, 1: 100, 2: 50},
        fallback_depth_2_pct=10.0,
        transition_quarantine_pct=10.0,
        # Structure
        racing_line_lift=0.05,
        flat_vs_banked_lambda_diff=0.10,
        # Planner (invariants hold: robust < nominal, exploitable <= nominal)
        planner_nominal_mean=1.18,
        planner_robust_mean=1.00,
        planner_exploitable_mean=1.10,
        planner_robust_tightening=0.18,
        planner_exploitable_lift=0.10,
        planner_trusted_pct=40.0,
        planner_max_robust_penalty=0.40,
        # Stability
        lap_to_lap_std=0.05,
        n_laps_used=20,
        # Bookkeeping
        elapsed_s=10.0,
        pipeline_succeeded=True,
        pipeline_warnings=[],
        exception=None,
    )
    base.update(overrides)
    return SessionMetrics(**base)


# ── ThresholdProfile.overlay ────────────────────────────────


class TestOverlay:
    def test_no_partial_returns_self(self):
        p = ThresholdProfile()
        assert p.overlay({}) == p

    def test_overlay_keys_replace_only_those(self):
        p = ThresholdProfile()
        p2 = p.overlay({"max_fallback_depth_2_pct_fail": 65.0})
        assert p2.max_fallback_depth_2_pct_fail == 65.0
        assert p2.max_fallback_depth_2_pct_warn == p.max_fallback_depth_2_pct_warn
        assert p2.lambda_band == p.lambda_band

    def test_overlay_lambda_band_list_to_tuple(self):
        p = ThresholdProfile()
        p2 = p.overlay({"lambda_band": [0.7, 1.3]})
        assert p2.lambda_band == (0.7, 1.3)
        assert isinstance(p2.lambda_band, tuple)

    def test_unknown_key_rejected(self):
        p = ThresholdProfile()
        with pytest.raises(ValueError, match="Unknown threshold keys"):
            p.overlay({"made_up_threshold": 99.0})


# ── Resolution chain ────────────────────────────────────────


class TestResolution:
    def test_default_used_when_no_overrides(self):
        rt = ReleaseThresholds()
        prof = rt.resolve(track_class="banked", vehicle_class="GT4")
        assert prof == rt.default

    def test_track_class_override(self):
        rt = ReleaseThresholds(
            by_track_class={"banked": {"max_fallback_depth_2_pct_fail": 70.0}},
        )
        prof = rt.resolve(track_class="banked", vehicle_class="GT4")
        assert prof.max_fallback_depth_2_pct_fail == 70.0
        # Other fields inherit
        assert prof.lambda_band == ThresholdProfile().lambda_band

    def test_vehicle_class_override(self):
        rt = ReleaseThresholds(
            by_vehicle_class={"GT4": {"lambda_band": [0.9, 1.6]}},
        )
        prof = rt.resolve(track_class="banked", vehicle_class="GT4")
        assert prof.lambda_band == (0.9, 1.6)

    def test_track_x_vehicle_overrides_both(self):
        rt = ReleaseThresholds(
            by_track_class={"banked": {"lambda_band": [0.5, 1.5]}},
            by_vehicle_class={"GT4": {"lambda_band": [0.7, 1.5]}},
            by_track_x_vehicle={"banked,GT4": {"lambda_band": [0.9, 1.6]}},
        )
        prof = rt.resolve(track_class="banked", vehicle_class="GT4")
        assert prof.lambda_band == (0.9, 1.6)

    def test_vehicle_overrides_track_when_more_specific(self):
        rt = ReleaseThresholds(
            by_track_class={"banked": {"max_fy_residual_std_n_warn": 5000.0}},
            by_vehicle_class={"GT4": {"max_fy_residual_std_n_warn": 2500.0}},
        )
        prof = rt.resolve(track_class="banked", vehicle_class="GT4")
        # vehicle layer comes after track layer → wins
        assert prof.max_fy_residual_std_n_warn == 2500.0

    def test_unrelated_classes_get_default(self):
        rt = ReleaseThresholds(
            by_vehicle_class={"GT4": {"lambda_band": [0.9, 1.6]}},
        )
        prof = rt.resolve(track_class="flat", vehicle_class="TouringCar")
        assert prof.lambda_band == ThresholdProfile().lambda_band


class TestThresholdsFromJson:
    def test_load_real_thresholds_file(self):
        path = Path(__file__).parent.parent.parent / "data" / "release_thresholds.json"
        rt = ReleaseThresholds.from_json(path)
        # GT4 should have its own band
        prof = rt.resolve(track_class="banked", vehicle_class="GT4")
        assert prof.lambda_band == (0.9, 1.6)

    def test_missing_file_returns_defaults(self, tmp_path):
        rt = ReleaseThresholds.from_json(tmp_path / "missing.json")
        assert rt.default == ThresholdProfile()
        assert rt.by_track_class == {}

    def test_unsupported_version_rejected(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"version": 999, "default": {}}))
        with pytest.raises(ValueError, match="Unsupported"):
            ReleaseThresholds.from_json(p)

    def test_default_partial_overlays(self, tmp_path):
        p = tmp_path / "th.json"
        p.write_text(json.dumps({
            "version": 1,
            "default": {"lambda_band": [0.5, 2.0]},
        }))
        rt = ReleaseThresholds.from_json(p)
        assert rt.default.lambda_band == (0.5, 2.0)


# ── Per-session evaluation ──────────────────────────────────


class TestEvaluateSession:
    def test_healthy_passes(self):
        m = _healthy_metrics()
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.PASS
        assert res.n_fail == 0
        assert res.n_warn == 0

    def test_planner_robust_invariant_violation_fails(self):
        m = _healthy_metrics(planner_robust_mean=1.30, planner_nominal_mean=1.18)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.FAIL
        # And the specific check fired
        names = [c.name for c in res.checks if c.decision == ReleaseDecision.FAIL]
        assert "planner_robust_le_nominal" in names

    def test_planner_exploitable_invariant_violation_fails(self):
        m = _healthy_metrics(planner_exploitable_mean=1.30, planner_nominal_mean=1.18)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.FAIL

    def test_lambda_out_of_band_fails(self):
        m = _healthy_metrics(lambda_median=2.5)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.FAIL
        names = [c.name for c in res.checks if c.decision == ReleaseDecision.FAIL]
        assert "lambda_in_band" in names

    def test_lambda_in_band_pct_low_warns(self):
        m = _healthy_metrics(lambda_median=1.0, lambda_in_band_pct=20.0)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.WARN

    def test_fallback_above_fail_threshold_fails(self):
        m = _healthy_metrics(fallback_depth_2_pct=70.0)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.FAIL

    def test_fallback_in_warn_band_warns(self):
        m = _healthy_metrics(fallback_depth_2_pct=40.0)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.WARN

    def test_transition_above_fail_threshold_fails(self):
        m = _healthy_metrics(transition_quarantine_pct=50.0)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.FAIL

    def test_racing_line_inverted_fails(self):
        m = _healthy_metrics(racing_line_lift=-0.20)  # below FAIL floor (-0.10)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.FAIL

    def test_racing_line_borderline_warns(self):
        m = _healthy_metrics(racing_line_lift=-0.07)  # in WARN band
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.WARN

    def test_low_accept_fails(self):
        m = _healthy_metrics(accept_pct=5.0)
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.FAIL

    def test_high_residual_warns(self):
        m = _healthy_metrics(fy_residual_std=4000.0)
        res = evaluate_session(m, ThresholdProfile())
        # Default max_fy_residual_std_n_warn=3000 → WARN
        assert res.decision == ReleaseDecision.WARN

    def test_pipeline_failure_fails_immediately(self):
        m = _healthy_metrics(
            pipeline_succeeded=False,
            exception="RuntimeError: boom",
        )
        res = evaluate_session(m, ThresholdProfile())
        assert res.decision == ReleaseDecision.FAIL
        # Only one check (pipeline_succeeded), short-circuit
        assert len(res.checks) == 1
        assert res.checks[0].name == "pipeline_succeeded"

    def test_per_class_threshold_changes_decision(self):
        # Default: lambda_band [0.6, 1.6]; m.lambda_median=1.7 → FAIL
        m = _healthy_metrics(lambda_median=1.7)
        prof_default = ThresholdProfile()
        prof_loose = ThresholdProfile().overlay({"lambda_band": [0.5, 2.0]})
        assert evaluate_session(m, prof_default).decision == ReleaseDecision.FAIL
        assert evaluate_session(m, prof_loose).decision == ReleaseDecision.PASS


# ── Suite-level aggregation ─────────────────────────────────


class TestEvaluateSuite:
    def test_all_pass_overall_pass(self):
        m1 = _healthy_metrics(dataset_id="d1")
        m2 = _healthy_metrics(dataset_id="d2")
        report = evaluate_suite(
            suite_session_metrics=[m1, m2],
            track_classes={"d1": "banked", "d2": "flat"},
            vehicle_classes={"d1": "GT4", "d2": "TouringCar"},
            thresholds=ReleaseThresholds(),
        )
        assert report.decision == ReleaseDecision.PASS
        assert report.n_pass == 2 and report.n_warn == 0 and report.n_fail == 0
        assert report.exit_code == 0

    def test_one_warn_overall_warn(self):
        m1 = _healthy_metrics(dataset_id="d1")
        m2 = _healthy_metrics(dataset_id="d2", fallback_depth_2_pct=45.0)
        report = evaluate_suite(
            suite_session_metrics=[m1, m2],
            track_classes={"d1": "banked", "d2": "banked"},
            vehicle_classes={"d1": "GT4", "d2": "GT4"},
            thresholds=ReleaseThresholds(),
        )
        assert report.decision == ReleaseDecision.WARN
        assert report.exit_code == 1

    def test_one_fail_overall_fail(self):
        m1 = _healthy_metrics(dataset_id="d1")
        m2 = _healthy_metrics(dataset_id="d2", lambda_median=3.0)
        report = evaluate_suite(
            suite_session_metrics=[m1, m2],
            track_classes={"d1": "banked", "d2": "banked"},
            vehicle_classes={"d1": "GT4", "d2": "GT4"},
            thresholds=ReleaseThresholds(),
        )
        assert report.decision == ReleaseDecision.FAIL
        assert report.exit_code == 2

    def test_top_causes_ranked_by_count(self):
        # Two sessions both fail on the same metric → that cause leads
        m1 = _healthy_metrics(dataset_id="d1", fallback_depth_2_pct=70.0)
        m2 = _healthy_metrics(dataset_id="d2", fallback_depth_2_pct=70.0)
        m3 = _healthy_metrics(dataset_id="d3", lambda_median=3.0)
        report = evaluate_suite(
            suite_session_metrics=[m1, m2, m3],
            track_classes={k: "banked" for k in ["d1", "d2", "d3"]},
            vehicle_classes={k: "GT4" for k in ["d1", "d2", "d3"]},
            thresholds=ReleaseThresholds(),
        )
        # fallback_pct_ceiling fires twice, lambda_in_band fires once
        first = report.top_failures[0]
        assert "fallback_pct_ceiling" in first
        assert "(2)" in first

    def test_class_overrides_change_outcome(self):
        # Without override, fallback at 65% would FAIL (default fail=60)
        # With banked override (fail=65), it stays at the boundary
        m = _healthy_metrics(dataset_id="d1", fallback_depth_2_pct=64.0)
        rt_default = ReleaseThresholds()
        rt_loose = ReleaseThresholds(
            by_track_class={"banked": {"max_fallback_depth_2_pct_fail": 70.0}},
        )
        r_default = evaluate_suite(
            suite_session_metrics=[m],
            track_classes={"d1": "banked"}, vehicle_classes={"d1": "GT4"},
            thresholds=rt_default,
        )
        r_loose = evaluate_suite(
            suite_session_metrics=[m],
            track_classes={"d1": "banked"}, vehicle_classes={"d1": "GT4"},
            thresholds=rt_loose,
        )
        assert r_default.decision == ReleaseDecision.FAIL
        # loose still WARN because warn=30 default (not overridden)
        assert r_loose.decision == ReleaseDecision.WARN

    def test_smoke_mode_flag_propagates(self):
        m = _healthy_metrics(dataset_id="d1")
        report = evaluate_suite(
            suite_session_metrics=[m],
            track_classes={"d1": "banked"}, vehicle_classes={"d1": "GT4"},
            thresholds=ReleaseThresholds(),
            smoke_mode=True,
        )
        assert report.smoke_mode is True
        assert report.to_dict()["smoke_mode"] is True


# ── Decision ordering ───────────────────────────────────────


class TestDecisionOrdering:
    def test_is_at_least(self):
        assert ReleaseDecision.FAIL.is_at_least(ReleaseDecision.WARN)
        assert ReleaseDecision.FAIL.is_at_least(ReleaseDecision.PASS)
        assert ReleaseDecision.WARN.is_at_least(ReleaseDecision.PASS)
        assert not ReleaseDecision.PASS.is_at_least(ReleaseDecision.WARN)


# ── Markdown rendering ──────────────────────────────────────


class TestMarkdown:
    def test_renders_pass(self):
        m = _healthy_metrics(dataset_id="d1")
        report = evaluate_suite(
            suite_session_metrics=[m],
            track_classes={"d1": "banked"}, vehicle_classes={"d1": "GT4"},
            thresholds=ReleaseThresholds(),
        )
        md = render_markdown(report)
        assert "PASS" in md
        assert "Headline" in md
        assert "d1" in md

    def test_renders_with_warnings(self):
        m = _healthy_metrics(dataset_id="d1", fallback_depth_2_pct=45.0)
        report = evaluate_suite(
            suite_session_metrics=[m],
            track_classes={"d1": "banked"}, vehicle_classes={"d1": "GT4"},
            thresholds=ReleaseThresholds(),
        )
        md = render_markdown(report)
        assert "Top warning causes" in md
        assert "fallback_pct_ceiling" in md

    def test_renders_with_failures(self):
        m = _healthy_metrics(dataset_id="d1", lambda_median=3.0)
        report = evaluate_suite(
            suite_session_metrics=[m],
            track_classes={"d1": "banked"}, vehicle_classes={"d1": "GT4"},
            thresholds=ReleaseThresholds(),
        )
        md = render_markdown(report)
        assert "FAIL" in md
        assert "lambda_in_band" in md
        assert "Per-session WARN/FAIL detail" in md


# ── JSON serialization ──────────────────────────────────────


class TestJsonSerialization:
    def test_report_to_dict_is_json_safe(self):
        m = _healthy_metrics(dataset_id="d1")
        report = evaluate_suite(
            suite_session_metrics=[m],
            track_classes={"d1": "banked"}, vehicle_classes={"d1": "GT4"},
            thresholds=ReleaseThresholds(),
        )
        d = report.to_dict()
        # Must round-trip through JSON without errors
        s = json.dumps(d)
        parsed = json.loads(s)
        assert parsed["decision"] == "pass"
        assert parsed["n_sessions"] == 1
        assert "schema_version" in parsed
        assert "sessions" in parsed
        assert parsed["sessions"][0]["dataset_id"] == "d1"
