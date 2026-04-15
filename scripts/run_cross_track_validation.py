"""CLI entry point for the cross-track friction validation suite.

Usage
-----
    python scripts/run_cross_track_validation.py \
        --manifest data/cross_track_manifest.json \
        --out validation_out/

    python scripts/run_cross_track_validation.py \
        --manifest data/cross_track_manifest.json \
        --out validation_out/ \
        --adaptive \
        --only daytona_mclaren570sgt4 spa_bmwm2csr

Behavior
--------
- Pass 1 (frozen) always runs.
- Pass 2 (adaptive) only runs with --adaptive.
- Missing .ibt files are skipped by default (so an incomplete machine
  setup doesn't abort the whole suite); pass --strict to fail-fast.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "telemetry_tool"))

from track_surface.validation import run_validation_suite  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cross-track validation suite for the friction estimation pipeline.",
    )
    p.add_argument(
        "--manifest", type=Path, required=True,
        help="Path to JSON manifest (see docs / examples).",
    )
    p.add_argument(
        "--out", type=Path, required=True,
        help="Output directory (passes write to subdirs pass_1_frozen / pass_2_adaptive).",
    )
    p.add_argument(
        "--adaptive", action="store_true",
        help="Also run Pass 2 (adaptation sensitivity) — writes to a separate dir.",
    )
    p.add_argument(
        "--only", nargs="*", default=None, metavar="DATASET_ID",
        help="Restrict to these dataset ids (default: all).",
    )
    p.add_argument(
        "--strict", action="store_true",
        help="Fail-fast on missing IBT files (default: skip and continue).",
    )
    p.add_argument(
        "--registry", type=Path, default=None, metavar="PATH",
        help="Path to vehicle calibration registry JSON (enables registry-driven calibration).",
    )
    p.add_argument(
        "--accumulator-dir", type=Path, default=None, metavar="DIR",
        help="Directory for cross-session accumulators (enables accumulator + layered query).",
    )
    p.add_argument(
        "--legacy-gate", action="store_true",
        help="Use the legacy single-axis bank-gradient transition gate (default: multi-criterion).",
    )
    p.add_argument(
        "--verbose", "-v", action="count", default=0,
        help="-v info, -vv debug",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    log_level = logging.WARNING
    if args.verbose >= 2:
        log_level = logging.DEBUG
    elif args.verbose >= 1:
        log_level = logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    results = run_validation_suite(
        manifest_path=args.manifest,
        out_dir=args.out,
        pass_2_adaptive=args.adaptive,
        only_datasets=args.only,
        skip_missing=not args.strict,
        calibration_registry_path=args.registry,
        accumulator_dir=args.accumulator_dir,
        use_multi_criterion_gate=not args.legacy_gate,
    )

    # Human summary to stdout
    print()
    print("=" * 70)
    print("CROSS-TRACK VALIDATION COMPLETE")
    print("=" * 70)
    for pass_label, suite in results.items():
        print(f"\n[{pass_label}] {suite.n_total} sessions:")
        print(f"  PASS: {suite.n_pass}")
        print(f"  WARN: {suite.n_warn}")
        print(f"  FAIL: {suite.n_fail}")
        print(f"  Reports: {suite.out_dir}/aggregate.md")
        print(f"           {suite.out_dir}/suite_summary.json")
        print(f"           {suite.out_dir}/sessions/*.json")

    # Exit code: non-zero if any FAIL in the frozen pass
    frozen = results.get("frozen")
    if frozen and frozen.n_fail > 0:
        print(f"\nFROZEN PASS HAS {frozen.n_fail} FAILURE(S)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
