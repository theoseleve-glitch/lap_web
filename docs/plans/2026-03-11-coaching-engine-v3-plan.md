# Coaching Engine V3 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded coaching engine with a config-driven, physics-informed coaching system that produces prescriptive, progressive, psychology-aware feedback — full stack (Python backend + Next.js frontend + Alembic migration).

**Architecture:** New `telemetry_tool/coaching/` package with 4 layers: taxonomy (cause definitions in JSON), analyzers (6 physics modules), templates (300+ parameterized coaching texts), and composers (assembly logic). Pipeline stages S13e–S13g2 run analyzers and compose coaching. Output persisted in `analysis_json["coaching_v3"]` for the GET endpoint. Frontend renders via new `coaching/` component group.

**Tech Stack:** Python 3.x dataclasses, Pydantic v2 (taxonomy validation), pandas/numpy (analyzers), Alembic/PostgreSQL (migration), Next.js 14/TypeScript/Tailwind (frontend), Vitest/pytest (tests).

**Spec:** `docs/plans/2026-03-11-coaching-engine-v3-design.md`

---

## File Map

### New Files (Backend)

| File | Responsibility |
|------|---------------|
| `telemetry_tool/coaching/__init__.py` | Public API: `generate_session_coaching_v3()` |
| `telemetry_tool/coaching/models.py` | All dataclasses (SessionCoaching, CornerCoachingDetail, etc.) with `to_dict()` |
| `telemetry_tool/coaching/taxonomy/causes.py` | `CauseTaxonomy` class — loads + validates `causes.json` |
| `telemetry_tool/coaching/taxonomy/causes.json` | ~40 cause definitions with symptom, diagnosis, thresholds |
| `telemetry_tool/coaching/taxonomy/symptoms.py` | Symptom→cause mapping rules |
| `telemetry_tool/coaching/analyzers/trail_brake.py` | 4-block braking analysis |
| `telemetry_tool/coaching/analyzers/exit_speed.py` | Exit→straight cascade calculator |
| `telemetry_tool/coaching/analyzers/traction_budget.py` | Friction circle budget |
| `telemetry_tool/coaching/analyzers/symptom_detector.py` | Rule-based symptom detection |
| `telemetry_tool/coaching/analyzers/throttle_lift.py` | Mid-corner throttle lift detection |
| `telemetry_tool/coaching/analyzers/weight_transfer.py` | Load transfer calculation |
| `telemetry_tool/coaching/templates/corner_tips.py` | ~300+ per-corner templates |
| `telemetry_tool/coaching/templates/drills.py` | ~20 drill types × 3 difficulty levels |
| `telemetry_tool/coaching/templates/narratives.py` | Session narrative templates |
| `telemetry_tool/coaching/templates/symptoms.py` | Symptom diagnosis text |
| `telemetry_tool/coaching/templates/progression.py` | Multi-session trend text |
| `telemetry_tool/coaching/templates/confidence_frames.py` | Strength framing templates |
| `telemetry_tool/coaching/templates/mental_imagery.py` | Visualization prompts |
| `telemetry_tool/coaching/templates/reference_points.py` | Brake point landmark descriptions |
| `telemetry_tool/coaching/composers/corner_composer.py` | Per-corner coaching assembly |
| `telemetry_tool/coaching/composers/session_composer.py` | Full session coaching assembly |
| `telemetry_tool/coaching/composers/focus_limiter.py` | Max 2 focus areas |
| `telemetry_tool/coaching/composers/progressive_coach.py` | Progressive goals + warm-up |
| `telemetry_tool/coaching/composers/confidence_framer.py` | Strength rewriting |
| `telemetry_tool/coaching/persistence/models.py` | corner_progression table definition |
| `telemetry_tool/coaching/persistence/queries.py` | DB store/retrieve |
| `telemetry_tool/pipeline/stages/s13_coaching_v3.py` | Pipeline stages S13e–S13g2 |
| `telemetry_tool/alembic/versions/040_corner_progression.py` | Migration |

### New Files (Tests)

| File | Tests |
|------|-------|
| `telemetry_tool/tests/coaching/test_models.py` | Dataclass creation + to_dict() |
| `telemetry_tool/tests/coaching/test_taxonomy.py` | causes.json validation + lookup |
| `telemetry_tool/tests/coaching/test_trail_brake.py` | 4-block detection |
| `telemetry_tool/tests/coaching/test_exit_speed.py` | Cascade calculation |
| `telemetry_tool/tests/coaching/test_traction_budget.py` | Friction circle budget |
| `telemetry_tool/tests/coaching/test_symptom_detector.py` | Symptom rules + tier fallback |
| `telemetry_tool/tests/coaching/test_throttle_lift.py` | Lift detection + severity |
| `telemetry_tool/tests/coaching/test_weight_transfer.py` | Load transfer calc |
| `telemetry_tool/tests/coaching/test_focus_limiter.py` | Max 2 enforcement |
| `telemetry_tool/tests/coaching/test_progressive_coach.py` | Goals + warm-up + late apex reset |
| `telemetry_tool/tests/coaching/test_confidence_framer.py` | Strength rewriting |
| `telemetry_tool/tests/coaching/test_corner_composer.py` | Per-corner assembly |
| `telemetry_tool/tests/coaching/test_session_composer.py` | Full session assembly |
| `telemetry_tool/tests/coaching/test_templates.py` | Template coverage (all cause×severity×vehicle) |
| `telemetry_tool/tests/coaching/test_persistence.py` | DB store/retrieve |
| `telemetry_tool/tests/coaching/test_pipeline_integration.py` | S13e–S13g2 stages |

### New Files (Frontend)

| File | Component |
|------|-----------|
| `lap-website/src/components/app/coaching/CoachingPanel.tsx` | Main container |
| `lap-website/src/components/app/coaching/SessionTheme.tsx` | Grade + narrative |
| `lap-website/src/components/app/coaching/FocusAreaCard.tsx` | Focus area + steps |
| `lap-website/src/components/app/coaching/DrillCard.tsx` | Drill + difficulty tabs |
| `lap-website/src/components/app/coaching/CornerCoachingCard.tsx` | Per-corner detail |
| `lap-website/src/components/app/coaching/SpeedTargets.tsx` | Target vs actual bars |
| `lap-website/src/components/app/coaching/TractionBudgetViz.tsx` | Friction circle SVG |
| `lap-website/src/components/app/coaching/TrailBrakeTimeline.tsx` | 4-block timeline |
| `lap-website/src/components/app/coaching/ExitCascadeViz.tsx` | Cascade arrows |
| `lap-website/src/components/app/coaching/CornerTrendChart.tsx` | Sparkline |
| `lap-website/src/components/app/coaching/WarmUpProtocol.tsx` | Pre-session card |
| `lap-website/src/components/app/coaching/MentalImageryPrompt.tsx` | Visualization card |
| `lap-website/src/components/app/coaching/NextSessionGoals.tsx` | Goals list |
| `lap-website/src/components/app/coaching/DeferredAreas.tsx` | "For later" section |
| `lap-website/src/components/app/coaching/StrengthsList.tsx` | Strengths |

### Modified Files

| File | Change |
|------|--------|
| `telemetry_tool/pipeline/orchestrator.py:1098-1104` | Insert S13e–S13g2 calls after S13d |
| `telemetry_tool/web/routes/data_v2.py:4579-4626` | Coaching endpoint: read coaching_v3 from analysis_json |
| `telemetry_tool/web/routes/sessions_v2.py:245-278` | Persist coaching_v3 in analysis_json blob |

---

## Chunk 1: Foundation — Models, Taxonomy, Package Structure

### Task 1: Package skeleton + models

**Files:**
- Create: `telemetry_tool/coaching/__init__.py`
- Create: `telemetry_tool/coaching/models.py`
- Create: `telemetry_tool/coaching/taxonomy/__init__.py`
- Create: `telemetry_tool/coaching/analyzers/__init__.py`
- Create: `telemetry_tool/coaching/templates/__init__.py`
- Create: `telemetry_tool/coaching/composers/__init__.py`
- Create: `telemetry_tool/coaching/persistence/__init__.py`
- Test: `telemetry_tool/tests/coaching/__init__.py`
- Test: `telemetry_tool/tests/coaching/test_models.py`

- [ ] **Step 1: Create package directories**

```bash
mkdir -p telemetry_tool/coaching/taxonomy
mkdir -p telemetry_tool/coaching/analyzers
mkdir -p telemetry_tool/coaching/templates
mkdir -p telemetry_tool/coaching/composers
mkdir -p telemetry_tool/coaching/persistence
mkdir -p telemetry_tool/tests/coaching
```

- [ ] **Step 2: Write the failing test for models**

Create `telemetry_tool/tests/coaching/test_models.py`:

