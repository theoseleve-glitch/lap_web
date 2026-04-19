# Cross-Session Reference Lap Overlay — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users overlay a lap from a different session onto the speed trace, track map, and GG explorer — on both the session detail page and the compare page — with dual hover markers.

**Architecture:** One composite backend endpoint returns speed + GPS + GG data for both laps distance-aligned. A React context provider fetches once and distributes to all charts. A FAB + modal lets users pick the reference session/lap. Each chart renders the overlay in racing-purple dashed style.

**Tech Stack:** Python/Flask (backend), React/TypeScript/Canvas (frontend), NumPy (interpolation), Zustand (hover sync)

**Spec:** `docs/superpowers/specs/2026-04-14-cross-session-reference-overlay-design.md`

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `lap-website/src/components/app/reference/types.ts` | TypeScript interfaces for reference overlay data |
| `lap-website/src/components/app/reference/ReferenceOverlayProvider.tsx` | Context provider — fetches composite data, distributes to charts |
| `lap-website/src/components/app/reference/ReferenceFAB.tsx` | Floating action button + modal picker |
| `lap-website/src/components/app/reference/index.ts` | Barrel export |
| `telemetry_tool/tests/test_reference_overlay.py` | Backend endpoint tests |
| `lap-website/src/__tests__/reference-overlay.test.tsx` | Frontend component tests |

### Modified files
| File | Changes |
|------|---------|
| `telemetry_tool/web/routes/data_v2.py` | Add `reference_candidates` + `reference_data` endpoint functions |
| `lap-website/src/components/shared/charts/SpeedTraceChart.tsx` | Consume reference context, draw dashed purple overlay + delta bar + dual hover marker |
| `lap-website/src/components/shared/charts/TrackMap.tsx` | Consume reference context, draw dashed purple GPS path + dual hover marker |
| `lap-website/src/components/shared/charts/GGExplorer.tsx` | Consume reference context, draw hollow purple scatter + dual hover marker |
| `lap-website/src/components/app/analytics/AnalyticsTab.tsx` | Wrap Row 1 charts in ReferenceOverlayProvider, add ReferenceFAB |
| `lap-website/src/app/app/compare/sessions/page.tsx` | Add TrackMap + GGExplorer overlays, wrap in ChartSyncProvider |

---

## Task 1: Backend — reference-candidates endpoint

Returns sessions on the same track as the current session, for populating the picker dropdown.

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (append near end, before any `if __name__` block)
- Test: `telemetry_tool/tests/test_reference_overlay.py`

- [ ] **Step 1: Write the failing test**

Create `telemetry_tool/tests/test_reference_overlay.py`:

```python
"""Tests for cross-session reference overlay endpoints."""
import json
import pytest


@pytest.fixture
def two_sessions_same_track(seeded_db):
    """Seed two sessions on the same track with GPS traces."""
    conn = seeded_db
    # seeded_db already has a session — grab its ID and track_name
    row = conn.execute(
        "SELECT session_id, track_name FROM sessions LIMIT 1"
    ).fetchone()
    existing_id = row["session_id"]
    track_name = row["track_name"]

    # Insert a second session on the same track
    import uuid
    second_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO sessions (session_id, driver_name, track_name, session_date,
           n_laps, best_lap_time_s, session_type, workspace_id)
           VALUES (?, ?, ?, '2026-04-10', 12, 44.8, 'practice', 'default')""",
        (second_id, "RefDriver", track_name),
    )
    # Insert a lap for the second session
    conn.execute(
        """INSERT INTO laps (session_id, lap_number, lap_time_s, is_best)
           VALUES (?, 1, 44.8, 1)""",
        (second_id,),
    )
    # Insert GPS trace for the second session's lap
    import numpy as np
    n = 100
    dists = np.linspace(0, 500, n).tolist()
    speeds = (np.random.uniform(10, 30, n)).tolist()
    lats = (np.linspace(51.0, 51.005, n)).tolist()
    lons = (np.linspace(-1.0, -0.995, n)).tolist()
    accel_lat = (np.random.uniform(-1.5, 1.5, n)).tolist()
    accel_long = (np.random.uniform(-2.0, 1.0, n)).tolist()
    conn.execute(
        """INSERT INTO gps_traces
           (session_id, lap_number, distances_json, speeds_json,
            latitudes_json, longitudes_json, accel_lat_json, accel_long_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (second_id, 1,
         json.dumps(dists), json.dumps(speeds),
         json.dumps(lats), json.dumps(lons),
         json.dumps(accel_lat), json.dumps(accel_long)),
    )
    conn.commit()
    return existing_id, second_id, track_name


def test_reference_candidates_returns_same_track_sessions(client, two_sessions_same_track):
    existing_id, second_id, track_name = two_sessions_same_track
    resp = client.get(f"/api/v1/sessions/{existing_id}/reference-candidates")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    candidates = body["data"]
    # Should contain the second session, NOT the current session
    candidate_ids = [c["session_id"] for c in candidates]
    assert second_id in candidate_ids
    assert existing_id not in candidate_ids
    # Check fields
    match = next(c for c in candidates if c["session_id"] == second_id)
    assert match["driver_name"] == "RefDriver"
    assert match["best_lap_time_s"] == 44.8


def test_reference_candidates_404_for_unknown_session(client):
    resp = client.get("/api/v1/sessions/nonexistent/reference-candidates")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_reference_overlay.py -v -k "candidates"`
Expected: FAIL — endpoint not found (404 from Flask, not our 404)

- [ ] **Step 3: Implement the endpoint**

Add to `telemetry_tool/web/routes/data_v2.py` (near the other session endpoints):

