"""2D grip-aware CasADi minimum-time OCP.

Same spatial (arc-length) formulation as :mod:`ocp`, but the friction
limit is a true 2D field mu(s, n) evaluated AT THE CHOSEN LINE inside
the NLP via a ``casadi.interpolant`` — so the optimizer routes around
lateral low-grip zones (wet rubber line, puddles) instead of only
slowing down for them.

Layering: this module imports nothing from ``track_surface``.  Callers
build a :class:`MuField` (see ``track_surface/mu_field.py``) and pass it
in.  ``ocp.py`` is intentionally untouched.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from telemetry_tool.lap_oracle.config import (
    OCPSolution,
    TrackModel,
    VehicleParams,
    WeatherConditions,
)
from telemetry_tool.lap_oracle.physics.bicycle_model import corner_speed
from telemetry_tool.lap_oracle.solver.ocp import HAS_CASADI, _build_solution
from telemetry_tool.lap_oracle.track.model import resample_track

logger = logging.getLogger(__name__)

if HAS_CASADI:
    import casadi as ca

G: float = 9.80665
RHO_AIR: float = 1.225


@dataclass(frozen=True)
class MuField:
    """Solver-ready 2D friction field on an (s, n) grid.

    Plain numpy value object so lap_oracle stays decoupled from
    track_surface.  ``mu_grid[i_s, i_n]`` with ``s_bins`` (M,) strictly
    increasing arclength centres and ``n_bins`` (K,) strictly increasing
    lateral-offset centres (+ = track-left, matching FrenetFrame).
    """

    s_bins: np.ndarray
    n_bins: np.ndarray
    mu_grid: np.ndarray

    def __post_init__(self) -> None:
        if self.mu_grid.shape != (len(self.s_bins), len(self.n_bins)):
            raise ValueError(
                f"mu_grid shape {self.mu_grid.shape} != "
                f"({len(self.s_bins)}, {len(self.n_bins)})"
            )


def _make_mu_interpolant(field: MuField):
    """Build the differentiable 2D lookup mu(s, n) for use inside the NLP.

    CasADi expects ``values`` flattened with the FIRST grid dimension
    varying FASTEST — Fortran order for our (M, K) grid.  Locked by
    ``test_interpolant_matches_gripsurface_bilinear``.
    """
    return ca.interpolant(
        "mu_sn",
        "linear",
        [field.s_bins.tolist(), field.n_bins.tolist()],
        field.mu_grid.flatten(order="F").tolist(),
    )
