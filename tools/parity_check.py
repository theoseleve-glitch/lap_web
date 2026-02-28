"""
Parity checker — compares webapp API outputs against old tool CLI baselines.

Supports type-aware comparison with configurable tolerances per field
category (time, speed, score, GPS, percentage). Produces a diff report
listing each comparison path with PASS/FAIL and delta details.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Import normalize_dict from the sibling normalize module
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import normalize_dict  # noqa: E402

# ---------------------------------------------------------------------------
# Tolerance presets keyed by field category
# ---------------------------------------------------------------------------
TOLERANCES = {
    "lap_time": 0.001,      # seconds — sub-millisecond
    "speed": 0.01,          # m/s
    "score": 0.5,           # scoring points (out of 25)
    "gps": 0.0001,          # ~11 m at equator
    "percentage": 0.1,      # percentage points
    "default": 0.0001,      # catch-all for uncategorised numerics
}

# ---------------------------------------------------------------------------
# Classification keywords → tolerance category
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS = {
    "lap_time": ("time", "duration", "lap_time", "sector_time"),
    "speed": ("speed", "velocity", "v_max", "v_min", "v_avg"),
    "score": ("score", "pace", "consistency", "execution", "robustness", "total"),
    "gps": ("lat", "lon", "latitude", "longitude", "gps"),
    "percentage": ("percent", "pct", "ratio"),
}


# ---------------------------------------------------------------------------
# ParityResult dataclass
# ---------------------------------------------------------------------------
@dataclass
class ParityResult:
    """Result of comparing a single value at a given JSON path."""

    path: str
    passed: bool
    baseline_value: Any
    webapp_value: Any
    tolerance: Optional[float]
    delta: Optional[float]
    message: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _classify_tolerance(path: str) -> float:
    """Auto-pick a tolerance based on the JSON key path.

    Scans the path string for category keywords and returns the
    corresponding tolerance. Falls back to TOLERANCES["default"].
    """
    lower = path.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return TOLERANCES[category]
    return TOLERANCES["default"]


def _is_numeric(v: Any) -> bool:
    """Return True for int or float (but not bool)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Core comparison functions
# ---------------------------------------------------------------------------
def compare_values(
    baseline: Any,
    webapp: Any,
    path: str,
    tolerance: Optional[float] = None,
) -> ParityResult:
    """Type-aware comparison of two values at a given JSON path.

    Rules:
    - Both None            -> pass
    - One None, other not  -> fail
    - Numeric              -> abs(delta) <= tolerance
    - String               -> exact match
    - List                 -> length check then element-wise
    - Dict                 -> delegate to compare_dicts (return aggregate)
    - Mismatched types     -> fail
    """
    # Resolve tolerance (explicit > auto-classified)
    tol = tolerance if tolerance is not None else _classify_tolerance(path)

    # --- Both None ---
    if baseline is None and webapp is None:
        return ParityResult(
            path=path,
            passed=True,
            baseline_value=None,
            webapp_value=None,
            tolerance=None,
            delta=None,
            message="both None",
        )

    # --- One None ---
    if baseline is None or webapp is None:
        return ParityResult(
            path=path,
            passed=False,
            baseline_value=baseline,
            webapp_value=webapp,
            tolerance=None,
            delta=None,
            message=f"None mismatch: baseline={baseline!r}, webapp={webapp!r}",
        )

    # --- Numeric ---
    if _is_numeric(baseline) and _is_numeric(webapp):
        delta = abs(float(baseline) - float(webapp))
        passed = delta <= tol
        return ParityResult(
            path=path,
            passed=passed,
            baseline_value=baseline,
            webapp_value=webapp,
            tolerance=tol,
            delta=delta,
            message="OK" if passed else f"delta {delta:.6f} > tolerance {tol}",
        )

    # --- String ---
    if isinstance(baseline, str) and isinstance(webapp, str):
        passed = baseline == webapp
        return ParityResult(
            path=path,
            passed=passed,
            baseline_value=baseline,
            webapp_value=webapp,
            tolerance=None,
            delta=None,
            message="OK" if passed else f"string mismatch: {baseline!r} != {webapp!r}",
        )

    # --- List ---
    if isinstance(baseline, list) and isinstance(webapp, list):
        if len(baseline) != len(webapp):
            return ParityResult(
                path=path,
                passed=False,
                baseline_value=baseline,
                webapp_value=webapp,
                tolerance=None,
                delta=None,
                message=f"list length mismatch: {len(baseline)} vs {len(webapp)}",
            )
        # Element-wise — return single aggregate result for the list
        all_pass = True
        child_messages = []
        for i, (bv, wv) in enumerate(zip(baseline, webapp)):
            child = compare_values(bv, wv, f"{path}[{i}]", tolerance=tolerance)
            if not child.passed:
                all_pass = False
                child_messages.append(child.message)
        return ParityResult(
            path=path,
            passed=all_pass,
            baseline_value=baseline,
            webapp_value=webapp,
            tolerance=tol,
            delta=None,
            message="OK" if all_pass else "; ".join(child_messages),
        )

    # --- Dict ---
    if isinstance(baseline, dict) and isinstance(webapp, dict):
        results = compare_dicts(baseline, webapp, tolerance=tolerance, prefix=path)
        all_pass = all(r.passed for r in results)
        fail_msgs = [r.message for r in results if not r.passed]
        return ParityResult(
            path=path,
            passed=all_pass,
            baseline_value=baseline,
            webapp_value=webapp,
            tolerance=None,
            delta=None,
            message="OK" if all_pass else "; ".join(fail_msgs),
        )

    # --- Bool ---
    if isinstance(baseline, bool) and isinstance(webapp, bool):
        passed = baseline == webapp
        return ParityResult(
            path=path,
            passed=passed,
            baseline_value=baseline,
            webapp_value=webapp,
            tolerance=None,
            delta=None,
            message="OK" if passed else f"bool mismatch: {baseline} != {webapp}",
        )

    # --- Type mismatch ---
    return ParityResult(
        path=path,
        passed=False,
        baseline_value=baseline,
        webapp_value=webapp,
        tolerance=None,
        delta=None,
        message=f"type mismatch: {type(baseline).__name__} vs {type(webapp).__name__}",
    )


