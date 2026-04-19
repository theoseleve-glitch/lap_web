"""Detector #17: Ensemble signal from existing pipeline coaching analyzers.

Wires the outputs of 5 independent coaching analyzers into the handling
detection system as additional evidence:

  - Trail brake analyzer (trail_brake.py): overlap quality score
  - Traction budget (traction_budget.py): friction circle utilization
  - Symptom detector (symptom_detector.py): entry/mid/exit symptom labels
  - Throttle lift detector (throttle_lift.py): exit throttle modulation
  - Weight transfer (weight_transfer.py): load dynamics

These analyzers run independently in the pipeline (s13_coaching_v3) and
produce their own assessments. This detector translates their signals
into the DetectorVote format for fusion.

Since the coaching analyzers require a different data format (lap DataFrame
with specific column names), this detector works with pre-computed results
stored in SessionContext.coaching_results (a dict set by the pipeline).
When coaching results aren't available (standalone mode), it abstains.
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.detectors.base import HandlingDetector
from telemetry_tool.handling.types import CornerWindow, DetectorVote, SessionContext


class PipelineEnsembleDetector(HandlingDetector):
    """Aggregates signals from the pipeline's coaching analyzers."""

    name = "pipeline_ensemble"
    default_weight = 0.8

    def detect(self, corner: CornerWindow, ctx: SessionContext) -> DetectorVote:
        coaching = getattr(ctx, "coaching_results", None)
        if not coaching:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        signals = []  # list of (direction, confidence) tuples

        # 1. Symptom detector: check for handling-related symptoms
        symptoms = coaching.get("symptoms", {}).get(str(corner.corner_id), [])
        for sym in symptoms:
            label = sym if isinstance(sym, str) else sym.get("label", "")
            if "understeer" in label.lower():
                zone = "entry" if "entry" in label else ("mid" if "mid" in label else "exit")
                signals.append((+0.7, 0.6, zone))
            elif "oversteer" in label.lower():
                zone = "entry" if "entry" in label else ("exit" if "exit" in label else "mid")
                signals.append((-0.7, 0.6, zone))

        # 2. Traction budget: low apex utilization = grip headroom = neutral
        #    High utilization with asymmetry = handling at limit
        traction = coaching.get("traction_budget", {}).get(str(corner.corner_id))
        if traction:
            entry_pct = traction.get("entry_total_pct", 50)
            exit_pct = traction.get("exit_total_pct", 50)
            if entry_pct > 85 and exit_pct < 70:
                signals.append((+0.5, 0.4, "entry"))  # entry-limited = understeer
            elif exit_pct > 85 and entry_pct < 70:
                signals.append((-0.5, 0.4, "exit"))  # exit-limited = oversteer

        # 3. Throttle lift: lift on exit = managing oversteer
        throttle_lifts = coaching.get("throttle_lifts", {}).get(str(corner.corner_id), [])
        for lift in throttle_lifts:
            severity = lift.get("severity", 0) if isinstance(lift, dict) else 0
            if severity > 0.3:
                signals.append((-0.6, min(severity, 1.0) * 0.5, "exit"))

        if not signals:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        # Fuse signals: weighted average
        total_w = sum(c for _, c, _ in signals)
        if total_w < 0.1:
            return DetectorVote(self.name, 0.0, 0.0, "mid")

        direction = sum(d * c for d, c, _ in signals) / total_w
        confidence = min(total_w / len(signals), 1.0)

        # Dominant zone
        zone_scores = {}
        for d, c, z in signals:
            zone_scores[z] = zone_scores.get(z, 0) + abs(d) * c
        zone = max(zone_scores, key=zone_scores.get) if zone_scores else "mid"

        return DetectorVote(
            self.name, float(np.clip(direction, -1, 1)),
            float(confidence), zone,
        )
