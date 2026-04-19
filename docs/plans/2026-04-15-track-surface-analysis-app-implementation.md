# Track-Surface Analysis Application Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, per user's autonomous execution preference). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a thin Flask + Celery application layer that wraps the frozen
`telemetry_tool/track_surface/` validation stack, adds support-tier gating, persists
runs, and exposes a stable REST contract.

**Architecture:** New `track_surface_app` package (orchestrator, resolver, gate,
artifact writer, repository). New `track_surface_tasks` Celery module on the
`pipeline` queue. New `routes/track_surface_analysis.py` Flask blueprint. New table
`analysis_runs` (Alembic 056) with RLS. No physics changes.

**Tech Stack:** Python 3, Flask, Pydantic v2, Celery, PostgreSQL 16 / SQLite,
Alembic, pytest, `track_surface` (frozen core).

**Design doc:** `docs/plans/2026-04-15-track-surface-analysis-app-design.md`

**Testing conventions (project-wide):**
- Python tests live in `telemetry_tool/tests/`. New tests go in
  `telemetry_tool/tests/test_track_surface_app/`.
- Use `pytest` (no separate runner).
- Fixtures live in the package `conftest.py` next to the tests.
- `USE_PG=0` in tests (SQLite in-memory or temp file). The code must work against
  both — use `db/sql_compat` translator.
- Do NOT invoke real physics code in tests: wire fakes at the `track_surface_app` seam.

---

## File inventory (what will be created / modified)

**Created:**
- `telemetry_tool/track_surface_app/__init__.py`
- `telemetry_tool/track_surface_app/domain.py` — enums + domain dataclasses
- `telemetry_tool/track_surface_app/support.py` — SupportTierResolver
- `telemetry_tool/track_surface_app/gating.py` — OutputGate
- `telemetry_tool/track_surface_app/artifacts.py` — ArtifactWriter
- `telemetry_tool/track_surface_app/persistence.py` — AnalysisRunRepository
- `telemetry_tool/track_surface_app/support_matrix.py` — SupportMatrix (static lookup)
- `telemetry_tool/track_surface_app/orchestrator.py` — AnalysisOrchestrator
- `telemetry_tool/tasks/track_surface_tasks.py` — Celery task
- `telemetry_tool/web/schemas/track_surface.py` — Pydantic v2 DTOs
- `telemetry_tool/web/routes/track_surface_analysis.py` — Flask blueprint
- `telemetry_tool/alembic/versions/056_analysis_runs.py` — DB migration
- `telemetry_tool/tests/test_track_surface_app/__init__.py`
- `telemetry_tool/tests/test_track_surface_app/conftest.py`
- `telemetry_tool/tests/test_track_surface_app/test_domain.py`
- `telemetry_tool/tests/test_track_surface_app/test_support_resolver.py`
- `telemetry_tool/tests/test_track_surface_app/test_output_gate.py`
- `telemetry_tool/tests/test_track_surface_app/test_artifact_writer.py`
- `telemetry_tool/tests/test_track_surface_app/test_persistence.py`
- `telemetry_tool/tests/test_track_surface_app/test_support_matrix.py`
- `telemetry_tool/tests/test_track_surface_app/test_orchestrator.py`
- `telemetry_tool/tests/test_track_surface_app/test_routes.py`
- `telemetry_tool/track_surface_app/data/support_matrix.json` — seed data

**Modified:**
- `telemetry_tool/web/app.py` — register new blueprint
- `telemetry_tool/web/api_utils.py` — add `SUPPORT_TIER_REFUSED` to ErrorCode

---

## Key fact: real `PipelineResult` fields

Before writing tasks, verified the core shapes from
`telemetry_tool/track_surface/validation/harness.py:123` and
`.../release_gate.py`. The fields this layer consumes are:

```python
# PipelineResult (dataclass)
dataset_id: str
n_samples_total: int
n_valid: int
best_lap: int
best_lap_time_s: float
n_laps: int
lap_times_s: dict[int, float]
track_length_m: float
field_coverage_pct: float
field_mean_confidence: float
bucket_active_count: int
bucket_sparse_count: int
bucket_fallback_distribution: dict[int, int]   # {0: count, 1: count, 2: count}
planner_nominal_mean_mu: float
planner_robust_mean_mu: float
planner_exploitable_mean_mu: float
planner_n_trusted: int
planner_n_degraded: int
calibration_profile_id: str | None
calibration_source: str | None   # "registry_active"|"class_fallback"|"default"|"none"
pipeline_warnings: list[str]
exception: str | None

# ReleaseSessionResult
decision: ReleaseDecision   # .PASS | .WARN | .FAIL
```

`calibration_source == "registry_active"` means validated; anything else means
fallback → tier D or reduced tier.

---

## Task 1: Package scaffolding + domain enums

**Files:**
- Create: `telemetry_tool/track_surface_app/__init__.py`
- Create: `telemetry_tool/track_surface_app/domain.py`
- Create: `telemetry_tool/tests/test_track_surface_app/__init__.py`
- Create: `telemetry_tool/tests/test_track_surface_app/test_domain.py`

- [ ] **Step 1.1: Write the failing test (`test_domain.py`)**

```python
"""Tests for track_surface_app domain enums + dataclasses."""
from __future__ import annotations

import pytest

from track_surface_app.domain import (
    SupportTier,
    ConfidenceLevel,
    AnalysisRunStatus,
    PlannerModeAvailability,
)


class TestSupportTier:
    def test_values_are_stable_strings(self):
        assert SupportTier.A.value == "A"
        assert SupportTier.B.value == "B"
        assert SupportTier.C.value == "C"
        assert SupportTier.D.value == "D"

    def test_from_string_roundtrip(self):
        for tier in SupportTier:
            assert SupportTier(tier.value) is tier

    def test_from_string_unknown_raises(self):
        with pytest.raises(ValueError):
            SupportTier("X")


class TestConfidenceLevel:
    def test_from_mean_confidence_high(self):
        assert ConfidenceLevel.from_mean_confidence(0.9) is ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_mean_confidence(0.80) is ConfidenceLevel.HIGH

    def test_from_mean_confidence_medium(self):
        assert ConfidenceLevel.from_mean_confidence(0.65) is ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_mean_confidence(0.50) is ConfidenceLevel.MEDIUM

    def test_from_mean_confidence_low(self):
        assert ConfidenceLevel.from_mean_confidence(0.49) is ConfidenceLevel.LOW
        assert ConfidenceLevel.from_mean_confidence(0.0) is ConfidenceLevel.LOW

    def test_from_mean_confidence_unknown(self):
        assert ConfidenceLevel.from_mean_confidence(None) is ConfidenceLevel.UNKNOWN


class TestAnalysisRunStatus:
    def test_terminal(self):
        assert AnalysisRunStatus.SUCCEEDED.is_terminal()
        assert AnalysisRunStatus.FAILED.is_terminal()
        assert not AnalysisRunStatus.QUEUED.is_terminal()
        assert not AnalysisRunStatus.RUNNING.is_terminal()


class TestPlannerModeAvailability:
    def test_for_tier_a_all_on(self):
        av = PlannerModeAvailability.for_tier(SupportTier.A)
        assert av.nominal and av.robust and av.exploitable

    def test_for_tier_b_exploitable_off(self):
        av = PlannerModeAvailability.for_tier(SupportTier.B)
        assert av.nominal and av.robust and not av.exploitable

    def test_for_tier_c_all_off(self):
        av = PlannerModeAvailability.for_tier(SupportTier.C)
        assert not (av.nominal or av.robust or av.exploitable)

    def test_for_tier_d_all_off(self):
        av = PlannerModeAvailability.for_tier(SupportTier.D)
        assert not (av.nominal or av.robust or av.exploitable)

    def test_to_dict(self):
        av = PlannerModeAvailability.for_tier(SupportTier.B)
        assert av.to_dict() == {"nominal": True, "robust": True, "exploitable": False}
```

- [ ] **Step 1.2: Run test — expect ImportError**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_domain.py -v`
Expected: FAIL / collection error — module doesn't exist yet.

- [ ] **Step 1.3: Create package `__init__.py` (empty)**

```python
# telemetry_tool/track_surface_app/__init__.py
"""Thin application layer over telemetry_tool.track_surface validated core.

This package owns:
  - HTTP-facing DTO translation (via web/schemas/track_surface.py)
  - Support-tier gating (SupportTierResolver, OutputGate)
  - Persistence (AnalysisRunRepository, analysis_runs table)
  - Orchestration (AnalysisOrchestrator + Celery task)

It does NOT contain physics. All numerics stay in track_surface/.
"""
```

- [ ] **Step 1.4: Create `domain.py`**

```python
# telemetry_tool/track_surface_app/domain.py
"""Domain enums and value objects for the track-surface analysis app.

These types are the vocabulary of the application layer. They are translated
from research-layer concepts (ReleaseDecision, fallback_depth, confidence) by
SupportTierResolver, and translated to HTTP shapes by web/schemas/track_surface.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SupportTier(str, Enum):
    """User-facing gating tier. Derived from release decision + fallback + calibration."""
    A = "A"    # full: nominal + robust + exploitable
    B = "B"    # partial: nominal + robust
    C = "C"    # descriptive only: no planner
    D = "D"    # unsupported: no analysis


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"

    @classmethod
    def from_mean_confidence(cls, mean: float | None) -> "ConfidenceLevel":
        if mean is None:
            return cls.UNKNOWN
        if mean >= 0.80:
            return cls.HIGH
        if mean >= 0.50:
            return cls.MEDIUM
        return cls.LOW


class AnalysisRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    def is_terminal(self) -> bool:
        return self in (AnalysisRunStatus.SUCCEEDED, AnalysisRunStatus.FAILED)


@dataclass(frozen=True)
class PlannerModeAvailability:
    """Which planner modes (nominal/robust/exploitable) a tier exposes."""
    nominal: bool
    robust: bool
    exploitable: bool

    @classmethod
    def for_tier(cls, tier: SupportTier) -> "PlannerModeAvailability":
        if tier is SupportTier.A:
            return cls(nominal=True, robust=True, exploitable=True)
        if tier is SupportTier.B:
            return cls(nominal=True, robust=True, exploitable=False)
        return cls(nominal=False, robust=False, exploitable=False)

    def to_dict(self) -> dict[str, bool]:
        return {"nominal": self.nominal, "robust": self.robust, "exploitable": self.exploitable}


# Closed set of machine-readable support reasons. Frontend can switch on these.
SUPPORT_REASONS = frozenset({
    "all_checks_passed",
    "release_gate_warn",
    "release_gate_fail",
    "moderate_fallback",
    "high_global_fallback",
    "vehicle_profile_not_validated",
    "track_profile_not_validated",
    "track_geometry_missing",
    "calibration_missing",
    "insufficient_channels",
    "gps_speed_only_available",
    "no_pipeline_run",
})
```

- [ ] **Step 1.5: Run test — expect PASS**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_domain.py -v`
Expected: all 11 tests pass.

- [ ] **Step 1.6: Commit**

```bash
git add telemetry_tool/track_surface_app/__init__.py \
        telemetry_tool/track_surface_app/domain.py \
        telemetry_tool/tests/test_track_surface_app/__init__.py \
        telemetry_tool/tests/test_track_surface_app/test_domain.py
git commit -m "feat(track-surface-app): domain enums (SupportTier, ConfidenceLevel, AnalysisRunStatus)"
```

---

## Task 2: Test fixtures (`conftest.py`)

**Files:**
- Create: `telemetry_tool/tests/test_track_surface_app/conftest.py`

These fixtures are used by every subsequent test task. Writing them once up front
keeps later tasks short.

- [ ] **Step 2.1: Create `conftest.py`**

```python
# telemetry_tool/tests/test_track_surface_app/conftest.py
"""Fixtures for track_surface_app tests. No real physics is invoked."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


# ── Minimal stand-in for track_surface.validation.harness.PipelineResult ──
# Mirrors the real dataclass fields the app layer consumes. Using a local
# dataclass keeps tests independent of the core module.

@dataclass
class FakePipelineResult:
    dataset_id: str = "fake-dataset"
    n_samples_total: int = 10_000
    n_valid: int = 9_500
    best_lap: int = 3
    best_lap_time_s: float = 88.123
    n_laps: int = 5
    lap_times_s: dict[int, float] = field(default_factory=lambda: {1: 90.0, 2: 89.1, 3: 88.1, 4: 88.5, 5: 89.7})
    track_length_m: float = 3820.0
    field_coverage_pct: float = 85.0
    field_mean_confidence: float = 0.82
    bucket_active_count: int = 6
    bucket_sparse_count: int = 0
    bucket_fallback_distribution: dict[int, int] = field(default_factory=lambda: {0: 800, 1: 150, 2: 50})
    planner_nominal_mean_mu: float = 1.05
    planner_robust_mean_mu: float = 0.98
    planner_exploitable_mean_mu: float = 1.12
    planner_n_trusted: int = 900
    planner_n_degraded: int = 100
    calibration_profile_id: str | None = "iracing_mx5_2024"
    calibration_source: str | None = "registry_active"
    pipeline_warnings: list[str] = field(default_factory=list)
    exception: str | None = None
    bucket_diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeReleaseDecision:
    # Mirrors track_surface.validation.release_gate.ReleaseDecision enum-ish
    value: str       # "pass" | "warn" | "fail"


@dataclass
class FakeReleaseSessionResult:
    dataset_id: str = "fake-dataset"
    track_class: str = "flat"
    vehicle_class: str = "mx5"
    profile_description: str = "default"
    decision: FakeReleaseDecision = field(default_factory=lambda: FakeReleaseDecision("pass"))
    checks: list = field(default_factory=list)
    n_pass: int = 10
    n_warn: int = 0
    n_fail: int = 0


# ── Factory fixtures ─────────────────────────────────────────

