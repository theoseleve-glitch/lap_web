# Corner Detection & Coaching System Rebuild — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace broken corner detection with a track decomposition engine that classifies every track section, detects MRP, analyzes understeer/oversteer with causal chains, and coaches through dual basic/advanced engines — with user-defined corner selection as an alternative input.

**Architecture:** Hybrid rebuild — new decomposition + classification + MRP + handling detection + dual coaching engines. Reuse existing `corner_analysis.py` physics (time-loss decomposition, grip utilisation, ranking) and `coaching_engine.py` narrative synthesis. Replace `corner_detection.py` entirely.

**Tech Stack:** Python 3.14, NumPy, Pandas, dataclasses. Frontend: React/TypeScript canvas components. Flask API endpoints. SQLite/PostgreSQL schema.

**Design doc:** `docs/plans/2026-03-10-corner-coaching-rebuild-design.md`

---

## Phase 1: Track Decomposition Engine

### Task 1: Corner Focus Scorer

**Files:**
- Create: `telemetry_tool/corner_focus.py`
- Test: `telemetry_tool/tests/test_corner_focus.py`

**Step 1: Write the failing test**

```python
"""Tests for corner exit importance scoring."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from corner_focus import score_exit_importance


def test_long_straight_high_importance():
    """Corner followed by 400m straight → high exit importance."""
    assert score_exit_importance(400.0) > 0.8


def test_short_straight_low_importance():
    """Corner followed by 30m before next corner → low exit importance."""
    assert score_exit_importance(30.0) < 0.3


def test_no_straight_zero():
    """Corner immediately followed by another → near zero."""
    assert score_exit_importance(0.0) == pytest.approx(0.0, abs=0.05)


def test_medium_straight():
    """150m straight → moderate importance."""
    result = score_exit_importance(150.0)
    assert 0.4 < result < 0.7


def test_monotonic():
    """Longer straights always produce higher scores."""
    prev = 0.0
    for dist in [0, 50, 100, 200, 400, 800]:
        score = score_exit_importance(float(dist))
        assert score >= prev
        prev = score


def test_capped_at_one():
    """Score never exceeds 1.0."""
    assert score_exit_importance(2000.0) <= 1.0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_corner_focus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'corner_focus'`

**Step 3: Write minimal implementation**

```python
"""Corner exit importance scoring.

Scores how important a corner's exit speed is based on the length of the
straight that follows.  Longer straight → more time gained/lost from exit
speed differences → higher importance (0.0 to 1.0).

Uses a saturating curve: importance = 1 - exp(-straight_length / scale).
Scale of 200m means a 200m straight gives ~63% importance, 400m gives ~86%.
"""
from __future__ import annotations

_SCALE_M = 200.0  # characteristic length — tune based on typical circuits


def score_exit_importance(straight_length_m: float) -> float:
    """Return exit importance score 0.0–1.0 for a given following straight length."""
    import math
    if straight_length_m <= 0:
        return 0.0
    return min(1.0, 1.0 - math.exp(-straight_length_m / _SCALE_M))
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_corner_focus.py -v`
Expected: 6 passed

**Step 5: Commit**

```bash
git add telemetry_tool/corner_focus.py telemetry_tool/tests/test_corner_focus.py
git commit -m "feat: add corner exit importance scorer"
```

---

### Task 2: Corner Classifier

**Files:**
- Create: `telemetry_tool/corner_classifier.py`
- Test: `telemetry_tool/tests/test_corner_classifier.py`

**Step 1: Write the failing test**

