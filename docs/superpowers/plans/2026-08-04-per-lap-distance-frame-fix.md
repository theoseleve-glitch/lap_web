# Per-Lap Distance Frame Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every resampled lap use one canonical 0-based per-lap distance frame, so that corner spans detected on one lap actually match every other lap.

**Architecture:** RaceChrono's `Distance (m)` is cumulative *session* distance. `resampling.resample_lap_by_distance` preserves each lap's absolute range, so lap 1 spans 153.9–1356.4 m while lap 5 spans 4997.9–6196.5 m. Corners are detected on one lap only and carry that lap's absolute span, so the ubiquitous `(dist >= s_start) & (dist <= s_end)` idiom returns an empty mask on every other lap. Fix: subtract each lap's own `d_min` inside `resample_lap_by_distance`. Resampling sits downstream of every producer of frame heterogeneity and runs unconditionally, so one edit there collapses all frames at once.

**Tech Stack:** Python 3.14, pandas, numpy, pytest. Frontend: Next.js 14 + TypeScript.

**Branch:** `fix/per-lap-distance-frame`, worktree `C:\Users\Admin\lap_web-wt-distframe`, forked from `feat/adaptive-coaching` @ `476a889`.

## Global Constraints

- **Tests import bare module names** (`from resampling import ...`), never `from telemetry_tool.resampling import ...`. `telemetry_tool/tests/conftest.py:12-14` puts the project root on `sys.path`. The wrong prefix has already caused one production-only crash in this codebase.
- **Run tests from the repo root:** `python -m pytest telemetry_tool/tests/... -v`.
- **Bite-check every test.** After a test passes, deliberately break the code it guards and confirm it goes red. A test that cannot fail is worse than no test — five tests on a previous build could not fail and all five looked correct on the page.
- **Assert on counts and values, never on the absence of exceptions.** `s10b_corners.py:380-382` swallows exceptions with `logger.debug`, and `_extract_corner_metrics` returns `None` rather than raising. A test that only checks "did not throw" passes against the bug.
- **Never emit the absolute origin as a DataFrame column.** Loose first-match column sniffers (`gps_repo.py:49`, `theoretical_repo.py:41`, `s10b_corners.py:400`, `theoretical_adapter.py:475`) would bind to it and silently reintroduce the old frame. Logs only.
- **Do not fix `apply_kart_traction_floor`'s dropped return** (`s09_physics.py:269`) in this branch. It would raise the grip envelope on every kart session — a behaviour change hidden inside a correctness fix.
- **Do not repair the dead `gate_advanced` gate** (Task 8 pins it deliberately).
- Commit after every task. Conventional commit prefixes (`fix:`, `test:`, `chore:`).

---

### Task 1: Canonical 0-based frame in `resample_lap_by_distance`

**Files:**
- Create: `telemetry_tool/tests/test_distance_frame.py`
- Modify: `telemetry_tool/resampling.py:198-205`
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `resample_lap_by_distance(lap_df, n_points=1000) -> pd.DataFrame` whose `"Distance (m)"` column now always starts at `0.0` and ends at the lap's span. `"distance_norm"` is unchanged (still 0.0–1.0). Every later task depends on this invariant.

- [ ] **Step 1: Write the failing tests**

Create `telemetry_tool/tests/test_distance_frame.py`:

```python
"""The canonical per-lap distance frame.

RaceChrono exports cumulative SESSION distance, so lap 5 of a real session
spans e.g. 4997.9-6196.5 m.  Every resampled lap must be rebased to 0 so that
corner spans detected on one lap match all the others.

The offsets used here are the measured values from
telemetry_tool/data/raw/OK_R4.csv.
"""
import numpy as np
import pandas as pd
import pytest


def _lap(d_start: float, d_end: float, lap_no: int, n: int = 500) -> pd.DataFrame:
    """A lap whose Distance column carries a genuine absolute offset."""
    d = np.linspace(d_start, d_end, n)
    return pd.DataFrame({
        "Distance (m)": d,
        "Speed (m/s)": np.linspace(10.0, 30.0, n),
        "Time (s)": np.linspace(0.0, 75.0, n),
        "Lap #": float(lap_no),
    })


def test_resampled_lap_starts_at_zero_regardless_of_absolute_offset():
    from resampling import resample_lap_by_distance

    out = resample_lap_by_distance(_lap(4997.9, 6196.5, 5), n_points=100)

    assert out["Distance (m)"].iloc[0] == pytest.approx(0.0)
    assert out["Distance (m)"].iloc[-1] == pytest.approx(6196.5 - 4997.9)


def test_all_laps_share_one_frame():
    from resampling import resample_lap_by_distance

    laps = [_lap(153.9, 1356.4, 1), _lap(4997.9, 6196.5, 5)]
    outs = [resample_lap_by_distance(l, n_points=100) for l in laps]

    for o in outs:
        assert o["Distance (m)"].iloc[0] == pytest.approx(0.0)
    # spans stay distinct (laps really are different lengths) but origins agree
    assert outs[0]["Distance (m)"].iloc[-1] != pytest.approx(
        outs[1]["Distance (m)"].iloc[-1]
    )


def test_channels_are_not_clamped_by_the_rebase():
    """Guards the shift-before-interpolate trap.

    If dist_raw is not shifted before _interp_channel, np.interp sees an
    absolute x-array against a 0-based grid, every query falls left of the
    first point, and every channel is returned as a constant.
    """
    from resampling import resample_lap_by_distance

    out = resample_lap_by_distance(_lap(4997.9, 6196.5, 5), n_points=200)

    assert out["Speed (m/s)"].iloc[0] == pytest.approx(10.0, abs=0.2)
    assert out["Speed (m/s)"].iloc[-1] == pytest.approx(30.0, abs=0.2)
    assert out["Speed (m/s)"].nunique() > 100, "channel was clamped to a constant"


def test_distance_norm_still_spans_zero_to_one():
    from resampling import resample_lap_by_distance

    out = resample_lap_by_distance(_lap(4997.9, 6196.5, 5), n_points=100)

    assert out["distance_norm"].iloc[0] == pytest.approx(0.0)
    assert out["distance_norm"].iloc[-1] == pytest.approx(1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py -v`

