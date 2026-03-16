# Endurance Report System — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-tier drill-down report system (Team → Driver → Stint) for multi-driver endurance races with auto pit detection and driver assignment.

**Architecture:** Auto-detect pit stops from lap times, store stint boundaries in DB, let users assign drivers to stints via UI, run existing scorer per-stint, render 3-tier drill-down in a new Endurance tab on session detail.

**Tech Stack:** Python/Flask (backend), PostgreSQL + Alembic (DB), Next.js/React/TypeScript (frontend), existing `stint_analysis.py` functions (reuse), existing scoring module.

**Spec:** `docs/superpowers/specs/2026-03-16-endurance-report-design.md`

---

## File Structure

### Backend — New Files
- `telemetry_tool/alembic/versions/046_endurance_stints.py` — Migration for endurance tables
- `telemetry_tool/pipeline/stages/s14_endurance.py` — Pit detection pipeline stage
- `telemetry_tool/web/repos/endurance_repo.py` — CRUD for stints + driver assignments
- `telemetry_tool/endurance_scoring.py` — Per-stint, per-driver, team scoring orchestration

### Backend — Modified Files
- `telemetry_tool/pipeline/orchestrator.py` — Register stage s14
- `telemetry_tool/web/routes/data_v2.py` — 4 new endpoints (stints, configure, assign, endurance-report)
- `telemetry_tool/web/app.py` — No change needed (data_v2 blueprint already registered)

### Frontend — New Files
- `lap-website/src/components/app/endurance/EnduranceTab.tsx` — Main tab with setup + tier routing
- `lap-website/src/components/app/endurance/SetupFlow.tsx` — Pit detection config + driver assignment
- `lap-website/src/components/app/endurance/TeamReport.tsx` — Tier 3
- `lap-website/src/components/app/endurance/DriverReport.tsx` — Tier 2
- `lap-website/src/components/app/endurance/StintReport.tsx` — Tier 1
- `lap-website/src/components/app/endurance/StrategyTimeline.tsx` — Visual stint timeline bar
- `lap-website/src/components/app/endurance/index.ts` — Barrel export
- `lap-website/src/components/app/endurance/types.ts` — Shared types

### Frontend — Modified Files
- `lap-website/src/app/app/sessions/[id]/page.tsx` — Add Endurance tab to TABS array + lazy import

### Tests
- `telemetry_tool/tests/test_endurance_detection.py` — Pit detection + stint boundary tests
- `telemetry_tool/tests/test_endurance_scoring.py` — Per-stint, per-driver, team scoring
- `telemetry_tool/tests/test_endurance_api.py` — API endpoint tests

---

## Chunk 1: Backend — Database + Pit Detection

### Task 1: Alembic Migration for Endurance Tables

**Files:**
- Create: `telemetry_tool/alembic/versions/046_endurance_stints.py`

- [ ] **Step 1: Write the migration**

```python
"""046 — endurance stints and driver assignments."""
from alembic import op
import sqlalchemy as sa

revision = "046"
down_revision = "045"

def upgrade():
    op.create_table(
        "endurance_stints",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("stint_number", sa.Integer, nullable=False),
        sa.Column("start_lap", sa.Integer, nullable=False),
        sa.Column("end_lap", sa.Integer, nullable=False),
        sa.Column("lap_count", sa.Integer, nullable=False),
        sa.Column("pit_lap_number", sa.Integer, nullable=True),
        sa.Column("pit_lap_time_s", sa.Float, nullable=True),
        sa.Column("condition", sa.Text, nullable=True, server_default="dry"),
        sa.Column("driver_id", sa.Integer, nullable=True),
        sa.Column("driver_name", sa.Text, nullable=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
                  server_default=sa.text("current_setting('app.current_workspace_id')::integer")),
        sa.UniqueConstraint("session_id", "stint_number", name="uq_endurance_stint"),
    )
    op.create_index("idx_endurance_stints_session", "endurance_stints", ["session_id"])
    op.create_index("idx_endurance_stints_workspace", "endurance_stints", ["workspace_id"])

    # RLS policy
    op.execute("""
        ALTER TABLE endurance_stints ENABLE ROW LEVEL SECURITY;
        CREATE POLICY endurance_stints_tenant_isolation ON endurance_stints
            USING (workspace_id = current_setting('app.current_workspace_id')::integer)
            WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);
    """)

    # Add pit_threshold_s to sessions table for user-configured threshold
    op.add_column("sessions", sa.Column("pit_threshold_s", sa.Float, nullable=True))

def downgrade():
    op.drop_column("sessions", "pit_threshold_s")
    op.execute("DROP POLICY IF EXISTS endurance_stints_tenant_isolation ON endurance_stints")
    op.drop_table("endurance_stints")
```

