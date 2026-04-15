"""Train ML models on DTM-extracted handling features.

Pipeline:
  1. Load (or extract) dtm_features.csv
  2. Prepare X/y, clean NaN/inf
  3. 80/20 train/test split (seed=42)
  4. Train GaussianNB, GMMClustering, HandlingAnomalyDetector
  5. Save models to telemetry_tool/handling/ml/models/
  6. Print evaluation summary
"""
from __future__ import annotations

import sys
import pathlib
import os

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Model save directory
MODELS_DIR = ROOT / "telemetry_tool" / "handling" / "ml" / "models"
FEATURES_PATH = ROOT / "data" / "external" / "dtm_features.csv"

# Columns to exclude from feature matrix
EXCLUDE_COLS = {"label", "label_numeric", "fused_direction", "fused_confidence"}


def _ensure_features() -> pd.DataFrame:
    """Load dtm_features.csv, running extraction first if needed."""
    if FEATURES_PATH.exists():
        print(f"Loading existing features: {FEATURES_PATH}")
        return pd.read_csv(FEATURES_PATH)

    print("dtm_features.csv not found -- running feature extraction...")
    from scripts.ml.extract_features import main as extract_main
    extract_main()

    if not FEATURES_PATH.exists():
        print("ERROR: Feature extraction did not produce dtm_features.csv")
        sys.exit(1)

    return pd.read_csv(FEATURES_PATH)


