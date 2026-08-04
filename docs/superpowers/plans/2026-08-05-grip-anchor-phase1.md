# Grip Anchor (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every corner-lap an honestly-labelled grip-utilisation number — what fraction of the *available* grip the driver used — where "available" always carries a tier saying what it was measured against.

**Architecture:** One pure module (`telemetry_tool/grip_anchor.py`) owning a tier vocabulary, a reason taxonomy, an inline channel-trust ratio, and a fail-safe `decide_anchor()`. A thin pipeline stage calls it where all inputs already coexist (`orchestrator.py`, right after `10d_per_lap_corners`). Results persist as four new columns on `corner_metrics`, which already has the right unique key, RLS, and a `SELECT *` endpoint.

**Tech Stack:** Python 3.14, numpy, pandas, pytest, Alembic, SQLite (tests) / PostgreSQL (prod).

**Branch:** `feat/driving-pattern-recognition`, worktree `C:\Users\Admin\lap_web-wt-patterns`, rebased onto `fix/per-lap-distance-frame`.

**Spec:** `docs/superpowers/specs/2026-08-04-driving-pattern-recognition-design.md` §5.3.

## Global Constraints

- **Tests import BARE module names** (`from grip_anchor import ...`), never `from telemetry_tool.grip_anchor import ...`. `telemetry_tool/tests/conftest.py` puts the project root on `sys.path`. The wrong prefix has already caused a production-only crash in this codebase.
- **Run tests from the repo root:** `python -m pytest telemetry_tool/tests/... -v`.
- **Bite-check every test.** Break the code it guards, confirm RED, restore, confirm GREEN. Report the exact red output. A test that cannot fail is worse than no test.
- **After any test run, check `git status --short`.** It must show only untracked `telemetry_tool/data/cache/`. A test that mutates tracked files is a defect — this already happened on the parent branch with `models/tracks.json`.
- **NEVER cap the percentage at 100.** The lateral envelope is a *percentile*, not a maximum (`friction_model.py:465`), so exceeding it is expected and is the single most diagnostic value available. The legacy `grip_utilisation_pct` caps at 100 (`corner_analysis.py:665`) — do not copy that.
- **Fail-safe always.** Any doubt degrades toward the lower tier. An unknown or absent signal never yields a `physics` tier. This mirrors `track_surface/honesty.py`.
- **Units: all arithmetic in m/s².** `FrictionCircle` is m/s²; `FrictionBin`/`GripMap` μ are G. Never mix. The persisted baseline column is named `..._g` and is the only place a G value appears.
- **Do NOT touch the legacy `grip_utilization` column** on `corner_metrics`. Phase 1 ships beside it; Phase 2 decides its fate.
- **Do NOT use** `friction_envelope.is_feasible` (5–10% solver slack, and it tests a circle), `sensor_quality.curvature_agreement` (wrong axis, wrong threshold, produced after the hook), or `DataQualityReport` (never persisted — gated on `isinstance(dq, dict)` against a dataclass).
- No drive-by refactors. Commit after every task, conventional prefixes.

---

## File Structure

| File | Responsibility |
|---|---|
| `telemetry_tool/grip_anchor.py` (new) | Pure: tier + reason vocabulary, channel-trust ratio, bin provenance, ellipse fill, `decide_anchor`, consumer guard. No I/O, no pipeline knowledge. |
| `telemetry_tool/pipeline/stages/s10d2_grip_anchor.py` (new) | Thin stage: walks per-lap corner metrics, calls `decide_anchor`, attaches results. |
| `telemetry_tool/pipeline/orchestrator.py` (modify) | Wire the stage in after `10d_per_lap_corners`. |
| `telemetry_tool/friction_model.py` (modify) | Add in-memory `exponent_source` field so a fitted exponent is distinguishable from the default hint. No migration — the object is never persisted. |
| `telemetry_tool/alembic/versions/085_grip_anchor.py` (new) | Four columns on `corner_metrics`. |
| `telemetry_tool/db/schema.py` (modify) | Mirror the columns + bump `SCHEMA_VERSION`, or the pytest fixture cannot see the table. |
| `telemetry_tool/db/queries.py` (modify) | Add the four columns to `INSERT_CORNER_METRIC`. |
| `telemetry_tool/tests/test_grip_anchor.py` (new) | All unit tests for the pure module. |
| `telemetry_tool/tests/test_grip_anchor_pipeline.py` (new) | Stage wiring + persistence + real-data validation. |

---

### Task 1: Tier vocabulary, reason taxonomy, consumer guard

**Files:**
- Create: `telemetry_tool/grip_anchor.py`
- Test: `telemetry_tool/tests/test_grip_anchor.py`

**Interfaces:**
- Consumes: nothing.
- Produces: constants `TIER_PHYSICS_ELLIPSE_FITTED = "physics_ellipse_fitted"`, `TIER_PHYSICS_ELLIPSE_DEFAULT_P2 = "physics_ellipse_default_p2"`, `TIER_DRIVER_BEST_SESSION = "driver_best_session"`, `TIER_REFUSED = "refused"`, `TIERS: frozenset[str]`, the `REASON_*` constants listed below, and `is_quotable_as_physics(tier: str | None) -> bool`.

Modelled on `telemetry_tool/track_surface/honesty.py:13-39` — read that file first; copy its shape, not its values.

- [ ] **Step 1: Write the failing test**

Create `telemetry_tool/tests/test_grip_anchor.py`:

```python
"""Phase 1 grip anchor — tier vocabulary and the pure decision function.

The anchor answers "you used X% of the available grip here" and ALWAYS says
what "available" was measured against. Fail-safe: any doubt degrades toward
the lower tier; an unknown signal never yields a physics tier.
"""
import numpy as np
import pytest


def test_tier_vocabulary_is_closed():
    import grip_anchor as ga

    assert ga.TIERS == frozenset({
        ga.TIER_PHYSICS_ELLIPSE_FITTED,
        ga.TIER_PHYSICS_ELLIPSE_DEFAULT_P2,
        ga.TIER_DRIVER_BEST_SESSION,
        ga.TIER_REFUSED,
    })
    # Cross-session tier must NOT exist yet — corner identity is not stable
    # across sessions, so a driver_best_track value would be a promise we
    # cannot keep. Phase 2 adds it as a NEW value, not a redefinition.
    assert not hasattr(ga, "TIER_DRIVER_BEST_TRACK")


def test_only_physics_tiers_are_quotable_as_physics():
    import grip_anchor as ga

    assert ga.is_quotable_as_physics(ga.TIER_PHYSICS_ELLIPSE_FITTED) is True
    assert ga.is_quotable_as_physics(ga.TIER_PHYSICS_ELLIPSE_DEFAULT_P2) is True
    assert ga.is_quotable_as_physics(ga.TIER_DRIVER_BEST_SESSION) is False
    assert ga.is_quotable_as_physics(ga.TIER_REFUSED) is False
    assert ga.is_quotable_as_physics(None) is False
    assert ga.is_quotable_as_physics("something_invented") is False


def test_reserved_reasons_exist_for_phase_2_prerequisites():
    """Reserving these now forces Phase 2 to handle them deliberately."""
    import grip_anchor as ga

    assert ga.REASON_CONDITION_UNKNOWN == "condition_unknown"
    assert ga.REASON_CORNER_IDENTITY_UNSTABLE == "corner_identity_unstable"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'grip_anchor'`.

- [ ] **Step 3: Create the module**

Create `telemetry_tool/grip_anchor.py`:

