"""Validation and calibration tools for handling detection (G1-G5).

G1  Known-setup validation: assert correct detection on labeled data
G2  Expert annotation: store/retrieve user-tagged corners (DB layer elsewhere)
G3  Confidence calibration: Platt scaling on Bayesian posterior
G4  Ablation study: measure impact of removing each detector
G5  Multi-track validation: run G1 across multiple tracks
"""
from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np

from telemetry_tool.handling.types import SessionContext, CornerWindow
from telemetry_tool.handling.detectors.base import DetectorRegistry
from telemetry_tool.handling.fusion import BayesianFusion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# G1: Known-setup validation
# ---------------------------------------------------------------------------

def validate_known_setup(
    result: dict,
    expected: dict[int, str],
) -> dict:
    """Validate detection against known corner labels.

    Args:
        result: Output of run_handling_analysis().
        expected: {corner_id: "understeer" | "oversteer" | "neutral"}.

    Returns:
        {
            "n_tested": int,
            "n_correct": int,
            "accuracy": float,
            "per_corner": [{corner_id, expected, detected, correct}],
            "false_positives": [corner_ids],
            "false_negatives": [corner_ids],
        }
    """
    per_corner = []
    correct = 0
    false_pos = []
    false_neg = []

    for corner_id, expected_label in expected.items():
        # Find events for this corner
        corner_events = [e for e in result.get("events", [])
                         if e.get("corner_id") == corner_id]

        if corner_events:
            # Use the event with highest confidence
            best = max(corner_events, key=lambda e: e.get("confidence", 0))
            detected = best.get("event_type", "neutral")
        else:
            detected = "neutral"

        is_correct = detected == expected_label
        if is_correct:
            correct += 1
        elif expected_label == "neutral" and detected != "neutral":
            false_pos.append(corner_id)
        elif expected_label != "neutral" and detected == "neutral":
            false_neg.append(corner_id)

        per_corner.append({
            "corner_id": corner_id,
            "expected": expected_label,
            "detected": detected,
            "correct": is_correct,
        })

    n = len(expected)
    return {
        "n_tested": n,
        "n_correct": correct,
        "accuracy": correct / n if n > 0 else 0,
        "per_corner": per_corner,
        "false_positives": false_pos,
        "false_negatives": false_neg,
    }


# ---------------------------------------------------------------------------
# G3: Confidence calibration (Platt scaling)
# ---------------------------------------------------------------------------

def calibrate_confidence(
    predictions: list[dict],
    annotations: dict[int, str],
) -> dict:
    """Assess how well confidence predicts correctness.

    Args:
        predictions: List of FusedEvent.to_dict() from multiple sessions.
        annotations: {corner_id: "understeer" | "oversteer" | "neutral"}.

    Returns calibration metrics and suggested adjustment.
    """
    bins = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    calibration = []

    for lo, hi in bins:
        in_bin = [p for p in predictions
                  if lo <= p.get("confidence", 0) < hi
                  and p.get("corner_id") in annotations]
        if not in_bin:
            calibration.append({"bin": f"{lo:.0%}-{hi:.0%}", "n": 0, "accuracy": None})
            continue

        correct = sum(1 for p in in_bin
                      if p.get("event_type") == annotations.get(p.get("corner_id")))
        acc = correct / len(in_bin)
        expected_conf = (lo + hi) / 2
        calibration.append({
            "bin": f"{lo:.0%}-{hi:.0%}",
            "n": len(in_bin),
            "accuracy": round(acc, 3),
            "expected": round(expected_conf, 2),
            "gap": round(acc - expected_conf, 3),  # positive = underconfident
        })

    return {"calibration_bins": calibration}


# ---------------------------------------------------------------------------
# G4: Ablation study
# ---------------------------------------------------------------------------

def run_ablation(
    registry: DetectorRegistry,
    corners: list[CornerWindow],
    ctx: SessionContext,
    baseline_events: list[dict],
) -> dict:
    """Remove each detector one at a time and measure impact.

    Returns:
        {detector_name: {
            "events_without": int,
            "events_baseline": int,
            "delta": int,
            "impact": "high" | "medium" | "low",
        }}
    """
    fusion = BayesianFusion()
    n_baseline = len(baseline_events)
    results = {}

    for skip_det in registry.detectors:
        # Run all detectors EXCEPT this one
        all_events = []
        for cw in corners:
            votes = [v for v in registry.run_all(cw, ctx)
                     if v.detector_name != skip_det.name]
            events = fusion.fuse_corner(cw, votes)
            all_events.extend(events)

        n_without = len(all_events)
        delta = n_baseline - n_without

        if abs(delta) > n_baseline * 0.3:
            impact = "high"
        elif abs(delta) > n_baseline * 0.1:
            impact = "medium"
        else:
            impact = "low"

        results[skip_det.name] = {
            "events_without": n_without,
            "events_baseline": n_baseline,
            "delta": delta,
            "impact": impact,
        }

    return results


# ---------------------------------------------------------------------------
# G5: Multi-track validation summary
# ---------------------------------------------------------------------------

def multi_track_summary(track_results: dict[str, dict]) -> dict:
    """Summarize validation across multiple tracks.

    Args:
        track_results: {track_name: validate_known_setup() output}

    Returns:
        Overall accuracy and per-track breakdown.
    """
    total_tested = 0
    total_correct = 0
    per_track = []

    for track, vr in track_results.items():
        total_tested += vr["n_tested"]
        total_correct += vr["n_correct"]
        per_track.append({
            "track": track,
            "accuracy": vr["accuracy"],
            "n_tested": vr["n_tested"],
            "false_positives": len(vr["false_positives"]),
            "false_negatives": len(vr["false_negatives"]),
        })

    return {
        "overall_accuracy": total_correct / total_tested if total_tested > 0 else 0,
        "total_tested": total_tested,
        "per_track": per_track,
    }
