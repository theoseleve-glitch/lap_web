#!/usr/bin/env python3
"""Re-detect track assignments for all sessions using updated thresholds.

Idempotent — safe to run multiple times. Reads GPS data from each session's
raw CSV, recomputes fingerprints, and updates sessions.track_id where the
new match differs from the current assignment.

Usage:
    python scripts/redetect_tracks.py [--dry-run] [-v]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "telemetry_tool"))

logger = logging.getLogger(__name__)


def redetect_all(dry_run: bool = False) -> dict:
    """Re-run track detection for all sessions. Returns summary dict."""
    from db.schema import ensure_schema
    from web.db import get_db_connection
    from track_detection import register_or_match_track

    conn = get_db_connection()
    ensure_schema(conn)

    sessions = conn.execute(
        "SELECT s.session_id, s.track_id, s.raw_csv_path, t.track_name "
        "FROM sessions s "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.deleted_at IS NULL "
        "ORDER BY s.session_date"
    ).fetchall()
    sessions = [dict(r) for r in sessions]

    stats = {"total": len(sessions), "reassigned": 0, "failed": 0,
             "unchanged": 0, "new_tracks": 0}
    changes = []

    for sess in sessions:
        sid = sess["session_id"]
        old_track_id = sess["track_id"]
        csv_path = sess.get("raw_csv_path")

        if not csv_path or not Path(csv_path).exists():
            logger.debug("Session %s: no CSV at %s, skipping", sid, csv_path)
            stats["failed"] += 1
            continue

        try:
            from io_racechrono import read_racechrono_csv

            df = read_racechrono_csv(csv_path)
            if df is None or df.empty:
                stats["failed"] += 1
                continue

            result, _ = register_or_match_track(
                df, track_name=sess.get("track_name") or "Unknown Track"
            )

            if result.track_id != old_track_id:
                changes.append({
                    "session_id": sid,
                    "old_track_id": old_track_id,
                    "old_track_name": sess.get("track_name", "?"),
                    "new_track_id": result.track_id,
                    "new_track_name": result.track_name,
                    "confidence": result.confidence,
                })
                if not dry_run:
                    conn.execute(
                        "UPDATE sessions SET track_id = ? WHERE session_id = ?",
                        (result.track_id, sid),
                    )
                stats["reassigned"] += 1
                if result.is_new:
                    stats["new_tracks"] += 1
            else:
                stats["unchanged"] += 1

        except Exception as exc:
            logger.warning("Session %s: re-detection failed: %s", sid, exc)
            stats["failed"] += 1

    if not dry_run:
        conn.commit()

    return {"stats": stats, "changes": changes}


def main():
    parser = argparse.ArgumentParser(
        description="Re-detect track assignments for all sessions"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show changes without applying")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    result = redetect_all(dry_run=args.dry_run)
    stats = result["stats"]
    changes = result["changes"]

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{mode}Re-detection complete:")
    print(f"  Total sessions:  {stats['total']}")
    print(f"  Reassigned:      {stats['reassigned']}")
    print(f"  New tracks:      {stats['new_tracks']}")
    print(f"  Unchanged:       {stats['unchanged']}")
    print(f"  Failed/skipped:  {stats['failed']}")

    if changes:
        print("\nChanges:")
        for c in changes:
            print(
                f"  {c['session_id']}: "
                f"{c['old_track_name']} -> {c['new_track_name']} "
                f"(conf={c['confidence']:.2f})"
            )


if __name__ == "__main__":
    main()
