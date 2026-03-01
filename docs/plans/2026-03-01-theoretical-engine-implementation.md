# Theoretical Engine Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the existing theoretical lap computation engine into the web API so uploads automatically produce theoretical laps, and schedule weekly training to improve models from accumulated data.

**Architecture:** The upload route dispatches a Celery pipeline chain (`pipeline_ingest → pipeline_analyze → pipeline_finalize`). The finalize stage calls `run_full_analysis()` from `pipeline.py` which runs the 14-stage pipeline including theoretical lap computation (stage 10). A weekly Celery Beat task trains track-specific envelopes and global models from all session data, then reprocesses sessions with improved models.

**Tech Stack:** Python 3.x, Celery 5, Redis (broker), PostgreSQL 16, Flask, kart_envelope QSS solver

---

## Context for the Implementer

### Key Files You Need to Know

| File | Purpose | Current State |
|------|---------|---------------|
| `telemetry_tool/web/routes/api_v1_data.py:636-749` | Upload endpoint (`POST /files/upload`) | Saves CSV to disk, returns filename. **Does NOT trigger pipeline.** |
| `telemetry_tool/tasks/pipeline_tasks.py` | Celery tasks: `pipeline_ingest`, `pipeline_analyze`, `pipeline_finalize` | Tasks exist. `build_pipeline_chain()` builds the chain. **But stage runners on lines 182-203 are PLACEHOLDERS** — they log stage names without calling real pipeline code. |
| `telemetry_tool/pipeline.py:475` | `run_full_analysis(csv_path, session_meta)` | The real 14-stage pipeline. **Works end-to-end.** Returns a dict with `theoretical_lap`, `theoretical_metrics`, `score_result`, etc. |
| `telemetry_tool/pipeline_context.py` | `PipelineContext` — Redis-backed job state | Stores job_id, workspace_id, session_id, file_path. Intermediate DataFrames saved as Parquet. |
| `telemetry_tool/celery_app.py` | Celery app factory with Beat schedule | Beat schedule has 10 periodic tasks. **No training task.** |
| `kart_envelope/run_training.py` | Train CapabilityEnvelopes per (track, kart) | CLI script. Groups sessions, calls `train_library()`. |
| `kart_envelope/monthly_retrain.py` | Three-tier monthly retraining wave | CLI script. Calls `train_and_package_three_tier_bundles()`. |
| `telemetry_tool/db/queries.py:525` | `INSERT_THEORETICAL_DATA` query | Inserts into `theoretical_data` table. |
| `telemetry_tool/web/models.py:1252` | `get_theoretical_data()` | Reads from `theoretical_data` table for the API response. |

### Critical Insight

The pipeline tasks in `pipeline_tasks.py` lines 182-203 are **stubs**:

```python
def _run_finalize_stages(ctx: PipelineContext) -> None:
    """Placeholder: run finalize stages 9-15, updating context progress."""
    for i, stage in enumerate(_FINALIZE_STAGES):
        ctx.update_stage(stage, "running")
        logger.info("Job %s: stage %s", ctx.job_id, stage)
        ctx.update_stage(stage, "completed")
```

They iterate stage names but **never call `pipeline.run_full_analysis()`**. This is the root cause of "no theoretical data" — the engine exists but is never invoked.

---

### Task 1: Wire Stage Runners to Real Pipeline

**Files:**
- Modify: `telemetry_tool/tasks/pipeline_tasks.py:170-204`
- Read: `telemetry_tool/pipeline.py:475-530` (for `run_full_analysis()` signature)
- Test: `telemetry_tool/tests/test_pipeline_tasks.py` (new)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_pipeline_tasks.py`:

```python
"""Tests for pipeline task stage runners."""
import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_redis():
    """In-memory Redis mock that stores/retrieves PipelineContext."""
    store = {}

    class FakeRedis:
        def get(self, key):
            return store.get(key)

        def set(self, key, value, ex=None):
            store[key] = value

        def delete(self, key):
            store.pop(key, None)

    return FakeRedis()


