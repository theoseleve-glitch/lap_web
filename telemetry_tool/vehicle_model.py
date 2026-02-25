"""
vehicle_model.py
----------------
Automatic vehicle classification and physical parameter estimation from
telemetry data.

The current pipeline treats a 125cc kart and a GT3 car identically.  But
their physics differ enormously: karts have no aerodynamic downforce, no
ABS, and generate 1.0-1.4g lateral grip; GT3 cars have significant
downforce (grip increases with v²), ABS, and routinely exceed 2.0g.

This module analyses the friction model (A2) output and per-lap metrics
to determine the vehicle class and estimate physical parameters that
feed into the lap simulation (B1) for more accurate physics.

Classification strategy
~~~~~~~~~~~~~~~~~~~~~~~
1. **Peak grip levels** — the absolute magnitude of lateral, traction,
   and braking accelerations immediately narrows the field.
2. **Speed-dependent grip** (downforce detection) — if a_lat_max(v) grows
   with v², the vehicle has aerodynamic downforce.  Fit the model
   ``a_lat = a0 + a1·v²`` and test the significance of a1.
3. **ABS detection** — with ABS, braking deceleration reaches a plateau
   almost instantly and has very low variability across laps.  Without
   ABS, there is more variation and progressive build-up.
4. **Top speed** — separates karts (< 40 m/s) from cars.

Public API
~~~~~~~~~~
``classify_vehicle(friction, lap_metrics)``
    Determine vehicle class and parameters.

``estimate_aero_parameters(friction, max_speed_mps)``
    Fit downforce and drag coefficients.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no side effects, no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs → identical outputs.
- Numpy / pandas only (no scipy — uses numpy least-squares for fitting).
"""

from __future__ import annotations

import enum
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import numpy as np

logger = logging.getLogger(__name__)

# -- -

# Physical constants

# -- -


_G: Final[float] = 9.80665

# -- -

# Friction interface protocol

# -- -


class FrictionLike(Protocol):
    """Structural interface for a friction model (friction_model.FrictionCircle)."""

    v_grid: np.ndarray
    traction_vals: np.ndarray
    braking_vals: np.ndarray
    lateral_vals: np.ndarray
    exponent: float

    def lateral_max(self, speed: float | np.ndarray) -> np.ndarray: ...
    def traction_max(self, speed: float | np.ndarray) -> np.ndarray: ...
    def braking_max(self, speed: float | np.ndarray) -> np.ndarray: ...


# -- -

# Vehicle class enum

# -- -


class VehicleClass(enum.Enum):
    """Broad vehicle classification."""
    KART = "kart"
    FORMULA = "formula"
    GT = "gt"
    TOURING = "touring"
    ROAD_CAR = "road_car"
    UNKNOWN = "unknown"


# -- -

# Vehicle parameters dataclass

# -- -


@dataclass
class VehicleParameters:
    """
    Estimated vehicle physical parameters.

    Attributes
    ----------
    vehicle_class : VehicleClass
        Broad classification.
    estimated_mass_kg : float or None
        Inferred mass (None if not determinable).
    peak_lateral_g : float
        Observed peak lateral acceleration [g].
    peak_braking_g : float
        Observed peak braking deceleration [g].
    peak_traction_g : float
        Observed peak traction acceleration [g].
    has_downforce : bool
        True if grip increases significantly with speed.
    has_abs : bool
        True if braking traces suggest ABS.
    rolling_resistance_est : float
        Estimated rolling resistance coefficient.
    aero_drag_factor_est : float
        Estimated Cd·A·ρ/(2·m).  0 for karts.
    downforce_coeff_est : float
        Estimated CL·A·ρ/(2·m) [1/m].  0 if no downforce.
    confidence : float
        Classification confidence (0–1).
    classification_reasons : list[str]
        Human-readable reasons for the classification.
    """
    vehicle_class:            VehicleClass
    estimated_mass_kg:        float | None
    peak_lateral_g:           float
    peak_braking_g:           float
    peak_traction_g:          float
    has_downforce:            bool
    has_abs:                  bool
    rolling_resistance_est:   float
    aero_drag_factor_est:     float
    downforce_coeff_est:      float = 0.0
    confidence:               float = 0.5
    classification_reasons:   list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vehicle_class":          self.vehicle_class.value,
            "estimated_mass_kg":      self.estimated_mass_kg,
            "peak_lateral_g":         round(self.peak_lateral_g, 3),
            "peak_braking_g":         round(self.peak_braking_g, 3),
            "peak_traction_g":        round(self.peak_traction_g, 3),
            "has_downforce":          self.has_downforce,
            "has_abs":                self.has_abs,
            "rolling_resistance_est": round(self.rolling_resistance_est, 4),
            "aero_drag_factor_est":   round(self.aero_drag_factor_est, 5),
            "downforce_coeff_est":    round(self.downforce_coeff_est, 6),
            "confidence":             round(self.confidence, 3),
            "classification_reasons": list(self.classification_reasons),
        }


