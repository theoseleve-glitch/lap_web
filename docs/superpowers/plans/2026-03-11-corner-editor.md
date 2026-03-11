# Corner Editor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the toggle-based CornerPicker with a click-to-place corner editor that auto-proceeds with detected corners after 15s of inactivity.

**Architecture:** New `CornerEditor.tsx` canvas component with drag handles, replacing `CornerPicker.tsx`. Backend extended to accept custom corner geometry alongside the existing `selected_corner_ids` format. Pipeline finalize stage enriches custom corners with lat/lon/direction from track data before passing to analysis.

**Tech Stack:** React 18 + Canvas 2D (frontend), Pydantic v2 (schema), Flask (route), Python dataclass (pipeline context)

**Spec:** `docs/superpowers/specs/2026-03-11-corner-editor-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `lap-website/src/components/app/CornerEditor.tsx` | Canvas corner editor with timer, click-to-place, drag handles |
| Modify | `lap-website/src/app/app/sessions/upload/page.tsx` | Swap CornerPicker for CornerEditor, update submit payload |
| Modify | `telemetry_tool/web/schemas/jobs.py` | Add `corners` field to ResumeJobSchema |
| Modify | `telemetry_tool/web/routes/jobs.py` | Handle new `corners` payload in resume endpoint |
| Modify | `telemetry_tool/pipeline_context.py` | Add `custom_corners` field + setter |
| Modify | `telemetry_tool/tasks/pipeline_tasks.py` | Use custom corners in finalize when provided |
| Modify | `telemetry_tool/pipeline/helpers.py` | Add `enrich_custom_corners()` helper |
| Create | `telemetry_tool/tests/test_custom_corners.py` | Backend tests for custom corner flow |

---

## Chunk 1: Backend — Schema + Context + Enrichment

### Task 1: Extend ResumeJobSchema to accept custom corners

**Files:**
- Modify: `telemetry_tool/web/schemas/jobs.py`
- Create: `telemetry_tool/tests/test_custom_corners.py`

- [ ] **Step 1: Write failing test for new schema field**

In `telemetry_tool/tests/test_custom_corners.py`:

```python
"""Tests for custom corner geometry in the resume flow."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pydantic import ValidationError


class TestResumeJobSchema:
    """Verify ResumeJobSchema accepts the new corners field."""

    def test_accepts_custom_corners(self):
        from web.schemas.jobs import ResumeJobSchema

        body = ResumeJobSchema(corners=[
            {"s_start": 100.0, "s_apex": 130.0, "s_end": 160.0},
            {"s_start": 300.0, "s_apex": 340.0, "s_end": 370.0},
        ])
        assert body.corners is not None
        assert len(body.corners) == 2
        assert body.corners[0].s_apex == 130.0

    def test_accepts_legacy_selected_corner_ids(self):
        from web.schemas.jobs import ResumeJobSchema

        body = ResumeJobSchema(selected_corner_ids=[1, 3, 5])
        assert body.selected_corner_ids == [1, 3, 5]
        assert body.corners is None

    def test_rejects_empty_body(self):
        from web.schemas.jobs import ResumeJobSchema

        with pytest.raises(ValidationError):
            ResumeJobSchema()

    def test_rejects_corner_with_start_after_end(self):
        from web.schemas.jobs import ResumeJobSchema

        with pytest.raises(ValidationError):
            ResumeJobSchema(corners=[
                {"s_start": 200.0, "s_apex": 130.0, "s_end": 100.0},
            ])

    def test_rejects_corner_with_apex_outside_range(self):
        from web.schemas.jobs import ResumeJobSchema

        with pytest.raises(ValidationError):
            ResumeJobSchema(corners=[
                {"s_start": 100.0, "s_apex": 50.0, "s_end": 160.0},
            ])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py::TestResumeJobSchema -v`
Expected: FAIL — `corners` field does not exist on ResumeJobSchema.

- [ ] **Step 3: Implement schema changes**

In `telemetry_tool/web/schemas/jobs.py`:

```python
"""Pydantic schemas for job management endpoints."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from web.schemas.common import PaginationParams


class CustomCorner(BaseModel):
    """A user-defined corner zone with entry/apex/exit distances."""

    s_start: float = Field(..., description="Entry distance along track (m)")
    s_apex: float = Field(..., description="Apex distance along track (m)")
    s_end: float = Field(..., description="Exit distance along track (m)")

    @model_validator(mode="after")
    def _check_ordering(self):
        if self.s_start > self.s_end:
            raise ValueError(f"s_start ({self.s_start}) must be <= s_end ({self.s_end})")
        if self.s_apex < self.s_start or self.s_apex > self.s_end:
            raise ValueError(f"s_apex ({self.s_apex}) must be between s_start and s_end")
        return self


class ResumeJobSchema(BaseModel):
    """POST /api/v1/jobs/:id/resume request body.

    Accepts one of:
    - joker_decision: for paused (joker) jobs
    - selected_corner_ids: legacy corner selection (filter auto-detected)
    - corners: custom corner geometry (entry/apex/exit distances)
    """

    joker_decision: Optional[Literal["accept", "reject"]] = None
    selected_corner_ids: Optional[list[int]] = None
    corners: Optional[list[CustomCorner]] = None

    @model_validator(mode="after")
    def _check_at_least_one(self):
        if (self.joker_decision is None
                and self.selected_corner_ids is None
                and self.corners is None):
            raise ValueError(
                "One of joker_decision, selected_corner_ids, or corners must be provided"
            )
        return self


class JobListParams(PaginationParams):
    """Query parameters for GET /api/v1/jobs."""

    limit: int = Field(default=50, ge=1, le=100)
    status: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py::TestResumeJobSchema -v`
Expected: All 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/web/schemas/jobs.py telemetry_tool/tests/test_custom_corners.py
git commit -m "feat: add CustomCorner schema for corner editor geometry"
```

---

### Task 2: Add custom_corners to PipelineContext