- [ ] **Step 2: Run migration**

```bash
cd telemetry_tool && alembic upgrade head
```

- [ ] **Step 3: Verify on VPS**

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec -T api alembic upgrade head"
```

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/alembic/versions/046_endurance_stints.py
git commit -m "feat: migration 046 — endurance_stints table with RLS"
```

---

### Task 2: Endurance Repository (CRUD)

**Files:**
- Create: `telemetry_tool/web/repos/endurance_repo.py`
- Test: `telemetry_tool/tests/test_endurance_detection.py`

- [ ] **Step 1: Write the failing test for stint storage**

```python
# telemetry_tool/tests/test_endurance_detection.py
import pytest
from web.repos.endurance_repo import (
    detect_and_store_stints,
    get_stints,
    assign_driver_to_stint,
    get_endurance_config,
)

def test_detect_stints_from_lap_times(test_db):
    """Pit laps > threshold create stint boundaries."""
    # Setup: 12 laps, pit at lap 6 (180s) and lap 10 (150s)
    lap_times = {
        1: 52.1, 2: 53.0, 3: 52.5, 4: 53.2, 5: 52.8,
        6: 180.0,  # pit
        7: 53.5, 8: 52.9, 9: 53.1,
        10: 150.0,  # pit
        11: 52.0, 12: 53.3,
    }
    stints = detect_and_store_stints(
        test_db, "sess1", lap_times, pit_threshold_s=120.0
    )
    assert len(stints) == 3
    assert stints[0]["start_lap"] == 1
    assert stints[0]["end_lap"] == 5
    assert stints[0]["pit_lap_number"] == 6
    assert stints[1]["start_lap"] == 7
    assert stints[1]["end_lap"] == 9
    assert stints[2]["start_lap"] == 11
    assert stints[2]["end_lap"] == 12

def test_assign_driver_to_stint(test_db):
    """Assign a driver name to a stint."""
    lap_times = {1: 52.0, 2: 53.0, 3: 180.0, 4: 52.0, 5: 53.0}
    detect_and_store_stints(test_db, "sess1", lap_times, pit_threshold_s=120.0)
    assign_driver_to_stint(test_db, "sess1", stint_number=1, driver_name="Théo")
    stints = get_stints(test_db, "sess1")
    assert stints[0]["driver_name"] == "Théo"

def test_no_pit_stops_single_stint(test_db):
    """Session with no pit laps = single stint."""
    lap_times = {1: 52.0, 2: 53.0, 3: 52.5, 4: 53.1}
    stints = detect_and_store_stints(test_db, "sess1", lap_times, pit_threshold_s=120.0)
    assert len(stints) == 1
    assert stints[0]["start_lap"] == 1
    assert stints[0]["end_lap"] == 4

def test_reconfigure_threshold_redetects(test_db):
    """Changing pit threshold re-detects stints."""
    lap_times = {1: 52.0, 2: 53.0, 3: 90.0, 4: 52.0, 5: 53.0}
    # At 120s threshold, lap 3 is not a pit
    stints = detect_and_store_stints(test_db, "sess1", lap_times, pit_threshold_s=120.0)
    assert len(stints) == 1
    # At 80s threshold, lap 3 IS a pit
    stints = detect_and_store_stints(test_db, "sess1", lap_times, pit_threshold_s=80.0)
    assert len(stints) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest telemetry_tool/tests/test_endurance_detection.py -v
```

