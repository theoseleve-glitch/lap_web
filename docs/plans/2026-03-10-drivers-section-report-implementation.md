# Drivers Section Full Re-Port — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fully re-port the drivers section: fix list page field mismatches, enrich the API with profile/progression/style/badges endpoints, rebuild the driver detail page as a scrollable view with Recharts charts and inline editing.

**Architecture:** Backend enriches `api_v1_entities.py` with 7 new endpoints reusing existing `driver_repo.py` functions. Frontend fixes list page types, rebuilds detail page with stacked sections (stats, progression charts, style radar, badges, sessions table), uses existing `InlineEdit` component.

**Tech Stack:** Flask (backend), Recharts (new dep), React Query, Zustand, TailwindCSS, existing `InlineEdit` component

---

## Key Files Reference

- **Backend routes**: `telemetry_tool/web/routes/api_v1_entities.py`
- **Backend repo**: `telemetry_tool/web/repos/driver_repo.py` (all data functions exist)
- **Backend queries**: `telemetry_tool/db/queries.py`
- **Backend tests**: `telemetry_tool/tests/test_entity_api.py`
- **Frontend list**: `lap-website/src/app/app/drivers/page.tsx`
- **Frontend detail (stub)**: `lap-website/src/app/app/drivers/[id]/page.tsx`
- **Frontend progression (delete)**: `lap-website/src/app/app/drivers/[id]/progression/page.tsx`
- **Frontend API client**: `lap-website/src/lib/api-client.ts` (get/post/patch/delete)
- **Frontend envelope**: `lap-website/src/lib/http-envelope.ts` (auto-unwraps `{ok, data}`)
- **Frontend query keys**: `lap-website/src/lib/query-keys.ts`
- **Frontend types**: `lap-website/src/lib/api-types.ts`
- **Frontend InlineEdit**: `lap-website/src/components/app/InlineEdit.tsx` (already exists)
- **Frontend barrel**: `lap-website/src/components/app/index.ts`

## Important Conventions

- Backend `api_response(data)` wraps in `{ok: true, data: ...}`. Frontend `parseEnvelopeOrThrow` auto-unwraps, so `api.get<T>(path)` returns `T` directly (not the envelope).
- Entity field convention: `id`/`name` (not `driver_id`/`driver_name`).
- `_get_conn()` in `api_v1_entities.py` is overridden in tests via `ent._get_conn = lambda: db`.
- The `web.models` module re-exports everything from `web.repos.*` via `from web.repos import *`.

---

### Task 1: Backend — Enrich `_map_driver()` and list endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_entities.py:43-61`
- Test: `telemetry_tool/tests/test_entity_api.py`

**Step 1: Write failing tests for enriched driver list**

Add to `telemetry_tool/tests/test_entity_api.py`:

```python
def test_list_drivers_has_enriched_fields(client, db):
    """List should include has_profile, style_label, total_laps."""
    resp = client.get("/api/v1/drivers")
    assert resp.status_code == 200
    drivers = resp.get_json()["data"]
    alice = next(d for d in drivers if d["name"] == "Alice")
    # All enriched fields must be present
    assert "has_profile" in alice
    assert "style_label" in alice
    assert "total_laps" in alice
    assert isinstance(alice["has_profile"], bool)
    assert isinstance(alice["total_laps"], int)
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_entity_api.py::test_list_drivers_has_enriched_fields -v`
Expected: FAIL — `has_profile` not in response.

**Step 3: Implement enriched `_map_driver()` and list endpoint**

In `api_v1_entities.py`, replace `_map_driver` and `list_drivers`:

```python
def _map_driver(row):
    """Map DB driver row to frontend-expected field names."""
    d = dict(row)
    return {
        "id": d["driver_id"],
        "name": d["driver_name"],
        "notes": d.get("notes"),
        "created_at": d.get("created_at"),
        "session_count": d.get("session_count", 0),
        "personal_best_s": d.get("personal_best_s"),
        "mean_score": d.get("mean_score"),
        "has_profile": d.get("has_profile", False),
        "style_label": d.get("style_label"),
        "total_laps": d.get("total_laps", 0),
    }


@bp.route("/drivers", methods=["GET"])
def list_drivers():
    conn = _get_conn()
    from web.repos.driver_repo import get_all_drivers
    rows = get_all_drivers(conn)
    return api_response([_map_driver(r) for r in rows])
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_entity_api.py::test_list_drivers_has_enriched_fields -v`
Expected: PASS

**Step 5: Run all existing entity tests to check no regressions**

Run: `cd telemetry_tool && python -m pytest tests/test_entity_api.py -v`
Expected: All pass

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_entities.py telemetry_tool/tests/test_entity_api.py
git commit -m "feat(api): enrich GET /drivers with profile, style, laps fields"
```

---

### Task 2: Backend — Driver detail, profile, progression, style, badges, sessions, delete endpoints

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_entities.py`
- Test: `telemetry_tool/tests/test_entity_api.py`

**Step 1: Write failing tests for all new endpoints**

Add to `test_entity_api.py`:

```python
def test_get_driver_detail_enriched(client, db):
    """GET /drivers/:id returns profile + session stats."""
    resp = client.get("/api/v1/drivers/1")
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert d["name"] == "Alice"
    assert "profile" in d
    assert "session_count" in d


def test_get_driver_progression(client, db):
    """GET /drivers/:id/progression returns list."""
    resp = client.get("/api/v1/drivers/1/progression")
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert isinstance(d["progression"], list)


def test_get_driver_progression_not_found(client, db):
    resp = client.get("/api/v1/drivers/9999/progression")
    assert resp.status_code == 404


def test_get_driver_style_history(client, db):
    """GET /drivers/:id/style-history returns list."""
    resp = client.get("/api/v1/drivers/1/style-history")
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert isinstance(d["history"], list)


def test_get_driver_badges(client, db):
    """GET /drivers/:id/badges returns list."""
    resp = client.get("/api/v1/drivers/1/badges")
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert isinstance(d["badges"], list)


def test_get_driver_badges_with_data(client, db):
    """Badges endpoint returns inserted badge."""
    db.execute(
        "INSERT INTO driver_badges (driver_id, badge_type, badge_name, badge_level) "
        "VALUES (1, 'consistency', 'Iron Consistency', 'bronze')"
    )
    db.commit()
    resp = client.get("/api/v1/drivers/1/badges")
    badges = resp.get_json()["data"]["badges"]
    assert len(badges) == 1
    assert badges[0]["badge_name"] == "Iron Consistency"


def test_get_driver_best_ever(client, db):
    """GET /drivers/:id/best-ever returns relative performance."""
    resp = client.get("/api/v1/drivers/1/best-ever")
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert "best_pct" in d
    assert "records_held" in d


def test_get_driver_sessions(client, db):
    """GET /drivers/:id/sessions returns session list."""
    resp = client.get("/api/v1/drivers/1/sessions")
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert isinstance(d["sessions"], list)
    assert len(d["sessions"]) >= 1


def test_patch_driver_profile(client, db):
    """PATCH /drivers/:id/profile updates editable field."""
    resp = client.patch("/api/v1/drivers/1/profile", json={"field": "goals", "value": "Win championship"})
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert d["field"] == "goals"


def test_patch_driver_profile_invalid_field(client, db):
    """PATCH /drivers/:id/profile rejects non-editable fields."""
    resp = client.patch("/api/v1/drivers/1/profile", json={"field": "driver_id", "value": "99"})
    assert resp.status_code == 400


def test_delete_driver(client, db):
    """DELETE /drivers/:id cascade-deletes driver."""
    resp = client.delete("/api/v1/drivers/2")
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert d["deleted"] is True
    # Verify gone
    resp2 = client.get("/api/v1/drivers/2")
    assert resp2.status_code == 404


def test_delete_driver_not_found(client, db):
    resp = client.delete("/api/v1/drivers/9999")
    assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `cd telemetry_tool && python -m pytest tests/test_entity_api.py -k "progression or style or badges or best_ever or sessions or profile or delete_driver" -v`
Expected: Multiple FAIL

**Step 3: Implement all new endpoints**

Add to `api_v1_entities.py` after the existing `patch_driver` function:

```python
def _verify_driver(conn, driver_id):
    """Return driver row or None."""
    return conn.execute(
        "SELECT * FROM drivers WHERE driver_id = ?", (driver_id,)
    ).fetchone()