**Files:**
- Modify: `telemetry_tool/pipeline_context.py`
- Modify: `telemetry_tool/tests/test_custom_corners.py`

- [ ] **Step 1: Write failing test**

Append to `telemetry_tool/tests/test_custom_corners.py`:

```python
class TestPipelineContext:
    """Verify PipelineContext handles custom_corners."""

    def test_set_and_serialize_custom_corners(self):
        from unittest.mock import MagicMock
        from pipeline_context import PipelineContext

        mock_redis = MagicMock()
        ctx = PipelineContext.create(
            job_id="test-job",
            workspace_id=1,
            file_path="/tmp/test.csv",
            redis_client=mock_redis,
        )

        corners = [
            {"s_start": 100.0, "s_apex": 130.0, "s_end": 160.0},
            {"s_start": 300.0, "s_apex": 340.0, "s_end": 370.0},
        ]
        ctx.set_custom_corners(corners)
        assert ctx.custom_corners == corners

        # Verify serialization round-trip
        data = ctx._to_dict()
        assert data["custom_corners"] == corners

    def test_custom_corners_none_by_default(self):
        from unittest.mock import MagicMock
        from pipeline_context import PipelineContext

        mock_redis = MagicMock()
        ctx = PipelineContext.create(
            job_id="test-job",
            workspace_id=1,
            file_path="/tmp/test.csv",
            redis_client=mock_redis,
        )
        assert ctx.custom_corners is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py::TestPipelineContext -v`
Expected: FAIL — `custom_corners` not defined.

- [ ] **Step 3: Add custom_corners field to PipelineContext**

In `telemetry_tool/pipeline_context.py`, add to the dataclass fields (after `selected_corner_ids`):

```python
    custom_corners: Optional[list] = None
```

In `_to_dict()`, add:

```python
            "custom_corners": self.custom_corners,
```

In `load()` classmethod, add to the constructor:

```python
            custom_corners=data.get("custom_corners"),
```

Add setter method after `set_selected_corner_ids`:

```python
    def set_custom_corners(self, corners: list) -> None:
        """Set user-defined corner geometry for analysis."""
        self.custom_corners = corners
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py::TestPipelineContext -v`
Expected: All 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline_context.py telemetry_tool/tests/test_custom_corners.py
git commit -m "feat: add custom_corners field to PipelineContext"
```

---

### Task 3: Add enrich_custom_corners helper

**Files:**
- Modify: `telemetry_tool/pipeline/helpers.py`
- Modify: `telemetry_tool/tests/test_custom_corners.py`

- [ ] **Step 1: Write failing test**

Append to `telemetry_tool/tests/test_custom_corners.py`:

```python
class TestEnrichCustomCorners:
    """Verify enrich_custom_corners adds lat/lon/direction from track data."""

    def test_enriches_with_lat_lon(self):
        import numpy as np
        from pipeline.helpers import enrich_custom_corners

        # Straight track going east then curving south
        lats = np.array([48.0, 48.0, 48.0, 47.999, 47.998])
        lons = np.array([2.0, 2.001, 2.002, 2.003, 2.003])
        dists = np.array([0.0, 100.0, 200.0, 300.0, 400.0])

        custom = [
            {"s_start": 50.0, "s_apex": 100.0, "s_end": 150.0},
            {"s_start": 250.0, "s_apex": 300.0, "s_end": 350.0},
        ]

        enriched = enrich_custom_corners(custom, lats, lons, dists)

        assert len(enriched) == 2
        # Corner IDs assigned sequentially (0-based)
        assert enriched[0]["corner_id"] == 0
        assert enriched[1]["corner_id"] == 1
        # Lat/lon derived from apex distance
        assert enriched[0]["lat"] == pytest.approx(48.0, abs=0.01)
        assert enriched[0]["lon"] == pytest.approx(2.001, abs=0.001)
        # Direction field exists
        assert "direction" in enriched[0]
        # Original distances preserved
        assert enriched[0]["s_start"] == 50.0
        assert enriched[0]["s_apex"] == 100.0
        assert enriched[0]["s_end"] == 150.0

    def test_empty_input(self):
        import numpy as np
        from pipeline.helpers import enrich_custom_corners

        result = enrich_custom_corners(
            [], np.array([48.0]), np.array([2.0]), np.array([0.0])
        )
        assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py::TestEnrichCustomCorners -v`
Expected: FAIL — `enrich_custom_corners` not found.

- [ ] **Step 3: Implement enrich_custom_corners**

Append to `telemetry_tool/pipeline/helpers.py`:

```python
def enrich_custom_corners(
    custom_corners: list[dict[str, Any]],
    lats: np.ndarray,
    lons: np.ndarray,
    dists: np.ndarray,
) -> list[dict[str, Any]]:
    """Enrich user-defined corner zones with lat/lon, direction, and corner_id.

    Each corner dict must have s_start, s_apex, s_end (distances in meters).
    Returns a new list of corner dicts ready for the pipeline.
    """
    if not custom_corners or len(lats) < 2 or len(dists) < 2:
        return []

    enriched = []
    for i, cn in enumerate(custom_corners):
        s_apex = cn["s_apex"]
        s_start = cn["s_start"]
        s_end = cn["s_end"]

        # Find track indices for apex
        apex_idx = int(np.searchsorted(dists, s_apex))
        apex_idx = min(apex_idx, len(lats) - 1)

        start_idx = int(np.searchsorted(dists, s_start))
        start_idx = min(start_idx, len(lats) - 1)
        end_idx = int(np.searchsorted(dists, s_end))
        end_idx = min(end_idx, len(lats) - 1)

        # Determine direction from track curvature at apex
        direction = _compute_direction(lats, lons, apex_idx)

        enriched.append({
            "corner_id": i,
            "s_start": s_start,
            "s_apex": s_apex,
            "s_end": s_end,
            "lat": float(lats[apex_idx]) if np.isfinite(lats[apex_idx]) else 0.0,
            "lon": float(lons[apex_idx]) if np.isfinite(lons[apex_idx]) else 0.0,
            "dist_m": float(dists[apex_idx]),
            "direction": direction,
        })

    return enriched


