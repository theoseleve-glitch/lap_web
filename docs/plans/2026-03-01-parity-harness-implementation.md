# Parity Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A pytest test suite that uploads a synthetic CSV via Flask test client, queries 7 data endpoints, and asserts pipeline-to-API parity with hard tolerances. Also fixes 4 endpoints to return structured `{available: false, reason_code}` instead of 404 on missing data.

**Architecture:** Single test file with a session-scoped fixture that uploads once (capturing the pipeline result via `unittest.mock.patch(wraps=...)`), then each test queries one endpoint and compares against the captured truth. Endpoints that currently return 404 for missing data are modified to return `{available: false, reason_code: "..."}`.

**Tech Stack:** pytest, Flask test client, unittest.mock, numpy (for synthetic CSV), json (for artifact dumps)

---

### Task 1: Add `DATA_UNAVAILABLE` error code

**Files:**
- Modify: `telemetry_tool/web/api_utils.py:34-59`

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_parity_harness.py` with a minimal import check:

```python
"""Parity harness: pipeline-to-API round-trip tolerance tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.api_utils import ErrorCode


def test_error_code_has_data_unavailable():
    assert hasattr(ErrorCode, "DATA_UNAVAILABLE")
    assert ErrorCode.DATA_UNAVAILABLE == "DATA_UNAVAILABLE"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_error_code_has_data_unavailable -v`
Expected: FAIL with `AttributeError: type object 'ErrorCode' has no attribute 'DATA_UNAVAILABLE'`

**Step 3: Write minimal implementation**

In `telemetry_tool/web/api_utils.py`, add after line 59 (after `NOT_IMPLEMENTED`):

```python
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_error_code_has_data_unavailable -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/api_utils.py telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: add DATA_UNAVAILABLE error code for missing-data contract"
```

---

### Task 2: Fix scores endpoint — return structured unavailability instead of 404

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:393-410` (get_scores)
- Test: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the failing test**

Add to `test_parity_harness.py`:

```python
import json
import pytest

from web.app import create_app


@pytest.fixture(scope="module")
def app_client():
    """Flask test client with in-memory SQLite."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_scores_missing_returns_available_false(app_client):
    """Scores endpoint must return {available: false, reason_code} not 404."""
    resp = app_client.get("/api/v1/sessions/nonexistent/scores")
    # Session not found is still 404 — that's fine.
    # But for an existing session with no score data, we need available: false.
    # For this test, we need a session that exists but has no scores.
    # We'll handle that in the seeded fixture tests. For now, verify 404 shape.
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["ok"] is False
```

Actually, the proper test requires a session that exists but has no score_details row. Let's add a seeded session without scores:

```python
from db.schema import ensure_schema


@pytest.fixture(scope="module")
def app_with_empty_session():
    """Flask app with a session that has no score data."""
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        from web.db import get_db_connection
        conn = get_db_connection()
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')"
        )
        conn.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, n_laps, best_lap_time_s, total_score) "
            "VALUES ('empty_s', 'test.csv', 1, 'practice', 5, 60.0, NULL)"
        )
        conn.commit()
    with app.test_client() as client:
        yield client


def test_scores_missing_returns_structured_unavailability(app_with_empty_session):
    resp = app_with_empty_session.get("/api/v1/sessions/empty_s/scores")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["available"] is False
    assert body["data"]["reason_code"] == "NO_SCORE_DATA"
    assert "message" in body["data"]
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_scores_missing_returns_structured_unavailability -v`
Expected: FAIL — currently returns 404, not 200 with available:false

**Step 3: Write minimal implementation**

In `telemetry_tool/web/routes/data_v2.py`, replace lines 402-408:

```python
    # OLD:
    # scores = models.get_score_details(conn, session_id)
    # if scores is None:
    #     return api_error(
    #         ErrorCode.NOT_FOUND,
    #         "No score details for this session",
    #         status=404,
    #     )
    # return api_response(scores)

    # NEW:
    scores = models.get_score_details(conn, session_id)
    if scores is None:
        return api_response({
            "available": False,
            "reason_code": "NO_SCORE_DATA",
            "message": "Scoring data not available for this session",
        })

    scores["available"] = True
    return api_response(scores)
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_scores_missing_returns_structured_unavailability -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_parity_harness.py
git commit -m "fix: scores endpoint returns structured unavailability instead of 404"
```

---

### Task 3: Fix speed-trace and gps-trace endpoints — structured unavailability

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:271-277` (speed-trace trace-missing branch)
- Modify: `telemetry_tool/web/routes/data_v2.py:329-335` (gps-trace trace-missing branch)
- Test: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the failing tests**