```python
"""Phase 1 grip anchor: an honestly-labelled "% of available grip used".

Every number this module emits carries a TIER naming what "available" was
measured against, and a machine-readable REASON when it had to degrade.
Pure and dependency-light — no I/O, no pipeline knowledge — so the decision
can be bite-checked without a database.

Fail-SAFE: any doubt degrades toward the lower tier. An unknown or absent
signal must never produce a physics tier.

Shape copied from ``track_surface/honesty.py``; values are our own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

# -- Tier vocabulary — the ONLY legal values of corner_metrics.grip_anchor_tier.
# Two physics tiers, not one: the ellipse exponent is FITTED from boundary
# samples but silently falls back to a hint when they are thin, and a claim of
# "fitted ellipse" over a defaulted p=2 would be a false provenance claim.
TIER_PHYSICS_ELLIPSE_FITTED: Final = "physics_ellipse_fitted"
TIER_PHYSICS_ELLIPSE_DEFAULT_P2: Final = "physics_ellipse_default_p2"
# Session-scoped only. Cross-session ("driver_best_track") is NOT available:
# corner_id is a positional index over curvature regions found in one lap of
# one session, and corner_persistence has zero production callers. Phase 2
# adds a new tier value rather than redefining this one.
TIER_DRIVER_BEST_SESSION: Final = "driver_best_session"
TIER_REFUSED: Final = "refused"

TIERS: Final = frozenset({
    TIER_PHYSICS_ELLIPSE_FITTED,
    TIER_PHYSICS_ELLIPSE_DEFAULT_P2,
    TIER_DRIVER_BEST_SESSION,
    TIER_REFUSED,
})

_PHYSICS_TIERS: Final = frozenset({
    TIER_PHYSICS_ELLIPSE_FITTED,
    TIER_PHYSICS_ELLIPSE_DEFAULT_P2,
})

# -- Reason taxonomy (machine-readable).
REASON_NO_ENVELOPE: Final = "no_envelope"
REASON_BIN_FABRICATED: Final = "bin_fabricated"
REASON_SPEED_OUT_OF_BINS: Final = "speed_out_of_bins"
REASON_CHANNEL_UNTRUSTED: Final = "channel_untrusted"
REASON_NO_LAP_BASELINE: Final = "no_lap_baseline"
REASON_NO_MEASUREMENT: Final = "no_measurement"
# Reserved for Phase 2 — see the tier comments above.
REASON_CONDITION_UNKNOWN: Final = "condition_unknown"
REASON_CORNER_IDENTITY_UNSTABLE: Final = "corner_identity_unstable"


def is_quotable_as_physics(tier: str | None) -> bool:
    """The consumer guard. ONLY a physics tier may be presented to a driver as
    an absolute claim about the car's limit. Everything else — including an
    unknown tier — is relative or nothing."""
    return tier in _PHYSICS_TIERS
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -v`
Expected: 3 passed.

- [ ] **Step 5: Bite-check**

Temporarily change `is_quotable_as_physics` to `return tier is not None`. Re-run.
Expected: `test_only_physics_tiers_are_quotable_as_physics` goes RED on the `driver_best_session` assertion. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/grip_anchor.py telemetry_tool/tests/test_grip_anchor.py
git commit -m "feat(grip_anchor): tier vocabulary, reason taxonomy, consumer guard"
```

---

### Task 2: Inline channel-trust ratio

**Files:**
- Modify: `telemetry_tool/grip_anchor.py`
- Test: `telemetry_tool/tests/test_grip_anchor.py`

**Interfaces:**
- Consumes: Task 1's module.
- Produces: `channel_trust_ratio(a_lat_mps2: np.ndarray, speed_mps: np.ndarray, curvature_1pm: np.ndarray, *, min_geo_accel: float = 2.0, min_samples: int = 20) -> float | None`

Why inline rather than reusing `sensor_quality.curvature_agreement`: that signal bins by ~0.5 m of *distance* while the envelope bins by *speed*; it admits samples down to 0.05 G (the near-straight regime, measured at 0.531 in `docs/validation/attitude_correction_report.md:57`); and it is produced at `orchestrator.py:1349`, after this stage's hook. Computing it here over our own corner mask, at the threshold the 0.961 figure was actually measured under, retires all three problems at once.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor.py`:

```python
def test_channel_trust_ratio_is_one_for_a_perfectly_consistent_channel():
    """If a_lat exactly equals v^2 * kappa, the ratio must be 1.0."""
    import grip_anchor as ga

    v = np.full(200, 20.0)
    kappa = np.full(200, 0.02)          # v^2*kappa = 8.0 m/s^2, well above the gate
    a_lat = v ** 2 * kappa

    assert ga.channel_trust_ratio(a_lat, v, kappa) == pytest.approx(1.0)


def test_channel_trust_ratio_detects_a_systematically_low_channel():
    import grip_anchor as ga

    v = np.full(200, 20.0)
    kappa = np.full(200, 0.02)
    a_lat = 0.85 * v ** 2 * kappa       # reads 15% low

    assert ga.channel_trust_ratio(a_lat, v, kappa) == pytest.approx(0.85)


def test_channel_trust_ratio_ignores_near_straight_samples():
    """Straights are v^2*kappa ~ 0, so the ratio there is noise over noise.
    Averaging them in is exactly what makes the persisted sensor_quality
    signal read 0.531 instead of ~0.96."""
    import grip_anchor as ga

    v = np.full(400, 20.0)
    kappa = np.concatenate([np.full(200, 0.02), np.full(200, 1e-5)])
    a_lat = np.concatenate([
        v[:200] ** 2 * kappa[:200],          # honest cornering samples
        np.full(200, 5.0),                    # garbage on the straight
    ])

    # Only the cornering half is admitted, so the garbage cannot move it.
    assert ga.channel_trust_ratio(a_lat, v, kappa) == pytest.approx(1.0)


def test_channel_trust_ratio_returns_none_when_too_few_samples():
    import grip_anchor as ga

    v = np.full(5, 20.0)
    kappa = np.full(5, 0.02)
    assert ga.channel_trust_ratio(v ** 2 * kappa, v, kappa) is None


def test_channel_trust_ratio_returns_none_on_all_nan():
    import grip_anchor as ga

    n = 200
    v = np.full(n, 20.0)
    kappa = np.full(n, 0.02)
    assert ga.channel_trust_ratio(np.full(n, np.nan), v, kappa) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -k channel_trust -v`
Expected: FAIL — `AttributeError: module 'grip_anchor' has no attribute 'channel_trust_ratio'`.

- [ ] **Step 3: Implement**

Append to `telemetry_tool/grip_anchor.py`:

```python
def channel_trust_ratio(
    a_lat_mps2: np.ndarray,
    speed_mps: np.ndarray,
    curvature_1pm: np.ndarray,
    *,
    min_geo_accel: float = 2.0,
    min_samples: int = 20,
) -> float | None:
    """Median |a_lat| / (v^2 * kappa) over genuinely-cornering samples.

    1.0 means the measured lateral channel agrees with the path geometry.
    Returns None when there is not enough cornering to judge — which is a
    refusal, not a pass.

    ``min_geo_accel`` (m/s^2) is the whole point: on a straight, v^2*kappa is
    ~0 and the ratio is noise divided by noise. Averaging those in is what
    drags the persisted sensor_quality figure to 0.531. Restricted to real
    cornering, real kart data measures 0.961.
    """
    a = np.abs(np.asarray(a_lat_mps2, dtype=float))
    v = np.asarray(speed_mps, dtype=float)
    k = np.abs(np.asarray(curvature_1pm, dtype=float))

    a_geo = v ** 2 * k
    usable = np.isfinite(a) & np.isfinite(a_geo) & (a_geo > min_geo_accel)
    if int(usable.sum()) < min_samples:
        return None

    ratio = float(np.nanmedian(a[usable] / a_geo[usable]))
    return ratio if np.isfinite(ratio) else None


# Band within which the lateral channel is trusted for an absolute claim.
# Real kart data measures 0.961; the production frontend uses [0.80, 1.20]
# after filtering zeros (TrackSurfacePanel.tsx:513).
TRUST_BAND_LOW: Final = 0.80
TRUST_BAND_HIGH: Final = 1.25


def channel_is_trusted(ratio: float | None) -> bool:
    """Fail-safe: None (not measurable) is NOT trusted."""
    return ratio is not None and TRUST_BAND_LOW <= ratio <= TRUST_BAND_HIGH
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -v`
Expected: 8 passed.

