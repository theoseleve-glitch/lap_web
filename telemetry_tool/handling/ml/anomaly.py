"""Mahalanobis distance-based anomaly detector for handling patterns.

Numpy-only implementation -- no sklearn or scipy dependency.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class HandlingAnomalyDetector:
    """Detects unusual handling patterns via Mahalanobis distance.

    Trained on "normal" corners only.  Corners far from the normal
    distribution are flagged as anomalous (potential handling issues).
    """

    def __init__(self, contamination: float = 0.1) -> None:
        if not 0.0 < contamination < 1.0:
            raise ValueError("contamination must be in (0, 1)")
        self.contamination = contamination
        self.mean: Optional[np.ndarray] = None           # (d,)
        self.cov_inv: Optional[np.ndarray] = None        # (d, d)
        self.threshold: Optional[float] = None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, X_normal: np.ndarray) -> "HandlingAnomalyDetector":
        """Fit on normal (non-anomalous) corners only.

        Computes mean, inverse covariance (regularised), and sets the
        detection threshold at the ``(1 - contamination)`` percentile
        of training Mahalanobis distances.
        """
        if X_normal.ndim != 2:
            raise ValueError("X_normal must be 2-D")
        n, d = X_normal.shape
        if n < 2:
            raise ValueError("Need at least 2 samples to compute covariance")

        self.mean = np.mean(X_normal, axis=0)

        # Regularised covariance
        cov = np.cov(X_normal.T)
        if cov.ndim == 0:
            # Single feature edge case
            cov = np.array([[float(cov)]])
        cov += np.eye(d) * 1e-6
        self.cov_inv = np.linalg.inv(cov)

        # Set threshold from training distances
        distances = self.score_samples(X_normal)
        self.threshold = float(
            np.percentile(distances, (1.0 - self.contamination) * 100)
        )

        logger.info(
            "HandlingAnomalyDetector fitted: %d samples, %d features, "
            "threshold=%.4f",
            n, d, self.threshold,
        )
        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def score_samples(self, X: np.ndarray) -> np.ndarray:
        """Return Mahalanobis distance for each sample.

        ``d(x) = sqrt((x - mu)^T  Sigma^{-1}  (x - mu))``
        """
        self._check_fitted()
        X = np.atleast_2d(X)
        diff = X - self.mean
        # Efficient per-row Mahalanobis: sum of element-wise (diff @ Sigma_inv) * diff
        left = diff @ self.cov_inv
        mahal_sq = np.sum(left * diff, axis=1)
        # Clamp tiny negatives from floating-point noise
        mahal_sq = np.maximum(mahal_sq, 0.0)
        return np.sqrt(mahal_sq)

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return 1 for anomaly, 0 for normal."""
        distances = self.score_samples(X)
        return (distances > self.threshold).astype(int)

    def decision_function(self, X: np.ndarray) -> np.ndarray:
        """Return signed anomaly score (positive = more anomalous).

        Score is ``distance - threshold`` so positive values are anomalies.
        """
        return self.score_samples(X) - self.threshold

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save model parameters to a JSON file."""
        self._check_fitted()
        data = {
            "contamination": self.contamination,
            "mean": self.mean.tolist(),
            "cov_inv": self.cov_inv.tolist(),
            "threshold": self.threshold,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("HandlingAnomalyDetector saved to %s", path)

    @classmethod
    def load(cls, path: str) -> "HandlingAnomalyDetector":
        """Load model parameters from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        model = cls(contamination=data["contamination"])
        model.mean = np.array(data["mean"])
        model.cov_inv = np.array(data["cov_inv"])
        model.threshold = data["threshold"]
        logger.info("HandlingAnomalyDetector loaded from %s", path)
        return model

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_fitted(self) -> None:
        if self.mean is None:
            raise RuntimeError("Model has not been fitted yet")
