"""
corner_mastery.py
-----------------
Per-corner mastery scoring and report-card generation.

Combines multiple corner performance dimensions into a single
0-100 mastery score per corner, providing a "report card" that
highlights specific strengths and improvement areas.

Dimensions
~~~~~~~~~~
1. **Brake Precision** (0-100): consistency of brake initiation point
   across laps. Computed as ``100 * (1 - std(brake_m) / threshold)``.
2. **Apex Speed Efficiency** (0-100): how close apex speeds are to
   the theoretical/best observed.
3. **Exit Utilisation** (0-100): exit speed relative to best practice
   or best personal observed.
4. **Consistency** (0-100): inverse of time-loss CV across laps for
   that corner.
5. **Grip Utilisation** (0-100): how much of the available grip
   envelope is used.

Public API
~~~~~~~~~~
- ``compute_corner_mastery(corner_metrics_by_corner, best_practices)``
- ``rank_corners(mastery_results)``
- ``generate_corner_report_card(mastery)``

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs -> identical outputs.
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Final, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# Brake point scatter threshold (metres) for 0% precision
BRAKE_SCATTER_ZERO_M: Final[float] = 15.0

# Apex speed: % deficit from best that maps to zero score
APEX_DEFICIT_ZERO_PCT: Final[float] = 20.0

# Exit speed: deficit (m/s) that maps to zero score
EXIT_DEFICIT_ZERO_MPS: Final[float] = 5.0

# Time loss CV threshold for consistency zero (%)
CONSISTENCY_CV_ZERO: Final[float] = 80.0

# Sub-score weights for composite mastery
_W_BRAKE:       Final[float] = 0.20
_W_APEX:        Final[float] = 0.25
_W_EXIT:        Final[float] = 0.20
_W_CONSISTENCY: Final[float] = 0.15
_W_GRIP:        Final[float] = 0.20


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class CornerMastery:
    """Mastery assessment for a single corner."""

    corner_id: int
    n_laps: int = 0

    # Sub-scores (0-100)
    brake_precision_score: float = 0.0
    apex_speed_score: float = 0.0
    exit_utilisation_score: float = 0.0
    consistency_score: float = 0.0
    grip_utilisation_score: float = 0.0

    # Composite
    mastery_score: float = 0.0
    grade: str = "F"

    # Details
    brake_std_m: float = float("nan")
    apex_speed_mean_mps: float = float("nan")
    apex_speed_best_mps: float = float("nan")
    exit_speed_mean_mps: float = float("nan")
    exit_speed_best_mps: float = float("nan")
    time_loss_mean_ms: float = float("nan")
    time_loss_std_ms: float = float("nan")
    grip_mean_pct: float = float("nan")

    # Coaching
    strongest_area: str = ""
    weakest_area: str = ""
    coaching_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "corner_id": self.corner_id,
            "n_laps": self.n_laps,
            "mastery_score": round(self.mastery_score, 1),
            "grade": self.grade,
            "brake_precision_score": round(self.brake_precision_score, 1),
            "apex_speed_score": round(self.apex_speed_score, 1),
            "exit_utilisation_score": round(self.exit_utilisation_score, 1),
            "consistency_score": round(self.consistency_score, 1),
            "grip_utilisation_score": round(self.grip_utilisation_score, 1),
            "brake_std_m": _r(self.brake_std_m),
            "apex_speed_mean_mps": _r(self.apex_speed_mean_mps),
            "exit_speed_mean_mps": _r(self.exit_speed_mean_mps),
            "time_loss_mean_ms": _r(self.time_loss_mean_ms),
            "time_loss_std_ms": _r(self.time_loss_std_ms),
            "grip_mean_pct": _r(self.grip_mean_pct),
            "strongest_area": self.strongest_area,
            "weakest_area": self.weakest_area,
            "coaching_hint": self.coaching_hint,
        }


def _r(v: float, places: int = 2) -> float:
    """Safe round that handles NaN."""
    return round(v, places) if math.isfinite(v) else v


def _grade(score: float) -> str:
    """Map 0-100 score to letter grade."""
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "F"


def _safe_float(v: Any) -> float:
    """Convert to float, returning NaN for None/invalid."""
    if v is None:
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


# ============================================================================
# Core Computation
# ============================================================================


def compute_corner_mastery(
    corner_metrics_by_corner: dict[int, list[dict]],
    best_practices: Optional[dict[int, dict]] = None,
) -> list[CornerMastery]:
    """
    Compute mastery scores for each corner.

    Parameters
    ----------
    corner_metrics_by_corner:
        ``{corner_id: [lap_metrics_dicts]}``.
        Each dict has keys: brake_point_m, entry_speed_mps, apex_speed_mps,
        exit_speed_mps, grip_utilization, time_loss_ms, etc.
    best_practices:
        ``{corner_id: {best_apex_mps, best_exit_mps, ...}}``.
        If None, uses the best values from the driver's own data.

    Returns
    -------
    list[CornerMastery]
        One entry per corner, sorted by corner_id.
    """
    if not corner_metrics_by_corner:
        return []

    results: list[CornerMastery] = []
    bp = best_practices or {}

    for corner_id in sorted(corner_metrics_by_corner.keys()):
        laps = corner_metrics_by_corner[corner_id]
        n = len(laps)

        if n == 0:
            results.append(CornerMastery(corner_id=corner_id))
            continue

        # Extract arrays
        brake_pts = [_safe_float(m.get("brake_point_m")) for m in laps]
        apex_spds = [_safe_float(m.get("apex_speed_mps")) for m in laps]
        exit_spds = [_safe_float(m.get("exit_speed_mps")) for m in laps]
        grips     = [_safe_float(m.get("grip_utilization")) for m in laps]
        losses    = [_safe_float(m.get("time_loss_ms")) for m in laps]

        # --- Brake Precision ---
        valid_brakes = [v for v in brake_pts if math.isfinite(v)]
        if len(valid_brakes) >= 2:
            brake_std = float(np.std(valid_brakes, ddof=1))
            brake_score = max(0.0, 100.0 * (1.0 - brake_std / BRAKE_SCATTER_ZERO_M))
        else:
            brake_std = float("nan")
            brake_score = 50.0  # neutral when unknown

        # --- Apex Speed Efficiency ---
        valid_apex = [v for v in apex_spds if math.isfinite(v) and v > 0]
        if valid_apex:
            apex_mean = float(np.mean(valid_apex))
            # Best reference: best_practices or personal best
            ref_apex = _safe_float(bp.get(corner_id, {}).get("best_apex_mps"))
            if not math.isfinite(ref_apex):
                ref_apex = float(np.max(valid_apex))
            if ref_apex > 0:
                deficit_pct = max(0.0, (ref_apex - apex_mean) / ref_apex * 100.0)
                apex_score = max(0.0, 100.0 * (1.0 - deficit_pct / APEX_DEFICIT_ZERO_PCT))
            else:
                apex_score = 50.0
        else:
            apex_mean = float("nan")
            apex_score = 50.0

        # --- Exit Utilisation ---
        valid_exit = [v for v in exit_spds if math.isfinite(v) and v > 0]
        if valid_exit:
            exit_mean = float(np.mean(valid_exit))
            ref_exit = _safe_float(bp.get(corner_id, {}).get("best_exit_mps"))
            if not math.isfinite(ref_exit):
                ref_exit = float(np.max(valid_exit))
            if ref_exit > 0:
                deficit_mps = max(0.0, ref_exit - exit_mean)
                exit_score = max(0.0, 100.0 * (1.0 - deficit_mps / EXIT_DEFICIT_ZERO_MPS))
            else:
                exit_score = 50.0
        else:
            exit_mean = float("nan")
            exit_score = 50.0

        # --- Consistency (inverse of time-loss variation) ---
        valid_losses = [abs(v) for v in losses if math.isfinite(v)]
        if len(valid_losses) >= 2:
            loss_mean = float(np.mean(valid_losses))
            loss_std = float(np.std(valid_losses, ddof=1))
            loss_cv = (loss_std / loss_mean * 100.0) if loss_mean > 0 else 0.0
            consistency_score = max(0.0, 100.0 * (1.0 - loss_cv / CONSISTENCY_CV_ZERO))
        else:
            loss_mean = float(np.mean(valid_losses)) if valid_losses else float("nan")
            loss_std = float("nan")
            consistency_score = 50.0

        # --- Grip Utilisation ---
        valid_grips = [v for v in grips if math.isfinite(v)]
        if valid_grips:
            grip_mean = float(np.mean(valid_grips))
            # Grip is already 0-100
            grip_score = min(100.0, max(0.0, grip_mean))
        else:
            grip_mean = float("nan")
            grip_score = 50.0

        # --- Composite Mastery Score ---
        mastery = (
            brake_score * _W_BRAKE
            + apex_score * _W_APEX
            + exit_score * _W_EXIT
            + consistency_score * _W_CONSISTENCY
            + grip_score * _W_GRIP
        )
        mastery = min(100.0, max(0.0, mastery))

        # --- Strongest / Weakest ---
        sub = {
            "Brake Precision": brake_score,
            "Apex Speed": apex_score,
            "Exit Speed": exit_score,
            "Consistency": consistency_score,
            "Grip Usage": grip_score,
        }
        strongest = max(sub, key=sub.get)
        weakest = min(sub, key=sub.get)

        # --- Coaching hint ---
        hint = _generate_hint(weakest, sub[weakest], corner_id)

        cm = CornerMastery(
            corner_id=corner_id,
            n_laps=n,
            brake_precision_score=round(brake_score, 1),
            apex_speed_score=round(apex_score, 1),
            exit_utilisation_score=round(exit_score, 1),
            consistency_score=round(consistency_score, 1),
            grip_utilisation_score=round(grip_score, 1),
            mastery_score=round(mastery, 1),
            grade=_grade(mastery),
            brake_std_m=brake_std if math.isfinite(brake_std) else float("nan"),
            apex_speed_mean_mps=apex_mean if math.isfinite(apex_mean) else float("nan"),
            apex_speed_best_mps=ref_apex if 'ref_apex' in dir() and math.isfinite(ref_apex) else float("nan"),
            exit_speed_mean_mps=exit_mean if math.isfinite(exit_mean) else float("nan"),
            exit_speed_best_mps=ref_exit if 'ref_exit' in dir() and math.isfinite(ref_exit) else float("nan"),
            time_loss_mean_ms=loss_mean if math.isfinite(loss_mean) else float("nan"),
            time_loss_std_ms=loss_std if 'loss_std' in dir() and math.isfinite(loss_std) else float("nan"),
            grip_mean_pct=grip_mean if math.isfinite(grip_mean) else float("nan"),
            strongest_area=strongest,
            weakest_area=weakest,
            coaching_hint=hint,
        )
        results.append(cm)

    logger.info(
        "Corner mastery: %d corners, scores=%s",
        len(results),
        [f"C{r.corner_id}={r.mastery_score:.0f}" for r in results],
    )
    return results


def _generate_hint(weakest: str, score: float, corner_id: int) -> str:
    """Generate a coaching hint based on weakest area."""
    cid = f"Corner {corner_id}"
    if score >= 80:
        return f"{cid}: strong across all areas. Fine-tune for marginal gains."
    hints = {
        "Brake Precision": (
            f"{cid}: brake point scatter is high -- "
            f"use a consistent visual reference marker."
        ),
        "Apex Speed": (
            f"{cid}: apex speed below potential -- "
            f"carry more speed through the turn-in phase."
        ),
        "Exit Speed": (
            f"{cid}: exit speed below potential -- "
            f"focus on earlier throttle application and straighter exit line."
        ),
        "Consistency": (
            f"{cid}: lap-to-lap variation is high -- "
            f"simplify your approach and hit the same marks every lap."
        ),
        "Grip Usage": (
            f"{cid}: grip utilisation is low -- "
            f"push closer to the traction limit through the corner."
        ),
    }
    return hints.get(weakest, f"{cid}: focus on {weakest.lower()} improvement.")


# ============================================================================
# Ranking & Report Card
# ============================================================================


def rank_corners(mastery_results: list[CornerMastery]) -> list[CornerMastery]:
    """Rank corners from worst to best mastery (improvement priority)."""
    return sorted(mastery_results, key=lambda m: m.mastery_score)


def generate_corner_report_card(mastery_results: list[CornerMastery]) -> dict[str, Any]:
    """
    Generate a summary report card for all corners.

    Returns
    -------
    dict
        Keys: overall_mastery, corner_grades, priority_corners, summary.
    """
    if not mastery_results:
        return {"overall_mastery": 0.0, "corner_grades": {}, "priority_corners": [], "summary": ""}

    overall = float(np.mean([m.mastery_score for m in mastery_results]))
    grades = {f"Corner {m.corner_id}": m.grade for m in mastery_results}
    ranked = rank_corners(mastery_results)
    priority = [m.corner_id for m in ranked[:3]]

    summary_parts = [f"Overall corner mastery: {overall:.0f}/100 ({_grade(overall)})"]
    if ranked and ranked[0].mastery_score < 60:
        summary_parts.append(
            f"Priority: Corner {ranked[0].corner_id} ({ranked[0].mastery_score:.0f}) -- "
            f"{ranked[0].weakest_area} needs work."
        )

    return {
        "overall_mastery": round(overall, 1),
        "overall_grade": _grade(overall),
        "corner_grades": grades,
        "priority_corners": priority,
        "corners": [m.to_dict() for m in mastery_results],
        "summary": " ".join(summary_parts),
    }


# ============================================================================
# Self-test
# ============================================================================


def _run_tests() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # Helpers
    def _make_metrics(n_laps: int, corner_id: int = 1,
                      brake_base: float = 50.0, brake_scatter: float = 1.0,
                      apex_base: float = 15.0, exit_base: float = 20.0,
                      grip: float = 75.0, loss_base: float = 100.0) -> list[dict]:
        rng = np.random.default_rng(42 + corner_id)
        return [
            {
                "brake_point_m": brake_base + rng.normal(0, brake_scatter),
                "apex_speed_mps": apex_base + rng.normal(0, 0.3),
                "exit_speed_mps": exit_base + rng.normal(0, 0.4),
                "grip_utilization": grip + rng.normal(0, 3),
                "time_loss_ms": max(0, loss_base + rng.normal(0, 20)),
            }
            for _ in range(n_laps)
        ]

    # --- Tests ---

    def t_basic_mastery():
        data = {1: _make_metrics(10, corner_id=1)}
        results = compute_corner_mastery(data)
        assert len(results) == 1
        m = results[0]
        assert 0 <= m.mastery_score <= 100
        assert m.grade in ("S", "A", "B", "C", "D", "F")
        assert m.n_laps == 10

    _test("basic_mastery", t_basic_mastery)

    def t_multiple_corners():
        data = {
            1: _make_metrics(10, corner_id=1, brake_scatter=1.0),
            2: _make_metrics(10, corner_id=2, brake_scatter=8.0),  # poor braking
            3: _make_metrics(10, corner_id=3, grip=40.0),          # low grip
        }
        results = compute_corner_mastery(data)
        assert len(results) == 3
        # Corner 2 should have worse brake precision
        c1 = next(r for r in results if r.corner_id == 1)
        c2 = next(r for r in results if r.corner_id == 2)
        assert c1.brake_precision_score > c2.brake_precision_score

    _test("multiple_corners", t_multiple_corners)

    def t_empty_input():
        assert compute_corner_mastery({}) == []

    _test("empty_input", t_empty_input)

    def t_single_lap():
        data = {1: _make_metrics(1)}
        results = compute_corner_mastery(data)
        assert len(results) == 1
        assert results[0].n_laps == 1

    _test("single_lap", t_single_lap)

    def t_with_best_practices():
        data = {1: _make_metrics(10, apex_base=14.0, exit_base=19.0)}
        bp = {1: {"best_apex_mps": 16.0, "best_exit_mps": 22.0}}
        results = compute_corner_mastery(data, best_practices=bp)
        m = results[0]
        # Should have lower scores because reference is higher
        assert m.apex_speed_score < 100

    _test("with_best_practices", t_with_best_practices)

    def t_ranking():
        data = {
            1: _make_metrics(10, loss_base=50),
            2: _make_metrics(10, loss_base=200),
            3: _make_metrics(10, loss_base=100),
        }
        results = compute_corner_mastery(data)
        ranked = rank_corners(results)
        # Ranked should be worst first
        assert ranked[0].corner_id != ranked[-1].corner_id

    _test("ranking", t_ranking)

    def t_report_card():
        data = {
            1: _make_metrics(10, corner_id=1),
            2: _make_metrics(10, corner_id=2),
        }
        results = compute_corner_mastery(data)
        card = generate_corner_report_card(results)
        assert "overall_mastery" in card
        assert "corners" in card
        assert len(card["corners"]) == 2
        assert card["overall_grade"] in ("S", "A", "B", "C", "D", "F")

    _test("report_card", t_report_card)

    def t_nan_robustness():
        data = {1: [
            {"brake_point_m": None, "apex_speed_mps": 15.0,
             "exit_speed_mps": None, "grip_utilization": None,
             "time_loss_ms": 100},
            {"brake_point_m": 50.0, "apex_speed_mps": None,
             "exit_speed_mps": 20.0, "grip_utilization": 70,
             "time_loss_ms": None},
        ]}
        results = compute_corner_mastery(data)
        assert len(results) == 1
        assert math.isfinite(results[0].mastery_score)

    _test("nan_robustness", t_nan_robustness)

    def t_serialization():
        data = {1: _make_metrics(5)}
        results = compute_corner_mastery(data)
        d = results[0].to_dict()
        for key in ("mastery_score", "grade", "brake_precision_score",
                     "coaching_hint", "strongest_area", "weakest_area"):
            assert key in d, f"Missing key: {key}"

    _test("serialization", t_serialization)

    def t_deterministic():
        data = {1: _make_metrics(10)}
        r1 = compute_corner_mastery(data)
        r2 = compute_corner_mastery(data)
        assert r1[0].to_dict() == r2[0].to_dict()

    _test("deterministic", t_deterministic)

    # Summary
    total = len(passed) + len(failed)
    print(f"\nCorner Mastery Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