- [ ] **Step 5: Bite-check**

Change `min_geo_accel: float = 2.0` to `0.0`. Re-run.
Expected: `test_channel_trust_ratio_ignores_near_straight_samples` goes RED (the straight-line garbage now dominates). Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/grip_anchor.py telemetry_tool/tests/test_grip_anchor.py
git commit -m "feat(grip_anchor): inline channel-trust ratio over cornering samples only"
```

---

### Task 3: Distinguish a fitted ellipse exponent from the default hint

**Files:**
- Modify: `telemetry_tool/friction_model.py`
- Test: `telemetry_tool/tests/test_grip_anchor.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `FrictionCircle.exponent_source: str` — `"fitted"` or `"hint"`. In-memory dataclass field only. `FrictionCircle` is NEVER persisted (`to_dict`/`from_dict` have exactly one caller, its own inline test), so **no migration is required**.

`_fit_ellipse_exponent` silently returns `exponent_hint` when fewer than 20 boundary samples qualify, and `run_friction_model` calls `build_friction_model` with no exponent kwarg, so the hint is 2.0. A genuine fit landing near 2.0 is therefore indistinguishable from a silent default — which is exactly the ambiguity the two physics tiers exist to remove.

- [ ] **Step 1: Read the fit function**

The call site is `friction_model.py:650` (`fitted_exp = _fit_ellipse_exponent(...)`). The function is defined at `:677`. It has exactly two returns:
- `return exponent_hint` at approximately `:736` — the insufficient-boundary-data fallback (its own log line sits just above it)
- `return best_p` at approximately `:760` — the successful grid-search result

Read both and confirm the line numbers before editing.

- [ ] **Step 2: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor.py`:

```python
def test_friction_circle_reports_whether_its_exponent_was_fitted():
    """A fitted p that happens to land near 2.0 must be distinguishable from
    a silent fallback to the 2.0 hint — otherwise a 'fitted ellipse' tier is
    a claim we cannot support."""
    from friction_model import FrictionCircle

    fc = FrictionCircle(
        v_grid=np.linspace(5.0, 40.0, 8),
        traction_vals=np.full(8, 3.0),
        braking_vals=np.full(8, 9.0),
        lateral_vals=np.full(8, 12.0),
    )
    # Default construction has not fitted anything.
    assert fc.exponent_source == "hint"
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -k exponent_was_fitted -v`
Expected: FAIL — `AttributeError: 'FrictionCircle' object has no attribute 'exponent_source'`.

- [ ] **Step 4: Add the field and set it at both fit outcomes**

In `telemetry_tool/friction_model.py`, add to the `FrictionCircle` dataclass immediately after the `exponent` field (currently line 284):

```python
    # "fitted" when _fit_ellipse_exponent had enough boundary samples to
    # actually fit p; "hint" when it silently fell back to the default.
    # In-memory only — this object is never persisted, so no migration.
    exponent_source: str = "hint"
```

Then, in `build_friction_model`, set it where the fitted exponent is assigned to the returned `FrictionCircle`: `"fitted"` when `_fit_ellipse_exponent` genuinely fitted, `"hint"` on its fallback path. Read the function to find where the exponent reaches the constructor; if `_fit_ellipse_exponent` currently returns only a float, change it to return `(exponent, source)` and update its single call site. Do NOT change the numeric behaviour — only report it.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -v`
Expected: 9 passed.

Run: `python -m pytest telemetry_tool/tests/ -k "friction" -v --continue-on-collection-errors`
Expected: no new failures — you changed reporting, not numbers.

- [ ] **Step 6: Bite-check**

Change the default to `exponent_source: str = "fitted"`. Re-run.
Expected: `test_friction_circle_reports_whether_its_exponent_was_fitted` goes RED. Restore.

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/friction_model.py telemetry_tool/tests/test_grip_anchor.py
git commit -m "feat(friction_model): report whether the ellipse exponent was fitted or defaulted"
```

---

### Task 4: Uncapped ellipse fill

**Files:**
- Modify: `telemetry_tool/grip_anchor.py`
- Test: `telemetry_tool/tests/test_grip_anchor.py`

**Interfaces:**
- Consumes: `FrictionCircle` (`traction_max(speed)`, `braking_max(speed)`, `lateral_max(speed)` — all m/s²; `.exponent: float`).
- Produces: `ellipse_fill_pct(a_lat_mps2: float, a_long_mps2: float, speed_mps: float, friction: Any) -> float | None`

The superellipse is `|ax/ax_max|^p + |ay/ay_max|^p = 1`. For a sample at `(a_lat, a_long)`, the fraction of the boundary used along that sample's own direction is:

```
pct = 100 * ( (|a_long|/ax_max)^p + (|a_lat|/ay_max)^p ) ^ (1/p)
```

`ax_max` is `braking_max(v)` when `a_long < 0`, else `traction_max(v)` — the axes are asymmetric and using the wrong one silently mis-scales the longitudinal contribution.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor.py`:

```python
class _FakeFriction:
    """Minimal stand-in with the real FrictionCircle accessor names."""

    def __init__(self, lat=12.0, brake=9.0, traction=3.0, exponent=2.0):
        self._lat, self._brake, self._trac, self.exponent = lat, brake, traction, exponent
        self.exponent_source = "fitted"

    def lateral_max(self, speed):
        return np.asarray(self._lat, dtype=float)

    def braking_max(self, speed):
        return np.asarray(self._brake, dtype=float)

    def traction_max(self, speed):
        return np.asarray(self._trac, dtype=float)


def test_ellipse_fill_is_100_at_the_pure_lateral_boundary():
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0)
    assert ga.ellipse_fill_pct(12.0, 0.0, 25.0, f) == pytest.approx(100.0)


def test_ellipse_fill_is_100_at_the_pure_braking_boundary():
    import grip_anchor as ga

    f = _FakeFriction(brake=9.0)
    assert ga.ellipse_fill_pct(0.0, -9.0, 25.0, f) == pytest.approx(100.0)


def test_ellipse_fill_uses_the_braking_axis_for_deceleration():
    """Braking and traction limits are asymmetric (9.0 vs 3.0 here). Using the
    wrong axis silently mis-scales the longitudinal term."""
    import grip_anchor as ga

    f = _FakeFriction(brake=9.0, traction=3.0)
    braking = ga.ellipse_fill_pct(0.0, -3.0, 25.0, f)
    accelerating = ga.ellipse_fill_pct(0.0, 3.0, 25.0, f)

    assert braking == pytest.approx(100.0 * 3.0 / 9.0)
    assert accelerating == pytest.approx(100.0)


def test_ellipse_fill_combines_both_axes():
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0, brake=9.0, exponent=2.0)
    # Half of each axis: sqrt(0.5^2 + 0.5^2) = 0.7071
    assert ga.ellipse_fill_pct(6.0, -4.5, 25.0, f) == pytest.approx(70.71, abs=0.01)


def test_ellipse_fill_is_NOT_capped_at_100():
    """The envelope is a percentile, not a maximum, so exceeding it is expected
    and is the most diagnostic value we can report. Capping destroys the one
    signal that reveals over-driving or a wrong envelope."""
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0)
    assert ga.ellipse_fill_pct(18.0, 0.0, 25.0, f) == pytest.approx(150.0)


def test_ellipse_fill_returns_none_on_a_degenerate_envelope():
    import grip_anchor as ga

    assert ga.ellipse_fill_pct(5.0, 0.0, 25.0, _FakeFriction(lat=0.0)) is None
    assert ga.ellipse_fill_pct(np.nan, 0.0, 25.0, _FakeFriction()) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -k ellipse_fill -v`