@pytest.fixture
def pipeline_context(mock_redis):
    """Create a PipelineContext for testing."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline_context import PipelineContext

    return PipelineContext.create(
        mock_redis, "test-job-1", "ws-1", "sess-1", "/data/test.csv",
        temp_root="/tmp",
    )


def test_run_finalize_calls_real_pipeline(pipeline_context):
    """_run_finalize_stages must call run_full_analysis, not just log."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    with patch("tasks.pipeline_tasks.run_full_analysis") as mock_run:
        mock_run.return_value = {
            "theoretical_lap": None,
            "theoretical_metrics": None,
            "score_result": None,
            "steps_ok": ["gps_filter"],
            "steps_failed": [],
            "errors": {},
        }
        from tasks.pipeline_tasks import _run_finalize_stages
        _run_finalize_stages(pipeline_context)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert str(call_args[0][0]).endswith("test.csv")


def test_run_finalize_stores_theoretical_data(pipeline_context):
    """When run_full_analysis returns theoretical data, it must be stored in DB."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    mock_result = {
        "theoretical_lap": {"distance_m": [0, 100], "v_env_mps": [20, 25]},
        "theoretical_metrics": {
            "best_s": 62.5,
            "simulation_method": "kart_envelope_qss",
        },
        "score_result": {"total": 75.0, "grade": "B"},
        "lap_times": {"1": 65.0, "2": 63.0},
        "steps_ok": ["theoretical_lap"],
        "steps_failed": [],
        "errors": {},
    }

    with patch("tasks.pipeline_tasks.run_full_analysis", return_value=mock_result), \
         patch("tasks.pipeline_tasks._store_theoretical_data") as mock_store:
        from tasks.pipeline_tasks import _run_finalize_stages
        _run_finalize_stages(pipeline_context)
        mock_store.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_tasks.py -v`
Expected: FAIL — `_run_finalize_stages` doesn't call `run_full_analysis`

**Step 3: Implement the real stage runners**

In `telemetry_tool/tasks/pipeline_tasks.py`, replace lines 170-204:

```python
# ---------------------------------------------------------------------------
# Stage runners — call the real pipeline
# ---------------------------------------------------------------------------

from pipeline import run_full_analysis


def _build_session_meta(ctx: PipelineContext) -> dict:
    """Build session_meta dict from PipelineContext for run_full_analysis."""
    return {
        "session_id": ctx.session_id,
        "session_type": "practice",
        "track_state": "dry",
    }


def _store_theoretical_data(
    session_id: str, result: dict, conn=None
) -> None:
    """Persist theoretical lap results to the theoretical_data table."""
    import json as _json

    theo_metrics = result.get("theoretical_metrics")
    if theo_metrics is None:
        return

    if conn is None:
        conn = _get_pg_connection()

    theo_lap = result.get("theoretical_lap")
    lap_times = result.get("lap_times", {})
    best_actual = min(lap_times.values()) if lap_times else None

    theo_time = theo_metrics.get("best_s")
    gap_pct = None
    if theo_time and best_actual and theo_time > 0:
        gap_pct = round((best_actual - theo_time) / theo_time * 100, 2)

    speeds_json = None
    distances_json = None
    if theo_lap is not None:
        speeds_json = _json.dumps(
            theo_lap.get("v_env_mps", theo_lap.get("speeds", []))
        )
        distances_json = _json.dumps(
            theo_lap.get("distance_m", theo_lap.get("distances", []))
        )

    # Upsert: insert or update if session already has theoretical data
    conn.execute(
        text(
            "INSERT INTO theoretical_data "
            "(session_id, theoretical_time_s, actual_best_time_s, gap_pct, "
            " simulation_method, speed_profile_json, distance_json, metrics_json, "
            " corner_coaching_json, delta_map_json, session_scalars_json) "
            "VALUES (:sid, :theo_time, :actual, :gap, :method, :speeds, :dists, "
            "        :metrics, :coaching, :delta, :scalars) "
            "ON CONFLICT (session_id) DO UPDATE SET "
            " theoretical_time_s = EXCLUDED.theoretical_time_s, "
            " actual_best_time_s = EXCLUDED.actual_best_time_s, "
            " gap_pct = EXCLUDED.gap_pct, "
            " simulation_method = EXCLUDED.simulation_method, "
            " speed_profile_json = EXCLUDED.speed_profile_json, "
            " distance_json = EXCLUDED.distance_json, "
            " metrics_json = EXCLUDED.metrics_json, "
            " corner_coaching_json = EXCLUDED.corner_coaching_json, "
            " delta_map_json = EXCLUDED.delta_map_json, "
            " session_scalars_json = EXCLUDED.session_scalars_json"
        ),
        {
            "sid": session_id,
            "theo_time": theo_time,
            "actual": best_actual,
            "gap": gap_pct,
            "method": theo_metrics.get("simulation_method", "unknown"),
            "speeds": speeds_json,
            "dists": distances_json,
            "metrics": _json.dumps(theo_metrics),
            "coaching": _json.dumps(result.get("corner_coaching"))
                if result.get("corner_coaching") else None,
            "delta": _json.dumps(result.get("delta_map_summary"))
                if result.get("delta_map_summary") else None,
            "scalars": _json.dumps(result.get("session_scalars"))
                if result.get("session_scalars") else None,
        },
    )
    conn.commit()


def _run_ingest_stages(ctx: PipelineContext) -> None:
    """Stages 1-4: For now, the upload route handles CSV ingestion.

    The PipelineContext already has the file_path from upload.
    Mark stages as completed so the chain can proceed.
    """
    for stage in _INGEST_STAGES:
        ctx.update_stage(stage, "running")
        ctx.update_stage(stage, "completed")


def _run_analyze_stages(ctx: PipelineContext) -> None:
    """Stages 5-8: Handled as part of run_full_analysis in finalize."""
    for stage in _ANALYZE_STAGES:
        ctx.update_stage(stage, "running")
        ctx.update_stage(stage, "completed")


def _run_finalize_stages(ctx: PipelineContext) -> None:
    """Stages 9-15: Run the full analysis pipeline and store results."""
    ctx.update_stage("pipeline_run", "running")

    session_meta = _build_session_meta(ctx)
    result = run_full_analysis(
        csv_path=ctx.file_path,
        session_meta=session_meta,
        enable_ml=True,
        enable_report=False,  # Reports generated separately
    )

    # Store theoretical data if computed
    if result.get("theoretical_metrics"):
        ctx.update_stage("theoretical_store", "running")
        try:
            _store_theoretical_data(ctx.session_id, result)
        except Exception:
            logger.warning(
                "Failed to store theoretical data for %s",
                ctx.session_id, exc_info=True,
            )

    # Store scores if computed
    score = result.get("score_result")
    if score:
        ctx.update_stage("scoring_store", "running")
        try:
            conn = _get_pg_connection()
            conn.execute(
                text(
                    "UPDATE sessions SET total_score = :score, grade = :grade "
                    "WHERE session_id = :sid"
                ),
                {
                    "score": score.get("total"),
                    "grade": score.get("grade"),
                    "sid": ctx.session_id,
                },
            )
            conn.commit()
        except Exception:
            logger.warning(
                "Failed to store scores for %s",
                ctx.session_id, exc_info=True,
            )

    for stage in _FINALIZE_STAGES:
        ctx.update_stage(stage, "completed")
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_tasks.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/tasks/pipeline_tasks.py telemetry_tool/tests/test_pipeline_tasks.py
git commit -m "feat(pipeline): wire stage runners to real analysis pipeline"
```

---

### Task 2: Trigger Pipeline Chain After Upload

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py:636-749`
- Read: `telemetry_tool/tasks/pipeline_tasks.py:438-451` (for `build_pipeline_chain`)
- Read: `telemetry_tool/pipeline_context.py:86-125` (for `PipelineContext.create`)
- Test: `telemetry_tool/tests/test_upload_pipeline.py` (new)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_upload_pipeline.py`:

```python
"""Test that CSV upload triggers the Celery pipeline chain."""
from unittest.mock import MagicMock, patch
import io
import pytest


@pytest.fixture
def app():
    """Minimal Flask app for testing upload."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