```python
"""Tests for coaching.models — all dataclasses and to_dict() serialization."""
import pytest
from telemetry_tool.coaching.models import (
    BrakingBlock, TrailBrakeAssessment, ExitSpeedCascade, TractionBudget,
    ThrottleLiftEvent, Symptom, SymptomDetection, WeightTransferInsight,
    CornerTrend, CornerCoachingDetail, WarmUpProtocol,
    FocusArea, Drill, ProgressionInsight, SessionCoaching,
)


class TestBrakingBlock:
    def test_creation(self):
        b = BrakingBlock(
            block_id=3, name="trail_brake", s_start=100.0, s_end=120.0,
            duration_s=0.8, peak_decel_mps2=-8.5, overlap_m=20.0,
            trail_pct_at_turnin=45.0, release_rate_mps3=-12.0,
            release_linearity=0.85, transition_duration_s=None,
        )
        assert b.block_id == 3
        assert b.name == "trail_brake"

    def test_to_dict_roundtrip(self):
        b = BrakingBlock(
            block_id=1, name="throttle_to_brake", s_start=80.0, s_end=85.0,
            duration_s=0.15, peak_decel_mps2=None, overlap_m=None,
            trail_pct_at_turnin=None, release_rate_mps3=None,
            release_linearity=None, transition_duration_s=None,
        )
        d = b.to_dict()
        assert d["block_id"] == 1
        assert d["peak_decel_mps2"] is None


class TestTrailBrakeAssessment:
    def test_creation_with_trail(self):
        blocks = [
            BrakingBlock(i, f"b{i}", 0, 10, 0.5,
                         None, None, None, None, None, None)
            for i in range(1, 5)
        ]
        t = TrailBrakeAssessment(
            corner_id=3, blocks=blocks, overall_score=72.0,
            has_trail_braking=True, theoretical_overlap_m=15.0,
            actual_overlap_m=10.0, time_loss_from_no_trail_s=0.12,
            primary_issue=None,
        )
        assert t.has_trail_braking is True
        d = t.to_dict()
        assert len(d["blocks"]) == 4


class TestExitSpeedCascade:
    def test_cascade_ratio(self):
        e = ExitSpeedCascade(
            corner_id=5,
            actual_exit_speed_mps=20.0, theoretical_exit_speed_mps=23.0,
            exit_speed_delta_mps=3.0,
            straight_length_m=300.0,
            straight_end_speed_actual_mps=45.0,
            straight_end_speed_theoretical_mps=47.5,
            time_loss_in_corner_s=0.18,
            time_loss_on_straight_s=0.22,
            total_cascade_time_s=0.40,
            exit_gain_needed_kmh=10.8,
            straight_gain_resulting_kmh=9.0,
            cascade_ratio=1.22,
        )
        assert e.total_cascade_time_s == pytest.approx(0.40)
        d = e.to_dict()
        assert d["cascade_ratio"] == pytest.approx(1.22)


class TestTractionBudget:
    def test_remaining_pct(self):
        tb = TractionBudget(
            corner_id=2,
            entry_lateral_pct=40.0, entry_longitudinal_pct=60.0,
            entry_total_pct=72.1, entry_remaining_pct=27.9,
            apex_lateral_pct=85.0, apex_longitudinal_pct=5.0,
            apex_total_pct=85.1, apex_remaining_pct=14.9,
            exit_lateral_pct=50.0, exit_longitudinal_pct=45.0,
            exit_total_pct=67.3, exit_remaining_pct=32.7,
            theoretical_apex_total_pct=92.0, grip_headroom_pct=6.9,
        )
        assert tb.apex_remaining_pct == pytest.approx(14.9)


class TestSessionCoaching:
    def test_backward_compat_to_dict(self):
        """Old fields must always be present; new fields appear only when set."""
        sc = SessionCoaching(
            session_theme="Good session",
            narrative="You drove well.",
            strengths=["pace"],
            weaknesses=["consistency"],
            focus_areas=[],
            drills=[],
            progression=[],
            next_session_goals=["Improve T3"],
            confidence=0.85,
        )
        d = sc.to_dict()
        # Old fields always present
        assert "session_theme" in d
        assert "narrative" in d
        assert "confidence" in d
        # New optional fields present but None
        assert d.get("corner_coaching") is None
        assert d.get("vehicle_class") is None

    def test_new_fields_serialized(self):
        sc = SessionCoaching(
            session_theme="t", narrative="n", strengths=[], weaknesses=[],
            focus_areas=[], drills=[], progression=[],
            next_session_goals=[], confidence=0.9,
            vehicle_class="kart",
            mental_imagery_prompts=["Imagine Turn 3..."],
        )
        d = sc.to_dict()
        assert d["vehicle_class"] == "kart"
        assert d["mental_imagery_prompts"] == ["Imagine Turn 3..."]
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd telemetry_tool && python -m pytest tests/coaching/test_models.py -v
```
Expected: `ModuleNotFoundError: No module named 'telemetry_tool.coaching'`

- [ ] **Step 4: Implement models.py**

Create `telemetry_tool/coaching/__init__.py`:
```python
"""Coaching Engine V3 — config-driven, physics-informed coaching."""
```

Create all `__init__.py` files for subpackages (empty).

Create `telemetry_tool/coaching/models.py` with all dataclasses from spec sections 4.1–4.8. Each dataclass gets a `to_dict()` method that recursively serializes, handling `None` optional fields and nested dataclasses.

Key implementation notes:
- `SessionCoaching.to_dict()` must emit ALL fields including new Optional ones (as None when unset)
- Nested dataclasses (e.g., `CornerCoachingDetail.traction_budget`) call their own `to_dict()`
- Float rounding: time values to 3 decimals, speeds to 2 decimals, percentages to 1 decimal
- `FocusArea` adds `progressive_steps: list[str] | None = None` and `symptom_diagnosis: str | None = None`
- `Drill` adds `difficulty: str | None = None`, `success_criteria: str | None = None`, `difficulty_progression: dict | None = None`

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd telemetry_tool && python -m pytest tests/coaching/test_models.py -v
```
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/coaching/ telemetry_tool/tests/coaching/
git commit -m "feat(coaching-v3): package skeleton + all dataclass models with to_dict()"
```

---

### Task 2: Cause taxonomy — JSON + Pydantic validation

**Files:**
- Create: `telemetry_tool/coaching/taxonomy/causes.json`
- Create: `telemetry_tool/coaching/taxonomy/causes.py`
- Test: `telemetry_tool/tests/coaching/test_taxonomy.py`

- [ ] **Step 1: Write the failing test**

Create `telemetry_tool/tests/coaching/test_taxonomy.py`:

```python
"""Tests for CauseTaxonomy — JSON loading, Pydantic validation, lookup."""
import pytest
from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy


class TestCauseTaxonomyLoading:
    def test_loads_all_categories(self):
        tax = CauseTaxonomy()
        assert "braking" in tax.categories
        assert "cornering" in tax.categories
        assert "exit" in tax.categories
        assert "consistency" in tax.categories
        assert "vehicle_management" in tax.categories

    def test_braking_has_seven_causes(self):
        tax = CauseTaxonomy()
        assert len(tax.categories["braking"]) == 7

    def test_each_cause_has_required_fields(self):
        tax = CauseTaxonomy()
        for cat_name, causes in tax.categories.items():
            for cause_id, cause in causes.items():
                assert "symptom" in cause, f"{cat_name}.{cause_id} missing symptom"
                assert "diagnosis" in cause, f"{cat_name}.{cause_id} missing diagnosis"
                assert "root_cause" in cause, f"{cat_name}.{cause_id} missing root_cause"
                assert cause["root_cause"] in (
                    "technique", "confidence", "line", "balance",
                    "aggression", "fitness", "management", "awareness", "fear"
                ), f"{cat_name}.{cause_id} invalid root_cause: {cause['root_cause']}"


class TestCauseTaxonomyLookup:
    def test_get_cause(self):
        tax = CauseTaxonomy()
        cause = tax.get_cause("early_braking_confidence")
        assert cause is not None
        assert cause["root_cause"] in ("confidence", "fear")

    def test_get_cause_unknown_returns_none(self):
        tax = CauseTaxonomy()
        assert tax.get_cause("nonexistent_cause") is None

    def test_get_category_for_cause(self):
        tax = CauseTaxonomy()
        assert tax.get_category("early_apex") == "cornering"
        assert tax.get_category("late_throttle_application") == "exit"

    def test_get_severity(self):
        tax = CauseTaxonomy()
        sev = tax.get_severity("early_braking_confidence", delta=7.0)
        assert sev in ("mild", "moderate", "severe")

    def test_get_severity_mild(self):
        tax = CauseTaxonomy()
        sev = tax.get_severity("early_braking_confidence", delta=3.0)
        assert sev == "mild"

    def test_get_severity_severe(self):
        tax = CauseTaxonomy()
        sev = tax.get_severity("early_braking_confidence", delta=25.0)
        assert sev == "severe"


class TestCauseTaxonomyValidation:
    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"version": 2, "categories": {"braking": {"causes": {"x": {}}}}}')
        with pytest.raises(ValueError):
            CauseTaxonomy(path=str(bad))
```

- [ ] **Step 2: Run to verify failure**