```python
"""Tests for geometry + speed corner classification."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from corner_classifier import classify_corner, CornerClassification


def _make_curvature(length_m, peak_curvature, n_points=100):
    """Generate a single-peak curvature profile."""
    s = np.linspace(0, length_m, n_points)
    curv = peak_curvature * np.exp(-0.5 * ((s - length_m / 2) / (length_m / 6)) ** 2)
    return s, curv


def test_kink():
    """Short, low curvature, minimal speed drop → kink."""
    s, curv = _make_curvature(30.0, 0.005)
    speeds = np.full_like(s, 30.0)  # barely slows down
    speeds[len(s)//2] = 28.0  # 6% drop
    result = classify_corner(s, curv, speeds, direction_changes=0, directions=["L"])
    assert result.corner_type == "kink"


def test_hairpin():
    """Tight radius, large direction change → hairpin."""
    s, curv = _make_curvature(60.0, 0.06)  # radius ~17m
    speeds = np.linspace(25, 8, len(s))  # heavy braking
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["R"], total_heading_change=140.0)
    assert result.corner_type == "hairpin"


def test_fast_sweeper():
    """Long, moderate curvature, high min speed → fast sweeper."""
    s, curv = _make_curvature(120.0, 0.008)
    straight_speed = 40.0
    speeds = np.full_like(s, straight_speed * 0.8)  # 80% of straight speed
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["L"], straight_speed_mps=straight_speed)
    assert result.corner_type == "fast_sweeper"


def test_simple_corner():
    """Standard single-peak corner."""
    s, curv = _make_curvature(80.0, 0.025)
    speeds = np.linspace(30, 18, len(s))
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["R"], total_heading_change=80.0)
    assert result.corner_type == "simple"


def test_chicane():
    """Multiple peaks, alternating directions → chicane."""
    s = np.linspace(0, 100, 200)
    curv = 0.02 * (np.exp(-((s - 30) / 8) ** 2) + np.exp(-((s - 70) / 8) ** 2))
    speeds = np.full_like(s, 20.0)
    result = classify_corner(s, curv, speeds, direction_changes=1,
                             directions=["L", "R"], n_peaks=2)
    assert result.corner_type == "chicane"


def test_double_apex():
    """Two peaks, same direction → double apex."""
    s = np.linspace(0, 100, 200)
    curv = 0.02 * (np.exp(-((s - 30) / 8) ** 2) + np.exp(-((s - 70) / 8) ** 2))
    speeds = np.full_like(s, 20.0)
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["L", "L"], n_peaks=2)
    assert result.corner_type == "double_apex"


def test_compound():
    """Multiple peaks, mixed directions but not simple chicane → compound."""
    s = np.linspace(0, 150, 300)
    curv = 0.015 * (np.exp(-((s - 30) / 8) ** 2) +
                    np.exp(-((s - 70) / 8) ** 2) +
                    np.exp(-((s - 110) / 8) ** 2))
    speeds = np.full_like(s, 18.0)
    result = classify_corner(s, curv, speeds, direction_changes=2,
                             directions=["L", "R", "L"], n_peaks=3)
    assert result.corner_type == "compound"


def test_decreasing_radius():
    """Curvature increases through corner → decreasing radius."""
    s = np.linspace(0, 80, 100)
    curv = 0.01 + 0.02 * (s / 80)  # increases linearly
    speeds = np.linspace(25, 15, 100)
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["R"], total_heading_change=70.0)
    assert result.corner_type == "decreasing_radius"


def test_classification_has_all_fields():
    """Output has all required fields."""
    s, curv = _make_curvature(80.0, 0.025)
    speeds = np.linspace(30, 18, len(s))
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["R"], total_heading_change=80.0)
    assert hasattr(result, "corner_type")
    assert hasattr(result, "min_radius_m")
    assert hasattr(result, "arc_length_m")
    assert hasattr(result, "speed_ratio")
    assert hasattr(result, "confidence")
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_corner_classifier.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
"""Corner classification using geometry + speed context.

Classifies corners into types: kink, fast_sweeper, simple, hairpin,
double_apex, compound, chicane, decreasing_radius, increasing_radius.

Uses curvature profile shape, arc length, speed ratio (min corner speed
vs straight speed), direction changes, and heading change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class CornerClassification:
    """Result of corner type classification."""
    corner_type: str        # "kink" | "fast_sweeper" | "simple" | "hairpin" | etc.
    min_radius_m: float     # minimum radius (1 / max curvature)
    arc_length_m: float     # total corner length
    speed_ratio: float      # min_speed / straight_speed (0-1)
    confidence: float       # classification confidence (0-1)


# Thresholds (tunable)
_KINK_MAX_LENGTH_M = 40.0
_KINK_MAX_SPEED_DROP = 0.10      # <10% speed drop
_SWEEPER_MIN_LENGTH_M = 80.0
_SWEEPER_MIN_SPEED_RATIO = 0.70  # >70% of straight speed
_HAIRPIN_MAX_RADIUS_M = 25.0
_HAIRPIN_MIN_HEADING_DEG = 120.0
_DECREASING_RADIUS_SLOPE_THRESHOLD = 0.3  # normalized curvature slope


def classify_corner(
    distances: np.ndarray,
    curvatures: np.ndarray,
    speeds: np.ndarray,
    *,
    direction_changes: int = 0,
    directions: Optional[list[str]] = None,
    n_peaks: int = 1,
    total_heading_change: float = 0.0,
    straight_speed_mps: Optional[float] = None,
) -> CornerClassification:
    """Classify a corner segment by its geometry and speed profile.

    Parameters
    ----------
    distances : array of distance values along the corner
    curvatures : array of curvature values (1/radius)
    speeds : array of speed values (m/s)
    direction_changes : number of L→R or R→L transitions
    directions : list of directions per curvature peak ("L"/"R")
    n_peaks : number of distinct curvature peaks
    total_heading_change : total heading change in degrees
    straight_speed_mps : typical straight speed for speed ratio calculation
    """
    arc_length = float(distances[-1] - distances[0])
    max_curv = float(np.max(np.abs(curvatures)))
    min_radius = 1.0 / max_curv if max_curv > 1e-6 else 9999.0
    min_speed = float(np.min(speeds))
    max_speed = float(np.max(speeds))

    if straight_speed_mps is not None and straight_speed_mps > 0:
        speed_ratio = min_speed / straight_speed_mps
    else:
        speed_ratio = min_speed / max_speed if max_speed > 0 else 1.0

    directions = directions or []
    confidence = 0.8  # default

    # Multi-peak classification first
    if n_peaks >= 2:
        if direction_changes >= 1 and len(set(directions)) > 1:
            corner_type = "chicane"
            confidence = 0.85
        elif direction_changes == 0 and len(set(directions)) == 1:
            corner_type = "double_apex"
            confidence = 0.80
        else:
            corner_type = "compound"
            confidence = 0.75
    # Single-peak classification
    elif arc_length < _KINK_MAX_LENGTH_M and (1.0 - speed_ratio) < _KINK_MAX_SPEED_DROP:
        corner_type = "kink"
        confidence = 0.85
    elif total_heading_change >= _HAIRPIN_MIN_HEADING_DEG and min_radius < _HAIRPIN_MAX_RADIUS_M:
        corner_type = "hairpin"
        confidence = 0.90
    elif arc_length >= _SWEEPER_MIN_LENGTH_M and speed_ratio >= _SWEEPER_MIN_SPEED_RATIO:
        corner_type = "fast_sweeper"
        confidence = 0.80
    else:
        # Check for decreasing/increasing radius
        n = len(curvatures)
        if n >= 10:
            first_half_mean = float(np.mean(np.abs(curvatures[:n // 2])))
            second_half_mean = float(np.mean(np.abs(curvatures[n // 2:])))
            total_mean = (first_half_mean + second_half_mean) / 2
            if total_mean > 1e-6:
                ratio = (second_half_mean - first_half_mean) / total_mean
                if ratio > _DECREASING_RADIUS_SLOPE_THRESHOLD:
                    corner_type = "decreasing_radius"
                    confidence = 0.70
                elif ratio < -_DECREASING_RADIUS_SLOPE_THRESHOLD:
                    corner_type = "increasing_radius"
                    confidence = 0.70
                else:
                    corner_type = "simple"
                    confidence = 0.85
            else:
                corner_type = "simple"
                confidence = 0.85
        else:
            corner_type = "simple"
            confidence = 0.85

    return CornerClassification(
        corner_type=corner_type,
        min_radius_m=min_radius,
        arc_length_m=arc_length,
        speed_ratio=speed_ratio,
        confidence=confidence,
    )
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_corner_classifier.py -v`
Expected: 10 passed