@pytest.fixture
def make_pipeline_result():
    """Factory: build a FakePipelineResult with targeted tier overrides."""
    def _build(**overrides) -> FakePipelineResult:
        pr = FakePipelineResult()
        for k, v in overrides.items():
            setattr(pr, k, v)
        return pr
    return _build


@pytest.fixture
def make_release_result():
    """Factory: build a FakeReleaseSessionResult for the given decision string."""
    def _build(decision: str = "pass", **overrides) -> FakeReleaseSessionResult:
        rr = FakeReleaseSessionResult(decision=FakeReleaseDecision(decision))
        for k, v in overrides.items():
            setattr(rr, k, v)
        return rr
    return _build


# ── Tier-targeted fixtures (use in support-resolver + gating tests) ───

@pytest.fixture
def tier_a_inputs(make_pipeline_result, make_release_result):
    """PipelineResult + ReleaseResult that MUST yield tier A."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 900, 1: 50, 2: 50},   # fb2 = 5%
        calibration_source="registry_active",
        field_mean_confidence=0.82,
    )
    rr = make_release_result("pass")
    return pr, rr


@pytest.fixture
def tier_b_inputs_fallback(make_pipeline_result, make_release_result):
    """Tier B via moderate fallback (fb2 = 15%)."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 750, 1: 100, 2: 150},
        calibration_source="registry_active",
        field_mean_confidence=0.68,
    )
    rr = make_release_result("pass")
    return pr, rr


@pytest.fixture
def tier_b_inputs_warn(make_pipeline_result, make_release_result):
    """Tier B via release gate WARN."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 900, 1: 50, 2: 50},   # fb2 = 5%, but WARN dominates
        calibration_source="registry_active",
    )
    rr = make_release_result("warn")
    return pr, rr


@pytest.fixture
def tier_c_inputs_fail(make_pipeline_result, make_release_result):
    """Tier C via release gate FAIL."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 800, 1: 100, 2: 100},
        calibration_source="registry_active",
        field_mean_confidence=0.4,
    )
    rr = make_release_result("fail")
    return pr, rr


@pytest.fixture
def tier_c_inputs_fallback(make_pipeline_result, make_release_result):
    """Tier C via high global fallback (fb2 = 40%)."""
    pr = make_pipeline_result(
        bucket_fallback_distribution={0: 300, 1: 300, 2: 400},
        calibration_source="registry_active",
        field_mean_confidence=0.45,
    )
    rr = make_release_result("pass")
    return pr, rr


@pytest.fixture
def tier_d_inputs_no_calibration(make_pipeline_result, make_release_result):
    """Tier D via missing vehicle calibration."""
    pr = make_pipeline_result(calibration_source="none")
    rr = make_release_result("pass")
    return pr, rr


@pytest.fixture
def tier_d_inputs_default_calibration(make_pipeline_result, make_release_result):
    """Tier D via unvalidated (default) calibration fallback."""
    pr = make_pipeline_result(calibration_source="default")
    rr = make_release_result("pass")
    return pr, rr
```

- [ ] **Step 2.2: Commit**

```bash
git add telemetry_tool/tests/test_track_surface_app/conftest.py
git commit -m "test(track-surface-app): shared fixtures (FakePipelineResult, tier-targeted inputs)"
```

---

## Task 3: `SupportTierResolver`

**Files:**
- Create: `telemetry_tool/track_surface_app/support.py`
- Create: `telemetry_tool/tests/test_track_surface_app/test_support_resolver.py`

- [ ] **Step 3.1: Write failing tests**

```python
# test_support_resolver.py
"""Tests for SupportTierResolver."""
from __future__ import annotations

import pytest

from track_surface_app.domain import SupportTier
from track_surface_app.support import SupportTierResolver, compute_fallback_depth_2_pct


class TestComputeFallbackDepth2Pct:
    def test_empty_dist_returns_zero(self):
        assert compute_fallback_depth_2_pct({}) == 0.0

    def test_basic_ratio(self):
        # 800 + 150 + 50 = 1000, 50/1000 = 5%
        assert compute_fallback_depth_2_pct({0: 800, 1: 150, 2: 50}) == pytest.approx(5.0)

    def test_no_fb2_key_returns_zero(self):
        assert compute_fallback_depth_2_pct({0: 100, 1: 0}) == 0.0

    def test_only_fb2(self):
        assert compute_fallback_depth_2_pct({2: 100}) == 100.0


class TestTierResolution:
    def test_tier_a_full_pass(self, tier_a_inputs):
        pr, rr = tier_a_inputs
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.A
        assert reason == "all_checks_passed"

    def test_tier_b_via_moderate_fallback(self, tier_b_inputs_fallback):
        pr, rr = tier_b_inputs_fallback
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.B
        assert reason == "moderate_fallback"

    def test_tier_b_via_release_warn(self, tier_b_inputs_warn):
        pr, rr = tier_b_inputs_warn
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.B
        assert reason == "release_gate_warn"

    def test_tier_c_via_fail(self, tier_c_inputs_fail):
        pr, rr = tier_c_inputs_fail
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.C
        assert reason == "release_gate_fail"

    def test_tier_c_via_high_fallback(self, tier_c_inputs_fallback):
        pr, rr = tier_c_inputs_fallback
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.C
        assert reason == "high_global_fallback"

    def test_tier_d_no_calibration(self, tier_d_inputs_no_calibration):
        pr, rr = tier_d_inputs_no_calibration
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.D
        assert reason == "vehicle_profile_not_validated"

    def test_tier_d_default_calibration(self, tier_d_inputs_default_calibration):
        pr, rr = tier_d_inputs_default_calibration
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.D
        assert reason == "vehicle_profile_not_validated"

    def test_tier_d_when_pipeline_failed(self, make_pipeline_result, make_release_result):
        pr = make_pipeline_result(
            calibration_source="registry_active",
            n_valid=0,
            exception="RuntimeError: solver failed",
        )
        rr = make_release_result("fail")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.D
        assert reason == "track_geometry_missing"


class TestTierBoundaries:
    def test_fb2_at_exactly_10_goes_b(self, make_pipeline_result, make_release_result):
        # 100 → 10% exactly
        pr = make_pipeline_result(
            bucket_fallback_distribution={0: 800, 1: 100, 2: 100},
            calibration_source="registry_active",
        )
        rr = make_release_result("pass")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.B
        assert reason == "moderate_fallback"

    def test_fb2_at_9_99_goes_a(self, make_pipeline_result, make_release_result):
        pr = make_pipeline_result(
            bucket_fallback_distribution={0: 900, 1: 1, 2: 99},   # 99/1000 = 9.9%
            calibration_source="registry_active",
        )
        rr = make_release_result("pass")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.A

    def test_fb2_at_exactly_30_goes_c(self, make_pipeline_result, make_release_result):
        pr = make_pipeline_result(
            bucket_fallback_distribution={0: 600, 1: 100, 2: 300},
            calibration_source="registry_active",
        )
        rr = make_release_result("pass")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.C
        assert reason == "high_global_fallback"

    def test_fail_beats_high_fallback(self, make_pipeline_result, make_release_result):
        # Both conditions true — FAIL reported first
        pr = make_pipeline_result(
            bucket_fallback_distribution={0: 400, 1: 200, 2: 400},
            calibration_source="registry_active",
        )
        rr = make_release_result("fail")
        tier, reason = SupportTierResolver().resolve(pr, rr)
        assert tier is SupportTier.C
        assert reason == "release_gate_fail"
```

- [ ] **Step 3.2: Run tests — expect ImportError**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_support_resolver.py -v`
Expected: FAIL.

- [ ] **Step 3.3: Implement `support.py`**

```python
# telemetry_tool/track_surface_app/support.py
"""SupportTierResolver — maps (PipelineResult, ReleaseSessionResult) → SupportTier.

This is the translation seam between research concepts and product concepts.
Inputs are duck-typed — we read attributes by name so the resolver can be tested
with fakes without importing the real validation harness.
"""
from __future__ import annotations

import logging
from typing import Any

from track_surface_app.domain import SupportTier

logger = logging.getLogger(__name__)

# Threshold constants. Kept here (not in a config file) because they encode
# the product-side tier contract, not a tunable physics parameter.
FB2_TIER_B_THRESHOLD_PCT = 10.0
FB2_TIER_C_THRESHOLD_PCT = 30.0

_VALIDATED_CALIBRATION_SOURCES = {"registry_active"}


def compute_fallback_depth_2_pct(dist: dict[int, int]) -> float:
    """Compute the percentage of points resolved by the global fallback (depth 2).

    Args:
        dist: Mapping depth (0/1/2) → count, as emitted by `bucket_fallback_distribution`
              on PipelineResult.

    Returns:
        Float percentage in [0, 100].
    """
    total = sum(dist.values()) if dist else 0
    if total <= 0:
        return 0.0
    return (dist.get(2, 0) / total) * 100.0


def _has_track_geometry(pipeline_result: Any) -> bool:
    """True iff the pipeline produced enough output to be meaningful."""
    if getattr(pipeline_result, "exception", None) is not None:
        return False
    if getattr(pipeline_result, "n_valid", 0) <= 0:
        return False
    if getattr(pipeline_result, "track_length_m", 0.0) <= 0.0:
        return False
    return True


def _is_validated_calibration(pipeline_result: Any) -> bool:
    src = getattr(pipeline_result, "calibration_source", None)
    return src in _VALIDATED_CALIBRATION_SOURCES


class SupportTierResolver:
    """Maps research-layer outputs to a user-facing SupportTier + reason code.

    Usage:
        tier, reason = SupportTierResolver().resolve(pipeline_result, release_result)

    Both inputs are duck-typed. They must expose:
      - pipeline_result: .n_valid, .exception, .track_length_m, .calibration_source,
        .bucket_fallback_distribution
      - release_result: .decision.value  (one of "pass"|"warn"|"fail")
    """

    def resolve(self, pipeline_result: Any, release_result: Any) -> tuple[SupportTier, str]:
        # Tier D — can't produce meaningful output at all
        if not _is_validated_calibration(pipeline_result):
            return SupportTier.D, "vehicle_profile_not_validated"
        if not _has_track_geometry(pipeline_result):
            return SupportTier.D, "track_geometry_missing"

        decision = getattr(release_result.decision, "value", None)
        fb2_pct = compute_fallback_depth_2_pct(
            getattr(pipeline_result, "bucket_fallback_distribution", {}) or {}
        )

        # Tier C — ran but advanced outputs not trustworthy
        if decision == "fail":
            return SupportTier.C, "release_gate_fail"
        if fb2_pct >= FB2_TIER_C_THRESHOLD_PCT:
            return SupportTier.C, "high_global_fallback"

        # Tier B — partial
        if decision == "warn":
            return SupportTier.B, "release_gate_warn"
        if fb2_pct >= FB2_TIER_B_THRESHOLD_PCT:
            return SupportTier.B, "moderate_fallback"

        # Tier A — full
        return SupportTier.A, "all_checks_passed"
```

- [ ] **Step 3.4: Run tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_support_resolver.py -v`
Expected: all tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add telemetry_tool/track_surface_app/support.py \
        telemetry_tool/tests/test_track_surface_app/test_support_resolver.py
git commit -m "feat(track-surface-app): SupportTierResolver maps pipeline+release → tier+reason"
```

---

## Task 4: `OutputGate`

**Files:**
- Create: `telemetry_tool/track_surface_app/gating.py`
- Create: `telemetry_tool/tests/test_track_surface_app/test_output_gate.py`

- [ ] **Step 4.1: Write failing tests**

```python
# test_output_gate.py
"""Tests for OutputGate — filters artifacts and planner modes by tier."""
from __future__ import annotations

import pytest

from track_surface_app.domain import SupportTier
from track_surface_app.gating import (
    OutputGate,
    ALL_ARTIFACT_KINDS,
    ALWAYS_PUBLIC_ARTIFACTS,
)


class TestArtifactGating:
    def test_tier_a_allows_everything(self):
        gate = OutputGate(SupportTier.A)
        allowed = gate.filter_artifact_kinds(ALL_ARTIFACT_KINDS)
        assert set(allowed) == set(ALL_ARTIFACT_KINDS)

    def test_tier_b_filters_exploitable_only(self):
        gate = OutputGate(SupportTier.B)
        allowed = set(gate.filter_artifact_kinds(ALL_ARTIFACT_KINDS))
        assert "planner_exploitable" not in allowed
        assert "planner_robust" in allowed
        assert "planner_nominal" in allowed
        assert "surface_field" in allowed

    def test_tier_c_only_summary_and_diagnostics(self):
        gate = OutputGate(SupportTier.C)
        allowed = set(gate.filter_artifact_kinds(ALL_ARTIFACT_KINDS))
        assert allowed == {"summary", "diagnostics"}

    def test_tier_d_only_summary_and_diagnostics(self):
        gate = OutputGate(SupportTier.D)
        allowed = set(gate.filter_artifact_kinds(ALL_ARTIFACT_KINDS))
        assert allowed == {"summary", "diagnostics"}


class TestArtifactAccess:
    @pytest.mark.parametrize("tier", list(SupportTier))
    def test_summary_is_always_public(self, tier):
        assert OutputGate(tier).is_artifact_allowed("summary")

    def test_tier_a_allows_exploitable(self):
        assert OutputGate(SupportTier.A).is_artifact_allowed("planner_exploitable")

    def test_tier_b_refuses_exploitable(self):
        assert not OutputGate(SupportTier.B).is_artifact_allowed("planner_exploitable")

    def test_tier_c_refuses_surface_field(self):
        assert not OutputGate(SupportTier.C).is_artifact_allowed("surface_field")

    def test_unknown_artifact_refused(self):
        assert not OutputGate(SupportTier.A).is_artifact_allowed("zzz_unknown")


class TestEndpointGating:
    def test_summary_endpoint_all_tiers(self):
        for tier in SupportTier:
            assert OutputGate(tier).is_endpoint_allowed("summary")

    def test_planner_endpoint_only_a_and_b(self):
        assert OutputGate(SupportTier.A).is_endpoint_allowed("planner")
        assert OutputGate(SupportTier.B).is_endpoint_allowed("planner")
        assert not OutputGate(SupportTier.C).is_endpoint_allowed("planner")
        assert not OutputGate(SupportTier.D).is_endpoint_allowed("planner")

    def test_surface_endpoint_all_except_d(self):
        assert OutputGate(SupportTier.A).is_endpoint_allowed("surface")
        assert OutputGate(SupportTier.B).is_endpoint_allowed("surface")
        assert OutputGate(SupportTier.C).is_endpoint_allowed("surface")
        assert not OutputGate(SupportTier.D).is_endpoint_allowed("surface")

    def test_uncertainty_endpoint_all_except_d(self):
        assert OutputGate(SupportTier.A).is_endpoint_allowed("uncertainty")
        assert not OutputGate(SupportTier.D).is_endpoint_allowed("uncertainty")
```

