"""Stage 6: Merge all feature files and train ML models."""
import sys, pathlib, json, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PARQUET_DIR = ROOT / "data" / "external"
MODEL_DIR = ROOT / "telemetry_tool" / "handling" / "ml" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def _load(name):
    """Load parquet or CSV feature file."""
    pq = PARQUET_DIR / f"{name}.parquet"
    csv = PARQUET_DIR / f"{name}.csv"
    if pq.exists():
        return pd.read_parquet(pq)
    if csv.exists():
        return pd.read_csv(csv)
    return pd.DataFrame()


def _get_feature_cols(df):
    """Get numeric feature columns (exclude labels and metadata strings)."""
    exclude = {"gt_understeer_deg", "gt_label", "label", "label_numeric",
               "source", "year", "track", "driver", "session", "session_name",
               "event_type", "label_source", "fused_direction", "fused_confidence",
               "driving_phase", "sector_type"}
    cols = [c for c in df.columns if c not in exclude and df[c].dtype in ("float64", "float32", "int64", "int32")]
    return cols


def main():
    print("Loading feature files...")

    frames = {}
    for name in ["dtm_events", "tumftm_features", "f1_features", "motorsport_features", "kart_features"]:
        df = _load(name)
        if len(df) > 0:
            frames[name] = df
            print(f"  {name}: {len(df)} rows, {len(df.columns)} cols")
        else:
            print(f"  {name}: NOT FOUND")

    if not frames:
        print("No feature files found! Run stages 1-5 first.")
        return

    # Merge
    all_data = pd.concat(frames.values(), ignore_index=True, sort=False)
    all_data = all_data.fillna(0)
    print(f"\nMerged: {len(all_data)} total rows")

    # Determine labels — check multiple sources
    if "label_numeric" not in all_data.columns:
        all_data["label_numeric"] = 0
    # DTM events use numeric "label" column directly (-1, 0, +1)
    if "label" in all_data.columns:
        numeric_labels = pd.to_numeric(all_data["label"], errors="coerce")
        mask = numeric_labels.notna() & (numeric_labels != 0)
        all_data.loc[mask, "label_numeric"] = numeric_labels[mask].astype(int)
    # TUMFTM uses "gt_label" column
    if "gt_label" in all_data.columns:
        gt = pd.to_numeric(all_data["gt_label"], errors="coerce")
        mask = gt.notna() & (gt != 0)
        all_data.loc[mask, "label_numeric"] = gt[mask].astype(int)

    feature_cols = _get_feature_cols(all_data)
    print(f"Feature columns: {len(feature_cols)}")

    X = all_data[feature_cols].values.astype(np.float64)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    y = all_data["label_numeric"].values.astype(int)

    print(f"Labels: OS={np.sum(y==-1)}, neutral={np.sum(y==0)}, US={np.sum(y==1)}")

    # Split: 80/20 stratified
    rng = np.random.RandomState(42)
    train_idx, test_idx = [], []
    for c in [-1, 0, 1]:
        ci = np.where(y == c)[0]
        rng.shuffle(ci)
        split = int(0.8 * len(ci))
        train_idx.extend(ci[:split])
        test_idx.extend(ci[split:])
    train_idx = np.array(train_idx)
    test_idx = np.array(test_idx)

    X_train, y_train = X[train_idx], y[train_idx]
    X_test, y_test = X[test_idx], y[test_idx]
    print(f"Train: {len(X_train)}, Test: {len(X_test)}")

    results = {}

    # --- A. Naive Bayes ---
    print("\n--- Naive Bayes ---")
    from telemetry_tool.handling.ml.naive_bayes import GaussianNB
    nb = GaussianNB()
    nb.fit(X_train, y_train)
    nb_acc = nb.score(X_test, y_test)
    nb.save(str(MODEL_DIR / "naive_bayes_model.json"))
    preds = nb.predict(X_test)
    print(f"  Accuracy: {nb_acc:.1%}")
    for c in [-1, 0, 1]:
        mask = y_test == c
        if mask.sum() > 0:
            correct = np.sum(preds[mask] == c)
            print(f"  Class {c:+d}: {correct}/{mask.sum()} ({correct/mask.sum():.0%})")
    results["naive_bayes"] = {"accuracy": round(nb_acc, 4)}

    # --- B. Ridge Regression (on TUMFTM only) ---
    print("\n--- Ridge Regression ---")
    if "tumftm_features" in frames:
        tumftm = frames["tumftm_features"]
        t_fcols = [c for c in feature_cols if c in tumftm.columns]
        Xt = tumftm[t_fcols].values.astype(np.float64)
        Xt = np.nan_to_num(Xt, nan=0.0, posinf=0.0, neginf=0.0)
        yt = tumftm["gt_understeer_deg"].values.astype(np.float64) if "gt_understeer_deg" in tumftm.columns else np.zeros(len(tumftm))
        yt = np.nan_to_num(yt)

        if len(Xt) > 10 and np.std(yt) > 1e-6:
            # Ridge: (X'X + λI)^-1 X'y
            lam = 1.0
            XtX = Xt.T @ Xt + lam * np.eye(Xt.shape[1])
            w = np.linalg.solve(XtX, Xt.T @ yt)
            pred_y = Xt @ w
            ss_res = np.sum((yt - pred_y) ** 2)
            ss_tot = np.sum((yt - np.mean(yt)) ** 2)
            r2 = 1 - ss_res / (ss_tot + 1e-12)
            mae = np.mean(np.abs(yt - pred_y))
            print(f"  R²: {r2:.4f}, MAE: {mae:.4f} deg")
            print(f"  Top 5 features by |weight|:")
            order = np.argsort(np.abs(w))[::-1][:5]
            for i in order:
                print(f"    {t_fcols[i]:30s} w={w[i]:+.4f}")
            # Save weights
            ridge_weights = {t_fcols[i]: float(w[i]) for i in range(len(w))}
            with open(MODEL_DIR / "ridge_weights.json", "w") as f:
                json.dump({"r2": r2, "mae": mae, "weights": ridge_weights}, f, indent=2)
            results["ridge"] = {"r2": round(r2, 4), "mae": round(mae, 4)}
        else:
            print("  Insufficient TUMFTM data for regression")
            results["ridge"] = {"r2": 0, "mae": 0}
    else:
        print("  No TUMFTM data available")
        results["ridge"] = {"r2": 0, "mae": 0}

    # --- C. GMM Clustering ---
    print("\n--- GMM Clustering ---")
    from telemetry_tool.handling.ml.gmm_clustering import GMMClustering
    gmm = GMMClustering(n_components=7, max_iter=100)
    gmm.fit(X_train)
    gmm.save(str(MODEL_DIR / "gmm_model.json"))
    clusters = gmm.predict(X_test)
    cluster_labels = gmm.label_clusters(X_test, y_test)
    print(f"  Clusters: {len(set(clusters))}")
    for ci in sorted(set(clusters)):
        mask = clusters == ci
        n = mask.sum()
        label = cluster_labels.get(ci, "?")
        print(f"    Cluster {ci} ({label:10s}): {n} corners")
    results["gmm"] = {"n_clusters": len(set(clusters)), "labels": cluster_labels}

    # --- D. Anomaly Detector ---
    print("\n--- Anomaly Detector ---")
    from telemetry_tool.handling.ml.anomaly import HandlingAnomalyDetector
    normal_mask = y_train == 0
    if normal_mask.sum() > 20:
        ad = HandlingAnomalyDetector(contamination=0.1)
        ad.fit(X_train[normal_mask])
        ad.save(str(MODEL_DIR / "anomaly_model.json"))
        anomalies = ad.predict(X_test)
        anom_rate = anomalies.mean()
        # Check if events are flagged
        event_mask = y_test != 0
        if event_mask.sum() > 0:
            event_anom_rate = anomalies[event_mask].mean()
            print(f"  Overall anomaly rate: {anom_rate:.1%}")
            print(f"  Event anomaly rate:   {event_anom_rate:.1%}")
            results["anomaly"] = {"overall_rate": round(float(anom_rate), 4),
                                  "event_rate": round(float(event_anom_rate), 4)}
        else:
            print(f"  Overall anomaly rate: {anom_rate:.1%} (no events in test set)")
            results["anomaly"] = {"overall_rate": round(float(anom_rate), 4)}
    else:
        print("  Not enough normal samples")
        results["anomaly"] = {}

    # --- E. Random Forest ---
    print("\n--- Random Forest ---")
    from telemetry_tool.handling.ml.random_forest import RandomForest
    rf = RandomForest(n_estimators=50, max_depth=3, seed=42)
    rf.fit(X_train, y_train)
    rf_acc = rf.score(X_test, y_test)
    rf.save(str(MODEL_DIR / "random_forest_model.json"))
    print(f"  Accuracy: {rf_acc:.1%}")
    if rf.feature_importance_ is not None:
        print(f"  Top 10 features:")
        order = np.argsort(rf.feature_importance_)[::-1][:10]
        for i in order:
            if i < len(feature_cols):
                print(f"    {feature_cols[i]:30s} importance={rf.feature_importance_[i]:.4f}")
    results["random_forest"] = {"accuracy": round(rf_acc, 4)}

    # Save summary
    results["data_summary"] = {
        "total_rows": len(all_data),
        "sources": {k: len(v) for k, v in frames.items()},
        "n_features": len(feature_cols),
        "label_dist": {"os": int(np.sum(y == -1)), "neutral": int(np.sum(y == 0)), "us": int(np.sum(y == 1))},
    }
    with open(MODEL_DIR / "training_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"TRAINING COMPLETE")
    print(f"{'='*60}")
    print(f"Models saved to: {MODEL_DIR}")
    print(f"NB: {nb_acc:.1%}, Ridge R²: {results['ridge']['r2']:.4f}, RF: {rf_acc:.1%}")


if __name__ == "__main__":
    main()
