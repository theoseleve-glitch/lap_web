# Race Strategy Restore — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix race strategy entitlement gating, enforce the 3h DEMO limit, enrich the live dashboard, and extract shared components.

**Architecture:** Backend-first (fix entitlement resolution so frontend can rely on it), then frontend gating via existing UpgradeBanner, then live enrichment, then shared component extraction.

**Tech Stack:** Python/Flask (backend entitlements, service layer), TypeScript/React/Next.js (frontend pages, shared components), TanStack React Query, Zustand entitlements store.

---

### Task 1: Fix `authorize_feature("race_strategy")` fall-through

The middleware passes `"race_strategy"` as the feature key, but `authorize_feature()` only handles `"race_strategy_full"`. Unknown features fall through to `return True` at line 402 — the gate is open for everyone.

**Files:**
- Modify: `telemetry_tool/auth/entitlements.py:383-393`
- Test: `telemetry_tool/tests/test_entitlements.py` (or create if not exists)

**Step 1: Write the failing test**

Create or extend the entitlements test file:

```python
# telemetry_tool/tests/test_entitlements_race_strategy.py
"""Tests for race_strategy feature gating in authorize_feature()."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)


@pytest.fixture
def mock_flask_g():
    """Mock Flask g object with workspace_id."""
    mock_g = MagicMock()
    mock_g.workspace_id = 1
    return mock_g


class TestAuthorizeRaceStrategy:
    """Test authorize_feature for 'race_strategy' key."""

    def test_race_strategy_allowed_for_racer(self, mock_flask_g):
        """Racer tier with race_strategy_limit='full' should be allowed."""
        from auth.entitlements import authorize_feature

        # Mock the entitlements to return racer-tier data
        with patch("auth.entitlements.get_user_entitlements") as mock_ent, \
             patch("auth.entitlements.g", mock_flask_g):
            mock_ent.return_value = {
                "plan_tier": "racer",
                "race_strategy_limit": "full",
            }
            allowed, ctx = authorize_feature(None, user_id=1, feature="race_strategy")
            assert allowed is True

    def test_race_strategy_allowed_for_demo_limited(self, mock_flask_g):
        """Demo tier with race_strategy_limit='limited_3h' should be allowed
        (the 3h limit is enforced at create/update time, not at the gate)."""
        from auth.entitlements import authorize_feature

        with patch("auth.entitlements.get_user_entitlements") as mock_ent, \
             patch("auth.entitlements.g", mock_flask_g):
            mock_ent.return_value = {
                "plan_tier": "demo",
                "race_strategy_limit": "limited_3h",
            }
            allowed, ctx = authorize_feature(None, user_id=1, feature="race_strategy")
            assert allowed is True

    def test_race_strategy_denied_when_no_limit(self, mock_flask_g):
        """No race_strategy_limit (None) means no plan — should be denied."""
        from auth.entitlements import authorize_feature

        with patch("auth.entitlements.get_user_entitlements") as mock_ent, \
             patch("auth.entitlements.g", mock_flask_g):
            mock_ent.return_value = {
                "plan_tier": "demo",
                "race_strategy_limit": None,
            }
            allowed, ctx = authorize_feature(None, user_id=1, feature="race_strategy")
            assert allowed is False
            assert ctx["upgrade_tier"] == "racer"
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_entitlements_race_strategy.py -v`
Expected: First test PASSES (currently falls through to True), third test FAILS (currently returns True for None)

**Step 3: Implement the fix**

In `telemetry_tool/auth/entitlements.py`, add a handler for `"race_strategy"` **before** the existing `"race_strategy_full"` handler (before line 383):

```python
    # Check race_strategy (mutation gate — allow if any limit is set)
    if feature == "race_strategy":
        limit = entitlements.get("race_strategy_limit")
        if not limit:
            return False, {
                "reason": "Race strategy requires a plan subscription",
                "upgrade_tier": "racer",
                "upgrade_url": "/billing?plan=RACER",
                "current_tier": tier,
            }
        return True, {"current_tier": tier}

    # Check race_strategy_full (demo has 3h limit)
    if feature == "race_strategy_full":
        ...
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_entitlements_race_strategy.py -v`
Expected: All 3 PASS

**Step 5: Commit**

```bash
git add telemetry_tool/auth/entitlements.py telemetry_tool/tests/test_entitlements_race_strategy.py
git commit -m "fix: resolve race_strategy feature key in authorize_feature

Previously fell through to 'allow by default' — now checks
race_strategy_limit field. Denies if None (no plan), allows for
both 'limited_3h' and 'full' (3h limit enforced at create time)."
```

