"""
performance_fingerprint.py
--------------------------
Driver performance fingerprinting across 6 normalised dimensions.

Creates a unique, comparable fingerprint vector for each driver session
that can be used for:
- Driver comparison (overlay radar charts)
- Evolution tracking (how does the fingerprint change over time?)
- Team composition analysis (complementary strengths)
- Session quality assessment (balanced vs. imbalanced profiles)

Dimensions (all normalised 0-100)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **Raw Pace**        -- best lap relative to track record/theoretical
2. **Consistency**     -- inverse CV of lap times
3. **Racecraft**       -- robustness / adaptation score
4. **Technical Skill** -- corner execution quality
5. **Tyre Management** -- pace fade and grip preservation
6. **Mental Fortitude** -- concentration index / lapse resistance

Public API
~~~~~~~~~~
- ``compute_fingerprint(session_data)``
- ``compare_fingerprints(fp1, fp2)``
- ``compute_evolution(fingerprints_over_time)``
- ``compute_balance_score(fingerprint)``

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

DIMENSION_NAMES: Final[list[str]] = [
    "Raw Pace",
    "Consistency",
    "Racecraft",
    "Technical Skill",
    "Tyre Management",
    "Mental Fortitude",
]

N_DIMENSIONS: Final[int] = 6


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class Fingerprint:
    """A 6-dimensional performance fingerprint."""

    session_id: str = ""
    driver_name: str = ""

    raw_pace: float = 50.0
    consistency: float = 50.0
    racecraft: float = 50.0
    technical_skill: float = 50.0
    tyre_management: float = 50.0
    mental_fortitude: float = 50.0

    # Derived
    balance_score: float = 50.0  # 0=extreme specialist, 100=perfectly balanced
    overall_rating: float = 50.0

    def to_vector(self) -> list[float]:
        """Return the 6 dimensions as a list."""
        return [
            self.raw_pace,
            self.consistency,
            self.racecraft,
            self.technical_skill,
            self.tyre_management,
            self.mental_fortitude,
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "driver_name": self.driver_name,
            "dimensions": {
                "raw_pace": round(self.raw_pace, 1),
                "consistency": round(self.consistency, 1),
                "racecraft": round(self.racecraft, 1),
                "technical_skill": round(self.technical_skill, 1),
                "tyre_management": round(self.tyre_management, 1),
                "mental_fortitude": round(self.mental_fortitude, 1),
            },
            "vector": [round(v, 1) for v in self.to_vector()],
            "balance_score": round(self.balance_score, 1),
            "overall_rating": round(self.overall_rating, 1),
            "dimension_names": list(DIMENSION_NAMES),
        }


def _clamp(v: float) -> float:
    """Clamp to 0-100."""
    if not math.isfinite(v):
        return 50.0
    return max(0.0, min(100.0, v))


# ============================================================================
# Fingerprint Computation
# ============================================================================


def compute_fingerprint(
    session_data: dict[str, Any],
) -> Fingerprint:
    """
    Compute a 6-dimension fingerprint from session scoring data.

    Parameters
    ----------
    session_data:
        Dict with keys from scoring output and analysis results:
        - ``pace_pct``: pace sub-score as % of max (0-100)
        - ``consistency_pct``: consistency sub-score as % of max
        - ``robustness_pct``: robustness sub-score as % of max
        - ``execution_pct``: execution sub-score as % of max
        - ``pace_fade_pct``: pace fade % (positive = worse, 0-10 typical)
        - ``concentration_index``: from fatigue detection (0-100)
        - ``adaptation_score``: from phase-aware scoring (0-1)
        - ``session_id``, ``driver_name``: metadata

    Returns
    -------
    Fingerprint
    """
    fp = Fingerprint(
        session_id=str(session_data.get("session_id", "")),
        driver_name=str(session_data.get("driver_name", "")),
    )

    # 1. Raw Pace: from pace sub-score percentage
    pace_pct = session_data.get("pace_pct")
    if pace_pct is not None and math.isfinite(float(pace_pct)):
        fp.raw_pace = _clamp(float(pace_pct))

    # 2. Consistency: from consistency sub-score percentage
    cons_pct = session_data.get("consistency_pct")
    if cons_pct is not None and math.isfinite(float(cons_pct)):
        fp.consistency = _clamp(float(cons_pct))

    # 3. Racecraft: blend of robustness + adaptation
    robust_pct = session_data.get("robustness_pct", 50.0)
    adapt = session_data.get("adaptation_score")
    if robust_pct is not None and math.isfinite(float(robust_pct)):
        rob = float(robust_pct)
    else:
        rob = 50.0
    if adapt is not None and math.isfinite(float(adapt)):
        # adaptation_score is 0-1 scale
        adp = float(adapt) * 100.0
        fp.racecraft = _clamp(rob * 0.6 + adp * 0.4)
    else:
        fp.racecraft = _clamp(rob)

    # 4. Technical Skill: from execution sub-score
    exec_pct = session_data.get("execution_pct")
    if exec_pct is not None and math.isfinite(float(exec_pct)):
        fp.technical_skill = _clamp(float(exec_pct))

    # 5. Tyre Management: inverse of pace fade
    fade = session_data.get("pace_fade_pct", 0.0)
    if fade is not None and math.isfinite(float(fade)):
        # 0% fade = 100 score, 10%+ fade = 0 score
        fp.tyre_management = _clamp(100.0 - float(fade) * 10.0)

    # 6. Mental Fortitude: from concentration index
    conc = session_data.get("concentration_index")
    if conc is not None and math.isfinite(float(conc)):
        fp.mental_fortitude = _clamp(float(conc))

    # Derived metrics
    fp.balance_score = compute_balance_score(fp)
    fp.overall_rating = round(float(np.mean(fp.to_vector())), 1)

    logger.info(
        "Fingerprint: %s pace=%.0f cons=%.0f race=%.0f tech=%.0f tyre=%.0f mental=%.0f "
        "| overall=%.0f balance=%.0f",
        fp.session_id, fp.raw_pace, fp.consistency, fp.racecraft,
        fp.technical_skill, fp.tyre_management, fp.mental_fortitude,
        fp.overall_rating, fp.balance_score,
    )
    return fp


# ============================================================================
# Comparison & Evolution
# ============================================================================


def compare_fingerprints(
    fp1: Fingerprint,
    fp2: Fingerprint,
) -> dict[str, Any]:
    """
    Compare two fingerprints dimension-by-dimension.

    Returns
    -------
    dict
        Per-dimension deltas, overall similarity, and which driver is
        stronger in each dimension.
    """
    v1 = fp1.to_vector()
    v2 = fp2.to_vector()

    deltas = {}
    advantages_1: list[str] = []
    advantages_2: list[str] = []

    for i, name in enumerate(DIMENSION_NAMES):
        d = v1[i] - v2[i]
        deltas[name] = round(d, 1)
        if d > 5:
            advantages_1.append(name)
        elif d < -5:
            advantages_2.append(name)

    # Cosine similarity
    a1 = np.array(v1, dtype=float)
    a2 = np.array(v2, dtype=float)
    dot = float(np.dot(a1, a2))
    norm1 = float(np.linalg.norm(a1))
    norm2 = float(np.linalg.norm(a2))
    similarity = (dot / (norm1 * norm2) * 100.0) if (norm1 > 0 and norm2 > 0) else 0.0

    return {
        "driver_1": fp1.driver_name,
        "driver_2": fp2.driver_name,
        "deltas": deltas,
        "similarity_pct": round(similarity, 1),
        "advantages_1": advantages_1,
        "advantages_2": advantages_2,
        "overall_1": fp1.overall_rating,
        "overall_2": fp2.overall_rating,
    }


def compute_evolution(
    fingerprints: list[Fingerprint],
) -> dict[str, Any]:
    """
    Track how a driver's fingerprint evolves over time.

    Parameters
    ----------
    fingerprints:
        Chronologically ordered fingerprints for the same driver.

    Returns
    -------
    dict
        Per-dimension trends, overall improvement, and dimension labels.
    """
    if not fingerprints:
        return {"trends": {}, "overall_trend": 0.0}

    n = len(fingerprints)
    if n < 2:
        return {
            "trends": {name: 0.0 for name in DIMENSION_NAMES},
            "overall_trend": 0.0,
            "latest": fingerprints[0].to_dict() if fingerprints else {},
        }

    # Per-dimension trend (slope)
    trends: dict[str, float] = {}
    for dim_idx, name in enumerate(DIMENSION_NAMES):
        values = [fp.to_vector()[dim_idx] for fp in fingerprints]
        arr = np.array(values, dtype=float)
        x = np.arange(n, dtype=float)
        mask = np.isfinite(arr)
        if mask.sum() >= 2:
            xm, ym = x[mask], arr[mask]
            x_bar, y_bar = float(xm.mean()), float(ym.mean())
            denom = float(((xm - x_bar) ** 2).sum())
            slope = float(((xm - x_bar) * (ym - y_bar)).sum() / denom) if denom > 0 else 0.0
        else:
            slope = 0.0
        trends[name] = round(slope, 2)

    overall_values = [fp.overall_rating for fp in fingerprints]
    overall_trend = overall_values[-1] - overall_values[0] if len(overall_values) >= 2 else 0.0

    return {
        "trends": trends,
        "overall_trend": round(overall_trend, 1),
        "n_sessions": n,
        "latest": fingerprints[-1].to_dict(),
    }


def compute_balance_score(fp: Fingerprint) -> float:
    """
    How balanced is the fingerprint? 100 = all dimensions equal, 0 = extreme specialist.

    Uses inverse coefficient of variation of the 6 dimensions.
    """
    v = fp.to_vector()
    valid = [x for x in v if math.isfinite(x)]
    if len(valid) < 2:
        return 50.0
    arr = np.array(valid, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    if mean <= 0:
        return 50.0
    cv = std / mean
    # CV of 0 = perfectly balanced = 100, CV of 0.5+ = very unbalanced = 0
    return round(max(0.0, min(100.0, (1.0 - cv / 0.5) * 100.0)), 1)


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

    def t_basic_fingerprint():
        data = {
            "session_id": "test-001",
            "driver_name": "TestDriver",
            "pace_pct": 85.0,
            "consistency_pct": 90.0,
            "robustness_pct": 70.0,
            "execution_pct": 80.0,
            "pace_fade_pct": 2.0,
            "concentration_index": 88.0,
        }
        fp = compute_fingerprint(data)
        assert fp.raw_pace == 85.0
        assert fp.consistency == 90.0
        assert fp.technical_skill == 80.0
        assert 0 <= fp.overall_rating <= 100
        assert 0 <= fp.balance_score <= 100

    _test("basic_fingerprint", t_basic_fingerprint)

    def t_default_values():
        fp = compute_fingerprint({})
        assert fp.raw_pace == 50.0  # default
        assert 0 <= fp.overall_rating <= 100  # valid range
        # Most dimensions default to 50, tyre_mgmt defaults to 100 (0% fade)
        assert fp.consistency == 50.0

    _test("default_values", t_default_values)

    def t_clamping():
        data = {
            "pace_pct": 150.0,
            "consistency_pct": -20.0,
            "concentration_index": 200.0,
        }
        fp = compute_fingerprint(data)
        assert fp.raw_pace == 100.0
        assert fp.consistency == 0.0
        assert fp.mental_fortitude == 100.0

    _test("clamping", t_clamping)

    def t_comparison():
        fp1 = compute_fingerprint({"pace_pct": 90, "consistency_pct": 80,
                                    "execution_pct": 85, "driver_name": "A"})
        fp2 = compute_fingerprint({"pace_pct": 70, "consistency_pct": 95,
                                    "execution_pct": 60, "driver_name": "B"})
        result = compare_fingerprints(fp1, fp2)
        assert "deltas" in result
        assert "similarity_pct" in result
        assert "Raw Pace" in result["advantages_1"]  # A has more pace
        assert "Consistency" in result["advantages_2"]  # B has more consistency

    _test("comparison", t_comparison)

    def t_evolution():
        fps = [
            compute_fingerprint({"pace_pct": 60 + i * 5, "session_id": f"s{i}"})
            for i in range(5)
        ]
        evo = compute_evolution(fps)
        assert evo["overall_trend"] > 0  # improving
        assert "trends" in evo
        assert evo["trends"]["Raw Pace"] > 0

    _test("evolution", t_evolution)

    def t_balance_perfectly_balanced():
        data = {"pace_pct": 80, "consistency_pct": 80, "robustness_pct": 80,
                "execution_pct": 80, "pace_fade_pct": 2, "concentration_index": 80}
        fp = compute_fingerprint(data)
        assert fp.balance_score > 80  # should be high

    _test("balance_perfectly_balanced", t_balance_perfectly_balanced)

    def t_balance_specialist():
        data = {"pace_pct": 100, "consistency_pct": 20, "robustness_pct": 20,
                "execution_pct": 20, "pace_fade_pct": 8, "concentration_index": 20}
        fp = compute_fingerprint(data)
        assert fp.balance_score < 50  # should be low for specialist

    _test("balance_specialist", t_balance_specialist)

    def t_serialization():
        fp = compute_fingerprint({"pace_pct": 85, "session_id": "t1"})
        d = fp.to_dict()
        assert "dimensions" in d
        assert "vector" in d
        assert len(d["vector"]) == 6
        assert "dimension_names" in d

    _test("serialization", t_serialization)

    def t_deterministic():
        data = {"pace_pct": 75, "consistency_pct": 80}
        fp1 = compute_fingerprint(data)
        fp2 = compute_fingerprint(data)
        assert fp1.to_dict() == fp2.to_dict()

    _test("deterministic", t_deterministic)

    def t_nan_inputs():
        data = {"pace_pct": float("nan"), "consistency_pct": None}
        fp = compute_fingerprint(data)
        assert math.isfinite(fp.overall_rating)
        assert 0 <= fp.overall_rating <= 100

    _test("nan_inputs", t_nan_inputs)

    # Summary
    total = len(passed) + len(failed)
    print(f"\nPerformance Fingerprint Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
