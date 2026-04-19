"""Validate corner phase segmentation against motorsport driving-phase labels.

Pipeline:
  1. Load motorsport data (lap 3 or all if lap filter fails)
  2. Detect corners via |a_lat_g| > 0.25, contiguous segments, merge close ones
  3. For each corner, run segment_corner_phases() and compare to driving_phase labels
  4. Compute agreement metrics and save to artifacts/phase_validation.json
"""
from __future__ import annotations

import json
import sys
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from telemetry_tool.handling.calibration import segment_corner_phases

MOTORSPORT_PATH = ROOT / "data" / "external" / "kaggle_motorsport" / "motorsport_data.csv"
OUTPUT_PATH = ROOT / "artifacts" / "phase_validation.json"

# Phase mapping: our phase name -> set of expected motorsport driving_phase labels
PHASE_MAP = {
    "entry": {"braking", "hard_braking"},
    "mid":   {"cruise", "coasting"},
    "exit":  {"acceleration", "full_acceleration"},
}


def _load_data() -> dict:
    """Load motorsport data, trying lap 3 first, then all data."""
    from scripts.adapters.motorsport_adapter import load as load_motorsport

    path = str(MOTORSPORT_PATH)
    try:
        data = load_motorsport(path, lap_number=3)
        print(f"Loaded lap 3: {len(data['time_s'])} samples")
        return data
    except (ValueError, KeyError):
        print("Lap 3 not found, loading all data...")
        data = load_motorsport(path)
        print(f"Loaded all data: {len(data['time_s'])} samples")
        return data


def _detect_corners(
    a_lat_g: np.ndarray,
    threshold: float = 0.25,
    min_len: int = 20,
    merge_gap: int = 10,
) -> list[tuple[int, int]]:
    """Detect corners as contiguous segments where |a_lat_g| > threshold."""
    above = np.abs(a_lat_g) > threshold
    changes = np.diff(above.astype(int))
    starts = list(np.where(changes == 1)[0] + 1)
    ends = list(np.where(changes == -1)[0] + 1)

    if above[0]:
        starts.insert(0, 0)
    if above[-1]:
        ends.append(len(a_lat_g))

    # Pair up and filter short segments
    corners = []
    for s, e in zip(starts, ends):
        if e - s >= min_len:
            corners.append((s, e))

    # Merge close segments
    if len(corners) < 2:
        return corners

    merged = [corners[0]]
    for s, e in corners[1:]:
        prev_s, prev_e = merged[-1]
        if s - prev_e <= merge_gap:
            merged[-1] = (prev_s, e)
        else:
            merged.append((s, e))

    return merged


def main() -> None:
    if not MOTORSPORT_PATH.exists():
        print(f"Motorsport data not found at {MOTORSPORT_PATH}")
        sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 1. Load data
    data = _load_data()
    a_lat_g = data["a_lat_g"]
    a_lon_g = data["a_lon_g"]
    driving_phase = data["driving_phase"]

    # Estimate sample rate from time array
    time_s = data["time_s"]
    dt = np.median(np.diff(time_s))
    fs = 1.0 / dt if dt > 0 else 25.0
    print(f"Estimated sample rate: {fs:.1f} Hz")

    # 2. Detect corners
    corners = _detect_corners(a_lat_g)
    print(f"Detected {len(corners)} corners")

    if not corners:
        print("No corners detected -- cannot validate")
        sys.exit(1)

    # 3. Compare phases for each corner
    total_match = 0
    total_samples = 0
    phase_stats = {"entry": {"match": 0, "total": 0}, "mid": {"match": 0, "total": 0}, "exit": {"match": 0, "total": 0}}
    mismatch_counts: dict[str, int] = {}  # "our_phase -> motorsport_label" -> count
    corner_results = []

    for ci, (start_i, end_i) in enumerate(corners):
        seg_alat = a_lat_g[start_i:end_i]
        seg_alon = a_lon_g[start_i:end_i]
        seg_phase = driving_phase[start_i:end_i]

        entry, mid, exit_ = segment_corner_phases(seg_alat, seg_alon, fs)

        corner_detail = {"corner": ci, "start_i": int(start_i), "end_i": int(end_i), "n_samples": int(end_i - start_i), "phases": {}}

        for phase_name, (p_start, p_end) in [("entry", entry), ("mid", mid), ("exit", exit_)]:
            phase_labels = seg_phase[p_start:p_end]
            n_phase = len(phase_labels)
            if n_phase == 0:
                continue

            expected = PHASE_MAP[phase_name]
            matches = sum(1 for lbl in phase_labels if lbl in expected)

            phase_stats[phase_name]["match"] += matches
            phase_stats[phase_name]["total"] += n_phase
            total_match += matches
            total_samples += n_phase

            # Track mismatches
            for lbl in phase_labels:
                if lbl not in expected:
                    key = f"{phase_name} -> {lbl}"
                    mismatch_counts[key] = mismatch_counts.get(key, 0) + 1

            corner_detail["phases"][phase_name] = {
                "range": [int(p_start), int(p_end)],
                "n_samples": int(n_phase),
                "matches": int(matches),
                "agreement": round(matches / n_phase, 4) if n_phase > 0 else 0.0,
            }

        corner_results.append(corner_detail)

    # 4. Compute summary
    overall_agreement = total_match / total_samples if total_samples > 0 else 0.0
    per_phase = {}
    for phase_name, stats in phase_stats.items():
        pct = stats["match"] / stats["total"] if stats["total"] > 0 else 0.0
        per_phase[phase_name] = {"match": stats["match"], "total": stats["total"], "agreement": round(pct, 4)}

    # Top mismatches
    top_mismatches = sorted(mismatch_counts.items(), key=lambda x: -x[1])[:10]

    # Print results
    print("\n" + "=" * 60)
    print("PHASE SEGMENTATION VALIDATION")
    print("=" * 60)
    print(f"Corners analyzed:    {len(corners)}")
    print(f"Total samples:       {total_samples}")
    print(f"Overall agreement:   {overall_agreement:.2%}")
    print()
    print("Per-phase agreement:")
    for phase_name, stats in per_phase.items():
        print(f"  {phase_name:8s}: {stats['agreement']:.2%}  ({stats['match']}/{stats['total']})")
    print()
    print("Top mismatches (our_phase -> motorsport_label : count):")
    for key, count in top_mismatches:
        print(f"  {key:40s}: {count}")

    # 5. Save to JSON
    report = {
        "corners_analyzed": len(corners),
        "total_samples": total_samples,
        "overall_agreement": round(overall_agreement, 4),
        "per_phase": per_phase,
        "top_mismatches": {k: v for k, v in top_mismatches},
        "phase_mapping": {k: sorted(v) for k, v in PHASE_MAP.items()},
        "corners": corner_results,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nResults saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