Expected: `test_resampled_lap_starts_at_zero_regardless_of_absolute_offset` and `test_all_laps_share_one_frame` FAIL with the first distance being `4997.9` rather than `0.0`. The other two PASS already (they describe behaviour that must be preserved).

- [ ] **Step 3: Implement the rebase**

In `telemetry_tool/resampling.py`, replace lines 198-205:

```python
    dist_raw = pd.to_numeric(lap_df[_COL_DIST], errors="coerce").values
    _validate_distance(dist_raw)

    d_min = float(np.nanmin(dist_raw))
    d_max = float(np.nanmax(dist_raw))

    dist_grid = np.linspace(d_min, d_max, n_points)
    dist_norm = (dist_grid - d_min) / (d_max - d_min)   # 0.0 – 1.0
```

with:

```python
    dist_raw = pd.to_numeric(lap_df[_COL_DIST], errors="coerce").values
    _validate_distance(dist_raw)

    d_min = float(np.nanmin(dist_raw))
    d_max = float(np.nanmax(dist_raw))
    span = d_max - d_min

    # Canonical frame: every resampled lap is 0-based per-lap metres.
    #
    # RaceChrono's "Distance (m)" is cumulative SESSION distance, so lap 5 of a
    # ten-lap session starts near 5 km.  Corners are detected on one lap only
    # (s07_resample.py:82-83) and carry that lap's span, so without this rebase
    # every (dist >= s_start) & (dist <= s_end) mask is empty on all other laps.
    #
    # Shift dist_raw here, BEFORE _interp_channel below, or np.interp compares an
    # absolute x-array against a 0-based grid and clamps every channel flat.
    #
    # The absolute origin is deliberately kept out of the returned frame — a
    # column carrying it would be picked up by the loose first-match distance
    # sniffers elsewhere in the codebase and silently restore the old frame.
    dist_raw = dist_raw - d_min

    dist_grid = np.linspace(0.0, span, n_points)
    dist_norm = dist_grid / span   # 0.0 – 1.0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py -v`
Expected: 4 passed.

- [ ] **Step 5: Bite-check**

Temporarily change `dist_raw = dist_raw - d_min` to `dist_raw = dist_raw` and re-run.
Expected: `test_channels_are_not_clamped_by_the_rebase` goes RED (speed clamped to a constant), proving that test can fail. Restore the line.

Then temporarily change `np.linspace(0.0, span, n_points)` back to `np.linspace(d_min, d_max, n_points)` and re-run.
Expected: the two frame tests go RED. Restore.

- [ ] **Step 6: Run the existing suites that touch resampling**

Run: `python -m pytest telemetry_tool/tests/test_distance_integrity.py telemetry_tool/tests/test_distance_gate.py -v`
Expected: all pass. These fixtures build laps starting at 0, so they are frame-blind and must be unaffected.

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/resampling.py telemetry_tool/tests/test_distance_frame.py
git commit -m "fix(resampling): rebase every lap to a 0-based per-lap distance frame

RaceChrono exports cumulative session distance and resampling preserved each
lap's absolute range, so corner spans detected on lap 1 matched nothing on
laps 2..N. Measured on OK_R4.csv: 9 of 10 laps returned zero corner samples.

Rebasing at the resampling boundary collapses all frames at once - resampling
runs unconditionally and sits downstream of every producer of frame
heterogeneity (distance_integrity early-returns unchanged on clean GPS)."
```

---

### Task 2: Acceptance test — corner masks populate on every lap

**Files:**
- Modify: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: `resample_lap_by_distance` from Task 1.
- Produces: nothing consumed downstream; this is the headline acceptance gate.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_corner_mask_populates_on_every_lap():
    """The headline bug: corner spans come from ONE lap, masks run on ALL laps.

    Asserts on sample COUNTS, not on the absence of exceptions - the production
    call sites swallow failures (s10b_corners.py:380-382) and return None
    (corner_diagnosis.py:238-241), so an exception-based test passes against
    the bug.
    """
    from resampling import resample_lap_by_distance

    starts = [153.9, 1356.5, 2574.6, 3784.9, 4997.9]      # measured, OK_R4
    ends = [1356.4, 2574.5, 3784.9, 4997.7, 6196.5]
    laps = {
        i + 1: resample_lap_by_distance(_lap(s, e, i + 1), n_points=1000)
        for i, (s, e) in enumerate(zip(starts, ends))
    }

    # corner spans as corner_detection would emit them: taken from ONE lap
    detection_lap = laps[min(laps)]
    d_det = detection_lap["Distance (m)"].values
    corner_spans = [(d_det[100], d_det[160]), (d_det[400], d_det[470])]

    for lap_no, lap in laps.items():
        dist = lap["Distance (m)"].values
        for ci, (s0, s1) in enumerate(corner_spans):
            n = int(((dist >= s0) & (dist <= s1)).sum())
            assert n >= 5, (
                f"lap {lap_no} corner {ci}: {n} samples - "
                "corner_diagnosis bails below 5"
            )
```

- [ ] **Step 2: Run it**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_corner_mask_populates_on_every_lap -v`
Expected: PASS (Task 1 already fixed it).

- [ ] **Step 3: Bite-check**

Temporarily revert `np.linspace(0.0, span, n_points)` to `np.linspace(d_min, d_max, n_points)` in `resampling.py` and re-run.
Expected: RED with `lap 2 corner 0: 0 samples`. Restore.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/tests/test_distance_frame.py
git commit -m "test(resampling): acceptance gate - corner masks populate on every lap"
```

