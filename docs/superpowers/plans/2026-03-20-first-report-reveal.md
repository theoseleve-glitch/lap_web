# First Report Reveal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone reveal page shown after upload that surfaces focus areas, top corners, recoverable time, drills, and confidence.

**Architecture:** New `GET /api/v1/sessions/<id>/reveal` backend endpoint reads already-persisted data from 3 tables (sessions, scores, theoretical_data, analysis_json). New Next.js page at `/app/sessions/[id]/reveal/` fetches this endpoint and renders 5 animated sections. Upload redirect changed from session detail to reveal page.

**Tech Stack:** Python/Flask (backend endpoint), Next.js 14/TypeScript/Tailwind (frontend page), pytest (backend tests)

**Spec:** `docs/superpowers/specs/2026-03-20-first-report-reveal-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `telemetry_tool/web/routes/data_v2.py` | Modify | Add `GET /sessions/<id>/reveal` endpoint + `_build_reveal_payload()` helper |
| `telemetry_tool/tests/test_data_api_v2.py` | Modify | Add tests for reveal endpoint |
| `lap-website/src/app/app/sessions/[id]/reveal/page.tsx` | Create | Reveal page component with staggered animations |
| `lap-website/src/app/app/sessions/upload/page.tsx` | Modify | Change redirect target (one line) |

---

## Task 1: Backend — Reveal Endpoint Tests

**Files:**
- Modify: `telemetry_tool/tests/test_data_api_v2.py`

- [ ] **Step 1: Add sample data builders for reveal**

Append to the existing test file, after the existing sample builders:

```python
def _sample_session_row():
    """Session dict as returned by get_session_by_id, with reveal-relevant fields."""
    return {
        "session_id": "sess-001",
        "csv_filename": "session.csv",
        "display_name": "Practice 1",
        "driver_name": "Alex",
        "track_name": "Franciacorta",
        "track_id": "trk-001",
        "session_date": "2026-03-20",
        "session_type": "practice",
        "track_state": "dry",
        "n_laps": 14,
        "best_lap_time_s": 58.234,
        "total_score": 72,
        "grade": "B",
        "notes": None,
        "driver_id": 1,
        "kart_id": None,
        "kart_name": None,
        "track_unnamed": False,
    }


def _sample_theoretical_data():
    """Theoretical data with corner_coaching and confidence."""
    return {
        "corner_coaching": [
            {
                "corner_id": 3, "direction": "L",
                "time_loss_total_s": 0.31,
                "coaching_hints": ["Trail-brake deeper into corner"],
            },
            {
                "corner_id": 7, "direction": "R",
                "time_loss_total_s": 0.22,
                "coaching_hints": ["Earlier throttle application"],
            },
            {
                "corner_id": 1, "direction": "L",
                "time_loss_total_s": 0.18,
                "coaching_hints": ["Tighter entry line"],
            },
            {
                "corner_id": 5, "direction": "R",
                "time_loss_total_s": 0.10,
                "coaching_hints": [],
            },
        ],
        "theoretical_metrics": {
            "confidence": {
                "confidence_score": 82,
                "confidence_level": "high",
                "confidence_reasons": ["enough laps"],
                "component_scores": {},
            }
        },
    }


def _sample_analysis_json_with_coaching():
    """Analysis JSON containing coaching_v3 with focus_areas and drills."""
    return {
        "coaching_v3": {
            "focus_areas": [
                {"rank": 1, "category": "braking", "time_loss_s": 0.31,
                 "corner_ids": [3], "summary": "Late braking into T3",
                 "advice": "Trail-brake deeper"},
                {"rank": 2, "category": "exit_traction", "time_loss_s": 0.22,
                 "corner_ids": [7], "summary": "Exit speed lost at T7",
                 "advice": "Earlier throttle"},
                {"rank": 3, "category": "consistency", "time_loss_s": 0.15,
                 "corner_ids": [], "summary": "Lap time variation above target",
                 "advice": "Focus on rhythm"},
            ],
            "drills": [
                {"rank": 1, "title": "Trail-brake deeper into T3",
                 "description": "Focus on trail-braking", "focus_corners": [3],
                 "target_metric": "brake_release_point",
                 "target_improvement": "0.31s", "lap_count": 5},
                {"rank": 2, "title": "Hold throttle through T7 exit",
                 "description": "Exit traction drill", "focus_corners": [7],
                 "target_metric": "exit_speed",
                 "target_improvement": "0.22s", "lap_count": 5},
                {"rank": 3, "title": "Smooth steering T1 entry",
                 "description": "Entry precision", "focus_corners": [1],
                 "target_metric": "entry_line",
                 "target_improvement": "0.18s", "lap_count": 3},
            ],
        }
    }
