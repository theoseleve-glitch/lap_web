# Endurance Upload Flow V2 — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-stint endurance processing pipeline that avoids OOM on large files by processing each stint individually, with a dedicated endurance upload form and real-time stint completion progress.

**Architecture:** Quick first-pass reads only lap times from CSV (low memory). User configures stints + assigns drivers. Celery processes each stint's row subset through the full pipeline. Frontend shows stints appearing in a roll-menu as they complete. Driver and team reports computed after all stints done.

**Tech Stack:** Python/Flask, Celery, PostgreSQL, Redis (SSE), Next.js/React/TypeScript.

**Spec:** `docs/superpowers/specs/2026-03-16-endurance-upload-flow-v2.md`

---

## File Structure

### Backend — New Files
- `telemetry_tool/endurance_ingest.py` — Quick lap-time-only reader (no full pipeline)
- `telemetry_tool/web/routes/endurance_upload.py` — Blueprint: detect + process endpoints
- `telemetry_tool/tasks/endurance_tasks.py` — Celery tasks: per-stint pipeline + aggregation

### Backend — Modified Files
- `telemetry_tool/web/app.py` — Register endurance_upload blueprint

### Frontend — New Files
- `lap-website/src/components/app/endurance/StintConfigFlow.tsx` — Lap table + stint assignment
- `lap-website/src/components/app/endurance/StintProcessingProgress.tsx` — Roll-menu progress

### Frontend — Modified Files
- `lap-website/src/app/app/sessions/upload/page.tsx` — Endurance form mode + 2-step flow

---

## Chunk 1: Backend — Quick Lap Detection

### Task 1: Quick Lap Reader

**Files:**
- Create: `telemetry_tool/endurance_ingest.py`

- [ ] **Step 1: Implement quick lap reader**

Reads only lap boundaries from a RaceChrono CSV without loading the full DataFrame. Uses the streaming ingest to read just the `Lap #` and `Time` columns, then computes lap times from elapsed time differences.

