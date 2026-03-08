# Theoretical Overfitting Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect "too good to be true" theoretical laps by cross-validating the percentile envelope against holdout laps.

**Architecture:** Deterministic train/holdout split → build envelope on all laps → score holdout approach ratios per segment → flag `overfit_suspected` if holdout can't reach 85% of theoretical in most segments. Wire into pipeline stage 10 between theoretical metrics and confidence.

**Tech Stack:** Python 3.x, NumPy, pandas, pytest

---

### Task 1: Deterministic lap split + PlausibilityResult dataclass

**Files:**
- Modify: `telemetry_tool/theoretical_engine.py`
- Create: `telemetry_tool/tests/test_theoretical_plausibility.py`

**Step 1: Write the failing tests**

Create `telemetry_tool/tests/test_theoretical_plausibility.py`:

```python
"""Tests for theoretical overfitting detection via cross-validation."""
import numpy as np
import pandas as pd
import pytest


def _make_lap(n_points: int, base_speed: float, noise_std: float = 0.5,
              rng=None) -> pd.DataFrame:
    """Create a synthetic lap DataFrame."""
    if rng is None:
        rng = np.random.default_rng(42)
    dist = np.linspace(0, 500, n_points)
    speed = np.full(n_points, base_speed) + rng.normal(0, noise_std, n_points)
    speed = np.clip(speed, 2.0, 100.0)
    return pd.DataFrame({"distance_m": dist, "speed_mps": speed})


def test_split_deterministic():
    """Same laps produce identical train/holdout split every time."""
    from theoretical_engine import split_laps_train_holdout

    rng = np.random.default_rng(99)
    laps = [_make_lap(100, 20.0, rng=rng) for _ in range(10)]

    train1, hold1, idx1 = split_laps_train_holdout(laps)
    train2, hold2, idx2 = split_laps_train_holdout(laps)

    assert idx1 == idx2
    assert len(train1) == len(train2)
    assert len(hold1) == len(hold2)
    # Holdout is ~30% (every 3rd lap)
    assert len(hold1) == 3  # indices 2, 5, 8
    assert len(train1) == 7


def test_split_few_laps_skips():
    """Fewer than 4 laps → holdout is empty, all laps returned as train."""
    from theoretical_engine import split_laps_train_holdout

    laps = [_make_lap(100, 20.0) for _ in range(3)]
    train, hold, idx = split_laps_train_holdout(laps)

    assert len(train) == 3
    assert len(hold) == 0
    assert idx == []
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_theoretical_plausibility.py::test_split_deterministic telemetry_tool/tests/test_theoretical_plausibility.py::test_split_few_laps_skips -v`
Expected: FAIL with ImportError

**Step 3: Add split function and PlausibilityResult to theoretical_engine.py**

Append at the end of `telemetry_tool/theoretical_engine.py` (after `caps_from_percentile_envelope_with_bands()`):

```python


def split_laps_train_holdout(
    laps: list[pd.DataFrame],
    holdout_fraction: float = 0.3,
) -> tuple[list[pd.DataFrame], list[pd.DataFrame], list[int]]:
    """Deterministic train/holdout split for cross-validation.

    Uses modular selection (every Nth lap) for determinism — no randomness.
    Requires at least 4 laps; below that returns all laps as train.

    Parameters
    ----------
    laps : list of DataFrames (distance-resampled)
    holdout_fraction : target fraction for holdout (default 0.3)

    Returns
    -------
    (train_laps, holdout_laps, holdout_indices)
    """
    n = len(laps)
    if n < 4:
        return laps, [], []

    # Every Nth lap goes to holdout (deterministic)
    step = max(2, round(1.0 / holdout_fraction))
    holdout_indices = [i for i in range(n) if (i + 1) % step == 0]

    # Ensure at least 1 holdout and at least 3 train
    if not holdout_indices:
        holdout_indices = [n - 1]
    while n - len(holdout_indices) < 3 and len(holdout_indices) > 1:
        holdout_indices.pop()

    holdout_set = set(holdout_indices)
    train = [laps[i] for i in range(n) if i not in holdout_set]
    holdout = [laps[i] for i in holdout_indices]

    return train, holdout, holdout_indices


@dataclass
class PlausibilityResult:
    """Result of theoretical plausibility cross-validation."""
    segment_approach_ratios: np.ndarray   # (n_holdout, n_segments)
    mean_approach_ratio: float            # overall mean across holdout
    best_approach_ratio: float            # best holdout lap's mean ratio
    all_segments_exceeded: bool           # theoretical > all holdout everywhere
    segments_never_approached: int        # segments where no holdout reaches threshold
    plausibility_score: float             # 0-1 composite
    overfit_suspected: bool               # True if score < 0.5

    def to_dict(self) -> dict:
        return {
            "mean_approach_ratio": round(self.mean_approach_ratio, 4),
            "best_approach_ratio": round(self.best_approach_ratio, 4),
            "all_segments_exceeded": self.all_segments_exceeded,
            "segments_never_approached": self.segments_never_approached,
            "plausibility_score": round(self.plausibility_score, 4),
            "overfit_suspected": self.overfit_suspected,
        }
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_theoretical_plausibility.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/theoretical_engine.py telemetry_tool/tests/test_theoretical_plausibility.py
git commit -m "feat(theoretical): add deterministic train/holdout split and PlausibilityResult dataclass"
```