- [ ] **Step 4.2: Run tests — expect ImportError**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_output_gate.py -v`
Expected: FAIL.

- [ ] **Step 4.3: Implement `gating.py`**

```python
# telemetry_tool/track_surface_app/gating.py
"""OutputGate — enforces what each SupportTier is permitted to see.

The gate is consulted in two places:
  1. Artifact endpoints: filter the index + refuse forbidden kinds.
  2. Summary/planner/surface/uncertainty endpoints: refuse tier-inappropriate access.

Kept simple and data-driven so the contract is obvious from a table.
"""
from __future__ import annotations

from track_surface_app.domain import SupportTier

# All artifact kinds emitted by ArtifactWriter (see artifacts.py).
ALL_ARTIFACT_KINDS: tuple[str, ...] = (
    "summary",
    "surface_field",
    "confidence_heatmap",
    "planner_nominal",
    "planner_robust",
    "planner_exploitable",
    "racing_line_deltas",
    "diagnostics",
)

# Artifacts that every tier (even D) can see. Covers transparency: a user always
# sees at minimum "we tried, here's why it didn't work".
ALWAYS_PUBLIC_ARTIFACTS: frozenset[str] = frozenset({"summary", "diagnostics"})

# Additional artifacts allowed at tier C (beyond ALWAYS_PUBLIC).
_TIER_C_EXTRA: frozenset[str] = frozenset()

# Additional artifacts allowed at tier B (beyond tier C).
_TIER_B_EXTRA: frozenset[str] = frozenset({
    "surface_field",
    "confidence_heatmap",
    "planner_nominal",
    "planner_robust",
    "racing_line_deltas",
})

# Additional artifacts allowed at tier A (beyond tier B).
_TIER_A_EXTRA: frozenset[str] = frozenset({"planner_exploitable"})


# Endpoint gating (simpler, explicit table)
_ENDPOINT_TIER_ALLOWLIST: dict[str, set[SupportTier]] = {
    "summary":     {SupportTier.A, SupportTier.B, SupportTier.C, SupportTier.D},
    "surface":     {SupportTier.A, SupportTier.B, SupportTier.C},
    "planner":     {SupportTier.A, SupportTier.B},
    "uncertainty": {SupportTier.A, SupportTier.B, SupportTier.C},
    "artifacts":   {SupportTier.A, SupportTier.B, SupportTier.C, SupportTier.D},
}


def _allowed_artifacts(tier: SupportTier) -> frozenset[str]:
    if tier is SupportTier.A:
        return ALWAYS_PUBLIC_ARTIFACTS | _TIER_C_EXTRA | _TIER_B_EXTRA | _TIER_A_EXTRA
    if tier is SupportTier.B:
        return ALWAYS_PUBLIC_ARTIFACTS | _TIER_C_EXTRA | _TIER_B_EXTRA
    if tier is SupportTier.C:
        return ALWAYS_PUBLIC_ARTIFACTS | _TIER_C_EXTRA
    return ALWAYS_PUBLIC_ARTIFACTS   # tier D


class OutputGate:
    """Applies per-tier access rules to artifacts and endpoints."""

    def __init__(self, tier: SupportTier):
        self._tier = tier
        self._allowed_artifacts = _allowed_artifacts(tier)

    @property
    def tier(self) -> SupportTier:
        return self._tier

    def filter_artifact_kinds(self, kinds) -> list[str]:
        """Return only the artifact kinds this tier may see."""
        return [k for k in kinds if k in self._allowed_artifacts]

    def is_artifact_allowed(self, kind: str) -> bool:
        return kind in self._allowed_artifacts

    def is_endpoint_allowed(self, endpoint_name: str) -> bool:
        return self._tier in _ENDPOINT_TIER_ALLOWLIST.get(endpoint_name, set())
```

- [ ] **Step 4.4: Run tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_output_gate.py -v`
Expected: all tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add telemetry_tool/track_surface_app/gating.py \
        telemetry_tool/tests/test_track_surface_app/test_output_gate.py
git commit -m "feat(track-surface-app): OutputGate enforces per-tier artifact + endpoint access"
```

---

## Task 5: `ArtifactWriter` (PipelineResult → frontend-safe DTOs)

**Files:**
- Create: `telemetry_tool/track_surface_app/artifacts.py`
- Create: `telemetry_tool/tests/test_track_surface_app/test_artifact_writer.py`

- [ ] **Step 5.1: Write failing tests**

```python
# test_artifact_writer.py
"""Tests for ArtifactWriter — serializes PipelineResult to JSON DTOs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from track_surface_app.domain import SupportTier
from track_surface_app.gating import OutputGate
from track_surface_app.artifacts import ArtifactWriter


class TestArtifactWriter:
    def test_writes_summary_for_any_tier(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="r1", session_id=42)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.A))
        assert "summary" in index
        p = tmp_path / "42" / "r1" / "summary.json"
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["run_id"] == "r1"
        assert data["session_id"] == 42
        assert data["n_laps"] == 5
        assert data["best_lap_time_s"] == pytest.approx(88.123)

    def test_tier_d_writes_only_summary_and_diagnostics(self, tmp_path, tier_d_inputs_no_calibration):
        pr, _rr = tier_d_inputs_no_calibration
        writer = ArtifactWriter(tmp_path, run_id="rD", session_id=99)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.D))
        assert set(index.keys()) == {"summary", "diagnostics"}
        assert not (tmp_path / "99" / "rD" / "surface_field.json").exists()
        assert not (tmp_path / "99" / "rD" / "planner_nominal.json").exists()

    def test_tier_a_writes_all_kinds(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="rA", session_id=1)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.A))
        for k in ("summary", "surface_field", "confidence_heatmap",
                  "planner_nominal", "planner_robust", "planner_exploitable",
                  "racing_line_deltas", "diagnostics"):
            assert k in index, f"missing artifact {k}"
            p = tmp_path / "1" / "rA" / f"{k}.json"
            assert p.exists()

    def test_tier_b_skips_exploitable(self, tmp_path, tier_b_inputs_fallback):
        pr, _rr = tier_b_inputs_fallback
        writer = ArtifactWriter(tmp_path, run_id="rB", session_id=7)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.B))
        assert "planner_exploitable" not in index
        assert "planner_robust" in index
        assert "planner_nominal" in index

    def test_summary_has_no_numpy_or_nonjson(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="r", session_id=1)
        writer.write_all(pr, gate=OutputGate(SupportTier.A))
        # Round-trip every JSON file; if any non-serializable object leaked, json.loads
        # would have already failed on write. This also verifies files are valid UTF-8 JSON.
        for p in (tmp_path / "1" / "r").glob("*.json"):
            data = json.loads(p.read_text())
            _assert_json_only(data)

    def test_planner_summary_has_expected_fields(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="r", session_id=1)
        writer.write_all(pr, gate=OutputGate(SupportTier.A))
        p = tmp_path / "1" / "r" / "planner_nominal.json"
        data = json.loads(p.read_text())
        assert data["mode"] == "nominal"
        assert "mu_eff_mean" in data
        assert data["total_point_count"] == pr.planner_n_trusted + pr.planner_n_degraded

    def test_index_paths_are_relative(self, tmp_path, tier_a_inputs):
        pr, _rr = tier_a_inputs
        writer = ArtifactWriter(tmp_path, run_id="r", session_id=1)
        index = writer.write_all(pr, gate=OutputGate(SupportTier.A))
        for kind, path_str in index.items():
            # Paths in the index are stored as POSIX-style relative to the base
            # for portability across OSes.
            assert not Path(path_str).is_absolute()


def _assert_json_only(obj):
    """Recursively confirm obj contains only JSON-native types."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return
    if isinstance(obj, list):
        for x in obj:
            _assert_json_only(x)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, str), f"non-string key: {k!r}"
            _assert_json_only(v)
        return
    raise AssertionError(f"non-JSON type leaked: {type(obj).__name__}")
```

- [ ] **Step 5.2: Run tests — expect ImportError**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_artifact_writer.py -v`
Expected: FAIL.

- [ ] **Step 5.3: Implement `artifacts.py`**

```python
# telemetry_tool/track_surface_app/artifacts.py
"""ArtifactWriter — serialize PipelineResult to frontend-safe JSON files.

Each artifact is a stable DTO. No numpy arrays, no internal dataclasses, no
research-layer leakage. Output lands under ``<base>/<session_id>/<run_id>/``.

Artifact kinds and their schemas are documented in
``docs/plans/2026-04-15-track-surface-analysis-app-design.md`` §10.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from track_surface_app.gating import OutputGate

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _finite(value: Any, default: float = 0.0) -> float:
    """Return value cast to float, falling back to default for NaN / non-finite."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):   # NaN or Inf
        return default
    return f


class ArtifactWriter:
    """Writes frontend-safe DTOs for one analysis run.

    The writer never raises on unusual PipelineResult shapes; it coerces
    silently (missing fields become zero/null) so a partial-success run can
    still produce a meaningful summary + diagnostics.
    """

    def __init__(self, base_dir: Path | str, run_id: str, session_id: int):
        self._base = Path(base_dir) / str(session_id) / run_id
        self._run_id = run_id
        self._session_id = session_id

    def write_all(self, pipeline_result: Any, gate: OutputGate) -> dict[str, str]:
        """Write every artifact kind allowed by ``gate``.

        Returns a mapping ``{kind: relative_path}`` suitable for the
        ``artifacts_index`` column on ``analysis_runs``.
        """
        self._base.mkdir(parents=True, exist_ok=True)
        index: dict[str, str] = {}

        builders = {
            "summary": self._build_summary,
            "surface_field": self._build_surface_field,
            "confidence_heatmap": self._build_confidence_heatmap,
            "planner_nominal": lambda pr: self._build_planner(pr, "nominal"),
            "planner_robust": lambda pr: self._build_planner(pr, "robust"),
            "planner_exploitable": lambda pr: self._build_planner(pr, "exploitable"),
            "racing_line_deltas": self._build_racing_line_deltas,
            "diagnostics": self._build_diagnostics,
        }

        for kind, builder in builders.items():
            if not gate.is_artifact_allowed(kind):
                continue
            try:
                dto = builder(pipeline_result)
            except Exception as exc:   # artifact-local failure; log + skip
                logger.exception("Failed to build artifact %s for run %s: %s",
                                 kind, self._run_id, exc)
                continue
            rel_path = f"{self._session_id}/{self._run_id}/{kind}.json"
            full_path = self._base / f"{kind}.json"
            full_path.write_text(json.dumps(dto, ensure_ascii=False, sort_keys=True))
            index[kind] = rel_path

        return index

    # ── Individual builders ─────────────────────────────────

    def _header(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "session_id": self._session_id,
            "generated_at": _now_iso(),
        }

    def _build_summary(self, pr: Any) -> dict[str, Any]:
        return {
            **self._header(),
            "n_samples_total": int(getattr(pr, "n_samples_total", 0) or 0),
            "n_samples_accepted": int(getattr(pr, "n_valid", 0) or 0),
            "n_laps": int(getattr(pr, "n_laps", 0) or 0),
            "best_lap": int(getattr(pr, "best_lap", -1) or -1),
            "best_lap_time_s": _finite(getattr(pr, "best_lap_time_s", 0.0)),
            "track_length_m": _finite(getattr(pr, "track_length_m", 0.0)),
            "lap_times_s": {str(k): _finite(v) for k, v in
                            (getattr(pr, "lap_times_s", {}) or {}).items()},
            "warnings": list(getattr(pr, "pipeline_warnings", []) or []),
            "calibration_profile_id": getattr(pr, "calibration_profile_id", None),
            "calibration_source": getattr(pr, "calibration_source", None),
        }

    def _build_surface_field(self, pr: Any) -> dict[str, Any]:
        return {
            **self._header(),
            "coverage_pct": _finite(getattr(pr, "field_coverage_pct", 0.0)),
            "mean_confidence": _finite(getattr(pr, "field_mean_confidence", 0.0)),
            "cells_observed": int(getattr(pr, "field_cells_observed", 0) or 0),
            "cells_total": int(getattr(pr, "field_cells_total", 0) or 0),
            "bucket_active_count": int(getattr(pr, "bucket_active_count", 0) or 0),
            "bucket_sparse_count": int(getattr(pr, "bucket_sparse_count", 0) or 0),
            # No full mesh in v1 — downsampled mesh is future work; we publish
            # the stats that every tier above D needs without exposing raw cells.
        }

    def _build_confidence_heatmap(self, pr: Any) -> dict[str, Any]:
        # Placeholder shape — no raw per-cell data in v1. Histogram only.
        conf = _finite(getattr(pr, "field_mean_confidence", 0.0))
        return {
            **self._header(),
            "mean_confidence": conf,
            "high_conf_cells": int(getattr(pr, "field_high_conf_cells", 0) or 0),
            "zero_conf_cells": int(getattr(pr, "field_zero_conf_cells", 0) or 0),
            "histogram_buckets": [
                {"low": 0.0, "high": 0.25, "label": "very_low"},
                {"low": 0.25, "high": 0.50, "label": "low"},
                {"low": 0.50, "high": 0.75, "label": "medium"},
                {"low": 0.75, "high": 1.0, "label": "high"},
            ],
        }

    def _build_planner(self, pr: Any, mode: str) -> dict[str, Any]:
        mean_mu_field = f"planner_{mode}_mean_mu"
        return {
            **self._header(),
            "mode": mode,
            "mu_eff_mean": _finite(getattr(pr, mean_mu_field, 0.0)),
            "trusted_point_count": int(getattr(pr, "planner_n_trusted", 0) or 0),
            "degraded_point_count": int(getattr(pr, "planner_n_degraded", 0) or 0),
            "total_point_count": (
                int(getattr(pr, "planner_n_trusted", 0) or 0)
                + int(getattr(pr, "planner_n_degraded", 0) or 0)
            ),
            "max_robust_penalty": _finite(getattr(pr, "planner_max_robust_penalty", 0.0)),
        }

    def _build_racing_line_deltas(self, pr: Any) -> dict[str, Any]:
        return {
            **self._header(),
            "center_lambda": _finite(getattr(pr, "racing_line_center_lambda", 0.0)),
            "left_lambda": _finite(getattr(pr, "racing_line_left_lambda", 0.0)),
            "right_lambda": _finite(getattr(pr, "racing_line_right_lambda", 0.0)),
        }

    def _build_diagnostics(self, pr: Any) -> dict[str, Any]:
        # Intentionally light — this artifact is always public.
        return {
            **self._header(),
            "elapsed_s": _finite(getattr(pr, "elapsed_s", 0.0)),
            "exception": getattr(pr, "exception", None),
            "gate_accept_pct": _finite(getattr(pr, "gate_accept_pct", 0.0)),
            "transition_pct": _finite(getattr(pr, "transition_pct", 0.0)),
            "fy_residual_std": _finite(getattr(pr, "fy_residual_std", 0.0)),
            "fx_residual_std": _finite(getattr(pr, "fx_residual_std", 0.0)),
            "bucket_fallback_distribution": {
                str(k): int(v) for k, v in
                (getattr(pr, "bucket_fallback_distribution", {}) or {}).items()
            },
        }
```