```python
# telemetry_tool/endurance_ingest.py
"""Quick lap detection for endurance sessions.

Reads only lap boundaries from a CSV — no full pipeline, no GPS,
no feature engineering. Memory: ~10MB regardless of file size.
"""
from __future__ import annotations

import csv
import logging
import statistics
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def detect_laps_quick(
    csv_path: str | Path,
    pit_threshold_s: float = 120.0,
) -> dict[str, Any]:
    """Fast first-pass: extract lap times and detect pit stops.

    Reads the CSV row-by-row, tracking only the Lap # column and
    elapsed time. Memory usage is O(n_laps), not O(n_rows).

    Returns dict with laps, auto_stints, median_lap_time_s.
    """
    csv_path = Path(csv_path)
    laps: dict[int, dict[str, Any]] = {}
    current_lap: int | None = None
    lap_start_time: float | None = None
    last_time: float = 0.0

    # Find column indices from header
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        # Skip comment rows (RaceChrono puts metadata before header)
        header: list[str] = []
        for row in reader:
            if not row:
                continue
            joined = ",".join(row).lower()
            if "lap" in joined and "time" in joined:
                header = [c.strip() for c in row]
                break

        if not header:
            return {"laps": [], "auto_stints": [], "error": "No header found"}

        # Find relevant columns
        lap_col = _find_col(header, ["lap #", "lap", "lap number"])
        time_col = _find_col(header, ["time (s)", "time(s)", "elapsed (s)", "time"])

        if lap_col is None or time_col is None:
            return {"laps": [], "auto_stints": [], "error": f"Missing columns: lap={lap_col}, time={time_col}"}

        # Stream through rows — only track lap transitions
        for row in reader:
            if len(row) <= max(lap_col, time_col):
                continue
            try:
                lap_num = int(float(row[lap_col]))
                elapsed = float(row[time_col])
            except (ValueError, TypeError):
                continue

            if current_lap is None or lap_num != current_lap:
                # Lap transition
                if current_lap is not None and lap_start_time is not None:
                    lap_time = last_time - lap_start_time
                    if lap_time > 0:
                        laps[current_lap] = {
                            "lap_number": current_lap,
                            "lap_time_s": round(lap_time, 3),
                        }
                current_lap = lap_num
                lap_start_time = elapsed

            last_time = elapsed

        # Final lap
        if current_lap is not None and lap_start_time is not None:
            lap_time = last_time - lap_start_time
            if lap_time > 0:
                laps[current_lap] = {
                    "lap_number": current_lap,
                    "lap_time_s": round(lap_time, 3),
                }

    # Classify laps
    lap_list = sorted(laps.values(), key=lambda l: l["lap_number"])
    valid_times = [l["lap_time_s"] for l in lap_list if l["lap_time_s"] < pit_threshold_s]
    median_time = statistics.median(valid_times) if valid_times else 0

    for lap in lap_list:
        if lap["lap_time_s"] > pit_threshold_s:
            lap["status"] = "pit"
        elif median_time > 0 and lap["lap_time_s"] > median_time * 2:
            lap["status"] = "anomaly"
        else:
            lap["status"] = "valid"

    # Build auto-detected stints
    stints = _build_stints(lap_list)

    return {
        "laps": lap_list,
        "auto_stints": stints,
        "median_lap_time_s": round(median_time, 3),
        "pit_threshold_s": pit_threshold_s,
        "total_laps": len(lap_list),
    }


def _build_stints(laps: list[dict]) -> list[dict]:
    """Group consecutive valid/anomaly laps into stints."""
    stints: list[dict] = []
    current: list[int] = []

    for lap in laps:
        if lap["status"] == "pit":
            if current:
                stints.append({
                    "stint_number": len(stints) + 1,
                    "start_lap": current[0],
                    "end_lap": current[-1],
                    "lap_count": len(current),
                    "pit_lap_number": lap["lap_number"],
                    "pit_lap_time_s": lap["lap_time_s"],
                })
                current = []
        else:
            current.append(lap["lap_number"])

    if current:
        stints.append({
            "stint_number": len(stints) + 1,
            "start_lap": current[0],
            "end_lap": current[-1],
            "lap_count": len(current),
            "pit_lap_number": None,
            "pit_lap_time_s": None,
        })

    return stints


def _find_col(header: list[str], candidates: list[str]) -> int | None:
    """Find column index matching any candidate name (case-insensitive)."""
    lower = [h.lower().strip() for h in header]
    for c in candidates:
        if c.lower() in lower:
            return lower.index(c.lower())
    return None
```

- [ ] **Step 2: Test locally**

```bash
python -c "from endurance_ingest import detect_laps_quick; print(detect_laps_quick('data/raw/MKR_R.csv', 120))"
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/endurance_ingest.py
git commit -m "feat: quick lap detection for endurance — reads only lap column, O(n_laps) memory"
```

---

### Task 2: Endurance Upload Blueprint

**Files:**
- Create: `telemetry_tool/web/routes/endurance_upload.py`
- Modify: `telemetry_tool/web/app.py` — register blueprint

- [ ] **Step 1: Create blueprint with detect endpoint**

