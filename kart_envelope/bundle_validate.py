#!/usr/bin/env python3
"""
bundle_validate.py
------------------
Validate one bundle_v2 artifact directory.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from kart_envelope.offline.validate_bundle import validate_bundle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate bundle_v2 artifacts.")
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    report = validate_bundle(args.bundle_dir)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    logger.info("Bundle validation report: %s", report)
    if report.get("errors"):
        sys.exit(2)


if __name__ == "__main__":
    main()