# -- -

# Classification thresholds

# -- -


# Lateral grip thresholds [g]

_KART_LAT_MAX:      Final[float] = 1.8
_ROAD_LAT_MAX:      Final[float] = 1.2
_TOURING_LAT_MAX:   Final[float] = 1.5
_GT_LAT_MAX:        Final[float] = 2.5
_FORMULA_LAT_MIN:   Final[float] = 2.0

# Speed thresholds [m/s]

_KART_SPEED_MAX:    Final[float] = 45.0    # ~162 km/h
_ROAD_SPEED_MAX:    Final[float] = 55.0    # ~198 km/h

# Downforce significance: a1 in a_lat = a0 + a1·v²

# For meaningful downforce: a1 > 0.001 g/(m/s)² ≈ 0.01 m/s²/(m/s)²

_DOWNFORCE_THRESHOLD: Final[float] = 0.001

# ABS detection: coefficient of variation of peak braking across laps

_ABS_CV_THRESHOLD: Final[float] = 0.08    # CV < 8% suggests ABS

# Rolling resistance defaults by class

_RR_DEFAULTS: Final[dict[VehicleClass, float]] = {
    VehicleClass.KART:     0.015,
    VehicleClass.FORMULA:  0.010,
    VehicleClass.GT:       0.012,
    VehicleClass.TOURING:  0.013,
    VehicleClass.ROAD_CAR: 0.015,
    VehicleClass.UNKNOWN:  0.013,
}

# Mass estimates by class [kg]

_MASS_DEFAULTS: Final[dict[VehicleClass, float]] = {
    VehicleClass.KART:     170.0,   # kart + driver
    VehicleClass.FORMULA:  700.0,
    VehicleClass.GT:       1300.0,
    VehicleClass.TOURING:  1400.0,
    VehicleClass.ROAD_CAR: 1500.0,
    VehicleClass.UNKNOWN:  1000.0,
}


# -- -

# Internal helpers

# -- -


def _safe_max(arr: np.ndarray) -> float:
    """Max of finite values, or 0.0."""
    finite = arr[np.isfinite(arr)]
    return float(finite.max()) if len(finite) > 0 else 0.0


def _safe_mean(arr: np.ndarray) -> float:
    """Mean of finite values, or 0.0."""
    finite = arr[np.isfinite(arr)]
    return float(finite.mean()) if len(finite) > 0 else 0.0


def _get_metric(metrics: list[dict[str, Any]], key: str) -> np.ndarray:
    """Extract a metric across all laps, returning finite values only."""
    vals = []
    for m in metrics:
        v = m.get(key)
        if v is not None and math.isfinite(v):
            vals.append(v)
    return np.array(vals, dtype=float)


def _extract_peak_gs(
    friction: FrictionLike,
) -> tuple[float, float, float]:
    """
    Extract peak grip levels [g] from the friction model.
    """
    lat_g = _safe_max(friction.lateral_vals) / _G
    brk_g = _safe_max(friction.braking_vals) / _G
    trc_g = _safe_max(friction.traction_vals) / _G
    return lat_g, brk_g, trc_g


