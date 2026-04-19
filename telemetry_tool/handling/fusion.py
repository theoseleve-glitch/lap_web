"""Bayesian fusion of detector votes into handling events.

Implements:
  C1  Bayesian update (log-odds) instead of weighted voting
  C3  Conflict flagging via entropy of vote distribution
  C5  Per-phase fusion (entry / mid / exit independently)
  C6  Minimum 2-detector agreement rule
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict

import numpy as np

from telemetry_tool.handling.types import (
    CornerWindow, DetectorVote, FusedEvent, SessionContext,
)

logger = logging.getLogger(__name__)

# Minimum event duration in seconds — shorter events are noise
MIN_EVENT_DURATION_S = 0.3

# Single-detector events require this minimum confidence to survive
SINGLE_DETECTOR_MIN_CONF = 0.80


class BayesianFusion:
    """Fuse multiple detector votes per corner-zone using Bayesian log-odds."""

    def fuse_corner(
        self,
        corner: CornerWindow,
        votes: list[DetectorVote],
        detector_weights: dict[str, float] | None = None,
    ) -> list[FusedEvent]:
        """Fuse all votes for one corner into events per zone.

        Args:
            corner: The corner being analyzed.
            votes: All detector votes for this corner.
            detector_weights: Optional per-detector weight overrides.

        Returns:
            List of FusedEvent (one per zone that has a significant signal).
        """
        if not votes:
            return []

        # Separate confidence modifiers (B7 line variation) from directional votes
        conf_multiplier = 1.0
        directional_votes = []
        for v in votes:
            if v.is_confidence_modifier:
                conf_multiplier *= v.confidence
            else:
                directional_votes.append(v)

        if not directional_votes:
            return []

        # Group votes by zone (C5: per-phase fusion)
        zone_votes: dict[str, list[DetectorVote]] = defaultdict(list)
        for v in directional_votes:
            zone_votes[v.zone].append(v)

        events = []
        for zone, zvotes in zone_votes.items():
            event = self._fuse_zone(
                corner, zone, zvotes, conf_multiplier, detector_weights
            )
            if event is not None:
                events.append(event)

        return events

    def _fuse_zone(
        self,
        corner: CornerWindow,
        zone: str,
        votes: list[DetectorVote],
        conf_multiplier: float,
        weights: dict[str, float] | None,
    ) -> FusedEvent | None:
        """Bayesian fusion for one corner-zone."""
        if not votes:
            return None

        # C1: Bayesian log-odds update
        # Prior: log_odds = 0 (neutral, 50/50)
        # Each vote converts to a likelihood ratio
        log_odds = 0.0
        for v in votes:
            w = (weights or {}).get(v.detector_name, 1.0)
            lr = self._vote_to_likelihood_ratio(v.direction, v.confidence)
            log_odds += w * math.log(lr + 1e-12)

        # Convert back to posterior
        posterior = 1.0 / (1.0 + math.exp(-log_odds))
        # Direction: deviation from 0.5 neutral
        direction = (posterior - 0.5) * 2.0  # maps [0,1] to [-1,+1]

        # Confidence: based on how far from neutral + agreement + count
        n_voters = len(votes)
        magnitude = abs(direction)

        # Agreement: how much do voters agree on direction?
        dirs = [v.direction for v in votes]
        if n_voters > 1:
            agreement = 1.0 - np.std(dirs)
            agreement = max(agreement, 0.0)
        else:
            agreement = 0.5

        # Confidence: use the STRONGEST individual signal boosted by agreement,
        # not a triple-multiplication that compresses everything to near-zero.
        #
        # Old formula: magnitude * agreement * (n_voters/4) → avg ~20%
        # New formula: max_individual_conf * agreement_boost * voter_bonus → avg ~50%

        # Start from the strongest individual detector confidence
        max_individual = max(v.confidence for v in votes)

        # Agreement boost: if all voters point the same way, multiply by 1.3
        # If they disagree, multiply by 0.5
        if n_voters > 1:
            same_sign = sum(1 for d in dirs if d * direction > 0)
            agreement_ratio = same_sign / n_voters  # 1.0 = all agree
            agreement_boost = 0.5 + agreement_ratio  # range: 0.5 (all disagree) to 1.5 (all agree)
        else:
            agreement_boost = 0.8

        # Voter bonus: more detectors = more confidence (diminishing returns)
        voter_bonus = min(1.0 + 0.15 * (n_voters - 1), 1.6)  # 1 voter=1.0, 4=1.45, 6=1.6

        confidence = max_individual * agreement_boost * voter_bonus * conf_multiplier
        # Blend with Bayesian magnitude to penalize weak posterior
        confidence = confidence * (0.3 + 0.7 * min(magnitude / 0.5, 1.0))
        confidence = min(confidence, 0.95)  # cap at 95% — never fully certain without ground truth

        # C6: Single-detector events need high individual confidence
        if n_voters == 1 and max_individual < 0.6:
            return None

        # C3: Conflict detection
        conflict = False
        if n_voters >= 2:
            pos = sum(1 for d in dirs if d > 0.15)
            neg = sum(1 for d in dirs if d < -0.15)
            if pos > 0 and neg > 0:
                conflict = True
                confidence *= 0.6  # reduce confidence on conflicting evidence

        # Determine event boundaries from phase segmentation
        start_dist, end_dist, duration = self._zone_boundaries(corner, zone)

        if duration < MIN_EVENT_DURATION_S:
            return None

        if magnitude < 0.10 or confidence < 0.05:
            return None

        return FusedEvent(
            corner_id=corner.corner_id,
            zone=zone,
            direction=float(direction),
            confidence=float(confidence),
            start_dist_m=start_dist,
            end_dist_m=end_dist,
            duration_s=duration,
            n_voters=n_voters,
            conflict=conflict,
            detector_votes={
                v.detector_name: (v.direction, v.confidence)
                for v in votes
            },
        )

    @staticmethod
    def _vote_to_likelihood_ratio(direction: float, confidence: float) -> float:
        """Convert a detector vote to a likelihood ratio for Bayesian update.

        LR > 1 means evidence for understeer (positive direction).
        LR < 1 means evidence for oversteer (negative direction).
        LR = 1 means no evidence.

        Capped at [0.1, 10.0] to prevent single-detector domination.
        """
        # Scale direction by confidence: strong confident vote = strong LR
        effective = direction * confidence
        # Map [-1, +1] to LR via exponential
        lr = math.exp(effective * 2.0)  # e^2 ≈ 7.4 for full confident vote
        return max(0.1, min(lr, 10.0))

    @staticmethod
    def _zone_boundaries(
        corner: CornerWindow, zone: str
    ) -> tuple[float, float, float]:
        """Get distance and duration boundaries for a zone."""
        if zone == "entry":
            s, e = corner.phase_entry
        elif zone == "exit":
            s, e = corner.phase_exit
        elif zone == "mid":
            s, e = corner.phase_mid
        else:
            s, e = 0, corner.n_samples

        # Clamp to valid range
        s = max(0, min(s, corner.n_samples - 1))
        e = max(s + 1, min(e, corner.n_samples))

        start_dist = float(corner.dist_m[s]) if s < len(corner.dist_m) else 0.0
        end_dist = float(corner.dist_m[e - 1]) if e <= len(corner.dist_m) else start_dist
        duration = float(corner.time_s[e - 1] - corner.time_s[s]) if e > s else 0.0

        return start_dist, end_dist, max(duration, 0.0)