```python
def test_speed_trace_missing_returns_available_false(app_with_empty_session):
    """Speed trace for session with no GPS data must return available:false."""
    resp = app_with_empty_session.get("/api/v1/sessions/empty_s/speed-trace")
    # empty_s has no GPS traces — should return available:false, not 404
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["data"]["available"] is False
    assert body["data"]["reason_code"] == "NO_SPEED_TRACE"


def test_gps_trace_missing_returns_available_false(app_with_empty_session):
    resp = app_with_empty_session.get("/api/v1/sessions/empty_s/gps-trace")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["data"]["available"] is False
    assert body["data"]["reason_code"] == "NO_GPS_DATA"
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_parity_harness.py -k "speed_trace_missing or gps_trace_missing" -v`
Expected: FAIL — both return 404 currently

**Step 3: Write minimal implementation**

In `data_v2.py` `get_speed_trace()`, replace the trace-is-None block (lines 272-277):

```python
    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_response({
            "available": False,
            "reason_code": "NO_SPEED_TRACE",
            "message": f"No speed trace data for lap {lap_num}",
        })
```

In `data_v2.py` `get_gps_trace()`, replace trace-is-None block (lines 330-335):

```python
    trace = models.get_gps_trace(conn, session_id, lap_num)
    if trace is None:
        return api_response({
            "available": False,
            "reason_code": "NO_GPS_DATA",
            "message": f"No GPS trace for lap {lap_num}",
        })
```

Also add `"available": True` to the happy-path responses of both endpoints so the contract is symmetric.

For `get_speed_trace` add to the result dict (after line 283):
```python
    result["available"] = True
```

For `get_gps_trace` update the return (lines 337-343) to include:
```python
    return api_response({
        "latitudes": trace.get("latitudes", []),
        "longitudes": trace.get("longitudes", []),
        "distances": trace.get("distances", []),
        "speeds": trace.get("speeds", []),
        "lap_number": lap_num,
        "available": True,
    })
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_parity_harness.py -k "speed_trace_missing or gps_trace_missing" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_parity_harness.py
git commit -m "fix: speed-trace and gps-trace return structured unavailability"
```

---

### Task 4: Fix sector_times endpoint — structured unavailability

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:1335-1336` (sector_times fallthrough)
- Test: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the failing test**

```python
def test_sectors_missing_returns_available_false(app_with_empty_session):
    resp = app_with_empty_session.get("/api/v1/sessions/empty_s/sector_times")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["data"]["available"] is False
    assert body["data"]["reason_code"] == "NO_SECTOR_DATA"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_sectors_missing_returns_available_false -v`
Expected: FAIL — returns 404

**Step 3: Write minimal implementation**

In `data_v2.py` `get_sector_times()`, replace the final `api_error` at lines 1335-1336:

```python
    # OLD:
    # return api_error(ErrorCode.NOT_FOUND,
    #                  "No sector analysis for this session", status=404)

    # NEW:
    return api_response({
        "available": False,
        "reason_code": "NO_SECTOR_DATA",
        "message": "Sector analysis not available for this session",
    })
```

Also wrap the happy-path return at line 1317 to add `available: True`:

```python
    if analysis and analysis.get("sector_analysis"):
        result = analysis["sector_analysis"]
        if isinstance(result, dict):
            result["available"] = True
        return api_response(result)
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_sectors_missing_returns_available_false -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_parity_harness.py
git commit -m "fix: sector_times returns structured unavailability instead of 404"
```

---

### Task 5: Add GG and corners reason_codes to existing available:false responses

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:380-385` (gg-data)
- Modify: `telemetry_tool/web/routes/data_v2.py:434-437` (corners)
- Test: `telemetry_tool/tests/test_parity_harness.py`

These two endpoints already return `available: false` but WITHOUT `reason_code` or `message`. We add those fields.

**Step 1: Write the failing tests**

```python
def test_gg_missing_has_reason_code(app_with_empty_session):
    """GG endpoint already returns available:false — verify it has reason_code."""
    # Need a session with GPS trace but no accel columns.
    # For this test, empty_s has no GPS at all, so it'll 404 on the no-laps check.
    # We need to insert laps + a GPS trace without accel columns.
    # This is tested more thoroughly in test_missing_data_contract. For now,
    # test the gg-data code path by inserting a trace with empty accel.
    pass  # Covered by test_missing_data_contract (Task 7)


def test_corners_missing_has_reason_code(app_with_empty_session):
    """Corners must include reason_code when available:false."""
    # empty_s has no theoretical data → corners returns available:false
    # but currently no reason_code
    resp = app_with_empty_session.get("/api/v1/sessions/empty_s/corners")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["data"]["available"] is False
    assert body["data"]["reason_code"] == "NO_CORNER_DATA"
    assert "message" in body["data"]
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_corners_missing_has_reason_code -v`
Expected: FAIL — `reason_code` not in response

**Step 3: Write minimal implementation**

In `data_v2.py` `get_gg_data()`, update the return block (lines 380-385):