**Step 5: Commit**

```bash
git add telemetry_tool/corner_classifier.py telemetry_tool/tests/test_corner_classifier.py
git commit -m "feat: add geometry + speed corner classifier"
```

---

### Task 3: Track Decomposition Engine

**Files:**
- Create: `telemetry_tool/track_decomposition.py`
- Test: `telemetry_tool/tests/test_track_decomposition.py`

This is the core module that replaces `corner_detection.py`. It segments the track into typed sections.

**Step 1: Write the failing test**

```python
"""Tests for track decomposition engine."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest
from track_decomposition import decompose_track, TrackSection


def _make_oval_trace(n_points=400, straight_length=200.0, radius=50.0):
    """Generate a simple oval track with two straights and two corners."""
    points = []
    # Straight 1 (heading east)
    for x in np.linspace(0, straight_length, n_points // 4):
        points.append((x, 0.0))
    # Corner 1 (right turn, semicircle south)
    cx, cy = straight_length, radius
    for a in np.linspace(-np.pi / 2, np.pi / 2, n_points // 4):
        points.append((cx + radius * np.cos(a), cy + radius * np.sin(a)))
    # Straight 2 (heading west)
    for x in np.linspace(straight_length, 0, n_points // 4):
        points.append((x, 2 * radius))
    # Corner 2 (right turn, semicircle north)
    cx2, cy2 = 0, radius
    for a in np.linspace(np.pi / 2, 3 * np.pi / 2, n_points // 4):
        points.append((cx2 + radius * np.cos(a), cy2 + radius * np.sin(a)))

    xs, ys = zip(*points)
    xs, ys = np.array(xs), np.array(ys)
    dists = np.concatenate([[0], np.cumsum(np.sqrt(np.diff(xs)**2 + np.diff(ys)**2))])

    # Speed: fast on straights, slow in corners
    speeds = np.full(len(xs), 30.0)
    q = n_points // 4
    speeds[q:2*q] = 15.0   # corner 1
    speeds[3*q:] = 15.0     # corner 2

    df = pd.DataFrame({
        "Latitude": ys * 0.00001,   # fake GPS
        "Longitude": xs * 0.00001,
        "Speed (m/s)": speeds,
        "Distance (m)": dists,
    })
    return df


def test_oval_produces_4_sections():
    """An oval track should decompose into ~4 sections: 2 straights + 2 corners."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    corners = [s for s in sections if s.section_type == "corner"]
    straights = [s for s in sections if s.section_type == "straight"]
    assert len(corners) == 2, f"Expected 2 corners, got {len(corners)}"
    assert len(straights) >= 1, "Expected at least 1 straight"


def test_sections_cover_full_track():
    """All sections together should cover the full track distance."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    total_covered = sum(s.s_end - s.s_start for s in sections)
    track_length = df["Distance (m)"].iloc[-1]
    assert total_covered == pytest.approx(track_length, rel=0.05)


def test_sections_are_ordered():
    """Sections should be in distance order with no gaps."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    for i in range(1, len(sections)):
        assert sections[i].s_start >= sections[i - 1].s_start


def test_corners_have_type():
    """Corner sections should have a corner_type assigned."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    corners = [s for s in sections if s.section_type == "corner"]
    for c in corners:
        assert c.corner_type is not None
        assert c.corner_type != ""


def test_corners_have_direction():
    """Corner sections should have L or R direction."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    corners = [s for s in sections if s.section_type == "corner"]
    for c in corners:
        assert c.direction in ("L", "R")


def test_sections_have_exit_importance():
    """All sections should have exit_importance scored."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    for s in sections:
        assert 0.0 <= s.exit_importance <= 1.0


def test_empty_df_returns_empty():
    """Empty DataFrame returns no sections."""
    df = pd.DataFrame(columns=["Latitude", "Longitude", "Speed (m/s)", "Distance (m)"])
    sections = decompose_track(df)
    assert sections == []


def test_section_ids_sequential():
    """Section IDs should be sequential starting from 1."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    for i, s in enumerate(sections):
        assert s.section_id == i + 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_track_decomposition.py -v`
