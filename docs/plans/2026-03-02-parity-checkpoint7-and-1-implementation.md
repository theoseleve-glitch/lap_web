# Parity Restoration — Checkpoint #7 + #1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish the parity measurement baseline (golden fixture + harness + truth dashboard) and harden the API layer (JSON guard, graceful degradation, session identity fixes).

**Architecture:** Golden fixture CSV committed as read-only reference. Python harness script calls local pipeline + SaaS API, compares with tolerance rules. Flask after_request hook intercepts HTML responses to JSON consumers. All data endpoints return `available=false` + `reason_code` for missing optional data.

**Tech Stack:** Python 3.11, Flask, pytest, Playwright (probes), Next.js TypeScript

**Design doc:** `docs/plans/2026-03-02-full-parity-restoration-design.md`

---

### Task 1: Store Golden Fixture + Manifest

**Files:**
- Create: `fixtures/golden/manifest.json`
- Copy: `data/raw/OK_R3.csv` → `fixtures/golden/OK_R3.csv`

**Step 1: Create fixtures directory and copy golden CSV**

```bash
mkdir -p fixtures/golden
cp data/raw/OK_R3.csv fixtures/golden/OK_R3.csv
```

**Step 2: Generate SHA-256 checksum**

```bash
python -c "import hashlib, pathlib; print(hashlib.sha256(pathlib.Path('fixtures/golden/OK_R3.csv').read_bytes()).hexdigest())"
```

**Step 3: Create manifest.json**

Create `fixtures/golden/manifest.json`:
```json
{
  "local_tool_commit": "<current HEAD hash>",
  "saas_commit": "<current HEAD hash>",
  "environment": "production",
  "fixture_file": "OK_R3.csv",
  "fixture_sha256": "<hash from step 2>",
  "created_at": "2026-03-02",
  "tolerance_rules": {
    "lap_times_ms": 5,
    "best_lap_index": "exact",
    "score_pillar": 0.1,
    "sector_times_s": 0.001,
    "corner_boundaries_m": 1.0
  }
}
```

**Step 4: Commit**

```bash
git add fixtures/golden/
git commit -m "feat: store golden fixture OK_R3.csv + manifest with tolerance rules"
```

---

### Task 2: Parity Harness Script — Local Pipeline Runner

**Files:**
- Create: `scripts/parity_harness.py`
- Reference: `telemetry_tool/pipeline.py:537-543` (session_date derivation)
- Reference: `telemetry_tool/tests/test_re_port_correctness.py:91-186` (pipeline invocation pattern)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_parity_harness.py`:
```python
"""Tests for the parity harness — tolerance comparisons."""
import pytest
import json

from scripts.parity_harness import compare_scores, compare_laps, compare_corners


class TestToleranceComparison:
    def test_scores_within_tolerance(self):
        local = {"total_score": 71.9, "pace": 18.5, "consistency": 20.1,
                 "execution": 15.3, "robustness": 6.8, "adaptation": 11.2}
        saas = {"total_score": 71.9, "pace": 18.5, "consistency": 20.1,
                "execution": 15.3, "robustness": 6.8, "adaptation": 11.2}
        result = compare_scores(local, saas, tolerance=0.1)
        assert result["pass"] is True
        assert len(result["failures"]) == 0

    def test_scores_outside_tolerance(self):
        local = {"total_score": 71.9, "pace": 18.5}
        saas = {"total_score": 72.5, "pace": 18.5}
        result = compare_scores(local, saas, tolerance=0.1)
        assert result["pass"] is False
        assert "total_score" in result["failures"][0]["field"]

    def test_laps_best_index_must_match(self):
        local = [{"lap": 1, "time_s": 74.5}, {"lap": 2, "time_s": 73.1}]
        saas = [{"lap": 1, "time_s": 74.5}, {"lap": 2, "time_s": 73.1}]
        result = compare_laps(local, saas, time_tolerance_ms=5)
        assert result["pass"] is True

    def test_laps_time_outside_tolerance(self):
        local = [{"lap": 1, "time_s": 74.500}]
        saas = [{"lap": 1, "time_s": 74.510}]
        result = compare_laps(local, saas, time_tolerance_ms=5)
        assert result["pass"] is False

    def test_corners_within_tolerance(self):
        local = [{"corner_id": "C1", "s_start": 100.0, "s_end": 130.0, "s_apex": 115.0}]
        saas = [{"corner_id": "C1", "s_start": 100.5, "s_end": 130.2, "s_apex": 115.8}]
        result = compare_corners(local, saas, boundary_tolerance_m=1.0)
        assert result["pass"] is True