```python
    lat_g = trace.get("accel_lat") or []
    lon_g = trace.get("accel_long") or []
    has_accel = bool(lat_g and lon_g)

    result = {
        "accel_lat": lat_g if has_accel else [],
        "accel_long": lon_g if has_accel else [],
        "lap_number": lap_num,
        "available": has_accel,
    }
    if not has_accel:
        result["reason_code"] = "NO_GG_DATA"
        result["message"] = "No accelerometer data available for this session"

    return api_response(result)
```

In `data_v2.py` `get_corners()`, update the return block (lines 434-437):

```python
    theo = models.get_theoretical_data(conn, session_id)
    corners = theo.get("corner_coaching") if theo else None

    if not corners:
        return api_response({
            "corners": [],
            "available": False,
            "reason_code": "NO_CORNER_DATA",
            "message": "Corner detection did not produce results for this session",
        })

    return api_response({
        "corners": corners,
        "available": True,
    })
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_corners_missing_has_reason_code -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_parity_harness.py
git commit -m "fix: add reason_code to GG and corners unavailability responses"
```

---

### Task 6: Build synthetic CSV fixture and upload fixture

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Build the synthetic CSV generator**

Add to `test_parity_harness.py`:

```python
import io
import tempfile
import numpy as np


def _generate_synthetic_csv(n_laps=5, points_per_lap=200, seed=42):
    """Generate a deterministic RaceChrono-like CSV with 5 laps.

    Returns path to a temporary CSV file.

    The simulated track is a 500m oval. Each lap has speed variations
    at fixed distance intervals to give the corner detector features.
    Lateral and longitudinal accelerations are included for GG data.
    """
    rng = np.random.RandomState(seed)
    lines = []

    # RaceChrono metadata header
    lines.append("# RaceChrono Pro v9.1.3")
    lines.append("# Session: Parity Test")
    lines.append("# Track: Synthetic Oval 500m")

    # Column header
    cols = [
        "Time (s)",
        "Lap #",
        "Distance (m)",
        "Speed (m/s)",
        "Latitude",
        "Longitude",
        "Lateral acceleration (m/s²)",
        "Longitudinal acceleration (m/s²)",
    ]
    lines.append(",".join(cols))

    lap_length = 500.0  # meters
    base_lat, base_lon = 51.5074, -0.1278  # London
    t = 0.0

    for lap in range(1, n_laps + 1):
        for i in range(points_per_lap):
            frac = i / points_per_lap
            dist = frac * lap_length

            # Speed: ~15 m/s with dips at 4 "corners" (at 25%, 50%, 75%, 100%)
            corner_effect = 0.0
            for c_frac in [0.25, 0.50, 0.75, 1.0]:
                delta = abs(frac - c_frac)
                if delta < 0.05:
                    corner_effect = -5.0 * (1.0 - delta / 0.05)
            speed = 15.0 + corner_effect + rng.normal(0, 0.1)
            speed = max(speed, 5.0)

            # Lap-to-lap variation: lap 3 is fastest
            if lap == 3:
                speed *= 1.02
            elif lap == 1:
                speed *= 0.97  # outlap-ish

            dt = (lap_length / points_per_lap) / max(speed, 1.0)
            t += dt

            # GPS: oval via sin/cos
            angle = frac * 2 * np.pi
            lat = base_lat + 0.001 * np.sin(angle)
            lon = base_lon + 0.002 * np.cos(angle)

            # Accelerations
            accel_lat = -speed**2 * 0.001 * np.sin(2 * angle) + rng.normal(0, 0.2)
            accel_long = corner_effect * 0.5 + rng.normal(0, 0.1)

            lines.append(
                f"{t:.4f},{lap},{dist:.2f},{speed:.4f},"
                f"{lat:.7f},{lon:.7f},{accel_lat:.4f},{accel_long:.4f}"
            )

    content = "\n".join(lines) + "\n"
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return tmp.name
```

**Step 2: Add the upload fixture that captures pipeline truth**

```python
import os
from unittest.mock import patch


@pytest.fixture(scope="module")
def uploaded_session():
    """Upload synthetic CSV via Flask test client, capture pipeline result.

    Returns (client, session_id, pipeline_summary) tuple.
    The pipeline_summary is the full dict returned by run_full_analysis().
    """
    csv_path = _generate_synthetic_csv(n_laps=5, points_per_lap=200, seed=42)
    captured = {}

    app = create_app()
    app.config["TESTING"] = True

    # Patch run_full_analysis with wraps= to intercept result
    original_fn = None
    try:
        from pipeline import run_full_analysis as orig
        original_fn = orig
    except ImportError:
        pytest.skip("pipeline module not importable")

    def _capture_wrapper(*args, **kwargs):
        result = original_fn(*args, **kwargs)
        captured["summary"] = result
        return result

    with app.test_client() as client:
        with app.app_context():
            with patch("web.routes.sessions_v2.run_full_analysis",
                       side_effect=_capture_wrapper):
                with open(csv_path, "rb") as f:
                    resp = client.post(
                        "/api/v1/sessions/upload",
                        data={
                            "file": (f, "parity_test.csv"),
                            "session_type": "practice",
                            "track_state": "dry",
                            "driver_name": "ParityDriver",
                        },
                        content_type="multipart/form-data",
                    )

        assert resp.status_code == 200, f"Upload failed: {resp.get_json()}"
        body = resp.get_json()
        session_id = body["data"]["session_id"]

        yield client, session_id, captured.get("summary", {})

    # Cleanup
    try:
        os.unlink(csv_path)
    except OSError:
        pass
```