Expected: FAIL

**Step 3: Write implementation**

The implementation should:
1. Compute curvature from GPS coordinates (reuse smoothing approach from `corner_detection.py`)
2. Classify each point as straight/corner/transition based on curvature threshold
3. Merge adjacent same-type segments, merge close corners into compounds
4. For each corner segment: compute direction, count peaks, detect direction changes
5. Call `corner_classifier.classify_corner()` for typing
6. Call `corner_focus.score_exit_importance()` using distance to next corner
7. Assign geometric apex (point of max curvature within segment)

Key functions to implement:
- `decompose_track(df: pd.DataFrame, **kwargs) -> list[TrackSection]` — main entry point
- `_compute_curvature(lats, lons, distances) -> np.ndarray` — GPS to curvature
- `_segment_by_curvature(distances, curvatures, speeds, threshold) -> list[RawSegment]` — initial segmentation
- `_merge_close_corners(segments, merge_gap_m) -> list[RawSegment]` — group nearby corners
- `_classify_segments(segments, curvatures, speeds, distances) -> list[TrackSection]` — apply classifier + focus

The `TrackSection` dataclass:
```python
@dataclass
class TrackSection:
    section_id: int
    section_type: str          # "straight" | "corner" | "transition"
    corner_type: str | None
    s_start: float
    s_end: float
    direction: str | None      # "L" | "R" | None
    geometric_apex: float | None
    exit_importance: float
    sub_corners: list[dict] | None

    def to_dict(self) -> dict: ...
```