```python
# telemetry_tool/web/routes/endurance_upload.py
"""Endurance upload flow — quick detect + per-stint processing."""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

from flask import Blueprint, g, request

from web.api_utils import api_error, api_response, ErrorCode
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)
bp = Blueprint("endurance_upload", __name__, url_prefix="/api/v1/endurance")


@bp.route("/detect", methods=["POST"])
@rate_limit(tier="write")
def detect_stints():
    """Upload CSV + quick detect lap times and pit stops.

    Form fields: file, pit_threshold_s, drivers (JSON array), session metadata.
    Returns lap list + auto-detected stints. File is cached for later processing.
    """
    f = request.files.get("file")
    if not f or not f.filename:
        return api_error(ErrorCode.VALIDATION_ERROR, "No file provided", status=400)

    pit_threshold = float(request.form.get("pit_threshold_s", 120))
    drivers_json = request.form.get("drivers", "[]")
    try:
        drivers = json.loads(drivers_json)
    except (json.JSONDecodeError, TypeError):
        drivers = []

    # Save file to temp location
    job_id = uuid.uuid4().hex[:24]
    upload_dir = Path(f"/data/uploads/endurance_{job_id}")
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f.filename
    f.save(str(file_path))

    # Quick detect
    from endurance_ingest import detect_laps_quick
    result = detect_laps_quick(str(file_path), pit_threshold)

    if result.get("error"):
        return api_error(ErrorCode.VALIDATION_ERROR, result["error"], status=400)

    # Cache metadata in Redis for the process step
    import redis as _redis
    from web.config import Config
    _r = _redis.Redis.from_url(Config.REDIS_URL)
    _r.set(f"endurance:meta:{job_id}", json.dumps({
        "file_path": str(file_path),
        "file_name": f.filename,
        "drivers": drivers,
        "pit_threshold_s": pit_threshold,
        "workspace_id": str(g.workspace_id),
        "session_meta": {
            "session_type": "endurance",
            "track_state": request.form.get("track_state", "dry"),
            "kart_name": request.form.get("kart_name", ""),
            "track_name": request.form.get("track_name", ""),
            "session_date": request.form.get("session_date", ""),
        },
    }), ex=7200)  # 2 hour TTL

    result["job_id"] = job_id
    return api_response(result)


@bp.route("/process", methods=["POST"])
@rate_limit(tier="write")
def process_stints():
    """Start per-stint processing with user-confirmed configuration.

    Body: { job_id, stints: [{ stint_number, start_lap, end_lap, driver_name, condition }] }
    Dispatches Celery tasks per stint.
    """
    body = request.get_json(silent=True) or {}
    job_id = body.get("job_id")
    stint_configs = body.get("stints")

    if not job_id or not stint_configs:
        return api_error(ErrorCode.VALIDATION_ERROR, "job_id and stints required", status=400)

    # Load cached metadata
    import redis as _redis
    from web.config import Config
    _r = _redis.Redis.from_url(Config.REDIS_URL)
    raw = _r.get(f"endurance:meta:{job_id}")
    if not raw:
        return api_error(ErrorCode.NOT_FOUND, "Job expired or not found", status=404)

    meta = json.loads(raw)

    # Dispatch Celery chain
    from tasks.endurance_tasks import process_endurance_session
    process_endurance_session.delay(job_id, meta, stint_configs)

    return api_response({"job_id": job_id, "stints_queued": len(stint_configs)})
```

- [ ] **Step 2: Register blueprint in app.py**

Add to `create_app()`:
```python
from web.routes.endurance_upload import bp as endurance_upload_bp
app.register_blueprint(endurance_upload_bp)
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/web/routes/endurance_upload.py telemetry_tool/web/app.py
git commit -m "feat: endurance upload blueprint — detect + process endpoints"
```

---

## Chunk 2: Backend — Per-Stint Celery Tasks

### Task 3: Endurance Celery Tasks

**Files:**
- Create: `telemetry_tool/tasks/endurance_tasks.py`

- [ ] **Step 1: Implement per-stint processing task**