```bash
cd telemetry_tool && python -m pytest tests/coaching/test_taxonomy.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement causes.json**

Create `telemetry_tool/coaching/taxonomy/causes.json` with ALL 26 causes from spec section 5.2:
- 7 braking causes
- 7 cornering causes
- 5 exit causes
- 4 consistency causes
- 3 vehicle_management causes

Each cause has: `symptom`, `diagnosis`, `root_cause`, `severity_thresholds` (`{mild, moderate, severe}` with numeric thresholds), `unit`.

- [ ] **Step 4: Implement causes.py**

Create `telemetry_tool/coaching/taxonomy/causes.py`:

```python
"""CauseTaxonomy — loads and validates causes.json, provides lookup methods."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, field_validator


class CauseDefinition(BaseModel):
    symptom: str
    diagnosis: str
    root_cause: str
    severity_thresholds: dict[str, float]
    unit: str

    @field_validator("root_cause")
    @classmethod
    def validate_root_cause(cls, v: str) -> str:
        valid = {"technique", "confidence", "line", "balance",
                 "aggression", "fitness", "management", "awareness", "fear"}
        if v not in valid:
            raise ValueError(f"Invalid root_cause: {v}")
        return v

    @field_validator("severity_thresholds")
    @classmethod
    def validate_thresholds(cls, v: dict) -> dict:
        for key in ("mild", "moderate", "severe"):
            if key not in v:
                raise ValueError(f"Missing severity threshold: {key}")
        return v


class CauseTaxonomy:
    def __init__(self, path: str | None = None):
        if path is None:
            path = str(Path(__file__).parent / "causes.json")
        with open(path, "r") as f:
            raw = json.load(f)
        self.categories: dict[str, dict[str, dict]] = {}
        self._cause_to_category: dict[str, str] = {}
        for cat_name, cat_data in raw.get("categories", {}).items():
            causes = {}
            for cause_id, cause_data in cat_data.get("causes", {}).items():
                # Validate via Pydantic — raises ValueError if invalid
                CauseDefinition(**cause_data)
                causes[cause_id] = cause_data
                self._cause_to_category[cause_id] = cat_name
            self.categories[cat_name] = causes

    def get_cause(self, cause_id: str) -> dict | None:
        return next(
            (causes[cause_id] for causes in self.categories.values()
             if cause_id in causes), None)

    def get_category(self, cause_id: str) -> str | None:
        return self._cause_to_category.get(cause_id)

    def get_severity(self, cause_id: str, delta: float) -> str:
        cause = self.get_cause(cause_id)
        if cause is None:
            return "moderate"
        thresholds = cause["severity_thresholds"]
        if abs(delta) >= thresholds["severe"]:
            return "severe"
        if abs(delta) >= thresholds["moderate"]:
            return "moderate"
        return "mild"
```

- [ ] **Step 5: Run tests**

```bash
cd telemetry_tool && python -m pytest tests/coaching/test_taxonomy.py -v
```
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/coaching/taxonomy/
git add telemetry_tool/tests/coaching/test_taxonomy.py
git commit -m "feat(coaching-v3): cause taxonomy with 26 causes, Pydantic validation, severity lookup"
```

---

## Chunk 2: Analyzers (6 physics modules)

### Task 3: Exit speed cascade analyzer

**Files:**
- Create: `telemetry_tool/coaching/analyzers/exit_speed.py`
- Test: `telemetry_tool/tests/coaching/test_exit_speed.py`

- [ ] **Step 1: Write the failing test**

Create `telemetry_tool/tests/coaching/test_exit_speed.py`:

```python
"""Tests for exit speed cascade analyzer."""
import pytest
import numpy as np
import pandas as pd
from telemetry_tool.coaching.analyzers.exit_speed import analyze_exit_cascades
from telemetry_tool.coaching.models import ExitSpeedCascade


def _make_corners():
    """Two corners: C1 at 100-150m (before 200m straight), C3 at 400-430m (before 100m straight)."""
    return [
        {"corner_id": 1, "s_start": 100.0, "s_end": 150.0},
        {"corner_id": 3, "s_start": 400.0, "s_end": 430.0},
    ]


def _make_lap(exit_speeds_mps):
    """Lap DataFrame with distance grid and speed profile."""
    dist = np.arange(0, 600, 1.0)
    speed = np.full_like(dist, 30.0)
    # Set exit speeds at corner ends
    speed[150] = exit_speeds_mps[0]
    speed[430] = exit_speeds_mps[1]
    return pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": speed})


class TestExitSpeedCascade:
    def test_cascade_computed_for_each_corner(self):
        corners = _make_corners()
        driver_lap = _make_lap([20.0, 25.0])
        theo_lap = _make_lap([23.0, 27.0])
        track_length = 600.0
        results = analyze_exit_cascades(corners, driver_lap, theo_lap, track_length)
        assert len(results) == 2
        assert all(isinstance(r, ExitSpeedCascade) for r in results)

    def test_full_integration_formula_used_for_low_speed(self):
        """At kart speeds (v_exit < 10 m/s), full integration must be used."""
        corners = [{"corner_id": 1, "s_start": 50.0, "s_end": 80.0}]
        driver_lap = _make_lap([6.0, 6.0])  # ~22 km/h kart exit
        theo_lap = _make_lap([9.0, 9.0])    # ~32 km/h theoretical
        track_length = 600.0
        results = analyze_exit_cascades(corners, driver_lap, theo_lap, track_length)
        # Full integration: L/v_actual - L/v_theoretical
        # Straight length ~320m (150 to 400, next corner or end)
        r = results[0]
        assert r.time_loss_on_straight_s > 0
        # Must NOT use approximation (which would overestimate by >20%)

    def test_cascade_ratio(self):
        corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 150.0}]
        driver_lap = _make_lap([20.0, 25.0])
        theo_lap = _make_lap([23.0, 27.0])
        results = analyze_exit_cascades(corners, driver_lap, theo_lap, 600.0)
        r = results[0]
        assert r.cascade_ratio == pytest.approx(
            r.time_loss_on_straight_s / max(r.time_loss_in_corner_s, 0.001), rel=0.01)

    def test_returns_empty_when_no_corners(self):
        results = analyze_exit_cascades([], pd.DataFrame(), pd.DataFrame(), 500.0)
        assert results == []

    def test_kmh_conversion(self):
        corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 150.0}]
        driver_lap = _make_lap([20.0, 25.0])
        theo_lap = _make_lap([23.0, 27.0])
        results = analyze_exit_cascades(corners, driver_lap, theo_lap, 600.0)
        r = results[0]
        assert r.exit_gain_needed_kmh == pytest.approx(3.0 * 3.6, rel=0.01)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd telemetry_tool && python -m pytest tests/coaching/test_exit_speed.py -v
```

- [ ] **Step 3: Implement exit_speed.py**

Create `telemetry_tool/coaching/analyzers/exit_speed.py`.

Key implementation:
- `analyze_exit_cascades(corners, driver_lap, theoretical_lap, track_length) -> list[ExitSpeedCascade]`
- For each corner, find the distance to the next corner (or track end) = straight_length
- Read actual and theoretical speed at corner exit point
- Compute straight-end speeds using constant-acceleration model
- Time loss in corner: trapezoidal integration of 1/v_actual - 1/v_theoretical over corner segment
- Time loss on straight: `L / v_actual_exit - L / v_theoretical_exit` (full integration, NOT approximation)
- cascade_ratio = straight_loss / corner_loss

- [ ] **Step 4: Run tests**

```bash
cd telemetry_tool && python -m pytest tests/coaching/test_exit_speed.py -v
```

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/analyzers/exit_speed.py telemetry_tool/tests/coaching/test_exit_speed.py
git commit -m "feat(coaching-v3): exit speed cascade analyzer with full numerical integration"
```

---

### Task 4: Trail brake analyzer

**Files:**
- Create: `telemetry_tool/coaching/analyzers/trail_brake.py`
- Test: `telemetry_tool/tests/coaching/test_trail_brake.py`

- [ ] **Step 1: Write the failing test**

Create `telemetry_tool/tests/coaching/test_trail_brake.py`:

```python
"""Tests for trail brake 4-block analyzer."""
import pytest
import numpy as np
import pandas as pd
from telemetry_tool.coaching.analyzers.trail_brake import analyze_trail_braking
from telemetry_tool.coaching.models import TrailBrakeAssessment, BrakingBlock


def _make_corner_lap(has_trail=True, has_pedal_channels=True):
    """
    Synthetic corner data: distance 100-200m.
    With trail-braking: brake overlaps with steering from 130-150m.
    Without: brake ends at 125m before steering starts at 130m.
    """
    n = 100
    dist = np.linspace(100, 200, n)
    speed = np.linspace(30, 15, n)  # decelerating into corner
    time_s = np.cumsum(np.diff(dist, prepend=dist[0]) / np.maximum(speed, 1))

    if has_pedal_channels:
        throttle = np.zeros(n)
        brake = np.zeros(n)
        steering = np.zeros(n)

        if has_trail:
            # Block 1 (100-105): throttle→brake transition
            throttle[:5] = np.linspace(80, 0, 5)
            # Block 2 (105-130): straight-line braking
            brake[5:30] = np.linspace(90, 70, 25)
            # Block 3 (130-150): trail-brake (brake + steer overlap)
            brake[30:50] = np.linspace(70, 0, 20)
            steering[30:50] = np.linspace(0, 45, 20)
            # Block 4 (150-155): brake→throttle transition
            steering[50:] = np.linspace(45, 30, n - 50)
            throttle[55:] = np.linspace(0, 60, n - 55)
        else:
            # No trail: brake ends before steering starts
            brake[5:25] = 80.0
            steering[30:] = 40.0
            throttle[55:] = 60.0

        return pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": speed, "Time (s)": time_s,
            "Throttle (%)": throttle, "Brake (%)": brake,
            "Steering angle (deg)": steering,
        })
    else:
        # Fallback: accel-only
        lat_accel = np.zeros(n)
        lon_accel = np.zeros(n)
        lon_accel[5:50] = -6.0  # braking
        lat_accel[30:] = 8.0    # cornering
        return pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": speed, "Time (s)": time_s,
            "Lateral acceleration (m/s2)": lat_accel,
            "Longitudinal acceleration (m/s2)": lon_accel,
        })


class TestTrailBrakeAnalyzer:
    def test_detects_four_blocks(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=True)
        result = analyze_trail_braking(corner, lap)
        assert isinstance(result, TrailBrakeAssessment)
        assert len(result.blocks) == 4

    def test_trail_braking_detected(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=True)
        result = analyze_trail_braking(corner, lap)
        assert result.has_trail_braking is True
        assert result.actual_overlap_m > 0

    def test_no_trail_braking_detected(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=False)
        result = analyze_trail_braking(corner, lap)
        assert result.has_trail_braking is False
        assert result.primary_issue == "no_trail_braking"

    def test_accel_fallback_tier(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=True, has_pedal_channels=False)
        result = analyze_trail_braking(corner, lap)
        # Should still detect overlap from accel data
        assert isinstance(result, TrailBrakeAssessment)
        assert result.has_trail_braking is True

    def test_overall_score_range(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_corner_lap(has_trail=True)
        result = analyze_trail_braking(corner, lap)
        assert 0 <= result.overall_score <= 100
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement trail_brake.py**

Key logic:
- Check for `Throttle (%)`, `Brake (%)`, `Steering angle (deg)` columns → Tier 1
- Fallback to `Lateral acceleration`, `Longitudinal acceleration` → Tier 2/3
- Slice lap DataFrame to corner segment (s_start to s_end)
- Walk through distance points, classify each into Block 1-4 based on thresholds
- Compute overlap_m = length of Block 3 segment
- Score: 100 * (actual_overlap / max(theoretical_overlap, 1)) * release_linearity

- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/coaching/analyzers/trail_brake.py telemetry_tool/tests/coaching/test_trail_brake.py
git commit -m "feat(coaching-v3): trail brake 4-block analyzer with accel fallback"
```

---

### Task 5: Traction budget analyzer

**Files:**
- Create: `telemetry_tool/coaching/analyzers/traction_budget.py`
- Test: `telemetry_tool/tests/coaching/test_traction_budget.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for traction budget (friction circle utilization) analyzer."""
import pytest
import numpy as np
import pandas as pd
from telemetry_tool.coaching.analyzers.traction_budget import analyze_traction_budget
from telemetry_tool.coaching.models import TractionBudget


