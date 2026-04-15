"""Multi-criterion transition gate.

Replaces the single-threshold ``bank_gradient > 0.008`` quarantine rule.
The cross-track validation showed that the simple cliff is too
aggressive on banked tracks (38% on Daytona) and too noisy on flat
tracks with elevation (32% false positives on Spa). This module
combines several independent stability signals into a hysteresis-
aware gate that produces:

  - boolean accept mask (True = stable, kept)
  - per-sample regime label (STABLE_FLAT / STABLE_BANKED / UNSTABLE)
  - per-sample reason codes for any rejected sample
  - per-sample integer score (number of criteria fired)
  - aggregate diagnostics (counts per reason, per regime, run lengths)

Design rules:
  - Deterministic, interpretable, debuggable. Every rejection has a name.
  - No ML, no black-box classifier. Just thresholds + state machine.
  - "Several independent criteria" — the gate uses 7 by default.
  - Conservative-but-not-destructive: entry_score=2 means a single noisy
    signal is NOT enough to reject a sample.
  - Stable state management via classical 2-threshold + dwell + padding.

Pipeline position: this gate is called BEFORE bucketing and BEFORE
the inverse solver (so its output can also feed roll/tire calibration
filtering). That means it does NOT have access to lambda or per-sample
residuals — that's intentional. The signals it does have (geometry +
vehicle state + suspension + road-state quality) are enough.

Failure modes the gate catches:
  - Banking transitions (Daytona infield-to-banking, oval-to-pit)
  - Sudden steering corrections (driver mistake / off-track moments)
  - Yaw spikes (snap oversteer, kerbs)
  - Curb hits / wheel unload (suspension spike)
  - Road-state estimator self-flagging unreliable (road_quality drop)

Failure modes it explicitly does NOT catch (left for downstream):
  - Tire-model mismatch (use lambda_out_of_band warning instead)
  - Inverse-solver low confidence (already handled by surface_field
    confidence weighting)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

import numpy as np

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────────────


class TransitionReason(Enum):
    """Why was a sample rejected by the transition gate?

    Each reason corresponds to one criterion in the scoring. A rejected
    sample may carry multiple reasons. ``DWELL`` and ``PADDING`` are
    state-machine reasons — they fire when no criterion was active at
    that exact sample but the hysteresis logic still keeps it rejected.
    """
    BANK_TRANSITION = "bank_transition"
    GRADE_TRANSITION = "grade_transition"
    STEERING_SPIKE = "steering_spike"
    YAW_JERK = "yaw_jerk"
    A_LAT_JERK = "a_lat_jerk"
    RIDE_HEIGHT_SPIKE = "ride_height_spike"
    ROAD_QUALITY_DROP = "road_quality_drop"
    DWELL = "dwell"                # rejected by min_dwell_samples
    PADDING = "padding"            # rejected by pre/post padding


class RegimeLabel(Enum):
    """Stable regime label assigned to each sample."""
    STABLE_FLAT = "stable_flat"
    STABLE_BANKED = "stable_banked"
    UNSTABLE = "unstable"


# ── Configuration ────────────────────────────────────────────


# Defaults calibrated on real iRacing 60Hz telemetry (Daytona, Spa, Okayama).
# The goal is "fires on real transitions, ignores suspension/sensor noise".
# See docs/transition_gate_assessment.md for the empirical justification.
_BANK_GRAD_THRESH_DEFAULT: Final[float] = 0.012      # rad/sample (~41°/s)
_GRADE_GRAD_THRESH_DEFAULT: Final[float] = 0.015     # rad/sample
_STEER_RATE_THRESH_DEFAULT: Final[float] = 8.0       # rad/s — sharp correction
_YAW_JERK_THRESH_DEFAULT: Final[float] = 8.0         # rad/s²
_A_LAT_JERK_THRESH_DEFAULT: Final[float] = 60.0      # m/s³ — only big lateral spikes
_RIDE_HEIGHT_RATE_THRESH_DEFAULT: Final[float] = 0.50  # m/s — real curb hit, not suspension noise
_ROAD_QUALITY_THRESH_DEFAULT: Final[float] = 0.10    # only the worst self-flagged cases
_BANKED_REGIME_RAD: Final[float] = 0.08              # ~4.6° — same as condition_bucketing


@dataclass(frozen=True)
class TransitionGateConfig:
    """All thresholds and state-machine knobs.

    Every value is documented here. If a threshold needs to change for
    a particular vehicle or track, do it through this config — never
    hardcode in callsites.
    """
    # ── Per-criterion thresholds ─────────────────────────────
    bank_grad_thresh_rad_per_sample: float = _BANK_GRAD_THRESH_DEFAULT
    grade_grad_thresh_rad_per_sample: float = _GRADE_GRAD_THRESH_DEFAULT
    steer_rate_thresh_rad_per_s: float = _STEER_RATE_THRESH_DEFAULT
    yaw_jerk_thresh_rad_per_s2: float = _YAW_JERK_THRESH_DEFAULT
    a_lat_jerk_thresh_m_per_s3: float = _A_LAT_JERK_THRESH_DEFAULT
    ride_height_rate_thresh_m_per_s: float = _RIDE_HEIGHT_RATE_THRESH_DEFAULT
    road_quality_thresh: float = _ROAD_QUALITY_THRESH_DEFAULT

    # ── Sampling rate ────────────────────────────────────────
    sample_rate_hz: float = 60.0      # used to convert per-sample → per-second

    # ── Hysteresis state machine ─────────────────────────────
    entry_score: int = 2              # need ≥ this many criteria firing → UNSTABLE
    exit_score: int = 0               # need < this many to exit UNSTABLE
    min_dwell_samples: int = 10       # once UNSTABLE, must stay for ≥ this long
    pre_padding_samples: int = 5      # extend UNSTABLE backwards in time
    post_padding_samples: int = 5     # extend UNSTABLE forwards in time

    # ── Regime classification ────────────────────────────────
    banked_threshold_rad: float = _BANKED_REGIME_RAD


# ── Output records ───────────────────────────────────────────


@dataclass
class TransitionFeatures:
    """Per-sample features used by the gate.

    All arrays are sample-aligned to the input length. NaN-safe: the
    feature computation tolerates NaN inputs (e.g. missing ride heights)
    and returns zeros for the corresponding criterion.
    """
    bank_grad: np.ndarray
    grade_grad: np.ndarray
    steer_rate: np.ndarray
    yaw_jerk: np.ndarray
    a_lat_jerk: np.ndarray
    ride_height_rate_max: np.ndarray   # max abs rate across the 4 wheels
    road_quality: np.ndarray
    has_ride_height: bool


@dataclass
class TransitionGateDiagnostics:
    """Aggregate diagnostics — what got rejected, where, why."""
    n_total: int
    n_accepted: int
    n_rejected: int
    accept_pct: float
    reject_pct: float
    reason_counts: dict[str, int]                  # reason.value → count
    regime_counts: dict[str, int]                  # label.value → count
    n_unstable_runs: int
    longest_unstable_run: int
    median_unstable_run: int

    def to_dict(self) -> dict:
        return {
            "n_total": self.n_total,
            "n_accepted": self.n_accepted,
            "n_rejected": self.n_rejected,
            "accept_pct": round(self.accept_pct, 3),
            "reject_pct": round(self.reject_pct, 3),
            "reason_counts": dict(self.reason_counts),
            "regime_counts": dict(self.regime_counts),
            "n_unstable_runs": self.n_unstable_runs,
            "longest_unstable_run": self.longest_unstable_run,
            "median_unstable_run": self.median_unstable_run,
        }


@dataclass
class TransitionGateResult:
    """Per-sample gate output + aggregate diagnostics."""
    accept_mask: np.ndarray            # (N,) bool — True = stable, accepted
    regime: np.ndarray                 # (N,) object — RegimeLabel per sample
    score: np.ndarray                  # (N,) int — number of criteria fired
    reasons_per_sample: list[list[TransitionReason]]   # per-sample list (empty if accepted)
    features: TransitionFeatures
    diagnostics: TransitionGateDiagnostics

    @property
    def reject_mask(self) -> np.ndarray:
        return ~self.accept_mask


# ── Feature computation ──────────────────────────────────────


def _safe_gradient(arr: np.ndarray) -> np.ndarray:
    """np.gradient with NaN-guard. NaN → 0."""
    if arr.size == 0:
        return arr.copy()
    g = np.gradient(arr.astype(np.float64))
    g[~np.isfinite(g)] = 0.0
    return g


def compute_transition_features(
    *,
    bank_est: np.ndarray,
    grade_est: np.ndarray,
    yaw_rate: np.ndarray,
    steer: np.ndarray,
    a_lat: np.ndarray,
    road_quality: np.ndarray,
    ride_heights: np.ndarray | None = None,    # (N, 4) or None
    sample_rate_hz: float = 60.0,
) -> TransitionFeatures:
    """Compute per-sample stability features.

    Pure function. All inputs are sample-aligned 1D arrays (or
    (N, 4) for ride_heights). Output arrays are also sample-aligned.

    Per-sample derivatives use np.gradient (centered differences with
    edge handling). Time-rate features (steer_rate, yaw_jerk,
    a_lat_jerk, ride_height_rate_max) multiply by sample_rate_hz to
    convert per-sample → per-second.
    """
    n = len(bank_est)
    dt = 1.0 / sample_rate_hz

    # Derivatives in per-sample units
    bank_grad = np.abs(_safe_gradient(bank_est))
    grade_grad = np.abs(_safe_gradient(grade_est))

    # Per-second derivatives
    steer_rate = np.abs(_safe_gradient(steer)) / dt
    yaw_jerk = np.abs(_safe_gradient(yaw_rate)) / dt
    a_lat_jerk = np.abs(_safe_gradient(a_lat)) / dt

    # Ride heights: per-wheel absolute rate, then max across 4 wheels
    has_ride_height = ride_heights is not None and ride_heights.shape == (n, 4)
    if has_ride_height:
        rh_rates = np.zeros((n, 4))
        for w in range(4):
            rh_rates[:, w] = np.abs(_safe_gradient(ride_heights[:, w])) / dt
        ride_height_rate_max = rh_rates.max(axis=1)
    else:
        ride_height_rate_max = np.zeros(n)

    # Road quality is already a 0-1 score
    rq = np.asarray(road_quality, dtype=np.float64)
    rq[~np.isfinite(rq)] = 0.0

    return TransitionFeatures(
        bank_grad=bank_grad,
        grade_grad=grade_grad,
        steer_rate=steer_rate,
        yaw_jerk=yaw_jerk,
        a_lat_jerk=a_lat_jerk,
        ride_height_rate_max=ride_height_rate_max,
        road_quality=rq,
        has_ride_height=has_ride_height,
    )


# ── Per-sample scoring ───────────────────────────────────────


def score_per_sample(
    features: TransitionFeatures,
    config: TransitionGateConfig,
) -> tuple[np.ndarray, list[list[TransitionReason]]]:
    """Score each sample by counting how many criteria fired.

    Returns
    -------
    score : (N,) int — number of criteria firing per sample
    reasons : list of length N, each a list of TransitionReason for that sample
    """
    n = len(features.bank_grad)
    score = np.zeros(n, dtype=np.int32)
    reasons: list[list[TransitionReason]] = [[] for _ in range(n)]

    def _add(mask: np.ndarray, reason: TransitionReason) -> None:
        idx = np.where(mask)[0]
        score[idx] += 1
        for i in idx:
            reasons[int(i)].append(reason)

    _add(features.bank_grad > config.bank_grad_thresh_rad_per_sample,
         TransitionReason.BANK_TRANSITION)
    _add(features.grade_grad > config.grade_grad_thresh_rad_per_sample,
         TransitionReason.GRADE_TRANSITION)
    _add(features.steer_rate > config.steer_rate_thresh_rad_per_s,
         TransitionReason.STEERING_SPIKE)
    _add(features.yaw_jerk > config.yaw_jerk_thresh_rad_per_s2,
         TransitionReason.YAW_JERK)
    _add(features.a_lat_jerk > config.a_lat_jerk_thresh_m_per_s3,
         TransitionReason.A_LAT_JERK)
    if features.has_ride_height:
        _add(features.ride_height_rate_max > config.ride_height_rate_thresh_m_per_s,
             TransitionReason.RIDE_HEIGHT_SPIKE)
    _add(features.road_quality < config.road_quality_thresh,
         TransitionReason.ROAD_QUALITY_DROP)

    return score, reasons


# ── Hysteresis state machine ─────────────────────────────────


def apply_hysteresis(
    score: np.ndarray,
    config: TransitionGateConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """State machine producing the final unstable mask.

    Two thresholds + minimum dwell + symmetric padding.

    Returns
    -------
    unstable_mask : (N,) bool — True = sample is in the UNSTABLE state
    rejected_by_dwell : (N,) bool — would be stable by score, kept unstable by dwell
    rejected_by_padding : (N,) bool — would be stable, kept unstable by padding
    """
    n = len(score)
    if n == 0:
        empty = np.zeros(0, dtype=bool)
        return empty, empty, empty

    raw_unstable = np.zeros(n, dtype=bool)
    is_unstable = False
    state_start = -config.min_dwell_samples
    rejected_by_dwell = np.zeros(n, dtype=bool)

    for i in range(n):
        if not is_unstable:
            if score[i] >= config.entry_score:
                is_unstable = True
                state_start = i
                raw_unstable[i] = True
            else:
                raw_unstable[i] = False
        else:
            raw_unstable[i] = True
            can_exit = (
                score[i] <= config.exit_score
                and (i - state_start) >= config.min_dwell_samples
            )
            if can_exit:
                is_unstable = False

    # Identify samples that would be stable by raw score but are kept
    # unstable by the dwell rule (entered above entry_score, then score
    # dropped below exit_score, but not yet past the min_dwell window).
    # We attribute them to DWELL.
    # raw_unstable is True at i; if score[i] <= exit_score AND raw_unstable
    # is True, the dwell rule is what's keeping it unstable.
    rejected_by_dwell = raw_unstable & (score <= config.exit_score)

    # Symmetric padding: extend UNSTABLE windows by pre/post samples
    if config.pre_padding_samples > 0 or config.post_padding_samples > 0:
        padded = raw_unstable.copy()
        # Find run boundaries
        diff = np.diff(np.concatenate(([False], raw_unstable, [False])).astype(int))
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0]
        for s_idx, e_idx in zip(starts, ends):
            pad_lo = max(0, s_idx - config.pre_padding_samples)
            pad_hi = min(n, e_idx + config.post_padding_samples)
            padded[pad_lo:pad_hi] = True
        rejected_by_padding = padded & (~raw_unstable)
        unstable_mask = padded
    else:
        rejected_by_padding = np.zeros(n, dtype=bool)
        unstable_mask = raw_unstable

    return unstable_mask, rejected_by_dwell, rejected_by_padding


# ── Regime classification ────────────────────────────────────


def classify_regime(
    bank_est: np.ndarray,
    unstable_mask: np.ndarray,
    config: TransitionGateConfig,
) -> np.ndarray:
    """Per-sample regime label as an object array of RegimeLabel."""
    n = len(bank_est)
    out = np.empty(n, dtype=object)
    banked = np.abs(bank_est) > config.banked_threshold_rad
    for i in range(n):
        if unstable_mask[i]:
            out[i] = RegimeLabel.UNSTABLE
        elif banked[i]:
            out[i] = RegimeLabel.STABLE_BANKED
        else:
            out[i] = RegimeLabel.STABLE_FLAT
    return out


# ── Run-length helpers ───────────────────────────────────────


def _run_lengths(mask: np.ndarray) -> list[int]:
    """Lengths of consecutive True runs in mask."""
    if mask.size == 0:
        return []
    diff = np.diff(np.concatenate(([False], mask.astype(bool), [False])).astype(int))
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    return [int(e - s) for s, e in zip(starts, ends)]


# ── Top-level orchestrator ───────────────────────────────────


def apply_gate(
    *,
    bank_est: np.ndarray,
    grade_est: np.ndarray,
    yaw_rate: np.ndarray,
    steer: np.ndarray,
    a_lat: np.ndarray,
    road_quality: np.ndarray,
    ride_heights: np.ndarray | None = None,
    config: TransitionGateConfig | None = None,
) -> TransitionGateResult:
    """End-to-end gate: features → score → hysteresis → regime → diagnostics.

    All arrays are sample-aligned. ``ride_heights`` is optional ((N, 4) or None).

    Output is a :class:`TransitionGateResult`. To use the gate as a drop-in
    replacement for the old transition_mask, take ``result.reject_mask``.
    """
    cfg = config or TransitionGateConfig()
    n = len(bank_est)

    features = compute_transition_features(
        bank_est=bank_est, grade_est=grade_est, yaw_rate=yaw_rate,
        steer=steer, a_lat=a_lat, road_quality=road_quality,
        ride_heights=ride_heights, sample_rate_hz=cfg.sample_rate_hz,
    )
    score, reasons_per_sample = score_per_sample(features, cfg)
    unstable, dwell_only, padding_only = apply_hysteresis(score, cfg)

    # Attach DWELL / PADDING reasons where applicable
    for i in range(n):
        if unstable[i] and not reasons_per_sample[i]:
            # Sample is unstable but no criterion fired — must be dwell or padding
            if padding_only[i]:
                reasons_per_sample[i].append(TransitionReason.PADDING)
            elif dwell_only[i]:
                reasons_per_sample[i].append(TransitionReason.DWELL)

    accept_mask = ~unstable
    regime = classify_regime(bank_est, unstable, cfg)

    # Diagnostics
    reason_counts: dict[str, int] = {}
    for i in range(n):
        for r in reasons_per_sample[i]:
            reason_counts[r.value] = reason_counts.get(r.value, 0) + 1
    regime_counts: dict[str, int] = {lbl.value: 0 for lbl in RegimeLabel}
    for lbl in regime:
        regime_counts[lbl.value] += 1

    runs = _run_lengths(unstable)
    longest = max(runs) if runs else 0
    median = int(np.median(runs)) if runs else 0

    diagnostics = TransitionGateDiagnostics(
        n_total=n,
        n_accepted=int(accept_mask.sum()),
        n_rejected=int(unstable.sum()),
        accept_pct=float(accept_mask.mean() * 100.0) if n else 0.0,
        reject_pct=float(unstable.mean() * 100.0) if n else 0.0,
        reason_counts=reason_counts,
        regime_counts=regime_counts,
        n_unstable_runs=len(runs),
        longest_unstable_run=longest,
        median_unstable_run=median,
    )

    return TransitionGateResult(
        accept_mask=accept_mask,
        regime=regime,
        score=score,
        reasons_per_sample=reasons_per_sample,
        features=features,
        diagnostics=diagnostics,
    )