```python
# telemetry_tool/tasks/endurance_tasks.py
"""Celery tasks for per-stint endurance processing."""
from __future__ import annotations

import json
import logging
from typing import Any

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.endurance_tasks.process_endurance_session",
    queue="pipeline",
    bind=True,
    max_retries=0,
)
def process_endurance_session(
    self,
    job_id: str,
    meta: dict[str, Any],
    stint_configs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Process each stint through the pipeline, then aggregate.

    1. For each stint: extract rows, run pipeline, store results
    2. Compute per-driver reports
    3. Compute team report
    """
    import redis as _redis
    from web.config import Config

    _r = _redis.Redis.from_url(Config.REDIS_URL)

    file_path = meta["file_path"]
    workspace_id = meta["workspace_id"]
    session_meta = meta.get("session_meta", {})
    total_stints = len(stint_configs)

    # Broadcast: starting
    _publish(_r, job_id, {"status": "processing", "total_stints": total_stints})

    stint_results = []

    for i, stint_cfg in enumerate(stint_configs):
        stint_num = stint_cfg["stint_number"]
        start_lap = stint_cfg["start_lap"]
        end_lap = stint_cfg["end_lap"]
        driver_name = stint_cfg.get("driver_name", f"Driver {stint_num}")
        condition = stint_cfg.get("condition", "dry")

        _publish(_r, job_id, {
            "status": "processing_stint",
            "stint_number": stint_num,
            "driver_name": driver_name,
            "progress_pct": round(i / total_stints * 100),
        })

        try:
            result = _process_single_stint(
                file_path=file_path,
                start_lap=start_lap,
                end_lap=end_lap,
                stint_number=stint_num,
                driver_name=driver_name,
                condition=condition,
                session_meta=session_meta,
                workspace_id=workspace_id,
                job_id=job_id,
            )
            stint_results.append(result)

            _publish(_r, job_id, {
                "status": "stint_complete",
                "stint_number": stint_num,
                "driver_name": driver_name,
                "best_lap_s": result.get("best_lap_s"),
                "lap_count": result.get("lap_count"),
                "progress_pct": round((i + 1) / total_stints * 100),
            })
        except Exception as exc:
            logger.exception("Failed to process stint %d", stint_num)
            _publish(_r, job_id, {
                "status": "stint_error",
                "stint_number": stint_num,
                "error": str(exc)[:200],
            })
            stint_results.append({"stint_number": stint_num, "error": str(exc)[:200]})

    # Compute driver + team reports
    _publish(_r, job_id, {"status": "processing_drivers"})

    from endurance_scoring import compute_driver_report, compute_team_report
    from web.repos.endurance_repo import get_stints
    from web.db import get_db_connection

    conn = get_db_connection()

    # Group by driver
    driver_stints: dict[str, list] = {}
    for r in stint_results:
        d = r.get("driver_name", "Unknown")
        if d not in driver_stints:
            driver_stints[d] = []
        driver_stints[d].append(r)

    driver_reports = {}
    for driver, stints in driver_stints.items():
        driver_reports[driver] = compute_driver_report(driver, stints)
        _publish(_r, job_id, {"status": "driver_complete", "driver_name": driver})

    _publish(_r, job_id, {"status": "processing_team"})

    total_laps = sum(r.get("lap_count", 0) for r in stint_results if not r.get("error"))
    total_time = sum(r.get("total_time_s", 0) for r in stint_results if not r.get("error"))
    team_report = compute_team_report(driver_reports, total_laps, total_stints, total_time)

    # Store full report in Redis (TTL 4h) for frontend
    _r.set(f"endurance:report:{job_id}", json.dumps({
        "team": team_report,
        "drivers": driver_reports,
        "stint_results": stint_results,
    }), ex=14400)

    _publish(_r, job_id, {"status": "completed", "job_id": job_id})

    return {"job_id": job_id, "stints_processed": len(stint_results)}


def _process_single_stint(
    file_path: str,
    start_lap: int,
    end_lap: int,
    stint_number: int,
    driver_name: str,
    condition: str,
    session_meta: dict,
    workspace_id: str,
    job_id: str,
) -> dict[str, Any]:
    """Run the pipeline on a single stint's rows.

    Reads only rows belonging to laps [start_lap, end_lap] from the CSV,
    then runs the standard pipeline on this subset.
    """
    import pandas as pd
    from io import StringIO
    from pathlib import Path

    # Read only the stint's rows from CSV
    csv_path = Path(file_path)
    header_lines: list[str] = []
    stint_lines: list[str] = []

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        # Find header
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if "lap" in lower and ("time" in lower or "speed" in lower):
                header_lines.append(line)
                header_cols = [c.strip() for c in stripped.split(",")]
                break
            header_lines.append(line)  # comment/metadata lines

        # Find lap column index
        lap_col_idx = None
        for i, col in enumerate(header_cols):
            if col.lower() in ("lap #", "lap", "lap number"):
                lap_col_idx = i
                break

        if lap_col_idx is None:
            raise ValueError("Cannot find Lap # column")

        # Stream rows, keep only stint's laps
        for line in f:
            parts = line.split(",")
            if len(parts) <= lap_col_idx:
                continue
            try:
                lap_num = int(float(parts[lap_col_idx].strip()))
            except (ValueError, TypeError):
                continue
            if start_lap <= lap_num <= end_lap:
                stint_lines.append(line)

    if not stint_lines:
        return {
            "stint_number": stint_number,
            "driver_name": driver_name,
            "lap_count": 0,
            "error": "No rows found for this stint",
        }

    # Write stint CSV to temp file
    import tempfile
    stint_csv = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", prefix=f"stint{stint_number}_",
        delete=False, dir="/tmp",
    )
    stint_csv.writelines(header_lines)
    stint_csv.writelines(stint_lines)
    stint_csv.close()

    # Run pipeline on stint CSV
    try:
        from pipeline.orchestrator import run_pipeline

        summary = run_pipeline(
            csv_path=stint_csv.name,
            session_meta={
                **session_meta,
                "driver_name": driver_name,
                "session_type": "endurance_stint",
                "track_state": condition,
            },
        )

        # Extract results
        score = summary.get("score_result") or {}
        subs = score.get("sub_scores", {})
        lap_metrics = summary.get("lap_metrics") or []
        valid_times = [
            lm["lap_time_s"] for lm in lap_metrics
            if lm.get("lap_time_s") and lm["lap_time_s"] > 0
        ]

        return {
            "stint_number": stint_number,
            "driver_name": driver_name,
            "condition": condition,
            "start_lap": start_lap,
            "end_lap": end_lap,
            "lap_count": len(valid_times),
            "best_lap_s": round(min(valid_times), 3) if valid_times else None,
            "mean_lap_s": round(sum(valid_times) / len(valid_times), 3) if valid_times else None,
            "total_time_s": round(sum(valid_times), 3) if valid_times else 0,
            "scores": {
                "pace": round(subs.get("pace", {}).get("score", 0), 1),
                "consistency": round(subs.get("consistency", {}).get("score", 0), 1),
                "robustness": round(subs.get("robustness", {}).get("score", 0), 1),
            },
            "session_id": summary.get("db_session_id"),
        }
    finally:
        import os
        os.unlink(stint_csv.name)


def _publish(redis_client, job_id: str, data: dict) -> None:
    """Publish SSE event for endurance job progress."""
    redis_client.publish(f"endurance:{job_id}", json.dumps(data))
    # Also store latest status for polling fallback
    redis_client.set(f"endurance:status:{job_id}", json.dumps(data), ex=7200)
```

