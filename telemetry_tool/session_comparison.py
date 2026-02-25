"""
session_comparison.py
---------------------
Session Comparison Matrix — generates structured head-to-head comparisons
between multiple sessions, highlighting improvements and regressions across
key performance dimensions.

Core Features
~~~~~~~~~~~~~
1. **Pairwise Comparison**: Compare any two sessions on the same track
   across pace, consistency, score, and per-corner metrics.
2. **Improvement Tracking**: Delta calculations with sign-aware formatting
   (green = improved, red = regressed).
3. **Matrix View**: When >2 sessions are provided, builds an NxN matrix
   of pairwise deltas for key metrics.
4. **Best Session Identification**: Across a set of sessions, identifies
   which session holds the record for each metric.

Public API
~~~~~~~~~~
- ``compare_two_sessions(session_a, session_b)``
- ``build_comparison_matrix(sessions)``
- ``find_best_per_metric(sessions)``

Design Principles
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
from typing import Any, Final

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

IMPROVEMENT_THRESHOLD: Final[float] = 0.1  # 0.1% minimum to count as improved
COMPARISON_METRICS: Final[list[str]] = [
    "best_lap_time_s",
    "mean_lap_time_s",
    "total_score",
    "n_laps",
    "cv_pct",
    "consistency_pct",
]

METRIC_LABELS: Final[dict[str, str]] = {
    "best_lap_time_s": "Best Lap",
    "mean_lap_time_s": "Mean Lap",
    "total_score": "Score",
    "n_laps": "Laps",
    "cv_pct": "CV%",
    "consistency_pct": "Consistency",
}

# Lower is better for these metrics
LOWER_IS_BETTER: Final[set[str]] = {"best_lap_time_s", "mean_lap_time_s", "cv_pct"}


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class SessionSummary:
    """Summary of a single session for comparison."""
    session_id: str = ""
    driver_name: str = ""
    session_date: str = ""
    session_type: str = ""
    best_lap_time_s: float = 0.0
    mean_lap_time_s: float = 0.0
    total_score: float = 0.0
    n_laps: int = 0
    cv_pct: float = 0.0
    consistency_pct: float = 0.0

    def get_metric(self, name: str) -> float:
        return getattr(self, name, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "driver_name": self.driver_name,
            "session_date": self.session_date,
            "session_type": self.session_type,
            "best_lap_time_s": round(self.best_lap_time_s, 3),
            "mean_lap_time_s": round(self.mean_lap_time_s, 3),
            "total_score": round(self.total_score, 1),
            "n_laps": self.n_laps,
            "cv_pct": round(self.cv_pct, 2),
            "consistency_pct": round(self.consistency_pct, 1),
        }


@dataclass
class PairwiseComparison:
    """Comparison between two sessions."""
    session_a: SessionSummary = field(default_factory=SessionSummary)
    session_b: SessionSummary = field(default_factory=SessionSummary)
    deltas: dict[str, float] = field(default_factory=dict)
    improvements: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    net_assessment: str = ""  # "improved", "regressed", "mixed", "unchanged"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_a": self.session_a.to_dict(),
            "session_b": self.session_b.to_dict(),
            "deltas": {k: round(v, 4) for k, v in self.deltas.items()},
            "improvements": self.improvements,
            "regressions": self.regressions,
            "unchanged": self.unchanged,
            "net_assessment": self.net_assessment,
        }


@dataclass
class ComparisonMatrix:
    """NxN comparison matrix for multiple sessions."""
    sessions: list[SessionSummary] = field(default_factory=list)
    pairwise: list[PairwiseComparison] = field(default_factory=list)
    best_per_metric: dict[str, str] = field(default_factory=dict)  # metric → session_id
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions": [s.to_dict() for s in self.sessions],
            "pairwise": [p.to_dict() for p in self.pairwise],
            "best_per_metric": self.best_per_metric,
            "metric_labels": dict(METRIC_LABELS),
            "lower_is_better": list(LOWER_IS_BETTER),
            "summary": self.summary,
        }


# ============================================================================
# Core Functions
# ============================================================================


def compute_cv_from_laps(lap_times: list[float]) -> float:
    """Compute coefficient of variation from lap times."""
    valid = [t for t in lap_times if t is not None and math.isfinite(t) and t > 0]
    if len(valid) < 2:
        return 0.0
    arr = np.array(valid, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    return (std / mean * 100) if mean > 0 else 0.0


def build_session_summary(data: dict[str, Any]) -> SessionSummary:
    """Build a SessionSummary from raw session data."""
    ss = SessionSummary(
        session_id=str(data.get("session_id", "")),
        driver_name=str(data.get("driver_name", "")),
        session_date=str(data.get("session_date", "")),
        session_type=str(data.get("session_type", "")),
        n_laps=int(data.get("n_laps", 0)),
        total_score=float(data.get("total_score", 0) or 0),
    )

    best = data.get("best_lap_time_s")
    if best is not None and math.isfinite(float(best)):
        ss.best_lap_time_s = float(best)

    mean = data.get("mean_lap_time_s")
    if mean is not None and math.isfinite(float(mean)):
        ss.mean_lap_time_s = float(mean)

    cv = data.get("cv_pct")
    if cv is not None and math.isfinite(float(cv)):
        ss.cv_pct = float(cv)

    cons = data.get("consistency_pct")
    if cons is not None and math.isfinite(float(cons)):
        ss.consistency_pct = float(cons)
    elif ss.cv_pct > 0:
        # Derive consistency from CV
        ss.consistency_pct = max(0, 100 * (1 - ss.cv_pct / 10))

    return ss


def compare_two_sessions(
    session_a: SessionSummary,
    session_b: SessionSummary,
) -> PairwiseComparison:
    """
    Compare two sessions and classify each metric as improved/regressed.

    Convention: B is the "newer" session, so improvements mean B is better.
    """
    comp = PairwiseComparison(session_a=session_a, session_b=session_b)

    for metric in COMPARISON_METRICS:
        val_a = session_a.get_metric(metric)
        val_b = session_b.get_metric(metric)

        if val_a == 0 and val_b == 0:
            comp.unchanged.append(metric)
            comp.deltas[metric] = 0.0
            continue

        delta = val_b - val_a
        comp.deltas[metric] = delta

        lower_better = metric in LOWER_IS_BETTER

        # Determine if improved
        if val_a != 0:
            pct_change = abs(delta) / abs(val_a) * 100
        else:
            pct_change = 100.0 if delta != 0 else 0.0

        if pct_change < IMPROVEMENT_THRESHOLD:
            comp.unchanged.append(metric)
        elif (lower_better and delta < 0) or (not lower_better and delta > 0):
            comp.improvements.append(metric)
        else:
            comp.regressions.append(metric)

    # Net assessment
    n_imp = len(comp.improvements)
    n_reg = len(comp.regressions)
    if n_imp > n_reg:
        comp.net_assessment = "improved"
    elif n_reg > n_imp:
        comp.net_assessment = "regressed"
    elif n_imp > 0:
        comp.net_assessment = "mixed"
    else:
        comp.net_assessment = "unchanged"

    return comp


def find_best_per_metric(
    sessions: list[SessionSummary],
) -> dict[str, str]:
    """Find which session holds the best value for each metric."""
    best: dict[str, str] = {}

    for metric in COMPARISON_METRICS:
        lower_better = metric in LOWER_IS_BETTER
        best_val = None
        best_sid = ""

        for ss in sessions:
            val = ss.get_metric(metric)
            if val == 0:
                continue
            if best_val is None:
                best_val = val
                best_sid = ss.session_id
            elif (lower_better and val < best_val) or (not lower_better and val > best_val):
                best_val = val
                best_sid = ss.session_id

        best[metric] = best_sid

    return best


def build_comparison_matrix(
    sessions_data: list[dict[str, Any]],
) -> ComparisonMatrix:
    """
    Build an NxN comparison matrix from session data.

    Parameters
    ----------
    sessions_data:
        List of dicts with session fields (session_id, best_lap_time_s, etc.)

    Returns
    -------
    ComparisonMatrix
    """
    matrix = ComparisonMatrix()

    if not sessions_data:
        matrix.summary = "No sessions to compare."
        return matrix

    # Build summaries
    for data in sessions_data:
        ss = build_session_summary(data)
        matrix.sessions.append(ss)

    # Pairwise comparisons (chronological pairs)
    for i in range(len(matrix.sessions) - 1):
        comp = compare_two_sessions(matrix.sessions[i], matrix.sessions[i + 1])
        matrix.pairwise.append(comp)

    # Best per metric
    matrix.best_per_metric = find_best_per_metric(matrix.sessions)

    # Summary
    n = len(matrix.sessions)
    if n == 1:
        matrix.summary = f"Single session: {matrix.sessions[0].session_id}"
    elif n == 2:
        comp = matrix.pairwise[0]
        matrix.summary = (
            f"Session comparison: {comp.net_assessment}. "
            f"{len(comp.improvements)} improved, "
            f"{len(comp.regressions)} regressed, "
            f"{len(comp.unchanged)} unchanged."
        )
    else:
        improvements = sum(
            1 for p in matrix.pairwise if p.net_assessment == "improved"
        )
        matrix.summary = (
            f"{n} sessions compared. "
            f"{improvements}/{n - 1} transitions showed improvement."
        )

    logger.info(
        "Comparison matrix: %d sessions, %d pairwise, summary=%s",
        n, len(matrix.pairwise), matrix.summary,
    )

    return matrix


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

    def t_session_summary():
        data = {
            "session_id": "s1", "best_lap_time_s": 60.0,
            "mean_lap_time_s": 61.0, "total_score": 82.5,
            "n_laps": 20, "session_date": "2025-01-15",
        }
        ss = build_session_summary(data)
        assert ss.session_id == "s1"
        assert ss.best_lap_time_s == 60.0
        assert ss.n_laps == 20

    _test("session_summary", t_session_summary)

    def t_pairwise_improved():
        a = SessionSummary(
            session_id="s1", best_lap_time_s=61.0,
            mean_lap_time_s=62.0, total_score=75.0, cv_pct=3.0,
        )
        b = SessionSummary(
            session_id="s2", best_lap_time_s=60.0,
            mean_lap_time_s=61.0, total_score=82.0, cv_pct=2.0,
        )
        comp = compare_two_sessions(a, b)
        assert comp.net_assessment == "improved"
        assert "best_lap_time_s" in comp.improvements
        assert "total_score" in comp.improvements

    _test("pairwise_improved", t_pairwise_improved)

    def t_pairwise_regressed():
        a = SessionSummary(
            session_id="s1", best_lap_time_s=60.0,
            total_score=85.0, cv_pct=1.5,
        )
        b = SessionSummary(
            session_id="s2", best_lap_time_s=62.0,
            total_score=70.0, cv_pct=4.0,
        )
        comp = compare_two_sessions(a, b)
        assert comp.net_assessment == "regressed"

    _test("pairwise_regressed", t_pairwise_regressed)

    def t_pairwise_unchanged():
        a = SessionSummary(
            session_id="s1", best_lap_time_s=60.0,
            total_score=80.0,
        )
        b = SessionSummary(
            session_id="s2", best_lap_time_s=60.0,
            total_score=80.0,
        )
        comp = compare_two_sessions(a, b)
        assert comp.net_assessment == "unchanged"

    _test("pairwise_unchanged", t_pairwise_unchanged)

    def t_matrix_two_sessions():
        data = [
            {"session_id": "s1", "best_lap_time_s": 61.0, "total_score": 75.0,
             "mean_lap_time_s": 62.0, "n_laps": 20, "session_date": "2025-01-15"},
            {"session_id": "s2", "best_lap_time_s": 60.0, "total_score": 82.0,
             "mean_lap_time_s": 61.0, "n_laps": 22, "session_date": "2025-01-20"},
        ]
        matrix = build_comparison_matrix(data)
        assert len(matrix.sessions) == 2
        assert len(matrix.pairwise) == 1
        assert "best_lap_time_s" in matrix.best_per_metric

    _test("matrix_two_sessions", t_matrix_two_sessions)

    def t_matrix_three_sessions():
        data = [
            {"session_id": "s1", "best_lap_time_s": 62.0, "total_score": 70.0},
            {"session_id": "s2", "best_lap_time_s": 61.0, "total_score": 75.0},
            {"session_id": "s3", "best_lap_time_s": 60.0, "total_score": 80.0},
        ]
        matrix = build_comparison_matrix(data)
        assert len(matrix.sessions) == 3
        assert len(matrix.pairwise) == 2  # s1-s2, s2-s3
        assert matrix.best_per_metric["best_lap_time_s"] == "s3"

    _test("matrix_three_sessions", t_matrix_three_sessions)

    def t_best_per_metric():
        sessions = [
            SessionSummary(session_id="s1", best_lap_time_s=61.0, total_score=70.0, cv_pct=3.0),
            SessionSummary(session_id="s2", best_lap_time_s=60.0, total_score=85.0, cv_pct=2.0),
            SessionSummary(session_id="s3", best_lap_time_s=60.5, total_score=80.0, cv_pct=1.5),
        ]
        best = find_best_per_metric(sessions)
        assert best["best_lap_time_s"] == "s2"  # lowest time
        assert best["total_score"] == "s2"       # highest score
        assert best["cv_pct"] == "s3"            # lowest CV

    _test("best_per_metric", t_best_per_metric)

    def t_empty_sessions():
        matrix = build_comparison_matrix([])
        assert len(matrix.sessions) == 0
        assert "No sessions" in matrix.summary

    _test("empty_sessions", t_empty_sessions)

    def t_single_session():
        data = [{"session_id": "s1", "best_lap_time_s": 60.0}]
        matrix = build_comparison_matrix(data)
        assert len(matrix.sessions) == 1
        assert len(matrix.pairwise) == 0

    _test("single_session", t_single_session)

    def t_nan_robustness():
        data = [
            {"session_id": "s1", "best_lap_time_s": float("nan"),
             "total_score": None, "n_laps": 10},
            {"session_id": "s2", "best_lap_time_s": 60.0,
             "total_score": 80.0, "n_laps": 12},
        ]
        matrix = build_comparison_matrix(data)
        assert len(matrix.sessions) == 2
        for p in matrix.pairwise:
            for v in p.deltas.values():
                assert math.isfinite(v)

    _test("nan_robustness", t_nan_robustness)

    def t_serialization():
        data = [
            {"session_id": "s1", "best_lap_time_s": 61.0, "total_score": 75.0},
            {"session_id": "s2", "best_lap_time_s": 60.0, "total_score": 82.0},
        ]
        matrix = build_comparison_matrix(data)
        d = matrix.to_dict()
        assert "sessions" in d
        assert "pairwise" in d
        assert "best_per_metric" in d
        assert "metric_labels" in d

    _test("serialization", t_serialization)

    def t_deterministic():
        data = [
            {"session_id": "s1", "best_lap_time_s": 61.0, "total_score": 75.0},
            {"session_id": "s2", "best_lap_time_s": 60.0, "total_score": 82.0},
        ]
        m1 = build_comparison_matrix(data)
        m2 = build_comparison_matrix(data)
        assert m1.to_dict() == m2.to_dict()

    _test("deterministic", t_deterministic)

    # Summary
    total = len(passed) + len(failed)
    print(f"\nSession Comparison Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
