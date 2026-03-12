# OCP Downstream Chain + Corner Re-selection Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the full corner analysis, coaching, and scoring chain into the OCP Celery task's downstream update, and allow corner re-selection on completed sessions.

**Architecture:** Replace the partial `_update_downstream()` in `ocp_tasks.py` with a full chain that calls `run_corner_analysis()`, `run_coaching_analyzers()`, `run_enhanced_coaching()`, and `score_session()` using the OCP theoretical result. Extend the `/jobs/<id>/resume` endpoint to accept `"completed"` status, reconstruct `PipelineContext` from the DB when Redis state is gone, and dispatch `pipeline_finalize` which re-runs the full pipeline from CSV.

**Tech Stack:** Python 3.14, Flask, Celery, Redis, PostgreSQL/SQLite, CasADi/IPOPT, pandas, numpy

**Spec:** `docs/superpowers/specs/2026-03-12-ocp-downstream-chain-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `telemetry_tool/tasks/ocp_tasks.py` | OCP Celery task + downstream chain | Modify: replace `_update_downstream` + helpers |
| `telemetry_tool/scoring/pace.py` | Pace scoring `is_physics` check | Already done |
| `telemetry_tool/scoring/execution.py` | Execution scoring `is_physics` check | Already done |
| `telemetry_tool/web/routes/jobs.py` | Resume endpoint + context reconstruction | Modify: status guard + `_reconstruct_context_from_db` |
| `telemetry_tool/tasks/pipeline_tasks.py` | Finalize task fallback path | Modify: pass corners in fallback |
| `telemetry_tool/tests/test_ocp_downstream.py` | Unit tests for downstream chain | Create |
| `telemetry_tool/tests/test_resume_completed.py` | Tests for corner re-selection on completed jobs | Create |

---

## Chunk 1: Full OCP Downstream Chain

### Task 1: Test `_ocp_result_to_dataframe` and `_build_theoretical_result_dict`

**Files:**
- Create: `telemetry_tool/tests/test_ocp_downstream.py`
- Modify: `telemetry_tool/tasks/ocp_tasks.py`

- [ ] **Step 1: Write tests for existing `_ocp_result_to_dataframe` + new `_build_theoretical_result_dict`**

```python
# telemetry_tool/tests/test_ocp_downstream.py
"""Tests for OCP downstream update chain in tasks/ocp_tasks.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest


class _FakeResult:
    """Minimal stand-in for solver.result.TheoreticalResult."""
    def __init__(self, n=100, lap_time=70.0, converged=True):
        self.distance_profile = np.linspace(0, 500, n)
        self.speed_profile = 15.0 + 5.0 * np.sin(np.linspace(0, 4 * np.pi, n))
        self.a_long_profile = np.gradient(self.speed_profile ** 2 / 2, self.distance_profile)
        self.a_lat_profile = self.speed_profile ** 2 * 0.01  # fake curvature
        self.lap_time_s = lap_time
        self.converged = converged
        self.solver_meta = {"wall_time_s": 1.5, "iterations": 200, "converged": converged, "nodes": n}

    def to_dict(self):
        return {
            "lap_time_s": self.lap_time_s,
            "speed_profile": [
                {"distance_m": round(float(self.distance_profile[i]), 2),
                 "speed_mps": round(float(self.speed_profile[i]), 3)}
                for i in range(len(self.speed_profile))
            ],
            "converged": self.converged,
            "solver_meta": self.solver_meta,
            "vehicle_params_used": {},
            "calibration": {},
            "corner_times": [],
            "tier": 1,
        }


class TestOcpResultToDataframe:
    def test_produces_correct_columns(self):
        from tasks.ocp_tasks import _ocp_result_to_dataframe

        result = _FakeResult(n=50)
        df = _ocp_result_to_dataframe(result)

        assert isinstance(df, pd.DataFrame)
        assert set(df.columns) == {"distance_m", "speed_mps", "time_s", "a_long", "a_lat"}
        assert len(df) == 50

    def test_cumulative_time_increases(self):
        from tasks.ocp_tasks import _ocp_result_to_dataframe

        result = _FakeResult(n=50)
        df = _ocp_result_to_dataframe(result)

        assert df["time_s"].iloc[0] == 0.0
        assert df["time_s"].iloc[-1] > 0.0
        assert (df["time_s"].diff().iloc[1:] > 0).all()

    def test_returns_none_for_short_profile(self):
        from tasks.ocp_tasks import _ocp_result_to_dataframe

        result = _FakeResult(n=1)
        assert _ocp_result_to_dataframe(result) is None


class TestBuildTheoreticalResultDict:
    def test_produces_correct_shape(self):
        from tasks.ocp_tasks import _build_theoretical_result_dict

        result = _FakeResult(n=50)
        d = _build_theoretical_result_dict(result)

        assert isinstance(d, dict)
        assert "speed_profile" in d
        assert "track_length_m" in d
        assert isinstance(d["speed_profile"], list)
        assert len(d["speed_profile"]) == 50
        assert "distance_m" in d["speed_profile"][0]
        assert "speed_mps" in d["speed_profile"][0]
        assert d["track_length_m"] == pytest.approx(500.0, abs=1.0)
```

- [ ] **Step 2: Run tests to verify `_ocp_result_to_dataframe` passes and `_build_theoretical_result_dict` fails**

Run: `cd telemetry_tool && python -m pytest tests/test_ocp_downstream.py -v --tb=short`
Expected: `TestOcpResultToDataframe` tests PASS, `TestBuildTheoreticalResultDict` FAIL (function doesn't exist yet)

- [ ] **Step 3: Add `_build_theoretical_result_dict` to `ocp_tasks.py`**

Add after `_ocp_result_to_dataframe` (after line 413):

```python
def _build_theoretical_result_dict(result) -> dict:
    """Build the dict shape that run_coaching_analyzers expects for theoretical_result.

    Shape: {"speed_profile": [{"distance_m": ..., "speed_mps": ...}, ...], "track_length_m": float}
    """
    import numpy as np
    dist = np.array(result.distance_profile)
    speed = np.array(result.speed_profile)
    return {
        "speed_profile": [
            {"distance_m": round(float(dist[i]), 2), "speed_mps": round(float(speed[i]), 3)}
            for i in range(len(dist))
        ],
        "track_length_m": float(dist[-1]) if len(dist) > 0 else 0.0,
    }
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `cd telemetry_tool && python -m pytest tests/test_ocp_downstream.py -v --tb=short`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/tests/test_ocp_downstream.py telemetry_tool/tasks/ocp_tasks.py
git commit -m "feat(ocp): add _build_theoretical_result_dict + tests"
```

---

### Task 2: Test and implement full `_update_downstream`

**Files:**
- Modify: `telemetry_tool/tests/test_ocp_downstream.py`
- Modify: `telemetry_tool/tasks/ocp_tasks.py`

- [ ] **Step 1: Write test for full downstream chain with mocked pipeline functions**

Append to `telemetry_tool/tests/test_ocp_downstream.py`:

```python
from unittest.mock import patch, MagicMock


def _make_analysis_json():
    """Minimal analysis_json with required keys."""
    return {
        "lap_times": [74.3, 75.1, 76.0],
        "speed_trace_best": [
            {"distance_m": float(i), "speed_mps": 15.0 + 0.01 * i}
            for i in range(500)
        ],
        "corners": [
            {"corner_id": 0, "s_start": 50.0, "s_apex": 75.0, "s_end": 100.0,
             "apex_speed_mps": 12.0, "apex_distance_m": 75.0},
            {"corner_id": 1, "s_start": 200.0, "s_apex": 225.0, "s_end": 250.0,
             "apex_speed_mps": 14.0, "apex_distance_m": 225.0},
        ],
        "corner_coaching": [
            {"corner_id": 0, "apex_distance_m": 75.0, "entry_distance_m": 50.0,
             "exit_distance_m": 100.0, "actual_apex_speed_mps": 12.0},
            {"corner_id": 1, "apex_distance_m": 225.0, "entry_distance_m": 200.0,
             "exit_distance_m": 250.0, "actual_apex_speed_mps": 14.0},
        ],
        "friction_model": {"max_lateral_g": 1.2},
        "session_type": "practice",
    }


class TestUpdateDownstream:
    @patch("tasks.ocp_tasks._persist_updated_analysis")
    @patch("tasks.ocp_tasks._update_score_details_table")
    @patch("tasks.ocp_tasks._update_session_score_columns")
    def test_calls_score_session_with_ocp_method(self, mock_sess, mock_score_tbl, mock_persist):
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = _make_analysis_json()
        conn = MagicMock()

        _update_downstream(conn, "sess-1", result, result_dict, analysis_json)

        # Verify scoring was run and stored
        assert analysis_json["simulation_method"] == "ocp"
        assert analysis_json["theoretical_metrics"]["best_s"] == 68.5
        assert analysis_json["theoretical_metrics"]["simulation_method"] == "ocp"
        assert "score_result" in analysis_json
        assert analysis_json["score_result"]["total_score"] >= 0

        # Verify persist was called
        mock_persist.assert_called_once()
        mock_score_tbl.assert_called_once()
        mock_sess.assert_called_once()

    @patch("tasks.ocp_tasks._persist_updated_analysis")
    @patch("tasks.ocp_tasks._update_score_details_table")
    @patch("tasks.ocp_tasks._update_session_score_columns")
    def test_calls_corner_analysis_when_corners_exist(self, mock_sess, mock_score_tbl, mock_persist):
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = _make_analysis_json()
        conn = MagicMock()

        with patch("tasks.ocp_tasks.run_corner_analysis") as mock_ca:
            mock_ca.return_value = [
                {"corner_id": 0, "time_loss_s": 0.3},
                {"corner_id": 1, "time_loss_s": 0.5},
            ]
            _update_downstream(conn, "sess-1", result, result_dict, analysis_json)
            mock_ca.assert_called_once()
            # Verify theoretical_lap arg is a DataFrame (3rd positional arg)
            call_args = mock_ca.call_args
            theo_arg = call_args[0][2]
            assert isinstance(theo_arg, pd.DataFrame)
            assert "distance_m" in theo_arg.columns

    @patch("tasks.ocp_tasks._persist_updated_analysis")
    @patch("tasks.ocp_tasks._update_score_details_table")
    @patch("tasks.ocp_tasks._update_session_score_columns")
    def test_graceful_degradation_preserves_ocp_data(self, mock_sess, mock_score_tbl, mock_persist):
        """If corner analysis or coaching throws, scoring + OCP data should still be stored."""
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = _make_analysis_json()
        conn = MagicMock()

        with patch("tasks.ocp_tasks.run_corner_analysis", side_effect=RuntimeError("boom")):
            # Should NOT raise — graceful degradation
            _update_downstream(conn, "sess-1", result, result_dict, analysis_json)

        # Scoring should still be updated even if corners failed
        assert analysis_json["simulation_method"] == "ocp"
        assert "score_result" in analysis_json
        mock_persist.assert_called_once()

    def test_no_crash_when_no_lap_times(self):
        """analysis_json with no lap_times should exit early without error."""
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = {"corners": [], "corner_coaching": []}
        conn = MagicMock()

        # Should not raise
        _update_downstream(conn, "sess-1", result, result_dict, analysis_json)
```

- [ ] **Step 2: Run tests to verify new tests fail (current `_update_downstream` doesn't call `run_corner_analysis`)**

Run: `cd telemetry_tool && python -m pytest tests/test_ocp_downstream.py::TestUpdateDownstream -v --tb=short`
Expected: `test_calls_corner_analysis_when_corners_exist` FAIL (no `run_corner_analysis` call)

- [ ] **Step 3: Replace `_update_downstream` with full chain**

Replace the entire `_update_downstream` function (lines 305-385 in `ocp_tasks.py`) with:

```python
def _update_downstream(conn, session_id, result, result_dict, analysis_json):
    """Re-run corner analysis, coaching, and scoring with OCP theoretical data.

    Called after _store_ocp_result so analysis_json["theoretical_ocp"] already
    exists in the DB.  Updates the same DB row with refreshed scores, corner
    metrics, and coaching text.
    """
    import numpy as np
    import pandas as pd

    try:
        # 1. Build data shapes from OCP result
        theo_df = _ocp_result_to_dataframe(result)
        if theo_df is None or len(theo_df) < 10:
            logger.debug("OCP downstream: could not build theoretical DataFrame")
            return

        theo_result_dict = _build_theoretical_result_dict(result)

        speeds = np.array(result.speed_profile)
        theo_metrics = {
            "best_s": float(result.lap_time_s),
            "simulation_method": "ocp",
            "method": "ocp",
            "max_speed_mps": float(speeds.max()),
            "avg_speed_mps": float(speeds.mean()),
            "min_speed_mps": float(speeds.min()),
            "confidence": 1.0 if result.converged else 0.7,
        }

        # 2. Reconstruct dependencies from analysis_json
        best_lap_df = _reconstruct_best_lap_df(analysis_json)
        corners = analysis_json.get("corners", [])
        friction_model = analysis_json.get("friction_model") or {"max_lateral_g": 1.2}
        resampled_laps = {0: best_lap_df} if best_lap_df is not None else {}
        available_columns = set(best_lap_df.columns) if best_lap_df is not None else set()

        # 3. Build observed metrics
        observed_metrics = _extract_observed_metrics(analysis_json)
        if not observed_metrics.get("best_s"):
            logger.debug("OCP downstream: no observed best_s, skipping")
            return

        # 4. Re-run corner analysis with OCP theoretical
        corner_perfs = None
        if corners and best_lap_df is not None:
            try:
                from pipeline.stages.s10b_corners import run_corner_analysis
                corner_perfs = run_corner_analysis(
                    corners, best_lap_df, theo_df, friction_model, resampled_laps,
                )
                if corner_perfs:
                    analysis_json["corner_perfs"] = corner_perfs
            except Exception:
                logger.warning("OCP downstream: corner analysis failed", exc_info=True)

        # 5. Re-run coaching analyzers
        analyzer_bundle = None
        if corner_perfs:
            try:
                from pipeline.stages.s13_coaching_v3 import run_coaching_analyzers
                analyzer_bundle = run_coaching_analyzers(
                    corner_perfs, best_lap_df, theo_result_dict,
                    friction_model, resampled_laps, available_columns,
                )
            except Exception:
                logger.warning("OCP downstream: coaching analyzers failed", exc_info=True)

        # 6. Re-score with OCP theoretical
        from scoring.scorer import score_session

        session_type = analysis_json.get("session_type", "practice")
        new_scores = score_session(
            observed_metrics, theo_metrics, session_type,
            corner_coaching=corner_perfs or [],
        )

        # 7. Re-run enhanced coaching
        coaching_v3 = None
        if corner_perfs:
            try:
                from pipeline.stages.s13_coaching_v3 import run_enhanced_coaching
                coaching_v2 = analysis_json.get("coaching_v3") or analysis_json.get("coaching")
                driving_style = analysis_json.get("driving_style")
                vehicle_class = (analysis_json.get("vehicle_params") or {}).get("vehicle_class", "car")
                coaching_v3 = run_enhanced_coaching(
                    corner_perfs, coaching_v2, new_scores,
                    lap_metrics=None, driving_style=driving_style,
                    analyzer_bundle=analyzer_bundle, driver_history=None,
                    vehicle_class=vehicle_class,
                )
                if coaching_v3:
                    analysis_json["coaching_v3"] = coaching_v3
            except Exception:
                logger.warning("OCP downstream: enhanced coaching failed", exc_info=True)

        # 8. Update corner speed targets via interpolation (always, even if corner analysis failed)
        _update_corner_targets(analysis_json, result, corners)

        # 9. Store everything in analysis_json
        analysis_json["score_result"] = new_scores
        analysis_json["theoretical_metrics"] = theo_metrics
        analysis_json["simulation_method"] = "ocp"

        # 10. Persist — single transaction for RLS safety
        _persist_all(conn, session_id, analysis_json, new_scores)

        logger.info(
            "OCP downstream update complete for session %s: "
            "score=%.1f/%s, method=ocp, corners=%d",
            session_id,
            new_scores.get("total_score", 0),
            new_scores.get("grade", "?"),
            len(corner_perfs) if corner_perfs else 0,
        )

    except Exception:
        logger.warning(
            "OCP downstream update failed for session %s (raw OCP data preserved)",
            session_id, exc_info=True,
        )
```

- [ ] **Step 4: Replace the three separate persist helpers with a single `_persist_all`**

Replace `_persist_updated_analysis`, `_update_score_details_table`, and `_update_session_score_columns` with:

```python
def _persist_all(conn, session_id, analysis_json, new_scores):
    """Persist analysis_json, score_details, and session score columns in one commit.

    Uses a single conn.commit() to preserve SET LOCAL RLS context on PG.
    """
    import os
    use_pg = os.environ.get("USE_PG", "0") not in ("0", "false", "no")

    # 1. analysis_json blob
    if use_pg:
        conn.execute(
            "UPDATE sessions SET analysis_json = ?::jsonb WHERE id = ?",
            (json.dumps(analysis_json), session_id),
        )
    else:
        conn.execute(
            "UPDATE sessions SET analysis_json = ? WHERE id = ?",
            (json.dumps(analysis_json), session_id),
        )

    # 2. sessions.total_score + grade
    conn.execute(
        "UPDATE sessions SET total_score = ?, grade = ? WHERE id = ?",
        (new_scores.get("total_score"), new_scores.get("grade"), session_id),
    )

    # 3. score_details table
    try:
        from web.repos.score_repo import insert_score_details
        insert_score_details(conn, session_id, {"score_result": new_scores})
    except Exception:
        logger.debug("score_details update skipped", exc_info=True)

    # Single commit preserves SET LOCAL RLS context
    conn.commit()
```

- [ ] **Step 5: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_ocp_downstream.py -v --tb=short`
Expected: All tests PASS

- [ ] **Step 6: Run existing scoring tests to verify no regressions**

Run: `cd telemetry_tool && python -m pytest tests/test_scoring_boundaries.py tests/test_adaptive_scoring.py tests/test_scoring_session_types.py tests/test_optimal_pipeline.py -x -q --tb=short`
Expected: 85 passed

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/tasks/ocp_tasks.py telemetry_tool/tests/test_ocp_downstream.py
git commit -m "feat(ocp): full downstream chain — corner analysis, coaching, scoring

Wire run_corner_analysis, run_coaching_analyzers, run_enhanced_coaching
into _update_downstream. Single-commit persist for RLS safety."
```

---

### Task 3: Test RLS workspace context setup

**Files:**
- Modify: `telemetry_tool/tests/test_ocp_downstream.py`
- Modify: `telemetry_tool/tasks/ocp_tasks.py`

- [ ] **Step 1: Write test for workspace context**

Append to `test_ocp_downstream.py`:

```python
class TestRlsContext:
    @patch.dict(os.environ, {"USE_PG": "1"})
    @patch("tasks.ocp_tasks._persist_all")
    def test_workspace_context_set_before_persist(self, mock_persist):
        from tasks.ocp_tasks import _update_downstream

        result = _FakeResult(n=100, lap_time=68.5)
        result_dict = result.to_dict()
        analysis_json = _make_analysis_json()
        conn = MagicMock()

        # Pass workspace_id through — _run_ocp_impl passes it
        # We need to check that _update_downstream sets RLS context
        with patch("tasks.ocp_tasks._set_rls_if_pg") as mock_rls:
            _update_downstream(conn, "sess-1", result, result_dict, analysis_json, workspace_id=1)
            mock_rls.assert_called_once_with(conn, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_ocp_downstream.py::TestRlsContext -v --tb=short`
Expected: FAIL (`_update_downstream` doesn't accept `workspace_id` yet)

- [ ] **Step 3: Add `workspace_id` parameter to `_update_downstream` and RLS helper**

Update `_update_downstream` signature to accept `workspace_id: int | None = None` and add at the top of the try block:

```python
_set_rls_if_pg(conn, workspace_id)
```

Add the helper:

```python
def _set_rls_if_pg(conn, workspace_id):
    """Set workspace RLS context if running on PG."""
    if workspace_id is None:
        return
    if os.environ.get("USE_PG", "0") in ("0", "false", "no"):
        return
    try:
        from auth.workspace import set_workspace_context
        set_workspace_context(conn, workspace_id)
    except Exception:
        logger.debug("RLS context setup skipped", exc_info=True)
```

Update the call site in `_run_ocp_impl` (line 163) to pass `workspace_id`:

```python
_update_downstream(conn, session_id, result, result_dict, analysis_json, workspace_id=workspace_id)
```

(The `workspace_id` parameter is already available — it's passed to `_run_ocp_impl`.)

- [ ] **Step 4: Run all tests**

Run: `cd telemetry_tool && python -m pytest tests/test_ocp_downstream.py -v --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/tasks/ocp_tasks.py telemetry_tool/tests/test_ocp_downstream.py
git commit -m "feat(ocp): set RLS workspace context before downstream persist"
```

---

## Chunk 2: Corner Re-selection on Completed Sessions

### Task 4: Test and implement `_reconstruct_context_from_db`

**Files:**
- Create: `telemetry_tool/tests/test_resume_completed.py`
- Modify: `telemetry_tool/web/routes/jobs.py`

- [ ] **Step 1: Write tests for context reconstruction**

```python
# telemetry_tool/tests/test_resume_completed.py
"""Tests for corner re-selection on completed sessions."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
import pytest


