#!/usr/bin/env python3
"""
run_training.py
---------------
Train capability envelopes from all available session data.

Groups sessions by (track, kart) and produces one envelope JSON per group.

Usage:
    python -m kart_envelope.run_training
    python kart_envelope/run_training.py
"""
from __future__ import annotations

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
from kart_envelope.pipeline import train_library

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    raw_dir = project_root / "data" / "raw"
    meta_path = Path(__file__).resolve().parent / "data" / "sessions_metadata.json"
    models_dir = project_root / "data" / "models" / "kart_envelope"
    tracks_dir = project_root / "data" / "models" / "tracks"

    # Load metadata
    with open(meta_path, encoding="utf-8") as fh:
        meta_data = json.load(fh)

    sessions: list[tuple[Path, SessionMetadata]] = []
    for entry in meta_data["sessions"]:
        csv_path = raw_dir / entry["session_file"]
        if not csv_path.exists():
            logger.warning("CSV not found, skipping: %s", csv_path)
            continue

        meta = SessionMetadata(
            session_file=entry["session_file"],
            kart_id=entry.get("kart_id", "unknown_kart"),
            kart_class=entry.get("kart_class", "4t"),
            track_name=entry.get("track_name"),
            condition_label=entry.get("condition_label"),
            track_record_s=entry.get("track_record_s"),
            notes=entry.get("notes", ""),
        )
        sessions.append((csv_path, meta))
        logger.info("Queued: %s (track=%s, kart=%s, condition=%s)",
                     entry["session_file"], meta.track_name,
                     meta.kart_id, meta.condition_label)

    logger.info("=" * 60)
    logger.info("Training with %d sessions across %d track/kart combos",
                len(sessions),
                len({(m.track_name, m.kart_id) for _, m in sessions}))
    logger.info("=" * 60)

    config = default_config()
    t0 = time.time()

    results = train_library(
        session_files=sessions,
        config=config,
        models_dir=models_dir,
        tracks_dir=tracks_dir,
    )

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("Training complete in %.1f s", elapsed)

    for name, info in results.get("envelopes", {}).items():
        logger.info("  Envelope: %-30s | %d sessions, %d laps, p=%.2f | %s",
                     name, info["n_sessions"], info["n_laps"],
                     info["p_combined"], info["path"])

    # Save summary
    summary_path = models_dir / "training_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    logger.info("Summary written to %s", summary_path)


if __name__ == "__main__":
    main()