---

### Task 2: compute_theoretical_plausibility() function

**Files:**
- Modify: `telemetry_tool/theoretical_engine.py`
- Modify: `telemetry_tool/tests/test_theoretical_plausibility.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_theoretical_plausibility.py`:

```python


def test_healthy_envelope_passes():
    """8 realistic laps with achievable theoretical → no overfit flag."""
    from theoretical_engine import (
        build_theoretical_lap, split_laps_train_holdout,
        compute_theoretical_plausibility,
    )

    rng = np.random.default_rng(42)
    n_points = 200
    laps = []
    for i in range(8):
        dist = np.linspace(0, 500, n_points)
        # All laps centered around 20 m/s with small variation
        speed = np.full(n_points, 20.0) + rng.normal(0, 0.8, n_points)
        speed = np.clip(speed, 5.0, 40.0)
        laps.append(pd.DataFrame({
            "distance_m": dist,
            "speed_mps": speed,
            "accel_long_mps2": rng.normal(0, 1.0, n_points),
        }))

    train, holdout, _ = split_laps_train_holdout(laps)
    theo = build_theoretical_lap(laps, n_points=n_points)

    result = compute_theoretical_plausibility(theo, holdout)

    assert not result.overfit_suspected
    assert result.plausibility_score > 0.5
    assert result.best_approach_ratio > 0.80
    assert result.segments_never_approached < 5  # most segments reachable

    d = result.to_dict()
    assert "plausibility_score" in d
    assert "overfit_suspected" in d


def test_outlier_inflates_envelope():
    """7 normal laps + 1 outlier at 2x speed → overfit detected."""
    from theoretical_engine import (
        build_theoretical_lap, split_laps_train_holdout,
        compute_theoretical_plausibility,
    )

    rng = np.random.default_rng(42)
    n_points = 200
    laps = []
    for i in range(7):
        dist = np.linspace(0, 500, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 0.5, n_points)
        speed = np.clip(speed, 5.0, 40.0)
        laps.append(pd.DataFrame({
            "distance_m": dist,
            "speed_mps": speed,
            "accel_long_mps2": rng.normal(0, 1.0, n_points),
        }))

    # Outlier lap: 2x the normal speed
    dist = np.linspace(0, 500, n_points)
    speed = np.full(n_points, 40.0) + rng.normal(0, 0.5, n_points)
    speed = np.clip(speed, 5.0, 80.0)
    laps.append(pd.DataFrame({
        "distance_m": dist,
        "speed_mps": speed,
        "accel_long_mps2": rng.normal(0, 1.0, n_points),
    }))

    _, holdout, _ = split_laps_train_holdout(laps)
    # Build theoretical on ALL laps (including outlier) — this inflates envelope
    theo = build_theoretical_lap(laps, n_points=n_points)

    result = compute_theoretical_plausibility(theo, holdout)

    assert result.overfit_suspected
    assert result.plausibility_score < 0.5
    assert result.best_approach_ratio < 0.85
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_theoretical_plausibility.py::test_healthy_envelope_passes telemetry_tool/tests/test_theoretical_plausibility.py::test_outlier_inflates_envelope -v`
Expected: FAIL with ImportError

**Step 3: Add compute_theoretical_plausibility() to theoretical_engine.py**