**Step 3: Write a smoke test that the fixture works**

```python
def test_upload_fixture_produces_session(uploaded_session):
    client, session_id, summary = uploaded_session
    assert session_id is not None
    assert "steps_ok" in summary
    assert len(summary.get("steps_ok", [])) > 0
```

**Step 4: Run the smoke test**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_upload_fixture_produces_session -v`
Expected: PASS (pipeline runs on synthetic CSV, session persisted)

**Step 5: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness synthetic CSV generator and upload fixture"
```

---

### Task 7: Tolerance helpers and artifact dumper

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Add tolerance dict, helpers, and artifact dumper**

```python
import json
from pathlib import Path

# ════════════════════════════════════════════════════════════════
# TOLERANCE CONTRACT — single source of truth
# Any change here must be reviewed and agreed upon.
# ════════════════════════════════════════════════════════════════
TOLERANCES = {
    "lap_time_s":       0.005,   # +/-5 ms
    "best_lap_index":   0,       # exact
    "total_score":      0.1,     # +/-0.1 out of 100
    "pillar_score":     0.1,     # +/-0.1 per pillar
    "grade":            0,       # exact string
    "sector_time_s":    0.001,   # +/-1 ms
    "corner_s_start":   1.0,     # +/-1 m
    "corner_s_end":     1.0,     # +/-1 m
    "corner_s_apex":    1.0,     # +/-1 m
    "speed_mps":        0.01,    # +/-0.01 m/s per sample
    "gps_lat_lon":      1e-6,    # ~0.1 m at equator
    "accel_g":          0.01,    # +/-0.01 g per sample
}


def _artifacts_dir(tmp_path_factory):
    """Return (or create) the parity artifacts directory."""
    d = tmp_path_factory.mktemp("parity_artifacts")
    return d


def dump_artifact(directory: Path, name: str, data):
    """Write a JSON artifact for post-mortem inspection."""
    path = directory / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def assert_close(actual, expected, tol_key: str, label: str = ""):
    """Assert numeric value within tolerance. Clear failure message."""
    tol = TOLERANCES[tol_key]
    diff = abs(actual - expected)
    assert diff <= tol, (
        f"PARITY FAIL [{label}]: {actual} vs {expected} "
        f"(diff={diff:.6f}, tol={tol} [{tol_key}])"
    )


def assert_exact(actual, expected, label: str = ""):
    """Assert exact equality with clear label."""
    assert actual == expected, (
        f"PARITY FAIL [{label}]: {actual!r} != {expected!r}"
    )
```

**Step 2: Verify helpers work**

```python
def test_assert_close_passes():
    assert_close(60.003, 60.0, "lap_time_s", "test lap")


def test_assert_close_fails():
    with pytest.raises(AssertionError, match="PARITY FAIL"):
        assert_close(60.1, 60.0, "lap_time_s", "test lap")
```

**Step 3: Run helper tests**

Run: `pytest telemetry_tool/tests/test_parity_harness.py -k "assert_close" -v`
Expected: PASS