```

- [ ] **Step 2: Write tests for reveal endpoint — happy path**

```python
class TestRevealEndpoint:
    """Tests for GET /api/v1/sessions/<id>/reveal."""

    @patch("web.routes.data_v2.models.get_analysis_json")
    @patch("web.routes.data_v2.models.get_theoretical_data")
    @patch("web.routes.data_v2.models.get_score_details")
    @patch("web.routes.data_v2.models.get_session_by_id")
    @patch("web.routes.data_v2.get_db_connection")
    def test_reveal_full_data(self, mock_conn, mock_session, mock_scores,
                               mock_theo, mock_analysis, client):
        mock_conn.return_value = MagicMock()
        mock_session.return_value = _sample_session_row()
        mock_scores.return_value = {
            "weaknesses": ["Execution needs work", "Pace below target"],
        }
        mock_theo.return_value = _sample_theoretical_data()
        mock_analysis.return_value = _sample_analysis_json_with_coaching()

        resp = client.get("/api/v1/sessions/sess-001/reveal")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        # Session-level fields from sessions table
        assert data["total_score"] == 72
        assert data["grade"] == "B"
        assert data["best_lap_s"] == 58.234
        assert data["n_laps"] == 14
        assert data["track_name"] == "Franciacorta"
        assert data["session_date"] == "2026-03-20"

        # Top corners: top 3 by time_loss, with coaching_hints[0]
        assert len(data["top_corners"]) == 3
        assert data["top_corners"][0]["corner_id"] == 3
        assert data["top_corners"][0]["time_loss_s"] == 0.31
        assert data["top_corners"][0]["coaching_hint"] == "Trail-brake deeper into corner"
        assert data["top_corners"][0]["direction"] == "L"

        # Recoverable: sum of ALL corners with positive loss (0.31+0.22+0.18+0.10)
        assert abs(data["recoverable_s"] - 0.81) < 0.01

        # Focus areas from coaching_v3
        assert len(data["focus_areas"]) == 3
        assert data["focus_areas"][0]["category"] == "braking"
        assert data["focus_areas"][0]["summary"] == "Late braking into T3"

        # Drills from coaching_v3
        assert len(data["drills"]) == 3
        assert data["drills"][0]["title"] == "Trail-brake deeper into T3"
        assert data["drills"][0]["target_improvement"] == "0.31s"

        # Confidence
        assert data["confidence"]["score"] == 82
        assert data["confidence"]["level"] == "high"

    @patch("web.routes.data_v2.models.get_analysis_json")
    @patch("web.routes.data_v2.models.get_theoretical_data")
    @patch("web.routes.data_v2.models.get_score_details")
    @patch("web.routes.data_v2.models.get_session_by_id")
    @patch("web.routes.data_v2.get_db_connection")
    def test_reveal_session_not_found(self, mock_conn, mock_session,
                                       mock_scores, mock_theo, mock_analysis,
                                       client):
        mock_conn.return_value = MagicMock()
        mock_session.return_value = None
        resp = client.get("/api/v1/sessions/nonexistent/reveal")
        assert resp.status_code == 404

    @patch("web.routes.data_v2.models.get_analysis_json")
    @patch("web.routes.data_v2.models.get_theoretical_data")
    @patch("web.routes.data_v2.models.get_score_details")
    @patch("web.routes.data_v2.models.get_session_by_id")
    @patch("web.routes.data_v2.get_db_connection")
    def test_reveal_no_coaching_falls_back_to_weaknesses(
        self, mock_conn, mock_session, mock_scores, mock_theo,
        mock_analysis, client
    ):
        mock_conn.return_value = MagicMock()
        mock_session.return_value = _sample_session_row()
        mock_scores.return_value = {
            "weaknesses": ["Execution needs work", "Pace below target"],
        }
        mock_theo.return_value = _sample_theoretical_data()
        mock_analysis.return_value = {}  # No coaching_v2 or v3

        resp = client.get("/api/v1/sessions/sess-001/reveal")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        # Falls back to weaknesses strings
        assert len(data["focus_areas"]) == 2
        assert data["focus_areas"][0]["summary"] == "Execution needs work"
        assert data["focus_areas"][0]["category"] == "general"

        # No drills when no coaching data
        assert data["drills"] == []

    @patch("web.routes.data_v2.models.get_analysis_json")
    @patch("web.routes.data_v2.models.get_theoretical_data")
    @patch("web.routes.data_v2.models.get_score_details")
    @patch("web.routes.data_v2.models.get_session_by_id")
    @patch("web.routes.data_v2.get_db_connection")
    def test_reveal_coaching_v2_fallback(
        self, mock_conn, mock_session, mock_scores, mock_theo,
        mock_analysis, client
    ):
        """coaching_v3 missing but coaching_v2 present — should use v2."""
        mock_conn.return_value = MagicMock()
        mock_session.return_value = _sample_session_row()
        mock_scores.return_value = {"weaknesses": []}
        mock_theo.return_value = _sample_theoretical_data()
        # Only coaching_v2, no coaching_v3
        mock_analysis.return_value = {
            "coaching_v2": {
                "focus_areas": [
                    {"rank": 1, "category": "braking", "time_loss_s": 0.25,
                     "summary": "V2 braking focus"},
                ],
                "drills": [
                    {"rank": 1, "title": "V2 drill one",
                     "target_improvement": "0.25s"},
                ],
            }
        }

        resp = client.get("/api/v1/sessions/sess-001/reveal")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        assert len(data["focus_areas"]) == 1
        assert data["focus_areas"][0]["summary"] == "V2 braking focus"
        assert len(data["drills"]) == 1
        assert data["drills"][0]["title"] == "V2 drill one"

    @patch("web.routes.data_v2.models.get_analysis_json")
    @patch("web.routes.data_v2.models.get_theoretical_data")
    @patch("web.routes.data_v2.models.get_score_details")
    @patch("web.routes.data_v2.models.get_session_by_id")
    @patch("web.routes.data_v2.get_db_connection")
    def test_reveal_no_corners(self, mock_conn, mock_session, mock_scores,
                                mock_theo, mock_analysis, client):
        mock_conn.return_value = MagicMock()
        mock_session.return_value = _sample_session_row()
        mock_scores.return_value = {"weaknesses": []}
        mock_theo.return_value = {}  # No corner_coaching
        mock_analysis.return_value = {}

        resp = client.get("/api/v1/sessions/sess-001/reveal")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        assert data["top_corners"] == []
        assert data["recoverable_s"] is None

    @patch("web.routes.data_v2.models.get_analysis_json")
    @patch("web.routes.data_v2.models.get_theoretical_data")
    @patch("web.routes.data_v2.models.get_score_details")
    @patch("web.routes.data_v2.models.get_session_by_id")
    @patch("web.routes.data_v2.get_db_connection")
    def test_reveal_no_confidence(self, mock_conn, mock_session, mock_scores,
                                   mock_theo, mock_analysis, client):
        mock_conn.return_value = MagicMock()
        mock_session.return_value = _sample_session_row()
        mock_scores.return_value = {"weaknesses": []}
        mock_theo.return_value = {"corner_coaching": []}  # No theoretical_metrics
        mock_analysis.return_value = {}

        resp = client.get("/api/v1/sessions/sess-001/reveal")
        assert resp.status_code == 200
        data = resp.get_json()["data"]

        assert data["confidence"] is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai && python -m pytest telemetry_tool/tests/test_data_api_v2.py::TestRevealEndpoint -v`

Expected: FAIL — endpoint doesn't exist yet.

- [ ] **Step 4: Commit tests**

```bash
git add telemetry_tool/tests/test_data_api_v2.py
git commit -m "test(reveal): add tests for GET /sessions/<id>/reveal endpoint"
```

---

## Task 2: Backend — Reveal Endpoint Implementation

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py`

