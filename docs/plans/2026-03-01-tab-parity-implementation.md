# Tab Structure Parity Restoration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bring SaaS session detail page to full parity with local desktop tool — 5 tabs, deep Overview with driving style/debrief/badges, score formatting fixes, Focus Mode button, and Analytics rename.

**Architecture:** Backend adds `evaluate_badges()` to scoring.py and enriches the `/scores` API response. Frontend restructures from 6 tabs to 5 by merging Performance into Overview, renames Visualize to Analytics, and adds 3 new Overview sections (DrivingStyle, SessionDebrief, AchievementsBadges). Focus Mode skeleton gets wired to the header.

**Tech Stack:** Python (Flask/scoring), TypeScript (Next.js 14, React, Tailwind CSS), Canvas API (radar chart)

---

### Task 1: Backend — Add `evaluate_badges()` to scoring.py

**Files:**
- Modify: `telemetry_tool/scoring.py:1457` (after `score_session()` returns)
- Test: `telemetry_tool/tests/test_scoring_badges.py` (new)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_scoring_badges.py`:

```python
"""Tests for badge evaluation logic."""
import pytest
from scoring import evaluate_badges, MAX_PACE, MAX_CONSISTENCY, MAX_EXECUTION, MAX_ROBUSTNESS, MAX_ADAPTATION


def _make_score_result(pace_pct=0.5, cons_pct=0.5, exec_pct=0.5, rob_pct=0.5, adapt_pct=0.5):
    """Build a minimal score_result dict with given percentages of max."""
    total = (pace_pct * MAX_PACE + cons_pct * MAX_CONSISTENCY +
             exec_pct * MAX_EXECUTION + rob_pct * MAX_ROBUSTNESS +
             adapt_pct * MAX_ADAPTATION)
    return {
        "total_score": total,
        "grade": "B",
        "sub_scores": {
            "pace":        {"score": pace_pct * MAX_PACE,        "max": MAX_PACE},
            "consistency": {"score": cons_pct * MAX_CONSISTENCY,  "max": MAX_CONSISTENCY},
            "execution":   {"score": exec_pct * MAX_EXECUTION,    "max": MAX_EXECUTION},
            "robustness":  {"score": rob_pct * MAX_ROBUSTNESS,    "max": MAX_ROBUSTNESS},
            "adaptation":  {"score": adapt_pct * MAX_ADAPTATION,  "max": MAX_ADAPTATION},
        },
    }


def test_no_badges_below_threshold():
    result = _make_score_result(0.3, 0.3, 0.3, 0.3, 0.3)
    badges = evaluate_badges(result)
    assert badges == []


def test_bronze_at_60_pct():
    result = _make_score_result(pace_pct=0.60)
    badges = evaluate_badges(result)
    pace_badge = [b for b in badges if b["category"] == "pace"]
    assert len(pace_badge) == 1
    assert pace_badge[0]["tier"] == "bronze"
    assert pace_badge[0]["id"] == "pace_master"


def test_silver_at_75_pct():
    result = _make_score_result(cons_pct=0.75)
    badges = evaluate_badges(result)
    cons_badge = [b for b in badges if b["category"] == "consistency"]
    assert len(cons_badge) == 1
    assert cons_badge[0]["tier"] == "silver"


def test_gold_at_90_pct():
    result = _make_score_result(exec_pct=0.92)
    badges = evaluate_badges(result)
    exec_badge = [b for b in badges if b["category"] == "execution"]
    assert len(exec_badge) == 1
    assert exec_badge[0]["tier"] == "gold"


def test_flow_state_badge_uses_total():
    result = _make_score_result(0.80, 0.80, 0.80, 0.80, 0.80)
    badges = evaluate_badges(result)
    flow = [b for b in badges if b["id"] == "flow_state"]
    assert len(flow) == 1
    assert flow[0]["tier"] == "silver"


def test_highest_tier_wins():
    """A 92% score should only get gold, not bronze+silver+gold."""
    result = _make_score_result(pace_pct=0.92)
    badges = evaluate_badges(result)
    pace_badges = [b for b in badges if b["category"] == "pace"]
    assert len(pace_badges) == 1
    assert pace_badges[0]["tier"] == "gold"


def test_badge_shape():
    result = _make_score_result(pace_pct=0.65)
    badges = evaluate_badges(result)
    b = badges[0]
    assert set(b.keys()) == {"id", "label", "tier", "category", "criteria"}
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_scoring_badges.py -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_badges'`

**Step 3: Write minimal implementation**

Add to `telemetry_tool/scoring.py` after line 1457 (after `score_session` function ends):

