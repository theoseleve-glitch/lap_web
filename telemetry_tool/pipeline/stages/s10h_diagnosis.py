"""
Stage S10h — Corner diagnosis (auto-detected corners, honesty-gated)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs the corner-diagnosis classifier (``coaching.corner_diagnosis.classify_all_corners``)
against a session's corners, passing the REAL ``curvature_profile`` so the classifier's
yaw-residual confidence gate (Phase-2 Task 1) can actually do its job.

Previously this classifier only ran for operator-drawn ``user_corners`` (a rare path),
which meant most customers never got a diagnosis at all. This stage lets the orchestrator
run it on the AUTO-detected ``corners`` (from :func:`pipeline.stages.s07_resample.
run_corner_detection`) on EVERY session instead — falling back to those only when no
operator-drawn corners exist.

Key-shape note
~~~~~~~~~~~~~~
Auto-detected corners (``corner_detection.detect_corners``) are keyed
``corner_id`` / ``s_start`` / ``s_apex`` / ``s_end`` / ``direction`` — NOT the
classifier's ``corner_index`` / ``s_entry`` / ``s_apex`` / ``s_exit`` contract (that
shape matches the ``user_corners`` DB table columns instead, which is why the operator
path already worked). :func:`run_corner_diagnosis` shims the auto-corner keys onto the
classifier's contract at the call site — the classifier itself is NOT changed.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _shim_auto_corner(corner: dict[str, Any]) -> dict[str, Any]:
    """Map an auto-detected corner dict onto the classifier's expected keys.

    Corners that already carry the classifier's native keys (``corner_index`` /
    ``s_entry`` / ``s_exit`` — e.g. operator-drawn ``user_corners`` rows) pass through
    unchanged. Auto-detected corners (``corner_id`` / ``s_start`` / ``s_end``) are
    mapped onto those names; ``s_apex`` is already shared by both shapes.
    """
    if "corner_index" in corner and "s_entry" in corner and "s_exit" in corner:
        return corner

    shimmed = dict(corner)
    if "corner_index" not in shimmed and "corner_id" in shimmed:
        shimmed["corner_index"] = shimmed["corner_id"]
    if "s_entry" not in shimmed and "s_start" in shimmed:
        shimmed["s_entry"] = shimmed["s_start"]
    if "s_exit" not in shimmed and "s_end" in shimmed:
        shimmed["s_exit"] = shimmed["s_end"]
    return shimmed


def run_corner_diagnosis(
    corners: list[dict[str, Any]],
    resampled_laps: dict[int, pd.DataFrame],
    curvature_profile: Optional[pd.DataFrame],
    theoretical_lap: Optional[pd.DataFrame],
    vehicle_class: str,
    valid_lap_numbers: list[int],
    mrp_events: Optional[dict[int, dict]] = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Run the corner-diagnosis classifier against *corners* (auto or operator-drawn).

    Thin, pure wrapper around ``coaching.corner_diagnosis.classify_all_corners``:
    shims auto-detected corner keys onto the classifier's
    ``corner_index``/``s_entry``/``s_apex``/``s_exit`` contract, then delegates.
    Does NOT modify the classifier's contract.

    Parameters
    ----------
    corners : list[dict]
        Corner descriptors — either auto-detected (``run_corner_detection`` output)
        or operator-drawn (``user_corners`` DB rows already in the classifier's
        native shape).
    resampled_laps : dict[int, pd.DataFrame]
        Per-lap resampled telemetry.
    curvature_profile : pd.DataFrame or None
        The session's real curvature profile (``summary["curvature_profile"]``).
        Passing the real profile (instead of ``None``) is what lets the classifier's
        yaw-residual labels score "high" confidence instead of defaulting to "low".
    theoretical_lap : pd.DataFrame or None
        Theoretical/optimal lap, used for entry/apex/exit speed deltas.
    vehicle_class : str
        Vehicle class key for threshold lookup (e.g. "car", "kart").
    valid_lap_numbers : list[int]
        Laps to diagnose (excludes invalid/excluded laps).
    mrp_events : dict[int, dict] or None
        Minimum-radius-point events, keyed by corner, if available.

    Returns
    -------
    dict
        ``{lap_num_str: {corner_key_str: {"label": str|None, "confidence": "high"|"low"}}}``
        (the P2-Task-1 shape), or ``{}`` if there is nothing to diagnose (no corners,
        no laps, or no valid lap numbers) instead of raising.
    """
    if not corners or not resampled_laps or not valid_lap_numbers:
        return {}

    from coaching.corner_diagnosis import classify_all_corners

    shimmed_corners = [_shim_auto_corner(c) for c in corners]

    return classify_all_corners(
        resampled_laps,
        theoretical_lap,
        shimmed_corners,
        vehicle_class,
        valid_lap_numbers,
        curvature_profile=curvature_profile,
        mrp_events=mrp_events,
    )