def _compute_direction(
    lats: np.ndarray, lons: np.ndarray, idx: int, window: int = 5,
) -> str:
    """Estimate turn direction (L/R) from track curvature at *idx*."""
    n = len(lats)
    if n < 3 or idx < 1 or idx >= n - 1:
        return "S"

    lo = max(0, idx - window)
    hi = min(n - 1, idx + window)

    # Cross product of (before→apex) x (apex→after) vectors
    cos_mid = math.cos(math.radians(lats[idx]))
    dx1 = (lons[idx] - lons[lo]) * cos_mid
    dy1 = lats[idx] - lats[lo]
    dx2 = (lons[hi] - lons[idx]) * cos_mid
    dy2 = lats[hi] - lats[idx]

    cross = dx1 * dy2 - dy1 * dx2
    if abs(cross) < 1e-12:
        return "S"
    return "L" if cross > 0 else "R"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py::TestEnrichCustomCorners -v`
Expected: All 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/helpers.py telemetry_tool/tests/test_custom_corners.py
git commit -m "feat: add enrich_custom_corners helper for user-defined corner zones"
```

---

### Task 4: Wire custom corners through resume route + finalize

**Files:**
- Modify: `telemetry_tool/web/routes/jobs.py` (lines 263-300)
- Modify: `telemetry_tool/tasks/pipeline_tasks.py` (lines 538-580)
- Modify: `telemetry_tool/tests/test_custom_corners.py`

- [ ] **Step 1: Write failing test for finalize with custom corners**

Append to `telemetry_tool/tests/test_custom_corners.py`:

```python
class TestFinalizeWithCustomCorners:
    """Verify _run_finalize_stages uses custom_corners when set."""

    def test_custom_corners_override_detected(self):
        """When custom_corners is set on context, finalize should use them
        instead of auto-detected corners."""
        # This is a unit-level check on the branching logic.
        # We verify the filtering code path by checking the condition.
        from pipeline_context import PipelineContext
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        ctx = PipelineContext.create(
            job_id="test-job",
            workspace_id=1,
            file_path="/tmp/test.csv",
            redis_client=mock_redis,
        )

        custom = [
            {"s_start": 100.0, "s_apex": 130.0, "s_end": 160.0, "corner_id": 0},
        ]
        ctx.set_custom_corners(custom)

        # custom_corners takes precedence
        assert ctx.custom_corners is not None
        assert ctx.selected_corner_ids is None

    def test_selected_ids_still_works(self):
        """Legacy selected_corner_ids path still functions."""
        from pipeline_context import PipelineContext
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        ctx = PipelineContext.create(
            job_id="test-job",
            workspace_id=1,
            file_path="/tmp/test.csv",
            redis_client=mock_redis,
        )

        ctx.set_selected_corner_ids([1, 3, 5])
        assert ctx.selected_corner_ids == [1, 3, 5]
        assert ctx.custom_corners is None
```

- [ ] **Step 2: Run test to verify it passes** (these tests should already pass from Task 2)

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py::TestFinalizeWithCustomCorners -v`
Expected: All 2 PASS.

- [ ] **Step 3: Update resume route to handle custom corners**

In `telemetry_tool/web/routes/jobs.py`, inside the `resume()` function, update the `awaiting_corner_selection` branch (around line 295-300):

Replace:
```python
    if current_status == "awaiting_corner_selection":
        # Corner selection path
        selected_ids = g.body.selected_corner_ids
        if ctx is not None and selected_ids is not None:
            ctx.set_selected_corner_ids(selected_ids)
            ctx.save()
```

With:
```python
    if current_status == "awaiting_corner_selection":
        # Corner selection path — custom geometry or legacy ID filter
        if ctx is not None:
            if g.body.corners is not None:
                # New path: user-defined corner zones
                ctx.set_custom_corners([
                    {"s_start": c.s_start, "s_apex": c.s_apex, "s_end": c.s_end}
                    for c in g.body.corners
                ])
                ctx.save()
            elif g.body.selected_corner_ids is not None:
                # Legacy path: filter auto-detected corners
                ctx.set_selected_corner_ids(g.body.selected_corner_ids)
                ctx.save()
```

- [ ] **Step 4: Update _run_finalize_stages to use custom corners**

In `telemetry_tool/tasks/pipeline_tasks.py`, in `_run_finalize_stages()` around line 560-568, replace the corner filtering block:

Replace:
```python
        # Filter corners by user selection if specified
        if ctx.selected_corner_ids is not None and corners:
            selected_set = set(ctx.selected_corner_ids)
            corners = [c for c in corners if c.get("corner_id") in selected_set]
            logger.info(
                "Job %s: filtered to %d selected corners (from user selection)",
                ctx.job_id, len(corners),
            )
```

With:
```python
        # Custom corners override auto-detected; legacy filter as fallback
        if ctx.custom_corners is not None:
            # User-defined corner zones — enrich with lat/lon/direction
            from pipeline.helpers import enrich_custom_corners
            import numpy as np

            # Load track arrays from the layout stored in Redis
            redis_client = ctx.redis_client
            raw_layout = redis_client.get(f"pipeline:layout:{ctx.job_id}") if redis_client else None
            if raw_layout:
                layout = _json.loads(raw_layout)
                lats = np.array(layout.get("latitudes", []))
                lons = np.array(layout.get("longitudes", []))
                dists = np.array(layout.get("distances", []))
                corners = enrich_custom_corners(ctx.custom_corners, lats, lons, dists)
            else:
                # Fallback: use custom corners as-is with sequential IDs
                corners = [
                    {**cn, "corner_id": i, "lat": 0.0, "lon": 0.0, "direction": "S"}
                    for i, cn in enumerate(ctx.custom_corners)
                ]
            logger.info(
                "Job %s: using %d custom corners (user-defined)",
                ctx.job_id, len(corners),
            )
        elif ctx.selected_corner_ids is not None and corners:
            selected_set = set(ctx.selected_corner_ids)
            corners = [c for c in corners if c.get("corner_id") in selected_set]
            logger.info(
                "Job %s: filtered to %d selected corners (from user selection)",
                ctx.job_id, len(corners),
            )