Expected: FAIL — `AttributeError: module 'grip_anchor' has no attribute 'ellipse_fill_pct'`.

- [ ] **Step 3: Implement**

Append to `telemetry_tool/grip_anchor.py`:

```python
def _scalar(x: Any) -> float:
    """FrictionCircle accessors return 0-d or 1-element arrays."""
    return float(np.asarray(x).reshape(-1)[0])


def ellipse_fill_pct(
    a_lat_mps2: float,
    a_long_mps2: float,
    speed_mps: float,
    friction: Any,
) -> float | None:
    """Percentage of the friction ellipse used, along this sample's own
    combined-g direction. NOT capped at 100 — see the module docstring.

    Superellipse: |ax/ax_max|^p + |ay/ay_max|^p = 1, so the fraction of the
    boundary reached is that sum raised to 1/p.
    """
    a_lat = abs(float(a_lat_mps2))
    a_long = float(a_long_mps2)
    if not (np.isfinite(a_lat) and np.isfinite(a_long) and np.isfinite(speed_mps)):
        return None

    try:
        ay_max = _scalar(friction.lateral_max(speed_mps))
        # Asymmetric axes: decelerating is bounded by braking grip, not traction.
        ax_max = _scalar(
            friction.braking_max(speed_mps) if a_long < 0
            else friction.traction_max(speed_mps)
        )
        p = float(friction.exponent)
    except Exception:
        return None

    if not (np.isfinite(ay_max) and np.isfinite(ax_max)) or ay_max <= 0 or ax_max <= 0 or p <= 0:
        return None

    frac = (abs(a_long) / ax_max) ** p + (a_lat / ay_max) ** p
    if not np.isfinite(frac):
        return None
    return 100.0 * frac ** (1.0 / p)
```

Add `from typing import Any, Final` to the imports if `Any` is not already imported.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -v`
Expected: 15 passed.

- [ ] **Step 5: Bite-check**

Add `return min(100.0, ...)` around the final return. Re-run.
Expected: `test_ellipse_fill_is_NOT_capped_at_100` goes RED. Restore.

Then swap `braking_max` and `traction_max` in the `a_long < 0` branch. Re-run.
Expected: `test_ellipse_fill_uses_the_braking_axis_for_deceleration` goes RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/grip_anchor.py telemetry_tool/tests/test_grip_anchor.py
git commit -m "feat(grip_anchor): uncapped ellipse fill along the sample's own direction"
```

---

### Task 5: Bin provenance — is the envelope bin a measurement?

**Files:**
- Modify: `telemetry_tool/grip_anchor.py`
- Test: `telemetry_tool/tests/test_grip_anchor.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `bin_is_measured(bin_obj: Any) -> bool`

`friction_envelope.py:221-234` and `:248`: the synthetic branch is entered exactly when `n_in_bin < 8` and sets `confidence = 0.0`; real bins get `conf = min(1.0, n/32)` with `n >= 8`, so a real confidence is always `>= 0.25`. So `confidence == 0.0` ⟺ `sample_count < 8`, exactly and exclusively.

Do **not** use the `accel_max_g == global * 0.6` proxy: `round(g*0.6, 4)` versus `round(g, 4)*0.6` makes that comparison fail most of the time.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor.py`:

```python
def test_bin_is_measured_rejects_a_fabricated_bin():
    import grip_anchor as ga
    from friction_envelope import FrictionBin

    fabricated = FrictionBin(
        speed_center_mps=20.0, combined_g_p95=1.0, lat_max_g=1.0,
        accel_max_g=0.6, brake_max_g=1.0, sample_count=3, confidence=0.0,
    )
    assert ga.bin_is_measured(fabricated) is False


def test_bin_is_measured_accepts_a_real_bin():
    import grip_anchor as ga
    from friction_envelope import FrictionBin

    real = FrictionBin(
        speed_center_mps=20.0, combined_g_p95=1.3, lat_max_g=1.3,
        accel_max_g=0.35, brake_max_g=0.62, sample_count=41, confidence=1.0,
    )
    assert ga.bin_is_measured(real) is True


def test_bin_is_measured_is_fail_safe_on_none_or_junk():
    import grip_anchor as ga

    assert ga.bin_is_measured(None) is False
    assert ga.bin_is_measured(object()) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -k bin_is_measured -v`
Expected: FAIL — no attribute `bin_is_measured`.

- [ ] **Step 3: Implement**

Append to `telemetry_tool/grip_anchor.py`:

```python
# A FrictionBin is fabricated exactly when friction_envelope took its
# synthetic branch: n_in_bin < 8, which sets confidence to 0.0. Real bins get
# min(1.0, n/32) with n >= 8, hence confidence >= 0.25. The two are exclusive.
_MIN_MEASURED_SAMPLES: Final = 8


def bin_is_measured(bin_obj: Any) -> bool:
    """True only when this envelope bin is a real measurement.

    Fail-safe: anything we cannot inspect is treated as fabricated.
    """
    try:
        confidence = float(getattr(bin_obj, "confidence"))
        sample_count = int(getattr(bin_obj, "sample_count"))
    except (AttributeError, TypeError, ValueError):
        return False
    return confidence > 0.0 and sample_count >= _MIN_MEASURED_SAMPLES
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -v`
Expected: 18 passed.

- [ ] **Step 5: Bite-check**

Change the return to `return True`. Re-run.
Expected: `test_bin_is_measured_rejects_a_fabricated_bin` and `test_bin_is_measured_is_fail_safe_on_none_or_junk` go RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/grip_anchor.py telemetry_tool/tests/test_grip_anchor.py
git commit -m "feat(grip_anchor): fabricated-bin detection via the exact confidence/sample-count oracle"
```

---

### Task 6: `decide_anchor` — the fail-safe tier decision

**Files:**
- Modify: `telemetry_tool/grip_anchor.py`
- Test: `telemetry_tool/tests/test_grip_anchor.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
```python
@dataclass(frozen=True)
class Anchor:
    tier: str
    reason: str | None
    pct: float | None            # NOT capped at 100
    baseline_g: float | None     # what "available" was, in G

def decide_anchor(
    *,
    a_lat_mps2: float,
    a_long_mps2: float,
    speed_mps: float,
    friction: Any,
    envelope_bin: Any,
    trust_ratio: float | None,
    session_best_lat_mps2: float | None,
) -> Anchor
```

Precedence, strongest doubt first, mirroring `honesty.decide_tier`: no envelope → no measurement → fabricated bin → untrusted channel → tier 2 → refused.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor.py`:

```python
def _args(**over):
    base = dict(
        a_lat_mps2=9.0, a_long_mps2=0.0, speed_mps=25.0,
        friction=_FakeFriction(lat=12.0), envelope_bin=None,
        trust_ratio=0.96, session_best_lat_mps2=10.0,
    )
    base.update(over)
    return base


def _measured_bin():
    from friction_envelope import FrictionBin
    return FrictionBin(
        speed_center_mps=25.0, combined_g_p95=1.3, lat_max_g=1.3,
        accel_max_g=0.35, brake_max_g=0.62, sample_count=41, confidence=1.0,
    )


def test_decide_anchor_gives_fitted_physics_when_everything_passes():
    import grip_anchor as ga

    a = ga.decide_anchor(**_args(envelope_bin=_measured_bin()))
    assert a.tier == ga.TIER_PHYSICS_ELLIPSE_FITTED
    assert a.reason is None
    assert a.pct == pytest.approx(75.0)          # 9.0 / 12.0
    assert a.baseline_g == pytest.approx(12.0 / 9.80665)


def test_decide_anchor_flags_a_defaulted_exponent():
    import grip_anchor as ga

    f = _FakeFriction(lat=12.0)
    f.exponent_source = "hint"
    a = ga.decide_anchor(**_args(friction=f, envelope_bin=_measured_bin()))
    assert a.tier == ga.TIER_PHYSICS_ELLIPSE_DEFAULT_P2


