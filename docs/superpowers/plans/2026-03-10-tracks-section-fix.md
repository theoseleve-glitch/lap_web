# Tracks Section Fix — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix track detection misassignment, complete the tracks REST API, add workspace/RLS isolation, fix frontend delete behavior, and build the track evolution dashboard.

**Architecture:** Bottom-up incremental fix. Fix detection thresholds first (backend), then extend existing `api_v1_entities.py` endpoints, add RLS migration, fix frontend, and build evolution page. Each layer is independently testable.

**Tech Stack:** Python/Flask (backend), Alembic (migrations), Next.js/React/TypeScript/TanStack Query (frontend), SQLite + PostgreSQL (dual DB support)

---

## Chunk 1: Track Detection Fix

### Task 1: Tighten Track Detection Thresholds

**Files:**
- Modify: `telemetry_tool/track_detection.py:80-81` (default constants)
- Modify: `telemetry_tool/track_detection.py:483` (sf_saturation)

- [ ] **Step 1: Update default threshold constants**

In `telemetry_tool/track_detection.py`, change lines 80-81:

```python
# Before:
_DEFAULT_LAP_TOL:  Final[float] = 0.06   # +/-6 % lap-length tolerance
_DEFAULT_MIN_IOU:  Final[float] = 0.50   # minimum bounding-box IoU

# After:
_DEFAULT_LAP_TOL:  Final[float] = 0.06   # +/-6 % lap-length tolerance (unchanged — already reasonable)
_DEFAULT_MIN_IOU:  Final[float] = 0.75   # minimum bounding-box IoU (tightened from 0.50 for kart circuits)
```

- [ ] **Step 2: Reduce start/finish saturation distance**

In `telemetry_tool/track_detection.py`, change line 483:

```python
# Before:
sf_sim = max(0.0, 1.0 - sf_dist / 500.0)  # 500 m saturation

# After:
sf_sim = max(0.0, 1.0 - sf_dist / 200.0)  # 200 m saturation (tightened for kart circuits)
```

- [ ] **Step 3: Run existing track detection tests**