**Step 4: Run tests**

Run: `python -m pytest telemetry_tool/tests/test_track_decomposition.py -v`
Expected: 8 passed

**Step 5: Commit**

```bash
git add telemetry_tool/track_decomposition.py telemetry_tool/tests/test_track_decomposition.py
git commit -m "feat: add track decomposition engine with section classification"
```

---

## Phase 2: MRP + Handling Detection

### Task 4: MRP Detector

**Files:**
- Create: `telemetry_tool/mrp_detector.py`
- Test: `telemetry_tool/tests/test_mrp_detector.py`

**Step 1: Write the failing test**

Tests should cover:
- MRP found at peak yaw rate point
- MRP found at min speed when yaw rate unavailable
- MRP falls within corner boundaries
- MRP with steering angle confirmation (rich data)
- `mrp_apex_delta_m` computed correctly
- Full `CornerEvents` timeline populated
- Events in correct distance order

Key test cases:
```python
def test_mrp_at_peak_yaw_rate():
    """MRP should be at the point of maximum yaw rate."""

def test_mrp_fallback_to_min_speed():
    """When yaw rate unavailable, MRP falls back to minimum speed point."""

def test_mrp_clamped_to_corner():
    """MRP must fall between s_start and s_end."""

def test_corner_events_ordered():
    """Events timeline: brake < turn_in < mrp < throttle < track_out."""

def test_mrp_apex_delta():
    """mrp_apex_delta_m = mrp_m - geometric_apex_m."""

def test_brake_point_detected():
    """Brake initiation found where accel_long drops below -1.0."""

def test_throttle_application_detected():
    """Throttle onset found where accel_long rises above +0.5."""
```

**Step 3: Write implementation**

Core logic:
1. For each `TrackSection` with type "corner", extract the lap data slice from `s_start - _SEARCH_MARGIN_M` to `s_end + margin`
2. Compute yaw rate from heading changes (or use existing `yaw_rate` column if available)
3. Find peak yaw rate within [s_start, s_end] → MRP candidate
4. Find min speed within [s_start, s_end] → speed-based MRP candidate
5. If both within 5m, average them. If not, use yaw rate peak.
6. If steering angle available, confirm with peak steering.
7. Detect brake initiation, turn-in, trail-brake end, throttle application, track-out using acceleration thresholds from `corner_analysis.py` constants.

**Step 5: Commit**

```bash
git add telemetry_tool/mrp_detector.py telemetry_tool/tests/test_mrp_detector.py
git commit -m "feat: add MRP detector with corner event timeline"
```

---

### Task 5: Handling Detector (Understeer/Oversteer)

**Files:**
- Create: `telemetry_tool/handling_detector.py`
- Test: `telemetry_tool/tests/test_handling_detector.py`

**Step 1: Write the failing test**