def test_upload_dispatches_pipeline_chain(app, tmp_path):
    """After successful upload, the Celery pipeline chain must be dispatched."""
    app.config["DATA_RAW_DIR"] = str(tmp_path)

    with app.test_client() as client, \
         patch("web.routes.api_v1_data.build_pipeline_chain") as mock_chain, \
         patch("web.routes.api_v1_data.PipelineContext") as mock_ctx, \
         patch("web.routes.api_v1_data._get_redis_client") as mock_redis:

        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance
        mock_redis.return_value = MagicMock()

        csv_content = b"Time,Speed,Distance\n0.0,10.5,0\n0.1,11.0,1\n"
        data = {"file": (io.BytesIO(csv_content), "test_session.csv")}

        resp = client.post(
            "/api/v1/files/upload",
            data=data,
            content_type="multipart/form-data",
        )

        # Upload should succeed
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

        # Pipeline chain should have been dispatched
        mock_chain.assert_called_once()
        mock_chain_instance.apply_async.assert_called_once()

        # Response should include job_id for status polling
        assert "job_id" in body["data"]
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_upload_pipeline.py -v`
Expected: FAIL — upload doesn't dispatch chain or return job_id

**Step 3: Add pipeline dispatch to upload endpoint**

In `telemetry_tool/web/routes/api_v1_data.py`, at the **top of the file** add imports:

```python
import uuid
```

Then modify the upload endpoint. After `f.save(str(dest))` (line 742), before the `return`, add:

```python
    # Dispatch Celery pipeline chain for analysis
    job_id = str(uuid.uuid4())
    pipeline_dispatched = False
    try:
        from tasks.pipeline_tasks import build_pipeline_chain
        from pipeline_context import PipelineContext
        import redis as _redis
        from web.config import Config

        redis_client = _redis.Redis.from_url(Config.REDIS_URL)
        workspace_id = str(getattr(g, "workspace_id", "1"))
        session_id = safe_name.rsplit(".", 1)[0]  # filename without .csv

        PipelineContext.create(
            redis_client=redis_client,
            job_id=job_id,
            workspace_id=workspace_id,
            session_id=session_id,
            file_path=str(dest),
        )

        pipeline_chain = build_pipeline_chain(job_id)
        pipeline_chain.apply_async()
        pipeline_dispatched = True
        logger.info("Pipeline chain dispatched: job_id=%s session=%s", job_id, session_id)
    except Exception:
        logger.warning("Failed to dispatch pipeline chain for %s (non-fatal)", safe_name, exc_info=True)