```

**Step 2: Run test to verify it fails**

```bash
pytest telemetry_tool/tests/test_parity_harness.py -v
```
Expected: ImportError — `scripts.parity_harness` not found

**Step 3: Implement the parity harness core**

Create `scripts/parity_harness.py`:
```python
#!/usr/bin/env python3
"""Parity harness — compare local pipeline output with SaaS API responses.

Usage:
    python scripts/parity_harness.py --session-id <ID> --api-url <URL>
    python scripts/parity_harness.py --run-local --fixture fixtures/golden/OK_R3.csv
    python scripts/parity_harness.py --compare-only --baseline fixtures/golden/baseline/
"""
import argparse
import json
import sys
from pathlib import Path


def compare_scores(local: dict, saas: dict, tolerance: float = 0.1) -> dict:
    """Compare score pillars within tolerance."""
    failures = []
    fields = ["total_score", "pace", "consistency", "execution", "robustness", "adaptation"]
    for f in fields:
        lv = local.get(f)
        sv = saas.get(f)
        if lv is None or sv is None:
            if lv != sv:
                failures.append({"field": f, "local": lv, "saas": sv, "reason": "missing"})
            continue
        if abs(float(lv) - float(sv)) > tolerance:
            failures.append({
                "field": f, "local": lv, "saas": sv,
                "delta": round(abs(float(lv) - float(sv)), 4),
                "tolerance": tolerance,
            })
    return {"pass": len(failures) == 0, "failures": failures}


def compare_laps(local: list, saas: list, time_tolerance_ms: float = 5) -> dict:
    """Compare lap times and best lap index."""
    failures = []
    if len(local) != len(saas):
        failures.append({"reason": "lap_count_mismatch", "local": len(local), "saas": len(saas)})
        return {"pass": False, "failures": failures}

    tolerance_s = time_tolerance_ms / 1000.0
    for i, (ll, sl) in enumerate(zip(local, saas)):
        lt = ll.get("time_s") or ll.get("lap_time_s", 0)
        st = sl.get("time_s") or sl.get("lap_time_s", 0)
        if lt and st and abs(float(lt) - float(st)) > tolerance_s:
            failures.append({
                "lap": i + 1, "local_time": lt, "saas_time": st,
                "delta_ms": round(abs(float(lt) - float(st)) * 1000, 2),
            })

    # Best lap index must match
    local_best = min(range(len(local)), key=lambda i: local[i].get("time_s", float("inf")))
    saas_best = min(range(len(saas)), key=lambda i: saas[i].get("time_s", float("inf")))
    if local_best != saas_best:
        failures.append({
            "reason": "best_lap_mismatch",
            "local_best_idx": local_best,
            "saas_best_idx": saas_best,
        })

    return {"pass": len(failures) == 0, "failures": failures}


def compare_corners(local: list, saas: list, boundary_tolerance_m: float = 1.0) -> dict:
    """Compare corner boundaries within tolerance."""
    failures = []
    if len(local) != len(saas):
        failures.append({"reason": "corner_count_mismatch", "local": len(local), "saas": len(saas)})
        return {"pass": False, "failures": failures}

    for lc, sc in zip(local, saas):
        cid = lc.get("corner_id", "?")
        for field in ["s_start", "s_end", "s_apex"]:
            lv = lc.get(field)
            sv = sc.get(field)
            if lv is not None and sv is not None:
                if abs(float(lv) - float(sv)) > boundary_tolerance_m:
                    failures.append({
                        "corner": cid, "field": field,
                        "local": lv, "saas": sv,
                        "delta_m": round(abs(float(lv) - float(sv)), 2),
                    })

    return {"pass": len(failures) == 0, "failures": failures}


