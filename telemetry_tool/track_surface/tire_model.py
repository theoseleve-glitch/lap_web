"""
Quasi-steady combined-slip tire model with load sensitivity.

v1 scope:
  - Combined slip (alpha + kappa coupling)
  - Load sensitivity (peak mu decreases with Fz)
  - Camber thrust
  - Pressure/temperature/wear hooks in the interface (optional, scale output)
  - Force capacity envelope at each operating point
  - No transient dynamics (relaxation length deferred to v2)
  - No road-surface scaling embedded (lambda_surface lives in the inverse solver)

The model uses a simplified Pacejka-like formulation for pure slip, then
applies a friction-circle weighting for combined slip. This is deliberately
simpler than full MF6.1/MF-Swift — the goal for v1 is a physically sane
(Fx, Fy, capacity) prediction that the inverse solver can invert for
lambda_surface, not a tire-data-fitting exercise.

Parameters can be:
  - Defaults (reasonable GT class rubber on dry asphalt)
  - Fitted from telemetry via scipy optimization (deferred)
  - Loaded from AC tires.ini where available (only sim with readable params)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final

import numpy as np

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665


# ── Data structures ──────────────────────────────────────────


@dataclass
class TireParams:
    """Pacejka-like parameters for one tire (or one axle).

    Lateral (Fy) pure slip:  Fy = D_y × sin(C_y × arctan(B_y × alpha))
    Longitudinal (Fx) pure:  Fx = D_x × sin(C_x × arctan(B_x × kappa))

    Where D = d1 × Fz + d2 × Fz²  (load-sensitive peak force)
    So peak mu = D / Fz = d1 + d2 × Fz  (decreases with load when d2 < 0)

    Combined slip uses a friction-circle weighting.
    """
    # Lateral
    b_lat: float = 10.0     # stiffness factor
    c_lat: float = 1.3      # shape factor
    d1_lat: float = 1.4     # peak force coefficient (linear in Fz)
    d2_lat: float = -0.00005 # load sensitivity (negative → mu drops with Fz)

    # Longitudinal
    b_long: float = 12.0
    c_long: float = 1.65
    d1_long: float = 1.35
    d2_long: float = -0.00005

    # Camber
    camber_stiffness: float = 0.15  # Fy per rad of camber, normalized by Fz

    # Combined slip exponent (friction ellipse shape)
    p_combined: float = 1.6  # 2.0 = circle, < 2 = diamond-ish

    @classmethod
    def gt4_default(cls) -> TireParams:
        """Reasonable defaults for GT4-class dry tire."""
        return cls()

    @classmethod
    def formula_default(cls) -> TireParams:
        """Higher grip for formula/open-wheel."""
        return cls(d1_lat=1.8, d1_long=1.7, b_lat=12.0, b_long=14.0)


@dataclass
class TireState:
    """Dynamic tire condition (optional in v1)."""
    temp_surface_c: float | None = None
    temp_core_c: float | None = None
    pressure_kpa: float | None = None
    wear_pct: float | None = None    # remaining tread 0-100
    compound: str = "unknown"

    def grip_scale(self) -> float:
        """Multiplicative grip factor from tire condition.

        Returns a scale in [0.7, 1.05] that modulates the tire output.
        This is a PLACEHOLDER — the real model should be learned from data.
        In v1, it provides hooks so the interface doesn't change when
        a proper thermal model is added later.
        """
        scale = 1.0

        if self.temp_surface_c is not None:
            # Bell curve centered at 90°C, ±30°C half-width
            t = self.temp_surface_c
            scale *= 1.0 - 0.003 * min((t - 90.0) ** 2 / 100.0, 10.0)

        if self.wear_pct is not None and self.wear_pct < 50.0:
            scale *= 0.85 + 0.15 * (self.wear_pct / 50.0)

        if self.pressure_kpa is not None:
            p_target = 185.0
            scale *= 1.0 - 0.001 * min(abs(self.pressure_kpa - p_target), 30.0)

        return float(np.clip(scale, 0.70, 1.05))


@dataclass
class TireInputs:
    """Per-wheel inputs for one sample."""
    alpha: float            # slip angle [rad] (from wheel_kinematics)
    kappa: float | None     # slip ratio (None if unobserved)
    fz: float               # normal load [N]
    camber: float           # camber angle [rad]
    vx: float               # longitudinal speed [m/s] (for quality gating)
    state: TireState | None = None  # optional tire condition


@dataclass
class TireOutputs:
    """Predicted tire forces and capacity at this operating point."""
    fx: float               # longitudinal force [N]
    fy: float               # lateral force [N]
    mz: float | None = None # self-aligning moment [Nm] (deferred)

    fx_capacity: float = 0.0  # max |Fx| at current (alpha, Fz, state)
    fy_capacity: float = 0.0  # max |Fy| at current (kappa, Fz, state)
    combined_utilization: float | None = None  # |F_used| / |F_capacity| in 0-1

    quality: float = 0.0     # 0-1 output confidence
    flags: dict = field(default_factory=dict)


# ── Core model ───────────────────────────────────────────────


def _pure_lateral(alpha: float, fz: float, params: TireParams) -> float:
    """Pure lateral force Fy(alpha) at given Fz. Odd-symmetric in alpha."""
    D = (params.d1_lat * fz + params.d2_lat * fz * fz)
    return D * np.sin(params.c_lat * np.arctan(params.b_lat * alpha))


def _pure_longitudinal(kappa: float, fz: float, params: TireParams) -> float:
    """Pure longitudinal force Fx(kappa) at given Fz. Odd-symmetric in kappa."""
    D = (params.d1_long * fz + params.d2_long * fz * fz)
    return D * np.sin(params.c_long * np.arctan(params.b_long * kappa))


def _peak_lateral_force(fz: float, params: TireParams) -> float:
    """Maximum |Fy| achievable at this Fz (pure lateral, at peak alpha)."""
    # D = d1 × Fz + d2 × Fz² (peak of the Pacejka curve)
    return abs(params.d1_lat * fz + params.d2_lat * fz * fz)


def _peak_longitudinal_force(fz: float, params: TireParams) -> float:
    """Maximum |Fx| achievable at this Fz (pure longitudinal, at peak kappa)."""
    return abs(params.d1_long * fz + params.d2_long * fz * fz)


def predict_tire_forces(
    inputs: TireInputs,
    params: TireParams,
) -> TireOutputs:
    """Predict combined-slip tire forces for one wheel at one sample.

    Physics:
    1. Compute pure-slip forces Fy0(alpha) and Fx0(kappa)
    2. Apply friction-circle combined-slip weighting
    3. Add camber thrust
    4. Scale by tire state (if provided)
    5. Compute capacity envelope at this operating point

    When kappa is None (unobserved), treat as kappa=0 (pure cornering)
    and flag quality accordingly.
    """
    flags: dict[str, bool] = {}
    fz = max(inputs.fz, 1.0)  # prevent division by zero
    alpha = inputs.alpha
    camber = inputs.camber

    # Handle unobserved slip ratio
    if inputs.kappa is not None:
        kappa = inputs.kappa
        flags["kappa_available"] = True
    else:
        kappa = 0.0
        flags["kappa_available"] = False

    # ── Pure slip forces ─────────────────────────────────────
    fy_pure = _pure_lateral(alpha, fz, params)
    fx_pure = _pure_longitudinal(kappa, fz, params)

    # ── Combined slip (friction ellipse weighting) ───────────
    # At combined slip, the available force in each direction is reduced.
    # Using the p-norm friction ellipse:
    #   (|Fx|/Fx_max)^p + (|Fy|/Fy_max)^p <= 1
    #
    # We scale each pure-slip force to lie on the ellipse boundary:
    fy_cap_pure = _peak_lateral_force(fz, params)
    fx_cap_pure = _peak_longitudinal_force(fz, params)

    # Normalized demands
    fy_norm = abs(fy_pure) / max(fy_cap_pure, 1.0)
    fx_norm = abs(fx_pure) / max(fx_cap_pure, 1.0)

    p = params.p_combined
    demand = (fx_norm ** p + fy_norm ** p)

    if demand > 1e-9:
        # Scale factor to bring the combined force onto the ellipse
        scale = min(1.0, 1.0 / (demand ** (1.0 / p)))
    else:
        scale = 1.0

    fx_combined = fx_pure * scale
    fy_combined = fy_pure * scale

    # ── Camber thrust ────────────────────────────────────────
    # Lateral force from camber: Fy_camber = camber_stiffness × Fz × camber
    fy_camber = params.camber_stiffness * fz * camber
    fy_combined += fy_camber

    # ── Tire state scaling ───────────────────────────────────
    grip_scale = 1.0
    if inputs.state is not None:
        grip_scale = inputs.state.grip_scale()
        flags["tire_state_applied"] = True
    else:
        flags["tire_state_applied"] = False

    fx_out = fx_combined * grip_scale
    fy_out = fy_combined * grip_scale

    # ── Capacity envelope ────────────────────────────────────
    # At the current (alpha, kappa), how much Fx and Fy is available?
    # This accounts for combined slip: if kappa is consuming some capacity,
    # the available Fy is reduced.

    # Available Fy given current kappa demand:
    fx_used_frac = (abs(fx_combined) / max(fx_cap_pure, 1.0)) ** p
    fy_available_frac = max(0.0, 1.0 - fx_used_frac) ** (1.0 / p)
    fy_capacity = fy_cap_pure * fy_available_frac * grip_scale

    # Available Fx given current alpha demand:
    fy_used_frac = (abs(fy_combined) / max(fy_cap_pure, 1.0)) ** p
    fx_available_frac = max(0.0, 1.0 - fy_used_frac) ** (1.0 / p)
    fx_capacity = fx_cap_pure * fx_available_frac * grip_scale

    # Combined utilization
    f_total = np.sqrt(fx_out ** 2 + fy_out ** 2)
    f_cap_total = np.sqrt(fx_capacity ** 2 + fy_capacity ** 2) if (fx_capacity + fy_capacity) > 0 else 1.0
    combined_util = float(f_total / max(f_cap_total, 1.0))

    # ── Quality ──────────────────────────────────────────────
    quality = 0.5  # base
    if inputs.vx > 10.0:
        quality += 0.2
    if inputs.kappa is not None:
        quality += 0.2
    if inputs.state is not None:
        quality += 0.1
    quality = min(quality, 1.0)

    return TireOutputs(
        fx=float(fx_out),
        fy=float(fy_out),
        mz=None,  # deferred
        fx_capacity=float(fx_capacity),
        fy_capacity=float(fy_capacity),
        combined_utilization=float(np.clip(combined_util, 0, 1)),
        quality=float(quality),
        flags=flags,
    )


# ── Batch API ────────────────────────────────────────────────


def predict_tire_forces_batch(
    alpha: np.ndarray,
    kappa: np.ndarray | None,
    fz: np.ndarray,
    camber: np.ndarray,
    vx: np.ndarray,
    params: TireParams,
    tire_states: list[TireState | None] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized tire force prediction for N samples.

    Returns (fx, fy, fx_capacity, fy_capacity) arrays of shape (N,).
    """
    n = len(alpha)
    fx_out = np.zeros(n)
    fy_out = np.zeros(n)
    fx_cap = np.zeros(n)
    fy_cap = np.zeros(n)

    for i in range(n):
        inp = TireInputs(
            alpha=float(alpha[i]),
            kappa=float(kappa[i]) if kappa is not None else None,
            fz=float(fz[i]),
            camber=float(camber[i]),
            vx=float(vx[i]),
            state=tire_states[i] if tire_states else None,
        )
        out = predict_tire_forces(inp, params)
        fx_out[i] = out.fx
        fy_out[i] = out.fy
        fx_cap[i] = out.fx_capacity
        fy_cap[i] = out.fy_capacity

    return fx_out, fy_out, fx_cap, fy_cap


# ── Diagnostic: peak mu vs load curve ────────────────────────


def peak_mu_vs_load(
    fz_range: np.ndarray,
    params: TireParams,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute peak lateral and longitudinal mu as a function of Fz.

    Returns (mu_lat, mu_long) arrays showing load sensitivity.
    This is for diagnostics — should show mu decreasing with Fz.
    """
    mu_lat = np.array([
        _peak_lateral_force(fz, params) / max(fz, 1.0) for fz in fz_range
    ])
    mu_long = np.array([
        _peak_longitudinal_force(fz, params) / max(fz, 1.0) for fz in fz_range
    ])
    return mu_lat, mu_long