```

Then change the return statement to include `job_id`:

```python
    stat = dest.stat()
    response_data = {
        "filename": safe_name,
        "size_bytes": stat.st_size,
        "size_human": _human_size(stat.st_size),
    }
    if pipeline_dispatched:
        response_data["job_id"] = job_id
        response_data["pipeline_status"] = "dispatched"
    return api_response(response_data)
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_upload_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_data.py telemetry_tool/tests/test_upload_pipeline.py
git commit -m "feat(upload): dispatch Celery pipeline chain after CSV upload"
```

---

### Task 3: Create Weekly Training Celery Task

**Files:**
- Create: `telemetry_tool/tasks/training_tasks.py`
- Test: `telemetry_tool/tests/test_training_tasks.py` (new)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_training_tasks.py`:

```python
"""Tests for the weekly training Celery task."""
from unittest.mock import MagicMock, patch, call
import pytest


def test_weekly_retrain_groups_sessions_by_track(tmp_path):
    """Training task must group sessions by track_id for envelope training."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    mock_conn = MagicMock()
    # Simulate 5 sessions across 2 tracks
    mock_conn.execute.return_value.fetchall.return_value = [
        {"session_id": "s1", "track_id": "monza", "csv_filename": "s1.csv"},
        {"session_id": "s2", "track_id": "monza", "csv_filename": "s2.csv"},
        {"session_id": "s3", "track_id": "monza", "csv_filename": "s3.csv"},
        {"session_id": "s4", "track_id": "spa", "csv_filename": "s4.csv"},
        {"session_id": "s5", "track_id": "spa", "csv_filename": "s5.csv"},
    ]

    with patch("tasks.training_tasks._get_pg_connection", return_value=mock_conn), \
         patch("tasks.training_tasks._train_track_envelopes") as mock_train, \
         patch("tasks.training_tasks._reprocess_sessions"):
        from tasks.training_tasks import _gather_training_groups
        groups = _gather_training_groups(mock_conn)

        # Should have 2 groups (monza=3 sessions, spa=2 sessions)
        assert len(groups) == 2
        assert any(g["track_id"] == "monza" and len(g["sessions"]) == 3 for g in groups)


def test_weekly_retrain_skips_groups_under_3_sessions(tmp_path):
    """Groups with fewer than 3 sessions should be skipped."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {"session_id": "s1", "track_id": "spa", "csv_filename": "s1.csv"},
        {"session_id": "s2", "track_id": "spa", "csv_filename": "s2.csv"},
    ]

    with patch("tasks.training_tasks._get_pg_connection", return_value=mock_conn):
        from tasks.training_tasks import _gather_training_groups
        groups = _gather_training_groups(mock_conn)

        # spa only has 2 sessions → filtered out
        trainable = [g for g in groups if len(g["sessions"]) >= 3]
        assert len(trainable) == 0


def test_reprocess_calls_pipeline_for_each_session():
    """Reprocessing must call run_full_analysis for each session."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    sessions = [
        {"session_id": "s1", "csv_filename": "s1.csv"},
        {"session_id": "s2", "csv_filename": "s2.csv"},
    ]

    with patch("tasks.training_tasks.run_full_analysis") as mock_run, \
         patch("tasks.training_tasks._store_theoretical_data"), \
         patch("tasks.training_tasks._get_pg_connection"):
        mock_run.return_value = {
            "theoretical_metrics": {"best_s": 60},
            "theoretical_lap": None,
            "steps_ok": [], "steps_failed": [], "errors": {},
        }
        from tasks.training_tasks import _reprocess_sessions
        results = _reprocess_sessions(sessions, data_dir="/data/raw")

        assert mock_run.call_count == 2
        assert results["succeeded"] == 2
        assert results["failed"] == 0
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_training_tasks.py -v`
Expected: FAIL — module does not exist