- [ ] **Step 3: Implement endurance_repo.py**

```python
# telemetry_tool/web/repos/endurance_repo.py
"""Endurance stint detection, storage, and driver assignment."""
from __future__ import annotations
import sqlite3
from typing import Any

DEFAULT_PIT_THRESHOLD_S = 120.0


def detect_and_store_stints(
    conn: sqlite3.Connection,
    session_id: str,
    lap_times: dict[int, float],
    pit_threshold_s: float = DEFAULT_PIT_THRESHOLD_S,
) -> list[dict[str, Any]]:
    """Detect pit laps, create stint boundaries, store in DB.

    Replaces any existing stints for this session (idempotent).
    """
    # Clear existing stints
    conn.execute(
        "DELETE FROM endurance_stints WHERE session_id = :sid",
        {"sid": session_id},
    )

    # Sort laps by number
    sorted_laps = sorted(lap_times.items())

    # Classify pit laps
    pit_laps = {ln for ln, t in sorted_laps if t > pit_threshold_s}

    # Group valid laps into stints
    stints: list[dict[str, Any]] = []
    current_laps: list[int] = []
    last_pit_lap: int | None = None

    for lap_num, lap_time in sorted_laps:
        if lap_num in pit_laps:
            # End current stint
            if current_laps:
                stints.append({
                    "stint_number": len(stints) + 1,
                    "start_lap": current_laps[0],
                    "end_lap": current_laps[-1],
                    "lap_count": len(current_laps),
                    "pit_lap_number": lap_num,
                    "pit_lap_time_s": lap_time,
                })
                current_laps = []
        else:
            current_laps.append(lap_num)

    # Final stint (no trailing pit)
    if current_laps:
        stints.append({
            "stint_number": len(stints) + 1,
            "start_lap": current_laps[0],
            "end_lap": current_laps[-1],
            "lap_count": len(current_laps),
            "pit_lap_number": None,
            "pit_lap_time_s": None,
        })

    # Persist
    for s in stints:
        conn.execute(
            "INSERT INTO endurance_stints "
            "(session_id, stint_number, start_lap, end_lap, lap_count, "
            " pit_lap_number, pit_lap_time_s) "
            "VALUES (:sid, :sn, :sl, :el, :lc, :pln, :plt)",
            {
                "sid": session_id,
                "sn": s["stint_number"],
                "sl": s["start_lap"],
                "el": s["end_lap"],
                "lc": s["lap_count"],
                "pln": s["pit_lap_number"],
                "plt": s["pit_lap_time_s"],
            },
        )
    conn.commit()

    # Store threshold on session
    conn.execute(
        "UPDATE sessions SET pit_threshold_s = :pt WHERE session_id = :sid",
        {"pt": pit_threshold_s, "sid": session_id},
    )
    conn.commit()

    return stints


def get_stints(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict[str, Any]]:
    """Return all stints for a session, ordered by stint_number."""
    rows = conn.execute(
        "SELECT * FROM endurance_stints "
        "WHERE session_id = :sid ORDER BY stint_number",
        {"sid": session_id},
    ).fetchall()
    return [dict(r) for r in rows]


def assign_driver_to_stint(
    conn: sqlite3.Connection,
    session_id: str,
    stint_number: int,
    driver_name: str | None = None,
    driver_id: int | None = None,
    condition: str | None = None,
) -> None:
    """Assign a driver and/or condition to a stint."""
    sets: list[str] = []
    vals: dict[str, Any] = {"sid": session_id, "sn": stint_number}

    if driver_name is not None:
        sets.append("driver_name = :dn")
        vals["dn"] = driver_name
    if driver_id is not None:
        sets.append("driver_id = :did")
        vals["did"] = driver_id
    if condition is not None:
        sets.append("condition = :cond")
        vals["cond"] = condition

    if sets:
        conn.execute(
            f"UPDATE endurance_stints SET {', '.join(sets)} "
            "WHERE session_id = :sid AND stint_number = :sn",
            vals,
        )
        conn.commit()


def bulk_assign_drivers(
    conn: sqlite3.Connection,
    session_id: str,
    assignments: list[dict[str, Any]],
) -> int:
    """Bulk assign drivers + conditions to stints.

    Each assignment: {stint_number, driver_name?, driver_id?, condition?}
    """
    count = 0
    for a in assignments:
        assign_driver_to_stint(
            conn, session_id,
            stint_number=a["stint_number"],
            driver_name=a.get("driver_name"),
            driver_id=a.get("driver_id"),
            condition=a.get("condition"),
        )
        count += 1
    return count


def get_endurance_config(
    conn: sqlite3.Connection,
    session_id: str,
) -> dict[str, Any]:
    """Return endurance configuration for a session."""
    row = conn.execute(
        "SELECT pit_threshold_s FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    return {
        "pit_threshold_s": (row["pit_threshold_s"] if row and row["pit_threshold_s"]
                            else DEFAULT_PIT_THRESHOLD_S),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest telemetry_tool/tests/test_endurance_detection.py -v
```

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/web/repos/endurance_repo.py telemetry_tool/tests/test_endurance_detection.py
git commit -m "feat: endurance repo — pit detection + stint storage + driver assignment"
```

---

### Task 3: Per-Stint Scoring

**Files:**
- Create: `telemetry_tool/endurance_scoring.py`
- Test: `telemetry_tool/tests/test_endurance_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# telemetry_tool/tests/test_endurance_scoring.py
from endurance_scoring import compute_stint_scores, compute_driver_report, compute_team_report

