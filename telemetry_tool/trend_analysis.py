"""
trend_analysis.py
-----------------
Multi-session pace trend analysis: polynomial fitting with bootstrap
confidence intervals and plateau detection.

Public API
~~~~~~~~~~
``compute_multi_session_trend(sessions)``
    Fit polynomial trend to pace over time, with confidence intervals.

``detect_plateau(trend, window=5)``
    Detect if the driver has stopped improving (plateau).
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_multi_session_trend(
    sessions: list[dict[str, Any]],
    *,
    degree: int = 2,
    n_bootstrap: int = 100,
) -> dict[str, Any]:
    """
    Fit a polynomial trend to session pace over time.

    Parameters
    ----------
    sessions : list[dict]
        Each dict must have: 'session_date' (ISO str or ordinal),
        'best_lap_time_s' (float). Optionally: 'total_score', 'session_id'.
    degree : int
        Polynomial degree for fitting (default 2 = quadratic).
    n_bootstrap : int
        Number of bootstrap samples for confidence interval.

    Returns
    -------
    dict with keys:
        trend_points: list of {x, y_actual, y_fitted} points
        coefficients: polynomial coefficients
        r_squared: goodness of fit
        improvement_rate: pace improvement per session (s/session)
        confidence_band: {lower: [...], upper: [...]}
        plateau: dict from detect_plateau()
        sessions_count: int
    """
    if len(sessions) < 2:
        return {
            "trend_points": [],
            "coefficients": [],
            "r_squared": 0.0,
            "improvement_rate": 0.0,
            "confidence_band": {"lower": [], "upper": []},
            "plateau": {"is_plateau": False, "reason": "insufficient data"},
            "sessions_count": len(sessions),
        }

    # Sort by date
    sorted_sessions = sorted(sessions, key=lambda s: s.get("session_date", ""))

    # Convert to numerical x-axis (session index)
    xs = np.arange(len(sorted_sessions), dtype=float)
    ys = np.array([
        s.get("best_lap_time_s", float("nan"))
        for s in sorted_sessions
    ])

    # Filter NaN
    valid = np.isfinite(ys)
    if valid.sum() < 2:
        return {
            "trend_points": [],
            "coefficients": [],
            "r_squared": 0.0,
            "improvement_rate": 0.0,
            "confidence_band": {"lower": [], "upper": []},
            "plateau": {"is_plateau": False, "reason": "insufficient valid data"},
            "sessions_count": len(sessions),
        }

    xs_valid = xs[valid]
    ys_valid = ys[valid]

    # Fit polynomial
    deg = min(degree, len(xs_valid) - 1)
    coeffs = np.polyfit(xs_valid, ys_valid, deg)
    poly = np.poly1d(coeffs)
    y_fitted = poly(xs_valid)

    # R-squared
    ss_res = np.sum((ys_valid - y_fitted) ** 2)
    ss_tot = np.sum((ys_valid - np.mean(ys_valid)) ** 2)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Improvement rate (linear component: pace change per session)
    if len(xs_valid) >= 2:
        linear_coeffs = np.polyfit(xs_valid, ys_valid, 1)
        improvement_rate = -float(linear_coeffs[0])  # Negative slope = improvement
    else:
        improvement_rate = 0.0

    # Bootstrap confidence intervals
    np.random.seed(42)
    boot_fits = []
    for _ in range(n_bootstrap):
        idx = np.random.choice(len(xs_valid), size=len(xs_valid), replace=True)
        try:
            bc = np.polyfit(xs_valid[idx], ys_valid[idx], deg)
            boot_fits.append(np.poly1d(bc)(xs_valid))
        except (np.linalg.LinAlgError, ValueError):
            continue

    if boot_fits:
        all_boots = np.array(boot_fits)
        ci_lower = np.percentile(all_boots, 5, axis=0).tolist()
        ci_upper = np.percentile(all_boots, 95, axis=0).tolist()
    else:
        ci_lower = y_fitted.tolist()
        ci_upper = y_fitted.tolist()

    # Build trend points
    trend_points = []
    vi = 0
    for i, s in enumerate(sorted_sessions):
        if valid[i]:
            trend_points.append({
                "x": int(i),
                "session_date": s.get("session_date", ""),
                "session_id": s.get("session_id", ""),
                "y_actual": round(float(ys_valid[vi]), 3),
                "y_fitted": round(float(y_fitted[vi]), 3),
            })
            vi += 1

    # Plateau detection
    plateau = detect_plateau(ys_valid)

    return {
        "trend_points": trend_points,
        "coefficients": [round(float(c), 6) for c in coeffs],
        "r_squared": round(float(r_squared), 4),
        "improvement_rate": round(float(improvement_rate), 4),
        "confidence_band": {
            "lower": [round(v, 3) for v in ci_lower],
            "upper": [round(v, 3) for v in ci_upper],
        },
        "plateau": plateau,
        "sessions_count": len(sorted_sessions),
    }


def detect_plateau(
    pace_values: "np.ndarray | list[float]",
    window: int = 5,
    threshold_pct: float = 0.5,
) -> dict[str, Any]:
    """
    Detect if performance has plateaued.

    A plateau is declared when the last `window` sessions show
    less than `threshold_pct`% improvement in pace.

    Parameters
    ----------
    pace_values : array-like
        Chronologically ordered best lap times.
    window : int
        Number of recent sessions to analyze.
    threshold_pct : float
        Minimum improvement % to NOT be considered a plateau.

    Returns
    -------
    dict with: is_plateau (bool), reason (str), recent_improvement_pct (float)
    """
    arr = np.array(pace_values, dtype=float)
    arr = arr[np.isfinite(arr)]

    if len(arr) < window:
        return {
            "is_plateau": False,
            "reason": "insufficient data",
            "recent_improvement_pct": 0.0,
            "window": window,
        }

    recent = arr[-window:]
    # Improvement = (first - last) / first * 100
    if recent[0] > 0:
        improvement_pct = (recent[0] - recent[-1]) / recent[0] * 100.0
    else:
        improvement_pct = 0.0

    # Also check variance in recent window
    cv_pct = (float(np.std(recent, ddof=1)) / float(np.mean(recent)) * 100) if np.mean(recent) > 0 else 0

    is_plateau = abs(improvement_pct) < threshold_pct and cv_pct < 2.0

    if is_plateau:
        reason = f"Last {window} sessions show only {improvement_pct:.2f}% change (CV={cv_pct:.1f}%)"
    elif improvement_pct > 0:
        reason = f"Still improving: {improvement_pct:.2f}% over last {window} sessions"
    elif improvement_pct < -threshold_pct:
        reason = f"Pace declining: {improvement_pct:.2f}% over last {window} sessions"
    else:
        reason = f"Stable pace (CV={cv_pct:.1f}%)"

    return {
        "is_plateau": is_plateau,
        "reason": reason,
        "recent_improvement_pct": round(improvement_pct, 3),
        "window": window,
    }


# ── Inline tests ──────────────────────────────────────────────

def _run_tests() -> None:
    """Self-contained test suite."""
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # Test 1: improving driver
    def t_improving():
        sessions = [
            {"session_date": f"2024-01-{i+1:02d}", "best_lap_time_s": 65.0 - i * 0.5}
            for i in range(10)
        ]
        result = compute_multi_session_trend(sessions)
        assert result["improvement_rate"] > 0, "Should detect improvement"
        assert result["r_squared"] > 0.8
        assert result["sessions_count"] == 10
        assert len(result["trend_points"]) == 10

    _test("improving_driver", t_improving)

    # Test 2: plateau
    def t_plateau():
        sessions = [
            {"session_date": f"2024-01-{i+1:02d}", "best_lap_time_s": 60.0 + np.random.normal(0, 0.05)}
            for i in range(10)
        ]
        np.random.seed(42)
        result = compute_multi_session_trend(sessions)
        plateau = result["plateau"]
        assert plateau["is_plateau"] or abs(plateau["recent_improvement_pct"]) < 1.0

    _test("plateau_detection", t_plateau)

    # Test 3: empty / single session
    def t_few():
        result = compute_multi_session_trend([])
        assert result["sessions_count"] == 0
        result2 = compute_multi_session_trend([{"best_lap_time_s": 60.0}])
        assert result2["sessions_count"] == 1
        assert len(result2["trend_points"]) == 0

    _test("few_sessions", t_few)

    # Test 4: NaN values handled
    def t_nan():
        sessions = [
            {"session_date": "2024-01-01", "best_lap_time_s": 62.0},
            {"session_date": "2024-01-02", "best_lap_time_s": float("nan")},
            {"session_date": "2024-01-03", "best_lap_time_s": 61.0},
            {"session_date": "2024-01-04", "best_lap_time_s": 60.5},
        ]
        result = compute_multi_session_trend(sessions)
        assert len(result["trend_points"]) == 3  # NaN excluded

    _test("nan_handled", t_nan)

    # Test 5: confidence bands exist
    def t_ci():
        sessions = [
            {"session_date": f"2024-01-{i+1:02d}", "best_lap_time_s": 65.0 - i * 0.3}
            for i in range(8)
        ]
        result = compute_multi_session_trend(sessions)
        assert len(result["confidence_band"]["lower"]) > 0
        assert len(result["confidence_band"]["upper"]) > 0

    _test("confidence_bands", t_ci)

    # Test 6: detect_plateau directly
    def t_plateau_direct():
        # Flat data → plateau
        flat = [60.0, 60.1, 59.9, 60.0, 60.05]
        result = detect_plateau(flat, window=5, threshold_pct=0.5)
        assert result["is_plateau"]

        # Improving data → not plateau
        improving = [65.0, 64.0, 63.0, 62.0, 61.0]
        result2 = detect_plateau(improving, window=5, threshold_pct=0.5)
        assert not result2["is_plateau"]

    _test("plateau_direct", t_plateau_direct)

    # Test 7: declining performance
    def t_declining():
        sessions = [
            {"session_date": f"2024-01-{i+1:02d}", "best_lap_time_s": 60.0 + i * 0.5}
            for i in range(10)
        ]
        result = compute_multi_session_trend(sessions)
        assert result["improvement_rate"] < 0, "Should detect declining pace"

    _test("declining_pace", t_declining)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nTrend Analysis Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