Run: `cd telemetry_tool && python track_detection.py`
Expected: All 14 tests pass (tests use explicit tolerance params so defaults don't affect them)

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/track_detection.py
git commit -m "fix: tighten track detection thresholds (IoU 0.50→0.75, S/F 500m→200m)"
```

### Task 2: Add Metadata-First Track Name Matching

**Files:**
- Modify: `telemetry_tool/track_detection.py:575-634` (register_or_match_track function)

- [ ] **Step 1: Add fuzzy name matching before geometric matching**

In `telemetry_tool/track_detection.py`, modify `register_or_match_track()` to check track names first. Insert after `database = load_track_database(db_path)` (line 605) and before `result = match_track(...)` (line 607):

```python
    # -- Metadata-first: prefer name match over pure geometry ----------
    if track_name and track_name != "Unknown Track":
        name_lower = track_name.strip().lower()
        for entry in database:
            stored_name = (entry.get("track_name") or "").strip().lower()
            if not stored_name or stored_name == "unknown track":
                continue
            # Exact match
            if stored_name == name_lower:
                stored_fp = TrackFingerprint.from_dict(entry["fingerprint"])
                iou = fingerprint.bbox.iou(stored_fp.bbox)
                logger.info(
                    "Track name exact match: %r -> %r (id=%s, iou=%.4f)",
                    track_name, entry["track_name"], entry["track_id"], iou,
                )
                return MatchResult(
                    matched=True,
                    track_id=entry["track_id"],
                    track_name=entry["track_name"],
                    is_new=False,
                    lap_length_m=stored_fp.lap_length_m,
                    iou=round(iou, 4),
                    length_ratio=0.0,
                    confidence=1.0,
                ), database
```

- [ ] **Step 2: Run existing tests**

Run: `cd telemetry_tool && python track_detection.py`
Expected: All 14 tests pass (no existing tests pass track_name)

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/track_detection.py
git commit -m "feat: add metadata-first track name matching before geometric matching"
```

### Task 3: Re-Detection Migration Script

**Files:**
- Create: `scripts/redetect_tracks.py`

- [ ] **Step 1: Write the re-detection script**

```python
#!/usr/bin/env python3
"""Re-detect track assignments for all sessions using updated thresholds.

Idempotent — safe to run multiple times. Reads GPS data from each session's
raw DataFrame (stored via the pipeline), recomputes fingerprints, and updates
sessions.track_id where the new match differs from the current assignment.

Usage:
    python scripts/redetect_tracks.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telemetry_tool"))

from db.schema import ensure_schema
from web.db import get_db_connection
from track_detection import (
    compute_track_fingerprint,
    load_track_database,
    register_or_match_track,
    save_track_database,
)

logger = logging.getLogger(__name__)


def redetect_all(dry_run: bool = False) -> dict:
    """Re-run track detection for all sessions.

    Returns summary dict with counts.
    """
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

    stats = {"total": len(sessions), "reassigned": 0, "failed": 0, "unchanged": 0, "new_tracks": 0}
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
            import pandas as pd
            from io_racechrono import read_racechrono_csv
            df = read_racechrono_csv(csv_path)
            if df is None or df.empty:
                stats["failed"] += 1
                continue

            result, _ = register_or_match_track(df, track_name=sess.get("track_name") or "Unknown Track")

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
    parser = argparse.ArgumentParser(description="Re-detect track assignments for all sessions")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
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
        print(f"\nChanges:")
        for c in changes:
            print(f"  {c['session_id']}: {c['old_track_name']} -> {c['new_track_name']} (conf={c['confidence']:.2f})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test with --dry-run**

Run: `python scripts/redetect_tracks.py --dry-run -v`
Expected: Lists sessions and shows what would change without modifying DB

- [ ] **Step 3: Commit**

```bash
git add scripts/redetect_tracks.py
git commit -m "feat: add re-detection migration script for track assignments"
```

---

## Chunk 2: Backend API Fixes

### Task 4: Fix DELETE to Cascade

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_entities.py:226-245`

- [ ] **Step 1: Write failing test**

Create test in `telemetry_tool/tests/test_tracks_api.py`:

```python
"""Tests for tracks API endpoints in api_v1_entities.py."""
import json
import pytest
from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def seeded_track(client):
    """Seed a track + session via direct DB insert."""
    from web.db import get_db_connection
    from db.schema import ensure_schema
    conn = get_db_connection()
    ensure_schema(conn)
    conn.execute(
        "INSERT OR IGNORE INTO tracks (track_id, track_name, lap_length_m) VALUES (?, ?, ?)",
        ("test-track-1", "Test Circuit", 1200.0),
    )
    conn.execute(
        "INSERT OR IGNORE INTO drivers (driver_id, driver_name) VALUES (?, ?)",
        (1, "Test Driver"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO sessions (session_id, track_id, driver_id, session_date) VALUES (?, ?, ?, ?)",
        ("sess-1", "test-track-1", 1, "2026-01-01"),
    )
    conn.commit()
    return "test-track-1"


def test_delete_track_cascades(client, seeded_track):
    """DELETE /api/v1/tracks/:id should cascade-delete sessions."""
    resp = client.delete(f"/api/v1/tracks/{seeded_track}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ok"] is True
    assert data["data"]["deleted"] is True


def test_delete_track_not_found(client):
    resp = client.delete("/api/v1/tracks/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_tracks_api.py::test_delete_track_cascades -v`
Expected: FAIL — returns 409 instead of 200

- [ ] **Step 3: Replace block-delete with cascade-delete**

In `telemetry_tool/web/routes/api_v1_entities.py`, replace the `delete_track` function (lines 226-245):

```python
@bp.route("/tracks/<track_id>", methods=["DELETE"])
def delete_track(track_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM tracks WHERE track_id = ?", (track_id,)
    ).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    from web.repos.track_repo import delete_track_cascade
    counts = delete_track_cascade(conn, track_id)
    conn.commit()
    return api_response({"deleted": True, "sessions_removed": counts.get("sessions", 0)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_tracks_api.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_entities.py telemetry_tool/tests/test_tracks_api.py
git commit -m "fix: track DELETE cascades instead of blocking on linked sessions"
```

### Task 5: Add Missing API Endpoints (sessions list, evolution, sectors, records)

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_entities.py` (add endpoints after existing tracks section)

- [ ] **Step 1: Add tracks/:id/sessions endpoint**

Add after the `delete_track` function in `api_v1_entities.py`:

```python
@bp.route("/tracks/<track_id>/sessions", methods=["GET"])
def list_track_sessions(track_id):
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score, "
        "s.n_laps, s.track_state, d.driver_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.track_id = ? AND s.deleted_at IS NULL "
        "ORDER BY s.session_date DESC",
        (track_id,),
    ).fetchall()
    return api_response([dict(r) for r in rows])
