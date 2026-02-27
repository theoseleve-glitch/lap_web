#!/usr/bin/env python3
"""
run_batch_optimal.py
--------------------
Train on all sessions, then run all-session + all-lap optimal sweeps.

Outputs:
  - per-session files in ``data/outputs/<session_id>/``
  - global table ``data/outputs/batch_all_laps_optimal.csv``
  - global summary ``data/outputs/batch_all_laps_optimal_summary.json``

When ``--session`` is used, results are merged into an existing global batch
file (if present) instead of overwriting all other sessions.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from kart_envelope.config import default_config
from kart_envelope.ingest.metadata import SessionMetadata, parse_metadata
from kart_envelope.pipeline import analyze_session, train_library

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _build_session_list(
    metadata_path: Path,
    data_dir: Path,
    session_filter: str | None,
) -> list[tuple[Path, SessionMetadata]]:
    meta = parse_metadata(metadata_path)
    rows: list[tuple[Path, SessionMetadata]] = []
    for m in meta:
        if session_filter:
            filt = session_filter.strip().lower()
            if filt not in m.session_file.lower() and filt != Path(m.session_file).stem.lower():
                continue
        csv_path = data_dir / m.session_file
        if not csv_path.exists():
            logger.warning("Missing CSV (skip): %s", csv_path)
            continue
        rows.append((csv_path, m))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch all-lap optimal analysis.")
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data") / "session_metadata.csv",
        help="Metadata file (CSV/JSON/YAML).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory containing telemetry CSV files.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("data") / "models" / "kart_envelope",
        help="Directory for trained envelope models.",
    )
    parser.add_argument(
        "--tracks-dir",
        type=Path,
        default=Path("data") / "models" / "tracks",
        help="Directory for track geometry cache.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data") / "outputs",
        help="Directory for per-session outputs.",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Optional session filter (full filename or stem substring).",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="Skip envelope library training and reuse existing model files.",
    )
    parser.add_argument("--product-tier", type=str, choices=("b2c", "b2b_basic", "b2b_premium"), default=None)
    parser.add_argument("--b2b-whitelist-tracks", type=str, default=None)
    parser.add_argument("--b2b-whitelist-karts", type=str, default=None)
    parser.add_argument("--b2b-whitelist-layouts", type=str, default=None)
    parser.add_argument("--strict-domain", action="store_true")
    args = parser.parse_args()

    session_files = _build_session_list(args.metadata, args.data_dir, args.session)
    if not session_files:
        logger.error("No sessions resolved from metadata.")
        sys.exit(1)

    cfg = default_config()
    if args.product_tier:
        cfg = replace(cfg, product_tier=args.product_tier)
    if args.b2b_whitelist_tracks is not None:
        cfg = replace(cfg, b2b_whitelist_track_ids=args.b2b_whitelist_tracks)
    if args.b2b_whitelist_karts is not None:
        cfg = replace(cfg, b2b_whitelist_kart_ids=args.b2b_whitelist_karts)
    if args.b2b_whitelist_layouts is not None:
        cfg = replace(cfg, b2b_whitelist_layout_ids=args.b2b_whitelist_layouts)
    if args.strict_domain:
        cfg = replace(cfg, domain_soft_gate_enable=False)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_train:
        logger.info("Training library from %d session(s)...", len(session_files))
        t0 = time.time()
        train_library(
            session_files=session_files,
            config=cfg,
            models_dir=args.models_dir,
            tracks_dir=args.tracks_dir,
        )
        logger.info("Training complete in %.1fs.", time.time() - t0)

    all_rows: list[dict[str, object]] = []
    session_stats: list[dict[str, object]] = []
    for csv_path, meta in session_files:
        logger.info("Analyzing %s ...", meta.session_file)
        if args.product_tier:
            meta.product_tier = args.product_tier
        result = analyze_session(
            csv_path=csv_path,
            metadata=meta,
            config=cfg,
            models_dir=args.models_dir,
            tracks_dir=args.tracks_dir,
            output_dir=args.output_dir,
            optimize_all_laps=True,
        )
        if result.get("errors"):
            logger.warning("Session %s produced warnings: %s", meta.session_file, result["errors"])

        session_id = Path(meta.session_file).stem
        lap_csv = args.output_dir / session_id / "all_laps_optimal.csv"
        if not lap_csv.exists():
            logger.warning("No all-laps output for %s", session_id)
            continue
        df = pd.read_csv(lap_csv)
        if df.empty:
            continue
        df["session_id"] = session_id
        df["session_file"] = meta.session_file
        df["track_name"] = meta.track_name
        df["kart_id"] = meta.kart_id
        df["condition_label"] = meta.condition_label
        all_rows.extend(df.to_dict(orient="records"))

        best_gain = float(df["gain_s"].max()) if "gain_s" in df.columns else 0.0
        mean_gain = float(df["gain_s"].mean()) if "gain_s" in df.columns else 0.0
        session_stats.append({
            "session_id": session_id,
            "session_file": meta.session_file,
            "n_laps": int(len(df)),
            "best_gain_s": round(best_gain, 4),
            "mean_gain_s": round(mean_gain, 4),
        })

    if not all_rows:
        logger.error("No batch all-laps rows produced.")
        sys.exit(2)

    batch_df = pd.DataFrame(all_rows)
    batch_path = args.output_dir / "batch_all_laps_optimal.csv"

    # Incremental mode: keep previously computed sessions when filtering to one
    # session, replacing only the sessions computed in this run.
    if args.session and batch_path.exists():
        try:
            old_df = pd.read_csv(batch_path)
            if not old_df.empty and "session_id" in old_df.columns:
                new_session_ids = set(batch_df["session_id"].astype(str).tolist())
                old_keep = old_df[~old_df["session_id"].astype(str).isin(new_session_ids)]
                batch_df = pd.concat([old_keep, batch_df], ignore_index=True)
                logger.info(
                    "Merged filtered run with existing batch: kept %d old rows, added %d new rows.",
                    len(old_keep),
                    len(all_rows),
                )
        except Exception as exc:
            logger.warning("Failed to merge with existing batch CSV, writing fresh file: %s", exc)

    batch_df.to_csv(batch_path, index=False)

    # Rebuild per-session stats from the final batch table to reflect either
    # full or merged incremental runs.
    grouped_stats: list[dict[str, object]] = []
    for session_id, g in batch_df.groupby("session_id", sort=True):
        grouped_stats.append({
            "session_id": str(session_id),
            "session_file": str(g["session_file"].iloc[0]) if "session_file" in g.columns else f"{session_id}.csv",
            "n_laps": int(len(g)),
            "best_gain_s": round(float(g["gain_s"].max()), 4),
            "mean_gain_s": round(float(g["gain_s"].mean()), 4),
        })

    summary = {
        "sessions_processed": int(batch_df["session_id"].nunique()),
        "rows": int(len(batch_df)),
        "global_best_gain_s": round(float(batch_df["gain_s"].max()), 4),
        "global_mean_gain_s": round(float(batch_df["gain_s"].mean()), 4),
        "session_stats": grouped_stats,
        "csv_path": str(batch_path).replace("\\", "/"),
    }
    summary_path = args.output_dir / "batch_all_laps_optimal_summary.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    logger.info("Wrote %s (%d rows).", batch_path, len(batch_df))
    logger.info("Wrote %s.", summary_path)


if __name__ == "__main__":
    main()
