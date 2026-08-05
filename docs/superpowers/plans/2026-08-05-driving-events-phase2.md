# Driving Events (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a located, named, quantified driver mistake in front of a customer — every corner-lap priced in seconds against that driver's own best pass through the same corner.

**Architecture:** Two retroactive fixes to Phase 1's stage, then a per-corner-lap *time* measurement reusing the existing `_integrate_time`, then a `DrivingEvent` record persisted to a new RLS table, four detectors that emit it, and two read surfaces over the same records — a ranked "where the time went" list and a per-corner consistency aggregate.

**Tech Stack:** Python 3.14, numpy, pandas, pytest, Alembic, SQLite (tests) / PostgreSQL (prod).

**Branch:** `feat/driving-pattern-recognition`, worktree `C:\Users\Admin\lap_web-wt-patterns`.

**Spec:** `docs/superpowers/specs/2026-08-04-driving-pattern-recognition-design.md` §5.1, §5.5, §5.6, §5.7.

## Global Constraints

- **Tests import BARE module names** (`import driving_events as de`), never `from telemetry_tool...`. `telemetry_tool/tests/conftest.py` puts the project root on `sys.path`.
- **Run tests from the repo root:** `python -m pytest telemetry_tool/tests/... -v`.
- **Bite-check every test.** Break the code it guards, confirm RED, restore, confirm GREEN, report the exact red output. A test that cannot fail is worse than none — six such tests were caught during Phase 1 by mutating code and watching the suite stay green.
- **After any test run check `git status --short`** — only gitignored cache paths may appear. Tests dirtying tracked files has happened three times in this lineage.
- **NO CONFIDENCE FLOAT.** A `DrivingEvent` carries a mandatory `evidence` dict, a validity tier, and `n_samples_in_window`. Rank by measured seconds. The reasoning is in the spec §5.5 — `handling/`'s confidence is circularly calibrated and three of its detectors push the posterior the wrong way.
- **Never invent a magnitude.** If a window is too short or a channel absent, emit `Insufficient` with the missing field named — never a plausible-looking number.
- **Reuse `corner_analysis._integrate_time` and `_slice_range`** (`corner_analysis.py:337-356`). Do not write a second `dt = ds/v` integrator; two will disagree.
- **Reuse `grip_anchor`'s vocabulary** for validity/reason values. One honesty vocabulary across both phases.
- Do NOT build: `over_braking`, `envelope_exceedance`, `corner_rounding`, `handling/` understeer-oversteer, `coast_gap`, a shape-primitive library, new `causes.json` entries. Each is cut in spec §5.5 with a reason.
- No drive-by refactors. Commit after every task, conventional prefixes.

## Measured facts this plan is built on

From `scratchpad/probe_phase2_detectors.py` over `data/raw/OK_R4.csv` (54 corner-laps, 9 racing laps, 6 corners):

| Fact | Value | Consequence |
|---|---|---|
| `over_slowing` fire rate | 57% | rank, don't flag |
| `late_throttle` fire rate | 68% | rank, don't flag |
| `re_braking` fire rate | **7%** | rare enough to flag |
| time cost distribution | mostly 0.05–0.4 s, worst **0.885 s** | plausible; this is the ranking key |
| absolute-vs-`distance_norm` corner-time delta | median **0.0665 s**, max **2.682 s** | frame noise EXCEEDS the signal — Task 2 is mandatory |
| lap spans | 1198.7–1218.0 m; truncated lap 10 = 1064.3 m | lap 10 wins "best" everywhere under normalised slicing — Task 1 is mandatory |
| per-corner-best composite | 0.121 s under the real best lap | small; the composite-lap caveat is real but minor |

---

## File Structure

| File | Responsibility |
|---|---|
| `telemetry_tool/pipeline/stages/s10d2_grip_anchor.py` (modify) | Tasks 1–3: honour `excluded_laps`, slice on `distance_norm`, measure per-corner-lap time |
| `telemetry_tool/driving_events.py` (new) | Pure: `DrivingEvent`, validity vocabulary, the detector protocol, the four detectors. No I/O. |
| `telemetry_tool/pipeline/stages/s10d3_driving_events.py` (new) | Thin stage: run the registry over corner-lap windows, return events |
| `telemetry_tool/alembic/versions/086_driving_events.py` (new) | The table |
| `telemetry_tool/db/schema.py` (modify) | `PHASE_25_TABLES` + `ALL_TABLES` |
| `telemetry_tool/db/queries.py` (modify) | INSERT + the two read queries |
| `telemetry_tool/web/repos/events_repo.py` (new) | Writer + the two readers |
| `telemetry_tool/web/routes/data_v2.py` (modify) | Two endpoints |
| `telemetry_tool/tests/test_driving_events.py` (new) | Pure-module tests |
| `telemetry_tool/tests/test_driving_events_pipeline.py` (new) | Stage, persistence, endpoints, real-data acceptance |

---

### Task 1: Honour `excluded_laps` in the grip anchor

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s10d2_grip_anchor.py`
- Modify: `telemetry_tool/pipeline/orchestrator.py` (the `10d2_grip_anchor` `_safe_step` call)
- Test: `telemetry_tool/tests/test_grip_anchor_pipeline.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `run_grip_anchor(..., excluded_laps: frozenset[int] = frozenset())` — laps in that set contribute neither a peak nor a session best.

This is a **defect in shipped Phase 1 code**. `run_grip_anchor` never receives `excluded_laps`, so its per-corner `session_best` peak loop iterates every resampled lap — while stage 10d honours the exclusion (`s10b_corners.py:362`). Measured consequence on real data: the truncated final lap (1064 m against ~1200 m) contributes corners mapped to the wrong tarmac and wins "best" almost everywhere.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor_pipeline.py`:

```python
def test_grip_anchor_ignores_excluded_laps_when_choosing_the_session_best():
    """An excluded lap must not set the per-corner reference. On real data the
    truncated final lap otherwise wins 'best' at almost every corner."""
    from pipeline.stages import s10d2_grip_anchor

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0}]

    # lap 2 is excluded but has a much higher lateral peak
    laps = {
        1: _lap_frame(a_lat_g=0.9),
        2: _lap_frame(a_lat_g=2.0),
    }

    out = s10d2_grip_anchor.run_grip_anchor(
        metrics, corners, laps, excluded_laps=frozenset({2}),
    )
    # lap 1 is the only admissible lap, so it IS the session best -> 100%
    assert out[0]["grip_anchor_pct"] == pytest.approx(100.0, abs=0.5)


def test_grip_anchor_uses_an_excluded_lap_if_not_told_to_exclude_it():
    """Control: without the exclusion, lap 2's higher peak becomes the
    reference and lap 1 scores below 100. This is what pins the fix."""
    from pipeline.stages import s10d2_grip_anchor

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0}]
    laps = {1: _lap_frame(a_lat_g=0.9), 2: _lap_frame(a_lat_g=2.0)}

    out = s10d2_grip_anchor.run_grip_anchor(metrics, corners, laps)
    assert out[0]["grip_anchor_pct"] < 60.0     # 0.9 / 2.0
```

If `_lap_frame` is not already a module-level helper in that file, read the file and reuse whatever fixture builder exists — do not define a second one.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -k excluded_laps -v`
Expected: FAIL — `run_grip_anchor() got an unexpected keyword argument 'excluded_laps'`.