```

- [ ] **Step 2: Add tracks/:id/evolution endpoint**

```python
@bp.route("/tracks/<track_id>/evolution", methods=["GET"])
def track_evolution(track_id):
    """Aggregate evolution data: lap trends, sector breakdown, conditions, corner metrics."""
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)

    # Lap time trend: best lap per session, ordered by date
    sessions = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, s.total_score, "
        "s.n_laps, s.track_state, d.driver_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.track_id = ? AND s.deleted_at IS NULL AND s.best_lap_time_s IS NOT NULL "
        "ORDER BY s.session_date ASC",
        (track_id,),
    ).fetchall()
    lap_trend = [dict(r) for r in sessions]

    # Sector breakdown: sector times per session (if available)
    sector_data = []
    for sess in lap_trend:
        sid = sess["session_id"]
        sectors = conn.execute(
            "SELECT sector_index, MIN(sector_time_s) AS best_sector_time_s "
            "FROM sector_times WHERE session_id = ? "
            "GROUP BY sector_index ORDER BY sector_index",
            (sid,),
        ).fetchall()
        if sectors:
            sector_data.append({
                "session_id": sid,
                "session_date": sess["session_date"],
                "sectors": [dict(s) for s in sectors],
            })

    # Corner metrics aggregated: avg time loss per corner across all sessions
    corner_metrics = conn.execute(
        "SELECT cm.corner_index, AVG(cm.time_loss_s) AS avg_time_loss_s, "
        "AVG(cm.min_speed_mps) AS avg_min_speed_mps, COUNT(*) AS sample_count "
        "FROM corner_metrics cm "
        "JOIN sessions s ON cm.session_id = s.session_id "
        "WHERE s.track_id = ? AND s.deleted_at IS NULL "
        "GROUP BY cm.corner_index "
        "ORDER BY AVG(cm.time_loss_s) DESC",
        (track_id,),
    ).fetchall()

    return api_response({
        "lap_trend": lap_trend,
        "sector_breakdown": sector_data,
        "corner_metrics": [dict(r) for r in corner_metrics],
    })
```

- [ ] **Step 3: Add sectors CRUD endpoints**

```python
@bp.route("/tracks/<track_id>/sectors", methods=["GET"])
def list_track_sectors(track_id):
    conn = _get_conn()
    from web.repos.track_repo import get_track_sectors
    sectors = get_track_sectors(conn, track_id)
    return api_response(sectors)


@bp.route("/tracks/<track_id>/sectors", methods=["POST"])
def add_track_sector(track_id):
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    body = request.get_json(silent=True) or {}
    lat = body.get("lat") or body.get("latitude")
    lon = body.get("lon") or body.get("longitude")
    if lat is None or lon is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "lat and lon are required", status=400)
    from web.repos.track_repo import upsert_track_sector
    sector_id = upsert_track_sector(conn, track_id, float(lat), float(lon), body.get("distance_m"))
    conn.commit()
    return api_response({"sector_id": sector_id}, status=201)