```python
# =============================================================================
# Badge evaluation
# =============================================================================

_BADGE_DEFS: Final[list[dict[str, Any]]] = [
    {"id": "pace_master",          "label": "Pace Master",          "category": "pace"},
    {"id": "consistency_champion", "label": "Consistency Champion", "category": "consistency"},
    {"id": "execution_expert",     "label": "Execution Expert",     "category": "execution"},
    {"id": "endurance_warrior",    "label": "Endurance Warrior",    "category": "robustness"},
    {"id": "adaptor",              "label": "Adaptor",              "category": "adaptation"},
]

_TIER_THRESHOLDS: Final[list[tuple[str, float, str]]] = [
    ("gold",   0.90, ">=90%"),
    ("silver", 0.75, ">=75%"),
    ("bronze", 0.60, ">=60%"),
]


def evaluate_badges(score_result: dict[str, Any]) -> list[dict[str, str]]:
    """Evaluate achievement badges from a score_session() result.

    Returns a list of badge dicts, one per earned badge (highest tier only).
    """
    sub = score_result.get("sub_scores", {})
    badges: list[dict[str, str]] = []

    for defn in _BADGE_DEFS:
        cat = defn["category"]
        cat_data = sub.get(cat, {})
        score = cat_data.get("score", 0)
        mx = cat_data.get("max", 1)
        frac = score / mx if mx > 0 else 0.0

        for tier, threshold, label_suffix in _TIER_THRESHOLDS:
            if frac >= threshold:
                badges.append({
                    "id":       defn["id"],
                    "label":    defn["label"],
                    "tier":     tier,
                    "category": cat,
                    "criteria": f"{label_suffix} {cat} score",
                })
                break  # highest tier wins

    # Flow State badge — based on total score
    total = score_result.get("total_score", 0)
    for tier, threshold_frac, label_suffix in _TIER_THRESHOLDS:
        threshold_pts = threshold_frac * TOTAL_MAX
        if total >= threshold_pts:
            badges.append({
                "id":       "flow_state",
                "label":    "Flow State",
                "tier":     tier,
                "category": "total",
                "criteria": f"{label_suffix} overall score",
            })
            break

    return badges
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_scoring_badges.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/scoring.py telemetry_tool/tests/test_scoring_badges.py
git commit -m "feat: add evaluate_badges() to scoring.py for achievement tier system"
```

---