```python
@bp.route("/sessions/<session_id>/reference-candidates", methods=["GET"])
@_safe_api
def get_reference_candidates(session_id: str) -> tuple[dict, int]:
    """Return sessions on the same track for the reference picker."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    track_name = session.get("track_name")
    if not track_name:
        return api_response([])

    try:
        limit = max(1, min(int(request.args.get("limit", 20)), 50))
    except (ValueError, TypeError):
        limit = 20

    ws_id = getattr(g, "workspace_id", "default")
    rows = conn.execute(
        """SELECT session_id, driver_name, session_date, best_lap_time_s,
                  n_laps, session_type
           FROM sessions
           WHERE track_name = :track AND session_id != :sid
                 AND workspace_id = :ws
           ORDER BY session_date DESC
           LIMIT :lim""",
        {"track": track_name, "sid": session_id, "ws": ws_id, "lim": limit},
    ).fetchall()

    candidates = [
        {
            "session_id": r["session_id"],
            "driver_name": r["driver_name"],
            "session_date": r["session_date"],
            "best_lap_time_s": r["best_lap_time_s"],
            "n_laps": r["n_laps"],
            "session_type": r["session_type"],
        }
        for r in rows
    ]
    return api_response(candidates)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_reference_overlay.py -v -k "candidates"`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_reference_overlay.py
git commit -m "feat(api): add reference-candidates endpoint for cross-session picker"
```

---

## Task 2: Backend — reference-data composite endpoint

Returns speed, GPS, and GG for both primary and reference laps, distance-aligned.

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`
- Test: `telemetry_tool/tests/test_reference_overlay.py`

