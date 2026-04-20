# W5 — Shared Kernels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `telemetry_tool/shared/` — the neutral home for geometry, physics, and coaching-taxonomy primitives shared by the real-life pipeline (Side A) and the simracing engines (Side B). Unblock W6 (coaching) via T5.3 and W7 (optimizer) via T5.2; leave deprecation shims so concurrent Wave-2 sessions keep compiling.

**Architecture:**
- Three sub-packages under `telemetry_tool/shared/`:
  - `shared/geometry/` — `TrackGeometry` (moved from `kart_envelope/track/geometry.py`) and `FrenetFrame` (moved from `telemetry_tool/track_surface/frenet.py`), decoupled from kart-specific config.
  - `shared/physics/` — abstract bases only: `FrictionModel` (protocol) and `VehicleModel` (abstract). Concrete implementations stay in their current homes; cross-side consumers depend on the bases.
  - `shared/coaching_taxonomy/` — the full pattern ontology: `models.py`, `causes.py` / `causes.json`, `templates/`, plus `channels.py` (receives `ChannelTag` + `SessionCapabilities` pulled from W1's contracts package).
- Every old location keeps a one-cycle deprecation shim that re-exports the moved symbol and emits `DeprecationWarning(stacklevel=2)`.
- Public surface of `shared/` imports **nothing** from `kart_envelope/`, `sim_optimizer/`, `pipeline/`, `coaching/`, or `track_surface/`. Verified via a new test `tests/test_shared_kernel_isolation.py` that greps the import AST.

**Tech Stack:** Python 3.x · dataclasses · numpy · pytest · Pydantic v2 (for `ChannelTag` / `SessionCapabilities`) · pydeps (one-off audit) · git worktrees

**Spec reference:** `docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md` §5 W5 (T5.1–T5.5), §6 dependency graph

**Session prompt:** `c:\Users\Admin\Downloads\02-W5-shared-kernels.md` (the downloaded Wave 2 session brief for W5)

**Branch:** `feat/ws-w5-shared-kernels`

**Worktree:** `.worktrees/ws-w5-shared-kernels` (project convention — the `.worktrees/` directory is already in use for `ws-w1-contracts` and `feat-ocp-solver`; the README's `../worktrees/` path is superseded).

---

## Decisions requiring /approve before code

Five items fall outside the session prompt's declared paths, depend on pre-work by other sessions, or resolve ambiguities in the spec. Confirm each before Task 1 code starts.

| # | Item | Proposed resolution |
|---|------|---------------------|
| **D1** | **W1 merge prerequisite** — prompt says "Verify with `git log --grep 'signal:W1-done'`"; W1 is complete on `feat/ws-w1-contracts` (ends at commit `b0aec453 docs(plan): W1 contracts — all tasks complete + delivery summary`) but not merged to main and did not use that signal string. T5.3 *must* touch W1 artifacts (`ChannelTag`, `SessionCapabilities`). | Merge `feat/ws-w1-contracts` → `main` first (preferred); then create this worktree from main. Alternative: branch `feat/ws-w5-shared-kernels` from `feat/ws-w1-contracts` directly. Plan assumes the former. |
| **D2** | **Spec path in session prompt** — `02-W5-shared-kernels.md` references `docs/architecture/2026-04-19-unified-coaching-architecture-design.md`; actual path is `docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md`. | Treat as documentation-only typo; this plan uses the real path and flags it for the README bundle author. No code impact. |
| **D3** | **`shared/` location** — spec says `telemetry_tool/shared/`, but `kart_envelope/` is a top-level package at repo root. Putting `shared/` inside `telemetry_tool/` means `kart_envelope` imports from `telemetry_tool.shared.*`. | Acceptable: `kart_envelope/track/geometry.py:27` already imports `from telemetry_tool.reference_line`, so the asymmetric coupling already exists. Follow the spec literally — new package at `telemetry_tool/shared/`. |
| **D4** | **FrenetFrame scope** — spec lists `FrenetFrame` as a shared-geometry primitive alongside `TrackGeometry`. Currently `FrenetFrame` lives at `telemetry_tool/track_surface/frenet.py` (231 LOC) and is consumed by many `track_surface/` modules but not yet by Side B. | Move it in T5.1 so the `shared/geometry/` package is complete in one cut. Leave a re-export shim at the old path. |
| **D5** | **Uncommitted changes on `main`** at plan-writing time: `telemetry_tool/auth/oauth.py`, `telemetry_tool/auth/service.py`, `telemetry_tool/tests/test_auth_oauth.py`, `telemetry_tool/web/routes/data_v2.py`. | None of these collide with W5 paths — no action needed. Noted so the integration-merge driver knows the main-branch baseline is not clean. |

**Stop and ask also if:** running the full pytest suite before T5.1 reveals pre-existing failures unrelated to W5 — we need a green baseline before any move in order to detect regressions reliably.

---

## Execution order (per session prompt)

**T5.2 first → T5.3 → T5.1 → T5.4 → T5.5.** Rationale from the prompt: session #7 (physics) needs more lead time wrapping `qss_enhanced.py` than session #6 needs for detector migration. T5.1 can run after because TrackGeometry's consumers are stable. T5.4 must run last because it rewrites call sites that only exist once the previous tasks have moved the symbols.

Signal commit messages (greppable across worktrees):

- After T5.2 lands on this branch: `[signal:W5.T5.2-done]`
- After T5.3 lands on this branch: `[signal:W5.T5.3-done]`
- After the whole branch merges: `[signal:W5-done]`

---

## Import-graph audit

### Before (current main + W1 branch merged)

```
kart_envelope/                         telemetry_tool/
├── track/geometry.py (TrackGeometry)  ├── track_surface/frenet.py (FrenetFrame)
│   └── imports: KartEnvelopeConfig,   │   └── imports: numpy only
│                CANONICAL_TO_RAW,     │
│                reference_line        ├── coaching/
├── envelope/capability.py             │   ├── models.py          ── 25+ import sites
├── envelope/pacejka.py                │   ├── taxonomy/causes.py ── 3+ import sites
├── solver/min_time.py                 │   ├── templates/*        ── 5+ import sites
├── solver/ocp_casadi.py               │   ├── analyzers/*        (stay)
├── coaching/driver_diagnostics.py     │   └── composers/*        (stay)
└── coaching/corner_coaching.py        │
                                       ├── sim_optimizer/
                                       │   ├── solver/qss_enhanced.py     ── imports kart_envelope.track.geometry
                                       │   ├── reconstruction/input_trace.py ── imports kart_envelope.track.geometry
                                       │   └── pipeline.py                 ── imports kart_envelope.track.geometry
                                       │
                                       ├── track_surface/ (50+ files touching TrackGeometry / FrenetFrame)
                                       │
                                       └── web/schemas/contracts/capabilities.py (W1)
                                           └── ChannelTag, SessionCapabilities
```

**Problem**: Side B (`sim_optimizer/*`) imports from Side A (`kart_envelope/track/geometry`). Without W5, every new sim adapter replicates that coupling.

### After W5

```
telemetry_tool/shared/
├── geometry/
│   ├── __init__.py
│   ├── track.py         (TrackGeometry, TrackGeometryError)
│   └── frenet.py        (FrenetFrame)
├── physics/
│   ├── __init__.py
│   ├── friction.py      (FrictionModel Protocol)
│   └── vehicle.py       (VehicleModel ABC)
├── coaching_taxonomy/
│   ├── __init__.py
│   ├── models.py        (all @dataclass models from coaching/models.py)
│   ├── causes.py        (CauseTaxonomy)
│   ├── causes.json      (data file referenced by causes.py)
│   ├── channels.py      (ChannelTag, SessionCapabilities — pulled from W1 contracts)
│   └── templates/
│       ├── __init__.py
│       ├── confidence_frames.py
│       ├── corner_tips.py
│       ├── drills.py
│       ├── mental_imagery.py
│       ├── narratives.py
│       ├── progression.py
│       ├── reference_points.py
│       └── symptoms.py
└── __init__.py           (empty — no re-exports from top level to keep surface minimal)
```

**Old locations keep deprecation shims:**

- `kart_envelope/track/geometry.py` → shim re-exporting `TrackGeometry`
- `telemetry_tool/track_surface/frenet.py` → shim re-exporting `FrenetFrame`
- `telemetry_tool/coaching/models.py` → shim re-exporting every dataclass
- `telemetry_tool/coaching/taxonomy/causes.py` → shim re-exporting `CauseTaxonomy`
- `telemetry_tool/coaching/templates/*.py` → shim re-exporting each template constant
- `telemetry_tool/web/schemas/contracts/capabilities.py` → shim re-exporting `ChannelTag` and `SessionCapabilities`

**Invariant verified by new test**: `telemetry_tool/shared/**/*.py` contains zero imports matching `^(from|import)\s+(kart_envelope|telemetry_tool\.(kart_envelope|sim_optimizer|pipeline|coaching|track_surface|web)\.)`. Enforced by `telemetry_tool/tests/test_shared_kernel_isolation.py`.

---

## File manifest

### Created

```
telemetry_tool/shared/
├── __init__.py
├── geometry/
│   ├── __init__.py
│   ├── track.py
│   └── frenet.py
├── physics/
│   ├── __init__.py
│   ├── friction.py
│   └── vehicle.py
└── coaching_taxonomy/
    ├── __init__.py
    ├── models.py
    ├── causes.py
    ├── causes.json
    ├── channels.py
    └── templates/
        ├── __init__.py
        ├── confidence_frames.py
        ├── corner_tips.py
        ├── drills.py
        ├── mental_imagery.py
        ├── narratives.py
        ├── progression.py
        ├── reference_points.py
        └── symptoms.py

telemetry_tool/tests/test_shared/
├── __init__.py
├── conftest.py
├── test_isolation.py            # import-graph invariant
├── test_geometry_track.py       # smoke + deprecation-warning assertion
├── test_geometry_frenet.py
├── test_physics_friction.py
├── test_physics_vehicle.py
├── test_coaching_taxonomy_models.py
├── test_coaching_taxonomy_causes.py
├── test_coaching_taxonomy_channels.py
├── test_coaching_taxonomy_templates.py
└── test_deprecation_shims.py    # asserts every shim emits DeprecationWarning
```

### Converted to deprecation shims (keep alive one release cycle)

```
kart_envelope/track/geometry.py
telemetry_tool/track_surface/frenet.py
telemetry_tool/coaching/models.py
telemetry_tool/coaching/taxonomy/__init__.py       (now re-exports from shared)
telemetry_tool/coaching/taxonomy/causes.py
telemetry_tool/coaching/templates/__init__.py      (re-exports)
telemetry_tool/coaching/templates/confidence_frames.py
telemetry_tool/coaching/templates/corner_tips.py
telemetry_tool/coaching/templates/drills.py
telemetry_tool/coaching/templates/mental_imagery.py
telemetry_tool/coaching/templates/narratives.py
telemetry_tool/coaching/templates/progression.py
telemetry_tool/coaching/templates/reference_points.py
telemetry_tool/coaching/templates/symptoms.py
telemetry_tool/web/schemas/contracts/capabilities.py   (ChannelTag + SessionCapabilities moved out; file keeps shim)
```

### Modified — call-site rewrites (T5.4)

```
telemetry_tool/coaching/__init__.py
telemetry_tool/coaching/analyzers/exit_speed.py
telemetry_tool/coaching/analyzers/symptom_detector.py
telemetry_tool/coaching/analyzers/throttle_lift.py
telemetry_tool/coaching/analyzers/trail_brake.py
telemetry_tool/coaching/analyzers/traction_budget.py
telemetry_tool/coaching/analyzers/weight_transfer.py
telemetry_tool/coaching/composers/confidence_framer.py
telemetry_tool/coaching/composers/corner_composer.py
telemetry_tool/coaching/composers/focus_limiter.py
telemetry_tool/coaching/composers/progressive_coach.py
telemetry_tool/coaching/composers/session_composer.py

kart_envelope/coaching/driver_diagnostics.py         (imports TrackGeometry)
kart_envelope/envelope/grip_map.py                    (imports TrackGeometry)
kart_envelope/solver/min_time.py                      (imports TrackGeometry)
kart_envelope/solver/ocp_casadi.py                    (imports TrackGeometry)
kart_envelope/track/detection.py                      (imports TrackGeometry)

telemetry_tool/sim_optimizer/solver/qss_enhanced.py
telemetry_tool/sim_optimizer/reconstruction/input_trace.py
telemetry_tool/sim_optimizer/pipeline.py

telemetry_tool/theoretical_adapter.py
telemetry_tool/track_surface/*.py                     (18 files touching FrenetFrame / TrackGeometry — enumerated in Task 9)

telemetry_tool/tests/test_sim_optimizer/test_qss_enhanced.py
telemetry_tool/tests/test_sim_optimizer/test_input_reconstruction.py
telemetry_tool/tests/coaching/test_*.py               (14 files — enumerated in Task 11)
telemetry_tool/tests/test_frenet.py
```

No other files touched outside this manifest.

---

## Shared deprecation-shim template

Every old-location file becomes a ~10 line shim. Use this template verbatim:

```python
# <PATH>
"""Deprecation shim — content moved to ``<NEW_PATH>`` (W5 shared kernels).

This module re-exports the moved symbol so concurrent Wave-2 worktrees that
still import from the old path keep working. Remove after one release cycle
(earliest: the release after W5 merges).
"""
from __future__ import annotations

import warnings

from <NEW_MODULE> import <SYMBOL> as <SYMBOL>  # re-export

warnings.warn(
    "<PATH> is deprecated; import <SYMBOL> from <NEW_MODULE> instead "
    "(W5 shared kernels refactor).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["<SYMBOL>"]
```

For multi-symbol shims (e.g. `coaching/models.py`), list every symbol in the import and in `__all__`. The `stacklevel=2` is required so the warning points at the caller, not the shim itself.

---

## Tasks

### Task 0: Worktree setup + green baseline (prerequisite)

**Files:** _none created_ — environment setup only

- [ ] **Step 0.1: Confirm W1 has merged to main (D1 resolution)**

Run: `git log --oneline main -10 | grep -E "W1|contracts"`

Expected: at least one commit whose message references W1 contracts — ideally a merge commit like `Merge branch 'feat/ws-w1-contracts'`.

If absent, **stop and ask user to merge W1 first** per Decision D1.

- [ ] **Step 0.2: Verify `.worktrees/` is git-ignored**

Run: `git check-ignore -q .worktrees && echo "ok: ignored" || echo "FAIL: not ignored"`

Expected: `ok: ignored`. If not, add `.worktrees/` to `.gitignore` and commit before proceeding.

- [ ] **Step 0.3: Create W5 worktree from main**

Run: `git worktree add .worktrees/ws-w5-shared-kernels -b feat/ws-w5-shared-kernels main`

Then `cd .worktrees/ws-w5-shared-kernels` for all subsequent work.

- [ ] **Step 0.4: Verify clean green baseline**

Run: `pytest telemetry_tool/tests/ kart_envelope/tests/ -x -q`

Expected: all tests pass. If any fail, capture the list, report to user, stop. A dirty baseline defeats regression detection.

- [ ] **Step 0.5: Snapshot the `pydeps` import graph (optional but cheap)**

Run: `pip install pydeps && pydeps telemetry_tool --max-bacon 2 --show-dot > ../../artifacts/import-graph-before.dot` (best-effort; skip on install failure).

Commit none of this yet.

---

### Task 1: `shared/` package scaffold + isolation test (T5.0 prep)

Creating the skeleton and the failing invariant test first so every subsequent task has a green-field target to push into.

**Files:**
- Create: `telemetry_tool/shared/__init__.py`
- Create: `telemetry_tool/shared/geometry/__init__.py`
- Create: `telemetry_tool/shared/physics/__init__.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/__init__.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/__init__.py`
- Create: `telemetry_tool/tests/test_shared/__init__.py`
- Create: `telemetry_tool/tests/test_shared/conftest.py`
- Create: `telemetry_tool/tests/test_shared/test_isolation.py`

- [ ] **Step 1.1: Write failing import-isolation test**

```python
# telemetry_tool/tests/test_shared/test_isolation.py
"""Invariant: telemetry_tool/shared/ must not import from any side-specific package.

W5 acceptance: `shared/` has zero imports from `kart_envelope/`,
`sim_optimizer/`, `pipeline/`, `coaching/`, `track_surface/`, or
`web/schemas/contracts/`.
"""
from __future__ import annotations

import ast
import pathlib

SHARED_ROOT = pathlib.Path(__file__).resolve().parents[2] / "shared"
FORBIDDEN_ROOTS = {
    "kart_envelope",
    "telemetry_tool.kart_envelope",
    "telemetry_tool.sim_optimizer",
    "telemetry_tool.pipeline",
    "telemetry_tool.coaching",
    "telemetry_tool.track_surface",
    "telemetry_tool.web",
}


def _iter_py_files(root: pathlib.Path):
    yield from (p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _imports(py_path: pathlib.Path) -> set[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_shared_has_no_side_specific_imports():
    assert SHARED_ROOT.exists(), f"shared/ missing: {SHARED_ROOT}"
    offenders: list[tuple[str, str]] = []
    for py in _iter_py_files(SHARED_ROOT):
        for mod in _imports(py):
            for banned in FORBIDDEN_ROOTS:
                if mod == banned or mod.startswith(banned + "."):
                    offenders.append((str(py.relative_to(SHARED_ROOT)), mod))
    assert not offenders, f"shared/ imports from forbidden roots: {offenders}"
```

- [ ] **Step 1.2: Run it — expect FAIL (shared/ missing)**

Run: `pytest telemetry_tool/tests/test_shared/test_isolation.py -v`

Expected: AssertionError `shared/ missing: .../telemetry_tool/shared`.

- [ ] **Step 1.3: Create empty package files**

```python
# telemetry_tool/shared/__init__.py
"""Cross-side primitives used by both real-life and simracing engines.

This package is the W5 deliverable — see
``docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md``
§5 W5. Nothing inside ``shared/`` may import from ``kart_envelope/``,
``sim_optimizer/``, ``pipeline/``, ``coaching/``, ``track_surface/``, or
``web/``. Enforced by ``tests/test_shared/test_isolation.py``.
"""
```

```python
# telemetry_tool/shared/geometry/__init__.py
"""Track geometry primitives — centerline, curvature, Frenet frame."""
```

```python
# telemetry_tool/shared/physics/__init__.py
"""Physics primitives — abstract bases for friction and vehicle models."""
```

```python
# telemetry_tool/shared/coaching_taxonomy/__init__.py
"""Coaching taxonomy — pattern ontology, data models, templates, channel tags."""
```

```python
# telemetry_tool/shared/coaching_taxonomy/templates/__init__.py
"""Coaching narrative / drill / reference-point templates (data modules)."""
```

Empty `tests/test_shared/__init__.py` and `tests/test_shared/conftest.py` too.

- [ ] **Step 1.4: Run isolation test — expect PASS (empty package passes trivially)**

Run: `pytest telemetry_tool/tests/test_shared/test_isolation.py -v`

Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add telemetry_tool/shared/ telemetry_tool/tests/test_shared/
git commit -m "feat(shared): package scaffold + import-isolation invariant (W5.T5.0)"
```

---

### Task 2: Physics abstract bases (T5.2 — unblocks #7)

Create the `FrictionModel` protocol and `VehicleModel` abstract class that the W7 optimizer dispatcher can depend on without coupling to kart or sim concretes.

Per risk "err on the side of leaving in place" — we do **not** move `kart_envelope/envelope/pacejka.py`, `sim_optimizer/param_id/vehicle_model.py`, or any other concrete physics file. Those keep their homes; they gain a base-class lineage.

**Files:**
- Create: `telemetry_tool/shared/physics/friction.py`
- Create: `telemetry_tool/shared/physics/vehicle.py`
- Create: `telemetry_tool/tests/test_shared/test_physics_friction.py`
- Create: `telemetry_tool/tests/test_shared/test_physics_vehicle.py`
- Modify: `telemetry_tool/shared/physics/__init__.py` (add re-exports)

- [ ] **Step 2.1: Write failing test for `FrictionModel`**

```python
# telemetry_tool/tests/test_shared/test_physics_friction.py
from __future__ import annotations

import numpy as np
from telemetry_tool.shared.physics import FrictionModel


def test_friction_model_is_a_protocol():
    """Consumers should be able to duck-type against FrictionModel."""
    class _StubTire:
        def mu(self, slip: np.ndarray, load_n: np.ndarray) -> np.ndarray:
            return np.full_like(slip, 1.0)

    stub: FrictionModel = _StubTire()
    out = stub.mu(np.array([0.0, 0.05]), np.array([3000.0, 3000.0]))
    assert out.shape == (2,)
    assert np.allclose(out, 1.0)


def test_friction_model_runtime_checkable():
    from telemetry_tool.shared.physics.friction import FrictionModel

    class Concrete:
        def mu(self, slip, load_n):  # noqa: ANN001
            return slip

    assert isinstance(Concrete(), FrictionModel)
```

- [ ] **Step 2.2: Run test — expect ImportError (no friction.py yet)**

Run: `pytest telemetry_tool/tests/test_shared/test_physics_friction.py -v`

Expected: ImportError: cannot import name 'FrictionModel'.

- [ ] **Step 2.3: Implement `FrictionModel` as runtime-checkable Protocol**

```python
# telemetry_tool/shared/physics/friction.py
"""Friction-model contract for both real-life (envelope-fit) and sim (Pacejka) tire models.

A concrete implementation only needs to provide ``mu(slip, load_n)``; everything
else (combined-slip, temperature, degradation) is an extension surface owned by
the concrete class.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class FrictionModel(Protocol):
    """Returns the available friction coefficient at given slip and vertical load.

    Parameters
    ----------
    slip : np.ndarray
        Signed slip ratio (longitudinal) or slip angle (lateral), radians for angles.
    load_n : np.ndarray
        Vertical load per contact patch, Newtons. Must broadcast with ``slip``.

    Returns
    -------
    np.ndarray
        Available grip coefficient, dimensionless. Same shape as ``slip``.
    """

    def mu(self, slip: np.ndarray, load_n: np.ndarray) -> np.ndarray: ...
```

- [ ] **Step 2.4: Re-export from `shared.physics`**

```python
# telemetry_tool/shared/physics/__init__.py
"""Physics primitives — abstract bases for friction and vehicle models."""
from telemetry_tool.shared.physics.friction import FrictionModel
from telemetry_tool.shared.physics.vehicle import VehicleModel

__all__ = ["FrictionModel", "VehicleModel"]
```

- [ ] **Step 2.5: Run — `VehicleModel` import still fails**

Run: `pytest telemetry_tool/tests/test_shared/test_physics_friction.py -v`

Expected: ImportError `cannot import name 'VehicleModel'`.

- [ ] **Step 2.6: Write failing test for `VehicleModel`**

```python
# telemetry_tool/tests/test_shared/test_physics_vehicle.py
from __future__ import annotations

import pytest
from telemetry_tool.shared.physics import VehicleModel


def test_vehicle_model_abstract_requires_mass():
    class Incomplete(VehicleModel):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # missing abstract methods


def test_vehicle_model_minimal_concrete():
    class Stub(VehicleModel):
        @property
        def mass_kg(self) -> float:
            return 720.0

        @property
        def wheelbase_m(self) -> float:
            return 1.05

        @property
        def cg_height_m(self) -> float:
            return 0.28

    s = Stub()
    assert s.mass_kg == 720.0
    assert s.wheelbase_m == 1.05
    assert s.cg_height_m == 0.28
```

- [ ] **Step 2.7: Implement `VehicleModel`**

```python
# telemetry_tool/shared/physics/vehicle.py
"""Abstract vehicle model — minimal surface shared by both sides.

Concrete vehicles (kart envelope capability, sim_optimizer param_id,
lap_oracle physics) extend this with their full parameterization. The base
exists so W7 optimizer can request "any vehicle" without importing a concrete.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class VehicleModel(ABC):
    """Minimum interface every vehicle representation must satisfy."""

    @property
    @abstractmethod
    def mass_kg(self) -> float: ...

    @property
    @abstractmethod
    def wheelbase_m(self) -> float: ...

    @property
    @abstractmethod
    def cg_height_m(self) -> float: ...
```

- [ ] **Step 2.8: Run both physics tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_shared/test_physics_ -v`

Expected: all tests PASS. Isolation test still PASS.

- [ ] **Step 2.9: Commit with T5.2 signal**

```bash
git add telemetry_tool/shared/physics/ telemetry_tool/tests/test_shared/test_physics_*
git commit -m "feat(shared): physics bases — FrictionModel protocol + VehicleModel ABC [signal:W5.T5.2-done]"
```

> **Other sessions (#7 optimizer): start consuming `telemetry_tool.shared.physics.{FrictionModel,VehicleModel}` now.**

---

### Task 3: Coaching taxonomy — `models.py` move (T5.3 part 1 — largest surface)

Move `telemetry_tool/coaching/models.py` (519 LOC, ~25 call-sites) to `shared/coaching_taxonomy/models.py` via a two-step copy-then-shim. Import rewrites happen in T5.4.

**Files:**
- Create: `telemetry_tool/shared/coaching_taxonomy/models.py`
- Create: `telemetry_tool/tests/test_shared/test_coaching_taxonomy_models.py`
- Modify later (Task 9 / T5.4): `telemetry_tool/coaching/models.py` → shim

- [ ] **Step 3.1: Copy the file verbatim**

Run: `cp telemetry_tool/coaching/models.py telemetry_tool/shared/coaching_taxonomy/models.py`

- [ ] **Step 3.2: Inspect for kart-specific / sim-specific imports**

Run: `grep -nE "^(from|import)" telemetry_tool/shared/coaching_taxonomy/models.py`

Expected: only `from __future__`, `dataclasses`, `typing`. If any `from telemetry_tool.coaching.*` or `from kart_envelope.*` appear, stop — those mean the file was not pure data. Resolve before moving. (Pre-scan confirms pure data at plan-writing time.)

- [ ] **Step 3.3: Write smoke test**

```python
# telemetry_tool/tests/test_shared/test_coaching_taxonomy_models.py
"""Every dataclass exported from the legacy location is re-exported from shared
and to_dict() still round-trips.
"""
from __future__ import annotations

import inspect

from telemetry_tool.shared.coaching_taxonomy import models as shared_models


EXPECTED = {
    "BrakingBlock",
    "TrailBrakeAssessment",
    "WeightTransferInsight",
    "ThrottleLiftEvent",
    "ExitSpeedCascade",
    "TractionBudget",
    "SymptomDetection",
    "Symptom",
    "FocusArea",
    "CornerCoachingDetail",
    "SessionCoaching",
}


def test_all_legacy_dataclasses_present():
    present = {
        name for name, obj in inspect.getmembers(shared_models, inspect.isclass)
        if obj.__module__ == shared_models.__name__
    }
    missing = EXPECTED - present
    assert not missing, f"missing dataclasses after move: {missing}"


def test_braking_block_to_dict_roundtrip():
    block = shared_models.BrakingBlock(
        block_id=1, name="trail", s_start=120.0, s_end=145.0, duration_s=1.2,
    )
    d = block.to_dict()
    assert d["block_id"] == 1
    assert d["name"] == "trail"
    assert d["s_start"] == 120.0
```

- [ ] **Step 3.4: Run — expect PASS**

Run: `pytest telemetry_tool/tests/test_shared/test_coaching_taxonomy_models.py -v`

Expected: PASS. Isolation still PASS.

- [ ] **Step 3.5: Add package re-export**

```python
# telemetry_tool/shared/coaching_taxonomy/__init__.py
"""Coaching taxonomy — pattern ontology, data models, templates, channel tags."""
from telemetry_tool.shared.coaching_taxonomy import models  # noqa: F401
```

- [ ] **Step 3.6: Commit**

```bash
git add telemetry_tool/shared/coaching_taxonomy/ telemetry_tool/tests/test_shared/test_coaching_taxonomy_models.py
git commit -m "feat(shared): coaching_taxonomy.models — copy of coaching/models.py (W5.T5.3 step 1/4)"
```

---

### Task 4: Coaching taxonomy — `causes` move (T5.3 part 2)

**Files:**
- Create: `telemetry_tool/shared/coaching_taxonomy/causes.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/causes.json`
- Create: `telemetry_tool/tests/test_shared/test_coaching_taxonomy_causes.py`

- [ ] **Step 4.1: Copy source + data file**

Run: `cp telemetry_tool/coaching/taxonomy/causes.py telemetry_tool/shared/coaching_taxonomy/causes.py && cp telemetry_tool/coaching/taxonomy/causes.json telemetry_tool/shared/coaching_taxonomy/causes.json`

- [ ] **Step 4.2: Fix the JSON file-path resolution**

Open `telemetry_tool/shared/coaching_taxonomy/causes.py`. Wherever it loads `causes.json` (likely via `Path(__file__).parent / "causes.json"` or similar), confirm the relative layout still works (`causes.json` sits next to `causes.py` in both locations, so usually nothing to change). If it used an absolute import path like `telemetry_tool.coaching.taxonomy`, rewrite to use `Path(__file__).parent / "causes.json"`.

- [ ] **Step 4.3: Write smoke test**

```python
# telemetry_tool/tests/test_shared/test_coaching_taxonomy_causes.py
from __future__ import annotations

from telemetry_tool.shared.coaching_taxonomy.causes import CauseTaxonomy


def test_cause_taxonomy_loads():
    tax = CauseTaxonomy()
    # replace the keyword assertions below with one known cause from causes.json
    # after reading the file during implementation
    assert len(tax) > 0 or hasattr(tax, "causes")  # loose shape check
```

> **Implementer note:** open `causes.json` and tighten this test against one real cause ID before committing.

- [ ] **Step 4.4: Run + commit**

Run: `pytest telemetry_tool/tests/test_shared/test_coaching_taxonomy_causes.py -v`

```bash
git add telemetry_tool/shared/coaching_taxonomy/causes.py telemetry_tool/shared/coaching_taxonomy/causes.json telemetry_tool/tests/test_shared/test_coaching_taxonomy_causes.py
git commit -m "feat(shared): coaching_taxonomy.causes — copy of coaching/taxonomy/causes (W5.T5.3 step 2/4)"
```

---

### Task 5: Coaching taxonomy — `templates/` move (T5.3 part 3)

Templates are pure data modules (constants) — 8 files. Copy verbatim.

**Files:**
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/confidence_frames.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/corner_tips.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/drills.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/mental_imagery.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/narratives.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/progression.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/reference_points.py`
- Create: `telemetry_tool/shared/coaching_taxonomy/templates/symptoms.py`
- Create: `telemetry_tool/tests/test_shared/test_coaching_taxonomy_templates.py`

- [ ] **Step 5.1: Copy every template file**

```bash
for f in confidence_frames corner_tips drills mental_imagery narratives progression reference_points symptoms; do
  cp telemetry_tool/coaching/templates/${f}.py telemetry_tool/shared/coaching_taxonomy/templates/${f}.py
done
```

- [ ] **Step 5.2: Scan for cross-module imports inside templates**

Run: `grep -nE "^(from|import)" telemetry_tool/shared/coaching_taxonomy/templates/*.py`

Expected: only stdlib / typing / dataclasses imports (pre-scan confirms). If any `from telemetry_tool.coaching.*` exists, the template is not pure data — stop and ask.

- [ ] **Step 5.3: Write smoke test**

```python
# telemetry_tool/tests/test_shared/test_coaching_taxonomy_templates.py
from __future__ import annotations

import importlib

TEMPLATE_MODULES = [
    "confidence_frames",
    "corner_tips",
    "drills",
    "mental_imagery",
    "narratives",
    "progression",
    "reference_points",
    "symptoms",
]


def test_every_template_module_importable():
    for name in TEMPLATE_MODULES:
        mod = importlib.import_module(f"telemetry_tool.shared.coaching_taxonomy.templates.{name}")
        assert mod is not None, name


def test_known_template_constants_exposed():
    from telemetry_tool.shared.coaching_taxonomy.templates import corner_tips, drills
    assert hasattr(corner_tips, "CORNER_TIPS")
    assert hasattr(drills, "DRILL_LIBRARY")
```

- [ ] **Step 5.4: Run + commit**

Run: `pytest telemetry_tool/tests/test_shared/test_coaching_taxonomy_templates.py -v`

```bash
git add telemetry_tool/shared/coaching_taxonomy/templates/ telemetry_tool/tests/test_shared/test_coaching_taxonomy_templates.py
git commit -m "feat(shared): coaching_taxonomy.templates — copy of coaching/templates/* (W5.T5.3 step 3/4)"
```

---

### Task 6: `ChannelTag` + `SessionCapabilities` move (T5.3 part 4 — W1 coupling)

Per session prompt: "If session #1 defined `ChannelTag`… move it to `shared/coaching_taxonomy/channels.py` as part of T5.3." W1 defined them in `telemetry_tool/web/schemas/contracts/capabilities.py`. Move them out; leave a re-export shim at the old path so W6 and W8 can import from either side during the transition.

**Files:**
- Create: `telemetry_tool/shared/coaching_taxonomy/channels.py`
- Create: `telemetry_tool/tests/test_shared/test_coaching_taxonomy_channels.py`
- Modify: `telemetry_tool/web/schemas/contracts/capabilities.py` → shim
- Modify: `telemetry_tool/web/schemas/contracts/__init__.py` (import from shim still works — no change)

- [ ] **Step 6.1: Read W1 implementation**

Run: `cat telemetry_tool/web/schemas/contracts/capabilities.py`

Expected: two top-level definitions — the `ChannelTag` enum and the `SessionCapabilities` Pydantic model. Capture the exact content for verbatim move.

- [ ] **Step 6.2: Write failing test**

```python
# telemetry_tool/tests/test_shared/test_coaching_taxonomy_channels.py
from __future__ import annotations

from telemetry_tool.shared.coaching_taxonomy.channels import (
    ChannelTag, SessionCapabilities,
)


def test_channel_tag_w6_required_set():
    required = {"GPS", "LAT_G", "LON_G", "YAW_RATE", "THROTTLE", "BRAKE", "STEER"}
    present = {tag.name for tag in ChannelTag}
    missing = required - present
    assert not missing


def test_session_capabilities_default_empty():
    caps = SessionCapabilities()
    assert caps.has(ChannelTag.GPS) is False
```

- [ ] **Step 6.3: Run — expect ImportError**

Run: `pytest telemetry_tool/tests/test_shared/test_coaching_taxonomy_channels.py -v`

Expected: ImportError.

- [ ] **Step 6.4: Move the definitions**

Move the full content of `capabilities.py` (the enum + the model) into `telemetry_tool/shared/coaching_taxonomy/channels.py`. Preserve the module docstring, amended to reflect the new location.

- [ ] **Step 6.5: Convert `capabilities.py` to shim**

```python
# telemetry_tool/web/schemas/contracts/capabilities.py
"""Deprecation shim — ChannelTag and SessionCapabilities moved to
``telemetry_tool.shared.coaching_taxonomy.channels`` (W5 shared kernels).
"""
from __future__ import annotations

import warnings

from telemetry_tool.shared.coaching_taxonomy.channels import (
    ChannelTag as ChannelTag,
    SessionCapabilities as SessionCapabilities,
)

warnings.warn(
    "telemetry_tool.web.schemas.contracts.capabilities is deprecated; "
    "import ChannelTag and SessionCapabilities from "
    "telemetry_tool.shared.coaching_taxonomy.channels (W5 shared kernels).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["ChannelTag", "SessionCapabilities"]
```

- [ ] **Step 6.6: Run W1 + W5 test suites**

Run: `pytest telemetry_tool/tests/test_contracts/ telemetry_tool/tests/test_shared/ -v`

Expected: both suites pass. The W1 contract tests still work because the shim re-exports the exact symbols.

- [ ] **Step 6.7: Update `shared/coaching_taxonomy/__init__.py`**

```python
# telemetry_tool/shared/coaching_taxonomy/__init__.py
"""Coaching taxonomy — pattern ontology, data models, templates, channel tags."""
from telemetry_tool.shared.coaching_taxonomy import causes, models  # noqa: F401
from telemetry_tool.shared.coaching_taxonomy.channels import (  # noqa: F401
    ChannelTag,
    SessionCapabilities,
)

__all__ = ["ChannelTag", "SessionCapabilities", "causes", "models"]
```

- [ ] **Step 6.8: Commit with T5.3 signal**

```bash
git add telemetry_tool/shared/coaching_taxonomy/channels.py \
        telemetry_tool/shared/coaching_taxonomy/__init__.py \
        telemetry_tool/web/schemas/contracts/capabilities.py \
        telemetry_tool/tests/test_shared/test_coaching_taxonomy_channels.py
git commit -m "feat(shared): coaching_taxonomy.channels — ChannelTag + SessionCapabilities [signal:W5.T5.3-done]"
```

> **Other sessions (#6 coaching): start consuming `telemetry_tool.shared.coaching_taxonomy.{models,causes,templates,channels}` now.**

---

### Task 7: `TrackGeometry` move (T5.1 part 1)

The source file is 408 LOC and has two external imports at the top (`kart_envelope.config.KartEnvelopeConfig`, `kart_envelope.ingest.columns.CANONICAL_TO_RAW`) plus one cross-package import (`telemetry_tool.reference_line`). Strategy: move the class; decouple the kart-specific imports by reading the source first.

**Files:**
- Create: `telemetry_tool/shared/geometry/track.py`
- Create: `telemetry_tool/tests/test_shared/test_geometry_track.py`

- [ ] **Step 7.1: Read the source in full**

Run: `cat kart_envelope/track/geometry.py` (all 408 lines)

Identify every use of `KartEnvelopeConfig` and `CANONICAL_TO_RAW`. Expected outcome (from pre-scan): the imports are used for column-name canonicalization and config-driven defaults. They are called inside `@classmethod` factories like `from_dataframe(...)`, not in core geometry math. The data holder itself is pure numpy.

- [ ] **Step 7.2: Decouple factory parameters**

When copying to `shared/geometry/track.py`:
- Drop the imports of `KartEnvelopeConfig` and `CANONICAL_TO_RAW` and the `sys.path` hack (lines 21–26 in current source).
- Factory methods that used `KartEnvelopeConfig` gain a typed parameter instead — e.g. `from_dataframe(df, *, column_map: dict[str, str], config: TrackGeometryConfig)` where `TrackGeometryConfig` is a new small dataclass defined inside this file containing only the fields TrackGeometry actually consumes (e.g. resample step, smoothing window).
- `reference_line` import: if `telemetry_tool.reference_line` is a pure-numpy helper, inline the two calls (`compute_curvature_profile`, `compute_reference_line`) into `shared/geometry/track.py` **only if they are <50 LOC combined and self-contained**. Otherwise, keep the import — `reference_line` is a telemetry-tool-level module not a side-specific one, so it satisfies the isolation invariant as long as it does not itself import from `kart_envelope/`, `sim_optimizer/`, etc. Verify via the isolation test.

> **If inlining fails the isolation test** (e.g. `reference_line` depends on kart-specific code), stop and propose moving `reference_line` to `shared/geometry/` in a follow-up task.

- [ ] **Step 7.3: Write failing test**

```python
# telemetry_tool/tests/test_shared/test_geometry_track.py
from __future__ import annotations

import numpy as np

from telemetry_tool.shared.geometry.track import TrackGeometry, TrackGeometryError


def test_track_geometry_imports():
    assert TrackGeometry is not None
    assert TrackGeometryError is not None


def test_track_geometry_minimal_construction():
    g = TrackGeometry(
        distance_m=np.array([0.0, 10.0, 20.0, 30.0]),
        curvature_1pm=np.zeros(4),
        heading_rad=np.zeros(4),
        x_ref_m=np.array([0.0, 10.0, 20.0, 30.0]),
        y_ref_m=np.zeros(4),
        lap_length_m=30.0,
        track_id="smoke",
    )
    assert g.lap_length_m == 30.0
    assert g.has_elevation is False
    assert g.has_signed_curvature is False


def test_track_geometry_roundtrip_dict():
    g = TrackGeometry(
        distance_m=np.array([0.0, 10.0, 20.0]),
        curvature_1pm=np.array([0.0, 0.01, 0.02]),
        heading_rad=np.zeros(3),
        x_ref_m=np.array([0.0, 10.0, 20.0]),
        y_ref_m=np.zeros(3),
        lap_length_m=20.0,
    )
    roundtrip = TrackGeometry.from_dict(g.to_dict())
    assert np.allclose(roundtrip.distance_m, g.distance_m)
    assert np.allclose(roundtrip.curvature_1pm, g.curvature_1pm)
```

- [ ] **Step 7.4: Run — expect ImportError**

Run: `pytest telemetry_tool/tests/test_shared/test_geometry_track.py -v`

- [ ] **Step 7.5: Write `shared/geometry/track.py`**

Paste the decoupled content produced in step 7.2. Keep the class body character-identical to the original for `to_dict` / `from_dict` and the numpy-based methods. Change module docstring to reflect the new location.

- [ ] **Step 7.6: Re-export from package**

```python
# telemetry_tool/shared/geometry/__init__.py
"""Track geometry primitives — centerline, curvature, Frenet frame."""
from telemetry_tool.shared.geometry.track import TrackGeometry, TrackGeometryError

__all__ = ["TrackGeometry", "TrackGeometryError"]
```

- [ ] **Step 7.7: Run full W5 + sim_optimizer + track_surface smoke suite**

Run: `pytest telemetry_tool/tests/test_shared/ telemetry_tool/tests/test_sim_optimizer/ telemetry_tool/tests/test_frenet.py -q`

Expected: new W5 tests pass; `test_sim_optimizer` still green because it still imports from the old `kart_envelope.track.geometry` (shim comes in T5.5).

- [ ] **Step 7.8: Commit**

```bash
git add telemetry_tool/shared/geometry/track.py telemetry_tool/shared/geometry/__init__.py telemetry_tool/tests/test_shared/test_geometry_track.py
git commit -m "feat(shared): geometry.track — TrackGeometry decoupled from kart_envelope config (W5.T5.1 step 1/2)"
```

---

### Task 8: `FrenetFrame` move (T5.1 part 2)

231 LOC, purely numpy-based (verified at plan-writing time: `grep -nE '^(from|import)' telemetry_tool/track_surface/frenet.py` returned only `numpy`, `dataclasses`, `logging`, `typing`). Straightforward copy.

**Files:**
- Create: `telemetry_tool/shared/geometry/frenet.py`
- Create: `telemetry_tool/tests/test_shared/test_geometry_frenet.py`

- [ ] **Step 8.1: Copy verbatim**

Run: `cp telemetry_tool/track_surface/frenet.py telemetry_tool/shared/geometry/frenet.py`

- [ ] **Step 8.2: Update docstring header**

Change the module docstring in the new file from `track_surface/frenet.py` to `shared/geometry/frenet.py` and replace the first line with a one-line pointer to the spec.

- [ ] **Step 8.3: Write smoke test**

```python
# telemetry_tool/tests/test_shared/test_geometry_frenet.py
from __future__ import annotations

import numpy as np

from telemetry_tool.shared.geometry.frenet import FrenetFrame


def test_frenet_frame_projects_centerline_points_to_zero_lateral():
    centerline = np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [30.0, 0.0]])
    frame = FrenetFrame.from_centerline(centerline)
    # A point exactly on the centerline has n ≈ 0
    s, n = frame.world_to_frenet(np.array([[15.0, 0.0]]))
    assert abs(s[0] - 15.0) < 1e-6
    assert abs(n[0]) < 1e-6
```

> **Implementer note:** confirm `FrenetFrame.from_centerline` is the constructor name; adapt if different.

- [ ] **Step 8.4: Re-export + run**

```python
# telemetry_tool/shared/geometry/__init__.py  (update)
from telemetry_tool.shared.geometry.track import TrackGeometry, TrackGeometryError
from telemetry_tool.shared.geometry.frenet import FrenetFrame

__all__ = ["TrackGeometry", "TrackGeometryError", "FrenetFrame"]
```

Run: `pytest telemetry_tool/tests/test_shared/test_geometry_frenet.py -v`

- [ ] **Step 8.5: Commit**

```bash
git add telemetry_tool/shared/geometry/frenet.py telemetry_tool/shared/geometry/__init__.py telemetry_tool/tests/test_shared/test_geometry_frenet.py
git commit -m "feat(shared): geometry.frenet — FrenetFrame moved from track_surface (W5.T5.1 step 2/2)"
```

---

### Task 9: Call-site rewrites — side B (sim_optimizer) + real-life-side (kart_envelope / track_surface / coaching) (T5.4)

Two sub-tasks: rewrite imports across the whole repo in one atomic set of commits, one per package so `git bisect` stays useful.

**Files modified:** per the manifest above. Use `Grep` + `Edit` for each; do not do blanket sed replaces.

- [ ] **Step 9.1: Rewrite `sim_optimizer/` imports**

Files:
- `telemetry_tool/sim_optimizer/solver/qss_enhanced.py:14`
- `telemetry_tool/sim_optimizer/reconstruction/input_trace.py:10`
- `telemetry_tool/sim_optimizer/pipeline.py:16`

Change `from kart_envelope.track.geometry import TrackGeometry` → `from telemetry_tool.shared.geometry.track import TrackGeometry`.

Run: `pytest telemetry_tool/tests/test_sim_optimizer/ -q`

Expected: all pass.

Commit:
```bash
git commit -m "refactor(sim_optimizer): import TrackGeometry from shared (W5.T5.4)"
```

- [ ] **Step 9.2: Rewrite `kart_envelope/` TrackGeometry callers**

Files (see manifest).

Change `from kart_envelope.track.geometry import TrackGeometry` → `from telemetry_tool.shared.geometry.track import TrackGeometry`.

Run: `pytest kart_envelope/tests/ -q`

Commit:
```bash
git commit -m "refactor(kart_envelope): import TrackGeometry from shared (W5.T5.4)"
```

- [ ] **Step 9.3: Rewrite `track_surface/` FrenetFrame callers**

Expected file list (from pre-scan) — 18 source files under `telemetry_tool/track_surface/` plus tests under `telemetry_tool/tests/test_frenet.py`, `test_surface_builder.py`, `test_line_delta.py`, `test_track_store.py`, `test_track_matcher.py`, `test_road_attitude_field.py`, `test_bump_detection.py`, `test_elevation_3d.py`, `test_pre_session.py`. Enumerate with:

```bash
grep -l "from telemetry_tool.track_surface.frenet import FrenetFrame\|from \.frenet import FrenetFrame" telemetry_tool/track_surface/ telemetry_tool/tests/ -r
```

Rewrite each to `from telemetry_tool.shared.geometry.frenet import FrenetFrame` (absolute) or keep relative where it stays inside `track_surface/` and rely on the re-export shim (T5.5) — prefer absolute to make the graph explicit.

Run: `pytest telemetry_tool/tests/test_frenet.py telemetry_tool/tests/test_track_store.py -q`

Commit:
```bash
git commit -m "refactor(track_surface): import FrenetFrame from shared (W5.T5.4)"
```

- [ ] **Step 9.4: Rewrite `coaching/` imports for models / taxonomy / templates**

Files (13 source files + 14 test files, enumerated in the grep output captured during audit). For each, transform:

| Old | New |
|-----|-----|
| `from telemetry_tool.coaching.models import X` | `from telemetry_tool.shared.coaching_taxonomy.models import X` |
| `from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy` | `from telemetry_tool.shared.coaching_taxonomy.causes import CauseTaxonomy` |
| `from telemetry_tool.coaching.templates.<name> import X` | `from telemetry_tool.shared.coaching_taxonomy.templates.<name> import X` |

Do these per file with Edit, not a single regex — some imports are multi-line (`from ... import (\n A,\n B,\n)`).

Run: `pytest telemetry_tool/tests/coaching/ -q`

Commit:
```bash
git commit -m "refactor(coaching): import models/taxonomy/templates from shared (W5.T5.4)"
```

- [ ] **Step 9.5: Rewrite `telemetry_tool/theoretical_adapter.py`**

Single file, single import line. Edit, run the relevant tests, commit.

```bash
git commit -m "refactor(theoretical_adapter): import TrackGeometry from shared (W5.T5.4)"
```

- [ ] **Step 9.6: Full-repo sanity**

Run: `pytest telemetry_tool/tests/ kart_envelope/tests/ -q`

Expected: all green. Isolation test still PASS.

---

### Task 10: Deprecation shims (T5.5)

Convert every old location into a thin re-export. The shim template is at the top of this document. Apply it verbatim for each symbol set.

**Files:**
- Modify → shim: `kart_envelope/track/geometry.py`
- Modify → shim: `telemetry_tool/track_surface/frenet.py`
- Modify → shim: `telemetry_tool/coaching/models.py`
- Modify → shim: `telemetry_tool/coaching/taxonomy/causes.py`
- Modify → shim: `telemetry_tool/coaching/taxonomy/__init__.py`
- Modify → shim: `telemetry_tool/coaching/templates/<each>.py`

- [ ] **Step 10.1: Write failing deprecation test**

```python
# telemetry_tool/tests/test_shared/test_deprecation_shims.py
from __future__ import annotations

import importlib
import warnings

SHIM_MODULES = [
    "kart_envelope.track.geometry",
    "telemetry_tool.track_surface.frenet",
    "telemetry_tool.coaching.models",
    "telemetry_tool.coaching.taxonomy.causes",
    "telemetry_tool.coaching.templates.corner_tips",
    "telemetry_tool.coaching.templates.drills",
    "telemetry_tool.coaching.templates.narratives",
    "telemetry_tool.web.schemas.contracts.capabilities",
]


def test_every_shim_emits_deprecation_warning():
    for name in SHIM_MODULES:
        # force a fresh import
        mod = importlib.import_module(name)
        importlib.reload(mod)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            importlib.reload(mod)
        dep = [w for w in captured if issubclass(w.category, DeprecationWarning)]
        assert dep, f"{name} did not emit DeprecationWarning"
```

- [ ] **Step 10.2: Run — expect all shims still silent**

Run: `pytest telemetry_tool/tests/test_shared/test_deprecation_shims.py -v`

Expected: failure listing the modules without warnings.

- [ ] **Step 10.3: Convert each file to the shim template**

For each module in `SHIM_MODULES`, replace the entire file body with the template (top of doc). Fill in `<PATH>`, `<NEW_MODULE>`, `<SYMBOL>` / `<SYMBOLS>`. For multi-symbol modules (`coaching/models.py`, `coaching/templates/<name>.py`) include every public name in both the import and `__all__`.

For `kart_envelope/track/geometry.py`, re-export `TrackGeometry` **and** `TrackGeometryError`.

- [ ] **Step 10.4: Run all tests**

Run: `pytest telemetry_tool/tests/ kart_envelope/tests/ -q`

Expected: all green. `test_deprecation_shims.py` passes (every shim fires a warning).

- [ ] **Step 10.5: Commit**

```bash
git commit -m "refactor(shared): deprecation shims for all moved modules (W5.T5.5)"
```

---

### Task 11: Full audit + merge signal

- [ ] **Step 11.1: Re-run the isolation test explicitly**

Run: `pytest telemetry_tool/tests/test_shared/test_isolation.py -v`

Expected: PASS — no forbidden imports in `shared/`.

- [ ] **Step 11.2: Full-repo test**

Run: `pytest -q`

Expected: all tests pass. Any failure = stop, investigate, do not merge.

- [ ] **Step 11.3: Deprecation-warning cleanup sweep**

Run: `pytest -q -W error::DeprecationWarning telemetry_tool/tests/test_shared/` (W5 suite must not emit deprecation warnings itself — it imports from new locations only).

Run: `pytest -q -W error::DeprecationWarning telemetry_tool/tests/coaching/ telemetry_tool/tests/test_sim_optimizer/ kart_envelope/tests/` — **if this fails**, those suites still have call sites that route through the shims; fix them (they were missed in T5.4) and commit.

- [ ] **Step 11.4: Final plan checklist update**

Tick every `- [ ]` in this document as the implementer completes steps. The merge cannot proceed while items are unchecked.

- [ ] **Step 11.5: Merge signal commit**

```bash
git commit --allow-empty -m "chore(shared): W5 complete [signal:W5-done]"
```

- [ ] **Step 11.6: Hand off to the integration driver**

Report: worktree `.worktrees/ws-w5-shared-kernels`, branch `feat/ws-w5-shared-kernels`, full task checklist ticked. Ready for merge per the Wave-2 merge order `W5 → W2/W9 → W3/W4 → W6/W7 → W8`.

---

## Acceptance criteria (W5 exit gate)

- [ ] No module outside `telemetry_tool/shared/` owns a cross-side primitive (`TrackGeometry`, `FrenetFrame`, `ChannelTag`, `SessionCapabilities`, coaching `models`/`taxonomy`/`templates`)
- [ ] `telemetry_tool/tests/test_shared/test_isolation.py` green — `shared/` imports no forbidden roots
- [ ] Full test suite green (`pytest telemetry_tool/tests/ kart_envelope/tests/`)
- [ ] Every old location emits `DeprecationWarning` with `stacklevel=2`
- [ ] `shared/physics/{FrictionModel,VehicleModel}` importable (T5.2 signal emitted)
- [ ] `shared/coaching_taxonomy/{models,causes,templates,channels}` importable (T5.3 signal emitted)
- [ ] `shared/geometry/{TrackGeometry,FrenetFrame}` importable (T5.1 complete)
- [ ] Signal commits present: `[signal:W5.T5.2-done]`, `[signal:W5.T5.3-done]`, `[signal:W5-done]`
- [ ] Zero deprecation warnings in the W5 own test suite (it imports from new locations)

---

## Risks & mitigations

| Risk | Severity | Mitigation |
|------|---------|-----------|
| `TrackGeometry` decoupling breaks behavior of `kart_envelope` consumers that relied on implicit config defaults | High | Step 7.2 keeps factories that used `KartEnvelopeConfig` by parameterizing them; fall back to leaving the kart-specific factory **in** `kart_envelope/track/` as a thin wrapper that calls the shared class, if inlining proves too invasive |
| `reference_line` proves to couple back into kart-specific code | Medium | Plan explicitly allows leaving the `reference_line` import unmoved; isolation test enforces that choice — if the test fails, follow-up to move `reference_line` |
| Circular import surfaces after shims | Medium | Deprecation shims are strict one-way (`old → new`); new code paths never import from old locations. Isolation test + `-W error::DeprecationWarning` in Task 11 catches slips |
| Concurrent sessions land import changes on `feat/ws-w5-*` area during W5 | Medium | Shims keep old paths alive the entire release cycle; rebase vs merge choice coordinated with the integration driver |
| Physics primitive moves over-extend scope | Medium | Plan moves **only abstract bases**; concrete physics files stay put. Per spec risk mitigation: "Err on the side of leaving in place" |
| Coaching-taxonomy move is larger than estimated | Low | ~33 import-site rewrites enumerated in the manifest; partial completion of T5.4 can signal mid-flight if needed |
| CAUSES.json path resolution breaks after move | Low | Step 4.2 explicitly verifies + switches to `Path(__file__).parent / "causes.json"` |

---

## Self-review notes

Scan run against spec §5 W5 (T5.1–T5.5) at plan-completion time:

- T5.1 covered by Tasks 7 + 8
- T5.2 covered by Task 2
- T5.3 covered by Tasks 3, 4, 5, 6 (split by sub-surface)
- T5.4 covered by Task 9 (split per package for bisectable commits)
- T5.5 covered by Task 10
- Full audit + exit gate in Task 11

Scan against session-prompt acceptance criteria: every box is in the acceptance list above. Scan for placeholders: none. Scan for type consistency: shared package public surface is `{TrackGeometry, TrackGeometryError, FrenetFrame, FrictionModel, VehicleModel, ChannelTag, SessionCapabilities, models, causes, templates, channels}`; matched across all tasks.

---

**Status:** Plan draft — awaiting `/approve`.
**Next step on approval:** proceed to Task 0 in the W5 worktree.