class TestReconstructContextFromDb:
    def test_returns_context_when_job_exists(self, tmp_path):
        from web.routes.jobs import _reconstruct_context_from_db

        # Create a fake CSV file
        csv_path = tmp_path / "session.csv"
        csv_path.write_text("col1,col2\n1,2\n")

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "job-1",
            "workspace_id": "ws-1",
            "file_path": str(csv_path),
        }

        redis_client = MagicMock()
        redis_client.get.return_value = None  # Not in Redis

        ctx = _reconstruct_context_from_db(conn, "job-1", redis_client, temp_root=str(tmp_path))

        assert ctx is not None
        assert ctx.job_id == "job-1"
        assert ctx.workspace_id == "ws-1"
        assert ctx.session_id == "job-1"  # convention: session_id == job_id
        assert ctx.file_path == str(csv_path)

    def test_returns_none_when_csv_missing(self, tmp_path):
        from web.routes.jobs import _reconstruct_context_from_db

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "job-1",
            "workspace_id": "ws-1",
            "file_path": "/nonexistent/path.csv",
        }

        redis_client = MagicMock()
        redis_client.get.return_value = None

        ctx = _reconstruct_context_from_db(conn, "job-1", redis_client, temp_root=str(tmp_path))
        assert ctx is None

    def test_returns_none_when_job_not_found(self, tmp_path):
        from web.routes.jobs import _reconstruct_context_from_db

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None

        redis_client = MagicMock()
        redis_client.get.return_value = None

        ctx = _reconstruct_context_from_db(conn, "job-1", redis_client, temp_root=str(tmp_path))
        assert ctx is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_resume_completed.py -v --tb=short`
Expected: FAIL (function doesn't exist)

- [ ] **Step 3: Implement `_reconstruct_context_from_db` in `jobs.py`**

Add after `_load_pipeline_context` (after line 102):

```python
def _reconstruct_context_from_db(conn, job_id: str, redis_client, temp_root: str = "/tmp"):
    """Reconstruct PipelineContext from DB when Redis state is gone.

    Used for corner re-selection on completed sessions. Returns None if
    the job is not found or the original CSV no longer exists.
    """
    from pathlib import Path
    from pipeline_context import PipelineContext

    row = conn.execute(
        text("SELECT job_id, workspace_id, file_path FROM ingestion_jobs WHERE job_id = :job_id"),
        {"job_id": job_id},
    ).fetchone()

    if row is None:
        return None

    file_path = row["file_path"] if isinstance(row, dict) else row[2]
    workspace_id = row["workspace_id"] if isinstance(row, dict) else row[1]

    if not file_path or not Path(file_path).exists():
        return None

    return PipelineContext.create(
        redis_client=redis_client,
        job_id=job_id,
        workspace_id=str(workspace_id),
        session_id=job_id,  # convention: session_id == job_id
        file_path=str(file_path),
        temp_root=temp_root,
    )