- [ ] **Step 3: Implement**

Add `excluded_laps: frozenset[int] = frozenset()` as a keyword-only parameter to `run_grip_anchor`, and skip excluded laps in the peak-accumulation loop (around `s10d2_grip_anchor.py:102`), matching how `s10b_corners.py:362` does it. Read both first.

- [ ] **Step 4: Pass it from the orchestrator**

In `telemetry_tool/pipeline/orchestrator.py`, add `excluded_laps=excluded_laps` to the `10d2_grip_anchor` `_safe_step` call. Verify that variable name is what is actually in scope there — the neighbouring `10d_per_lap_corners` call passes it positionally, so read lines 1180–1210 and match.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -v`
Expected: all pass.

- [ ] **Step 6: Bite-check**

Remove the exclusion check from the peak loop. Re-run.
Expected: `test_grip_anchor_ignores_excluded_laps_when_choosing_the_session_best` goes RED. Restore.

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10d2_grip_anchor.py telemetry_tool/pipeline/orchestrator.py telemetry_tool/tests/test_grip_anchor_pipeline.py
git commit -m "fix(grip_anchor): honour excluded_laps when choosing the per-corner session best

Stage 10d already excluded them; the anchor did not, so a truncated or
outlier lap could set the reference for every corner."
```

---

### Task 2: Slice corner windows on `distance_norm`

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s10d2_grip_anchor.py` (`_corner_mask`)
- Test: `telemetry_tool/tests/test_grip_anchor_pipeline.py`

**Interfaces:**
- Consumes: `distance_norm`, present in every resampled lap (`resampling.py:227`), currently read by nothing.
- Produces: `_corner_mask` slices on the normalised axis; corner spans are converted once, at that boundary.

**Why this is mandatory, not a refinement.** Each lap is rebased to its own span (`resampling.py:211-226`), and real lap spans on OK_R4 range 1198.7–1218.0 m. So the same tarmac drifts up to ~19 m between racing laps — 20–60% of a 30–90 m corner's width. Measured: switching frames changes corner time by a **median of 0.0665 s and up to 2.682 s**, against a detection threshold of 0.05 s. The frame error is larger than the signal.

Corners carry absolute `s_start`/`s_end` from the detection lap, so convert: `n = (s - d_min_det) / (d_max_det - d_min_det)`, then mask `distance_norm` in `[n_start, n_end]`.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor_pipeline.py`:

```python
def test_corner_window_is_frame_stable_across_laps_of_different_length():
    """Two laps of the same circuit driven at different measured lengths must
    yield the same corner window in FRACTION of the lap, not the same window
    in absolute metres. Real laps on OK_R4 span 1198.7-1218.0 m."""
    from pipeline.stages import s10d2_grip_anchor

    def _lap_of_length(total_m, n=1000):
        d = np.linspace(0.0, total_m, n)
        return pd.DataFrame({
            "Distance (m)": d,
            "distance_norm": d / total_m,
            "Speed (m/s)": np.full(n, 25.0),
            "Lateral acceleration (G) *calc": np.full(n, 0.9),
        })

    short, long = _lap_of_length(1000.0), _lap_of_length(1200.0)
    corner = {"corner_id": 1, "s_start": 250.0, "s_end": 350.0}   # 25%-35%

    m_short = s10d2_grip_anchor._corner_mask(short, corner, short)
    m_long = s10d2_grip_anchor._corner_mask(long, corner, short)

    assert m_short is not None and m_long is not None
    # Same FRACTION of each lap -> sample counts within one of each other.
    assert abs(int(m_short.sum()) - int(m_long.sum())) <= 1

    # And the long lap's window really is further along in metres.
    d_long = long["Distance (m)"].values[m_long]
    assert d_long.min() == pytest.approx(300.0, abs=5.0)   # 25% of 1200
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -k frame_stable -v`
Expected: FAIL — either on the signature (`_corner_mask` currently takes two arguments) or on the sample-count assertion.

- [ ] **Step 3: Implement**

Change `_corner_mask(lap_df, corner)` to `_corner_mask(lap_df, corner, detection_lap)` and slice on `distance_norm`:

```python
def _corner_mask(lap_df, corner, detection_lap):
    """Corner windows are sliced on distance_norm, not absolute metres.

    Each lap is rebased to its own span (resampling.py:211-226) and real lap
    spans vary by ~20 m across a session, so the same tarmac drifts. Measured
    on OK_R4: absolute-metre slicing shifts corner time by a median of 0.067 s
    and up to 2.68 s -- larger than the signal we are trying to detect.
    """
    det_col = next((c for c in ("Distance (m)", "distance_m")
                    if c in detection_lap.columns), None)
    if det_col is None or "distance_norm" not in lap_df.columns:
        return None
    dd = pd.to_numeric(detection_lap[det_col], errors="coerce").values
    d_min, d_max = float(np.nanmin(dd)), float(np.nanmax(dd))
    span = d_max - d_min
    if not np.isfinite(span) or span <= 0:
        return None
    try:
        n0 = (float(corner.get("s_start", 0.0)) - d_min) / span
        n1 = (float(corner.get("s_end", 0.0)) - d_min) / span
    except (TypeError, ValueError):
        return None

    dn = pd.to_numeric(lap_df["distance_norm"], errors="coerce").values
    mask = (dn >= n0) & (dn <= n1)
    return mask if mask.sum() >= 3 else None
```

Update both call sites in the file to pass the detection lap. The detection lap is the one corners were detected on — `sorted(resampled_laps)[0]` (see `s07_resample.py:82-83`). Derive it once at the top of `run_grip_anchor` and thread it.

**Fall back safely:** if `distance_norm` is missing (an older cached frame), return None rather than silently reverting to absolute metres — a silent frame switch is exactly what this task removes.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py telemetry_tool/tests/test_grip_anchor.py -v`
Expected: all pass. If a Phase-1 test now fails because the window moved, that is expected — read it, confirm the new value is right, and update the expectation. **Never change a threshold to make a test pass.**

- [ ] **Step 5: Bite-check**

Revert `_corner_mask` to slice `Distance (m)` absolutely. Re-run.
Expected: `test_corner_window_is_frame_stable_across_laps_of_different_length` goes RED. Restore.

- [ ] **Step 6: Re-run the real-data acceptance test**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -k real_kart -v -s`
Report the tier distribution. It may shift from the Phase-1 baseline of `{session_envelope_ellipse_fitted: 57, driver_best_session: 15}` — that is fine and expected, since the windows moved. Report the new numbers; do NOT tune anything to restore the old ones.

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10d2_grip_anchor.py telemetry_tool/tests/test_grip_anchor_pipeline.py
git commit -m "fix(grip_anchor): slice corner windows on distance_norm, not absolute metres

Lap spans vary ~20 m across a session so absolute slicing drifts off the
tarmac. Measured: median corner-time error 0.067 s, max 2.68 s -- larger
than the 0.05 s signal."
```

---

### Task 3: Per-corner-lap time and the per-corner session best

**Files:**
- Modify: `telemetry_tool/pipeline/stages/s10d2_grip_anchor.py`
- Test: `telemetry_tool/tests/test_grip_anchor_pipeline.py`

**Interfaces:**
- Consumes: `corner_analysis._integrate_time`, `_corner_mask` from Task 2.
- Produces: each corner-lap metric dict gains `corner_time_s: float | None` and `corner_time_best_s: float | None`; the stage returns them alongside the existing `grip_anchor_*` keys.

This is the ranking key for everything downstream. `_integrate_time(dist, speed)` (`corner_analysis.py:346-356`) is pure, theoretical-free, and does not clamp — the clamps live in its callers. Reuse it exactly.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor_pipeline.py`:

```python
def test_corner_time_is_measured_and_referenced_to_the_session_best():
    """Each corner-lap gets its own traversal time and the best time any
    admissible lap achieved through the same corner."""
    from pipeline.stages import s10d2_grip_anchor

    def _lap_at(speed, n=1000, total=1000.0):
        d = np.linspace(0.0, total, n)
        return pd.DataFrame({
            "Distance (m)": d,
            "distance_norm": d / total,
            "Speed (m/s)": np.full(n, speed),
            "Lateral acceleration (G) *calc": np.full(n, 0.9),
        })

    corners = [{"corner_id": 1, "s_start": 250.0, "s_end": 350.0}]
    metrics = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 20.0},
    ]
    laps = {1: _lap_at(10.0), 2: _lap_at(20.0)}

    out = s10d2_grip_anchor.run_grip_anchor(metrics, corners, laps)
    by_lap = {m["lap_number"]: m for m in out}

    # 100 m at 10 m/s = 10 s; at 20 m/s = 5 s.
    assert by_lap[1]["corner_time_s"] == pytest.approx(10.0, rel=0.02)
    assert by_lap[2]["corner_time_s"] == pytest.approx(5.0, rel=0.02)
    # Both rows carry the SAME best -- the fastest admissible pass.
    assert by_lap[1]["corner_time_best_s"] == pytest.approx(5.0, rel=0.02)
    assert by_lap[2]["corner_time_best_s"] == pytest.approx(5.0, rel=0.02)


def test_corner_time_is_none_when_the_window_is_unusable():
    from pipeline.stages import s10d2_grip_anchor

    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0}]
    out = s10d2_grip_anchor.run_grip_anchor(metrics, [], {})
    assert out[0]["corner_time_s"] is None
    assert out[0]["corner_time_best_s"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -k corner_time -v`
Expected: FAIL — `KeyError: 'corner_time_s'`.

- [ ] **Step 3: Implement**

In `run_grip_anchor`, in the same per-(corner, lap) loop that already computes the lateral peak, also compute the traversal time:

```python
from corner_analysis import _integrate_time
...
            d_win = pd.to_numeric(lap_df[dist_col], errors="coerce").values[mask]
            v_win = pd.to_numeric(lap_df[speed_col], errors="coerce").values[mask]
            t = float(_integrate_time(d_win, v_win))
            if np.isfinite(t) and t > 0:
                corner_time[(cid, lap_num)] = t
```

Then reduce to a per-corner best (`min`) exactly as the lateral peak reduces to a max, and attach both to every metric dict — `None` when absent. Excluded laps must contribute to neither, per Task 1.

`_integrate_time` returns `0.0` when it cannot integrate (fewer than 2 usable samples), so treat `0.0` as absent rather than as a real time — a zero-second corner is not a measurement.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py telemetry_tool/tests/test_grip_anchor.py -v`
Expected: all pass.

- [ ] **Step 5: Bite-check**

Change the reduction from `min` to `max`. Re-run.
Expected: the session-best assertions go RED (best becomes 10.0, not 5.0). Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10d2_grip_anchor.py telemetry_tool/tests/test_grip_anchor_pipeline.py
git commit -m "feat(grip_anchor): measure per-corner-lap time and the per-corner session best"
```

---

### Task 4: Migration 086 and the `driving_events` table

**Files:**
- Create: `telemetry_tool/alembic/versions/086_driving_events.py`
- Modify: `telemetry_tool/db/schema.py`
- Modify: `telemetry_tool/tasks/retention_tasks.py`
- Modify: `telemetry_tool/tasks/gdpr_tasks.py`
- Test: `telemetry_tool/tests/test_driving_events_pipeline.py`

**Interfaces:**
- Produces: table `driving_events` with `UNIQUE(session_id, lap_number, corner_id, event_type)`.

**A NEW TABLE is not the same as a NEW COLUMN.** Phase 1 learned that a column added only to `db/schema.py`'s `CREATE TABLE IF NOT EXISTS` body is a no-op against an existing table, and needed an idempotent `ALTER` in `db/migrate.py`. That lesson does **not** transfer here: `ensure_schema` iterates `ALL_TABLES` and executes each DDL, and `CREATE TABLE IF NOT EXISTS` on a table that does not exist yet creates it — on new and existing databases alike. So no `db/migrate.py` change is required. Verify that claim in Step 1 rather than trusting it.

The unique key is required, not optional: nothing in the repo deletes corner rows before rewriting, so without it every reprocess doubles the table, and `sql_compat`'s `INSERT OR REPLACE` → `ON CONFLICT` translation needs a conflict target.

- [ ] **Step 1: Read the patterns and verify the claim above**

Run: `sed -n '1,90p' telemetry_tool/alembic/versions/081_feeling_competition.py`
Run: `grep -n "PHASE_24_TABLES" -B 20 telemetry_tool/db/schema.py | head -30`
Run: `grep -n "def ensure_schema" -A 20 telemetry_tool/db/migrate.py`

Confirm: `ensure_schema` executes every DDL in `ALL_TABLES`, so a new table needs only `db/schema.py`. If that is NOT what you find, STOP and report NEEDS_CONTEXT.

- [ ] **Step 2: Write the failing test**

Create `telemetry_tool/tests/test_driving_events_pipeline.py`:

```python
"""Driving events — schema, persistence, stage wiring and real-data acceptance."""
import numpy as np
import pandas as pd
import pytest


def test_driving_events_table_exists_with_the_expected_columns(test_db):
    cur = test_db.execute("SELECT * FROM driving_events LIMIT 0")
    cols = {d[0] for d in cur.description}

    for c in (
        "session_id", "lap_number", "corner_id", "event_type",
        "s_norm_start", "s_norm_end",
        "magnitude", "magnitude_unit",
        "time_cost_s", "validity", "reason",
        "n_samples_in_window", "evidence_json",
    ):
        assert c in cols, f"{c} missing from driving_events"


def test_driving_events_has_a_unique_key_so_reprocess_does_not_double(test_db):
    """Without this, every reprocess doubles the table."""
    row = dict(
        session_id="s1", lap_number=1, corner_id=1, event_type="over_slowing",
        s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4, magnitude_unit="m/s",
        time_cost_s=0.31, validity="measured", reason=None,
        n_samples_in_window=42, evidence_json="{}",
    )
    cols = ", ".join(row)
    binds = ", ".join(f":{k}" for k in row)
    sql = f"INSERT OR REPLACE INTO driving_events ({cols}) VALUES ({binds})"

    test_db.execute(sql, row)
    test_db.execute(sql, row)
    test_db.commit()

    n = test_db.execute(
        "SELECT count(*) FROM driving_events WHERE session_id='s1'"
    ).fetchone()[0]
    assert n == 1, "reprocess duplicated the row -- unique key missing"


def test_driving_events_is_registered_for_retention_and_gdpr():
    """Data that cannot be purged or exported is a compliance defect."""
    from tasks import retention_tasks
    import inspect
    from tasks import gdpr_tasks

    assert "driving_events" in retention_tasks._RAW_DATA_TABLES
    assert "driving_events" in inspect.getsource(gdpr_tasks)
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_driving_events_pipeline.py -v`
Expected: all three FAIL — no such table.