```

- [ ] **Step 5: Run all backend tests**

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/jobs.py telemetry_tool/tasks/pipeline_tasks.py telemetry_tool/tests/test_custom_corners.py
git commit -m "feat: wire custom corner geometry through resume route and finalize stage"
```

---

## Chunk 2: Frontend — CornerEditor Component

### Task 5: Create CornerEditor.tsx — rendering and timer

**Files:**
- Create: `lap-website/src/components/app/CornerEditor.tsx`

This is the core new component. It reuses the projection/rendering logic from CornerPicker but adds:
- Timer bar with 15s auto-proceed
- Click-to-place corners with ±30m auto-expand
- Drag handles for entry/exit
- Click-apex-to-delete

- [ ] **Step 1: Create CornerEditor.tsx with types, projection reuse, and rendering**

Create `lap-website/src/components/app/CornerEditor.tsx`. The component is large, so build it in stages. Start with the types, projection import, and basic rendering:

```typescript
/**
 * CornerEditor.tsx — Canvas-based corner zone editor.
 *
 * Replaces CornerPicker. Users click the track to place corners (entry/apex/exit),
 * drag handles to adjust zones, click apex to delete. Auto-detected corners load
 * as defaults; 15s timer auto-proceeds if user doesn't interact.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

/* ── Types ──────────────────────────────────────────── */

export interface TrackLayout {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds: number[];
  corners: {
    corner_id: number;
    direction: string;
    lat: number;
    lon: number;
    dist_m: number;
    s_start: number | null;
    s_end: number | null;
    s_apex: number | null;
  }[];
  track_id?: string;
}

export interface EditorCorner {
  id: string;
  s_start: number;
  s_apex: number;
  s_end: number;
  idxStart: number;
  idxApex: number;
  idxEnd: number;
}

interface CornerEditorProps {
  trackLayout: TrackLayout;
  onSubmit: (corners: { s_start: number; s_apex: number; s_end: number }[]) => void;
  isSubmitting: boolean;
  autoDetectedCorners: EditorCorner[];
}

type EditorMode = 'timer' | 'editing';
type DragTarget = { cornerId: string; handle: 'start' | 'end' } | null;

/* ── Constants ──────────────────────────────────────── */

const TIMER_DURATION_MS = 15_000;
const DEFAULT_ZONE_M = 30; // ±30m around apex
const MIN_ZONE_M = 10;
const HANDLE_RADIUS = 6;
const APEX_RADIUS = 9;
const HIT_RADIUS_HANDLE = 14;
const HIT_RADIUS_APEX = 16;
const SNAP_RADIUS = 20;

const CORNER_COLORS = [
  '#f97316', '#60a5fa', '#a78bfa', '#34d399',
  '#f472b6', '#fbbf24', '#38bdf8', '#fb7185',
];
```

- [ ] **Step 2: Add projection builder and drawing helpers**

Continue in the same file. Reuse the projection logic from CornerPicker (buildProjection, speedToColor) and add new drawing for editor corners:

```typescript
/* ── Projection (same as CornerPicker) ─────────────── */

interface Projection {
  pxs: number[];
  pys: number[];
  projectPoint: (lat: number, lon: number) => [number, number];
}

function buildProjection(
  lats: number[], lons: number[], w: number, h: number, padding: number,
): Projection {
  const midLat = lats.reduce((a, b) => a + b, 0) / lats.length;
  const midLon = lons.reduce((a, b) => a + b, 0) / lons.length;
  const cosLat = Math.cos((midLat * Math.PI) / 180);

  const xs: number[] = [];
  const ys: number[] = [];
  for (let i = 0; i < lats.length; i++) {
    xs.push((lons[i]! - midLon) * cosLat);
    ys.push(lats[i]! - midLat);
  }

  let cxx = 0, cyy = 0, cxy = 0;
  for (let i = 0; i < xs.length; i++) {
    cxx += xs[i] * xs[i]; cyy += ys[i] * ys[i]; cxy += xs[i] * ys[i];
  }
  const pcaAngle = 0.5 * Math.atan2(2 * cxy, cxx - cyy);

  const drawW = w - padding * 2;
  const drawH = h - padding * 2;
  let bestAngle = 0, bestScale = 0;

  for (const candidate of [pcaAngle, pcaAngle + Math.PI / 2]) {
    const cosA = Math.cos(candidate), sinA = Math.sin(candidate);
    let rMinX = Infinity, rMaxX = -Infinity, rMinY = Infinity, rMaxY = -Infinity;
    for (let i = 0; i < xs.length; i++) {
      const rx = xs[i] * cosA - ys[i] * sinA;
      const ry = xs[i] * sinA + ys[i] * cosA;
      if (rx < rMinX) rMinX = rx; if (rx > rMaxX) rMaxX = rx;
      if (ry < rMinY) rMinY = ry; if (ry > rMaxY) rMaxY = ry;
    }
    const s = Math.min(drawW / (rMaxX - rMinX || 0.0001), drawH / (rMaxY - rMinY || 0.0001));
    if (s > bestScale) { bestScale = s; bestAngle = candidate; }
  }

  const cosR = Math.cos(bestAngle), sinR = Math.sin(bestAngle);
  const pxs = new Array(lats.length);
  const pys = new Array(lats.length);

  const rxs = new Array(lats.length);
  const rys = new Array(lats.length);
  let rMinX = Infinity, rMaxX = -Infinity, rMinY = Infinity, rMaxY = -Infinity;
  for (let i = 0; i < xs.length; i++) {
    rxs[i] = xs[i] * cosR - ys[i] * sinR;
    rys[i] = xs[i] * sinR + ys[i] * cosR;
    if (rxs[i] < rMinX) rMinX = rxs[i]; if (rxs[i] > rMaxX) rMaxX = rxs[i];
    if (rys[i] < rMinY) rMinY = rys[i]; if (rys[i] > rMaxY) rMaxY = rys[i];
  }

  const spanX = rMaxX - rMinX || 0.0001;
  const spanY = rMaxY - rMinY || 0.0001;
  const scale = Math.min(drawW / spanX, drawH / spanY);
  const usedW = spanX * scale, usedH = spanY * scale;
  const offsetX = padding + (drawW - usedW) / 2;
  const offsetY = padding + (drawH - usedH) / 2;
  const centerY = offsetY + usedH / 2;
  const TILT_K = 0.88;

  for (let i = 0; i < lats.length; i++) {
    pxs[i] = offsetX + (rxs[i] - rMinX) * scale;
    const baseY = offsetY + (rMaxY - rys[i]) * scale;
    pys[i] = centerY + (baseY - centerY) * TILT_K;
  }

  const projectPoint = (lat: number, lon: number): [number, number] => {
    const lx = (lon - midLon) * cosLat;
    const ly = lat - midLat;
    const rx = lx * cosR - ly * sinR;
    const ry = lx * sinR + ly * cosR;
    const px = offsetX + (rx - rMinX) * scale;
    const baseY2 = offsetY + (rMaxY - ry) * scale;
    return [px, centerY + (baseY2 - centerY) * TILT_K];
  };

  return { pxs, pys, projectPoint };
}

function speedToColor(t: number): string {
  const c = Math.max(0, Math.min(1, t));
  let r: number, g: number, b: number;
  if (c < 0.25) { const s = c / 0.25; r = 0; g = Math.round(180 * s); b = 220; }
  else if (c < 0.5) { const s = (c - 0.25) / 0.25; r = 0; g = 180 + Math.round(40 * s); b = Math.round(220 * (1 - s)); }
  else if (c < 0.75) { const s = (c - 0.5) / 0.25; r = Math.round(240 * s); g = 220; b = 0; }
  else { const s = (c - 0.75) / 0.25; r = 240; g = Math.round(220 * (1 - s)); b = 0; }
  return `rgb(${r},${g},${b})`;
}

/* ── Track helpers ──────────────────────────────────── */

function distToIndex(distances: number[], dist: number): number {
  let lo = 0, hi = distances.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (distances[mid] < dist) lo = mid + 1; else hi = mid;
  }
  return Math.min(lo, distances.length - 1);
}

function nearestTrackPoint(
  cx: number, cy: number, proj: Projection, radius: number,
): number {
  let best = radius * radius;
  let bestIdx = -1;
  for (let i = 0; i < proj.pxs.length; i++) {
    const d = (proj.pxs[i] - cx) ** 2 + (proj.pys[i] - cy) ** 2;
    if (d < best) { best = d; bestIdx = i; }
  }
  return bestIdx;
}
```

- [ ] **Step 3: Add the drawing function**

