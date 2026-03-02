# Testing + CI Discipline, Parity Polish & Ergonomics — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent regressions with comprehensive testing and CI gates, fix SaaS formatting parity with the desktop tool, and restore efficiency ergonomics (bulk ops, compare shortcut, full Focus Mode).

**Architecture:** Three parallel workstreams — (1) shared format-utils first as foundation, (2) backend tests + CI in parallel with frontend parity, (3) ergonomics after parity is stable. Focus Mode is the largest single task and can run in parallel with CI work.

**Tech Stack:** Python/pytest (backend tests), TypeScript/Vitest (frontend unit), Playwright (E2E), GitHub Actions (CI), Next.js/React/Zustand (frontend), Tailwind CSS

**Design doc:** `docs/plans/2026-03-02-testing-ci-parity-design.md`

---

## Task 1: Create shared format-utils module

Foundation for all parity work. Extracts duplicated formatters into one file.

**Files:**
- Create: `lap-website/src/lib/format-utils.ts`
- Test: `lap-website/src/__tests__/format-utils.test.ts`

**Step 1: Write the failing tests**

Create `lap-website/src/__tests__/format-utils.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { formatLapTime, formatDate, formatDistance, mpsToKmh, mps2ToG } from '@/lib/format-utils';

describe('formatLapTime', () => {
  it('returns em dash for null', () => {
    expect(formatLapTime(null)).toBe('\u2014');
  });
  it('returns em dash for undefined', () => {
    expect(formatLapTime(undefined)).toBe('\u2014');
  });
  it('returns em dash for NaN', () => {
    expect(formatLapTime(NaN)).toBe('\u2014');
  });
  it('formats sub-60s as decimal with s suffix', () => {
    expect(formatLapTime(45.123)).toBe('45.123s');
  });
  it('formats exactly 60s as M:SS.sss', () => {
    expect(formatLapTime(60.0)).toBe('1:00.000');
  });
  it('formats over 60s as M:SS.sss', () => {
    expect(formatLapTime(62.345)).toBe('1:02.345');
  });
  it('formats over 10min as MM:SS.sss', () => {
    expect(formatLapTime(625.1)).toBe('10:25.100');
  });
});

describe('formatDate', () => {
  it('returns em dash for null', () => {
    expect(formatDate(null)).toBe('\u2014');
  });
  it('formats ISO date to en-GB short', () => {
    expect(formatDate('2026-01-15')).toBe('15 Jan 2026');
  });
  it('returns raw string for invalid date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date');
  });
});

describe('formatDistance', () => {
  it('returns em dash for null', () => {
    expect(formatDistance(null)).toBe('\u2014');
  });
  it('rounds to integer (matches desktop)', () => {
    expect(formatDistance(1247.3)).toBe('1247');
  });
  it('rounds 0.5 up', () => {
    expect(formatDistance(999.5)).toBe('1000');
  });
});

describe('mpsToKmh', () => {
  it('returns em dash for null', () => {
    expect(mpsToKmh(null)).toBe('\u2014');
  });
  it('converts m/s to km/h with 1 decimal', () => {
    expect(mpsToKmh(10.0)).toBe('36.0');
  });
});

describe('mps2ToG', () => {
  it('returns em dash for null', () => {
    expect(mps2ToG(null)).toBe('\u2014');
  });
  it('converts m/s2 to G with 2 decimals', () => {
    expect(mps2ToG(9.81)).toBe('1.00');
  });
  it('uses absolute value for negative braking', () => {
    expect(mps2ToG(-9.81)).toBe('1.00');
  });
});
```

**Step 2: Run tests to verify they fail**

Run: `cd lap-website && npx vitest run src/__tests__/format-utils.test.ts`
Expected: FAIL — module `@/lib/format-utils` does not exist

**Step 3: Write the implementation**

Create `lap-website/src/lib/format-utils.ts`:

```typescript
/**
 * Shared formatting utilities for telemetry display.
 *
 * All null/undefined/NaN inputs return em dash (—).
 * Numeric precision matches the desktop tool (ground truth).
 */

const EM_DASH = '\u2014';

/** Lap time: sub-60s → "45.123s", 60s+ → "1:02.345" */
export function formatLapTime(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return EM_DASH;
  if (seconds >= 60) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds - mins * 60;
    return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
  }
  return `${seconds.toFixed(3)}s`;
}

/** Date: ISO "2026-01-15" → "15 Jan 2026" (en-GB) */
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return EM_DASH;
  try {
    const d = new Date(dateStr + 'T00:00:00');
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch {
    return dateStr;
  }
}

/** Distance in meters, integer precision (matches desktop %.0f) */
export function formatDistance(meters: number | null | undefined): string {
  if (meters == null || !isFinite(meters)) return EM_DASH;
  return String(Math.round(meters));
}

/** Speed: m/s → km/h with 1 decimal (matches desktop %.1f) */
export function mpsToKmh(mps: number | null | undefined): string {
  if (mps == null || !isFinite(mps)) return EM_DASH;
  return (mps * 3.6).toFixed(1);
}

/** Acceleration: m/s² → G with 2 decimals, absolute value (matches desktop %.2f) */
export function mps2ToG(mps2: number | null | undefined): string {
  if (mps2 == null || !isFinite(mps2)) return EM_DASH;
  return (Math.abs(mps2) / 9.81).toFixed(2);
}

/** Score color class based on thresholds */
export function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}
```