**Step 3: Implement the training task**

Create `telemetry_tool/tasks/training_tasks.py`:

```python
"""Weekly training Celery task — train envelopes, global model, reprocess sessions.

Runs every Sunday at 00:00 UTC via Celery Beat.

Three tiers:
  1. Track-specific CapabilityEnvelopes (per track_id group)
  2. Global model bundle (offline pipeline)
  3. Reprocess all sessions with improved models
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from celery import shared_task
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Minimum sessions per track to train an envelope
_MIN_SESSIONS_PER_GROUP = 3

# Throttle: seconds between reprocess batches
_REPROCESS_PAUSE_S = 5

# Paths (Docker volume mounts)
_DATA_RAW_DIR = Path("/data/uploads")
_MODELS_DIR = Path("/data/models/kart_envelope")
_BUNDLES_DIR = _MODELS_DIR / "bundles"


def _get_pg_connection():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _gather_training_groups(conn) -> list[dict]:
    """Group non-expired sessions by track_id for envelope training."""
    rows = conn.execute(
        text(
            "SELECT session_id, track_id, csv_filename "
            "FROM sessions "
            "WHERE retention_expired IS NOT TRUE "
            "ORDER BY track_id, session_id"
        )
    ).fetchall()

    groups_map: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        track_id = r.get("track_id", "unknown")
        groups_map[track_id].append(r)

    return [
        {"track_id": tid, "sessions": sessions}
        for tid, sessions in groups_map.items()
    ]


def _train_track_envelopes(groups: list[dict]) -> dict:
    """Tier 1: Train a CapabilityEnvelope per track group."""
    results = {"trained": 0, "skipped": 0, "errors": []}

    for group in groups:
        track_id = group["track_id"]
        sessions = group["sessions"]

        if len(sessions) < _MIN_SESSIONS_PER_GROUP:
            results["skipped"] += 1
            logger.info(
                "Skipping track %s: only %d sessions (need %d)",
                track_id, len(sessions), _MIN_SESSIONS_PER_GROUP,
            )
            continue

        try:
            from kart_envelope.envelope.capability import train_capability_envelope

            # Collect telemetry DataFrames for this track
            all_dfs = []
            for sess in sessions:
                csv_path = _DATA_RAW_DIR / sess["csv_filename"]
                if not csv_path.exists():
                    continue
                try:
                    from telemetry_tool.io_racechrono import read_racechrono_csv
                    df = read_racechrono_csv(str(csv_path))
                    if df is not None and len(df) > 0:
                        all_dfs.append(df)
                except Exception:
                    logger.warning("Failed to read %s", csv_path, exc_info=True)

            if len(all_dfs) < _MIN_SESSIONS_PER_GROUP:
                results["skipped"] += 1
                continue

            import pandas as pd
            combined = pd.concat(all_dfs, ignore_index=True)
            envelope = train_capability_envelope(combined)

            # Save envelope
            out_path = _MODELS_DIR / "envelopes" / f"{track_id}.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as fh:
                json.dump(envelope.to_dict(), fh, indent=2)

            results["trained"] += 1
            logger.info("Trained envelope for track %s (%d sessions)", track_id, len(all_dfs))

        except Exception as exc:
            results["errors"].append({"track_id": track_id, "error": str(exc)})
            logger.warning("Failed to train envelope for %s", track_id, exc_info=True)

    return results


def _train_global_model() -> dict:
    """Tier 2: Train global model bundle via offline pipeline."""
    try:
        from kart_envelope.offline.bundle_packager import (
            train_and_package_three_tier_bundles,
        )
        from kart_envelope.config import default_config

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
        return {"status": "ok", "report": report}
    except Exception as exc:
        logger.warning("Global model training failed (non-fatal)", exc_info=True)
        return {"status": "failed", "error": str(exc)}


def _reprocess_sessions(sessions: list[dict], data_dir: str = "/data/uploads") -> dict:
    """Tier 3: Re-run pipeline on each session with updated models."""
    from pipeline import run_full_analysis

    results = {"succeeded": 0, "failed": 0, "errors": []}

    for i, sess in enumerate(sessions):
        session_id = sess["session_id"]
        csv_path = Path(data_dir) / sess["csv_filename"]

        if not csv_path.exists():
            results["failed"] += 1
            results["errors"].append({"session_id": session_id, "error": "CSV not found"})
            continue

        try:
            result = run_full_analysis(
                csv_path=str(csv_path),
                session_meta={"session_id": session_id},
                enable_report=False,
            )

            if result.get("theoretical_metrics"):
                _store_theoretical_data(session_id, result)

            results["succeeded"] += 1
            logger.info("Reprocessed %s (%d/%d)", session_id, i + 1, len(sessions))

        except Exception as exc:
            results["failed"] += 1
            results["errors"].append({"session_id": session_id, "error": str(exc)})
            logger.warning("Reprocess failed for %s", session_id, exc_info=True)

        # Throttle to avoid overloading
        if (i + 1) % 10 == 0:
            time.sleep(_REPROCESS_PAUSE_S)

    return results


def _store_theoretical_data(session_id: str, result: dict) -> None:
    """Persist theoretical results to theoretical_data table (upsert)."""
    # Import from pipeline_tasks to avoid duplication
    from tasks.pipeline_tasks import _store_theoretical_data as _store
    conn = _get_pg_connection()
    _store(session_id, result, conn=conn)


@shared_task(
    name="tasks.training_tasks.weekly_retrain_and_reprocess",
    soft_time_limit=7200,   # 2 hours
    time_limit=9000,        # 2.5 hours hard
    queue="pipeline",
)
def weekly_retrain_and_reprocess() -> dict:
    """Weekly training: envelopes, global model, reprocess all sessions.

    Scheduled via Celery Beat every Sunday at 00:00 UTC.
    """
    start = time.time()
    audit = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tiers": {},
    }

    conn = _get_pg_connection()

    # Tier 1: Track-specific envelopes
    logger.info("=== Tier 1: Training track-specific envelopes ===")
    groups = _gather_training_groups(conn)
    tier1 = _train_track_envelopes(groups)
    audit["tiers"]["envelopes"] = tier1

    # Tier 2: Global model bundle
    logger.info("=== Tier 2: Training global model bundle ===")
    tier2 = _train_global_model()
    audit["tiers"]["global_model"] = tier2

    # Tier 3: Reprocess all sessions
    logger.info("=== Tier 3: Reprocessing all sessions ===")
    all_sessions = []
    for group in groups:
        all_sessions.extend(group["sessions"])
    tier3 = _reprocess_sessions(all_sessions, data_dir=str(_DATA_RAW_DIR))
    audit["tiers"]["reprocess"] = tier3

    elapsed = round(time.time() - start, 1)
    audit["elapsed_s"] = elapsed
    audit["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Save audit manifest
    manifest_path = _MODELS_DIR / f"training_audit_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(manifest_path, "w") as fh:
            json.dump(audit, fh, indent=2)
    except Exception:
        logger.warning("Failed to write audit manifest", exc_info=True)

    logger.info(
        "Weekly retrain complete in %.1fs: envelopes=%d, reprocessed=%d/%d",
        elapsed, tier1["trained"],
        tier3["succeeded"], tier3["succeeded"] + tier3["failed"],
    )
    return audit
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_training_tasks.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/tasks/training_tasks.py telemetry_tool/tests/test_training_tasks.py
git commit -m "feat(training): add weekly retrain Celery task with 3-tier training"
```