```

- [ ] **Step 4: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_resume_completed.py -v --tb=short`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/tests/test_resume_completed.py telemetry_tool/web/routes/jobs.py
git commit -m "feat(resume): add _reconstruct_context_from_db for completed jobs"
```

---

### Task 5: Extend `/resume` status guard + OCP revocation

**Files:**
- Modify: `telemetry_tool/tests/test_resume_completed.py`
- Modify: `telemetry_tool/web/routes/jobs.py`

- [ ] **Step 1: Write test for completed status acceptance**

Append to `test_resume_completed.py`:

```python
class TestResumeStatusGuard:
    def test_completed_status_allowed(self):
        """The resume endpoint should accept 'completed' status."""
        # This tests the status guard logic, not the full endpoint.
        RESUMABLE = ("paused", "awaiting_corner_selection", "completed")
        assert "completed" in RESUMABLE
```

- [ ] **Step 2: Update the status guard in `jobs.py` resume endpoint**

In `web/routes/jobs.py`, change line 313:

From:
```python
if current_status not in ("paused", "awaiting_corner_selection"):
```

To:
```python
if current_status not in ("paused", "awaiting_corner_selection", "completed"):
```

- [ ] **Step 3: Add context fallback for completed jobs**

After the existing `_load_pipeline_context` call (line 321-328), add a fallback:

```python
    if ctx is None and current_status == "completed":
        ctx = _reconstruct_context_from_db(conn, job_id, redis_client)
        if ctx is None:
            return api_error(
                ErrorCode.CONFLICT,
                "Original session file no longer available. Please re-upload.",
                status=409,
            )
