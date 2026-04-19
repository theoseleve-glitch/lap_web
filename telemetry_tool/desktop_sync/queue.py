"""SyncQueue — local SQLite queue for pending cloud uploads.

One row per session bundle. Statuses: pending → uploading → uploaded | failed.
Racer tier inserts as "skipped" (waits for manual trigger).
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sync_queue (
    queue_id         TEXT PRIMARY KEY,
    bundle_path      TEXT NOT NULL,
    checksum_sha256  TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    attempt_count    INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 5,
    last_attempt_at  TEXT,
    next_retry_at    TEXT,
    error_message    TEXT,
    cloud_bundle_id  TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    uploaded_at      TEXT,
    analysis_status  TEXT,
    analysis_tier    TEXT,
    track_name       TEXT,
    vehicle_name     TEXT
);
"""

# Columns added in Beta — safe ALTER TABLE for existing DBs.
_BETA_COLUMNS = [
    ("analysis_status", "TEXT"),
    ("analysis_tier", "TEXT"),
    ("track_name", "TEXT"),
    ("vehicle_name", "TEXT"),
]


@dataclass
class SyncQueueEntry:
    queue_id: str
    bundle_path: str
    checksum_sha256: str
    status: str
    attempt_count: int
    max_attempts: int
    last_attempt_at: str | None
    next_retry_at: str | None
    error_message: str | None
    cloud_bundle_id: str | None
    created_at: str
    uploaded_at: str | None
    analysis_status: str | None = None     # queued | running | succeeded | failed | None
    analysis_tier: str | None = None       # A | B | C | D | None
    track_name: str | None = None
    vehicle_name: str | None = None