**Step 4: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness tolerance contract and assertion helpers"
```

---

### Task 8: test_scores_parity

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the test**

```python
def test_scores_parity(uploaded_session, tmp_path_factory):
    """Pipeline score_result vs GET /scores must match within tolerance."""
    client, session_id, summary = uploaded_session
    artifacts = _artifacts_dir(tmp_path_factory)

    # Pipeline truth
    score_result = summary.get("score_result", {})
    sub = score_result.get("sub_scores", {})
    pipeline_scores = {
        "total_score": score_result.get("total_score"),
        "grade": score_result.get("grade"),
        "pace_score": sub.get("pace", {}).get("score"),
        "consistency_score": sub.get("consistency", {}).get("score"),
        "execution_score": sub.get("execution", {}).get("score"),
        "robustness_score": sub.get("robustness", {}).get("score"),
    }

    # API side
    resp = client.get(f"/api/v1/sessions/{session_id}/scores")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    api_scores = body["data"]

    # Dump artifacts before assertions
    dump_artifact(artifacts, "scores_pipeline", pipeline_scores)
    dump_artifact(artifacts, "scores_api", api_scores)

    # Assertions
    if pipeline_scores["total_score"] is None:
        # Pipeline didn't produce scores — API must say available:false
        assert api_scores.get("available") is False
        return

    assert api_scores.get("available") is True

    assert_close(
        api_scores["pace_score"], pipeline_scores["pace_score"],
        "pillar_score", "pace"
    )
    assert_close(
        api_scores["consistency_score"], pipeline_scores["consistency_score"],
        "pillar_score", "consistency"
    )
    assert_close(
        api_scores["execution_score"], pipeline_scores["execution_score"],
        "pillar_score", "execution"
    )
    assert_close(
        api_scores["robustness_score"], pipeline_scores["robustness_score"],
        "pillar_score", "robustness"
    )

    # Total score: sum of pillars should match (separate tolerance)
    api_total = (
        api_scores["pace_score"] + api_scores["consistency_score"]
        + api_scores["execution_score"] + api_scores["robustness_score"]
    )
    # Note: total may also include adaptation, so check pipeline total directly
    assert_close(
        api_total, pipeline_scores["total_score"],
        "total_score", "total (sum)"
    )

    # Grade: exact
    assert_exact(
        body["data"].get("grade", score_result.get("grade")),
        pipeline_scores["grade"],
        "grade"
    )
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_scores_parity -v`
Expected: PASS if pipeline produces scores on the synthetic fixture

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness — test_scores_parity"
```

---

### Task 9: test_laps_parity

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the test**

```python
def test_laps_parity(uploaded_session, tmp_path_factory):
    """Pipeline lap_metrics vs GET /laps must match."""
    client, session_id, summary = uploaded_session
    artifacts = _artifacts_dir(tmp_path_factory)

    # Pipeline truth
    pipeline_laps = summary.get("lap_metrics", [])
    best_key = summary.get("best_lap_key")

    # API side
    resp = client.get(f"/api/v1/sessions/{session_id}/laps")
    assert resp.status_code == 200
    body = resp.get_json()
    api_laps = body["data"]["laps"]

    dump_artifact(artifacts, "laps_pipeline", {
        "laps": pipeline_laps, "best_lap_key": best_key
    })
    dump_artifact(artifacts, "laps_api", body["data"])

    # Same number of laps
    assert_exact(len(api_laps), len(pipeline_laps), "lap count")

    # Per-lap comparison
    for p_lap, a_lap in zip(
        sorted(pipeline_laps, key=lambda x: x["lap_number"]),
        sorted(api_laps, key=lambda x: x["lap_number"]),
    ):
        ln = p_lap["lap_number"]
        assert_exact(a_lap["lap_number"], ln, f"lap {ln} number")
        assert_close(
            a_lap["lap_time_s"], p_lap["lap_time_s"],
            "lap_time_s", f"lap {ln} time"
        )
        assert_close(
            a_lap["speed_mean_mps"], p_lap["speed_mean_mps"],
            "speed_mps", f"lap {ln} speed_mean"
        )

    # Best lap index: exact match
    api_best = [lp for lp in api_laps if lp.get("is_best")]
    if best_key is not None and api_best:
        assert_exact(
            api_best[0]["lap_number"], best_key, "best lap index"
        )
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_laps_parity -v`
Expected: PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness — test_laps_parity"
```

---

### Task 10: test_speed_trace_parity

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the test**

```python
def test_speed_trace_parity(uploaded_session, tmp_path_factory):
    """Pipeline best-lap speed trace vs GET /speed-trace."""
    client, session_id, summary = uploaded_session
    artifacts = _artifacts_dir(tmp_path_factory)

    best_key = summary.get("best_lap_key")
    resampled = summary.get("resampled_laps", {})

    resp = client.get(f"/api/v1/sessions/{session_id}/speed-trace")
    assert resp.status_code == 200
    body = resp.get_json()
    api_data = body["data"]

    dump_artifact(artifacts, "speed_trace_api", api_data)

    if api_data.get("available") is False:
        # Pipeline may not have produced traces for synthetic data
        dump_artifact(artifacts, "speed_trace_pipeline", {"available": False})
        return

    api_speeds = api_data["speeds"]
    api_dists = api_data["distances"]

    # Pipeline truth: GPS traces are stored per-lap as arrays
    # The DB stores what insert_gps_traces wrote, which comes from resampled_laps
    if best_key and best_key in resampled:
        import pandas as pd
        best_df = resampled[best_key]
        if isinstance(best_df, pd.DataFrame) and "Speed (m/s)" in best_df.columns:
            p_speeds = best_df["Speed (m/s)"].tolist()
            assert_exact(len(api_speeds), len(p_speeds), "speed trace length")
            for i, (a, p) in enumerate(zip(api_speeds, p_speeds)):
                assert_close(a, p, "speed_mps", f"speed[{i}]")

    dump_artifact(artifacts, "speed_trace_pipeline", {
        "best_key": best_key,
        "n_points": len(api_speeds),
    })
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_speed_trace_parity -v`
Expected: PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness — test_speed_trace_parity"
```