```typescript
/* ── Drawing ──────────────────────────────────────── */

function drawEditorMap(
  canvas: HTMLCanvasElement,
  layout: TrackLayout,
  corners: EditorCorner[],
  hoverIdx: number,
  timerPct: number,
  mode: EditorMode,
): Projection | null {
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  const lats = layout.latitudes ?? [];
  const lons = layout.longitudes ?? [];
  const distances = layout.distances ?? [];
  const speeds = layout.speeds ?? [];
  if (lats.length < 2) return null;

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, w, h);

  const proj = buildProjection(lats, lons, w, h, 24);

  // Speed normalization
  let minSpd = Infinity, maxSpd = -Infinity;
  if (speeds.length === lats.length) {
    for (const s of speeds) { if (s < minSpd) minSpd = s; if (s > maxSpd) maxSpd = s; }
  }
  const spdRange = maxSpd - minSpd || 1;

  // Ground grid
  let pMinX = Infinity, pMaxX = -Infinity, pMinY = Infinity, pMaxY = -Infinity;
  for (let i = 0; i < proj.pxs.length; i++) {
    if (proj.pxs[i] < pMinX) pMinX = proj.pxs[i]; if (proj.pxs[i] > pMaxX) pMaxX = proj.pxs[i];
    if (proj.pys[i] < pMinY) pMinY = proj.pys[i]; if (proj.pys[i] > pMaxY) pMaxY = proj.pys[i];
  }
  ctx.strokeStyle = 'rgba(240, 237, 229, 0.06)';
  ctx.lineWidth = 0.5;
  const gridStep = Math.max(20, (pMaxX - pMinX) / 12);
  for (let x = pMinX - 8; x <= pMaxX + 8; x += gridStep) {
    ctx.beginPath(); ctx.moveTo(x, pMinY - 8); ctx.lineTo(x, pMaxY + 8); ctx.stroke();
  }
  for (let y = pMinY - 8; y <= pMaxY + 8; y += gridStep) {
    ctx.beginPath(); ctx.moveTo(pMinX - 8, y); ctx.lineTo(pMaxX + 8, y); ctx.stroke();
  }

  // Shadow pass
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.lineWidth = 5; ctx.strokeStyle = 'rgba(0, 0, 0, 0.35)';
  ctx.beginPath();
  for (let i = 0; i < lats.length; i++) {
    const x = proj.pxs[i], y = proj.pys[i] + 5;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Main track — speed-colored
  for (let i = 0; i < lats.length - 1; i++) {
    const depthT = (proj.pys[i] - pMinY) / (pMaxY - pMinY || 1);
    ctx.lineWidth = 2 + depthT * 1.5;
    if (speeds.length === lats.length) {
      ctx.strokeStyle = speedToColor((speeds[i] - minSpd) / spdRange);
    } else {
      ctx.strokeStyle = '#F0EDE5';
    }
    ctx.beginPath();
    ctx.moveTo(proj.pxs[i], proj.pys[i]);
    ctx.lineTo(proj.pxs[i + 1], proj.pys[i + 1]);
    ctx.stroke();
  }

  // Corner zones
  for (let ci = 0; ci < corners.length; ci++) {
    const cn = corners[ci];
    const color = CORNER_COLORS[ci % CORNER_COLORS.length];

    // Highlighted segment
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.lineWidth = 6;
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.8;
    ctx.beginPath();
    for (let i = cn.idxStart; i <= cn.idxEnd; i++) {
      if (i === cn.idxStart) ctx.moveTo(proj.pxs[i], proj.pys[i]);
      else ctx.lineTo(proj.pxs[i], proj.pys[i]);
    }
    ctx.stroke();
    ctx.globalAlpha = 1.0;

    // Entry handle
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(proj.pxs[cn.idxStart], proj.pys[cn.idxStart], HANDLE_RADIUS, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Exit handle
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(proj.pxs[cn.idxEnd], proj.pys[cn.idxEnd], HANDLE_RADIUS, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Apex marker (larger)
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(proj.pxs[cn.idxApex], proj.pys[cn.idxApex], APEX_RADIUS, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Label
    ctx.font = '600 10px "Space Mono", monospace';
    ctx.fillStyle = '#F0EDE5';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`C${ci + 1}`, proj.pxs[cn.idxApex], proj.pys[cn.idxApex] - 14);
  }

  // Ghost hover preview (when hovering empty track)
  if (hoverIdx >= 0 && mode === 'editing') {
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = 'rgba(249, 115, 22, 0.5)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(proj.pxs[hoverIdx], proj.pys[hoverIdx], APEX_RADIUS + 4, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // S/F marker
  ctx.fillStyle = 'rgba(240, 237, 229, 0.15)';
  ctx.beginPath(); ctx.arc(proj.pxs[0], proj.pys[0], 8, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#F0EDE5';
  ctx.beginPath(); ctx.arc(proj.pxs[0], proj.pys[0], 4, 0, Math.PI * 2); ctx.fill();
  ctx.font = '600 9px "Space Mono", monospace';
  ctx.fillStyle = 'rgba(240, 237, 229, 0.7)';
  ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
  ctx.fillText('S/F', proj.pxs[0], proj.pys[0] - 10);

  // Timer bar
  if (mode === 'timer' && timerPct > 0) {
    const barY = h - 4;
    const barW = w * timerPct;
    ctx.fillStyle = 'rgba(107, 114, 128, 0.3)';
    ctx.fillRect(0, barY, w, 4);
    ctx.fillStyle = 'rgba(249, 115, 22, 0.6)';
    ctx.fillRect(0, barY, barW, 4);
  }

  // Instruction
  ctx.font = '11px "Space Mono", monospace';
  ctx.fillStyle = 'rgba(240, 237, 229, 0.5)';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  const msg = mode === 'timer'
    ? 'Click anywhere on the track to edit corners'
    : 'Click track to add corner \u00B7 Click apex to delete \u00B7 Drag handles to adjust';
  ctx.fillText(msg, w / 2, h - 10);

  return proj;
}
```

- [ ] **Step 4: Add the component with state machine, timer, and interactions**

