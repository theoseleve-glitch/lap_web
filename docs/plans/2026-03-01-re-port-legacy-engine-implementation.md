# Re-Port Legacy Telemetry Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the SaaS telemetry system from the ground up using the working Old Tool as the canonical engine, preserving auth/billing/marketing infrastructure.

**Architecture:** Gut all broken telemetry code (Next.js chart components, Flask data API routes, session pages). Re-wire the upload endpoint to call `run_full_analysis()` synchronously. Rebuild data API endpoints that serve exactly what the Old Tool's vanilla JS modules expect. Wrap those vanilla JS modules in React components with distance-based hover sync via Zustand.

**Tech Stack:** Python/Flask (backend), Next.js 14/TypeScript/Tailwind (frontend), PostgreSQL 16, vanilla JS Canvas charts (wrapped in React), Matplotlib (report export)

**Design Doc:** `docs/plans/2026-03-01-re-port-legacy-engine-design.md`

---

## Phase 0: Gut Broken Telemetry Code

### Task 0.1: Create Feature Branch

**Files:**
- None (git operation only)

**Step 1: Create and switch to feature branch**

Run:
```bash
git checkout -b feat/re-port-legacy-engine
```

**Step 2: Commit**

No files changed yet — branch created.

---

### Task 0.2: Remove Broken Next.js Chart Components

**Files:**
- Delete: `lap-website/src/components/app/charts/` (entire directory — 26 files)
- Delete: `lap-website/src/components/app/ChartPanel.tsx`
- Delete: `lap-website/src/components/app/ChartTooltip.tsx`
- Delete: `lap-website/src/components/mechanisms/TelemetryTracesCanvas.tsx`
- Delete: `lap-website/src/hooks/useInteractiveCanvas.ts`
- Delete: `lap-website/src/lib/chart-hover-store.ts`

**Step 1: Delete all chart components and supporting files**

Run:
```bash
rm -rf lap-website/src/components/app/charts/
rm -f lap-website/src/components/app/ChartPanel.tsx
rm -f lap-website/src/components/app/ChartTooltip.tsx
rm -f lap-website/src/components/mechanisms/TelemetryTracesCanvas.tsx
rm -f lap-website/src/hooks/useInteractiveCanvas.ts
rm -f lap-website/src/lib/chart-hover-store.ts
```

**Step 2: Find and list any remaining imports of deleted files**

Run:
```bash
cd lap-website && grep -r "charts/" src/ --include="*.tsx" --include="*.ts" -l
grep -r "useInteractiveCanvas" src/ --include="*.tsx" --include="*.ts" -l
grep -r "chart-hover-store" src/ --include="*.tsx" --include="*.ts" -l
grep -r "ChartPanel" src/ --include="*.tsx" --include="*.ts" -l
grep -r "ChartTooltip" src/ --include="*.tsx" --include="*.ts" -l
grep -r "TelemetryTracesCanvas" src/ --include="*.tsx" --include="*.ts" -l
```

Note: These imports will exist in the page files we're about to gut in Task 0.3. No action needed yet — they'll be removed together.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove broken chart components, hooks, and stores"
```

---

### Task 0.3: Gut Broken Next.js Telemetry Pages

**Files:**
- Gut: `lap-website/src/app/app/sessions/[id]/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/sessions/[id]/corners/[cornerId]/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/visualize/[id]/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/compare/sessions/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/compare/drivers/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/analytics/trends/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/analytics/pace-predictor/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/analytics/weather/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/analytics/meteo/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/analytics/weight-simulator/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/tracks/[id]/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/tracks/[id]/evolution/page.tsx` -> replace with placeholder
- Gut: `lap-website/src/app/app/leaderboard/page.tsx` -> replace with placeholder

**Step 1: Replace each page with a minimal placeholder**

Each gutted page gets this pattern (adjust title per page):

```tsx
'use client';

export default function SessionDetailPage() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-zinc-100 mb-2">Session Detail</h1>
        <p className="text-zinc-400">Re-port in progress. This page is being rebuilt.</p>
      </div>
    </div>
  );
}
```

Keep: `lap-website/src/app/app/sessions/page.tsx` (session list — will rewire in Phase 2)
Keep: `lap-website/src/app/app/tracks/page.tsx` (track list)
Keep: `lap-website/src/app/app/dashboard/page.tsx` (dashboard shell)
Keep: `lap-website/src/app/app/compare/page.tsx` (compare landing)
Keep: `lap-website/src/app/app/analytics/page.tsx` (analytics landing)
Keep: `lap-website/src/app/app/visualize/page.tsx` (visualize landing)

**Step 2: Verify build compiles**

Run:
```bash
cd lap-website && npm run build
```

Expected: Build succeeds. If import errors, fix remaining references to deleted chart components.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: gut broken telemetry pages with placeholders"
```

---

