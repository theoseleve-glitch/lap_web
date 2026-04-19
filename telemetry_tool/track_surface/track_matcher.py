"""
track_surface/track_matcher.py
------------------------------
Cross-sim track matching by curvature fingerprint.

Computes a rotation/translation-invariant shape fingerprint from the
signed curvature profile, then uses cross-correlation to match tracks
across different simulators or data sources.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.signal import correlate

from track_surface.frenet import FrenetFrame

logger = logging.getLogger(__name__)

_FINGERPRINT_LENGTH = 200


@dataclass
class TrackMatch:
    """Result of matching two tracks."""

    track_id_a: str
    track_id_b: str
    sim_a: str
    sim_b: str
    similarity: float          # 0-1, 1 = identical
    length_diff_pct: float     # absolute percentage difference in length
    shape_correlation: float   # raw cross-correlation peak value

    def to_dict(self) -> dict:
        return {
            "track_id_a": self.track_id_a,
            "track_id_b": self.track_id_b,
            "sim_a": self.sim_a,
            "sim_b": self.sim_b,
            "similarity": round(self.similarity, 4),
            "length_diff_pct": round(self.length_diff_pct, 2),
            "shape_correlation": round(self.shape_correlation, 4),
        }


def compute_track_fingerprint(frenet: FrenetFrame) -> np.ndarray:
    """Compute a rotation/translation-invariant shape fingerprint.

    Uses the signed curvature profile kappa(s) normalized by lap length.
    The curvature-vs-normalized-distance signature is invariant to the
    track's position and orientation in world space.

    Parameters
    ----------
    frenet : FrenetFrame with curvature_1pm and s_grid.

    Returns
    -------
    A fixed-length (200,) array: curvature resampled to 200 points
    at uniform normalized distance (0 to 1).
    """
    if frenet.n_points < 3 or frenet.total_length_m < 1e-6:
        return np.zeros(_FINGERPRINT_LENGTH)

    # Normalized distance [0, 1]
    s_norm = frenet.s_grid / frenet.total_length_m

    # Resample curvature to fixed grid
    s_uniform = np.linspace(0.0, 1.0, _FINGERPRINT_LENGTH, endpoint=False)
    kappa_resampled = np.interp(s_uniform, s_norm, frenet.curvature_1pm)

    # Normalize amplitude so the fingerprint is scale-invariant:
    # multiply by total_length to make kappa dimensionless (turns per lap)
    kappa_resampled = kappa_resampled * frenet.total_length_m

    return kappa_resampled


def match_tracks(
    fingerprint_a: np.ndarray,
    fingerprint_b: np.ndarray,
    length_a: float,
    length_b: float,
    max_length_diff_pct: float = 5.0,
) -> float:
    """Compare two track fingerprints.

    Returns similarity 0-1:
    1. Check lap length: if diff > max_length_diff_pct, return 0.0.
    2. Cross-correlate the curvature profiles (handles start/finish
       offset differences).
    3. Similarity = max correlation value (normalized).

    Parameters
    ----------
    fingerprint_a, fingerprint_b : (200,) curvature fingerprints.
    length_a, length_b : lap lengths in metres.
    max_length_diff_pct : maximum allowed length difference (%).

    Returns
    -------
    Similarity score between 0.0 and 1.0.
    """
    if length_a <= 0 or length_b <= 0:
        return 0.0

    # Length check
    avg_len = (length_a + length_b) / 2.0
    diff_pct = abs(length_a - length_b) / avg_len * 100.0
    if diff_pct > max_length_diff_pct:
        return 0.0

    a = np.asarray(fingerprint_a, dtype=np.float64)
    b = np.asarray(fingerprint_b, dtype=np.float64)

    # Handle degenerate cases
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-12 or norm_b < 1e-12:
        # Both zero => identical (both straight tracks)
        if norm_a < 1e-12 and norm_b < 1e-12:
            return 1.0
        return 0.0

    # Normalize
    a_norm = a / norm_a
    b_norm = b / norm_b

    # Cross-correlate (circular, to handle start/finish offset)
    # Use scipy.signal.correlate in 'full' mode on doubled signal
    # for circular cross-correlation
    a_doubled = np.tile(a_norm, 2)
    xcorr = correlate(a_doubled, b_norm, mode="valid")

    # Maximum cross-correlation value is the similarity
    similarity = float(np.max(xcorr))

    # Clamp to [0, 1] — negative correlation means anti-correlated
    return max(0.0, min(1.0, similarity))


def find_matching_tracks(
    target_frenet: FrenetFrame,
    known_tracks: dict[str, tuple],
    min_similarity: float = 0.85,
) -> list[TrackMatch]:
    """Find tracks in the known set that match the target.

    Parameters
    ----------
    target_frenet : FrenetFrame for the track to match.
    known_tracks : dict mapping track_id to (frenet, sim_source) tuples.
    min_similarity : minimum similarity threshold.

    Returns
    -------
    List of TrackMatch sorted by similarity descending.
    """
    target_fp = compute_track_fingerprint(target_frenet)
    target_len = target_frenet.total_length_m

    matches: list[TrackMatch] = []
    for track_id, (frenet, sim_source) in known_tracks.items():
        candidate_fp = compute_track_fingerprint(frenet)
        candidate_len = frenet.total_length_m

        sim = match_tracks(target_fp, candidate_fp, target_len, candidate_len)
        if sim < min_similarity:
            continue

        avg_len = (target_len + candidate_len) / 2.0
        length_diff_pct = abs(target_len - candidate_len) / avg_len * 100.0

        # Get shape correlation (raw, not clamped)
        a_n = target_fp / max(np.linalg.norm(target_fp), 1e-12)
        b_n = candidate_fp / max(np.linalg.norm(candidate_fp), 1e-12)
        shape_corr = float(np.dot(a_n, b_n))

        matches.append(TrackMatch(
            track_id_a="target",
            track_id_b=track_id,
            sim_a="target",
            sim_b=sim_source,
            similarity=sim,
            length_diff_pct=length_diff_pct,
            shape_correlation=shape_corr,
        ))

    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches
