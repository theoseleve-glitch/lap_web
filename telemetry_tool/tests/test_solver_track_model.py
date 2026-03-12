"""Tests for track mesh generation."""
import numpy as np
import pytest

from solver.track_model import TrackMesh, build_mesh, refine_mesh


class TestBuildMesh:
    def test_uniform_mesh_node_count(self):
        distances = np.linspace(0, 1000, 2000)
        curvatures = np.zeros(2000)
        mesh = build_mesh(distances, curvatures, n_nodes=500)
        assert len(mesh.s) == 500
        assert mesh.s[0] == pytest.approx(0.0)
        assert mesh.s[-1] == pytest.approx(1000.0, rel=1e-3)

    def test_curvature_interpolated(self):
        distances = np.linspace(0, 100, 1000)
        curvatures = np.sin(distances * 0.1)
        mesh = build_mesh(distances, curvatures, n_nodes=50)
        assert len(mesh.kappa) == 50
        assert np.any(np.abs(mesh.kappa) > 0.01)

    def test_ds_positive(self):
        distances = np.linspace(0, 500, 1000)
        curvatures = np.zeros(1000)
        mesh = build_mesh(distances, curvatures, n_nodes=100)
        assert np.all(mesh.ds > 0)
        assert len(mesh.ds) == 99


class TestRefineMesh:
    def test_refine_adds_nodes_in_high_gradient(self):
        s = np.linspace(0, 500, 100)
        kappa = np.zeros(100)
        kappa[45:55] = 0.05
        mesh = build_mesh(s, kappa, n_nodes=100)
        speed = np.ones(100) * 30.0
        speed[45:55] = 15.0
        refined = refine_mesh(mesh, speed, gradient_threshold=0.5)
        assert len(refined.s) > len(mesh.s)

    def test_refine_preserves_endpoints(self):
        s = np.linspace(0, 1000, 200)
        kappa = np.zeros(200)
        mesh = build_mesh(s, kappa, n_nodes=50)
        speed = np.ones(50) * 25.0
        refined = refine_mesh(mesh, speed, gradient_threshold=0.01)
        assert refined.s[0] == pytest.approx(0.0)
        assert refined.s[-1] == pytest.approx(1000.0, rel=1e-3)