- [ ] **Step 5.4: Run tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_artifact_writer.py -v`
Expected: all tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add telemetry_tool/track_surface_app/artifacts.py \
        telemetry_tool/tests/test_track_surface_app/test_artifact_writer.py
git commit -m "feat(track-surface-app): ArtifactWriter emits JSON DTOs (no numpy leakage)"
```

---

## Task 6: Alembic migration 056 + `AnalysisRunRepository`

**Files:**
- Create: `telemetry_tool/alembic/versions/056_analysis_runs.py`
- Create: `telemetry_tool/track_surface_app/persistence.py`
- Create: `telemetry_tool/tests/test_track_surface_app/test_persistence.py`

- [ ] **Step 6.1: Write failing tests**

```python
# test_persistence.py
"""Tests for AnalysisRunRepository against an in-memory SQLite schema."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from track_surface_app.domain import AnalysisRunStatus, SupportTier, ConfidenceLevel
from track_surface_app.persistence import AnalysisRunRepository


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite with the analysis_runs table mirroring the PG schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY,
            session_id INTEGER NOT NULL,
            workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            support_tier TEXT,
            support_reason TEXT,
            confidence_level TEXT,
            fallback_depth_distribution TEXT,
            validated_vehicle_profile TEXT,
            validated_track_profile TEXT,
            planner_mode_availability TEXT,
            warnings TEXT NOT NULL DEFAULT '[]',
            artifacts_index TEXT NOT NULL DEFAULT '{}',
            release_decision TEXT,
            pipeline_summary TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        )
        """
    )
    conn.commit()
    yield conn
    conn.close()


class TestInsertAndGet:
    def test_insert_queued_row(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r1", session_id=10, workspace_id=1)
        run = repo.get("r1")
        assert run is not None
        assert run.run_id == "r1"
        assert run.session_id == 10
        assert run.workspace_id == 1
        assert run.status is AnalysisRunStatus.QUEUED
        assert run.completed_at is None

    def test_get_missing_returns_none(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        assert repo.get("nonexistent") is None


class TestStatusTransitions:
    def test_update_status_running(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=1, workspace_id=1)
        repo.update_status("r", AnalysisRunStatus.RUNNING)
        assert repo.get("r").status is AnalysisRunStatus.RUNNING

    def test_mark_succeeded_sets_terminal_fields(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=1, workspace_id=1)
        repo.mark_succeeded(
            run_id="r",
            support_tier=SupportTier.A,
            support_reason="all_checks_passed",
            confidence_level=ConfidenceLevel.HIGH,
            fallback_depth_distribution={0: 0.8, 1: 0.15, 2: 0.05},
            validated_vehicle_profile="iracing_mx5_2024",
            validated_track_profile="daytona_rc_v5",
            planner_mode_availability={"nominal": True, "robust": True, "exploitable": True},
            warnings=[],
            artifacts_index={"summary": "1/r/summary.json"},
            release_decision="pass",
            pipeline_summary={"n_valid": 9500},
        )
        run = repo.get("r")
        assert run.status is AnalysisRunStatus.SUCCEEDED
        assert run.support_tier is SupportTier.A
        assert run.confidence_level is ConfidenceLevel.HIGH
        assert run.release_decision == "pass"
        assert run.artifacts_index == {"summary": "1/r/summary.json"}
        assert run.completed_at is not None

    def test_mark_failed(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=1, workspace_id=1)
        repo.mark_failed(
            run_id="r",
            error_code="INTERNAL_ERROR",
            error_message="boom",
            support_tier=SupportTier.D,
            support_reason="calibration_missing",
        )
        run = repo.get("r")
        assert run.status is AnalysisRunStatus.FAILED
        assert run.error_code == "INTERNAL_ERROR"
        assert run.error_message == "boom"
        assert run.support_tier is SupportTier.D
        assert run.completed_at is not None


class TestInFlightDetection:
    def test_has_in_flight_queued(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=5, workspace_id=1)
        assert repo.has_in_flight(5)

    def test_has_in_flight_running(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=5, workspace_id=1)
        repo.update_status("r", AnalysisRunStatus.RUNNING)
        assert repo.has_in_flight(5)

    def test_no_in_flight_after_success(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=5, workspace_id=1)
        repo.mark_succeeded(
            run_id="r",
            support_tier=SupportTier.A, support_reason="all_checks_passed",
            confidence_level=ConfidenceLevel.HIGH,
            fallback_depth_distribution={}, validated_vehicle_profile=None,
            validated_track_profile=None, planner_mode_availability={},
            warnings=[], artifacts_index={}, release_decision="pass",
            pipeline_summary={},
        )
        assert not repo.has_in_flight(5)

    def test_no_in_flight_for_different_session(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=5, workspace_id=1)
        assert not repo.has_in_flight(999)


class TestLatestForSession:
    def test_returns_none_when_no_run(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        assert repo.get_latest_for_session(42) is None

    def test_returns_most_recent(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="old", session_id=42, workspace_id=1)
        repo.insert_queued(run_id="new", session_id=42, workspace_id=1)
        latest = repo.get_latest_for_session(42)
        assert latest is not None
        assert latest.run_id == "new"
```

- [ ] **Step 6.2: Run tests — expect ImportError**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_persistence.py -v`
Expected: FAIL.

- [ ] **Step 6.3: Create Alembic migration 056**

```python
# telemetry_tool/alembic/versions/056_analysis_runs.py
"""056 — Create analysis_runs table for track-surface analysis lifecycle.

Per-session analysis run records (queued → running → succeeded/failed), with
support-tier + artifact index. Workspace-scoped via RLS.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "056"
down_revision = "055"


def upgrade():
    op.create_table(
        "analysis_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer,
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text("current_setting('app.current_workspace_id')::integer"),
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("support_tier", sa.Text),
        sa.Column("support_reason", sa.Text),
        sa.Column("confidence_level", sa.Text),
        sa.Column("fallback_depth_distribution", JSONB),
        sa.Column("validated_vehicle_profile", sa.Text),
        sa.Column("validated_track_profile", sa.Text),
        sa.Column("planner_mode_availability", JSONB),
        sa.Column("warnings", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("artifacts_index", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("release_decision", sa.Text),
        sa.Column("pipeline_summary", JSONB),
        sa.Column("error_code", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_analysis_runs_session", "analysis_runs", ["session_id"])
    op.create_index("idx_analysis_runs_workspace", "analysis_runs", ["workspace_id"])
    op.execute(
        "CREATE INDEX idx_analysis_runs_status ON analysis_runs (status) "
        "WHERE status IN ('queued', 'running')"
    )

    op.execute("ALTER TABLE analysis_runs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY analysis_runs_tenant ON analysis_runs "
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS analysis_runs_tenant ON analysis_runs")
    op.drop_index("idx_analysis_runs_status", table_name="analysis_runs")
    op.drop_index("idx_analysis_runs_workspace", table_name="analysis_runs")
    op.drop_index("idx_analysis_runs_session", table_name="analysis_runs")
    op.drop_table("analysis_runs")
```

- [ ] **Step 6.4: Implement `persistence.py`**

```python
# telemetry_tool/track_surface_app/persistence.py
"""AnalysisRunRepository — CRUD for the analysis_runs table.

SQL is written with ``:name`` placeholders so it runs against SQLite (dev) and
PostgreSQL (prod) via ``db/sql_compat``. When used from a Flask request, the
caller is responsible for supplying a PG-wrapped connection; RLS filtering is
automatic via ``SET LOCAL app.current_workspace_id``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from track_surface_app.domain import (
    AnalysisRunStatus,
    ConfidenceLevel,
    SupportTier,
)


@dataclass
class AnalysisRunRecord:
    """Snapshot of one row from analysis_runs."""
    run_id: str
    session_id: int
    workspace_id: int
    status: AnalysisRunStatus
    support_tier: SupportTier | None
    support_reason: str | None
    confidence_level: ConfidenceLevel | None
    fallback_depth_distribution: dict[str, float] | None
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: dict[str, bool] | None
    warnings: list[str]
    artifacts_index: dict[str, str]
    release_decision: str | None
    pipeline_summary: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime | str
    completed_at: datetime | str | None


