"""Asserts the spec's validation gates against a harness report.

Gated by OCP2D_VALIDATION_REPORT (path to the JSON emitted by
scripts/validate_ocp2d.py) — mirrors the TEST_DATABASE_URL gating
convention.  Unset → SKIP locally; the Lane-1 sign-off run MUST execute
this with a real report produced from real track data AND --vehicle-json
(gate 4 is structurally invalid without real vehicle params).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_REPORT = os.environ.get("OCP2D_VALIDATION_REPORT", "")

needs_report = pytest.mark.skipif(
    not _REPORT, reason="OCP2D_VALIDATION_REPORT not set"
)


@pytest.fixture(scope="module")
def report() -> dict:
    data = json.loads(Path(_REPORT).read_text())
    assert "error" not in data, (
        f"harness failed at {data.get('failed_at')}: {data.get('error')}"
    )
    return data


@needs_report
def test_report_is_a_sign_off_run(report):
    """The sign-off report must come from real vehicle params and real laps."""
    assert report["vehicle_params"] == "from_json", (
        "gate 4 is meaningless against the default GT vehicle — "
        "re-run the harness with --vehicle-json"
    )
    assert report["n_laps"] >= 3, "need at least 3 full laps for a meaningful gate 2"


@needs_report
def test_gate1_determinism(report):
    assert report["gates"]["gate1_determinism"]["passed"] is True


@needs_report
def test_gate2_dry_line_plausibility(report):
    g = report["gates"]["gate2_dry_plausibility"]
    assert g["passed"] is True, (
        f"dry line deviates {g['median_dev_m']}m lap-equalized median "
        f"(target {g['target_median_m']}m; pooled {g['pooled_median_dev_m']}m, "
        f"p90 {g['p90_dev_m']}m)"
    )


@needs_report
def test_gate3_wet_correctness(report):
    g = report["gates"]["gate3_wet_correctness"]
    assert g["wet_line_better"], (
        f"wet line carries no more grip than the dry line "
        f"({g['mean_mu_wet_line']} vs {g['mean_mu_dry_line_under_wet_field']})"
    )
    assert g["puddle_crossings"] == 0
    assert g["wet_solver_status"] in ("optimal", "acceptable")
    assert g["passed"] is True


@needs_report
def test_gate4_laptime_sanity(report):
    g = report["gates"]["gate4_laptime_sanity"]
    assert g["status"] == "valid", "run the harness with --vehicle-json"
    assert g["passed"] is True, (
        f"predicted {g['predicted_s']}s vs real {g['best_real_s']}s "
        f"({g['pct_err']}% err, target {g['target_pct']}%)"
    )


@needs_report
def test_gate5_robustness(report):
    g = report["gates"]["gate5_robustness"]
    assert g["passed"] is True, (
        f"status={g['solver_status']} time={g['solve_time_s']}s"
    )
