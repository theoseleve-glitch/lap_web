"""
Tire parameter fitting from curated high-confidence telemetry.

v1 scope: fit a single LATERAL D SCALE FACTOR.

    D_lat_fitted = k_lat × D_lat_default

This absorbs the systematic bias between the default tire peak and the
actual session data, without touching Pacejka shape (B, C, E), combined
slip, or load sensitivity.

The fit uses only curated samples from flat, high-confidence cornering
zones where road-state contamination is minimal. Train/validation split
is by odd/even laps (not random rows) to test generalization.

Explicitly NOT fitted:
- Longitudinal D (no kappa available)
- Pacejka B, C, E shape parameters
- Combined-slip interaction
- Roll compliance
- Road lambda (that's the surface field's job)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from scipy.optimize import minimize_scalar

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665


# ── Curation ─────────────────────────────────────────────────


@dataclass
class CurationConfig:
    """Thresholds for selecting calibration samples."""
    max_bank_rad: float = 0.05       # ~3 degrees — flat sections only
    max_bank_gradient: float = 0.005  # stable bank (not transitioning)
    min_a_lat_tire: float = 3.0      # moderate lateral excitation
    min_speed: float = 15.0          # good kinematic quality
    min_beta_quality: float = 0.15   # from beta estimator
    min_road_quality: float = 0.3    # from road state estimator
    min_fz: float = 1500.0           # no wheel-unload artefacts
    max_alpha: float = 0.30          # within linear-ish tire range
    not_quarantined: bool = True     # exclude transition-quarantined samples


@dataclass
class CurationResult:
    """Result of the data curation step."""
    mask: np.ndarray              # (N,) bool — True = included in calibration set
    n_total: int
    n_selected: int
    exclusion_reasons: dict[str, int]  # reason → count of excluded samples


def curate_calibration_set(
    *,
    bank_rad: np.ndarray,
    bank_gradient: np.ndarray,
    a_lat_tire: np.ndarray,
    speed: np.ndarray,
    beta_quality: np.ndarray,
    road_quality: np.ndarray,
    fz_per_wheel: np.ndarray,       # (N, 4)
    alpha_per_wheel: np.ndarray,    # (N, 4)
    transition_mask: np.ndarray,    # (N,) bool — True = quarantined
    config: CurationConfig | None = None,
) -> CurationResult:
    """Select samples suitable for tire-model calibration.

    Only flat, high-confidence, well-excited cornering samples pass.
    Returns a boolean mask and diagnostics.
    """
    if config is None:
        config = CurationConfig()

    N = len(speed)
    mask = np.ones(N, dtype=bool)
    reasons: dict[str, int] = {}

    def _exclude(reason: str, cond: np.ndarray) -> None:
        n_before = mask.sum()
        mask[cond] = False
        n_after = mask.sum()
        reasons[reason] = int(n_before - n_after)

    # Flat sections only
    _exclude("high_bank", np.abs(bank_rad) > config.max_bank_rad)
    _exclude("bank_transition", np.abs(bank_gradient) > config.max_bank_gradient)

    # Excitation
    _exclude("low_lateral", np.abs(a_lat_tire) < config.min_a_lat_tire)
    _exclude("low_speed", speed < config.min_speed)

    # Upstream quality
    _exclude("low_beta_quality", beta_quality < config.min_beta_quality)
    _exclude("low_road_quality", road_quality < config.min_road_quality)

    # Per-wheel validity
    fz_min_per_sample = fz_per_wheel.min(axis=1)
    _exclude("low_fz", fz_min_per_sample < config.min_fz)

    alpha_max_per_sample = np.abs(alpha_per_wheel).max(axis=1)
    _exclude("high_alpha", alpha_max_per_sample > config.max_alpha)

    # Transition quarantine
    if config.not_quarantined:
        _exclude("quarantined", transition_mask)

    return CurationResult(
        mask=mask,
        n_total=N,
        n_selected=int(mask.sum()),
        exclusion_reasons=reasons,
    )


# ── Fitting ──────────────────────────────────────────────────


@dataclass
class FitResult:
    """Result of the tire parameter fitting."""
    k_lat: float                    # fitted lateral D scale factor
    k_lat_std: float                # uncertainty estimate
    residual_before: float          # mean |lambda - 1.0| before fit
    residual_after: float           # mean |lambda - 1.0| after fit
    n_train: int
    n_validation: int
    train_median_lambda_before: float
    train_median_lambda_after: float
    validation_median_lambda_before: float
    validation_median_lambda_after: float
    identifiability_note: str = ""

    def to_dict(self) -> dict:
        return {
            "k_lat": round(self.k_lat, 4),
            "k_lat_std": round(self.k_lat_std, 4),
            "residual_before": round(self.residual_before, 4),
            "residual_after": round(self.residual_after, 4),
            "n_train": self.n_train,
            "n_validation": self.n_validation,
            "train_median_before": round(self.train_median_lambda_before, 4),
            "train_median_after": round(self.train_median_lambda_after, 4),
            "val_median_before": round(self.validation_median_lambda_before, 4),
            "val_median_after": round(self.validation_median_lambda_after, 4),
            "identifiability_note": self.identifiability_note,
        }


def fit_lateral_d_scale(
    *,
    lambda_raw: np.ndarray,         # (N,) raw lambda from inverse solver
    confidence: np.ndarray,         # (N,) inverse solver confidence
    curation_mask: np.ndarray,      # (N,) bool from curate_calibration_set
    lap_numbers: np.ndarray,        # (N,) for train/val split
) -> FitResult:
    """Fit a single lateral D scale factor k_lat.

    The goal: find k_lat such that lambda_corrected = lambda_raw / k_lat
    has median ≈ 1.0 on the curated anchor set.

    Equivalently: k_lat = median(lambda_raw) on the curated set.

    This is the simplest possible "fit" — a robust location estimator
    of the systematic bias. No optimizer needed; the median IS the answer.
    We use minimize_scalar on a Huber loss only to get the uncertainty
    estimate from the curvature.

    Train/validation split: odd laps = train, even laps = validation.
    """
    # Apply curation + finite lambda filter
    valid = curation_mask & np.isfinite(lambda_raw) & (confidence > 0.1)
    if valid.sum() < 50:
        return FitResult(
            k_lat=1.0, k_lat_std=0.5,
            residual_before=0.0, residual_after=0.0,
            n_train=0, n_validation=0,
            train_median_lambda_before=0.0,
            train_median_lambda_after=0.0,
            validation_median_lambda_before=0.0,
            validation_median_lambda_after=0.0,
            identifiability_note="Insufficient curated samples (< 50)",
        )

    lam_valid = lambda_raw[valid]
    conf_valid = confidence[valid]
    laps_valid = lap_numbers[valid]

    # Train/validation split: odd laps → train, even → validation
    unique_laps = np.unique(laps_valid)
    train_laps = set(unique_laps[unique_laps % 2 == 1])
    val_laps = set(unique_laps[unique_laps % 2 == 0])

    train_mask = np.array([int(l) in train_laps for l in laps_valid])
    val_mask = ~train_mask

    lam_train = lam_valid[train_mask]
    lam_val = lam_valid[val_mask]
    conf_train = conf_valid[train_mask]

    if len(lam_train) < 20:
        return FitResult(
            k_lat=float(np.median(lam_valid)), k_lat_std=0.3,
            residual_before=float(np.abs(lam_valid - 1.0).mean()),
            residual_after=0.0,
            n_train=len(lam_train), n_validation=len(lam_val),
            train_median_lambda_before=float(np.median(lam_train)),
            train_median_lambda_after=1.0,
            validation_median_lambda_before=float(np.median(lam_val)) if len(lam_val) > 0 else 0.0,
            validation_median_lambda_after=0.0,
            identifiability_note="Small train set — using simple median",
        )

    # ── Primary estimator: confidence-weighted median ────────
    # The median is optimally robust to up to 50% contamination.
    # We use a weighted median where confidence is the weight.
    order = np.argsort(lam_train)
    lam_sorted = lam_train[order]
    conf_sorted = conf_train[order]
    cum_weight = np.cumsum(conf_sorted)
    total_weight = cum_weight[-1]
    median_idx = int(np.searchsorted(cum_weight, total_weight * 0.5))
    median_idx = min(median_idx, len(lam_sorted) - 1)
    k_lat = float(lam_sorted[median_idx])

    # Clamp to physical range
    k_lat = float(np.clip(k_lat, 0.5, 3.0))

    # ── Uncertainty: IQR-based (robust) ──────────────────────
    q25_idx = int(np.searchsorted(cum_weight, total_weight * 0.25))
    q75_idx = int(np.searchsorted(cum_weight, total_weight * 0.75))
    q25_idx = min(q25_idx, len(lam_sorted) - 1)
    q75_idx = min(q75_idx, len(lam_sorted) - 1)
    iqr = float(lam_sorted[q75_idx] - lam_sorted[q25_idx])
    # MAD-based std estimate: std ≈ IQR / 1.35 for normal
    k_lat_std = max(iqr / 1.35, 0.01)

    # ── Before/after metrics ─────────────────────────────────
    train_before = float(np.median(lam_train))
    train_after = float(np.median(lam_train / k_lat))
    val_before = float(np.median(lam_val)) if len(lam_val) > 0 else 0.0
    val_after = float(np.median(lam_val / k_lat)) if len(lam_val) > 0 else 0.0

    residual_before = float(np.abs(lam_valid - 1.0).mean())
    residual_after = float(np.abs(lam_valid / k_lat - 1.0).mean())

    # ── Identifiability check ────────────────────────────────
    # If train and validation disagree by > 20%, the fit is not generalizing
    note = ""
    if len(lam_val) > 10:
        if abs(train_before - val_before) / max(train_before, 0.1) > 0.20:
            note = "WARNING: train/val lambda medians differ by > 20% — fit may not generalize"
        elif abs(train_after - val_after) > 0.15:
            note = "NOTE: validation median after fit is {:.3f} (ideally ~1.0)".format(val_after)
    if len(lam_train) < 100:
        note += " Small training set — interpret with caution."

    return FitResult(
        k_lat=k_lat,
        k_lat_std=k_lat_std,
        residual_before=residual_before,
        residual_after=residual_after,
        n_train=len(lam_train),
        n_validation=len(lam_val),
        train_median_lambda_before=train_before,
        train_median_lambda_after=train_after,
        validation_median_lambda_before=val_before,
        validation_median_lambda_after=val_after,
        identifiability_note=note,
    )


def apply_d_scale(
    current_d1_lat: float,
    k_lat: float,
) -> float:
    """Apply the fitted scale factor to get the new D parameter."""
    return current_d1_lat * k_lat