---

### Task 11: test_gps_trace_parity

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the test**

```python
def test_gps_trace_parity(uploaded_session, tmp_path_factory):
    """Pipeline best-lap GPS vs GET /gps-trace."""
    client, session_id, summary = uploaded_session
    artifacts = _artifacts_dir(tmp_path_factory)

    resp = client.get(f"/api/v1/sessions/{session_id}/gps-trace")
    assert resp.status_code == 200
    body = resp.get_json()
    api_data = body["data"]

    dump_artifact(artifacts, "gps_trace_api", api_data)

    if api_data.get("available") is False:
        return

    api_lats = api_data["latitudes"]
    api_lons = api_data["longitudes"]

    best_key = summary.get("best_lap_key")
    resampled = summary.get("resampled_laps", {})

    if best_key and best_key in resampled:
        import pandas as pd
        best_df = resampled[best_key]
        if isinstance(best_df, pd.DataFrame):
            lat_col = next(
                (c for c in best_df.columns if "lat" in c.lower()), None
            )
            lon_col = next(
                (c for c in best_df.columns if "lon" in c.lower()), None
            )
            if lat_col and lon_col:
                p_lats = best_df[lat_col].tolist()
                p_lons = best_df[lon_col].tolist()
                assert_exact(len(api_lats), len(p_lats), "gps trace length")
                for i in range(len(api_lats)):
                    assert_close(
                        api_lats[i], p_lats[i], "gps_lat_lon", f"lat[{i}]"
                    )
                    assert_close(
                        api_lons[i], p_lons[i], "gps_lat_lon", f"lon[{i}]"
                    )
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_gps_trace_parity -v`
Expected: PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness — test_gps_trace_parity"
```

---

### Task 12: test_corners_parity

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the test**

```python
def test_corners_parity(uploaded_session, tmp_path_factory):
    """Pipeline corner coaching vs GET /corners."""
    client, session_id, summary = uploaded_session
    artifacts = _artifacts_dir(tmp_path_factory)

    resp = client.get(f"/api/v1/sessions/{session_id}/corners")
    assert resp.status_code == 200
    body = resp.get_json()
    api_data = body["data"]

    dump_artifact(artifacts, "corners_api", api_data)

    if api_data.get("available") is False:
        # Verify it has the required contract fields
        assert "reason_code" in api_data, "Missing reason_code on unavailable corners"
        assert api_data["reason_code"] == "NO_CORNER_DATA"
        return

    api_corners = api_data["corners"]

    # Pipeline truth: corner coaching from theoretical analysis
    pipeline_corners = summary.get("corner_coaching") or []
    # Also check theoretical_metrics for corner data
    if not pipeline_corners:
        # Corner coaching may be nested under score_result or theoretical
        theo = summary.get("theoretical_metrics") or {}
        pipeline_corners = theo.get("corner_coaching") or []

    dump_artifact(artifacts, "corners_pipeline", pipeline_corners)

    if not pipeline_corners:
        # Pipeline didn't produce corners — API should say available:false
        assert api_data.get("available") is False
        return

    assert_exact(len(api_corners), len(pipeline_corners), "corner count")

    for p_c, a_c in zip(
        sorted(pipeline_corners, key=lambda x: x.get("corner_id", 0)),
        sorted(api_corners, key=lambda x: x.get("corner_id", 0)),
    ):
        cid = p_c.get("corner_id", "?")
        if "s_start" in p_c and "s_start" in a_c:
            assert_close(
                a_c["s_start"], p_c["s_start"],
                "corner_s_start", f"corner {cid} s_start"
            )
        if "s_end" in p_c and "s_end" in a_c:
            assert_close(
                a_c["s_end"], p_c["s_end"],
                "corner_s_end", f"corner {cid} s_end"
            )
        if "s_apex" in p_c and "s_apex" in a_c:
            assert_close(
                a_c["s_apex"], p_c["s_apex"],
                "corner_s_apex", f"corner {cid} s_apex"
            )
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_corners_parity -v`
Expected: PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness — test_corners_parity"
```

---

### Task 13: test_sectors_parity and test_gg_data_parity

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write both tests**