- [ ] **Step 1: Add the `_build_reveal_payload()` helper**

Add this near the other helper functions (before the route definitions, around line 50). The function reads from already-fetched data dicts — no DB calls of its own.

```python
def _build_reveal_payload(
    session: dict,
    scores: dict | None,
    theo_data: dict | None,
    analysis: dict | None,
) -> dict:
    """Assemble the reveal payload from pre-fetched data.

    All inputs are dicts as returned by the repo functions.
    Returns a dict matching the reveal API contract.
    """
    result: dict = {
        "total_score": session.get("total_score"),
        "grade": session.get("grade"),
        "best_lap_s": session.get("best_lap_time_s"),
        "n_laps": session.get("n_laps"),
        "track_name": session.get("track_name"),
        "session_date": session.get("session_date"),
    }

    # ── Top corners (from theoretical_data.corner_coaching) ──
    corner_coaching = (theo_data or {}).get("corner_coaching", []) or []
    # Filter corners with positive time loss, sort desc
    lossy = [c for c in corner_coaching
             if (c.get("time_loss_total_s") or 0) > 0]
    lossy.sort(key=lambda c: c.get("time_loss_total_s", 0), reverse=True)

    result["top_corners"] = []
    for c in lossy[:3]:
        hints = c.get("coaching_hints") or []
        result["top_corners"].append({
            "corner_id": c.get("corner_id"),
            "direction": c.get("direction"),
            "time_loss_s": round(c.get("time_loss_total_s", 0), 3),
            "coaching_hint": hints[0] if hints else None,
        })

    result["recoverable_s"] = (
        round(sum(c.get("time_loss_total_s", 0) for c in lossy), 3)
        if lossy else None
    )

    # ── Focus areas (prefer coaching_v3 > coaching_v2 > scores.weaknesses) ──
    analysis = analysis or {}
    coaching = analysis.get("coaching_v3") or analysis.get("coaching_v2") or {}
    raw_focus = coaching.get("focus_areas", []) if coaching else []

    if raw_focus:
        # Sort by time_loss_s desc if available, take top 3
        sorted_fa = sorted(raw_focus, key=lambda f: f.get("time_loss_s", 0), reverse=True)
        result["focus_areas"] = [
            {"category": f.get("category", "general"), "summary": f.get("summary", "")}
            for f in sorted_fa[:3]
        ]
    else:
        # Fallback to scores.weaknesses (plain strings)
        weaknesses = (scores or {}).get("weaknesses", []) or []
        result["focus_areas"] = [
            {"category": "general", "summary": w}
            for w in weaknesses[:3]
        ]

    # ── Drills (prefer coaching_v3 > coaching_v2) ──
    raw_drills = coaching.get("drills", []) if coaching else []
    if raw_drills:
        sorted_drills = sorted(raw_drills, key=lambda d: d.get("rank", 999))
        result["drills"] = [
            {"title": d.get("title", ""), "target_improvement": d.get("target_improvement", "")}
            for d in sorted_drills[:3]
        ]
    else:
        result["drills"] = []

    # ── Confidence (from theoretical_metrics) ──
    theo_metrics = (theo_data or {}).get("theoretical_metrics", {}) or {}
    conf = theo_metrics.get("confidence")
    if conf and isinstance(conf, dict):
        result["confidence"] = {
            "score": conf.get("confidence_score"),
            "level": conf.get("confidence_level"),
        }
    else:
        result["confidence"] = None

    return result
```