class TestTractionBudget:
    def test_basic_computation(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        lap = pd.DataFrame({
            "Distance (m)": np.linspace(100, 200, 50),
            "Speed (m/s)": np.full(50, 20.0),
            "Lateral acceleration (m/s2)": np.full(50, 6.0),
            "Longitudinal acceleration (m/s2)": np.linspace(-4, 3, 50),
        })
        # Friction model: max lateral = 10 m/s2 at 20 m/s
        friction_max = 10.0
        result = analyze_traction_budget(corner, lap, friction_max)
        assert isinstance(result, TractionBudget)
        assert 0 <= result.apex_total_pct <= 100
        assert result.apex_remaining_pct == pytest.approx(100 - result.apex_total_pct, abs=0.5)

    def test_remaining_is_complement(self):
        corner = {"corner_id": 1, "s_start": 0.0, "s_end": 100.0, "s_apex": 50.0}
        lap = pd.DataFrame({
            "Distance (m)": np.linspace(0, 100, 50),
            "Speed (m/s)": np.full(50, 25.0),
            "Lateral acceleration (m/s2)": np.full(50, 5.0),
            "Longitudinal acceleration (m/s2)": np.full(50, 0.0),
        })
        result = analyze_traction_budget(corner, lap, 10.0)
        for zone in ("entry", "apex", "exit"):
            total = getattr(result, f"{zone}_total_pct")
            remaining = getattr(result, f"{zone}_remaining_pct")
            assert total + remaining == pytest.approx(100.0, abs=1.0)
```

- [ ] **Step 2-4: Run, implement, verify**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): traction budget analyzer (friction circle utilization)"
```

---

### Task 6: Symptom detector

**Files:**
- Create: `telemetry_tool/coaching/analyzers/symptom_detector.py`
- Create: `telemetry_tool/coaching/taxonomy/symptoms.py`
- Test: `telemetry_tool/tests/coaching/test_symptom_detector.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for symptom detector with tier fallback."""
import pytest
import numpy as np
import pandas as pd
from telemetry_tool.coaching.analyzers.symptom_detector import detect_symptoms
from telemetry_tool.coaching.models import SymptomDetection


def _make_early_apex_lap():
    """Lap where steering increases past apex and road unused at exit."""
    n = 100
    dist = np.linspace(100, 200, n)
    speed = np.full(n, 20.0)
    steering = np.zeros(n)
    # Steering increases past apex (index 50)
    steering[30:70] = np.linspace(0, 60, 40)  # keeps increasing past midpoint
    lateral_pos = np.zeros(n)
    lateral_pos[80:] = 1.5  # 1.5m inside at exit = road unused
    return pd.DataFrame({
        "Distance (m)": dist, "Speed (m/s)": speed,
        "Steering angle (deg)": steering,
        "Lateral position (m)": lateral_pos,
    })


class TestSymptomDetector:
    def test_detects_early_apex_tier1(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        lap = _make_early_apex_lap()
        result = detect_symptoms(corner, lap)
        assert isinstance(result, SymptomDetection)
        symptom_ids = [s.symptom_id for s in result.symptoms]
        assert "early_apex" in symptom_ids

    def test_tier2_no_steering_still_detects_via_position(self):
        """Without steering column, detect early apex via exit position."""
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        n = 100
        dist = np.linspace(100, 200, n)
        lap = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": np.full(n, 20.0),
            "Lateral position (m)": np.concatenate([np.zeros(80), np.full(20, 1.5)]),
        })
        result = detect_symptoms(corner, lap)
        symptom_ids = [s.symptom_id for s in result.symptoms]
        assert "early_apex" in symptom_ids

    def test_tier1_symptom_not_emitted_without_tier1_channels(self):
        """understeer_entry requires lat-accel + steering; GPS-only should not emit it."""
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        lap = pd.DataFrame({
            "Distance (m)": np.linspace(100, 200, 50),
            "Speed (m/s)": np.full(50, 20.0),
        })
        result = detect_symptoms(corner, lap)
        symptom_ids = [s.symptom_id for s in result.symptoms]
        assert "understeer_entry" not in symptom_ids

    def test_confidence_between_0_and_1(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "s_apex": 150.0}
        lap = _make_early_apex_lap()
        result = detect_symptoms(corner, lap)
        for s in result.symptoms:
            assert 0 <= s.confidence <= 1
```

- [ ] **Step 2-4: Run, implement, verify**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): symptom detector with 3-tier channel fallback"
```

---

### Task 7: Throttle lift detector

**Files:**
- Create: `telemetry_tool/coaching/analyzers/throttle_lift.py`
- Test: `telemetry_tool/tests/coaching/test_throttle_lift.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for throttle lift detector."""
import pytest
import numpy as np
import pandas as pd
from telemetry_tool.coaching.analyzers.throttle_lift import detect_throttle_lifts
from telemetry_tool.coaching.models import ThrottleLiftEvent


def _make_lift_lap(drop_pct=60, lat_grip_pct=75):
    n = 100
    dist = np.linspace(100, 200, n)
    throttle = np.full(n, 70.0)
    throttle[50:53] = [70, 30, 10]  # abrupt lift at midpoint
    throttle[53:60] = np.linspace(10, 70, 7)  # recover
    lat_accel = np.full(n, lat_grip_pct / 100 * 10)  # as fraction of 10 m/s2 max
    return pd.DataFrame({
        "Distance (m)": dist, "Speed (m/s)": np.full(n, 25.0),
        "Throttle (%)": throttle,
        "Lateral acceleration (m/s2)": lat_accel,
        "Time (s)": np.linspace(0, 4, n),
    })


class TestThrottleLiftDetector:
    def test_detects_dangerous_lift(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_lift_lap(drop_pct=60, lat_grip_pct=75)
        results = detect_throttle_lifts(corner, lap, friction_max=10.0, vehicle_mass_kg=750.0)
        assert len(results) >= 1
        assert results[0].severity == "dangerous"

    def test_benign_lift(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = _make_lift_lap(drop_pct=15, lat_grip_pct=30)
        results = detect_throttle_lifts(corner, lap, friction_max=10.0, vehicle_mass_kg=750.0)
        if results:
            assert results[0].severity == "benign"

    def test_no_throttle_channel_returns_empty(self):
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        lap = pd.DataFrame({
            "Distance (m)": np.linspace(100, 200, 50),
            "Speed (m/s)": np.full(50, 25.0),
        })
        results = detect_throttle_lifts(corner, lap, friction_max=10.0, vehicle_mass_kg=750.0)
        assert results == []
```

- [ ] **Step 2-4: Run, implement, verify**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): throttle lift detector with severity classification"
```

---

### Task 8: Weight transfer analyzer

**Files:**
- Create: `telemetry_tool/coaching/analyzers/weight_transfer.py`
- Test: `telemetry_tool/tests/coaching/test_weight_transfer.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for weight transfer analyzer."""
import pytest
from telemetry_tool.coaching.analyzers.weight_transfer import compute_weight_transfer
from telemetry_tool.coaching.models import WeightTransferInsight


class TestWeightTransfer:
    def test_car_defaults(self):
        result = compute_weight_transfer(
            corner_id=1, braking_decel_mps2=8.0, cornering_accel_mps2=6.0,
            exit_accel_mps2=4.0, vehicle_class="car",
        )
        assert isinstance(result, WeightTransferInsight)
        assert result.entry_front_load_pct > 50  # weight shifts forward under braking
        assert result.exit_rear_load_pct > 50     # weight shifts rearward under accel
        assert "%" in result.insight_text

    def test_kart_defaults(self):
        result = compute_weight_transfer(
            corner_id=1, braking_decel_mps2=6.0, cornering_accel_mps2=8.0,
            exit_accel_mps2=3.0, vehicle_class="kart",
        )
        assert result.entry_front_load_pct > 50

    def test_custom_vehicle_params(self):
        result = compute_weight_transfer(
            corner_id=1, braking_decel_mps2=8.0, cornering_accel_mps2=6.0,
            exit_accel_mps2=4.0, vehicle_class="car",
            wheelbase_m=2.8, cg_height_m=0.5, mass_kg=900.0,
        )
        assert isinstance(result, WeightTransferInsight)