### Task 0.4: Remove Broken Flask API Data Routes

**Files:**
- Delete: `telemetry_tool/web/routes/api_v1_data.py` (159 KB)
- Delete: `telemetry_tool/web/routes/api_data.py` (153 KB)
- Delete: `telemetry_tool/web/routes/analysis.py` (33 KB)
- Delete: `telemetry_tool/web/routes/visualize.py` (5 KB)
- Delete: `telemetry_tool/web/routes/comparisons.py` (10 KB)
- Delete: `telemetry_tool/web/routes/sessions.py` (7 KB)
- Delete: `telemetry_tool/web/routes/batch.py` (6 KB)
- Delete: `telemetry_tool/web/routes/exports.py` (2 KB)
- Modify: `telemetry_tool/web/app.py` (remove blueprint registrations)

**Step 1: Delete the route files**

Run:
```bash
rm -f telemetry_tool/web/routes/api_v1_data.py
rm -f telemetry_tool/web/routes/api_data.py
rm -f telemetry_tool/web/routes/analysis.py
rm -f telemetry_tool/web/routes/visualize.py
rm -f telemetry_tool/web/routes/comparisons.py
rm -f telemetry_tool/web/routes/sessions.py
rm -f telemetry_tool/web/routes/batch.py
rm -f telemetry_tool/web/routes/exports.py
```

**Step 2: Update `app.py` to remove blueprint registrations**

In `telemetry_tool/web/app.py`, find the `_BLUEPRINTS` list (around line 222) and remove entries for deleted routes. Also remove the conditional `api_v1_data` registration (around line 310) and `batch` registration (around line 302).

Keep all other blueprint registrations intact (auth, billing, workspaces, teams, health, ingest, drivers, tracks, karts, dashboard, etc.).

**Step 3: Verify Flask app starts**

Run:
```bash
python telemetry_tool/main.py --serve
```

Expected: App starts without import errors. Some routes will 404 — that's expected.

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove broken Flask API data routes and blueprint registrations"
```

---

### Task 0.5: Remove Broken Tests for Deleted Routes

**Files:**
- Delete: `telemetry_tool/tests/test_api_v1_data.py` (59 KB)
- Delete: `telemetry_tool/tests/test_api_contracts.py` (25 KB)
- Delete: `telemetry_tool/tests/test_pipeline_tasks.py` (32 KB — Celery tasks)
- Keep: All other test files (they test pipeline logic, auth, models — still needed)

**Step 1: Delete test files for removed routes**

Run:
```bash
rm -f telemetry_tool/tests/test_api_v1_data.py
rm -f telemetry_tool/tests/test_api_contracts.py
rm -f telemetry_tool/tests/test_pipeline_tasks.py
```

**Step 2: Verify remaining tests pass**

Run:
```bash
pytest telemetry_tool/tests/ -x --timeout=60 2>&1 | tail -20
```

Expected: Remaining tests pass. If any fail due to imports from deleted routes, fix those imports.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove tests for deleted API routes"
```

---

### Task 0.6: Phase 0 Checkpoint — Verify Clean State

**Step 1: Verify Flask app starts cleanly**

Run:
```bash
python telemetry_tool/main.py --serve
```

Expected: Starts without errors. Health endpoint works: `curl http://localhost:5000/healthz`

**Step 2: Verify Next.js builds**

Run:
```bash
cd lap-website && npm run build
```

Expected: Build succeeds. All placeholder pages compile.

**Step 3: Verify remaining tests pass**

Run:
```bash
pytest telemetry_tool/tests/ -x --timeout=60
```

Expected: All remaining tests pass.

**Step 4: Commit checkpoint**

```bash
git add -A
git commit -m "checkpoint: phase 0 complete — broken telemetry code removed"
```

---

## Phase 1: Port Old Tool Backend

### Task 1.1: Write Upload Endpoint Tests

**Files:**
- Create: `telemetry_tool/tests/test_upload_sync.py`
- Reference: `telemetry_tool/pipeline.py:475-530` (run_full_analysis signature)
- Reference: `telemetry_tool/web/models.py` (persistence functions)
- Reference: `telemetry_tool/web/routes/ingest.py` (existing upload route)

**Step 1: Write failing test for synchronous upload**

