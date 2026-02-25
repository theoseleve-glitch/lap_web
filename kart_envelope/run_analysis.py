#!/usr/bin/env python3
"""
run_analysis.py
---------------
Run the full kart_envelope analysis pipeline on a session CSV.

Uses trained capability envelopes to:
1. Infer session conditions (grip/power/brake scalars)
2. Compute the theoretical minimum-time lap
3. Compute delta maps (actual vs theoretical)
4. Generate corner-by-corner coaching tips

Usage:
    python kart_envelope/run_analysis.py                     # analyse CKS_FP+Q.csv
    python kart_envelope/run_analysis.py --session OK_R4.csv # analyse specific session
    python kart_envelope/run_analysis.py --all               # analyse all sessions
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Ensure project root on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from kart_envelope.config import default_config
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.pipeline import analyze_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_metadata() -> list[dict]:
    """Load sessions metadata."""
    meta_path = Path(__file__).resolve().parent / "data" / "sessions_metadata.json"
    with open(meta_path, encoding="utf-8") as fh:
        return json.load(fh)["sessions"]


def run_one(session_entry: dict) -> dict | None:
    """Run analysis for a single session."""
    project_root = Path(__file__).resolve().parent.parent
    raw_dir = project_root / "data" / "raw"
    models_dir = project_root / "data" / "models" / "kart_envelope"
    tracks_dir = project_root / "data" / "models" / "tracks"
    output_dir = project_root / "data" / "outputs"

    csv_path = raw_dir / session_entry["session_file"]
    if not csv_path.exists():
        logger.error("CSV not found: %s", csv_path)
        return None

    meta = SessionMetadata(
        session_file=session_entry["session_file"],
        kart_id=session_entry.get("kart_id", "unknown_kart"),
        kart_class=session_entry.get("kart_class", "4t"),
        track_name=session_entry.get("track_name"),
        condition_label=session_entry.get("condition_label"),
        track_record_s=session_entry.get("track_record_s"),
        notes=session_entry.get("notes", ""),
    )

    logger.info("=" * 70)
    logger.info("ANALYSING: %s", session_entry["session_file"])
    logger.info("  Track: %s | Kart: %s | Condition: %s | Record: %s",
                meta.track_name, meta.kart_id,
                meta.condition_label, meta.track_record_s)
    logger.info("=" * 70)

    config = default_config()
    t0 = time.time()

    result = analyze_session(
        csv_path=csv_path,
        metadata=meta,
        config=config,
        models_dir=models_dir,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
    )

    elapsed = time.time() - t0

    # Print results
    logger.info("-" * 70)
    logger.info("RESULTS for %s (%.1f s):", session_entry["session_file"], elapsed)

    if result.get("errors"):
        for err in result["errors"]:
            logger.error("  ERROR: %s", err)

    if "session_scalars" in result:
        sc = result["session_scalars"]
        logger.info("  Session scalars: grip=%.2f, power=%.2f, brake=%.2f (%s)",
                     sc["mu"], sc["p"], sc["b"], sc["condition"])

    if "theoretical_lap_time_s" in result:
        logger.info("  Theoretical lap time: %.3f s", result["theoretical_lap_time_s"])

    if "coaching_text" in result:
        logger.info("  Coaching summary:")
        for line in result["coaching_text"].split("\n"):
            logger.info("    %s", line)

    if "output_dir" in result:
        logger.info("  Outputs written to: %s", result["output_dir"])

    logger.info("-" * 70)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run kart envelope session analysis")
    parser.add_argument("--session", type=str, default=None,
                        help="Session CSV filename (e.g. CKS_FP+Q.csv)")
    parser.add_argument("--all", action="store_true",
                        help="Analyse all sessions in metadata")
    args = parser.parse_args()

    meta_data = load_metadata()

    if args.all:
        # Run all sessions
        results = {}
        for entry in meta_data:
            result = run_one(entry)
            if result:
                results[entry["session_file"]] = result

        logger.info("\n" + "=" * 70)
        logger.info("ALL SESSIONS COMPLETE (%d/%d)", len(results), len(meta_data))
        logger.info("=" * 70)

        # Summary table
        logger.info("%-20s %-8s %-8s %-10s %-10s %-10s",
                     "Session", "Track", "Cond", "Theory(s)", "Grip", "Power")
        for name, res in results.items():
            sc = res.get("session_scalars", {})
            theo = res.get("theoretical_lap_time_s", 0)
            logger.info("%-20s %-8s %-8s %-10.3f %-10.2f %-10.2f",
                         name[:20],
                         res.get("track_id", "?"),
                         sc.get("condition", "?"),
                         theo,
                         sc.get("mu", 0),
                         sc.get("p", 0))
    else:
        # Run single session
        session_name = args.session or "CKS_FP+Q.csv"
        entry = next((e for e in meta_data if e["session_file"] == session_name), None)
        if entry is None:
            logger.error("Session '%s' not found in metadata. Available sessions:", session_name)
            for e in meta_data:
                logger.info("  %s", e["session_file"])
            sys.exit(1)

        run_one(entry)


if __name__ == "__main__":
    main()