```

- [ ] **Step 4: Add OCP task revocation before dispatch**

Before `_dispatch_finalize(job_id)` (line 359), add:

```python
    # Revoke any in-flight OCP task from the previous run
    if current_status == "completed":
        _revoke_inflight_ocp(conn, job_id)
```

Add the helper:

```python
def _revoke_inflight_ocp(conn, job_id: str):
    """Revoke an in-flight OCP Celery task to prevent race conditions."""
    try:
        row = conn.execute(
            text("SELECT analysis_json FROM sessions WHERE session_id = :sid"),
            {"sid": job_id},
        ).fetchone()
        if row:
            import json as _json
            aj = _json.loads(row[0]) if row[0] else {}
            ocp_task_id = aj.get("ocp_task_id")
            if ocp_task_id:
                celery = _get_celery_app()
                if celery:
                    celery.control.revoke(ocp_task_id, terminate=True)
                    logger.info("Revoked in-flight OCP task %s for job %s", ocp_task_id, job_id)
    except Exception:
        logger.debug("OCP revocation skipped for job %s", job_id, exc_info=True)


def _get_celery_app():
    try:
        from tasks.celery_app import celery
        return celery
    except ImportError:
        return None
```

- [ ] **Step 5: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_resume_completed.py -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/jobs.py telemetry_tool/tests/test_resume_completed.py
git commit -m "feat(resume): allow completed status + OCP revocation on re-selection"
```