- [ ] **Step 2: Commit**

```bash
git add telemetry_tool/tasks/endurance_tasks.py
git commit -m "feat: endurance Celery tasks — per-stint pipeline + aggregation"
```

---

### Task 4: SSE Stream for Endurance Progress

**Files:**
- Modify: `telemetry_tool/web/routes/endurance_upload.py` — add stream + status endpoints

- [ ] **Step 1: Add stream and status endpoints**

Add to `endurance_upload.py`:

```python
@bp.route("/status/<job_id>", methods=["GET"])
def endurance_status(job_id: str):
    """Poll endpoint for endurance job status."""
    import redis as _redis
    from web.config import Config
    _r = _redis.Redis.from_url(Config.REDIS_URL)
    raw = _r.get(f"endurance:status:{job_id}")
    if not raw:
        return api_error(ErrorCode.NOT_FOUND, "Job not found", status=404)
    return api_response(json.loads(raw))


@bp.route("/report/<job_id>", methods=["GET"])
def endurance_report(job_id: str):
    """Get the full endurance report after processing."""
    import redis as _redis
    from web.config import Config
    _r = _redis.Redis.from_url(Config.REDIS_URL)
    raw = _r.get(f"endurance:report:{job_id}")
    if not raw:
        return api_error(ErrorCode.NOT_FOUND, "Report not ready or expired", status=404)
    return api_response(json.loads(raw))
```