---

### Task 4: Add Training Task to Celery Beat Schedule

**Files:**
- Modify: `telemetry_tool/celery_app.py:44,69-120`

**Step 1: Add `tasks.training_tasks` to the `include` list**

In `celery_app.py` line 44, add to the `include` list:

```python
include=[
    "tasks.pipeline_tasks",
    "tasks.batch_tasks",
    "tasks.gdpr_tasks",
    "tasks.billing_tasks",
    "tasks.alerting_tasks",
    "tasks.email_tasks",
    "tasks.archival_tasks",
    "tasks.usage_tasks",
    "tasks.retention_tasks",
    "tasks.training_tasks",   # NEW
],
```

**Step 2: Add the Beat schedule entry**

In `celery_app.py`, inside the `beat_schedule` dict (after the last entry around line 119), add:

```python
            "weekly-retrain-and-reprocess": {
                "task": "tasks.training_tasks.weekly_retrain_and_reprocess",
                "schedule": crontab(hour=0, minute=0, day_of_week=0),  # Sunday midnight
                "options": {"queue": "pipeline"},
            },
```

**Step 3: Commit**

```bash
git add telemetry_tool/celery_app.py
git commit -m "feat(celery): add weekly retrain task to Beat schedule (Sunday 00:00)"
```

---