Append at end of `telemetry_tool/theoretical_engine.py` (after `PlausibilityResult`):

```python


def compute_theoretical_plausibility(
    theoretical_df: pd.DataFrame,
    holdout_laps: list[pd.DataFrame],
    n_segments: int = 10,
    approach_threshold: float = 0.85,
) -> PlausibilityResult:
    """Score how plausible the theoretical lap is using holdout laps.

    Splits the track into equal-distance segments and checks whether
    holdout laps can approach the theoretical speed in each segment.

    Parameters
    ----------
    theoretical_df : DataFrame with distance_m and v_env_mps columns
    holdout_laps : list of DataFrames with distance_m and speed_mps
    n_segments : number of equal-distance segments to check
    approach_threshold : ratio below which a segment is "never approached"

    Returns
    -------
    PlausibilityResult with overfit_suspected flag.
    """
    if not holdout_laps or theoretical_df is None or len(theoretical_df) == 0:
        return PlausibilityResult(
            segment_approach_ratios=np.array([]),
            mean_approach_ratio=1.0,
            best_approach_ratio=1.0,
            all_segments_exceeded=False,
            segments_never_approached=0,
            plausibility_score=1.0,
            overfit_suspected=False,
        )

    theo_dist = theoretical_df["distance_m"].values
    theo_speed = theoretical_df["v_env_mps"].values
    d_min, d_max = theo_dist[0], theo_dist[-1]
    seg_edges = np.linspace(d_min, d_max, n_segments + 1)

    # Compute mean theoretical speed per segment
    theo_seg_speeds = np.zeros(n_segments)
    for s in range(n_segments):
        mask = (theo_dist >= seg_edges[s]) & (theo_dist < seg_edges[s + 1])
        if s == n_segments - 1:
            mask = (theo_dist >= seg_edges[s]) & (theo_dist <= seg_edges[s + 1])
        if mask.any():
            theo_seg_speeds[s] = np.mean(theo_speed[mask])
        else:
            theo_seg_speeds[s] = np.mean(theo_speed)

    # Compute approach ratios for each holdout lap
    n_holdout = len(holdout_laps)
    ratios = np.zeros((n_holdout, n_segments))

    for h, lap in enumerate(holdout_laps):
        lap_dist = lap["distance_m"].values
        lap_speed = lap["speed_mps"].values

        # Normalize lap distance to start at 0
        if len(lap_dist) > 0 and lap_dist[0] > 1.0:
            lap_dist = lap_dist - lap_dist[0]

        for s in range(n_segments):
            mask = (lap_dist >= seg_edges[s]) & (lap_dist < seg_edges[s + 1])
            if s == n_segments - 1:
                mask = (lap_dist >= seg_edges[s]) & (lap_dist <= seg_edges[s + 1])
            if mask.any() and theo_seg_speeds[s] > 0:
                ratios[h, s] = np.mean(lap_speed[mask]) / theo_seg_speeds[s]
            else:
                ratios[h, s] = 1.0  # no data = assume OK

    # Aggregate metrics
    mean_approach = float(np.mean(ratios))
    best_approach = float(np.max(np.mean(ratios, axis=1))) if n_holdout > 0 else 1.0

    # Best holdout per segment
    best_per_seg = np.max(ratios, axis=0) if n_holdout > 0 else np.ones(n_segments)
    all_exceeded = bool(np.all(best_per_seg < 1.0))
    never_approached = int(np.sum(best_per_seg < approach_threshold))

    # Plausibility score
    score = 1.0
    score -= (never_approached / n_segments) * 0.5
    if all_exceeded:
        score -= 0.3
    if best_approach < 0.80:
        score -= 0.2
    score = max(0.0, score)

    return PlausibilityResult(
        segment_approach_ratios=ratios,
        mean_approach_ratio=mean_approach,
        best_approach_ratio=best_approach,
        all_segments_exceeded=all_exceeded,
        segments_never_approached=never_approached,
        plausibility_score=score,
        overfit_suspected=score < 0.5,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_theoretical_plausibility.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/theoretical_engine.py telemetry_tool/tests/test_theoretical_plausibility.py
git commit -m "feat(theoretical): add compute_theoretical_plausibility() for overfitting detection"
```

---

### Task 3: Pipeline wiring — cross-validation in stage 10