- [ ] **Step 4: Create the migration**

Create `telemetry_tool/alembic/versions/086_driving_events.py`, modelled on `081_feeling_competition.py:43-89`. Columns as in the test, plus `workspace_id` and whatever the RLS pattern in 081 requires. Include the `UNIQUE(session_id, lap_number, corner_id, event_type)` constraint and an index on `(session_id, time_cost_s)` — the ranked read orders by cost.

```python
revision = "086_driving_events"
down_revision = "085_grip_anchor"
```

Copy 081's RLS policy statements verbatim in shape, substituting the table name.

- [ ] **Step 5: Mirror in `db/schema.py`**

Add a `_DRIVING_EVENTS_TABLE` DDL string and a `PHASE_25_TABLES` list containing it, then append `+ PHASE_25_TABLES` to `ALL_TABLES`. Match the SQLite types used by neighbouring tables (`TEXT`, `INTEGER`, `REAL`). Do NOT bump `SCHEMA_VERSION` — nothing about a new table requires it, and 37 already collides with another branch.

- [ ] **Step 6: Register for retention and GDPR**

Add `"driving_events"` to `retention_tasks._RAW_DATA_TABLES` (`retention_tasks.py:44-53`) and to the export dict in `gdpr_tasks.py` beside `"corner_metrics"` (around `:382`). Read both first and match the surrounding style.

- [ ] **Step 7: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_driving_events_pipeline.py -v`
Expected: 3 passed.

- [ ] **Step 8: Verify the alembic graph**

Run the AST head-check (it MUST handle annotated assignments — `down_revision: Union[str, None] = (...)` — or it reports phantom heads on this repo):

```bash
python -c "
import os,ast
d='telemetry_tool/alembic/versions'
revs={}; parents=set()
for f in sorted(os.listdir(d)):
    if not f.endswith('.py'): continue
    tree=ast.parse(open(os.path.join(d,f),encoding='utf-8',errors='replace').read())
    for node in tree.body:
        if isinstance(node,ast.Assign) and node.targets and isinstance(node.targets[0],ast.Name):
            name,val=node.targets[0].id,node.value
        elif isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name) and node.value is not None:
            name,val=node.target.id,node.value
        else: continue
        try: v=ast.literal_eval(val)
        except Exception: continue
        if name=='revision': revs[v]=f
        elif name=='down_revision' and v is not None:
            parents.update(v if isinstance(v,(tuple,list)) else [v])
print('HEADS:', sorted(r for r in revs if r not in parents))
"
```
Expected: `HEADS: ['086_driving_events']` — exactly one.

- [ ] **Step 9: Bite-check**

Remove the UNIQUE constraint from `db/schema.py`. Re-run.
Expected: `test_driving_events_has_a_unique_key_so_reprocess_does_not_double` goes RED with `assert 2 == 1`. Restore.

- [ ] **Step 10: Commit**

```bash
git add telemetry_tool/alembic/versions/086_driving_events.py telemetry_tool/db/schema.py telemetry_tool/tasks/retention_tasks.py telemetry_tool/tasks/gdpr_tasks.py telemetry_tool/tests/test_driving_events_pipeline.py
git commit -m "feat(db): driving_events table (migration 086) with retention and GDPR registration"
```

---

### Task 5: The `DrivingEvent` record and validity vocabulary

**Files:**
- Create: `telemetry_tool/driving_events.py`
- Test: `telemetry_tool/tests/test_driving_events.py`

**Interfaces:**
- Produces:
```python
VALIDITY_MEASURED = "measured"
VALIDITY_INSUFFICIENT_SAMPLES = "insufficient_samples"
VALIDITY_NOT_MEASURABLE = "not_measurable"
VALIDITIES: frozenset[str]

@dataclass(frozen=True)
class DrivingEvent:
    event_type: str
    lap_number: int
    corner_id: int
    s_norm_start: float
    s_norm_end: float
    magnitude: float | None
    magnitude_unit: str
    time_cost_s: float | None
    validity: str
    reason: str | None
    n_samples_in_window: int
    evidence: dict           # MANDATORY, non-empty for a measured event

EVENT_TYPES: frozenset[str]   # over_slowing, late_throttle, re_braking, envelope_under_use
```

**No `confidence` field.** The spec §5.5 records why: `handling/`'s is circularly calibrated with three detectors pushing the posterior the wrong way, and there is no ground truth anywhere in the repo to calibrate a replacement. `evidence` + `validity` + `n_samples_in_window` are checkable claims; a probability is not.

- [ ] **Step 1: Write the failing test**

Create `telemetry_tool/tests/test_driving_events.py`:

```python
"""Driving events — the record and its vocabularies.

Every event is a checkable claim: what this lap did, what the reference lap
did, which lap that was, and how many samples the window held. There is
deliberately no confidence float -- see the spec's section 5.5.
"""
import pytest


def test_vocabularies_are_closed():
    import driving_events as de

    assert de.VALIDITIES == frozenset({
        de.VALIDITY_MEASURED,
        de.VALIDITY_INSUFFICIENT_SAMPLES,
        de.VALIDITY_NOT_MEASURABLE,
    })
    assert de.EVENT_TYPES == frozenset({
        "over_slowing", "late_throttle", "re_braking", "envelope_under_use",
    })


def test_there_is_no_confidence_field():
    """A probability nobody can calibrate is worse than no number at all."""
    import dataclasses
    import driving_events as de

    names = {f.name for f in dataclasses.fields(de.DrivingEvent)}
    assert "confidence" not in names
    assert "evidence" in names
    assert "n_samples_in_window" in names


def test_a_measured_event_must_carry_evidence():
    import driving_events as de

    with pytest.raises(ValueError, match="evidence"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4,
            magnitude_unit="m/s", time_cost_s=0.31,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=42, evidence={},
        )


def test_a_non_measured_event_must_not_carry_a_magnitude():
    """Refusing with a number attached is the failure this layer prevents."""
    import driving_events as de

    with pytest.raises(ValueError, match="magnitude"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4,
            magnitude_unit="m/s", time_cost_s=None,
            validity=de.VALIDITY_INSUFFICIENT_SAMPLES, reason="window too short",
            n_samples_in_window=2, evidence={"n": 2},
        )


