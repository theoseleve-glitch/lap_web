"""
Old tool runner — invokes the CLI pipeline (`run_full_analysis`) in-process,
extracts comparable metrics, normalizes them, and writes a JSON baseline.

Used by the E2E certification harness to generate ground-truth baselines
that are later compared against webapp API outputs via parity_check.py.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path setup — ensure project root and telemetry_tool are importable
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "telemetry_tool"))
sys.path.insert(0, str(TOOLS_DIR))

from normalize import normalize_dict  # noqa: E402

# ---------------------------------------------------------------------------
# Batch config locations
# ---------------------------------------------------------------------------
BATCH_CONFIG_DIR = Path(__file__).resolve().parent / "batch_configs"
DEFAULT_CONFIGS = ["OK_R1", "OK_R3", "OK_R4"]


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_batch_config(config_path: str) -> dict:
    """Load a JSON batch configuration file.

    Parameters
    ----------
    config_path : str
        Path to a JSON file containing session_type, track_state, and
        drivers list.

    Returns
    -------
    dict
        Parsed configuration.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Pipeline invocation
# ---------------------------------------------------------------------------
def run_old_tool(csv_path: str, config: dict) -> dict:
    """Import and call ``run_full_analysis()`` from ``telemetry_tool.pipeline``.

    Parameters
    ----------
    csv_path : str
        Path to the RaceChrono/RaceBox CSV file.
    config : dict
        Batch configuration with ``session_type``, ``track_state``, and
        ``drivers`` list.  The first driver entry is used.

    Returns
    -------
    dict
        Raw result dict from ``run_full_analysis()``.
    """
    from telemetry_tool.pipeline import run_full_analysis

    session_meta: dict[str, Any] = {
        "session_type": config.get("session_type", "practice"),
        "track_state": config.get("track_state", "dry"),
    }

    # Extract driver-specific settings from the first driver entry
    drivers = config.get("drivers", [])
    driver_cfg = drivers[0] if drivers else {}

    lap_range: Optional[tuple[int, int]] = None
    raw_range = driver_cfg.get("lap_range")
    if raw_range is not None:
        lap_range = tuple(raw_range)  # type: ignore[arg-type]

    driver_tag: Optional[str] = driver_cfg.get("name")

    result = run_full_analysis(
        csv_path=csv_path,
        session_meta=session_meta,
        enable_ml=False,
        enable_report=False,
        lap_range=lap_range,
        driver_tag=driver_tag,
    )

    return result


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------
def extract_comparable_metrics(raw_result: dict) -> dict:
    """Extract key fields from a raw pipeline result for parity comparison.

    All accesses use ``.get()`` so that partially-failed pipeline runs
    still produce a valid (sparse) metrics dict.

    Parameters
    ----------
    raw_result : dict
        The dict returned by ``run_full_analysis()``.

    Returns
    -------
    dict
        Flat-ish dict of comparable metrics suitable for normalization
        and parity checking.
    """
    score_result = raw_result.get("score_result") or {}
    corners = raw_result.get("corners") or []
    lap_metrics = raw_result.get("lap_metrics") or []
    delta_segments = raw_result.get("delta_segments") or []
    segment_losses = raw_result.get("segment_losses") or []
    track_match = raw_result.get("track_match")

    return {
        # --- Scores ---
        "scores": {
            "pace": score_result.get("pace"),
            "consistency": score_result.get("consistency"),
            "execution": score_result.get("execution"),
            "robustness": score_result.get("robustness"),
            "total_score": score_result.get("total_score"),
            "grade": score_result.get("grade"),
        },
        # --- Lap times ---
        "lap_times": raw_result.get("lap_times") or [],
        # --- Corners ---
        "corner_count": len(corners),
        "corners": corners,
        # --- Metrics ---
        "consistency_metrics": raw_result.get("consistency_metrics"),
        "robustness_metrics": raw_result.get("robustness_metrics"),
        "theoretical_metrics": raw_result.get("theoretical_metrics"),
        # --- Counts ---
        "lap_metrics_count": len(lap_metrics),
        "delta_segments_count": len(delta_segments),
        "segment_losses_count": len(segment_losses),
        # --- Track ---
        "track_id": raw_result.get("track_id"),
        "track_match": {
            "name": track_match.get("name") if track_match else None,
            "length_m": track_match.get("length_m") if track_match else None,
        },
        # --- Pipeline health ---
        "steps_ok": raw_result.get("steps_ok") or [],
        "steps_failed": raw_result.get("steps_failed") or [],
    }


# ---------------------------------------------------------------------------
# Full baseline generation
# ---------------------------------------------------------------------------
def generate_baseline(
    csv_path: str,
    config_path: str,
    output_path: str,
) -> dict:
    """Run the full pipeline: load config, run tool, extract, normalize, write.

    Parameters
    ----------
    csv_path : str
        Path to the CSV file.
    config_path : str
        Path to the JSON batch config.
    output_path : str
        Path to write the normalized JSON baseline.

    Returns
    -------
    dict
        The normalized metrics dict (same as what is written to disk).
    """
    config = load_batch_config(config_path)
    raw_result = run_old_tool(csv_path, config)
    metrics = extract_comparable_metrics(raw_result)
    normalized = normalize_dict(metrics)

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, sort_keys=True)

    return normalized


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Old tool runner — generate baselines from CLI pipeline"
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Path to CSV file (required unless --all)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to batch config JSON (required unless --all)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write the baseline JSON (required unless --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all default configs (OK_R1, OK_R3, OK_R4)",
    )

    args = parser.parse_args()

    if args.all:
        for name in DEFAULT_CONFIGS:
            config_path = str(BATCH_CONFIG_DIR / f"{name}.json")
            csv_path = str(ROOT / "data" / "raw" / f"{name}.csv")
            output_path = str(
                ROOT / "audit" / "baselines" / "old_tool" / f"{name}.json"
            )
            print(f"[RUN] {name}: {csv_path} -> {output_path}")
            try:
                result = generate_baseline(csv_path, config_path, output_path)
                n_steps_ok = len(result.get("steps_ok", []))
                n_steps_fail = len(result.get("steps_failed", []))
                print(f"  OK  steps={n_steps_ok}, failed={n_steps_fail}")
            except Exception as e:
                print(f"  FAIL  {e}")
    else:
        if not args.csv or not args.config or not args.output:
            parser.error("--csv, --config, and --output are required (or use --all)")
        result = generate_baseline(args.csv, args.config, args.output)
        n_steps_ok = len(result.get("steps_ok", []))
        n_steps_fail = len(result.get("steps_failed", []))
        print(f"Baseline generated: steps_ok={n_steps_ok}, steps_failed={n_steps_fail}")
        print(f"Written to: {args.output}")


if __name__ == "__main__":
    main()
