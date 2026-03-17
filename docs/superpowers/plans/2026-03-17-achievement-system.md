# Achievement System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing gamification backend into the session upload flow, upgrade visuals to hex SVG badges with animations, add licence tier system, and add shareable session cards.

**Architecture:** The backend gamification modules (`gamification/xp.py`, `achievements.py`, `streaks.py`) are fully implemented but never called. The session upload Celery finalize task needs to call them and return results to the frontend. The frontend components exist but need visual upgrade to hex SVG badges with particle/glow animations. New features: licence tiers (computed from driver_xp) and canvas-rendered share cards.

**Tech Stack:** Python Flask, PostgreSQL, Celery, Next.js 14, TypeScript, Tailwind CSS, Canvas API, SVG

**Spec:** `docs/superpowers/specs/2026-03-17-achievement-system-design.md`

---

## File Map

### Backend — Modify
- `telemetry_tool/tasks/pipeline_tasks.py` — call gamification after persist (the wiring)
- `telemetry_tool/gamification/xp.py` — add licence tier computation
- `telemetry_tool/web/routes/api_v1_entities.py` — add licence to progress endpoint

### Backend — Create
- `telemetry_tool/gamification/licence.py` — licence tier logic
- `telemetry_tool/tests/test_gamification_wire.py` — integration test

### Frontend — Upgrade
- `lap-website/src/components/app/gamification/BadgeHex.tsx` — new: hex SVG badge component
- `lap-website/src/components/app/gamification/AchievementUnlockOverlay.tsx` — new: full-screen unlock with particles
- `lap-website/src/components/app/gamification/LevelUpModal.tsx` — upgrade: licence card flip + shimmer
- `lap-website/src/components/app/gamification/AchievementGrid.tsx` — upgrade: use BadgeHex
- `lap-website/src/components/app/gamification/LicenceCard.tsx` — new: tier card + progress

### Frontend — Create
- `lap-website/src/components/app/gamification/ShareCardCanvas.tsx` — canvas PNG generator
- `lap-website/src/components/app/gamification/ParticleBurst.tsx` — reusable particle animation

---

## Chunk 1: Backend Wiring (gamification on session upload)

### Task 1.1: Wire gamification into pipeline finalize

**Files:**
- Modify: `telemetry_tool/tasks/pipeline_tasks.py` — `_persist_session_data()` function, after all persist steps

- [ ] **Step 1: Read `_persist_session_data` to find the insertion point**

The function ends around line 895 with `conn.close()`. The gamification calls should go after all persist steps succeed but before `conn.close()`.

- [ ] **Step 2: Add gamification wiring after session persist**

After the channel metadata persist (step 11), before `conn.close()`, add:

```python
# 12. Gamification — award XP, check achievements, update streak
try:
    from gamification.xp import award_session_xp
    from gamification.achievements import check_achievements
    from gamification.streaks import update_streak
    from gamification.queries import count_driver_sessions, get_driver_best_lap

    meta = result.get("session_meta") or {}
    score_result = result.get("score_result") or {}
    badges = score_result.get("badges", [])

    # Streak
    session_date = meta.get("session_date") or meta.get("date", "")
    streak_result = update_streak(conn, driver_id, ctx.workspace_id, session_date)
    conn.commit()

    # Previous best for PB detection
    prev_best = get_driver_best_lap(conn, driver_id, ctx.workspace_id)
    current_best = result.get("best_lap_time_s") or (
        min(t for t in (result.get("lap_times") or []) if t and t > 0)
        if result.get("lap_times") else None
    )

    # XP
    xp_result = award_session_xp(
        conn, driver_id, ctx.workspace_id, session_id,
        badges=badges,
        previous_best_lap=prev_best,
        current_best_lap=current_best,
    )
    conn.commit()

    # Achievements
    session_count = count_driver_sessions(conn, driver_id, ctx.workspace_id)
    prev_score = None  # TODO: fetch previous session score for score_jump
    achievement_context = {
        "session_count": session_count,
        "badges": badges,
        "streak": streak_result.get("current_streak", 0),
        "is_personal_best": (
            current_best is not None and prev_best is not None
            and current_best < prev_best
        ),
        "score_improvement": 0,
        "plan_just_completed": False,
        "week_just_completed": False,
    }
    new_achievements = check_achievements(
        conn, driver_id, ctx.workspace_id, session_id, achievement_context,
    )
    conn.commit()

    # Store gamification results in analysis_json for frontend
    gam_data = {
        "xp_gained": xp_result.get("xp_gained", 0),
        "old_level": xp_result.get("old_level", 0),
        "new_level": xp_result.get("new_level", 0),
        "leveled_up": xp_result.get("leveled_up", False),
        "current_streak": streak_result.get("current_streak", 0),
        "new_achievements": [
            {"key": a["key"], "label": a["label"], "description": a["description"], "icon": a["icon"]}
            for a in new_achievements
        ],
    }
    result["gamification"] = gam_data
    logger.info(
        "Gamification: +%d XP, level %d→%d, streak %d, %d new achievements for session %s",
        gam_data["xp_gained"], gam_data["old_level"], gam_data["new_level"],
        gam_data["current_streak"], len(new_achievements), session_id,
    )
except Exception:
    logger.warning("Gamification failed (non-fatal)", exc_info=True)
    conn.rollback()
```