def _prepare_data(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Separate features (X) and labels (y) from the dataframe."""
    feature_cols = [
        c for c in df.columns
        if c not in EXCLUDE_COLS and pd.api.types.is_numeric_dtype(df[c])
    ]
    print(f"Feature columns ({len(feature_cols)}): {feature_cols[:5]}... (truncated)")

    X = df[feature_cols].to_numpy(dtype=np.float64)
    y = df["label_numeric"].to_numpy(dtype=np.float64)

    # Clean NaN / inf
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0).astype(int)

    return X, y


def _train_test_split(
    X: np.ndarray, y: np.ndarray, test_frac: float = 0.2, seed: int = 42
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Simple 80/20 split with numpy random."""
    rng = np.random.RandomState(seed)
    n = len(X)
    indices = rng.permutation(n)
    split = int(n * (1 - test_frac))
    train_idx, test_idx = indices[:split], indices[split:]
    return X[train_idx], X[test_idx], y[train_idx], y[test_idx]


def _confusion_counts(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Count correct predictions per class."""
    classes = sorted(set(y_true) | set(y_pred))
    result = {}
    for c in classes:
        mask = y_true == c
        total = int(mask.sum())
        correct = int((y_pred[mask] == c).sum()) if total > 0 else 0
        result[int(c)] = {"total": total, "correct": correct}
    return result


def _cluster_purity(
    assignments: np.ndarray, y: np.ndarray, n_components: int
) -> dict:
    """For each cluster, compute % of samples matching the dominant label."""
    purity = {}
    for k in range(n_components):
        mask = assignments == k
        count = int(mask.sum())
        if count == 0:
            purity[k] = {"count": 0, "purity": 0.0, "dominant": "empty"}
            continue
        unique, counts = np.unique(y[mask], return_counts=True)
        dominant_idx = int(np.argmax(counts))
        dominant_label = int(unique[dominant_idx])
        dominant_count = int(counts[dominant_idx])
        label_map = {-1: "oversteer", 0: "neutral", 1: "understeer"}
        purity[k] = {
            "count": count,
            "purity": dominant_count / count,
            "dominant": label_map.get(dominant_label, str(dominant_label)),
        }
    return purity


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load features
    df = _ensure_features()
    print(f"Loaded {len(df)} corners with {len(df.columns)} columns")

    if "label_numeric" not in df.columns:
        print("ERROR: label_numeric column missing from features CSV")
        sys.exit(1)

    # 2. Prepare X, y
    X, y = _prepare_data(df)
    print(f"Feature matrix: {X.shape}, Labels: {y.shape}")
    print(f"Label distribution: OS={int((y == -1).sum())}, "
          f"neutral={int((y == 0).sum())}, US={int((y == 1).sum())}")

    # 3. Train/test split
    X_train, X_test, y_train, y_test = _train_test_split(X, y)
    print(f"\nSplit: train={len(X_train)}, test={len(X_test)}")

    # 4. Train GaussianNB
    print("\n" + "=" * 60)
    print("GAUSSIAN NAIVE BAYES")
    print("=" * 60)
    from telemetry_tool.handling.ml.naive_bayes import GaussianNB

    nb = GaussianNB()
    nb.fit(X_train, y_train)
    accuracy = nb.score(X_test, y_test)
    nb_path = str(MODELS_DIR / "naive_bayes_model.json")
    nb.save(nb_path)

    y_pred_nb = nb.predict(X_test)
    confusion = _confusion_counts(y_test, y_pred_nb)
    print(f"  Accuracy: {accuracy:.4f}")
    print(f"  Saved:    {nb_path}")
    print("  Per-class results:")
    label_names = {-1: "oversteer (OS)", 0: "neutral", 1: "understeer (US)"}
    for c, stats in sorted(confusion.items()):
        name = label_names.get(c, str(c))
        pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"    {name:20s}: {stats['correct']}/{stats['total']} ({pct:.1f}%)")

    # 5. Train GMMClustering
    # -- Feature importance via variance ratio (Fisher's discriminant) --
    print("\n  Feature importance (variance ratio between classes):")
    feature_cols = [
        c for c in df.columns
        if c not in EXCLUDE_COLS and pd.api.types.is_numeric_dtype(df[c])
    ]
    trained_classes = sorted(nb.means.keys())
    if len(trained_classes) >= 2:
        # Compute Fisher's discriminant ratio per feature:
        # ratio = between-class variance / pooled within-class variance
        n_features = X_train.shape[1]
        global_mean = np.mean(X_train, axis=0)
        between_var = np.zeros(n_features)
        within_var = np.zeros(n_features)
        for c in trained_classes:
            mask_c = y_train == c
            n_c = mask_c.sum()
            if n_c == 0:
                continue
            class_mean = nb.means[c]
            class_var = nb.variances[c]
            between_var += n_c * (class_mean - global_mean) ** 2
            within_var += n_c * class_var
        within_var = np.where(within_var < 1e-12, 1e-12, within_var)
        fisher_ratio = between_var / within_var
        ranked_indices = np.argsort(fisher_ratio)[::-1]

        print("\n  Top 5 most discriminative features:")
        for rank, idx in enumerate(ranked_indices[:5], 1):
            fname = feature_cols[idx] if idx < len(feature_cols) else f"feature_{idx}"
            print(f"    {rank}. {fname:35s}  Fisher ratio = {fisher_ratio[idx]:.4f}")

        print(f"\n  All feature Fisher ratios (descending):")
        for idx in ranked_indices[:10]:
            fname = feature_cols[idx] if idx < len(feature_cols) else f"feature_{idx}"
            print(f"    {fname:35s}  {fisher_ratio[idx]:.6f}")
    else:
        print("  (Only one class trained -- cannot compute variance ratios)")

    print("\n" + "=" * 60)
    print("GMM CLUSTERING")
    print("=" * 60)
    from telemetry_tool.handling.ml.gmm_clustering import GMMClustering

    n_components = min(5, len(X_train))
    gmm = GMMClustering(n_components=n_components, random_state=42)
    gmm.fit(X_train)
    cluster_labels = gmm.label_clusters(X_test, y_test)
    gmm_path = str(MODELS_DIR / "gmm_model.json")
    gmm.save(gmm_path)

    assignments = gmm.predict(X_test)
    purity = _cluster_purity(assignments, y_test, n_components)
    print(f"  Components: {n_components}")
    print(f"  Saved:      {gmm_path}")
    print(f"  Cluster labels: {cluster_labels}")
    print("  Cluster purity:")
    for k, stats in sorted(purity.items()):
        print(f"    Cluster {k} ({stats['dominant']:12s}): "
              f"{stats['count']:3d} samples, purity={stats['purity']:.2f}")

    # 6. Train HandlingAnomalyDetector
    print("\n" + "=" * 60)
    print("HANDLING ANOMALY DETECTOR")
    print("=" * 60)
    from telemetry_tool.handling.ml.anomaly import HandlingAnomalyDetector

    normal_mask = y_train == 0
    normal_count = int(normal_mask.sum())
    print(f"  Training on {normal_count} normal corners")

    if normal_count < 3:
        print("  WARNING: Not enough normal samples to train anomaly detector")
    else:
        ad = HandlingAnomalyDetector(contamination=0.1)
        ad.fit(X_train[normal_mask])
        ad_path = str(MODELS_DIR / "anomaly_model.json")
        ad.save(ad_path)

        preds = ad.predict(X_test)
        anomaly_rate = float(preds.mean())
        print(f"  Saved:         {ad_path}")
        print(f"  Overall anomaly rate: {anomaly_rate:.2%}")

        # Check anomaly rate for specific event types
        if "label" in df.columns:
            # Re-split labels to match test set indices
            labels_all = df["label"].to_numpy()
            rng = np.random.RandomState(42)
            indices = rng.permutation(len(X))
            split = int(len(X) * 0.8)
            test_labels = labels_all[indices[split:]]

            for event in ["Loss of Traction", "Lock-up"]:
                event_mask = test_labels == event
                event_count = int(event_mask.sum())
                if event_count > 0:
                    event_anomalies = int(preds[event_mask].sum())
                    print(f"  '{event}': {event_anomalies}/{event_count} "
                          f"flagged as anomalies ({event_anomalies / event_count:.1%})")
                else:
                    print(f"  '{event}': 0 samples in test set")

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"Models saved to: {MODELS_DIR}")


if __name__ == "__main__":
    main()