def test_decide_anchor_falls_to_session_best_when_the_channel_is_untrusted():
    import grip_anchor as ga

    a = ga.decide_anchor(**_args(trust_ratio=0.42, envelope_bin=_measured_bin()))
    assert a.tier == ga.TIER_DRIVER_BEST_SESSION
    assert a.reason == ga.REASON_CHANNEL_UNTRUSTED
    assert a.pct == pytest.approx(90.0)          # 9.0 / 10.0
    assert a.baseline_g == pytest.approx(10.0 / 9.80665)


def test_decide_anchor_falls_to_session_best_on_a_fabricated_bin():
    import grip_anchor as ga
    from friction_envelope import FrictionBin

    fabricated = FrictionBin(
        speed_center_mps=25.0, combined_g_p95=1.0, lat_max_g=1.0,
        accel_max_g=0.6, brake_max_g=1.0, sample_count=3, confidence=0.0,
    )
    a = ga.decide_anchor(**_args(envelope_bin=fabricated))
    assert a.tier == ga.TIER_DRIVER_BEST_SESSION
    assert a.reason == ga.REASON_BIN_FABRICATED


def test_decide_anchor_refuses_when_nothing_is_available():
    import grip_anchor as ga

    a = ga.decide_anchor(**_args(
        friction=None, envelope_bin=None, session_best_lat_mps2=None,
    ))
    assert a.tier == ga.TIER_REFUSED
    assert a.reason == ga.REASON_NO_LAP_BASELINE
    assert a.pct is None
    assert a.baseline_g is None


def test_decide_anchor_is_fail_safe_when_trust_is_unmeasurable():
    """None trust ratio means 'could not look', which must NOT pass."""
    import grip_anchor as ga

    a = ga.decide_anchor(**_args(trust_ratio=None, envelope_bin=_measured_bin()))
    assert a.tier == ga.TIER_DRIVER_BEST_SESSION
    assert a.reason == ga.REASON_CHANNEL_UNTRUSTED


def test_decide_anchor_never_emits_a_tier_outside_the_vocabulary():
    import grip_anchor as ga

    for kwargs in (
        _args(envelope_bin=_measured_bin()),
        _args(trust_ratio=None),
        _args(friction=None, session_best_lat_mps2=None),
        _args(a_lat_mps2=np.nan),
    ):
        assert ga.decide_anchor(**kwargs).tier in ga.TIERS
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -k decide_anchor -v`
Expected: FAIL — no attribute `decide_anchor`.

- [ ] **Step 3: Implement**

Append to `telemetry_tool/grip_anchor.py`:

```python
_G: Final = 9.80665


@dataclass(frozen=True)
class Anchor:
    """One corner-lap's grip verdict. ``pct`` is never capped at 100."""
    tier: str
    reason: str | None
    pct: float | None
    baseline_g: float | None


def _session_best_anchor(
    a_lat_mps2: float, session_best_lat_mps2: float | None, reason: str,
) -> Anchor:
    """Tier 2: relative to the driver's own best in THIS session."""
    if (
        session_best_lat_mps2 is None
        or not np.isfinite(session_best_lat_mps2)
        or session_best_lat_mps2 <= 0
        or not np.isfinite(a_lat_mps2)
    ):
        return Anchor(TIER_REFUSED, REASON_NO_LAP_BASELINE, None, None)
    return Anchor(
        TIER_DRIVER_BEST_SESSION,
        reason,
        100.0 * abs(a_lat_mps2) / session_best_lat_mps2,
        session_best_lat_mps2 / _G,
    )


def decide_anchor(
    *,
    a_lat_mps2: float,
    a_long_mps2: float,
    speed_mps: float,
    friction: Any,
    envelope_bin: Any,
    trust_ratio: float | None,
    session_best_lat_mps2: float | None,
) -> Anchor:
    """Decide what this corner-lap's grip usage may honestly be quoted against.

    Fail-SAFE, strongest doubt first: an absent envelope, an unmeasurable
    sample, a fabricated bin or an untrusted channel each drop us to the
    session-relative tier; if even that is unavailable we refuse.
    """
    if friction is None:
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_NO_ENVELOPE)

    if not bin_is_measured(envelope_bin):
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_BIN_FABRICATED)

    if not channel_is_trusted(trust_ratio):
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_CHANNEL_UNTRUSTED)

    pct = ellipse_fill_pct(a_lat_mps2, a_long_mps2, speed_mps, friction)
    if pct is None:
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_NO_MEASUREMENT)

    try:
        baseline_g = _scalar(friction.lateral_max(speed_mps)) / _G
    except Exception:
        baseline_g = None

    tier = (
        TIER_PHYSICS_ELLIPSE_FITTED
        if getattr(friction, "exponent_source", "hint") == "fitted"
        else TIER_PHYSICS_ELLIPSE_DEFAULT_P2
    )
    return Anchor(tier, None, pct, baseline_g)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -v`
Expected: 25 passed.

- [ ] **Step 5: Bite-check**

Change `if not channel_is_trusted(trust_ratio):` to `if False:`. Re-run.
Expected: `test_decide_anchor_falls_to_session_best_when_the_channel_is_untrusted` and `test_decide_anchor_is_fail_safe_when_trust_is_unmeasurable` go RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/grip_anchor.py telemetry_tool/tests/test_grip_anchor.py
git commit -m "feat(grip_anchor): fail-safe tiered anchor decision"
```

---

### Task 7: Migration 085 + schema mirror + insert columns

**Files:**
- Create: `telemetry_tool/alembic/versions/085_grip_anchor.py`
- Modify: `telemetry_tool/db/schema.py`
- Modify: `telemetry_tool/db/queries.py:742-756`
- Test: `telemetry_tool/tests/test_grip_anchor_pipeline.py`

**Interfaces:**
- Consumes: nothing.
- Produces: four columns on `corner_metrics`: `grip_anchor_tier TEXT`, `grip_anchor_reason TEXT`, `grip_anchor_pct DOUBLE PRECISION`, `grip_anchor_baseline_g DOUBLE PRECISION`.

The single alembic head is `084_merge_chain_ab` (verified). **The `db/schema.py` mirror and `SCHEMA_VERSION` bump are not optional** — the standard pytest fixture builds from `db/schema.py`, so a table that exists only in Alembic cannot be unit-tested. That omission is precisely why `store_corner_progression` was written, never wired, and never testable.

- [ ] **Step 1: Read the existing patterns**

Run: `sed -n '1,40p' telemetry_tool/alembic/versions/084_merge_chain_ab.py`
Run: `grep -n "corner_metrics" -A 25 telemetry_tool/db/schema.py | head -35`
Run: `grep -n "SCHEMA_VERSION" telemetry_tool/db/schema.py`

- [ ] **Step 2: Write the failing test**

Create `telemetry_tool/tests/test_grip_anchor_pipeline.py`:

```python
"""Grip anchor — schema, stage wiring and persistence."""
import numpy as np
import pandas as pd
import pytest


def test_corner_metrics_has_the_grip_anchor_columns(test_db):
    """The pytest fixture builds from db/schema.py, so a column that exists
    only in Alembic is invisible here — and therefore untestable."""
    cur = test_db.execute("SELECT * FROM corner_metrics LIMIT 0")
    cols = {d[0] for d in cur.description}

    assert "grip_anchor_tier" in cols
    assert "grip_anchor_reason" in cols
    assert "grip_anchor_pct" in cols
    assert "grip_anchor_baseline_g" in cols


def test_insert_corner_metric_carries_the_anchor_columns():
    from db.queries import INSERT_CORNER_METRIC

    for col in (
        "grip_anchor_tier", "grip_anchor_reason",
        "grip_anchor_pct", "grip_anchor_baseline_g",
    ):
        assert col in INSERT_CORNER_METRIC, f"{col} missing from the INSERT"
        assert f":{col}" in INSERT_CORNER_METRIC, f":{col} bind param missing"
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -v`
Expected: FAIL — the columns are absent.