Tests should cover:
- Understeer detected when actual yaw < expected yaw
- Oversteer detected when actual yaw > expected yaw
- Severity classification (mild/moderate/severe)
- Duration measurement
- Causal attribution: throttle-induced understeer
- Causal attribution: trail-brake oversteer
- Causal attribution: power oversteer
- No events on clean corner
- Advanced mode: steering vs radius divergence
- Time cost estimation

Key test approach: create synthetic corner data with known yaw rate deviations.

**Step 3: Write implementation**

Two classes:
- `BasicHandlingDetector` — GPS-only, uses expected vs actual yaw rate
- `AdvancedHandlingDetector(BasicHandlingDetector)` — adds steering/brake/RPM analysis

Core algorithm:
1. Compute expected yaw rate from reference curvature × speed at each point
2. Compute actual yaw rate from heading change / dt
3. Ratio = actual / expected. < 0.85 → understeer, > 1.15 → oversteer
4. Group contiguous violations into `HandlingEvent` spans
5. For each span, check concurrent driver inputs for causal attribution
6. Estimate time cost from speed deviation integrated over the span

**Step 5: Commit**

```bash
git add telemetry_tool/handling_detector.py telemetry_tool/tests/test_handling_detector.py
git commit -m "feat: add understeer/oversteer detector with causal chains"
```

---

## Phase 3: Dual Coaching Engines

### Task 6: Basic Coaching Engine (GPS-only)

**Files:**
- Create: `telemetry_tool/coaching_basic.py`
- Test: `telemetry_tool/tests/test_coaching_basic.py`

**Step 1: Write the failing test**

Tests should cover:
- Coaching generated for straight sections (top speed, braking zone)
- Coaching for corner sections (braking point, entry/apex/exit speeds, line)
- Corner focus note included when exit_importance > 0.5
- Optimal brake point compared to actual
- Time loss breakdown populated
- Coaching hints priority-ordered by time impact
- `primary_focus` is the highest-impact advice

**Step 3: Write implementation**

Reuses from `corner_analysis.py`:
- `CornerPerformance` time-loss decomposition logic
- Grip utilisation calculation
- `rank_improvement_opportunities()` for priority ordering

New logic:
- Straight section coaching: "You reached Xkm/h vs theoretical Ykm/h — lost Z.Zs"
- Corner focus notes: "Exit is critical — 380m straight follows. Prioritize exit speed."
- Braking analysis: brake point delta, braking trace shape vs G-G optimal
- Optimal line from exit-priority optimization

Output: `list[SectionCoaching]`

**Step 5: Commit**

```bash
git add telemetry_tool/coaching_basic.py telemetry_tool/tests/test_coaching_basic.py
git commit -m "feat: add GPS-only basic coaching engine"
```

---

### Task 7: Advanced Coaching Engine (Rich Data)

**Files:**
- Create: `telemetry_tool/coaching_advanced.py`
- Test: `telemetry_tool/tests/test_coaching_advanced.py`

**Step 1: Write the failing test**

Tests should cover:
- All basic coaching present
- Handling events integrated into coaching hints
- Throttle timing advice when throttle data available
- Steering quality advice when steering data available
- Gear selection advice when RPM/gear data available
- Graceful degradation when only some advanced channels present
- Channel tier detection works correctly

**Step 3: Write implementation**

Extends basic engine output with:
- `handling_summary` from `HandlingEvent` list
- `throttle_advice` — throttle application point vs optimal, progression rate
- `steering_advice` — smoothness, correction count, turn-in rate
- `gear_advice` — actual vs optimal gear, RPM range assessment
- `brake_pressure_advice` — modulation quality, trail-brake effectiveness

Also includes the channel tier detector:
```python
def get_coaching_tier(available_columns: set[str]) -> str:
    ADVANCED = {"Steering", "Brake", "Throttle", "RPM", "Gear"}
    if len(ADVANCED & available_columns) >= 3:
        return "advanced"
    return "basic"
```

**Step 5: Commit**

```bash
git add telemetry_tool/coaching_advanced.py telemetry_tool/tests/test_coaching_advanced.py
git commit -m "feat: add rich-data advanced coaching engine"
```

---