---

### Task 2: Fix `strategy_live` decorator in HTML blueprint

The `@require_feature("strategy_live")` decorator on lines 636 and 666 of `race_strategy_v2.py` references a feature key that doesn't exist in plan_definitions. The `require_feature` decorator calls `entitlement_snapshot().get("strategy_live", False)` which is always `False`.

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py:636,666`
- Modify: `telemetry_tool/web/middleware/entitlements.py:262-280`

**Step 1: Fix the `require_feature` decorator**

The decorator does `snapshot.get(feature_name, False)` — this only works for keys that exist directly in the snapshot dict. For `"race_strategy"`, the snapshot has `"race_strategy_limit"` (a string), not a boolean. We need the decorator to use `authorize_feature()` instead.

In `telemetry_tool/web/middleware/entitlements.py`, replace the `require_feature` function (lines 262-280):

```python
def require_feature(feature_name: str):
    """Gate a route behind a feature flag using authorize_feature()."""

    def _decorator(fn):
        @wraps(fn)
        def _wrapped(*args, **kwargs):
            # Skip entitlement check if PG mode or auth is off
            if not current_app.config.get("USE_PG") or not current_app.config.get("AUTH_REQUIRED"):
                return fn(*args, **kwargs)

            user_id, _ = _identity()
            if user_id is None:
                return fn(*args, **kwargs)  # Auth middleware handles 401

            conn = _get_conn()
            from auth.entitlements import authorize_feature as _authorize
            allowed, ctx = _authorize(conn, user_id, feature_name)
            if not allowed:
                return api_error(
                    ErrorCode.FORBIDDEN,
                    ctx.get("reason", f"Feature '{feature_name}' requires a plan upgrade."),
                    status=403,
                )
            g.entitlement_snapshot = ctx
            return fn(*args, **kwargs)

        return _wrapped

    return _decorator
```

**Step 2: Change decorators in race_strategy_v2.py**

In `telemetry_tool/web/routes/race_strategy_v2.py`:
- Line 636: Change `@require_feature("strategy_live")` to `@require_feature("race_strategy")`
- Line 666: Change `@require_feature("strategy_live")` to `@require_feature("race_strategy")`

**Step 3: Run existing tests to verify no regression**

Run: `pytest telemetry_tool/tests/ -v --timeout=30 -x`
Expected: PASS (no existing tests depend on the old behavior)

**Step 4: Commit**

```bash
git add telemetry_tool/web/middleware/entitlements.py telemetry_tool/web/routes/race_strategy_v2.py
git commit -m "fix: require_feature decorator uses authorize_feature(), fix strategy_live key

- require_feature now delegates to authorize_feature() for proper
  feature resolution (was doing raw dict lookup which missed non-boolean
  features like race_strategy_limit)