def compare_dicts(
    baseline: dict,
    webapp: dict,
    tolerance: Optional[float] = None,
    prefix: str = "",
) -> list[ParityResult]:
    """Recursively compare two dicts, returning a ParityResult per leaf.

    - Extra keys in webapp are OK (ignored).
    - Missing keys in webapp are FAIL.
    """
    results: list[ParityResult] = []

    for key in baseline:
        path = f"{prefix}.{key}" if prefix else key
        if key not in webapp:
            results.append(
                ParityResult(
                    path=path,
                    passed=False,
                    baseline_value=baseline[key],
                    webapp_value=None,
                    tolerance=None,
                    delta=None,
                    message=f"missing key in webapp: {path}",
                )
            )
            continue

        bv = baseline[key]
        wv = webapp[key]

        # Recurse into nested dicts
        if isinstance(bv, dict) and isinstance(wv, dict):
            results.extend(compare_dicts(bv, wv, tolerance=tolerance, prefix=path))
        else:
            results.append(compare_values(bv, wv, path, tolerance=tolerance))

    return results


# ---------------------------------------------------------------------------
# Diff report formatting
# ---------------------------------------------------------------------------
def _format_report(results: list[ParityResult]) -> str:
    """Generate a human-readable diff report."""
    lines = []
    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count

    lines.append("=" * 72)
    lines.append("PARITY CHECK REPORT")
    lines.append("=" * 72)
    lines.append(f"Total checks: {len(results)}")
    lines.append(f"Passed: {passed_count}")
    lines.append(f"Failed: {failed_count}")
    lines.append(f"Result: {'PASS' if failed_count == 0 else 'FAIL'}")
    lines.append("-" * 72)

    if failed_count > 0:
        lines.append("")
        lines.append("FAILURES:")
        lines.append("")
        for r in results:
            if not r.passed:
                lines.append(f"  FAIL  {r.path}")
                lines.append(f"        baseline: {r.baseline_value!r}")
                lines.append(f"        webapp:   {r.webapp_value!r}")
                if r.delta is not None:
                    lines.append(f"        delta:    {r.delta:.6f}")
                if r.tolerance is not None:
                    lines.append(f"        tol:      {r.tolerance}")
                lines.append(f"        reason:   {r.message}")
                lines.append("")

    lines.append("-" * 72)
    lines.append("")
    lines.append("ALL CHECKS:")
    lines.append("")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"  [{status}] {r.path}: {r.message}")

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level parity check runner
# ---------------------------------------------------------------------------
def run_parity_check(
    baseline_path: str,
    webapp_path: Optional[str] = None,
    webapp_data: Optional[dict] = None,
    output_path: Optional[str] = None,
    tolerance: Optional[float] = None,
) -> tuple[bool, list[ParityResult]]:
    """Load JSON files, normalize both, compare, optionally write diff report.

    Parameters
    ----------
    baseline_path : str
        Path to the baseline (old tool) JSON file.
    webapp_path : str, optional
        Path to the webapp API JSON file. One of webapp_path or
        webapp_data must be provided.
    webapp_data : dict, optional
        Already-loaded webapp data dict. Mutually exclusive with webapp_path.
    output_path : str, optional
        If given, write a diff report to this path.
    tolerance : float, optional
        Global tolerance override. If None, auto-classification is used.

    Returns
    -------
    tuple[bool, list[ParityResult]]
        (all_passed, list_of_results)
    """
    # --- Load baseline ---
    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline_raw = json.load(f)

    # --- Load webapp ---
    if webapp_data is not None:
        webapp_raw = webapp_data
    elif webapp_path is not None:
        with open(webapp_path, "r", encoding="utf-8") as f:
            webapp_raw = json.load(f)
    else:
        raise ValueError("Either webapp_path or webapp_data must be provided")

    # --- Normalize both ---
    baseline = normalize_dict(baseline_raw) if isinstance(baseline_raw, dict) else baseline_raw
    webapp = normalize_dict(webapp_raw) if isinstance(webapp_raw, dict) else webapp_raw

    # --- Compare ---
    if isinstance(baseline, dict) and isinstance(webapp, dict):
        results = compare_dicts(baseline, webapp, tolerance=tolerance)
    else:
        results = [compare_values(baseline, webapp, "<root>", tolerance=tolerance)]

    all_passed = all(r.passed for r in results)

    # --- Write diff report ---
    if output_path is not None:
        report = _format_report(results)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

    return all_passed, results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parity checker: compare webapp API output against CLI baseline"
    )
    parser.add_argument(
        "--baseline",
        required=True,
        help="Path to baseline JSON file (old tool output)",
    )
    parser.add_argument(
        "--webapp",
        required=True,
        help="Path to webapp JSON file (API output)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write the diff report (optional)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=None,
        help="Global tolerance override (optional)",
    )

    args = parser.parse_args()
    passed, results = run_parity_check(
        baseline_path=args.baseline,
        webapp_path=args.webapp,
        output_path=args.output,
        tolerance=args.tolerance,
    )

    # Print summary to stdout
    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count
    print(f"Parity check: {passed_count} passed, {failed_count} failed")

    if not passed:
        print("\nFailed checks:")
        for r in results:
            if not r.passed:
                print(f"  {r.path}: {r.message}")
        sys.exit(1)
    else:
        print("All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
