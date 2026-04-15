"""Dynamic detector weight calibration (C4).

Two-pass approach:
  1. Run base fusion with default weights across all corners
  2. Correlate each detector's vote direction with the fused consensus
  3. Boost detectors that consistently agree, reduce noisy ones
  4. Re-run fusion with adjusted weights
"""
from __future__ import annotations

import numpy as np

from telemetry_tool.handling.types import (
    CornerWindow, DetectorVote, SessionContext,
)
from telemetry_tool.handling.detectors.base import DetectorRegistry
from telemetry_tool.handling.fusion import BayesianFusion


def calibrate_weights(
    registry: DetectorRegistry,
    corners: list[CornerWindow],
    ctx: SessionContext,
    min_corners: int = 5,
) -> dict[str, float]:
    """Compute per-session detector weights by correlating with consensus.

    Returns a dict {detector_name: adjusted_weight}.
    If not enough data, returns default weights.
    """
    if len(corners) < min_corners:
        return {d.name: d.default_weight for d in registry.detectors}

    fusion = BayesianFusion()

    # Pass 1: run all detectors, get consensus per corner
    all_votes: list[list[DetectorVote]] = []
    consensus_dirs: list[float] = []

    for cw in corners:
        votes = registry.run_all(cw, ctx)
        all_votes.append(votes)
        events = fusion.fuse_corner(cw, votes)
        # Consensus = mean direction across all zones
        if events:
            consensus_dirs.append(np.mean([e.direction for e in events]))
        else:
            consensus_dirs.append(0.0)

    consensus = np.array(consensus_dirs)

    # Pass 2: correlate each detector with consensus
    detector_names = [d.name for d in registry.detectors]
    weights = {}

    for name in detector_names:
        det_dirs = []
        for ci, votes in enumerate(all_votes):
            matching = [v for v in votes if v.detector_name == name and v.confidence > 0.05]
            if matching:
                det_dirs.append((ci, matching[0].direction))

        if len(det_dirs) < 3:
            # Not enough data for this detector — use default
            det = next(d for d in registry.detectors if d.name == name)
            weights[name] = det.default_weight
            continue

        indices = [x[0] for x in det_dirs]
        dirs = np.array([x[1] for x in det_dirs])
        cons_subset = consensus[indices]

        # Correlation between detector direction and consensus
        if np.std(dirs) < 1e-6 or np.std(cons_subset) < 1e-6:
            det = next(d for d in registry.detectors if d.name == name)
            weights[name] = det.default_weight
            continue

        corr = np.corrcoef(dirs, cons_subset)[0, 1]

        # Adjust weight: high correlation = boost, low = reduce
        det = next(d for d in registry.detectors if d.name == name)
        base = det.default_weight

        # Scale: corr=1.0 → 1.3x weight, corr=0.0 → 0.7x, corr=-0.5 → 0.4x
        multiplier = 0.7 + 0.6 * max(corr, -0.5)
        weights[name] = round(base * multiplier, 3)

    return weights