```

- [ ] **Step 2-4: Run, implement, verify**

Key formula: `delta_F_front = (mass * decel * cg_height) / wheelbase`
Front load % = `(50 + delta_F_front / (mass * 9.81) * 100)`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): weight transfer analyzer with vehicle class defaults"
```

---

## Chunk 3: Templates (extensive library)

### Task 9: Corner tip templates

**Files:**
- Create: `telemetry_tool/coaching/templates/corner_tips.py`
- Test: `telemetry_tool/tests/coaching/test_templates.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for template coverage — every cause×severity×vehicle must have a template."""
import pytest
from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy
from telemetry_tool.coaching.templates.corner_tips import CORNER_TIPS


class TestCornerTipCoverage:
    def test_all_combinations_covered(self):
        tax = CauseTaxonomy()
        missing = []
        for cat_name, causes in tax.categories.items():
            for cause_id in causes:
                for severity in ("mild", "moderate", "severe"):
                    for vehicle in ("kart", "car"):
                        key = (cause_id, severity, vehicle)
                        if key not in CORNER_TIPS:
                            missing.append(key)
        assert missing == [], f"Missing templates: {missing}"

    def test_each_template_has_required_keys(self):
        for key, template in CORNER_TIPS.items():
            assert "tip" in template, f"{key} missing 'tip'"
            assert "progressive_steps" in template, f"{key} missing 'progressive_steps'"
            assert "symptom_check" in template, f"{key} missing 'symptom_check'"
            assert len(template["progressive_steps"]) == 3, f"{key} needs 3 progressive steps"

    def test_placeholder_formatting_doesnt_crash(self):
        """Fill a template with dummy values to verify no KeyError."""
        sample_key = list(CORNER_TIPS.keys())[0]
        template = CORNER_TIPS[sample_key]
        dummy = {
            "corner_name": "Turn 3", "delta_m": 10.0, "variance_m": 2.5,
            "step_m": 5.0, "current_m": 200.0, "step1_m": 195.0,
            "step2_m": 190.0, "target_delta_m": 3.0, "time_loss_s": 0.25,
            "exit_speed_loss_kmh": 4.0, "cascade_time_s": 0.18,
            "pct_increase": 12.0, "throttle_drop_pct": 60.0,
            "lift_duration_s": 0.15, "grip_pct": 75.0,
            "weight_shift_kg": 45.0, "yaw_spike": 8.5,
        }
        # Should not raise
        template["tip"].format(**dummy)
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement corner_tips.py**

Create `telemetry_tool/coaching/templates/corner_tips.py` with the full `CORNER_TIPS` dict.

This is the largest file. 26 causes × 3 severities × 2 vehicle classes = 156 entries minimum. Many templates can share structure with vehicle-specific adjustments (kart uses km/h in 20-80 range, car in 60-200 range).

Structure each entry as per spec section 6.1. Use `{placeholder}` format strings.

- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): corner tip template library (156+ templates)"
```

---

### Task 10: Drill library, narratives, and remaining templates

**Files:**
- Create: `telemetry_tool/coaching/templates/drills.py`
- Create: `telemetry_tool/coaching/templates/narratives.py`
- Create: `telemetry_tool/coaching/templates/confidence_frames.py`
- Create: `telemetry_tool/coaching/templates/mental_imagery.py`
- Create: `telemetry_tool/coaching/templates/reference_points.py`
- Create: `telemetry_tool/coaching/templates/progression.py`
- Create: `telemetry_tool/coaching/templates/symptoms.py`

- [ ] **Step 1: Write the failing tests**

Add to `telemetry_tool/tests/coaching/test_templates.py`:

```python
from telemetry_tool.coaching.templates.drills import DRILL_LIBRARY
from telemetry_tool.coaching.templates.narratives import SESSION_NARRATIVES
from telemetry_tool.coaching.templates.confidence_frames import CONFIDENCE_FRAMES
from telemetry_tool.coaching.templates.mental_imagery import MENTAL_IMAGERY


class TestDrillLibrary:
    def test_at_least_20_drill_types(self):
        assert len(DRILL_LIBRARY) >= 20

    def test_each_drill_has_three_difficulty_levels(self):
        for drill_id, drill in DRILL_LIBRARY.items():
            assert "title" in drill
            assert "difficulty_levels" in drill
            levels = drill["difficulty_levels"]
            for level in ("beginner", "intermediate", "advanced"):
                assert level in levels, f"{drill_id} missing {level}"
                assert "description" in levels[level]
                assert "success_criteria" in levels[level]
                assert "lap_count" in levels[level]

    def test_each_drill_has_applicable_causes(self):
        for drill_id, drill in DRILL_LIBRARY.items():
            assert "applicable_causes" in drill
            assert len(drill["applicable_causes"]) >= 1


class TestSessionNarratives:
    def test_coverage(self):
        """At least one narrative per grade band."""
        grade_bands = set()
        for key in SESSION_NARRATIVES:
            grade_bands.add(key[0])
        assert "S-A" in grade_bands
        assert "B-C" in grade_bands
        assert "D-F" in grade_bands

    def test_each_is_list_of_variants(self):
        for key, variants in SESSION_NARRATIVES.items():
            assert isinstance(variants, list)
            assert len(variants) >= 1


class TestMentalImagery:
    def test_has_entries(self):
        assert len(MENTAL_IMAGERY) >= 5

    def test_each_has_pre_session(self):
        for key, entry in MENTAL_IMAGERY.items():
            assert "pre_session" in entry
            assert len(entry["pre_session"]) > 50  # substantive text
```