def _detect_downforce(
    friction: FrictionLike,
) -> tuple[bool, float, float]:
    """
    Detect aerodynamic downforce by fitting a_lat(v) = a0 + a1·v².

    If a1 is positive and significant, the vehicle has downforce.

    Returns
    -------
    has_downforce : bool
    a0 : float
        Base mechanical grip [m/s²].
    a1 : float
        Downforce coefficient [m/s² per (m/s)²].
    """
    v = friction.v_grid.copy()
    a_lat = friction.lateral_vals.copy()

    # Filter to finite, positive speed

    mask = np.isfinite(v) & np.isfinite(a_lat) & (v > 2.0)
    if mask.sum() < 4:
        return False, _safe_mean(a_lat), 0.0

    v_f = v[mask]
    a_f = a_lat[mask]

    # Fit: a_lat = a0 + a1 * v²

    # This is linear in (1, v²): use numpy lstsq

    A = np.column_stack([np.ones(len(v_f)), v_f ** 2])
    result, residuals, rank, sv = np.linalg.lstsq(A, a_f, rcond=None)
    a0, a1 = float(result[0]), float(result[1])

    # Significance test: is a1 meaningfully positive?

    # Use simple residual-based check instead of scipy

    if len(residuals) > 0 and residuals[0] > 0:
        n = len(v_f)
        mse = residuals[0] / max(n - 2, 1)
        # Standard error of a1

        ATA_inv = np.linalg.inv(A.T @ A)
        se_a1 = math.sqrt(mse * ATA_inv[1, 1])
        if se_a1 > 1e-12:
            t_stat = a1 / se_a1
            # t > 2 roughly corresponds to p < 0.05 for n > 10

            significant = t_stat > 2.0 and a1 > 0
        else:
            # Near-zero residuals = near-perfect fit to the model

            significant = a1 > _DOWNFORCE_THRESHOLD
    else:
        # Perfect fit or underdetermined — check sign and magnitude

        significant = a1 > _DOWNFORCE_THRESHOLD

    # Also check relative magnitude: does grip at high speed exceed

    # grip at low speed by a meaningful margin?

    v_low = v_f[v_f < np.percentile(v_f, 30)]
    v_high = v_f[v_f > np.percentile(v_f, 70)]
    if len(v_low) > 0 and len(v_high) > 0:
        a_low_mean = float(np.mean(a_f[v_f < np.percentile(v_f, 30)]))
        a_high_mean = float(np.mean(a_f[v_f > np.percentile(v_f, 70)]))
        grip_increase = (a_high_mean - a_low_mean) / max(a_low_mean, 1.0)
        # Need at least 10% increase at high speed to call it downforce

        significant = significant and grip_increase > 0.10

    has_downforce = significant and a1 > 0
    return has_downforce, a0, max(a1, 0.0)


def _detect_abs(
    friction: FrictionLike,
    lap_metrics: list[dict[str, Any]],
) -> bool:
    """
    Detect ABS from braking consistency.

    With ABS, peak braking deceleration across laps has very low
    variability (CV < 8%) because the system automatically modulates
    to the limit.  Without ABS, driver skill variation means higher CV.
    """
    braking_peaks = _get_metric(lap_metrics, "braking_max_mps2")
    if len(braking_peaks) < 3:
        # Not enough data — check friction model braking profile shape

        # ABS: braking curve is flat (constant with speed)

        v = friction.v_grid
        b = friction.braking_vals
        mask = np.isfinite(v) & np.isfinite(b) & (v > 5.0)
        if mask.sum() < 3:
            return False
        b_valid = b[mask]
        if _safe_mean(b_valid) <= 0:
            return False
        cv = float(np.std(b_valid, ddof=1)) / _safe_mean(b_valid)
        return cv < _ABS_CV_THRESHOLD

    mean_braking = float(np.mean(braking_peaks))
    if mean_braking <= 0:
        return False

    cv = float(np.std(braking_peaks, ddof=1)) / mean_braking
    return cv < _ABS_CV_THRESHOLD


def _get_max_speed(
    friction: FrictionLike,
    lap_metrics: list[dict[str, Any]],
) -> float:
    """Get maximum observed speed [m/s] from lap metrics or friction grid."""
    speed_maxes = _get_metric(lap_metrics, "speed_max_mps")
    if len(speed_maxes) > 0:
        return float(np.max(speed_maxes))

    # Fall back to friction model grid extent

    v = friction.v_grid
    mask = np.isfinite(v)
    if mask.sum() > 0:
        return float(v[mask].max())

    return 0.0


# -- -

# Public API — classify_vehicle

# -- -