## Phase 4: Pipeline Integration + Schema

### Task 8: Database Schema Migration

**Files:**
- Create: `telemetry_tool/alembic/versions/017_corner_coaching_v2.py`
- Modify: `telemetry_tool/db/schema.py` (add new columns + table)

**Step 1: Write the Alembic migration**

Add columns to `corner_metrics`:
- `corner_type TEXT`
- `section_type TEXT`
- `mrp_distance_m REAL`
- `mrp_speed_mps REAL`
- `mrp_yaw_rate REAL`
- `geometric_apex_m REAL`
- `exit_importance REAL`
- `handling_events_json TEXT`
- `is_user_defined INTEGER DEFAULT 0`

Create `user_corners` table:
```sql
CREATE TABLE IF NOT EXISTS user_corners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    corner_index INTEGER NOT NULL,
    lat_entry REAL, lon_entry REAL,
    lat_apex REAL, lon_apex REAL,
    lat_exit REAL, lon_exit REAL,
    s_entry REAL, s_apex REAL, s_exit REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, corner_index)
);
```

**Step 2: Update SQLite schema**

Add matching columns/table to `db/schema.py` Phase 7 or new Phase 8.

**Step 3: Test migration**

Run: `python -c "from db.migrate import ensure_schema; import sqlite3; c=sqlite3.connect(':memory:'); ensure_schema(c); print('OK')"`
Expected: OK

**Step 5: Commit**

```bash
git add telemetry_tool/alembic/versions/017_corner_coaching_v2.py telemetry_tool/db/schema.py
git commit -m "feat: add schema migration for corner coaching v2"
```

---

### Task 9: Pipeline Stage Integration

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s10b_corners.py`
- Modify: `telemetry_tool/corner_persistence.py`

**Step 1: Modify s10b_corners.py**

Replace the existing corner detection call with track decomposition:

```python
# OLD: corners = detect_corners(best_lap_df, ...)
# NEW:
from track_decomposition import decompose_track
from mrp_detector import detect_all_mrp
from handling_detector import BasicHandlingDetector, AdvancedHandlingDetector
from coaching_basic import generate_basic_coaching
from coaching_advanced import generate_advanced_coaching, get_coaching_tier

def run_track_decomposition(best_lap_df, **kwargs):
    """Step 10c: Decompose track into typed sections."""
    return decompose_track(best_lap_df, **kwargs)

def run_mrp_detection(sections, best_lap_df, resampled_laps, **kwargs):
    """Step 10c2: Detect MRP + events for each corner section."""
    return detect_all_mrp(sections, best_lap_df, resampled_laps, **kwargs)

def run_handling_analysis(sections, events, best_lap_df, available_columns, **kwargs):
    """Step 10c3: Detect understeer/oversteer with causal chains."""
    tier = get_coaching_tier(available_columns)
    if tier == "advanced":
        detector = AdvancedHandlingDetector()
    else:
        detector = BasicHandlingDetector()
    return detector.analyze_all(sections, events, best_lap_df, **kwargs)

def run_coaching(sections, events, handling, best_lap_df, theoretical, friction, available_columns, **kwargs):
    """Step 10d: Generate coaching for all sections."""
    tier = get_coaching_tier(available_columns)
    if tier == "advanced":
        return generate_advanced_coaching(sections, events, handling, best_lap_df, theoretical, friction, **kwargs)
    return generate_basic_coaching(sections, events, handling, best_lap_df, theoretical, friction, **kwargs)
```

Check for user-defined corners before running autonomous:
```python
def run_corner_pipeline(conn, session_id, best_lap_df, ...):
    # Check for user-defined corners
    user_corners = conn.execute(
        "SELECT * FROM user_corners WHERE session_id = :sid ORDER BY corner_index",
        {"sid": session_id}
    ).fetchall()

    if user_corners:
        sections = _user_corners_to_sections(user_corners, best_lap_df)
    else:
        sections = run_track_decomposition(best_lap_df)
    # ... continue with MRP, handling, coaching