def test_stint_score_uses_only_stint_laps():
    """Per-stint scoring only uses laps within the stint range."""
    all_laps = [
        {"lap_number": 1, "lap_time_s": 52.1, "is_valid": True},
        {"lap_number": 2, "lap_time_s": 53.0, "is_valid": True},
        {"lap_number": 3, "lap_time_s": 52.5, "is_valid": True},
        # pit
        {"lap_number": 5, "lap_time_s": 54.0, "is_valid": True},
        {"lap_number": 6, "lap_time_s": 53.5, "is_valid": True},
    ]
    stint = {"stint_number": 1, "start_lap": 1, "end_lap": 3}
    result = compute_stint_scores(all_laps, stint)
    assert result["best_lap_s"] == 52.1
    assert result["lap_count"] == 3
    assert "pace" in result["scores"]

def test_driver_report_aggregates_stints():
    """Driver report combines stats across assigned stints."""
    stints = [
        {"stint_number": 1, "driver_name": "Théo", "best_lap_s": 52.1, "mean_lap_s": 53.0, "lap_count": 8},
        {"stint_number": 3, "driver_name": "Théo", "best_lap_s": 51.4, "mean_lap_s": 52.5, "lap_count": 10},
    ]
    report = compute_driver_report("Théo", stints)
    assert report["total_laps"] == 18
    assert report["best_lap_s"] == 51.4
    assert len(report["best_per_stint"]) == 2