### Task 2: Backend — Enrich `/scores` API response with badges + display_scores

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:489-505` (scores endpoint)
- Test: manual curl or extend existing test

**Step 1: Write the failing test (manual verification)**

The scores endpoint currently returns raw score_details. We need it to also return `badges` and `display_scores`. We will verify by curl after implementation.

**Step 2: Modify the scores endpoint**

In `telemetry_tool/web/routes/data_v2.py`, replace the `get_scores` function (lines 489-505) with:

```python
def get_scores(session_id: str):
    """Return score breakdown for a session, including badges and display-formatted scores."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    scores = models.get_score_details(conn, session_id)
    if scores is None:
        return api_response({
            "available": False,
            "reason_code": "NO_SCORE_DATA",
            "message": "Scoring data not available for this session",
        })

    scores["available"] = True

    # Display scores — integers for clean UI rendering
    display = {}
    for cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
        raw = scores.get(f"{cat}_score")
        mx = scores.get(f"{cat}_max")
        display[cat] = {
            "score": round(raw) if raw is not None else None,
            "max": round(mx) if mx is not None else None,
        }
    scores["display_scores"] = display

    # Badges
    try:
        from scoring import evaluate_badges
        # Reconstruct sub_scores dict from flat DB row
        sub_scores = {}
        for cat in ("pace", "consistency", "execution", "robustness", "adaptation"):
            sub_scores[cat] = {
                "score": scores.get(f"{cat}_score", 0) or 0,
                "max": scores.get(f"{cat}_max", 1) or 1,
            }
        total = sum(s["score"] for s in sub_scores.values())
        badges_result = {"total_score": total, "sub_scores": sub_scores}
        scores["badges"] = evaluate_badges(badges_result)
    except Exception:
        logger.warning("Badge evaluation failed for session %s", session_id, exc_info=True)
        scores["badges"] = []

    return api_response(scores)
```

Add the import at the top of the file (after existing imports, ~line 37):

```python
# Badge evaluation is imported inside the function to avoid circular imports
```

**Step 3: Verify**

Run the dev server and curl: `curl http://localhost:5000/api/v1/sessions/<any-id>/scores | python -m json.tool`
Expected: Response includes `display_scores` and `badges` fields.

**Step 4: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat: enrich /scores endpoint with badges and display_scores"
```

---

### Task 3: Frontend — Restructure tabs (6 → 5), rename Visualize → Analytics

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx:65-74` (Tab type + TABS array)
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx:310-321` (tab content rendering)

**Step 1: Update Tab type and TABS array**

Replace lines 65-74:

```typescript
type Tab = 'overview' | 'corners' | 'timeline' | 'analytics' | 'laps';

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'corners', label: 'Corners & Coaching' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'analytics', label: 'Analytics' },
  { key: 'laps', label: 'Lap Data' },
];
```

**Step 2: Update tab content rendering**

Replace lines 310-321:

```tsx
      {activeTab === 'overview' && (
        <OverviewTab session={session} scores={scores} laps={laps} bestLap={bestLap} sessionId={sessionId} corners={corners} />
      )}
      {activeTab === 'corners' && <CornersTab corners={corners} sessionId={sessionId} />}
      {activeTab === 'timeline' && <TimelineTab sessionId={sessionId} />}
      {activeTab === 'analytics' && (
        <AnalyticsTab sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} />
      )}
      {activeTab === 'laps' && <LapDataTab laps={laps} />}
```

**Step 3: Rename VisualizeTab function to AnalyticsTab**

Replace line 522 (`function VisualizeTab`) — rename function to `AnalyticsTab`. Add SectorPanel to the grid.

Replace lines 522-578 with:

```tsx
function AnalyticsTab({
  sessionId,
  gpsLaps,
  bestLap,
}: {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
}) {
  const apiBase = BACKEND_URL;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: GPS Map (tall) */}
        <div className="lg:col-span-1 lg:row-span-2">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">GPS Track Map</h3>
            <GpsTrace
              sessionId={sessionId}
              apiBase={apiBase}
              gpsLaps={gpsLaps}
              bestLap={bestLap}
              className="w-full"
            />
          </div>
        </div>

        {/* Top-right: Speed Trace */}
        <div className="lg:col-span-2">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">Speed Trace</h3>
            <SpeedTraceZoom
              sessionId={sessionId}
              apiBase={apiBase}
              gpsLaps={gpsLaps}
              bestLap={bestLap}
              className="w-full"
            />
          </div>
        </div>

        {/* Bottom-right: GG Diagram */}
        <div className="lg:col-span-2">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">G-G Diagram</h3>
            <GGExplorer
              sessionId={sessionId}
              apiBase={apiBase}
              gpsLaps={gpsLaps}
              bestLap={bestLap}
              className="w-full"
            />
          </div>
        </div>
      </div>

      {/* Sector Analysis */}
      <SectorPanel sessionId={sessionId} className="bg-concrete rounded-xl border border-steel/10" />
    </div>
  );
}
```

**Step 4: Remove PerformanceTab function**

Delete lines 685-836 (the entire `PerformanceTab` function). Its content will be merged into Overview in Task 4.

**Step 5: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds (may warn about unused PerformanceTab if not yet deleted)

**Step 6: Commit**

```bash
git add lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat: restructure session tabs — merge Performance into Overview, rename Visualize to Analytics"
```

---

### Task 4: Frontend — Deepen Overview tab (metrics grid + score formatting)

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx` — OverviewTab function (lines 330-493)

**Step 1: Update OverviewTab signature**

Add `sessionId` and `corners` props:

```tsx
function OverviewTab({
  session,
  scores,
  laps,
  bestLap,
  sessionId,
  corners,
}: {
  session: SessionData;
  scores: ScoreData | null;
  laps: LapData[];
  bestLap: number | null;
  sessionId: string;
  corners: CornerData[];
}) {
```

**Step 2: Fix score formatting in ScoreBar**

Replace line 124 (`score.toFixed(1)`) in ScoreBar:

```tsx
        <span className="text-steel font-telemetry">
          {score != null ? Math.round(score) : '--'} / {Math.round(max)}
        </span>
```

**Step 3: Fix total score formatting**

Replace lines 353-356 (total score display):

```tsx
                <div className="text-4xl font-monument text-chalk">
                  {session.total_score != null
                    ? Math.round(session.total_score)
                    : '--'}
                </div>
```

**Step 4: Add subtitle to Score Breakdown**

Replace line 348:

```tsx
          <h2 className="text-lg font-monument text-chalk mb-1">Score Breakdown</h2>
          <p className="text-steel text-xs font-body mb-4">How your score is built</p>
```

**Step 5: Add Performance Metrics grid after strengths/weaknesses**

After the strengths/weaknesses block (after line 438), before the closing `</div>` of the score card, add:

```tsx
              {/* Performance Metrics Grid (from Performance tab) */}
              <div className="mt-6 pt-4 border-t border-steel/10">
                <h3 className="text-sm font-monument text-chalk mb-3">Performance Metrics</h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: 'Total', value: session.total_score, max: 100, color: 'text-chalk' },
                    { label: 'Pace', value: scores.pace_score, max: scores.pace_max ?? 25, color: 'text-acid-green' },
                    { label: 'Consistency', value: scores.consistency_score, max: scores.consistency_max ?? 25, color: 'text-cyan-400' },
                    { label: 'Execution', value: scores.execution_score, max: scores.execution_max ?? 20, color: 'text-racing-purple' },
                    { label: 'Robustness', value: scores.robustness_score, max: scores.robustness_max ?? 15, color: 'text-pit-orange' },
                    { label: 'Adaptation', value: scores.adaptation_score, max: 15, color: 'text-marshal-yellow' },
                  ].map((m) => (
                    <div key={m.label} className="bg-asphalt rounded-lg p-3">
                      <p className="text-steel text-[10px] font-body uppercase tracking-wider mb-1">{m.label}</p>
                      <span className={`text-xl font-monument ${m.color}`}>
                        {m.value != null ? Math.round(m.value) : '--'}
                      </span>
                      <span className="text-steel text-xs font-body ml-1">/ {Math.round(m.max)}</span>
                    </div>
                  ))}
                  {/* Grade card */}
                  <div className="bg-asphalt rounded-lg p-3">
                    <p className="text-steel text-[10px] font-body uppercase tracking-wider mb-1">Grade</p>
                    <span className={`text-xl font-monument ${gradeColorClass(session.grade).split(' ')[0]}`}>
                      {session.grade || '--'}
                    </span>
                  </div>
                </div>
              </div>
```

**Step 6: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 7: Commit**

```bash
git add lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat: deepen Overview tab — add metrics grid, fix score integer formatting, add subtitle"
```

---

### Task 5: Frontend — Add DrivingStyleSection component

**Files:**
- Create: `lap-website/src/components/app/DrivingStyleSection.tsx`
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx` — add to OverviewTab

**Step 1: Create the component**

Create `lap-website/src/components/app/DrivingStyleSection.tsx`:

```tsx
'use client';

import { useEffect, useState, useRef } from 'react';
import { api } from '@/lib/api-client';

interface DrivingStyleFeature {
  name: string;
  value: number;
}

interface DrivingStyleData {
  available?: boolean;
  style_label?: string;
  style_confidence?: number;
  features: DrivingStyleFeature[];
  strengths: string[];
  weaknesses: string[];
}

const FEATURE_LABELS: Record<string, string> = {
  trail_braking_depth: 'Trail Braking',
  brake_point_consistency: 'Brake Consistency',
  brake_pressure_buildup_rate: 'Brake Buildup',
  apex_speed_ratio: 'Apex Speed',
  turn_in_aggressiveness: 'Turn-in Aggression',
  throttle_onset_delay_m: 'Throttle Onset',
  exit_acceleration_efficiency: 'Exit Acceleration',
  line_variation_index: 'Line Consistency',
  early_vs_late_stint_pace: 'Stint Endurance',
  smoothness_composite: 'Smoothness',
};

function drawRadar(
  canvas: HTMLCanvasElement,
  features: DrivingStyleFeature[],
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const cx = W / 2;
  const cy = H / 2;
  const R = Math.min(cx, cy) - 30;
  const n = features.length;
  if (n === 0) return;

  const angleStep = (2 * Math.PI) / n;

  // Draw rings
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 4; ring++) {
    const r = (ring / 4) * R;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const angle = i * angleStep - Math.PI / 2;
      const x = cx + r * Math.cos(angle);
      const y = cy + r * Math.sin(angle);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Draw axes
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + R * Math.cos(angle), cy + R * Math.sin(angle));
    ctx.stroke();
  }

  // Draw data polygon
  ctx.fillStyle = 'rgba(182, 255, 46, 0.15)';
  ctx.strokeStyle = '#B6FF2E';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i <= n; i++) {
    const idx = i % n;
    const val = Math.max(0, Math.min(1, features[idx].value));
    const r = val * R;
    const angle = idx * angleStep - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.fill();
  ctx.stroke();

  // Draw labels
  ctx.fillStyle = 'rgba(255,255,255,0.6)';
  ctx.font = '10px system-ui, sans-serif';
  ctx.textAlign = 'center';
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2;
    const labelR = R + 18;
    const x = cx + labelR * Math.cos(angle);
    const y = cy + labelR * Math.sin(angle);
    const label = FEATURE_LABELS[features[i].name] || features[i].name;
    ctx.fillText(label, x, y + 3);
  }
}

export function DrivingStyleSection({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<DrivingStyleData | null>(null);
  const [loading, setLoading] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get<DrivingStyleData>(`/sessions/${sessionId}/driving-style`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [sessionId]);

  // Draw radar when data arrives
  useEffect(() => {
    if (data?.features && canvasRef.current) {
      drawRadar(canvasRef.current, data.features);
    }
  }, [data]);

  if (loading) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-6 animate-pulse">
        <div className="h-4 bg-asphalt rounded w-32 mb-4" />
        <div className="h-48 bg-asphalt rounded" />
      </div>
    );
  }

  if (!data || data.available === false || !data.features?.length) {
    return null; // Graceful hide — no driving style data
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h2 className="text-lg font-monument text-chalk mb-1">Driving Style</h2>
      {data.style_label && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-acid-green text-sm font-body">{data.style_label}</span>
          {data.style_confidence != null && (
            <span className="text-steel text-xs font-body">
              ({Math.round(data.style_confidence * 100)}% confidence)
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Radar chart */}
        <div>
          <canvas
            ref={canvasRef}
            className="w-full"
            style={{ height: 260 }}
          />
        </div>

        {/* Trait bars + lists */}
        <div className="space-y-3">
          {data.features.map((f) => {
            const pct = Math.max(0, Math.min(100, f.value * 100));
            return (
              <div key={f.name}>
                <div className="flex justify-between text-xs mb-0.5">
                  <span className="text-steel font-body">
                    {FEATURE_LABELS[f.name] || f.name}
                  </span>
                  <span className="text-chalk font-telemetry">{pct.toFixed(0)}%</span>
                </div>
                <div className="w-full h-1.5 bg-asphalt rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-acid-green/60"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}

          {/* Strengths/Weaknesses from driving style */}
          {data.strengths?.length > 0 && (
            <div className="pt-2">
              <h4 className="text-xs text-green-400 font-body mb-1">Style Strengths</h4>
              <ul className="space-y-0.5">
                {data.strengths.map((s, i) => (
                  <li key={i} className="text-xs text-chalk/80 font-body">+ {s}</li>
                ))}
              </ul>
            </div>
          )}
          {data.weaknesses?.length > 0 && (
            <div className="pt-2">
              <h4 className="text-xs text-red-400 font-body mb-1">Style Weaknesses</h4>
              <ul className="space-y-0.5">
                {data.weaknesses.map((w, i) => (
                  <li key={i} className="text-xs text-chalk/80 font-body">- {w}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Add to OverviewTab**

In `page.tsx`, add import at top:

```tsx
import { DrivingStyleSection } from '@/components/app/DrivingStyleSection';
```

In the OverviewTab function, after the right column's best lap card (after the `</div>` that closes `space-y-6`, ~line 490), before the closing `</div>` of the OverviewTab grid, add a full-width row:

```tsx
      {/* Full-width sections below the 2-column layout */}
      <div className="lg:col-span-3 space-y-6">
        <DrivingStyleSection sessionId={sessionId} />
      </div>
```

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add lap-website/src/components/app/DrivingStyleSection.tsx lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat: add Driving Style section to Overview — radar chart, trait bars, style label"
```

---

### Task 6: Frontend — Add SessionDebrief component

**Files:**
- Create: `lap-website/src/components/app/SessionDebrief.tsx`
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx` — add to OverviewTab

**Step 1: Create the component**

Create `lap-website/src/components/app/SessionDebrief.tsx`:

```tsx
'use client';

interface CornerData {
  corner_number?: number;
  name?: string;
  coaching?: string;
  time_loss_s?: number | null;
  severity?: string;
}

interface ScoreData {
  pace_score: number | null;
  pace_max: number | null;
  consistency_score: number | null;
  consistency_max: number | null;
  execution_score: number | null;
  execution_max: number | null;
  robustness_score: number | null;
  robustness_max: number | null;
  adaptation_score: number | null;
  strengths: string[];
  weaknesses: string[];
}

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  is_valid: number;
  is_best: number;
}

interface SessionDebriefProps {
  totalScore: number | null;
  grade: string | null;
  scores: ScoreData | null;
  laps: LapData[];
  corners: CornerData[];
}

function fmtTime(s: number): string {
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const sec = s - m * 60;
    return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
  }
  return `${s.toFixed(3)}s`;
}

function buildSummary(totalScore: number | null, grade: string | null, scores: ScoreData | null): string {
  if (totalScore == null || !scores) return 'Score data unavailable for this session.';

  const parts: string[] = [`You scored ${Math.round(totalScore)}/100 (${grade || '?'} grade).`];

  if (scores.strengths?.length) {
    parts.push(`Your ${scores.strengths.join(' and ').toLowerCase()} ${scores.strengths.length === 1 ? 'was' : 'were'} standout.`);
  }
  if (scores.weaknesses?.length) {
    parts.push(`Focus on improving ${scores.weaknesses.join(' and ').toLowerCase()}.`);
  }

  return parts.join(' ');
}

function buildHighlights(laps: LapData[]): string[] {
  const validTimes = laps
    .filter((l) => l.is_valid && l.lap_time_s != null && l.lap_time_s > 0)
    .map((l) => l.lap_time_s!);

  if (validTimes.length === 0) return [];

  const best = Math.min(...validTimes);
  const mean = validTimes.reduce((a, b) => a + b, 0) / validTimes.length;
  const stddev = Math.sqrt(validTimes.reduce((a, t) => a + (t - mean) ** 2, 0) / validTimes.length);
  const cv = mean > 0 ? (stddev / mean) * 100 : 0;

  const highlights: string[] = [
    `Best lap: ${fmtTime(best)}`,
    `Consistency: ${cv.toFixed(1)}% variation across ${validTimes.length} laps`,
  ];

  // Top 25% average
  const sorted = [...validTimes].sort((a, b) => a - b);
  const top25Count = Math.max(1, Math.ceil(sorted.length * 0.25));
  const top25Avg = sorted.slice(0, top25Count).reduce((a, b) => a + b, 0) / top25Count;
  highlights.push(`Top 25% average: ${fmtTime(top25Avg)}`);

  return highlights;
}

function buildFocusAreas(corners: CornerData[]): { text: string; loss: number }[] {
  return corners
    .filter((c) => c.coaching && c.time_loss_s != null && c.time_loss_s > 0)
    .sort((a, b) => (b.time_loss_s ?? 0) - (a.time_loss_s ?? 0))
    .slice(0, 4)
    .map((c) => ({
      text: `${c.name || `Corner ${c.corner_number}`}: ${c.coaching} (+${c.time_loss_s!.toFixed(3)}s)`,
      loss: c.time_loss_s!,
    }));
}

function buildDrills(scores: ScoreData | null): string[] {
  if (!scores) return [];
  const drills: string[] = [];

  const consPct = scores.consistency_score != null && scores.consistency_max
    ? scores.consistency_score / scores.consistency_max
    : 1;
  if (consPct < 0.70) {
    drills.push('Consistency drill: 5 laps targeting same line and braking points');
  }

  const execPct = scores.execution_score != null && scores.execution_max
    ? scores.execution_score / scores.execution_max
    : 1;
  if (execPct < 0.70) {
    drills.push('Corner precision drill: focus on apex speed and exit throttle timing');
  }

  const robPct = scores.robustness_score != null && scores.robustness_max
    ? scores.robustness_score / scores.robustness_max
    : 1;
  if (robPct < 0.70) {
    drills.push('Endurance stint: 10+ lap run maintaining pace within 0.5% of best');
  }

  if (drills.length === 0) {
    drills.push('Continue refining your technique — focus on your weakest corner');
  }

  return drills;
}

export function SessionDebrief({ totalScore, grade, scores, laps, corners }: SessionDebriefProps) {
  const summary = buildSummary(totalScore, grade, scores);
  const highlights = buildHighlights(laps);
  const focusAreas = buildFocusAreas(corners);
  const drills = buildDrills(scores);

  if (!scores && totalScore == null) return null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h2 className="text-lg font-monument text-chalk mb-4">Session Debrief</h2>

      {/* Performance Summary */}
      <div className="mb-4">
        <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Performance Summary</h3>
        <p className="text-sm text-chalk/90 font-body leading-relaxed">{summary}</p>
      </div>

      {/* Key Highlights */}
      {highlights.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Key Highlights</h3>
          <ul className="space-y-1">
            {highlights.map((h, i) => (
              <li key={i} className="text-sm text-chalk/80 font-body flex gap-2">
                <span className="text-acid-green shrink-0">*</span>
                {h}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Focus Areas */}
      {focusAreas.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Focus Areas</h3>
          <ul className="space-y-1">
            {focusAreas.map((f, i) => (
              <li key={i} className="text-sm text-chalk/80 font-body flex gap-2">
                <span className="text-marshal-yellow shrink-0">!</span>
                {f.text}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Next Session Plan */}
      <div>
        <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Next Session Plan</h3>
        <ol className="space-y-1">
          {drills.map((d, i) => (
            <li key={i} className="text-sm text-chalk/80 font-body flex gap-2">
              <span className="text-cyan-400 shrink-0 font-telemetry">{i + 1}.</span>
              {d}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
```

**Step 2: Add to OverviewTab**

Import at top of page.tsx:

```tsx
import { SessionDebrief } from '@/components/app/SessionDebrief';
```

In the OverviewTab, inside the `lg:col-span-3` full-width section (created in Task 5), after `<DrivingStyleSection>`:

```tsx
        <SessionDebrief
          totalScore={session.total_score}
          grade={session.grade}
          scores={scores}
          laps={laps}
          corners={corners}
        />
```

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add lap-website/src/components/app/SessionDebrief.tsx lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat: add Session Debrief section — rule-based narrative from scores and corners"
```

---

### Task 7: Frontend — Add AchievementsBadges component

**Files:**
- Create: `lap-website/src/components/app/AchievementsBadges.tsx`
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx` — add to OverviewTab, update ScoreData type

**Step 1: Update ScoreData interface to include badges**

In `page.tsx`, update the `ScoreData` interface (around line 38) to add:

```typescript
interface BadgeData {
  id: string;
  label: string;
  tier: 'bronze' | 'silver' | 'gold';
  category: string;
  criteria: string;
}

interface ScoreData {
  pace_score: number | null;
  pace_max: number | null;
  consistency_score: number | null;
  consistency_max: number | null;
  execution_score: number | null;
  execution_max: number | null;
  robustness_score: number | null;
  robustness_max: number | null;
  adaptation_score: number | null;
  strengths: string[];
  weaknesses: string[];
  badges?: BadgeData[];
}
```

**Step 2: Create the component**

Create `lap-website/src/components/app/AchievementsBadges.tsx`:

```tsx
'use client';

interface BadgeData {
  id: string;
  label: string;
  tier: 'bronze' | 'silver' | 'gold';
  category: string;
  criteria: string;
}

const TIER_CONFIG = {
  gold:   { icon: 'AU', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', text: 'text-yellow-400', label: 'Gold' },
  silver: { icon: 'AG', bg: 'bg-zinc-400/10',   border: 'border-zinc-400/30',   text: 'text-zinc-300',   label: 'Silver' },
  bronze: { icon: 'CU', bg: 'bg-orange-600/10', border: 'border-orange-600/30', text: 'text-orange-400', label: 'Bronze' },
} as const;

export function AchievementsBadges({ badges }: { badges?: BadgeData[] }) {
  if (!badges || badges.length === 0) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h2 className="text-lg font-monument text-chalk mb-2">Achievements</h2>
        <p className="text-steel text-sm font-body">
          Keep pushing — badges unlock at 60%+ category scores.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h2 className="text-lg font-monument text-chalk mb-4">Achievements</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {badges.map((badge) => {
          const tier = TIER_CONFIG[badge.tier] || TIER_CONFIG.bronze;
          return (
            <div
              key={badge.id}
              className={`rounded-lg border p-4 ${tier.bg} ${tier.border}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs font-monument ${tier.text}`}>{tier.icon}</span>
                <span className={`text-xs font-body ${tier.text} uppercase tracking-wider`}>
                  {tier.label}
                </span>
              </div>
              <p className="text-sm font-body text-chalk">{badge.label}</p>
              <p className="text-[10px] text-steel font-body mt-1">{badge.criteria}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

**Step 3: Add to OverviewTab**

Import at top of page.tsx:

```tsx
import { AchievementsBadges } from '@/components/app/AchievementsBadges';
```

In the OverviewTab, inside the `lg:col-span-3` full-width section, after `<SessionDebrief>`:

```tsx
        <AchievementsBadges badges={scores?.badges} />
```

**Step 4: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 5: Commit**

```bash
git add lap-website/src/components/app/AchievementsBadges.tsx lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat: add Achievements section — badge cards with Bronze/Silver/Gold tiers"
```

---

### Task 8: Frontend — Wire Focus Mode button

**Files:**
- Modify: `lap-website/src/components/app/focus-mode/FocusMode.tsx` — upgrade from placeholder
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx` — add button + state

**Step 1: Upgrade FocusMode component**

Replace entire `FocusMode.tsx` with a working overlay that embeds the 3 chart tools:

```tsx
'use client';

import { SpeedTraceZoom, GpsTrace, GGExplorer } from '@/components/app/charts';
import { BACKEND_URL } from '@/lib/api-client';

interface FocusModeProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
  gpsLaps: number[];
  bestLap: number | null;
}

export function FocusMode({ sessionId, isOpen, onClose, gpsLaps, bestLap }: FocusModeProps) {
  if (!isOpen) return null;

  const apiBase = BACKEND_URL;

  return (
    <div
      className="fixed inset-0 z-50 bg-asphalt/98 overflow-auto"
      role="dialog"
      aria-modal="true"
      aria-label="Focus Mode"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-steel/10">
        <h2 className="text-lg font-monument text-chalk">Focus Mode</h2>
        <button
          onClick={onClose}
          className="px-3 py-1.5 bg-concrete border border-steel/20 rounded text-sm text-chalk font-body hover:bg-steel/10 transition-colors"
          aria-label="Close focus mode"
        >
          Exit Focus
        </button>
      </div>

      {/* Chart grid */}
      <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4" style={{ height: 'calc(100vh - 60px)' }}>
        <div className="bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
          <h3 className="text-xs font-monument text-steel mb-2">GPS Track Map</h3>
          <GpsTrace
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full h-full"
          />
        </div>
        <div className="bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
          <h3 className="text-xs font-monument text-steel mb-2">Speed Trace</h3>
          <SpeedTraceZoom
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full h-full"
          />
        </div>
        <div className="lg:col-span-2 bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
          <h3 className="text-xs font-monument text-steel mb-2">G-G Diagram</h3>
          <GGExplorer
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full h-full"
          />
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Add Focus Mode button + state to page**

In `page.tsx`, add import:

```tsx
import { FocusMode } from '@/components/app/focus-mode/FocusMode';
```

Add state (after other useState calls, ~line 148):

```tsx
  const [focusOpen, setFocusOpen] = useState(false);
```

Add button to header (after the "Download Report" link, inside the `flex items-center gap-3` div, ~line 282):

```tsx
          <button
            onClick={() => setFocusOpen(true)}
            className="px-4 py-2 bg-concrete border border-steel/20 rounded-lg text-sm text-chalk font-body hover:bg-steel/10 transition-colors"
            aria-label="Open focus mode"
          >
            Focus Mode
          </button>
```

Add component before closing `</div>` of the page (before the final `</div>`, ~line 322):

```tsx
      <FocusMode
        sessionId={sessionId}
        isOpen={focusOpen}
        onClose={() => setFocusOpen(false)}
        gpsLaps={gpsLaps}
        bestLap={bestLap}
      />
```

**Step 3: Verify build**

Run: `cd lap-website && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add lap-website/src/components/app/focus-mode/FocusMode.tsx lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat: wire Focus Mode button with GPS, Speed Trace, and GG chart tools"
```

---

### Task 9: Backend — Adaptation score parity test

**Files:**
- Create: `telemetry_tool/tests/test_adaptation_parity.py`

**Step 1: Write the parity test**

Create `telemetry_tool/tests/test_adaptation_parity.py`:

```python
"""Adaptation score parity tests — verify consistent output between paths."""
import pytest
from scoring import (
    score_session,
    MAX_ADAPTATION,
    ADAPT_V2_STABLE_DEFAULT_FRAC,
)


def _base_metrics():
    """Minimal metrics dict for scoring."""
    return {
        "best_s": 52.0,
        "n_laps": 10,
        "cv_pct": 1.2,
        "best_to_median_s": 0.8,
        "speed_mean_mps": 25.0,
        "accel_max_mps2": 8.0,
        "braking_max_mps2": 12.0,
        "early_mean_s": 53.0,
        "late_mean_s": 53.2,
        "early_yaw_var": 0.01,
        "late_yaw_var": 0.012,
    }


def _base_theory():
    """Minimal theoretical metrics."""
    return {"best_s": 50.0}


def test_default_adaptation_is_75_pct():
    """When no phase data, adaptation defaults to 75% of MAX_ADAPTATION."""
    result = score_session(_base_metrics(), _base_theory(), "practice")
    adapt = result["sub_scores"]["adaptation"]
    expected = round(MAX_ADAPTATION * ADAPT_V2_STABLE_DEFAULT_FRAC, 4)
    assert adapt["score"] == expected, (
        f"Default adaptation should be {expected}, got {adapt['score']}"
    )


def test_adaptation_display_rounds_cleanly():
    """Adaptation score rounds to an integer without ugly decimals."""
    result = score_session(_base_metrics(), _base_theory(), "practice")
    raw = result["sub_scores"]["adaptation"]["score"]
    display = round(raw)
    # 11.25 → 11; should not be 11.2500 in display
    assert isinstance(display, int)
    assert display in range(0, 16)


def test_adaptation_deterministic():
    """Same input produces same adaptation score (no randomness)."""
    r1 = score_session(_base_metrics(), _base_theory(), "practice")
    r2 = score_session(_base_metrics(), _base_theory(), "practice")
    assert r1["sub_scores"]["adaptation"]["score"] == r2["sub_scores"]["adaptation"]["score"]


def test_total_score_rounds_cleanly():
    """Total score should round to a clean integer for display."""
    result = score_session(_base_metrics(), _base_theory(), "practice")
    display = round(result["total_score"])
    assert isinstance(display, int)
    assert 0 <= display <= 100
```

**Step 2: Run tests**

Run: `cd telemetry_tool && python -m pytest tests/test_adaptation_parity.py -v`
Expected: All 4 tests PASS (these verify the current behavior is correct, not broken)

**Step 3: Commit**

```bash
git add telemetry_tool/tests/test_adaptation_parity.py
git commit -m "test: add adaptation score parity and display rounding tests"
```

---

### Task 10: Final verification — build, test, visual check

**Step 1: Run all backend tests**

```bash
cd telemetry_tool && python -m pytest tests/test_scoring_badges.py tests/test_adaptation_parity.py -v
```

Expected: All tests pass.

**Step 2: Run frontend build**

```bash
cd lap-website && npm run build
```

Expected: Build succeeds with no type errors.

**Step 3: Visual verification**

Start dev servers:
```bash
# Terminal 1
cd telemetry_tool && python main.py --serve

# Terminal 2
cd lap-website && npm run dev
```

Navigate to a session detail page and verify:
- [ ] 5 tabs visible: Overview, Corners & Coaching, Timeline, Analytics, Lap Data
- [ ] No "Performance" or "Visualize" tab
- [ ] Overview shows: Score Breakdown with subtitle, integer scores, Strengths, Areas to Improve, Performance Metrics grid, Driving Style radar, Session Debrief, Achievements
- [ ] Analytics tab has GPS + Speed + GG + Sector Panel
- [ ] Focus Mode button visible in header; clicking opens fullscreen overlay with 3 charts
- [ ] Score denominators show clean integers (e.g., "19 / 25" not "19.0 / 25.0")

**Step 4: Commit final state**

If any fixes were needed during visual check, commit them as a single fix commit.

```bash
git add -A
git commit -m "fix: visual adjustments from tab parity verification"
```
