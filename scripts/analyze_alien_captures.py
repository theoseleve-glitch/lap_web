#!/usr/bin/env python3
"""Batch analyze alien .ibt captures through the sim optimizer.

Walks the output directory from batch_replay_capture.py, loads each .ibt file,
runs the sim optimizer pipeline, and saves results as JSON + optional Parquet
sidecar.

Usage:
    # Analyze all captures from the batch replay tool
    python scripts/analyze_alien_captures.py ./data/oracle/alien_captures

    # Analyze a single .ibt file
    python scripts/analyze_alien_captures.py path/to/session.ibt

    # Analyze with custom output directory
    python scripts/analyze_alien_captures.py ./captures --output ./results

    # Skip already-analyzed sessions
    python scripts/analyze_alien_captures.py ./captures  # (default: skip existing)

    # Re-analyze everything
    python scripts/analyze_alien_captures.py ./captures --no-skip

What it does for each .ibt:
    1. Loads .ibt → DataFrame with irsdk__ columns
    2. Runs the 14-step sim optimizer pipeline
    3. Saves:
       - result.json  (theoretical lap time, vehicle model, corner coaching)
       - delta.json   (distance-aligned actual vs theoretical)
       - summary.json (top 5 corners, total time loss, vehicle params)
       - raw_sidecar.parquet (raw irsdk__ DataFrame for later re-analysis)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import pandas as pd

from telemetry_tool.sim_optimizer.ingest.ibt_loader import (
    load_ibt,
    load_ibt_with_metadata,
)
from telemetry_tool.sim_optimizer.pipeline import SimOptimizerResult, optimize_session
from telemetry_tool.sim_optimizer.output.traces import (
    serialize_lap_delta,
    serialize_theoretical_trace,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("alien_analysis")


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""

    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


def _find_ibt_files(input_path: Path) -> list[Path]:
    """Find all .ibt files under input_path."""
    if input_path.is_file() and input_path.suffix.lower() == ".ibt":
        return [input_path]

    ibt_files = sorted(input_path.rglob("*.ibt"))
    log.info("Found %d .ibt files under %s", len(ibt_files), input_path)
    return ibt_files


def _result_dir(ibt_path: Path, output_base: Path) -> Path:
    """Compute the output directory for a given .ibt file."""
    # Use the parent directory name (from batch_replay_capture) as folder
    parent_name = ibt_path.parent.name
    stem = ibt_path.stem
    return output_base / f"{parent_name}__{stem}"


def _save_result(
    result: SimOptimizerResult,
    metadata: dict,
    raw_df: pd.DataFrame,
    out_dir: Path,
) -> None:
    """Persist optimizer results to disk."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Summary JSON
    summary = dict(result.summary)
    summary["metadata"] = metadata
    summary["success"] = result.success
    summary["errors"] = result.errors
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, cls=_NumpyEncoder)

    # 2. Theoretical trace
    if result.input_trace is not None:
        trace_dict = serialize_theoretical_trace(result.input_trace)
        if result.theoretical:
            trace_dict["lap_time_s"] = round(float(result.theoretical.lap_time_s), 3)
        with open(out_dir / "theoretical.json", "w") as f:
            json.dump(trace_dict, f, indent=2, cls=_NumpyEncoder)

    # 3. Delta
    if result.delta is not None:
        delta_dict = serialize_lap_delta(result.delta)
        with open(out_dir / "delta.json", "w") as f:
            json.dump(delta_dict, f, indent=2, cls=_NumpyEncoder)

    # 4. Corner coaching
    if result.corners:
        corners_list = []
        for c in result.corners:
            if hasattr(c, "to_dict"):
                corners_list.append(c.to_dict())
            elif isinstance(c, dict):
                corners_list.append(c)
            else:
                corners_list.append({
                    "corner_id": getattr(c, "corner_id", None),
                    "time_loss_s": getattr(c, "time_loss_s", 0.0),
                    "root_cause": getattr(c, "root_cause", ""),
                    "coaching_text": getattr(c, "coaching_text", ""),
                    "brake_point_delta_m": getattr(c, "brake_point_delta_m", 0.0),
                    "apex_speed_delta_kph": getattr(c, "apex_speed_delta_kph", 0.0),
                    "exit_throttle_delta_pct": getattr(c, "exit_throttle_delta_pct", 0.0),
                })
        with open(out_dir / "corners.json", "w") as f:
            json.dump(corners_list, f, indent=2, cls=_NumpyEncoder)

    # 5. Raw sidecar Parquet (for re-analysis or web API)
    try:
        raw_df.to_parquet(out_dir / "raw_sidecar.parquet", index=False)
    except Exception as exc:
        log.warning("Failed to save Parquet sidecar: %s", exc)

    # 6. Vehicle model
    if result.vehicle_model is not None:
        vm_dict = {}
        if hasattr(result.vehicle_model, "to_dict"):
            vm_dict = result.vehicle_model.to_dict()
        with open(out_dir / "vehicle_model.json", "w") as f:
            json.dump(vm_dict, f, indent=2, cls=_NumpyEncoder)