- [ ] **Step 2-4: Implement all template files, run tests**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): drill library (20 types), narratives, mental imagery, confidence frames, reference points"
```

---

## Chunk 4: Composers (assembly logic)

### Task 11: Focus limiter

**Files:**
- Create: `telemetry_tool/coaching/composers/focus_limiter.py`
- Test: `telemetry_tool/tests/coaching/test_focus_limiter.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for focus limiter — max 2 focus areas per session."""
import pytest
from telemetry_tool.coaching.composers.focus_limiter import limit_focus_areas
from telemetry_tool.coaching.models import FocusArea


def _fa(rank, category, time_loss):
    return FocusArea(
        rank=rank, category=category, time_loss_s=time_loss,
        corner_ids=[rank], summary=f"{category} issue", advice="Fix it",
    )


class TestFocusLimiter:
    def test_max_two_returned(self):
        areas = [_fa(1, "braking", 0.5), _fa(2, "cornering", 0.4),
                 _fa(3, "exit", 0.3), _fa(4, "consistency", 0.1)]
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) <= 2
        assert len(deferred) == len(areas) - len(primary)

    def test_second_area_needs_30pct_of_first(self):
        areas = [_fa(1, "braking", 1.0), _fa(2, "cornering", 0.2)]  # 0.2 < 0.3*1.0
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) == 1  # second not significant enough

    def test_second_area_qualifies(self):
        areas = [_fa(1, "braking", 1.0), _fa(2, "cornering", 0.5)]  # 0.5 >= 0.3
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) == 2

    def test_merge_same_root_cause(self):
        areas = [_fa(1, "braking", 0.5), _fa(2, "braking", 0.4)]
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) == 1  # merged

    def test_single_area(self):
        areas = [_fa(1, "braking", 0.5)]
        primary, deferred = limit_focus_areas(areas)
        assert len(primary) == 1
        assert len(deferred) == 0

    def test_empty_input(self):
        primary, deferred = limit_focus_areas([])
        assert primary == []
        assert deferred == []
```

- [ ] **Step 2-4: Run, implement, verify**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): focus limiter — max 2 areas per session with merge logic"
```

---

### Task 12: Progressive coach + confidence framer

**Files:**
- Create: `telemetry_tool/coaching/composers/progressive_coach.py`
- Create: `telemetry_tool/coaching/composers/confidence_framer.py`
- Test: `telemetry_tool/tests/coaching/test_progressive_coach.py`
- Test: `telemetry_tool/tests/coaching/test_confidence_framer.py`

- [ ] **Step 1: Write the failing tests**

`test_progressive_coach.py`:
```python
"""Tests for progressive coach — goals, warm-up, late apex reset."""
import pytest
from telemetry_tool.coaching.composers.progressive_coach import (
    generate_progressive_goals, check_late_apex_reset, WarmUpProtocol,
)
from telemetry_tool.coaching.models import CornerCoachingDetail


def _corner_detail(corner_id, cause="early_braking_confidence", **kw):
    defaults = dict(
        corner_id=corner_id, corner_name=f"Turn {corner_id}",
        primary_cause=cause, cause_severity="moderate", cause_root="technique",
        symptom_evidence=[], diagnosis_text="test",
        coaching_tip="test tip", progressive_steps=["s1", "s2", "s3"],
        symptom_check="check",
        time_loss_corner_s=0.2, time_loss_cascade_s=0.35,
        exit_speed_target_kmh=80.0, apex_speed_target_kmh=65.0,
        entry_speed_target_kmh=90.0, braking_point_target_description="at 100m board",
        traction_budget=None, trail_brake=None, exit_cascade=None,
        weight_transfer_insight=None, trend=None,
    )
    defaults.update(kw)
    return CornerCoachingDetail(**defaults)


class TestProgressiveGoals:
    def test_generates_three_goals(self):
        corners = [_corner_detail(1), _corner_detail(3)]
        goals, warmup = generate_progressive_goals(corners, previous_goals=None, scores={"grade": "B"})
        assert len(goals) == 3
        assert isinstance(warmup, WarmUpProtocol)

    def test_warmup_has_three_phases(self):
        corners = [_corner_detail(1)]
        _, warmup = generate_progressive_goals(corners, None, {"grade": "C"})
        assert warmup.phase_1_laps > 0
        assert warmup.phase_2_laps > 0
        assert len(warmup.phase_3_instruction) > 0


class TestLateApexReset:
    def test_triggered_when_majority_early_apex(self):
        corners = [_corner_detail(i, cause="early_apex") for i in range(1, 8)]
        result = check_late_apex_reset(corners)
        assert result is not None
        assert "late" in result.lower() or "reset" in result.lower()

    def test_not_triggered_when_minority(self):
        corners = [_corner_detail(1, cause="early_apex"),
                    _corner_detail(2, cause="late_throttle_application"),
                    _corner_detail(3, cause="no_trail_braking")]
        result = check_late_apex_reset(corners)
        assert result is None
```

`test_confidence_framer.py`:
```python
"""Tests for confidence framer."""
from telemetry_tool.coaching.composers.confidence_framer import frame_strengths


class TestConfidenceFramer:
    def test_transforms_strengths(self):
        raw_strengths = ["pace", "execution"]
        corners = []  # simplified
        scores = {"sub_scores": {"pace": {"pct": 0.9}, "execution": {"pct": 0.85}}}
        framed = frame_strengths(raw_strengths, corners, scores)
        assert len(framed) == len(raw_strengths)
        for s in framed:
            assert len(s) > 20  # substantive text, not just the category name
```

- [ ] **Step 2-4: Run, implement, verify**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): progressive coach (goals, warm-up, late apex reset) + confidence framer"
```

---

### Task 13: Corner composer + session composer

**Files:**
- Create: `telemetry_tool/coaching/composers/corner_composer.py`
- Create: `telemetry_tool/coaching/composers/session_composer.py`
- Test: `telemetry_tool/tests/coaching/test_corner_composer.py`
- Test: `telemetry_tool/tests/coaching/test_session_composer.py`

- [ ] **Step 1: Write the failing tests**

`test_corner_composer.py`:
```python
"""Tests for corner composer — builds CornerCoachingDetail from analyzer outputs."""
import pytest
from telemetry_tool.coaching.composers.corner_composer import compose_corner_coaching
from telemetry_tool.coaching.models import (
    CornerCoachingDetail, TrailBrakeAssessment, ExitSpeedCascade,
    TractionBudget, SymptomDetection, Symptom, BrakingBlock,
)
from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy


class TestCornerComposer:
    def test_produces_corner_coaching_detail(self):
        corner_perf = {
            "corner_id": 3, "s_start": 100.0, "s_end": 200.0,
            "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
            "theoretical_apex_speed_mps": 18.0, "actual_apex_speed_mps": 16.0,
            "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
            "braking_point_delta_m": 12.0,
            "time_loss_s": 0.35, "time_loss_braking_s": 0.15,
            "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
            "grip_utilisation_pct": 68.0,
        }
        taxonomy = CauseTaxonomy()
        result = compose_corner_coaching(
            corner_perf=corner_perf,
            trail_brake=None, traction=None, exit_cascade=None,
            symptoms=None, throttle_lifts=[], weight_transfer=None,
            taxonomy=taxonomy, vehicle_class="car", driver_history=None,
        )
        assert isinstance(result, CornerCoachingDetail)
        assert result.corner_id == 3
        assert result.primary_cause is not None
        assert len(result.coaching_tip) > 10
        assert len(result.progressive_steps) == 3

    def test_symptom_overrides_metric_cause(self):
        """When symptom says early_apex but metrics say low_apex_speed, use symptom."""
        corner_perf = {
            "corner_id": 1, "s_start": 0.0, "s_end": 100.0,
            "theoretical_apex_speed_mps": 20.0, "actual_apex_speed_mps": 16.0,
            "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
            "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
            "braking_point_delta_m": 3.0,
            "time_loss_s": 0.3, "time_loss_braking_s": 0.05,
            "time_loss_apex_speed_s": 0.2, "time_loss_exit_s": 0.05,
            "grip_utilisation_pct": 65.0,
        }
        symptoms = SymptomDetection(
            corner_id=1,
            symptoms=[Symptom("early_apex", "Steering increases past apex",
                              {"steering_increase_deg": 12.0}, 0.9)]
        )
        taxonomy = CauseTaxonomy()
        result = compose_corner_coaching(
            corner_perf=corner_perf, trail_brake=None, traction=None,
            exit_cascade=None, symptoms=symptoms, throttle_lifts=[],
            weight_transfer=None, taxonomy=taxonomy,
            vehicle_class="car", driver_history=None,
        )
        assert result.primary_cause == "early_apex"  # symptom wins

    def test_speed_targets_none_without_theoretical(self):
        corner_perf = {
            "corner_id": 1, "s_start": 0.0, "s_end": 100.0,
            "theoretical_apex_speed_mps": None,
            "theoretical_entry_speed_mps": None,
            "theoretical_exit_speed_mps": None,
            "actual_entry_speed_mps": 22.0,
            "actual_apex_speed_mps": 16.0,
            "actual_exit_speed_mps": 20.0,
            "braking_point_delta_m": 0.0,
            "time_loss_s": 0.0, "time_loss_braking_s": 0.0,
            "time_loss_apex_speed_s": 0.0, "time_loss_exit_s": 0.0,
            "grip_utilisation_pct": 50.0,
        }
        taxonomy = CauseTaxonomy()
        result = compose_corner_coaching(
            corner_perf=corner_perf, trail_brake=None, traction=None,
            exit_cascade=None, symptoms=None, throttle_lifts=[],
            weight_transfer=None, taxonomy=taxonomy,
            vehicle_class="car", driver_history=None,
        )
        assert result.apex_speed_target_kmh is None
```

`test_session_composer.py`:
```python
"""Tests for session composer — full assembly."""
import pytest
from telemetry_tool.coaching.composers.session_composer import compose_session_coaching
from telemetry_tool.coaching.models import SessionCoaching
from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy


class TestSessionComposer:
    def test_produces_session_coaching(self):
        corner_perfs = [
            {"corner_id": i, "s_start": i*100, "s_end": i*100+50,
             "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
             "theoretical_apex_speed_mps": 18.0, "actual_apex_speed_mps": 16.0,
             "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
             "braking_point_delta_m": 10.0,
             "time_loss_s": 0.3, "time_loss_braking_s": 0.1,
             "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
             "grip_utilisation_pct": 65.0}
            for i in range(1, 6)
        ]
        scores = {"total_score": 72, "grade": "B", "strengths": ["pace"],
                  "weaknesses": ["consistency"],
                  "sub_scores": {"pace": {"pct": 0.8}}}
        taxonomy = CauseTaxonomy()
        result = compose_session_coaching(
            corner_perfs=corner_perfs, coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_results={},
            taxonomy=taxonomy, vehicle_class="car",
            driver_history=None, previous_goals=None,
        )
        assert isinstance(result, SessionCoaching)
        assert len(result.focus_areas) <= 2
        assert len(result.drills) >= 1
        assert len(result.next_session_goals) == 3
        assert result.vehicle_class == "car"

    def test_backward_compat_fields_present(self):
        corner_perfs = [
            {"corner_id": 1, "s_start": 0, "s_end": 100,
             "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
             "theoretical_apex_speed_mps": 18.0, "actual_apex_speed_mps": 16.0,
             "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
             "braking_point_delta_m": 10.0,
             "time_loss_s": 0.3, "time_loss_braking_s": 0.1,
             "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
             "grip_utilisation_pct": 65.0}
        ]
        taxonomy = CauseTaxonomy()
        result = compose_session_coaching(
            corner_perfs=corner_perfs, coaching_v2=None,
            scores={"total_score": 50, "grade": "D", "strengths": [], "weaknesses": [],
                    "sub_scores": {}},
            lap_metrics=None, driving_style=None,
            analyzer_results={}, taxonomy=taxonomy,
            vehicle_class="car", driver_history=None, previous_goals=None,
        )
        d = result.to_dict()
        # All original fields must be present
        for key in ("session_theme", "narrative", "strengths", "weaknesses",
                     "focus_areas", "drills", "progression", "next_session_goals", "confidence"):
            assert key in d
```

- [ ] **Step 2-4: Run, implement, verify**

Corner composer implementation notes:
- Resolve cause: symptoms (if present, highest confidence) → braking_point_delta + speed deltas → fallback to largest time_loss phase
- Look up template from CORNER_TIPS[(cause, severity, vehicle_class)]
- Fill placeholders with corner_perf metrics
- Speed targets: theoretical × 3.6 to km/h, or None

Session composer implementation notes:
- Run corner_composer for each corner
- Rank by cascade_time_loss (not just corner time_loss)
- Build focus areas from top causes
- focus_limiter → max 2
- Select drills matching focus area causes
- confidence_framer → rewrite strengths
- progressive_coach → 3 goals + warm-up
- late_apex_reset check
- narrative from SESSION_NARRATIVES
- mental imagery from MENTAL_IMAGERY

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): corner composer + session composer — full coaching assembly"
```

---

## Chunk 5: Pipeline integration + persistence + API

### Task 14: Persistence layer + Alembic migration

**Files:**
- Create: `telemetry_tool/coaching/persistence/models.py`
- Create: `telemetry_tool/coaching/persistence/queries.py`
- Create: `telemetry_tool/alembic/versions/040_corner_progression.py`
- Test: `telemetry_tool/tests/coaching/test_persistence.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for corner progression persistence."""
import pytest
from telemetry_tool.coaching.persistence.queries import (
    store_corner_progression, get_corner_history,
)


