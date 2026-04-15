"""Tests for the cross-track validation harness.

These tests use synthetic PipelineResult instances — they do NOT
require any .ibt file to be on disk. The pipeline_runner itself is
exercised separately in the integration smoke test.
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from track_surface.validation import (
    DatasetEntry,
    ExpectedMetrics,
    PipelineResult,
    SessionInfo,
    SessionMetrics,
    TrackSpec,
    ValidationManifest,
    ValidationWarning,
    VehicleSpec,
    WarningSeverity,
    classify_warnings,
    compute_metrics,
    load_manifest,
    write_aggregate_report,
    write_session_report,
)
from track_surface.validation.classifier import overall_severity
from track_surface.validation.suite import _run_one_pass


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def vehicle_gt4() -> VehicleSpec:
    return VehicleSpec(
        name="McLaren 570S GT4",
        klass="GT4",
        drive_layout="RWD",
        mass_kg=1222.5,
        wheelbase_m=2.67,
        track_front_m=1.666,
        track_rear_m=1.627,
        weight_dist_front=0.435,
        aero_cla=1.46,
        cg_height_m=0.15,
        brake_bias_front=0.49,
        steer_ratio=14.0,
        camber_front_deg=-4.0,
        camber_rear_deg=-2.8,
    )


@pytest.fixture
def track_daytona() -> TrackSpec:
    return TrackSpec(
        name="Daytona Road Course",
        layout="2011_road",
        regime="banked",
        expected_max_bank_deg=31.0,
        track_length_m=5729.0,
    )


@pytest.fixture
def expected_band() -> ExpectedMetrics:
    return ExpectedMetrics(
        lambda_band=(0.9, 1.6),
        min_observability_pct=50.0,
        racing_line_lift_min=0.0,
        min_field_coverage_pct=15.0,
        max_lap_to_lap_std=0.10,
        max_fy_residual_std=2500.0,
    )


@pytest.fixture
def daytona_entry(vehicle_gt4, track_daytona, expected_band) -> DatasetEntry:
    return DatasetEntry(
        id="daytona_test",
        ibt_path="C:/nonexistent/test.ibt",
        group="A_banked",
        track=track_daytona,
        vehicle=vehicle_gt4,
        session=SessionInfo(type="practice", kappa_available=False, ride_height_available=True),
        expected=expected_band,
    )


def _make_healthy_result() -> PipelineResult:
    """Realistic Daytona-baseline result."""
    r = PipelineResult(
        dataset_id="daytona_test",
        ibt_path="C:/nonexistent/test.ibt",
    )
    r.n_samples_total = 526779
    r.n_valid = 500000
    r.best_lap = 12
    r.best_lap_time_s = 113.97
    r.n_laps = 74
    r.lap_times_s = {i: 114.0 + 0.5 * (i % 3) for i in range(1, 16)}
    r.track_length_m = 5729.0

    r.bank_min_deg = -31.0
    r.bank_max_deg = 31.0
    r.bank_mean_abs_deg = 8.0
    r.grade_min_deg = -2.0
    r.grade_max_deg = 2.0
    r.n_transition_quarantined = 5000
    r.transition_pct = 1.0
    r.a_lat_raw_mean = 0.15
    r.a_lat_tire_mean = -0.05

    r.roll_compliance_used = 0.005
    r.tire_d1_lat_used = 2.8
    r.tire_d1_long_used = 2.7

    r.n_accepted_blocks = 30810
    r.n_rejected_blocks = 21868
    r.reject_reasons = {"low_speed": 456, "low_excitation": 117268, "low_demand": 46884}
    r.lambda_count = 308100
    r.lambda_mean = 1.39
    r.lambda_median = 1.35
    r.lambda_std = 0.12
    r.lambda_p5 = 0.95
    r.lambda_p95 = 1.55
    r.lambda_min = 0.4
    r.lambda_max = 2.0
    r.excitation_mean = 0.55

    r.lap_lambdas = {i: 1.20 + 0.02 * (i % 5) for i in range(1, 16)}

    r.field_grid_shape = (1139, 24)
    r.field_cells_observed = 5017
    r.field_cells_total = 27336
    r.field_coverage_pct = 18.35
    r.field_mean_observed = 1.18
    r.field_std_observed = 0.13
    r.field_mean_confidence = 0.16
    r.field_high_conf_cells = 50
    r.field_zero_conf_cells = 22319
    r.field_max_obs_per_cell = 345

    r.bucket_diagnostics = {
        "flat/early":  {"n_cells": 100, "lambda_mean": 1.20},
        "flat/mid":    {"n_cells": 200, "lambda_mean": 1.18},
        "flat/late":   {"n_cells": 50,  "lambda_mean": 1.16},
        "banked/early":{"n_cells": 80,  "lambda_mean": 1.30},
        "banked/mid":  {"n_cells": 150, "lambda_mean": 1.28},
        "banked/late": {"n_cells": 40,  "lambda_mean": 1.27},
    }
    r.bucket_active_count = 6
    r.bucket_sparse_count = 1
    r.bucket_fallback_distribution = {0: 400, 1: 100, 2: 73}

    r.racing_line_center_lambda = 1.24
    r.racing_line_left_lambda = 1.22
    r.racing_line_right_lambda = 1.19

    r.fy_residual_mean = 100.0
    r.fy_residual_std = 1500.0
    r.fx_residual_mean = 50.0
    r.fx_residual_std = 1200.0

    r.planner_nominal_mean_mu = 1.18
    r.planner_robust_mean_mu = 0.95
    r.planner_exploitable_mean_mu = 1.10
    r.planner_n_trusted = 200
    r.planner_n_degraded = 300
    r.planner_n_transition_excluded = 73
    r.planner_max_robust_penalty = 0.4
    r.planner_sectors_most_tightened = [(1500.0, 0.4)]

    r.elapsed_s = 12.3
    return r


@pytest.fixture
def healthy_result() -> PipelineResult:
    return _make_healthy_result()


# ── Manifest tests ──────────────────────────────────────────


class TestManifestLoading:
    def test_load_real_manifest(self):
        manifest_path = Path(__file__).parent.parent.parent / "data" / "cross_track_manifest.json"
        manifest = load_manifest(manifest_path)
        assert manifest.version == 1
        assert len(manifest.datasets) >= 1
        assert all(isinstance(e, DatasetEntry) for e in manifest.datasets)

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path / "missing.json")

    def test_load_missing_version(self, tmp_path):
        f = tmp_path / "m.json"
        f.write_text(json.dumps({"datasets": []}))
        with pytest.raises(ValueError, match="version"):
            load_manifest(f)

    def test_load_unsupported_version(self, tmp_path):
        f = tmp_path / "m.json"
        f.write_text(json.dumps({"version": 999, "datasets": []}))
        with pytest.raises(ValueError, match="Unsupported"):
            load_manifest(f)

    def test_load_bad_regime(self, tmp_path, vehicle_gt4):
        f = tmp_path / "m.json"
        f.write_text(json.dumps({
            "version": 1,
            "datasets": [{
                "id": "x", "ibt_path": "/p", "group": "A_banked",
                "track": {"name": "T", "layout": "L", "regime": "wibbly"},
                "vehicle": _vehicle_dict(vehicle_gt4),
            }],
        }))
        with pytest.raises(ValueError, match="regime"):
            load_manifest(f)

    def test_load_bad_drive_layout(self, tmp_path, vehicle_gt4):
        f = tmp_path / "m.json"
        veh = _vehicle_dict(vehicle_gt4)
        veh["drive_layout"] = "Magic"
        f.write_text(json.dumps({
            "version": 1,
            "datasets": [{
                "id": "x", "ibt_path": "/p", "group": "A_banked",
                "track": {"name": "T", "layout": "L", "regime": "flat"},
                "vehicle": veh,
            }],
        }))
        with pytest.raises(ValueError, match="drive_layout"):
            load_manifest(f)

    def test_duplicate_id_rejected(self, tmp_path, vehicle_gt4):
        f = tmp_path / "m.json"
        veh = _vehicle_dict(vehicle_gt4)
        track = {"name": "T", "layout": "L", "regime": "flat"}
        f.write_text(json.dumps({
            "version": 1,
            "datasets": [
                {"id": "dup", "ibt_path": "/a", "group": "A_banked",
                 "track": track, "vehicle": veh},
                {"id": "dup", "ibt_path": "/b", "group": "A_banked",
                 "track": track, "vehicle": veh},
            ],
        }))
        with pytest.raises(ValueError, match="Duplicate"):
            load_manifest(f)

    def test_filter_by_id(self, daytona_entry):
        manifest = ValidationManifest(version=1, datasets=[
            daytona_entry,
            replace(daytona_entry, id="other"),
        ])
        filtered = manifest.filter(["other"])
        assert len(filtered) == 1
        assert filtered[0].id == "other"

    def test_filter_unknown_raises(self, daytona_entry):
        manifest = ValidationManifest(version=1, datasets=[daytona_entry])
        with pytest.raises(KeyError, match="missing"):
            manifest.filter(["nope"])

    def test_get_by_id(self, daytona_entry):
        manifest = ValidationManifest(version=1, datasets=[daytona_entry])
        assert manifest.get("daytona_test") is daytona_entry
        with pytest.raises(KeyError):
            manifest.get("nope")

    def test_by_group(self, daytona_entry):
        manifest = ValidationManifest(version=1, datasets=[
            daytona_entry,
            replace(daytona_entry, id="other", group="B_flat_low_speed"),
        ])
        groups = manifest.by_group
        assert "A_banked" in groups
        assert "B_flat_low_speed" in groups


def _vehicle_dict(v: VehicleSpec) -> dict:
    return {
        "name": v.name, "class": v.klass, "drive_layout": v.drive_layout,
        "mass_kg": v.mass_kg, "wheelbase_m": v.wheelbase_m,
        "track_front_m": v.track_front_m, "track_rear_m": v.track_rear_m,
        "weight_dist_front": v.weight_dist_front, "aero_cla": v.aero_cla,
        "cg_height_m": v.cg_height_m, "brake_bias_front": v.brake_bias_front,
        "steer_ratio": v.steer_ratio, "camber_front_deg": v.camber_front_deg,
        "camber_rear_deg": v.camber_rear_deg,
    }


# ── Metric computation ──────────────────────────────────────


class TestMetricsComputation:
    def test_healthy_result_passes(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        assert m.dataset_id == "daytona_test"
        assert m.lambda_median == healthy_result.lambda_median
        assert m.coverage_pct == healthy_result.field_coverage_pct
        assert m.bucket_active_count == 6

    def test_accept_pct_computed(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        expected = 100.0 * 30810 / (30810 + 21868)
        assert abs(m.accept_pct - expected) < 0.01

    def test_racing_line_lift(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        off = 0.5 * (1.22 + 1.19)
        assert abs(m.racing_line_lift - (1.24 - off)) < 1e-6

    def test_lap_to_lap_std(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        # All lap_lambdas were 1.20-1.28 → small std
        assert m.lap_to_lap_std < 0.05
        assert m.n_laps_used == 15

    def test_lambda_in_band_pct_inside(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        # Median 1.35 is well inside [0.9, 1.6] — should be > 50%
        assert m.lambda_in_band_pct > 50.0

    def test_lambda_in_band_pct_outside(self, healthy_result, daytona_entry):
        bad = replace(daytona_entry, expected=replace(
            daytona_entry.expected, lambda_band=(0.5, 0.7)
        ))
        m = compute_metrics(healthy_result, bad)
        assert m.lambda_in_band_pct == 0.0

    def test_planner_invariants_computed(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        assert m.planner_robust_tightening > 0  # robust < nominal → positive tightening
        assert m.planner_exploitable_lift > 0   # exploitable > robust → positive lift
        assert m.planner_trusted_pct > 0

    def test_flat_vs_banked_diff(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        # flat avg = (1.20+1.18+1.16)/3 = 1.18
        # banked avg = (1.30+1.28+1.27)/3 = 1.283
        # diff ~= 0.10
        assert m.flat_vs_banked_lambda_diff is not None
        assert 0.05 < m.flat_vs_banked_lambda_diff < 0.20

    def test_flat_vs_banked_none_if_only_flat(self, daytona_entry):
        result = _make_healthy_result()
        result.bucket_diagnostics = {
            "flat/mid": {"n_cells": 100, "lambda_mean": 1.18},
            "banked/mid": {"n_cells": 0, "lambda_mean": None},
        }
        m = compute_metrics(result, daytona_entry)
        assert m.flat_vs_banked_lambda_diff is None

    def test_fallback_depth_2_pct(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        # 73 / (400+100+73) ~= 12.7%
        assert 12.0 < m.fallback_depth_2_pct < 14.0

    def test_pipeline_failure_propagates(self, daytona_entry):
        result = _make_healthy_result()
        result.exception = "RuntimeError: synthetic"
        result.lambda_count = 0
        m = compute_metrics(result, daytona_entry)
        assert m.pipeline_succeeded is False
        assert m.exception == "RuntimeError: synthetic"


# ── Warning classification ──────────────────────────────────


class TestClassifier:
    def test_healthy_session_no_fail(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=healthy_result)
        assert all(w.severity != WarningSeverity.FAIL for w in warnings)

    def test_band_violation_fails(self, healthy_result, daytona_entry):
        bad = replace(daytona_entry, expected=replace(
            daytona_entry.expected, lambda_band=(0.5, 0.7)
        ))
        m = compute_metrics(healthy_result, bad)
        warnings = classify_warnings(m, bad, result=healthy_result)
        cats = [w.category for w in warnings if w.severity == WarningSeverity.FAIL]
        assert "lambda_out_of_band" in cats

    def test_inverted_racing_line_fails(self, daytona_entry):
        result = _make_healthy_result()
        # Center much lower than off-line
        result.racing_line_center_lambda = 1.05
        result.racing_line_left_lambda = 1.30
        result.racing_line_right_lambda = 1.30
        m = compute_metrics(result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=result)
        cats = [w.category for w in warnings if w.severity == WarningSeverity.FAIL]
        assert "racing_line_inverted" in cats

    def test_planner_invariant_violation_fails(self, daytona_entry):
        result = _make_healthy_result()
        # Robust > Nominal — broken
        result.planner_robust_mean_mu = 1.50
        result.planner_nominal_mean_mu = 1.18
        m = compute_metrics(result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=result)
        cats = [w.category for w in warnings if w.severity == WarningSeverity.FAIL]
        assert "planner_infeasibility" in cats

    def test_excessive_fallback_warns(self, daytona_entry):
        result = _make_healthy_result()
        # Most grid points use global prior
        result.bucket_fallback_distribution = {0: 10, 1: 10, 2: 200}
        m = compute_metrics(result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=result)
        cats = [w.category for w in warnings]
        assert "excessive_fallback" in cats

    def test_low_observability_warns(self, daytona_entry):
        result = _make_healthy_result()
        result.n_accepted_blocks = 100
        result.n_rejected_blocks = 9000  # 1.1% accept rate
        m = compute_metrics(result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=result)
        cats = [w.category for w in warnings if w.severity == WarningSeverity.FAIL]
        assert "low_observability" in cats

    def test_sparse_bucket_fails_when_zero_active(self, daytona_entry):
        result = _make_healthy_result()
        result.bucket_active_count = 0
        m = compute_metrics(result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=result)
        cats = [w.category for w in warnings if w.severity == WarningSeverity.FAIL]
        assert "sparse_bucket" in cats

    def test_no_kappa_emits_info_warning(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=healthy_result)
        cats = [w.category for w in warnings]
        # daytona_entry has kappa_available=False
        assert "no_kappa_available" in cats

    def test_pipeline_exception_emits_fail(self, daytona_entry):
        result = _make_healthy_result()
        result.exception = "RuntimeError: x"
        result.lambda_count = 0
        m = compute_metrics(result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=result)
        assert len(warnings) == 1
        assert warnings[0].category == "pipeline_exception"
        assert warnings[0].severity == WarningSeverity.FAIL

    def test_severity_ordering(self):
        assert WarningSeverity.FAIL.is_at_least(WarningSeverity.WARN)
        assert WarningSeverity.WARN.is_at_least(WarningSeverity.OK)
        assert not WarningSeverity.OK.is_at_least(WarningSeverity.WARN)

    def test_overall_severity_picks_worst(self):
        ws = [
            ValidationWarning("c1", WarningSeverity.OK, "m", 0, 0, ""),
            ValidationWarning("c2", WarningSeverity.WARN, "m", 0, 0, ""),
            ValidationWarning("c3", WarningSeverity.WARN, "m", 0, 0, ""),
        ]
        assert overall_severity(ws) == WarningSeverity.WARN
        ws.append(ValidationWarning("c4", WarningSeverity.FAIL, "m", 0, 0, ""))
        assert overall_severity(ws) == WarningSeverity.FAIL


# ── Reporter ────────────────────────────────────────────────


class TestReporter:
    def test_session_report_writes_valid_json(
        self, tmp_path, healthy_result, daytona_entry,
    ):
        m = compute_metrics(healthy_result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=healthy_result)
        out = tmp_path / "session.json"
        write_session_report(
            out, entry=daytona_entry, result=healthy_result,
            metrics=m, warnings=warnings, pass_label="frozen",
        )
        assert out.is_file()
        loaded = json.loads(out.read_text())
        assert loaded["pass"] == "frozen"
        assert loaded["entry"]["id"] == "daytona_test"
        assert loaded["metrics"]["lambda_median"] == healthy_result.lambda_median
        assert "overall_severity" in loaded
        assert isinstance(loaded["warnings"], list)

    def test_aggregate_report_renders_markdown(
        self, tmp_path, healthy_result, daytona_entry,
    ):
        m = compute_metrics(healthy_result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=healthy_result)
        rows = [{
            "entry": daytona_entry,
            "result": healthy_result,
            "metrics": m,
            "warnings": warnings,
            "overall": overall_severity(warnings),
        }]
        out = tmp_path / "aggregate.md"
        write_aggregate_report(out, suite_results=rows, pass_label="frozen")
        text = out.read_text()
        assert "Cross-Track Validation Report" in text
        assert "daytona_test" in text
        assert "PASS" in text or "WARN" in text or "FAIL" in text
        assert "## Comparison" in text
        assert "## Top Regression Causes" in text


# ── Suite orchestrator ──────────────────────────────────────


class TestSuiteOrchestrator:
    def test_skip_missing_files(self, tmp_path, daytona_entry):
        manifest = ValidationManifest(version=1, datasets=[daytona_entry])
        from track_surface.validation.harness import PipelineConfig
        result = _run_one_pass(
            manifest=manifest,
            out_dir=tmp_path,
            config=PipelineConfig(),
            pass_label="frozen",
            only_datasets=None,
            skip_missing=True,
        )
        # Daytona entry's ibt_path doesn't exist → skipped → 0 sessions
        assert result.n_total == 0
        assert (tmp_path / "aggregate.md").is_file()
        assert (tmp_path / "suite_summary.json").is_file()

    def test_strict_missing_raises(self, tmp_path, daytona_entry):
        manifest = ValidationManifest(version=1, datasets=[daytona_entry])
        from track_surface.validation.harness import PipelineConfig
        with pytest.raises(FileNotFoundError):
            _run_one_pass(
                manifest=manifest,
                out_dir=tmp_path,
                config=PipelineConfig(),
                pass_label="frozen",
                only_datasets=None,
                skip_missing=False,
            )


# ── Reproducibility ─────────────────────────────────────────


class TestReproducibility:
    def test_metric_computation_is_deterministic(self, healthy_result, daytona_entry):
        m1 = compute_metrics(healthy_result, daytona_entry)
        m2 = compute_metrics(copy.deepcopy(healthy_result), daytona_entry)
        assert m1.to_dict() == m2.to_dict()

    def test_classifier_is_deterministic(self, healthy_result, daytona_entry):
        m = compute_metrics(healthy_result, daytona_entry)
        w1 = classify_warnings(m, daytona_entry, result=healthy_result)
        w2 = classify_warnings(m, daytona_entry, result=healthy_result)
        assert [w.to_dict() for w in w1] == [w.to_dict() for w in w2]

    def test_session_report_round_trip(
        self, tmp_path, healthy_result, daytona_entry,
    ):
        m = compute_metrics(healthy_result, daytona_entry)
        warnings = classify_warnings(m, daytona_entry, result=healthy_result)
        out_a = tmp_path / "a.json"
        out_b = tmp_path / "b.json"
        write_session_report(
            out_a, entry=daytona_entry, result=healthy_result,
            metrics=m, warnings=warnings, pass_label="frozen",
        )
        write_session_report(
            out_b, entry=daytona_entry, result=healthy_result,
            metrics=m, warnings=warnings, pass_label="frozen",
        )
        a = json.loads(out_a.read_text())
        b = json.loads(out_b.read_text())
        # Strip generated_at — not deterministic across calls
        a.pop("generated_at", None)
        b.pop("generated_at", None)
        assert a == b


# ── Vehicle/Track validation ───────────────────────────────


class TestSpecValidation:
    def test_invalid_weight_dist_rejected(self):
        with pytest.raises(ValueError, match="weight_dist_front"):
            VehicleSpec(
                name="X", klass="C", drive_layout="RWD",
                mass_kg=1000, wheelbase_m=2.5,
                track_front_m=1.5, track_rear_m=1.5,
                weight_dist_front=1.5,  # bad
                aero_cla=1.0, cg_height_m=0.3,
                brake_bias_front=0.5, steer_ratio=14.0,
                camber_front_deg=-3.0, camber_rear_deg=-2.0,
            )

    def test_negative_mass_rejected(self):
        with pytest.raises(ValueError, match="mass_kg"):
            VehicleSpec(
                name="X", klass="C", drive_layout="RWD",
                mass_kg=-100, wheelbase_m=2.5,
                track_front_m=1.5, track_rear_m=1.5,
                weight_dist_front=0.5,
                aero_cla=1.0, cg_height_m=0.3,
                brake_bias_front=0.5, steer_ratio=14.0,
                camber_front_deg=-3.0, camber_rear_deg=-2.0,
            )

    def test_invalid_regime_rejected(self):
        with pytest.raises(ValueError, match="regime"):
            TrackSpec(name="X", layout="L", regime="bumpy")

    def test_invalid_session_type_rejected(self):
        with pytest.raises(ValueError, match="type"):
            SessionInfo(type="parade")

    def test_invalid_id_rejected(self):
        valid_track = TrackSpec(name="X", layout="L", regime="flat")
        valid_vehicle = VehicleSpec(
            name="X", klass="C", drive_layout="RWD",
            mass_kg=1000, wheelbase_m=2.5,
            track_front_m=1.5, track_rear_m=1.5,
            weight_dist_front=0.5, aero_cla=1.0, cg_height_m=0.3,
            brake_bias_front=0.5, steer_ratio=14.0,
            camber_front_deg=-3.0, camber_rear_deg=-2.0,
        )
        with pytest.raises(ValueError, match="alphanumeric"):
            DatasetEntry(
                id="bad id with spaces!",
                ibt_path="/p", group="A_banked",
                track=valid_track, vehicle=valid_vehicle,
                session=SessionInfo(), expected=ExpectedMetrics(),
            )

    def test_invalid_group_rejected(self):
        valid_track = TrackSpec(name="X", layout="L", regime="flat")
        valid_vehicle = VehicleSpec(
            name="X", klass="C", drive_layout="RWD",
            mass_kg=1000, wheelbase_m=2.5,
            track_front_m=1.5, track_rear_m=1.5,
            weight_dist_front=0.5, aero_cla=1.0, cg_height_m=0.3,
            brake_bias_front=0.5, steer_ratio=14.0,
            camber_front_deg=-3.0, camber_rear_deg=-2.0,
        )
        with pytest.raises(ValueError, match="group"):
            DatasetEntry(
                id="x", ibt_path="/p", group="Z_unknown",
                track=valid_track, vehicle=valid_vehicle,
                session=SessionInfo(), expected=ExpectedMetrics(),
            )