### Task 5: Docker Volume for Models + Verify End-to-End

**Files:**
- Modify: `docker-compose.prod.yml` (add models volume)
- Check: Docker container can import `kart_envelope`

**Step 1: Add models volume to docker-compose.prod.yml**

Check if the `models` volume already exists in docker-compose. If not, add:

```yaml
volumes:
  models_data:

services:
  api:
    volumes:
      - models_data:/data/models
  celery-pipeline:
    volumes:
      - models_data:/data/models
```

**Step 2: Verify kart_envelope is importable in Docker**

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec api python -c 'import kart_envelope; print(\"OK\")'"
```

If this fails, the `kart_envelope` package needs to be included in the Docker image. Check if it's in the Dockerfile or if the directory is mounted.

**Step 3: Deploy and test**

```bash
# SCP updated files
scp telemetry_tool/tasks/pipeline_tasks.py root@46.225.227.24:/opt/lap-api/telemetry_tool/tasks/
scp telemetry_tool/tasks/training_tasks.py root@46.225.227.24:/opt/lap-api/telemetry_tool/tasks/
scp telemetry_tool/celery_app.py root@46.225.227.24:/opt/lap-api/telemetry_tool/
scp telemetry_tool/web/routes/api_v1_data.py root@46.225.227.24:/opt/lap-api/telemetry_tool/web/routes/

# Rebuild
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d"

# Upload a test CSV via curl and check if job_id is returned
curl -X POST https://api.lap-coach.racing/api/v1/files/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@test_session.csv"
# Expected: {"ok": true, "data": {"filename": "...", "job_id": "...", "pipeline_status": "dispatched"}}

# Check theoretical data was computed
curl https://api.lap-coach.racing/api/v1/sessions/<session_id>/theoretical \
  -H "Authorization: Bearer <token>"
# Expected: 200 with theoretical_time_s, speeds, distances
```

**Step 4: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat(docker): add models volume for trained envelope storage"
```

---

## Summary

| Task | What | Files Changed | Tests |
|------|------|---------------|-------|
| 1 | Wire stage runners to real pipeline | `pipeline_tasks.py` | `test_pipeline_tasks.py` |
| 2 | Trigger pipeline chain after upload | `api_v1_data.py` | `test_upload_pipeline.py` |
| 3 | Weekly training Celery task | `training_tasks.py` (new) | `test_training_tasks.py` |
| 4 | Beat schedule entry | `celery_app.py` | — |
| 5 | Docker volume + deployment | `docker-compose.prod.yml` | Manual E2E |

Total new code: ~350 lines implementation + ~150 lines tests.
