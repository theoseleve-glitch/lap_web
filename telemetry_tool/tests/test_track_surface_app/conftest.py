"""Fixtures for track_surface_app tests. No real physics is invoked."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


# ── Minimal stand-in for track_surface.validation.harness.PipelineResult ──
# Mirrors the real dataclass fields the app layer consumes. Using a local
# dataclass keeps tests independent of the core module.

@dataclass
class FakePipelineResult:
    dataset_id: str = "fake-dataset"
    n_samples_total: int = 10_000
    n_valid: int = 9_500
    best_lap: int = 3
    best_lap_time_s: float = 88.123
    n_laps: int = 5
    lap_times_s: dict[int, float] = field(default_factory=lambda: {1: 90.0, 2: 89.1, 3: 88.1, 4: 88.5, 5: 89.7})
    track_length_m: float = 3820.0
    field_coverage_pct: float = 85.0
    field_mean_confidence: float = 0.82
    field_high_conf_cells: int = 300
    field_zero_conf_cells: int = 20
    field_cells_observed: int = 450
    field_cells_total: int = 500
    bucket_active_count: int = 6
    bucket_sparse_count: int = 0
    bucket_fallback_distribution: dict[int, int] = field(default_factory=lambda: {0: 800, 1: 150, 2: 50})
    planner_nominal_mean_mu: float = 1.05
    planner_robust_mean_mu: float = 0.98
    planner_exploitable_mean_mu: float = 1.12
    planner_n_trusted: int = 900
    planner_n_degraded: int = 100
    planner_max_robust_penalty: float = 0.08
    racing_line_center_lambda: float = 0.95
    racing_line_left_lambda: float = 0.90
    racing_line_right_lambda: float = 0.92
    calibration_profile_id: str | None = "iracing_mx5_2024"
    calibration_source: str | None = "registry_active"
    pipeline_warnings: list[str] = field(default_factory=list)
    exception: str | None = None
    bucket_diagnostics: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 2.3
    gate_accept_pct: float = 85.0
    transition_pct: float = 8.0
    fy_residual_std: float = 1500.0
    fx_residual_std: float = 1200.0


@dataclass
class FakeReleaseDecision:
    # Mirrors track_surface.validation.release_gate.ReleaseDecision enum-ish
    value: str       # "pass" | "warn" | "fail"


@dataclass
class FakeReleaseSessionResult:
    dataset_id: str = "fake-dataset"
    track_class: str = "flat"
    vehicle_class: str = "mx5"
    profile_description: str = "default"
    decision: FakeReleaseDecision = field(default_factory=lambda: FakeReleaseDecision("pass"))
    checks: list = field(default_factory=list)
    n_pass: int = 10
    n_warn: int = 0
    n_fail: int = 0


# ── Factory fixtures ─────────────────────────────────────────

@pytest.fixture
def make_pipeline_result():
    """Factory: build a FakePipelineResult with targeted tier overrides."""
    def _build(**overrides) -> FakePipelineResult:
        pr = FakePipelineResult()
        for k, v in overrides.items():
            setattr(pr, k, v)
        return pr
    return _build


@pytest.fixture
def make_release_result():
    """Factory: build a FakeReleaseSessionResult for the given decision string."""
    def _build(decision: str = "pass", **overrides) -> FakeReleaseSessionResult:
        rr = FakeReleaseSessionResult(decision=FakeReleaseDecision(decision))
        for k, v in overrides.items():
            setattr(rr, k, v)
        return rr
    return _build


# ── Tier-targeted fixtures (use in support-resolver + gating tests) ───

@pytest.fixture
def tier_a_inputs(make_pipeline_result, make_release_result):
    """PipelineResult + ReleaseResult that MUST yield tier A."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 900, 1: 50, 2: 50},   # fb2 = 5%
        calibration_source="registry_active",
        field_mean_confidence=0.82,
    )
    rr = make_release_result("pass")
    return pr, rr


@pytest.fixture
def tier_b_inputs_fallback(make_pipeline_result, make_release_result):
    """Tier B via moderate fallback (fb2 = 15%)."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 750, 1: 100, 2: 150},
        calibration_source="registry_active",
        field_mean_confidence=0.68,
    )
    rr = make_release_result("pass")
    return pr, rr


@pytest.fixture
def tier_b_inputs_warn(make_pipeline_result, make_release_result):
    """Tier B via release gate WARN."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 900, 1: 50, 2: 50},   # fb2 = 5%, but WARN dominates
        calibration_source="registry_active",
    )
    rr = make_release_result("warn")
    return pr, rr


@pytest.fixture
def tier_c_inputs_fail(make_pipeline_result, make_release_result):
    """Tier C via release gate FAIL."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 800, 1: 100, 2: 100},
        calibration_source="registry_active",
        field_mean_confidence=0.4,
    )
    rr = make_release_result("fail")
    return pr, rr


@pytest.fixture
def tier_c_inputs_fallback(make_pipeline_result, make_release_result):
    """Tier C via high global fallback (fb2 = 40%)."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 300, 1: 300, 2: 400},
        calibration_source="registry_active",
        field_mean_confidence=0.45,
    )
    rr = make_release_result("pass")
    return pr, rr


@pytest.fixture
def tier_d_inputs_no_calibration(make_pipeline_result, make_release_result):
    """Tier D via missing vehicle calibration."""
    pr = make_pipeline_result(calibration_source="none")
    rr = make_release_result("pass")
    return pr, rr


@pytest.fixture
def tier_d_inputs_default_calibration(make_pipeline_result, make_release_result):
    """Tier D via unvalidated (default) calibration fallback."""
    pr = make_pipeline_result(calibration_source="default")
    rr = make_release_result("pass")
    return pr, rr