---

### Task 3: Reference line grid is no longer built from one lap

**Files:**
- Modify: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: `resample_lap_by_distance` from Task 1, `reference_line._build_common_grid`.
- Produces: nothing downstream. Documents a free side effect so a future regression is loud.

`reference_line._build_common_grid` (`reference_line.py:245-277`) medians the per-lap starts and ends. Under the old frame that produced a window belonging to the *middle* lap, and `_interpolate_lap_onto_grid`'s `left=nan/right=nan` (`:303-309`) then NaN'd nine laps entirely — so a "10-lap median reference line" was one lap. No code change is needed; the rebase fixes it. This task pins that.

- [ ] **Step 1: Write the test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_reference_grid_covers_all_laps_not_just_the_median_one():
    """Under the old frame the common grid sat in the middle lap's absolute
    window, so _interpolate_lap_onto_grid NaN'd every other lap entirely and
    np.nanmedian silently reduced a 10-lap reference to 1 lap."""
    import numpy as np
    from resampling import resample_lap_by_distance
    from reference_line import _build_common_grid, _interpolate_lap_onto_grid

    starts = [153.9, 1356.5, 2574.6, 3784.9, 4997.9]
    ends = [1356.4, 2574.5, 3784.9, 4997.7, 6196.5]
    laps = {
        i + 1: resample_lap_by_distance(_lap(s, e, i + 1), n_points=500)
        for i, (s, e) in enumerate(zip(starts, ends))
    }

    grid = _build_common_grid(laps)
    assert grid[0] == pytest.approx(0.0, abs=1.0)

    for lap_no, lap in laps.items():
        vals = _interpolate_lap_onto_grid(lap, grid, "Speed (m/s)")
        nan_frac = float(np.isnan(vals).mean())
        assert nan_frac < 0.05, f"lap {lap_no}: {nan_frac:.0%} NaN on the grid"
```

- [ ] **Step 2: Run it**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_reference_grid_covers_all_laps_not_just_the_median_one -v`

If `_build_common_grid` or `_interpolate_lap_onto_grid` have different signatures than assumed, read `telemetry_tool/reference_line.py:245-310` and adjust the call — do NOT change the assertions.

Expected: PASS.

- [ ] **Step 3: Bite-check**

Revert the `resampling.py` linspace to absolute and re-run.
Expected: RED with a high NaN fraction on 4 of 5 laps. Restore.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/tests/test_distance_frame.py
git commit -m "test(reference_line): pin that the common grid now covers every lap"
```

---

### Task 4: Tighten the legacy row-index guard — a NEW corruption path

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:580-588`
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing downstream.

`data_v2.py:580-588` detects the legacy row-index bug via `distances[0] == 0 and abs(distances[-1] - (len(distances) - 1)) < 1.0` and overwrites the trace with a haversine reconstruction. With `n_points=1000` (`s07_resample.py:25`) the second clause means "total length within 1 m of 999 m". Today the first clause is False for laps 2..N because they start near 5 km. **After Task 1 every lap starts at 0**, so any lap ~999 m long is misclassified and silently overwritten. Kart circuits sit squarely in that band.

The real legacy bug is `gps_repo.py:67` (`dists = np.arange(len(df), dtype=float)`), so discriminate on *value* rather than shape.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_999m_lap_is_not_mistaken_for_row_index_distances():
    """A 1000-point trace spanning 999 m is a REAL lap, not the legacy
    row-index bug. Before Task 1 the distances[0] == 0 clause hid this;
    after it, every lap starts at 0 and only the length discriminates."""
    from web.routes.data_v2 import _looks_like_row_index_distances

    real = [i * (999.0 / 999) for i in range(1000)]      # a genuine 999 m lap
    # consistent GPS: ~999 m of real movement
    assert _looks_like_row_index_distances(real, haversine_total=999.4) is False

    # the genuine legacy bug: distances are row indices, GPS says 1240 m
    assert _looks_like_row_index_distances(real, haversine_total=1240.0) is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_999m_lap_is_not_mistaken_for_row_index_distances -v`
Expected: FAIL with `ImportError: cannot import name '_looks_like_row_index_distances'`.

- [ ] **Step 3: Extract and tighten the guard**

Add near the top of `telemetry_tool/web/routes/data_v2.py` (module level, beside the other helpers):

```python
def _looks_like_row_index_distances(
    distances: list[float],
    haversine_total: float | None,
) -> bool:
    """True when a stored distance array is really row indices (0,1,2,...).

    The legacy bug is gps_repo.py:67 writing ``np.arange(len(df))``.  Shape
    alone is not enough to identify it: since every resampled lap is now
    0-based, a genuine ~999 m lap at n_points=1000 has the same shape.  So
    require the GPS-derived length to disagree with the stored length.
    """
    if not distances or len(distances) <= 2:
        return False
    if distances[0] != 0:
        return False
    if abs(distances[-1] - (len(distances) - 1)) >= 1.0:
        return False
    if haversine_total is None or haversine_total <= 0:
        return False
    # Row indices coincidentally matching the real distance is not a bug worth
    # "fixing" - only substitute when the two genuinely disagree.
    return abs(haversine_total - distances[-1]) / haversine_total > 0.10