```python
def test_sectors_parity(uploaded_session, tmp_path_factory):
    """Pipeline sector analysis vs GET /sector_times."""
    client, session_id, summary = uploaded_session
    artifacts = _artifacts_dir(tmp_path_factory)

    resp = client.get(f"/api/v1/sessions/{session_id}/sector_times")
    assert resp.status_code == 200
    body = resp.get_json()
    api_data = body["data"]

    dump_artifact(artifacts, "sectors_api", api_data)

    if api_data.get("available") is False:
        assert "reason_code" in api_data
        assert api_data["reason_code"] == "NO_SECTOR_DATA"
        return

    # Pipeline truth: sector analysis in analysis_json
    # The pipeline stores this as part of the summary under various keys
    # The endpoint reads from the analysis_json table
    pipeline_sectors = None
    if "sector_analysis" in (summary.get("analysis_json") or {}):
        pipeline_sectors = summary["analysis_json"]["sector_analysis"]

    dump_artifact(artifacts, "sectors_pipeline", pipeline_sectors)

    if pipeline_sectors and "sectors" in api_data:
        api_sectors = api_data["sectors"]
        p_sectors = pipeline_sectors.get("sectors", [])
        assert_exact(len(api_sectors), len(p_sectors), "sector count")

        for p_s, a_s in zip(p_sectors, api_sectors):
            sn = p_s.get("sector_num", "?")
            if "best_s" in p_s and "best_s" in a_s:
                assert_close(
                    a_s["best_s"], p_s["best_s"],
                    "sector_time_s", f"sector {sn} best"
                )
            if "mean_s" in p_s and "mean_s" in a_s:
                assert_close(
                    a_s["mean_s"], p_s["mean_s"],
                    "sector_time_s", f"sector {sn} mean"
                )


def test_gg_data_parity(uploaded_session, tmp_path_factory):
    """Pipeline GG accelerations vs GET /gg-data."""
    client, session_id, summary = uploaded_session
    artifacts = _artifacts_dir(tmp_path_factory)

    resp = client.get(f"/api/v1/sessions/{session_id}/gg-data")
    assert resp.status_code == 200
    body = resp.get_json()
    api_data = body["data"]

    dump_artifact(artifacts, "gg_api", api_data)

    if api_data.get("available") is False:
        assert "reason_code" in api_data
        assert api_data["reason_code"] == "NO_GG_DATA"
        return

    api_lat = api_data["accel_lat"]
    api_long = api_data["accel_long"]

    # Pipeline truth: accel data from resampled_laps best lap
    best_key = summary.get("best_lap_key")
    resampled = summary.get("resampled_laps", {})

    if best_key and best_key in resampled:
        import pandas as pd
        best_df = resampled[best_key]
        if isinstance(best_df, pd.DataFrame):
            lat_col = next(
                (c for c in best_df.columns if "lateral" in c.lower()
                 and "accel" in c.lower()), None
            )
            long_col = next(
                (c for c in best_df.columns if "longitudinal" in c.lower()
                 and "accel" in c.lower()), None
            )
            if lat_col and long_col:
                p_lat = best_df[lat_col].tolist()
                p_long = best_df[long_col].tolist()

                dump_artifact(artifacts, "gg_pipeline", {
                    "n_points": len(p_lat),
                    "lat_col": lat_col, "long_col": long_col,
                })

                assert_exact(len(api_lat), len(p_lat), "GG lat array length")
                assert_exact(len(api_long), len(p_long), "GG long array length")

                for i in range(len(api_lat)):
                    assert_close(
                        api_lat[i], p_lat[i], "accel_g", f"accel_lat[{i}]"
                    )
                    assert_close(
                        api_long[i], p_long[i], "accel_g", f"accel_long[{i}]"
                    )
```

**Step 2: Run tests**

Run: `pytest telemetry_tool/tests/test_parity_harness.py -k "sectors_parity or gg_data_parity" -v`
Expected: PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness — test_sectors_parity and test_gg_data_parity"
```

---

### Task 14: test_missing_data_contract

**Files:**
- Modify: `telemetry_tool/tests/test_parity_harness.py`

**Step 1: Write the test**

This test uploads a *minimal* CSV that intentionally lacks acceleration columns and has very few points (not enough for corner detection), then asserts the structured unavailability contract on all relevant endpoints.

```python
def _generate_minimal_csv(seed=99):
    """CSV with only Time, Lap#, Distance, Speed, Lat, Lon — no accelerations."""
    rng = np.random.RandomState(seed)
    lines = [
        "# RaceChrono Pro v9.1.3",
        "# Session: Minimal Test",
        "Time (s),Lap #,Distance (m),Speed (m/s),Latitude,Longitude",
    ]
    t = 0.0
    for lap in range(1, 4):
        for i in range(50):
            frac = i / 50
            speed = 12.0 + rng.normal(0, 0.1)
            dt = 10.0 / max(speed, 1.0)
            t += dt
            lat = 51.5 + 0.001 * np.sin(frac * 2 * np.pi)
            lon = -0.13 + 0.002 * np.cos(frac * 2 * np.pi)
            lines.append(f"{t:.4f},{lap},{frac * 500:.2f},{speed:.4f},{lat:.7f},{lon:.7f}")

    content = "\n".join(lines) + "\n"
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


