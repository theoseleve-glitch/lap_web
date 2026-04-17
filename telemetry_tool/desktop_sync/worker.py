"""SyncWorker — background thread that drains the sync queue.

Picks up ``pending`` entries, POSTs them to the webapp's
``/api/v1/bundles`` endpoint, handles success / duplicate / failure / retry.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from desktop_sync.queue import SyncQueue

logger = logging.getLogger(__name__)

_BOUNDARY = "----LapBundleUpload"
_MAX_BACKOFF_S = 30 * 60   # 30 minutes


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff: 5^attempt, capped at 30 min."""
    return min(_MAX_BACKOFF_S, 5 ** attempt)


def _next_retry_iso(attempt: int) -> str:
    delta = timedelta(seconds=_backoff_seconds(attempt))
    return (datetime.now(timezone.utc) + delta).isoformat()


class SyncWorker:
    """Background daemon that uploads pending bundles.

    Usage::

        worker = SyncWorker(queue=queue, api_url="https://api.lap-coach.racing")
        worker.start()       # spawns thread
        # ... app runs ...
        worker.stop()        # signals thread to exit
    """

    def __init__(
        self,
        *,
        queue: SyncQueue,
        api_url: str,
        auth_token: str | None = None,
        workspace_id: int | None = None,
        poll_interval_s: float = 10.0,
        auto_analyze: bool = False,
    ):
        self._queue = queue
        self._api_url = api_url.rstrip("/")
        self._auth_token = auth_token
        self._workspace_id = workspace_id
        self._poll_interval = poll_interval_s
        self._auto_analyze = auto_analyze
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="sync-worker")
        self._thread.start()
        logger.info("[SYNC] Worker started (poll=%ds)", self._poll_interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("[SYNC] Worker stopped")

    def drain_once(self) -> int:
        """Process all eligible pending entries. Returns count uploaded."""
        entries = self._queue.get_pending()
        uploaded = 0
        for entry in entries:
            if self._stop_event.is_set():
                break
            success = self._upload_one(entry.queue_id, entry.bundle_path, entry.checksum_sha256)
            if success:
                uploaded += 1
        return uploaded

    # ── Internal ────────────────────────────────────────────

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.drain_once()
            except Exception:
                logger.exception("[SYNC] Unexpected error in drain loop")
            self._stop_event.wait(timeout=self._poll_interval)

    def _upload_one(self, queue_id: str, bundle_path: str, checksum: str) -> bool:
        path = Path(bundle_path)
        if not path.is_file():
            self._queue.mark_permanently_failed(queue_id, f"bundle file missing: {bundle_path}")
            logger.warning("[SYNC] Bundle missing on disk: %s", bundle_path)
            return False

        self._queue.mark_uploading(queue_id)
        logger.info("[SYNC] Uploading %s ...", path.name)

        try:
            body, content_type = _build_multipart(path, checksum)
            headers = {"Content-Type": content_type}
            if self._auth_token:
                headers["Authorization"] = f"DeviceToken {self._auth_token}"
            if self._workspace_id is not None:
                headers["X-Workspace-Id"] = str(self._workspace_id)
            headers["X-Bundle-Sha256"] = checksum

            url = f"{self._api_url}/api/v1/bundles"
            req = Request(url, data=body, headers=headers, method="POST")
            resp = urlopen(req, timeout=120)
            resp_body = json.loads(resp.read().decode("utf-8"))

            cloud_id = resp_body.get("data", {}).get("bundle_id", "unknown")
            self._queue.mark_uploaded(queue_id, cloud_id)
            logger.info("[SYNC] Uploaded: %s → bundle_id=%s", path.name, cloud_id)

            # Auto-analyze for World Class users.
            if self._auto_analyze and cloud_id != "unknown":
                self._trigger_analysis(queue_id, cloud_id)

            return True

        except HTTPError as exc:
            resp_text = exc.read().decode("utf-8", errors="replace")
            try:
                err_body = json.loads(resp_text)
                code = err_body.get("error", {}).get("code", "")
                details = err_body.get("error", {}).get("details", [])
            except json.JSONDecodeError:
                code = f"HTTP_{exc.code}"
                details = []

            if code == "BUNDLE_DUPLICATE":
                existing_id = details[0].get("existing_bundle_id", "unknown") if details else "unknown"
                self._queue.mark_uploaded(queue_id, existing_id)
                logger.info("[SYNC] Already uploaded: %s (bundle_id=%s)", path.name, existing_id)
                return True

            error_msg = f"{code}: {err_body.get('error', {}).get('message', resp_text[:200])}"
            entry = self._queue.get(queue_id)
            attempt = (entry.attempt_count if entry else 0) + 1
            self._queue.mark_failed(queue_id, error_msg, next_retry_at=_next_retry_iso(attempt))
            logger.warning("[SYNC] Upload failed (%s): %s (attempt %d)", path.name, error_msg, attempt)
            return False

        except (URLError, OSError, TimeoutError) as exc:
            entry = self._queue.get(queue_id)
            attempt = (entry.attempt_count if entry else 0) + 1
            self._queue.mark_failed(
                queue_id, f"network: {exc}",
                next_retry_at=_next_retry_iso(attempt),
            )
            logger.warning("[SYNC] Network error for %s: %s (retry in %ds)",
                          path.name, exc, _backoff_seconds(attempt))
            return False

    def _trigger_analysis(self, queue_id: str, cloud_bundle_id: str) -> None:
        """POST /bundles/<id>/analyze after successful upload. Non-blocking.

        Updates analysis_status in the queue for UI display.
        """
        try:
            self._queue.update_analysis_status(queue_id, "queued")
            body = json.dumps({}).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self._auth_token:
                headers["Authorization"] = f"DeviceToken {self._auth_token}"
            url = f"{self._api_url}/api/v1/bundles/{cloud_bundle_id}/analyze"
            req = Request(url, data=body, headers=headers, method="POST")
            resp = urlopen(req, timeout=30)
            resp_body = json.loads(resp.read().decode("utf-8"))
            if resp_body.get("ok"):
                self._queue.update_analysis_status(queue_id, "running")
                logger.info("[SYNC] Analysis triggered for %s", cloud_bundle_id)
            else:
                self._queue.update_analysis_status(queue_id, "analysis_failed")
                logger.warning("[SYNC] Analysis trigger rejected for %s", cloud_bundle_id)
        except HTTPError as exc:
            code = ""
            try:
                err = json.loads(exc.read().decode("utf-8", errors="replace"))
                code = err.get("error", {}).get("code", "")
            except Exception:
                pass
            if code == "CONFLICT":
                # Already analyzing — fine.
                self._queue.update_analysis_status(queue_id, "running")
                logger.info("[SYNC] Analysis already in progress for %s", cloud_bundle_id)
            elif code == "READINESS_NOT_MET":
                self._queue.update_analysis_status(queue_id, "analysis_failed")
                logger.warning("[SYNC] Analysis readiness not met for %s", cloud_bundle_id)
            else:
                self._queue.update_analysis_status(queue_id, "analysis_failed")
                logger.warning("[SYNC] Analysis trigger HTTP %d for %s", exc.code, cloud_bundle_id)
        except (URLError, OSError) as exc:
            # Network error during analysis trigger — not fatal; upload succeeded.
            logger.warning("[SYNC] Analysis trigger network error: %s", exc)


def _build_multipart(bundle_path: Path, checksum: str) -> tuple[bytes, str]:
    """Build a multipart/form-data body with one file part."""
    boundary = _BOUNDARY
    filename = bundle_path.name
    file_data = bundle_path.read_bytes()

    parts = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="bundle"; filename="{filename}"\r\n'
        f"Content-Type: application/zip\r\n\r\n".encode()
    )
    parts.append(file_data)
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    body = b"".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type