```python
"""Tests for synchronous session upload + processing."""
import io
import json
import pytest
from unittest.mock import patch, MagicMock

from telemetry_tool.web.app import create_app


@pytest.fixture
def app():
    app = create_app({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSyncUpload:
    """Upload CSV -> synchronous processing -> persist -> return session_id."""

    def test_upload_returns_session_id(self, client):
        """POST /api/v1/sessions/upload with CSV returns session_id."""
        csv_content = b"Time (s),Speed (m/s),Lap #\n0,10,1\n1,12,1\n"
        with patch("telemetry_tool.web.routes.sessions_v2.run_full_analysis") as mock_pipeline:
            mock_pipeline.return_value = {
                "session_id": "test-123",
                "score_result": {"total_score": 75, "grade": "B"},
                "steps_ok": 14,
                "steps_failed": 0,
            }
            response = client.post(
                "/api/v1/sessions/upload",
                data={
                    "file": (io.BytesIO(csv_content), "test_session.csv"),
                    "session_type": "practice",
                    "track_state": "dry",
                    "driver_name": "Test Driver",
                },
                content_type="multipart/form-data",
            )
        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert data["data"]["session_id"] == "test-123"

    def test_upload_rejects_missing_file(self, client):
        """POST without file returns 400."""
        response = client.post(
            "/api/v1/sessions/upload",
            data={"session_type": "practice"},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400

    def test_upload_rejects_non_csv(self, client):
        """POST with non-CSV file returns 400."""
        response = client.post(
            "/api/v1/sessions/upload",
            data={
                "file": (io.BytesIO(b"not a csv"), "test.exe"),
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_upload_sync.py -v`
Expected: FAIL with import error (sessions_v2 module doesn't exist yet)

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_upload_sync.py
git commit -m "test: add failing tests for sync upload endpoint"
```

---

### Task 1.2: Implement Synchronous Upload Endpoint

**Files:**
- Create: `telemetry_tool/web/routes/sessions_v2.py`
- Modify: `telemetry_tool/web/app.py` (register new blueprint)
- Reference: `telemetry_tool/pipeline.py:475` (run_full_analysis)
- Reference: `telemetry_tool/web/models.py` (persistence)

**Step 1: Create the new sessions route with sync processing**

Create `telemetry_tool/web/routes/sessions_v2.py`:

```python
"""Session management routes -- v2 (re-port).

Synchronous processing via run_full_analysis(). No Celery.
"""
import logging
import os
import tempfile
import uuid
from pathlib import Path

from flask import Blueprint, g, request

from ..api_utils import api_response, api_error
from ..validation import validate_request

logger = logging.getLogger(__name__)

bp = Blueprint("sessions_v2", __name__, url_prefix="/api/v1")

# Allowed upload extensions
_ALLOWED_EXTENSIONS = {".csv", ".CSV"}
# Max upload size: 200 MB
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix in _ALLOWED_EXTENSIONS


@bp.route("/sessions/upload", methods=["POST"])
def upload_session():
    """Upload CSV -> synchronous processing -> persist -> return session_id.

    Form fields:
        file: CSV file (required)
        session_type: practice|qualifying|race|heat|final|endurance
        track_state: dry|wet|damp|green|rubbered|dusty
        driver_name: Driver name (required)
        lap_range: e.g. "3-15" (optional)
        exclude_laps: e.g. "1,2,16" (optional)
    """
    # Validate file presence
    if "file" not in request.files:
        return api_error("No file provided", 400)

    file = request.files["file"]
    if not file.filename:
        return api_error("No file selected", 400)

    if not _allowed_file(file.filename):
        return api_error("Only CSV files are accepted", 400)

    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    if file_size > _MAX_UPLOAD_BYTES:
        return api_error(f"File too large. Maximum: {_MAX_UPLOAD_BYTES // (1024*1024)}MB", 413)

    # Save to temp file
    tmp_dir = tempfile.mkdtemp(prefix="telemetry_upload_")
    csv_path = os.path.join(tmp_dir, file.filename)
    file.save(csv_path)

    try:
        # Build session metadata from form
        session_meta = _extract_session_meta(request.form, file.filename)

        # Get database connection
        from ..db_helpers import get_db_connection
        conn = get_db_connection()

        # SYNCHRONOUS processing -- identical to local tool
        from telemetry_tool.pipeline import run_full_analysis
        result = run_full_analysis(
            csv_path=csv_path,
            session_meta=session_meta,
            enable_ml=True,
            enable_report=True,
            output_dir=tmp_dir,
        )

        # Persist to database
        from ..models import upsert_session, insert_laps, insert_score_details
        session_id = result.get("session_id") or str(uuid.uuid4())

        # Build session dict for upsert
        score = result.get("score_result", {})
        session_dict = {
            "session_id": session_id,
            "csv_filename": file.filename,
            "session_type": session_meta.get("session_type", "practice"),
            "track_state": session_meta.get("track_state", "dry"),
            "total_score": score.get("total_score"),
            "grade": score.get("grade"),
        }
        upsert_session(conn, session_dict)

        # Insert laps
        lap_metrics = result.get("lap_metrics", [])
        if lap_metrics:
            insert_laps(conn, session_id, lap_metrics)

        # Insert scores
        if score:
            insert_score_details(conn, session_id, score)

        conn.commit()

        return api_response({
            "session_id": session_id,
            "grade": score.get("grade"),
            "total_score": score.get("total_score"),
            "steps_ok": result.get("steps_ok", 0),
            "steps_failed": result.get("steps_failed", 0),
        })

    except Exception as e:
        logger.exception("Upload processing failed: %s", e)
        return api_error(f"Processing failed: {str(e)}", 500)
    finally:
        # Cleanup temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _extract_session_meta(form, filename: str) -> dict:
    """Extract session metadata from form fields."""
    meta = {
        "csv_filename": filename,
        "session_type": form.get("session_type", "practice"),
        "track_state": form.get("track_state", "dry"),
        "drivers": [],
    }

    driver_name = form.get("driver_name", "Unknown")
    lap_range_str = form.get("lap_range", "")
    exclude_str = form.get("exclude_laps", "")

    driver = {"name": driver_name}

    if lap_range_str:
        parts = lap_range_str.split("-")
        if len(parts) == 2:
            try:
                driver["lap_range"] = (int(parts[0]), int(parts[1]))
            except ValueError:
                pass

    if exclude_str:
        try:
            driver["exclude"] = [int(x.strip()) for x in exclude_str.split(",") if x.strip()]
        except ValueError:
            pass

    meta["drivers"] = [driver]
    return meta
```

**Step 2: Register blueprint in app.py**

In `telemetry_tool/web/app.py`, add to the `_BLUEPRINTS` list:
```python
('.routes.sessions_v2', 'bp', 'sessions_v2_bp'),
```

**Step 3: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_upload_sync.py -v`
Expected: All 3 tests pass.

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/sessions_v2.py telemetry_tool/web/app.py
git commit -m "feat: add synchronous upload endpoint (sessions_v2)"
```

---

### Task 1.3: Write Data API Endpoint Tests

**Files:**
- Create: `telemetry_tool/tests/test_data_api_v2.py`
- Reference: `telemetry_tool/web/models.py` (query functions)

**Step 1: Write failing tests for core data endpoints**

```python
"""Tests for re-ported data API endpoints."""
import json
import pytest
from unittest.mock import patch

from telemetry_tool.web.app import create_app


@pytest.fixture
def app():
    app = create_app({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSessionList:
    def test_list_sessions(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_sessions") as mock:
            mock.return_value = [
                {"session_id": "s1", "csv_filename": "test.csv", "grade": "A"},
            ]
            resp = client.get("/api/v1/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert len(data["data"]["sessions"]) == 1


class TestSessionDetail:
    def test_get_session(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_session_by_id") as mock:
            mock.return_value = {
                "session_id": "s1",
                "csv_filename": "test.csv",
                "grade": "B",
                "total_score": 78,
            }
            resp = client.get("/api/v1/sessions/s1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["session_id"] == "s1"

    def test_get_session_404(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_session_by_id") as mock:
            mock.return_value = None
            resp = client.get("/api/v1/sessions/nonexistent")
        assert resp.status_code == 404


class TestSpeedTrace:
    def test_speed_trace_returns_distance_speed_arrays(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_gps_trace") as mock:
            mock.return_value = {
                "distances_json": "[0,10,20,30]",
                "speeds_json": "[5.0,8.0,12.0,10.0]",
            }
            resp = client.get("/api/v1/sessions/s1/speed-trace?lap=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "distances" in data["data"]
        assert "speeds" in data["data"]
        assert len(data["data"]["distances"]) == 4


class TestGpsTrace:
    def test_gps_trace_returns_coords(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_gps_trace") as mock:
            mock.return_value = {
                "latitudes_json": "[45.0,45.1]",
                "longitudes_json": "[9.0,9.1]",
                "distances_json": "[0,100]",
                "speeds_json": "[10,15]",
            }
            resp = client.get("/api/v1/sessions/s1/gps-trace?lap=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "lat" in data["data"]
        assert "lon" in data["data"]


class TestGGData:
    def test_gg_data_returns_accel(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_gps_trace") as mock:
            mock.return_value = {
                "accel_lat_json": "[0.5,-0.3]",
                "accel_long_json": "[0.2,-0.8]",
            }
            resp = client.get("/api/v1/sessions/s1/gg-data?lap=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "lat_g" in data["data"]
        assert "lon_g" in data["data"]


class TestLapTimes:
    def test_lap_times(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_laps_for_session") as mock:
            mock.return_value = [
                {"lap_number": 1, "lap_time_s": 65.3},
                {"lap_number": 2, "lap_time_s": 64.1},
            ]
            resp = client.get("/api/v1/sessions/s1/laps")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["laps"]) == 2


class TestScoreDetails:
    def test_score_details(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_score_details") as mock:
            mock.return_value = {
                "total_score": 82,
                "grade": "A",
                "pace_score": 22,
                "consistency_score": 20,
                "execution_score": 18,
                "robustness_score": 12,
                "adaptation_score": 10,
            }
            resp = client.get("/api/v1/sessions/s1/scores")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["total_score"] == 82


class TestCornerData:
    def test_corner_coaching(self, client):
        with patch("telemetry_tool.web.routes.data_v2.get_corner_coaching") as mock:
            mock.return_value = [
                {"corner_id": 1, "coaching_text": "Brake 5m later"},
            ]
            resp = client.get("/api/v1/sessions/s1/corners")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["data"]["corners"]) == 1


class TestDeleteSession:
    def test_delete_session(self, client):
        with patch("telemetry_tool.web.routes.data_v2.delete_session") as mock:
            mock.return_value = True
            resp = client.delete("/api/v1/sessions/s1")
        assert resp.status_code == 200
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -v`
Expected: FAIL with import error (data_v2 doesn't exist)

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_data_api_v2.py
git commit -m "test: add failing tests for re-ported data API endpoints"
```

---

### Task 1.4: Implement Data API Endpoints

**Files:**
- Create: `telemetry_tool/web/routes/data_v2.py`
- Modify: `telemetry_tool/web/app.py` (register blueprint)
- Reference: `telemetry_tool/web/models.py` (all query functions)

**Step 1: Create data_v2.py with all core endpoints**

Create `telemetry_tool/web/routes/data_v2.py` with these endpoints:

- `GET /api/v1/sessions` - List sessions (via `get_sessions()`)
- `GET /api/v1/sessions/<id>` - Session detail (via `get_session_by_id()`)
- `DELETE /api/v1/sessions/<id>` - Delete session
- `GET /api/v1/sessions/<id>/laps` - Lap list (via `get_laps_for_session()`)
- `GET /api/v1/sessions/<id>/speed-trace?lap=N` - Speed vs distance (via `get_gps_trace()`, return `distances` + `speeds`)
- `GET /api/v1/sessions/<id>/gps-trace?lap=N` - GPS coords (via `get_gps_trace()`, return `lat` + `lon` + `distances` + `speeds`)
- `GET /api/v1/sessions/<id>/gg-data?lap=N` - GG data (via `get_gps_trace()`, return `lat_g` + `lon_g`)
- `GET /api/v1/sessions/<id>/scores` - Score breakdown (via `get_score_details()`)
- `GET /api/v1/sessions/<id>/corners` - Corner coaching (via `get_corner_coaching()`)
- `GET /api/v1/sessions/<id>/conditions` - Condition phases (via `get_condition_phases()`)
- `GET /api/v1/sessions/<id>/laps/gps` - Lap numbers with GPS data

All endpoints use `api_response()` / `api_error()` from `api_utils.py` for standard envelope responses. All JSON fields stored in DB are parsed via a helper `_parse_json()` function.

For best-lap detection when no `?lap=` param: find first lap with `is_best=True`, fallback to first lap with valid data.

**Step 2: Register blueprint in app.py**

Add to `_BLUEPRINTS` list in `telemetry_tool/web/app.py`:
```python
('.routes.data_v2', 'bp', 'data_v2_bp'),
```

**Step 3: Run tests**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -v`
Expected: All tests pass.

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/web/app.py
git commit -m "feat: add re-ported data API endpoints (data_v2)"
```

---

### Task 1.5: Add Comparison and Report Download Endpoints

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`

**Step 1: Add comparison endpoint**

Add to `data_v2.py`:
- `GET /api/v1/compare/sessions?a=X&b=Y` - Returns both sessions' data, scores, and laps for side-by-side comparison
- `GET /api/v1/sessions/<id>/report?format=html|pdf` - Generate and download report using `reporting_html.py` / `reporting_pdf.py`

The comparison endpoint fetches both sessions via `get_session_by_id()`, both scores via `get_score_details()`, and both lap lists via `get_laps_for_session()`, returning them in a structured response.

The report endpoint checks for a pre-generated HTML report path on the session, and if found serves it. For PDF, uses `reporting_pdf.generate_pdf_from_html()`.

**Step 2: Run all data API tests**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -v`
Expected: All tests pass.

**Step 3: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat: add comparison and report download endpoints"
```

---

### Task 1.6: Phase 1 Checkpoint -- Backend Verification

**Step 1: Run all backend tests**

Run: `pytest telemetry_tool/tests/ -x --timeout=60`
Expected: All tests pass.

**Step 2: Start Flask and manually test key endpoints**

Run:
```bash
python telemetry_tool/main.py --serve
```

Then in another terminal:
```bash
curl http://localhost:5000/healthz
curl http://localhost:5000/api/v1/sessions
```

Expected: Health returns 200. Sessions returns empty list (no data yet).

**Step 3: Commit checkpoint**

```bash
git add -A
git commit -m "checkpoint: phase 1 complete -- backend re-ported with sync processing"
```

---

## Phase 2: Port Old Tool Frontend

### Task 2.1: Copy Old Tool JS Modules to Frontend

**Files:**
- Create: `lap-website/public/js/` directory
- Copy: Core vanilla JS chart modules from `telemetry_tool/web/static/js/`

**Step 1: Copy the core chart modules**

```bash
mkdir -p lap-website/public/js

# Core chart modules
cp telemetry_tool/web/static/js/speed_trace_zoom.js lap-website/public/js/
cp telemetry_tool/web/static/js/gps_trace.js lap-website/public/js/
cp telemetry_tool/web/static/js/gg_explorer.js lap-website/public/js/
cp telemetry_tool/web/static/js/gg_diagram.js lap-website/public/js/
cp telemetry_tool/web/static/js/track_map.js lap-website/public/js/
cp telemetry_tool/web/static/js/lap_overlay.js lap-website/public/js/
cp telemetry_tool/web/static/js/corner_replay.js lap-website/public/js/
cp telemetry_tool/web/static/js/corner_replay_cockpit.js lap-website/public/js/
cp telemetry_tool/web/static/js/focus_mode.js lap-website/public/js/
cp telemetry_tool/web/static/js/focus_tools.js lap-website/public/js/
cp telemetry_tool/web/static/js/lap_distribution.js lap-website/public/js/
cp telemetry_tool/web/static/js/lap_progress.js lap-website/public/js/
cp telemetry_tool/web/static/js/fingerprint_chart.js lap-website/public/js/
cp telemetry_tool/web/static/js/sector_chart.js lap-website/public/js/
cp telemetry_tool/web/static/js/speed_profile.js lap-website/public/js/
cp telemetry_tool/web/static/js/driving_style.js lap-website/public/js/
```

**Step 2: Commit**

```bash
git add lap-website/public/js/
git commit -m "chore: copy Old Tool vanilla JS chart modules to frontend"
```

---

### Task 2.2: Create Distance-Based Hover Sync Store

**Files:**
- Create: `lap-website/src/lib/chart-hover-store.ts`

**Step 1: Create the store with distance-based (not index-based) synchronization**

```typescript
/**
 * Chart hover synchronization store -- distance-based.
 *
 * All charts communicate hover position using real distance (meters),
 * NOT array indices. This matches the Old Tool's chart_sync.js behavior
 * and avoids misalignment when laps have different data lengths.
 */
import { create } from 'zustand';

interface ChartHoverState {
  /** Current hover distance in meters, or null if not hovering */
  hoverDistance: number | null;
  /** Which chart module triggered the hover */
  hoverSource: string | null;
  /** Set hover from a specific chart */
  setHover: (distance: number, source: string) => void;
  /** Clear hover (mouse left chart area) */
  clearHover: () => void;
}

export const useChartHoverStore = create<ChartHoverState>((set) => ({
  hoverDistance: null,
  hoverSource: null,
  setHover: (distance, source) => set({ hoverDistance: distance, hoverSource: source }),
  clearHover: () => set({ hoverDistance: null, hoverSource: null }),
}));
```

**Step 2: Commit**

```bash
git add lap-website/src/lib/chart-hover-store.ts
git commit -m "feat: add distance-based chart hover sync store"
```

---

### Task 2.3: Create React Wrapper Pattern for Vanilla JS Charts

**Files:**
- Create: `lap-website/src/components/app/charts/SpeedTraceZoom.tsx`
- Create: `lap-website/src/components/app/charts/GpsTrace.tsx`
- Create: `lap-website/src/components/app/charts/GGExplorer.tsx`
- Create: `lap-website/src/components/app/charts/index.ts`

**Step 1: Create React wrappers for each vanilla JS chart module**

Each wrapper follows this pattern:
1. Create a container div with `useRef`
2. Create a canvas element in `useEffect` and append to container
3. Load the vanilla JS module via dynamic script tag
4. Initialize the module with the canvas + config (API base, session ID)
5. Bridge hover events: module calls `onHoverDistance` callback -> Zustand store `setHover()`
6. Bridge external hover: subscribe to Zustand store, call module's `setExternalHover()` or `updateMarkerByDistance()`
7. On cleanup: call module `destroy()`, remove child nodes from container via DOM API, remove script tag

**Important**: Use `while (container.firstChild) container.removeChild(container.firstChild)` for cleanup instead of setting innerHTML, to avoid XSS vectors.

Create wrappers for:
- `SpeedTraceZoom` (wraps `speed_trace_zoom.js`)
- `GpsTrace` (wraps `gps_trace.js`)
- `GGExplorer` (wraps `gg_explorer.js`)

Each component accepts: `sessionId: string`, `apiBase: string`, `className?: string`

Create barrel export `index.ts` re-exporting all three.

**Step 2: Verify build**

Run: `cd lap-website && npm run build`

**Step 3: Commit**

```bash
git add lap-website/src/components/app/charts/
git commit -m "feat: add React wrappers for Old Tool chart modules (SpeedTrace, GPS, GG)"
```

---

### Task 2.4: Rebuild Session Detail Page

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`

**Step 1: Replace placeholder with real session detail page**

The session detail page mirrors the Old Tool's `session_detail.html` with 5 tabs:

1. **Overview** - Score breakdown (bar chart per category), session metadata, best lap info
2. **Visualize** - 3-panel layout: GpsTrace (left, spans 2 rows) + SpeedTraceZoom (top-right) + GGExplorer (bottom-right)
3. **Corners** - Corner coaching text from API
4. **Performance** - Score metrics cards
5. **Lap Data** - Table of all laps (lap number, time, avg speed, max speed, best flag)

Data fetching:
- `GET /api/v1/sessions/{id}` for session metadata
- `GET /api/v1/sessions/{id}/laps` for lap list
- `GET /api/v1/sessions/{id}/scores` for score breakdown
- Chart components fetch their own data internally

Styling: Dark theme matching Old Tool (`#0f1117` bg, `#181b24` cards, `#00d4ff` accent cyan)

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add lap-website/src/app/app/sessions/\[id\]/page.tsx
git commit -m "feat: rebuild session detail page with Old Tool chart wrappers"
```

---

### Task 2.5: Rebuild Visualize Page (Full-Screen Mode)

**Files:**
- Modify: `lap-website/src/app/app/visualize/[id]/page.tsx`

**Step 1: Replace placeholder with full-screen visualization**

This mirrors the Old Tool's `visualize.html`:
- 3-panel layout: GPS map (left, full height), Speed trace (top-right), GG diagram (bottom-right)
- Lap selector sidebar (list of available laps from `/api/v1/sessions/{id}/laps/gps`)
- All charts synced via distance-based hover store
- Full viewport height, minimal chrome

**Step 2: Verify build**

Run: `cd lap-website && npm run build`

**Step 3: Commit**

```bash
git add lap-website/src/app/app/visualize/\[id\]/page.tsx
git commit -m "feat: rebuild full-screen visualize page with synced charts"
```

---

### Task 2.6: Rebuild Compare Sessions Page

**Files:**
- Modify: `lap-website/src/app/app/compare/sessions/page.tsx`

**Step 1: Replace placeholder with comparison page**

Fetches data from `GET /api/v1/compare/sessions?a=X&b=Y`:
- Side-by-side score cards (session A vs session B)
- Lap-by-lap comparison table with delta
- Score category comparison (pace, consistency, execution, robustness)

Session selection: two dropdowns fetching from `GET /api/v1/sessions`

**Step 2: Verify build**

Run: `cd lap-website && npm run build`

**Step 3: Commit**

```bash
git add lap-website/src/app/app/compare/sessions/page.tsx
git commit -m "feat: rebuild session comparison page"
```

---

### Task 2.7: Phase 2 Checkpoint -- Frontend Verification

**Step 1: Build frontend**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no errors.

**Step 2: Lint**

Run: `cd lap-website && npm run lint`
Expected: No lint errors.

**Step 3: Commit checkpoint**

```bash
git add -A
git commit -m "checkpoint: phase 2 complete -- frontend re-ported with Old Tool chart wrappers"
```

---

## Phase 3: Adapt Vanilla JS Modules for React Integration

### Task 3.1: Audit Vanilla JS Module APIs

**Files:**
- Read: `lap-website/public/js/speed_trace_zoom.js`
- Read: `lap-website/public/js/gps_trace.js`
- Read: `lap-website/public/js/gg_explorer.js`

**Step 1: Check each module's initialization pattern**

The vanilla JS modules were designed for Flask/Jinja2 templates. They may use patterns like:
- `window.ModuleManager.register(...)` -- needs adaptation
- `document.getElementById(...)` -- needs to target the React-provided canvas
- `fetch('/api/...')` -- needs the API base URL injected
- Global state on `window` -- needs namespacing

**Step 2: Create adapter shims if needed**

If modules expect `window.ModuleManager`, create a minimal shim:

```javascript
// lap-website/public/js/module-shim.js
window.ModuleManager = window.ModuleManager || {
  _modules: {},
  register: function(name, mod) { this._modules[name] = mod; },
  get: function(name) { return this._modules[name]; }
};
```

**Step 3: Document which modules need API base URL injection**

Each module that calls `fetch('/api/...')` needs its fetch calls updated to use a configurable base URL. This is the main adaptation needed.

**Step 4: Commit any shims**

```bash
git add lap-website/public/js/
git commit -m "feat: add module shims for vanilla JS chart adaptation"
```

---

### Task 3.2: Wire Upload Flow in Frontend

**Files:**
- Find or create upload page/component in Next.js

**Step 1: Create or update upload component**

The upload component should:
1. Accept CSV file via drag-and-drop or file picker
2. Collect metadata (session type, track state, driver name) via form fields
3. POST to `/api/v1/sessions/upload` as multipart/form-data
4. Show loading state during synchronous processing (may take minutes)
5. On success: redirect to `/app/sessions/{session_id}`
6. On error: display error message

**Step 2: Commit**

```bash
git add -A
git commit -m "feat: wire upload flow to sync processing endpoint"
```

---

## Phase 4: Validation

### Task 4.1: Pipeline Correctness Test

**Files:**
- Create: `telemetry_tool/tests/test_re_port_correctness.py`

**Step 1: Test that pipeline produces correct output**

Use a known CSV fixture and verify:
- `score_result` is not None
- `steps_ok` > 0
- Running pipeline twice produces identical scores (determinism)

**Step 2: Run tests**

Run: `pytest telemetry_tool/tests/test_re_port_correctness.py -v`

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_re_port_correctness.py
git commit -m "test: add pipeline correctness validation tests"
```

---

### Task 4.2: API Contract Tests

**Files:**
- Modify: `telemetry_tool/tests/test_data_api_v2.py`

**Step 1: Add contract tests verifying response shapes**

Add tests that verify every API endpoint returns the exact shape the frontend chart modules expect:
- Speed trace: `{data: {distances: number[], speeds: number[], lap_number: number}}`
- GPS trace: `{data: {lat: number[], lon: number[], distances: number[], speeds: number[]}}`
- GG data: `{data: {lat_g: number[], lon_g: number[]}}`
- Laps: `{data: {laps: [{lap_number, lap_time_s, ...}]}}`
- Scores: `{data: {total_score, grade, pace_score, consistency_score, execution_score, robustness_score}}`

**Step 2: Run full test suite**

Run: `pytest telemetry_tool/tests/ -x --timeout=120`
Expected: All tests pass.

**Step 3: Commit**

```bash
git add -A
git commit -m "test: add API contract validation tests"
```

---

### Task 4.3: Frontend Build and Lint Validation

**Step 1: Full build**

Run: `cd lap-website && npm run build`

**Step 2: Lint**

Run: `cd lap-website && npm run lint`

**Step 3: Run existing frontend tests**

Run: `cd lap-website && npm run test`

**Step 4: Commit**

```bash
git add -A
git commit -m "checkpoint: phase 4 complete -- all validation tests pass"
```

---

## Phase 5: Cleanup

### Task 5.1: Remove Dead Imports and References

**Files:**
- Scan: `telemetry_tool/web/app.py` for stale blueprint references
- Scan: `lap-website/src/` for stale imports

**Step 1: Remove any remaining references to deleted routes**

Grep for imports of deleted modules and remove them.

**Step 2: Remove unused npm packages**

Check `package.json` for chart libraries that are no longer imported.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove dead imports and unused dependencies"
```

---

### Task 5.2: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update architecture section**

Update the CLAUDE.md to reflect:
- Synchronous processing (no Celery for telemetry analysis)
- New route files (`sessions_v2.py`, `data_v2.py`)
- Vanilla JS chart modules wrapped in React (`lap-website/public/js/`)
- Distance-based hover sync via Zustand
- Removed route files (`api_v1_data.py`, `api_data.py`, `analysis.py`, etc.)
- Phase ordering and what was done

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for re-ported architecture"
```

---

### Task 5.3: Final Checkpoint

**Step 1: Run all backend tests**

Run: `pytest telemetry_tool/tests/ -x --timeout=120`

**Step 2: Build frontend**

Run: `cd lap-website && npm run lint && npm run test && npm run build`

**Step 3: Start both services and smoke test**

Terminal 1: `python telemetry_tool/main.py --serve`
Terminal 2: `cd lap-website && npm run dev`

Navigate to `http://localhost:3000/app/sessions` -- should render the session list.

**Step 4: Final commit**

```bash
git add -A
git commit -m "checkpoint: re-port complete -- all phases validated"
```

---

## Summary

| Phase | Tasks | Purpose |
|-------|-------|---------|
| **0** | 0.1-0.6 | Gut broken telemetry code |
| **1** | 1.1-1.6 | Port Old Tool backend (sync processing + data API) |
| **2** | 2.1-2.7 | Port Old Tool frontend (vanilla JS in React wrappers) |
| **3** | 3.1-3.2 | Adapt vanilla JS modules + wire upload |
| **4** | 4.1-4.3 | Validation (pipeline correctness + API contracts + build) |
| **5** | 5.1-5.3 | Cleanup (dead code, docs, final verification) |

**Total tasks**: 22
**Estimated commits**: 22+

**Critical path**: Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 (sequential)

**Parallelizable**: Within Phase 2, chart wrappers (Task 2.3) and pages (Tasks 2.4-2.6) can be built in parallel by subagents.