class TestCornerProgression:
    def test_store_and_retrieve(self, test_db):
        """Store corner metrics, retrieve history."""
        store_corner_progression(
            conn=test_db, workspace_id="test-ws",
            driver_id=1, track_id=1, session_id=100, session_date="2026-03-11",
            corners=[
                {"corner_id": 3, "apex_speed_mps": 16.0, "entry_speed_mps": 22.0,
                 "exit_speed_mps": 20.0, "braking_point_m": 185.0,
                 "time_loss_s": 0.3, "grip_utilisation_pct": 68.0,
                 "trail_brake_score": 62.0, "primary_cause": "early_braking_confidence",
                 "theoretical_apex_mps": 18.0, "theoretical_entry_mps": 25.0,
                 "theoretical_exit_mps": 23.0},
            ],
        )
        history = get_corner_history(test_db, driver_id=1, track_id=1, corner_id=3)
        assert len(history) == 1
        assert history[0]["apex_speed_mps"] == pytest.approx(16.0)

    def test_minimum_sessions_for_trend(self, test_db):
        """Need 3+ sessions for trend to be non-None."""
        for session_id in range(1, 3):
            store_corner_progression(
                conn=test_db, workspace_id="test-ws",
                driver_id=1, track_id=1, session_id=session_id,
                session_date=f"2026-03-0{session_id}",
                corners=[{"corner_id": 3, "apex_speed_mps": 16.0 + session_id,
                           "entry_speed_mps": 22.0, "exit_speed_mps": 20.0,
                           "braking_point_m": 185.0, "time_loss_s": 0.3,
                           "grip_utilisation_pct": 68.0, "trail_brake_score": 62.0,
                           "primary_cause": "early_braking_confidence",
                           "theoretical_apex_mps": 18.0, "theoretical_entry_mps": 25.0,
                           "theoretical_exit_mps": 23.0}],
            )
        history = get_corner_history(test_db, driver_id=1, track_id=1, corner_id=3)
        assert len(history) == 2  # only 2 sessions, trend would be None
```

- [ ] **Step 2: Create migration file**

`telemetry_tool/alembic/versions/040_corner_progression.py`:
Use the exact SQL from spec section 4.9, including RLS WITH CHECK clause.
Set `down_revision` to match the actual 039 revision ID (check `039_fix_score_check_constraints.py`).

- [ ] **Step 3: Implement persistence queries**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coaching-v3): corner_progression table (migration 040) + persistence queries"
```

---

### Task 15: Pipeline stages S13e–S13g2

**Files:**
- Create: `telemetry_tool/pipeline/stages/s13_coaching_v3.py`
- Modify: `telemetry_tool/pipeline/orchestrator.py:1098-1104`
- Test: `telemetry_tool/tests/coaching/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for coaching V3 pipeline stages."""
import pytest
from telemetry_tool.pipeline.stages.s13_coaching_v3 import (
    run_coaching_analyzers, run_multi_session_lookup, run_enhanced_coaching,
    persist_coaching_v3,
)


class TestRunCoachingAnalyzers:
    def test_returns_analyzer_bundle(self):
        """With minimal valid data, returns dict with analyzer keys."""
        corner_perfs = [{"corner_id": 1, "s_start": 0, "s_end": 100,
                         "theoretical_entry_speed_mps": 25.0,
                         "actual_entry_speed_mps": 22.0,
                         "theoretical_apex_speed_mps": 18.0,
                         "actual_apex_speed_mps": 16.0,
                         "theoretical_exit_speed_mps": 23.0,
                         "actual_exit_speed_mps": 20.0,
                         "braking_point_delta_m": 10.0,
                         "time_loss_s": 0.3}]
        result = run_coaching_analyzers(
            corner_perfs=corner_perfs, best_lap_df=None,
            theoretical_result=None, friction_model=None,
            resampled_laps={}, available_columns=set(),
        )
        assert isinstance(result, dict)
        # Each analyzer key present (value may be None if data insufficient)
        for key in ("trail_brakes", "exit_cascades", "traction_budgets",
                     "symptoms", "throttle_lifts", "weight_transfers"):
            assert key in result


class TestRunEnhancedCoaching:
    def test_returns_session_coaching_dict(self):
        corner_perfs = [{"corner_id": 1, "s_start": 0, "s_end": 100,
                         "theoretical_entry_speed_mps": 25.0,
                         "actual_entry_speed_mps": 22.0,
                         "theoretical_apex_speed_mps": 18.0,
                         "actual_apex_speed_mps": 16.0,
                         "theoretical_exit_speed_mps": 23.0,
                         "actual_exit_speed_mps": 20.0,
                         "braking_point_delta_m": 10.0,
                         "time_loss_s": 0.3, "time_loss_braking_s": 0.1,
                         "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
                         "grip_utilisation_pct": 65.0}]
        scores = {"total_score": 65, "grade": "C", "strengths": [], "weaknesses": [],
                  "sub_scores": {}}
        result = run_enhanced_coaching(
            corner_perfs=corner_perfs, coaching_v2=None, scores=scores,
            lap_metrics=None, driving_style=None,
            analyzer_bundle={}, driver_history=None,
            vehicle_class="car", previous_goals=None,
        )
        assert isinstance(result, dict)
        assert "session_theme" in result
        assert "corner_coaching" in result
```

- [ ] **Step 2: Implement s13_coaching_v3.py**

Contains 4 functions:
- `run_coaching_analyzers()`: Runs all 6 analyzers, each in try/except. Returns dict of results.
- `run_multi_session_lookup()`: Queries corner_progression. Returns None if USE_PG=0 or driver_id is None.
- `run_enhanced_coaching()`: Calls session_composer. Falls back to old coaching_engine on exception.
- `persist_coaching_v3()`: Writes to analysis_json["coaching_v3"] and corner_progression table.

- [ ] **Step 3: Wire into orchestrator**

Modify `telemetry_tool/pipeline/orchestrator.py` after the S13d (practice_plan) stage call (~line 1098):

```python
# ── Coaching V3 ──
if os.environ.get("COACHING_V3", "1") != "0":
    from telemetry_tool.pipeline.stages import s13_coaching_v3
    _analyzer_bundle = self._safe_step(
        "S13e_analyzers", s13_coaching_v3.run_coaching_analyzers,
        corner_perfs=_corner_performances,
        best_lap_df=_best_lap_df,
        theoretical_result=_theoretical_result,
        friction_model=_friction_model,
        resampled_laps=_resampled_laps,
        available_columns=_available_columns,
    )
    summary["driver_id"] = _drv_id  # Ensure available for S13f
    _driver_history = self._safe_step(
        "S13f_multi_session", s13_coaching_v3.run_multi_session_lookup,
        driver_id=summary.get("driver_id"),
        track_id=summary.get("track_id"),
        corner_ids=[c["corner_id"] for c in (_corner_performances or [])],
    )
    _coaching_v3 = self._safe_step(
        "S13g_coaching_v3", s13_coaching_v3.run_enhanced_coaching,
        corner_perfs=_corner_performances,
        coaching_v2=_coaching_v2,
        scores=_score_result,
        lap_metrics=_lap_metrics_list,
        driving_style=_driving_style,
        analyzer_bundle=_analyzer_bundle,
        driver_history=_driver_history,
        vehicle_class=meta.get("vehicle_class", "car"),
        previous_goals=None,
    )
    self._safe_step(
        "S13g2_persist_coaching", s13_coaching_v3.persist_coaching_v3,
        coaching_dict=_coaching_v3,
        analysis_json=_analysis_json,
        conn=getattr(self, '_conn', None),
        session_id=meta.get("session_id"),
        driver_id=summary.get("driver_id"),
        track_id=summary.get("track_id"),
        corner_coaching=(_coaching_v3 or {}).get("corner_coaching"),
    )
```

- [ ] **Step 4: Run tests**

```bash
cd telemetry_tool && python -m pytest tests/coaching/test_pipeline_integration.py -v
```

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/pipeline/stages/s13_coaching_v3.py
git add telemetry_tool/pipeline/orchestrator.py
git add telemetry_tool/tests/coaching/test_pipeline_integration.py
git commit -m "feat(coaching-v3): pipeline stages S13e-S13g2 + orchestrator wiring"
```

---

### Task 16: API endpoint update

**Files:**
- Modify: `telemetry_tool/web/routes/data_v2.py:4579-4626`

- [ ] **Step 1: Modify get_coaching endpoint**

In `data_v2.py`, update the `get_coaching()` function (~line 4579):

```python
@data_v2_bp.route("/sessions/<session_id>/coaching", methods=["GET"])
def get_coaching(session_id: str):
    conn = _get_conn()
    try:
        # V3: Check for pre-computed coaching in analysis_json
        analysis = models.get_analysis_json(conn, session_id)
        if analysis and "coaching_v3" in analysis:
            return api_response(analysis["coaching_v3"])

        # Fallback: generate coaching at request time (old engine)
        # ... existing code unchanged ...
    except Exception as e:
        return api_error(str(e), 500)