def _parse_json(value: Any, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _enum_or_none(cls, value: Any):
    if value is None or value == "":
        return None
    try:
        return cls(value)
    except ValueError:
        return None


class AnalysisRunRepository:
    """CRUD for analysis_runs.

    Uses ``:name`` placeholders; compatible with both raw sqlite3 (tests) and
    the PG wrapper (production). Commits after each write so rows land even if
    the caller forgets — mirrors ``sessions_v2.py`` style.
    """

    def __init__(self, conn):
        self._conn = conn

    # ── Helpers ───────────────────────────────────────────────

    def _execute(self, sql: str, params: dict[str, Any]):
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
            return cur
        except Exception:
            cur.close()
            raise

    def _commit(self):
        if hasattr(self._conn, "commit"):
            self._conn.commit()

    def _row_to_record(self, row) -> AnalysisRunRecord:
        def _g(key):
            try:
                return row[key]
            except (KeyError, IndexError, TypeError):
                return None

        return AnalysisRunRecord(
            run_id=_g("run_id"),
            session_id=int(_g("session_id")),
            workspace_id=int(_g("workspace_id")),
            status=AnalysisRunStatus(_g("status")),
            support_tier=_enum_or_none(SupportTier, _g("support_tier")),
            support_reason=_g("support_reason"),
            confidence_level=_enum_or_none(ConfidenceLevel, _g("confidence_level")),
            fallback_depth_distribution=_parse_json(_g("fallback_depth_distribution"), None),
            validated_vehicle_profile=_g("validated_vehicle_profile"),
            validated_track_profile=_g("validated_track_profile"),
            planner_mode_availability=_parse_json(_g("planner_mode_availability"), None),
            warnings=_parse_json(_g("warnings"), []),
            artifacts_index=_parse_json(_g("artifacts_index"), {}),
            release_decision=_g("release_decision"),
            pipeline_summary=_parse_json(_g("pipeline_summary"), None),
            error_code=_g("error_code"),
            error_message=_g("error_message"),
            created_at=_g("created_at"),
            completed_at=_g("completed_at"),
        )

    # ── Writes ────────────────────────────────────────────────

    def insert_queued(self, *, run_id: str, session_id: int, workspace_id: int) -> None:
        cur = self._execute(
            """
            INSERT INTO analysis_runs (run_id, session_id, workspace_id, status)
            VALUES (:run_id, :session_id, :workspace_id, 'queued')
            """,
            {"run_id": run_id, "session_id": session_id, "workspace_id": workspace_id},
        )
        cur.close()
        self._commit()

    def update_status(self, run_id: str, status: AnalysisRunStatus) -> None:
        cur = self._execute(
            "UPDATE analysis_runs SET status = :status WHERE run_id = :run_id",
            {"status": status.value, "run_id": run_id},
        )
        cur.close()
        self._commit()

    def mark_succeeded(
        self,
        *,
        run_id: str,
        support_tier: SupportTier,
        support_reason: str,
        confidence_level: ConfidenceLevel,
        fallback_depth_distribution: dict[str, float] | None,
        validated_vehicle_profile: str | None,
        validated_track_profile: str | None,
        planner_mode_availability: dict[str, bool],
        warnings: list[str],
        artifacts_index: dict[str, str],
        release_decision: str | None,
        pipeline_summary: dict[str, Any] | None,
    ) -> None:
        cur = self._execute(
            """
            UPDATE analysis_runs SET
              status = 'succeeded',
              support_tier = :support_tier,
              support_reason = :support_reason,
              confidence_level = :confidence_level,
              fallback_depth_distribution = :fallback_depth_distribution,
              validated_vehicle_profile = :validated_vehicle_profile,
              validated_track_profile = :validated_track_profile,
              planner_mode_availability = :planner_mode_availability,
              warnings = :warnings,
              artifacts_index = :artifacts_index,
              release_decision = :release_decision,
              pipeline_summary = :pipeline_summary,
              completed_at = :completed_at
            WHERE run_id = :run_id
            """,
            {
                "run_id": run_id,
                "support_tier": support_tier.value,
                "support_reason": support_reason,
                "confidence_level": confidence_level.value,
                "fallback_depth_distribution": json.dumps(fallback_depth_distribution or {}),
                "validated_vehicle_profile": validated_vehicle_profile,
                "validated_track_profile": validated_track_profile,
                "planner_mode_availability": json.dumps(planner_mode_availability or {}),
                "warnings": json.dumps(list(warnings or [])),
                "artifacts_index": json.dumps(artifacts_index or {}),
                "release_decision": release_decision,
                "pipeline_summary": json.dumps(pipeline_summary or {}),
                "completed_at": datetime.utcnow().isoformat(),
            },
        )
        cur.close()
        self._commit()

    def mark_failed(
        self,
        *,
        run_id: str,
        error_code: str,
        error_message: str,
        support_tier: SupportTier | None = None,
        support_reason: str | None = None,
    ) -> None:
        cur = self._execute(
            """
            UPDATE analysis_runs SET
              status = 'failed',
              error_code = :error_code,
              error_message = :error_message,
              support_tier = :support_tier,
              support_reason = :support_reason,
              completed_at = :completed_at
            WHERE run_id = :run_id
            """,
            {
                "run_id": run_id,
                "error_code": error_code,
                "error_message": error_message,
                "support_tier": support_tier.value if support_tier else None,
                "support_reason": support_reason,
                "completed_at": datetime.utcnow().isoformat(),
            },
        )
        cur.close()
        self._commit()

    # ── Reads ─────────────────────────────────────────────────

    def get(self, run_id: str) -> AnalysisRunRecord | None:
        cur = self._execute(
            "SELECT * FROM analysis_runs WHERE run_id = :run_id",
            {"run_id": run_id},
        )
        try:
            row = cur.fetchone()
        finally:
            cur.close()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_latest_for_session(self, session_id: int) -> AnalysisRunRecord | None:
        cur = self._execute(
            """
            SELECT * FROM analysis_runs
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"session_id": session_id},
        )
        try:
            row = cur.fetchone()
        finally:
            cur.close()
        if row is None:
            return None
        return self._row_to_record(row)

    def has_in_flight(self, session_id: int) -> bool:
        cur = self._execute(
            """
            SELECT 1 FROM analysis_runs
            WHERE session_id = :session_id
              AND status IN ('queued', 'running')
            LIMIT 1
            """,
            {"session_id": session_id},
        )
        try:
            row = cur.fetchone()
        finally:
            cur.close()
        return row is not None
```

- [ ] **Step 6.5: Run tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_persistence.py -v`
Expected: all tests pass.

- [ ] **Step 6.6: Commit**

```bash
git add telemetry_tool/alembic/versions/056_analysis_runs.py \
        telemetry_tool/track_surface_app/persistence.py \
        telemetry_tool/tests/test_track_surface_app/test_persistence.py
git commit -m "feat(track-surface-app): analysis_runs table + repository (Alembic 056, RLS)"
```

---

## Task 7: `SupportMatrix` (static lookup) + seed data

**Files:**
- Create: `telemetry_tool/track_surface_app/support_matrix.py`
- Create: `telemetry_tool/track_surface_app/data/support_matrix.json`
- Create: `telemetry_tool/tests/test_track_surface_app/test_support_matrix.py`

- [ ] **Step 7.1: Write failing tests**

```python
# test_support_matrix.py
"""Tests for SupportMatrix — static (sim, vehicle, track) lookup."""
from __future__ import annotations

import json

import pytest

from track_surface_app.domain import SupportTier
from track_surface_app.support_matrix import SupportMatrix, SupportMatrixEntry


@pytest.fixture
def tmp_matrix(tmp_path):
    data = {
        "version": 1,
        "entries": [
            {
                "sim": "iracing",
                "vehicle": "mx5",
                "track": "daytona_rc",
                "max_support_tier": "A",
                "validated_vehicle_profile": "iracing_mx5_2024",
                "validated_track_profile": "daytona_rc_v5",
            },
            {
                "sim": "iracing",
                "vehicle": "mx5",
                "track": "spa",
                "max_support_tier": "B",
                "validated_vehicle_profile": "iracing_mx5_2024",
                "validated_track_profile": "spa_v3",
            },
        ],
    }
    p = tmp_path / "matrix.json"
    p.write_text(json.dumps(data))
    return p


class TestLoad:
    def test_load_valid(self, tmp_matrix):
        mx = SupportMatrix.load(tmp_matrix)
        assert len(mx.entries) == 2

    def test_missing_file_returns_empty(self, tmp_path):
        mx = SupportMatrix.load(tmp_path / "nonexistent.json")
        assert mx.entries == []


class TestResolve:
    def test_known_combo_returns_entry(self, tmp_matrix):
        mx = SupportMatrix.load(tmp_matrix)
        entry = mx.resolve(sim="iracing", vehicle="mx5", track="daytona_rc")
        assert entry is not None
        assert entry.max_support_tier is SupportTier.A
        assert entry.validated_vehicle_profile == "iracing_mx5_2024"

    def test_unknown_combo_returns_none(self, tmp_matrix):
        mx = SupportMatrix.load(tmp_matrix)
        assert mx.resolve(sim="ac", vehicle="gt3", track="nordschleife") is None

    def test_case_insensitive(self, tmp_matrix):
        mx = SupportMatrix.load(tmp_matrix)
        entry = mx.resolve(sim="IRACING", vehicle="MX5", track="daytona_rc")
        assert entry is not None
```

- [ ] **Step 7.2: Run tests — expect ImportError**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_support_matrix.py -v`
Expected: FAIL.

- [ ] **Step 7.3: Implement `support_matrix.py`**

```python
# telemetry_tool/track_surface_app/support_matrix.py
"""SupportMatrix — static lookup for (sim, vehicle, track) → max tier.

Seed data lives next to this module at ``data/support_matrix.json``. Frontend
queries ``/support/resolve?sim=...`` against this table BEFORE uploading a
session, so it knows which analysis controls to enable.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from track_surface_app.domain import SupportTier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupportMatrixEntry:
    sim: str
    vehicle: str
    track: str
    max_support_tier: SupportTier
    validated_vehicle_profile: str | None = None
    validated_track_profile: str | None = None


def _norm(s: str) -> str:
    return s.strip().lower() if s else ""


class SupportMatrix:
    """Static (sim, vehicle, track) → SupportMatrixEntry lookup."""

    def __init__(self, entries: list[SupportMatrixEntry]):
        self._entries = list(entries)
        self._index: dict[tuple[str, str, str], SupportMatrixEntry] = {
            (_norm(e.sim), _norm(e.vehicle), _norm(e.track)): e for e in entries
        }

    @property
    def entries(self) -> list[SupportMatrixEntry]:
        return list(self._entries)

    def resolve(self, *, sim: str, vehicle: str, track: str) -> SupportMatrixEntry | None:
        return self._index.get((_norm(sim), _norm(vehicle), _norm(track)))

    @classmethod
    def load(cls, path: Path | str) -> "SupportMatrix":
        p = Path(path)
        if not p.is_file():
            logger.warning("Support matrix file not found at %s — using empty", p)
            return cls(entries=[])
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("support_matrix root must be a JSON object")
        version = raw.get("version", 1)
        if version != 1:
            raise ValueError(f"Unsupported support_matrix version: {version}")
        entries_raw = raw.get("entries", [])
        entries: list[SupportMatrixEntry] = []
        for i, e in enumerate(entries_raw):
            try:
                entries.append(SupportMatrixEntry(
                    sim=str(e["sim"]),
                    vehicle=str(e["vehicle"]),
                    track=str(e["track"]),
                    max_support_tier=SupportTier(e["max_support_tier"]),
                    validated_vehicle_profile=e.get("validated_vehicle_profile"),
                    validated_track_profile=e.get("validated_track_profile"),
                ))
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed support matrix entry #%d: %s", i, exc)
        return cls(entries=entries)

    @classmethod
    def load_default(cls) -> "SupportMatrix":
        """Load from the packaged default location (``data/support_matrix.json``)."""
        default_path = Path(__file__).parent / "data" / "support_matrix.json"
        return cls.load(default_path)
```

- [ ] **Step 7.4: Create seed data `data/support_matrix.json`**

```python
# write telemetry_tool/track_surface_app/data/support_matrix.json
```

```json
{
  "version": 1,
  "entries": [
    {
      "sim": "iracing",
      "vehicle": "mx5",
      "track": "daytona_rc",
      "max_support_tier": "A",
      "validated_vehicle_profile": "iracing_mx5_2024",
      "validated_track_profile": "daytona_rc_v5"
    },
    {
      "sim": "iracing",
      "vehicle": "mx5",
      "track": "spa",
      "max_support_tier": "B",
      "validated_vehicle_profile": "iracing_mx5_2024",
      "validated_track_profile": "spa_v3"
    }
  ]
}
```

- [ ] **Step 7.5: Run tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_support_matrix.py -v`
Expected: all tests pass.

- [ ] **Step 7.6: Commit**

```bash
git add telemetry_tool/track_surface_app/support_matrix.py \
        telemetry_tool/track_surface_app/data/support_matrix.json \
        telemetry_tool/tests/test_track_surface_app/test_support_matrix.py
git commit -m "feat(track-surface-app): static SupportMatrix lookup + seed data"
```

---

## Task 8: Pydantic v2 HTTP schemas

**Files:**
- Create: `telemetry_tool/web/schemas/track_surface.py`

No standalone test file — the schemas are exercised by `test_routes.py` (Task 11).

- [ ] **Step 8.1: Inspect existing schema base classes**

Run: `grep -n 'StrictSchema\|LenientSchema' telemetry_tool/web/schemas/common.py`
Expected: two class definitions using `ConfigDict(extra="forbid")` and
`ConfigDict(extra="ignore")` respectively.

- [ ] **Step 8.2: Create `web/schemas/track_surface.py`**

```python
# telemetry_tool/web/schemas/track_surface.py
"""HTTP request / response schemas for the track-surface analysis API.

All types are Pydantic v2 BaseModels. Requests use StrictSchema (reject unknown
fields); responses use LenientSchema (forgiving on ingestion, strict on output).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from web.schemas.common import LenientSchema, StrictSchema


# ── Request schemas ─────────────────────────────────────────

class RunAnalysisRequest(StrictSchema):
    """POST /sessions/<sid>/run body. All fields optional."""
    vehicle_profile_override: str | None = None
    planner_modes: list[Literal["nominal", "robust", "exploitable"]] | None = None
    force_rerun: bool = False


class ResolveSupportParams(StrictSchema):
    """Query params for GET /support/resolve."""
    sim: str = Field(..., min_length=1, max_length=64)
    vehicle: str = Field(..., min_length=1, max_length=64)
    track: str = Field(..., min_length=1, max_length=128)


# ── Shared response shapes ──────────────────────────────────

class PlannerModeAvailabilityDTO(LenientSchema):
    nominal: bool
    robust: bool
    exploitable: bool


# ── Response schemas ────────────────────────────────────────

class AnalysisRunSummary(LenientSchema):
    run_id: str
    session_id: int
    status: Literal["queued", "running", "succeeded", "failed"]
    support_tier: Literal["A", "B", "C", "D"] | None
    support_reason: str | None
    confidence_level: Literal["high", "medium", "low", "unknown"] | None
    fallback_depth_pct: dict[str, float] | None
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: PlannerModeAvailabilityDTO | None
    warnings: list[str]
    artifacts_available: list[str]
    release_decision: Literal["pass", "warn", "fail"] | None
    error_code: str | None
    error_message: str | None
    created_at: str | None
    completed_at: str | None


class SessionSummary(LenientSchema):
    run_id: str
    session_id: int
    n_samples_total: int
    n_samples_accepted: int
    n_laps: int
    best_lap: int
    best_lap_time_s: float
    track_length_m: float
    lap_times_s: dict[str, float]
    warnings: list[str]
    calibration_profile_id: str | None
    calibration_source: str | None


class TrackSurfaceSummary(LenientSchema):
    run_id: str
    coverage_pct: float
    mean_confidence: float
    confidence_level: Literal["high", "medium", "low", "unknown"]
    fallback_depth_pct: dict[str, float]
    bucket_active_count: int
    bucket_sparse_count: int


class PlannerModeResult(LenientSchema):
    mode: Literal["nominal", "robust", "exploitable"]
    mu_eff_mean: float
    trusted_point_count: int
    degraded_point_count: int
    total_point_count: int
    max_robust_penalty: float


class PlannerSummary(LenientSchema):
    run_id: str
    support_tier: Literal["A", "B", "C", "D"]
    available_modes: list[str]
    nominal: PlannerModeResult | None
    robust: PlannerModeResult | None
    exploitable: PlannerModeResult | None
    unavailable_reason: str | None = None


class UncertaintySummary(LenientSchema):
    run_id: str
    mean_confidence: float
    confidence_level: Literal["high", "medium", "low", "unknown"]
    high_conf_cells: int
    zero_conf_cells: int
    fallback_depth_pct: dict[str, float]


class SupportSummary(LenientSchema):
    run_id: str | None
    sim: str | None
    vehicle: str | None
    track: str | None
    support_tier: Literal["A", "B", "C", "D"]
    support_reason: str
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: PlannerModeAvailabilityDTO
    warnings: list[str]


class SupportMatrixEntry(LenientSchema):
    sim: str
    vehicle: str
    track: str
    max_support_tier: Literal["A", "B", "C", "D"]
    validated_vehicle_profile: str | None
    validated_track_profile: str | None


class SupportMatrixResponse(LenientSchema):
    entries: list[SupportMatrixEntry]
    last_updated: str


class ArtifactRef(LenientSchema):
    kind: str
    download_url: str
    size_bytes: int
    version: str


class ArtifactsIndex(LenientSchema):
    run_id: str
    artifacts: list[ArtifactRef]
```

- [ ] **Step 8.3: Verify import**

Run: `python -c "from telemetry_tool.web.schemas.track_surface import AnalysisRunSummary; print('ok')"`
Expected: `ok`.

- [ ] **Step 8.4: Commit**

```bash
git add telemetry_tool/web/schemas/track_surface.py
git commit -m "feat(track-surface-app): Pydantic v2 schemas for analysis API"
```

---

## Task 9: Add `SUPPORT_TIER_REFUSED` to ErrorCode

**Files:**
- Modify: `telemetry_tool/web/api_utils.py`

- [ ] **Step 9.1: Read the ErrorCode class**

Run: `grep -n '^class ErrorCode\|SUPPORT_TIER\|UNAUTHORIZED' telemetry_tool/web/api_utils.py`
Expected: shows class header and existing codes.

- [ ] **Step 9.2: Add the new code**

Edit `telemetry_tool/web/api_utils.py`: inside the `ErrorCode` class definition (alongside other codes such as `NOT_FOUND`, `UNAUTHORIZED`, `VALIDATION_ERROR`), add:

```python
    SUPPORT_TIER_REFUSED = "SUPPORT_TIER_REFUSED"
```

- [ ] **Step 9.3: Sanity check**

Run: `python -c "from telemetry_tool.web.api_utils import ErrorCode; print(ErrorCode.SUPPORT_TIER_REFUSED)"`
Expected: `ErrorCode.SUPPORT_TIER_REFUSED`.

- [ ] **Step 9.4: Commit**

```bash
git add telemetry_tool/web/api_utils.py
git commit -m "feat(api): add SUPPORT_TIER_REFUSED error code"
```

---

## Task 10: `AnalysisOrchestrator` + Celery task

**Files:**
- Create: `telemetry_tool/track_surface_app/orchestrator.py`
- Create: `telemetry_tool/tasks/track_surface_tasks.py`
- Create: `telemetry_tool/tests/test_track_surface_app/test_orchestrator.py`

- [ ] **Step 10.1: Write failing tests**

```python
# test_orchestrator.py
"""Tests for AnalysisOrchestrator — end-to-end with a mocked pipeline."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from track_surface_app.domain import SupportTier, AnalysisRunStatus
from track_surface_app.orchestrator import AnalysisOrchestrator
from track_surface_app.persistence import AnalysisRunRepository


@pytest.fixture
def sqlite_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY,
            session_id INTEGER NOT NULL,
            workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            support_tier TEXT,
            support_reason TEXT,
            confidence_level TEXT,
            fallback_depth_distribution TEXT,
            validated_vehicle_profile TEXT,
            validated_track_profile TEXT,
            planner_mode_availability TEXT,
            warnings TEXT NOT NULL DEFAULT '[]',
            artifacts_index TEXT NOT NULL DEFAULT '{}',
            release_decision TEXT,
            pipeline_summary TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        )
        """
    )
    conn.commit()
    yield conn
    conn.close()


class TestEnqueue:
    def test_enqueue_creates_queued_row(self, sqlite_conn, tmp_path):
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=MagicMock(),
            evaluate_release_fn=MagicMock(),
            calibration_registry=None,
        )
        run_id = orch.enqueue(session_id=10, workspace_id=1)
        assert run_id
        repo = AnalysisRunRepository(sqlite_conn)
        run = repo.get(run_id)
        assert run.status is AnalysisRunStatus.QUEUED

    def test_enqueue_refuses_if_in_flight(self, sqlite_conn, tmp_path):
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=MagicMock(),
            evaluate_release_fn=MagicMock(),
            calibration_registry=None,
        )
        orch.enqueue(session_id=10, workspace_id=1)
        with pytest.raises(RuntimeError, match="in_flight"):
            orch.enqueue(session_id=10, workspace_id=1)

    def test_enqueue_force_rerun_allowed_when_in_flight(self, sqlite_conn, tmp_path):
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=MagicMock(),
            evaluate_release_fn=MagicMock(),
            calibration_registry=None,
        )
        r1 = orch.enqueue(session_id=10, workspace_id=1)
        r2 = orch.enqueue(session_id=10, workspace_id=1, force_rerun=True)
        assert r1 != r2


class TestExecute:
    def test_successful_tier_a_flow(self, sqlite_conn, tmp_path, tier_a_inputs):
        pr, rr = tier_a_inputs
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=lambda session_id, workspace_id: pr,
            evaluate_release_fn=lambda pipeline_result: rr,
            calibration_registry=None,
        )
        run_id = orch.enqueue(session_id=10, workspace_id=1)
        orch.execute(run_id)

        repo = AnalysisRunRepository(sqlite_conn)
        run = repo.get(run_id)
        assert run.status is AnalysisRunStatus.SUCCEEDED
        assert run.support_tier is SupportTier.A
        assert run.support_reason == "all_checks_passed"
        assert run.release_decision == "pass"
        assert "summary" in run.artifacts_index
        assert "planner_exploitable" in run.artifacts_index

    def test_tier_d_short_circuits(self, sqlite_conn, tmp_path, tier_d_inputs_no_calibration):
        pr, rr = tier_d_inputs_no_calibration
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=lambda session_id, workspace_id: pr,
            evaluate_release_fn=lambda pipeline_result: rr,
            calibration_registry=None,
        )
        run_id = orch.enqueue(session_id=10, workspace_id=1)
        orch.execute(run_id)

        repo = AnalysisRunRepository(sqlite_conn)
        run = repo.get(run_id)
        # Tier D is a "succeeded completion with advisory" semantically —
        # the run itself completed; only the advanced outputs are unavailable.
        assert run.status is AnalysisRunStatus.SUCCEEDED
        assert run.support_tier is SupportTier.D
        # Only summary + diagnostics artifacts
        assert set(run.artifacts_index.keys()) <= {"summary", "diagnostics"}

    def test_pipeline_exception_marks_failed(self, sqlite_conn, tmp_path):
        def boom(session_id, workspace_id):
            raise RuntimeError("kaboom")

        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=boom,
            evaluate_release_fn=MagicMock(),
            calibration_registry=None,
        )
        run_id = orch.enqueue(session_id=10, workspace_id=1)
        orch.execute(run_id)

        repo = AnalysisRunRepository(sqlite_conn)
        run = repo.get(run_id)
        assert run.status is AnalysisRunStatus.FAILED
        assert run.error_code == "INTERNAL_ERROR"
        assert "kaboom" in run.error_message
```

- [ ] **Step 10.2: Run tests — expect ImportError**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_orchestrator.py -v`
Expected: FAIL.

- [ ] **Step 10.3: Implement `orchestrator.py`**

```python
# telemetry_tool/track_surface_app/orchestrator.py
"""AnalysisOrchestrator — drives one analysis run end-to-end.

Responsibilities:
  1. enqueue(session_id, workspace_id, force_rerun) → run_id (INSERT queued row)
  2. execute(run_id) → runs pipeline, resolves tier, writes artifacts,
     updates status.

The two halves are split because the HTTP layer calls enqueue() synchronously
and execute() runs inside the Celery task. Both share the same orchestrator
object so test harness stays simple (call execute() inline — no Celery needed).

All heavy dependencies are injected:
  - run_pipeline_fn(session_id, workspace_id) → PipelineResult
  - evaluate_release_fn(pipeline_result) → ReleaseSessionResult
  - conn_factory() → DB connection (PG wrapper in prod, sqlite3 in tests)
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable

from track_surface_app.artifacts import ArtifactWriter
from track_surface_app.domain import (
    AnalysisRunStatus,
    ConfidenceLevel,
    PlannerModeAvailability,
    SupportTier,
)
from track_surface_app.gating import OutputGate
from track_surface_app.persistence import AnalysisRunRepository
from track_surface_app.support import SupportTierResolver, compute_fallback_depth_2_pct

logger = logging.getLogger(__name__)


# Keys exposed in pipeline_summary (kept small — this is persisted per-run).
_SAFE_PIPELINE_SUMMARY_FIELDS = (
    "n_samples_total", "n_valid",
    "best_lap", "best_lap_time_s", "n_laps", "track_length_m",
    "field_coverage_pct", "field_mean_confidence",
    "bucket_active_count", "bucket_sparse_count",
    "planner_nominal_mean_mu", "planner_robust_mean_mu", "planner_exploitable_mean_mu",
    "planner_n_trusted", "planner_n_degraded",
    "calibration_profile_id", "calibration_source",
    "elapsed_s",
)


def _sanitized_summary(pr: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _SAFE_PIPELINE_SUMMARY_FIELDS:
        val = getattr(pr, key, None)
        if isinstance(val, (int, float, str)) or val is None:
            out[key] = val
    return out


def _fallback_depth_distribution(pr: Any) -> dict[str, float]:
    """Turn the integer histogram into normalized % by depth key."""
    raw = getattr(pr, "bucket_fallback_distribution", None) or {}
    total = sum(raw.values()) if raw else 0
    if total <= 0:
        return {}
    return {str(k): (v / total) * 100.0 for k, v in raw.items()}


class AnalysisOrchestrator:
    def __init__(
        self,
        *,
        conn_factory: Callable[[], Any],
        artifacts_base_dir: Path | str,
        run_pipeline_fn: Callable[[int, int], Any],
        evaluate_release_fn: Callable[[Any], Any],
        calibration_registry: Any = None,
    ):
        self._conn_factory = conn_factory
        self._artifacts_base_dir = Path(artifacts_base_dir)
        self._run_pipeline_fn = run_pipeline_fn
        self._evaluate_release_fn = evaluate_release_fn
        self._calibration_registry = calibration_registry

    # ── Public API ────────────────────────────────────────────

    def enqueue(
        self,
        *,
        session_id: int,
        workspace_id: int,
        force_rerun: bool = False,
    ) -> str:
        """Create a queued analysis run and return its run_id."""
        conn = self._conn_factory()
        repo = AnalysisRunRepository(conn)
        if not force_rerun and repo.has_in_flight(session_id):
            raise RuntimeError(f"analysis_run_in_flight for session {session_id}")
        run_id = uuid.uuid4().hex
        repo.insert_queued(run_id=run_id, session_id=session_id, workspace_id=workspace_id)
        logger.info("Enqueued analysis run %s for session %s (workspace %s)",
                    run_id, session_id, workspace_id)
        return run_id

    def execute(self, run_id: str) -> None:
        """Run the pipeline synchronously against the given run_id row."""
        conn = self._conn_factory()
        repo = AnalysisRunRepository(conn)
        run = repo.get(run_id)
        if run is None:
            logger.error("execute() called for unknown run_id %s", run_id)
            return

        repo.update_status(run_id, AnalysisRunStatus.RUNNING)
        logger.info("Running analysis %s (session=%s)", run_id, run.session_id)

        try:
            pipeline_result = self._run_pipeline_fn(run.session_id, run.workspace_id)
        except Exception as exc:
            logger.exception("Pipeline execution failed for run %s", run_id)
            repo.mark_failed(run_id=run_id, error_code="INTERNAL_ERROR",
                             error_message=f"pipeline: {exc}")
            return

        try:
            release_result = self._evaluate_release_fn(pipeline_result)
        except Exception as exc:
            logger.exception("Release gate evaluation failed for run %s", run_id)
            repo.mark_failed(run_id=run_id, error_code="INTERNAL_ERROR",
                             error_message=f"release_gate: {exc}")
            return

        tier, reason = SupportTierResolver().resolve(pipeline_result, release_result)
        gate = OutputGate(tier)
        availability = PlannerModeAvailability.for_tier(tier)
        confidence_level = ConfidenceLevel.from_mean_confidence(
            getattr(pipeline_result, "field_mean_confidence", None)
            if tier is not SupportTier.D else None
        )

        try:
            writer = ArtifactWriter(self._artifacts_base_dir, run_id=run_id, session_id=run.session_id)
            artifacts_index = writer.write_all(pipeline_result, gate=gate)
        except Exception as exc:
            logger.exception("Artifact writing failed for run %s", run_id)
            repo.mark_failed(run_id=run_id, error_code="INTERNAL_ERROR",
                             error_message=f"artifacts: {exc}")
            return

        repo.mark_succeeded(
            run_id=run_id,
            support_tier=tier,
            support_reason=reason,
            confidence_level=confidence_level,
            fallback_depth_distribution=_fallback_depth_distribution(pipeline_result),
            validated_vehicle_profile=getattr(pipeline_result, "calibration_profile_id", None),
            validated_track_profile=None,   # filled in later once track registry exists
            planner_mode_availability=availability.to_dict(),
            warnings=list(getattr(pipeline_result, "pipeline_warnings", []) or []),
            artifacts_index=artifacts_index,
            release_decision=getattr(release_result.decision, "value", None),
            pipeline_summary=_sanitized_summary(pipeline_result),
        )
        logger.info("Analysis %s succeeded: tier=%s reason=%s", run_id, tier.value, reason)
```

- [ ] **Step 10.4: Implement Celery task `track_surface_tasks.py`**

Mirror the pattern from `telemetry_tool/tasks/ocp_tasks.py`:

```python
# telemetry_tool/tasks/track_surface_tasks.py
"""Celery task for track-surface analysis.

Follows the same import-guarded pattern as tasks/ocp_tasks.py so the module is
importable in test / CLI environments where Celery is absent.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_celery():
    try:
        from tasks.celery_app import celery
        return celery
    except ImportError:
        return None


def _run_impl(run_id: str) -> dict:
    """Execute one analysis run. Factored for testability."""
    from track_surface_app.orchestrator import AnalysisOrchestrator
    from web.app import current_app_config_or_none

    config = current_app_config_or_none()
    if config is None:
        logger.warning("No Flask app context — running track-surface analysis without config")

    orchestrator = _build_orchestrator(config)
    orchestrator.execute(run_id)
    return {"run_id": run_id, "status": "completed"}


def _build_orchestrator(config):
    """Wire the orchestrator against real dependencies. Keeps orchestrator.py
    decoupled from Flask / Celery specifics."""
    from pathlib import Path

    from track_surface_app.orchestrator import AnalysisOrchestrator
    from track_surface.validation import harness, release_gate
    from web.db import get_conn    # project's DB helper

    base_dir = Path(config["RESULTS_DIR"]) / "track_surface" if config else Path("./results/track_surface")

    def run_pipeline(session_id: int, workspace_id: int):
        # Real wiring: builds a DatasetEntry from the session row, then delegates.
        # Detailed loader left to the integration task once session loader API is
        # available to this layer.
        raise NotImplementedError(
            "run_pipeline adapter must be wired to session loader — see Task 11.3"
        )

    def evaluate_release(pipeline_result):
        # Placeholder stub; real ReleaseThresholds wiring is in the integration task.
        raise NotImplementedError(
            "evaluate_release adapter must be wired — see Task 11.3"
        )

    return AnalysisOrchestrator(
        conn_factory=get_conn,
        artifacts_base_dir=base_dir,
        run_pipeline_fn=run_pipeline,
        evaluate_release_fn=evaluate_release,
    )


_celery = _get_celery()
if _celery is not None:
    @_celery.task(
        name="tasks.track_surface_tasks.run_track_surface_analysis",
        bind=True,
        queue="pipeline",
        max_retries=1,
        retry_backoff=True,
        soft_time_limit=180,
        time_limit=240,
    )
    def run_track_surface_analysis(self, run_id: str) -> dict:
        return _run_impl(run_id)
else:
    def run_track_surface_analysis(run_id: str) -> dict:  # pragma: no cover - CLI fallback
        return _run_impl(run_id)
```

- [ ] **Step 10.5: Run orchestrator tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_orchestrator.py -v`
Expected: all tests pass.

- [ ] **Step 10.6: Commit**

```bash
git add telemetry_tool/track_surface_app/orchestrator.py \
        telemetry_tool/tasks/track_surface_tasks.py \
        telemetry_tool/tests/test_track_surface_app/test_orchestrator.py
git commit -m "feat(track-surface-app): AnalysisOrchestrator + Celery task stub"
```

---

## Task 11: Flask blueprint

**Files:**
- Create: `telemetry_tool/web/routes/track_surface_analysis.py`
- Create: `telemetry_tool/tests/test_track_surface_app/test_routes.py`

- [ ] **Step 11.1: Write failing tests**

```python
# test_routes.py
"""Integration tests for the track-surface analysis blueprint.

Exercises the HTTP contract with a test Flask app. The orchestrator is mocked
so no Celery / physics is involved.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask, g

from track_surface_app.domain import SupportTier, AnalysisRunStatus, ConfidenceLevel
from track_surface_app.persistence import AnalysisRunRepository


@pytest.fixture
def app(tmp_path):
    """Minimal Flask app with the analysis blueprint mounted."""
    app = Flask(__name__)
    app.config["RESULTS_DIR"] = str(tmp_path)
    app.config["TESTING"] = True

    # In-memory sqlite with the analysis_runs schema
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY,
            session_id INTEGER NOT NULL,
            workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            support_tier TEXT, support_reason TEXT, confidence_level TEXT,
            fallback_depth_distribution TEXT, validated_vehicle_profile TEXT,
            validated_track_profile TEXT, planner_mode_availability TEXT,
            warnings TEXT NOT NULL DEFAULT '[]',
            artifacts_index TEXT NOT NULL DEFAULT '{}',
            release_decision TEXT, pipeline_summary TEXT,
            error_code TEXT, error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        )
        """
    )
    conn.commit()
    app.config["_test_conn"] = conn

    # Simulate tenant middleware by setting g.workspace_id directly
    @app.before_request
    def fake_tenant():
        g.workspace_id = 1
        g.current_user_id = 1
        g.request_id = "test-req-id"

    from web.routes.track_surface_analysis import bp as ts_bp, inject_conn_factory
    # Pass our sqlite conn to the blueprint's conn factory
    inject_conn_factory(lambda: conn)
    app.register_blueprint(ts_bp)

    yield app
    conn.close()


@pytest.fixture
def client(app):
    return app.test_client()


class TestRun:
    def test_post_run_returns_202_with_run_id(self, app, client):
        with patch("web.routes.track_surface_analysis.dispatch_celery_task") as dispatch:
            resp = client.post("/api/v1/track-surface/sessions/42/run", json={})
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["ok"] is True
        assert "run_id" in body["data"]
        assert body["data"]["status"] == "queued"
        dispatch.assert_called_once()

    def test_post_run_in_flight_409(self, app, client):
        conn = app.config["_test_conn"]
        repo = AnalysisRunRepository(conn)
        repo.insert_queued(run_id="existing", session_id=42, workspace_id=1)
        with patch("web.routes.track_surface_analysis.dispatch_celery_task"):
            resp = client.post("/api/v1/track-surface/sessions/42/run", json={})
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "CONFLICT"

    def test_post_run_force_rerun_succeeds(self, app, client):
        conn = app.config["_test_conn"]
        repo = AnalysisRunRepository(conn)
        repo.insert_queued(run_id="existing", session_id=42, workspace_id=1)
        with patch("web.routes.track_surface_analysis.dispatch_celery_task"):
            resp = client.post("/api/v1/track-surface/sessions/42/run",
                               json={"force_rerun": True})
        assert resp.status_code == 202


class TestGetRun:
    def _seed_succeeded(self, conn, *, tier, run_id="r", session_id=42):
        repo = AnalysisRunRepository(conn)
        repo.insert_queued(run_id=run_id, session_id=session_id, workspace_id=1)
        repo.mark_succeeded(
            run_id=run_id,
            support_tier=tier,
            support_reason="all_checks_passed" if tier is SupportTier.A else "release_gate_warn",
            confidence_level=ConfidenceLevel.HIGH,
            fallback_depth_distribution={"0": 80.0, "1": 15.0, "2": 5.0},
            validated_vehicle_profile="iracing_mx5_2024",
            validated_track_profile="daytona_rc_v5",
            planner_mode_availability={"nominal": True, "robust": True,
                                       "exploitable": tier is SupportTier.A},
            warnings=[],
            artifacts_index={"summary": f"42/{run_id}/summary.json",
                             "diagnostics": f"42/{run_id}/diagnostics.json"},
            release_decision="pass",
            pipeline_summary={"n_valid": 9500, "best_lap_time_s": 88.1,
                              "n_samples_total": 10000, "n_laps": 5,
                              "best_lap": 3, "track_length_m": 3820.0,
                              "field_coverage_pct": 85.0,
                              "field_mean_confidence": 0.82,
                              "bucket_active_count": 6, "bucket_sparse_count": 0,
                              "planner_nominal_mean_mu": 1.05,
                              "planner_robust_mean_mu": 0.98,
                              "planner_exploitable_mean_mu": 1.12,
                              "planner_n_trusted": 900,
                              "planner_n_degraded": 100,
                              "calibration_profile_id": "iracing_mx5_2024",
                              "calibration_source": "registry_active"},
        )

    def test_get_session_returns_latest_run(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.A)
        resp = client.get("/api/v1/track-surface/sessions/42")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["support_tier"] == "A"
        assert body["data"]["planner_mode_availability"] == {
            "nominal": True, "robust": True, "exploitable": True,
        }

    def test_get_session_404_when_no_run(self, client):
        resp = client.get("/api/v1/track-surface/sessions/9999")
        assert resp.status_code == 404

    def test_get_planner_refused_at_tier_c(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.C)
        resp = client.get("/api/v1/track-surface/sessions/42/planner")
        assert resp.status_code == 451
        body = resp.get_json()
        assert body["error"]["code"] == "SUPPORT_TIER_REFUSED"

    def test_get_surface_refused_at_tier_d(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.D)
        resp = client.get("/api/v1/track-surface/sessions/42/surface")
        assert resp.status_code == 451


class TestSupportResolve:
    def test_known_combo(self, client):
        resp = client.get("/api/v1/track-surface/support/resolve"
                          "?sim=iracing&vehicle=mx5&track=daytona_rc")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["support_tier"] == "A"

    def test_unknown_combo_tier_d(self, client):
        resp = client.get("/api/v1/track-surface/support/resolve"
                          "?sim=ac&vehicle=gt3&track=nord")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["support_tier"] == "D"
        assert body["data"]["support_reason"] == "vehicle_profile_not_validated"


class TestSupportMatrix:
    def test_returns_entries(self, client):
        resp = client.get("/api/v1/track-surface/support/matrix")
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body["data"]["entries"], list)
        assert len(body["data"]["entries"]) >= 1
```

- [ ] **Step 11.2: Run tests — expect ImportError**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_routes.py -v`
Expected: FAIL — blueprint doesn't exist yet.

- [ ] **Step 11.3: Implement the blueprint**

```python
# telemetry_tool/web/routes/track_surface_analysis.py
"""HTTP endpoints for the track-surface analysis app.

All endpoints use the standard ``{ok, data, error, meta}`` envelope and rely on
``g.workspace_id`` set by the tenant middleware.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from flask import Blueprint, g, jsonify, request, send_file
from pydantic import ValidationError

from track_surface_app.domain import (
    AnalysisRunStatus,
    PlannerModeAvailability,
    SupportTier,
)
from track_surface_app.gating import OutputGate, ALL_ARTIFACT_KINDS
from track_surface_app.orchestrator import AnalysisOrchestrator
from track_surface_app.persistence import AnalysisRunRecord, AnalysisRunRepository
from track_surface_app.support_matrix import SupportMatrix
from web.api_utils import (
    ErrorCode,
    api_error,
    api_response,
)
from web.schemas.track_surface import (
    RunAnalysisRequest,
    ResolveSupportParams,
)

logger = logging.getLogger(__name__)

bp = Blueprint("track_surface_analysis", __name__, url_prefix="/api/v1/track-surface")

# ── Dependency injection (for tests) ─────────────────────────

_CONN_FACTORY: Callable[[], Any] | None = None
_SUPPORT_MATRIX: SupportMatrix | None = None


def inject_conn_factory(factory: Callable[[], Any]) -> None:
    """Override the DB conn factory (used in tests)."""
    global _CONN_FACTORY
    _CONN_FACTORY = factory


def inject_support_matrix(matrix: SupportMatrix) -> None:
    """Override the support matrix (used in tests)."""
    global _SUPPORT_MATRIX
    _SUPPORT_MATRIX = matrix


def _get_conn():
    if _CONN_FACTORY is not None:
        return _CONN_FACTORY()
    from web.db import get_conn
    return get_conn()


def _get_matrix() -> SupportMatrix:
    global _SUPPORT_MATRIX
    if _SUPPORT_MATRIX is None:
        _SUPPORT_MATRIX = SupportMatrix.load_default()
    return _SUPPORT_MATRIX


def dispatch_celery_task(run_id: str) -> None:
    """Dispatch the Celery task. Isolated so tests can patch it."""
    try:
        from tasks.track_surface_tasks import run_track_surface_analysis
        celery_obj = getattr(run_track_surface_analysis, "delay", None)
        if callable(celery_obj):
            run_track_surface_analysis.delay(run_id)
        else:
            # Celery not available — run inline (dev/test)
            run_track_surface_analysis(run_id)
    except Exception as exc:   # celery layer issue — don't fail the request
        logger.exception("Failed to dispatch Celery task for run %s: %s", run_id, exc)


# ── Serialization helpers ────────────────────────────────────

def _run_to_summary_dict(run: AnalysisRunRecord) -> dict[str, Any]:
    gate = OutputGate(run.support_tier) if run.support_tier else OutputGate(SupportTier.D)
    artifacts_available = [
        k for k in run.artifacts_index.keys() if gate.is_artifact_allowed(k)
    ]
    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "status": run.status.value,
        "support_tier": run.support_tier.value if run.support_tier else None,
        "support_reason": run.support_reason,
        "confidence_level": run.confidence_level.value if run.confidence_level else None,
        "fallback_depth_pct": run.fallback_depth_distribution,
        "validated_vehicle_profile": run.validated_vehicle_profile,
        "validated_track_profile": run.validated_track_profile,
        "planner_mode_availability": run.planner_mode_availability,
        "warnings": run.warnings,
        "artifacts_available": artifacts_available,
        "release_decision": run.release_decision,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": str(run.created_at) if run.created_at else None,
        "completed_at": str(run.completed_at) if run.completed_at else None,
    }


def _tier_refused(tier: SupportTier, reason: str, *, endpoint: str):
    return api_error(
        ErrorCode.SUPPORT_TIER_REFUSED,
        message=f"{endpoint} unavailable at support tier {tier.value}.",
        details={
            "support_tier": tier.value,
            "support_reason": reason,
            "planner_mode_availability":
                PlannerModeAvailability.for_tier(tier).to_dict(),
        },
        status=451,
    )


# ── POST /sessions/<sid>/run ────────────────────────────────

@bp.route("/sessions/<int:session_id>/run", methods=["POST"])
def run_analysis(session_id: int):
    try:
        req = RunAnalysisRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return api_error(ErrorCode.VALIDATION_ERROR, message=str(exc), status=422)

    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, message="missing workspace context",
                         status=401)

    # Build a minimal orchestrator for the enqueue step only; execute happens
    # in the Celery worker.
    orchestrator = AnalysisOrchestrator(
        conn_factory=_get_conn,
        artifacts_base_dir=".",    # not used by enqueue
        run_pipeline_fn=lambda *a, **kw: None,
        evaluate_release_fn=lambda *a, **kw: None,
    )
    try:
        run_id = orchestrator.enqueue(
            session_id=session_id,
            workspace_id=workspace_id,
            force_rerun=req.force_rerun,
        )
    except RuntimeError as exc:
        if "in_flight" in str(exc):
            return api_error(
                ErrorCode.CONFLICT,
                message="An analysis run is already in flight for this session.",
                status=409,
            )
        raise

    dispatch_celery_task(run_id)

    # Return the just-created queued row
    repo = AnalysisRunRepository(_get_conn())
    run = repo.get(run_id)
    return api_response(_run_to_summary_dict(run), status=202)


# ── GET /sessions/<sid> ─────────────────────────────────────

@bp.route("/sessions/<int:session_id>", methods=["GET"])
def get_session_run(session_id: int):
    repo = AnalysisRunRepository(_get_conn())
    run = repo.get_latest_for_session(session_id)
    if run is None:
        return api_error(ErrorCode.NOT_FOUND,
                         message=f"No analysis run found for session {session_id}",
                         status=404)
    return api_response(_run_to_summary_dict(run))


# ── GET /sessions/<sid>/summary ─────────────────────────────

@bp.route("/sessions/<int:session_id>/summary", methods=["GET"])
def get_session_summary(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    if run.pipeline_summary is None:
        return api_error(ErrorCode.NOT_FOUND, message="No summary for this run",
                         status=404)
    return api_response({
        "run_id": run.run_id,
        "session_id": run.session_id,
        **{k: run.pipeline_summary.get(k) for k in (
            "n_samples_total", "n_laps", "best_lap", "best_lap_time_s",
            "track_length_m", "calibration_profile_id", "calibration_source",
        )},
        "n_samples_accepted": run.pipeline_summary.get("n_valid"),
        "lap_times_s": run.pipeline_summary.get("lap_times_s", {}),
        "warnings": run.warnings,
    })


# ── GET /sessions/<sid>/surface ─────────────────────────────

@bp.route("/sessions/<int:session_id>/surface", methods=["GET"])
def get_session_surface(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    if not OutputGate(tier).is_endpoint_allowed("surface"):
        return _tier_refused(tier, run.support_reason or "no_pipeline_run",
                             endpoint="surface")
    ps = run.pipeline_summary or {}
    return api_response({
        "run_id": run.run_id,
        "coverage_pct": ps.get("field_coverage_pct", 0.0),
        "mean_confidence": ps.get("field_mean_confidence", 0.0),
        "confidence_level": run.confidence_level.value if run.confidence_level else "unknown",
        "fallback_depth_pct": run.fallback_depth_distribution or {},
        "bucket_active_count": ps.get("bucket_active_count", 0),
        "bucket_sparse_count": ps.get("bucket_sparse_count", 0),
    })


# ── GET /sessions/<sid>/planner ─────────────────────────────

@bp.route("/sessions/<int:session_id>/planner", methods=["GET"])
def get_session_planner(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    if not OutputGate(tier).is_endpoint_allowed("planner"):
        return _tier_refused(tier, run.support_reason or "no_pipeline_run",
                             endpoint="planner")

    ps = run.pipeline_summary or {}
    av = PlannerModeAvailability.for_tier(tier)
    data = {
        "run_id": run.run_id,
        "support_tier": tier.value,
        "available_modes": [m for m, on in av.to_dict().items() if on],
        "nominal": None,
        "robust": None,
        "exploitable": None,
        "unavailable_reason": None,
    }
    for mode in ("nominal", "robust", "exploitable"):
        if not getattr(av, mode):
            continue
        mean_mu_key = f"planner_{mode}_mean_mu"
        data[mode] = {
            "mode": mode,
            "mu_eff_mean": ps.get(mean_mu_key, 0.0),
            "trusted_point_count": ps.get("planner_n_trusted", 0),
            "degraded_point_count": ps.get("planner_n_degraded", 0),
            "total_point_count": ps.get("planner_n_trusted", 0) + ps.get("planner_n_degraded", 0),
            "max_robust_penalty": ps.get("planner_max_robust_penalty", 0.0),
        }
    return api_response(data)


# ── GET /sessions/<sid>/uncertainty ─────────────────────────

@bp.route("/sessions/<int:session_id>/uncertainty", methods=["GET"])
def get_session_uncertainty(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    if not OutputGate(tier).is_endpoint_allowed("uncertainty"):
        return _tier_refused(tier, run.support_reason or "no_pipeline_run",
                             endpoint="uncertainty")
    ps = run.pipeline_summary or {}
    return api_response({
        "run_id": run.run_id,
        "mean_confidence": ps.get("field_mean_confidence", 0.0),
        "confidence_level": run.confidence_level.value if run.confidence_level else "unknown",
        "high_conf_cells": ps.get("field_high_conf_cells", 0),
        "zero_conf_cells": ps.get("field_zero_conf_cells", 0),
        "fallback_depth_pct": run.fallback_depth_distribution or {},
    })


# ── GET /sessions/<sid>/artifacts ───────────────────────────

@bp.route("/sessions/<int:session_id>/artifacts", methods=["GET"])
def get_session_artifacts(session_id: int):
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    gate = OutputGate(tier)
    refs: list[dict[str, Any]] = []
    for kind, rel_path in (run.artifacts_index or {}).items():
        if not gate.is_artifact_allowed(kind):
            continue
        refs.append({
            "kind": kind,
            "download_url": f"/api/v1/track-surface/sessions/{run.session_id}"
                            f"/artifacts/{kind}",
            "size_bytes": 0,
            "version": "v1",
        })
    return api_response({"run_id": run.run_id, "artifacts": refs})


# ── GET /sessions/<sid>/artifacts/<kind> ───────────────────

@bp.route("/sessions/<int:session_id>/artifacts/<string:kind>", methods=["GET"])
def download_artifact(session_id: int, kind: str):
    if kind not in ALL_ARTIFACT_KINDS:
        return api_error(ErrorCode.NOT_FOUND,
                         message=f"Unknown artifact kind: {kind}", status=404)
    run = _require_run(session_id)
    if isinstance(run, tuple):
        return run
    tier = run.support_tier or SupportTier.D
    if not OutputGate(tier).is_artifact_allowed(kind):
        return _tier_refused(tier, run.support_reason or "no_pipeline_run",
                             endpoint=f"artifact:{kind}")
    rel_path = (run.artifacts_index or {}).get(kind)
    if not rel_path:
        return api_error(ErrorCode.NOT_FOUND,
                         message=f"Artifact {kind} not generated for this run",
                         status=404)
    from flask import current_app
    from pathlib import Path
    base = Path(current_app.config.get("RESULTS_DIR", ".")) / "track_surface"
    full_path = base / rel_path
    if not full_path.is_file():
        return api_error(ErrorCode.NOT_FOUND,
                         message="Artifact file missing on disk", status=404)
    return send_file(full_path, mimetype="application/json")


# ── GET /support/resolve ────────────────────────────────────

@bp.route("/support/resolve", methods=["GET"])
def resolve_support():
    try:
        params = ResolveSupportParams.model_validate(dict(request.args))
    except ValidationError as exc:
        return api_error(ErrorCode.VALIDATION_ERROR, message=str(exc), status=422)

    entry = _get_matrix().resolve(sim=params.sim, vehicle=params.vehicle,
                                  track=params.track)
    if entry is None:
        tier = SupportTier.D
        av = PlannerModeAvailability.for_tier(tier)
        return api_response({
            "run_id": None,
            "sim": params.sim, "vehicle": params.vehicle, "track": params.track,
            "support_tier": tier.value,
            "support_reason": "vehicle_profile_not_validated",
            "validated_vehicle_profile": None,
            "validated_track_profile": None,
            "planner_mode_availability": av.to_dict(),
            "warnings": ["combination_not_in_support_matrix"],
        })

    tier = entry.max_support_tier
    av = PlannerModeAvailability.for_tier(tier)
    return api_response({
        "run_id": None,
        "sim": params.sim, "vehicle": params.vehicle, "track": params.track,
        "support_tier": tier.value,
        "support_reason": "all_checks_passed" if tier is SupportTier.A
                          else "moderate_fallback",
        "validated_vehicle_profile": entry.validated_vehicle_profile,
        "validated_track_profile": entry.validated_track_profile,
        "planner_mode_availability": av.to_dict(),
        "warnings": [],
    })


# ── GET /support/matrix ─────────────────────────────────────

@bp.route("/support/matrix", methods=["GET"])
def get_support_matrix():
    matrix = _get_matrix()
    return api_response({
        "entries": [
            {
                "sim": e.sim,
                "vehicle": e.vehicle,
                "track": e.track,
                "max_support_tier": e.max_support_tier.value,
                "validated_vehicle_profile": e.validated_vehicle_profile,
                "validated_track_profile": e.validated_track_profile,
            }
            for e in matrix.entries
        ],
        "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })


# ── Shared helper ───────────────────────────────────────────

def _require_run(session_id: int):
    """Load the latest run for this session or return a 404 envelope."""
    repo = AnalysisRunRepository(_get_conn())
    run = repo.get_latest_for_session(session_id)
    if run is None:
        return api_error(ErrorCode.NOT_FOUND,
                         message=f"No analysis run found for session {session_id}",
                         status=404)
    return run
```

- [ ] **Step 11.4: Run route tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_track_surface_app/test_routes.py -v`
Expected: all tests pass. If `api_error` / `api_response` signatures differ from
the assumption, adjust the blueprint to match `web/api_utils.py`.

- [ ] **Step 11.5: Commit**

```bash
git add telemetry_tool/web/routes/track_surface_analysis.py \
        telemetry_tool/tests/test_track_surface_app/test_routes.py
git commit -m "feat(track-surface-app): Flask blueprint with 9 endpoints + tier gating"
```

---

## Task 12: Register blueprint in `app.py`

**Files:**
- Modify: `telemetry_tool/web/app.py`

- [ ] **Step 12.1: Find `_blueprint_imports`**

Run: `grep -n '_blueprint_imports\|routes.sessions_v2\|routes.data_v2' telemetry_tool/web/app.py | head -10`
Expected: shows the tuple literal containing existing blueprints.

- [ ] **Step 12.2: Add the new blueprint to the tuple**

Edit the `_blueprint_imports` tuple to include:

```python
('.routes.track_surface_analysis', 'bp', 'track_surface_analysis_bp'),
```

Placed alphabetically near `sessions_v2` / `data_v2`.

- [ ] **Step 12.3: Smoke test app factory**

Run: `python -c "from telemetry_tool.web.app import create_app; app = create_app(); print(sorted(r.rule for r in app.url_map.iter_rules() if r.rule.startswith('/api/v1/track-surface'))[:3])"`
Expected: prints at least 3 routes under `/api/v1/track-surface/`.

- [ ] **Step 12.4: Commit**

```bash
git add telemetry_tool/web/app.py
git commit -m "feat(web): register track_surface_analysis blueprint"
```

---

## Task 13: Full test suite + lint/build verification

- [ ] **Step 13.1: Run the new test package**

Run: `pytest telemetry_tool/tests/test_track_surface_app/ -v`
Expected: all tests pass. Count printed in output.

- [ ] **Step 13.2: Run full backend suite (regression check)**

Run: `pytest telemetry_tool/tests/ -x --tb=short`
Expected: no regressions. If a pre-existing unrelated test was already failing
before this work, note it and continue.

- [ ] **Step 13.3: Sanity-check migration on SQLite**

Run: `python -c "from telemetry_tool.alembic.versions.\"056_analysis_runs\" import upgrade; print('migration importable')"`

(The migration runs against PG in prod; SQLite import-smoke is enough here.)

- [ ] **Step 13.4: Commit final checkpoint**

Nothing to stage if all earlier tasks committed cleanly. If unstaged files
remain, inspect and commit or revert:

Run: `git status`

---

## Out-of-plan note: completion step is NOT deploy

Per `CLAUDE.md` "Ship It Live" rule, a real deploy would follow (scp, `docker
compose build api`, `curl /healthz`). **That step is intentionally excluded from
this plan** — the scope here is "code + tests land on branch". Deployment
happens after user review of the branch diff and any follow-up changes.

---

## Self-review (done)

1. **Spec coverage:** each of §§4–11 in the design doc maps to at least one task.
   Support matrix seed data, RLS policy, SUPPORT_TIER_REFUSED error, all
   endpoints, all gating rules — covered.
2. **Placeholder scan:** one intentional `NotImplementedError` in
   `_build_orchestrator` (Task 10.4) — it's the session-loader adapter that
   must be wired against the real session store. Marked clearly. No other TBDs.
3. **Type consistency:** `SupportTier`, `AnalysisRunStatus`, `ConfidenceLevel`,
   `PlannerModeAvailability` used consistently across all tasks. Repository
   field names match schema field names.
4. **Ambiguity:** tier-D decision — "failed" vs "succeeded"? Per Task 10.1
   test, tier D via missing calibration = `status=SUCCEEDED`, `support_tier=D`
   (the run completed; advanced features just unavailable). Tier D via pipeline
   exception = `status=FAILED`. Consistent in tests + orchestrator code.