- [ ] **Step 4: Create the migration**

Create `telemetry_tool/alembic/versions/085_grip_anchor.py`:

```python
"""085 -- grip anchor columns on corner_metrics.

Phase 1 of driving-pattern-recognition. Stores an honestly-labelled
"% of available grip used" alongside the legacy grip_utilization column,
which is deliberately left untouched (see the Phase 1 plan).

grip_anchor_pct is NOT capped at 100: the friction envelope is a percentile,
so exceeding it is expected and is the most diagnostic value available.
"""
from alembic import op
import sqlalchemy as sa

revision = "085_grip_anchor"
down_revision = "084_merge_chain_ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("corner_metrics", sa.Column("grip_anchor_tier", sa.Text(), nullable=True))
    op.add_column("corner_metrics", sa.Column("grip_anchor_reason", sa.Text(), nullable=True))
    op.add_column("corner_metrics", sa.Column("grip_anchor_pct", sa.Float(), nullable=True))
    op.add_column("corner_metrics", sa.Column("grip_anchor_baseline_g", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("corner_metrics", "grip_anchor_baseline_g")
    op.drop_column("corner_metrics", "grip_anchor_pct")
    op.drop_column("corner_metrics", "grip_anchor_reason")
    op.drop_column("corner_metrics", "grip_anchor_tier")
```

- [ ] **Step 5: Mirror in `db/schema.py` and bump `SCHEMA_VERSION`**

Add the four columns to the `corner_metrics` CREATE TABLE in `telemetry_tool/db/schema.py`, matching the style already used there (SQLite types — `TEXT` and `REAL`). Bump `SCHEMA_VERSION` by one.

- [ ] **Step 6: Add the columns to the INSERT**

In `telemetry_tool/db/queries.py`, extend `INSERT_CORNER_METRIC` (lines 742-756) so the column list ends with `grip_anchor_tier, grip_anchor_reason, grip_anchor_pct, grip_anchor_baseline_g` and the VALUES list ends with the matching `:grip_anchor_*` bind params. Keep the existing columns and their order unchanged.

- [ ] **Step 7: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -v`
Expected: 2 passed.

Run: `python -m pytest telemetry_tool/tests/ -k "schema or migration or corner_metric" -v --continue-on-collection-errors`
Expected: no new failures.

- [ ] **Step 8: Verify the alembic graph still has one head**

Run:
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
Expected: `HEADS: ['085_grip_anchor']` — exactly one. Note this parser must handle **annotated** assignments (`down_revision: Union[str, None] = (...)`); a parser that only handles plain assignments reports phantom extra heads.

- [ ] **Step 9: Bite-check**

Remove one column from `db/schema.py`. Re-run.
Expected: `test_corner_metrics_has_the_grip_anchor_columns` goes RED naming that column. Restore.

- [ ] **Step 10: Commit**

```bash
git add telemetry_tool/alembic/versions/085_grip_anchor.py telemetry_tool/db/schema.py telemetry_tool/db/queries.py telemetry_tool/tests/test_grip_anchor_pipeline.py
git commit -m "feat(db): grip anchor columns on corner_metrics (migration 085)"
```

---

### Task 8: Pipeline stage

**Files:**
- Create: `telemetry_tool/pipeline/stages/s10d2_grip_anchor.py`
- Test: `telemetry_tool/tests/test_grip_anchor_pipeline.py`

**Interfaces:**
- Consumes: `grip_anchor.decide_anchor`, `grip_anchor.channel_trust_ratio`.
- Produces:
```python
def run_grip_anchor(
    per_lap_corner_metrics: list[dict],
    corners: list[dict],
    resampled_laps: dict[int, pd.DataFrame],
    *,
    friction_model: Any = None,
    friction_envelope: Any = None,
    curvature_profile: Any = None,
) -> list[dict]
```
It returns the SAME list, with each dict gaining `grip_anchor_tier`, `grip_anchor_reason`, `grip_anchor_pct`, `grip_anchor_baseline_g`.

Each per-lap metric dict carries at least `lap_number`, `corner_id`, `apex_speed_mps` (see `s10b_corners.py:360-378`).

The session-best baseline for tier 2 is the maximum lateral acceleration observed at that corner across all laps **in this session** — computed in this same pass, because `corner_id` is only self-consistent within one session.

- [ ] **Step 1: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor_pipeline.py`:

```python
def _lap_frame(n=400, a_lat_g=0.9):
    d = np.linspace(0.0, 1200.0, n)
    return pd.DataFrame({
        "Distance (m)": d,
        "Speed (m/s)": np.full(n, 25.0),
        "Lateral acceleration (G) *calc": np.full(n, a_lat_g),
        "accel_long_mps2": np.zeros(n),
    })


def test_run_grip_anchor_attaches_a_tier_to_every_metric():
    from pipeline.stages import s10d2_grip_anchor

    metrics = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 25.0},
    ]
    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    laps = {1: _lap_frame(a_lat_g=0.9), 2: _lap_frame(a_lat_g=1.1)}

    out = s10d2_grip_anchor.run_grip_anchor(metrics, corners, laps)

    assert len(out) == 2
    for m in out:
        assert "grip_anchor_tier" in m
        assert m["grip_anchor_tier"] is not None


def test_run_grip_anchor_refuses_rather_than_inventing_when_it_has_nothing():
    """No friction model, no usable laps: it must refuse, not fabricate."""
    import grip_anchor as ga
    from pipeline.stages import s10d2_grip_anchor

    metrics = [{"lap_number": 1, "corner_id": 1, "apex_speed_mps": 25.0}]
    out = s10d2_grip_anchor.run_grip_anchor(metrics, [], {})

    assert out[0]["grip_anchor_tier"] == ga.TIER_REFUSED
    assert out[0]["grip_anchor_pct"] is None


def test_run_grip_anchor_never_raises_on_malformed_input():
    """This runs inside _safe_step, but a stage that throws loses the whole
    step; assert on RESULTS, not on the absence of an exception."""
    from pipeline.stages import s10d2_grip_anchor

    out = s10d2_grip_anchor.run_grip_anchor(
        [{"lap_number": None, "corner_id": None}], [], {},
    )
    assert len(out) == 1
    assert "grip_anchor_tier" in out[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -k run_grip_anchor -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.stages.s10d2_grip_anchor'`.

- [ ] **Step 3: Implement**

Create `telemetry_tool/pipeline/stages/s10d2_grip_anchor.py`:

```python
"""Step 10d2: attach an honestly-labelled grip anchor to each corner-lap.

Runs immediately after 10d_per_lap_corners, the only point where the friction
model, the corner list, the resampled laps and the per-lap metrics all coexist.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

import grip_anchor as ga
from corner_analysis import _resolve_accel_lat

logger = logging.getLogger(__name__)

_ANCHOR_KEYS = (
    "grip_anchor_tier", "grip_anchor_reason",
    "grip_anchor_pct", "grip_anchor_baseline_g",
)


def _corner_mask(lap_df: pd.DataFrame, corner: dict) -> np.ndarray | None:
    """Distances are 0-based per-lap metres (canonical frame, see
    resampling.resample_lap_by_distance)."""
    col = next((c for c in ("Distance (m)", "distance_m") if c in lap_df.columns), None)
    if col is None:
        return None
    dist = pd.to_numeric(lap_df[col], errors="coerce").values
    mask = (dist >= float(corner.get("s_start", 0.0))) & (dist <= float(corner.get("s_end", 0.0)))
    return mask if mask.sum() >= 3 else None


def _apply(metric: dict, anchor: ga.Anchor) -> None:
    metric["grip_anchor_tier"] = anchor.tier
    metric["grip_anchor_reason"] = anchor.reason
    metric["grip_anchor_pct"] = anchor.pct
    metric["grip_anchor_baseline_g"] = anchor.baseline_g


def run_grip_anchor(
    per_lap_corner_metrics: list[dict[str, Any]],
    corners: list[dict[str, Any]],
    resampled_laps: dict[int, pd.DataFrame],
    *,
    friction_model: Any = None,
    friction_envelope: Any = None,
    curvature_profile: Any = None,
) -> list[dict[str, Any]]:
    """Attach grip_anchor_* to every metric dict. Returns the same list."""
    metrics = list(per_lap_corner_metrics or [])
    if not metrics:
        return metrics

    corners_by_id = {c.get("corner_id"): c for c in (corners or [])}

    # Peak lateral per (corner, lap), and the session best per corner. Both
    # come from this session only: corner_id is not stable across sessions.
    peak: dict[tuple[Any, Any], float] = {}
    for lap_num, lap_df in (resampled_laps or {}).items():
        if lap_df is None or len(lap_df) < 10:
            continue
        a_lat = _resolve_accel_lat(lap_df)          # already m/s², already abs
        for cid, corner in corners_by_id.items():
            mask = _corner_mask(lap_df, corner)
            if mask is None:
                continue
            vals = a_lat[mask]
            vals = vals[np.isfinite(vals)]
            if vals.size:
                peak[(cid, lap_num)] = float(np.nanmax(vals))

    session_best: dict[Any, float] = {}
    for (cid, _lap), v in peak.items():
        if v > session_best.get(cid, 0.0):
            session_best[cid] = v

    # One trust ratio per session, over cornering samples only.
    trust = _session_trust_ratio(resampled_laps, curvature_profile)

    for m in metrics:
        try:
            cid, lap_num = m.get("corner_id"), m.get("lap_number")
            anchor = ga.decide_anchor(
                a_lat_mps2=peak.get((cid, lap_num), float("nan")),
                a_long_mps2=0.0,
                speed_mps=float(m.get("apex_speed_mps") or 0.0),
                friction=friction_model,
                envelope_bin=_bin_for_speed(friction_envelope, m.get("apex_speed_mps")),
                trust_ratio=trust,
                session_best_lat_mps2=session_best.get(cid),
            )
        except Exception:
            logger.debug("grip anchor failed for corner=%s lap=%s", m.get("corner_id"), m.get("lap_number"))
            anchor = ga.Anchor(ga.TIER_REFUSED, ga.REASON_NO_MEASUREMENT, None, None)
        _apply(m, anchor)

    tiers = {}
    for m in metrics:
        tiers[m["grip_anchor_tier"]] = tiers.get(m["grip_anchor_tier"], 0) + 1
    logger.info("Grip anchor tiers across %d corner-laps: %s", len(metrics), tiers)
    return metrics


def _bin_for_speed(envelope: Any, speed: Any) -> Any:
    """Nearest friction bin to this corner's apex speed, or None."""
    bins = getattr(envelope, "friction_bins", None)
    if not bins or speed is None:
        return None
    try:
        v = float(speed)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return min(bins, key=lambda b: abs(float(b.speed_center_mps) - v))


def _session_trust_ratio(
    resampled_laps: dict[int, pd.DataFrame] | None, curvature_profile: Any,
) -> float | None:
    """Median |a_lat| / (v^2*kappa) over cornering samples across all laps."""
    if not resampled_laps or curvature_profile is None:
        return None
    try:
        cp_d = pd.to_numeric(curvature_profile["distance_m"], errors="coerce").values
        cp_k = pd.to_numeric(curvature_profile["curvature_1pm"], errors="coerce").values
    except Exception:
        return None

    ratios = []
    for lap_df in resampled_laps.values():
        if lap_df is None or len(lap_df) < 50:
            continue
        col = next((c for c in ("Distance (m)", "distance_m") if c in lap_df.columns), None)
        spd = next((c for c in ("Speed (m/s)", "speed_mps") if c in lap_df.columns), None)
        if col is None or spd is None:
            continue
        d = pd.to_numeric(lap_df[col], errors="coerce").values
        v = pd.to_numeric(lap_df[spd], errors="coerce").values
        r = ga.channel_trust_ratio(_resolve_accel_lat(lap_df), v, np.interp(d, cp_d, cp_k))
        if r is not None:
            ratios.append(r)
    return float(np.median(ratios)) if ratios else None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -v`
Expected: 5 passed.

- [ ] **Step 5: Bite-check**

In `decide_anchor`'s refusal path, change `REASON_NO_LAP_BASELINE` to `REASON_NO_ENVELOPE`. Re-run.
Expected: `test_run_grip_anchor_refuses_rather_than_inventing_when_it_has_nothing` still passes (it only checks the tier) but `test_decide_anchor_refuses_when_nothing_is_available` in `test_grip_anchor.py` goes RED. Restore. **If neither goes red, the refusal path is untested — say so and add a reason assertion.**

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/pipeline/stages/s10d2_grip_anchor.py telemetry_tool/tests/test_grip_anchor_pipeline.py
git commit -m "feat(pipeline): step 10d2 attaches a tiered grip anchor to each corner-lap"
```

---

### Task 9: Wire the stage into the orchestrator and persist

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py` (immediately after the `10d_per_lap_corners` `_record`)
- Modify: `telemetry_tool/web/repos/score_repo.py:92` — the sole writer of `INSERT_CORNER_METRIC`
- Test: `telemetry_tool/tests/test_grip_anchor_pipeline.py`

**Interfaces:**
- Consumes: `s10d2_grip_anchor.run_grip_anchor`.
- Produces: per-lap corner metric dicts carrying `grip_anchor_*`, persisted to `corner_metrics`.

Verified for you: `score_repo.py:92` is the ONLY caller of `INSERT_CORNER_METRIC`. And `curvature_profile` is assigned at `orchestrator.py:888` and remains in scope at the hook, so it can be passed straight through.

- [ ] **Step 1: Read both sites**

Run: `grep -n "10d_per_lap_corners" -B 4 -A 8 telemetry_tool/pipeline/orchestrator.py`
Run: `sed -n '80,115p' telemetry_tool/web/repos/score_repo.py`

Confirm the local variable holding the per-lap metrics (the plan assumes `_plcm`) and the exact shape of the dict `score_repo` binds.

- [ ] **Step 2: Write the failing test**

Append to `telemetry_tool/tests/test_grip_anchor_pipeline.py`:

```python
def test_orchestrator_runs_the_grip_anchor_step():
    import inspect
    from pipeline import orchestrator

    src = inspect.getsource(orchestrator)
    assert "s10d2_grip_anchor" in src, "the grip anchor stage is not wired in"
    assert "10d2_grip_anchor" in src, "the step is not recorded under its own name"


def test_corner_metric_writer_binds_the_anchor_params(test_db):
    """A missing bind param raises at execute time in prod but is invisible
    until then — assert the round-trip stores and returns the values."""
    from db.queries import INSERT_CORNER_METRIC

    row = {
        "session_id": "s1", "lap_number": 1, "corner_id": 1,
        "brake_point_m": None, "brake_intensity": None,
        "entry_speed_mps": None, "apex_speed_mps": 25.0, "exit_speed_mps": None,
        "throttle_onset_m": None, "exit_accel_mps2": None,
        "grip_utilization": None, "time_loss_ms": None, "coaching_hint": None,
        "grip_anchor_tier": "physics_ellipse_fitted",
        "grip_anchor_reason": None,
        "grip_anchor_pct": 137.5,
        "grip_anchor_baseline_g": 1.33,
    }
    test_db.execute(INSERT_CORNER_METRIC, row)
    test_db.commit()

    got = test_db.execute(
        "SELECT grip_anchor_tier, grip_anchor_pct FROM corner_metrics "
        "WHERE session_id='s1' AND lap_number=1 AND corner_id=1"
    ).fetchone()

    assert got[0] == "physics_ellipse_fitted"
    assert got[1] == pytest.approx(137.5)   # NOT clamped to 100
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -k "orchestrator or writer" -v`
Expected: both FAIL.

