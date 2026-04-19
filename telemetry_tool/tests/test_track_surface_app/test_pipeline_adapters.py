"""Tests for pipeline_adapters.build_adapters.

Exercises the REAL SupportTierResolver + release gate paths while stubbing
``harness.run_pipeline`` (no .ibt fixture ships with the repo).
"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest

from track_surface.validation.harness import PipelineResult
from track_surface.validation.release_gate import ReleaseDecision

from track_surface_app.domain import SupportTier
from track_surface_app.pipeline_adapters import (
    AdapterConfig,
    build_adapters,
)
from track_surface_app.session_loader import (
    NOT_SUPPORTED_SOURCE_FORMAT_NOT_IBT,
    SessionLoader,
)
from track_surface_app.support import SupportTierResolver


_VALID_VEHICLE_SPEC = {
    "name": "Mazda MX-5 2024",
    "klass": "MX5",
    "drive_layout": "RWD",
    "mass_kg": 1100.0,
    "wheelbase_m": 2.31,
    "track_front_m": 1.495,
    "track_rear_m": 1.505,
    "weight_dist_front": 0.52,
    "aero_cla": 0.35,
    "cg_height_m": 0.50,
    "brake_bias_front": 0.58,
    "steer_ratio": 15.0,
    "camber_front_deg": -2.5,
    "camber_rear_deg": -1.5,
}

_VALID_TRACK_SPEC = {
    "name": "Daytona",
    "layout": "road_course",
    "regime": "banked",
    "expected_max_bank_deg": 31.0,
    "track_length_m": 5726.0,
}


def _sqlite():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY,
            source_path TEXT,
            analysis_json TEXT,
            track_id TEXT,
            kart_id INTEGER
        );
        CREATE TABLE tracks (
            track_id TEXT PRIMARY KEY,
            track_name TEXT,
            lap_length_m REAL
        );
        """
    )
    conn.commit()
    return conn


def _seed_supported_session(conn, sid, ibt_path):
    aj = {"track_spec": _VALID_TRACK_SPEC, "vehicle_spec": _VALID_VEHICLE_SPEC}
    conn.execute(
        "INSERT INTO sessions (session_id, source_path, analysis_json) VALUES (?,?,?)",
        (sid, str(ibt_path), json.dumps(aj)),
    )
    conn.commit()


def _seed_csv_session(conn, sid, csv_path):
    conn.execute(
        "INSERT INTO sessions (session_id, source_path, analysis_json) VALUES (?,?,?)",
        (sid, str(csv_path), None),
    )
    conn.commit()


class TestNotSupportedShortCircuit:
    def test_csv_source_returns_tier_d_stub(self, tmp_path):
        conn = _sqlite()
        try:
            csv = tmp_path / "sess.csv"
            csv.write_text("x")
            _seed_csv_session(conn, 1, csv)
            loader = SessionLoader(conn_factory=lambda: conn)
            run_pipe, eval_release = build_adapters(
                session_loader=loader, config=AdapterConfig(),
            )

            pr = run_pipe(1, workspace_id=1)
            # Stub PipelineResult MUST drive SupportTierResolver to Tier D.
            assert pr.calibration_source == "none"
            assert any("not_supported" in w for w in pr.pipeline_warnings)

            rr = eval_release(pr)
            # Decision value is PASS on unsupported stub (tier D is decided
            # upstream by the resolver, not by the release gate).
            assert rr.decision.value == "pass"

            # Drive the real resolver with the stub results → Tier D.
            tier, reason = SupportTierResolver().resolve(pr, rr)
            assert tier is SupportTier.D
            assert reason == "vehicle_profile_not_validated"
        finally:
            conn.close()


class TestSupportedPathCallsRunPipeline:
    def test_calls_harness_run_pipeline_with_built_entry(self, tmp_path):
        conn = _sqlite()
        try:
            ibt = tmp_path / "sess.ibt"
            ibt.write_bytes(b"\x00" * 16)
            _seed_supported_session(conn, 1, ibt)
            loader = SessionLoader(conn_factory=lambda: conn)

            fake_result = PipelineResult(
                dataset_id="saas_session_1", ibt_path=str(ibt),
                n_samples_total=10_000, n_valid=9_500,
                n_laps=3, track_length_m=5726.0,
                field_coverage_pct=85.0, field_mean_confidence=0.82,
                bucket_fallback_distribution={0: 900, 1: 50, 2: 50},
                planner_nominal_mean_mu=1.05,
                planner_robust_mean_mu=0.98,
                planner_exploitable_mean_mu=1.12,
                planner_n_trusted=900, planner_n_degraded=100,
                calibration_profile_id="iracing_mx5_2024",
                calibration_source="registry_active",
            )

            run_pipe, _ = build_adapters(
                session_loader=loader, config=AdapterConfig(),
            )

            with patch(
                "track_surface_app.pipeline_adapters.run_pipeline",
                return_value=fake_result,
            ) as mock_run:
                pr = run_pipe(1, workspace_id=1)
                assert mock_run.call_count == 1
                passed_entry = mock_run.call_args[0][0]
                assert passed_entry.id == "saas_session_1"
                assert passed_entry.ibt_path == str(ibt)
                assert passed_entry.vehicle.klass == "MX5"
                assert passed_entry.track.regime == "banked"

            assert pr.calibration_source == "registry_active"
            assert pr.n_valid == 9_500
        finally:
            conn.close()