@bp.route("/tracks/<track_id>/sectors/<int:sector_id>", methods=["DELETE"])
def remove_track_sector(track_id, sector_id):
    conn = _get_conn()
    from web.repos.track_repo import delete_track_sector
    delete_track_sector(conn, track_id, sector_id)
    conn.commit()
    return api_response({"deleted": True})
```

- [ ] **Step 4: Add records CRUD endpoints**

```python
@bp.route("/tracks/<track_id>/records", methods=["GET"])
def list_track_records(track_id):
    conn = _get_conn()
    from web.repos.track_repo import get_track_records
    records = get_track_records(conn, track_id)
    return api_response(records)


@bp.route("/tracks/<track_id>/records", methods=["POST"])
def add_track_record(track_id):
    conn = _get_conn()
    row = conn.execute("SELECT track_id FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Track not found", status=404)
    body = request.get_json(silent=True) or {}
    record_time = body.get("record_time_s")
    if record_time is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "record_time_s is required", status=400)
    from web.repos.track_repo import upsert_track_record
    upsert_track_record(
        conn, track_id,
        record_time_s=float(record_time),
        record_holder=body.get("record_holder"),
        record_date=body.get("record_date"),
        vehicle_class=body.get("vehicle_class"),
        source=body.get("source"),
    )
    conn.commit()
    return api_response({"saved": True}, status=201)


@bp.route("/tracks/<track_id>/records/<int:record_id>", methods=["DELETE"])
def remove_track_record(track_id, record_id):
    conn = _get_conn()
    from web.repos.track_repo import delete_track_record
    delete_track_record(conn, record_id)
    conn.commit()
    return api_response({"deleted": True})
```

- [ ] **Step 5: Run all tests**

Run: `pytest telemetry_tool/tests/test_tracks_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_entities.py telemetry_tool/tests/test_tracks_api.py
git commit -m "feat: add tracks sessions/evolution/sectors/records API endpoints"
```

### Task 6: Delete Legacy tracks.py Routes

**Files:**
- Delete: `telemetry_tool/web/routes/tracks.py`
- Modify: `telemetry_tool/web/app.py` (remove tracks blueprint registration)

- [ ] **Step 1: Find and remove tracks blueprint registration in app.py**

Search `app.py` for the tracks blueprint import/registration and remove it.

- [ ] **Step 2: Delete the legacy routes file**

```bash
git rm telemetry_tool/web/routes/tracks.py
```

- [ ] **Step 3: Run all tests to verify nothing breaks**

Run: `pytest telemetry_tool/tests/ -v --tb=short`
Expected: All tests pass (no existing tests depend on legacy HTML tracks routes)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove legacy HTML tracks routes (replaced by api_v1_entities)"
```

---

## Chunk 3: Workspace/RLS Migration

### Task 7: Alembic Migration 017 — Tracks RLS

**Files:**
- Create: `alembic/versions/017_tracks_workspace_rls.py`

- [ ] **Step 1: Write the migration**

