"""Phase 2: Validate handling detectors against TUMFTM ground truth.

TUMFTM data has actual steering angle + lateral velocity, so we can compute
the TRUE understeer angle and compare with our detector predictions.

Ground truth: understeer_angle = actual_steering - kinematic_steering
  Positive = understeer (driver turns more than path requires)
  Negative = oversteer
"""
import sys, pathlib, json, warnings
import numpy as np
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.adapters.tumftm_adapter import load as load_tumftm
from telemetry_tool.handling.runner import run_handling_analysis


def validate_one_file(csv_path: str) -> dict:
    """Run detectors on one TUMFTM file and compare with ground truth."""
    data = load_tumftm(csv_path)
    n = len(data["time_s"])
    if n < 500:
        return {"file": csv_path, "error": "too short", "n_samples": n}

    # Run our detection system
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
        wheelbase_m=2.6,  # race car, not kart
        vehicle_class="car",
    )

    corners = result.get("corners", [])
    events = result.get("events", [])
    gt_us = data.get("understeer_angle_deg", np.zeros(n))

    # For each detected corner, compute mean ground-truth understeer angle
    correct = 0
    total = 0
    per_corner = []

    for ci, corner in enumerate(corners):
        start_m = corner["start_m"]
        end_m = corner["end_m"]

        # Find ground truth samples in this corner
        mask = (data["dist_m"] >= start_m) & (data["dist_m"] <= end_m)
        if mask.sum() < 10:
            continue

        gt_mean = float(np.nanmean(gt_us[mask]))
        gt_label = "understeer" if gt_mean > 0.5 else ("oversteer" if gt_mean < -0.5 else "neutral")

        # Find our prediction for this corner
        corner_events = [e for e in events if e.get("corner_id") == ci]
        if corner_events:
            best_ev = max(corner_events, key=lambda e: e.get("confidence", 0))
            pred_label = best_ev.get("event_type", "neutral")
            pred_dir = best_ev.get("direction", 0)
        else:
            pred_label = "neutral"
            pred_dir = 0.0

        is_correct = pred_label == gt_label
        if is_correct:
            correct += 1
        total += 1

        per_corner.append({
            "corner_id": ci,
            "gt_mean_deg": round(gt_mean, 2),
            "gt_label": gt_label,
            "pred_label": pred_label,
            "pred_direction": round(pred_dir, 3),
            "correct": is_correct,
        })

    return {
        "file": str(pathlib.Path(csv_path).name),
        "n_samples": n,
        "n_corners": len(corners),
        "n_events": len(events),
        "n_compared": total,
        "n_correct": correct,
        "accuracy": correct / total if total > 0 else 0,
        "per_corner": per_corner,
    }


def main():
    tumftm_dir = ROOT / "data" / "external" / "tumftm"
    csv_files = sorted(tumftm_dir.glob("data_to_*.csv"))
    csv_files = [f for f in csv_files if f.stat().st_size > 1000]

    if not csv_files:
        print("No TUMFTM CSV files found!")
        return

    print(f"Validating against {len(csv_files)} TUMFTM files...\n")

    all_results = []
    total_correct = 0
    total_compared = 0

    for csv_path in csv_files:
        print(f"  Processing {csv_path.name}...", end=" ", flush=True)
        try:
            r = validate_one_file(str(csv_path))
            all_results.append(r)
            total_correct += r.get("n_correct", 0)
            total_compared += r.get("n_compared", 0)
            print(f"{r.get('n_corners', 0)} corners, {r.get('n_correct', 0)}/{r.get('n_compared', 0)} correct")
        except Exception as e:
            print(f"ERROR: {e}")
            all_results.append({"file": csv_path.name, "error": str(e)})

    # Summary
    accuracy = total_correct / total_compared if total_compared > 0 else 0
    print(f"\n{'='*60}")
    print(f"GROUND TRUTH VALIDATION SUMMARY")
    print(f"{'='*60}")
    print(f"Files processed:  {len(all_results)}")
    print(f"Total corners:    {total_compared}")
    print(f"Correct:          {total_correct}")
    print(f"Accuracy:         {accuracy:.1%}")

    # Per-file breakdown
    for r in all_results:
        if "error" in r and r["error"]:
            print(f"  {r['file']:30s} ERROR: {r['error']}")
        else:
            print(f"  {r['file']:30s} {r.get('n_correct',0)}/{r.get('n_compared',0)} = {r.get('accuracy',0):.0%}")

    # Save results
    out_path = ROOT / "artifacts" / "validation_ground_truth.json"
    with open(out_path, "w") as f:
        json.dump({
            "overall_accuracy": round(accuracy, 4),
            "total_corners": total_compared,
            "total_correct": total_correct,
            "files": all_results,
        }, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
