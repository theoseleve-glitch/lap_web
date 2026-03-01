"""Weekly training Celery task -- train envelopes, global model, reprocess sessions.

Runs every Sunday at 00:00 UTC via Celery Beat.

Three tiers:
  1. Track-specific CapabilityEnvelopes (per track_id group, min 3 sessions)
  2. Global model bundle (offline pipeline)
  3. Reprocess all sessions with improved models
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from celery_app import celery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum sessions per track to train an envelope
_MIN_SESSIONS_PER_GROUP = 3

# Throttle: seconds between reprocess batches
_REPROCESS_PAUSE_S = 5
_REPROCESS_BATCH_SIZE = 10

# Paths (Docker volume mounts)
_DATA_RAW_DIR = Path("/data/uploads")
_MODELS_DIR = Path("/data/models/kart_envelope")
_BUNDLES_DIR = _MODELS_DIR / "bundles"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_pg_connection():
    """Return a PG connection via the web.db_pg module."""
    from web.db_pg import get_pg_connection

    return get_pg_connection()


def _gather_training_groups(conn) -> list[dict]:
    """Group non-expired sessions by track_id for envelope training.

    Returns list of dicts: [{"track_id": ..., "sessions": [...]}, ...]
    Each session dict has keys: session_id, track_id, csv_filename.
    """
    rows = conn.execute(
        "SELECT session_id, track_id, csv_filename "
        "FROM sessions "
        "WHERE retention_expired IS NOT TRUE "
        "  AND csv_filename IS NOT NULL "
        "ORDER BY track_id, session_id"
    ).fetchall()

    groups_map: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        track_id = r.get("track_id") or "unknown"
        groups_map[track_id].append(r)

    return [
        {"track_id": tid, "sessions": sessions}
        for tid, sessions in groups_map.items()
    ]


def _train_track_envelopes(groups: list[dict]) -> dict:
    """Tier 1: Train a CapabilityEnvelope per track group (>= 3 sessions)."""
    results: dict[str, Any] = {"trained": 0, "skipped": 0, "errors": []}

    for group in groups:
        track_id = group["track_id"]
        sessions = group["sessions"]

        if len(sessions) < _MIN_SESSIONS_PER_GROUP:
            results["skipped"] += 1
            logger.info(
                "Skipping track %s: only %d sessions (need %d)",
                track_id,
                len(sessions),
                _MIN_SESSIONS_PER_GROUP,
            )
            continue

        try:
            from kart_envelope.pipeline import train_library
            from kart_envelope.ingest.metadata import SessionMetadata

            session_files = []
            for sess in sessions:
                csv_path = _DATA_RAW_DIR / sess["csv_filename"]
                if not csv_path.exists():
                    continue
                meta = SessionMetadata(
                    session_file=sess["csv_filename"],
                    track_name=track_id,
                    kart_id="unknown",
                )
                session_files.append((csv_path, meta))

            if len(session_files) < _MIN_SESSIONS_PER_GROUP:
                results["skipped"] += 1
                continue

            train_library(
                session_files=session_files,
                models_dir=_MODELS_DIR,
                tracks_dir=_MODELS_DIR / "tracks",
            )
            results["trained"] += 1
            logger.info(
                "Trained envelope for track %s (%d sessions)",
                track_id,
                len(session_files),
            )

        except Exception as exc:
            results["errors"].append({"track_id": track_id, "error": str(exc)})
            logger.warning(
                "Failed to train envelope for %s",
                track_id,
                exc_info=True,
            )

    return results


def _train_global_model() -> dict:
    """Tier 2: Train global model bundle via offline pipeline."""
    try:
        from kart_envelope.config import default_config
        from kart_envelope.offline.bundle_packager import (
            train_and_package_three_tier_bundles,
        )

        cfg = default_config()
        report = train_and_package_three_tier_bundles(
            metadata_path=_DATA_RAW_DIR / "session_metadata.csv",
            outputs_dir=_DATA_RAW_DIR.parent / "outputs",
            models_dir=_MODELS_DIR,
            bundle_root=_BUNDLES_DIR,
            dataset_path=Path(cfg.offline_dataset_path),
            counterfactual_path=Path(cfg.offline_counterfactual_path),
            report_path=Path(cfg.offline_training_report_path),
        )
        return {
            "status": "ok",
            "report_keys": list(report.keys()) if isinstance(report, dict) else "done",
        }
    except Exception as exc:
        logger.warning("Global model training failed (non-fatal)", exc_info=True)
        return {"status": "failed", "error": str(exc)}


def _reprocess_sessions(sessions: list[dict], data_dir: str = "/data/uploads") -> dict:
    """Tier 3: Re-run pipeline on each session with updated models."""
    from pipeline import run_full_analysis
    from tasks.pipeline_tasks import _store_theoretical_data

    results: dict[str, Any] = {"succeeded": 0, "failed": 0, "errors": []}

    for i, sess in enumerate(sessions):
        session_id = sess["session_id"]
        csv_path = Path(data_dir) / sess["csv_filename"]

        if not csv_path.exists():
            results["failed"] += 1
            results["errors"].append(
                {"session_id": session_id, "error": "CSV not found"}
            )
            continue

        try:
            result = run_full_analysis(
                csv_path=str(csv_path),
                session_meta={"session_id": session_id},
                enable_report=False,
            )

            if result.get("theoretical_metrics"):
                conn = _get_pg_connection()
                _store_theoretical_data(session_id, result, conn=conn)

            results["succeeded"] += 1
            logger.info(
                "Reprocessed %s (%d/%d)", session_id, i + 1, len(sessions)
            )

        except Exception as exc:
            results["failed"] += 1
            results["errors"].append(
                {"session_id": session_id, "error": str(exc)}
            )
            logger.warning(
                "Reprocess failed for %s", session_id, exc_info=True
            )

        # Throttle to avoid overloading
        if (i + 1) % _REPROCESS_BATCH_SIZE == 0:
            time.sleep(_REPROCESS_PAUSE_S)

    return results


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(
    name="tasks.training_tasks.weekly_retrain_and_reprocess",
    soft_time_limit=7200,  # 2 hours
    time_limit=9000,  # 2.5 hours hard
    queue="pipeline",
)
def weekly_retrain_and_reprocess() -> dict:
    """Weekly training: envelopes, global model, reprocess all sessions.

    Scheduled via Celery Beat every Sunday at 00:00 UTC.
    """
    start = time.time()
    audit: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tiers": {},
    }

    conn = _get_pg_connection()

    # Tier 1: Track-specific envelopes
    logger.info("=== Tier 1: Training track-specific envelopes ===")
    groups = _gather_training_groups(conn)
    tier1 = _train_track_envelopes(groups)
    audit["tiers"]["envelopes"] = tier1

    # Tier 2: Global model bundle
    logger.info("=== Tier 2: Training global model bundle ===")
    tier2 = _train_global_model()
    audit["tiers"]["global_model"] = tier2

    # Tier 3: Reprocess all sessions
    logger.info("=== Tier 3: Reprocessing all sessions ===")
    all_sessions = []
    for group in groups:
        all_sessions.extend(group["sessions"])
    tier3 = _reprocess_sessions(all_sessions, data_dir=str(_DATA_RAW_DIR))
    audit["tiers"]["reprocess"] = tier3

    elapsed = round(time.time() - start, 1)
    audit["elapsed_s"] = elapsed
    audit["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Save audit manifest
    audit_dir = _MODELS_DIR / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = (
        audit_dir
        / f"training_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    )
    try:
        with open(manifest_path, "w") as fh:
            json.dump(audit, fh, indent=2)
    except Exception:
        logger.warning("Failed to write audit manifest", exc_info=True)

    logger.info(
        "Weekly retrain complete in %.1fs: envelopes=%d, reprocessed=%d/%d",
        elapsed,
        tier1["trained"],
        tier3["succeeded"],
        tier3["succeeded"] + tier3["failed"],
    )
    return audit
