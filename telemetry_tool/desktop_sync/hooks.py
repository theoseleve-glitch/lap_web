"""Post-finalize hooks for desktop session sync.

These functions are called from ``main.py`` and ``batch_replay_capture.py``
after a session/capture finishes. They are designed to NEVER raise — all
errors are logged and swallowed so the host process remains stable.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Module-level singleton — the worker thread is shared across calls within
# the same process lifetime.
_WORKER = None
_QUEUE = None
_ENTITLEMENTS = None


def _get_queue():
    """Lazily create the SyncQueue (auto-creates SQLite table)."""
    global _QUEUE
    if _QUEUE is None:
        from desktop_sync.queue import SyncQueue
        db_path = _resolve_db_path()
        _QUEUE = SyncQueue(db_path=db_path)
    return _QUEUE


def _get_config():
    from desktop_sync.config import UserConfig
    return UserConfig()


def _get_sync_policy():
    """Fetch server-trusted sync policy (cached, offline-safe)."""
    global _ENTITLEMENTS
    if _ENTITLEMENTS is None:
        from desktop_sync.entitlements import CachedEntitlements
        _ENTITLEMENTS = CachedEntitlements()
    return _ENTITLEMENTS.get_policy()


def _resolve_db_path() -> Path:
    """Find the local telemetry DB. Reuse the same file as the main app."""
    try:
        from path_manager import get_base_dir
        return get_base_dir() / "telemetry.db"
    except ImportError:
        return Path(os.environ.get("TELEMETRY_DB_PATH", "telemetry.db"))


def _ensure_worker():
    """Start the background upload worker if not already running."""
    global _WORKER
    if _WORKER is not None:
        return
    config = _get_config()
    api_url = config.cloud_api_url
    if not api_url:
        logger.debug("[SYNC] No cloud_api_url configured — worker not started")
        return
    from desktop_sync.auth import DeviceAuth
    from desktop_sync.worker import SyncWorker
    auth = DeviceAuth(config)
    policy = _get_sync_policy()
    _WORKER = SyncWorker(
        queue=_get_queue(),
        api_url=api_url,
        auth_token=auth.device_token,
        auto_analyze=policy.auto_analyze,
    )
    _WORKER.start()


def on_session_finalized(
    results: list[dict[str, Any]],
    csv_path: Path,
    session_info: dict[str, Any],
) -> None:
    """Post-finalize hook for ``main.py``.

    Called after ``run()`` returns. Builds a bundle from the first successful
    result and enqueues it. Starts the worker thread if auto_upload is on.

    NEVER raises. All errors are logged.
    """
    try:
        _on_session_finalized_inner(results, csv_path, session_info)
    except Exception as exc:
        logger.warning("[SYNC] Post-finalize hook failed (non-fatal): %s", exc)
        print(f"  [SYNC] Sync skipped: {exc}")


def _on_session_finalized_inner(
    results: list[dict[str, Any]],
    csv_path: Path,
    session_info: dict[str, Any],
) -> None:
    # Only sync sessions that completed at least partially.
    successful = [r for r in results if not r.get("steps_failed")]
    if not successful and results:
        # Fall back to first result even if it had warnings — still worth syncing.
        successful = results[:1]
    if not successful:
        logger.info("[SYNC] No results to sync")
        return

    result = successful[0]

    # Check for IBT source — only IBT sessions are bundle-compatible.
    source_path = csv_path
    if not source_path.suffix.lower() == ".ibt":
        # CSV sessions stay on the legacy sessions_v2 path — no bundle.
        logger.debug("[SYNC] Source is %s (not IBT) — skipping bundle creation",
                    source_path.suffix)
        return

    track_name = (
        result.get("track_id")
        or session_info.get("track_name")
        or csv_path.stem
    )
    car_name = (
        session_info.get("car_name")
        or session_info.get("vehicle_name")
        or "unknown"
    )

    from desktop_sync.bundle_builder import build_session_bundle, compute_bundle_checksum

    output_dir = Path(result.get("output_dir", csv_path.parent))
    bundle_path = build_session_bundle(
        ibt_path=source_path,
        track_name=str(track_name),
        car_name=str(car_name),
        output_dir=output_dir,
        session_type=session_info.get("session_type", "practice"),
    )

    checksum = compute_bundle_checksum(bundle_path)
    config = _get_config()
    policy = _get_sync_policy()
    queue = _get_queue()

    if not policy.can_upload:
        print(f"  [SYNC] Bundle built: {bundle_path.name}")
        print(f"  [SYNC] Cloud upload requires a Racer or World Class plan.")
        return

    queue_id = queue.enqueue(
        bundle_path=str(bundle_path),
        checksum=checksum,
        auto_upload=policy.auto_upload,
        max_attempts=config.max_upload_attempts,
    )

    if policy.auto_upload:
        print(f"  [SYNC] Bundle built: {bundle_path.name}")
        print(f"  [SYNC] Queued for auto-upload (id: {queue_id[:8]})")
        _ensure_worker()
    else:
        print(f"  [SYNC] Bundle built: {bundle_path.name}")
        print(f"  [SYNC] Use 'python -m desktop_sync upload' to sync to cloud.")


def on_ibt_captured(
    ibt_path: Path,
    capture_meta: dict[str, Any],
    output_dir: Path,
) -> None:
    """Post-capture hook for ``batch_replay_capture.py``.

    Called after IBT copy + capture_meta.json write. Builds a bundle and
    enqueues it.

    NEVER raises. All errors are logged.
    """
    try:
        _on_ibt_captured_inner(ibt_path, capture_meta, output_dir)
    except Exception as exc:
        logger.warning("[SYNC] Post-capture hook failed (non-fatal): %s", exc)
        print(f"  [SYNC] Sync skipped: {exc}")


def _on_ibt_captured_inner(
    ibt_path: Path,
    capture_meta: dict[str, Any],
    output_dir: Path,
) -> None:
    track_name = capture_meta.get("track_name", "unknown")
    car_name = capture_meta.get("car_name", "unknown")

    from desktop_sync.bundle_builder import build_session_bundle, compute_bundle_checksum

    bundle_path = build_session_bundle(
        ibt_path=ibt_path,
        track_name=str(track_name),
        car_name=str(car_name),
        output_dir=output_dir,
        capture_meta=capture_meta,
    )

    checksum = compute_bundle_checksum(bundle_path)
    config = _get_config()
    policy = _get_sync_policy()
    queue = _get_queue()

    if not policy.can_upload:
        print(f"  [SYNC] Bundle saved locally: {bundle_path.name}")
        print(f"  [SYNC] Cloud upload requires a Racer or World Class plan.")
        return

    queue.enqueue(
        bundle_path=str(bundle_path),
        checksum=checksum,
        auto_upload=policy.auto_upload,
        max_attempts=config.max_upload_attempts,
    )

    if policy.auto_upload:
        print(f"  [SYNC] Bundle queued for upload: {bundle_path.name}")
        _ensure_worker()
    else:
        print(f"  [SYNC] Bundle saved locally: {bundle_path.name}")


def shutdown_worker(timeout: float = 3.0) -> None:
    """Gracefully stop the worker thread (called at process exit)."""
    global _WORKER
    if _WORKER is not None:
        _WORKER.stop(timeout=timeout)
        _WORKER = None
