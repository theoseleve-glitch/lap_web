# Corner Timeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the fixed 20%/60%/20% corner phase splitting with an event-based Corner Timeline using physics-defined events (BP, EOB, MRP, MIN_SPEED, APEX, THROTTLE_ON, TRACK_OUT), MRP-driven mistake detection, multi-lap stability metrics, and per-segment loss attribution.

**Architecture:** New `CornerEvent` and `CornerTimeline` dataclasses in `corner_analysis.py`. Event detection uses hysteresis-based change-point detection for braking/throttle events and prominence-based peak detection for MRP. Mistakes are classified by comparing event positions and values. Pipeline wires at stage 10c after existing `analyze_corners()`.

**Tech Stack:** Python 3.x, NumPy, pandas, scipy.signal (for prominence), dataclasses

---

### Task 1: CornerEvent + CornerTimeline Dataclasses

**Files:**
- Modify: `telemetry_tool/corner_analysis.py:93-98` (insert before CornerPerformance)
- Test: `telemetry_tool/tests/test_corner_timeline.py`

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_corner_timeline.py`:

```python
"""Tests for the Corner Timeline event detection system."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.corner_analysis import CornerEvent, CornerTimeline


class TestCornerEventDataclass:
    """Test CornerEvent dataclass creation and serialisation."""

    def test_create_and_to_dict(self):
        ev = CornerEvent(
            event_type="BP",
            s_position=100.0,
            confidence=0.9,
            source_channel="accel_long",
            value=-3.5,
            available=True,
        )
        d = ev.to_dict()
        assert d["event_type"] == "BP"
        assert d["s_position"] == 100.0
        assert d["confidence"] == 0.9
        assert d["source_channel"] == "accel_long"
        assert d["value"] == -3.5
        assert d["available"] is True

    def test_unavailable_event(self):
        ev = CornerEvent(
            event_type="MRP",
            s_position=0.0,
            confidence=0.0,
            source_channel="yaw_rate",
            value=0.0,
            available=False,
        )
        assert ev.available is False
        assert ev.confidence == 0.0


class TestCornerTimelineDataclass:
    """Test CornerTimeline dataclass creation and serialisation."""

    def test_create_and_to_dict(self):
        events = [
            CornerEvent("BP", 90.0, 0.95, "accel_long", -3.0, True),
            CornerEvent("EOB", 110.0, 0.90, "accel_long", -0.3, True),
            CornerEvent("MRP", 125.0, 0.85, "yaw_rate", 12.0, True),
            CornerEvent("MIN_SPEED", 130.0, 1.0, "speed", 15.5, True),
            CornerEvent("THROTTLE_ON", 140.0, 0.90, "accel_long", 0.8, True),
            CornerEvent("TRACK_OUT", 170.0, 0.50, "position", 0.0, True),
        ]
        tl = CornerTimeline(
            corner_id=1,
            events=events,
            segment_losses_s={},
            segment_confidences={},
            mistakes=[],
            mrp_strength=12.0,
            mrp_stability_std_m=0.0,
            event_stability={},
        )
        d = tl.to_dict()
        assert d["corner_id"] == 1
        assert len(d["events"]) == 6
        assert d["mrp_strength"] == 12.0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestCornerEventDataclass::test_create_and_to_dict -v`
Expected: FAIL with `ImportError: cannot import name 'CornerEvent'`

**Step 3: Write minimal implementation**

Insert in `telemetry_tool/corner_analysis.py` at line 93 (before `class CornerAnalysisError`), add:

```python
# =============================================================================
# Corner Timeline data structures
# =============================================================================

@dataclass
class CornerEvent:
    """A single physics-defined event within a corner."""
    event_type: str           # "BP"|"EOB"|"MRP"|"MIN_SPEED"|"APEX"|"THROTTLE_ON"|"TRACK_OUT"
    s_position: float         # distance along lap [m]
    confidence: float         # 0-1 (channel quality × detection quality)
    source_channel: str       # which channel detected it
    value: float              # the signal value at that point
    available: bool           # False if channel missing

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "s_position": round(self.s_position, 2),
            "confidence": round(self.confidence, 3),
            "source_channel": self.source_channel,
            "value": round(self.value, 4),
            "available": self.available,
        }


@dataclass
class CornerTimeline:
    """Event-based timeline for a single corner across the lap."""
    corner_id: int
    events: list[CornerEvent]          # ordered by s_position
    segment_losses_s: dict[str, float] # "BP_EOB", "EOB_MRP", etc.
    segment_confidences: dict[str, float]
    mistakes: list[dict]               # [{"type": str, "severity": float, "evidence": dict}]
    mrp_strength: float                # peak prominence of yaw_rate
    mrp_stability_std_m: float         # lap-to-lap std-dev of MRP s-position
    event_stability: dict[str, float]  # std-dev per event type across laps

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "events": [e.to_dict() for e in self.events],
            "segment_losses_s": {k: round(v, 4) for k, v in self.segment_losses_s.items()},
            "segment_confidences": {k: round(v, 3) for k, v in self.segment_confidences.items()},
            "mistakes": self.mistakes,
            "mrp_strength": round(self.mrp_strength, 2),
            "mrp_stability_std_m": round(self.mrp_stability_std_m, 2),
            "event_stability": {k: round(v, 2) for k, v in self.event_stability.items()},
        }

    def get_event(self, event_type: str) -> Optional[CornerEvent]:
        """Return the first event of the given type, or None."""
        for e in self.events:
            if e.event_type == event_type:
                return e
        return None
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py -v`
Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/corner_analysis.py telemetry_tool/tests/test_corner_timeline.py
git commit -m "feat(corners): add CornerEvent + CornerTimeline dataclasses"
```

---

### Task 2: detect_corner_events() — BP, EOB, ThrottleOn, TrackOut with Hysteresis

**Files:**
- Modify: `telemetry_tool/corner_analysis.py` (append new function after existing code)
- Test: `telemetry_tool/tests/test_corner_timeline.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_corner_timeline.py`:

```python
from telemetry_tool.corner_analysis import detect_corner_events


def _make_corner(cid=1, s_start=100.0, s_end=200.0):
    return {"corner_id": cid, "s_start": s_start, "s_end": s_end}


def _make_braking_lap_df(n=500, corner_s_start=100.0, corner_s_end=200.0):
    """Synthetic lap with clear braking, min-speed, and acceleration zones."""
    dist = np.linspace(0, 300, n)
    speed = np.ones(n) * 30.0  # 30 m/s baseline

    # Braking zone: 70m → 100m, speed drops from 30 to 15
    brake_mask = (dist >= 70) & (dist <= 100)
    speed[brake_mask] = np.interp(
        dist[brake_mask], [70, 100], [30, 15],
    )
    # Mid-corner: 100m → 150m at ~15 m/s
    mid_mask = (dist > 100) & (dist <= 150)
    speed[mid_mask] = 15.0
    # Acceleration: 150m → 200m, speed rises from 15 to 28
    accel_mask = (dist > 150) & (dist <= 200)
    speed[accel_mask] = np.interp(
        dist[accel_mask], [150, 200], [15, 28],
    )
    # Post-corner: 28 m/s
    post_mask = dist > 200
    speed[post_mask] = 28.0

    # Derive accel_long from speed gradient
    ds = np.gradient(dist)
    ds[ds == 0] = 1e-6
    dv = np.gradient(speed)
    accel_long = speed * dv / ds

    df = pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "accel_long_mps2": accel_long,
    })
    return df


class TestDetectCornerEvents:
    """Test detect_corner_events() for braking + throttle detection."""

    def test_braking_signal_detects_bp_eob(self):
        """Synthetic braking ramp → correct BP and EOB positions."""
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)

        bp = tl.get_event("BP")
        eob = tl.get_event("EOB")
        assert bp is not None and bp.available
        assert eob is not None and eob.available
        # BP should be near 70m (where braking starts)
        assert 60.0 <= bp.s_position <= 100.0
        # EOB should be after BP
        assert eob.s_position > bp.s_position

    def test_min_speed_detected(self):
        """MIN_SPEED detected near corner mid-point."""
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)

        ms = tl.get_event("MIN_SPEED")
        assert ms is not None and ms.available
        # Min speed should be around 100-150m where speed is lowest
        assert 95.0 <= ms.s_position <= 155.0
        assert ms.value == pytest.approx(15.0, abs=1.0)

    def test_throttle_on_detected(self):
        """THROTTLE_ON detected after min-speed."""
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)

        to = tl.get_event("THROTTLE_ON")
        ms = tl.get_event("MIN_SPEED")
        assert to is not None and to.available
        assert ms is not None
        assert to.s_position >= ms.s_position

    def test_track_out_fallback_to_s_end(self):
        """TRACK_OUT uses s_end when no position data is available."""
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)

        tout = tl.get_event("TRACK_OUT")
        assert tout is not None
        assert tout.s_position == pytest.approx(200.0, abs=1.0)

    def test_events_ordered_by_s_position(self):
        """All events in timeline are ordered by s_position."""
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)

        positions = [e.s_position for e in tl.events if e.available]
        assert positions == sorted(positions)
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestDetectCornerEvents -v`
Expected: FAIL with `ImportError: cannot import name 'detect_corner_events'`

**Step 3: Write minimal implementation**

Append to `telemetry_tool/corner_analysis.py`:

```python
# =============================================================================
# Corner Timeline — Event Detection
# =============================================================================

# Hysteresis parameters
_BP_THRESHOLD_MPS2: float = -1.0
_EOB_THRESHOLD_MPS2: float = -0.5
_TRACTION_THRESHOLD_MPS2_TL: float = 0.5
_MIN_SUSTAINED_M: float = 5.0
_MIN_EVENT_SEPARATION_M: float = 3.0
_TL_SEARCH_MARGIN_M: float = 50.0

_COL_YAW: str = "yaw_rate_dps"
_COL_HEADING: str = "heading_deg"
_COL_X: str = "X (m)"
_COL_Y: str = "Y (m)"


def _detect_bp(
    dist: np.ndarray,
    accel: np.ndarray,
    s_start: float,
    search_margin_m: float = _TL_SEARCH_MARGIN_M,
    threshold: float = _BP_THRESHOLD_MPS2,
    min_sustained_m: float = _MIN_SUSTAINED_M,
    data_quality: float = 1.0,
) -> CornerEvent:
    """Detect braking point: scan backward from s_start for sustained accel < threshold."""
    search_start = s_start - search_margin_m
    mask = (dist >= search_start) & (dist <= s_start)
    if mask.sum() < 3:
        return CornerEvent("BP", s_start, 0.0, "accel_long", 0.0, False)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    a_seg = accel[idx]

    # Scan backward for first point where accel < threshold sustained over min_sustained_m
    bp_pos = float("nan")
    bp_val = 0.0
    for i in range(len(a_seg) - 1, -1, -1):
        if np.isfinite(a_seg[i]) and a_seg[i] < threshold:
            # Check if sustained: find how far back it stays below threshold
            start_d = d_seg[i]
            j = i
            while j >= 0 and np.isfinite(a_seg[j]) and a_seg[j] < threshold:
                j -= 1
            sustained_d = start_d - d_seg[max(j, 0)]
            if sustained_d >= min_sustained_m or (i - max(j, 0)) >= 2:
                bp_pos = float(d_seg[max(j + 1, 0)])
                bp_val = float(a_seg[max(j + 1, 0)])
                break

    if not np.isfinite(bp_pos):
        # Fallback: use existing _find_braking_point
        bp_pos = _find_braking_point(dist, accel, s_start, search_margin_m, threshold)
        if np.isfinite(bp_pos):
            bp_idx = np.argmin(np.abs(dist - bp_pos))
            bp_val = float(accel[bp_idx]) if bp_idx < len(accel) else 0.0
        else:
            return CornerEvent("BP", s_start, 0.0, "accel_long", 0.0, False)

    conf = min(1.0, data_quality * 0.95)
    return CornerEvent("BP", bp_pos, conf, "accel_long", bp_val, True)


def _detect_eob(
    dist: np.ndarray,
    accel: np.ndarray,
    bp_s: float,
    s_end: float,
    threshold: float = _EOB_THRESHOLD_MPS2,
    min_sustained_m: float = _MIN_SUSTAINED_M,
    data_quality: float = 1.0,
) -> CornerEvent:
    """Detect end-of-braking: first point after BP where accel > threshold with hysteresis."""
    if not np.isfinite(bp_s):
        return CornerEvent("EOB", 0.0, 0.0, "accel_long", 0.0, False)

    mask = (dist > bp_s) & (dist <= s_end)
    if mask.sum() < 2:
        return CornerEvent("EOB", 0.0, 0.0, "accel_long", 0.0, False)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    a_seg = accel[idx]

    for i in range(len(a_seg)):
        if np.isfinite(a_seg[i]) and a_seg[i] > threshold:
            # Check sustained: must stay above for min_sustained_m
            start_d = d_seg[i]
            j = i
            sustained = True
            while j < len(a_seg) and (d_seg[j] - start_d) < min_sustained_m:
                if np.isfinite(a_seg[j]) and a_seg[j] < threshold:
                    sustained = False
                    break
                j += 1
            if sustained:
                conf = min(1.0, data_quality * 0.90)
                return CornerEvent("EOB", float(d_seg[i]), conf, "accel_long", float(a_seg[i]), True)

    # Fallback: where accel is least negative after BP
    least_neg_idx = np.argmax(a_seg)
    conf = min(1.0, data_quality * 0.5)
    return CornerEvent("EOB", float(d_seg[least_neg_idx]), conf, "accel_long", float(a_seg[least_neg_idx]), True)


def _detect_min_speed(
    dist: np.ndarray,
    speed: np.ndarray,
    s_start: float,
    s_end: float,
    data_quality: float = 1.0,
) -> CornerEvent:
    """Detect minimum speed point within corner."""
    mask = (dist >= s_start) & (dist <= s_end)
    if mask.sum() < 2:
        return CornerEvent("MIN_SPEED", (s_start + s_end) / 2, 0.0, "speed", 0.0, False)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    s_seg = speed[idx]

    finite = np.isfinite(s_seg)
    if finite.sum() == 0:
        return CornerEvent("MIN_SPEED", (s_start + s_end) / 2, 0.0, "speed", 0.0, False)

    min_idx = np.argmin(s_seg[finite])
    finite_indices = np.where(finite)[0]
    actual_idx = finite_indices[min_idx]

    conf = min(1.0, data_quality * 1.0)
    return CornerEvent("MIN_SPEED", float(d_seg[actual_idx]), conf, "speed", float(s_seg[actual_idx]), True)


def _detect_throttle_on(
    dist: np.ndarray,
    accel: np.ndarray,
    min_speed_s: float,
    s_end: float,
    threshold: float = _TRACTION_THRESHOLD_MPS2_TL,
    min_sustained_m: float = _MIN_SUSTAINED_M,
    data_quality: float = 1.0,
) -> CornerEvent:
    """Detect throttle application: first point after min-speed where accel > threshold sustained."""
    mask = (dist >= min_speed_s) & (dist <= s_end + 20.0)
    if mask.sum() < 2:
        return CornerEvent("THROTTLE_ON", s_end, 0.0, "accel_long", 0.0, False)

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    a_seg = accel[idx]

    for i in range(len(a_seg)):
        if np.isfinite(a_seg[i]) and a_seg[i] > threshold:
            start_d = d_seg[i]
            j = i
            sustained = True
            while j < len(a_seg) and (d_seg[j] - start_d) < min_sustained_m:
                if np.isfinite(a_seg[j]) and a_seg[j] < threshold:
                    sustained = False
                    break
                j += 1
            if sustained:
                conf = min(1.0, data_quality * 0.90)
                return CornerEvent("THROTTLE_ON", float(d_seg[i]), conf, "accel_long", float(a_seg[i]), True)

    # Fallback: first positive accel after min-speed
    for i in range(len(a_seg)):
        if np.isfinite(a_seg[i]) and a_seg[i] > 0:
            conf = min(1.0, data_quality * 0.4)
            return CornerEvent("THROTTLE_ON", float(d_seg[i]), conf, "accel_long", float(a_seg[i]), True)

    return CornerEvent("THROTTLE_ON", s_end, 0.0, "accel_long", 0.0, False)


def _detect_track_out(
    dist: np.ndarray,
    s_end: float,
    df: pd.DataFrame,
    data_quality: float = 1.0,
) -> CornerEvent:
    """Detect track-out: where lateral position returns to track edge, or s_end fallback."""
    # If XY data available, try to detect track-out
    if _COL_X in df.columns and _COL_Y in df.columns:
        # For now, use s_end as track-out (full lateral position analysis is complex)
        conf = min(1.0, data_quality * 0.5)
        return CornerEvent("TRACK_OUT", s_end, conf, "position", 0.0, True)

    # Fallback: s_end
    return CornerEvent("TRACK_OUT", s_end, 0.3, "position", 0.0, True)


def detect_corner_events(
    corner: dict,
    lap_df: pd.DataFrame,
    theoretical_df: Optional[pd.DataFrame] = None,
    data_quality: float = 1.0,
) -> CornerTimeline:
    """
    Detect physics-defined events within a corner region.

    For each corner [s_start, s_end], detects:
    - BP (Braking Point): where sustained deceleration begins
    - EOB (End of Braking): where deceleration eases off
    - MRP (Max Rotation Point): peak yaw rate (see Task 3)
    - MIN_SPEED: lowest speed within corner
    - APEX: innermost lateral position (requires XY data)
    - THROTTLE_ON: first sustained positive acceleration after min-speed
    - TRACK_OUT: where car returns to track edge, or s_end fallback

    Parameters
    ----------
    corner : dict
        Corner dict with corner_id, s_start, s_end.
    lap_df : pd.DataFrame
        Distance-resampled lap data.
    theoretical_df : pd.DataFrame, optional
        Theoretical lap for segment loss computation.
    data_quality : float
        Overall data quality score (0-1).

    Returns
    -------
    CornerTimeline with detected events, initially empty mistakes/losses.
    """
    cid = int(corner.get("corner_id", 0))
    s_start = float(corner.get("s_start", 0.0))
    s_end = float(corner.get("s_end", 0.0))

    dist = _resolve_dist(lap_df)
    speed = _resolve_speed(lap_df)
    accel = _resolve_accel_long(lap_df)

    events: list[CornerEvent] = []

    # 1. BP
    bp = _detect_bp(dist, accel, s_start, data_quality=data_quality)
    events.append(bp)

    # 2. EOB
    eob = _detect_eob(
        dist, accel,
        bp.s_position if bp.available else s_start,
        s_end,
        data_quality=data_quality,
    )
    events.append(eob)

    # 3. MRP — placeholder, filled by Task 3
    mrp = CornerEvent("MRP", 0.0, 0.0, "yaw_rate", 0.0, False)
    events.append(mrp)

    # 4. MIN_SPEED
    ms = _detect_min_speed(dist, speed, s_start, s_end, data_quality=data_quality)
    events.append(ms)

    # 5. APEX — requires XY, skip for now
    events.append(CornerEvent("APEX", ms.s_position, 0.0, "position", 0.0, False))

    # 6. THROTTLE_ON
    to = _detect_throttle_on(
        dist, accel,
        ms.s_position if ms.available else s_start,
        s_end,
        data_quality=data_quality,
    )
    events.append(to)

    # 7. TRACK_OUT
    tout = _detect_track_out(dist, s_end, lap_df, data_quality=data_quality)
    events.append(tout)

    # Sort by s_position (available events first by position)
    events.sort(key=lambda e: (not e.available, e.s_position))

    return CornerTimeline(
        corner_id=cid,
        events=events,
        segment_losses_s={},
        segment_confidences={},
        mistakes=[],
        mrp_strength=0.0,
        mrp_stability_std_m=0.0,
        event_stability={},
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py -v`
Expected: 8 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/corner_analysis.py telemetry_tool/tests/test_corner_timeline.py
git commit -m "feat(corners): add detect_corner_events() with hysteresis BP/EOB/ThrottleOn"
```

---

### Task 3: MRP Detection from Yaw Rate with Prominence + Heading Fallback

**Files:**
- Modify: `telemetry_tool/corner_analysis.py` (add `_detect_mrp()`, update `detect_corner_events()`)
- Test: `telemetry_tool/tests/test_corner_timeline.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_corner_timeline.py`:

```python
class TestMRPDetection:
    """Test MRP (Max Rotation Point) detection."""

    def test_clean_yaw_peak(self):
        """Single clean yaw peak → MRP detected with high confidence."""
        n = 500
        dist = np.linspace(0, 300, n)
        speed = np.ones(n) * 20.0
        accel = np.zeros(n)
        # Add yaw_rate with clear peak at 150m
        yaw = np.zeros(n)
        peak_center = 150.0
        sigma = 10.0
        yaw = 15.0 * np.exp(-0.5 * ((dist - peak_center) / sigma) ** 2)

        df = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "accel_long_mps2": accel,
            "yaw_rate_dps": yaw,
        })
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        mrp = tl.get_event("MRP")
        assert mrp is not None and mrp.available
        assert 140.0 <= mrp.s_position <= 160.0
        assert mrp.value == pytest.approx(15.0, abs=1.0)
        assert mrp.confidence >= 0.7

    def test_noisy_yaw_still_detects(self):
        """Gaussian noise on yaw → MRP still detected, lower confidence."""
        rng = np.random.RandomState(42)
        n = 500
        dist = np.linspace(0, 300, n)
        speed = np.ones(n) * 20.0
        accel = np.zeros(n)
        yaw = 12.0 * np.exp(-0.5 * ((dist - 150.0) / 10.0) ** 2)
        yaw += rng.normal(0, 2.0, n)  # add noise

        df = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "accel_long_mps2": accel,
            "yaw_rate_dps": yaw,
        })
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        mrp = tl.get_event("MRP")
        assert mrp is not None and mrp.available
        assert 130.0 <= mrp.s_position <= 170.0

    def test_missing_yaw_channel(self):
        """No yaw_rate column → MRP marked unavailable, no crash."""
        df = _make_braking_lap_df()  # has no yaw_rate_dps column
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        mrp = tl.get_event("MRP")
        assert mrp is not None
        assert mrp.available is False

    def test_multiple_yaw_peaks_selects_dominant(self):
        """Two peaks in corner → selects dominant (highest prominence)."""
        n = 500
        dist = np.linspace(0, 300, n)
        speed = np.ones(n) * 20.0
        accel = np.zeros(n)
        # Two peaks: small one at 120m, dominant at 160m
        yaw = (5.0 * np.exp(-0.5 * ((dist - 120.0) / 5.0) ** 2) +
               12.0 * np.exp(-0.5 * ((dist - 160.0) / 8.0) ** 2))

        df = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "accel_long_mps2": accel,
            "yaw_rate_dps": yaw,
        })
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        mrp = tl.get_event("MRP")
        assert mrp is not None and mrp.available
        # Should pick the dominant peak near 160m
        assert 150.0 <= mrp.s_position <= 170.0
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestMRPDetection -v`
Expected: FAIL (MRP currently always unavailable)

**Step 3: Write implementation**

Add `_detect_mrp()` to `corner_analysis.py` and update `detect_corner_events()`:

```python
def _detect_mrp(
    dist: np.ndarray,
    df: pd.DataFrame,
    s_start: float,
    s_end: float,
    min_prominence_dps: float = 0.5,
    data_quality: float = 1.0,
) -> tuple[CornerEvent, float]:
    """
    Detect Max Rotation Point from yaw_rate or heading derivative.

    Returns (CornerEvent, mrp_strength) where mrp_strength is the peak prominence.
    """
    # Try yaw_rate_dps first
    yaw_col = None
    channel_conf = 0.0
    yaw_vals = None

    if _COL_YAW in df.columns:
        yaw_col = _COL_YAW
        channel_conf = 1.0
        yaw_vals = pd.to_numeric(df[_COL_YAW], errors="coerce").values.astype(float)
    elif _COL_HEADING in df.columns:
        # Derive yaw rate from heading
        heading = pd.to_numeric(df[_COL_HEADING], errors="coerce").values.astype(float)
        ds = np.gradient(dist)
        ds[ds == 0] = 1e-6
        # yaw_rate ≈ d(heading)/ds × speed (crude approximation)
        yaw_vals = np.abs(np.gradient(heading) / ds)
        channel_conf = 0.6

    if yaw_vals is None:
        return CornerEvent("MRP", 0.0, 0.0, "yaw_rate", 0.0, False), 0.0

    mask = (dist >= s_start) & (dist <= s_end)
    if mask.sum() < 3:
        return CornerEvent("MRP", 0.0, 0.0, "yaw_rate", 0.0, False), 0.0

    idx = np.where(mask)[0]
    d_seg = dist[idx]
    y_seg = np.abs(yaw_vals[idx])

    # Replace NaN with 0 for peak finding
    y_clean = np.where(np.isfinite(y_seg), y_seg, 0.0)

    if len(y_clean) < 3:
        return CornerEvent("MRP", 0.0, 0.0, "yaw_rate", 0.0, False), 0.0

    # Find peaks with prominence
    try:
        from scipy.signal import find_peaks

        peaks, properties = find_peaks(y_clean, prominence=min_prominence_dps)
        if len(peaks) == 0:
            # Fallback: just use argmax
            peak_idx = np.argmax(y_clean)
            peak_val = float(y_clean[peak_idx])
            if peak_val < min_prominence_dps:
                return CornerEvent("MRP", 0.0, 0.0, "yaw_rate", 0.0, False), 0.0
            prominence = peak_val * 0.5  # rough estimate
        else:
            # Select peak with highest prominence
            best = np.argmax(properties["prominences"])
            peak_idx = peaks[best]
            peak_val = float(y_clean[peak_idx])
            prominence = float(properties["prominences"][best])
    except ImportError:
        # No scipy: use argmax
        peak_idx = np.argmax(y_clean)
        peak_val = float(y_clean[peak_idx])
        prominence = peak_val * 0.5

    # Detection confidence scales with prominence
    det_conf = min(1.0, prominence / 5.0)  # 5 deg/s = full confidence
    conf = channel_conf * det_conf * data_quality

    return (
        CornerEvent("MRP", float(d_seg[peak_idx]), conf, yaw_col or "yaw_rate", peak_val, True),
        prominence,
    )
```

Then update `detect_corner_events()` to replace the MRP placeholder:

```python
    # 3. MRP — from yaw rate
    mrp, mrp_strength = _detect_mrp(dist, lap_df, s_start, s_end, data_quality=data_quality)
    events.append(mrp)
```

And update the timeline construction:
```python
    return CornerTimeline(
        ...
        mrp_strength=mrp_strength,
        ...
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py -v`
Expected: 12 tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/corner_analysis.py telemetry_tool/tests/test_corner_timeline.py
git commit -m "feat(corners): add MRP detection with prominence + heading fallback"
```

---

### Task 4: compute_segment_losses() — Per-Segment Time Attribution

**Files:**
- Modify: `telemetry_tool/corner_analysis.py` (add function)
- Test: `telemetry_tool/tests/test_corner_timeline.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_corner_timeline.py`:

```python
from telemetry_tool.corner_analysis import compute_segment_losses


class TestSegmentLosses:
    """Test per-segment loss attribution."""

    def test_known_speed_profiles(self):
        """Known speed profiles → correct per-segment time attribution."""
        n = 200
        dist = np.linspace(0, 300, n)

        # Driver: 25 m/s flat
        drv_speed = np.ones(n) * 25.0
        # Theoretical: 30 m/s flat (faster everywhere)
        theo_speed = np.ones(n) * 30.0

        drv_df = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": drv_speed,
            "accel_long_mps2": np.zeros(n),
        })
        theo_df = pd.DataFrame({
            "distance_m": dist,
            "v_env_mps": theo_speed,
        })

        # Create a timeline with events at known positions
        events = [
            CornerEvent("BP", 80.0, 0.9, "accel_long", -3.0, True),
            CornerEvent("EOB", 110.0, 0.9, "accel_long", -0.3, True),
            CornerEvent("MRP", 130.0, 0.8, "yaw_rate", 10.0, True),
            CornerEvent("THROTTLE_ON", 160.0, 0.9, "accel_long", 0.5, True),
            CornerEvent("TRACK_OUT", 200.0, 0.5, "position", 0.0, True),
        ]
        tl = CornerTimeline(
            corner_id=1, events=events,
            segment_losses_s={}, segment_confidences={},
            mistakes=[], mrp_strength=10.0,
            mrp_stability_std_m=0.0, event_stability={},
        )

        losses = compute_segment_losses(tl, drv_df, theo_df)
        # All segments should have positive losses (driver is slower)
        assert all(v >= 0 for v in losses.values())
        # Total should be roughly (300/25 - 300/30) ≈ 2.0s for full lap
        # But segments only cover 80-200m = 120m
        # Expected per segment: (seg_len/25 - seg_len/30)
        total = sum(losses.values())
        assert total > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestSegmentLosses -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Append to `corner_analysis.py`:

```python
def compute_segment_losses(
    timeline: CornerTimeline,
    driver_df: pd.DataFrame,
    theoretical_df: pd.DataFrame,
) -> dict[str, float]:
    """
    Compute per-segment time losses between consecutive events.

    Segments: BP→EOB, EOB→MRP, MRP→ThrottleOn, ThrottleOn→TrackOut.
    For each: integrate time delta = Σ(1/v_actual - 1/v_theoretical) × ds.

    Returns dict of segment_name → time_loss_s (positive = driver lost time).
    """
    segment_pairs = [
        ("BP_EOB", "BP", "EOB"),
        ("EOB_MRP", "EOB", "MRP"),
        ("MRP_THROTTLE_ON", "MRP", "THROTTLE_ON"),
        ("THROTTLE_ON_TRACK_OUT", "THROTTLE_ON", "TRACK_OUT"),
    ]

    drv_dist = _resolve_dist(driver_df)
    drv_speed = _resolve_speed(driver_df)

    # Resolve theoretical arrays
    theo_dist = None
    theo_speed = None
    for dcol in ("distance_m", "Distance (m)"):
        if dcol in theoretical_df.columns:
            theo_dist = theoretical_df[dcol].to_numpy(dtype=float)
            break
    for scol in ("v_env_mps", "speed_mps", "Speed (m/s)"):
        if scol in theoretical_df.columns:
            theo_speed = theoretical_df[scol].to_numpy(dtype=float)
            break

    if theo_dist is None or theo_speed is None:
        return {}

    losses: dict[str, float] = {}
    confidences: dict[str, float] = {}

    for seg_name, start_type, end_type in segment_pairs:
        ev_start = timeline.get_event(start_type)
        ev_end = timeline.get_event(end_type)

        if ev_start is None or ev_end is None or not ev_start.available or not ev_end.available:
            losses[seg_name] = 0.0
            confidences[seg_name] = 0.0
            continue

        s0 = ev_start.s_position
        s1 = ev_end.s_position

        if s1 <= s0:
            losses[seg_name] = 0.0
            confidences[seg_name] = 0.0
            continue

        t_drv = _integrate_time(
            drv_dist[_slice_range(drv_dist, s0, s1)],
            drv_speed[_slice_range(drv_dist, s0, s1)],
        )
        t_theo = _integrate_time(
            theo_dist[_slice_range(theo_dist, s0, s1)],
            theo_speed[_slice_range(theo_dist, s0, s1)],
        )
        losses[seg_name] = max(0.0, round(t_drv - t_theo, 4))
        confidences[seg_name] = min(ev_start.confidence, ev_end.confidence)

    timeline.segment_losses_s = losses
    timeline.segment_confidences = confidences
    return losses
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestSegmentLosses -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/corner_analysis.py telemetry_tool/tests/test_corner_timeline.py
git commit -m "feat(corners): add compute_segment_losses() per-segment time attribution"
```

---

### Task 5: detect_corner_mistakes() — 6 Mistake Classifiers

**Files:**
- Modify: `telemetry_tool/corner_analysis.py` (add function)
- Test: `telemetry_tool/tests/test_corner_timeline.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_corner_timeline.py`:

```python
from telemetry_tool.corner_analysis import detect_corner_mistakes


class TestMistakeDetection:
    """Test mistake classifiers."""

    def test_power_before_rotation(self):
        """THROTTLE_ON before MRP with high yaw → mistake detected."""
        events = [
            CornerEvent("BP", 80.0, 0.9, "accel_long", -3.0, True),
            CornerEvent("EOB", 110.0, 0.9, "accel_long", -0.3, True),
            CornerEvent("MRP", 160.0, 0.8, "yaw_rate", 12.0, True),
            CornerEvent("MIN_SPEED", 130.0, 1.0, "speed", 15.0, True),
            CornerEvent("THROTTLE_ON", 140.0, 0.9, "accel_long", 0.5, True),
            CornerEvent("TRACK_OUT", 200.0, 0.5, "position", 0.0, True),
        ]
        tl = CornerTimeline(
            corner_id=1, events=events,
            segment_losses_s={}, segment_confidences={},
            mistakes=[], mrp_strength=12.0,
            mrp_stability_std_m=0.0, event_stability={},
        )

        # Build a lap_df with yaw_rate data
        n = 300
        dist = np.linspace(0, 300, n)
        yaw = 12.0 * np.exp(-0.5 * ((dist - 160.0) / 10.0) ** 2)
        df = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": np.ones(n) * 20.0,
            "accel_long_mps2": np.zeros(n),
            "yaw_rate_dps": yaw,
        })

        corner = _make_corner(1, 100.0, 200.0)
        mistakes = detect_corner_mistakes(tl, df, corner)

        types = [m["type"] for m in mistakes]
        assert "power_before_rotation" in types

    def test_no_mistakes_clean_corner(self):
        """Clean corner with proper event ordering → no rotation mistakes."""
        events = [
            CornerEvent("BP", 80.0, 0.9, "accel_long", -3.0, True),
            CornerEvent("EOB", 110.0, 0.9, "accel_long", -0.3, True),
            CornerEvent("MRP", 130.0, 0.85, "yaw_rate", 12.0, True),
            CornerEvent("MIN_SPEED", 135.0, 1.0, "speed", 15.0, True),
            CornerEvent("THROTTLE_ON", 160.0, 0.9, "accel_long", 0.5, True),
            CornerEvent("TRACK_OUT", 200.0, 0.5, "position", 0.0, True),
        ]
        tl = CornerTimeline(
            corner_id=1, events=events,
            segment_losses_s={}, segment_confidences={},
            mistakes=[], mrp_strength=12.0,
            mrp_stability_std_m=0.0, event_stability={},
        )

        n = 300
        dist = np.linspace(0, 300, n)
        yaw = 12.0 * np.exp(-0.5 * ((dist - 130.0) / 10.0) ** 2)
        df = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": np.ones(n) * 20.0,
            "accel_long_mps2": np.zeros(n),
            "yaw_rate_dps": yaw,
        })

        corner = _make_corner(1, 100.0, 200.0)
        mistakes = detect_corner_mistakes(tl, df, corner)

        rot_mistakes = [m for m in mistakes if m["type"] in (
            "power_before_rotation", "rotation_too_late",
        )]
        assert len(rot_mistakes) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestMistakeDetection -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Append to `corner_analysis.py`:

```python
def detect_corner_mistakes(
    timeline: CornerTimeline,
    lap_df: pd.DataFrame,
    corner: dict,
) -> list[dict]:
    """
    Classify technique mistakes from a corner timeline.

    Mistake classifiers:
    - no_clear_mrp: MRP confidence < 0.3 or unavailable
    - mrp_plateau: MRP prominence < 1.0 deg/s (flat yaw profile)
    - mrp_drift: MRP stability std > 10m across laps (requires event_stability)
    - mrp_after_apex: MRP s_position > MIN_SPEED s_position + 5m
    - power_before_rotation: THROTTLE_ON < MRP AND yaw at throttle_on > 50% of peak
    - rotation_too_late: MRP s_position > EOB s_position + 30% of corner length
    """
    mistakes: list[dict] = []
    mrp = timeline.get_event("MRP")
    eob = timeline.get_event("EOB")
    throttle_on = timeline.get_event("THROTTLE_ON")
    min_speed = timeline.get_event("MIN_SPEED")

    s_start = float(corner.get("s_start", 0.0))
    s_end = float(corner.get("s_end", 0.0))
    corner_len = s_end - s_start

    # 1. no_clear_mrp
    if mrp is None or not mrp.available or mrp.confidence < 0.3:
        mistakes.append({
            "type": "no_clear_mrp",
            "severity": 0.5,
            "evidence": {
                "mrp_confidence": mrp.confidence if mrp else 0.0,
                "mrp_available": mrp.available if mrp else False,
            },
        })

    # 2. mrp_plateau
    if timeline.mrp_strength < 1.0 and mrp is not None and mrp.available:
        mistakes.append({
            "type": "mrp_plateau",
            "severity": round(1.0 - timeline.mrp_strength, 2),
            "evidence": {
                "prominence_dps": round(timeline.mrp_strength, 2),
            },
        })

    # 3. mrp_drift (requires multi-lap data in event_stability)
    mrp_std = timeline.event_stability.get("MRP", 0.0)
    if mrp_std > 10.0:
        mistakes.append({
            "type": "mrp_drift",
            "severity": round(min(1.0, mrp_std / 20.0), 2),
            "evidence": {
                "mrp_stability_std_m": round(mrp_std, 1),
            },
        })

    # 4. mrp_after_apex (use MIN_SPEED as apex proxy)
    if (mrp is not None and mrp.available and
            min_speed is not None and min_speed.available):
        delta = mrp.s_position - min_speed.s_position
        if delta > 5.0:
            mistakes.append({
                "type": "mrp_after_apex",
                "severity": round(min(1.0, delta / 15.0), 2),
                "evidence": {
                    "mrp_s": round(mrp.s_position, 1),
                    "min_speed_s": round(min_speed.s_position, 1),
                    "delta_m": round(delta, 1),
                },
            })

    # 5. power_before_rotation
    if (mrp is not None and mrp.available and
            throttle_on is not None and throttle_on.available):
        if throttle_on.s_position < mrp.s_position:
            # Check yaw rate at throttle_on position
            dist = _resolve_dist(lap_df)
            yaw_at_throttle = 0.0
            peak_yaw = mrp.value
            if _COL_YAW in lap_df.columns:
                yaw_vals = pd.to_numeric(lap_df[_COL_YAW], errors="coerce").values.astype(float)
                to_idx = np.argmin(np.abs(dist - throttle_on.s_position))
                yaw_at_throttle = abs(float(yaw_vals[to_idx])) if to_idx < len(yaw_vals) else 0.0

            yaw_ratio = yaw_at_throttle / max(peak_yaw, 1e-6)
            if yaw_ratio > 0.5:
                mistakes.append({
                    "type": "power_before_rotation",
                    "severity": round(min(1.0, yaw_ratio * 0.8), 2),
                    "evidence": {
                        "throttle_on_s": round(throttle_on.s_position, 1),
                        "mrp_s": round(mrp.s_position, 1),
                        "yaw_at_throttle": round(yaw_at_throttle, 1),
                        "peak_yaw": round(peak_yaw, 1),
                    },
                })

    # 6. rotation_too_late
    if (mrp is not None and mrp.available and
            eob is not None and eob.available and corner_len > 0):
        delta = mrp.s_position - eob.s_position
        delta_pct = delta / corner_len
        if delta_pct > 0.3:
            mistakes.append({
                "type": "rotation_too_late",
                "severity": round(min(1.0, delta_pct / 0.5), 2),
                "evidence": {
                    "mrp_s": round(mrp.s_position, 1),
                    "eob_s": round(eob.s_position, 1),
                    "delta_pct": round(delta_pct, 2),
                    "corner_len_m": round(corner_len, 1),
                },
            })

    return mistakes
```

**Step 4: Run test to verify it passes**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestMistakeDetection -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/corner_analysis.py telemetry_tool/tests/test_corner_timeline.py
git commit -m "feat(corners): add detect_corner_mistakes() with 6 classifiers"
```

---

### Task 6: compute_event_stability() — Multi-Lap Std-Dev

**Files:**
- Modify: `telemetry_tool/corner_analysis.py` (add function)
- Test: `telemetry_tool/tests/test_corner_timeline.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_corner_timeline.py`:

```python
from telemetry_tool.corner_analysis import compute_event_stability


class TestEventStability:
    """Test multi-lap event position stability."""

    def test_five_laps_varying_bp(self):
        """5 laps with varying BP → std-dev computed correctly."""
        corners = [_make_corner(1, 100.0, 200.0)]

        # Create 5 laps with BP at different positions (70, 72, 68, 74, 71)
        bp_positions = [70, 72, 68, 74, 71]
        all_lap_dfs = []
        for bp_pos in bp_positions:
            n = 500
            dist = np.linspace(0, 300, n)
            speed = np.ones(n) * 30.0
            # Braking from bp_pos
            brake_mask = (dist >= bp_pos) & (dist <= 100)
            speed[brake_mask] = np.interp(dist[brake_mask], [bp_pos, 100], [30, 15])
            mid_mask = (dist > 100) & (dist <= 150)
            speed[mid_mask] = 15.0
            accel_mask = (dist > 150) & (dist <= 200)
            speed[accel_mask] = np.interp(dist[accel_mask], [150, 200], [15, 28])
            post = dist > 200
            speed[post] = 28.0

            ds = np.gradient(dist)
            ds[ds == 0] = 1e-6
            dv = np.gradient(speed)
            accel = speed * dv / ds

            df = pd.DataFrame({
                "Distance (m)": dist,
                "Speed (m/s)": speed,
                "accel_long_mps2": accel,
            })
            all_lap_dfs.append(df)

        stability = compute_event_stability(corners, all_lap_dfs)
        assert 1 in stability
        # BP std-dev should be around 2m (std of [70,72,68,74,71])
        bp_std = stability[1].get("BP", 0.0)
        assert bp_std > 0.5  # not zero — real variation exists
        assert bp_std < 10.0  # but not crazy

    def test_fewer_than_3_laps_skipped(self):
        """< 3 laps → stability metrics skipped."""
        corners = [_make_corner(1, 100.0, 200.0)]
        df = _make_braking_lap_df()
        stability = compute_event_stability(corners, [df, df])
        # Should return empty or skip
        assert stability == {} or 1 not in stability or stability[1] == {}
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestEventStability -v`
Expected: FAIL with `ImportError`

**Step 3: Write implementation**

Append to `corner_analysis.py`:

```python
def compute_event_stability(
    corners: list[dict],
    all_lap_dfs: list[pd.DataFrame],
    data_quality: float = 1.0,
) -> dict[int, dict[str, float]]:
    """
    Compute std-dev of each event's s_position across multiple laps.

    Parameters
    ----------
    corners : list of corner dicts
    all_lap_dfs : list of DataFrames, one per lap
    data_quality : float, 0-1

    Returns
    -------
    dict mapping corner_id → {event_type → std_dev_m}
    Skips if fewer than 3 laps.
    """
    if len(all_lap_dfs) < 3:
        return {}

    result: dict[int, dict[str, float]] = {}

    for corner in corners:
        cid = int(corner.get("corner_id", 0))
        event_positions: dict[str, list[float]] = {}

        for lap_df in all_lap_dfs:
            if lap_df is None or len(lap_df) < 10:
                continue
            try:
                tl = detect_corner_events(corner, lap_df, data_quality=data_quality)
                for ev in tl.events:
                    if ev.available and ev.s_position > 0:
                        event_positions.setdefault(ev.event_type, []).append(ev.s_position)
            except Exception:
                continue

        stability: dict[str, float] = {}
        for ev_type, positions in event_positions.items():
            if len(positions) >= 3:
                stability[ev_type] = float(np.std(positions))

        result[cid] = stability

    return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestEventStability -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telemetry_tool/corner_analysis.py telemetry_tool/tests/test_corner_timeline.py
git commit -m "feat(corners): add compute_event_stability() multi-lap std-dev"
```

---

### Task 7: Pipeline Wiring — Stage 10c Timeline + Mistakes + Stability

**Files:**
- Modify: `telemetry_tool/pipeline.py:2631` (after `summary["corner_performances"]`)
- Test: `telemetry_tool/tests/test_corner_timeline.py`

**Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_corner_timeline.py`:

```python
class TestPipelineIntegration:
    """Test that pipeline stage 10c produces corner_timelines."""

    def test_corner_timelines_in_summary(self):
        """Smoke test: detect_corner_events produces timelines that can be serialized."""
        df = _make_braking_lap_df()
        corners = [_make_corner(1, 100.0, 200.0)]

        timelines = []
        for c in corners:
            tl = detect_corner_events(c, df)
            tl.mistakes = detect_corner_mistakes(tl, df, c)
            timelines.append(tl.to_dict())

        assert len(timelines) == 1
        assert "events" in timelines[0]
        assert "mistakes" in timelines[0]
        # Should be JSON-serializable
        import json
        json.dumps(timelines)
```

**Step 2: Run test to verify it fails**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py::TestPipelineIntegration -v`
Expected: Should PASS already (this is a smoke test using already-implemented functions). If the import of `detect_corner_mistakes` was already done in Task 5, this passes.

**Step 3: Wire into pipeline.py**

In `telemetry_tool/pipeline.py`, after line 2631 (`summary["corner_performances"] = corner_performances`), insert:

```python
    # -- 10c-ii: Corner Timeline detection (event-based) --

    corner_timelines: list[dict] = []

    def _corner_timelines():
        ca_mod = _import("corner_analysis")
        if ca_mod is None or not hasattr(ca_mod, "detect_corner_events"):
            return None
        if not corners or best_lap_df is None:
            return None

        dq = summary.get("data_quality")
        dq_score = getattr(dq, "overall_confidence", 1.0) if dq else 1.0

        theo_df = None
        theo_result = summary.get("theoretical_lap")
        if theo_result is not None and isinstance(theo_result, pd.DataFrame):
            theo_df = theo_result

        timelines = []
        for c in corners:
            try:
                tl = ca_mod.detect_corner_events(c, best_lap_df, theo_df, dq_score)
                # Segment losses
                if theo_df is not None and hasattr(ca_mod, "compute_segment_losses"):
                    ca_mod.compute_segment_losses(tl, best_lap_df, theo_df)
                # Mistakes
                if hasattr(ca_mod, "detect_corner_mistakes"):
                    tl.mistakes = ca_mod.detect_corner_mistakes(tl, best_lap_df, c)
                timelines.append(tl)
            except Exception:
                logger.debug("Corner timeline failed for corner %s", c.get("corner_id"), exc_info=True)

        # Multi-lap stability
        if hasattr(ca_mod, "compute_event_stability") and resampled_laps:
            all_dfs = [
                resampled_laps[k] for k in sorted(resampled_laps.keys())
                if k not in excluded_laps and resampled_laps[k] is not None and len(resampled_laps[k]) >= 10
            ]
            if len(all_dfs) >= 3:
                try:
                    stability = ca_mod.compute_event_stability(corners, all_dfs, dq_score)
                    for tl in timelines:
                        cid_stab = stability.get(tl.corner_id, {})
                        tl.mrp_stability_std_m = cid_stab.get("MRP", 0.0)
                        tl.event_stability = cid_stab
                except Exception:
                    logger.debug("Event stability failed", exc_info=True)

        return [tl.to_dict() for tl in timelines]

    tl_result, tl_err = _safe_step("10c_corner_timelines", _corner_timelines)
    _record("10c_corner_timelines", tl_result, tl_err)
    if tl_result is not None:
        corner_timelines = tl_result
        logger.info("Corner timelines: %d corners with events", len(tl_result))
    summary["corner_timelines"] = corner_timelines
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py telemetry_tool/tests/test_corner_timeline.py
git commit -m "feat(corners): wire corner timelines into pipeline stage 10c-ii"
```

---

### Task 8: API + Reporting Extensions

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:738-759` (extend `/corners` with timeline)
- Modify: `telemetry_tool/reporting_html.py:1851-1862` (add events + mistakes columns)
- Modify: `telemetry_tool/corner_analysis.py` (update `rank_improvement_opportunities` with new weights)

**Step 1: Extend `/corners` endpoint**

In `telemetry_tool/web/routes/data_v2.py`, in the `get_corners()` function, after building the corners list (around line 775), add timeline data merge:

```python
    # -- 5. Merge timeline data if available --
    if theo:
        timeline_list = theo.get("corner_timelines", [])
        tl_map = {}
        for tl in (timeline_list or []):
            tid = tl.get("corner_id")
            if tid is not None:
                tl_map[tid] = tl

        if corners and tl_map:
            for corner in corners:
                cid = corner.get("corner_id")
                if cid in tl_map:
                    corner["timeline"] = tl_map[cid]
```

**Step 2: Update reporting — add Mistakes column**

In `telemetry_tool/reporting_html.py`, inside `_build_corner_table_html()`, after extracting `coaching_txt` (around line 1828), add:

```python
        # Timeline mistakes (if available)
        mistakes_html = ""
        if isinstance(p, dict):
            timeline = p.get("timeline", {})
            if timeline:
                mistake_list = timeline.get("mistakes", [])
                if mistake_list:
                    top = mistake_list[0]
                    sev = top.get("severity", 0)
                    sev_color = "#ff4444" if sev > 0.6 else ("#ffd600" if sev > 0.3 else "#88ff88")
                    mistakes_html = (
                        f'<span style="color:{sev_color};font-size:0.75rem;">'
                        f'{top.get("type", "").replace("_", " ")}'
                        f' ({sev:.0%})</span>'
                    )
```

And add the column to the row template and header.

**Step 3: Update `rank_improvement_opportunities` with new weights**

In `corner_analysis.py`, update `rank_improvement_opportunities()`:

```python
def rank_improvement_opportunities(
    corner_performances: list[CornerPerformance],
    corner_timelines: Optional[list[CornerTimeline]] = None,
) -> list[CornerPerformance]:
    """
    Sort corners by composite priority (descending).

    Weights:
    - time_loss_s: 0.6
    - sum(mistake_severities): 0.2
    - mrp_stability_std_m: 0.1 (unstable = higher priority)
    - max segment loss: 0.1
    """
    if corner_timelines is None:
        return sorted(corner_performances, key=lambda p: p.time_loss_s, reverse=True)

    tl_map = {tl.corner_id: tl for tl in corner_timelines}

    def _score(p: CornerPerformance) -> float:
        score = p.time_loss_s * 0.6
        tl = tl_map.get(p.corner_id)
        if tl:
            mistake_sum = sum(m.get("severity", 0) for m in tl.mistakes)
            score += mistake_sum * 0.2
            score += min(tl.mrp_stability_std_m / 20.0, 1.0) * 0.1
            if tl.segment_losses_s:
                score += max(tl.segment_losses_s.values()) * 0.1
        return score

    return sorted(corner_performances, key=_score, reverse=True)
```

**Step 4: Run all tests**

Run: `pytest telemetry_tool/tests/test_corner_timeline.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add telemetry_tool/corner_analysis.py telemetry_tool/web/routes/data_v2.py telemetry_tool/reporting_html.py
git commit -m "feat(corners): extend API + reporting with timeline data, update ranking weights"
```
