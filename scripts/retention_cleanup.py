"""Demo tier retention cleanup.

Deletes raw upload files for demo-tier users' sessions older than 30 days.
Keeps DB rows (including scores, lap data, reports) so users can still
browse their analysis history — only the raw CSV is removed.

Run via cron daily: 0 3 * * * /opt/lap-api/scripts/retention_cleanup.sh
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("retention")

DEMO_RETENTION_DAYS = 30
UPLOAD_ROOT = Path("/data/uploads")


def main() -> int:
    conn = psycopg2.connect(os.environ["TELEMETRY_PG_URL"])
    cur = conn.cursor()

    cutoff = datetime.now(timezone.utc) - timedelta(days=DEMO_RETENTION_DAYS)

    # Find demo-tier sessions older than cutoff with raw files still present
    cur.execute(
        """
        SELECT s.session_id, s.workspace_id, s.source_path, s.created_at, u.email
        FROM sessions s
        JOIN workspaces w ON w.id = s.workspace_id
        LEFT JOIN users u ON u.id = w.owner_user_id
        WHERE s.created_at < %s
          AND s.deleted_at IS NULL
          AND (s.retention_expired IS NULL OR s.retention_expired = false)
          AND (u.plan_tier IS NULL OR u.plan_tier IN ('demo', 'free'))
          AND s.source_path IS NOT NULL
        """,
        (cutoff,),
    )
    rows = cur.fetchall()

    if not rows:
        logger.info("No demo sessions older than %d days to clean", DEMO_RETENTION_DAYS)
        conn.close()
        return 0

    logger.info("Found %d demo sessions eligible for cleanup", len(rows))

    total_freed = 0
    cleaned_ids: list[int] = []

    for session_id, workspace_id, source_path, created_at, email in rows:
        try:
            # Resolve the job directory from source_path
            # source_path looks like /data/uploads/job_xxx/file.csv
            path = Path(source_path)
            if not path.is_absolute():
                path = UPLOAD_ROOT / path

            # Compute directory size before deletion
            size_before = 0
            if path.exists():
                if path.is_file():
                    size_before = path.stat().st_size
                    path.unlink()
                    logger.info("Deleted file: %s (%d bytes)", path, size_before)
                elif path.is_dir():
                    for f in path.rglob("*"):
                        if f.is_file():
                            size_before += f.stat().st_size
                    shutil.rmtree(path)
                    logger.info("Deleted dir: %s (%d bytes)", path, size_before)

                # Also check and clean the parent job_xxx directory if empty
                parent = path.parent
                if parent != UPLOAD_ROOT and parent.exists() and parent.is_dir():
                    try:
                        if not any(parent.iterdir()):
                            parent.rmdir()
                    except OSError:
                        pass

            total_freed += size_before
            cleaned_ids.append(session_id)

        except Exception as e:
            logger.warning("Failed to clean session %s: %s", session_id, e)

    # Mark sessions as retention_expired in bulk
    if cleaned_ids:
        cur.execute(
            "UPDATE sessions SET retention_expired = true "
            "WHERE session_id = ANY(%s)",
            (cleaned_ids,),
        )
        conn.commit()

    logger.info(
        "Retention cleanup complete: %d sessions, %.1f MB freed",
        len(cleaned_ids),
        total_freed / 1e6,
    )
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