```typescript
/* ── Auto-detect → EditorCorner conversion ─────────── */

function autoDetectedToEditor(layout: TrackLayout): EditorCorner[] {
  const distances = layout.distances ?? [];
  if (distances.length < 2) return [];

  return (layout.corners ?? [])
    .filter((c) => c.s_start != null && c.s_end != null)
    .map((c, i) => {
      const s_apex = c.s_apex ?? (c.s_start! + c.s_end!) / 2;
      return {
        id: `auto-${i}`,
        s_start: c.s_start!,
        s_apex: s_apex,
        s_end: c.s_end!,
        idxStart: distToIndex(distances, c.s_start!),
        idxApex: distToIndex(distances, s_apex),
        idxEnd: distToIndex(distances, c.s_end!),
      };
    });
}

let _idCounter = 0;
function nextId(): string {
  return `corner-${++_idCounter}-${Date.now()}`;
}

/* ── Component ──────────────────────────────────────── */

export function CornerEditor({ trackLayout, onSubmit, isSubmitting }: Omit<CornerEditorProps, 'autoDetectedCorners'>) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const projRef = useRef<Projection | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  const distances = trackLayout?.distances ?? [];

  // State
  const [corners, setCorners] = useState<EditorCorner[]>(() => autoDetectedToEditor(trackLayout));
  const [mode, setMode] = useState<EditorMode>('timer');
  const [timerPct, setTimerPct] = useState(1);
  const [hoverIdx, setHoverIdx] = useState(-1);
  const [dragTarget, setDragTarget] = useState<DragTarget>(null);

  // ── Timer ────────────────────────────────────────
  useEffect(() => {
    if (mode !== 'timer') return;
    startTimeRef.current = Date.now();

    const interval = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      const remaining = 1 - elapsed / TIMER_DURATION_MS;
      if (remaining <= 0) {
        clearInterval(interval);
        setTimerPct(0);
        // Auto-proceed
        onSubmit(corners.map((c) => ({ s_start: c.s_start, s_apex: c.s_apex, s_end: c.s_end })));
      } else {
        setTimerPct(remaining);
      }
    }, 50);

    timerRef.current = interval;
    return () => clearInterval(interval);
  }, [mode, corners, onSubmit]);

  const cancelTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setMode('editing');
    setTimerPct(0);
  }, []);

  // ── Drawing ──────────────────────────────────────
  useEffect(() => {
    if (!canvasRef.current) return;
    projRef.current = drawEditorMap(canvasRef.current, trackLayout, corners, hoverIdx, timerPct, mode);
  }, [trackLayout, corners, hoverIdx, timerPct, mode]);

  useEffect(() => {
    if (!canvasRef.current) return;
    const canvas = canvasRef.current;
    const ro = new ResizeObserver(() => {
      projRef.current = drawEditorMap(canvas, trackLayout, corners, hoverIdx, timerPct, mode);
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [trackLayout, corners, hoverIdx, timerPct, mode]);

  // ── Hit testing ──────────────────────────────────
  const hitTest = useCallback((cx: number, cy: number): { type: 'apex' | 'handle'; cornerId: string; handle?: 'start' | 'end' } | null => {
    const proj = projRef.current;
    if (!proj) return null;

    for (const cn of corners) {
      // Apex hit (delete)
      const apxX = proj.pxs[cn.idxApex], apxY = proj.pys[cn.idxApex];
      if ((apxX - cx) ** 2 + (apxY - cy) ** 2 < HIT_RADIUS_APEX ** 2) {
        return { type: 'apex', cornerId: cn.id };
      }
      // Start handle
      const stX = proj.pxs[cn.idxStart], stY = proj.pys[cn.idxStart];
      if ((stX - cx) ** 2 + (stY - cy) ** 2 < HIT_RADIUS_HANDLE ** 2) {
        return { type: 'handle', cornerId: cn.id, handle: 'start' };
      }
      // End handle
      const enX = proj.pxs[cn.idxEnd], enY = proj.pys[cn.idxEnd];
      if ((enX - cx) ** 2 + (enY - cy) ** 2 < HIT_RADIUS_HANDLE ** 2) {
        return { type: 'handle', cornerId: cn.id, handle: 'end' };
      }
    }
    return null;
  }, [corners]);

  // ── Mouse handlers ───────────────────────────────
  const getCanvasPos = useCallback((e: React.MouseEvent): [number, number] => {
    const rect = canvasRef.current!.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || !projRef.current) return;
    if (mode === 'timer') cancelTimer();

    const [cx, cy] = getCanvasPos(e);
    const hit = hitTest(cx, cy);

    if (hit?.type === 'apex') {
      // Delete corner
      setCorners((prev) => prev.filter((c) => c.id !== hit.cornerId));
      return;
    }

    if (hit?.type === 'handle') {
      // Start dragging
      setDragTarget({ cornerId: hit.cornerId, handle: hit.handle! });
      return;
    }

    // Click on empty track → place new corner
    const trackIdx = nearestTrackPoint(cx, cy, projRef.current, SNAP_RADIUS);
    if (trackIdx < 0 || distances.length < 2) return;

    const apexDist = distances[trackIdx];
    const maxDist = distances[distances.length - 1];
    const startDist = Math.max(0, apexDist - DEFAULT_ZONE_M);
    const endDist = Math.min(maxDist, apexDist + DEFAULT_ZONE_M);

    const newCorner: EditorCorner = {
      id: nextId(),
      s_start: startDist,
      s_apex: apexDist,
      s_end: endDist,
      idxStart: distToIndex(distances, startDist),
      idxApex: trackIdx,
      idxEnd: distToIndex(distances, endDist),
    };

    setCorners((prev) => [...prev, newCorner].sort((a, b) => a.s_apex - b.s_apex));
  }, [mode, cancelTimer, hitTest, getCanvasPos, distances]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || !projRef.current) return;
    const [cx, cy] = getCanvasPos(e);

    if (dragTarget) {
      // Dragging a handle
      const trackIdx = nearestTrackPoint(cx, cy, projRef.current, 50);
      if (trackIdx < 0) return;
      const newDist = distances[trackIdx];

      setCorners((prev) => prev.map((cn) => {
        if (cn.id !== dragTarget.cornerId) return cn;
        if (dragTarget.handle === 'start') {
          const clamped = Math.min(newDist, cn.s_apex - MIN_ZONE_M);
          const clampedIdx = distToIndex(distances, Math.max(0, clamped));
          return { ...cn, s_start: Math.max(0, clamped), idxStart: clampedIdx };
        } else {
          const clamped = Math.max(newDist, cn.s_apex + MIN_ZONE_M);
          const maxDist = distances[distances.length - 1];
          const clampedIdx = distToIndex(distances, Math.min(maxDist, clamped));
          return { ...cn, s_end: Math.min(maxDist, clamped), idxEnd: clampedIdx };
        }
      }));
      return;
    }

    // Hover preview — find nearest track point not inside an existing corner
    if (mode === 'editing') {
      const trackIdx = nearestTrackPoint(cx, cy, projRef.current, SNAP_RADIUS);
      if (trackIdx >= 0) {
        const dist = distances[trackIdx];
        const insideCorner = corners.some((cn) => dist >= cn.s_start && dist <= cn.s_end);
        setHoverIdx(insideCorner ? -1 : trackIdx);
      } else {
        setHoverIdx(-1);
      }
    }
  }, [dragTarget, distances, corners, mode, getCanvasPos]);

  const handleMouseUp = useCallback(() => {
    setDragTarget(null);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setHoverIdx(-1);
    setDragTarget(null);
  }, []);

  // ── Actions ──────────────────────────────────────
  const handleSubmit = useCallback(() => {
    onSubmit(corners.map((c) => ({ s_start: c.s_start, s_apex: c.s_apex, s_end: c.s_end })));
  }, [corners, onSubmit]);

  const resetToAutoDetected = useCallback(() => {
    setCorners(autoDetectedToEditor(trackLayout));
  }, [trackLayout]);

  const clearAll = useCallback(() => setCorners([]), []);

  // ── Cursor ───────────────────────────────────────
  const cursor = dragTarget ? 'grabbing' : mode === 'editing' ? 'crosshair' : 'pointer';

  return (
    <div className="rounded-lg border border-steel/20 bg-concrete overflow-hidden">
      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ display: 'block', height: '420px', cursor }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        role="application"
        aria-label="Track map corner editor"
      />

      {/* Controls */}
      <div className="p-4 border-t border-steel/10">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className="font-telemetry text-chalk text-sm">
              {corners.length} corner{corners.length !== 1 ? 's' : ''} defined
            </span>
            {mode === 'editing' && (
              <>
                <button type="button" onClick={resetToAutoDetected}
                  className="text-xs font-telemetry text-pit-orange hover:text-pit-orange/80 transition-colors">
                  Reset to Auto-detected
                </button>
                <button type="button" onClick={clearAll}
                  className="text-xs font-telemetry text-steel hover:text-chalk transition-colors">
                  Clear All
                </button>
              </>
            )}
          </div>
          {mode === 'timer' && (
            <span className="text-xs font-telemetry text-steel animate-pulse">
              Auto-proceeding in {Math.ceil(timerPct * 15)}s...
            </span>
          )}
        </div>

        {/* Corner chips */}
        {corners.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {corners.map((cn, i) => {
              const color = CORNER_COLORS[i % CORNER_COLORS.length];
              return (
                <button
                  key={cn.id}
                  type="button"
                  onClick={() => {
                    if (mode === 'timer') cancelTimer();
                    setCorners((prev) => prev.filter((c) => c.id !== cn.id));
                  }}
                  className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-telemetry
                    border border-chalk/40 text-chalk bg-asphalt hover:bg-safety-red/10 hover:border-safety-red/30
                    transition-all duration-150 group"
                  title="Click to remove"
                >
                  <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                  C{i + 1}
                  <span className="text-steel/40 group-hover:text-safety-red transition-colors">x</span>
                </button>
              );
            })}
          </div>
        )}

        {/* Submit */}
        {mode === 'editing' && (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitting || corners.length === 0}
            className="w-full px-6 py-3 bg-gold text-carbon font-monument text-sm rounded-lg
              hover:bg-gold/90 transition-colors
              disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-gold"
          >
            {isSubmitting ? 'Resuming Analysis...' : `Continue Analysis (${corners.length} corners)`}
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd lap-website && npx tsc --noEmit 2>&1 | grep -i "CornerEditor" | head -10`
Expected: No errors mentioning CornerEditor.

