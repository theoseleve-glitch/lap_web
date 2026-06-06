"""Bi-weekly training Celery task -- train envelopes, ML models, reprocess sessions.

Scheduled every Sunday at 00:00 UTC via Celery Beat, but only executes
on even ISO-week numbers (i.e. every two weeks).

Five tiers:
  1. Track-specific CapabilityEnvelopes (per track_id group, min 3 sessions)
  2. Global kart_envelope model bundle (offline pipeline)
  3. ML engine models (global GBR, per-driver GBR + IsolationForest, anomaly)
  4. Reprocess all sessions with improved models
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

# Redis config key
_CONFIG_REDIS_KEY = "lap:training:config"

# Bi-weekly interval: run on even ISO week numbers (0 = every week)
_SCHEDULE_INTERVAL_WEEKS = 2

# Paths (Docker volume mounts)
_DATA_RAW_DIR = Path("/data/uploads")
_MODELS_DIR = Path("/data/models/kart_envelope")
_BUNDLES_DIR = _MODELS_DIR / "bundles"
_ML_DATA_DIR = Path("/data")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_redis_config():
    """Get a Redis client for config reading."""
    try:
        import redis

        from web.config import Config

        return redis.Redis.from_url(
            Config.REDIS_URL, socket_timeout=2, decode_responses=True,
        )
    except Exception:
        return None


def _load_training_config() -> dict:
    """Load training config from Redis, fallback to hardcoded defaults."""
    defaults = {
        "min_sessions_per_group": _MIN_SESSIONS_PER_GROUP,
        "reprocess_batch_size": _REPROCESS_BATCH_SIZE,
        "reprocess_pause_s": _REPROCESS_PAUSE_S,
        "schedule_interval_weeks": _SCHEDULE_INTERVAL_WEEKS,
    }
    r = _get_redis_config()
    if r:
        try:
            overrides = r.hgetall(_CONFIG_REDIS_KEY)
            for key, val in overrides.items():
                if key in defaults:
                    defaults[key] = int(val)
        except Exception:
            pass
    return defaults


def _get_pg_connection():
    """Return a standalone maintenance PG connection (BYPASSRLS role).

    Model training is inherently CROSS-TENANT: it reads sessions/drivers
    across ALL workspaces. The app role (``telemetry_app``) is NOBYPASSRLS,
    so reads over RLS-enabled tables (``sessions``, ``drivers``) fail closed
    when no ``app.current_workspace_id`` GUC is set. We therefore use the
    maint DSN (``telemetry_maint``, BYPASSRLS but NOSUPERUSER).

    NOTE: this returns a STANDALONE connection (never cached on flask.g).
    Every caller MUST close it via ``return_pg_connection`` in a finally.
    """
    from web.db_pg import get_maint_connection

    return get_maint_connection()


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


def _train_track_envelopes(
    groups: list[dict], min_sessions: int = _MIN_SESSIONS_PER_GROUP,
) -> dict:
    """Tier 1: Train a CapabilityEnvelope per track group (>= min_sessions)."""
    results: dict[str, Any] = {"trained": 0, "skipped": 0, "errors": []}

    for group in groups:
        track_id = group["track_id"]
        sessions = group["sessions"]

        if len(sessions) < min_sessions:
            results["skipped"] += 1
            logger.info(
                "Skipping track %s: only %d sessions (need %d)",
                track_id,
                len(sessions),
                min_sessions,
            )
            continue

        try:
            from kart_envelope.ingest.metadata import SessionMetadata
            from kart_envelope.pipeline import train_library

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

            if len(session_files) < min_sessions:
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


def _train_ml_models(conn) -> dict:
    """Tier 3: Train ML engine models (global, per-driver, anomaly).

    Uses the accumulated features Parquet file as the training dataset.
    Trains:
      - Global GradientBoostingRegressor (lap time prediction)
      - Per-driver GBR + IsolationForest (one set per active driver)
      - Global anomaly detection model (condition-normalised IsolationForest)
    """
    results: dict[str, Any] = {
        "global_model": None,
        "driver_models_trained": 0,
        "driver_models_skipped": 0,
        "anomaly_model": None,
        "errors": [],
    }

    # Check if feature dataset exists
    features_path = _ML_DATA_DIR / "processed" / "features.parquet"
    if not features_path.exists():
        features_path = _ML_DATA_DIR / "processed" / "features.csv"
    if not features_path.exists():
        results["errors"].append("Feature dataset not found — ML training skipped")
        logger.warning("ML training: feature dataset not found at %s", _ML_DATA_DIR)
        return results

    # -- Global model --
    try:
        from ml_engine import train_global_model
        meta = train_global_model(str(_ML_DATA_DIR))
        results["global_model"] = {
            "status": "ok",
            "training_samples": meta.get("training_samples"),
            "mae": meta.get("mae"),
        }
        logger.info(
            "Trained global model: %d samples, MAE=%.4f",
            meta.get("training_samples", 0),
            meta.get("mae", float("nan")),
        )
    except Exception as exc:
        results["errors"].append({"model": "global", "error": str(exc)})
        logger.warning("Global model training failed: %s", exc, exc_info=True)

    # -- Per-driver models --
    try:
        drivers = conn.execute(
            "SELECT DISTINCT d.driver_name FROM sessions s "
            "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
            "WHERE d.driver_name IS NOT NULL AND d.driver_name != ''"
        ).fetchall()
        driver_names = [
            (dict(r) if not isinstance(r, dict) else r).get("driver_name")
            for r in drivers
        ]
    except Exception as exc:
        driver_names = []
        results["errors"].append({"model": "drivers_query", "error": str(exc)})

    for driver_name in driver_names:
        if not driver_name:
            continue
        try:
            from ml_engine import train_driver_model
            meta = train_driver_model(driver_name, str(_ML_DATA_DIR))
            results["driver_models_trained"] += 1
            logger.info("Trained driver model for %s", driver_name)
        except Exception as exc:
            err_str = str(exc)
            if "Insufficient" in err_str or "No data" in err_str:
                results["driver_models_skipped"] += 1
                logger.info("Skipped driver model for %s: %s", driver_name, err_str)
            else:
                results["errors"].append(
                    {"model": f"driver:{driver_name}", "error": err_str}
                )
                logger.warning(
                    "Driver model training failed for %s: %s",
                    driver_name, exc, exc_info=True,
                )

    # -- Anomaly detection model --
    try:
        import pandas as pd

        from anomaly_detection import train_anomaly_model

        try:
            import pyarrow.parquet as pq
            feature_df = pq.read_table(
                _ML_DATA_DIR / "processed" / "features.parquet"
            ).to_pandas()
        except (ImportError, FileNotFoundError):
            feature_df = pd.read_csv(
                _ML_DATA_DIR / "processed" / "features.csv"
            )

        model = train_anomaly_model(feature_df)
        results["anomaly_model"] = {
            "status": "ok",
            "condition_keys": list(model.condition_models.keys()),
            "total_samples": model.total_samples,
        }
        logger.info(
            "Trained anomaly model: %d conditions, %d samples",
            len(model.condition_models),
            model.total_samples,
        )
    except Exception as exc:
        results["errors"].append({"model": "anomaly", "error": str(exc)})
        logger.warning("Anomaly model training failed: %s", exc, exc_info=True)

    return results


def _reprocess_sessions(
    sessions: list[dict],
    data_dir: str = "/data/uploads",
    batch_size: int = _REPROCESS_BATCH_SIZE,
    pause_s: int = _REPROCESS_PAUSE_S,
) -> dict:
    """Tier 3: Re-run pipeline on each session with updated models."""
    from pipeline import run_full_analysis
    from tasks.pipeline_tasks import _store_theoretical_data
    from web.db_pg import return_pg_connection

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
                # Reprocessing an already-gamified session must NOT re-award XP
                # (award_session_xp is additive) — that would inflate XP on
                # every biweekly retrain.
                skip_gamification=True,
            )

            if result.get("theoretical_metrics"):
                # _store_theoretical_data INSERTs into theoretical_data (RLS)
                # WITHOUT an explicit workspace_id — it relies on the column's
                # current_setting('app.current_workspace_id') DEFAULT. On the
                # maint role (BYPASSRLS, no GUC) that DEFAULT evaluates to NULL
                # and the INSERT fails the NOT NULL / FK. So resolve THIS
                # session's workspace_id and SET the GUC on the maint conn
                # before the per-session write. If it can't be resolved, log
                # and skip the store (best-effort) — the analysis still ran.
                conn = _get_pg_connection()
                try:
                    ws_row = conn.execute(
                        "SELECT workspace_id FROM sessions "
                        "WHERE session_id = %(sid)s",
                        {"sid": session_id},
                    ).fetchone()
                    ws_id = None
                    if ws_row is not None:
                        wr = dict(ws_row) if not isinstance(ws_row, dict) else ws_row
                        ws_id = wr.get("workspace_id")

                    if ws_id is not None:
                        # Scope the per-session write to its workspace so the
                        # theoretical_data DEFAULT resolves correctly.
                        conn.execute(
                            "SET app.current_workspace_id = %(ws)s",
                            {"ws": str(ws_id)},
                        )
                        _store_theoretical_data(session_id, result, conn=conn)
                    else:
                        logger.warning(
                            "Skipping theoretical_data write for %s: "
                            "could not resolve workspace_id on maint conn",
                            session_id,
                        )
                finally:
                    # Standalone maint connection — close to avoid a leak per
                    # reprocessed session in this recurring beat task.
                    return_pg_connection(conn)

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
        if (i + 1) % batch_size == 0:
            time.sleep(pause_s)

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
    """Bi-weekly training: envelopes, ML models, reprocess all sessions.

    Scheduled via Celery Beat every Sunday at 00:00 UTC.
    Skips execution on odd ISO-weeks when schedule_interval_weeks == 2
    (bi-weekly gate).
    """
    start = time.time()
    config = _load_training_config()

    # -- Bi-weekly gate: skip odd ISO-week numbers ----------------
    interval = config.get("schedule_interval_weeks", _SCHEDULE_INTERVAL_WEEKS)
    if interval > 1:
        iso_week = datetime.now(timezone.utc).isocalendar()[1]
        if iso_week % interval != 0:
            logger.info(
                "Bi-weekly gate: ISO week %d is not divisible by %d — skipping.",
                iso_week, interval,
            )
            return {
                "skipped": True,
                "reason": f"ISO week {iso_week} not divisible by {interval}",
                "iso_week": iso_week,
            }

    audit: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "tiers": {},
    }

    # Standalone maintenance connection (BYPASSRLS) for the cross-tenant
    # training READS in Tiers 1 and 3. Closed in the finally below — it is
    # NOT cached on flask.g, so leaving it open would leak a connection on
    # every (bi-)weekly beat run.
    from web.db_pg import return_pg_connection
    conn = _get_pg_connection()
    groups: list[dict] = []
    try:
        # Tier 1: Track-specific envelopes
        logger.info("=== Tier 1: Training track-specific envelopes ===")
        groups = _gather_training_groups(conn)
        tier1 = _train_track_envelopes(
            groups, min_sessions=config["min_sessions_per_group"],
        )
        audit["tiers"]["envelopes"] = tier1

        # Tier 2: Global kart_envelope model bundle
        logger.info("=== Tier 2: Training global kart_envelope model bundle ===")
        tier2 = _train_global_model()
        audit["tiers"]["global_model"] = tier2

        # Tier 3: ML engine models (global, per-driver, anomaly)
        logger.info("=== Tier 3: Training ML engine models ===")
        tier3 = _train_ml_models(conn)
        audit["tiers"]["ml_models"] = tier3
    finally:
        # Done with the shared cross-tenant read connection. Tier 4 manages
        # its own per-session maint connections internally.
        return_pg_connection(conn)

    # Tier 4: Reprocess all sessions with improved models
    logger.info("=== Tier 4: Reprocessing all sessions ===")
    all_sessions = []
    for group in groups:
        all_sessions.extend(group["sessions"])
    tier4 = _reprocess_sessions(
        all_sessions,
        data_dir=str(_DATA_RAW_DIR),
        batch_size=config["reprocess_batch_size"],
        pause_s=config["reprocess_pause_s"],
    )
    audit["tiers"]["reprocess"] = tier4

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
        "Bi-weekly retrain complete in %.1fs: envelopes=%d, "
        "ml_drivers=%d, reprocessed=%d/%d",
        elapsed,
        tier1["trained"],
        tier3["driver_models_trained"],
        tier4["succeeded"],
        tier4["succeeded"] + tier4["failed"],
    )
    return audit