```

- [ ] **Step 2: Test manually**

```bash
# Start dev server
python telemetry_tool/main.py --serve
# curl the endpoint for a session
curl http://localhost:5000/api/v1/sessions/1/coaching | python -m json.tool
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/web/routes/data_v2.py
git commit -m "feat(coaching-v3): GET /coaching endpoint reads coaching_v3 from analysis_json"
```

---

### Task 17: Public API + __init__.py

**Files:**
- Modify: `telemetry_tool/coaching/__init__.py`

- [ ] **Step 1: Wire up public API**

```python
"""Coaching Engine V3 — config-driven, physics-informed coaching."""
from telemetry_tool.coaching.composers.session_composer import compose_session_coaching
from telemetry_tool.coaching.models import SessionCoaching

__all__ = ["compose_session_coaching", "SessionCoaching"]
```

- [ ] **Step 2: Run full test suite**

```bash
cd telemetry_tool && python -m pytest tests/coaching/ -v
```
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/coaching/__init__.py
git commit -m "feat(coaching-v3): public API in coaching.__init__"
```

---

## Chunk 6: Frontend components

### Task 18: CoachingPanel + SessionTheme + FocusAreaCard

**Files:**
- Create: `lap-website/src/components/app/coaching/CoachingPanel.tsx`
- Create: `lap-website/src/components/app/coaching/SessionTheme.tsx`
- Create: `lap-website/src/components/app/coaching/FocusAreaCard.tsx`

- [ ] **Step 1: Create CoachingPanel**

Main container that fetches `/api/v1/sessions/{id}/coaching` via `apiFetch()` and renders sub-components. Uses React Query for data fetching. Handles both V3 (with `corner_coaching`) and fallback (without) responses.

- [ ] **Step 2: Create SessionTheme**

Renders grade badge (color-coded S/A/B/C/D/F), session theme headline, and narrative paragraph.

- [ ] **Step 3: Create FocusAreaCard**

Renders a single focus area with:
- Category icon + time loss badge
- Affected corner IDs
- Summary text
- Collapsible accordion for `progressive_steps` (3 steps) — hidden if field absent
- `symptom_diagnosis` badge — hidden if field absent

- [ ] **Step 4: Run frontend build**

```bash
cd lap-website && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add lap-website/src/components/app/coaching/
git commit -m "feat(coaching-v3): CoachingPanel, SessionTheme, FocusAreaCard frontend components"
```

---

### Task 19: DrillCard + NextSessionGoals + StrengthsList + DeferredAreas

**Files:**
- Create: `lap-website/src/components/app/coaching/DrillCard.tsx`
- Create: `lap-website/src/components/app/coaching/NextSessionGoals.tsx`
- Create: `lap-website/src/components/app/coaching/StrengthsList.tsx`
- Create: `lap-website/src/components/app/coaching/DeferredAreas.tsx`

- [ ] **Step 1: Create DrillCard**

Tab interface: Beginner / Intermediate / Advanced. Each tab shows description, success criteria, lap count. Uses `difficulty_progression` if present, falls back to flat `description`.

- [ ] **Step 2: Create NextSessionGoals, StrengthsList, DeferredAreas**

- NextSessionGoals: Checkbox list of 3 goals. If `previous_goals` context exists, show "Last session: ..." reference.
- StrengthsList: Renders confidence-framed strength strings.
- DeferredAreas: Collapsed "For later" section showing remaining focus areas beyond top 2.

- [ ] **Step 3: Build + commit**

```bash
cd lap-website && npm run build
git commit -m "feat(coaching-v3): DrillCard, NextSessionGoals, StrengthsList, DeferredAreas"
```

---

### Task 20: CornerCoachingCard + sub-components

**Files:**
- Create: `lap-website/src/components/app/coaching/CornerCoachingCard.tsx`
- Create: `lap-website/src/components/app/coaching/SpeedTargets.tsx`
- Create: `lap-website/src/components/app/coaching/TractionBudgetViz.tsx`
- Create: `lap-website/src/components/app/coaching/TrailBrakeTimeline.tsx`
- Create: `lap-website/src/components/app/coaching/ExitCascadeViz.tsx`
- Create: `lap-website/src/components/app/coaching/CornerTrendChart.tsx`

- [ ] **Step 1: Create CornerCoachingCard**

Progressive disclosure: collapsed shows corner name + cause + time loss. Expanded shows all sub-components.

- [ ] **Step 2: Create SpeedTargets**

Horizontal bar chart: 3 rows (Entry, Apex, Exit). Each row: actual speed bar (blue) vs target speed bar (green outline). Gap highlighted in red. Renders nothing if targets are null.

- [ ] **Step 3: Create TractionBudgetViz**

Small SVG friction circle (~80px). Filled arc = used grip %. Remaining arc = green = "unused grip." Labels: "{total}% used / {remaining}% available."

- [ ] **Step 4: Create TrailBrakeTimeline**

Horizontal bar divided into 4 colored blocks:
- Block 1 (yellow): throttle→brake
- Block 2 (red): straight-line brake
- Block 3 (orange, key): trail brake overlap
- Block 4 (green): brake→throttle
Labels show overlap distance and score.

- [ ] **Step 5: Create ExitCascadeViz**

Arrow diagram: `[Corner: -0.18s] → [Straight: -0.16s] = [-0.34s total]`
Shows exit speed gain needed and straight-end speed gain.

- [ ] **Step 6: Create CornerTrendChart**

Mini sparkline (Recharts or plain SVG). X = session index, Y = apex speed. Dotted line = theoretical target. Only renders when `trend.sessions_tracked >= 3`.

- [ ] **Step 7: Build + commit**

```bash
cd lap-website && npm run build
git commit -m "feat(coaching-v3): CornerCoachingCard + SpeedTargets, TractionBudgetViz, TrailBrakeTimeline, ExitCascadeViz, CornerTrendChart"
```

---

### Task 21: WarmUpProtocol + MentalImageryPrompt

**Files:**
- Create: `lap-website/src/components/app/coaching/WarmUpProtocol.tsx`
- Create: `lap-website/src/components/app/coaching/MentalImageryPrompt.tsx`

- [ ] **Step 1: Create WarmUpProtocol**

Card with 3 phase rows:
- Phase 1: "{laps} sighting laps" + instruction
- Phase 2: "{laps} build laps" + instruction
- Phase 3: "Push" + instruction
Only renders when `warm_up_protocol` is non-null.

- [ ] **Step 2: Create MentalImageryPrompt**

Italic card with visualization prompts. Only renders when `mental_imagery_prompts` is non-null and non-empty.

- [ ] **Step 3: Build + commit**

```bash
cd lap-website && npm run build
git commit -m "feat(coaching-v3): WarmUpProtocol + MentalImageryPrompt components"
```

---

## Chunk 7: Integration testing + final verification

### Task 22: Full integration test

**Files:**
- Test: `telemetry_tool/tests/coaching/test_pipeline_integration.py` (extend)

- [ ] **Step 1: Write end-to-end test**

```python
class TestFullPipelineIntegration:
    def test_coaching_v3_in_pipeline_summary(self, seeded_db):
        """Run full pipeline on a seeded session, verify coaching_v3 in summary."""
        from telemetry_tool.pipeline.orchestrator import PipelineOrchestrator
        orch = PipelineOrchestrator(db=seeded_db)
        summary = orch.run_full_analysis(
            csv_path="data/raw/test_session.csv",
            meta={"vehicle_class": "car"},
        )
        # coaching_v3 should be in analysis_json
        assert "coaching_v3" in (summary.get("analysis_json") or {})
        coaching = summary["analysis_json"]["coaching_v3"]
        assert "session_theme" in coaching
        assert "corner_coaching" in coaching
        assert coaching.get("vehicle_class") == "car"
        # Max 2 focus areas
        assert len(coaching.get("focus_areas", [])) <= 2
```

- [ ] **Step 2: Run all coaching tests**

```bash
cd telemetry_tool && python -m pytest tests/coaching/ -v --tb=short
```

- [ ] **Step 3: Run full test suite (regression)**

```bash
cd telemetry_tool && python -m pytest tests/ -v --tb=short -x
```

- [ ] **Step 4: Commit**

```bash
git commit -m "test(coaching-v3): full integration test — pipeline produces coaching_v3"
```

---

### Task 23: Frontend build verification

- [ ] **Step 1: Run frontend lint + type check**

```bash
cd lap-website && npm run lint && npx tsc --noEmit
```

- [ ] **Step 2: Run frontend build**

```bash
cd lap-website && npm run build
```

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(coaching-v3): complete implementation — backend, frontend, migration, tests"
```

---

## Summary

| Chunk | Tasks | What it builds |
|-------|-------|---------------|
| 1 | 1-2 | Package skeleton, models, taxonomy |
| 2 | 3-8 | 6 physics analyzers |
| 3 | 9-10 | Template library (300+ templates) |
| 4 | 11-13 | Composers (focus limiter, progressive coach, corner+session composers) |
| 5 | 14-17 | Persistence, migration, pipeline stages, API endpoint |
| 6 | 18-21 | Frontend components (15 files) |
| 7 | 22-23 | Integration testing + verification |

**Total: 23 tasks, ~45 new files, 3 modified files, 1 migration.**

Each chunk produces working, testable software. Chunks 1-5 are sequential (each depends on prior). Chunk 6 (frontend) can run in parallel with Chunk 5 once Chunk 4 is done (API shape is defined). Chunk 7 is final verification.