- [ ] **Step 2: Add the route**

Add near the other session-scoped endpoints (after the scores endpoint, around line 850):

```python
# ── GET /api/v1/sessions/<id>/reveal ──────────────────────────────────

@bp.route("/sessions/<session_id>/reveal", methods=["GET"])
@_safe_api
def get_reveal(session_id: str) -> tuple[dict, int]:
    """Return a lightweight reveal payload for post-upload display."""
    conn = get_db_connection()
    session = models.get_session_by_id(conn, session_id)
    if session is None:
        return api_error(ErrorCode.NOT_FOUND, "Session not found", status=404)

    scores = models.get_score_details(conn, session_id)
    theo_data = models.get_theoretical_data(conn, session_id)
    analysis = models.get_analysis_json(conn, session_id)

    payload = _build_reveal_payload(session, scores, theo_data, analysis)
    return api_response(payload)
```

- [ ] **Step 3: Run the reveal tests**

Run: `cd C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai && python -m pytest telemetry_tool/tests/test_data_api_v2.py::TestRevealEndpoint -v`

Expected: All 6 tests PASS.

- [ ] **Step 4: Run the full data_v2 test suite to check for regressions**

Run: `cd C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai && python -m pytest telemetry_tool/tests/test_data_api_v2.py -v`