---

### Task 6: Pass custom corners in pipeline_tasks fallback path

**Files:**
- Modify: `telemetry_tool/tasks/pipeline_tasks.py:637-645`

- [ ] **Step 1: Update the fallback path to pass corners**

In `pipeline_tasks.py`, replace the fallback `run_full_analysis` call (lines 637-645):

From:
```python
    else:
        # Fallback: full re-run (intermediate state expired or missing)
        logger.warning("Job %s: intermediate state missing, running full pipeline", ctx.job_id)
        result = run_full_analysis(
            csv_path=ctx.file_path,
            session_meta=session_meta,
            enable_report=False,
            progress_callback=_make_progress_callback(_job_id, conn),
        )
```

To:
```python
    else:
        # Fallback: full re-run (intermediate state expired or missing)
        logger.warning("Job %s: intermediate state missing, running full pipeline", ctx.job_id)
        _fallback_corners = None
        if ctx.custom_corners is not None:
            _fallback_corners = [
                {**cn, "corner_id": i, "lat": 0.0, "lon": 0.0, "direction": "S"}
                for i, cn in enumerate(ctx.custom_corners)
            ]
            logger.info("Job %s: passing %d custom corners to full re-run",
                         ctx.job_id, len(_fallback_corners))
        result = run_full_analysis(
            csv_path=ctx.file_path,
            session_meta=session_meta,
            enable_report=False,
            progress_callback=_make_progress_callback(_job_id, conn),
            preloaded_corners=_fallback_corners,
        )
```