def test_team_report_compares_drivers():
    """Team report includes driver comparison."""
    driver_reports = {
        "Théo": {"best_lap_s": 51.4, "total_laps": 42},
        "William": {"best_lap_s": 52.0, "total_laps": 45},
    }
    report = compute_team_report(driver_reports, total_laps=87, total_stints=10)
    assert len(report["driver_comparison"]) == 2
    assert report["total_laps"] == 87
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest telemetry_tool/tests/test_endurance_scoring.py -v
```

- [ ] **Step 3: Implement endurance_scoring.py**

Build `compute_stint_scores()`, `compute_driver_report()`, `compute_team_report()`. Per-stint scoring calls the existing `score_session()` with metrics computed from the stint's laps only. Driver aggregation takes the best across stints and weighted means. Team report combines all.

Key: reuse `scoring.scorer.score_session()` by computing `metrics_dict` from the lap subset:
```python
metrics = {
    "best_s": min(lap_times),
    "mean_s": statistics.mean(lap_times),
    "median_s": statistics.median(lap_times),
    "std_s": statistics.stdev(lap_times) if len(lap_times) > 1 else 0,
    "n_valid_laps": len(lap_times),
    "best_to_median_s": statistics.median(lap_times) - min(lap_times),
    "early_mean_s": statistics.mean(lap_times[:len(lap_times)//3]) if len(lap_times) >= 3 else statistics.mean(lap_times),
    "late_mean_s": statistics.mean(lap_times[-len(lap_times)//3:]) if len(lap_times) >= 3 else statistics.mean(lap_times),
}
score_result = score_session(metrics, {}, session_type="endurance_stint", track_state=condition)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest telemetry_tool/tests/test_endurance_scoring.py -v
```

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/endurance_scoring.py telemetry_tool/tests/test_endurance_scoring.py
git commit -m "feat: endurance scoring — per-stint, per-driver, team aggregation"
```

---

## Chunk 2: Backend — API Endpoints

### Task 4: Stints API Endpoints

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (add 4 endpoints at end of file)
- Test: `telemetry_tool/tests/test_endurance_api.py`

- [ ] **Step 1: Write the failing API test**

```python
# telemetry_tool/tests/test_endurance_api.py
def test_get_stints_returns_detected_stints(client, seeded_endurance_session):
    """GET /sessions/{id}/stints returns stint boundaries."""
    resp = client.get(f"/api/v1/sessions/{seeded_endurance_session}/stints")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"]
    assert len(data["data"]["stints"]) >= 2

def test_configure_stints_redetects(client, seeded_endurance_session):
    """POST /sessions/{id}/stints/configure with new threshold re-detects."""
    resp = client.post(
        f"/api/v1/sessions/{seeded_endurance_session}/stints/configure",
        json={"pit_threshold_s": 90},
    )
    assert resp.status_code == 200

def test_assign_drivers(client, seeded_endurance_session):
    """POST /sessions/{id}/stints/assign saves driver assignments."""
    resp = client.post(
        f"/api/v1/sessions/{seeded_endurance_session}/stints/assign",
        json={"assignments": [
            {"stint_number": 1, "driver_name": "Théo", "condition": "dry"},
            {"stint_number": 2, "driver_name": "William", "condition": "damp"},
        ]},
    )
    assert resp.status_code == 200

def test_endurance_report_requires_assignments(client, seeded_endurance_session):
    """GET /sessions/{id}/endurance-report fails without driver assignments."""
    resp = client.get(f"/api/v1/sessions/{seeded_endurance_session}/endurance-report")
    assert resp.status_code == 400  # no assignments yet
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement 4 endpoints in data_v2.py**

Add at end of file, after existing endpoints:
1. `GET /sessions/<id>/stints` — calls `get_stints()` + enriches with per-stint stats from laps table
2. `POST /sessions/<id>/stints/configure` — calls `detect_and_store_stints()` with new threshold
3. `POST /sessions/<id>/stints/assign` — calls `bulk_assign_drivers()`
4. `GET /sessions/<id>/endurance-report` — calls `compute_team_report()` + `compute_driver_report()` per driver

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_endurance_api.py
git commit -m "feat: endurance API — stints, configure, assign, report endpoints"
```

---

### Task 5: Pipeline Integration — Auto-Detect on Upload

**Files:**
- Create: `telemetry_tool/pipeline/stages/s14_endurance.py`
- Modify: `telemetry_tool/pipeline/orchestrator.py`

- [ ] **Step 1: Create pipeline stage**

```python
# telemetry_tool/pipeline/stages/s14_endurance.py
"""Stage 14: Detect pit stops and create stint boundaries."""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

def run_endurance_detection(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Detect pit laps from lap metrics, store stint boundaries."""
    lap_metrics = summary.get("lap_metrics") or []
    if not lap_metrics or len(lap_metrics) < 3:
        return None

    lap_times = {}
    for lm in lap_metrics:
        ln = lm.get("lap_number")
        lt = lm.get("lap_time_s")
        if ln is not None and lt is not None and lt > 0:
            lap_times[ln] = lt

    if len(lap_times) < 3:
        return None

    # Use default threshold for auto-detection
    from web.repos.endurance_repo import detect_and_store_stints, DEFAULT_PIT_THRESHOLD_S
    from web.db import get_db_connection

    conn = get_db_connection()
    session_id = summary.get("session_id")
    if not session_id:
        return None

    stints = detect_and_store_stints(conn, session_id, lap_times, DEFAULT_PIT_THRESHOLD_S)

    if len(stints) <= 1:
        logger.info("No pit stops detected for session %s", session_id)
        return None

    logger.info("Detected %d stints for session %s", len(stints), session_id)
    return {"n_stints": len(stints), "stints": stints}
```

- [ ] **Step 2: Register in orchestrator.py**

Add to `_STAGE_MAP` between scoring and persist:
```python
("14_endurance", "Endurance Detection"),
```

Add to the run function:
```python
from pipeline.stages import s14_endurance
endurance_r, err = _safe_step("14_endurance", s14_endurance.run_endurance_detection, summary)
if endurance_r:
    summary["endurance_stints"] = endurance_r
```

- [ ] **Step 3: Test with a real upload**

Upload a CSV with known pit stops, verify stints are detected in DB.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/pipeline/stages/s14_endurance.py telemetry_tool/pipeline/orchestrator.py
git commit -m "feat: pipeline stage 14 — auto-detect pit stops on upload"
```

- [ ] **Step 5: Deploy backend**

```bash
scp files → docker compose build api && up -d api
```

---

## Chunk 3: Frontend — Endurance Tab + Setup Flow

### Task 6: Types + Barrel Export

**Files:**
- Create: `lap-website/src/components/app/endurance/types.ts`
- Create: `lap-website/src/components/app/endurance/index.ts`

- [ ] **Step 1: Create types**

```typescript
// types.ts
export interface Stint {
  stint_number: number;
  start_lap: number;
  end_lap: number;
  lap_count: number;
  pit_lap_number: number | null;
  pit_lap_time_s: number | null;
  condition: string | null;
  driver_name: string | null;
  driver_id: number | null;
  // Enriched stats
  best_lap_s?: number;
  mean_lap_s?: number;
  consistency_cv_pct?: number;
}

export interface StintAssignment {
  stint_number: number;
  driver_name?: string;
  driver_id?: number;
  condition?: string;
}

export interface DriverReport {
  driver_name: string;
  total_laps: number;
  total_stints: number;
  stints: Stint[];
  best_lap_s: number;
  mean_lap_s: number;
  consistency_cv_pct: number;
  best_per_stint: { stint_number: number; best_lap_s: number }[];
  scores: { pace: number; consistency: number; robustness: number };
}

export interface TeamReport {
  total_laps: number;
  total_time_s: number;
  total_stints: number;
  drivers: string[];
  driver_comparison: DriverReport[];
  scores: { pace: number; consistency: number; robustness: number };
}

export type EnduranceTier = 'team' | 'driver' | 'stint';
```

- [ ] **Step 2: Create barrel export**

```typescript
// index.ts
export { EnduranceTab } from './EnduranceTab';
```

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/endurance/
git commit -m "feat: endurance types + barrel export"
```

---

### Task 7: Setup Flow Component

**Files:**
- Create: `lap-website/src/components/app/endurance/SetupFlow.tsx`

- [ ] **Step 1: Build the setup flow**

The setup flow shows when no driver assignments exist yet:
1. Stint detection summary with threshold adjuster
2. "Add Driver" button → driver name input
3. Stint checkboxes per driver
4. Condition dropdown per stint
5. "Generate Report" button

Component fetches `GET /sessions/{id}/stints` on mount, shows detected stints, allows driver assignment via `POST /sessions/{id}/stints/assign`.

- [ ] **Step 2: Verify it renders**

- [ ] **Step 3: Commit**

---

### Task 8: Add Endurance Tab to Session Detail

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`

- [ ] **Step 1: Add tab**

Add `'endurance'` to Tab type and TABS array (conditionally — only when stints > 1 or session_type is endurance).

Lazy import: `const EnduranceTab = lazy(() => import('@/components/app/endurance').then(m => ({ default: m.EnduranceTab })));`

- [ ] **Step 2: Build and verify**

- [ ] **Step 3: Commit**

---

## Chunk 4: Frontend — 3-Tier Reports

### Task 9: Team Report (Tier 3)

**Files:**
- Create: `lap-website/src/components/app/endurance/TeamReport.tsx`
- Create: `lap-website/src/components/app/endurance/StrategyTimeline.tsx`

- [ ] **Step 1: Build TeamReport**

Fetches `GET /sessions/{id}/endurance-report`. Renders:
- Race summary stat cards
- Driver comparison table (clickable rows → drill to Tier 2)
- Strategy timeline (colored stint blocks per driver)
- Team score bars

- [ ] **Step 2: Build StrategyTimeline**

Horizontal bar chart: X = lap number, colored blocks per driver. Pit stops as gaps. Uses canvas or simple divs.

- [ ] **Step 3: Commit**

---

### Task 10: Driver Report (Tier 2)

**Files:**
- Create: `lap-website/src/components/app/endurance/DriverReport.tsx`

- [ ] **Step 1: Build DriverReport**

Receives driver data from parent. Renders:
- Driver header with stats
- Stint cards grid (clickable → drill to Tier 1)
- Best lap progression line (stint # vs best time)
- Driver score bars
- Back button → Team

- [ ] **Step 2: Commit**

---

### Task 11: Stint Report (Tier 1)

**Files:**
- Create: `lap-website/src/components/app/endurance/StintReport.tsx`

- [ ] **Step 1: Build StintReport**

Reuses existing overview layout pattern (score bars, stat cards, lap table). Scoped to stint's lap range. Condition badge in header. Back button → Driver.

Fetches laps for the stint range and reuses existing `StatCard`, `ScoreBar` components.

- [ ] **Step 2: Commit**

---

### Task 12: EnduranceTab Router

**Files:**
- Create: `lap-website/src/components/app/endurance/EnduranceTab.tsx`

- [ ] **Step 1: Build the main tab component**

Manages state: `{ tier: 'team' | 'driver' | 'stint', driverName?: string, stintNumber?: number }`.

```
if no assignments → render SetupFlow
if tier === 'team' → render TeamReport
if tier === 'driver' → render DriverReport
if tier === 'stint' → render StintReport
```

Navigation callbacks: `onSelectDriver(name)`, `onSelectStint(number)`, `onBack()`.

- [ ] **Step 2: Build, deploy, test full flow**

```bash
npm run build && npm run cf:deploy
```

- [ ] **Step 3: Final commit**

```bash
git add lap-website/src/components/app/endurance/
git commit -m "feat: endurance 3-tier report — team, driver, stint drill-down"
```

---

## Deployment Checklist

- [ ] Run migration 046 on VPS
- [ ] Deploy backend (scp → docker compose build api && up -d api)
- [ ] Deploy frontend (npm run build && npm run cf:deploy)
- [ ] Test: upload endurance CSV → stints detected → assign drivers → generate report → drill-down works
- [ ] Verify existing non-endurance sessions are unaffected (no Endurance tab appears)
