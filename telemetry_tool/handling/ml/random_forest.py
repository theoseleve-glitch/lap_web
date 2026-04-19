"""Random Forest classifier — numpy-only implementation.

Bagged ensemble of shallow decision trees (max_depth=3) for
interpretable handling event classification.

Provides feature importance via split frequency counting.
"""
from __future__ import annotations

import json
import numpy as np


class DecisionStump:
    """Single decision tree with limited depth."""

    def __init__(self, max_depth: int = 3):
        self.max_depth = max_depth
        self.tree = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        self.classes_ = np.unique(y)
        self.n_features_ = X.shape[1]
        self.split_counts_ = np.zeros(self.n_features_)
        self.tree = self._build(X, y, depth=0)

    def _build(self, X, y, depth):
        if depth >= self.max_depth or len(y) < 4 or len(np.unique(y)) == 1:
            vals, counts = np.unique(y, return_counts=True)
            return {"leaf": True, "class": int(vals[np.argmax(counts)]),
                    "proba": {int(v): int(c) for v, c in zip(vals, counts)}}

        best_feat, best_thr, best_score = 0, 0.0, -1.0
        n = len(y)

        # Random feature subset (sqrt(n_features))
        n_try = max(1, int(np.sqrt(self.n_features_)))
        feat_idx = np.random.choice(self.n_features_, n_try, replace=False)

        for fi in feat_idx:
            vals = np.unique(X[:, fi])
            if len(vals) < 2:
                continue
            thresholds = (vals[:-1] + vals[1:]) / 2
            # Sample thresholds if too many
            if len(thresholds) > 20:
                thresholds = np.random.choice(thresholds, 20, replace=False)

            for thr in thresholds:
                left = y[X[:, fi] <= thr]
                right = y[X[:, fi] > thr]
                if len(left) < 2 or len(right) < 2:
                    continue
                score = self._gini_gain(y, left, right)
                if score > best_score:
                    best_score = score
                    best_feat = fi
                    best_thr = float(thr)

        if best_score <= 0:
            vals, counts = np.unique(y, return_counts=True)
            return {"leaf": True, "class": int(vals[np.argmax(counts)]),
                    "proba": {int(v): int(c) for v, c in zip(vals, counts)}}

        self.split_counts_[best_feat] += 1
        mask = X[:, best_feat] <= best_thr
        return {
            "leaf": False, "feature": int(best_feat), "threshold": best_thr,
            "left": self._build(X[mask], y[mask], depth + 1),
            "right": self._build(X[~mask], y[~mask], depth + 1),
        }

    @staticmethod
    def _gini_gain(parent, left, right):
        def gini(arr):
            if len(arr) == 0:
                return 0
            _, counts = np.unique(arr, return_counts=True)
            p = counts / len(arr)
            return 1 - np.sum(p ** 2)

        n = len(parent)
        return gini(parent) - (len(left) / n * gini(left) + len(right) / n * gini(right))

    def predict(self, X):
        return np.array([self._predict_one(x, self.tree) for x in X])

    def _predict_one(self, x, node):
        if node["leaf"]:
            return node["class"]
        if x[node["feature"]] <= node["threshold"]:
            return self._predict_one(x, node["left"])
        return self._predict_one(x, node["right"])


class RandomForest:
    """Bagged ensemble of decision stumps.

    Features:
      - Feature importance from split frequency
      - Majority voting for classification
      - Interpretable (shallow trees)
    """

    def __init__(self, n_estimators: int = 50, max_depth: int = 3, seed: int = 42):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.seed = seed
        self.trees: list[DecisionStump] = []
        self.feature_importance_: np.ndarray | None = None
        self.classes_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        rng = np.random.RandomState(self.seed)
        self.classes_ = np.unique(y)
        n = len(y)
        self.trees = []
        total_splits = np.zeros(X.shape[1])

        for i in range(self.n_estimators):
            # Bootstrap sample
            idx = rng.choice(n, n, replace=True)
            tree = DecisionStump(max_depth=self.max_depth)
            np.random.seed(self.seed + i)
            tree.fit(X[idx], y[idx])
            self.trees.append(tree)
            total_splits += tree.split_counts_

        total = total_splits.sum()
        self.feature_importance_ = total_splits / total if total > 0 else total_splits

    def predict(self, X: np.ndarray) -> np.ndarray:
        preds = np.array([t.predict(X) for t in self.trees])
        # Majority vote
        result = np.zeros(len(X), dtype=int)
        for i in range(len(X)):
            vals, counts = np.unique(preds[:, i], return_counts=True)
            result[i] = vals[np.argmax(counts)]
        return result

    def score(self, X: np.ndarray, y: np.ndarray) -> float:
        return float(np.mean(self.predict(X) == y))

    def save(self, path: str):
        data = {
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "seed": self.seed,
            "classes": self.classes_.tolist() if self.classes_ is not None else [],
            "feature_importance": self.feature_importance_.tolist() if self.feature_importance_ is not None else [],
            "trees": [t.tree for t in self.trees],
            "split_counts": [t.split_counts_.tolist() for t in self.trees],
        }
        with open(path, "w") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path: str) -> "RandomForest":
        with open(path) as f:
            data = json.load(f)
        rf = cls(data["n_estimators"], data["max_depth"], data["seed"])
        rf.classes_ = np.array(data["classes"])
        rf.feature_importance_ = np.array(data["feature_importance"])
        rf.trees = []
        for tree_data, splits in zip(data["trees"], data["split_counts"]):
            t = DecisionStump(data["max_depth"])
            t.tree = tree_data
            t.split_counts_ = np.array(splits)
            t.classes_ = rf.classes_
            t.n_features_ = len(splits)
            rf.trees.append(t)
        return rf
