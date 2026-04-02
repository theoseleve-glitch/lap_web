"""Compute per-sample boolean masks for segment filtering.

Each mask identifies samples that should be excluded from clean-lap
analysis (off-track, pit lane, drafting, yellow flags, too slow).
The ``clean`` mask is the complement: samples where none of the
exclusion conditions are active.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from telemetry_tool.sim_optimizer.config import SimOptimizerConfig
    from telemetry_tool.sim_optimizer.ingest.raw_channels import RawChannelSet

logger = logging.getLogger(__name__)


@dataclass
class SegmentMask:
    """Per-sample boolean masks for segment classification."""

    n_samples: int
    off_track: np.ndarray   # grass / gravel / sand
    pit: np.ndarray         # on pit road
    draft: np.ndarray       # car ahead within draft distance
    yellow: np.ndarray      # yellow flag active
    slow: np.ndarray        # below minimum speed threshold
    clean: np.ndarray       # none of the above


def compute_segment_mask(
    channels: RawChannelSet,
    *,
    config: SimOptimizerConfig,
) -> SegmentMask:
    """Build exclusion masks from *channels* using *config* thresholds.

    If a channel is ``None`` the corresponding mask stays all-False
    (we don't flag what we can't check).
    """
    n = channels.n_samples
    false = np.zeros(n, dtype=bool)

    # Off-track: track_surface != 3  OR  is_on_track == False
    off_track = false.copy()
    if channels.track_surface is not None:
        off_track = off_track | (channels.track_surface != 3)
    if channels.is_on_track is not None:
        off_track = off_track | (channels.is_on_track == 0)

    # Pit road
    if channels.on_pit_road is not None:
        pit = channels.on_pit_road.astype(bool)
    else:
        pit = false.copy()

    # Draft: car ahead closer than threshold
    if channels.car_dist_ahead is not None:
        draft = channels.car_dist_ahead < config.aero_draft_distance_m
    else:
        draft = false.copy()

    # Yellow flag
    if channels.session_flags is not None:
        flags_int = channels.session_flags.astype(np.int64)
        yellow = (flags_int & config.filter_yellow_flag_bits) != 0
    else:
        yellow = false.copy()

    # Slow speed
    if channels.speed_mps is not None:
        slow = channels.speed_mps < config.filter_min_speed_mps
    else:
        slow = false.copy()

    # Clean = none of the exclusions
    clean = ~(off_track | pit | draft | yellow | slow)

    mask = SegmentMask(
        n_samples=n,
        off_track=off_track,
        pit=pit,
        draft=draft,
        yellow=yellow,
        slow=slow,
        clean=clean,
    )

    logger.info(
        "Segment mask (%d samples): off_track=%d  pit=%d  draft=%d  "
        "yellow=%d  slow=%d  clean=%d (%.1f%%)",
        n,
        off_track.sum(),
        pit.sum(),
        draft.sum(),
        yellow.sum(),
        slow.sum(),
        clean.sum(),
        100.0 * clean.sum() / max(n, 1),
    )
    return mask