class SyncQueue:
    """CRUD for the sync_queue table in the local SQLite DB."""

    def __init__(self, db_path: Path | str | None = None, conn: sqlite3.Connection | None = None):
        if conn is not None:
            self._conn = conn
            self._owns_conn = False
        else:
            db = str(db_path) if db_path else ":memory:"
            self._conn = sqlite3.connect(db, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._owns_conn = True
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.execute(_CREATE_TABLE)
        # Add Beta columns to pre-existing tables (idempotent).
        for col, col_type in _BETA_COLUMNS:
            try:
                self._conn.execute(f"ALTER TABLE sync_queue ADD COLUMN {col} {col_type}")
            except Exception:
                pass   # column already exists
        self._conn.commit()

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()

    # ── Writes ──────────────────────────────────────────────

    def enqueue(
        self, *, bundle_path: str, checksum: str,
        auto_upload: bool = True, max_attempts: int = 5,
    ) -> str:
        """Insert a new queue entry. Returns the queue_id."""
        queue_id = uuid.uuid4().hex
        status = "pending" if auto_upload else "skipped"
        self._conn.execute(
            """
            INSERT INTO sync_queue
                (queue_id, bundle_path, checksum_sha256, status, max_attempts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (queue_id, bundle_path, checksum, status, max_attempts),
        )
        self._conn.commit()
        logger.info("[SYNC] Queued %s (status=%s)", Path(bundle_path).name, status)
        return queue_id

    def mark_uploading(self, queue_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE sync_queue SET status='uploading', last_attempt_at=? WHERE queue_id=?",
            (now, queue_id),
        )
        self._conn.commit()

    def mark_uploaded(self, queue_id: str, cloud_bundle_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            UPDATE sync_queue
            SET status='uploaded', cloud_bundle_id=?, uploaded_at=?, error_message=NULL
            WHERE queue_id=?
            """,
            (cloud_bundle_id, now, queue_id),
        )
        self._conn.commit()

    def mark_failed(self, queue_id: str, error: str, next_retry_at: str | None = None) -> None:
        self._conn.execute(
            """
            UPDATE sync_queue
            SET status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'failed' ELSE 'pending' END,
                attempt_count = attempt_count + 1,
                error_message = ?,
                next_retry_at = ?
            WHERE queue_id = ?
            """,
            (error, next_retry_at, queue_id),
        )
        self._conn.commit()

    def mark_permanently_failed(self, queue_id: str, error: str) -> None:
        """Mark as failed with no retry (non-transient error like file missing)."""
        self._conn.execute(
            "UPDATE sync_queue SET status='failed', attempt_count=max_attempts, "
            "error_message=? WHERE queue_id=?",
            (error, queue_id),
        )
        self._conn.commit()

    def promote_skipped(self, queue_id: str) -> None:
        """Move a 'skipped' entry to 'pending' (manual upload trigger)."""
        self._conn.execute(
            "UPDATE sync_queue SET status='pending' WHERE queue_id=? AND status='skipped'",
            (queue_id,),
        )
        self._conn.commit()

    def promote_all_skipped(self) -> int:
        """Move all 'skipped' entries to 'pending'. Returns count."""
        cur = self._conn.execute(
            "UPDATE sync_queue SET status='pending' WHERE status='skipped'"
        )
        self._conn.commit()
        return cur.rowcount

    def update_analysis_status(
        self, queue_id: str, analysis_status: str, analysis_tier: str | None = None,
    ) -> None:
        """Update the analysis tracking columns after triggering or polling analysis."""
        self._conn.execute(
            "UPDATE sync_queue SET analysis_status=?, analysis_tier=? WHERE queue_id=?",
            (analysis_status, analysis_tier, queue_id),
        )
        self._conn.commit()

    def update_session_metadata(
        self, queue_id: str, track_name: str | None, vehicle_name: str | None,
    ) -> None:
        self._conn.execute(
            "UPDATE sync_queue SET track_name=?, vehicle_name=? WHERE queue_id=?",
            (track_name, vehicle_name, queue_id),
        )
        self._conn.commit()

    def retry_failed(self) -> int:
        """Reset all 'failed' entries to 'pending' with attempt_count reset."""
        cur = self._conn.execute(
            "UPDATE sync_queue SET status='pending', attempt_count=0, error_message=NULL "
            "WHERE status='failed'"
        )
        self._conn.commit()
        return cur.rowcount

    # ── Reads ───────────────────────────────────────────────

    def get_pending(self) -> list[SyncQueueEntry]:
        """Return entries eligible for upload (status=pending, retry time elapsed)."""
        now = datetime.now(timezone.utc).isoformat()
        rows = self._conn.execute(
            """
            SELECT * FROM sync_queue
            WHERE status = 'pending'
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY created_at ASC
            """,
            (now,),
        ).fetchall()
        return [self._to_entry(r) for r in rows]

    def get(self, queue_id: str) -> SyncQueueEntry | None:
        row = self._conn.execute(
            "SELECT * FROM sync_queue WHERE queue_id=?", (queue_id,),
        ).fetchone()
        return self._to_entry(row) if row else None

    def list_all(self) -> list[SyncQueueEntry]:
        rows = self._conn.execute(
            "SELECT * FROM sync_queue ORDER BY created_at DESC"
        ).fetchall()
        return [self._to_entry(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) c FROM sync_queue GROUP BY status"
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}

    @staticmethod
    def _to_entry(row) -> SyncQueueEntry:
        def _g(key, default=None):
            try:
                return row[key]
            except (KeyError, IndexError):
                return default
        return SyncQueueEntry(
            queue_id=row["queue_id"],
            bundle_path=row["bundle_path"],
            checksum_sha256=row["checksum_sha256"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            last_attempt_at=row["last_attempt_at"],
            next_retry_at=row["next_retry_at"],
            error_message=row["error_message"],
            cloud_bundle_id=row["cloud_bundle_id"],
            created_at=row["created_at"],
            uploaded_at=row["uploaded_at"],
            analysis_status=_g("analysis_status"),
            analysis_tier=_g("analysis_tier"),
            track_name=_g("track_name"),
            vehicle_name=_g("vehicle_name"),
        )