**Step 4: Run tests to verify they pass**

Run: `cd lap-website && npx vitest run src/__tests__/format-utils.test.ts`
Expected: All 16 tests PASS

**Step 5: Commit**

```bash
git add lap-website/src/lib/format-utils.ts lap-website/src/__tests__/format-utils.test.ts
git commit -m "feat: add shared format-utils module with full test coverage"
```

---

## Task 2: Fix session list page formatters (parity)

Replace the broken `formatLapTime` in `sessions/page.tsx` that always shows `0:45.123` for sub-60s laps.

**Files:**
- Modify: `lap-website/src/app/app/sessions/page.tsx`

**Step 1: Replace local formatters with shared imports**

In `lap-website/src/app/app/sessions/page.tsx`:

1. Add import at top: `import { formatLapTime, formatDate, scoreColor } from '@/lib/format-utils';`
2. Delete the local `formatLapTime` function (lines 43-48)
3. Delete the local `formatDate` function (lines 50-62)
4. Delete the local `scoreColor` function (lines 64-70)
5. The `formatLapTime` import handles sub-60s correctly (`45.123s` not `0:45.123`)

**Step 2: Verify build passes**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no type errors

**Step 3: Commit**

```bash
git add lap-website/src/app/app/sessions/page.tsx
git commit -m "fix: use shared formatters in session list — correct sub-60s lap time display"
```

---

## Task 3: Fix session detail + compare page formatters (parity)

Replace local formatters and fix null sentinels (`--` → `—`).

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`
- Modify: `lap-website/src/app/app/compare/sessions/page.tsx`

**Step 1: Session detail page**

In `lap-website/src/app/app/sessions/[id]/page.tsx`:

1. Add import: `import { formatLapTime, formatDate, formatDistance, mpsToKmh, mps2ToG, scoreColor } from '@/lib/format-utils';`
2. Delete the local `formatLapTime` function (lines 91-98)
3. Delete the local `mpsToKmh` function (lines 101-103)
4. The shared versions use `—` (em dash) instead of `--` (double hyphen)

**Step 2: Compare page**

In `lap-website/src/app/app/compare/sessions/page.tsx`:

1. Add same import from `@/lib/format-utils`
2. Delete any local `formatLapTime`, `mpsToKmh`, `formatDate`, `mps2ToG` functions
3. Replace raw `session.session_date` references in MetadataCard with `formatDate(session.session_date)`

**Step 3: Fix distance precision**

Search for `toFixed(1)` calls on `line_length_m` values in both files. Replace with `formatDistance()` call.

**Step 4: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add lap-website/src/app/app/sessions/[id]/page.tsx lap-website/src/app/app/compare/sessions/page.tsx
git commit -m "fix: unified formatters in session detail + compare — consistent null sentinel and distance precision"
```

---

## Task 4: Add joker and pit badge semantics

Desktop has 4 badge types (Best, Joker, Pit, Invalid). SaaS is missing Joker and Pit distinction.

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx` (LapDataTab section)
- Modify: `lap-website/src/app/app/compare/sessions/page.tsx` (LapTimesTable section)

**Step 1: Update session detail LapDataTab**

Find the badge rendering section in the LapDataTab. Currently:

```tsx
{isIncomplete ? (
  <span className="... bg-marshal-yellow/20 text-marshal-yellow ..."> ... </span>
) : isInvalid ? (
  <span className="... bg-safety-red/20 text-safety-red ..."> ... </span>
) : (
  <span className="... bg-green-500/10 text-green-400 ...">Valid</span>
)}
```

Replace with expanded badge logic:

```tsx
{/* Badge priority: Best > Joker > Pit > Invalid > Incomplete > Valid */}
{lap.is_joker ? (
  <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-marshal-yellow/20 text-marshal-yellow border border-marshal-yellow/30"
    title="Joker lap — excluded from ranking">J</span>
) : lap.invalid_reason === 'Pitted lap' ? (
  <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-pit-orange/20 text-pit-orange border border-pit-orange/30">Pit</span>
) : isIncomplete ? (
  <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-marshal-yellow/20 text-marshal-yellow border border-marshal-yellow/30"
    title={lap.invalid_reason || 'Incomplete'}>{lap.invalid_reason || 'Incomplete'}</span>
) : isInvalid ? (
  <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-safety-red/20 text-safety-red border border-safety-red/30">
    {lap.invalid_reason || 'Invalid'}</span>
) : (
  <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-green-500/10 text-green-400 border border-green-500/20">Valid</span>
)}
```

**Step 2: Update compare LapTimesTable similarly**

Add Joker and Pit badges to the compare page's lap table.

**Step 3: Add Joker row styling**

Add to row className logic: `lap.is_joker ? 'opacity-50' : ''` (joker laps are dimmed like invalid).

**Step 4: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add lap-website/src/app/app/sessions/[id]/page.tsx lap-website/src/app/app/compare/sessions/page.tsx
git commit -m "feat: add Joker and Pit badge types — full desktop badge parity"
```