def test_an_unknown_event_type_is_rejected():
    import driving_events as de

    with pytest.raises(ValueError, match="event_type"):
        de.DrivingEvent(
            event_type="invented_thing", lap_number=1, corner_id=1,
            s_norm_start=0.0, s_norm_end=0.1, magnitude=None,
            magnitude_unit="", time_cost_s=None,
            validity=de.VALIDITY_NOT_MEASURABLE, reason="x",
            n_samples_in_window=0, evidence={"n": 0},
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_driving_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'driving_events'`.

- [ ] **Step 3: Implement**

Create `telemetry_tool/driving_events.py` with the constants above and the frozen dataclass, validating in `__post_init__`:
- `event_type` must be in `EVENT_TYPES`
- `validity` must be in `VALIDITIES`
- a `measured` event must have non-empty `evidence`
- a non-`measured` event must have `magnitude is None` and `time_cost_s is None`
Raise `ValueError` with the offending field named in the message.

Give the module a docstring stating plainly that there is no confidence field and why.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_driving_events.py -v`
Expected: 5 passed.

- [ ] **Step 5: Bite-check**

Delete the `measured`-requires-evidence check. Re-run.
Expected: `test_a_measured_event_must_carry_evidence` goes RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/driving_events.py telemetry_tool/tests/test_driving_events.py
git commit -m "feat(driving_events): the event record, with evidence instead of a confidence float"
```

---

### Task 6: Detector protocol, registry, and the capability record

**Files:**
- Modify: `telemetry_tool/driving_events.py`
- Test: `telemetry_tool/tests/test_driving_events.py`

**Interfaces:**
- Produces:
```python
@dataclass(frozen=True)
class CornerWindow:
    lap_number: int
    corner_id: int
    s_norm_start: float
    s_norm_end: float
    n_samples: int
    speed_mps: np.ndarray
    a_lat_mps2: np.ndarray
    a_long_mps2: np.ndarray | None     # None when the channel is absent
    dist_m: np.ndarray
    apex_speed_mps: float | None
    corner_time_s: float | None
    throttle_onset_m: float | None     # speed-derivative proxy, NOT a throttle channel
    reference: dict          # per-corner session bests: apex_speed_mps, corner_time_s, throttle_onset_m
    grip_anchor_pct: float | None

class Detector(Protocol):
    name: str
    requires: frozenset[str]
    min_samples: int
    def detect(self, w: CornerWindow) -> DrivingEvent | None: ...

REGISTRY: tuple[Detector, ...]

def run_registry(windows: Iterable[CornerWindow]) -> tuple[list[DrivingEvent], dict[str, str]]
    # -> (events, capability) where capability maps detector name to one of
    #    "detected" | "not_triggered" | "insufficient"
```

The capability record is the point: without it, "found nothing" and "could not look" are the same empty list. Copy the distinction from `track_surface/prescriptive/_internal.py:117-153`, which already models `Detected` / `NotTriggered` / `Insufficient` / `Unregistered` in production — read it before writing.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_driving_events.py`:

```python
import numpy as np


def _window(**over):
    import driving_events as de
    base = dict(
        lap_number=1, corner_id=1, s_norm_start=0.25, s_norm_end=0.35,
        n_samples=40,
        speed_mps=np.full(40, 12.0), a_lat_mps2=np.full(40, 9.0),
        a_long_mps2=np.zeros(40), dist_m=np.linspace(250.0, 350.0, 40),
        apex_speed_mps=12.0, corner_time_s=8.0,
        reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                   "throttle_onset_m": 10.0},
        grip_anchor_pct=95.0,
    )
    base.update(over)
    return de.CornerWindow(**base)


def test_registry_reports_not_triggered_separately_from_insufficient():
    """'Found nothing' and 'could not look' must never be the same answer."""
    import driving_events as de

    # A clean window: detectors can look, and (mostly) find nothing.
    clean = _window(apex_speed_mps=13.5, corner_time_s=7.5)
    _, cap = de.run_registry([clean])
    assert set(cap.values()) <= {"detected", "not_triggered", "insufficient"}
    assert cap["over_slowing"] == "not_triggered"

    # A window too short to judge.
    tiny = _window(n_samples=2, speed_mps=np.full(2, 12.0),
                   a_lat_mps2=np.full(2, 9.0), a_long_mps2=np.zeros(2),
                   dist_m=np.linspace(250.0, 260.0, 2))
    _, cap2 = de.run_registry([tiny])
    assert cap2["over_slowing"] == "insufficient"


def test_registry_marks_a_detector_insufficient_when_its_channel_is_absent():
    import driving_events as de

    w = _window(a_long_mps2=None)
    _, cap = de.run_registry([w])
    assert cap["re_braking"] == "insufficient"


def test_every_event_the_registry_emits_is_in_the_vocabulary():
    import driving_events as de

    events, _ = de.run_registry([_window(), _window(lap_number=2)])
    for e in events:
        assert e.event_type in de.EVENT_TYPES
        assert e.validity in de.VALIDITIES
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_driving_events.py -k registry -v`
Expected: FAIL — no `CornerWindow` / `run_registry`.

- [ ] **Step 3: Implement**

Add `CornerWindow`, the `Detector` protocol, an empty `REGISTRY` (Tasks 7–8 populate it), and `run_registry`. `run_registry` must:
- skip a detector whose `requires` are not satisfied by the window, recording `insufficient`
- skip a detector whose window has fewer than `min_samples`, recording `insufficient`
- record `detected` if it emitted at least one event across all windows, else `not_triggered`
- never raise: wrap each `detect` call and record `insufficient` on exception

Use "insufficient" for both the can't-look cases — the distinction that matters to a customer is look-vs-couldn't, not which reason.

- [ ] **Step 4: Run to verify it passes**

The registry is empty at this point, so the tests that assert on specific detector names will fail. **That is expected** — write the implementation, then mark those three tests `@pytest.mark.xfail(reason="registry populated in Tasks 7-8", strict=True)` and remove the marks in Task 8. Using `strict=True` means they fail loudly if they start passing early.

Run: `python -m pytest telemetry_tool/tests/test_driving_events.py -v`
Expected: all pass, with three xfailed.

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/driving_events.py telemetry_tool/tests/test_driving_events.py
git commit -m "feat(driving_events): detector protocol, registry, and the capability record"
```

---

### Task 7: `over_slowing` and `late_throttle`

**Files:**
- Modify: `telemetry_tool/driving_events.py`
- Test: `telemetry_tool/tests/test_driving_events.py`

**Interfaces:**
- Consumes: `CornerWindow`, `DrivingEvent` from Tasks 5–6.
- Produces: two detectors registered in `REGISTRY`.

Both compare this corner-lap to the driver's own best pass through the same corner. Measured fire rates 57% and 68% — so these RANK rather than flag, and the plan's read surface (Task 10) orders by `time_cost_s`.

`late_throttle` is **relative only**. `throttle_onset_m` is a speed-derivative proxy (`s10b_corners.py:494-498`), not a real throttle channel — as an absolute claim it is fiction, but the proxy's bias appears on both sides of a same-corner comparison and cancels. The event's `magnitude_unit` is `"m"` and its evidence must name the proxy.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_driving_events.py`:

```python
def test_over_slowing_measures_the_apex_deficit_against_the_reference():
    import driving_events as de

    w = _window(apex_speed_mps=12.0, corner_time_s=8.0,
                reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                           "throttle_onset_m": 10.0})
    ev = de.OVER_SLOWING.detect(w)

    assert ev is not None
    assert ev.event_type == "over_slowing"
    assert ev.magnitude == pytest.approx(1.5)        # 13.5 - 12.0
    assert ev.magnitude_unit == "m/s"
    assert ev.time_cost_s == pytest.approx(0.5)      # 8.0 - 7.5
    assert ev.validity == de.VALIDITY_MEASURED
    # The claim must be reconstructible from stored numbers.
    assert ev.evidence["apex_speed_mps"] == pytest.approx(12.0)
    assert ev.evidence["reference_apex_speed_mps"] == pytest.approx(13.5)


def test_over_slowing_is_silent_when_this_lap_IS_the_reference():
    import driving_events as de

    w = _window(apex_speed_mps=13.5, corner_time_s=7.5,
                reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                           "throttle_onset_m": 10.0})
    assert de.OVER_SLOWING.detect(w) is None


def test_over_slowing_refuses_rather_than_guessing_without_a_reference():
    import driving_events as de

    w = _window(reference={})
    ev = de.OVER_SLOWING.detect(w)
    assert ev is None or ev.validity != de.VALIDITY_MEASURED


def test_late_throttle_measures_metres_later_than_the_reference():
    import driving_events as de

    w = _window(
        throttle_onset_m=24.0,
        reference={"apex_speed_mps": 12.0, "corner_time_s": 8.0,
                   "throttle_onset_m": 10.0},
    )
    ev = de.LATE_THROTTLE.detect(w)

    assert ev is not None
    assert ev.event_type == "late_throttle"
    assert ev.magnitude == pytest.approx(14.0)      # 24.0 - 10.0
    assert ev.magnitude_unit == "m"
    # The evidence must name the proxy, because this is NOT a throttle channel.
    assert "proxy" in " ".join(str(v) for v in ev.evidence.values()).lower() \
        or ev.evidence.get("source") == "speed_derivative_proxy"


def test_late_throttle_refuses_when_this_lap_has_no_onset():
    """No onset was found -- refuse, do not invent one."""
    import driving_events as de

    w = _window(
        throttle_onset_m=None,
        reference={"apex_speed_mps": 12.0, "corner_time_s": 8.0,
                   "throttle_onset_m": 10.0},
    )
    ev = de.LATE_THROTTLE.detect(w)
    assert ev is None or ev.validity != de.VALIDITY_MEASURED
```

`throttle_onset_m: float | None` is declared as a `CornerWindow` field in Task 6 — add it to the `_window` helper's defaults (use `20.0`) when you extend that helper here.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_driving_events.py -k "over_slowing or late_throttle" -v`
Expected: FAIL — no `OVER_SLOWING`.

- [ ] **Step 3: Implement**

Add both detectors and register them. Thresholds: emit only when the deficit is positive and above a small floor (the probe used 0.5 m/s for apex and 2 m for throttle onset) — state the floor as a named module constant with the measured justification in a comment. `time_cost_s` comes from `corner_time_s - reference["corner_time_s"]`, never clamped.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_driving_events.py -v`
Expected: pass (two of the three Task-6 xfails may now pass — if so, remove those marks now).

- [ ] **Step 5: Bite-check**

Change the `over_slowing` magnitude to `reference - reference` (always zero). Re-run.
Expected: the magnitude assertion goes RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/driving_events.py telemetry_tool/tests/test_driving_events.py
git commit -m "feat(driving_events): over_slowing and late_throttle detectors"
```

---

### Task 8: `re_braking` and `envelope_under_use`

**Files:**
- Modify: `telemetry_tool/driving_events.py`
- Test: `telemetry_tool/tests/test_driving_events.py`

**Interfaces:**
- Produces: two more detectors in `REGISTRY`; the Task-6 xfail marks are removed here.

`re_braking` fires on **7%** of real corner-laps — the only candidate rare enough to work as a flag rather than a ranking. It needs `a_long_mps2`; at ~85–105 ms per sample a genuine dab is 2–3 samples, so require a sustained run of **≥3** and refuse otherwise. **Units:** the resampled frame carries `Longitudinal acceleration (G) *calc` in **G**, not `accel_long_mps2` — the window builder (Task 9) converts; this detector receives m/s².

`envelope_under_use` is a per-phase slice of Phase 1's `grip_anchor_pct`, already on the window. It inherits Phase 1's tier and reason for free and is the only detector whose number has already been measured on real data.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_driving_events.py`:

```python
def test_re_braking_needs_a_sustained_run_not_a_single_sample():
    import driving_events as de

    a = np.zeros(40)
    a[20] = -2.0                       # one isolated sample
    assert de.RE_BRAKING.detect(_window(a_long_mps2=a)) is None

    a2 = np.zeros(40)
    a2[20:23] = -2.0                   # three consecutive
    ev = de.RE_BRAKING.detect(_window(a_long_mps2=a2))
    assert ev is not None
    assert ev.event_type == "re_braking"
    assert ev.validity == de.VALIDITY_MEASURED


def test_re_braking_refuses_when_the_channel_is_absent():
    import driving_events as de

    ev = de.RE_BRAKING.detect(_window(a_long_mps2=None))
    assert ev is None or ev.validity != de.VALIDITY_MEASURED


def test_envelope_under_use_fires_below_the_floor_and_is_silent_above():
    import driving_events as de

    low = de.ENVELOPE_UNDER_USE.detect(_window(grip_anchor_pct=62.0))
    assert low is not None
    assert low.magnitude == pytest.approx(62.0)
    assert low.magnitude_unit == "pct"

    assert de.ENVELOPE_UNDER_USE.detect(_window(grip_anchor_pct=101.5)) is None


def test_envelope_under_use_refuses_without_a_phase_1_number():
    import driving_events as de

    ev = de.ENVELOPE_UNDER_USE.detect(_window(grip_anchor_pct=None))
    assert ev is None or ev.validity != de.VALIDITY_MEASURED
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_driving_events.py -k "re_braking or under_use" -v`
Expected: FAIL — no `RE_BRAKING`.

- [ ] **Step 3: Implement, and remove the Task-6 xfail marks**

Add both detectors, register all four, and delete the three `@pytest.mark.xfail` marks added in Task 6. Because they were `strict=True` they will have been failing loudly if the registry filled early — confirm they now pass on their own merits.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_driving_events.py -v`
Expected: all pass, **zero xfailed**.

- [ ] **Step 5: Bite-check**

Change `re_braking`'s run requirement from 3 to 1. Re-run.
Expected: `test_re_braking_needs_a_sustained_run_not_a_single_sample` goes RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/driving_events.py telemetry_tool/tests/test_driving_events.py
git commit -m "feat(driving_events): re_braking and envelope_under_use detectors"
```

---

### Task 9: The pipeline stage

**Files:**
- Create: `telemetry_tool/pipeline/stages/s10d3_driving_events.py`
- Modify: `telemetry_tool/pipeline/orchestrator.py`
- Test: `telemetry_tool/tests/test_driving_events_pipeline.py`

**Interfaces:**
- Produces:
```python
def run_driving_events(
    per_lap_corner_metrics: list[dict],
    corners: list[dict],
    resampled_laps: dict[int, pd.DataFrame],
    *,
    excluded_laps: frozenset[int] = frozenset(),
) -> dict   # {"events": [...], "capability": {...}}
```

Builds a `CornerWindow` per corner-lap and runs the registry. **Must never raise** — it runs inside `_safe_step`, and Phase 1 learned that rebinding the metrics variable from a failing step discards them, so bind the result to its own name and promote only on success.

**Unit conversion happens here**, once: the resampled frame carries `Longitudinal acceleration (G) *calc` and `Lateral acceleration (G) *calc` in **G**; multiply by 9.80665. Reuse `corner_analysis._resolve_accel_lat` for the lateral channel rather than writing a second converter.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_driving_events_pipeline.py`:

```python
def test_stage_returns_events_and_a_capability_record():
    from pipeline.stages import s10d3_driving_events

    n = 400
    d = np.linspace(0.0, 1200.0, n)
    def lap(v):
        return pd.DataFrame({
            "Distance (m)": d, "distance_norm": d / 1200.0,
            "Speed (m/s)": np.full(n, v),
            "Lateral acceleration (G) *calc": np.full(n, 0.9),
            "Longitudinal acceleration (G) *calc": np.zeros(n),
        })

    corners = [{"corner_id": 1, "s_start": 300.0, "s_end": 400.0}]
    metrics = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0,
         "corner_time_s": 10.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 70.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 12.5,
         "corner_time_s": 8.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 99.0},
    ]

    out = s10d3_driving_events.run_driving_events(
        metrics, corners, {1: lap(10.0), 2: lap(12.5)},
    )

    assert "events" in out and "capability" in out
    assert set(out["capability"]) == {
        "over_slowing", "late_throttle", "re_braking", "envelope_under_use"}
    # lap 1 was slower than the reference, so something must be said about it
    assert any(e.lap_number == 1 for e in out["events"])


def test_stage_never_raises_on_malformed_input():
    from pipeline.stages import s10d3_driving_events

    for args in (
        ([], [], {}),
        ([None], [None], {1: None}),
        ([{"lap_number": None, "corner_id": None}], ["junk"], {1: pd.DataFrame()}),
    ):
        out = s10d3_driving_events.run_driving_events(*args)
        assert isinstance(out, dict)
        assert "events" in out and "capability" in out


def test_orchestrator_runs_the_driving_events_stage(_isolated_track_registry, tmp_path):
    """Behavioural: spy on the stage while driving the real orchestrator.

    Mirrors test_grip_anchor_pipeline.py's orchestrator spy exactly -- patch
    run_per_lap_corner_metrics to return a fixed non-empty list (synthetic-CSV
    corner detection is unreliable), then assert the stage under test was
    actually called. A source-grep would pass even if it were wired into dead
    code.
    """
    from unittest.mock import patch
    from pipeline.stages import s10b_corners, s10d3_driving_events
    import pipeline

    fixed = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0,
         "corner_time_s": 10.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 70.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 12.5,
         "corner_time_s": 8.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 99.0},
    ]
    csv_path = _write_synthetic_csv(tmp_path)   # see note below

    with patch.object(s10b_corners, "run_per_lap_corner_metrics",
                      return_value=fixed), \
         patch.object(s10d3_driving_events, "run_driving_events",
                      wraps=s10d3_driving_events.run_driving_events) as spy:
        pipeline.run_full_analysis(str(csv_path), {})

    assert spy.call_count == 1, "the driving-events stage was never called"
    assert spy.call_args.args[0] == fixed
```

Before writing this, read `test_grip_anchor_pipeline.py`'s `test_orchestrator_calls_grip_anchor_with_the_per_lap_metrics_and_friction_model` and reuse its synthetic-CSV builder rather than writing `_write_synthetic_csv` from scratch — if that helper already exists under another name, import or copy it and say which. Also confirm whether the orchestrator holds a module reference or a direct function reference to the stage; if the latter, patch the orchestrator's attribute rather than the module's, or the spy will not intercept.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_driving_events_pipeline.py -k "stage or orchestrator" -v`
Expected: FAIL — no such module.

- [ ] **Step 3: Implement the stage**

Build one `CornerWindow` per corner-lap, reusing `s10d2_grip_anchor._corner_mask` for the window (import it, do not duplicate — a second mask implementation would drift from Task 2's frame fix). Convert G→m/s² once. Skip excluded laps. Run the registry. Return `{"events": [...], "capability": {...}}`.

- [ ] **Step 4: Wire it into the orchestrator**

Insert a `10d3_driving_events` `_safe_step` immediately after the `10d2_grip_anchor` block, binding to its own name and promoting only on success — copy the shape of the `_plcm_anchored` pattern at `orchestrator.py:1200-1210`, which exists precisely because an in-place rebind discarded everything on failure. Store into `summary["driving_events"]` and `summary["driving_events_capability"]`.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_driving_events_pipeline.py telemetry_tool/tests/test_driving_events.py -v`
Expected: all pass.

- [ ] **Step 6: Bite-check**

Remove the orchestrator step. Re-run.
Expected: the orchestrator spy test goes RED. Restore.

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10d3_driving_events.py telemetry_tool/pipeline/orchestrator.py telemetry_tool/tests/test_driving_events_pipeline.py
git commit -m "feat(pipeline): step 10d3 emits driving events and a capability record"
```

---

### Task 10: Persistence and the two read surfaces

**Files:**
- Create: `telemetry_tool/web/repos/events_repo.py`
- Modify: `telemetry_tool/db/queries.py`
- Modify: `telemetry_tool/web/routes/data_v2.py`
- Modify: `telemetry_tool/pipeline/stages/s15_persist.py` (or wherever corner metrics are persisted — find it in Step 1)
- Test: `telemetry_tool/tests/test_driving_events_pipeline.py`

**Interfaces:**
- Produces:
  - `events_repo.insert_driving_events(conn, session_id, events) -> int`
  - `events_repo.get_ranked_events(conn, session_id, limit=10) -> list[dict]` — ordered by `time_cost_s` DESC
  - `events_repo.get_corner_consistency(conn, session_id) -> list[dict]` — per corner: best, median, spread of `corner_time_s`
  - `GET /api/v1/sessions/<id>/driving-events` and `.../corner-consistency`

Two surfaces, one data model — this is what "rank + consistency together" means. The ranked list answers *what should I fix next*; the aggregate answers *where am I unreliable*.

- [ ] **Step 1: Find the persistence site and an endpoint to model on**

Run: `grep -rn "insert_corner_metrics" telemetry_tool/ --include=*.py | grep -v tests`
Run: `sed -n '3452,3470p' telemetry_tool/web/routes/data_v2.py`

The first gives the writer to sit beside; the second is the `SELECT *` corner-metrics endpoint whose shape to copy.

- [ ] **Step 2: Write the failing tests**

Append to `telemetry_tool/tests/test_driving_events_pipeline.py`:

```python
def test_ranked_events_are_ordered_by_time_cost(test_db):
    from web.repos import events_repo
    import driving_events as de

    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=L, corner_id=C,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=cost,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"apex_speed_mps": 10.0},
        )
        for (L, C, cost) in [(1, 1, 0.10), (7, 4, 0.885), (9, 1, 0.412)]
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=2)
    assert [round(g["time_cost_s"], 3) for g in got] == [0.885, 0.412]
    assert got[0]["lap_number"] == 7 and got[0]["corner_id"] == 4


def test_corner_consistency_reports_best_median_and_spread(test_db):
    from web.repos import events_repo
    import driving_events as de

    # corner 4 is inconsistent, corner 2 is tight
    rows = [(4, 0.0), (4, 0.45), (4, 0.89), (2, 0.0), (2, 0.05), (2, 0.09)]
    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=i + 1, corner_id=c,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=cost,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=40, evidence={"x": 1},
        )
        for i, (c, cost) in enumerate(rows)
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    by_corner = {r["corner_id"]: r for r in
                 events_repo.get_corner_consistency(test_db, "s1")}
    assert by_corner[4]["spread_s"] > by_corner[2]["spread_s"]
    assert by_corner[4]["worst_s"] == pytest.approx(0.89)


def test_insert_is_idempotent_so_reprocess_does_not_double(test_db):
    from web.repos import events_repo
    import driving_events as de

    ev = de.DrivingEvent(
        event_type="over_slowing", lap_number=1, corner_id=1,
        s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0, magnitude_unit="m/s",
        time_cost_s=0.2, validity=de.VALIDITY_MEASURED, reason=None,
        n_samples_in_window=40, evidence={"x": 1},
    )
    events_repo.insert_driving_events(test_db, "s1", [ev])
    events_repo.insert_driving_events(test_db, "s1", [ev])
    test_db.commit()

    n = test_db.execute(
        "SELECT count(*) FROM driving_events WHERE session_id='s1'").fetchone()[0]
    assert n == 1
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest telemetry_tool/tests/test_driving_events_pipeline.py -k "ranked or consistency or idempotent" -v`
Expected: FAIL — no `events_repo`.

- [ ] **Step 4: Implement the repo and queries**

Write `INSERT_DRIVING_EVENT` (using `INSERT OR REPLACE` so the unique key makes it idempotent), `SELECT_RANKED_EVENTS` and `SELECT_CORNER_CONSISTENCY` in `db/queries.py`, and the three repo functions. Serialise `evidence` to JSON. Use `_safe_float` on every numeric bind — Phase 1 learned that a raw `numpy.float64` raises `can't adapt` in psycopg2 and the exception is swallowed, losing the whole write.

Compute best/median/spread in SQL if the dialect allows it on both SQLite and PG; otherwise compute in Python from a plain `SELECT` and say why in a comment.

- [ ] **Step 5: Persist from the pipeline**

Call `insert_driving_events` where corner metrics are persisted (found in Step 1), guarded so a failure is logged at warning and swallowed — matching the neighbouring pattern — but **log it with `exc_info=True`**, unlike the bare `except` at `endurance_tasks.py:781-782`.

- [ ] **Step 6: Add the two endpoints**

Add `GET /api/v1/sessions/<session_id>/driving-events?limit=N` and `GET /api/v1/sessions/<session_id>/corner-consistency` to `data_v2.py`, modelled on the corner-metrics endpoint's auth, tenancy and response-envelope shape.

- [ ] **Step 7: Run to verify they pass**

Run: `python -m pytest telemetry_tool/tests/test_driving_events_pipeline.py telemetry_tool/tests/test_driving_events.py -v`
Expected: all pass.

- [ ] **Step 8: Bite-check**

Change the ranked query's `ORDER BY` to ascending. Re-run.
Expected: `test_ranked_events_are_ordered_by_time_cost` goes RED. Restore.

- [ ] **Step 9: Commit**

```bash
git add telemetry_tool/web/repos/events_repo.py telemetry_tool/db/queries.py telemetry_tool/web/routes/data_v2.py telemetry_tool/tests/test_driving_events_pipeline.py
git add -u telemetry_tool/
git commit -m "feat(events): persist driving events and serve ranked + consistency views"
```

---

### Task 11: Real-data acceptance

**Files:**
- Test: `telemetry_tool/tests/test_driving_events_pipeline.py`

**Interfaces:** none consumed downstream. This is the gate.

**Isolation is mandatory:** monkeypatch `track_detection._default_db_path` to a `tmp_path` file, or the run appends to the tracked `telemetry_tool/models/tracks.json`. This has happened three times in this lineage.

- [ ] **Step 1: Write the test**

Append to `telemetry_tool/tests/test_driving_events_pipeline.py`:

```python
import os

_REAL_CSV = "telemetry_tool/data/raw/OK_R4.csv"


@pytest.fixture
def _isolated_track_registry(tmp_path, monkeypatch):
    import track_detection
    monkeypatch.setattr(
        track_detection, "_default_db_path", lambda: str(tmp_path / "tracks.json"))


@pytest.mark.skipif(not os.path.exists(_REAL_CSV), reason="real fixture absent")
def test_driving_events_on_real_kart_telemetry(_isolated_track_registry):
    """Acceptance: events are emitted, every one is in the vocabulary, the
    capability record covers all four detectors, and the costs are plausible.

    Probe baseline on this session (54 corner-laps, 9 racing laps, 6 corners):
    over_slowing 57%, late_throttle 68%, re_braking 7%, worst cost 0.885 s.
    """
    import driving_events as de
    from pipeline import run_full_analysis

    summary = run_full_analysis(_REAL_CSV, {})
    events = summary.get("driving_events") or []
    cap = summary.get("driving_events_capability") or {}

    assert events, "no driving events produced on real telemetry"
    assert set(cap) == {"over_slowing", "late_throttle",
                        "re_braking", "envelope_under_use"}

    for e in events:
        assert e.event_type in de.EVENT_TYPES
        assert e.validity in de.VALIDITIES
        if e.validity == de.VALIDITY_MEASURED:
            assert e.evidence, "a measured event must carry evidence"
            if e.time_cost_s is not None:
                assert -0.5 <= e.time_cost_s <= 5.0, (
                    f"implausible cost {e.time_cost_s}s "
                    f"(lap {e.lap_number} corner {e.corner_id})")

    laps = {e.lap_number for e in events}
    assert len(laps) >= 4, f"events on only {len(laps)} laps: {laps}"

    from collections import Counter
    print(f"\nevent types: {Counter(e.event_type for e in events)}")
    print(f"capability:  {cap}")
    costs = [e.time_cost_s for e in events if e.time_cost_s is not None]
    if costs:
        print(f"cost s: min {min(costs):.3f} median "
              f"{sorted(costs)[len(costs)//2]:.3f} max {max(costs):.3f}")
```

- [ ] **Step 2: Run it**

Run: `python -m pytest telemetry_tool/tests/test_driving_events_pipeline.py -k real_kart -v -s`
Expected: PASS. **Record the printed distributions in your report — they are the headline result of Phase 2.**

- [ ] **Step 3: Compare against the probe baseline**

The probe measured over_slowing 57%, late_throttle 68%, re_braking 7% on 54 corner-laps. Compare your event counts. A large divergence means the stage's windows differ from the probe's — investigate and report rather than adjusting a threshold.

- [ ] **Step 4: Check the tree**

Run: `git status --short`
Expected: only gitignored cache paths. If `telemetry_tool/models/tracks.json` appears, the isolation fixture is not working.

- [ ] **Step 5: Bite-check**

Make `run_registry` return `([], {})`. Re-run.
Expected: RED on `assert events`. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/tests/test_driving_events_pipeline.py
git commit -m "test(driving_events): acceptance on real kart telemetry"
```

---

## Known not-covered by Phase 2

- **`over_braking`, `envelope_exceedance`** — tautological against a self-referential percentile envelope; see spec §5.5.
- **`corner_rounding`** — a shape verdict over 10–20 samples with no ground truth.
- **`handling/` understeer-oversteer** — best-lap-only, and its confidence is circularly calibrated.
- **`coast_gap`** — 0.3 s is ~3 samples on this grid; real once Phase 4a ingests the ~100 Hz IMU.
- **The shape-primitive library** — the four surviving detectors need a min-index, a threshold-crossing run and an integral. Three inline helpers, not a library.
- **Cross-session anything** — corner identity is positional per-session; Phase 5.
- **Frontend rendering** — Phase 2 persists and serves; Phase 3 renders.
- **The composite-lap caveat** — the sum of per-corner bests is a lap nobody drove (measured 0.121 s under the real best). Never render a summed total without labelling it an unattainable composite.
- **Corner-local cost only** — slowing at corner N also costs time on the following straight, which a corner-window integral misses entirely.
