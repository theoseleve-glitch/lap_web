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

    result = analyze_session(
        csv_path=Path(args.csv_path),
        metadata=meta,
        config=config,
        models_dir=Path(args.models_dir),
        tracks_dir=Path(args.tracks_dir),
        output_dir=Path(args.output_dir),
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

    # --- train ---
    p_train = sub.add_parser("train", help="Train envelope library.")
    p_train.add_argument("metadata_path", type=str,
                          help="Metadata file listing all sessions.")
    p_train.add_argument("--config", type=Path, default=None)
    p_train.add_argument("--data-dir", type=str, default=".")
    p_train.add_argument("--models-dir", type=str, default="models")
    p_train.add_argument("--tracks-dir", type=str, default="tracks")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.command == "analyze":
        _cmd_analyze(args)
    elif args.command == "train":
        _cmd_train(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