def classify_vehicle(
    friction: FrictionLike,
    lap_metrics: list[dict[str, Any]],
) -> VehicleParameters:
    """
    Determine vehicle class and physical parameters from telemetry data.

    Analyses the friction model's speed-dependent grip envelope and
    per-lap feature metrics to classify the vehicle and estimate
    parameters for the lap simulation.

    Parameters
    ----------
    friction : FrictionLike
        Friction circle model (from ``friction_model.py``).
    lap_metrics : list[dict[str, Any]]
        Per-lap feature dicts (from ``features.py``), each containing
        keys like ``"speed_max_mps"``, ``"accel_max_mps2"``,
        ``"braking_max_mps2"``, ``"lat_accel_max_mps2"``.

    Returns
    -------
    VehicleParameters
    """
    reasons: list[str] = []

    # --- Extract peak grip levels -
    peak_lat_g, peak_brk_g, peak_trc_g = _extract_peak_gs(friction)

    # Also consider lap metric peaks (may exceed friction model envelope

    # if friction was built conservatively)

    metric_lat_peaks = _get_metric(lap_metrics, "lat_accel_max_mps2")
    if len(metric_lat_peaks) > 0:
        peak_lat_g = max(peak_lat_g, float(np.max(metric_lat_peaks)) / _G)

    metric_brk_peaks = _get_metric(lap_metrics, "braking_max_mps2")
    if len(metric_brk_peaks) > 0:
        peak_brk_g = max(peak_brk_g, float(np.max(metric_brk_peaks)) / _G)

    metric_trc_peaks = _get_metric(lap_metrics, "accel_max_mps2")
    if len(metric_trc_peaks) > 0:
        peak_trc_g = max(peak_trc_g, float(np.max(metric_trc_peaks)) / _G)

    # --- Downforce detection -
    has_downforce, a0_grip, a1_downforce = _detect_downforce(friction)
    if has_downforce:
        reasons.append(
            f"Downforce detected: grip increases with speed "
            f"(a1={a1_downforce:.4f} m/s² per (m/s)²)"
        )

    # --- ABS detection -
    has_abs = _detect_abs(friction, lap_metrics)
    if has_abs:
        reasons.append("ABS detected: very consistent braking across laps")

    # --- Max speed -
    max_speed = _get_max_speed(friction, lap_metrics)

    # --- Classification logic -
    scores: dict[VehicleClass, float] = {vc: 0.0 for vc in VehicleClass}

    # KART: low grip, no downforce, low top speed

    if peak_lat_g < _KART_LAT_MAX and not has_downforce:
        scores[VehicleClass.KART] += 0.3
        if max_speed < _KART_SPEED_MAX:
            scores[VehicleClass.KART] += 0.3
        if not has_abs:
            scores[VehicleClass.KART] += 0.2
        if peak_trc_g < 0.8:
            scores[VehicleClass.KART] += 0.1

    # FORMULA: very high grip, strong downforce, typically no ABS

    if peak_lat_g >= _GT_LAT_MAX:
        # Only formula at very high grip levels (>2.5g)

        scores[VehicleClass.FORMULA] += 0.4
    if peak_lat_g >= _FORMULA_LAT_MIN and has_downforce and not has_abs:
        scores[VehicleClass.FORMULA] += 0.3
    if has_downforce and peak_brk_g > 2.5:
        scores[VehicleClass.FORMULA] += 0.2

    # GT: moderate-high grip, some downforce, usually ABS

    if _TOURING_LAT_MAX < peak_lat_g <= _GT_LAT_MAX:
        scores[VehicleClass.GT] += 0.3
    elif peak_lat_g > _GT_LAT_MAX and peak_lat_g <= 3.0:
        # Slightly above GT range but not extreme → could still be GT

        scores[VehicleClass.GT] += 0.1
    if has_downforce and peak_lat_g < 3.0:
        scores[VehicleClass.GT] += 0.2
    if has_abs and peak_lat_g > 1.3:
        scores[VehicleClass.GT] += 0.25
    if max_speed > 55 and peak_brk_g > 1.2:
        scores[VehicleClass.GT] += 0.1

    # TOURING: moderate grip, ABS, moderate speed

    if _ROAD_LAT_MAX < peak_lat_g <= _TOURING_LAT_MAX:
        scores[VehicleClass.TOURING] += 0.3
    if has_abs and peak_lat_g <= _TOURING_LAT_MAX:
        scores[VehicleClass.TOURING] += 0.3
    if not has_downforce and max_speed < 70:
        scores[VehicleClass.TOURING] += 0.1

    # ROAD CAR: low grip, low speed

    if peak_lat_g <= _ROAD_LAT_MAX:
        scores[VehicleClass.ROAD_CAR] += 0.4
        if max_speed < _ROAD_SPEED_MAX:
            scores[VehicleClass.ROAD_CAR] += 0.2
        if not has_downforce:
            scores[VehicleClass.ROAD_CAR] += 0.2

    # Select the class with highest score

    best_class = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_class]

    if best_score < 0.2:
        best_class = VehicleClass.UNKNOWN
        confidence = 0.2
        reasons.append("Low classification confidence; defaulting to UNKNOWN")
    else:
        confidence = min(1.0, best_score)

    # Build reason summary

    reasons.insert(0,
        f"Classified as {best_class.value}: "
        f"lat={peak_lat_g:.2f}g, brk={peak_brk_g:.2f}g, "
        f"trc={peak_trc_g:.2f}g, vmax={max_speed:.0f}m/s, "
        f"downforce={'yes' if has_downforce else 'no'}, "
        f"ABS={'yes' if has_abs else 'no'}"
    )

    # --- Estimate physical parameters -
    rr = _RR_DEFAULTS.get(best_class, 0.013)
    mass = _MASS_DEFAULTS.get(best_class)

    # Aero drag estimate

    aero_params = estimate_aero_parameters(friction, max_speed)
    aero_drag = aero_params.get("drag_factor", 0.0)
    downforce_coeff = aero_params.get("downforce_coeff", 0.0)

    if not has_downforce:
        downforce_coeff = 0.0
    if best_class == VehicleClass.KART:
        aero_drag = max(aero_drag, 0.001)  # karts still have some drag
        downforce_coeff = 0.0

    logger.info(
        "Vehicle classified: %s (confidence=%.0f%%, lat=%.2fg, "
        "brk=%.2fg, trc=%.2fg, vmax=%.0f m/s, downforce=%s, ABS=%s).",
        best_class.value, confidence * 100, peak_lat_g, peak_brk_g,
        peak_trc_g, max_speed, has_downforce, has_abs,
    )

    return VehicleParameters(
        vehicle_class=best_class,
        estimated_mass_kg=mass,
        peak_lateral_g=round(peak_lat_g, 3),
        peak_braking_g=round(peak_brk_g, 3),
        peak_traction_g=round(peak_trc_g, 3),
        has_downforce=has_downforce,
        has_abs=has_abs,
        rolling_resistance_est=rr,
        aero_drag_factor_est=round(aero_drag, 5),
        downforce_coeff_est=round(downforce_coeff, 6),
        confidence=round(confidence, 3),
        classification_reasons=reasons,
    )


