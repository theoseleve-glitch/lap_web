"""Gaussian Naive Bayes classifier for handling event classification.

Numpy-only implementation -- no sklearn dependency.
"""

from __future__ import annotations

import json
import logging
from typing import Dict

import numpy as np

logger = logging.getLogger(__name__)


class GaussianNB:
    """Gaussian Naive Bayes for handling event classification.

    Classes: understeer (+1), oversteer (-1), neutral (0).
    Features: 32 detector outputs + 5 metadata = 37 features.
    """

    def __init__(self) -> None:
        self.classes = [-1, 0, 1]
        self.means: Dict[int, np.ndarray] = {}
        self.variances: Dict[int, np.ndarray] = {}
        self.priors: Dict[int, float] = {}

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray) -> "GaussianNB":
        """Train on feature matrix *X* (n_samples x n_features) and labels *y*.

        Computes per-class mean, variance, and prior probability.
        """
        if X.ndim != 2 or y.ndim != 1:
            raise ValueError("X must be 2-D and y must be 1-D")
        if len(X) != len(y):
            raise ValueError("X and y must have the same number of samples")
        if len(X) == 0:
            raise ValueError("Cannot fit on empty data")

        for c in self.classes:
            mask = y == c
            if mask.sum() == 0:
                continue
            X_c = X[mask]
            self.means[c] = np.mean(X_c, axis=0)
            self.variances[c] = np.var(X_c, axis=0) + 1e-9  # avoid zero variance
            self.priors[c] = float(mask.sum()) / len(y)

        if not self.means:
            raise ValueError("No valid classes found in y")

        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _log_likelihoods(self, X: np.ndarray) -> np.ndarray:
        """Return (n_samples, n_classes) matrix of log-likelihoods.

        For each class c and sample x the log-likelihood is:
            -0.5 * sum(log(2*pi*var) + (x - mean)^2 / var) + log(prior)
        """
        trained = sorted(self.means.keys())
        n = X.shape[0]
        ll = np.full((n, len(trained)), -np.inf)
        for idx, c in enumerate(trained):
            mean = self.means[c]
            var = self.variances[c]
            log_prior = np.log(self.priors[c])
            # Vectorised over samples
            diff = X - mean
            ll[:, idx] = (
                -0.5 * np.sum(np.log(2.0 * np.pi * var) + diff ** 2 / var, axis=1)
                + log_prior
            )
        return ll

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict class label for each row in *X*."""
        self._check_fitted()
        X = np.atleast_2d(X)
        ll = self._log_likelihoods(X)
        trained = sorted(self.means.keys())
        indices = np.argmax(ll, axis=1)
        return np.array([trained[i] for i in indices])

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return (n_samples, n_classes) probability matrix.

        Columns correspond to ``sorted(self.means.keys())``.
        """
        self._check_fitted()
        X = np.atleast_2d(X)
        ll = self._log_likelihoods(X)
        # Log-sum-exp trick for numerical stability
        max_ll = np.max(ll, axis=1, keepdims=True)
        exp_ll = np.exp(ll - max_ll)
        proba = exp_ll / np.sum(exp_ll, axis=1, keepdims=True)
        return proba

    def score(self, X: np.ndarray, y: np.ndarray) -> float:
        """Return classification accuracy on *X* / *y*."""
        preds = self.predict(X)
        return float(np.mean(preds == y))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save model parameters to a JSON file."""
        self._check_fitted()
        data = {
            "classes": self.classes,
            "means": {str(k): v.tolist() for k, v in self.means.items()},
            "variances": {str(k): v.tolist() for k, v in self.variances.items()},
            "priors": {str(k): v for k, v in self.priors.items()},
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("GaussianNB saved to %s", path)

    @classmethod
    def load(cls, path: str) -> "GaussianNB":
        """Load model parameters from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        model = cls()
        model.classes = data["classes"]
        model.means = {int(k): np.array(v) for k, v in data["means"].items()}
        model.variances = {int(k): np.array(v) for k, v in data["variances"].items()}
        model.priors = {int(k): v for k, v in data["priors"].items()}
        logger.info("GaussianNB loaded from %s", path)
        return model

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_fitted(self) -> None:
        if not self.means:
            raise RuntimeError("Model has not been fitted yet")