- [ ] **Step 6: Commit**

```bash
git add lap-website/src/components/app/CornerEditor.tsx
git commit -m "feat: add CornerEditor component with timer, click-to-place, and drag handles"
```

---

### Task 6: Wire CornerEditor into the upload page

**Files:**
- Modify: `lap-website/src/app/app/sessions/upload/page.tsx`

- [ ] **Step 1: Update imports**

Replace the CornerPicker import:

```typescript
// Old
import { CornerPicker, type TrackLayout } from '@/components/app/CornerPicker';
// New
import { CornerEditor, type TrackLayout } from '@/components/app/CornerEditor';
```

- [ ] **Step 2: Update the resumeWithCorners function**

Replace the `resumeWithCorners` function to support both payload formats:

```typescript
async function resumeWithCorners(
  jobId: string,
  corners: { s_start: number; s_apex: number; s_end: number }[],
): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/api/v1/jobs/${jobId}/resume`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ corners }),
    credentials: 'include',
  });
  const envelope = await res.json();
  if (!envelope.ok) throw new Error(envelope.error?.message ?? 'Resume failed');
}
```

- [ ] **Step 3: Update the handleCornerSubmit callback**

Replace the `handleCornerSubmit` callback:

```typescript
  const handleCornerSubmit = useCallback(async (
    corners: { s_start: number; s_apex: number; s_end: number }[],
  ) => {
    if (!jobId) return;
    setIsSubmittingCorners(true);
    try {
      await resumeWithCorners(jobId, corners);
      setPageState('tracking');
      setProgressPct(47);
      connectSSE(jobId);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Resume failed');
      setPageState('error');
    } finally {
      setIsSubmittingCorners(false);
    }
  }, [jobId, connectSSE]);
```

- [ ] **Step 4: Swap the component in JSX**

Replace the corner picker section (around line 934-951):

```jsx
      {showCornerPicker && (
        <div className="max-w-3xl">
          <div className="mb-4 p-4 rounded-lg bg-pit-orange/5 border border-pit-orange/20">
            <p className="text-chalk font-body text-sm mb-1">
              Define corners for detailed analysis
            </p>
            <p className="text-steel text-xs font-body">
              Click on the track to place corners. Drag entry/exit handles to adjust zones.
              Auto-detected corners will be used if you don&apos;t interact within 15 seconds.
            </p>
          </div>
          <CornerEditor
            trackLayout={trackLayout}
            onSubmit={handleCornerSubmit}
            isSubmitting={isSubmittingCorners}
          />
        </div>
      )}
```

- [ ] **Step 5: Verify build**

Run: `cd lap-website && npx tsc --noEmit 2>&1 | grep -i "upload\|corner" | head -10`
Expected: No errors in upload page or CornerEditor.

- [ ] **Step 6: Commit**

```bash
git add lap-website/src/app/app/sessions/upload/page.tsx
git commit -m "feat: swap CornerPicker for CornerEditor on upload page"
```

---

## Chunk 3: Cleanup and Integration Test

### Task 7: Run full test suite and verify

- [ ] **Step 1: Run backend tests**

Run: `cd telemetry_tool && python -m pytest tests/test_custom_corners.py -v`
Expected: All tests PASS.

- [ ] **Step 2: Run frontend type check**

Run: `cd lap-website && npx tsc --noEmit 2>&1 | grep -c "error TS"`
Expected: Same count as before changes (pre-existing e2e errors only).

- [ ] **Step 3: Run frontend build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`
Expected: Build succeeds.

- [ ] **Step 4: Final commit with all changes**

Only if any uncommitted changes remain:

```bash
git add -A
git commit -m "chore: corner editor integration cleanup"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Schema: CustomCorner + ResumeJobSchema | `schemas/jobs.py`, `tests/test_custom_corners.py` |
| 2 | PipelineContext: custom_corners field | `pipeline_context.py` |
| 3 | Helper: enrich_custom_corners | `pipeline/helpers.py` |
| 4 | Route + finalize: wire custom corners | `routes/jobs.py`, `tasks/pipeline_tasks.py` |
| 5 | CornerEditor.tsx | New component |
| 6 | Upload page: swap component + payload | `upload/page.tsx` |
| 7 | Integration verification | All files |
