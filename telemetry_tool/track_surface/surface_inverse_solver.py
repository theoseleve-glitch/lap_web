"""
Surface friction inverse solver — finds the road-surface scaling lambda
that explains observed tire forces given the tire model prediction.

The core equation:

    (Fx_obs, Fy_obs) ≈ TireModel(alpha, kappa, Fz, camber, state) × lambda

lambda_surface ≈ 1.0 on clean dry asphalt. Higher = grippier surface
(fresh rubber deposit), lower = slippery (dust, moisture, worn asphalt).

The inverse is NOT a simple division because the tire model is nonlinear
(load sensitivity, combined slip). We solve:

    lambda* = argmin_lambda || F_obs - lambda × F_pred ||²

which for the scalar lambda case has a closed-form least-squares solution:

    lambda* = dot(F_obs, F_pred) / dot(F_pred, F_pred)

This stays valid when the tire model is nonlinear because lambda only
scales the OUTPUT, not the internal nonlinearity. The tire handles
load sensitivity and combined slip internally; lambda captures what
the road surface contributes on top.

Excitation gating: updates only occur when the tire is sufficiently
loaded (force demand is informative). Low-excitation samples get
lambda = None + low confidence, not a fabricated estimate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final

import numpy as np

from track_surface.tire_model import TireInputs, TireOutputs, TireParams, predict_tire_forces

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665


# ── Data structures ──────────────────────────────────────────


@dataclass
class SurfaceEstimate:
    """Per-sample road-surface friction estimate."""
    lambda_surface: float | None   # road scaling (None if unobservable)
    confidence: float              # 0-1 estimation confidence
    excitation: float              # 0-1 how informative this sample was

    # Decomposed for diagnostics
    fx_obs: float = 0.0
    fy_obs: float = 0.0
    fx_pred: float = 0.0
    fy_pred: float = 0.0
    f_obs_mag: float = 0.0
    f_pred_mag: float = 0.0

    flags: dict = field(default_factory=dict)


@dataclass
class ExcitationConfig:
    """Thresholds for determining when a sample is informative enough
    to update the surface estimate."""

    # Minimum force magnitude relative to Fz (normalized demand)
    min_force_demand: float = 0.4

    # Minimum slip angle magnitude for lateral information
    min_alpha_rad: float = 0.01

    # Minimum speed for reliable kinematics
    min_speed_mps: float = 8.0

    # Minimum Fz to trust per-wheel forces
    min_fz_n: float = 800.0

    # Maximum lambda before flagging as suspect (surface can't be 3x grippier)
    max_lambda: float = 2.0
    min_lambda: float = 0.3

    # Reject samples where tire model prediction is too small
    # (prevents lambda blowup from dividing by near-zero)
    min_pred_force_n: float = 200.0


# ── Core solver ──────────────────────────────────────────────


def solve_lambda_surface(
    *,
    fx_obs: float,
    fy_obs: float,
    tire_input: TireInputs,
    tire_params: TireParams,
    config: ExcitationConfig | None = None,
) -> SurfaceEstimate:
    """Solve for the road-surface scaling lambda from one wheel at one sample.

    The tire model predicts (Fx_pred, Fy_pred) at the current slip state.
    The observed forces (Fx_obs, Fy_obs) come from per-wheel reconstruction.
    Lambda scales the prediction to match the observation:

        lambda* = dot(F_obs, F_pred) / dot(F_pred, F_pred)

    Parameters
    ----------
    fx_obs, fy_obs : observed per-wheel forces from reconstruction [N]
    tire_input : slip state, Fz, camber, speed, tire condition
    tire_params : tire model parameters
    config : excitation/gating thresholds

    Returns
    -------
    SurfaceEstimate with lambda, confidence, and diagnostics.
    """
    if config is None:
        config = ExcitationConfig()

    flags: dict[str, bool] = {}

    # ── Predict tire forces at this slip state ───────────────
    tire_out = predict_tire_forces(tire_input, tire_params)
    fx_pred = tire_out.fx
    fy_pred = tire_out.fy

    f_obs_mag = np.sqrt(fx_obs ** 2 + fy_obs ** 2)
    f_pred_mag = np.sqrt(fx_pred ** 2 + fy_pred ** 2)

    # ── Excitation checks ────────────────────────────────────
    # Each check independently gates the update. All must pass.

    excitation = 0.0
    reject_reasons = []

    # 1. Speed sufficient
    if tire_input.vx < config.min_speed_mps:
        reject_reasons.append("low_speed")
        flags["low_speed"] = True

    # 2. Normal load sufficient
    if tire_input.fz < config.min_fz_n:
        reject_reasons.append("low_fz")
        flags["low_fz"] = True

    # 3. Slip angle informative
    if abs(tire_input.alpha) < config.min_alpha_rad:
        # Low alpha is fine for longitudinal estimation but not for lateral
        # Only penalize if we're relying on lateral information
        if tire_input.kappa is None or abs(tire_input.kappa) < 0.01:
            reject_reasons.append("low_excitation")
            flags["low_excitation"] = True

    # 4. Force demand sufficient (fraction of tire capacity used)
    normalized_demand = f_obs_mag / max(tire_input.fz, 1.0)
    if normalized_demand < config.min_force_demand:
        reject_reasons.append("low_demand")
        flags["low_demand"] = True

    # 5. Tire model prediction large enough to invert
    if f_pred_mag < config.min_pred_force_n:
        reject_reasons.append("low_prediction")
        flags["low_prediction"] = True

    # Compute excitation score (0-1)
    excitation = min(1.0, normalized_demand / 0.8)
    if tire_input.kappa is not None:
        excitation = min(1.0, excitation + 0.2)  # bonus for combined-slip info

    # ── Reject if any gate fails ─────────────────────────────
    if reject_reasons:
        flags["rejected"] = True
        flags["reject_reasons"] = reject_reasons
        return SurfaceEstimate(
            lambda_surface=None,
            confidence=0.0,
            excitation=excitation,
            fx_obs=fx_obs, fy_obs=fy_obs,
            fx_pred=fx_pred, fy_pred=fy_pred,
            f_obs_mag=f_obs_mag, f_pred_mag=f_pred_mag,
            flags=flags,
        )

    # ── Solve for lambda ─────────────────────────────────────
    # lambda* = dot(F_obs, F_pred) / dot(F_pred, F_pred)
    # This is the scalar least-squares solution: minimize ||F_obs - lambda * F_pred||²
    dot_obs_pred = fx_obs * fx_pred + fy_obs * fy_pred
    dot_pred_pred = fx_pred * fx_pred + fy_pred * fy_pred

    if dot_pred_pred < 1.0:  # prediction too small
        flags["degenerate"] = True
        return SurfaceEstimate(
            lambda_surface=None, confidence=0.0, excitation=excitation,
            fx_obs=fx_obs, fy_obs=fy_obs,
            fx_pred=fx_pred, fy_pred=fy_pred,
            f_obs_mag=f_obs_mag, f_pred_mag=f_pred_mag,
            flags=flags,
        )

    lambda_raw = dot_obs_pred / dot_pred_pred

    # ── Sanity clamp ─────────────────────────────────────────
    if lambda_raw < config.min_lambda or lambda_raw > config.max_lambda:
        flags["lambda_clamped"] = True
        # Still return the clamped value but with reduced confidence
        lambda_clamped = float(np.clip(lambda_raw, config.min_lambda, config.max_lambda))
        conf_penalty = 0.5  # halve confidence when clamped
    else:
        lambda_clamped = float(lambda_raw)
        conf_penalty = 1.0
        flags["lambda_clamped"] = False

    # ── Confidence ───────────────────────────────────────────
    # Higher excitation + higher tire model quality + unclamped = higher confidence
    confidence = excitation * tire_out.quality * conf_penalty

    # Residual check: if F_obs and F_pred point in very different directions,
    # the model may be wrong (not just scaled). Reduce confidence.
    if f_obs_mag > 100 and f_pred_mag > 100:
        cos_angle = dot_obs_pred / (f_obs_mag * f_pred_mag)
        if cos_angle < 0.5:  # > 60° angular mismatch
            confidence *= 0.3
            flags["direction_mismatch"] = True

    flags["rejected"] = False
    return SurfaceEstimate(
        lambda_surface=lambda_clamped,
        confidence=float(np.clip(confidence, 0.0, 1.0)),
        excitation=float(excitation),
        fx_obs=fx_obs, fy_obs=fy_obs,
        fx_pred=fx_pred, fy_pred=fy_pred,
        f_obs_mag=f_obs_mag, f_pred_mag=f_pred_mag,
        flags=flags,
    )


# ── Multi-wheel solver ───────────────────────────────────────


def solve_lambda_multi_wheel(
    *,
    fx_obs_wheels: tuple[float, float, float, float],
    fy_obs_wheels: tuple[float, float, float, float],
    tire_inputs: tuple[TireInputs, TireInputs, TireInputs, TireInputs],
    tire_params: TireParams,
    config: ExcitationConfig | None = None,
) -> tuple[SurfaceEstimate, ...]:
    """Solve lambda_surface independently for each of the 4 wheels.

    Returns a tuple of 4 SurfaceEstimate (one per wheel: FL, FR, RL, RR).
    The per-wheel estimates can be aggregated downstream into a single
    per-sample or per-cell surface estimate.
    """
    results = []
    for w in range(4):
        est = solve_lambda_surface(
            fx_obs=fx_obs_wheels[w],
            fy_obs=fy_obs_wheels[w],
            tire_input=tire_inputs[w],
            tire_params=tire_params,
            config=config,
        )
        results.append(est)
    return tuple(results)


def aggregate_wheel_lambdas(
    estimates: tuple[SurfaceEstimate, ...],
) -> tuple[float | None, float]:
    """Aggregate 4 per-wheel lambda estimates into a single per-sample value.

    Uses confidence-weighted mean of the valid (non-None) estimates.
    Returns (lambda_aggregated, confidence_aggregated).
    """
    lambdas = []
    weights = []
    for est in estimates:
        if est.lambda_surface is not None and est.confidence > 0.01:
            lambdas.append(est.lambda_surface)
            weights.append(est.confidence)

    if not lambdas:
        return None, 0.0

    w = np.array(weights)
    l = np.array(lambdas)
    w_sum = w.sum()
    if w_sum < 1e-9:
        return None, 0.0

    lambda_agg = float(np.sum(l * w) / w_sum)
    conf_agg = float(np.mean(w))  # average confidence across contributing wheels
    return lambda_agg, conf_agg


# ── Batch solver ─────────────────────────────────────────────


def solve_lambda_batch(
    *,
    fx_obs: np.ndarray,        # (N, 4) per-wheel observed forces
    fy_obs: np.ndarray,        # (N, 4)
    alpha: np.ndarray,         # (N, 4) slip angles
    kappa: np.ndarray | None,  # (N, 4) or None
    fz: np.ndarray,            # (N, 4) normal loads
    camber: np.ndarray,        # (N, 4) camber angles
    vx: np.ndarray,            # (N,) speed
    tire_params: TireParams,
    config: ExcitationConfig | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Batch lambda estimation for N samples × 4 wheels.

    Returns
    -------
    lambda_per_sample : (N,) aggregated lambda (NaN where unobservable)
    confidence_per_sample : (N,) aggregated confidence
    """
    N = len(vx)
    lambda_out = np.full(N, np.nan)
    conf_out = np.zeros(N)

    for i in range(N):
        inputs = []
        for w in range(4):
            k = float(kappa[i, w]) if kappa is not None else None
            inputs.append(TireInputs(
                alpha=float(alpha[i, w]),
                kappa=k,
                fz=float(fz[i, w]),
                camber=float(camber[i, w]),
                vx=float(vx[i]),
            ))

        estimates = solve_lambda_multi_wheel(
            fx_obs_wheels=(float(fx_obs[i, 0]), float(fx_obs[i, 1]),
                          float(fx_obs[i, 2]), float(fx_obs[i, 3])),
            fy_obs_wheels=(float(fy_obs[i, 0]), float(fy_obs[i, 1]),
                          float(fy_obs[i, 2]), float(fy_obs[i, 3])),
            tire_inputs=tuple(inputs),
            tire_params=tire_params,
            config=config,
        )

        lam, conf = aggregate_wheel_lambdas(estimates)
        if lam is not None:
            lambda_out[i] = lam
            conf_out[i] = conf

    return lambda_out, conf_out
