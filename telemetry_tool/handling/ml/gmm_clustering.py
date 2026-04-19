"""Gaussian Mixture Model for unsupervised corner clustering.

Numpy-only implementation with diagonal covariance and EM algorithm.
No sklearn dependency.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


class GMMClustering:
    """Gaussian Mixture Model for handling archetype discovery.

    Clusters corners into *k* groups by their detector feature vectors.
    Each cluster represents a handling archetype (e.g. "entry understeer",
    "exit oversteer", "neutral", etc.).

    Uses diagonal covariance for stability and speed.
    """

    def __init__(
        self,
        n_components: int = 5,
        max_iter: int = 100,
        tol: float = 1e-4,
        n_restarts: int = 3,
        random_state: Optional[int] = None,
    ) -> None:
        self.n_components = n_components
        self.max_iter = max_iter
        self.tol = tol
        self.n_restarts = n_restarts
        self.random_state = random_state

        self.means: Optional[np.ndarray] = None       # (k, d)
        self.covariances: Optional[np.ndarray] = None  # (k, d) diagonal
        self.weights: Optional[np.ndarray] = None      # (k,)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, X: np.ndarray) -> "GMMClustering":
        """Fit GMM using EM with random restarts, keeping best log-likelihood."""
        if X.ndim != 2:
            raise ValueError("X must be 2-D")
        n, d = X.shape
        if n < self.n_components:
            raise ValueError(
                f"Need at least {self.n_components} samples, got {n}"
            )

        rng = np.random.RandomState(self.random_state)
        best_ll = -np.inf

        for restart in range(self.n_restarts):
            means, covs, weights = self._init_params(X, rng)
            prev_ll = -np.inf

            for it in range(self.max_iter):
                # E-step
                resp = self._e_step(X, means, covs, weights)

                # M-step
                means, covs, weights = self._m_step(X, resp)

                # Check convergence
                ll = self._log_likelihood(X, means, covs, weights)
                if abs(ll - prev_ll) < self.tol:
                    logger.debug(
                        "Restart %d converged at iteration %d (ll=%.4f)",
                        restart, it, ll,
                    )
                    break
                prev_ll = ll

            if ll > best_ll:
                best_ll = ll
                self.means = means.copy()
                self.covariances = covs.copy()
                self.weights = weights.copy()

        logger.info(
            "GMM fitted: %d components, best log-likelihood=%.4f",
            self.n_components, best_ll,
        )
        return self

    def _init_params(
        self, X: np.ndarray, rng: np.random.RandomState
    ) -> tuple:
        """Initialise parameters by picking random data points as means."""
        n, d = X.shape
        indices = rng.choice(n, size=self.n_components, replace=False)
        means = X[indices].copy()
        covs = np.full((self.n_components, d), np.var(X, axis=0) + 1e-6)
        weights = np.full(self.n_components, 1.0 / self.n_components)
        return means, covs, weights

    def _e_step(
        self,
        X: np.ndarray,
        means: np.ndarray,
        covs: np.ndarray,
        weights: np.ndarray,
    ) -> np.ndarray:
        """Compute responsibilities (n_samples x k)."""
        n = X.shape[0]
        log_resp = np.zeros((n, self.n_components))
        for k in range(self.n_components):
            log_resp[:, k] = (
                np.log(weights[k] + 1e-300)
                + self._log_gaussian(X, means[k], covs[k])
            )
        # Log-sum-exp for normalisation
        max_log = np.max(log_resp, axis=1, keepdims=True)
        log_resp -= max_log
        resp = np.exp(log_resp)
        resp /= np.sum(resp, axis=1, keepdims=True) + 1e-300
        return resp

    def _m_step(
        self, X: np.ndarray, resp: np.ndarray
    ) -> tuple:
        """Update means, covariances, and weights from responsibilities."""
        n, d = X.shape
        Nk = np.sum(resp, axis=0)  # (k,)
        Nk_safe = np.maximum(Nk, 1e-300)

        weights = Nk / n
        means = (resp.T @ X) / Nk_safe[:, None]

        covs = np.zeros((self.n_components, d))
        for k in range(self.n_components):
            diff = X - means[k]
            covs[k] = (resp[:, k:k+1] * diff ** 2).sum(axis=0) / Nk_safe[k]
        covs += 1e-6  # regularise

        return means, covs, weights

    @staticmethod
    def _log_gaussian(
        X: np.ndarray, mean: np.ndarray, var: np.ndarray
    ) -> np.ndarray:
        """Log probability under diagonal Gaussian. Returns (n,)."""
        d = len(mean)
        diff = X - mean
        return -0.5 * (
            d * np.log(2.0 * np.pi)
            + np.sum(np.log(var))
            + np.sum(diff ** 2 / var, axis=1)
        )

    def _log_likelihood(
        self,
        X: np.ndarray,
        means: np.ndarray,
        covs: np.ndarray,
        weights: np.ndarray,
    ) -> float:
        """Total log-likelihood of data under the model."""
        n = X.shape[0]
        log_probs = np.zeros((n, self.n_components))
        for k in range(self.n_components):
            log_probs[:, k] = (
                np.log(weights[k] + 1e-300)
                + self._log_gaussian(X, means[k], covs[k])
            )
        max_log = np.max(log_probs, axis=1, keepdims=True)
        return float(np.sum(max_log.ravel() + np.log(
            np.sum(np.exp(log_probs - max_log), axis=1)
        )))

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Assign each sample to the most likely cluster."""
        self._check_fitted()
        X = np.atleast_2d(X)
        resp = self._e_step(X, self.means, self.covariances, self.weights)
        return np.argmax(resp, axis=1)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return responsibility matrix (n_samples x k)."""
        self._check_fitted()
        X = np.atleast_2d(X)
        return self._e_step(X, self.means, self.covariances, self.weights)

    def label_clusters(
        self, X: np.ndarray, y: np.ndarray
    ) -> Dict[int, str]:
        """Assign semantic labels to clusters using labelled data.

        *y* should contain values from {-1, 0, 1} mapping to
        oversteer, neutral, understeer.

        Returns ``{cluster_id: "understeer" | "oversteer" | "neutral"}``.
        """
        LABEL_MAP = {-1: "oversteer", 0: "neutral", 1: "understeer"}

        assignments = self.predict(X)
        labels: Dict[int, str] = {}
        for k in range(self.n_components):
            mask = assignments == k
            if mask.sum() == 0:
                labels[k] = "neutral"
                continue
            counts = Counter(int(v) for v in y[mask])
            dominant = counts.most_common(1)[0][0]
            labels[k] = LABEL_MAP.get(dominant, "neutral")
        return labels

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save model parameters to a JSON file."""
        self._check_fitted()
        data = {
            "n_components": self.n_components,
            "max_iter": self.max_iter,
            "tol": self.tol,
            "means": self.means.tolist(),
            "covariances": self.covariances.tolist(),
            "weights": self.weights.tolist(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("GMMClustering saved to %s", path)

    @classmethod
    def load(cls, path: str) -> "GMMClustering":
        """Load model parameters from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        model = cls(
            n_components=data["n_components"],
            max_iter=data["max_iter"],
            tol=data["tol"],
        )
        model.means = np.array(data["means"])
        model.covariances = np.array(data["covariances"])
        model.weights = np.array(data["weights"])
        logger.info("GMMClustering loaded from %s", path)
        return model

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_fitted(self) -> None:
        if self.means is None:
            raise RuntimeError("Model has not been fitted yet")