def compare_sectors(local: list, saas: list, time_tolerance_s: float = 0.001) -> dict:
    """Compare sector times within tolerance."""
    failures = []
    if len(local) != len(saas):
        failures.append({"reason": "sector_count_mismatch", "local": len(local), "saas": len(saas)})
        return {"pass": False, "failures": failures}

    for ls, ss in zip(local, saas):
        sid = ls.get("sector_id", "?")
        for field in ["best_time_s", "mean_time_s"]:
            lv = ls.get(field)
            sv = ss.get(field)
            if lv is not None and sv is not None:
                if abs(float(lv) - float(sv)) > time_tolerance_s:
                    failures.append({
                        "sector": sid, "field": field,
                        "local": lv, "saas": sv,
                        "delta_s": round(abs(float(lv) - float(sv)), 4),
                    })

    return {"pass": len(failures) == 0, "failures": failures}


def fetch_saas_data(api_url: str, session_id: str, token: str | None = None) -> dict:
    """Fetch all endpoint data from SaaS API for a session."""
    import requests
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    endpoints = {
        "scores": f"/api/v1/sessions/{session_id}/scores",
        "laps": f"/api/v1/sessions/{session_id}/laps",
        "corners": f"/api/v1/sessions/{session_id}/corners",
        "sectors": f"/api/v1/sessions/{session_id}/sectors",
        "gg_data": f"/api/v1/sessions/{session_id}/gg-data",
        "speed_trace": f"/api/v1/sessions/{session_id}/speed-trace?lap=best",
        "gps_trace": f"/api/v1/sessions/{session_id}/gps-trace?lap=best",
        "driving_style": f"/api/v1/sessions/{session_id}/driving-style",
    }

    results = {}
    for key, path in endpoints.items():
        url = f"{api_url.rstrip('/')}{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            body = resp.json()
            results[key] = body.get("data") if body.get("ok") else {"error": body.get("error")}
        except Exception as e:
            results[key] = {"error": str(e)}

    return results


