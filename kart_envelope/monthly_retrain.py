#!/usr/bin/env python3
"""
monthly_retrain.py
------------------
Run a full monthly three-tier retraining wave and persist an audit manifest.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from kart_envelope.config import default_config
from kart_envelope.offline.bundle_packager import train_and_package_three_tier_bundles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    cfg = default_config()
    parser = argparse.ArgumentParser(description="Run monthly three-tier retraining.")
    parser.add_argument("--metadata", type=Path, default=Path("data") / "session_metadata.csv")
    parser.add_argument("--outputs-dir", type=Path, default=Path("data") / "outputs")
    parser.add_argument("--models-dir", type=Path, default=Path("data") / "models" / "kart_envelope")
    parser.add_argument("--bundles-dir", type=Path, default=Path("data") / "models" / "kart_envelope" / "bundles")
    parser.add_argument("--dataset-path", type=Path, default=Path(cfg.offline_dataset_path))
    parser.add_argument("--counterfactual-path", type=Path, default=Path(cfg.offline_counterfactual_path))
    parser.add_argument("--report-path", type=Path, default=Path(cfg.offline_training_report_path))
    parser.add_argument("--min-rows-per-bundle", type=int, default=int(cfg.offline_min_rows_per_bundle))
    parser.add_argument("--counterfactual-samples", type=int, default=int(cfg.offline_counterfactual_samples_per_row))
    parser.add_argument("--counterfactual-noise-scale", type=float, default=float(cfg.offline_counterfactual_noise_scale))
    parser.add_argument("--random-state", type=int, default=int(cfg.offline_teacher_random_state))
    args = parser.parse_args()

    report = train_and_package_three_tier_bundles(
        metadata_path=args.metadata,
        outputs_dir=args.outputs_dir,
        models_dir=args.models_dir,
        bundle_root=args.bundles_dir,
        dataset_path=args.dataset_path,
        counterfactual_path=args.counterfactual_path,
        report_path=args.report_path,
        min_rows_per_bundle=args.min_rows_per_bundle,
        counterfactual_samples_per_row=args.counterfactual_samples,
        counterfactual_noise_scale=args.counterfactual_noise_scale,
        random_state=args.random_state,
        publish_global_fallback=bool(cfg.offline_publish_global_fallback_bundle),
        premium_teacher_dir=Path(cfg.offline_premium_teacher_dir),
    )

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "monthly_three_tier_retrain",
        "report_path": str(args.report_path),
        "reports": report.get("reports", {}),
    }
    manifest_path = args.report_path.with_name(f"{args.report_path.stem}_monthly_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    logger.info("Monthly retrain complete -> %s", manifest_path)


if __name__ == "__main__":
    main()