**Files:**
- Modify: `telemetry_tool/pipeline.py`

**Step 1: Read pipeline.py around lines 2373-2444**

Understand the existing flow: `_compute_theo_metrics()` → `theo_metrics` → `_compute_confidence()` → `_confidence` → attach to `theo_metrics["confidence"]`.

**Step 2: Add plausibility check between theo_metrics and confidence**

After line 2379 (`summary["theoretical_metrics"] = theo_metrics`) and before line 2381 (`# ── 10b-ii: Attach confidence assessment ──`), insert:

```python

    # ── 10b-i½: Theoretical plausibility cross-validation ──
    _plausibility = None

    def _compute_plausibility():
        if theoretical_lap is None or theo_mod is None:
            return None
        if not hasattr(theo_mod, "split_laps_train_holdout"):
            return None
        if not hasattr(theo_mod, "compute_theoretical_plausibility"):
            return None

        # Need laps_for_theo from the enclosing scope
        _laps = laps_for_theo if 'laps_for_theo' in dir() else None
        if _laps is None or len(_laps) < 4:
            return None

        _, holdout, _ = theo_mod.split_laps_train_holdout(_laps)
        if not holdout:
            return None

        return theo_mod.compute_theoretical_plausibility(
            theoretical_lap, holdout,
        )

    _plausibility, err = _safe_step("10b_plausibility", _compute_plausibility)
    _record("10b_plausibility", _plausibility, err)

    if _plausibility is not None and theo_metrics is not None:
        theo_metrics["plausibility"] = _plausibility.to_dict()
        summary["theoretical_metrics"] = theo_metrics
```

IMPORTANT: The variable `laps_for_theo` is defined inside `_theoretical()` which is a nested function. It won't be accessible in the outer scope. You need to hoist it. Find where `laps_for_theo` is assigned (around line 2230-2242 inside `_theoretical()`) and store it on a mutable container in the outer scope.

Before the `_theoretical()` function definition (around line 2106), add:
```python
    _laps_for_theo_ref = [None]  # mutable container to capture laps_for_theo
```

Inside `_theoretical()`, right before the `return theo_mod.build_theoretical_lap(...)` calls (lines 2330 and 2339), add:
```python
            _laps_for_theo_ref[0] = laps_for_theo
```

Then in `_compute_plausibility()`, use:
```python
        _laps = _laps_for_theo_ref[0]
        if _laps is None or len(_laps) < 4:
            return None
```

**Step 3: Inject overfit_suspected into confidence**

After the plausibility block and after `_confidence` is computed (after line 2440), modify the confidence attachment block:

Replace lines 2442-2444:
```python
    if _confidence is not None and theo_metrics is not None:
        theo_metrics["confidence"] = _confidence.to_dict()
        summary["theoretical_metrics"] = theo_metrics
```

With:
```python
    if _confidence is not None and theo_metrics is not None:
        conf_dict = _confidence.to_dict()
        # Inject plausibility penalty
        if _plausibility is not None and _plausibility.overfit_suspected:
            reasons = conf_dict.get("confidence_reasons", [])
            reasons.insert(0, "overfit_suspected: theoretical may be unreachable")
            conf_dict["confidence_reasons"] = reasons
            # Apply penalty
            raw_score = conf_dict.get("confidence_score", 100)
            penalized = int(raw_score * _plausibility.plausibility_score)
            conf_dict["confidence_score"] = max(0, penalized)
            # Recompute level
            if penalized >= 75:
                conf_dict["confidence_level"] = "high"
            elif penalized >= 45:
                conf_dict["confidence_level"] = "medium"
            else:
                conf_dict["confidence_level"] = "low"
        theo_metrics["confidence"] = conf_dict
        summary["theoretical_metrics"] = theo_metrics
```

**Step 4: Run tests**

Run: `pytest telemetry_tool/tests/test_optimal_pipeline.py telemetry_tool/tests/test_theoretical_plausibility.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline.py
git commit -m "feat(pipeline): wire theoretical plausibility cross-validation into stage 10"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | `split_laps_train_holdout()` + `PlausibilityResult` dataclass | 2 |
| 2 | `compute_theoretical_plausibility()` with segment scoring | 2 |
| 3 | Pipeline wiring: plausibility → confidence penalty | 0 (existing pipeline tests) |
| **Total** | | **4 new tests** |
