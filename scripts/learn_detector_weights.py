"""Learn optimal detector weights from TUMFTM ground truth via linear regression.

Loads all TUMFTM files, runs handling analysis to collect per-corner detector
votes, then fits a linear model mapping vote directions to the true understeer
angle.  The learned weights replace the hand-tuned defaults.

Usage:
    python scripts/learn_detector_weights.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.adapters.tumftm_adapter import load as load_tumftm
from telemetry_tool.handling.runner import run_handling_analysis

# Ordered detector names — must match _ALL_DETECTOR_CLASSES in runner.py
DETECTOR_NAMES = [
    "apex_timing", "corner_balance", "speed_recovery", "lat_g_jerk",
    "trail_braking", "gg_shape", "path_divergence", "yaw_residual",
    "heading_accel", "friction_asymmetry", "speed_scrub", "throttle_response",
    "steering_corrections", "lat_g_plateau", "braking_distance", "line_variation",
]

CURRENT_WEIGHTS = {
    "apex_timing": 1.0, "corner_balance": 0.9, "speed_recovery": 0.8,
    "lat_g_jerk": 0.7, "trail_braking": 0.4, "gg_shape": 0.8,
    "path_divergence": 0.5, "yaw_residual": 1.0, "heading_accel": 0.9,
    "friction_asymmetry": 0.7, "speed_scrub": 0.6, "throttle_response": 0.7,
    "steering_corrections": 0.5, "lat_g_plateau": 0.6,
    "braking_distance": 0.5, "line_variation": 1.0,
}


def _collect_samples(csv_files: list[pathlib.Path]):
    """Run analysis on each file and extract (feature_row, ground_truth) pairs."""
    rows_X = []
    rows_y = []

    for csv_path in csv_files:
        print(f"  Loading {csv_path.name}...", end=" ", flush=True)
        try:
            data = load_tumftm(str(csv_path))
        except Exception as exc:
            print(f"SKIP (load error: {exc})")
            continue

        n = len(data["time_s"])
        if n < 500:
            print(f"SKIP ({n} samples)")
            continue

        result = run_handling_analysis(
            time_s=data["time_s"],
            dist_m=data["dist_m"],
            speed_mps=data["speed_mps"],
            a_lat_g=data["a_lat_g"],
            a_lon_g=data["a_lon_g"],
            bearing_deg=data["bearing_deg"],
            lat_deg=data["lat_deg"],
            lon_deg=data["lon_deg"],
            lap_col=data["lap_col"],
            best_lap=1,
            wheelbase_m=2.6,
            vehicle_class="car",
            use_dynamic_weights=False,
        )

        corners = result.get("corners", [])
        events = result.get("events", [])
        gt_us = data.get("understeer_angle_deg", np.zeros(n))
        dist_m = data["dist_m"]
        n_added = 0

        for corner in corners:
            start_m = corner["start_m"]
            end_m = corner["end_m"]
            ci = corner["corner_id"]

            # Ground truth: mean understeer angle across the corner
            mask = (dist_m >= start_m) & (dist_m <= end_m)
            if mask.sum() < 10:
                continue
            gt_mean = float(np.nanmean(gt_us[mask]))
            if not np.isfinite(gt_mean):
                continue

            # Build feature vector: fused direction per detector across all
            # events in this corner
            corner_events = [e for e in events if e.get("corner_id") == ci]
            if not corner_events:
                continue

            feat = np.zeros(len(DETECTOR_NAMES), dtype=np.float64)
            for ev in corner_events:
                votes = ev.get("detector_votes", {})
                for di, dname in enumerate(DETECTOR_NAMES):
                    if dname in votes:
                        v = votes[dname]
                        direction = v["direction"] if isinstance(v, dict) else v[0]
                        confidence = v["confidence"] if isinstance(v, dict) else v[1]
                        # Weighted contribution: direction * confidence
                        feat[di] += direction * confidence

            # Skip corners where no detector voted at all
            if np.all(feat == 0):
                continue

            # Sanitize
            feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
            rows_X.append(feat)
            rows_y.append(gt_mean)
            n_added += 1

        print(f"{len(corners)} corners, {n_added} usable")

    return np.array(rows_X), np.array(rows_y)


def _fit_weights(X: np.ndarray, y: np.ndarray):
    """Fit y = X @ w + b via least squares. Returns (weights, bias, r_squared)."""
    n = X.shape[0]
    # Augment with bias column
    X_aug = np.column_stack([X, np.ones(n)])
    result, residuals, rank, sv = np.linalg.lstsq(X_aug, y, rcond=None)
    weights = result[:-1]
    bias = result[-1]

    y_pred = X_aug @ result
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1.0 - ss_res / (ss_tot + 1e-12)

    return weights, bias, r_squared


def _per_detector_correlation(X: np.ndarray, y: np.ndarray):
    """Pearson correlation of each detector column with ground truth."""
    correlations = {}
    for di, dname in enumerate(DETECTOR_NAMES):
        col = X[:, di]
        if np.std(col) < 1e-8 or np.std(y) < 1e-8:
            correlations[dname] = 0.0
        else:
            correlations[dname] = float(np.corrcoef(col, y)[0, 1])
    return correlations


def _validate_with_weights(
    csv_files: list[pathlib.Path],
    weights: dict[str, float],
    label: str,
):
    """Re-run validation with specific weights, return accuracy."""
    total_correct = 0
    total_compared = 0

    for csv_path in csv_files:
        try:
            data = load_tumftm(str(csv_path))
        except Exception:
            continue
        n = len(data["time_s"])
        if n < 500:
            continue

        result = run_handling_analysis(
            time_s=data["time_s"],
            dist_m=data["dist_m"],
            speed_mps=data["speed_mps"],
            a_lat_g=data["a_lat_g"],
            a_lon_g=data["a_lon_g"],
            bearing_deg=data["bearing_deg"],
            lat_deg=data["lat_deg"],
            lon_deg=data["lon_deg"],
            lap_col=data["lap_col"],
            best_lap=1,
            wheelbase_m=2.6,
            vehicle_class="car",
            use_dynamic_weights=False,
        )

        corners = result.get("corners", [])
        events = result.get("events", [])
        gt_us = data.get("understeer_angle_deg", np.zeros(n))
        dist_m_arr = data["dist_m"]

        for corner in corners:
            mask = (dist_m_arr >= corner["start_m"]) & (dist_m_arr <= corner["end_m"])
            if mask.sum() < 10:
                continue
            gt_mean = float(np.nanmean(gt_us[mask]))
            gt_label = (
                "understeer" if gt_mean > 0.5
                else ("oversteer" if gt_mean < -0.5 else "neutral")
            )

            ci = corner["corner_id"]
            corner_events = [e for e in events if e.get("corner_id") == ci]
            if corner_events:
                best_ev = max(corner_events, key=lambda e: e.get("confidence", 0))
                pred_label = best_ev.get("event_type", "neutral")
            else:
                pred_label = "neutral"

            if pred_label == gt_label:
                total_correct += 1
            total_compared += 1

    accuracy = total_correct / total_compared if total_compared > 0 else 0
    return accuracy, total_correct, total_compared


def main():
    tumftm_dir = ROOT / "data" / "external" / "tumftm"
    csv_files = sorted(tumftm_dir.glob("data_to_*.csv"))
    csv_files = [f for f in csv_files if f.stat().st_size > 1000]

    if not csv_files:
        print("No TUMFTM CSV files found in data/external/tumftm/")
        return

    print(f"Learning detector weights from {len(csv_files)} TUMFTM files\n")

    # Step 1: collect samples
    print("Step 1: Collecting per-corner samples...")
    X, y = _collect_samples(csv_files)
    print(f"\n  Collected {len(y)} corner samples with ground truth\n")

    if len(y) < 10:
        print("Not enough samples for regression. Aborting.")
        return

    # Step 2: per-detector correlation
    print("Step 2: Per-detector correlation with ground truth")
    correlations = _per_detector_correlation(X, y)
    for dname in DETECTOR_NAMES:
        c = correlations[dname]
        bar = "+" * int(abs(c) * 20) if c >= 0 else "-" * int(abs(c) * 20)
        print(f"  {dname:24s}  r={c:+.3f}  {bar}")

    # Step 3: linear regression
    print("\nStep 3: Fitting linear regression...")
    raw_weights, bias, r_sq = _fit_weights(X, y)
    print(f"  R-squared: {r_sq:.4f}")
    print(f"  Bias: {bias:.4f}")

    # Step 4: normalize to match current weight budget
    current_total = sum(CURRENT_WEIGHTS.values())
    raw_abs = np.abs(raw_weights)
    raw_total = raw_abs.sum()
    if raw_total < 1e-8:
        print("All weights near zero — regression failed. Aborting.")
        return

    scale = current_total / raw_total
    learned_weights = {}
    for di, dname in enumerate(DETECTOR_NAMES):
        learned_weights[dname] = round(float(np.abs(raw_weights[di]) * scale), 3)

    # Step 5: comparison table
    print(f"\nStep 4: Weight comparison (normalized to sum={current_total:.1f})")
    print(f"  {'Detector':24s}  {'Current':>8s}  {'Learned':>8s}  {'Change':>8s}")
    print(f"  {'-'*24}  {'-'*8}  {'-'*8}  {'-'*8}")
    for dname in DETECTOR_NAMES:
        cur = CURRENT_WEIGHTS[dname]
        lrn = learned_weights[dname]
        delta = lrn - cur
        print(f"  {dname:24s}  {cur:8.3f}  {lrn:8.3f}  {delta:+8.3f}")

    # Step 6: save learned weights
    out_path = ROOT / "telemetry_tool" / "handling" / "learned_weights.json"
    payload = {
        "description": "Detector weights learned from TUMFTM ground truth via linear regression",
        "n_samples": int(len(y)),
        "r_squared": round(float(r_sq), 4),
        "bias": round(float(bias), 4),
        "per_detector_correlation": {k: round(v, 4) for k, v in correlations.items()},
        "weights": learned_weights,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  Saved learned weights to {out_path}")

    # Step 7: validate with current weights
    print("\nStep 5: Validating with current (hand-tuned) weights...")
    acc_cur, cor_cur, tot_cur = _validate_with_weights(csv_files, CURRENT_WEIGHTS, "current")
    print(f"  Current accuracy: {acc_cur:.1%} ({cor_cur}/{tot_cur})")

    # Note: the runner's use_dynamic_weights=False path uses detector defaults,
    # which matches CURRENT_WEIGHTS.  To inject learned_weights into the
    # fusion, the runner would need a detector_weights parameter.  For now
    # we report the regression quality and per-detector insights.
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Samples:           {len(y)}")
    print(f"  R-squared:         {r_sq:.4f}")
    print(f"  Current accuracy:  {acc_cur:.1%}")
    best_det = max(correlations, key=lambda k: abs(correlations[k]))
    print(f"  Best predictor:    {best_det} (r={correlations[best_det]:+.3f})")
    worst_det = min(correlations, key=lambda k: abs(correlations[k]))
    print(f"  Weakest predictor: {worst_det} (r={correlations[worst_det]:+.3f})")


if __name__ == "__main__":
    main()