```

**Step 2: Update corner_persistence.py**

Add persistence for new fields: `corner_type`, `mrp_distance_m`, etc.

**Step 3: Test pipeline integration**

Run: `python -m pytest telemetry_tool/tests/test_re_port_correctness.py -v -k "corner"` (if any corner-specific tests exist)

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10b_corners.py telemetry_tool/corner_persistence.py
git commit -m "feat: integrate track decomposition into pipeline stage"
```

---

### Task 10: API Endpoints Update

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (update corners endpoint)
- Create: `telemetry_tool/web/routes/user_corners.py` (new endpoints)

**Step 1: Update corners endpoint**

Modify `get_corners()` (line 827) to include new fields in response:
- `corner_type`, `section_type`, `mrp_distance_m`, `mrp_speed_mps`, `geometric_apex_m`
- `exit_importance`, `handling_events`, `is_user_defined`

**Step 2: Create user corners endpoints**

```python
# POST /api/v1/sessions/<id>/user-corners
# GET /api/v1/sessions/<id>/user-corners
# POST /api/v1/sessions/<id>/recoach
```

**Step 3: Test endpoints**

Run: `python -m pytest telemetry_tool/tests/test_data_api_v2.py -v -k "corner"`

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/web/routes/user_corners.py
git commit -m "feat: update corners API + add user corner endpoints"
```

---

## Phase 5: Frontend

### Task 11: Corner Picker Component

**Files:**
- Create: `lap-website/src/components/app/charts/CornerPicker.tsx`

Interactive track map with click-to-define corners:
- Renders GPS trace on canvas (reuse GpsTrace rendering logic)
- Click handlers for placing entry/apex/exit markers
- Snap-to-nearest-track-point
- Corner list sidebar
- "Done" button → POST to `/api/v1/sessions/{id}/user-corners`
- Banner during processing: "Define your corners now, or let auto-detection handle it"

**Step 5: Commit**

```bash
git add lap-website/src/components/app/charts/CornerPicker.tsx
git commit -m "feat: add interactive corner picker component"
```

---

### Task 12: Updated Corner Coaching Display

**Files:**
- Modify: `lap-website/src/components/app/analytics/SectorPanel.tsx` (or create new `CornerCoachingPanel.tsx`)

Display the new coaching output:
- Section list with type badges (hairpin, sweeper, etc.)
- Per-section coaching cards with time loss breakdown
- MRP vs geometric apex visualization
- Handling events (understeer/oversteer) with severity colors
- Corner focus indicator
- Auto/Custom toggle if user-defined corners exist

**Step 5: Commit**

```bash
git add lap-website/src/components/app/analytics/
git commit -m "feat: update corner coaching display with new fields"
```

---

### Task 13: Build + Deploy

**Step 1: Run all backend tests**

```bash
python -m pytest telemetry_tool/tests/ -x -q --tb=short
```

**Step 2: Build frontend**

```bash
cd lap-website && npm run build
```

**Step 3: Deploy frontend**

```bash
npm run cf:deploy
```

**Step 4: Deploy backend**

```bash
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/telemetry_tool/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build --no-cache api && docker compose -f docker-compose.prod.yml up -d api"
```

**Step 5: Run migration on production**

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose exec api alembic upgrade head"
```

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: complete corner coaching v2 rebuild"
```

---

## Execution Order & Dependencies

```
Task 1 (corner_focus) ──┐
Task 2 (classifier)  ───┤
                         ├──→ Task 3 (decomposition) ──→ Task 4 (MRP) ──→ Task 5 (handling)
                         │                                                       │
                         │    Task 6 (basic coaching) ◄──────────────────────────┘
                         │              │
                         │    Task 7 (advanced coaching) ◄── Task 6
                         │              │
Task 8 (schema) ─────────┼──→ Task 9 (pipeline integration) ◄── Task 7
                         │              │
                         └──→ Task 10 (API) ◄── Task 9
                                        │
                              Task 11 (corner picker) ◄── Task 10
                              Task 12 (coaching display) ◄── Task 10
                                        │
                              Task 13 (deploy) ◄── Task 11 + Task 12
```

**Parallelizable:**
- Tasks 1 + 2 (no dependencies)
- Tasks 6 + 8 (independent)
- Tasks 11 + 12 (independent frontend components)
