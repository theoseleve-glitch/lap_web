"""Tests for the minimum-time QSS solver."""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from kart_envelope.config import default_config
from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.solver.min_time import SolverError, TheoreticalResult, compute_theoretical_lap
from kart_envelope.track.geometry import TrackGeometry


class TestSolver:
    def test_circular_track(self, known_envelope):
        """On a constant-curvature circle, v_max = sqrt(ay_max / kappa).

        For kappa=0.04, ay_max=8.0: v_max = sqrt(200) = 14.14 m/s.
        Lap time ≈ distance / v_max.
        """
        n = 500
        dist = np.linspace(0, 500, n)
        kappa = np.full(n, 0.04)

        geom = TrackGeometry(
            distance_m=dist,
            curvature_1pm=kappa,
            heading_rad=np.cumsum(kappa * (dist[1] - dist[0])),
            x_ref_m=np.zeros(n),
            y_ref_m=np.zeros(n),
            lap_length_m=500.0,
            track_id="circle",
        )

        result = compute_theoretical_lap(geom, known_envelope, config=default_config())
        assert result.solver_backend == "qss"
        assert isinstance(result.solver_diagnostics, dict)

        expected_v = math.sqrt(8.0 / 0.04)  # 14.14 m/s
        mean_v = float(np.mean(result.speed_profile_mps))
        assert mean_v == pytest.approx(expected_v, rel=0.05)

        expected_time = 500.0 / expected_v
        assert result.lap_time_s == pytest.approx(expected_time, rel=0.05)

    def test_straight_track(self, known_envelope):
        """On a straight (kappa=0), speed should be limited by max_speed."""
        n = 500
        dist = np.linspace(0, 500, n)
        kappa = np.zeros(n)

        geom = TrackGeometry(
            distance_m=dist,
            curvature_1pm=kappa,
            heading_rad=np.zeros(n),
            x_ref_m=dist,
            y_ref_m=np.zeros(n),
            lap_length_m=500.0,
            track_id="straight",
        )

        cfg = default_config()
        result = compute_theoretical_lap(geom, known_envelope, config=cfg)

        # Should reach close to max speed (45 m/s limited by traction)
        # Traction is 5 m/s², so from 1 m/s: v² = 1 + 2*5*d → v = sqrt(1+5000) ≈ 70
        # But capped at solver_max_speed_mps = 45
        assert float(np.max(result.speed_profile_mps)) == pytest.approx(
            cfg.solver_max_speed_mps, abs=1.0)

    def test_oval_track(self, known_envelope, oval_geometry):
        """Full oval test: reasonable lap time."""
        result = compute_theoretical_lap(oval_geometry, known_envelope, config=default_config())
        # 500 m oval with turns → expect ~30-40 s at ~12-16 m/s average
        assert 20.0 < result.lap_time_s < 60.0
        assert result.lap_time_s > 0
        assert len(result.speed_profile_mps) == len(oval_geometry.distance_m)

    def test_finite_speed(self, known_envelope, oval_geometry):
        """All speed values should be finite and positive."""
        result = compute_theoretical_lap(oval_geometry, known_envelope)
        assert np.all(np.isfinite(result.speed_profile_mps))
        assert np.all(result.speed_profile_mps > 0)

    def test_too_few_points(self, known_envelope):
        """Should raise SolverError with < 3 points."""
        geom = TrackGeometry(
            distance_m=np.array([0, 1]),
            curvature_1pm=np.array([0, 0]),
            heading_rad=np.array([0, 0]),
            x_ref_m=np.array([0, 1]),
            y_ref_m=np.array([0, 0]),
            lap_length_m=1.0,
            track_id="tiny",
        )
        with pytest.raises(SolverError):
            compute_theoretical_lap(geom, known_envelope)

    def test_to_dict(self, known_envelope, oval_geometry):
        result = compute_theoretical_lap(oval_geometry, known_envelope)
        d = result.to_dict()
        assert "lap_time_s" in d
        assert d["lap_time_s"] > 0
        assert "pct_cornering_limited" in d
        assert d.get("solver_backend") == "qss"
        assert isinstance(d.get("solver_diagnostics"), dict)

    def test_solver_backend_alias_qss(self, known_envelope, oval_geometry):
        cfg = replace(default_config(), solver_backend="envelope_qss")
        result = compute_theoretical_lap(oval_geometry, known_envelope, config=cfg)
        assert result.method == "envelope_qss"

    def test_solver_backend_fallback_from_casadi(
        self, known_envelope, oval_geometry, monkeypatch
    ):
        import kart_envelope.solver.ocp_casadi as ocp

        def _raise(*args, **kwargs):
            raise RuntimeError("forced casadi failure")

        monkeypatch.setattr(ocp, "compute_theoretical_lap_casadi", _raise)
        cfg = replace(
            default_config(),
            solver_backend="casadi_ocp",
            solver_backend_fallback_to_qss=True,
        )
        result = compute_theoretical_lap(oval_geometry, known_envelope, config=cfg)
        assert result.method == "envelope_qss_fallback"

    def test_solver_backend_no_fallback_raises(
        self, known_envelope, oval_geometry, monkeypatch
    ):
        import kart_envelope.solver.ocp_casadi as ocp

        def _raise(*args, **kwargs):
            raise RuntimeError("forced casadi failure")

        monkeypatch.setattr(ocp, "compute_theoretical_lap_casadi", _raise)
        cfg = replace(
            default_config(),
            solver_backend="casadi_ocp",
            solver_backend_fallback_to_qss=False,
        )
        with pytest.raises(SolverError):
            compute_theoretical_lap(oval_geometry, known_envelope, config=cfg)