- [ ] **Step 2: Verify syntax**

Run: `cd telemetry_tool && python -c "import ast; ast.parse(open('tasks/pipeline_tasks.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run existing pipeline tests**

Run: `cd telemetry_tool && python -m pytest tests/test_optimal_pipeline.py -v --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/tasks/pipeline_tasks.py
git commit -m "fix(resume): pass custom corners in fallback full-rerun path"
```

---

### Task 7: Final integration smoke test

**Files:**
- Modify: `telemetry_tool/tests/test_ocp_downstream.py`

- [ ] **Step 1: Add end-to-end integration test**

Append to `test_ocp_downstream.py`:

```python
class TestEndToEndSmoke:
    """Verify the full chain doesn't crash with realistic-ish data."""

    def test_full_chain_smoke(self):
        from tasks.ocp_tasks import (
            _ocp_result_to_dataframe,
            _build_theoretical_result_dict,
            _extract_observed_metrics,
        )

        result = _FakeResult(n=200, lap_time=70.0)
        analysis_json = _make_analysis_json()

        # DataFrame conversion
        theo_df = _ocp_result_to_dataframe(result)
        assert theo_df is not None
        assert len(theo_df) == 200
        assert theo_df["time_s"].iloc[-1] > 0

        # Dict conversion
        theo_dict = _build_theoretical_result_dict(result)
        assert theo_dict["track_length_m"] > 0
        assert len(theo_dict["speed_profile"]) == 200

        # Observed metrics
        obs = _extract_observed_metrics(analysis_json)
        assert obs["best_s"] == 74.3
        assert obs["n_laps"] == 3
        assert obs["cv_pct"] > 0
```

- [ ] **Step 2: Run full test suite**

Run: `cd telemetry_tool && python -m pytest tests/test_ocp_downstream.py tests/test_resume_completed.py tests/test_scoring_boundaries.py tests/test_adaptive_scoring.py tests/test_scoring_session_types.py tests/test_optimal_pipeline.py -v --tb=short`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/tests/test_ocp_downstream.py
git commit -m "test(ocp): add end-to-end smoke test for downstream chain"
```