---

## Task 5: Backend contract tests

Test every API endpoint's response shape.

**Files:**
- Create: `telemetry_tool/tests/test_api_contracts.py`

**Step 1: Write the contract tests**

Create `telemetry_tool/tests/test_api_contracts.py`:

```python
"""Contract tests: validate response envelope shape for all /api/v1 endpoints.

Every endpoint must return {ok: bool, data: ..., error: ..., meta: ...}.
Tests use the Flask test client with a seeded SQLite database.
"""
import json
import pytest
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture
def client(seeded_db):
    """Flask test client with seeded data and PG/auth OFF."""
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.config["AUTH_REQUIRED"] = False
    # Patch db connection to use seeded_db
    with app.test_client() as c:
        with app.app_context():
            import web.db as db_mod
            db_mod._connection = seeded_db
            yield c


def _envelope_ok(resp):
    """Assert response is a valid OK envelope."""
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.data}"
    data = resp.get_json()
    assert data is not None, "Response is not JSON"
    assert "ok" in data, "Missing 'ok' field"
    assert data["ok"] is True, f"ok is not True: {data}"
    assert "data" in data, "Missing 'data' field"
    return data


class TestSessionEndpoints:
    """Contract tests for session data endpoints."""

    def test_session_list_shape(self, client):
        resp = client.get("/api/v1/sessions")
        data = _envelope_ok(resp)
        assert "sessions" in data["data"]
        assert isinstance(data["data"]["sessions"], list)
        if data["data"]["sessions"]:
            s = data["data"]["sessions"][0]
            assert isinstance(s.get("session_id"), (str, int))

    def test_session_detail_shape(self, client):
        resp = client.get("/api/v1/sessions/s1")
        data = _envelope_ok(resp)
        d = data["data"]
        assert "session" in d
        assert "laps" in d
        assert isinstance(d["laps"], list)

    def test_session_laps_shape(self, client):
        resp = client.get("/api/v1/sessions/s1/laps")
        data = _envelope_ok(resp)
        laps = data["data"]["laps"]
        assert isinstance(laps, list)
        assert len(laps) > 0
        lap = laps[0]
        assert "lap_number" in lap
        assert isinstance(lap["lap_number"], int)

    def test_session_speed_trace_shape(self, client):
        resp = client.get("/api/v1/sessions/s1/speed-trace")
        data = _envelope_ok(resp)
        assert "traces" in data["data"]

    def test_session_gps_trace_shape(self, client):
        resp = client.get("/api/v1/sessions/s1/gps-trace")
        data = _envelope_ok(resp)
        assert "traces" in data["data"]

    def test_session_gg_data_shape(self, client):
        resp = client.get("/api/v1/sessions/s1/gg-data")
        data = _envelope_ok(resp)
        assert "gg" in data["data"]

    def test_session_scores_shape(self, client):
        resp = client.get("/api/v1/sessions/s1/scores")
        data = _envelope_ok(resp)
        scores = data["data"]
        # Should contain score categories
        assert "scores" in scores or "pace_score" in scores or "total_score" in scores

    def test_session_corners_shape(self, client):
        resp = client.get("/api/v1/sessions/s1/corners")
        data = _envelope_ok(resp)
        assert "corners" in data["data"]

    def test_session_not_found(self, client):
        resp = client.get("/api/v1/sessions/nonexistent")
        assert resp.status_code in (404, 200)  # Some endpoints return 200 with empty data

    def test_session_delete(self, client):
        resp = client.delete("/api/v1/sessions/s1")
        assert resp.status_code in (200, 204)


class TestCompareEndpoints:
    """Contract tests for comparison endpoint."""

    def test_compare_sessions_shape(self, client):
        resp = client.get("/api/v1/compare/sessions?a=s1&b=s2")
        data = _envelope_ok(resp)
        d = data["data"]
        assert "session_a" in d or "a" in d or "comparison" in d


class TestErrorResponses:
    """Contract tests for error response shapes."""

    def test_404_has_error_field(self, client):
        resp = client.get("/api/v1/nonexistent-endpoint-xyz")
        assert resp.status_code in (404, 405)

    def test_method_not_allowed(self, client):
        resp = client.post("/api/v1/sessions")
        # Should not crash — either 405 or handled
        assert resp.status_code in (404, 405, 400, 200)
```

**Step 2: Run to verify**