- [ ] **Step 4: Wire the stage**

In `telemetry_tool/pipeline/orchestrator.py`, immediately after the `_record("10d_per_lap_corners", ...)` line, add:

```python
    # Step 10d2 — tiered grip anchor. Runs here because this is the only point
    # where the friction model, corners, resampled laps and per-lap metrics
    # all coexist. Every downstream number is quoted against this.
    if _plcm:
        _plcm, err = _safe_step(
            "10d2_grip_anchor", s10d2_grip_anchor.run_grip_anchor,
            _plcm, corners, resampled_laps,
            friction_model=summary.get("friction_model"),
            friction_envelope=summary.get("friction_envelope"),
            curvature_profile=curvature_profile,
        )
        _record("10d2_grip_anchor", _plcm, err)
```

Add `s10d2_grip_anchor` to the stage imports at the top of the file, matching the existing import style. Verify the local variable holding the per-lap metrics is really named `_plcm` and that `curvature_profile` is in scope at that point — read the surrounding lines and use the actual names.

- [ ] **Step 5: Pass the params in the writer**

In `telemetry_tool/web/repos/score_repo.py:92`, add these four entries to the dict bound into `Q.INSERT_CORNER_METRIC`, matching the `.get()` style of the surrounding keys so a metric dict lacking them still inserts:

```python
            "grip_anchor_tier": m.get("grip_anchor_tier"),
            "grip_anchor_reason": m.get("grip_anchor_reason"),
            "grip_anchor_pct": m.get("grip_anchor_pct"),
            "grip_anchor_baseline_g": m.get("grip_anchor_baseline_g"),
```

Use whatever the loop variable is actually called there (the plan assumes `m`) — read lines 80-115 and match it.

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -v`
Expected: 7 passed.

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor.py -v`
Expected: 25 passed.

- [ ] **Step 7: Bite-check**

Remove the `grip_anchor_pct` bind param from the writer dict. Re-run.
Expected: `test_corner_metric_writer_binds_the_anchor_params` goes RED. Restore.

- [ ] **Step 8: Commit**

```bash
git add telemetry_tool/pipeline/orchestrator.py telemetry_tool/tests/test_grip_anchor_pipeline.py
git add -u telemetry_tool/
git commit -m "feat(pipeline): wire the grip anchor stage and persist its columns"
```

---

### Task 10: Real-data validation

**Files:**
- Test: `telemetry_tool/tests/test_grip_anchor_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing consumed downstream. This is the acceptance gate.

Unit tests prove the logic; this proves it survives real telemetry. `telemetry_tool/data/raw/OK_R4.csv` is a real RaceChrono kart export (211,002 rows, 10 laps) already in the repo.

**Isolation is mandatory:** any test that drives the real pipeline must monkeypatch `track_detection._default_db_path` to a `tmp_path` file, or it appends fingerprint entries to the tracked `telemetry_tool/models/tracks.json` on every run. This already happened once on the parent branch.

- [ ] **Step 1: Write the test**

Append to `telemetry_tool/tests/test_grip_anchor_pipeline.py`:

```python
import os

_REAL_CSV = "telemetry_tool/data/raw/OK_R4.csv"


@pytest.fixture
def _isolated_track_registry(tmp_path, monkeypatch):
    """Keep the pipeline's track-registration write off the tracked
    models/tracks.json — see the parent branch's test-hygiene incident."""
    import track_detection
    monkeypatch.setattr(
        track_detection, "_default_db_path", lambda: str(tmp_path / "tracks.json")
    )


@pytest.mark.skipif(not os.path.exists(_REAL_CSV), reason="real fixture absent")
def test_grip_anchor_on_real_kart_telemetry(_isolated_track_registry):
    """Acceptance: on real data every corner-lap gets a tier from the closed
    vocabulary, physics-tier percentages are physically plausible, and the
    trust ratio lands near the 0.961 measured during design."""
    import grip_anchor as ga
    from pipeline import run_full_analysis

    summary = run_full_analysis(_REAL_CSV)
    metrics = summary.get("per_lap_corner_metrics") or []
    assert metrics, "no per-lap corner metrics produced"

    tiers = [m.get("grip_anchor_tier") for m in metrics]
    assert all(t in ga.TIERS for t in tiers), f"tier outside vocabulary: {set(tiers)}"

    # Every lap must be represented — the parent branch fixed the bug where
    # only lap 1 produced corner data.
    laps = {m["lap_number"] for m in metrics}
    assert len(laps) >= 5, f"only {len(laps)} laps produced corner metrics: {laps}"

    physics = [
        m for m in metrics
        if ga.is_quotable_as_physics(m.get("grip_anchor_tier"))
        and m.get("grip_anchor_pct") is not None
    ]
    for m in physics:
        assert 0.0 <= m["grip_anchor_pct"] <= 300.0, (
            f"implausible grip pct {m['grip_anchor_pct']} "
            f"(lap {m['lap_number']} corner {m['corner_id']})"
        )
        assert 0.2 <= m["grip_anchor_baseline_g"] <= 3.0, (
            f"implausible baseline {m['grip_anchor_baseline_g']} G"
        )

    print(f"\ntier distribution: "
          f"{ {t: tiers.count(t) for t in set(tiers)} }")
```

- [ ] **Step 2: Run it**

Run: `python -m pytest telemetry_tool/tests/test_grip_anchor_pipeline.py -k real_kart -v -s`
Expected: PASS. Record the printed tier distribution in your report — it is the headline result of Phase 1.

- [ ] **Step 3: Check the working tree is clean**

Run: `git status --short`
Expected: only untracked `telemetry_tool/data/cache/`. If `telemetry_tool/models/tracks.json` appears as modified, the isolation fixture is not working — fix it before continuing.

- [ ] **Step 4: Bite-check**

In `grip_anchor.decide_anchor`, change the final return's tier to a literal `"made_up_tier"`. Re-run.
Expected: the vocabulary assertion goes RED. Restore.

- [ ] **Step 5: Interpret the result and report**

If **every** corner-lap came back `refused` or `driver_best_session`, Phase 1 has not delivered its headline claim. Report which reason dominates and why — the reason taxonomy exists precisely so this is diagnosable rather than mysterious. Do not adjust thresholds to manufacture a physics tier.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/tests/test_grip_anchor_pipeline.py
git commit -m "test(grip_anchor): acceptance on real kart telemetry"
```

---

## Known not-covered by Phase 1

State these plainly so nobody assumes otherwise:

- **Cross-session tier 2** (`driver_best_track`). Requires stable corner identity across sessions; `corner_persistence.match_corners` exists but has zero production callers. Phase 2.
- **Condition scoping.** `sessions.track_state` is `NOT NULL DEFAULT 'dry'` and the upload UI never sets it, so `dry` frequently means "nobody said". `REASON_CONDITION_UNKNOWN` is reserved but never emitted in Phase 1.
- **Longitudinal usage.** Phase 1 anchors on peak lateral only; `a_long_mps2` is threaded through `decide_anchor` and `ellipse_fill_pct` but passed as `0.0` by the stage. Wiring a real longitudinal value is Phase 2, and the low-speed traction envelope is known-broken (0.07–0.22 g measured at 8–13 m/s against a real 0.33 g) so it needs its own gate.
- **The legacy `grip_utilization` column** is untouched and still capped at 100. Two percentages now exist on `corner_metrics`; Phase 2 decides which the API serves.
- **No frontend.** Phase 1 persists and serves via the existing `SELECT *` endpoint; rendering is Phase 3.
- **`DataQualityReport`'s signals** (`gps_quality`, `accel_quality`, `yaw_quality`) remain unpersisted on this branch — a separate one-line fix landed on `fix/per-lap-distance-frame` for `summary["data_quality"]`, but the report's per-channel sub-scores are still unused as gate inputs.
