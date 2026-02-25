"""
wet_physics.py
--------------
Wet-condition awareness for the physics-based theoretical lap.

Bridges condition detection (``session_context``, ``condition_tracking``)
with the physics engine (``friction_model``, ``lap_simulation``) so that
theoretical laps automatically adjust to track surface conditions.

Architecture
~~~~~~~~~~~~
1.  **Observed-grip path** — if enough laps are recorded in a single
    condition, the friction model built from those laps already reflects
    the grip level.  No adjustment needed.
2.  **Phase-aware path** — if conditions change mid-session the module
    splits laps by phase, builds per-phase friction models, and runs
    separate theoretical laps.
3.  **Scaling-factor path** — when the friction model was built from a
    mixed-condition dataset (or we need to *estimate* grip for an
    unobserved state), literature-based scaling factors are applied to
    the friction ellipse.

Public API
~~~~~~~~~~
- ``SURFACE_GRIP_FACTORS`` — dict mapping TrackState → (low, mid, high)
- ``adjust_friction_for_conditions(friction, track_state, confidence)``
- ``build_phase_friction_models(resampled_laps, phases_df)``
- ``run_phase_aware_simulation(phases, curvature, ...)``
- ``select_theoretical_for_lap(lap_number, phase_results)``
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Final, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# =============================================================================

# Surface grip scaling factors (from motorsport vehicle dynamics literature)

# =============================================================================

# Each value is (low, mid, high) where mid is the nominal factor.

# Factors are relative to dry asphalt = 1.0.


SURFACE_GRIP_FACTORS: Final[dict[str, tuple[float, float, float]]] = {
    # state_value:   (low,  mid,  high)

    "dry":           (1.00, 1.00, 1.00),
    "green":         (0.90, 0.95, 1.00),
    "rubbered":      (1.00, 1.02, 1.05),  # rubber build-up adds grip
    "dusty":         (0.85, 0.90, 0.95),
    "damp":          (0.80, 0.85, 0.90),
    "greasy":        (0.75, 0.80, 0.85),
    "wet":           (0.60, 0.68, 0.75),
    "full_wet":      (0.40, 0.48, 0.55),
    "drying":        (0.75, 0.82, 0.90),  # wide range: depends on line
    "cold":          (0.85, 0.90, 0.95),
    "unknown":       (0.80, 0.90, 1.00),  # conservative default
}

# Column names

_COL_DIST:  Final[str] = "Distance (m)"
_COL_SPEED: Final[str] = "Speed (m/s)"

# Minimum laps per phase for a meaningful friction model

_MIN_LAPS_PER_PHASE: Final[int] = 3


# =============================================================================

# Data structures

# =============================================================================


class WetPhysicsError(ValueError):
    """Raised on invalid input or insufficient data."""


@dataclass
class PhaseTheoretical:
    """Theoretical lap result for a single condition phase.

    Attributes
    ----------
    phase_id : int
        Phase identifier from ``condition_tracking``.
    lap_start : int
        First lap in this phase.
    lap_end : int
        Last lap in this phase.
    track_state : str
        Surface condition label for this phase.
    grip_factor : float
        Scaling factor applied (1.0 = no scaling, from observed data).
    friction_model : Any
        ``FrictionCircle`` for this phase (may be scaled or phase-specific).
    theoretical_result : Any
        ``TheoreticalLapResult`` for this phase (or None on failure).
    lap_time_s : float
        Theoretical lap time for this phase.
    confidence : float
        Confidence in this phase's theoretical (0–1).
    method : str
        ``"phase_observed"`` or ``"phase_scaled"``.
    """

    phase_id:            int = 0
    lap_start:           int = 0
    lap_end:             int = 0
    track_state:         str = "dry"
    grip_factor:         float = 1.0
    friction_model:      Any = None
    theoretical_result:  Any = None
    lap_time_s:          float = float("nan")
    confidence:          float = 1.0
    method:              str = "phase_observed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_id":     self.phase_id,
            "lap_start":    self.lap_start,
            "lap_end":      self.lap_end,
            "track_state":  self.track_state,
            "grip_factor":  round(self.grip_factor, 4),
            "lap_time_s":   round(self.lap_time_s, 3) if math.isfinite(self.lap_time_s) else None,
            "confidence":   round(self.confidence, 3),
            "method":       self.method,
        }


# =============================================================================

# Public API — friction adjustment

# =============================================================================


def get_grip_factor(
    track_state: str,
    *,
    confidence: float = 1.0,
) -> float:
    """
    Return the nominal grip scaling factor for a track surface state.

    When *confidence* < 1.0 the factor is interpolated toward 1.0 (dry),
    reflecting uncertainty about the actual condition.

    Parameters
    ----------
    track_state:
        Surface state string (e.g. ``"wet"``, ``"damp"``).
        Accepts both enum values and raw strings.
    confidence:
        How confident we are about the state (0–1).

    Returns
    -------
    float
        Grip factor (0.0–1.0+ range).
    """
    # Normalise the state string

    state_key = str(track_state).lower().strip()
    # Handle enum objects

    if hasattr(track_state, "value"):
        state_key = str(track_state.value).lower().strip()

    low, mid, high = SURFACE_GRIP_FACTORS.get(state_key, (0.80, 0.90, 1.00))

    # Blend toward dry (1.0) when confidence is low

    confidence = max(0.0, min(1.0, confidence))
    factor = mid * confidence + 1.0 * (1.0 - confidence)

    return round(factor, 4)


def adjust_friction_for_conditions(
    friction: Any,
    track_state: str,
    phase_confidence: float = 1.0,
) -> Any:
    """
    Scale a ``FrictionCircle`` for a given track surface condition.

    If the friction model was already built from laps in the target
    condition, pass ``track_state="dry"`` (factor=1.0) to skip scaling.

    For mixed-condition datasets or condition estimation, this applies
    the literature-based scaling factor via ``FrictionCircle.scaled()``.

    Parameters
    ----------
    friction:
        A ``FrictionCircle`` instance.
    track_state:
        Target surface condition.
    phase_confidence:
        Confidence in the state label (0–1).

    Returns
    -------
    FrictionCircle
        Scaled friction model (or the original if factor ≈ 1.0).
    """
    if friction is None:
        return None

    factor = get_grip_factor(track_state, confidence=phase_confidence)

    # Skip if essentially dry

    if abs(factor - 1.0) < 0.005:
        return friction

    if hasattr(friction, "scaled"):
        return friction.scaled(factor)

    # Fallback: return original with a warning

    logger.warning(
        "Friction object has no .scaled() method; returning unscaled. "
        "track_state=%s, factor=%.3f",
        track_state, factor,
    )
    return friction


# =============================================================================

# Public API — phase-aware friction models

# =============================================================================


def build_phase_friction_models(
    resampled_laps: dict[int, pd.DataFrame],
    phases_df: pd.DataFrame,
    baseline_friction: Any = None,
) -> list[PhaseTheoretical]:
    """
    Build separate friction models for each condition phase.

    For phases with enough laps (≥ ``_MIN_LAPS_PER_PHASE``), a fresh
    friction model is built from only those laps (observed grip).
    For short phases, the *baseline_friction* model is scaled using
    the phase's track state label.

    Parameters
    ----------
    resampled_laps:
        ``{lap_number: DataFrame}`` for all laps.
    phases_df:
        Output of ``condition_tracking.build_condition_phases`` +
        ``label_phases``.  Expected columns: ``phase_id``, ``lap_start``,
        ``lap_end``, ``n_laps``, ``phase_track_state``, ``confidence``.
    baseline_friction:
        Session-wide ``FrictionCircle`` to use as fallback for short phases.

    Returns
    -------
    list[PhaseTheoretical]
        One entry per phase with ``friction_model`` populated.
        ``theoretical_result`` is left as None (caller runs simulations).
    """
    if phases_df is None or phases_df.empty:
        return []

    # Try importing friction_model for per-phase builds

    try:
        import friction_model as fm_mod
        _has_fm = True
    except ImportError:
        _has_fm = False

    sorted_keys = sorted(resampled_laps.keys())
    results: list[PhaseTheoretical] = []

    for _, row in phases_df.iterrows():
        pid       = int(row.get("phase_id", 0))
        lap_start = int(row.get("lap_start", 0))
        lap_end   = int(row.get("lap_end", 0))
        n_laps    = int(row.get("n_laps", 0))
        state     = str(row.get("phase_track_state", "dry"))
        conf      = float(row.get("confidence", 1.0))

        # Collect laps for this phase

        phase_laps = {
            k: resampled_laps[k]
            for k in sorted_keys
            if lap_start <= k <= lap_end and k in resampled_laps
        }

        pt = PhaseTheoretical(
            phase_id=pid,
            lap_start=lap_start,
            lap_end=lap_end,
            track_state=state,
            confidence=conf,
        )

        if len(phase_laps) >= _MIN_LAPS_PER_PHASE and _has_fm:
            # Build friction model from phase-specific laps (observed grip)

            try:
                fc = fm_mod.build_friction_model(phase_laps)
                pt.friction_model = fc
                pt.grip_factor = 1.0  # no scaling needed: observed
                pt.method = "phase_observed"
                logger.info(
                    "Phase %d (%s, laps %d-%d): built observed friction model "
                    "from %d laps.",
                    pid, state, lap_start, lap_end, len(phase_laps),
                )
            except Exception as exc:
                logger.warning(
                    "Phase %d friction build failed: %s — falling back to scaling.",
                    pid, exc,
                )
                pt.friction_model = adjust_friction_for_conditions(
                    baseline_friction, state, conf,
                )
                pt.grip_factor = get_grip_factor(state, confidence=conf)
                pt.method = "phase_scaled"
        else:
            # Not enough laps or no friction_model module — scale baseline

            pt.friction_model = adjust_friction_for_conditions(
                baseline_friction, state, conf,
            )
            pt.grip_factor = get_grip_factor(state, confidence=conf)
            pt.method = "phase_scaled"
            logger.info(
                "Phase %d (%s, laps %d-%d): scaled baseline friction by %.3f "
                "(%d laps, min=%d).",
                pid, state, lap_start, lap_end,
                pt.grip_factor, len(phase_laps), _MIN_LAPS_PER_PHASE,
            )

        results.append(pt)

    return results


# =============================================================================

# Public API — phase-aware simulation

# =============================================================================


def run_phase_aware_simulation(
    phase_models: list[PhaseTheoretical],
    curvature: Any,
    reference_line: Any = None,
    vehicle_params: Any = None,
) -> list[PhaseTheoretical]:
    """
    Run a theoretical lap simulation for each condition phase.

    Parameters
    ----------
    phase_models:
        Output of :func:`build_phase_friction_models`, each with
        ``friction_model`` populated.
    curvature:
        Curvature array (1/m) from the reference line.
    reference_line:
        Optional reference-line object (for ``distance_m``).
    vehicle_params:
        Optional vehicle classification result.

    Returns
    -------
    list[PhaseTheoretical]
        Same list, now with ``theoretical_result`` and ``lap_time_s`` filled.
    """
    try:
        import lap_simulation as sim_mod
        _has_sim = True
    except ImportError:
        _has_sim = False

    if not _has_sim:
        logger.warning("lap_simulation module unavailable — cannot run phase sims.")
        return phase_models

    for pt in phase_models:
        if pt.friction_model is None:
            logger.warning("Phase %d: no friction model, skipping simulation.", pt.phase_id)
            continue

        try:
            result = sim_mod.simulate_theoretical_lap(
                curvature,
                pt.friction_model,
                **({"vehicle_params": vehicle_params} if vehicle_params else {}),
            )
            pt.theoretical_result = result
            pt.lap_time_s = result.lap_time_s
            logger.info(
                "Phase %d (%s): theoretical lap = %.2fs (grip_factor=%.3f, method=%s)",
                pt.phase_id, pt.track_state, pt.lap_time_s,
                pt.grip_factor, pt.method,
            )
        except Exception as exc:
            logger.warning("Phase %d simulation failed: %s", pt.phase_id, exc)
            pt.lap_time_s = float("nan")

    return phase_models


def select_theoretical_for_lap(
    lap_number: int,
    phase_results: list[PhaseTheoretical],
) -> Optional[PhaseTheoretical]:
    """
    Find the correct theoretical reference for a given lap number.

    Returns the ``PhaseTheoretical`` whose lap range contains
    *lap_number*, or ``None`` if no match.
    """
    for pt in phase_results:
        if pt.lap_start <= lap_number <= pt.lap_end:
            return pt
    return None


def summarize_phase_results(
    phase_results: list[PhaseTheoretical],
) -> dict[str, Any]:
    """
    Produce a summary dict for pipeline output / report embedding.
    """
    if not phase_results:
        return {"n_phases": 0, "phases": []}

    return {
        "n_phases": len(phase_results),
        "phases": [pt.to_dict() for pt in phase_results],
        "has_wet_phase": any(
            pt.track_state in ("wet", "full_wet", "damp", "drying", "greasy")
            for pt in phase_results
        ),
        "grip_range": (
            round(min(pt.grip_factor for pt in phase_results), 3),
            round(max(pt.grip_factor for pt in phase_results), 3),
        ),
    }


# =============================================================================

# Self-test

# =============================================================================


def _run_tests() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # -- Mock objects

    _G = 9.80665

    class MockFrictionCircle:
        """Minimal mock matching the FrictionCircle interface."""
        def __init__(self, lat: float = 1.2, brk: float = 1.3, trc: float = 0.8):
            self.v_grid = np.array([0, 10, 20, 30, 40], dtype=float)
            self.lateral_vals = np.full(5, lat * _G)
            self.braking_vals = np.full(5, brk * _G)
            self.traction_vals = np.full(5, trc * _G)
            self.exponent = 2.0

        def lateral_max(self, speed):
            return np.full_like(np.atleast_1d(speed), self.lateral_vals[2], dtype=float)
        def braking_max(self, speed):
            return np.full_like(np.atleast_1d(speed), self.braking_vals[2], dtype=float)
        def traction_max(self, speed):
            return np.full_like(np.atleast_1d(speed), self.traction_vals[2], dtype=float)

        def scaled(self, factor: float) -> "MockFrictionCircle":
            return MockFrictionCircle(
                lat=self.lateral_vals[2] / _G * factor,
                brk=self.braking_vals[2] / _G * factor,
                trc=self.traction_vals[2] / _G * factor,
            )

    class MockTrackState:
        """Simulate an enum-like object."""
        def __init__(self, value: str):
            self.value = value
        def __str__(self):
            return self.value

    def _make_phases_df() -> pd.DataFrame:
        return pd.DataFrame([
            {"phase_id": 0, "lap_start": 1, "lap_end": 8,
             "n_laps": 8, "phase_track_state": "dry", "confidence": 1.0},
            {"phase_id": 1, "lap_start": 9, "lap_end": 15,
             "n_laps": 7, "phase_track_state": "wet", "confidence": 0.85},
        ])

    def _make_resampled_laps(n: int = 15) -> dict[int, pd.DataFrame]:
        rng = np.random.default_rng(42)
        laps = {}
        for i in range(1, n + 1):
            dist = np.linspace(0, 500, 200)
            laps[i] = pd.DataFrame({
                _COL_DIST: dist,
                _COL_SPEED: 20 + 5 * np.sin(2 * np.pi * dist / 500) + rng.normal(0, 0.3, 200),
                "accel_lat_mps2": rng.normal(0, 4, 200),
                "accel_long_mps2": rng.normal(0, 3, 200),
            })
        return laps

    # -- Tests

    # == Grip factor tests ==


    def t_grip_factor_dry():
        f = get_grip_factor("dry")
        assert f == 1.0, f"dry should be 1.0, got {f}"

    _test("grip_factor_dry", t_grip_factor_dry)

    def t_grip_factor_wet():
        f = get_grip_factor("wet")
        assert 0.60 <= f <= 0.75, f"wet should be 0.60-0.75, got {f}"

    _test("grip_factor_wet", t_grip_factor_wet)

    def t_grip_factor_damp():
        f = get_grip_factor("damp")
        assert 0.80 <= f <= 0.90, f"damp should be 0.80-0.90, got {f}"

    _test("grip_factor_damp", t_grip_factor_damp)

    def t_grip_factor_full_wet():
        f = get_grip_factor("full_wet")
        assert 0.40 <= f <= 0.55, f"full_wet should be 0.40-0.55, got {f}"

    _test("grip_factor_full_wet", t_grip_factor_full_wet)

    def t_grip_factor_drying():
        f = get_grip_factor("drying")
        assert 0.75 <= f <= 0.90, f"drying should be 0.75-0.90, got {f}"

    _test("grip_factor_drying", t_grip_factor_drying)

    def t_grip_factor_unknown():
        f = get_grip_factor("unknown")
        assert 0.80 <= f <= 1.00, f"unknown should be 0.80-1.00, got {f}"

    _test("grip_factor_unknown", t_grip_factor_unknown)

    def t_grip_factor_enum():
        """Accept enum-like objects with .value attribute."""
        state = MockTrackState("wet")
        f = get_grip_factor(state)
        assert 0.60 <= f <= 0.75, f"Enum wet should be 0.60-0.75, got {f}"

    _test("grip_factor_enum", t_grip_factor_enum)

    def t_grip_factor_confidence_blend():
        """Low confidence blends toward dry (1.0)."""
        f_full = get_grip_factor("wet", confidence=1.0)
        f_half = get_grip_factor("wet", confidence=0.5)
        f_zero = get_grip_factor("wet", confidence=0.0)
        assert f_full < f_half < f_zero, (
            f"Decreasing confidence should increase factor: "
            f"{f_full}, {f_half}, {f_zero}"
        )
        assert abs(f_zero - 1.0) < 0.001, "Zero confidence should be ~1.0 (dry)"

    _test("grip_factor_confidence_blend", t_grip_factor_confidence_blend)

    def t_grip_ordering():
        """Grip factors should decrease: dry > damp > wet > full_wet."""
        f_dry  = get_grip_factor("dry")
        f_damp = get_grip_factor("damp")
        f_wet  = get_grip_factor("wet")
        f_fw   = get_grip_factor("full_wet")
        assert f_dry > f_damp > f_wet > f_fw, (
            f"Expected dry > damp > wet > full_wet: "
            f"{f_dry}, {f_damp}, {f_wet}, {f_fw}"
        )

    _test("grip_ordering", t_grip_ordering)

    # == Friction adjustment tests ==


    def t_adjust_dry_noop():
        fc = MockFrictionCircle()
        adjusted = adjust_friction_for_conditions(fc, "dry")
        # Should return the same object (no scaling)

        assert adjusted is fc, "Dry should return same object"

    _test("adjust_dry_noop", t_adjust_dry_noop)

    def t_adjust_wet_scales():
        fc = MockFrictionCircle(lat=1.2)
        adjusted = adjust_friction_for_conditions(fc, "wet")
        orig_lat = float(fc.lateral_max(20.0).flat[0])
        new_lat = float(adjusted.lateral_max(20.0).flat[0])
        assert new_lat < orig_lat, (
            f"Wet friction should be lower: {new_lat} vs {orig_lat}"
        )
        ratio = new_lat / orig_lat
        assert 0.55 <= ratio <= 0.80, f"Wet scaling ratio should be ~0.68, got {ratio}"

    _test("adjust_wet_scales", t_adjust_wet_scales)

    def t_adjust_none_friction():
        result = adjust_friction_for_conditions(None, "wet")
        assert result is None

    _test("adjust_none_friction", t_adjust_none_friction)

    def t_adjust_confidence():
        fc = MockFrictionCircle(lat=1.2)
        adj_sure = adjust_friction_for_conditions(fc, "wet", phase_confidence=1.0)
        adj_unsure = adjust_friction_for_conditions(fc, "wet", phase_confidence=0.5)
        lat_sure = float(adj_sure.lateral_max(20.0).flat[0])
        lat_unsure = float(adj_unsure.lateral_max(20.0).flat[0])
        assert lat_unsure > lat_sure, (
            f"Lower confidence should produce less scaling: "
            f"{lat_unsure} vs {lat_sure}"
        )

    _test("adjust_confidence", t_adjust_confidence)

    # == Phase model building tests ==


    def t_build_phase_models_basic():
        laps = _make_resampled_laps(15)
        phases = _make_phases_df()
        baseline = MockFrictionCircle()
        results = build_phase_friction_models(laps, phases, baseline)
        assert len(results) == 2
        assert results[0].track_state == "dry"
        assert results[1].track_state == "wet"

    _test("build_phase_models_basic", t_build_phase_models_basic)

    def t_phase_models_have_friction():
        laps = _make_resampled_laps(15)
        phases = _make_phases_df()
        baseline = MockFrictionCircle()
        results = build_phase_friction_models(laps, phases, baseline)
        for pt in results:
            assert pt.friction_model is not None, (
                f"Phase {pt.phase_id}: no friction model"
            )

    _test("phase_models_have_friction", t_phase_models_have_friction)

    def t_phase_wet_has_lower_grip():
        """Wet phase should have lower grip than dry phase."""
        laps = _make_resampled_laps(15)
        phases = _make_phases_df()
        baseline = MockFrictionCircle()
        results = build_phase_friction_models(laps, phases, baseline)

        dry_phase = results[0]
        wet_phase = results[1]

        # If wet phase used scaling, grip_factor < 1.0

        if wet_phase.method == "phase_scaled":
            assert wet_phase.grip_factor < 1.0, (
                f"Wet phase grip_factor should be < 1.0: {wet_phase.grip_factor}"
            )

    _test("phase_wet_has_lower_grip", t_phase_wet_has_lower_grip)

    def t_phase_models_empty_phases():
        laps = _make_resampled_laps(10)
        empty_df = pd.DataFrame()
        results = build_phase_friction_models(laps, empty_df)
        assert results == []

    _test("phase_models_empty_phases", t_phase_models_empty_phases)

    def t_phase_models_none_phases():
        laps = _make_resampled_laps(10)
        results = build_phase_friction_models(laps, None)
        assert results == []

    _test("phase_models_none_phases", t_phase_models_none_phases)

    def t_phase_short_uses_scaling():
        """Phase with < 3 laps should use scaling fallback."""
        phases = pd.DataFrame([{
            "phase_id": 0, "lap_start": 1, "lap_end": 2,
            "n_laps": 2, "phase_track_state": "damp", "confidence": 0.8,
        }])
        laps = _make_resampled_laps(5)
        baseline = MockFrictionCircle()
        results = build_phase_friction_models(laps, phases, baseline)
        assert len(results) == 1
        assert results[0].method == "phase_scaled"
        assert results[0].grip_factor < 1.0

    _test("phase_short_uses_scaling", t_phase_short_uses_scaling)

    # == Selection tests ==


    def t_select_for_lap():
        pts = [
            PhaseTheoretical(phase_id=0, lap_start=1, lap_end=8, track_state="dry"),
            PhaseTheoretical(phase_id=1, lap_start=9, lap_end=15, track_state="wet"),
        ]
        assert select_theoretical_for_lap(5, pts).phase_id == 0
        assert select_theoretical_for_lap(10, pts).phase_id == 1
        assert select_theoretical_for_lap(1, pts).phase_id == 0
        assert select_theoretical_for_lap(15, pts).phase_id == 1

    _test("select_for_lap", t_select_for_lap)

    def t_select_for_lap_missing():
        pts = [
            PhaseTheoretical(phase_id=0, lap_start=5, lap_end=10),
        ]
        assert select_theoretical_for_lap(3, pts) is None
        assert select_theoretical_for_lap(12, pts) is None

    _test("select_for_lap_missing", t_select_for_lap_missing)

    # == Summarize tests ==


    def t_summarize_phases():
        pts = [
            PhaseTheoretical(
                phase_id=0, lap_start=1, lap_end=8,
                track_state="dry", grip_factor=1.0, lap_time_s=90.0,
            ),
            PhaseTheoretical(
                phase_id=1, lap_start=9, lap_end=15,
                track_state="wet", grip_factor=0.68, lap_time_s=105.0,
            ),
        ]
        s = summarize_phase_results(pts)
        assert s["n_phases"] == 2
        assert s["has_wet_phase"] is True
        assert s["grip_range"] == (0.68, 1.0)
        assert len(s["phases"]) == 2

    _test("summarize_phases", t_summarize_phases)

    def t_summarize_empty():
        s = summarize_phase_results([])
        assert s["n_phases"] == 0

    _test("summarize_empty", t_summarize_empty)

    def t_summarize_dry_only():
        pts = [
            PhaseTheoretical(
                phase_id=0, lap_start=1, lap_end=20,
                track_state="dry", grip_factor=1.0,
            ),
        ]
        s = summarize_phase_results(pts)
        assert s["has_wet_phase"] is False

    _test("summarize_dry_only", t_summarize_dry_only)

    # == PhaseTheoretical tests ==


    def t_phase_theoretical_to_dict():
        pt = PhaseTheoretical(
            phase_id=1, lap_start=5, lap_end=12,
            track_state="wet", grip_factor=0.68,
            lap_time_s=105.2, confidence=0.85, method="phase_observed",
        )
        d = pt.to_dict()
        assert d["phase_id"] == 1
        assert d["grip_factor"] == 0.68
        assert d["lap_time_s"] == 105.2
        assert d["method"] == "phase_observed"

    _test("phase_theoretical_to_dict", t_phase_theoretical_to_dict)

    def t_phase_theoretical_nan_time():
        pt = PhaseTheoretical(lap_time_s=float("nan"))
        d = pt.to_dict()
        assert d["lap_time_s"] is None

    _test("phase_theoretical_nan_time", t_phase_theoretical_nan_time)

    # == Integration / scoring tests ==


    def t_wet_scoring_integration():
        """Wet theoretical is slower → pace gap smaller → fairer scoring."""
        fc_dry = MockFrictionCircle(lat=1.2)
        fc_wet = adjust_friction_for_conditions(fc_dry, "wet")

        dry_lat = float(fc_dry.lateral_max(20.0).flat[0])
        wet_lat = float(fc_wet.lateral_max(20.0).flat[0])

        # A driver pulling 0.9G lateral:

        driver_lat = 0.9 * _G
        # vs dry theoretical: gap is large

        dry_gap_pct = (dry_lat - driver_lat) / dry_lat * 100
        # vs wet theoretical: gap is smaller (or driver may exceed!)

        wet_gap_pct = (wet_lat - driver_lat) / wet_lat * 100

        assert wet_gap_pct < dry_gap_pct, (
            f"Wet theoretical should produce smaller gap: "
            f"wet={wet_gap_pct:.1f}% vs dry={dry_gap_pct:.1f}%"
        )

    _test("wet_scoring_integration", t_wet_scoring_integration)

    def t_all_surface_states_have_factors():
        """Every surface state in SURFACE_GRIP_FACTORS should work."""
        for state in SURFACE_GRIP_FACTORS:
            f = get_grip_factor(state)
            assert 0 < f <= 1.1, f"State '{state}': factor={f} out of range"

    _test("all_surface_states_have_factors", t_all_surface_states_have_factors)

    def t_rubbered_above_dry():
        """Rubbered-in track should have grip ≥ dry."""
        f = get_grip_factor("rubbered")
        assert f >= 1.0, f"Rubbered should be >= 1.0, got {f}"

    _test("rubbered_above_dry", t_rubbered_above_dry)

    def t_adjust_preserves_ellipse_shape():
        """Scaling should preserve the exponent and relative proportions."""
        fc = MockFrictionCircle(lat=1.2, brk=1.3, trc=0.8)
        scaled = adjust_friction_for_conditions(fc, "wet")

        orig_ratio = (
            float(fc.lateral_max(20.0).flat[0])
            / float(fc.braking_max(20.0).flat[0])
        )
        new_ratio = (
            float(scaled.lateral_max(20.0).flat[0])
            / float(scaled.braking_max(20.0).flat[0])
        )
        assert abs(orig_ratio - new_ratio) < 0.01, (
            f"Scaling should preserve proportions: {orig_ratio:.4f} vs {new_ratio:.4f}"
        )

    _test("adjust_preserves_ellipse_shape", t_adjust_preserves_ellipse_shape)

    # -- Summary
    total = len(passed) + len(failed)
    print(f"\nWet Physics Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  \u2713 {name}")
    for name, tb in failed:
        print(f"  \u2717 {name}\n{tb}")

    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