```

Then guard the substitution. The existing haversine loop ends at `data_v2.py:604` with an unconditional assignment:

```python
                cum.append(cum[-1] + _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
            distances = cum
```

Change that last line to:

```python
                cum.append(cum[-1] + _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
            # Shape alone no longer discriminates: every resampled lap is now
            # 0-based, so a genuine ~999 m lap at n_points=1000 has the same
            # shape as row indices. Only substitute when GPS actually disagrees.
            if _looks_like_row_index_distances(distances, cum[-1] if cum else None):
                distances = cum
```

Note the block at `data_v2.py:606-609` already rebases per-lap distances to start at 0 (`if distances[0] != 0`). Post-fix that becomes an idempotent no-op — leave it, it still protects legacy rows.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_999m_lap_is_not_mistaken_for_row_index_distances -v`
Expected: PASS.

- [ ] **Step 5: Bite-check**

Change the final return in the helper to `return True` and re-run.
Expected: the first assertion goes RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_distance_frame.py
git commit -m "fix(data_v2): discriminate legacy row-index distances by value, not shape

The 0-based rebase makes every lap start at 0, so the old shape heuristic
would silently haversine-overwrite any ~999 m lap at n_points=1000 - which is
most kart circuits. Require the GPS length to actually disagree."
```

---

### Task 5: Delete the `theo_d0` corner-span rebase

**Files:**
- Modify: `telemetry_tool/web/repos/theoretical_repo.py:92-107`
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `corner_coaching` spans are persisted verbatim.

This block subtracts the theoretical lap's first distance from every persisted corner span. Post-Task-1 the theoretical lap is 0-based on all solver paths, so `theo_d0 == 0` and the branch is dead — but it is the single line that has been silently mutating persisted spans into a fifth coordinate frame. Leaving dead code that rewrites persisted data is how the current mixed-frame DB was produced.

Keep the `distance_json` rebase at `:45-52` — it is guarded on `raw_dists[0] != 0` and becomes an idempotent no-op that still protects legacy inputs.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_corner_coaching_spans_are_persisted_verbatim():
    """theoretical_repo must not re-rebase spans that are already 0-based."""
    import inspect
    from web.repos import theoretical_repo

    src = inspect.getsource(theoretical_repo)
    assert "theo_d0" not in src, (
        "theo_d0 rebase still present - it mutates persisted corner spans "
        "into a distinct coordinate frame"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_corner_coaching_spans_are_persisted_verbatim -v`
Expected: FAIL — `theo_d0` is present.

- [ ] **Step 3: Delete the block**

In `telemetry_tool/web/repos/theoretical_repo.py`, replace lines 92-107:

```python
    # Serialize new kart_envelope fields
    # Normalize corner_coaching distances to per-lap 0-based
    corner_coaching = summary.get("corner_coaching")
    if corner_coaching and distance_json:
        # Use the theoretical lap's distance offset for normalization
        theo_d0 = 0.0
        if theo_lap is not None and hasattr(theo_lap, "columns") and dist_col:
            raw = theo_lap[dist_col].values
            if len(raw) > 0:
                theo_d0 = float(raw[0])
        if theo_d0 != 0:
            for cc in corner_coaching:
                for key in ("s_start", "s_end", "s_apex", "distance_start",
                            "distance_end", "distance_apex", "apex_distance_m"):
                    v = cc.get(key)
                    if v is not None and isinstance(v, (int, float)):
                        cc[key] = round(v - theo_d0, 4)
```

with:

```python
    # Corner spans arrive already in the canonical 0-based per-lap frame
    # established in resampling.resample_lap_by_distance, so they are persisted
    # verbatim.  A second rebase here previously produced a distinct fifth
    # coordinate frame in the database.
    corner_coaching = summary.get("corner_coaching")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_corner_coaching_spans_are_persisted_verbatim -v`
Expected: PASS.

- [ ] **Step 5: Verify nothing else referenced it**

Run: `grep -rn "theo_d0" telemetry_tool/`
Expected: no results.

Run: `python -m pytest telemetry_tool/tests/ -q -k "theoretical"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/repos/theoretical_repo.py telemetry_tool/tests/test_distance_frame.py
git commit -m "fix(theoretical_repo): stop rebasing persisted corner spans by theo_d0

Spans now arrive in the canonical 0-based frame. This block was the only
writer that silently mutated persisted spans into a distinct frame."
```

---

### Task 6: Bump `PIPELINE_VERSION` so sessions report themselves stale

**Files:**
- Modify: `telemetry_tool/pipeline_version.py:16`
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PIPELINE_VERSION == 3`; `GET /sessions/stale` now lists pre-fix sessions.

`pipeline_status.compute_pipeline_hash` digests step *names* only, and this change renames no step, so `full_version_string()` would be byte-identical and nothing would ever mark a session stale. The module docstring (`pipeline_version.py:6-9`) instructs exactly this bump.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_pipeline_version_bumped_for_the_frame_change():
    """The structural hash digests step NAMES only, so a change inside
    resampling.py is invisible to it. Without a manual bump, every pre-fix
    session reports itself current forever and nothing gets reprocessed."""
    from pipeline_version import PIPELINE_VERSION, is_stale

    assert PIPELINE_VERSION >= 3
    assert is_stale(2) is True
    assert is_stale(None) is True
    assert is_stale(PIPELINE_VERSION) is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_pipeline_version_bumped_for_the_frame_change -v`
Expected: FAIL — `PIPELINE_VERSION` is 2.

- [ ] **Step 3: Bump it**

In `telemetry_tool/pipeline_version.py`, change line 16:

```python
PIPELINE_VERSION: int = 2
```

to:

```python
# 3: distance frame rebased to 0-based per-lap metres in
#    resampling.resample_lap_by_distance. All prior sessions carry corner
#    spans, grip maps and reference lines built in the old absolute frame
#    and must be reprocessed.
PIPELINE_VERSION: int = 3
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_pipeline_version_bumped_for_the_frame_change -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline_version.py telemetry_tool/tests/test_distance_frame.py
git commit -m "chore(pipeline): bump PIPELINE_VERSION to 3 for the distance frame change"
```

---

### Task 7: Harden `grip_map` binning so a frame regression is loud

**Files:**
- Modify: `telemetry_tool/grip_map.py:229-230`, `telemetry_tool/grip_map.py:249-250`
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing downstream.

`grip_map` takes `bin_edges` from lap 1 and digitises every other lap into them with `np.clip(bin_idx, 0, n_bins - 1)`. Under the old frame laps 2..N did not land out of range — they all landed in the *terminal bin*, poisoning it. Clipping turned a frame bug into plausible-looking data. Replace with a drop so the next regression is visible.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_grip_map_bins_are_not_poisoned_by_out_of_range_samples():
    """np.clip silently dumps every out-of-frame sample into the last bin,
    which is how a frame bug produced a plausible-looking grip map."""
    import inspect
    import grip_map

    src = inspect.getsource(grip_map)
    assert "np.clip(bin_idx" not in src, (
        "grip_map still clips out-of-range bin indices into the terminal bin"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_grip_map_bins_are_not_poisoned_by_out_of_range_samples -v`
Expected: FAIL.

- [ ] **Step 3: Replace clip with a drop**

There are exactly two sites, `grip_map.py:229-232` and `grip_map.py:249-252`, and both are textually identical:

```python
            bin_idx = np.digitize(d_valid, bin_edges) - 1
            bin_idx = np.clip(bin_idx, 0, n_bins - 1)
            for i, m in zip(bin_idx, mu_valid):
                bin_samples[i].append(float(m))
```

Replace **both** with:

```python
            bin_idx = np.digitize(d_valid, bin_edges) - 1
            # Drop rather than clip: clipping dumps every out-of-frame sample
            # into the terminal bin, silently converting a coordinate-frame bug
            # into a plausible-looking grip map.
            _in_range = (bin_idx >= 0) & (bin_idx < n_bins)
            if not _in_range.all():
                logger.warning(
                    "grip_map: dropping %d/%d samples outside the bin range",
                    int((~_in_range).sum()), int(_in_range.size),
                )
            for i, m in zip(bin_idx[_in_range], mu_valid[_in_range]):
                bin_samples[i].append(float(m))
```

`bin_idx` and `mu_valid` are the only two arrays consumed here (they are zipped), so masking both keeps them synchronised. `logger` is already defined at module level.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py -v`
Expected: all pass.

Run: `python -m pytest telemetry_tool/tests/ -q -k "grip"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/grip_map.py telemetry_tool/tests/test_distance_frame.py
git commit -m "fix(grip_map): drop out-of-range samples instead of clipping into the last bin"
```

---

### Task 8: Fence the dead `gate_advanced` gate — pin current behaviour

**Files:**
- Create: `telemetry_tool/tests/test_distance_quality_gate_fence.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

`orchestrator.py:492-495` stores `distance_quality` as a **dict** (via `.to_dict()`), while every consumer gates on `hasattr(distance_quality, "gate_advanced")` — `orchestrator.py:1043/1444/1457`, `s10_theoretical.py:82-86`, `s13_scoring.py:141-143/169-171`. `hasattr` on a dict is always False, so degraded-distance sessions are **never gated today**.

Do **not** repair this here. Repairing it would start suppressing theoretical laps and coaching on sessions that currently emit them — a behaviour change hidden inside a correctness fix. This task pins the current behaviour so a future "helpful" fix is a deliberate, visible decision.

- [ ] **Step 1: Write the test**

Create `telemetry_tool/tests/test_distance_quality_gate_fence.py`:

```python
"""Fence: the distance-quality gate is currently DEAD and must stay that way
until repairing it is a deliberate, separately-reviewed decision.

orchestrator.py stores distance_quality as a dict (.to_dict()) while every
consumer checks hasattr(dq, "gate_advanced").  hasattr on a dict is False, so
degraded sessions are never gated.  Repairing this would start suppressing
theoretical laps and coaching on sessions that currently emit them.
"""


def test_hasattr_gate_is_false_for_a_dict():
    """Documents the mechanism, so the fence below is understandable."""
    dq = {"gate_advanced": True, "monotonic_ratio": 0.4}
    assert hasattr(dq, "gate_advanced") is False


def test_consumers_still_use_hasattr_not_dict_access():
    """If this fails, someone repaired the gate. That may be correct - but it
    is a behaviour change that must ship on its own branch with its own
    review, not inside a coordinate-frame fix."""
    import inspect
    from pipeline.stages import s10_theoretical

    src = inspect.getsource(s10_theoretical)
    assert 'hasattr(' in src and 'gate_advanced' in src, (
        "the distance-quality gate appears to have been changed - see the "
        "module docstring in this file before accepting"
    )
```

- [ ] **Step 2: Run it**

Run: `python -m pytest telemetry_tool/tests/test_distance_quality_gate_fence.py -v`
Expected: PASS.

- [ ] **Step 3: Bite-check**

In `telemetry_tool/pipeline/stages/s10_theoretical.py`, temporarily change the `hasattr(...)` gate to `distance_quality.get("gate_advanced")` and re-run.
Expected: `test_consumers_still_use_hasattr_not_dict_access` goes RED. Restore.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/tests/test_distance_quality_gate_fence.py
git commit -m "test(pipeline): fence the dead distance-quality gate against drive-by repair"
```

---

### Task 9: Remove the frontend frame compensations

**Files:**
- Modify: `lap-website/src/components/app/corners/TheoreticalBestPanel.tsx:89-145`
- Modify: `lap-website/src/components/app/corners/TrackMapView.tsx:38-51`

**Interfaces:**
- Consumes: API corner spans, now 0-based.
- Produces: nothing downstream.

Both components carry hand-rolled compensations for the old frame, with the wrong assumption written into their comments. Post-fix both degrade to no-ops for normal corners — which is exactly why they must be **deleted** rather than left: a guarded no-op will hide the next regression.

One genuine exception: `corner_detection.py:657-661` emits one merged wrap-around region per closed circuit with `s_start > s_end`, which can exceed the lap length. `TheoreticalBestPanel`'s `lapOffset` does **not** degrade to a no-op for that corner, so deleting it changes that corner's rendering. That corner's mask is empty in every frame (see §"Known not-fixed" below) so this is not a regression.

- [ ] **Step 1: Read both files**

Run: `sed -n '85,150p' lap-website/src/components/app/corners/TheoreticalBestPanel.tsx`
Run: `sed -n '30,55p' lap-website/src/components/app/corners/TrackMapView.tsx`

- [ ] **Step 2: Delete the `lapOffset` compensation**

In `TheoreticalBestPanel.tsx`, remove the `lapOffset` computation and every use of it, so corner distances are used directly. Replace the compensation with a one-line comment:

```tsx
// Corner spans are 0-based per-lap metres (canonical frame, see
// resampling.resample_lap_by_distance). No offset compensation needed.
```

- [ ] **Step 3: Delete the modulo wrap**

In `TrackMapView.tsx`, remove the `apex > dMax` modulo wrap and its comment about "multi-lap cumulative" values, replacing with:

```tsx
// s_apex is 0-based per-lap metres; no wrap needed.
```

- [ ] **Step 4: Typecheck and build**

Run: `cd lap-website && npm run lint`
Expected: no new errors.

Run: `cd lap-website && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add lap-website/src/components/app/corners/TheoreticalBestPanel.tsx lap-website/src/components/app/corners/TrackMapView.tsx
git commit -m "fix(webapp): drop the frontend distance-frame compensations

Both assumed the API served cumulative multi-lap distances. Spans are now
0-based per-lap metres. Deleted rather than left as guarded no-ops, which
would hide the next regression."
```

---

### Task 10: Invalidate the chart cache on reprocess

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py` (reprocess path)
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: `chart_cache.invalidate_session_cache`.
- Produces: nothing downstream.

`/corners`, `/speed-trace`, `/gps-trace` and `/delta` are `@chart_cached(ttl=3600)`. `chart_cache.invalidate_session_cache` has exactly one caller — the session DELETE path (`data_v2.py:1568-1571`). Nothing invalidates on reprocess, so a reprocessed session serves the pre-fix frame for up to an hour.

- [ ] **Step 1: Find the reprocess path**

Run: `grep -n "reprocess" telemetry_tool/web/routes/data_v2.py | head -20`
Run: `grep -n "invalidate_session_cache" telemetry_tool/web/ -r`

- [ ] **Step 2: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_reprocess_invalidates_the_chart_cache():
    """Chart endpoints are cached for an hour. Without invalidation a
    reprocessed session keeps serving the pre-fix distance frame."""
    import inspect
    from web.routes import data_v2

    src = inspect.getsource(data_v2)
    # the DELETE path already calls it; require at least two call sites
    assert src.count("invalidate_session_cache(") >= 2, (
        "reprocess path does not invalidate the chart cache"
    )
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_reprocess_invalidates_the_chart_cache -v`
Expected: FAIL — only one call site.

- [ ] **Step 4: Add the call**

In the reprocess handler identified in Step 1, immediately after the reprocess job is dispatched, add:

```python
    # The distance frame (and everything derived from it) changes on reprocess;
    # chart endpoints are cached for an hour and would otherwise keep serving
    # the previous frame.
    chart_cache.invalidate_session_cache(session_id)
```

Match the import style already used at `data_v2.py:1568-1571`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_reprocess_invalidates_the_chart_cache -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_distance_frame.py
git commit -m "fix(data_v2): invalidate the chart cache when a session is reprocessed"
```

---

### Task 11: Stop swallowing per-lap corner failures silently

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s10b_corners.py:380-382`
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `run_per_lap_corner_metrics` logs a per-lap failure count at WARNING.

The per-lap loop ends with `except Exception as exc: logger.debug(...); continue`. At DEBUG level, in production, a total failure of every lap is invisible — which is how this bug survived. The fix does not change control flow; it makes the silence audible.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_per_lap_corner_failures_are_reported_not_silently_swallowed():
    """A total per-lap failure must not be invisible at production log level."""
    import inspect
    from pipeline.stages import s10b_corners

    src = inspect.getsource(s10b_corners.run_per_lap_corner_metrics)
    assert "logger.warning" in src, (
        "per-lap corner failures are still only logged at debug level"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_per_lap_corner_failures_are_reported_not_silently_swallowed -v`
Expected: FAIL.

- [ ] **Step 3: Count and report**

In `telemetry_tool/pipeline/stages/s10b_corners.py`, initialise a counter beside the existing `results` list at the top of the loop body's enclosing function, then change lines 380-382:

```python
        except Exception as exc:
            logger.debug("Corner analysis for lap %s: %s", lap_num, exc)
            continue
```

to:

```python
        except Exception as exc:
            _failed_laps.append(lap_num)
            logger.debug("Corner analysis for lap %s: %s", lap_num, exc)
            continue
```

and immediately before the existing `if results:` summary block, add:

```python
    if _failed_laps:
        logger.warning(
            "Per-lap corner metrics: %d/%d laps produced nothing (%s)",
            len(_failed_laps), len(_failed_laps) + len(set(
                m["lap_number"] for m in results
            )), _failed_laps[:10],
        )
```

Declare `_failed_laps: list = []` alongside `results`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10b_corners.py telemetry_tool/tests/test_distance_frame.py
git commit -m "fix(s10b_corners): report per-lap corner failures at warning level

A total failure of every lap was previously invisible in production - which is
how the distance-frame bug survived undetected."
```

---

### Task 12: Persist the data-quality report

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py:926`
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `summary["data_quality"]` is now a `dict`, so `analysis_json.data_quality_summary` is written for the first time.

`summary["data_quality"]` holds a `DataQualityReport` dataclass, while both persistence paths gate on `isinstance(dq, dict)` (`tasks/pipeline_tasks.py:562-563`, `web/routes/sessions_v2.py:269-270`). So the key is never written.

**Critical:** convert only the summary entry. The local `data_quality_rpt` is passed as an *object* to many consumers that use attribute access (`s10_theoretical.py:161,302-303`, `orchestrator.py:1150`). Converting the local would break all of them.

`contract_adapter/session.py:157-160` already handles both dict and object, so it is unaffected.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_data_quality_is_summarised_as_a_dict_for_persistence():
    """Both persistence paths gate on isinstance(dq, dict), so a dataclass
    means analysis_json.data_quality_summary is never written."""
    import inspect
    from pipeline import orchestrator

    src = inspect.getsource(orchestrator)
    assert 'summary["data_quality"] = data_quality_rpt\n' not in src, (
        "summary['data_quality'] still holds the dataclass; persistence "
        "gates on isinstance(dq, dict) and will skip it"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_data_quality_is_summarised_as_a_dict_for_persistence -v`
Expected: FAIL.

- [ ] **Step 3: Convert only the summary entry**

In `telemetry_tool/pipeline/orchestrator.py`, change line 926:

```python
    summary["data_quality"] = data_quality_rpt
```

to:

```python
    # Persistence gates on isinstance(dq, dict) in both pipeline_tasks.py and
    # sessions_v2.py, so the summary carries the serialised form.  The local
    # data_quality_rpt stays an object - s10_theoretical and the scoring stages
    # reach into it by attribute.
    summary["data_quality"] = (
        data_quality_rpt.to_dict()
        if data_quality_rpt is not None and hasattr(data_quality_rpt, "to_dict")
        else data_quality_rpt
    )
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py -v`
Expected: all pass.

Run: `python -m pytest telemetry_tool/tests/ -q -k "quality or theoretical or scoring"`
Expected: all pass — this is the check that no attribute-access consumer was broken.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/orchestrator.py telemetry_tool/tests/test_distance_frame.py
git commit -m "fix(orchestrator): serialise data_quality into the summary so it persists

Both persistence paths gate on isinstance(dq, dict) while the summary held the
dataclass, so analysis_json.data_quality_summary was never written. The local
report object is unchanged - downstream stages read it by attribute."
```

---

### Task 13: Pass `best_lap_number` into the v2 handling analysis

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py:1233-1236`
- Test: `telemetry_tool/tests/test_distance_frame.py`

**Interfaces:**
- Consumes: `summary["best_lap"]` (or the equivalent key found in Step 1).
- Produces: `run_handling_analysis_v2` receives the real best lap number.

`s10b_corners.py:759-760` defaults `best_lap_number` to `1` when not supplied, and the orchestrator never supplies it (`orchestrator.py:1233-1236` passes only `v2_sections`, `best_lap_df`, `available_columns`). So the handling ensemble masks on lap 1 while `best_lap_df` is the *actual* best lap — mismatched whenever the best lap is not lap 1.

- [ ] **Step 1: Find the best-lap key**

Run: `grep -n 'best_lap' telemetry_tool/pipeline/orchestrator.py | head -20`

Identify the variable holding the best lap number near `orchestrator.py:836`. Use that exact name in Step 3.

- [ ] **Step 2: Write the failing test**

Append to `telemetry_tool/tests/test_distance_frame.py`:

```python
def test_handling_v2_receives_the_real_best_lap_number():
    """s10b_corners defaults best_lap_number to 1, so the handling ensemble
    masked lap 1 while best_lap_df was the actual best lap."""
    import inspect
    from pipeline import orchestrator

    src = inspect.getsource(orchestrator)
    idx = src.find("run_handling_analysis_v2")
    assert idx != -1
    call = src[idx:idx + 400]
    assert "best_lap_number" in call, (
        "run_handling_analysis_v2 is still called without best_lap_number"
    )
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py::test_handling_v2_receives_the_real_best_lap_number -v`
Expected: FAIL.

- [ ] **Step 4: Pass it through**

In `telemetry_tool/pipeline/orchestrator.py`, change lines 1233-1236:

```python
        v2_handling, err = _safe_step(
            "10g3_handling_v2", s10b_corners.run_handling_analysis_v2,
            v2_sections, best_lap_df, available_columns=_avail_cols,
        )
```

to (substituting the variable name found in Step 1 for `best_lap_num`):

```python
        v2_handling, err = _safe_step(
            "10g3_handling_v2", s10b_corners.run_handling_analysis_v2,
            v2_sections, best_lap_df, available_columns=_avail_cols,
            best_lap_number=best_lap_num,
        )
```

If `run_handling_analysis_v2`'s signature does not accept `best_lap_number` as a keyword, read `s10b_corners.py:740-770` and add it as a keyword-only parameter defaulting to `None`, preserving the existing `if best_lap_number is None: best_lap_number = 1` fallback.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest telemetry_tool/tests/test_distance_frame.py -v`
Expected: all pass.

Run: `python -m pytest telemetry_tool/tests/ -q -k "handling"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/pipeline/orchestrator.py telemetry_tool/pipeline/stages/s10b_corners.py telemetry_tool/tests/test_distance_frame.py
git commit -m "fix(orchestrator): pass the real best lap number to handling analysis v2

It defaulted to lap 1 while best_lap_df was the actual best lap, so the
handling ensemble masked the wrong lap whenever they differed."
```

---

### Task 14: Full suite, real-data verification, and the deploy runbook

**Files:**
- Create: `docs/runbooks/per-lap-distance-frame-deploy.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the deploy procedure.

- [ ] **Step 1: Run the full backend suite**

Run: `python -m pytest telemetry_tool/tests/ -q`
Expected: no NEW failures relative to the pre-change baseline. Capture the baseline first:

```bash
git stash && python -m pytest telemetry_tool/tests/ -q 2>&1 | tail -5 > /tmp/baseline.txt && git stash pop
python -m pytest telemetry_tool/tests/ -q 2>&1 | tail -5
```

Compare. Any newly-failing test must be investigated, not accepted.

- [ ] **Step 2: Verify on real data**

Run the probe from the design phase against the fixed code:

```bash
python -c "
import sys; sys.path.insert(0,'telemetry_tool')
import pandas as pd, numpy as np
from resampling import resample_lap_by_distance
from derived_channels import compute_yaw_rate_from_heading
import corner_detection
df = pd.read_csv('telemetry_tool/data/raw/OK_R4.csv', skiprows=10, low_memory=False)
df = df[np.isfinite(pd.to_numeric(df['Lap #'], errors='coerce'))]
laps = {int(k): compute_yaw_rate_from_heading(g.reset_index(drop=True)) for k,g in df.groupby('Lap #')}
rs = {n: resample_lap_by_distance(g, n_points=1000) for n,g in laps.items()}
first = sorted(rs)[0]
corners = corner_detection.detect_corners(rs[first])
for n in sorted(rs):
    d = rs[n]['Distance (m)'].values
    tot = sum(int(((d>=c['s_start'])&(d<=c['s_end'])).sum()) for c in corners)
    print('lap', n, 'corner samples', tot)
"
```

Expected: **every** lap reports ~270+ corner samples. Before the fix, 9 of 10 reported 0.

- [ ] **Step 3: Write the deploy runbook**

Create `docs/runbooks/per-lap-distance-frame-deploy.md` covering, in order:

1. **Pre-deploy decision — `user_corners` (BLOCKING).** The table has no frame column and the route stores client values verbatim, so existing rows are in the old absolute frame. User corners **override** auto corners (`orchestrator.py:1271`: `_diagnosis_corners = user_corner_rows or corners`), so ignoring this makes exactly the sessions an operator inspected get *worse*. Its only in-repo writer, `CornerDefiner.tsx`, is exported at `charts/index.ts:12` and mounted nowhere, so the prod population is likely operator-only. **Count the prod rows first**, then either truncate or add a `frame` column defaulting to `legacy_absolute` and normalise on read.
2. **Drain in-flight pipeline state.** Jobs paused at `awaiting_corner_selection` hold old-frame corners in Redis for 7200 s (`pipeline_tasks.py:851-863`). Drain `pipeline:corners:*` and `pipeline:layout:*`, and reject `_load_intermediate_state` parquet whose `Distance (m)[0] > 1.0` — a mid-deploy resume would otherwise mix frames with no marker.
3. **Deploy backend** per `lap_web/CLAUDE.md`: `scp` → `docker compose -f docker-compose.prod.yml build api && up -d api` (build, never restart — source is COPY'd into the image) → `curl https://api.lap-coach.racing/healthz`.
4. **Deploy frontend:** `cd lap-website && npm run cf:deploy`.
5. **Flush `chart:*` in Redis.**
6. **Reprocess** via `onboarding/reprocess.py:278-336`. **Do not use `scripts/reprocess_theoretical.py`** — it imports `build_curvature_from_laps` from `pipeline.helpers`, a symbol that does not exist in the tree, so it no-ops on every session.
7. **Data that reprocessing is required for, because it is corrupted rather than merely offset:** `grip_map.distance_bins` + `bin_stats` (laps 2..N were clipped into the terminal bin); `reference_lines` (nine of ten laps contributed all-NaN, so a "10-lap median" was one lap); `corner_metrics` rows for laps 2..N (`throttle_onset_m`, `brake_intensity`, `exit_accel_mps2` are NULL). A number-shifting migration would leave these wrong while making them look repaired.
8. **`track_surfaces` / `track_surfaces_global` require destructive re-aggregation** — their `ON CONFLICT (track_id, distance_m, ...)` merge destroyed the contributing sessions' offsets, so post-fix sessions create a second disjoint bin grid alongside the legacy one.
9. **Verification:** pick three prod sessions, confirm `GET /sessions/<id>/corners` returns `s_start` values below the lap length, and confirm per-lap corner metrics are populated for laps 2..N.

- [ ] **Step 4: Commit**

```bash
git add docs/runbooks/per-lap-distance-frame-deploy.md
git commit -m "docs(runbook): deploy procedure for the per-lap distance frame fix"
```

---

## Known not-fixed

State these explicitly so nobody assumes otherwise:

- **`corner_diagnosis._extract_theo_metrics` stays dead.** It requires literal `"Distance (m)"` / `"Speed (m/s)"` on the theoretical lap (`corner_diagnosis.py:210-211, 736-737`), but the theoretical DataFrame's columns are `distance_m` / `v_env_mps` (`theoretical_engine.py:112-113`). Not a frame bug. Fixing the column names *without* the frame fix would just move the failure to `:745`'s `mask.sum() < 3`.
- **The wrap-around corner stays broken in every frame.** `corner_detection.py:657-661` emits one merged region per closed circuit with `s_start > s_end`, so every `(d >= s_start) & (d <= s_end)` mask is empty for it. One corner per circuit remains dead.
- **Corners are still detected from one lap** (`s07_resample.py:82-83`). The prize is that the *choice* of lap stops mattering for coordinates; a lap-1 anomaly still defines the session's corner set. Consensus detection is separate work.
- **The `gate_advanced` gate stays dead** — deliberately fenced in Task 8.
- **`distance_quality` still never reaches `sessions.analysis_json`**, so `GET /sessions/<id>/distance-quality` stays 404.
- **Track-surface `s` is not reconcilable by any rebase.** It is centreline arc length over the GT centreline; RaceChrono distance is GPS path length along the *driven* line. Different totals, different origins, error accumulating along `s`. That needs an explicit `s↔s` mapping, not an offset.
- **Five latent consumers stay frame-stale but inert.** `analysis_json["corners"]` is never written by the SaaS pipeline, so `ocp_tasks.py:459/490/607/723`, `data_v2.py:6256` and `data_v2.py:6550` do not run today. They revive the moment anyone persists corners — and `np.interp` clamps rather than raises, so a revived `ocp_tasks` would *poison the solver model* silently rather than crash.
