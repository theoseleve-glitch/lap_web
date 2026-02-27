#!/usr/bin/env python3
"""
train_offline.py
----------------
Offline-heavy training pipeline that builds bundle_v2 artifacts.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from kart_envelope.config import default_config
from kart_envelope.offline.bundle_packager import (
    train_and_package_bundles,
    train_and_package_three_tier_bundles,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train offline bundle_v2 artifacts.")
    parser.add_argument("--metadata", type=Path, default=Path("data") / "session_metadata.csv")
    parser.add_argument("--outputs-dir", type=Path, default=Path("data") / "outputs")
    parser.add_argument("--models-dir", type=Path, default=Path("data") / "models" / "kart_envelope")
    parser.add_argument("--bundles-dir", type=Path, default=Path("data") / "models" / "kart_envelope" / "bundles")
    parser.add_argument("--dataset-path", type=Path, default=None)
    parser.add_argument("--counterfactual-path", type=Path, default=None)
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument("--min-rows-per-bundle", type=int, default=None)
    parser.add_argument("--counterfactual-samples", type=int, default=None)
    parser.add_argument("--counterfactual-noise-scale", type=float, default=None)
    parser.add_argument("--random-state", type=int, default=None)
    parser.add_argument("--no-global-fallback", action="store_true")
    parser.add_argument("--product-tier", type=str, default="b2c", choices=("b2c", "b2b_basic", "b2b_premium"))
    parser.add_argument("--distill-teacher-dir", type=Path, default=None)
    parser.add_argument("--three-tier", action="store_true")
    args = parser.parse_args()

    cfg = default_config()
    common_kwargs = dict(
        metadata_path=args.metadata,
        outputs_dir=args.outputs_dir,
        models_dir=args.models_dir,
        bundle_root=args.bundles_dir,
        dataset_path=args.dataset_path or Path(cfg.offline_dataset_path),
        counterfactual_path=args.counterfactual_path or Path(cfg.offline_counterfactual_path),
        report_path=args.report_path or Path(cfg.offline_training_report_path),
        min_rows_per_bundle=(
            args.min_rows_per_bundle
            if args.min_rows_per_bundle is not None
            else cfg.offline_min_rows_per_bundle
        ),
        counterfactual_samples_per_row=(
            args.counterfactual_samples
            if args.counterfactual_samples is not None
            else cfg.offline_counterfactual_samples_per_row
        ),
        counterfactual_noise_scale=(
            args.counterfactual_noise_scale
            if args.counterfactual_noise_scale is not None
            else cfg.offline_counterfactual_noise_scale
        ),
        random_state=(
            args.random_state
            if args.random_state is not None
            else cfg.offline_teacher_random_state
        ),
        publish_global_fallback=not args.no_global_fallback,
    )
    if args.three_tier:
        report = train_and_package_three_tier_bundles(
            **common_kwargs,
            premium_teacher_dir=Path(cfg.offline_premium_teacher_dir),
        )
    else:
        report = train_and_package_bundles(
            **common_kwargs,
            product_tier=args.product_tier,
            distill_teacher_dir=args.distill_teacher_dir,
            tier_bundle_subdir=True,
        )
    if "bundles" in report:
        n_bundles = len(report.get("bundles", {}))
        rows_total = int(report.get("rows_total", 0))
    else:
        n_bundles = int(sum(
            len((rep or {}).get("bundles", {}))
            for rep in (report.get("reports", {}) or {}).values()
            if isinstance(rep, dict)
        ))
        rows_total = int(sum(
            int((rep or {}).get("rows_total", 0))
            for rep in (report.get("reports", {}) or {}).values()
            if isinstance(rep, dict)
        ))
    logger.info(
        "Offline training complete: %d bundle(s), rows=%d",
        n_bundles,
        rows_total,
    )


if __name__ == "__main__":
    main()