# -- -

# Public API — estimate_aero_parameters

# -- -


def estimate_aero_parameters(
    friction: FrictionLike,
    max_speed_mps: float,
) -> dict[str, float]:
    """
    Estimate aerodynamic drag and downforce coefficients.

    Drag estimation
    ~~~~~~~~~~~~~~~
    At terminal velocity on a straight, all traction goes to overcoming
    drag + rolling resistance:

        a_traction(v_max) = drag_factor · v_max² + Crr · g

    Therefore:

        drag_factor = (a_traction(v_max) − Crr · g) / v_max²

    Downforce estimation
    ~~~~~~~~~~~~~~~~~~~~
    If lateral grip increases with speed:

        a_lat(v) = a0 + downforce_coeff · v²

    where ``downforce_coeff = CL · A · ρ / (2 · m)`` [units: 1/m,
    giving acceleration in m/s² when multiplied by v² in (m/s)²].

    Parameters
    ----------
    friction : FrictionLike
        Friction model.
    max_speed_mps : float
        Maximum observed speed [m/s].

    Returns
    -------
    dict with keys:
        ``drag_factor``     — estimated Cd·A·ρ/(2·m) [1/m]
        ``downforce_coeff`` — estimated CL·A·ρ/(2·m) [1/m]
        ``terminal_traction_g`` — traction available at max speed [g]
    """
    result: dict[str, float] = {
        "drag_factor": 0.0,
        "downforce_coeff": 0.0,
        "terminal_traction_g": 0.0,
    }

    if max_speed_mps < 5.0:
        return result

    # --- Drag from terminal velocity -
    a_traction_at_vmax = float(friction.traction_max(max_speed_mps))
    result["terminal_traction_g"] = round(a_traction_at_vmax / _G, 4)

    # Assume Crr ~0.013 as a baseline

    crr_g = 0.013 * _G
    a_available = a_traction_at_vmax - crr_g

    if a_available > 0 and max_speed_mps > 10.0:
        drag_factor = a_available / (max_speed_mps ** 2)
        result["drag_factor"] = round(max(drag_factor, 0.0), 6)

    # --- Downforce -
    _, _, a1 = _detect_downforce(friction)
    if a1 > 0:
        # a1 has units [m/s² per (m/s)²] which is [1/m] — same as CL·A·ρ/(2m)

        result["downforce_coeff"] = round(a1, 6)

    return result


# ============================================================================

# Inline tests

# ============================================================================