```python
"""017: Add workspace_id + RLS to tracks, track_records, track_sectors.

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = '017'
down_revision = '016'


def upgrade():
    # -- Step 1: Add nullable workspace_id columns --
    for table in ('tracks', 'track_records', 'track_sectors'):
        op.add_column(table, sa.Column('workspace_id', sa.dialects.postgresql.UUID(), nullable=True))
        op.create_foreign_key(
            f'fk_{table}_workspace_id', table, 'workspaces',
            ['workspace_id'], ['workspace_id'],
        )

    # -- Step 2: Backfill from sessions --
    op.execute("""
        UPDATE tracks t
        SET workspace_id = (
            SELECT DISTINCT s.workspace_id
            FROM sessions s
            WHERE s.track_id = t.track_id AND s.workspace_id IS NOT NULL
            LIMIT 1
        )
        WHERE t.workspace_id IS NULL
    """)
    # Orphan tracks: assign to first workspace
    op.execute("""
        UPDATE tracks
        SET workspace_id = (SELECT workspace_id FROM workspaces ORDER BY created_at LIMIT 1)
        WHERE workspace_id IS NULL
    """)
    # Backfill track_records and track_sectors from tracks
    for table in ('track_records', 'track_sectors'):
        op.execute(f"""
            UPDATE {table} r
            SET workspace_id = (
                SELECT t.workspace_id FROM tracks t WHERE t.track_id = r.track_id
            )
            WHERE r.workspace_id IS NULL
        """)

    # -- Step 3: Set NOT NULL --
    for table in ('tracks', 'track_records', 'track_sectors'):
        op.alter_column(table, 'workspace_id', nullable=False)

    # -- Step 4: RLS policies --
    for table in ('tracks', 'track_records', 'track_sectors'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
            USING (workspace_id = current_setting('app.workspace_id')::uuid)
            WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid)
        """)

    # -- Step 5: Workspace-scoped unique constraint on track names --
    op.create_unique_constraint('uq_tracks_workspace_name', 'tracks', ['workspace_id', 'track_name'])


def downgrade():
    op.drop_constraint('uq_tracks_workspace_name', 'tracks')
    for table in ('tracks', 'track_records', 'track_sectors'):
        op.execute(f"DROP POLICY IF EXISTS {table}_workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_constraint(f'fk_{table}_workspace_id', table, type_='foreignkey')
        op.drop_column(table, 'workspace_id')
```

- [ ] **Step 2: Test migration against local PG**

Run: `alembic upgrade head`
Expected: Migration applies cleanly

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/017_tracks_workspace_rls.py
git commit -m "feat: migration 017 — workspace_id + RLS on tracks tables"
```

---

## Chunk 4: Frontend Fixes

### Task 8: Fix Track Detail Delete Behavior

**Files:**
- Modify: `lap-website/src/app/app/tracks/[id]/page.tsx:142-174`

- [ ] **Step 1: Update delete confirmation message**

In `lap-website/src/app/app/tracks/[id]/page.tsx`, replace lines 146-149:

```tsx
{/* Before */}
{track.session_count > 0 && (
  <span className="text-safety-red"> This track has {track.session_count} linked session(s) — you must unlink them first.</span>
)}

{/* After */}
{track.session_count > 0 && (
  <span className="text-safety-red"> This will permanently delete {track.session_count} session(s) and all associated data.</span>
)}
```

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/app/app/tracks/\[id\]/page.tsx
git commit -m "fix: track delete confirmation warns about cascade instead of blocking"
```

### Task 9: Build Track Evolution Page

**Files:**
- Modify: `lap-website/src/app/app/tracks/[id]/evolution/page.tsx` (replace stub)

- [ ] **Step 1: Replace stub with full evolution dashboard**

```tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { QueryError, SkeletonBox } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

interface LapTrendEntry {
  session_id: string;
  session_date: string;
  best_lap_time_s: number;
  total_score: number | null;
  n_laps: number | null;
  track_state: string | null;
  driver_name: string | null;
}

interface SectorEntry {
  session_id: string;
  session_date: string;
  sectors: { sector_index: number; best_sector_time_s: number }[];
}

interface CornerMetric {
  corner_index: number;
  avg_time_loss_s: number;
  avg_min_speed_mps: number;
  sample_count: number;
}

interface EvolutionData {
  lap_trend: LapTrendEntry[];
  sector_breakdown: SectorEntry[];
  corner_metrics: CornerMetric[];
}

function fmtTime(s: number | null): string {
  if (s == null) return '\u2014';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function fmtDate(d: string | null): string {
  if (!d) return '\u2014';
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function conditionBadge(state: string | null) {
  const s = (state || 'dry').toLowerCase();
  const colors: Record<string, string> = {
    dry: 'bg-acid-green/20 text-acid-green',
    wet: 'bg-blue-500/20 text-blue-400',
    damp: 'bg-yellow-500/20 text-yellow-400',
    mixed: 'bg-purple-500/20 text-purple-400',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-telemetry uppercase ${colors[s] || colors.dry}`}>
      {s}
    </span>
  );
}