Expected: All existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(reveal): add GET /sessions/<id>/reveal endpoint"
```

---

## Task 3: Frontend — Reveal Page

**Files:**
- Create: `lap-website/src/app/app/sessions/[id]/reveal/page.tsx`

- [ ] **Step 1: Create the reveal page component**

```tsx
'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { formatLapTime } from '@/lib/format-utils';
import { AnimatedCounter } from '@/components/ui/AnimatedCounter';

// ── Types ────────────────────────────────────────────────────

interface FocusArea {
  category: string;
  summary: string;
}

interface TopCorner {
  corner_id: number;
  direction: string | null;
  time_loss_s: number;
  coaching_hint: string | null;
}

interface Drill {
  title: string;
  target_improvement: string;
}

interface Confidence {
  score: number;
  level: string;
}

interface RevealData {
  total_score: number | null;
  grade: string | null;
  best_lap_s: number | null;
  n_laps: number | null;
  track_name: string | null;
  session_date: string | null;
  focus_areas: FocusArea[];
  top_corners: TopCorner[];
  recoverable_s: number | null;
  drills: Drill[];
  confidence: Confidence | null;
}

// ── Grade colors (local, matches session detail page pattern) ────────

// Matches session detail page (page.tsx:130-137) — uses Tailwind palette
// because grade colors need 6 distinct hues beyond our 5 accent tokens.
const GRADE_COLORS: Record<string, string> = {
  S: 'text-yellow-400 border-yellow-400',
  A: 'text-green-400 border-green-400',
  B: 'text-cyan-400 border-cyan-400',
  C: 'text-yellow-500 border-yellow-500',
  D: 'text-orange-400 border-orange-400',
  F: 'text-red-500 border-red-500',
};

function gradeColorClass(grade: string | null): string {
  if (!grade) return 'text-steel border-steel';
  return GRADE_COLORS[grade.charAt(0).toUpperCase()] || 'text-steel border-steel';
}

// ── Confidence pill color ────────────────────────────────────

function confidenceColor(level: string): string {
  if (level === 'high') return 'text-acid-green bg-acid-green/10 border-acid-green/30';
  if (level === 'medium') return 'text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30';
  return 'text-safety-red bg-safety-red/10 border-safety-red/30';
}

// ── Animation wrapper ────────────────────────────────────────

