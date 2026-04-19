"""
Spatial Bayesian surface friction field — lambda_surface(s, n) with
mean, variance, and spatial correlation.

Unlike the per-cell p95 approach, adjacent cells share information
through a spatial prior. Observing grip at one apex cell improves
the estimate at nearby cells, weighted by distance.

The field maintains:
  - Per-cell posterior mean and variance
  - Evidence count and recency per cell
  - Spatial smoothing via a Gaussian kernel (approximating a GP posterior)

Updates occur ONLY when the inverse solver provides a confident lambda
estimate (excitation-gated). Between updates, variance grows (uncertainty
increases with time since last observation).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from scipy.ndimage import gaussian_filter

logger = logging.getLogger(__name__)

_DEFAULT_PRIOR_MEAN: Final[float] = 1.0   # clean dry asphalt
_DEFAULT_PRIOR_STD: Final[float] = 0.25   # moderate uncertainty before any data
_VARIANCE_DECAY_RATE: Final[float] = 0.001  # variance grows by this per sample without update
_SPATIAL_KERNEL_SIGMA_BINS: Final[float] = 2.0  # Gaussian kernel width in grid cells (~4-10m)
_MIN_CONFIDENCE_FOR_UPDATE: Final[float] = 0.15


@dataclass
class SurfaceFieldConfig:
    """Configuration for the surface field."""
    prior_mean: float = _DEFAULT_PRIOR_MEAN
    prior_std: float = _DEFAULT_PRIOR_STD
    variance_decay_rate: float = _VARIANCE_DECAY_RATE
    spatial_kernel_sigma: float = _SPATIAL_KERNEL_SIGMA_BINS
    min_confidence: float = _MIN_CONFIDENCE_FOR_UPDATE
    # Condition bucketing
    condition_label: str = "dry"     # for multi-condition tracking
    compound_label: str = "unknown"


@dataclass
class CellState:
    """Bayesian state for one (s, n) cell."""
    mean: float
    variance: float
    n_observations: int = 0
    last_update_idx: int = -1      # sample index of last update
    total_confidence: float = 0.0  # sum of confidences from all updates


class SurfaceField:
    """2D Bayesian field of lambda_surface with spatial correlation.

    Stores mean and variance per (s, n) cell. Updates are Kalman-like:
    new observation shifts the mean and shrinks the variance. Between
    observations, variance grows (representing increasing uncertainty
    about whether the surface has changed).

    Spatial correlation is applied after each batch of updates via a
    Gaussian smoothing pass on the INNOVATION (change from prior),
    not on the raw posterior — so well-observed cells don't get diluted
    by their poorly-observed neighbors.
    """

    def __init__(
        self,
        s_bins: np.ndarray,
        n_bins: np.ndarray,
        config: SurfaceFieldConfig | None = None,
    ):
        self.s_bins = s_bins
        self.n_bins = n_bins
        self.config = config or SurfaceFieldConfig()
        self.M = len(s_bins) - 1
        self.K = len(n_bins) - 1

        # Initialize prior
        self.mean = np.full((self.M, self.K), self.config.prior_mean, dtype=np.float64)
        self.variance = np.full((self.M, self.K), self.config.prior_std ** 2, dtype=np.float64)
        self.n_obs = np.zeros((self.M, self.K), dtype=np.int32)
        self.last_update = np.full((self.M, self.K), -1, dtype=np.int64)
        self.total_confidence = np.zeros((self.M, self.K), dtype=np.float64)

    @property
    def std(self) -> np.ndarray:
        """Per-cell standard deviation."""
        return np.sqrt(self.variance)

    @property
    def confidence_map(self) -> np.ndarray:
        """Per-cell confidence: inverse of normalized variance (0→1)."""
        max_var = self.config.prior_std ** 2
        return np.clip(1.0 - self.variance / max_var, 0.0, 1.0)

    def _cell_index(self, s: float, n: float) -> tuple[int, int]:
        """Map (s, n) to grid indices."""
        si = int(np.clip(np.searchsorted(self.s_bins, s) - 1, 0, self.M - 1))
        ni = int(np.clip(np.searchsorted(self.n_bins, n) - 1, 0, self.K - 1))
        return si, ni

    # ── Single-cell Kalman update ────────────────────────────

    def update_cell(
        self,
        s: float,
        n: float,
        lambda_obs: float,
        obs_variance: float,
        confidence: float,
        sample_idx: int = 0,
    ) -> None:
        """Bayesian update of one cell from one observation.

        Uses Kalman filter equations:
            K = prior_var / (prior_var + obs_var)
            mean_new = mean_old + K × (lambda_obs - mean_old)
            var_new = (1 - K) × prior_var

        The observation variance is modulated by confidence:
        lower confidence → higher obs_variance → smaller Kalman gain →
        less influence on the posterior.
        """
        if confidence < self.config.min_confidence:
            return

        si, ni = self._cell_index(s, n)

        # Observation variance: inversely proportional to confidence
        # High confidence → low obs_variance → large Kalman gain
        obs_var_effective = obs_variance / max(confidence, 0.01)

        prior_var = self.variance[si, ni]
        prior_mean = self.mean[si, ni]

        # Kalman gain
        K = prior_var / (prior_var + obs_var_effective)

        # Update
        self.mean[si, ni] = prior_mean + K * (lambda_obs - prior_mean)
        self.variance[si, ni] = (1.0 - K) * prior_var
        self.n_obs[si, ni] += 1
        self.last_update[si, ni] = sample_idx
        self.total_confidence[si, ni] += confidence

    # ── Batch update ─────────────────────────────────────────

    def update_batch(
        self,
        s_arr: np.ndarray,
        n_arr: np.ndarray,
        lambda_arr: np.ndarray,
        confidence_arr: np.ndarray,
        obs_variance: float = 0.04,  # default observation noise variance
        sample_idx_start: int = 0,
    ) -> int:
        """Update multiple cells from a batch of lambda observations.

        Only processes samples where lambda is not NaN and confidence
        exceeds the minimum threshold.

        Returns number of cells updated.
        """
        valid = (
            np.isfinite(lambda_arr)
            & (confidence_arr >= self.config.min_confidence)
        )
        n_valid = valid.sum()
        if n_valid == 0:
            return 0

        s_v = s_arr[valid]
        n_v = n_arr[valid]
        l_v = lambda_arr[valid]
        c_v = confidence_arr[valid]

        for i in range(n_valid):
            self.update_cell(
                s=float(s_v[i]),
                n=float(n_v[i]),
                lambda_obs=float(l_v[i]),
                obs_variance=obs_variance,
                confidence=float(c_v[i]),
                sample_idx=sample_idx_start + i,
            )

        return int(n_valid)

    # ── Variance decay (time-dependent uncertainty growth) ───

    def decay_variance(self, n_samples_elapsed: int = 1) -> None:
        """Increase variance for cells that haven't been updated recently.

        This models the fact that surface conditions can change (rubber
        wears off, temperature shifts, moisture). Cells with recent
        observations keep their low variance; stale cells get more uncertain.
        """
        growth = self.config.variance_decay_rate * n_samples_elapsed
        max_var = self.config.prior_std ** 2
        self.variance = np.minimum(self.variance + growth, max_var)

    # ── Spatial smoothing ────────────────────────────────────

    def apply_spatial_smoothing(self) -> None:
        """Share information between neighboring cells via Gaussian smoothing.

        Smooths the INNOVATION (mean - prior_mean) rather than the raw mean,
        so well-observed cells aren't diluted by uninformed neighbors.
        Then blends the smoothed innovation back proportionally to confidence.
        """
        sigma = self.config.spatial_kernel_sigma
        if sigma < 0.1:
            return

        innovation = self.mean - self.config.prior_mean
        conf = self.confidence_map

        # Smooth the innovation weighted by confidence
        weighted_innov = innovation * conf
        weight_sum = gaussian_filter(conf, sigma=sigma, mode="nearest")
        smoothed_innov = gaussian_filter(weighted_innov, sigma=sigma, mode="nearest")

        # Avoid division by zero
        safe_weight = np.maximum(weight_sum, 1e-6)
        smoothed_innov /= safe_weight

        # Blend: cells with high local confidence keep their own value;
        # cells with low confidence adopt the smoothed neighborhood value.
        blend_factor = np.clip(1.0 - conf, 0.0, 1.0)  # 0 = keep own, 1 = use smoothed
        self.mean = self.config.prior_mean + (
            innovation * (1.0 - blend_factor) + smoothed_innov * blend_factor
        )

        # Also smooth the variance slightly — poorly-observed cells
        # inherit some confidence from their well-observed neighbors
        self.variance = gaussian_filter(self.variance, sigma=sigma * 0.5, mode="nearest")

    # ── Queries ──────────────────────────────────────────────

    def query(self, s: float, n: float) -> tuple[float, float, float]:
        """Query the field at a point. Returns (mean, std, confidence)."""
        si, ni = self._cell_index(s, n)
        return (
            float(self.mean[si, ni]),
            float(np.sqrt(self.variance[si, ni])),
            float(self.confidence_map[si, ni]),
        )

    def query_batch(
        self, s_arr: np.ndarray, n_arr: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Batch query. Returns (means, stds, confidences)."""
        si = np.clip(np.searchsorted(self.s_bins, s_arr) - 1, 0, self.M - 1).astype(int)
        ni = np.clip(np.searchsorted(self.n_bins, n_arr) - 1, 0, self.K - 1).astype(int)
        return (
            self.mean[si, ni],
            np.sqrt(self.variance[si, ni]),
            self.confidence_map[si, ni],
        )

    # ── Diagnostics ──────────────────────────────────────────

    def summary(self) -> dict:
        """Summary statistics for the field."""
        observed = self.n_obs > 0
        return {
            "grid_shape": (self.M, self.K),
            "cells_observed": int(observed.sum()),
            "cells_total": self.M * self.K,
            "coverage_pct": float(observed.sum() / max(self.M * self.K, 1) * 100),
            "mean_lambda_observed": float(self.mean[observed].mean()) if observed.any() else None,
            "std_lambda_observed": float(self.std[observed].mean()) if observed.any() else None,
            "mean_lambda_all": float(self.mean.mean()),
            "mean_confidence": float(self.confidence_map.mean()),
            "max_observations_per_cell": int(self.n_obs.max()),
            "condition": self.config.condition_label,
            "compound": self.config.compound_label,
        }

    def to_export_dict(self) -> dict:
        """JSON-serializable export for visualization."""
        return {
            "s_bins": [round(float(v), 1) for v in self.s_bins],
            "n_bins": [round(float(v), 1) for v in self.n_bins],
            "mean": [[round(float(v), 4) for v in row] for row in self.mean],
            "std": [[round(float(v), 4) for v in row] for row in self.std],
            "confidence": [[round(float(v), 3) for v in row] for row in self.confidence_map],
            "n_observations": [[int(v) for v in row] for row in self.n_obs],
            "summary": self.summary(),
        }
