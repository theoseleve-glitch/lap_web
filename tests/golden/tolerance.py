"""
tolerance.py
------------
Tolerance comparison helpers for golden dataset regression tests.

Supports exact, absolute-range, relative-range, and existence checks.
"""
from __future__ import annotations

from typing import Any


class ToleranceMismatch(AssertionError):
    """Raised when a value falls outside its tolerance band."""


def tolerance_compare(
    actual: Any,
    expected: Any,
    tol_spec: dict[str, Any],
    field_name: str = "",
) -> None:
    """Compare actual vs expected using the tolerance spec.

    tol_spec keys:
        mode: "exact" | "range" | "relative" | "exists"
        abs:  absolute tolerance (for "range" mode)
        rel:  relative tolerance fraction (for "relative" mode)

    Raises ToleranceMismatch on failure.
    """
    mode = tol_spec.get("mode", "exact")
    label = field_name or "value"

    if mode == "exact":
        if actual != expected:
            raise ToleranceMismatch(
                f"{label}: expected exactly {expected!r}, got {actual!r}"
            )

    elif mode == "range":
        if actual is None or expected is None:
            return  # skip if either side missing
        abs_tol = tol_spec.get("abs", 0)
        lo = expected - abs_tol
        hi = expected + abs_tol
        if not (lo <= actual <= hi):
            raise ToleranceMismatch(
                f"{label}: expected {expected} +/- {abs_tol}, got {actual} "
                f"(range [{lo}, {hi}])"
            )

    elif mode == "relative":
        if actual is None or expected is None:
            return
        rel_tol = tol_spec.get("rel", 0.05)
        if expected == 0:
            if actual != 0:
                raise ToleranceMismatch(
                    f"{label}: expected 0, got {actual}"
                )
            return
        ratio = abs(actual - expected) / abs(expected)
        if ratio > rel_tol:
            raise ToleranceMismatch(
                f"{label}: expected {expected} +/- {rel_tol*100:.1f}%, "
                f"got {actual} (ratio {ratio:.4f})"
            )

    elif mode == "exists":
        if not actual:
            raise ToleranceMismatch(f"{label}: expected truthy, got {actual!r}")

    else:
        raise ValueError(f"Unknown tolerance mode: {mode!r}")


def compare_snapshot(
    actual: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[str]:
    """Compare an actual result dict against a saved snapshot.

    Uses the 'tolerances' key in the snapshot to determine per-field rules.
    Returns a list of mismatch descriptions (empty = all passed).
    """
    tolerances = snapshot.get("tolerances", {})
    errors: list[str] = []

    for key, tol_spec in tolerances.items():
        actual_val = actual.get(key)
        expected_val = snapshot.get(key)
        try:
            tolerance_compare(actual_val, expected_val, tol_spec, field_name=key)
        except ToleranceMismatch as e:
            errors.append(str(e))

    return errors
