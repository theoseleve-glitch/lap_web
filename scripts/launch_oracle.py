#!/usr/bin/env python
"""Launch script for the Lap Oracle system.

Usage
-----
    python scripts/launch_oracle.py              # full 48-hour run
    python scripts/launch_oracle.py --quick      # quick 30-min run
    python scripts/launch_oracle.py --status     # show progress and exit
    python scripts/launch_oracle.py --resume     # resume from checkpoint

See ``--help`` for all options.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.orchestrator import Orchestrator


def _show_status(config: OracleConfig) -> None:
    """Print current progress.json and exit."""
    progress_path = config.data_dir / "reports" / "progress.json"
    if not progress_path.exists():
        print("No progress file found. Has the oracle been started?")
        sys.exit(1)
    data = json.loads(progress_path.read_text(encoding="utf-8"))
    print(json.dumps(data, indent=2))


def _build_config(args: argparse.Namespace) -> OracleConfig:
    """Construct OracleConfig from parsed CLI arguments."""
    cfg = OracleConfig()

    cfg.run_hours = args.hours

    if args.quick:
        cfg.run_hours = 0.5
        cfg.harvest_workers = 2
        cfg.identify_workers = 1
        cfg.solve_workers = 2
        cfg.sweep_workers = 1

    if args.no_ac_driver:
        cfg.enable_ac_driver = False

    if args.no_gpu:
        cfg.enable_neural_training = False

    return cfg


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lap Oracle -- offline theoretical lap computation",
    )
    parser.add_argument(
        "--hours", type=float, default=48.0,
        help="Total run time in hours (default: 48)",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick mode: 30-min run with reduced workers",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from existing checkpoint (DataLake persists on disk)",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show progress.json and exit",
    )
    parser.add_argument(
        "--sims", type=str, default="",
        help="Comma-separated sim filter (placeholder, not yet wired)",
    )
    parser.add_argument(
        "--no-ac-driver", action="store_true",
        help="Disable Assetto Corsa RL driver",
    )
    parser.add_argument(
        "--no-gpu", action="store_true",
        help="Disable neural surrogate training (no GPU required)",
    )

    args = parser.parse_args()
    config = _build_config(args)

    if args.status:
        _show_status(config)
        return

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("lap_oracle")

    if args.sims:
        logger.info("Sim filter requested: %s (not yet wired)", args.sims)

    logger.info(
        "Starting Lap Oracle -- %.1f hours, resume=%s",
        config.run_hours, args.resume,
    )

    orch = Orchestrator(config, resume=args.resume)

    try:
        orch.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt -- shutting down gracefully")
        orch.stop()


if __name__ == "__main__":
    main()