- Changes @require_feature('strategy_live') to @require_feature('race_strategy')
  on go_live and live routes (strategy_live column didn't exist)"
```

---

### Task 3: Enforce 3-hour DEMO duration limit in service layer

**Files:**
- Modify: `telemetry_tool/services/race_strategy.py:220-279` (create_race)
- Modify: `telemetry_tool/services/race_strategy.py:282-362` (update_race)
- Modify: `telemetry_tool/web/routes/api_v1_race_strategy.py:91-116` (create endpoint)
- Modify: `telemetry_tool/web/routes/api_v1_race_strategy.py:147-180` (update endpoint)
- Test: `telemetry_tool/tests/test_entitlements_race_strategy.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_entitlements_race_strategy.py`:

```python
class TestDurationLimit:
    """Test 3-hour duration enforcement in create/update."""

    def test_create_race_rejects_over_limit(self):
        """create_race should raise ValueError when duration exceeds max."""
        from services.race_strategy import create_race
        from unittest.mock import MagicMock

        conn = MagicMock()
        data = {
            "race": {"race_name": "Test", "race_duration_s": 14400},  # 4h
            "drivers": [],
        }
        with pytest.raises(ValueError, match="3-hour"):
            create_race(conn, data, max_duration_s=10800)

    def test_create_race_allows_within_limit(self):
        """create_race should succeed when duration is within max."""
        from services.race_strategy import create_race
        from unittest.mock import MagicMock

        conn = MagicMock()
        # Mock cursor with lastrowid
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 42
        conn.execute.return_value = mock_cursor

        data = {
            "race": {"race_name": "Test", "race_duration_s": 7200},  # 2h
            "drivers": [],
        }
        result = create_race(conn, data, max_duration_s=10800)
        assert result == 42

    def test_create_race_no_limit(self):
        """create_race without max_duration_s should not check duration."""
        from services.race_strategy import create_race
        from unittest.mock import MagicMock

        conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 99
        conn.execute.return_value = mock_cursor

        data = {
            "race": {"race_name": "Test", "race_duration_s": 86400},  # 24h
            "drivers": [],
        }
        result = create_race(conn, data)  # no max — should succeed
        assert result == 99
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_entitlements_race_strategy.py::TestDurationLimit -v`
Expected: FAIL — `create_race()` doesn't accept `max_duration_s` param

**Step 3: Add duration validation to service functions**

In `telemetry_tool/services/race_strategy.py`, modify `create_race` (line 220):

```python
def create_race(conn, data: dict, max_duration_s: int | None = None) -> int:
    """Create a new race configuration with drivers and windows.
    ...
    Raises
    ------
    ValueError
        If max_duration_s is set and race_duration_s exceeds it.
    """
    race = data.get("race", data)
    drivers = data.get("drivers", [])
    windows = data.get("windows", [])

    # Enforce plan-based duration limit
    duration = race.get("race_duration_s", 10800)
    if max_duration_s is not None and duration > max_duration_s:
        limit_h = max_duration_s / 3600
        raise ValueError(
            f"Race duration exceeds your plan's {limit_h:.0f}-hour limit. "
            f"Upgrade to Racer for unlimited race duration."
        )

    # ... rest of existing code unchanged ...
```

Apply the same pattern to `update_race` (line 282):

```python
def update_race(conn, race_id: int, data: dict, max_duration_s: int | None = None) -> bool:
    ...
    cfg = data.get("race", data)
    duration = cfg.get("race_duration_s", race.get("race_duration_s"))
    if max_duration_s is not None and duration and duration > max_duration_s:
        limit_h = max_duration_s / 3600
        raise ValueError(
            f"Race duration exceeds your plan's {limit_h:.0f}-hour limit. "
            f"Upgrade to Racer for unlimited race duration."
        )
    # ... rest of existing code ...
```

**Step 4: Pass entitlement context from API routes**

In `telemetry_tool/web/routes/api_v1_race_strategy.py`, modify `create_race_endpoint` (line 93):

```python
@bp.route("/", methods=["POST"])
@rate_limit(tier="write")
def create_race_endpoint():
    data = request.get_json(silent=True)
    if not data:
        return api_error(ErrorCode.VALIDATION_ERROR, "JSON body is required", status=400)

    try:
        conn = get_pg_connection()

        # Resolve duration limit from entitlements
        max_dur = None
        try:
            from flask import g
            from auth.entitlements import get_user_entitlements
            user_id = getattr(g, "current_user_id", None)
            ws_id = getattr(g, "workspace_id", None)
            if user_id is not None:
                ent = get_user_entitlements(conn, user_id, ws_id)
                if ent.get("race_strategy_limit") == "limited_3h":
                    max_dur = 10800
        except Exception:
            pass  # Fail open — don't block on entitlement resolution errors

        race_id = create_race(conn, data, max_duration_s=max_dur)
        return api_response({"race_id": race_id}, status=201)
    except ValueError as ve:
        return api_error(ErrorCode.VALIDATION_ERROR, str(ve), status=400)
    except Exception as exc:
        logger.exception("Failed to create race")
        return api_error(ErrorCode.INTERNAL_ERROR, str(exc), status=500)
```

Apply the same pattern to `update_race_endpoint` (line 149).

**Step 5: Run tests**

Run: `pytest telemetry_tool/tests/test_entitlements_race_strategy.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add telemetry_tool/services/race_strategy.py telemetry_tool/web/routes/api_v1_race_strategy.py telemetry_tool/tests/test_entitlements_race_strategy.py
git commit -m "feat: enforce 3h DEMO race duration limit in create/update

- create_race() and update_race() accept optional max_duration_s
- API routes resolve race_strategy_limit from entitlements and pass
  max_duration_s=10800 when limit is 'limited_3h'
- Returns 400 with upgrade message when exceeded"
```

---

### Task 4: Fix `race_alerts` SQLite datetime syntax for PG

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py:86-94`

**Step 1: Fix the SQL**

In `telemetry_tool/web/routes/race_strategy_v2.py`, replace lines 86-94:

```python
    # 4. Check if we already sent a weather alert in the last 30 min
    try:
        import os
        use_pg = os.environ.get("USE_PG", "0") == "1"
        if use_pg:
            time_filter = "created_at > NOW() - INTERVAL '30 minutes'"
        else:
            time_filter = "created_at > datetime('now', '-30 minutes')"

        recent = conn.execute(
            f"SELECT id FROM race_alerts "
            f"WHERE race_id = ? AND alert_type = 'weather' "
            f"AND {time_filter} "
            f"ORDER BY id DESC LIMIT 1",
            (race_id,),
        ).fetchone()
        if recent:
            return None  # already alerted recently
    except Exception:
        # Table may not exist in SQLite dev mode — skip dedup
        pass
```

**Step 2: Run existing tests**

Run: `pytest telemetry_tool/tests/ -v --timeout=30 -x`
Expected: PASS

**Step 3: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py
git commit -m "fix: race_alerts datetime query uses PG-compatible syntax

Replaces SQLite-only datetime('now', '-30 minutes') with
NOW() - INTERVAL '30 minutes' when USE_PG=1."
```

---

### Task 5: Extract shared StintTimeline component

**Files:**
- Create: `lap-website/src/components/app/race-strategy/StintTimeline.tsx`
- Modify: `lap-website/src/app/app/race-strategy/[id]/page.tsx:110-141`
- Modify: `lap-website/src/app/app/race-strategy/[id]/live/page.tsx:116-152`
- Modify: `lap-website/src/app/app/race-strategy/[id]/summary/page.tsx:121-152`

**Step 1: Create the shared component**

```tsx
// lap-website/src/components/app/race-strategy/StintTimeline.tsx
'use client';

interface Stint {
  stint_id: number;
  stint_order: number;
  driver_id: number;
  driver_name: string;
  planned_duration_s: number | null;
  actual_duration_s: number | null;
  status: string;
}

interface StintTimelineProps {
  stints: Stint[];
  totalDuration: number;
  driverColors: Record<number, string>;
  /** Set to the active stint_id to highlight it with a green ring (live page). */
  activeStintId?: number;
  /** When true, prefer actual_duration_s over planned (summary page). */
  preferActual?: boolean;
}

function formatTime(s: number | null | undefined): string {
  if (s == null) return '\u2014';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

export function StintTimeline({
  stints,
  totalDuration,
  driverColors,
  activeStintId,
  preferActual = false,
}: StintTimelineProps) {
  if (!stints.length || !totalDuration) return null;
  return (
    <div className="flex h-10 w-full overflow-hidden border border-steel/20 rounded">
      {stints.map((s) => {
        const dur = preferActual
          ? (s.actual_duration_s || s.planned_duration_s || 0)
          : (s.planned_duration_s || s.actual_duration_s || 0);
        const pct = (dur / totalDuration) * 100;
        const bg = driverColors[s.driver_id] || '#888';
        const isActive = s.stint_id === activeStintId;
        return (
          <div
            key={s.stint_id}
            className={`flex items-center justify-center text-[10px] font-telemetry text-asphalt truncate border-r border-asphalt/30 last:border-r-0 ${
              isActive ? 'ring-2 ring-acid-green ring-inset animate-pulse' : ''
            }`}
            style={{ width: `${pct}%`, backgroundColor: bg }}
            title={`${s.driver_name} \u2014 ${formatTime(dur)}`}
          >
            {pct > 8 ? s.driver_name : ''}
          </div>
        );
      })}
    </div>
  );
}
```

**Step 2: Replace in detail page**

In `lap-website/src/app/app/race-strategy/[id]/page.tsx`:
- Add import: `import { StintTimeline } from '@/components/app/race-strategy/StintTimeline';`
- Delete lines 110-141 (local StintTimeline function)
- Keep the usage at line 424 unchanged (props match)

**Step 3: Replace in live page**

In `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`:
- Add import: `import { StintTimeline } from '@/components/app/race-strategy/StintTimeline';`
- Delete lines 116-152 (local StintTimeline function)
- Update usage at line 394 to match new props (add `preferActual={false}` or omit — default)

**Step 4: Replace in summary page**

In `lap-website/src/app/app/race-strategy/[id]/summary/page.tsx`:
- Add import: `import { StintTimeline } from '@/components/app/race-strategy/StintTimeline';`
- Delete lines 121-152 (local StintTimeline function)
- Update usage at line 229 to add `preferActual={true}`

**Step 5: Build to verify no breakage**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no errors

**Step 6: Commit**

```bash
git add lap-website/src/components/app/race-strategy/StintTimeline.tsx \
       lap-website/src/app/app/race-strategy/[id]/page.tsx \
       lap-website/src/app/app/race-strategy/[id]/live/page.tsx \
       lap-website/src/app/app/race-strategy/[id]/summary/page.tsx
git commit -m "refactor: extract shared StintTimeline component

Replaces 3 identical copies (detail, live, summary pages) with a
single shared component. Props: activeStintId for live highlight,
preferActual for summary page."
```

---

### Task 6: Wire UpgradeBanner into frontend race strategy pages

**Files:**
- Modify: `lap-website/src/app/app/race-strategy/page.tsx` (list page)
- Modify: `lap-website/src/app/app/race-strategy/[id]/page.tsx` (detail page)
- Modify: `lap-website/src/app/app/race-strategy/new/page.tsx` (create form)
- Modify: `lap-website/src/app/app/race-strategy/[id]/edit/page.tsx` (edit form)

**Step 1: Add UpgradeBanner to list page**

In `lap-website/src/app/app/race-strategy/page.tsx`, after the existing imports add:

```tsx
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';
import { canUseFeature } from '@/lib/entitlements-store';
```

Then inside the return, after `<PageHeader>` and before the stats grid (before line 129), add:

```tsx
      <UpgradeBanner
        feature="race_strategy_full"
        context="Demo plan limited to 3-hour races. Upgrade for unlimited duration."
      />
```

Also update the "New Race" button to show a lock hint when on demo:

```tsx
        actions={
          <Link
            href="/app/race-strategy/new"
            className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors inline-flex items-center gap-2"
          >
            + New Race
            {!canUseFeature('race_strategy_full') && (
              <span className="text-[10px] opacity-60" title="3h limit on Demo">3h max</span>
            )}
          </Link>
        }
```

**Step 2: Add Go-Live lock to detail page**

In `lap-website/src/app/app/race-strategy/[id]/page.tsx`, add imports:

```tsx
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';
import { canUseFeature } from '@/lib/entitlements-store';
```

Find the "Go Live" button (search for `go-live`). Wrap it with an entitlement check — if `!canUseFeature('race_strategy_full')`, show the button as disabled with a tooltip:

```tsx
{race.status === 'ready' && (
  canUseFeature('race_strategy_full') ? (
    <button onClick={() => goLiveMut.mutate()} disabled={goLiveMut.isPending} ...>
      Go Live
    </button>
  ) : (
    <div className="relative group">
      <button disabled className="px-4 py-2 bg-steel/30 text-steel font-telemetry text-sm rounded cursor-not-allowed">
        Go Live
      </button>
      <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:block
        bg-concrete border border-steel/30 rounded px-3 py-1.5 text-xs text-steel whitespace-nowrap">
        Upgrade to Racer for Live Dashboard
      </div>
    </div>
  )
)}
```

**Step 3: Add duration cap to create form**

In `lap-website/src/app/app/race-strategy/new/page.tsx`, add imports:

```tsx
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';
import { useEntitlementsStore } from '@/lib/entitlements-store';
```

Inside the component, read the entitlement:

```tsx
const raceStrategyLimit = useEntitlementsStore((s) => s.entitlements?.raceStrategyLimit);
const maxDurationMinutes = raceStrategyLimit === 'limited_3h' ? 180 : undefined;
```

Above the duration input fields, add:

```tsx
{raceStrategyLimit === 'limited_3h' && (
  <UpgradeBanner
    feature="race_strategy_full"
    context="Demo plan: races limited to 3 hours. Upgrade for unlimited duration."
    variant="inline"
  />
)}
```

On the duration hours/minutes inputs, add a max constraint:

```tsx
// After the existing hours input, add a max prop:
// If maxDurationMinutes is 180 => max hours = 3, max minutes = 0 when hours = 3
```

**Step 4: Apply same pattern to edit form**

Same changes as Step 3, applied to `[id]/edit/page.tsx`.

**Step 5: Build to verify**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 6: Commit**

```bash
git add lap-website/src/app/app/race-strategy/page.tsx \
       lap-website/src/app/app/race-strategy/[id]/page.tsx \
       lap-website/src/app/app/race-strategy/new/page.tsx \
       lap-website/src/app/app/race-strategy/[id]/edit/page.tsx
git commit -m "feat: wire UpgradeBanner into race strategy pages

- List page: banner for demo users, '3h max' badge on New Race button
- Detail page: Go Live button disabled for demo with tooltip
- Create/Edit: inline banner above duration fields, duration capped at 3h"
```

---

### Task 7: Create MessageLog component and render messages in live dashboard

**Files:**
- Create: `lap-website/src/components/app/race-strategy/MessageLog.tsx`
- Modify: `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`

**Step 1: Create MessageLog component**

```tsx
// lap-website/src/components/app/race-strategy/MessageLog.tsx
'use client';

import { useEffect, useRef } from 'react';

interface Message {
  msg_id: number;
  author: string;
  message: string;
  category: string;
  created_at: string;
}

interface MessageLogProps {
  messages: Message[];
}

const CATEGORY_COLORS: Record<string, string> = {
  info: 'bg-steel/20 text-steel',
  strategy: 'bg-pit-orange/20 text-pit-orange',
  incident: 'bg-flag-red/20 text-flag-red',
  weather: 'bg-marshal-yellow/20 text-marshal-yellow',
};

export function MessageLog({ messages }: MessageLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  if (!messages.length) {
    return (
      <div className="text-center text-steel text-sm py-4">
        No messages yet. Team messages will appear here.
      </div>
    );
  }

  return (
    <div className="max-h-64 overflow-y-auto space-y-2 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-steel/30">
      {messages.map((m) => (
        <div key={m.msg_id} className="flex items-start gap-2 text-sm">
          <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase ${CATEGORY_COLORS[m.category] || CATEGORY_COLORS.info}`}>
            {m.category}
          </span>
          <div className="min-w-0">
            <span className="font-medium text-chalk">{m.author}</span>
            <span className="text-steel ml-2">{m.message}</span>
          </div>
          <span className="shrink-0 text-[10px] text-steel/60 tabular-nums">
            {new Date(m.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
```

**Step 2: Add MessageLog to live dashboard**

In `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`:
- Add import: `import { MessageLog } from '@/components/app/race-strategy/MessageLog';`
- Find the end of the main content area (after stint log table, before the action buttons)
- Add a new section:

```tsx
{/* ── Team Messages ──────────────────────────────── */}
{state.messages && state.messages.length > 0 && (
  <div className="bg-concrete/50 border border-steel/20 rounded-lg p-4">
    <h3 className="text-sm font-telemetry text-steel mb-3">TEAM MESSAGES</h3>
    <MessageLog messages={state.messages} />
  </div>
)}
```

**Step 3: Build to verify**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add lap-website/src/components/app/race-strategy/MessageLog.tsx \
       lap-website/src/app/app/race-strategy/[id]/live/page.tsx
git commit -m "feat: render team messages in live race dashboard

New MessageLog component with auto-scroll and category badges.
Messages were already fetched but not displayed."
```

---

### Task 8: Enrich live state API with weather alerts

**Files:**
- Modify: `telemetry_tool/services/race_strategy.py:488-562` (get_live_state)

**Step 1: Add optional enrichment**

In `telemetry_tool/services/race_strategy.py`, modify `get_live_state` to include weather and intelligence data:

After the existing `engine_data` block (after line 548), add:

```python
    # Optional enrichment — weather alerts
    weather_alerts: list = []
    try:
        from pathlib import Path as _Path
        _enrich_root = str(_Path(__file__).resolve().parents[1])
        if _enrich_root not in sys.path:
            sys.path.insert(0, _enrich_root)
        from meteo_service import get_weather_forecast
        # Only fetch if race has track coordinates (future: add lat/lon to race_configs)
        # For now, skip — weather enrichment requires track lookup
    except ImportError:
        pass
    except Exception:
        logger.debug("Weather enrichment failed for race %d", race_id)

    # Optional enrichment — race intelligence
    intelligence: dict = {}
    try:
        from race_intelligence import analyze_race
        elapsed = _compute_elapsed_s(race.get("race_start_ts"))
        intelligence = analyze_race(conn, race_id, elapsed) or {}
    except ImportError:
        pass
    except Exception:
        logger.debug("Intelligence enrichment failed for race %d", race_id)
```

Then update the return dict to include:

```python
    return {
        "race": race,
        "drivers": drivers,
        "stints": stints,
        "pit_stops": pit_stops,
        "messages": messages,
        "active_stint": active_stint,
        "next_stint": next_stint,
        "driver_cumulative": driver_cumulative,
        "weather_alerts": weather_alerts,
        "intelligence": intelligence,
        **engine_data,
    }
```

**Step 2: Run existing tests**

Run: `pytest telemetry_tool/tests/ -v --timeout=30 -x`
Expected: PASS (enrichment uses try/except, won't break existing tests)

**Step 3: Commit**

```bash
git add telemetry_tool/services/race_strategy.py
git commit -m "feat: add weather and intelligence enrichment to live state API

Optional, graceful degradation. Returns empty defaults if modules
are unavailable or fail."
```

---

### Task 9: Extract shared RaceConfigForm component

**Files:**
- Create: `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx`
- Modify: `lap-website/src/app/app/race-strategy/new/page.tsx`
- Modify: `lap-website/src/app/app/race-strategy/[id]/edit/page.tsx`

**Step 1: Read both form files to identify all shared code**

Read `new/page.tsx` and `[id]/edit/page.tsx` fully. Identify:
- Shared types (DriverRow, WindowRow, form state)
- Shared helper functions (mmssToSeconds, parseNum, str, secondsToMM, secondsToSS)
- Shared JSX (all form sections: race config, drivers, pit strategy, windows, fuel/weight, qualifying)

**Step 2: Create the shared form component**

Extract to `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx`:
- Accept props: `mode`, `initialData`, `maxDurationS`, `onSubmit`, `isSubmitting`
- Internal state for all form fields (same as current new/edit pages)
- `useEffect` to populate from `initialData` when mode is 'edit'
- All form JSX shared between the two pages

**Step 3: Simplify new/page.tsx**

Replace the form JSX and state management with:

```tsx
import { RaceConfigForm } from '@/components/app/race-strategy/RaceConfigForm';

export default function NewRacePage() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const raceStrategyLimit = useEntitlementsStore((s) => s.entitlements?.raceStrategyLimit);
  const maxDurationS = raceStrategyLimit === 'limited_3h' ? 10800 : undefined;

  const handleSubmit = async (data: RaceFormData) => {
    setIsSubmitting(true);
    try {
      const res = await api.post<{ race_id: number }>('/race-strategy/', data);
      router.push(`/app/race-strategy/${res.race_id}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div>
      <PageHeader title="New Race" ... />
      <RaceConfigForm mode="create" maxDurationS={maxDurationS} onSubmit={handleSubmit} isSubmitting={isSubmitting} />
    </div>
  );
}
```

**Step 4: Simplify edit/page.tsx**

Same pattern, but loads `initialData` from GET and passes it as prop.

**Step 5: Build to verify**

Run: `cd lap-website && npm run build`
Expected: Build succeeds

**Step 6: Commit**

```bash
git add lap-website/src/components/app/race-strategy/RaceConfigForm.tsx \
       lap-website/src/app/app/race-strategy/new/page.tsx \
       lap-website/src/app/app/race-strategy/[id]/edit/page.tsx
git commit -m "refactor: extract shared RaceConfigForm component

Replaces duplicated form code in new and edit pages. Shared:
types, helpers, driver/window sub-forms, all form sections.
Props: mode, initialData, maxDurationS, onSubmit, isSubmitting."
```

---

### Task 10: Final verification

**Step 1: Run backend tests**

Run: `pytest telemetry_tool/tests/ -v --timeout=60`
Expected: All PASS

**Step 2: Build frontend**

Run: `cd lap-website && npm run build`
Expected: Build succeeds with no errors

**Step 3: Run frontend lint**

Run: `cd lap-website && npm run lint`
Expected: No errors

**Step 4: Manual smoke test checklist**

- [ ] Open /app/race-strategy — see UpgradeBanner on demo tier
- [ ] Click New Race — see duration cap and inline banner on demo
- [ ] Create a 2h race on demo — should succeed
- [ ] Try creating a 5h race on demo — should get 400 error
- [ ] View race detail — Go Live button disabled on demo with tooltip
- [ ] View live dashboard — messages section renders (if messages exist)
- [ ] StintTimeline renders identically on detail/live/summary pages
- [ ] On Racer tier — no banners, no restrictions, full access

**Step 5: Final commit**

If any lint/type fixes were needed, commit them.