- [ ] **Step 3: Verify syntax**

```bash
python -c "import ast; ast.parse(open('telemetry_tool/tasks/pipeline_tasks.py', encoding='utf-8').read()); print('OK')"
```

- [ ] **Step 4: Run existing pipeline tests**

```bash
pytest telemetry_tool/tests/test_re_port_correctness.py -v
```

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/tasks/pipeline_tasks.py
git commit -m "feat: wire gamification into session upload pipeline"
```

---

### Task 1.2: Add licence tier computation

**Files:**
- Create: `telemetry_tool/gamification/licence.py`

- [ ] **Step 1: Create licence tier module**

```python
"""Licence tier system — career progression gated by skill + experience."""
from __future__ import annotations
from typing import Any

LICENCE_TIERS = [
    {"tier": "rookie",   "color": "#888888", "laps": 0,    "score": 0,  "extra": None},
    {"tier": "club",     "color": "#B6FF2E", "laps": 50,   "score": 50, "extra": None},
    {"tier": "national", "color": "#00d4ff", "laps": 200,  "score": 65, "extra": "2_tracks"},
    {"tier": "pro",      "color": "#D946EF", "laps": 500,  "score": 75, "extra": "3_pbs"},
    {"tier": "elite",    "color": "#FFD400", "laps": 1000, "score": 85, "extra": "cv_1.5"},
    {"tier": "legend",   "color": "#FF3B6B", "laps": 2000, "score": 90, "extra": "streak_5_80"},
]


def compute_licence_tier(
    total_laps: int,
    best_score: float,
    track_count: int = 0,
    pb_improvements: int = 0,
    best_cv: float | None = None,
    best_streak_80: int = 0,
) -> dict[str, Any]:
    """Compute current licence tier and progress to next."""
    current_idx = 0
    for i, t in enumerate(LICENCE_TIERS):
        if total_laps < t["laps"] or best_score < t["score"]:
            break
        # Check extra requirements
        if t["extra"] == "2_tracks" and track_count < 2:
            break
        if t["extra"] == "3_pbs" and pb_improvements < 3:
            break
        if t["extra"] == "cv_1.5" and (best_cv is None or best_cv > 1.5):
            break
        if t["extra"] == "streak_5_80" and best_streak_80 < 5:
            break
        current_idx = i

    current = LICENCE_TIERS[current_idx]
    next_tier = LICENCE_TIERS[current_idx + 1] if current_idx < len(LICENCE_TIERS) - 1 else None

    progress = {}
    if next_tier:
        progress["laps"] = {"current": total_laps, "required": next_tier["laps"]}
        progress["score"] = {"current": best_score, "required": next_tier["score"]}

    return {
        "tier": current["tier"],
        "color": current["color"],
        "tier_index": current_idx,
        "next_tier": next_tier["tier"] if next_tier else None,
        "next_color": next_tier["color"] if next_tier else None,
        "progress": progress,
    }