def analyze_single(
    ibt_path: Path,
    output_dir: Path,
    *,
    skip_existing: bool = True,
) -> dict:
    """Analyze a single .ibt file.

    Returns a result dict with status, lap_time, errors, etc.
    """
    out_dir = _result_dir(ibt_path, output_dir)
    entry = {
        "file": str(ibt_path),
        "output": str(out_dir),
        "status": "pending",
    }

    # Skip check
    if skip_existing and (out_dir / "summary.json").exists():
        log.info("  Already analyzed — skipping")
        entry["status"] = "skipped"
        return entry

    start = time.monotonic()

    # Load
    loaded = load_ibt_with_metadata(ibt_path)
    if loaded is None:
        log.warning("  Failed to load .ibt")
        entry["status"] = "load_failed"
        return entry

    raw_df, metadata = loaded
    log.info(
        "  Loaded: %d samples, %d channels (%.1f Hz)",
        metadata["n_samples"],
        metadata["n_channels"],
        metadata["tick_rate"],
    )

    # Run optimizer
    try:
        result = optimize_session(raw_df)
    except Exception as exc:
        log.error("  Optimizer failed: %s", exc, exc_info=True)
        entry["status"] = "optimizer_error"
        entry["error"] = str(exc)
        return entry

    elapsed = time.monotonic() - start

    # Save
    _save_result(result, metadata, raw_df, out_dir)

    entry["status"] = "success" if result.success else "partial"
    entry["elapsed_s"] = round(elapsed, 2)
    entry["errors"] = result.errors

    if result.theoretical:
        entry["theoretical_lap_time_s"] = round(float(result.theoretical.lap_time_s), 3)
    if result.corners:
        entry["n_corners"] = len(result.corners)
        total_loss = sum(
            getattr(c, "time_loss_s", 0.0) if not isinstance(c, dict)
            else c.get("time_loss_s", 0.0)
            for c in result.corners
        )
        entry["total_time_loss_s"] = round(float(total_loss), 3)

    return entry


def batch_analyze(
    input_path: Path,
    output_dir: Path,
    *,
    skip_existing: bool = True,
) -> None:
    """Analyze all .ibt files under input_path."""
    ibt_files = _find_ibt_files(input_path)
    if not ibt_files:
        log.error("No .ibt files found in %s", input_path)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    results = {"success": 0, "partial": 0, "failed": 0, "skipped": 0, "details": []}
    total_start = time.monotonic()

    for i, ibt_path in enumerate(ibt_files, 1):
        log.info("")
        log.info("=" * 60)
        log.info("[%d/%d] %s", i, len(ibt_files), ibt_path.name)
        log.info("=" * 60)

        entry = analyze_single(ibt_path, output_dir, skip_existing=skip_existing)
        results["details"].append(entry)

        status = entry["status"]
        if status == "success":
            results["success"] += 1
            lap_t = entry.get("theoretical_lap_time_s", "?")
            log.info("  -> Theoretical: %ss | Corners: %s | Loss: %ss",
                     lap_t, entry.get("n_corners", 0),
                     entry.get("total_time_loss_s", "?"))
        elif status == "partial":
            results["partial"] += 1
            log.info("  -> Partial (errors: %s)", entry.get("errors", []))
        elif status == "skipped":
            results["skipped"] += 1
        else:
            results["failed"] += 1
            log.warning("  -> Failed: %s", status)

    total_elapsed = time.monotonic() - total_start

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("BATCH ANALYSIS COMPLETE (%.1fs)", total_elapsed)
    log.info("  Success:  %d", results["success"])
    log.info("  Partial:  %d", results["partial"])
    log.info("  Failed:   %d", results["failed"])
    log.info("  Skipped:  %d", results["skipped"])
    log.info("  Total:    %d", len(ibt_files))
    log.info("=" * 60)

    # Save batch summary
    summary_path = output_dir / "batch_analysis_summary.json"
    results["total_elapsed_s"] = round(total_elapsed, 2)
    results["n_files"] = len(ibt_files)
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, cls=_NumpyEncoder)
    log.info("Batch summary: %s", summary_path)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze alien .ibt captures through the sim optimizer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze batch_replay_capture output
  python scripts/analyze_alien_captures.py ./data/oracle/alien_captures

  # Analyze a single .ibt file
  python scripts/analyze_alien_captures.py path/to/session.ibt

  # Custom output location
  python scripts/analyze_alien_captures.py ./captures --output ./results

  # Re-analyze everything (no skip)
  python scripts/analyze_alien_captures.py ./captures --no-skip
""",
    )
    parser.add_argument(
        "input_path", type=Path,
        help="Directory with .ibt files (from batch_replay_capture) or a single .ibt file",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output directory (default: <input_path>/analysis_results)",
    )
    parser.add_argument(
        "--no-skip", action="store_true",
        help="Re-analyze even if results already exist",
    )

    args = parser.parse_args()

    if not args.input_path.exists():
        log.error("Input path does not exist: %s", args.input_path)
        sys.exit(1)

    output_dir = args.output or (
        args.input_path / "analysis_results"
        if args.input_path.is_dir()
        else args.input_path.parent / "analysis_results"
    )

    batch_analyze(
        args.input_path,
        output_dir,
        skip_existing=not args.no_skip,
    )


if __name__ == "__main__":
    main()