@pytest.fixture(scope="module")
def minimal_session():
    """Upload minimal CSV lacking accelerations."""
    csv_path = _generate_minimal_csv()
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        with app.app_context():
            with open(csv_path, "rb") as f:
                resp = client.post(
                    "/api/v1/sessions/upload",
                    data={
                        "file": (f, "minimal_test.csv"),
                        "session_type": "practice",
                        "track_state": "dry",
                        "driver_name": "MinimalDriver",
                    },
                    content_type="multipart/form-data",
                )
        if resp.status_code != 200:
            pytest.skip(f"Minimal upload failed: {resp.get_json()}")

        body = resp.get_json()
        session_id = body["data"]["session_id"]
        yield client, session_id

    try:
        os.unlink(csv_path)
    except OSError:
        pass


def test_missing_data_contract(minimal_session):
    """Endpoints must return {available:false, reason_code} not empty/404."""
    client, session_id = minimal_session

    # GG data: no accelerometers → must say NO_GG_DATA
    resp = client.get(f"/api/v1/sessions/{session_id}/gg-data")
    if resp.status_code == 200:
        body = resp.get_json()
        gg = body["data"]
        if not gg.get("available"):
            assert "reason_code" in gg, "GG unavailable but no reason_code"
            assert gg["reason_code"] == "NO_GG_DATA"
            assert "message" in gg

    # Scores: might or might not be available
    resp = client.get(f"/api/v1/sessions/{session_id}/scores")
    assert resp.status_code == 200
    body = resp.get_json()
    if not body["data"].get("available", True):
        assert "reason_code" in body["data"]

    # Corners: minimal data may not detect corners
    resp = client.get(f"/api/v1/sessions/{session_id}/corners")
    assert resp.status_code == 200
    body = resp.get_json()
    if not body["data"].get("available"):
        assert "reason_code" in body["data"]
        assert body["data"]["reason_code"] == "NO_CORNER_DATA"

    # Sectors
    resp = client.get(f"/api/v1/sessions/{session_id}/sector_times")
    assert resp.status_code == 200
    body = resp.get_json()
    if not body["data"].get("available", True):
        assert "reason_code" in body["data"]
        assert body["data"]["reason_code"] == "NO_SECTOR_DATA"
```

**Step 2: Run test**

Run: `pytest telemetry_tool/tests/test_parity_harness.py::test_missing_data_contract -v`
Expected: PASS

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness — test_missing_data_contract"
```

---

### Task 15: Run full parity suite, fix any issues, verify all green

**Files:**
- All files from previous tasks

**Step 1: Run the full suite**

Run: `pytest telemetry_tool/tests/test_parity_harness.py -v --tb=short`
Expected: All tests PASS

**Step 2: If any failures, debug and fix**

Common issues to watch for:
- Import paths: `pipeline` vs `telemetry_tool.pipeline` — check conftest.py sys.path
- Column name mismatches: pipeline uses RaceChrono headers, models may normalize
- Session ID format: may be generated differently than expected
- NaN/None in JSON: numpy NaN doesn't serialize — pipeline may need float conversion
- The `wraps=` patch may need the correct import path matching sessions_v2.py's import

**Step 3: Run existing tests to verify no regressions**

Run: `pytest telemetry_tool/tests/test_data_api_v2.py -v`
Run: `pytest telemetry_tool/tests/test_upload_sync.py -v`
Run: `pytest telemetry_tool/tests/test_re_port_correctness.py -v`
Expected: All PASS (endpoint changes should not break existing tests that mock DB)

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete parity harness — 7 tolerance tests + missing-data contract"
```

---

## Summary

| Task | What | Type |
|------|------|------|
| 1 | Add DATA_UNAVAILABLE error code | Infra |
| 2 | Fix scores endpoint — structured unavailability | Endpoint fix |
| 3 | Fix speed-trace + gps-trace endpoints | Endpoint fix |
| 4 | Fix sector_times endpoint | Endpoint fix |
| 5 | Add reason_code to GG + corners | Endpoint fix |
| 6 | Synthetic CSV generator + upload fixture | Test infra |
| 7 | Tolerance contract + assertion helpers | Test infra |
| 8 | test_scores_parity | Parity test |
| 9 | test_laps_parity | Parity test |
| 10 | test_speed_trace_parity | Parity test |
| 11 | test_gps_trace_parity | Parity test |
| 12 | test_corners_parity | Parity test |
| 13 | test_sectors_parity + test_gg_data_parity | Parity test |
| 14 | test_missing_data_contract | Contract test |
| 15 | Full suite run + regression check | Verification |

**Run command:** `pytest telemetry_tool/tests/test_parity_harness.py -v`
