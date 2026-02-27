"""
cli.py
------
Command-line interface for the kart-envelope pipeline.

Usage
-----
::

    python -m kart_envelope analyze <csv_path> --metadata <meta> [--config <yaml>]
    python -m kart_envelope train <metadata_path> [--data-dir <dir>] [--models-dir <dir>]
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _cmd_analyze(args: argparse.Namespace) -> None:
    from kart_envelope.config import load_config
    from kart_envelope.ingest.metadata import parse_metadata
    from kart_envelope.pipeline import analyze_session

    config = load_config(args.config)
    if args.solver_backend:
        config = replace(config, solver_backend=args.solver_backend)
    if args.no_solver_fallback:
        config = replace(config, solver_backend_fallback_to_qss=False)
    if args.no_cache:
        config = replace(config, reuse_cached_session_outputs=False)
    if args.fast_mode:
        config = replace(config, fast_inference_mode=True)
    if args.product_tier:
        config = replace(config, product_tier=args.product_tier)
    if args.b2b_whitelist_tracks is not None:
        config = replace(config, b2b_whitelist_track_ids=args.b2b_whitelist_tracks)
    if args.b2b_whitelist_karts is not None:
        config = replace(config, b2b_whitelist_kart_ids=args.b2b_whitelist_karts)
    if args.b2b_whitelist_layouts is not None:
        config = replace(config, b2b_whitelist_layout_ids=args.b2b_whitelist_layouts)
    if args.strict_domain:
        config = replace(config, domain_soft_gate_enable=False)
    meta_list = parse_metadata(args.metadata)

    # Find metadata for this specific file
    csv_name = Path(args.csv_path).name
    meta = None
    for m in meta_list:
        if m.session_file == csv_name or m.session_file == str(args.csv_path):
            meta = m
            break

    if meta is None:
        # Use first entry or create default
        if meta_list:
            meta = meta_list[0]
            meta.session_file = csv_name
            logging.getLogger(__name__).warning(
                "No exact metadata match for %s; using first entry.", csv_name)
        else:
            from kart_envelope.ingest.metadata import SessionMetadata
            meta = SessionMetadata(session_file=csv_name)
            if args.kart_id:
                meta.kart_id = args.kart_id

    # Override from CLI args
    if args.kart_id:
        meta.kart_id = args.kart_id
    if args.record_time is not None:
        meta.track_record_s = args.record_time
    if args.product_tier:
        meta.product_tier = args.product_tier
    if args.layout_id:
        meta.layout_id = args.layout_id

    result = analyze_session(
        csv_path=Path(args.csv_path),
        metadata=meta,
        config=config,
        models_dir=Path(args.models_dir),
        tracks_dir=Path(args.tracks_dir),
        output_dir=Path(args.output_dir),
        optimize_all_laps=bool(args.optimize_all_laps),
    )

    if result.get("errors"):
        print(f"\nCompleted with {len(result['errors'])} warning(s):")
        for e in result["errors"]:
            print(f"  - {e}")

    if "theoretical_lap_time_s" in result:
        print(f"\nTheoretical lap time: {result['theoretical_lap_time_s']:.3f} s")
    if "coaching_text" in result:
        print(f"\n{result['coaching_text']}")
    if "output_dir" in result:
        print(f"\nOutputs written to: {result['output_dir']}")


def _cmd_train(args: argparse.Namespace) -> None:
    from kart_envelope.config import load_config
    from kart_envelope.ingest.metadata import parse_metadata
    from kart_envelope.pipeline import train_library

    config = load_config(args.config)
    meta_list = parse_metadata(args.metadata_path)

    data_dir = Path(args.data_dir)
    session_files = []
    for meta in meta_list:
        csv_path = data_dir / meta.session_file
        if csv_path.exists():
            session_files.append((csv_path, meta))
        else:
            logging.getLogger(__name__).warning("File not found: %s", csv_path)

    if not session_files:
        print("No session files found. Check --data-dir and metadata paths.")
        sys.exit(1)

    print(f"Training with {len(session_files)} session(s)...")
    result = train_library(
        session_files=session_files,
        config=config,
        models_dir=Path(args.models_dir),
        tracks_dir=Path(args.tracks_dir),
    )

    n_env = len(result.get("envelopes", {}))
    print(f"\nTrained {n_env} envelope(s):")
    for key, info in result.get("envelopes", {}).items():
        print(f"  {key}: {info['n_sessions']} sessions, "
              f"{info['n_laps']} laps, p={info['p_combined']:.2f}")


def _cmd_train_offline(args: argparse.Namespace) -> None:
    from kart_envelope.config import default_config
    from kart_envelope.offline.bundle_packager import (
        train_and_package_bundles,
        train_and_package_three_tier_bundles,
    )

    cfg = default_config()
    common_kwargs = dict(
        metadata_path=Path(args.metadata),
        outputs_dir=Path(args.outputs_dir),
        models_dir=Path(args.models_dir),
        bundle_root=Path(args.bundles_dir),
        dataset_path=Path(args.dataset_path or cfg.offline_dataset_path),
        counterfactual_path=Path(args.counterfactual_path or cfg.offline_counterfactual_path),
        report_path=Path(args.report_path or cfg.offline_training_report_path),
        min_rows_per_bundle=int(args.min_rows_per_bundle or cfg.offline_min_rows_per_bundle),
        counterfactual_samples_per_row=int(args.counterfactual_samples or cfg.offline_counterfactual_samples_per_row),
        counterfactual_noise_scale=float(args.counterfactual_noise_scale or cfg.offline_counterfactual_noise_scale),
        random_state=int(args.random_state or cfg.offline_teacher_random_state),
        publish_global_fallback=not bool(args.no_global_fallback),
    )
    if args.three_tier:
        report = train_and_package_three_tier_bundles(
            **common_kwargs,
            premium_teacher_dir=Path(args.premium_teacher_dir or cfg.offline_premium_teacher_dir),
        )
    else:
        report = train_and_package_bundles(
            **common_kwargs,
            product_tier=str(args.product_tier or cfg.product_tier),
            distill_teacher_dir=(Path(args.distill_teacher_dir) if args.distill_teacher_dir else None),
            tier_bundle_subdir=True,
        )
    if "bundles" in report:
        n_bundles = len(report.get("bundles", {}))
    else:
        n_bundles = int(sum(
            len((rep or {}).get("bundles", {}))
            for rep in (report.get("reports", {}) or {}).values()
            if isinstance(rep, dict)
        ))
    print(f"Offline training complete. Bundles: {n_bundles}")


def _cmd_validate_bundle(args: argparse.Namespace) -> None:
    from kart_envelope.offline.validate_bundle import validate_bundle
    rep = validate_bundle(Path(args.bundle_dir))
    print(rep)
    if rep.get("errors"):
        raise SystemExit(2)


def _cmd_retrain_schedule(args: argparse.Namespace) -> None:
    from kart_envelope.retrain_schedule import build_retrain_jobs
    payload = build_retrain_jobs(
        trigger_path=Path(args.trigger_file),
        output_path=Path(args.output_file),
        min_drift_sigma=float(args.min_drift_sigma),
    )
    print(f"Generated {len(payload.get('jobs', []))} retrain job(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kart_envelope",
        description="Kart telemetry capability-envelope analysis pipeline.",
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                         help="Enable debug logging.")
    sub = parser.add_subparsers(dest="command")

    # --- analyze ---
    p_analyze = sub.add_parser("analyze", help="Analyse a single session.")
    p_analyze.add_argument("csv_path", type=str, help="Path to RaceChrono CSV.")
    p_analyze.add_argument("--metadata", type=str, required=True,
                            help="Metadata file (CSV/JSON/YAML).")
    p_analyze.add_argument("--config", type=Path, default=None,
                            help="Config YAML (optional).")
    p_analyze.add_argument("--models-dir", type=str, default="models")
    p_analyze.add_argument("--tracks-dir", type=str, default="tracks")
    p_analyze.add_argument("--output-dir", type=str, default="outputs")
    p_analyze.add_argument("--kart-id", type=str, default=None)
    p_analyze.add_argument("--record-time", type=float, default=None,
                            help="Track record time in seconds.")
    p_analyze.add_argument(
        "--optimize-all-laps",
        action="store_true",
        help="Run per-lap optimal sweep for all clean laps.",
    )
    p_analyze.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cached session-summary reuse for this run.",
    )
    p_analyze.add_argument(
        "--fast-mode",
        action="store_true",
        help="Enable fast inference profile from config defaults.",
    )
    p_analyze.add_argument(
        "--solver-backend",
        type=str,
        choices=("qss", "casadi_ocp"),
        default=None,
        help="Minimum-time solver backend to use.",
    )
    p_analyze.add_argument(
        "--product-tier",
        type=str,
        choices=("b2c", "b2b_basic", "b2b_premium"),
        default=None,
        help="Tier contract to enforce for sensor validation and bundle resolution.",
    )
    p_analyze.add_argument("--layout-id", type=str, default=None)
    p_analyze.add_argument("--b2b-whitelist-tracks", type=str, default=None)
    p_analyze.add_argument("--b2b-whitelist-karts", type=str, default=None)
    p_analyze.add_argument("--b2b-whitelist-layouts", type=str, default=None)
    p_analyze.add_argument(
        "--strict-domain",
        action="store_true",
        help="Disable soft gate fallback and reject out-of-domain B2B sessions.",
    )
    p_analyze.add_argument(
        "--no-solver-fallback",
        action="store_true",
        help="Disable fallback to QSS if selected solver backend fails.",
    )

    # --- train ---
    p_train = sub.add_parser("train", help="Train envelope library.")
    p_train.add_argument("metadata_path", type=str,
                          help="Metadata file listing all sessions.")
    p_train.add_argument("--config", type=Path, default=None)
    p_train.add_argument("--data-dir", type=str, default=".")
    p_train.add_argument("--models-dir", type=str, default="models")
    p_train.add_argument("--tracks-dir", type=str, default="tracks")

    # --- train-offline ---
    p_off = sub.add_parser("train-offline", help="Build bundle_v2 offline artifacts.")
    p_off.add_argument("--metadata", type=str, default="data/session_metadata.csv")
    p_off.add_argument("--outputs-dir", type=str, default="data/outputs")
    p_off.add_argument("--models-dir", type=str, default="data/models/kart_envelope")
    p_off.add_argument("--bundles-dir", type=str, default="data/models/kart_envelope/bundles")
    p_off.add_argument("--dataset-path", type=str, default=None)
    p_off.add_argument("--counterfactual-path", type=str, default=None)
    p_off.add_argument("--report-path", type=str, default=None)
    p_off.add_argument("--min-rows-per-bundle", type=int, default=None)
    p_off.add_argument("--counterfactual-samples", type=int, default=None)
    p_off.add_argument("--counterfactual-noise-scale", type=float, default=None)
    p_off.add_argument("--random-state", type=int, default=None)
    p_off.add_argument("--no-global-fallback", action="store_true")
    p_off.add_argument("--product-tier", type=str, default="b2c", choices=("b2c", "b2b_basic", "b2b_premium"))
    p_off.add_argument("--distill-teacher-dir", type=str, default=None)
    p_off.add_argument("--three-tier", action="store_true")
    p_off.add_argument("--premium-teacher-dir", type=str, default=None)

    # --- validate-bundle ---
    p_val = sub.add_parser("validate-bundle", help="Validate a bundle_v2 directory.")
    p_val.add_argument("--bundle-dir", type=str, required=True)

    # --- retrain-schedule ---
    p_ret = sub.add_parser("retrain-schedule", help="Create retrain job suggestions from drift triggers.")
    p_ret.add_argument("--trigger-file", type=str, default="data/models/kart_envelope/retrain_triggers.json")
    p_ret.add_argument("--output-file", type=str, default="data/models/kart_envelope/retrain_jobs.json")
    p_ret.add_argument("--min-drift-sigma", type=float, default=2.5)

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.command == "analyze":
        _cmd_analyze(args)
    elif args.command == "train":
        _cmd_train(args)
    elif args.command == "train-offline":
        _cmd_train_offline(args)
    elif args.command == "validate-bundle":
        _cmd_validate_bundle(args)
    elif args.command == "retrain-schedule":
        _cmd_retrain_schedule(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