- [ ] **Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_reference_overlay.py`:

```python
def test_reference_data_returns_aligned_composite(client, two_sessions_same_track):
    existing_id, second_id, _ = two_sessions_same_track
    # Need to know the lap numbers — existing session uses seeded_db laps
    resp = client.get(
        f"/api/v1/sessions/{existing_id}/reference-data"
        f"?ref_session={second_id}&ref_lap=1&primary_lap=1"
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    d = body["data"]
    # Check structure
    assert "distances" in d
    assert "speed" in d
    assert "gps" in d
    assert "gg" in d
    assert "primary" in d
    assert "reference" in d
    # Check distance array is non-empty and sorted
    dists = d["distances"]
    assert len(dists) > 0
    assert dists == sorted(dists)
    # Check all arrays same length
    n = len(dists)
    assert len(d["speed"]["primary"]) == n
    assert len(d["speed"]["reference"]) == n
    assert len(d["speed"]["delta_s"]) == n
    assert len(d["gps"]["primary"]["latitudes"]) == n
    assert len(d["gps"]["reference"]["latitudes"]) == n
    assert len(d["gg"]["primary"]["accel_lat"]) == n
    assert len(d["gg"]["reference"]["accel_lat"]) == n
    # Check metadata
    assert d["reference"]["session_id"] == second_id
    assert d["reference"]["driver_name"] == "RefDriver"


def test_reference_data_missing_ref_session_returns_400(client, two_sessions_same_track):
    existing_id, _, _ = two_sessions_same_track
    resp = client.get(
        f"/api/v1/sessions/{existing_id}/reference-data?ref_lap=1&primary_lap=1"
    )
    assert resp.status_code == 400


def test_reference_data_cross_track_returns_400(client, seeded_db):
    """Two sessions on different tracks should be rejected."""
    conn = seeded_db
    import uuid
    other_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO sessions (session_id, driver_name, track_name, session_date,
           n_laps, best_lap_time_s, session_type, workspace_id)
           VALUES (?, 'X', 'OtherTrack', '2026-04-10', 5, 50.0, 'practice', 'default')""",
        (other_id,),
    )
    conn.commit()
    existing_id = conn.execute("SELECT session_id FROM sessions WHERE track_name != 'OtherTrack' LIMIT 1").fetchone()["session_id"]
    resp = client.get(
        f"/api/v1/sessions/{existing_id}/reference-data"
        f"?ref_session={other_id}&ref_lap=1&primary_lap=1"
    )
    assert resp.status_code == 400
    assert "track" in resp.get_json()["error"]["message"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_reference_overlay.py -v -k "reference_data"`
Expected: FAIL — endpoint not found

- [ ] **Step 3: Implement the endpoint**

Add to `telemetry_tool/web/routes/data_v2.py`:

```python
@bp.route("/sessions/<session_id>/reference-data", methods=["GET"])
@_safe_api
def get_reference_data(session_id: str) -> tuple[dict, int]:
    """Composite cross-session reference data: speed + GPS + GG, distance-aligned."""
    import numpy as np

    ref_session_id = request.args.get("ref_session")
    if not ref_session_id:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         "ref_session parameter is required", status=400)

    conn = get_db_connection()

    # ── Validate both sessions exist ──
    session_a = models.get_session_by_id(conn, session_id)
    if session_a is None:
        return api_error(ErrorCode.NOT_FOUND, "Primary session not found", status=404)

    session_b = models.get_session_by_id(conn, ref_session_id)
    if session_b is None:
        return api_error(ErrorCode.NOT_FOUND, "Reference session not found", status=404)

    # ── Guard: same track ──
    track_a = session_a.get("track_name", "")
    track_b = session_b.get("track_name", "")
    if track_a != track_b:
        return api_error(ErrorCode.VALIDATION_ERROR,
                         f"Track mismatch: primary is '{track_a}', reference is '{track_b}'",
                         status=400)

    # ── Resolve lap numbers ──
    try:
        primary_lap = int(request.args["primary_lap"])
    except (KeyError, ValueError, TypeError):
        primary_lap = _resolve_lap_number(conn, session_id)
    try:
        ref_lap = int(request.args["ref_lap"])
    except (KeyError, ValueError, TypeError):
        ref_lap = _resolve_lap_number(conn, ref_session_id)

    if primary_lap is None or ref_lap is None:
        return api_error(ErrorCode.NOT_FOUND, "No laps found in one or both sessions",
                         status=404)

    # ── Fetch traces ──
    trace_a = models.get_gps_trace(conn, session_id, primary_lap)
    trace_b = models.get_gps_trace(conn, ref_session_id, ref_lap)

    if trace_a is None or trace_b is None:
        return api_error(ErrorCode.NOT_FOUND,
                         "No GPS trace for one or both laps", status=404)

    dist_a = trace_a.get("distances") or []
    dist_b = trace_b.get("distances") or []
    spd_a = trace_a.get("speeds") or []
    spd_b = trace_b.get("speeds") or []

    if len(dist_a) < 2 or len(dist_b) < 2 or not spd_a or not spd_b:
        return api_error(ErrorCode.NOT_FOUND,
                         "Insufficient trace data for comparison", status=404)

    # ── Normalize to 0-based distances ──
    if dist_a[0] != 0:
        d0 = dist_a[0]
        dist_a = [d - d0 for d in dist_a]
    if dist_b[0] != 0:
        d0 = dist_b[0]
        dist_b = [d - d0 for d in dist_b]

    # ── Common distance axis ──
    max_dist = min(dist_a[-1], dist_b[-1])
    if max_dist <= 0:
        return api_error(ErrorCode.NOT_FOUND,
                         "No valid distance range for comparison", status=404)

    n_points = min(500, min(len(dist_a), len(dist_b)))
    common = np.linspace(0, max_dist, n_points)

    # ── Interpolate speed ──
    interp_spd_a = np.interp(common, dist_a, spd_a).tolist()
    interp_spd_b = np.interp(common, dist_b, spd_b).tolist()

    # ── Cumulative time delta ──
    def _cum_delta(dists, speeds_a, speeds_b):
        delta = [0.0]
        for i in range(1, len(dists)):
            ds = dists[i] - dists[i - 1]
            va = speeds_a[i] if speeds_a[i] > 0 else speeds_a[i - 1]
            vb = speeds_b[i] if speeds_b[i] > 0 else speeds_b[i - 1]
            ta = ds / va if va > 0 else 0
            tb = ds / vb if vb > 0 else 0
            delta.append(round(delta[-1] + (tb - ta), 4))
        return delta

    delta_s = _cum_delta(common.tolist(), interp_spd_a, interp_spd_b)

    # ── Interpolate GPS ──
    lat_a = trace_a.get("latitudes") or []
    lon_a = trace_a.get("longitudes") or []
    lat_b = trace_b.get("latitudes") or []
    lon_b = trace_b.get("longitudes") or []

    gps_primary = {}
    gps_reference = {}
    if lat_a and lon_a and len(lat_a) == len(dist_a):
        gps_primary = {
            "latitudes": np.interp(common, dist_a, lat_a).tolist(),
            "longitudes": np.interp(common, dist_a, lon_a).tolist(),
        }
    if lat_b and lon_b and len(lat_b) == len(dist_b):
        gps_reference = {
            "latitudes": np.interp(common, dist_b, lat_b).tolist(),
            "longitudes": np.interp(common, dist_b, lon_b).tolist(),
        }

    # ── Interpolate GG ──
    alat_a = trace_a.get("accel_lat") or []
    along_a = trace_a.get("accel_long") or []
    alat_b = trace_b.get("accel_lat") or []
    along_b = trace_b.get("accel_long") or []

    def _safe_interp(common_d, orig_d, vals):
        if vals and len(vals) == len(orig_d):
            clean = [v if v is not None else 0.0 for v in vals]
            return np.interp(common_d, orig_d, clean).tolist()
        return []

    gg_primary = {
        "accel_lat": _safe_interp(common, dist_a, alat_a),
        "accel_long": _safe_interp(common, dist_a, along_a),
    }
    gg_reference = {
        "accel_lat": _safe_interp(common, dist_b, alat_b),
        "accel_long": _safe_interp(common, dist_b, along_b),
    }

    # ── Lap time from session metadata ──
    lap_a = conn.execute(
        "SELECT lap_time_s FROM laps WHERE session_id = :sid AND lap_number = :lap",
        {"sid": session_id, "lap": primary_lap},
    ).fetchone()
    lap_b = conn.execute(
        "SELECT lap_time_s FROM laps WHERE session_id = :sid AND lap_number = :lap",
        {"sid": ref_session_id, "lap": ref_lap},
    ).fetchone()

    common_list = common.tolist()
    return api_response({
        "primary": {
            "session_id": session_id,
            "lap_number": primary_lap,
            "lap_time_s": lap_a["lap_time_s"] if lap_a else None,
        },
        "reference": {
            "session_id": ref_session_id,
            "lap_number": ref_lap,
            "lap_time_s": lap_b["lap_time_s"] if lap_b else None,
            "driver_name": session_b.get("driver_name"),
            "session_date": session_b.get("session_date"),
        },
        "distances": common_list,
        "speed": {
            "primary": interp_spd_a,
            "reference": interp_spd_b,
            "delta_s": delta_s,
        },
        "gps": {
            "primary": gps_primary,
            "reference": gps_reference,
        },
        "gg": {
            "primary": gg_primary,
            "reference": gg_reference,
        },
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_reference_overlay.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run full backend test suite**

Run: `pytest telemetry_tool/tests/ -x -q`
Expected: No regressions

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_reference_overlay.py
git commit -m "feat(api): add reference-data composite endpoint for cross-session overlay"
```

---

## Task 3: Frontend — types + ReferenceOverlayProvider

Context provider that fetches composite data and distributes to all charts.

**Files:**
- Create: `lap-website/src/components/app/reference/types.ts`
- Create: `lap-website/src/components/app/reference/ReferenceOverlayProvider.tsx`
- Create: `lap-website/src/components/app/reference/index.ts`

- [ ] **Step 1: Create types.ts**

Create `lap-website/src/components/app/reference/types.ts`:

```typescript
export interface ReferenceCandidate {
  session_id: string;
  driver_name: string;
  session_date: string;
  best_lap_time_s: number | null;
  n_laps: number;
  session_type: string;
}

export interface ReferenceData {
  primary: {
    session_id: string;
    lap_number: number;
    lap_time_s: number | null;
  };
  reference: {
    session_id: string;
    lap_number: number;
    lap_time_s: number | null;
    driver_name: string;
    session_date: string;
  };
  distances: number[];
  speed: {
    primary: number[];
    reference: number[];
    delta_s: number[];
  };
  gps: {
    primary: { latitudes: number[]; longitudes: number[] };
    reference: { latitudes: number[]; longitudes: number[] };
  };
  gg: {
    primary: { accel_lat: number[]; accel_long: number[] };
    reference: { accel_lat: number[]; accel_long: number[] };
  };
}

export interface ReferenceOverlayContextValue {
  referenceSession: string | null;
  referenceLap: number | null;
  referenceData: ReferenceData | null;
  isLoading: boolean;
  error: string | null;
  setReference: (sessionId: string, lap: number) => void;
  clearReference: () => void;
}
```

- [ ] **Step 2: Create ReferenceOverlayProvider.tsx**

Create `lap-website/src/components/app/reference/ReferenceOverlayProvider.tsx`:

```tsx
'use client';

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react';
import { api } from '@/lib/api-client';
import type { ReferenceData, ReferenceOverlayContextValue } from './types';

const ReferenceOverlayContext = createContext<ReferenceOverlayContextValue | null>(null);

interface ProviderProps {
  sessionId: string;
  primaryLap: number | null;
  children: ReactNode;
}

export function ReferenceOverlayProvider({
  sessionId,
  primaryLap,
  children,
}: ProviderProps) {
  const [referenceSession, setReferenceSession] = useState<string | null>(null);
  const [referenceLap, setReferenceLap] = useState<number | null>(null);
  const [referenceData, setReferenceData] = useState<ReferenceData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setReference = useCallback((sid: string, lap: number) => {
    setReferenceSession(sid);
    setReferenceLap(lap);
    setError(null);
  }, []);

  const clearReference = useCallback(() => {
    setReferenceSession(null);
    setReferenceLap(null);
    setReferenceData(null);
    setError(null);
  }, []);

  useEffect(() => {
    if (!referenceSession || !referenceLap || !primaryLap) {
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setError(null);

    const params = new URLSearchParams({
      ref_session: referenceSession,
      ref_lap: String(referenceLap),
      primary_lap: String(primaryLap),
    });

    api
      .get<{ data: ReferenceData }>(
        `/sessions/${sessionId}/reference-data?${params}`
      )
      .then((res) => {
        if (!cancelled) {
          // api-client returns the envelope body directly
          const data = (res as any).data ?? res;
          setReferenceData(data);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.message ?? 'Failed to load reference data');
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, primaryLap, referenceSession, referenceLap]);

  return (
    <ReferenceOverlayContext.Provider
      value={{
        referenceSession,
        referenceLap,
        referenceData,
        isLoading,
        error,
        setReference,
        clearReference,
      }}
    >
      {children}
    </ReferenceOverlayContext.Provider>
  );
}

export function useReferenceOverlay(): ReferenceOverlayContextValue {
  const ctx = useContext(ReferenceOverlayContext);
  if (!ctx) {
    // Return no-op context when used outside provider (safe fallback)
    return {
      referenceSession: null,
      referenceLap: null,
      referenceData: null,
      isLoading: false,
      error: null,
      setReference: () => {},
      clearReference: () => {},
    };
  }
  return ctx;
}
```

- [ ] **Step 3: Create barrel export**

Create `lap-website/src/components/app/reference/index.ts`:

```typescript
export { ReferenceOverlayProvider, useReferenceOverlay } from './ReferenceOverlayProvider';
export type { ReferenceData, ReferenceCandidate, ReferenceOverlayContextValue } from './types';
```

- [ ] **Step 4: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors related to the new files

- [ ] **Step 5: Commit**

```bash
git add lap-website/src/components/app/reference/
git commit -m "feat(ui): add ReferenceOverlayProvider context for cross-session data"
```

---

## Task 4: Frontend — ReferenceFAB picker

Floating action button + modal that loads candidates and lets user pick a reference session/lap.

**Files:**
- Create: `lap-website/src/components/app/reference/ReferenceFAB.tsx`

- [ ] **Step 1: Create ReferenceFAB.tsx**

Create `lap-website/src/components/app/reference/ReferenceFAB.tsx`:

```tsx
'use client';

import { useState, useEffect, useRef, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { useReferenceOverlay } from './ReferenceOverlayProvider';
import type { ReferenceCandidate } from './types';

interface ReferenceFABProps {
  sessionId: string;
}

export function ReferenceFAB({ sessionId }: ReferenceFABProps) {
  const { referenceSession, referenceLap, referenceData, isLoading, setReference, clearReference } =
    useReferenceOverlay();
  const [open, setOpen] = useState(false);
  const [candidates, setCandidates] = useState<ReferenceCandidate[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [search, setSearch] = useState('');
  const modalRef = useRef<HTMLDivElement>(null);

  // Fetch candidates when modal opens
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingCandidates(true);
    api
      .get<{ data: ReferenceCandidate[] }>(
        `/sessions/${sessionId}/reference-candidates`
      )
      .then((res) => {
        if (!cancelled) {
          const list = (res as any).data ?? res;
          setCandidates(Array.isArray(list) ? list : []);
        }
      })
      .catch(() => {
        if (!cancelled) setCandidates([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingCandidates(false);
      });
    return () => { cancelled = true; };
  }, [open, sessionId]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  const filtered = useMemo(() => {
    if (!search.trim()) return candidates;
    const q = search.toLowerCase();
    return candidates.filter(
      (c) =>
        c.driver_name?.toLowerCase().includes(q) ||
        c.session_date?.includes(q) ||
        c.session_type?.toLowerCase().includes(q)
    );
  }, [candidates, search]);

  function handleSelect(c: ReferenceCandidate) {
    // Default to best lap (lap 1 as proxy — the API resolves best lap if needed)
    setReference(c.session_id, 1);
    setOpen(false);
    setSearch('');
  }

  function formatTime(s: number | null): string {
    if (s == null) return '--';
    const mins = Math.floor(s / 60);
    const secs = (s % 60).toFixed(1);
    return mins > 0 ? `${mins}:${secs.padStart(4, '0')}` : `${secs}s`;
  }

  // Active state — show pill with reference info
  if (referenceSession && referenceData) {
    const ref = referenceData.reference;
    const dateStr = ref.session_date
      ? new Date(ref.session_date).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })
      : '';
    return (
      <div className="absolute bottom-4 right-4 z-20 flex items-center gap-2 bg-concrete border border-racing-purple/40 rounded-full px-3 py-1.5 font-telemetry text-xs text-racing-purple shadow-lg">
        {isLoading && (
          <span className="animate-spin w-3 h-3 border border-racing-purple border-t-transparent rounded-full" />
        )}
        <span className="text-chalk">{dateStr}</span>
        <span>L{ref.lap_number}</span>
        <span>({formatTime(ref.lap_time_s)})</span>
        <button
          onClick={clearReference}
          className="ml-1 text-racing-purple hover:text-chalk transition-colors"
          aria-label="Clear reference lap"
        >
          &times;
        </button>
      </div>
    );
  }

  return (
    <div className="absolute bottom-4 right-4 z-20" ref={modalRef}>
      {/* FAB */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="w-10 h-10 bg-racing-purple rounded-full flex items-center justify-center text-white text-lg shadow-lg hover:bg-racing-purple/80 transition-colors"
          aria-label="Add reference lap from another session"
          title="Add reference lap"
        >
          +
        </button>
      )}

      {/* Modal */}
      {open && (
        <div className="absolute bottom-12 right-0 w-72 bg-concrete border border-steel/20 rounded-xl shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-steel/10">
            <span className="text-xs font-monument text-chalk">Add Reference Lap</span>
            <button
              onClick={() => setOpen(false)}
              className="text-steel hover:text-chalk text-sm"
            >
              &times;
            </button>
          </div>
          <div className="p-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search sessions..."
              className="w-full bg-asphalt text-chalk border border-steel/20 rounded px-2 py-1.5 text-xs font-telemetry placeholder:text-steel/50 focus:outline-none focus:border-racing-purple/50"
            />
          </div>
          <div className="max-h-60 overflow-y-auto px-2 pb-2 space-y-1">
            {loadingCandidates && (
              <div className="text-center py-4 text-steel text-xs">Loading...</div>
            )}
            {!loadingCandidates && filtered.length === 0 && (
              <div className="text-center py-4 text-steel text-xs">No sessions on this track</div>
            )}
            {filtered.map((c) => (
              <button
                key={c.session_id}
                onClick={() => handleSelect(c)}
                className="w-full text-left px-2 py-1.5 rounded hover:bg-steel/10 transition-colors group"
              >
                <div className="flex justify-between items-center">
                  <span className="text-xs font-telemetry text-chalk">
                    {c.session_date
                      ? new Date(c.session_date).toLocaleDateString('en-GB', {
                          month: 'short',
                          day: 'numeric',
                        })
                      : 'Unknown'}{' '}
                    &mdash; {c.session_type || 'session'}
                  </span>
                  <span className="text-xs font-telemetry text-racing-purple">
                    {formatTime(c.best_lap_time_s)}
                  </span>
                </div>
                <div className="text-[10px] font-telemetry text-steel">
                  {c.driver_name} &bull; {c.n_laps} laps
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add to barrel export**

In `lap-website/src/components/app/reference/index.ts`, add:

```typescript
export { ReferenceFAB } from './ReferenceFAB';
```

- [ ] **Step 3: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No type errors

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/components/app/reference/
git commit -m "feat(ui): add ReferenceFAB picker for cross-session reference selection"
```

---

## Task 5: Frontend — SpeedTraceChart overlay

Add racing-purple dashed reference line, delta bar, and dual hover marker.

**Files:**
- Modify: `lap-website/src/components/shared/charts/SpeedTraceChart.tsx`

**Context:** The chart uses a `drawSpeedTrace()` pure function that receives a `DrawOptions` object and renders to canvas. The existing `refSpeeds` field already draws a dashed reference line for intra-session comparison. We need to add a separate cross-session overlay from the `ReferenceOverlayProvider` context.

- [ ] **Step 1: Import and consume reference context**

At the top of `SpeedTraceChart.tsx`, after the existing imports, add:

```typescript
import { useReferenceOverlay } from '@/components/app/reference';
```

Inside the component function body (after the existing hooks), add:

```typescript
const { referenceData } = useReferenceOverlay();
```

- [ ] **Step 2: Extend DrawOptions with cross-session reference fields**

Add to the existing `DrawOptions` interface:

```typescript
interface DrawOptions {
  // ... existing fields ...
  crossRefSpeeds?: number[] | null;
  crossRefDistances?: number[] | null;
  crossRefDelta?: number[] | null;
  crossRefLabel?: string | null;
}
```

- [ ] **Step 3: Pass reference data into drawSpeedTrace call**

In the `useEffect` or `useCallback` where `drawSpeedTrace()` is called, add the cross-session fields to the options object:

```typescript
const crossRef = referenceData?.speed ?? null;
const crossRefDists = referenceData?.distances ?? null;

// Add to the drawSpeedTrace options:
crossRefSpeeds: crossRef?.reference ?? null,
crossRefDistances: crossRefDists,
crossRefDelta: crossRef?.delta_s ?? null,
crossRefLabel: referenceData?.reference
  ? `${referenceData.reference.driver_name} ${referenceData.reference.session_date} L${referenceData.reference.lap_number}`
  : null,
```

- [ ] **Step 4: Draw the cross-session reference line in drawSpeedTrace**

Inside the `drawSpeedTrace()` function, after the existing reference line drawing (the `refSpeeds` section), add:

```typescript
// ── Cross-session reference overlay (racing-purple dashed) ──
if (opts.crossRefSpeeds && opts.crossRefDistances) {
  ctx.save();
  ctx.strokeStyle = '#8B5CF6';  // racing-purple
  ctx.lineWidth = 1.5 * dpr;
  ctx.setLineDash([6 * dpr, 4 * dpr]);
  ctx.globalAlpha = 0.7;
  ctx.beginPath();
  for (let i = 0; i < opts.crossRefDistances.length; i++) {
    const d = opts.crossRefDistances[i];
    const s = opts.crossRefSpeeds[i] * 3.6; // m/s to km/h
    if (d < xMin || d > xMax) continue;
    const px = plotL + ((d - xMin) / (xMax - xMin)) * plotW;
    const py = plotT + (1 - (s - yMin) / (yMax - yMin)) * plotH;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();
}

// ── Delta bar (below main chart, above x-axis labels) ──
if (opts.crossRefDelta && opts.crossRefDistances) {
  const barH = 10 * dpr;
  const barY = plotT + plotH + 2 * dpr;
  for (let i = 1; i < opts.crossRefDistances.length; i++) {
    const d0 = opts.crossRefDistances[i - 1];
    const d1 = opts.crossRefDistances[i];
    if (d1 < xMin || d0 > xMax) continue;
    const px0 = plotL + ((Math.max(d0, xMin) - xMin) / (xMax - xMin)) * plotW;
    const px1 = plotL + ((Math.min(d1, xMax) - xMin) / (xMax - xMin)) * plotW;
    const delta = opts.crossRefDelta[i];
    // Positive delta = reference is slower = you're faster (green)
    ctx.fillStyle = delta > 0 ? 'rgba(34,197,94,0.3)' : 'rgba(255,42,42,0.3)';
    ctx.fillRect(px0, barY, px1 - px0, barH);
  }
}
```

- [ ] **Step 5: Draw dual hover markers**

In the hover marker section of `drawSpeedTrace()`, after drawing the primary marker, add:

```typescript
// ── Cross-session hover marker (hollow purple circle) ──
if (opts.crossRefSpeeds && opts.crossRefDistances && hoverIdx >= 0) {
  // Find closest index in cross-ref distances
  const hoverDist = opts.distances[hoverIdx];
  let refIdx = 0;
  let minDiff = Infinity;
  for (let i = 0; i < opts.crossRefDistances.length; i++) {
    const diff = Math.abs(opts.crossRefDistances[i] - hoverDist);
    if (diff < minDiff) { minDiff = diff; refIdx = i; }
  }
  if (refIdx < opts.crossRefSpeeds.length) {
    const refSpeed = opts.crossRefSpeeds[refIdx] * 3.6;
    const rpx = plotL + ((opts.crossRefDistances[refIdx] - xMin) / (xMax - xMin)) * plotW;
    const rpy = plotT + (1 - (refSpeed - yMin) / (yMax - yMin)) * plotH;
    ctx.save();
    ctx.strokeStyle = '#8B5CF6';
    ctx.lineWidth = 2 * dpr;
    ctx.beginPath();
    ctx.arc(rpx, rpy, 5 * dpr, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }
}
```

- [ ] **Step 6: Add referenceData to the useEffect dependency array**

Add `referenceData` to the dependency array of the effect that triggers re-drawing, so charts update when reference data arrives.

- [ ] **Step 7: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No type errors

- [ ] **Step 8: Commit**

```bash
git add lap-website/src/components/shared/charts/SpeedTraceChart.tsx
git commit -m "feat(ui): add cross-session speed trace overlay with delta bar and dual marker"
```

---

## Task 6: Frontend — TrackMap overlay

Add dashed racing-purple GPS path and dual position marker.

**Files:**
- Modify: `lap-website/src/components/shared/charts/TrackMap.tsx`

**Context:** The chart uses a `drawTrack()` function. It already has `compareTrace` support for intra-session overlay. We add a separate cross-session layer.

- [ ] **Step 1: Import and consume reference context**

Add import:
```typescript
import { useReferenceOverlay } from '@/components/app/reference';
```

Inside the component:
```typescript
const { referenceData } = useReferenceOverlay();
```

- [ ] **Step 2: Build reference trace data for drawTrack**

Before the `drawTrack` call, extract GPS reference data:

```typescript
const crossRefTrace = useMemo(() => {
  if (!referenceData?.gps?.reference?.latitudes?.length) return null;
  return {
    latitudes: referenceData.gps.reference.latitudes,
    longitudes: referenceData.gps.reference.longitudes,
    distances: referenceData.distances,
  };
}, [referenceData]);
```

- [ ] **Step 3: Draw cross-session GPS path in drawTrack**

In the `drawTrack()` function, after the existing trace is drawn and before corner markers, add:

```typescript
// ── Cross-session reference path (racing-purple dashed) ──
if (crossRefTrace && projection) {
  ctx.save();
  ctx.strokeStyle = '#8B5CF6';
  ctx.lineWidth = 2 * dpr;
  ctx.setLineDash([6 * dpr, 4 * dpr]);
  ctx.globalAlpha = 0.5;
  ctx.beginPath();
  for (let i = 0; i < crossRefTrace.latitudes.length; i++) {
    const [px, py] = projection.toXY(crossRefTrace.latitudes[i], crossRefTrace.longitudes[i]);
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();
}
```

- [ ] **Step 4: Draw dual position markers on hover**

After the primary hover marker is drawn, add:

```typescript
// ── Cross-session hover marker (hollow purple circle) ──
if (crossRefTrace && hoverIdx >= 0 && projection) {
  const hoverDist = distances[hoverIdx];
  // Find closest index in reference distances
  const refDists = referenceData?.distances ?? [];
  let refIdx = 0;
  let minDiff = Infinity;
  for (let i = 0; i < refDists.length; i++) {
    const diff = Math.abs(refDists[i] - hoverDist);
    if (diff < minDiff) { minDiff = diff; refIdx = i; }
  }
  if (refIdx < crossRefTrace.latitudes.length) {
    const [rpx, rpy] = projection.toXY(
      crossRefTrace.latitudes[refIdx],
      crossRefTrace.longitudes[refIdx]
    );
    ctx.save();
    ctx.strokeStyle = '#8B5CF6';
    ctx.lineWidth = 2 * dpr;
    ctx.beginPath();
    ctx.arc(rpx, rpy, 6 * dpr, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }
}
```

- [ ] **Step 5: Add referenceData to redraw dependencies**

Add `referenceData` and `crossRefTrace` to the dependency array of the draw effect.

- [ ] **Step 6: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No type errors

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/components/shared/charts/TrackMap.tsx
git commit -m "feat(ui): add cross-session GPS overlay with dual position marker on track map"
```

---

## Task 7: Frontend — GGExplorer overlay

Add hollow racing-purple reference scatter and dual acceleration marker.

**Files:**
- Modify: `lap-website/src/components/shared/charts/GGExplorer.tsx`

**Context:** Canvas-based density scatter. Currently has zero comparison capability. The `drawGG()` function receives `ggData` and `hoverIdx`.

- [ ] **Step 1: Import and consume reference context**

Add import:
```typescript
import { useReferenceOverlay } from '@/components/app/reference';
```

Inside the component:
```typescript
const { referenceData } = useReferenceOverlay();
```

- [ ] **Step 2: Extract reference GG data**

```typescript
const crossRefGG = useMemo(() => {
  if (!referenceData?.gg?.reference?.accel_lat?.length) return null;
  return {
    accel_lat: referenceData.gg.reference.accel_lat,
    accel_long: referenceData.gg.reference.accel_long,
    distances: referenceData.distances,
  };
}, [referenceData]);
```

- [ ] **Step 3: Draw reference scatter in drawGG**

In the `drawGG()` function, BEFORE the primary scatter is drawn (so reference appears behind), add:

```typescript
// ── Cross-session reference scatter (hollow purple circles) ──
if (crossRefGG) {
  ctx.save();
  ctx.strokeStyle = '#8B5CF6';
  ctx.lineWidth = 1 * dpr;
  ctx.globalAlpha = 0.4;
  for (let i = 0; i < crossRefGG.accel_lat.length; i++) {
    const latG = crossRefGG.accel_lat[i];
    const lonG = crossRefGG.accel_long[i];
    if (latG == null || lonG == null) continue;
    const px = centerX + (latG / axisMax) * halfW;
    const py = centerY - (lonG / axisMax) * halfH;
    ctx.beginPath();
    ctx.arc(px, py, 3 * dpr, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}
```

- [ ] **Step 4: Draw dual hover marker**

After the primary hover dot, add:

```typescript
// ── Cross-session hover marker (hollow purple circle) ──
if (crossRefGG && hoverIdx >= 0) {
  const hoverDist = ggData.distances?.[hoverIdx];
  if (hoverDist != null) {
    const refDists = referenceData?.distances ?? [];
    let refIdx = 0;
    let minDiff = Infinity;
    for (let i = 0; i < refDists.length; i++) {
      const diff = Math.abs(refDists[i] - hoverDist);
      if (diff < minDiff) { minDiff = diff; refIdx = i; }
    }
    if (refIdx < crossRefGG.accel_lat.length) {
      const rLatG = crossRefGG.accel_lat[refIdx];
      const rLonG = crossRefGG.accel_long[refIdx];
      if (rLatG != null && rLonG != null) {
        const rpx = centerX + (rLatG / axisMax) * halfW;
        const rpy = centerY - (rLonG / axisMax) * halfH;
        ctx.save();
        ctx.strokeStyle = '#8B5CF6';
        ctx.lineWidth = 2 * dpr;
        ctx.beginPath();
        ctx.arc(rpx, rpy, 6 * dpr, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }
  }
}
```

- [ ] **Step 5: Add referenceData to redraw dependencies**

- [ ] **Step 6: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No type errors

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/components/shared/charts/GGExplorer.tsx
git commit -m "feat(ui): add cross-session GG overlay with hollow scatter and dual marker"
```

---

## Task 8: Frontend — AnalyticsTab integration

Wrap the three target charts in `ReferenceOverlayProvider` and add the `ReferenceFAB`.

**Files:**
- Modify: `lap-website/src/components/app/analytics/AnalyticsTab.tsx` (lines 86-188 — Row 1 grid)

- [ ] **Step 1: Add imports**

At the top of `AnalyticsTab.tsx`, add:

```typescript
import { ReferenceOverlayProvider, ReferenceFAB } from '@/components/app/reference';
```

- [ ] **Step 2: Wrap Row 1 in ReferenceOverlayProvider**

Replace the Row 1 grid (lines 86-188) by wrapping it:

```tsx
{/* ── Row 1: Track Map + Speed Trace + GG Diagram ── */}
<ReferenceOverlayProvider sessionId={sessionId} primaryLap={bestLap}>
  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 relative">
    {/* ReferenceFAB — positioned absolute in the grid container */}
    <ReferenceFAB sessionId={sessionId} />

    <div className="lg:col-span-1">
      {/* ... existing GpsTrace card (unchanged) ... */}
    </div>
    <div className="lg:col-span-2">
      {/* ... existing SpeedTraceZoom card (unchanged) ... */}
    </div>
    <div className="lg:col-span-2">
      {/* ... existing GGExplorer card (unchanged) ... */}
    </div>
  </div>
</ReferenceOverlayProvider>
```

The key changes:
1. `<ReferenceOverlayProvider>` wraps the grid, passing `sessionId` and `primaryLap={bestLap}`
2. `<ReferenceFAB>` is added as first child inside the grid
3. `relative` class added to the grid div for FAB absolute positioning
4. All existing chart JSX inside remains unchanged

- [ ] **Step 3: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No type errors

- [ ] **Step 4: Run dev server and test manually**

Run: `cd lap-website && npm run dev`

1. Open a session detail page → Analytics tab
2. Verify the purple FAB appears bottom-right of the chart grid
3. Click it → verify modal shows same-track sessions
4. Select a session → verify all three charts show the purple overlay
5. Hover → verify dual markers on all charts
6. Click X on the pill → verify overlay clears

- [ ] **Step 5: Commit**

```bash
git add lap-website/src/components/app/analytics/AnalyticsTab.tsx
git commit -m "feat(ui): wire ReferenceOverlayProvider + FAB into AnalyticsTab"
```

---

## Task 9: Frontend — Compare page enhancement

Add TrackMap and GGExplorer to the compare page, using the same overlay rendering.

**Files:**
- Modify: `lap-website/src/app/app/compare/sessions/page.tsx`

**Context:** The compare page already has `CompareChartPanel` which shows SpeedOverlay, GpsOverlay, SectorDelta, and CornerCompare. We need to add a GGExplorer panel and wire the existing panels to use the `ReferenceOverlayProvider` for consistent overlay rendering.

- [ ] **Step 1: Import the reference components**

Add to the compare page imports:

```typescript
import { ReferenceOverlayProvider } from '@/components/app/reference';
import { GGExplorer } from '@/components/app/charts';
```

- [ ] **Step 2: Wrap CompareChartPanel in ReferenceOverlayProvider**

Find where `<CompareChartPanel>` is rendered (~line 635). Wrap it:

```tsx
{sessionAId && sessionBId && comparisonData && (
  <ReferenceOverlayProvider
    sessionId={sessionAId}
    primaryLap={comparisonData.session_a?.lap_number ?? null}
  >
    <CompareChartPanel sessionAId={sessionAId} sessionBId={sessionBId} />
  </ReferenceOverlayProvider>
)}
```

- [ ] **Step 3: Auto-set reference when both sessions are selected**

Add a `useEffect` that automatically sets the reference overlay when the compare page loads with two sessions:

```tsx
// Inside the compare page component, after the ReferenceOverlayProvider:
// We need a child component that can use the context to auto-set reference
function CompareAutoReference({
  sessionBId,
  lapB,
  children,
}: {
  sessionBId: string;
  lapB: number;
  children: React.ReactNode;
}) {
  const { setReference, referenceSession } = useReferenceOverlay();
  useEffect(() => {
    if (sessionBId && lapB && referenceSession !== sessionBId) {
      setReference(sessionBId, lapB);
    }
  }, [sessionBId, lapB, setReference, referenceSession]);
  return <>{children}</>;
}
```

Wrap the CompareChartPanel with it:

```tsx
<ReferenceOverlayProvider
  sessionId={sessionAId}
  primaryLap={comparisonData.session_a?.lap_number ?? null}
>
  <CompareAutoReference
    sessionBId={sessionBId}
    lapB={comparisonData.session_b?.lap_number ?? 1}
  >
    <CompareChartPanel sessionAId={sessionAId} sessionBId={sessionBId} />
  </CompareAutoReference>
</ReferenceOverlayProvider>
```

This automatically populates the reference overlay on the compare page without the user needing to use the FAB.

- [ ] **Step 4: Add GG Explorer to CompareChartPanel**

In the `CompareChartPanel` component (likely in `lap-website/src/app/app/compare/CompareChartPanel.tsx` or similar), add a new mode entry for GG:

Add to the MODES array:
```typescript
{ key: 'gg' as ChartMode, label: 'G-G Diagram' }
```

Add the rendering branch:
```tsx
{mode === 'gg' && (
  <div className="p-4">
    <GGExplorer
      sessionId={sessionAId}
      gpsLaps={[]}
      bestLap={null}
      className="w-full"
    />
  </div>
)}
```

The GGExplorer will automatically pick up the reference overlay from context and draw the cross-session scatter.

- [ ] **Step 5: Verify build**

Run: `cd lap-website && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No type errors

- [ ] **Step 6: Test manually**

1. Navigate to `/app/compare`
2. Select two sessions on the same track
3. Verify speed trace shows both lines (existing behavior + purple overlay)
4. Switch to "G-G Diagram" mode → verify dual scatter
5. Hover → verify dual markers sync across chart modes

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/app/app/compare/
git commit -m "feat(ui): add GG overlay to compare page with auto-reference wiring"
```

---

## Task 10: Full build + deploy

**Files:** None modified — verification only.

- [ ] **Step 1: Run full backend tests**

Run: `pytest telemetry_tool/tests/ -x -q`
Expected: All tests pass, no regressions

- [ ] **Step 2: Build frontend**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 3: Deploy backend**

```bash
scp telemetry_tool/web/routes/data_v2.py root@46.225.227.24:/opt/lap-api/telemetry_tool/web/routes/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
```

Verify: `curl -s https://api.lap-coach.racing/healthz | python -m json.tool`
Expected: `{"status": "ok"}`

- [ ] **Step 4: Deploy frontend**

Run: `cd lap-website && npm run cf:deploy`
Expected: Cloudflare Workers deployment succeeds

- [ ] **Step 5: Verify live**

1. Open `https://lap-coach.racing/app/sessions/<any-session>` → Analytics tab
2. Confirm FAB appears
3. Select a reference session → confirm overlay renders on all three charts
4. Test compare page with two sessions → confirm GG diagram mode works

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: cross-session reference lap overlay — full implementation"
```