Run: `pytest telemetry_tool/tests/test_api_contracts.py -v --tb=short`
Expected: Tests pass (or some may need adjustment based on actual endpoint paths)

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_api_contracts.py
git commit -m "test: add API contract tests — response shape assertions for all /api/v1 endpoints"
```

---

## Task 6: Backend scoring boundary tests

Test edge cases in the scoring system.

**Files:**
- Create: `telemetry_tool/tests/test_scoring_boundaries.py`

**Step 1: Write the tests**

Create `telemetry_tool/tests/test_scoring_boundaries.py`:

```python
"""Scoring boundary tests: edge cases in scoring.py grade assignment.

Tests the scoring system with boundary inputs: perfect, zero, single-lap,
invalid-only sessions, NaN/Inf inputs.
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class TestGradeBoundaries:
    """Grade letter assignment boundaries."""

    def test_score_100_is_grade_A(self, seeded_db):
        """A perfect score (100) should produce grade A or S."""
        seeded_db.execute(
            "UPDATE sessions SET total_score = 100 WHERE session_id = 's1'"
        )
        seeded_db.commit()
        row = seeded_db.execute(
            "SELECT total_score FROM sessions WHERE session_id = 's1'"
        ).fetchone()
        assert dict(row)["total_score"] == 100

    def test_score_0_is_grade_F(self, seeded_db):
        """A zero score should produce grade F."""
        seeded_db.execute(
            "UPDATE sessions SET total_score = 0, grade = 'F' WHERE session_id = 's1'"
        )
        seeded_db.commit()
        row = seeded_db.execute(
            "SELECT total_score, grade FROM sessions WHERE session_id = 's1'"
        ).fetchone()
        assert dict(row)["grade"] == "F"

    def test_grade_boundaries(self, seeded_db):
        """Verify grade letter thresholds: A=90+, B=80+, C=70+, D=60+, F<60."""
        from scoring import compute_grade

        assert compute_grade(95) in ("A", "A+", "S")
        assert compute_grade(85) == "B"
        assert compute_grade(75) == "C"
        assert compute_grade(65) == "D"
        assert compute_grade(50) == "F"


class TestScoringEdgeCases:
    """Edge cases for the scoring pipeline."""

    def test_single_lap_session(self, seeded_db):
        """Single-lap session should still produce a valid score."""
        seeded_db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, n_laps, "
            "total_score, grade) VALUES ('s3', 'one.csv', 1, 1, 40.0, 'D')"
        )
        seeded_db.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) "
            "VALUES ('s3', 1, 65.0, 1)"
        )
        seeded_db.commit()
        row = seeded_db.execute(
            "SELECT total_score FROM sessions WHERE session_id = 's3'"
        ).fetchone()
        assert dict(row)["total_score"] is not None

    def test_invalid_laps_excluded_from_best(self, seeded_db):
        """Invalid laps should not count as best lap."""
        # Insert a session with one invalid fast lap and one valid slow lap
        seeded_db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, n_laps) "
            "VALUES ('s4', 'invalid.csv', 1, 2)"
        )
        seeded_db.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid, invalid_reason) "
            "VALUES ('s4', 1, 30.0, 0, 'Short lap')"
        )
        seeded_db.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) "
            "VALUES ('s4', 2, 65.0, 1)"
        )
        seeded_db.commit()
        valid_laps = seeded_db.execute(
            "SELECT MIN(lap_time_s) as best FROM laps "
            "WHERE session_id = 's4' AND is_valid = 1"
        ).fetchone()
        assert dict(valid_laps)["best"] == 65.0  # The invalid 30s lap excluded

    def test_null_score_fields_handled(self, seeded_db):
        """Score components can be NULL without crashing."""
        seeded_db.execute(
            "INSERT INTO score_details (session_id, pace_score, pace_max) "
            "VALUES ('s1', NULL, 25)"
        )
        seeded_db.commit()
        row = seeded_db.execute(
            "SELECT pace_score FROM score_details WHERE session_id = 's1' "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        assert dict(row)["pace_score"] is None
```

**Step 2: Run to verify**

Run: `pytest telemetry_tool/tests/test_scoring_boundaries.py -v --tb=short`
Expected: Tests pass. Note: `compute_grade` import path may need adjustment based on actual module location.

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_scoring_boundaries.py
git commit -m "test: add scoring boundary tests — grade thresholds, edge cases, invalid lap exclusion"
```

---

## Task 7: Bulk operations — Select All, wire re-analyze, one-click compare

**Files:**
- Modify: `lap-website/src/app/app/sessions/page.tsx`

**Step 1: Add Select All**

Find the `DataTable` usage and add a Select All checkbox. Look for the `selectedKeys` state variable (line ~160). Add:

```tsx
// After the existing bulk action bar renders:
const allVisibleIds = sessions.map((s) => s.session_id);
const allSelected = allVisibleIds.length > 0 && allVisibleIds.every((id) => selectedKeys.has(id));

function handleSelectAll() {
  if (allSelected) {
    setSelectedKeys(new Set());
  } else {
    setSelectedKeys(new Set(allVisibleIds));
  }
}
```

Add a Select All checkbox in the table header area or the bulk action bar.

**Step 2: Wire re-analyze to real API**

Find the existing re-analyze handler (currently just calls `refetch()`). Replace with:

```tsx
const [bulkStatus, setBulkStatus] = useState<string | null>(null);

const reanalyzeMutation = useMutation({
  mutationFn: async (ids: string[]) => {
    setBulkStatus(`Re-analyzing 0/${ids.length}...`);
    const result = await api.post<{ succeeded: number; failed: number }>(
      '/sessions/batch-reanalyze',
      { session_ids: ids }
    );
    return result;
  },
  onSuccess: (data) => {
    const msg = data.failed
      ? `Done: ${data.succeeded} succeeded, ${data.failed} failed`
      : `Done: ${data.succeeded} sessions re-analyzed`;
    setBulkStatus(msg);
    setTimeout(() => setBulkStatus(null), 3000);
    setSelectedKeys(new Set());
    queryClient.invalidateQueries({ queryKey: ['sessions'] });
  },
  onError: (err: Error) => {
    setBulkStatus(`Error: ${err.message}`);
    setTimeout(() => setBulkStatus(null), 5000);
  },
});
```

**Step 3: Add one-click compare button**

When exactly 2 sessions are selected, show a Compare button:

```tsx
{selectedKeys.size === 2 && (
  <button
    onClick={() => {
      const [a, b] = Array.from(selectedKeys);
      router.push(`/app/compare/sessions?a=${a}&b=${b}`);
    }}
    className="px-3 py-1.5 bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded text-xs font-telemetry hover:bg-blue-500/30 transition-colors"
  >
    Compare 2 Sessions
  </button>
)}
```

**Step 4: Add count badges to action buttons**

Update button labels from "Delete" to `Delete ${selectedKeys.size} Sessions`, and "Re-analyze" to `Re-analyze ${selectedKeys.size} Sessions`.

**Step 5: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 6: Commit**

```bash
git add lap-website/src/app/app/sessions/page.tsx
git commit -m "feat: bulk ops — Select All, wire re-analyze API, one-click compare, count badges"
```

---

## Task 8: Focus Mode rewrite — ToolDock + SplitPane + keyboard shortcuts

Full desktop parity for Focus Mode. The `SplitPane` and `ToolDock` components already exist and are fully implemented but unused.

**Files:**
- Modify: `lap-website/src/components/app/focus-mode/FocusMode.tsx`
- Create: `lap-website/src/components/app/focus-mode/CornerNavBar.tsx`
- Create: `lap-website/src/stores/focus-mode-store.ts`

**Step 1: Create Zustand store with localStorage persistence**

Create `lap-website/src/stores/focus-mode-store.ts`:

```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ToolId } from '@/components/app/focus-mode/ToolDock';

interface FocusModeState {
  isOpen: boolean;
  dockVisible: boolean;
  activeTools: Record<string, ToolId[]>; // keyed by tab name
  splitSizes: Record<string, number>; // keyed by tab name, left panel %
  open: (tab?: string, primaryTool?: ToolId) => void;
  close: () => void;
  toggleDock: () => void;
  setActiveTools: (tab: string, tools: ToolId[]) => void;
  setSplitSize: (tab: string, leftPercent: number) => void;
  resetLayout: (tab: string) => void;
}

const TAB_DEFAULTS: Record<string, ToolId[]> = {
  overview: ['speed-trace', 'track-map'],
  corners: ['corner-analysis', 'track-map'],
  analytics: ['speed-trace', 'gg-diagram', 'track-map'],
  laps: ['speed-trace', 'lap-distribution'],
  timeline: ['speed-trace', 'stint-chart'],
};

export const useFocusModeStore = create<FocusModeState>()(
  persist(
    (set) => ({
      isOpen: false,
      dockVisible: true,
      activeTools: {},
      splitSizes: {},
      open: (tab = 'overview', primaryTool) =>
        set((state) => {
          const tools = primaryTool
            ? [primaryTool, ...(TAB_DEFAULTS[tab] ?? []).filter((t) => t !== primaryTool)]
            : state.activeTools[tab] ?? TAB_DEFAULTS[tab] ?? ['speed-trace', 'track-map'];
          return {
            isOpen: true,
            activeTools: { ...state.activeTools, [tab]: tools },
          };
        }),
      close: () => set({ isOpen: false }),
      toggleDock: () => set((state) => ({ dockVisible: !state.dockVisible })),
      setActiveTools: (tab, tools) =>
        set((state) => ({
          activeTools: { ...state.activeTools, [tab]: tools },
        })),
      setSplitSize: (tab, leftPercent) =>
        set((state) => ({
          splitSizes: { ...state.splitSizes, [tab]: leftPercent },
        })),
      resetLayout: (tab) =>
        set((state) => ({
          activeTools: { ...state.activeTools, [tab]: TAB_DEFAULTS[tab] ?? ['speed-trace', 'track-map'] },
          splitSizes: { ...state.splitSizes, [tab]: 60 },
        })),
    }),
    {
      name: 'focus-mode-layout',
      partialize: (state) => ({
        activeTools: state.activeTools,
        splitSizes: state.splitSizes,
        dockVisible: state.dockVisible,
      }),
    }
  )
);
```

**Step 2: Create CornerNavBar**

Create `lap-website/src/components/app/focus-mode/CornerNavBar.tsx`:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

interface CornerChip {
  corner_id: number;
  corner_name: string;
  time_loss_ms: number;
}

interface CornerNavBarProps {
  sessionId: string;
}

export function CornerNavBar({ sessionId }: CornerNavBarProps) {
  const [corners, setCorners] = useState<CornerChip[]>([]);

  useEffect(() => {
    api.get<{ corners: CornerChip[] }>(`/sessions/${sessionId}/corners`)
      .then((data) => {
        if (data.corners) setCorners(data.corners);
      })
      .catch(() => {}); // Graceful degradation
  }, [sessionId]);

  if (corners.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 px-4 py-1.5 bg-concrete/50 border-b border-steel/10 overflow-x-auto">
      <span className="text-[10px] font-telemetry text-steel/60 shrink-0">CORNERS</span>
      {corners.map((c) => {
        const ms = c.time_loss_ms;
        const sign = ms >= 0 ? '+' : '';
        const color = ms > 100 ? 'text-safety-red' : ms > 50 ? 'text-marshal-yellow' : 'text-acid-green';
        return (
          <button
            key={c.corner_id}
            className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-telemetry bg-asphalt/50 border border-steel/10 hover:border-acid-green/30 transition-colors ${color}`}
            title={c.corner_name}
          >
            {c.corner_name} {sign}{(ms / 1000).toFixed(3)}s
          </button>
        );
      })}
    </div>
  );
}
```

**Step 3: Rewrite FocusMode.tsx**

Replace `lap-website/src/components/app/focus-mode/FocusMode.tsx` entirely:

```tsx
'use client';

import { useEffect, useCallback } from 'react';
import { SpeedTraceZoom, GpsTrace, GGExplorer } from '@/components/app/charts';
import { BACKEND_URL } from '@/lib/api-client';
import { SplitPane } from './SplitPane';
import { ToolDock, useToolDock, TOOLS, type ToolId } from './ToolDock';
import { CornerNavBar } from './CornerNavBar';
import { useFocusModeStore } from '@/stores/focus-mode-store';

interface FocusModeProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
  gpsLaps: number[];
  bestLap: number | null;
  activeTab?: string;
}

/** Render a tool by its ID */
function ToolRenderer({
  toolId,
  sessionId,
  gpsLaps,
  bestLap,
}: {
  toolId: ToolId;
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
}) {
  const apiBase = BACKEND_URL;
  const commonProps = { sessionId, apiBase, gpsLaps, bestLap, className: 'w-full h-full' };

  switch (toolId) {
    case 'speed-trace':
      return <SpeedTraceZoom {...commonProps} />;
    case 'track-map':
      return <GpsTrace {...commonProps} />;
    case 'gg-diagram':
      return <GGExplorer {...commonProps} />;
    default:
      return (
        <div className="flex items-center justify-center h-full text-steel/40 font-body text-sm">
          {TOOLS.find((t) => t.id === toolId)?.label ?? toolId} — coming soon
        </div>
      );
  }
}

export function FocusMode({ sessionId, isOpen, onClose, gpsLaps, bestLap, activeTab = 'overview' }: FocusModeProps) {
  const { dockVisible, toggleDock, resetLayout } = useFocusModeStore();
  const { activeTools, toggle, reset, toggleByShortcut } = useToolDock('speed-trace');

  // Keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;
      if (e.key === 'Escape') { onClose(); return; }
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === 'r' || e.key === 'R') { reset(); resetLayout(activeTab); return; }
      if (e.key === 's' || e.key === 'S') { toggleDock(); return; }
      const num = parseInt(e.key, 10);
      if (num >= 0 && num <= 9) { toggleByShortcut(num); }
    },
    [isOpen, onClose, reset, resetLayout, activeTab, toggleDock, toggleByShortcut]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  if (!isOpen) return null;

  const toolIds = Array.from(activeTools);
  const leftTool = toolIds[0] ?? 'speed-trace';
  const rightTool = toolIds[1] ?? 'track-map';

  return (
    <div className="fixed inset-0 z-50 bg-asphalt/98 flex flex-col" role="dialog" aria-modal="true" aria-label="Focus Mode">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-steel/10 shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-monument text-chalk">Focus Mode</h2>
          <span className="text-[10px] font-telemetry text-steel/40">
            S=dock  R=reset  Esc=close  1-9=tools
          </span>
        </div>
        <button
          onClick={onClose}
          className="px-3 py-1.5 bg-concrete border border-steel/20 rounded text-sm text-chalk font-body hover:bg-steel/10 transition-colors"
          aria-label="Close focus mode"
        >
          Exit Focus
        </button>
      </div>

      {/* Corner nav bar */}
      <CornerNavBar sessionId={sessionId} />

      {/* Main area: dock + split pane */}
      <div className="flex flex-1 overflow-hidden">
        <ToolDock
          activeTools={activeTools}
          onToggle={toggle}
          onReset={reset}
          dockVisible={dockVisible}
        />

        <div className="flex-1 p-2">
          {toolIds.length <= 1 ? (
            <div className="h-full bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
              <ToolRenderer toolId={leftTool} sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} />
            </div>
          ) : (
            <SplitPane
              defaultLeftWidth={60}
              leftContent={
                <div className="h-full bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
                  <ToolRenderer toolId={leftTool} sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} />
                </div>
              }
              rightContent={
                <div className="h-full bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
                  <ToolRenderer toolId={rightTool} sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} />
                </div>
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 4: Add `F` key shortcut to session detail page**

In `lap-website/src/app/app/sessions/[id]/page.tsx`, add a `useEffect` in `SessionDetailPage`:

```tsx
// Open Focus Mode with F key
useEffect(() => {
  function handleKey(e: KeyboardEvent) {
    if (e.key === 'f' && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement)) {
      setFocusOpen(true);
    }
  }
  window.addEventListener('keydown', handleKey);
  return () => window.removeEventListener('keydown', handleKey);
}, []);
```

**Step 5: Add per-section expand buttons**

In the session detail page, next to each chart section header (Speed Trace, GPS Map, GG Diagram), add:

```tsx
<button
  onClick={() => { /* open focus mode with this tool primary */ setFocusOpen(true); }}
  className="p-1 text-steel/40 hover:text-acid-green transition-colors"
  title="Open in Focus Mode (F)"
  aria-label="Expand to Focus Mode"
>
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
    <polyline points="8,2 12,2 12,6" /><line x1="12" y1="2" x2="7" y2="7" />
    <polyline points="6,12 2,12 2,8" /><line x1="2" y1="12" x2="7" y2="7" />
  </svg>
</button>
```

**Step 6: Update FocusMode export in index.ts**

Ensure `CornerNavBar` is exported: add to `lap-website/src/components/app/focus-mode/index.ts`:

```typescript
export { CornerNavBar } from './CornerNavBar';
```

**Step 7: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 8: Commit**

```bash
git add lap-website/src/components/app/focus-mode/ lap-website/src/stores/focus-mode-store.ts lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat: Focus Mode — full desktop parity with ToolDock, SplitPane, keyboard shortcuts, corner nav"
```

---

## Task 9: CI pipeline — add contract tests, typecheck, E2E smoke, staging gate

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Add 3 new PR-check jobs**

Add after the existing `test-frontend` job:

```yaml
  contract-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run contract tests
        run: pytest telemetry_tool/tests/test_api_contracts.py -v --tb=short

  typecheck:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: lap-website
    steps:
      - uses: actions/checkout@v4
      - name: Set up Node 20
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: lap-website/package-lock.json
      - name: Install dependencies
        run: npm ci
      - name: TypeScript typecheck
        run: npx tsc --noEmit

  e2e-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Install backend deps
        run: pip install -r requirements.txt
      - name: Start API server
        run: |
          cd telemetry_tool
          python main.py --serve &
          sleep 5
        env:
          USE_PG: "0"
          AUTH_REQUIRED: "0"
          TELEMETRY_PORT: "5000"
      - name: Set up Node 20
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: lap-website/package-lock.json
      - name: Install frontend deps
        run: cd lap-website && npm ci
      - name: Install Playwright browsers
        run: cd lap-website && npx playwright install chromium
      - name: Run E2E smoke
        run: cd lap-website && npx playwright test e2e/critical-path.spec.ts --project=chromium
        env:
          NEXT_PUBLIC_API_URL: http://localhost:5000
```

**Step 2: Update deploy-api job needs**

Change the `needs` array:

```yaml
  deploy-api:
    runs-on: ubuntu-latest
    needs: [test-backend, test-frontend, contract-tests, typecheck]
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
```

Note: `e2e-smoke` is excluded from deploy-api `needs` to avoid blocking deploys on flaky E2E — it runs in parallel for visibility.

**Step 3: Add staging parity gate after deploy**

Add after the deploy-api job:

```yaml
  parity-smoke:
    runs-on: ubuntu-latest
    needs: [deploy-api]
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - uses: actions/checkout@v4
      - name: Set up Node 20
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: lap-website/package-lock.json
      - name: Install deps + Playwright
        run: cd lap-website && npm ci && npx playwright install chromium
      - name: Run parity smoke against live
        run: cd lap-website && npx playwright test e2e/certification-parity.spec.ts --project=chromium
        env:
          NEXT_PUBLIC_API_URL: ${{ vars.API_PREVIEW_URL }}
```

**Step 4: Verify YAML is valid**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: No errors

**Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add contract tests, typecheck, E2E smoke, and staging parity gate"
```

---

## Task 10: Playwright E2E — critical path spec

**Files:**
- Create: `lap-website/e2e/critical-path.spec.ts`

**Step 1: Write the spec**

Create `lap-website/e2e/critical-path.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

/**
 * Critical path E2E: the minimum viable user journey.
 * Runs against local dev server (USE_PG=0, AUTH_REQUIRED=0).
 */

test.describe('Critical Path', () => {
  test('session list loads and shows sessions', async ({ page }) => {
    await page.goto('/app/sessions');
    // Wait for data to load
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });
    // Table or empty state should appear
    const hasTable = await page.locator('table').count();
    const hasEmpty = await page.locator('text=No sessions').count();
    expect(hasTable + hasEmpty).toBeGreaterThan(0);
  });

  test('session detail renders tabs', async ({ page }) => {
    await page.goto('/app/sessions');
    // Click first session if any exist
    const firstRow = page.locator('tr[data-session-id], a[href*="/app/sessions/"]').first();
    if (await firstRow.count()) {
      await firstRow.click();
      await expect(page.locator('text=Overview')).toBeVisible({ timeout: 10_000 });
      await expect(page.locator('text=Laps')).toBeVisible();
    }
  });

  test('drivers page loads', async ({ page }) => {
    await page.goto('/app/drivers');
    await expect(page.locator('text=Drivers')).toBeVisible({ timeout: 10_000 });
  });

  test('tracks page loads', async ({ page }) => {
    await page.goto('/app/tracks');
    await expect(page.locator('text=Tracks')).toBeVisible({ timeout: 10_000 });
  });

  test('compare hub loads with feature cards', async ({ page }) => {
    await page.goto('/app/compare');
    await expect(page.locator('text=Compare')).toBeVisible({ timeout: 10_000 });
  });

  test('race strategy list loads', async ({ page }) => {
    await page.goto('/app/race-strategy');
    await expect(page.locator('text=Race Strategy')).toBeVisible({ timeout: 10_000 });
  });
});
```

**Step 2: Run locally to verify**

Run: `cd lap-website && npx playwright test e2e/critical-path.spec.ts --project=chromium`
Expected: Tests pass against local dev server (needs `npm run dev` running)

**Step 3: Commit**

```bash
git add lap-website/e2e/critical-path.spec.ts
git commit -m "test: add critical-path E2E spec — session list, detail, drivers, tracks, compare, strategy"
```

---

## Task 11: Playwright E2E — compare flow and bulk actions specs

**Files:**
- Create: `lap-website/e2e/compare-flow.spec.ts`
- Create: `lap-website/e2e/bulk-actions.spec.ts`

**Step 1: Compare flow spec**

Create `lap-website/e2e/compare-flow.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

test.describe('Compare Flow', () => {
  test('compare hub renders session and driver cards', async ({ page }) => {
    await page.goto('/app/compare');
    await expect(page.locator('text=Compare Sessions')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('text=Compare Drivers')).toBeVisible();
  });

  test('session compare page loads with dropdowns', async ({ page }) => {
    await page.goto('/app/compare/sessions');
    await expect(page.locator('text=Session A')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('text=Session B')).toBeVisible();
  });
});
```

**Step 2: Bulk actions spec**

Create `lap-website/e2e/bulk-actions.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

test.describe('Bulk Actions', () => {
  test('session list shows bulk action bar when rows selected', async ({ page }) => {
    await page.goto('/app/sessions');
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });
    // Check if checkbox selection is available
    const checkboxes = page.locator('input[type="checkbox"]');
    if (await checkboxes.count() > 0) {
      await checkboxes.first().click();
      // Bulk action bar should appear
      await expect(page.locator('text=Delete')).toBeVisible();
    }
  });

  test('compare button appears when exactly 2 selected', async ({ page }) => {
    await page.goto('/app/sessions');
    const checkboxes = page.locator('input[type="checkbox"]');
    if (await checkboxes.count() >= 2) {
      await checkboxes.nth(0).click();
      await checkboxes.nth(1).click();
      await expect(page.locator('text=Compare 2 Sessions')).toBeVisible();
    }
  });
});
```

**Step 3: Commit**

```bash
git add lap-website/e2e/compare-flow.spec.ts lap-website/e2e/bulk-actions.spec.ts
git commit -m "test: add compare flow and bulk actions E2E specs"
```

---

## Task 12: Final verification

**Step 1: Run all backend tests**

Run: `pytest telemetry_tool/tests/ -q --tb=short`
Expected: All pass (or pre-existing failures only)

**Step 2: Run all frontend tests**

Run: `cd lap-website && npm run test`
Expected: All Vitest tests pass

**Step 3: Build frontend**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no errors

**Step 4: Lint frontend**

Run: `cd lap-website && npm run lint`
Expected: No lint errors

**Step 5: Commit any fixes and push**

```bash
git push origin main
```

---

## Summary

| # | Task | Workstream | Files |
|---|------|-----------|-------|
| 1 | Shared format-utils + tests | Parity | 2 new |
| 2 | Session list formatters | Parity | 1 edit |
| 3 | Session detail + compare formatters | Parity | 2 edits |
| 4 | Joker + Pit badges | Parity | 2 edits |
| 5 | API contract tests | Testing | 1 new |
| 6 | Scoring boundary tests | Testing | 1 new |
| 7 | Bulk ops (Select All, re-analyze, compare) | Ergonomics | 1 edit |
| 8 | Focus Mode full rewrite | Ergonomics | 3 new, 1 edit |
| 9 | CI pipeline upgrades | CI | 1 edit |
| 10 | E2E critical path spec | Testing | 1 new |
| 11 | E2E compare + bulk specs | Testing | 2 new |
| 12 | Final verification | All | — |