@bp.route("/drivers/<int:driver_id>/progression", methods=["GET"])
def get_driver_progression(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    from web.repos.driver_repo import get_driver_progression as _get_prog
    prog = _get_prog(conn, driver_id)
    return api_response({"driver_id": driver_id, "progression": prog})


@bp.route("/drivers/<int:driver_id>/style-history", methods=["GET"])
def get_driver_style_history(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    from web.repos.driver_repo import get_driver_style_history as _get_style
    history = _get_style(conn, driver_id)
    for h in history:
        h.pop("strengths_json", None)
        h.pop("weaknesses_json", None)
    return api_response({"driver_id": driver_id, "history": history})


@bp.route("/drivers/<int:driver_id>/badges", methods=["GET"])
def get_driver_badges(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    rows = conn.execute(
        "SELECT * FROM driver_badges WHERE driver_id = ? ORDER BY earned_at DESC",
        (driver_id,),
    ).fetchall()
    return api_response({"driver_id": driver_id, "badges": [dict(r) for r in rows]})


@bp.route("/drivers/<int:driver_id>/best-ever", methods=["GET"])
def get_driver_best_ever(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    from web.repos.driver_repo import compute_best_ever_relative
    result = compute_best_ever_relative(conn, driver_id)
    return api_response(result)


@bp.route("/drivers/<int:driver_id>/sessions", methods=["GET"])
def get_driver_sessions(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, s.best_lap_time_s, "
        "s.total_score, s.n_laps, s.track_state, "
        "t.track_name, s.track_id "
        "FROM sessions s "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = ? AND s.deleted_at IS NULL "
        "ORDER BY s.session_date DESC",
        (driver_id,),
    ).fetchall()
    return api_response({"driver_id": driver_id, "sessions": [dict(r) for r in rows]})


@bp.route("/drivers/<int:driver_id>/profile", methods=["PATCH"])
def patch_driver_profile(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    body = request.get_json(silent=True) or {}
    field_name = body.get("field")
    value = body.get("value")
    if not field_name:
        return api_error(ErrorCode.VALIDATION_ERROR, "field is required", status=400)
    from web.repos.driver_repo import (
        get_driver_profile, upsert_driver_profile, update_driver_profile_field,
    )
    if get_driver_profile(conn, driver_id) is None:
        upsert_driver_profile(conn, driver_id, {})
        conn.commit()
    try:
        update_driver_profile_field(conn, driver_id, field_name, value)
        conn.commit()
    except ValueError:
        return api_error(ErrorCode.VALIDATION_ERROR, f"Field '{field_name}' is not editable", status=400)
    return api_response({"field": field_name, "value": value})


@bp.route("/drivers/<int:driver_id>", methods=["DELETE"])
def delete_driver(driver_id):
    conn = _get_conn()
    if not _verify_driver(conn, driver_id):
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    from web.repos.driver_repo import delete_driver_cascade
    delete_driver_cascade(conn, driver_id)
    conn.commit()
    return api_response({"deleted": True})
```

Also update the existing `get_driver` endpoint to include profile:

```python
@bp.route("/drivers/<int:driver_id>", methods=["GET"])
def get_driver(driver_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT d.*, COUNT(s.session_id) AS session_count, "
        "MIN(s.best_lap_time_s) AS personal_best_s, AVG(s.total_score) AS mean_score "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "WHERE d.driver_id = ?", (driver_id,)
    ).fetchone()
    if not row or row["driver_id"] is None:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    result = _map_driver(row)
    from web.repos.driver_repo import get_driver_profile
    profile = get_driver_profile(conn, driver_id)
    result["profile"] = dict(profile) if profile else None
    return api_response(result)
```

**Step 4: Run all tests**

Run: `cd telemetry_tool && python -m pytest tests/test_entity_api.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_entities.py telemetry_tool/tests/test_entity_api.py
git commit -m "feat(api): add driver profile, progression, style, badges, sessions, delete endpoints"
```

---

### Task 3: Frontend — Install Recharts

**Step 1: Install recharts**

Run: `cd lap-website && npm install recharts`

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add lap-website/package.json lap-website/package-lock.json
git commit -m "chore: add recharts dependency"
```

---

### Task 4: Frontend — Add driver query keys and fix API types

**Files:**
- Modify: `lap-website/src/lib/query-keys.ts`
- Modify: `lap-website/src/lib/api-types.ts`

**Step 1: Add driver query keys**

In `query-keys.ts`, add after the `tracks` section:

```typescript
  // ── Drivers ────────────────────────────────
  drivers: {
    all: ['drivers'] as const,
    detail: (id: number) => ['drivers', 'detail', id] as const,
    progression: (id: number) => ['drivers', 'progression', id] as const,
    styleHistory: (id: number) => ['drivers', 'style-history', id] as const,
    badges: (id: number) => ['drivers', 'badges', id] as const,
    bestEver: (id: number) => ['drivers', 'best-ever', id] as const,
    sessions: (id: number) => ['drivers', 'sessions', id] as const,
  },
```

**Step 2: Update `Driver` type in `api-types.ts`**

Replace the existing `Driver` interface:

```typescript
export interface Driver {
  id: number;
  name: string;
  notes: string | null;
  created_at: string | null;
  session_count: number;
  personal_best_s: number | null;
  mean_score: number | null;
  has_profile: boolean;
  style_label: string | null;
  total_laps: number;
}

export interface DriverProfile {
  driver_id: number;
  driver_name: string;
  weight_kg: number | null;
  kart_class: string | null;
  experience_level: string | null;
  goals: string | null;
  preferred_tracks: string | null;
  custom_notes: string | null;
  total_sessions: number;
  total_laps: number;
  best_ever_time_s: number | null;
  best_ever_track_id: string | null;
  pace_delta_mean_s: number | null;
  consistency_rating: number | null;
  aggression_index: number | null;
  smoothness_index: number | null;
  improvement_trend: string | null;
  wet_skill_proxy: number | null;
}

export interface DriverDetail extends Driver {
  profile: DriverProfile | null;
}

export interface DriverProgression {
  session_id: string;
  session_date: string | null;
  track_id: string | null;
  track_name: string | null;
  pace_delta_s: number | null;
  consistency_cv_pct: number | null;
  aggression_index: number | null;
  smoothness_index: number | null;
  total_score: number | null;
  n_laps: number | null;
}

export interface DriverStyleEntry {
  session_id: string;
  session_date: string | null;
  style_label: string | null;
  style_confidence: number | null;
  trail_braking_depth: number | null;
  brake_point_consistency: number | null;
  brake_pressure_buildup_rate: number | null;
  apex_speed_ratio: number | null;
  turn_in_aggressiveness: number | null;
  throttle_onset_delay_m: number | null;
  exit_acceleration_efficiency: number | null;
  line_variation_index: number | null;
  early_vs_late_stint_pace: number | null;
  smoothness_composite: number | null;
  strengths: string[];
  weaknesses: string[];
}

export interface DriverBadge {
  id: number;
  badge_type: string;
  badge_name: string;
  badge_level: string | null;
  metadata_json: string | null;
  earned_at: string;
}

export interface DriverBestEver {
  best_pct: number | null;
  best_track_name: string | null;
  best_driver_time: number | null;
  best_record_time: number | null;
  best_absolute_s: number | null;
  records_held: Array<Record<string, unknown>>;
}

export interface DriverSession {
  session_id: string;
  session_date: string | null;
  best_lap_time_s: number | null;
  total_score: number | null;
  n_laps: number | null;
  track_state: string | null;
  track_name: string | null;
  track_id: string | null;
}
```

**Step 3: Commit**

```bash
git add lap-website/src/lib/query-keys.ts lap-website/src/lib/api-types.ts
git commit -m "feat(frontend): add driver query keys and enriched types"
```

---

### Task 5: Frontend — Fix drivers list page

**Files:**
- Modify: `lap-website/src/app/app/drivers/page.tsx`

**Step 1: Fix the list page**

Key fixes:
1. `DriverRow` type uses `id`/`name` (not `driver_id`/`driver_name`)
2. `api.get<DriverRow[]>('/drivers')` — returns flat array, not `{ drivers: [...] }`
3. Use `queryKeys.drivers.all` for cache key
4. All template references use `driver.id` and `driver.name`

Replace the entire file content. The structure stays the same — just field names and data unwrapping change:

```tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { queryKeys } from '@/lib/query-keys';
import type { Driver } from '@/lib/api-types';
import { StatCard, QueryError, SkeletonCardGrid } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

const STYLE_COLORS: Record<string, string> = {
  Aggressive: 'bg-safety-red/10 text-safety-red',
  Smooth: 'bg-acid-green/10 text-acid-green',
  Balanced: 'bg-marshal-yellow/10 text-marshal-yellow',
  Conservative: 'bg-blue-400/10 text-blue-400',
};

/* ── Page ───────────────────────────────────────────────── */

export default function DriversPage() {

  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<'name' | 'sessions' | 'score'>('sessions');

  const { data: drivers = [], isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.drivers.all,
    queryFn: () => api.get<Driver[]>('/drivers'),
  });

  const filtered = useMemo(() => {
    let list = drivers;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((d) => d.name.toLowerCase().includes(q));
    }
    list = [...list].sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name);
      if (sort === 'sessions') return (b.session_count ?? 0) - (a.session_count ?? 0);
      if (sort === 'score') return (b.mean_score ?? 0) - (a.mean_score ?? 0);
      return 0;
    });
    return list;
  }, [drivers, search, sort]);

  // Aggregates
  const totalSessions = drivers.reduce((s, d) => s + (d.session_count ?? 0), 0);
  const totalLaps = drivers.reduce((s, d) => s + (d.total_laps ?? 0), 0);
  const bestScore = drivers.reduce<number | null>((best, d) => {
    if (d.mean_score == null) return best;
    return best == null ? d.mean_score : Math.max(best, d.mean_score);
  }, null);

  return (
    <div>
      <PageIntro title="Drivers" subtitle={`${drivers.length} driver${drivers.length !== 1 ? 's' : ''}`} />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Drivers" value={drivers.length} />
        <StatCard label="Total Sessions" value={totalSessions} />
        <StatCard label="Total Laps" value={totalLaps} />
        <StatCard label="Top Avg Score" value={bestScore?.toFixed(1) ?? '—'} unit="/100" />
      </div>

      {/* ── Filter Bar ──────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder="Search drivers..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-0 bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as 'name' | 'sessions' | 'score')}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        >
          <option value="sessions">Most Sessions</option>
          <option value="name">Alphabetical</option>
          <option value="score">Highest Score</option>
        </select>
      </div>

      {/* ── Content ─────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonCardGrid count={6} cols={3} />
      ) : error ? (
        <QueryError message="Couldn't load drivers." onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          {search ? (
            <>
              <p className="text-steel font-body text-sm">No drivers match &quot;{search}&quot;</p>
              <button type="button" onClick={() => setSearch('')}
                className="mt-3 text-pit-orange font-telemetry text-xs hover:underline">
                Clear search
              </button>
            </>
          ) : (
            <>
              <div className="text-4xl mb-3" aria-hidden="true">&#x1F464;</div>
              <h2 className="font-monument text-lg text-chalk mb-2">No drivers yet</h2>
              <p className="text-steel font-body text-sm max-w-md mx-auto">
                Drivers are automatically detected from uploaded telemetry data.
                Upload a session CSV to get started.
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((driver) => {
            const tier = scoreColor(driver.mean_score);
            return (
              <Link
                key={driver.id}
                href={`/app/drivers/${driver.id}`}
                className="group text-left bg-concrete rounded-lg border border-steel/20 p-5
                  hover:border-acid-green/40 transition-all"
              >
                {/* Name + style */}
                <div className="flex items-start justify-between">
                  <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors">
                    {driver.name}
                  </h3>
                  {driver.style_label && (
                    <span className={`px-2 py-0.5 rounded text-[10px] font-telemetry uppercase ${
                      STYLE_COLORS[driver.style_label] ?? 'bg-steel/10 text-steel'
                    }`}>
                      {driver.style_label}
                    </span>
                  )}
                </div>

                {/* Stats row */}
                <div className="flex items-center gap-3 mt-2 text-steel font-telemetry text-xs">
                  <span>{driver.session_count} session{driver.session_count !== 1 ? 's' : ''}</span>
                  <span className="text-steel/60">|</span>
                  <span>{driver.total_laps} laps</span>
                  {driver.has_profile && (
                    <>
                      <span className="text-steel/60">|</span>
                      <span className="text-acid-green/60">Profile</span>
                    </>
                  )}
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-3 mt-3">
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">PB</span>
                    <span className="text-acid-green font-telemetry text-sm">
                      {fmtTime(driver.personal_best_s)}
                    </span>
                  </div>
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">AVG SCORE</span>
                    <span className={`font-telemetry text-sm ${tier}`}>
                      {driver.mean_score?.toFixed(1) ?? '—'}
                    </span>
                  </div>
                  <div className="text-right">
                    {/* Score bar */}
                    <span className="text-steel/60 text-[10px] font-telemetry block">LEVEL</span>
                    <div className="w-full h-1.5 bg-steel/10 rounded-full mt-1">
                      <div
                        className="h-full rounded-full bg-acid-green/60"
                        style={{ width: `${Math.min(100, (driver.mean_score ?? 0))}%` }}
                      />
                    </div>
                  </div>
                </div>

                <div className="mt-3 text-right">
                  <span className="text-steel/50 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                    View profile &rarr;
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add lap-website/src/app/app/drivers/page.tsx
git commit -m "fix(frontend): fix drivers list field mapping and data unwrapping"
```

---

### Task 6: Frontend — Create driver chart components

**Files:**
- Create: `lap-website/src/components/app/drivers/ProgressionChart.tsx`
- Create: `lap-website/src/components/app/drivers/StyleRadar.tsx`
- Create: `lap-website/src/components/app/drivers/BadgeGrid.tsx`
- Create: `lap-website/src/components/app/drivers/DriverSessionsTable.tsx`

**Step 1: Create ProgressionChart**

```tsx
// lap-website/src/components/app/drivers/ProgressionChart.tsx
'use client';

import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend,
} from 'recharts';
import type { DriverProgression } from '@/lib/api-types';

interface Props {
  data: DriverProgression[];
}

function fmtDate(d: string | null): string {
  if (!d) return '';
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

export function ProgressionChart({ data }: Props) {
  if (data.length === 0) {
    return (
      <p className="text-steel font-body text-sm text-center py-8">
        No progression data yet. Upload more sessions to track improvement.
      </p>
    );
  }

  const chartData = data.map((d) => ({
    date: fmtDate(d.session_date),
    score: d.total_score,
    pace: d.pace_delta_s != null ? Math.abs(d.pace_delta_s) : null,
    consistency: d.consistency_cv_pct,
  }));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Score over time */}
      <div>
        <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-3">Score Trend</h4>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
            <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 10 }} />
            <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1a1a2e', border: '1px solid rgba(148,163,184,0.2)', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
            />
            <Line type="monotone" dataKey="score" stroke="#a3e635" strokeWidth={2} dot={{ r: 3 }} name="Score" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Consistency over time */}
      <div>
        <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-3">Consistency (CV%)</h4>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
            <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 10 }} />
            <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1a1a2e', border: '1px solid rgba(148,163,184,0.2)', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
            />
            <Line type="monotone" dataKey="consistency" stroke="#fb923c" strokeWidth={2} dot={{ r: 3 }} name="CV %" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
```

**Step 2: Create StyleRadar**

```tsx
// lap-website/src/components/app/drivers/StyleRadar.tsx
'use client';

import {
  ResponsiveContainer, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis,
} from 'recharts';
import type { DriverStyleEntry } from '@/lib/api-types';

const STYLE_COLORS: Record<string, string> = {
  Aggressive: 'bg-safety-red/10 text-safety-red',
  Smooth: 'bg-acid-green/10 text-acid-green',
  Balanced: 'bg-marshal-yellow/10 text-marshal-yellow',
  Conservative: 'bg-blue-400/10 text-blue-400',
};

interface Props {
  latest: DriverStyleEntry | null;
  history: DriverStyleEntry[];
}

const AXES: Array<{ key: keyof DriverStyleEntry; label: string }> = [
  { key: 'trail_braking_depth', label: 'Trail Braking' },
  { key: 'brake_point_consistency', label: 'Brake Consistency' },
  { key: 'apex_speed_ratio', label: 'Apex Speed' },
  { key: 'turn_in_aggressiveness', label: 'Turn-In' },
  { key: 'exit_acceleration_efficiency', label: 'Exit Accel' },
  { key: 'smoothness_composite', label: 'Smoothness' },
  { key: 'line_variation_index', label: 'Line Variation' },
  { key: 'early_vs_late_stint_pace', label: 'Stint Pace' },
];

export function StyleRadar({ latest, history }: Props) {
  if (!latest) {
    return (
      <p className="text-steel font-body text-sm text-center py-8">
        No driving style data yet.
      </p>
    );
  }

  const radarData = AXES.map(({ key, label }) => ({
    axis: label,
    value: Math.min(1, Math.max(0, (latest[key] as number) ?? 0)),
  }));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Radar */}
      <div>
        <div className="flex items-center gap-3 mb-3">
          <h4 className="font-telemetry text-xs text-steel/60 uppercase">Style Profile</h4>
          {latest.style_label && (
            <span className={`px-2 py-0.5 rounded text-[10px] font-telemetry uppercase ${
              STYLE_COLORS[latest.style_label] ?? 'bg-steel/10 text-steel'
            }`}>
              {latest.style_label}
            </span>
          )}
        </div>
        <ResponsiveContainer width="100%" height={280}>
          <RadarChart data={radarData}>
            <PolarGrid stroke="rgba(148,163,184,0.15)" />
            <PolarAngleAxis dataKey="axis" tick={{ fill: '#94a3b8', fontSize: 9 }} />
            <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
            <Radar dataKey="value" stroke="#a3e635" fill="#a3e635" fillOpacity={0.15} strokeWidth={2} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {/* Strengths + Weaknesses */}
      <div className="space-y-4">
        {latest.strengths.length > 0 && (
          <div>
            <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-2">Strengths</h4>
            <ul className="space-y-1">
              {latest.strengths.map((s, i) => (
                <li key={i} className="text-acid-green font-body text-sm flex items-center gap-2">
                  <span className="w-1 h-1 bg-acid-green rounded-full flex-shrink-0" />
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {latest.weaknesses.length > 0 && (
          <div>
            <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-2">Areas to Improve</h4>
            <ul className="space-y-1">
              {latest.weaknesses.map((w, i) => (
                <li key={i} className="text-pit-orange font-body text-sm flex items-center gap-2">
                  <span className="w-1 h-1 bg-pit-orange rounded-full flex-shrink-0" />
                  {w}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Style history labels */}
        {history.length > 1 && (
          <div>
            <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-2">Style History</h4>
            <div className="flex flex-wrap gap-2">
              {history.map((h, i) => (
                <span key={i} className={`px-2 py-0.5 rounded text-[10px] font-telemetry ${
                  STYLE_COLORS[h.style_label ?? ''] ?? 'bg-steel/10 text-steel'
                }`}>
                  {h.style_label ?? 'Unknown'}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 3: Create BadgeGrid**

```tsx
// lap-website/src/components/app/drivers/BadgeGrid.tsx
'use client';

import type { DriverBadge } from '@/lib/api-types';

const LEVEL_COLORS: Record<string, string> = {
  bronze: 'text-amber-600',
  silver: 'text-gray-300',
  gold: 'text-yellow-400',
  platinum: 'text-cyan-300',
};

interface Props {
  badges: DriverBadge[];
}

export function BadgeGrid({ badges }: Props) {
  if (badges.length === 0) {
    return (
      <p className="text-steel font-body text-sm text-center py-6">
        No badges earned yet.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
      {badges.map((b) => (
        <div
          key={b.id}
          className="bg-carbon rounded-lg border border-steel/15 p-3 text-center"
        >
          <div className={`text-2xl mb-1 ${LEVEL_COLORS[b.badge_level ?? ''] ?? 'text-steel'}`}>
            &#x1F3C6;
          </div>
          <p className="font-telemetry text-xs text-chalk truncate">{b.badge_name}</p>
          <p className="font-telemetry text-[10px] text-steel/60 uppercase mt-0.5">
            {b.badge_level ?? b.badge_type}
          </p>
          <p className="font-telemetry text-[10px] text-steel/40 mt-1">
            {new Date(b.earned_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' })}
          </p>
        </div>
      ))}
    </div>
  );
}
```

**Step 4: Create DriverSessionsTable**

```tsx
// lap-website/src/components/app/drivers/DriverSessionsTable.tsx
'use client';

import Link from 'next/link';
import type { DriverSession } from '@/lib/api-types';

interface Props {
  sessions: DriverSession[];
}

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

export function DriverSessionsTable({ sessions }: Props) {
  if (sessions.length === 0) {
    return (
      <p className="text-steel font-body text-sm text-center py-6">No sessions found.</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-steel/20">
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase">Date</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase">Track</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase text-right">Laps</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase text-right">Best Time</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase text-right">Score</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase text-right">Conditions</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.session_id} className="border-b border-steel/10 hover:bg-steel/5 transition-colors">
              <td className="py-2.5 font-telemetry text-xs text-chalk">
                <Link href={`/app/sessions/${s.session_id}`} className="hover:text-acid-green transition-colors">
                  {s.session_date ?? '—'}
                </Link>
              </td>
              <td className="py-2.5 font-body text-sm text-chalk">{s.track_name ?? '—'}</td>
              <td className="py-2.5 font-telemetry text-xs text-steel text-right">{s.n_laps ?? '—'}</td>
              <td className="py-2.5 font-telemetry text-xs text-acid-green text-right">{fmtTime(s.best_lap_time_s)}</td>
              <td className={`py-2.5 font-telemetry text-xs text-right ${scoreColor(s.total_score)}`}>
                {s.total_score?.toFixed(1) ?? '—'}
              </td>
              <td className="py-2.5 font-telemetry text-[10px] text-steel/60 text-right uppercase">
                {s.track_state ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

**Step 5: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds (components not yet imported elsewhere, tree-shaking keeps them)

**Step 6: Commit**

```bash
git add lap-website/src/components/app/drivers/
git commit -m "feat(frontend): add driver chart and table components"
```

---

### Task 7: Frontend — Rebuild driver detail page

**Files:**
- Modify: `lap-website/src/app/app/drivers/[id]/page.tsx`

**Step 1: Replace the stub with the full page**

```tsx
'use client';

import { useParams, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '@/lib/api-client';
import { queryKeys } from '@/lib/query-keys';
import type {
  DriverDetail, DriverProgression, DriverStyleEntry,
  DriverBadge, DriverBestEver, DriverSession,
} from '@/lib/api-types';
import { StatCard, QueryError, InlineEdit, SkeletonStatCards } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';
import { ProgressionChart } from '@/components/app/drivers/ProgressionChart';
import { StyleRadar } from '@/components/app/drivers/StyleRadar';
import { BadgeGrid } from '@/components/app/drivers/BadgeGrid';
import { DriverSessionsTable } from '@/components/app/drivers/DriverSessionsTable';

/* ── Helpers ───────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

const STYLE_COLORS: Record<string, string> = {
  Aggressive: 'bg-safety-red/10 text-safety-red',
  Smooth: 'bg-acid-green/10 text-acid-green',
  Balanced: 'bg-marshal-yellow/10 text-marshal-yellow',
  Conservative: 'bg-blue-400/10 text-blue-400',
};

/* ── Section wrapper ───────────────────────────────────── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-concrete rounded-lg border border-steel/20 p-5">
      <h3 className="font-monument text-sm text-chalk uppercase tracking-wider mb-4">{title}</h3>
      {children}
    </section>
  );
}

/* ── Page ───────────────────────────────────────────────── */

export default function DriverDetailPage() {
  const { id } = useParams<{ id: string }>();
  const driverId = Number(id);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // ── Queries (parallel) ──────────────────────────────
  const driverQ = useQuery({
    queryKey: queryKeys.drivers.detail(driverId),
    queryFn: () => api.get<DriverDetail>(`/drivers/${driverId}`),
  });

  const progressionQ = useQuery({
    queryKey: queryKeys.drivers.progression(driverId),
    queryFn: () => api.get<{ progression: DriverProgression[] }>(`/drivers/${driverId}/progression`),
    enabled: driverQ.isSuccess,
  });

  const styleQ = useQuery({
    queryKey: queryKeys.drivers.styleHistory(driverId),
    queryFn: () => api.get<{ history: DriverStyleEntry[] }>(`/drivers/${driverId}/style-history`),
    enabled: driverQ.isSuccess,
  });

  const badgesQ = useQuery({
    queryKey: queryKeys.drivers.badges(driverId),
    queryFn: () => api.get<{ badges: DriverBadge[] }>(`/drivers/${driverId}/badges`),
    enabled: driverQ.isSuccess,
  });

  const bestEverQ = useQuery({
    queryKey: queryKeys.drivers.bestEver(driverId),
    queryFn: () => api.get<DriverBestEver>(`/drivers/${driverId}/best-ever`),
    enabled: driverQ.isSuccess,
  });

  const sessionsQ = useQuery({
    queryKey: queryKeys.drivers.sessions(driverId),
    queryFn: () => api.get<{ sessions: DriverSession[] }>(`/drivers/${driverId}/sessions`),
    enabled: driverQ.isSuccess,
  });

  // ── Mutations ───────────────────────────────────────
  async function saveName(newName: string) {
    await api.patch(`/drivers/${driverId}`, { name: newName });
    queryClient.invalidateQueries({ queryKey: queryKeys.drivers.detail(driverId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.drivers.all });
  }

  async function saveNotes(newNotes: string) {
    await api.patch(`/drivers/${driverId}`, { notes: newNotes });
    queryClient.invalidateQueries({ queryKey: queryKeys.drivers.detail(driverId) });
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await api.delete(`/drivers/${driverId}`);
      queryClient.invalidateQueries({ queryKey: queryKeys.drivers.all });
      router.push('/app/drivers');
    } catch {
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  }

  // ── Loading / Error ─────────────────────────────────
  if (driverQ.isLoading) {
    return (
      <div>
        <PageIntro title="Driver" subtitle="Loading..." />
        <SkeletonStatCards count={5} />
      </div>
    );
  }

  if (driverQ.error) {
    return <QueryError message="Couldn't load driver." onRetry={() => driverQ.refetch()} />;
  }

  const driver = driverQ.data!;
  const progression = progressionQ.data?.progression ?? [];
  const styleHistory = styleQ.data?.history ?? [];
  const latestStyle = styleHistory.length > 0 ? styleHistory[styleHistory.length - 1] : null;
  const badges = badgesQ.data?.badges ?? [];
  const bestEver = bestEverQ.data;
  const sessions = sessionsQ.data?.sessions ?? [];

  return (
    <div className="space-y-6">

      {/* ── Header ─────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <InlineEdit
            value={driver.name}
            onSave={saveName}
            placeholder="Driver name"
          />
          <div className="mt-2">
            <InlineEdit
              value={driver.notes ?? ''}
              onSave={saveNotes}
              placeholder="Add notes..."
              multiline
              className="[&_button>span]:!font-body [&_button>span]:!text-sm [&_button>span]:!text-steel [&_button>span]:!font-normal"
            />
          </div>
        </div>
        {driver.style_label && (
          <span className={`px-3 py-1 rounded text-xs font-telemetry uppercase ${
            STYLE_COLORS[driver.style_label] ?? 'bg-steel/10 text-steel'
          }`}>
            {driver.style_label}
          </span>
        )}
      </div>

      {/* ── Stats Bar ──────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard label="Sessions" value={driver.session_count} />
        <StatCard label="Total Laps" value={driver.total_laps} />
        <StatCard label="Personal Best" value={fmtTime(driver.personal_best_s)} />
        <StatCard label="Avg Score" value={driver.mean_score?.toFixed(1) ?? '—'} unit="/100" />
        <StatCard
          label="vs Track Record"
          value={bestEver?.best_pct != null ? `${bestEver.best_pct}%` : '—'}
        />
      </div>

      {/* ── Records Held ───────────────────────────────── */}
      {bestEver && bestEver.records_held.length > 0 && (
        <Section title="Track Records Held">
          <div className="flex flex-wrap gap-3">
            {bestEver.records_held.map((r, i) => (
              <div key={i} className="bg-carbon rounded px-3 py-2 border border-acid-green/20">
                <p className="font-telemetry text-xs text-acid-green">
                  {(r as Record<string, string>).track_name ?? 'Unknown'}
                </p>
                <p className="font-telemetry text-[10px] text-steel/60">
                  {fmtTime((r as Record<string, number>).record_time_s ?? null)}
                </p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Progression ────────────────────────────────── */}
      <Section title="Progression">
        {progressionQ.isLoading ? (
          <div className="h-48 animate-pulse bg-steel/5 rounded" />
        ) : (
          <ProgressionChart data={progression} />
        )}
      </Section>

      {/* ── Driving Style ──────────────────────────────── */}
      <Section title="Driving Style">
        {styleQ.isLoading ? (
          <div className="h-48 animate-pulse bg-steel/5 rounded" />
        ) : (
          <StyleRadar latest={latestStyle} history={styleHistory} />
        )}
      </Section>

      {/* ── Badges ─────────────────────────────────────── */}
      <Section title="Badges">
        {badgesQ.isLoading ? (
          <div className="h-24 animate-pulse bg-steel/5 rounded" />
        ) : (
          <BadgeGrid badges={badges} />
        )}
      </Section>

      {/* ── Sessions ───────────────────────────────────── */}
      <Section title="Sessions">
        {sessionsQ.isLoading ? (
          <div className="h-32 animate-pulse bg-steel/5 rounded" />
        ) : (
          <DriverSessionsTable sessions={sessions} />
        )}
      </Section>

      {/* ── Danger Zone ────────────────────────────────── */}
      <section className="bg-concrete rounded-lg border border-safety-red/20 p-5">
        <h3 className="font-monument text-sm text-safety-red uppercase tracking-wider mb-3">Danger Zone</h3>
        {showDeleteConfirm ? (
          <div className="flex items-center gap-3">
            <p className="text-chalk font-body text-sm">
              Delete <strong>{driver.name}</strong> and all their sessions? This cannot be undone.
            </p>
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="px-4 py-2 bg-safety-red text-white font-telemetry text-xs rounded
                hover:bg-safety-red/80 disabled:opacity-50 transition-colors"
            >
              {deleting ? 'Deleting...' : 'Confirm Delete'}
            </button>
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(false)}
              className="px-4 py-2 bg-steel/10 text-steel font-telemetry text-xs rounded
                hover:bg-steel/20 transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowDeleteConfirm(true)}
            className="px-4 py-2 border border-safety-red/40 text-safety-red font-telemetry text-xs rounded
              hover:bg-safety-red/10 transition-colors"
          >
            Delete Driver
          </button>
        )}
      </section>
    </div>
  );
}
```

**Step 2: Delete the progression stub**

Delete `lap-website/src/app/app/drivers/[id]/progression/page.tsx`.

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add lap-website/src/app/app/drivers/
git rm lap-website/src/app/app/drivers/\[id\]/progression/page.tsx
git commit -m "feat(frontend): rebuild driver detail page with charts, style, badges, inline edit"
```

---

### Task 8: Verify everything end-to-end

**Step 1: Run backend tests**

Run: `cd telemetry_tool && python -m pytest tests/test_entity_api.py -v`
Expected: All pass

**Step 2: Run frontend build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 3: Run frontend lint**

Run: `cd lap-website && npm run lint`
Expected: No errors

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address lint/build issues from drivers re-port"
```
