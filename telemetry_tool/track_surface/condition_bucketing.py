"""
Condition bucketing — separate surface-field posteriors by operating regime.

Maintains independent Bayesian fields for different condition buckets so
that flat-section data does not contaminate banked-section estimates, and
early-stint tire behavior does not mix with late-stint degradation.

Bucket key: (section_regime, stint_phase)
  section_regime: "flat" | "banked" | "transition"
  stint_phase: "early" | "mid" | "late"

Transition regime is NEVER updated — those samples are quarantined.

Fallback hierarchy (from most specific to least):
  1. Exact bucket (same section + same stint phase)
  2. Same section, any stint phase
  3. Global prior

Every query reports which fallback level was used.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final

import numpy as np

from track_surface.surface_field import SurfaceField, SurfaceFieldConfig

logger = logging.getLogger(__name__)

_BANK_THRESHOLD_RAD: Final[float] = 0.08   # ~4.6° — above this = "banked"
_EARLY_STINT_LAPS: Final[int] = 5
_LATE_STINT_LAPS: Final[int] = 50


# ── Bucket identity ──────────────────────────────────────────


@dataclass(frozen=True)
class BucketKey:
    """Typed, hashable condition bucket identifier."""
    section_regime: str    # "flat" | "banked" | "transition"
    stint_phase: str       # "early" | "mid" | "late"

    def __str__(self) -> str:
        return f"{self.section_regime}/{self.stint_phase}"

    @classmethod
    def flat_early(cls) -> BucketKey:
        return cls("flat", "early")

    @classmethod
    def flat_mid(cls) -> BucketKey:
        return cls("flat", "mid")

    @classmethod
    def flat_late(cls) -> BucketKey:
        return cls("flat", "late")

    @classmethod
    def banked_early(cls) -> BucketKey:
        return cls("banked", "early")

    @classmethod
    def banked_mid(cls) -> BucketKey:
        return cls("banked", "mid")

    @classmethod
    def banked_late(cls) -> BucketKey:
        return cls("banked", "late")


ACTIVE_BUCKETS: Final[list[BucketKey]] = [
    BucketKey("flat", "early"),
    BucketKey("flat", "mid"),
    BucketKey("flat", "late"),
    BucketKey("banked", "early"),
    BucketKey("banked", "mid"),
    BucketKey("banked", "late"),
]

TRANSITION_BUCKET: Final[BucketKey] = BucketKey("transition", "any")


# ── Regime classification ────────────────────────────────────


def classify_section_regime(
    bank_rad: np.ndarray,
    transition_mask: np.ndarray,
) -> np.ndarray:
    """Classify each sample as "flat", "banked", or "transition".

    Returns an array of strings.
    """
    N = len(bank_rad)
    regime = np.full(N, "flat", dtype=object)
    regime[np.abs(bank_rad) > _BANK_THRESHOLD_RAD] = "banked"
    regime[transition_mask] = "transition"
    return regime


def classify_stint_phase(
    lap_numbers: np.ndarray,
) -> np.ndarray:
    """Classify each sample as "early", "mid", or "late" in the stint.

    Uses absolute lap number as a proxy. A proper stint detector would
    use fuel/tire-change events, but for v1 this is sufficient.
    """
    phase = np.full(len(lap_numbers), "mid", dtype=object)
    phase[lap_numbers <= _EARLY_STINT_LAPS] = "early"
    phase[lap_numbers > _LATE_STINT_LAPS] = "late"
    return phase


def assign_bucket_keys(
    bank_rad: np.ndarray,
    transition_mask: np.ndarray,
    lap_numbers: np.ndarray,
) -> np.ndarray:
    """Assign a BucketKey to each sample.

    Returns an object array of BucketKey instances.
    """
    section = classify_section_regime(bank_rad, transition_mask)
    phase = classify_stint_phase(lap_numbers)

    N = len(bank_rad)
    keys = np.empty(N, dtype=object)
    for i in range(N):
        if section[i] == "transition":
            keys[i] = TRANSITION_BUCKET
        else:
            keys[i] = BucketKey(str(section[i]), str(phase[i]))
    return keys


# ── Query result ─────────────────────────────────────────────


@dataclass
class BucketQueryResult:
    """Result of a bucketed surface-field query."""
    mean: float
    std: float
    confidence: float
    bucket_used: BucketKey
    fallback_depth: int       # 0 = exact, 1 = section-only, 2 = global
    evidence_count: int


# ── Bucketed field manager ───────────────────────────────────


class BucketedSurfaceField:
    """Maintains independent SurfaceFields per condition bucket.

    Updates go ONLY to the correct bucket. Queries resolve through
    the fallback hierarchy when the exact bucket is sparse.
    """

    def __init__(
        self,
        s_bins: np.ndarray,
        n_bins: np.ndarray,
        field_config: SurfaceFieldConfig | None = None,
    ):
        self.s_bins = s_bins
        self.n_bins = n_bins
        self.field_config = field_config or SurfaceFieldConfig()

        # One SurfaceField per active bucket
        self.fields: dict[BucketKey, SurfaceField] = {}
        for key in ACTIVE_BUCKETS:
            self.fields[key] = SurfaceField(s_bins, n_bins, self.field_config)

    def update(
        self,
        s: np.ndarray,
        n: np.ndarray,
        lambda_vals: np.ndarray,
        confidence: np.ndarray,
        bucket_keys: np.ndarray,     # object array of BucketKey
        obs_variance: float = 0.04,
    ) -> dict[BucketKey, int]:
        """Route updates to the correct bucket fields.

        Transition samples are silently dropped (never update any field).
        Returns count of observations per bucket.
        """
        counts: dict[BucketKey, int] = {}

        for key in ACTIVE_BUCKETS:
            mask = np.array([k == key for k in bucket_keys]) & np.isfinite(lambda_vals)
            if mask.sum() == 0:
                counts[key] = 0
                continue

            n_fed = self.fields[key].update_batch(
                s[mask], n[mask], lambda_vals[mask], confidence[mask],
                obs_variance=obs_variance,
            )
            counts[key] = n_fed

        return counts

    def apply_spatial_smoothing(self) -> None:
        """Smooth all bucket fields independently."""
        for field in self.fields.values():
            field.apply_spatial_smoothing()

    def query(
        self,
        s: float,
        n: float,
        bucket: BucketKey,
        min_confidence_for_exact: float = 0.05,
    ) -> BucketQueryResult:
        """Query with fallback hierarchy.

        1. Exact bucket
        2. Same section_regime, any stint_phase (merge all phases)
        3. Global prior
        """
        # Level 0: exact bucket
        if bucket in self.fields:
            field = self.fields[bucket]
            mean, std, conf = field.query(s, n)
            si, ni = field._cell_index(s, n)
            n_obs = int(field.n_obs[si, ni])
            if conf >= min_confidence_for_exact:
                return BucketQueryResult(
                    mean=mean, std=std, confidence=conf,
                    bucket_used=bucket, fallback_depth=0,
                    evidence_count=n_obs,
                )

        # Level 1: same section, any stint phase
        section_fields = [
            self.fields[k] for k in ACTIVE_BUCKETS
            if k.section_regime == bucket.section_regime and k in self.fields
        ]
        if section_fields:
            means, stds, confs, n_obss = [], [], [], []
            for f in section_fields:
                m, st, c = f.query(s, n)
                si, ni = f._cell_index(s, n)
                means.append(m)
                stds.append(st)
                confs.append(c)
                n_obss.append(int(f.n_obs[si, ni]))

            confs_arr = np.array(confs)
            if confs_arr.sum() > min_confidence_for_exact:
                # Confidence-weighted merge across stint phases
                w = confs_arr / max(confs_arr.sum(), 1e-9)
                merged_mean = float(np.sum(np.array(means) * w))
                merged_std = float(np.sqrt(np.sum(np.array(stds) ** 2 * w)))
                merged_conf = float(confs_arr.max() * 0.8)  # slight penalty for merging
                total_obs = sum(n_obss)

                return BucketQueryResult(
                    mean=merged_mean, std=merged_std, confidence=merged_conf,
                    bucket_used=BucketKey(bucket.section_regime, "merged"),
                    fallback_depth=1, evidence_count=total_obs,
                )

        # Level 2: global prior
        return BucketQueryResult(
            mean=self.field_config.prior_mean,
            std=self.field_config.prior_std,
            confidence=0.0,
            bucket_used=BucketKey("global", "prior"),
            fallback_depth=2,
            evidence_count=0,
        )

    def summary(self) -> dict:
        """Per-bucket summary statistics."""
        result = {}
        for key in ACTIVE_BUCKETS:
            f = self.fields[key]
            s = f.summary()
            result[str(key)] = {
                "cells_observed": s["cells_observed"],
                "mean_lambda": s["mean_lambda_observed"],
                "mean_confidence": s["mean_confidence"],
                "coverage_pct": s["coverage_pct"],
            }
        return result

    def diagnostics(self) -> dict:
        """Detailed diagnostics for all buckets."""
        diag = {}
        for key in ACTIVE_BUCKETS:
            f = self.fields[key]
            observed = f.n_obs > 0
            if observed.any():
                vals = f.mean[observed]
                diag[str(key)] = {
                    "n_cells": int(observed.sum()),
                    "lambda_mean": round(float(vals.mean()), 4),
                    "lambda_std": round(float(vals.std()), 4),
                    "lambda_p5": round(float(np.percentile(vals, 5)), 4),
                    "lambda_p95": round(float(np.percentile(vals, 95)), 4),
                    "confidence_mean": round(float(f.confidence_map[observed].mean()), 4),
                }
            else:
                diag[str(key)] = {"n_cells": 0, "lambda_mean": None}
        return diag