```

- [ ] **Step 2: Add licence to progress endpoint**

In `telemetry_tool/web/routes/api_v1_entities.py`, in `get_driver_progress_api()`, after getting progress, add:

```python
from gamification.licence import compute_licence_tier
# Fetch stats for licence computation
total_laps = progress.get("total_xp", 0) // 5  # rough estimate, or query
# ... compute licence and add to response
progress["licence"] = compute_licence_tier(total_laps, best_score, ...)
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/gamification/licence.py telemetry_tool/web/routes/api_v1_entities.py
git commit -m "feat: add licence tier system"
```

---

## Chunk 2: Frontend Visual Upgrade

### Task 2.1: BadgeHex SVG component

**Files:**
- Create: `lap-website/src/components/app/gamification/BadgeHex.tsx`

- [ ] **Step 1: Create the reusable hex badge SVG component**

Component accepts: `icon` (helmet/trophy/stopwatch/wheel/shield), `tier` (gold/silver/bronze/locked), `size` (number), `glow` (boolean), `animate` (boolean for stroke-draw).

Uses the SVG trophy designs from `docs/achievement-mockup.html`.

- [ ] **Step 2: Build to verify no TS errors**

```bash
cd lap-website && npm run build
```

- [ ] **Step 3: Commit**

### Task 2.2: ParticleBurst component

**Files:**
- Create: `lap-website/src/components/app/gamification/ParticleBurst.tsx`

- [ ] **Step 1: Create particle burst animation component**

Spawns N colored dots that explode outward using CSS keyframes. Props: `color`, `count`, `active`.

- [ ] **Step 2: Commit**

### Task 2.3: AchievementUnlockOverlay

**Files:**
- Create: `lap-website/src/components/app/gamification/AchievementUnlockOverlay.tsx`

- [ ] **Step 1: Build the full-screen unlock overlay**

Sequence: backdrop fade → particle burst → hex stroke draw → badge pop → ring expand → glow pulse → text stagger → tier dots → progress bar → dismiss button. Uses BadgeHex + ParticleBurst.

- [ ] **Step 2: Wire into session detail page**

In `app/sessions/[id]/page.tsx`, when `scores?.gamification?.new_achievements` has items, show the overlay for the first one.

- [ ] **Step 3: Build + commit**

### Task 2.4: Upgrade LevelUpModal with licence card flip

**Files:**
- Modify: `lap-website/src/components/app/gamification/LevelUpModal.tsx`

- [ ] **Step 1: Add licence card 3D flip animation**

Replace the current basic modal with: licence card (perspective + rotateY flip), shimmer sweep, large tier name with counter-scale, XP bar, streak flames, new achievements list.

- [ ] **Step 2: Build + commit**

### Task 2.5: LicenceCard component

**Files:**
- Create: `lap-website/src/components/app/gamification/LicenceCard.tsx`

- [ ] **Step 1: Create licence card with progress bar**

Shows current tier (gradient border + letter badge), progress to next (dual bar: laps + score), full tier ladder strip.

- [ ] **Step 2: Add to driver profile page**

In `app/drivers/[id]/page.tsx`, render `<LicenceCard>` from the progress API data.

- [ ] **Step 3: Build + commit**

### Task 2.6: Upgrade AchievementGrid to use BadgeHex

**Files:**
- Modify: `lap-website/src/components/app/gamification/AchievementGrid.tsx`

- [ ] **Step 1: Replace text-based badges with BadgeHex SVG**

Use the hex badge grid from the mockup. Earned = full color + hover scale. Locked = grey + lock icon + 35% opacity. Click = detail card.

- [ ] **Step 2: Build + commit**

---

## Chunk 3: Share Card + Deploy

### Task 3.1: ShareCardCanvas

**Files:**
- Create: `lap-website/src/components/app/gamification/ShareCardCanvas.tsx`

- [ ] **Step 1: Create canvas-based share card renderer**

1200x630 canvas. Draws: dark gradient bg, branding, session title, track, date, grade badge, key stats (best lap, score, laps, CV%), mini hex badges, URL. Exports as PNG blob via `canvas.toBlob()`.

- [ ] **Step 2: Add "Share" button to session detail page**

In `app/sessions/[id]/page.tsx`, add a share button that renders the canvas offscreen and triggers download.

- [ ] **Step 3: Build + commit**

### Task 3.2: Export updates + deploy

- [ ] **Step 1: Update gamification index exports**

Add new components to `lap-website/src/components/app/gamification/index.ts`.

- [ ] **Step 2: Deploy backend**

```bash
scp telemetry_tool/tasks/pipeline_tasks.py root@46.225.227.24:/opt/lap-api/telemetry_tool/tasks/pipeline_tasks.py
scp telemetry_tool/gamification/licence.py root@46.225.227.24:/opt/lap-api/telemetry_tool/gamification/licence.py
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api celery-pipeline celery-default && docker compose -f docker-compose.prod.yml up -d api celery-pipeline celery-default"
curl https://api.lap-coach.racing/healthz
```

- [ ] **Step 3: Deploy frontend**

```bash
cd lap-website
powershell -Command "Remove-Item -Path '.open-next' -Recurse -Force -ErrorAction SilentlyContinue"
npx @opennextjs/cloudflare build
npx wrangler deploy .open-next/worker.js --name lap-website --compatibility-date 2025-12-01 --compatibility-flags nodejs_compat --assets .open-next/assets
```

- [ ] **Step 4: Verify live**

Upload a test session, confirm gamification data appears in the session response (XP, level, streak, achievements).

---

## Deployment Sequence

Chunk 1 (backend wiring) can deploy independently — gamification starts accumulating silently.
Chunk 2 (visual upgrade) depends on Chunk 1 data being available.
Chunk 3 (share card) is independent of Chunk 2.