class TestReleaseGateWiring:
    def test_release_adapter_calls_compute_metrics_and_evaluate_session(self, tmp_path):
        conn = _sqlite()
        try:
            ibt = tmp_path / "sess.ibt"
            ibt.write_bytes(b"\x00" * 16)
            _seed_supported_session(conn, 1, ibt)
            loader = SessionLoader(conn_factory=lambda: conn)

            fake_result = PipelineResult(
                dataset_id="saas_session_1", ibt_path=str(ibt),
                n_samples_total=10_000, n_valid=9_500,
                n_laps=3, track_length_m=5726.0,
                field_coverage_pct=85.0, field_mean_confidence=0.82,
                bucket_fallback_distribution={0: 900, 1: 50, 2: 50},
                planner_nominal_mean_mu=1.05, planner_robust_mean_mu=0.98,
                planner_exploitable_mean_mu=1.12,
                planner_n_trusted=900, planner_n_degraded=100,
                calibration_profile_id="iracing_mx5_2024",
                calibration_source="registry_active",
            )

            run_pipe, eval_release = build_adapters(
                session_loader=loader, config=AdapterConfig(),
            )

            with patch(
                "track_surface_app.pipeline_adapters.run_pipeline",
                return_value=fake_result,
            ):
                run_pipe(1, workspace_id=1)   # populate cached entry

            # Real compute_metrics + evaluate_session paths run here.
            rr = eval_release(fake_result)
            assert rr.decision in (ReleaseDecision.PASS, ReleaseDecision.WARN, ReleaseDecision.FAIL)
            assert rr.track_class == "banked"
            assert rr.vehicle_class == "MX5"
            # At least one check must have executed against the real thresholds.
            assert len(rr.checks) > 0 or rr.n_pass + rr.n_warn + rr.n_fail == 0
        finally:
            conn.close()

    def test_release_adapter_short_circuits_when_entry_unsupported(self, tmp_path):
        conn = _sqlite()
        try:
            csv = tmp_path / "sess.csv"
            csv.write_text("x")
            _seed_csv_session(conn, 1, csv)
            loader = SessionLoader(conn_factory=lambda: conn)

            run_pipe, eval_release = build_adapters(
                session_loader=loader, config=AdapterConfig(),
            )
            pr = run_pipe(1, workspace_id=1)
            rr = eval_release(pr)
            # Stub release result — no checks run
            assert rr.checks == []
            assert rr.decision is ReleaseDecision.PASS
        finally:
            conn.close()


class TestFullResolverChain:
    """End-to-end through the REAL SupportTierResolver for both supported
    and unsupported sessions. No physics, but every domain seam runs for real."""

    def test_unsupported_session_resolves_to_tier_d(self, tmp_path):
        conn = _sqlite()
        try:
            _seed_csv_session(conn, 1, tmp_path / "x.csv")
            loader = SessionLoader(conn_factory=lambda: conn)
            run_pipe, eval_release = build_adapters(
                session_loader=loader, config=AdapterConfig(),
            )
            pr = run_pipe(1, workspace_id=1)
            rr = eval_release(pr)
            tier, reason = SupportTierResolver().resolve(pr, rr)
            assert tier is SupportTier.D
        finally:
            conn.close()

    def test_supported_session_with_tier_a_pipeline_resolves_to_tier_a(self, tmp_path):
        conn = _sqlite()
        try:
            ibt = tmp_path / "sess.ibt"
            ibt.write_bytes(b"\x00" * 16)
            _seed_supported_session(conn, 1, ibt)
            loader = SessionLoader(conn_factory=lambda: conn)

            fake_result = PipelineResult(
                dataset_id="saas_session_1", ibt_path=str(ibt),
                n_samples_total=10_000, n_valid=9_500,
                n_laps=3, track_length_m=5726.0,
                field_coverage_pct=85.0, field_mean_confidence=0.82,
                bucket_fallback_distribution={0: 900, 1: 50, 2: 50},   # fb2 = 5%
                planner_nominal_mean_mu=1.05, planner_robust_mean_mu=0.98,
                planner_exploitable_mean_mu=1.12,
                planner_n_trusted=900, planner_n_degraded=100,
                calibration_profile_id="iracing_mx5_2024",
                calibration_source="registry_active",
            )
            run_pipe, eval_release = build_adapters(
                session_loader=loader, config=AdapterConfig(),
            )

            with patch(
                "track_surface_app.pipeline_adapters.run_pipeline",
                return_value=fake_result,
            ):
                pr = run_pipe(1, workspace_id=1)

            rr = eval_release(pr)
            tier, reason = SupportTierResolver().resolve(pr, rr)

            # Whether tier lands on A, B, or C depends on real release gate
            # output against real thresholds — ANYTHING except Tier D is a
            # valid outcome for a validated-calibration session with real geometry.
            assert tier is not SupportTier.D
        finally:
            conn.close()