function FadeUp({ delay, children, className = '' }: {
  delay: number;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`opacity-0 translate-y-5 ${className}`}
      style={{
        animation: `fadeUp 400ms ease-out ${delay}ms forwards`,
      }}
    >
      {children}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────

export default function RevealPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.id as string;

  const [data, setData] = useState<RevealData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.get<RevealData>(`/sessions/${sessionId}/reveal`)
      .then((d) => {
        if (!d || !d.n_laps) {
          // Zero valid laps or null — skip reveal
          router.replace(`/app/sessions/${sessionId}`);
          return;
        }
        setData(d);
      })
      .catch(() => {
        setError(true);
      })
      .finally(() => setLoading(false));
  }, [sessionId, router]);

  if (loading) {
    return (
      <div className="min-h-screen bg-asphalt flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-gold rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !data) {
    router.replace('/app/sessions');
    return null;
  }

  const hasScore = data.total_score != null;
  const hasCorners = data.top_corners.length > 0;
  const hasFocus = data.focus_areas.length > 0;
  const hasDrills = data.drills.length > 0;

  return (
    <>
      {/* Keyframes */}
      <style>{`
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>

      <div className="min-h-screen bg-asphalt flex flex-col items-center justify-center px-4 py-12">
        <div className="w-full max-w-2xl space-y-8">

          {/* 1. Header bar (fade-in only, no translateY per spec) */}
          <div
            className="opacity-0 flex items-center justify-between"
            style={{ animation: 'fadeIn 300ms ease-out 0ms forwards' }}
          >
            <div className="font-monument text-sm text-steel">
              {data.track_name || 'Unknown Track'}
              {data.session_date && (
                <span className="ml-2 text-steel/60">{data.session_date}</span>
              )}
            </div>
            {data.confidence && (
              <div>
                <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-telemetry ${confidenceColor(data.confidence.level)}`}>
                  {data.confidence.score}% confidence
                </span>
                {data.confidence.score < 60 && (
                  <p className="text-safety-red/70 text-[10px] font-body mt-1 text-right">
                    Limited data — results improve with more laps
                  </p>
                )}
              </div>
            )}
          </div>

          {/* 2. Hero: Score + Grade */}
          <FadeUp delay={200}>
            <div className="text-center py-6">
              <p className="font-body text-steel text-sm mb-2">Your Session Report</p>
              {hasScore ? (
                <div className="flex items-center justify-center gap-4">
                  <span className="font-monument text-6xl text-chalk">
                    <AnimatedCounter value={Math.round(data.total_score!)} duration={1400} />
                  </span>
                  <span className="font-body text-steel text-xl">/ 100</span>
                  {data.grade && (
                    <span className={`w-12 h-12 flex items-center justify-center rounded-lg border-2 font-monument text-xl ${gradeColorClass(data.grade)}`}>
                      {data.grade}
                    </span>
                  )}
                </div>
              ) : data.best_lap_s != null ? (
                <div className="flex items-center justify-center gap-2">
                  <span className="font-monument text-5xl text-chalk">
                    {formatLapTime(data.best_lap_s)}
                  </span>
                  <span className="font-body text-steel text-sm">best lap</span>
                </div>
              ) : (
                <p className="font-monument text-2xl text-steel">Session Analyzed</p>
              )}
            </div>
          </FadeUp>

          {/* 3. Stat row */}
          <FadeUp delay={1600}>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-center">
              <div>
                <div className="font-telemetry text-2xl text-chalk">
                  {data.recoverable_s != null ? `${data.recoverable_s.toFixed(3)}s` : '\u2014'}
                </div>
                <div className="font-body text-xs text-steel mt-1">recoverable</div>
              </div>
              <div>
                <div className="font-telemetry text-2xl text-chalk">
                  {data.best_lap_s != null ? formatLapTime(data.best_lap_s) : '\u2014'}
                </div>
                <div className="font-body text-xs text-steel mt-1">best lap</div>
              </div>
              <div>
                <div className="font-telemetry text-2xl text-chalk">
                  {data.n_laps ?? '\u2014'}
                </div>
                <div className="font-body text-xs text-steel mt-1">laps analyzed</div>
              </div>
            </div>
          </FadeUp>

          {/* 4. Top Corners */}
          {hasCorners && (
            <div>
              <FadeUp delay={2000}>
                <h3 className="font-monument text-xs text-steel uppercase tracking-wider mb-3">
                  Top Corners
                </h3>
              </FadeUp>
              <div className="space-y-2">
                {data.top_corners.map((c, i) => (
                  <FadeUp key={c.corner_id} delay={2000 + (i + 1) * 100}>
                    <div className="bg-concrete rounded-xl border border-steel/10 p-4 flex items-center gap-4">
                      <div className="font-monument text-sm text-chalk whitespace-nowrap">
                        T{c.corner_id}
                        {c.direction && (
                          <span className="ml-1 text-steel text-xs">{c.direction}</span>
                        )}
                      </div>
                      <div className="font-telemetry text-safety-red whitespace-nowrap">
                        -{c.time_loss_s.toFixed(2)}s
                      </div>
                      {c.coaching_hint && (
                        <div className="text-chalk/80 font-body text-sm truncate">
                          {c.coaching_hint}
                        </div>
                      )}
                    </div>
                  </FadeUp>
                ))}
              </div>
            </div>
          )}

          {/* 5. Focus Areas + Drills */}
          {(hasFocus || hasDrills) && (
            <FadeUp delay={2500}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                {hasFocus && (
                  <div>
                    <h3 className="font-monument text-xs text-steel uppercase tracking-wider mb-3">
                      Focus Areas
                    </h3>
                    <ul className="space-y-2">
                      {data.focus_areas.map((fa, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <span className="text-gold mt-1 flex-shrink-0">&#x25CF;</span>
                          <span className="text-chalk font-body text-sm">{fa.summary}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {hasDrills ? (
                  <div>
                    <h3 className="font-monument text-xs text-steel uppercase tracking-wider mb-3">
                      Next-Session Drills
                    </h3>
                    <ol className="space-y-2">
                      {data.drills.map((d, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <span className="font-telemetry text-steel text-xs mt-0.5 flex-shrink-0">
                            {i + 1}.
                          </span>
                          <div>
                            <span className="text-chalk font-body text-sm">{d.title}</span>
                            {d.target_improvement && (
                              <span className="ml-2 text-steel font-telemetry text-xs">
                                ~{d.target_improvement}
                              </span>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : (
                  <div>
                    <h3 className="font-monument text-xs text-steel uppercase tracking-wider mb-3">
                      Next-Session Drills
                    </h3>
                    <p className="text-steel font-body text-sm">
                      Upload more sessions for personalized drills
                    </p>
                  </div>
                )}
              </div>
            </FadeUp>
          )}

          {/* 6. CTA */}
          <FadeUp delay={2900}>
            <div className="text-center pt-4">
              <Link
                href={`/app/sessions/${sessionId}`}
                className="inline-block bg-gold text-white font-telemetry rounded-lg px-8 py-3 hover:bg-gold/80 transition-colors"
              >
                View Full Session
              </Link>
            </div>
          </FadeUp>

        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Verify the page builds**

Run: `cd C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\lap-website && npx next build 2>&1 | head -30`

Expected: Build succeeds without errors. (The page won't render without a backend, but it should compile.)

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/app/app/sessions/\[id\]/reveal/page.tsx
git commit -m "feat(reveal): add reveal page with staggered animations"
```

---

## Task 4: Frontend — Change Upload Redirect

**Files:**
- Modify: `lap-website/src/app/app/sessions/upload/page.tsx`

- [ ] **Step 1: Change the redirect target**

In `lap-website/src/app/app/sessions/upload/page.tsx`, find the line:

```typescript
setTimeout(() => router.push(`/app/sessions/${sid}`), 1500);
```

Change to:

```typescript
setTimeout(() => router.push(`/app/sessions/${sid}/reveal`), 1500);
```

This is around line 631 — search for `router.push(\`/app/sessions/\${sid}\`)` in the completed handler (the one inside the `if (batchTotal <= 1)` block).

- [ ] **Step 2: Verify the build still works**

Run: `cd C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\lap-website && npx next build 2>&1 | head -30`

Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/app/app/sessions/upload/page.tsx
git commit -m "feat(reveal): redirect upload to reveal page instead of session detail"
```

---

## Task 5: Deploy & Verify

**Files:** None (deploy only)

- [ ] **Step 1: Run full backend test suite**

Run: `cd C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai && python -m pytest telemetry_tool/tests/test_data_api_v2.py -v`

Expected: All tests pass, including the 6 new reveal tests.

- [ ] **Step 2: Deploy backend**

```bash
scp telemetry_tool/web/routes/data_v2.py root@46.225.227.24:/opt/lap-api/telemetry_tool/web/routes/data_v2.py
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
```

Verify: `curl https://api.lap-coach.racing/healthz` returns 200.

- [ ] **Step 3: Test the reveal endpoint live**

```bash
# Pick any existing session ID from production
curl -s https://api.lap-coach.racing/api/v1/sessions | jq '.data[0].session_id'
# Then test the reveal endpoint
curl -s "https://api.lap-coach.racing/api/v1/sessions/<SESSION_ID>/reveal" | jq .
```

Expected: Returns JSON with `ok: true` and the reveal payload.

- [ ] **Step 4: Deploy frontend**

```bash
cd C:\Users\Admin\Documents\Telemetry\Analysis\V2_claude_ai\lap-website && npm run build && npm run cf:deploy
```

Expected: Cloudflare Workers deployment succeeds.

- [ ] **Step 5: Verify end-to-end**

Upload a CSV file at `https://lap-coach.racing/app/sessions/upload`. After processing completes, you should be redirected to `/app/sessions/<id>/reveal` instead of the session detail page. The reveal should show the animated sections, and "View Full Session" should navigate to the existing session detail.

- [ ] **Step 6: Commit all changes together if not already committed**

```bash
git add -A && git status  # Verify only expected files
git commit -m "feat(reveal): first report reveal — backend + frontend + redirect"
```