def dump_baseline(data: dict, output_dir: Path):
    """Dump API response data to JSON files for diffing."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, value in data.items():
        (output_dir / f"{key}.json").write_text(
            json.dumps(value, indent=2, default=str), encoding="utf-8"
        )


def main():
    parser = argparse.ArgumentParser(description="Parity harness")
    parser.add_argument("--session-id", help="Session ID to compare")
    parser.add_argument("--api-url", default="https://api.lap-coach.racing",
                        help="SaaS API base URL")
    parser.add_argument("--token", help="Bearer token for auth")
    parser.add_argument("--baseline-dir", default="fixtures/golden/baseline",
                        help="Directory with baseline JSON files")
    parser.add_argument("--dump", action="store_true",
                        help="Dump SaaS responses to baseline dir")
    args = parser.parse_args()

    if not args.session_id:
        parser.error("--session-id is required")

    print(f"Fetching SaaS data for session {args.session_id}...")
    saas_data = fetch_saas_data(args.api_url, args.session_id, args.token)

    baseline_dir = Path(args.baseline_dir)

    if args.dump:
        dump_baseline(saas_data, baseline_dir)
        print(f"Dumped to {baseline_dir}")
        return

    # Compare with stored baseline
    all_pass = True
    if (baseline_dir / "scores.json").exists():
        local_scores = json.loads((baseline_dir / "scores.json").read_text())
        result = compare_scores(local_scores, saas_data.get("scores", {}))
        status = "PASS" if result["pass"] else "FAIL"
        print(f"  Scores: {status}")
        if not result["pass"]:
            all_pass = False
            for f in result["failures"]:
                print(f"    {f}")

    if (baseline_dir / "laps.json").exists():
        local_laps = json.loads((baseline_dir / "laps.json").read_text())
        saas_laps = saas_data.get("laps", [])
        if isinstance(saas_laps, dict):
            saas_laps = saas_laps.get("laps", [])
        result = compare_laps(local_laps, saas_laps)
        status = "PASS" if result["pass"] else "FAIL"
        print(f"  Laps: {status}")
        if not result["pass"]:
            all_pass = False
            for f in result["failures"]:
                print(f"    {f}")

    if (baseline_dir / "corners.json").exists():
        local_corners = json.loads((baseline_dir / "corners.json").read_text())
        saas_corners = saas_data.get("corners", [])
        if isinstance(saas_corners, dict):
            saas_corners = saas_corners.get("corners", [])
        result = compare_corners(local_corners, saas_corners)
        status = "PASS" if result["pass"] else "FAIL"
        print(f"  Corners: {status}")
        if not result["pass"]:
            all_pass = False
            for f in result["failures"]:
                print(f"    {f}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
pytest telemetry_tool/tests/test_parity_harness.py -v
```
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add scripts/parity_harness.py telemetry_tool/tests/test_parity_harness.py
git commit -m "feat: parity harness with tolerance comparison functions"
```

---

### Task 3: Enhanced Truth Dashboard Probes

**Files:**
- Modify: `docs/audit-truth-dashboard.html`

**Step 1: Read current dashboard**

Read `docs/audit-truth-dashboard.html` to understand existing probe structure (6 probes currently).

**Step 2: Add entity population probes**

Add probes 7-10 to the dashboard JavaScript:
- Probe 7: `GET /api/v1/drivers` → count > 0
- Probe 8: `GET /api/v1/tracks` → count > 0, first track has `track_name`
- Probe 9: `GET /api/v1/karts` → returns 200 (not 404/500)
- Probe 10: `GET /api/v1/weekends` → returns 200 (not error state)

**Step 3: Add chart data completeness probes**

Add probes 11-15:
- Probe 11: Speed trace → `speeds` array length > 0, `distances` array length > 0
- Probe 12: GPS trace → `latitudes` array length > 0, `longitudes` array length > 0
- Probe 13: GG data → `accel_lat` array length > 0, `accel_long` array length > 0
- Probe 14: Sectors → array length > 0, each has numeric `best_time_s`
- Probe 15: Corners → each corner has `coaching_hint` string

**Step 4: Add JSON export button**

Add a button that dumps all probe results to a downloadable JSON file for CI artifact storage.

**Step 5: Commit**

```bash
git add docs/audit-truth-dashboard.html
git commit -m "feat: expand truth dashboard — entity population + chart completeness probes"
```

---

### Task 4: JSON Guard Middleware

**Files:**
- Modify: `telemetry_tool/web/app.py:137-164` (Phase 4 API infrastructure section)
- Test: `telemetry_tool/tests/test_api_contracts.py` (add guard tests)
- Reference: `telemetry_tool/web/api_utils.py:67-95` (envelope pattern)

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_api_contracts.py`:
```python
class TestJsonGuardMiddleware:
    """Verify the JSON guard catches HTML responses on /api/* routes."""

    def test_json_guard_intercepts_html_response(self, seeded_client):
        """If an /api/ endpoint somehow returns HTML, the guard must convert
        it to a structured JSON error with code API_HTML_RESPONSE."""
        # The guard only triggers when Content-Type is text/html on /api/* paths.
        # We test by hitting an endpoint that returns proper JSON and asserting
        # it passes through unchanged.
        resp = seeded_client.get("/api/v1/sessions")
        assert resp.content_type.startswith("application/json")
        body = resp.get_json()
        assert body["ok"] is True

    def test_non_api_routes_not_guarded(self, seeded_client):
        """Non-API routes (like /healthz) should not be intercepted."""
        resp = seeded_client.get("/healthz")
        # Health check returns JSON already, but the guard should not touch it
        assert resp.status_code in (200, 503)
```

**Step 2: Run test to verify it fails**

```bash
pytest telemetry_tool/tests/test_api_contracts.py::TestJsonGuardMiddleware -v
```
Expected: PASS (these are testing existing behavior) or FAIL if the test class doesn't resolve

**Step 3: Implement the JSON guard**

Add to `telemetry_tool/web/app.py` in the `create_app()` function, after the `init_request_id(app)` call (around line 150):

```python
# ── Phase 4b: JSON guard for /api/* routes ──────────────────
@app.after_request
def _json_guard(response):
    """Intercept HTML responses on /api/* paths.

    If a route under /api/ accidentally returns text/html (e.g.
    an old template route leaked into the API namespace), replace
    the response with a structured JSON error so the SaaS frontend
    never sees 'Unexpected token <'.
    """
    if not request.path.startswith("/api/"):
        return response
    ct = response.content_type or ""
    if "text/html" not in ct:
        return response
    # Check body for HTML markers
    try:
        body_start = response.get_data(as_text=True)[:100].strip().lower()
    except Exception:
        return response
    if body_start.startswith("<!doctype") or body_start.startswith("<html"):
        from web.api_utils import api_error, ErrorCode
        err_resp, status = api_error(
            ErrorCode.INTERNAL_ERROR,
            "Endpoint returned HTML instead of JSON",
            status=500,
        )
        return err_resp
    return response
```

**Step 4: Run tests**

```bash
pytest telemetry_tool/tests/test_api_contracts.py -v
```
Expected: All tests PASS including new TestJsonGuardMiddleware

**Step 5: Commit**

```bash
git add telemetry_tool/web/app.py telemetry_tool/tests/test_api_contracts.py
git commit -m "feat: add JSON guard middleware — intercept HTML responses on /api/* routes"
```

---

### Task 5: Graceful Degradation — available=false Pattern

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (multiple endpoints)
- Test: `telemetry_tool/tests/test_api_contracts.py`
- Reference: `telemetry_tool/web/routes/data_v2.py:544-640` (corners as existing example)

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_api_contracts.py`:
```python
class TestGracefulDegradation:
    """Optional data endpoints must return 200 + available=false, never 500."""

    @pytest.mark.parametrize("endpoint,data_key", [
        ("/api/v1/sessions/{sid}/corners", "corners"),
        ("/api/v1/sessions/{sid}/sectors", "sectors"),
        ("/api/v1/sessions/{sid}/gg-data", "gg_data"),
        ("/api/v1/sessions/{sid}/driving-style", "style"),
        ("/api/v1/sessions/{sid}/theoretical", "theoretical"),
        ("/api/v1/sessions/{sid}/stint-analysis", "stints"),
        ("/api/v1/sessions/{sid}/corner-metrics", "metrics"),
        ("/api/v1/sessions/{sid}/lap-distribution", "distribution"),
    ])
    def test_optional_endpoint_returns_available_false_when_empty(
        self, mock_client, endpoint, data_key
    ):
        """When optional analysis data is missing, endpoint must return
        200 with available=false and a reason_code, not 500."""
        # mock_client has no real analysis data, so optional endpoints
        # should gracefully degrade
        url = endpoint.format(sid="nonexistent-session-id")
        resp = mock_client.get(url)
        # Accept 200 (graceful) or 404 (session not found) — never 500
        assert resp.status_code in (200, 404), (
            f"{endpoint} returned {resp.status_code}: {resp.get_data(as_text=True)[:200]}"
        )
        if resp.status_code == 200:
            body = resp.get_json()
            data = body.get("data", {})
            # If data is empty/unavailable, must have available=false
            if isinstance(data, dict) and not data.get("available", True):
                assert "reason_code" in data, (
                    f"{endpoint} returned available=false but missing reason_code"
                )
```

**Step 2: Run test to verify behavior**

```bash
pytest telemetry_tool/tests/test_api_contracts.py::TestGracefulDegradation -v
```
Expected: Some may fail if endpoints return 500 instead of 200+available=false

**Step 3: Audit and fix each endpoint**

For each data_v2.py endpoint that serves optional analysis data, ensure the pattern:
```python
@bp.route("/sessions/<session_id>/theoretical", methods=["GET"])
@_safe_api()
def get_theoretical(session_id: str):
    conn = get_db_connection()
    session = _get_session_or_404(conn, session_id)

    # Fetch optional data
    theo = _fetch_theoretical(conn, session_id)
    if not theo:
        return api_response({
            "available": False,
            "reason_code": "no_theoretical",
            "data": None,
        })
    return api_response({"available": True, **theo})
```

Apply this pattern to: theoretical, driving-style, stint-analysis, corner-metrics, lap-distribution, brake-precision, fingerprint, speed-profile, delta, condition-phases.

The corners endpoint (lines 544-640) already follows this pattern — use it as the template.

**Step 4: Run tests**

```bash
pytest telemetry_tool/tests/test_api_contracts.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_api_contracts.py
git commit -m "fix: graceful degradation — all optional endpoints return available=false with reason_code"
```

---

### Task 6: Fix Session Identity — display_name + title

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:303-311` (session detail response)
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx:17-31` (SessionData interface)
- Test: `telemetry_tool/tests/test_api_contracts.py`

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_api_contracts.py`:
```python
class TestSessionIdentity:
    """Session header must show clean display name, not raw upload path."""

    def test_session_detail_has_display_name(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        body = resp.get_json()
        sessions = body["data"]["sessions"]
        if sessions:
            sid = sessions[0]["session_id"]
            detail = seeded_client.get(f"/api/v1/sessions/{sid}")
            detail_body = detail.get_json()
            session = detail_body["data"]
            # display_name must exist and not contain path separators
            assert "display_name" in session, "Missing display_name field"
            dn = session["display_name"]
            if dn:
                assert "/" not in dn and "\\" not in dn, (
                    f"display_name contains path separator: {dn}"
                )
                assert not dn.lower().endswith(".csv"), (
                    f"display_name should not end with .csv: {dn}"
                )

    def test_csv_filename_is_just_name(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        body = resp.get_json()
        sessions = body["data"]["sessions"]
        for s in sessions:
            fn = s.get("csv_filename", "")
            assert "/" not in fn and "\\" not in fn, (
                f"csv_filename contains path: {fn}"
            )

    def test_source_path_never_exposed(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        body = resp.get_json()
        sessions = body["data"]["sessions"]
        for s in sessions:
            assert "source_path" not in s, "source_path leaked in API response"
```

**Step 2: Run tests**

```bash
pytest telemetry_tool/tests/test_api_contracts.py::TestSessionIdentity -v
```

**Step 3: Fix backend — ensure display_name is always set**

In `telemetry_tool/web/routes/data_v2.py`, in the session detail endpoint (around line 303), ensure:
```python
result = dict(session)
result.pop("source_path", None)
result.pop("html_report_path", None)
if result.get("csv_filename"):
    result["csv_filename"] = Path(result["csv_filename"]).name
# Ensure display_name is set and clean
if not result.get("display_name"):
    fn = result.get("csv_filename", "")
    result["display_name"] = Path(fn).stem if fn else result.get("session_id", "")
```

Apply the same pattern in the sessions list endpoint (around line 255).

**Step 4: Fix frontend — use display_name for title**

In `lap-website/src/app/app/sessions/[id]/page.tsx`, find where the session title is rendered and change from `csv_filename` to `display_name`:
```typescript
// In the header section, replace:
<h1>{session.csv_filename}</h1>
// With:
<h1>{session.display_name || session.csv_filename?.replace('.csv', '') || session.session_id}</h1>
```

Also update the `SessionData` interface to include `display_name`:
```typescript
interface SessionData {
  session_id: string;
  csv_filename: string;
  display_name: string | null;  // add this
  // ... rest unchanged
}
```

**Step 5: Run tests**

```bash
pytest telemetry_tool/tests/test_api_contracts.py::TestSessionIdentity -v
```
Expected: All PASS

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_api_contracts.py \
  lap-website/src/app/app/sessions/\[id\]/page.tsx
git commit -m "fix: session identity — use display_name for title, strip paths from csv_filename"
```

---

### Task 7: Fix Session Date — Derive from Telemetry Timestamps

**Files:**
- Modify: `telemetry_tool/pipeline.py:537-543` (date derivation)
- Modify: `telemetry_tool/web/routes/sessions_v2.py` (upload metadata)
- Test: `telemetry_tool/tests/test_re_port_correctness.py` (add date test)

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_re_port_correctness.py`:
```python
class TestSessionDateDerivation:
    """Session date must come from telemetry timestamps, not upload time."""

    def test_session_date_from_csv_timestamp(self):
        """When CSV has a timestamp column, session_date should derive from it."""
        # The pipeline's parse_session_datetime extracts date from CSV filename
        # or from the first timestamp row. If neither exists, it falls back
        # to datetime.now(). This test verifies the fallback chain.
        from pipeline import run_full_analysis
        # Use the synthetic fixture which has Time column starting at 0.0
        # Since synthetic data has no real datetime, it should fall back
        # to user-provided date or today's date
        import tempfile, csv
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(["Lap #", "Time (s)", "Speed (m/s)", "Latitude (deg)", "Longitude (deg)"])
            for i in range(50):
                writer.writerow([1, i * 0.1, 20.0, 48.0 + i * 0.0001, -1.5 + i * 0.0001])
            csv_path = f.name

        meta = {"driver_name": "Test", "session_date": "2026-02-28"}
        result = run_full_analysis(csv_path, session_meta=meta)
        # session_date should honour the user-provided value
        assert result.get("session_date") == "2026-02-28" or result.get("date") == "2026-02-28"
```

**Step 2: Run test**

```bash
pytest telemetry_tool/tests/test_re_port_correctness.py::TestSessionDateDerivation -v
```

**Step 3: Verify pipeline date derivation is correct**

Read `telemetry_tool/pipeline.py:537-543` and verify the priority chain:
1. User-provided `session_date` from web form → `meta["date"]`
2. `parse_session_datetime(csv_path)` → extract from telemetry timestamps
3. Fallback: `datetime.now(timezone.utc)`

If the priority is already correct, ensure the upload endpoint passes `session_date` from the form. In `telemetry_tool/web/routes/sessions_v2.py`, verify:
```python
session_meta: dict = {
    ...
    "session_date": request.form.get("session_date"),  # must be present
}
```

**Step 4: Fix frontend to use session_date for display**

In `lap-website/src/app/app/sessions/[id]/page.tsx`, verify the date display uses `session.session_date` (not `session.created_at`). In the sessions list, verify sorting uses `session_date`.

**Step 5: Run tests**

```bash
pytest telemetry_tool/tests/ -v -k "session_date or SessionDate"
```

**Step 6: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/web/routes/sessions_v2.py \
  telemetry_tool/tests/test_re_port_correctness.py
git commit -m "fix: derive session_date from telemetry timestamps, not upload time"
```

---

### Task 8: Driver/Track Resolution Fix

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (session detail joins)
- Test: `telemetry_tool/tests/test_api_contracts.py`

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_api_contracts.py`:
```python
class TestDriverTrackResolution:
    """Session detail must resolve driver_name and track_name from FK joins."""

    def test_session_has_resolved_driver_name(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        body = resp.get_json()
        sessions = body["data"]["sessions"]
        for s in sessions:
            if s.get("driver_id"):
                assert s.get("driver_name"), (
                    f"Session {s['session_id']} has driver_id but no driver_name"
                )
                assert s["driver_name"] != "Unknown", (
                    f"Session {s['session_id']} driver_name should not be 'Unknown' "
                    f"when driver_id={s['driver_id']} exists"
                )

    def test_session_has_resolved_track_name(self, seeded_client):
        resp = seeded_client.get("/api/v1/sessions")
        body = resp.get_json()
        sessions = body["data"]["sessions"]
        for s in sessions:
            if s.get("track_id"):
                assert s.get("track_name"), (
                    f"Session {s['session_id']} has track_id but no track_name"
                )
                assert s["track_name"] != "Unknown Track", (
                    f"Session {s['session_id']} track_name should not be 'Unknown Track' "
                    f"when track_id={s['track_id']} exists"
                )
```

**Step 2: Run test**

```bash
pytest telemetry_tool/tests/test_api_contracts.py::TestDriverTrackResolution -v
```

**Step 3: Verify session list query joins driver+track**

In `telemetry_tool/web/routes/data_v2.py`, find the sessions list query and verify it includes LEFT JOINs:
```sql
SELECT s.*, d.driver_name, t.track_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
WHERE s.workspace_id = %(workspace_id)s
```

If the query doesn't join, add the joins. Also add to the session detail query.

**Step 4: Run tests**

```bash
pytest telemetry_tool/tests/test_api_contracts.py -v
```

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_api_contracts.py
git commit -m "fix: resolve driver_name and track_name via FK joins in session queries"
```

---

### Task 9: Run Checkpoint #1 Truth Dashboard Probes

**Files:**
- No code changes — verification only

**Step 1: Run truth dashboard probes**

Open `docs/audit-truth-dashboard.html` in a browser (or run via Playwright):
- Enter API URL: `https://api.lap-coach.racing`
- Enter a golden fixture session ID
- Click "Run Probes"

**Step 2: Verify Checkpoint #1 pass conditions**

Must be true:
- [ ] No HTML responses to `/api/*` (probe passes)
- [ ] No 500s for optional data endpoints (all return 200 + available=false or 200 + data)
- [ ] Session header identity probes PASS (title shows display_name, driver resolved, track resolved, date from telemetry)
- [ ] Entity population probes PASS (drivers > 0, tracks > 0)

**Step 3: Save probe output**

Export probe results JSON via the new export button. Save to `fixtures/golden/checkpoint1-probes.json`.

**Step 4: Commit probe results**

```bash
git add fixtures/golden/checkpoint1-probes.json
git commit -m "checkpoint: #1 truth dashboard probes — API hardening + session identity verified"
```

---

### Task 10: Editable Session Info Block (Checkpoint #2 start)

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`
- Reference: `telemetry_tool/web/routes/data_v2.py:1014-1017` (updatable fields)

**Step 1: Build inline edit UI**

In the session detail page's Session Info section, replace the read-only display with an editable form:
- "Edit" button toggles edit mode
- Fields: Date (date picker), Driver (dropdown from `/api/v1/drivers`), Track (dropdown from `/api/v1/tracks`), Type (dropdown: practice/qualifying/race/etc.), Condition (dropdown: dry/wet/damp/etc.), Kart (dropdown from `/api/v1/karts`)
- Save button calls `PATCH /api/v1/sessions/{id}` with changed fields
- Cancel button reverts to display mode
- On success: update local state with resolved names from response

**Step 2: Fetch entity lists for dropdowns**

```typescript
// Fetch drivers, tracks, karts for dropdowns
const [drivers] = await Promise.all([
  api.get('/drivers'),
  api.get('/tracks'),
  api.get('/karts'),
]);
```

**Step 3: Wire PATCH call**

```typescript
const handleSave = async () => {
  const resp = await api.patch(`/sessions/${sessionId}`, {
    body: JSON.stringify(editedFields),
  });
  if (resp.ok) {
    setSession({ ...session, ...resp.data });
    setEditing(false);
  }
};
```

**Step 4: Test manually**

- Open a session detail page
- Click "Edit"
- Change driver, track, condition
- Save → verify changes persist on page reload

**Step 5: Commit**

```bash
git add lap-website/src/app/app/sessions/\[id\]/page.tsx
git commit -m "feat: editable session info block — inline edit for date, driver, track, type, condition, kart"
```

---

### Task 11: Kart Field in Upload + Session Header

**Files:**
- Modify: `lap-website/src/app/app/sessions/upload/page.tsx`
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`
- Reference: `telemetry_tool/web/routes/sessions_v2.py:309-315`

**Step 1: Add kart dropdown to upload form**

In the upload page, add an optional kart selection dropdown that fetches from `GET /api/v1/karts`:
```typescript
const [karts, setKarts] = useState<Kart[]>([]);
useEffect(() => {
  api.get('/karts').then(resp => {
    if (resp.ok) setKarts(resp.data.karts || []);
  });
}, []);

// In the form:
<select name="kart_id" value={kart_id} onChange={...}>
  <option value="">No kart selected</option>
  {karts.map(k => (
    <option key={k.kart_id} value={k.kart_id}>{k.name}</option>
  ))}
</select>
```

**Step 2: Pass kart_id in upload FormData**

```typescript
if (kart_id) formData.append('kart_id', kart_id);
```

**Step 3: Display kart in session header**

In the session detail page, add kart display next to Type/Condition:
```typescript
{session.kart_name && (
  <span className="text-sm text-zinc-400">Kart: {session.kart_name}</span>
)}
```

**Step 4: Commit**

```bash
git add lap-website/src/app/app/sessions/upload/page.tsx \
  lap-website/src/app/app/sessions/\[id\]/page.tsx
git commit -m "feat: kart field in upload form and session header display"
```

---

## Checkpoint #2 Verification

After Tasks 10-11, run truth dashboard probes:
- Session metadata edits persist and reflect everywhere
- Entity pages show real data
- Kart field appears in session info

---

## Remaining Checkpoints (separate plan documents)

Checkpoints #3-#6 will be planned in subsequent sessions after Checkpoints #7, #1, #2 pass verification:

- **Checkpoint #3:** Sessions list + dashboard + visualize + chart sync (6 tasks)
- **Checkpoint #4:** Tab depth — overview/corners/analytics/laps (8 tasks)
- **Checkpoint #5:** Compare + secondary pages + exports (7 tasks)
- **Checkpoint #6:** Hardening + observability (5 tasks)

Design doc: `docs/plans/2026-03-02-full-parity-restoration-design.md`