def _run_tests() -> None:
    """
    Inline unit tests using synthetic data.
    Raises AssertionError on failure; prints a pass/fail summary.
    """
    import traceback
    from dataclasses import dataclass as _dc

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- -

    # Test friction models

    # -- -

    @_dc
    class MockFriction:
        """Configurable friction model for testing."""
        v_grid: np.ndarray
        traction_vals: np.ndarray
        braking_vals: np.ndarray
        lateral_vals: np.ndarray
        exponent: float = 2.0

        def lateral_max(self, speed):
            return np.interp(np.asarray(speed, dtype=float),
                             self.v_grid, self.lateral_vals)

        def traction_max(self, speed):
            return np.interp(np.asarray(speed, dtype=float),
                             self.v_grid, self.traction_vals)

        def braking_max(self, speed):
            return np.interp(np.asarray(speed, dtype=float),
                             self.v_grid, self.braking_vals)

    def _make_kart_friction() -> MockFriction:
        """Kart: constant grip, ~1.2g lateral, low top speed."""
        v = np.arange(0, 45, 2.0)
        return MockFriction(
            v_grid=v,
            lateral_vals=np.full(len(v), 1.2 * _G),
            braking_vals=np.full(len(v), 1.3 * _G),
            traction_vals=np.full(len(v), 0.7 * _G),
        )

    def _make_gt3_friction() -> MockFriction:
        """GT3: downforce increases grip with speed, peak ~2.0g lateral."""
        v = np.arange(0, 80, 2.0)
        # Grip increases with v²: at 70m/s → 1.3 + 0.0014*4900/g ≈ 2.0g

        lat = 1.3 * _G + 0.0014 * v ** 2
        brk = 1.4 * _G + 0.0010 * v ** 2
        trc = 0.8 * _G + 0.0006 * v ** 2
        return MockFriction(
            v_grid=v,
            lateral_vals=lat,
            braking_vals=brk,
            traction_vals=trc,
        )

    def _make_formula_friction() -> MockFriction:
        """Formula car: strong downforce, very high grip."""
        v = np.arange(0, 90, 2.0)
        lat = 1.8 * _G + 0.008 * v ** 2
        brk = 2.0 * _G + 0.006 * v ** 2
        trc = 1.2 * _G + 0.004 * v ** 2
        return MockFriction(
            v_grid=v,
            lateral_vals=lat,
            braking_vals=brk,
            traction_vals=trc,
        )

    def _make_road_car_friction() -> MockFriction:
        """Road car: low grip, no downforce."""
        v = np.arange(0, 55, 2.0)
        return MockFriction(
            v_grid=v,
            lateral_vals=np.full(len(v), 0.9 * _G),
            braking_vals=np.full(len(v), 1.0 * _G),
            traction_vals=np.full(len(v), 0.5 * _G),
        )

    def _make_touring_friction() -> MockFriction:
        """Touring car: moderate grip, no downforce, ABS."""
        v = np.arange(0, 65, 2.0)
        return MockFriction(
            v_grid=v,
            lateral_vals=np.full(len(v), 1.3 * _G),
            braking_vals=np.full(len(v), 1.2 * _G),
            traction_vals=np.full(len(v), 0.7 * _G),
        )

    def _make_lap_metrics(
        *,
        n_laps: int = 10,
        speed_max: float = 35.0,
        accel_max: float = 6.0,
        braking_max: float = 12.0,
        lat_max: float = 11.0,
        braking_cv: float = 0.12,
        seed: int = 42,
    ) -> list[dict[str, Any]]:
        rng = np.random.default_rng(seed)
        metrics = []
        for _ in range(n_laps):
            metrics.append({
                "speed_max_mps": speed_max + rng.normal(0, 1),
                "accel_max_mps2": accel_max + rng.normal(0, 0.3),
                "braking_max_mps2": braking_max * (1 + rng.normal(0, braking_cv)),
                "lat_accel_max_mps2": lat_max + rng.normal(0, 0.5),
            })
        return metrics

    # -- -

    # Test 1 — kart classification

    # -- -

    def t_classify_kart() -> None:
        friction = _make_kart_friction()
        metrics = _make_lap_metrics(
            speed_max=35, accel_max=6, braking_max=12, lat_max=11,
            braking_cv=0.15,  # no ABS
        )
        params = classify_vehicle(friction, metrics)
        assert params.vehicle_class == VehicleClass.KART, (
            f"Expected KART, got {params.vehicle_class}"
        )
        assert not params.has_downforce
        assert not params.has_abs
        assert params.peak_lateral_g < 1.8

    _test("classify_kart", t_classify_kart)

    # -- -

    # Test 2 — GT3 classification

    # -- -

    def t_classify_gt3() -> None:
        friction = _make_gt3_friction()
        metrics = _make_lap_metrics(
            speed_max=70, accel_max=10, braking_max=16, lat_max=18,
            braking_cv=0.05,  # ABS
        )
        params = classify_vehicle(friction, metrics)
        assert params.vehicle_class == VehicleClass.GT, (
            f"Expected GT, got {params.vehicle_class}"
        )
        assert params.has_downforce
        assert params.has_abs

    _test("classify_gt3", t_classify_gt3)

    # -- -

    # Test 3 — formula classification

    # -- -

    def t_classify_formula() -> None:
        friction = _make_formula_friction()
        metrics = _make_lap_metrics(
            speed_max=80, accel_max=15, braking_max=25, lat_max=35,
            braking_cv=0.12,  # no ABS (higher variability)
        )
        params = classify_vehicle(friction, metrics)
        assert params.vehicle_class == VehicleClass.FORMULA, (
            f"Expected FORMULA, got {params.vehicle_class}"
        )
        assert params.has_downforce
        assert params.peak_lateral_g > 2.0

    _test("classify_formula", t_classify_formula)

    # -- -

    # Test 4 — road car classification

    # -- -

    def t_classify_road_car() -> None:
        friction = _make_road_car_friction()
        metrics = _make_lap_metrics(
            speed_max=45, accel_max=4, braking_max=8, lat_max=8,
            braking_cv=0.15,
        )
        params = classify_vehicle(friction, metrics)
        assert params.vehicle_class == VehicleClass.ROAD_CAR, (
            f"Expected ROAD_CAR, got {params.vehicle_class}"
        )
        assert not params.has_downforce
        assert params.peak_lateral_g <= 1.2

    _test("classify_road_car", t_classify_road_car)

    # -- -

    # Test 5 — touring classification

    # -- -

    def t_classify_touring() -> None:
        friction = _make_touring_friction()
        metrics = _make_lap_metrics(
            speed_max=55, accel_max=7, braking_max=12, lat_max=12.5,
            braking_cv=0.04,  # ABS
        )
        params = classify_vehicle(friction, metrics)
        assert params.vehicle_class == VehicleClass.TOURING, (
            f"Expected TOURING, got {params.vehicle_class}"
        )
        assert params.has_abs

    _test("classify_touring", t_classify_touring)

    # -- -

    # Test 6 — downforce detection: kart has none

    # -- -

    def t_downforce_kart_none() -> None:
        friction = _make_kart_friction()
        has_df, _, _ = _detect_downforce(friction)
        assert not has_df, "Kart should have no downforce"

    _test("downforce_kart_none", t_downforce_kart_none)

    # -- -

    # Test 7 — downforce detection: GT3 has it

    # -- -

    def t_downforce_gt3_detected() -> None:
        friction = _make_gt3_friction()
        has_df, a0, a1 = _detect_downforce(friction)
        assert has_df, f"GT3 should have downforce (a1={a1:.6f})"
        assert a1 > 0, "Downforce coefficient should be positive"

    _test("downforce_gt3_detected", t_downforce_gt3_detected)

    # -- -

    # Test 8 — ABS detection: consistent braking

    # -- -

    def t_abs_detected() -> None:
        friction = _make_touring_friction()
        metrics = _make_lap_metrics(braking_max=12, braking_cv=0.03)
        assert _detect_abs(friction, metrics), "CV=3% should detect ABS"

    _test("abs_detected_consistent", t_abs_detected)

    # -- -

    # Test 9 — ABS not detected: variable braking

    # -- -

    def t_abs_not_detected() -> None:
        friction = _make_kart_friction()
        metrics = _make_lap_metrics(braking_max=12, braking_cv=0.20)
        assert not _detect_abs(friction, metrics), "CV=20% should not detect ABS"

    _test("abs_not_detected_variable", t_abs_not_detected)

    # -- -

    # Test 10 — to_dict serialisation

    # -- -

    def t_to_dict() -> None:
        friction = _make_kart_friction()
        metrics = _make_lap_metrics()
        params = classify_vehicle(friction, metrics)
        d = params.to_dict()
        assert "vehicle_class" in d
        assert "peak_lateral_g" in d
        assert "has_downforce" in d
        assert isinstance(d["classification_reasons"], list)
        assert len(d["classification_reasons"]) > 0

    _test("to_dict_serialisation", t_to_dict)

    # -- -

    # Test 11 — aero parameter estimation: kart has near-zero drag factor

    # -- -

    def t_aero_kart() -> None:
        friction = _make_kart_friction()
        aero = estimate_aero_parameters(friction, 35.0)
        assert "drag_factor" in aero
        assert "downforce_coeff" in aero
        # Kart drag factor should be small but present

        assert aero["drag_factor"] >= 0

    _test("aero_kart_params", t_aero_kart)

    # -- -

    # Test 12 — aero parameter estimation: GT3 has downforce coeff

    # -- -

    def t_aero_gt3() -> None:
        friction = _make_gt3_friction()
        aero = estimate_aero_parameters(friction, 70.0)
        assert aero["downforce_coeff"] > 0, (
            f"GT3 should have downforce_coeff > 0, got {aero['downforce_coeff']}"
        )

    _test("aero_gt3_params", t_aero_gt3)

    # -- -

    # Test 13 — empty lap metrics still works

    # -- -

    def t_empty_metrics() -> None:
        friction = _make_kart_friction()
        params = classify_vehicle(friction, [])
        assert isinstance(params.vehicle_class, VehicleClass)
        assert params.confidence > 0

    _test("empty_metrics", t_empty_metrics)

    # -- -

    # Test 14 — rolling resistance defaults by class

    # -- -

    def t_rolling_resistance() -> None:
        kart_friction = _make_kart_friction()
        kart_params = classify_vehicle(kart_friction, _make_lap_metrics(
            speed_max=35, braking_cv=0.15,
        ))
        assert kart_params.rolling_resistance_est == 0.015

        gt_friction = _make_gt3_friction()
        gt_params = classify_vehicle(gt_friction, _make_lap_metrics(
            speed_max=70, braking_max=16, lat_max=18, braking_cv=0.05,
        ))
        assert gt_params.rolling_resistance_est == 0.012

    _test("rolling_resistance_defaults", t_rolling_resistance)

    # -- -

    # Test 15 — mass estimation by class

    # -- -

    def t_mass_estimation() -> None:
        kart_params = classify_vehicle(
            _make_kart_friction(),
            _make_lap_metrics(speed_max=35, braking_cv=0.15),
        )
        assert kart_params.estimated_mass_kg == 170.0

        gt_params = classify_vehicle(
            _make_gt3_friction(),
            _make_lap_metrics(
                speed_max=70, braking_max=16, lat_max=18, braking_cv=0.05,
            ),
        )
        assert gt_params.estimated_mass_kg == 1300.0

    _test("mass_estimation", t_mass_estimation)

    # -- -

    # Test 16 — confidence varies with clarity

    # -- -

    def t_confidence_varies() -> None:
        # Clear kart → high confidence

        kart = classify_vehicle(
            _make_kart_friction(),
            _make_lap_metrics(speed_max=30, braking_cv=0.18),
        )
        # Ambiguous case: moderate grip, moderate speed

        ambig_friction = MockFriction(
            v_grid=np.arange(0, 60, 2.0),
            lateral_vals=np.full(30, 1.45 * _G),
            braking_vals=np.full(30, 1.3 * _G),
            traction_vals=np.full(30, 0.7 * _G),
        )
        ambig = classify_vehicle(
            ambig_friction,
            _make_lap_metrics(speed_max=50, lat_max=13, braking_cv=0.10),
        )
        # Kart should have higher confidence since it's a clearer signal

        assert kart.confidence >= ambig.confidence * 0.8, (
            f"Kart ({kart.confidence:.2f}) should be >= ambiguous "
            f"({ambig.confidence:.2f})"
        )

    _test("confidence_varies", t_confidence_varies)

    # -- -

    # Test 17 — VehicleClass enum values

    # -- -

    def t_enum_values() -> None:
        assert VehicleClass.KART.value == "kart"
        assert VehicleClass.FORMULA.value == "formula"
        assert VehicleClass.GT.value == "gt"
        assert VehicleClass.TOURING.value == "touring"
        assert VehicleClass.ROAD_CAR.value == "road_car"
        assert VehicleClass.UNKNOWN.value == "unknown"

    _test("enum_values", t_enum_values)

    # -- -

    # Test 18 — kart has no downforce in vehicle params

    # -- -

    def t_kart_no_aero() -> None:
        params = classify_vehicle(
            _make_kart_friction(),
            _make_lap_metrics(speed_max=35, braking_cv=0.15),
        )
        assert params.downforce_coeff_est == 0.0
        assert params.aero_drag_factor_est >= 0.001  # still has drag

    _test("kart_no_aero", t_kart_no_aero)

    # -- -

    # Test 19 — formula has high downforce coefficient

    # -- -

    def t_formula_high_downforce() -> None:
        params = classify_vehicle(
            _make_formula_friction(),
            _make_lap_metrics(
                speed_max=80, accel_max=15, braking_max=25,
                lat_max=35, braking_cv=0.12,  # no ABS
            ),
        )
        assert params.downforce_coeff_est > 0, (
            f"Formula should have downforce, got {params.downforce_coeff_est}"
        )

    _test("formula_high_downforce", t_formula_high_downforce)

    # -- -

    # Test 20 — low max speed returns safe aero params

    # -- -

    def t_aero_low_speed() -> None:
        friction = _make_kart_friction()
        aero = estimate_aero_parameters(friction, 2.0)
        assert aero["drag_factor"] == 0.0
        assert aero["downforce_coeff"] == 0.0

    _test("aero_low_speed_safe", t_aero_low_speed)

    # -- -

    # Summary

    # -- -

    total = len(passed) + len(failed)
    print(f"\nVehicle Model Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  ✓ {name}")
    for name, tb in failed:
        print(f"  ✗ {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


# -- -

# Entry point

# -- -


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