export default function TrackEvolutionPage() {
  const params = useParams();
  const id = params.id as string;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['track-evolution', id],
    queryFn: () => api.get<EvolutionData>(`/tracks/${id}/evolution`),
  });

  if (isLoading) {
    return (
      <div>
        <SkeletonBox className="h-8 w-48 mb-4" />
        <SkeletonBox className="h-64 w-full mb-4" />
        <SkeletonBox className="h-48 w-full" />
      </div>
    );
  }

  if (error) {
    return <QueryError message="Couldn't load evolution data." onRetry={() => refetch()} />;
  }

  if (!data) return null;

  const { lap_trend, sector_breakdown, corner_metrics } = data;

  // Compute rolling average (5-session window)
  const rollingAvg = lap_trend.map((entry, i) => {
    const windowSize = Math.min(5, i + 1);
    const window = lap_trend.slice(Math.max(0, i - windowSize + 1), i + 1);
    const avg = window.reduce((sum, e) => sum + e.best_lap_time_s, 0) / window.length;
    return { ...entry, rolling_avg: avg };
  });

  // Best and worst corners
  const sortedCorners = [...corner_metrics].sort((a, b) => b.avg_time_loss_s - a.avg_time_loss_s);
  const maxTimeLoss = sortedCorners.length > 0 ? sortedCorners[0].avg_time_loss_s : 1;

  return (
    <div>
      <PageIntro
        title="Track Evolution"
        subtitle={`${lap_trend.length} session${lap_trend.length !== 1 ? 's' : ''} analysed`}
        actions={
          <Link
            href={`/app/tracks/${id}`}
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            &larr; Track Detail
          </Link>
        }
      />

      {lap_trend.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <h2 className="font-monument text-lg text-chalk mb-2">No session data yet</h2>
          <p className="text-steel font-body text-sm">Upload sessions at this track to see your evolution.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* ── Lap Time Trend ─────────────────────────────── */}
          <div className="bg-concrete rounded-lg border border-steel/20 p-4">
            <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">Lap Time Trend</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-steel font-telemetry text-xs uppercase border-b border-steel/20">
                    <th className="text-left py-2 pr-4">Date</th>
                    <th className="text-left py-2 pr-4">Driver</th>
                    <th className="text-right py-2 pr-4">Best Lap</th>
                    <th className="text-right py-2 pr-4">Rolling Avg</th>
                    <th className="text-right py-2 pr-4">Score</th>
                    <th className="text-right py-2 pr-4">Laps</th>
                    <th className="text-center py-2">Condition</th>
                  </tr>
                </thead>
                <tbody>
                  {rollingAvg.map((entry, i) => {
                    const prev = i > 0 ? rollingAvg[i - 1] : null;
                    const improved = prev && entry.best_lap_time_s < prev.best_lap_time_s;
                    const worsened = prev && entry.best_lap_time_s > prev.best_lap_time_s;
                    return (
                      <tr key={entry.session_id} className="border-b border-steel/10 hover:bg-steel/5">
                        <td className="py-2 pr-4 text-chalk font-body">{fmtDate(entry.session_date)}</td>
                        <td className="py-2 pr-4 text-chalk font-body">{entry.driver_name || '\u2014'}</td>
                        <td className={`py-2 pr-4 text-right font-telemetry ${improved ? 'text-acid-green' : worsened ? 'text-safety-red' : 'text-chalk'}`}>
                          {fmtTime(entry.best_lap_time_s)}
                          {improved && ' \u2193'}
                          {worsened && ' \u2191'}
                        </td>
                        <td className="py-2 pr-4 text-right font-telemetry text-steel">
                          {fmtTime(entry.rolling_avg)}
                        </td>
                        <td className="py-2 pr-4 text-right font-telemetry text-chalk">
                          {entry.total_score != null ? entry.total_score.toFixed(0) : '\u2014'}
                        </td>
                        <td className="py-2 pr-4 text-right font-telemetry text-steel">
                          {entry.n_laps ?? '\u2014'}
                        </td>
                        <td className="py-2 text-center">{conditionBadge(entry.track_state)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Sector Breakdown ───────────────────────────── */}
          {sector_breakdown.length > 0 && (
            <div className="bg-concrete rounded-lg border border-steel/20 p-4">
              <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">Sector Breakdown</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-steel font-telemetry text-xs uppercase border-b border-steel/20">
                      <th className="text-left py-2 pr-4">Date</th>
                      {sector_breakdown[0]?.sectors.map((s) => (
                        <th key={s.sector_index} className="text-right py-2 pr-4">S{s.sector_index + 1}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sector_breakdown.map((entry) => (
                      <tr key={entry.session_id} className="border-b border-steel/10 hover:bg-steel/5">
                        <td className="py-2 pr-4 text-chalk font-body">{fmtDate(entry.session_date)}</td>
                        {entry.sectors.map((s) => (
                          <td key={s.sector_index} className="py-2 pr-4 text-right font-telemetry text-chalk">
                            {s.best_sector_time_s.toFixed(3)}s
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Corner Performance ─────────────────────────── */}
          {corner_metrics.length > 0 && (
            <div className="bg-concrete rounded-lg border border-steel/20 p-4">
              <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">
                Corner Performance (worst → best)
              </h2>
              <div className="space-y-2">
                {sortedCorners.map((corner) => {
                  const pct = maxTimeLoss > 0 ? (corner.avg_time_loss_s / maxTimeLoss) * 100 : 0;
                  return (
                    <div key={corner.corner_index} className="flex items-center gap-3">
                      <span className="w-12 text-right font-telemetry text-xs text-steel shrink-0">
                        T{corner.corner_index + 1}
                      </span>
                      <div className="flex-1 h-5 bg-asphalt rounded overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-safety-red to-pit-orange rounded"
                          style={{ width: `${Math.max(pct, 2)}%` }}
                        />
                      </div>
                      <span className="w-20 text-right font-telemetry text-xs text-chalk shrink-0">
                        {corner.avg_time_loss_s.toFixed(3)}s
                      </span>
                      <span className="w-16 text-right font-telemetry text-[10px] text-steel shrink-0">
                        ({corner.sample_count} samples)
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add evolution link to track detail page**

In `lap-website/src/app/app/tracks/[id]/page.tsx`, add a link button in the actions section (after the "All Tracks" link, around line 137):

```tsx
<Link
  href={`/app/tracks/${id}/evolution`}
  className="px-4 py-2 border border-acid-green/30 text-acid-green font-telemetry text-sm rounded hover:bg-acid-green/10 transition-colors"
>
  Evolution
</Link>
```

- [ ] **Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/app/app/tracks/\[id\]/evolution/page.tsx lap-website/src/app/app/tracks/\[id\]/page.tsx
git commit -m "feat: build track evolution dashboard (lap trend, sectors, corners)"
```

---

## Chunk 5: Integration Test & Cleanup

### Task 10: End-to-End Smoke Test

- [ ] **Step 1: Run full backend test suite**

Run: `pytest telemetry_tool/tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Run frontend build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 3: Run frontend lint**

Run: `cd lap-website && npm run lint`
Expected: No new lint errors

- [ ] **Step 4: Manual smoke test (if dev server available)**

Start backend: `cd telemetry_tool && python main.py --serve`
Start frontend: `cd lap-website && npm run dev`
Verify:
- `/app/tracks` loads and shows tracks
- Click a track → detail page loads, Edit/Delete/Evolution buttons visible
- Delete shows cascade warning with session count
- Evolution page shows trend data or "no data" message

- [ ] **Step 5: Final commit (if any cleanup needed)**

```bash
git add -A
git commit -m "chore: integration test cleanup for tracks section fix"
```