- [ ] **Step 2: Commit**

```bash
git add telemetry_tool/web/routes/endurance_upload.py
git commit -m "feat: endurance status + report polling endpoints"
```

---

## Chunk 3: Frontend — Endurance Upload Form + Stint Config

### Task 5: Endurance Upload Form Mode

**Files:**
- Modify: `lap-website/src/app/app/sessions/upload/page.tsx`

- [ ] **Step 1: Transform upload form when endurance selected**

When `sessionType === 'endurance'`:
- Hide "Driver Name" input
- Show "Endurance Drivers" section (already exists from previous commit)
- Show "Pit Stop Threshold" input
- Replace "Upload & Analyze" with "Upload & Detect Stints"
- On submit: POST to `/api/v1/endurance/detect` instead of normal upload
- On success: transition to StintConfigFlow

- [ ] **Step 2: Build and test**
- [ ] **Step 3: Commit**

---

### Task 6: Stint Configuration Flow

**Files:**
- Create: `lap-website/src/components/app/endurance/StintConfigFlow.tsx`

- [ ] **Step 1: Build the stint config component**

Receives detected laps + stints from detect endpoint. Shows:
- Lap table with status column (valid/pit/anomaly)
- User can override each lap: valid (assign stint), pit, or ignore
- Stint summary below with driver + condition dropdowns per stint
- "Process Stints" button → POST `/api/v1/endurance/process`

- [ ] **Step 2: Commit**

---

### Task 7: Stint Processing Progress

**Files:**
- Create: `lap-website/src/components/app/endurance/StintProcessingProgress.tsx`

- [ ] **Step 1: Build the progress roll-menu**

Polls `/api/v1/endurance/status/{jobId}` every 2s. Renders:
```
[✓] Stint 1 — Théo — 8 laps — 52.1s best     [View →]
[✓] Stint 2 — William — 7 laps — 53.2s best   [View →]
[⟳] Stint 3 — Théo — processing...
[ ] Stint 4 — William — queued
```

Completed stints are clickable → navigates to session detail page for that stint's session_id.

After all stints complete → shows driver reports → team report → link to full Endurance tab.

- [ ] **Step 2: Wire into upload page**

After StintConfigFlow submits, transition to StintProcessingProgress.

- [ ] **Step 3: Build, deploy, commit**

```bash
npm run build && npm run cf:deploy
git add lap-website/src/
git commit -m "feat: endurance upload flow — form mode, stint config, processing progress"
```

---

## Chunk 4: Deploy + Integration Test

### Task 8: Deploy Everything

- [ ] **Step 1: Deploy backend**

```bash
scp endurance_ingest.py endurance_upload.py endurance_tasks.py → VPS
docker compose build api celery-pipeline && up -d
```

- [ ] **Step 2: Deploy frontend**

```bash
npm run build && npm run cf:deploy
```

- [ ] **Step 3: Integration test**

1. Go to Upload → select Endurance session type
2. Add 2 drivers (Théo, William)
3. Set pit threshold = 120s
4. Upload 650MB endurance CSV
5. Quick detect returns laps + stints (fast, <5s)
6. Assign drivers to stints, set conditions
7. Click "Process Stints"
8. Watch roll-menu: stints complete one by one
9. Click completed stint → view stint report
10. After all done → view driver + team reports

- [ ] **Step 4: Final commit**

```bash
git commit -m "feat: endurance upload V2 — per-stint processing, no OOM"
```

---

## Deployment Checklist

- [ ] Register endurance_upload blueprint in app.py
- [ ] Ensure Celery pipeline worker picks up endurance_tasks
- [ ] Create /data/uploads directory on VPS (for endurance temp files)
- [ ] Test with 650MB CSV — verify no OOM, stints process individually
- [ ] Verify existing non-endurance uploads still work normally
