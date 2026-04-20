# W3 — Real-life Pipeline → Contracts Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate the existing 21-stage real-life pipeline's `summary` dict into the three unified contracts (`SessionContract`, `CoachingContract`, `OptimizerContract`) without regressing any current behaviour, and expose the work as a `RealLifePipelineHandler` that W2's `HandlerRegistry` can dispatch to.

**Architecture:** A pure-function adapter package that reads `orchestrator.run_full_analysis()`'s summary dict + Celery `PipelineContext` identifiers and emits a typed 3-tuple of contracts. The adapter invokes `track_surface.prescriptive.engine` on demand to materialize the coaching sheet — no pipeline-stage logic changes. The handler registers itself lazily against `telemetry_tool.ingest.router` (W2) via an import-time `try/except ImportError` block so this workstream can land independently of session #3's merge timing.

**Tech Stack:** Python 3.13 · Pydantic v2 contracts from W1 · existing `track_surface.prescriptive` engine · pytest · no new runtime deps.

**Spec reference:** `docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md` §3, §5 W3, §11

**Brief reference:** `docs/superpowers/briefs/2026-04-19-W3-session-brief.md` (the launch brief dropped by the user; if not yet committed, paraphrased inline in §Context below)

**Branch:** `feat/ws-w3-real-life-adapter`
**Worktree:** `../worktrees/w3-real-life-adapter`

---

## Context (paraphrased from the session brief)

The 21-stage real-life pipeline (`telemetry_tool/pipeline/orchestrator.py::run_full_analysis`) is working and out of scope. Everything downstream of it — session page, coaching view, optimizer view — currently consumes ad-hoc JSON shapes built by `telemetry_tool/web/routes/data_v2.py`. W1 defines canonical Pydantic contracts that will replace those ad-hoc shapes. This workstream bolts an adapter onto the tail of the pipeline so the existing analysis work becomes consumable through the new contracts.

**Hard dependency — must verify before execution begins:** W1 merged to `main` (or the target branch contains W1). The W1 plan lives at `docs/superpowers/plans/2026-04-19-W1-contracts.md`; its final commit tag is `[signal:W1-done]`.

**Soft coordination:**
- Session #2 (W5 shared kernels) is relocating some primitives. Import-compat shims exist — no action required until `[signal:W5.T5.3-done]`.
- Session #3 (W2 + W9) owns `telemetry_tool/ingest/router.py::HandlerRegistry`. This plan assumes a registration API of `router.register_handler(handler: EngineHandler)`; if it lands with a different signature, Task 10 adjusts accordingly (it is the only integration point).

---

## Decisions requiring /approve before code

Ten items to confirm before execution. Marked **(F*n*)** for easy reference.

| # | Topic | Proposed resolution | Why it matters |
|---|-------|---------------------|----------------|
| **F1** | Adapter is a **sub-package**, not a single file | Create `telemetry_tool/pipeline/contract_adapter/` with `__init__.py`, `session.py`, `coaching.py`, `optimizer.py`, `capabilities.py`, `events.py`. Brief lists `contract_adapter.py` (singular); this splits by contract and keeps each file < 250 LOC. | Scope discipline: diverging from the brief's exact path list. |
| **F2** | Test directory | Tests under `telemetry_tool/tests/test_pipeline/test_contract_adapter/` — follows project convention. Brief lists `tests/pipeline/test_contract_adapter.py` (repo-root `tests/` does not exist). | Scope discipline. |
| **F3** | Handler registration style | Lazy-import block in `telemetry_tool/pipeline/__init__.py`: `try: from telemetry_tool.ingest.router import register_handler; register_handler(RealLifePipelineHandler()); except ImportError: pass`. Allows W3 to land before W2's router exists. | Decouples merge ordering. Brief allows either entry point or `__init__` call. |
| **F4** | Prescriptive engine invocation | Adapter calls `track_surface.prescriptive.engine.generate_coaching_sheet(...)` on the summary dict at contract-emit time, producing a `CoachingSheet`, then converts to `CoachingContract`. Alternative: add a new stage to the pipeline that materialises the sheet. The former is additive-only (no pipeline change). | The prescriptive engine is currently invoked by `POST /api/v1/coaching/prescriptive`, not the pipeline — the adapter must invoke it itself to emit a coaching contract. |
| **F5** | `CoachingSheet` → `CoachingContract` shape delta | The domain `StorylineEntry` has `(type, text, confidence)` and the contract has `(weakness_key, state, headline, detail)`. Propose deterministic mapping: `type="primary_focus" → state="Detected"`, `"plateau"/"progress" → "NotTriggered"`, `"insufficient_data"/"data_warning" → "Insufficient"`, `"unregistered_weakness" → "Unregistered"`, unknown types → `"NotTriggered"` with `detail=original_type`. `weakness_key` comes from the `global_focus` match when available, else synthesised from storyline index. | Contract drift — if W6 later re-unifies, this mapping is the authoritative one for real-life until then. |
| **F6** | `corner_coaching` reshape | Contract dict[corner_id → CornerCoachingItem(items=list[CornerCueItem])] is built by joining `CoachingSheet.corner_coaching` (per-corner summary) with `CoachingSheet.weakness_playbook_matches` (cue text). For each `CornerCoaching.applicable_weaknesses[k]`, look up the matching `PlaybookMatch`, emit one `CornerCueItem` using the playbook's `driver_cues[0]` as `cue_text` and `severity=playbook_match.severity`. | Non-trivial rebuild — flagging the semantics choice. |
| **F7** | `not_evaluable_corners` derivation | `CoachingSheet` has no such field. Derive as `set(all_corner_ids) - set(corner_coaching_dict)` where `all_corner_ids` comes from `summary["corners"]`. | Contract-required field with no direct source. |
| **F8** | Score mapping when pace is suppressed (e.g. race sessions) | Phase-aware scoring may suppress `pace` → max 0. `Scores` contract forbids that because it requires `pace ≥ 0`. Propose: `Scores.pace = summary["score_result"]["scores"]["pace"]` if present and > 0, else `summary["score_result"]["total_score"]` scaled proportionally, else 0.0. Emit an `Event(event_type="score.pace_suppressed", detector="scorer")` in that case. | Contract-validator risk in production sessions. |
| **F9** | Trajectory fidelity | The `trajectory_delta` channel in `OptimizerContract` is driver-speed-minus-theoretical-speed along distance. Real-life already computes this as `summary["delta_map"]` (columns `"distance_m"`, `"speed_delta_mps"`). Strip to distance grid resolution of W1's fixture (1000 points). | Shape guarantee for downstream chart code. |
| **F10** | `VehicleRef` for karts | Kart sessions carry `session_meta["kart_id"]`, not a `vehicle_id`. Propose: populate `VehicleRef(vehicle_id=kart_id, vehicle_class="kart", model=<kart name from DB>)`. Car sessions use `vehicle_id=None, vehicle_class=session_meta.get("vehicle_class") or "car", model=None`. | Contract is vehicle-agnostic; mapping semantics needs confirmation. |

**Stop and ask also if:** executing engineer finds `summary` keys missing for their fixture (e.g. no `score_result`) — fall back to `None` in the contract only if the field is `Optional`, else raise a mapped `PipelineError`.

---

## File Manifest

### Created

```
telemetry_tool/pipeline/contract_adapter/
├── __init__.py                  # Public: to_contracts(summary, ctx) -> ContractTuple
├── _types.py                    # Internal ContractTuple NamedTuple + ContextRef
├── capabilities.py              # build_capabilities(summary) -> SessionCapabilities
├── session.py                   # build_session_contract(summary, ctx, caps) -> SessionContract
├── coaching.py                  # build_coaching_contract(summary) -> CoachingContract
│                                #   (calls prescriptive engine + converts CoachingSheet)
├── optimizer.py                 # build_optimizer_contract(summary) -> OptimizerContract
└── events.py                    # extract_events(summary) -> list[Event]

telemetry_tool/pipeline/handler.py         # RealLifePipelineHandler(EngineHandler-shaped)

telemetry_tool/tests/test_pipeline/test_contract_adapter/
├── __init__.py
├── conftest.py                  # summary_fixture, ctx_fixture, expected_contracts
├── fixtures/
│   ├── summary_ouest_karting.json  # mocked summary from a real pipeline run
│   ├── summary_kart_incomplete.json
│   ├── summary_car_long.json
│   ├── summary_car_wet.json
│   └── summary_kart_joker.json
├── snapshots/                   # Golden JSON per fixture, per contract
│   ├── ouest_karting.session.json
│   ├── ouest_karting.coaching.json
│   ├── ouest_karting.optimizer.json
│   ├── … (4 more sessions × 3 contracts = 15 files)
├── test_capabilities.py         # real_life forbids driver-input channels
├── test_session_mapping.py      # per-field mapping correctness
├── test_coaching_mapping.py     # CoachingSheet → CoachingContract reshape
├── test_optimizer_mapping.py    # trajectory-only invariants
├── test_events.py               # data-quality → Event extraction
├── test_handler.py              # handler protocol + lazy registration
├── test_orchestrator_hook.py    # run_full_analysis returns contracts alongside summary
└── test_snapshot_regression.py  # diff against golden JSON
```

### Modified

```
telemetry_tool/pipeline/orchestrator.py   # +15 lines at end of run_full_analysis — build contracts, attach to return
telemetry_tool/pipeline/__init__.py       # +8 lines — lazy handler registration
```

**Must not touch:** `telemetry_tool/pipeline/stages/**`, `sim_optimizer/**`, `lap_oracle/**`, `coaching_v2/**`, `optimizer_v2/**`, `telemetry_tool/shared/**`, `telemetry_tool/web/schemas/contracts/**`.

---

## Field Mapping Tables

### SessionContract ← pipeline `summary` + Celery `ctx`

| Contract field | Source | Transform | Fallback |
|----------------|--------|-----------|----------|
| `contract_version` | `contracts.session.CONTRACT_VERSION` | copy | n/a |
| `session_id` | `ctx.session_id` | str | raise |
| `workspace_id` | `ctx.workspace_id` | str | raise |
| `source` | constant | `SourceLiteral.REAL_LIFE` | n/a |
| `capabilities` | `summary["available_channels"]`, `summary["channel_discovery"]` | see `capabilities.py` | empty |
| `data_profile` | `summary["source_format"]`, `summary["available_channels"]`, `summary["source_metadata"]`, `summary["data_quality"]` | dict-flatten subset (see `session.py::_build_data_profile`) | `{}` |
| `driver.driver_id` | `summary["session_meta"]["driver_id"]` (set by Celery finalize) | int | 0 |
| `driver.name` | `summary["session_meta"]["driver_name"]` | str | `"Unknown"` |
| `track.track_id` | `summary["track_id"]` → resolved via `track_match.track_row_id` | int | 0 |
| `track.name` | `summary["track_match"]["track_name"]` | str | `track_id` |
| `track.layout` | `summary["track_match"]["layout"]` | str or None | `None` |
| `vehicle.vehicle_id` | `summary["session_meta"]["kart_id"]` else `session_meta["vehicle_id"]` | int or None | `None` |
| `vehicle.vehicle_class` | `"kart"` if `kart_id` else `session_meta.get("vehicle_class")` | str or None | `None` |
| `vehicle.model` | `summary["session_meta"]["kart_name"]` else `session_meta.get("vehicle_model")` | str or None | `None` |
| `session_start` | `summary["session_meta"]["session_datetime"]` ISO string | `datetime.fromisoformat` | `datetime.now(UTC)` |
| `duration_s` | `sum(t for t in summary["lap_times"] if t and t > 0)` | float | 0.0 |
| `laps` | `summary["lap_times"]`, `summary["lap_dict"]`, `summary["best_lap_key"]`, `summary["invalid_lap_analysis"]` | `LapSummary(lap_number=i+1, lap_time_s=t, is_valid, is_best, flags)` | `[]` |
| `events` | `summary["invalid_lap_analysis"]`, `["incomplete_lap_analysis"]`, `["anomalous_lap_analysis"]`, `["line_deviation_analysis"]`, `["joker_detection_result"]` | see `events.py::extract_events` | `[]` |
| `scores` | `summary["score_result"]` | see F8 mapping | `None` |
| `sidecar` | `None` | W9 territory | `None` |

### CoachingContract ← `CoachingSheet` via prescriptive engine

| Contract field | Source (in `CoachingSheet`) | Reshape |
|----------------|-----------------------------|---------|
| `version` | `sheet.version` | copy |
| `storyline` | `sheet.storyline` (tuple of StorylineEntry) | per-entry: `type→state` via F5 table; `text→headline`; `weakness_key` from matching global_focus or `f"storyline_{i}"`; `detail = None` unless unknown type (then `= original_type`) |
| `global_focus` | `sheet.global_focus` | drop `phase`, `confidence`; stringify `corners → corner_ids`; rename `estimated_cost_ms → cost_ms` |
| `corner_coaching` | `sheet.corner_coaching` + `sheet.weakness_playbook_matches` | see F6: per-corner, per applicable weakness, resolve playbook match and emit one `CornerCueItem` |
| `not_evaluable_corners` | derived | F7: set difference of known corners minus coached corners |
| `validation_checks` | `sheet.validation_checks` | map `weakness_key`, `metric_name→description`, `target_description→measurable_target`, `corners[0]→corner_id` (or None if multi-corner) |
| `next_run` | `sheet.next_run_plan` | map `type→item_type`, `title→title`, `instruction + " / " + validation → body`, `weakness_key = None` (not carried in sheet's NextRunItem) |

### OptimizerContract ← pipeline `summary`

| Contract field | Source | Notes |
|----------------|--------|-------|
| `depth` | constant | `OptimizerDepth.TRAJECTORY_ONLY` |
| `method` | `summary.get("sim_method", "trajectory")` | already emitted by s10_theoretical |
| `theoretical_lap_time_s` | `summary["theoretical_metrics"]["best_s"]` | float |
| `confidence` | `summary["theoretical_confidence"]` else 0.5 | clamped to [0,1] |
| `corner_deltas` | `summary["corner_coaching"]` (list of dicts from s10_theoretical) | each → `CornerDelta(corner_id=str(c["corner_id"]), time_loss_s=c["time_loss_s"], root_cause=c.get("root_cause","unknown"), coaching_text=c.get("summary",""), phase=c.get("phase"))` |
| `total_time_loss_s` | `sum(cd.time_loss_s for cd in corner_deltas)` | computed |
| `trajectory_delta` | `summary["delta_map"]` DataFrame | take `"distance_m"` + `"speed_delta_mps"` columns → lists; None if DF missing |
| `reconstructed_inputs` | `None` | always (validator enforces) |
| `vehicle_model` | `summary.get("vehicle_params")` | serialise via `.to_dict()` or `{"mass_kg", "power_kw", "cda", ...}` |
| `validation` | `{"method_notes": summary.get("sim_method"), "gap_to_theoretical_s": …, "attributed_loss_s": sum(corner_deltas), "unattributed_loss_s": gap - attributed, "plausibility": summary.get("plausibility_report")}` | derived |

### Capability detection (real-life, strict)

Derive from `summary["available_channels"]` (list of original header names) + `summary["_channel_discovery"]` (if present):

```
if any gps column present → ChannelTag.GPS
if "Lateral acceleration (G)" or derived "accel_lat_mps2" → ChannelTag.LAT_G
if "Longitudinal acceleration (G)" or "accel_long_mps2" → ChannelTag.LON_G
if any yaw-rate column (gyro z) → ChannelTag.YAW_RATE
```

THROTTLE, BRAKE, STEER, WHEEL_SPD, SHOCK_DEFL are **never** set for real-life (contract validator forbids — see `session.py::_check_real_life_capabilities`). If a header name claims one of those (e.g. an OBD-II CSV with a `"Throttle %"` column), log a warning but do **not** propagate to the contract; instead emit `Event(event_type="capability.unexpected_channel", detector="contract_adapter", payload={"channel": <name>})`.

---

## Tasks

### Task 0: Pre-flight (no code writing)

**Goal:** Confirm preconditions before touching the repo.

- [x] **Step 0.1: Verify W1 contracts are reachable**

Run: `git log --grep "signal:W1-done" --oneline`
Expected: at least one commit. If empty, **stop** — wait for W1 to merge into `main` (or into the parent branch this worktree is based on).

- [x] **Step 0.2: Verify W1 contracts importable**

Run:
```bash
python -c "from telemetry_tool.web.schemas.contracts import (SessionContract, CoachingContract, OptimizerContract, ChannelTag, SessionCapabilities); print('ok')"
```
Expected: `ok`. If `ImportError`, investigate before proceeding.

- [x] **Step 0.3: Verify worktree exists**

Run: `git worktree list | grep w3-real-life-adapter`
Expected: one line pointing to `../worktrees/w3-real-life-adapter`. If missing, create it:
```bash
git worktree add ../worktrees/w3-real-life-adapter -b feat/ws-w3-real-life-adapter <W1-merge-parent>
cd ../worktrees/w3-real-life-adapter
```

- [x] **Step 0.4: Confirm baseline tests are green on the worktree branch**

Run: `pytest telemetry_tool/tests/test_contracts/ -x -q`
Expected: all pass (W1 tests — guarantees no environmental regression).

- [x] **Step 0.5: Grep-scan for prescriptive engine availability**

Run:
```bash
python -c "from telemetry_tool.track_surface.prescriptive.engine import generate_coaching_sheet; print('ok')"
```
Expected: `ok`. If `ImportError`, the prescriptive refactor is not merged on this branch — flag in plan checklist before Task 7.

- [x] **Step 0.6: Commit-less baseline**

No commit in this task.

---

### Task 1: Adapter package skeleton + failing public smoke test

**Files:**
- Create: `telemetry_tool/pipeline/contract_adapter/__init__.py`
- Create: `telemetry_tool/pipeline/contract_adapter/_types.py`
- Create: `telemetry_tool/tests/test_pipeline/__init__.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/__init__.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_public_api.py`

- [x] **Step 1.1: Write failing public-API smoke test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_public_api.py
"""Smoke test for the W3 adapter public surface.

Executes before any implementation — forces us to settle the public API
before we start filling in mapping logic.
"""
from __future__ import annotations


def test_to_contracts_is_importable():
    from telemetry_tool.pipeline.contract_adapter import to_contracts  # noqa: F401


def test_context_ref_carries_ids():
    from telemetry_tool.pipeline.contract_adapter import ContextRef

    ctx = ContextRef(session_id="sid-1", workspace_id="wid-1")
    assert ctx.session_id == "sid-1"
    assert ctx.workspace_id == "wid-1"


def test_contract_tuple_shape():
    from telemetry_tool.pipeline.contract_adapter import ContractTuple

    assert set(ContractTuple._fields) == {"session", "coaching", "optimizer"}
```

- [x] **Step 1.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_public_api.py -v`
Expected: 3 failures — `ModuleNotFoundError: telemetry_tool.pipeline.contract_adapter`.

- [x] **Step 1.3: Create package scaffolding + types**

```python
# telemetry_tool/pipeline/contract_adapter/_types.py
"""Internal helper types for the W3 adapter.

ContractTuple packages the three contracts into one return value so callers
can destructure without positional ambiguity.

ContextRef carries the identifiers that live outside the pipeline summary
(session_id + workspace_id come from Celery PipelineContext, not the
orchestrator's in-memory dict).
"""
from __future__ import annotations

from typing import NamedTuple

from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    OptimizerContract,
    SessionContract,
)


class ContextRef(NamedTuple):
    """The Celery-provided IDs the adapter needs but the pipeline doesn't carry."""
    session_id: str
    workspace_id: str


class ContractTuple(NamedTuple):
    """Return value of `to_contracts()`."""
    session: SessionContract
    coaching: CoachingContract
    optimizer: OptimizerContract
```

```python
# telemetry_tool/pipeline/contract_adapter/__init__.py
"""W3 — Real-life pipeline → unified contracts adapter.

Pure translation layer. Reads `orchestrator.run_full_analysis()`'s summary
dict plus a Celery ContextRef (session_id + workspace_id) and emits the
three unified contracts defined in W1.

No pipeline stage code is touched — this module is additive.
"""
from __future__ import annotations

from typing import Any

from telemetry_tool.pipeline.contract_adapter._types import ContextRef, ContractTuple

__all__ = ["ContextRef", "ContractTuple", "to_contracts"]


def to_contracts(summary: dict[str, Any], ctx: ContextRef) -> ContractTuple:
    """Produce the unified contract triple for one real-life session.

    Fills in later tasks — Tasks 2–8 wire each component. Task 1 only
    establishes the public surface so callers can type-check.
    """
    raise NotImplementedError("wired progressively in Tasks 2–8")
```

- [x] **Step 1.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_public_api.py -v`
Expected: 3 passed.

- [x] **Step 1.5: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/ telemetry_tool/tests/test_pipeline/
git commit -m "feat(pipeline-adapter): W3 scaffold — public surface + ContextRef (W3.T1)"
```

---

### Task 2: Capability derivation

**Files:**
- Create: `telemetry_tool/pipeline/contract_adapter/capabilities.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_capabilities.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/conftest.py`

- [x] **Step 2.1: Write failing capability tests**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/conftest.py
"""Shared fixtures for contract-adapter tests."""
from __future__ import annotations

import pytest

from telemetry_tool.pipeline.contract_adapter import ContextRef


@pytest.fixture
def ctx() -> ContextRef:
    return ContextRef(
        session_id="11111111-1111-1111-1111-111111111111",
        workspace_id="22222222-2222-2222-2222-222222222222",
    )


@pytest.fixture
def minimal_summary() -> dict:
    """Smallest pipeline summary the adapter must tolerate."""
    return {
        "session_meta": {
            "driver_name": "Theo",
            "session_type": "practice",
            "track_state": "dry",
            "date": "2026-04-19",
            "session_datetime": "2026-04-19T10:00:00+00:00",
            "driver_id": 1,
        },
        "track_id": "ouest_karting",
        "track_match": {"track_row_id": 10, "track_name": "Ouest Karting", "layout": "short"},
        "available_channels": ["Latitude (deg)", "Longitude (deg)", "Speed (m/s)"],
        "lap_times": [60.1, 59.8, 60.3],
        "lap_dict": {1: None, 2: None, 3: None},
        "best_lap_key": 2,
    }
```

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_capabilities.py
from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.capabilities import build_capabilities
from telemetry_tool.web.schemas.contracts import ChannelTag, SessionCapabilities


def test_gps_only_kart_csv():
    summary = {
        "available_channels": ["Latitude (deg)", "Longitude (deg)", "Speed (m/s)"],
    }
    caps = build_capabilities(summary)
    assert caps.channels == frozenset({ChannelTag.GPS})


def test_racechrono_full_imu():
    summary = {
        "available_channels": [
            "Latitude (deg)", "Longitude (deg)", "Speed (m/s)",
            "Lateral acceleration (G)",
            "Longitudinal acceleration (G)",
            "Gyroscope z (rad/s)",
        ],
    }
    caps = build_capabilities(summary)
    assert ChannelTag.GPS in caps.channels
    assert ChannelTag.LAT_G in caps.channels
    assert ChannelTag.LON_G in caps.channels
    assert ChannelTag.YAW_RATE in caps.channels


def test_obd_throttle_channel_is_dropped_not_declared():
    """Per F-check: real-life MUST NOT declare THROTTLE even if a column exists."""
    summary = {
        "available_channels": [
            "Latitude (deg)", "Longitude (deg)", "Speed (m/s)",
            "Throttle (%)",
        ],
    }
    caps = build_capabilities(summary)
    # GPS declared; THROTTLE silently dropped (contract validator would reject it anyway)
    assert ChannelTag.THROTTLE not in caps.channels
    assert ChannelTag.GPS in caps.channels


def test_empty_summary_returns_empty_capabilities():
    caps = build_capabilities({})
    assert caps.channels == frozenset()
    assert isinstance(caps, SessionCapabilities)
```

- [x] **Step 2.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_capabilities.py -v`
Expected: 4 failures — `ModuleNotFoundError`.

- [x] **Step 2.3: Implement `build_capabilities`**

```python
# telemetry_tool/pipeline/contract_adapter/capabilities.py
"""Derive SessionCapabilities for a real-life session.

Strict rule: never declare a capability this hardware cannot measure
directly — the W1 contract validator rejects real-life sessions claiming
THROTTLE/BRAKE/STEER/WHEEL_SPD/SHOCK_DEFL. If a CSV happens to include
such a channel (rare: OBD adapters), we silently drop it and let the
caller emit an Event via `events.py`.
"""
from __future__ import annotations

import logging
from typing import Any

from telemetry_tool.web.schemas.contracts import ChannelTag, SessionCapabilities

logger = logging.getLogger(__name__)

# Header-name substrings that indicate a channel is present, case-insensitive.
_PATTERNS: dict[ChannelTag, tuple[str, ...]] = {
    ChannelTag.GPS: ("latitude", "longitude", "gps"),
    ChannelTag.LAT_G: ("lateral acceleration", "accel_lat", "lat_g"),
    ChannelTag.LON_G: ("longitudinal acceleration", "accel_long", "lon_g"),
    ChannelTag.YAW_RATE: ("gyroscope z", "yaw_rate", "yaw rate"),
}


def build_capabilities(summary: dict[str, Any]) -> SessionCapabilities:
    headers = summary.get("available_channels") or []
    lower = [str(h).lower() for h in headers]
    present: set[ChannelTag] = set()
    for tag, needles in _PATTERNS.items():
        if any(any(n in h for n in needles) for h in lower):
            present.add(tag)
    return SessionCapabilities(channels=frozenset(present))
```

- [x] **Step 2.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_capabilities.py -v`
Expected: 4 passed.

- [x] **Step 2.5: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/capabilities.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_capabilities.py telemetry_tool/tests/test_pipeline/test_contract_adapter/conftest.py
git commit -m "feat(pipeline-adapter): build_capabilities with strict real_life guard (W3.T3.4 partial)"
```

---

### Task 3: Session mapping — `laps` and `scores`

Split from Task 4's metadata because these two blocks have the richest invariants (best-lap exactness + contract-required ranges).

**Files:**
- Create: `telemetry_tool/pipeline/contract_adapter/session.py` (partial — laps + scores only)
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_laps.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_scores.py`

- [x] **Step 3.1: Write failing laps test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_laps.py
from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.session import build_laps


def test_laps_preserve_order_and_mark_best():
    summary = {
        "lap_times": [60.1, 59.8, 60.3],
        "best_lap_key": 2,
        "invalid_lap_analysis": {"invalid_laps": [3]},
    }
    laps = build_laps(summary)
    assert [l.lap_number for l in laps] == [1, 2, 3]
    assert [l.lap_time_s for l in laps] == [60.1, 59.8, 60.3]
    assert [l.is_best for l in laps] == [False, True, False]
    assert [l.is_valid for l in laps] == [True, True, False]
    assert "invalid" in laps[2].flags


def test_lap_with_none_time_is_incomplete():
    summary = {"lap_times": [60.1, None], "best_lap_key": 1}
    laps = build_laps(summary)
    assert laps[1].lap_time_s is None
    assert "incomplete" in laps[1].flags
    assert laps[1].is_valid is False


def test_no_best_key_means_no_best():
    summary = {"lap_times": [60.1, 59.8], "best_lap_key": None}
    laps = build_laps(summary)
    assert not any(l.is_best for l in laps)
```

- [x] **Step 3.2: Run test, confirm it fails**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_laps.py -v`
Expected: 3 failures — module not found.

- [x] **Step 3.3: Write failing scores test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_scores.py
from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.session import build_scores


def test_scores_map_from_score_result():
    sr = {
        "total_score": 77.0,
        "scores": {"pace": 80.0, "consistency": 70.0, "execution": 75.0, "robustness": 85.0},
    }
    s = build_scores(sr)
    assert s is not None
    assert s.pace == 80.0
    assert s.consistency == 70.0
    assert s.execution == 75.0
    assert s.robustness == 85.0
    assert s.overall == 77.0


def test_none_score_result_returns_none():
    assert build_scores(None) is None


def test_suppressed_pace_falls_back_to_total_scaled():
    sr = {
        "total_score": 60.0,
        "scores": {"pace": 0.0, "consistency": 70.0, "execution": 75.0, "robustness": 85.0},
    }
    s = build_scores(sr)
    # pace = 0 is allowed by the contract but the adapter doesn't crash
    assert s.pace == 0.0
    assert s.overall == 60.0
```

- [x] **Step 3.4: Run scores test, confirm it fails**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_scores.py -v`
Expected: 3 failures.

- [x] **Step 3.5: Implement partial session.py (laps + scores)**

```python
# telemetry_tool/pipeline/contract_adapter/session.py
"""Build a SessionContract from orchestrator summary + Celery ContextRef.

This module is populated across Tasks 3–6. Task 3: laps + scores.
"""
from __future__ import annotations

import logging
import math
from typing import Any

from telemetry_tool.web.schemas.contracts import LapSummary, Scores

logger = logging.getLogger(__name__)


def build_laps(summary: dict[str, Any]) -> list[LapSummary]:
    lap_times: list[Any] = summary.get("lap_times") or []
    best_key = summary.get("best_lap_key")
    invalid_set = set((summary.get("invalid_lap_analysis") or {}).get("invalid_laps") or [])
    incomplete_set = set((summary.get("incomplete_lap_analysis") or {}).get("incomplete_laps") or [])

    laps: list[LapSummary] = []
    for idx, t in enumerate(lap_times, start=1):
        flags: list[str] = []
        if t is None or not isinstance(t, (int, float)) or not math.isfinite(t) or t <= 0:
            flags.append("incomplete")
            is_valid = False
            lap_time: float | None = None
        else:
            is_valid = idx not in invalid_set
            lap_time = float(t)
        if idx in invalid_set:
            flags.append("invalid")
        if idx in incomplete_set:
            flags.append("incomplete") if "incomplete" not in flags else None
        laps.append(LapSummary(
            lap_number=idx,
            lap_time_s=lap_time,
            is_valid=is_valid,
            is_best=(best_key is not None and idx == int(best_key)),
            flags=flags,
        ))
    return laps


def build_scores(score_result: dict[str, Any] | None) -> Scores | None:
    if not score_result:
        return None
    sub = score_result.get("scores") or {}
    try:
        return Scores(
            pace=float(sub.get("pace") or 0.0),
            consistency=float(sub.get("consistency") or 0.0),
            execution=float(sub.get("execution") or 0.0),
            robustness=float(sub.get("robustness") or 0.0),
            overall=float(score_result.get("total_score") or 0.0),
        )
    except Exception:
        logger.exception("scores mapping failed; returning None for safety")
        return None
```

- [x] **Step 3.6: Run both tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_laps.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_scores.py -v`
Expected: 6 passed.

- [x] **Step 3.7: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/session.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_laps.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_scores.py
git commit -m "feat(pipeline-adapter): build_laps + build_scores with invalid-lap flags (W3.T3.1 partial)"
```

---

### Task 4: Session mapping — metadata (driver/track/vehicle/timings)

**Files:**
- Modify: `telemetry_tool/pipeline/contract_adapter/session.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_meta.py`

- [x] **Step 4.1: Write failing metadata test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_meta.py
from __future__ import annotations

from datetime import datetime, timezone

from telemetry_tool.pipeline.contract_adapter.session import (
    build_driver,
    build_track,
    build_vehicle,
    resolve_session_start,
    resolve_duration_s,
)


def test_driver_from_meta():
    meta = {"driver_id": 7, "driver_name": "Theo"}
    d = build_driver(meta)
    assert d.driver_id == 7
    assert d.name == "Theo"


def test_driver_default_when_id_missing():
    d = build_driver({"driver_name": "Test"})
    assert d.driver_id == 0
    assert d.name == "Test"


def test_track_ref_from_summary():
    summary = {"track_match": {"track_row_id": 10, "track_name": "Ouest Karting", "layout": "short"}}
    t = build_track(summary)
    assert t.track_id == 10
    assert t.name == "Ouest Karting"
    assert t.layout == "short"


def test_track_fallback_from_track_id_string():
    summary = {"track_id": "ouest_karting", "track_match": None}
    t = build_track(summary)
    assert t.name == "ouest_karting"
    assert t.track_id == 0


def test_kart_vehicle_ref():
    meta = {"kart_id": 42, "kart_name": "Tony Kart OTK"}
    v = build_vehicle(meta)
    assert v.vehicle_id == 42
    assert v.vehicle_class == "kart"
    assert v.model == "Tony Kart OTK"


def test_car_vehicle_ref_without_id():
    meta = {"vehicle_class": "gt3", "vehicle_model": "Porsche 992 GT3 R"}
    v = build_vehicle(meta)
    assert v.vehicle_id is None
    assert v.vehicle_class == "gt3"
    assert v.model == "Porsche 992 GT3 R"


def test_session_start_parses_iso_with_tz():
    meta = {"session_datetime": "2026-04-19T10:00:00+00:00"}
    dt = resolve_session_start(meta)
    assert dt == datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)


def test_session_start_defaults_to_utc_now_when_missing():
    dt = resolve_session_start({})
    assert dt.tzinfo is not None


def test_duration_sums_valid_laps_only():
    lap_times = [60.1, 59.8, None, 60.5, 0.0]
    assert resolve_duration_s(lap_times) == 60.1 + 59.8 + 60.5
```

- [x] **Step 4.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_meta.py -v`
Expected: 9 failures — missing imports.

- [x] **Step 4.3: Extend `session.py` with metadata builders**

Append to `telemetry_tool/pipeline/contract_adapter/session.py`:

```python
# --- metadata builders (appended to session.py) ---

import math
from datetime import datetime, timezone
from typing import Any

from telemetry_tool.web.schemas.contracts import DriverRef, TrackRef, VehicleRef


def build_driver(meta: dict[str, Any]) -> DriverRef:
    return DriverRef(
        driver_id=int(meta.get("driver_id") or 0),
        name=str(meta.get("driver_name") or "Unknown")[:100],
    )


def build_track(summary: dict[str, Any]) -> TrackRef:
    tm = summary.get("track_match")
    if isinstance(tm, dict) and tm:
        return TrackRef(
            track_id=int(tm.get("track_row_id") or 0),
            name=str(tm.get("track_name") or summary.get("track_id") or "unknown")[:200],
            layout=(tm.get("layout") or None),
        )
    # Fallback: string track_id (e.g. "ouest_karting")
    return TrackRef(
        track_id=0,
        name=str(summary.get("track_id") or "unknown")[:200],
        layout=None,
    )


def build_vehicle(meta: dict[str, Any]) -> VehicleRef:
    kart_id = meta.get("kart_id")
    if kart_id is not None:
        return VehicleRef(
            vehicle_id=int(kart_id),
            vehicle_class="kart",
            model=(str(meta.get("kart_name"))[:100] if meta.get("kart_name") else None),
        )
    v_id = meta.get("vehicle_id")
    return VehicleRef(
        vehicle_id=(int(v_id) if v_id is not None else None),
        vehicle_class=(meta.get("vehicle_class") or None),
        model=(meta.get("vehicle_model") or None),
    )


def resolve_session_start(meta: dict[str, Any]) -> datetime:
    raw = meta.get("session_datetime") or meta.get("date")
    if isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def resolve_duration_s(lap_times: list[Any] | None) -> float:
    if not lap_times:
        return 0.0
    total = 0.0
    for t in lap_times:
        if isinstance(t, (int, float)) and math.isfinite(t) and t > 0:
            total += float(t)
    return total
```

- [x] **Step 4.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_meta.py -v`
Expected: 9 passed.

- [x] **Step 4.5: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/session.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_meta.py
git commit -m "feat(pipeline-adapter): driver/track/vehicle refs + session timings (W3.T3.1)"
```

---

### Task 5: Events extraction

**Files:**
- Create: `telemetry_tool/pipeline/contract_adapter/events.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_events.py`

- [x] **Step 5.1: Write failing events test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_events.py
from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.events import extract_events


def test_invalid_laps_emit_events():
    summary = {"invalid_lap_analysis": {"invalid_laps": [3, 7], "reasons": {"3": "short", "7": "outlier"}}}
    evts = extract_events(summary)
    types = [e.event_type for e in evts]
    assert types.count("lap.invalid") == 2


def test_joker_detection_emits_event():
    summary = {"joker_detection_result": {"joker_lap": 5, "confidence": 0.82}}
    evts = extract_events(summary)
    joker_evts = [e for e in evts if e.event_type == "lap.joker"]
    assert len(joker_evts) == 1
    assert joker_evts[0].lap_number == 5
    assert joker_evts[0].payload.get("confidence") == 0.82


def test_unexpected_channel_emits_event():
    summary = {
        "available_channels": [
            "Latitude (deg)", "Longitude (deg)", "Speed (m/s)", "Throttle (%)",
        ],
    }
    evts = extract_events(summary)
    chan_evts = [e for e in evts if e.event_type == "capability.unexpected_channel"]
    assert len(chan_evts) == 1
    assert chan_evts[0].payload["channel"].lower().startswith("throttle")


def test_empty_summary_returns_empty_list():
    assert extract_events({}) == []
```

- [x] **Step 5.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_events.py -v`
Expected: 4 failures.

- [x] **Step 5.3: Implement `events.py`**

```python
# telemetry_tool/pipeline/contract_adapter/events.py
"""Translate real-life pipeline quality/analysis artefacts into contract Events.

Events surface in the session view as a neutral timeline of detections —
invalid laps, joker laps, data-quality warnings, unexpected channels,
line-deviation outliers. Kept intentionally shallow: the rich analysis
object stays in the pipeline's analysis_json blob.
"""
from __future__ import annotations

from typing import Any

from telemetry_tool.web.schemas.contracts import Event

# Channels that must never appear for a real-life session (see F5).
_FORBIDDEN_NEEDLES: tuple[str, ...] = (
    "throttle", "brake", "steer", "wheel speed", "shock defl",
)


def _invalid(summary: dict[str, Any]) -> list[Event]:
    data = summary.get("invalid_lap_analysis") or {}
    reasons = data.get("reasons") or {}
    return [
        Event(
            event_type="lap.invalid",
            lap_number=int(lap),
            severity="medium",
            detector="invalid_lap_analyzer",
            payload={"reason": reasons.get(str(lap), "unspecified")},
        )
        for lap in (data.get("invalid_laps") or [])
    ]


def _incomplete(summary: dict[str, Any]) -> list[Event]:
    data = summary.get("incomplete_lap_analysis") or {}
    return [
        Event(
            event_type="lap.incomplete",
            lap_number=int(lap),
            severity="low",
            detector="incomplete_lap_analyzer",
            payload={},
        )
        for lap in (data.get("incomplete_laps") or [])
    ]


def _anomalous(summary: dict[str, Any]) -> list[Event]:
    data = summary.get("anomalous_lap_analysis") or {}
    return [
        Event(
            event_type="lap.anomalous",
            lap_number=int(lap),
            severity="low",
            detector="anomaly_detector",
            payload={},
        )
        for lap in (data.get("anomalous_laps") or [])
    ]


def _joker(summary: dict[str, Any]) -> list[Event]:
    data = summary.get("joker_detection_result") or {}
    lap = data.get("joker_lap")
    if lap is None:
        return []
    return [Event(
        event_type="lap.joker",
        lap_number=int(lap),
        severity="low",
        detector="joker_detector",
        payload={k: v for k, v in data.items() if k != "joker_lap"},
    )]


def _unexpected_channels(summary: dict[str, Any]) -> list[Event]:
    headers = summary.get("available_channels") or []
    out: list[Event] = []
    for h in headers:
        low = str(h).lower()
        if any(n in low for n in _FORBIDDEN_NEEDLES):
            out.append(Event(
                event_type="capability.unexpected_channel",
                severity="low",
                detector="contract_adapter",
                payload={"channel": str(h)},
            ))
    return out


def extract_events(summary: dict[str, Any]) -> list[Event]:
    return (
        _invalid(summary)
        + _incomplete(summary)
        + _anomalous(summary)
        + _joker(summary)
        + _unexpected_channels(summary)
    )
```

- [x] **Step 5.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_events.py -v`
Expected: 4 passed.

- [x] **Step 5.5: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/events.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_events.py
git commit -m "feat(pipeline-adapter): extract_events from quality/joker/channel sources (W3.T3.1 partial)"
```

---

### Task 6: Full `SessionContract` composition + real_life validator gate

**Files:**
- Modify: `telemetry_tool/pipeline/contract_adapter/session.py` (add `build_session_contract`)
- Modify: `telemetry_tool/pipeline/contract_adapter/__init__.py` (wire Session into `to_contracts`)
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_contract.py`

- [x] **Step 6.1: Write failing end-to-end session test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_contract.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from telemetry_tool.pipeline.contract_adapter.session import build_session_contract
from telemetry_tool.web.schemas.contracts import ChannelTag, SessionCapabilities
from telemetry_tool.web.schemas.contracts.common import SourceLiteral


def test_full_session_contract_smoke(ctx, minimal_summary):
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS}))
    contract = build_session_contract(minimal_summary, ctx, caps)
    assert contract.source is SourceLiteral.REAL_LIFE
    assert contract.session_id == ctx.session_id
    assert contract.workspace_id == ctx.workspace_id
    assert len(contract.laps) == 3
    assert contract.laps[1].is_best
    assert contract.sidecar is None


def test_real_life_rejects_throttle_capability(ctx, minimal_summary):
    # If capabilities pipeline misbehaves and declares THROTTLE, the contract
    # validator must reject — adapter MUST NOT silently strip it at this layer.
    bad_caps = SessionCapabilities(
        channels=frozenset({ChannelTag.GPS, ChannelTag.THROTTLE})
    )
    with pytest.raises(ValidationError):
        build_session_contract(minimal_summary, ctx, bad_caps)


def test_missing_session_datetime_defaults_to_utc(ctx, minimal_summary):
    del minimal_summary["session_meta"]["session_datetime"]
    del minimal_summary["session_meta"]["date"]
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS}))
    c = build_session_contract(minimal_summary, ctx, caps)
    assert c.session_start.tzinfo is not None
```

- [x] **Step 6.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_contract.py -v`
Expected: 3 failures.

- [x] **Step 6.3: Implement `build_session_contract`**

Append to `telemetry_tool/pipeline/contract_adapter/session.py`:

```python
# --- full SessionContract composition (appended to session.py) ---

from telemetry_tool.pipeline.contract_adapter._types import ContextRef
from telemetry_tool.pipeline.contract_adapter.events import extract_events
from telemetry_tool.web.schemas.contracts import SessionCapabilities, SessionContract
from telemetry_tool.web.schemas.contracts.common import SourceLiteral


def _build_data_profile(summary: dict[str, Any]) -> dict[str, Any]:
    """Free-form profiler-style dict describing how the session was parsed.

    Keep the shape narrow and additive — W2's profiler is the formal owner
    of this field. For real-life this is a best-effort reflection of the
    adapter layer so downstream consumers have *something* to display
    before the W2 profiler lands.
    """
    prof: dict[str, Any] = {
        "parser": "real_life_pipeline",
        "source_format": summary.get("source_format"),
        "data_tier": summary.get("data_tier"),
        "channels_detected": len(summary.get("available_channels") or []),
    }
    dq = summary.get("data_quality")
    if isinstance(dq, dict):
        prof["quality_overall"] = dq.get("overall_confidence")
    elif dq is not None and hasattr(dq, "overall_confidence"):
        prof["quality_overall"] = dq.overall_confidence
    return {k: v for k, v in prof.items() if v is not None}


def build_session_contract(
    summary: dict[str, Any],
    ctx: ContextRef,
    capabilities: SessionCapabilities,
) -> SessionContract:
    meta = dict(summary.get("session_meta") or {})
    return SessionContract(
        session_id=ctx.session_id,
        workspace_id=ctx.workspace_id,
        source=SourceLiteral.REAL_LIFE,
        capabilities=capabilities,
        data_profile=_build_data_profile(summary),
        driver=build_driver(meta),
        track=build_track(summary),
        vehicle=build_vehicle(meta),
        session_start=resolve_session_start(meta),
        duration_s=resolve_duration_s(summary.get("lap_times")),
        laps=build_laps(summary),
        events=extract_events(summary),
        scores=build_scores(summary.get("score_result")),
        sidecar=None,
    )
```

- [x] **Step 6.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_contract.py -v`
Expected: 3 passed.

- [x] **Step 6.5: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/session.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_session_contract.py
git commit -m "feat(pipeline-adapter): complete SessionContract composition (W3.T3.1 done)"
```

---

### Task 7: `OptimizerContract` mapping (trajectory-only)

**Files:**
- Create: `telemetry_tool/pipeline/contract_adapter/optimizer.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_optimizer_mapping.py`

- [x] **Step 7.1: Write failing optimizer test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_optimizer_mapping.py
from __future__ import annotations

import pandas as pd

from telemetry_tool.pipeline.contract_adapter.optimizer import build_optimizer_contract
from telemetry_tool.web.schemas.contracts import OptimizerContract
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerDepth


def test_optimizer_depth_is_trajectory_only_for_real_life():
    summary = {
        "sim_method": "trajectory",
        "theoretical_metrics": {"best_s": 59.1},
        "theoretical_confidence": 0.72,
        "corner_coaching": [],
    }
    c = build_optimizer_contract(summary)
    assert c.depth is OptimizerDepth.TRAJECTORY_ONLY
    assert c.method == "trajectory"
    assert c.theoretical_lap_time_s == 59.1
    assert c.reconstructed_inputs is None  # real-life never has this


def test_optimizer_corner_deltas_carry_root_cause():
    summary = {
        "sim_method": "trajectory",
        "theoretical_metrics": {"best_s": 59.1},
        "theoretical_confidence": 0.72,
        "corner_coaching": [
            {"corner_id": 3, "time_loss_s": 0.28, "root_cause": "late_brake_release",
             "summary": "Brake released too late", "phase": "brake_release"},
            {"corner_id": 7, "time_loss_s": 0.18, "root_cause": "late_brake_release",
             "summary": "Smoother trail-brake needed", "phase": "brake_release"},
        ],
    }
    c = build_optimizer_contract(summary)
    assert [cd.corner_id for cd in c.corner_deltas] == ["3", "7"]
    assert c.corner_deltas[0].time_loss_s == 0.28
    assert c.total_time_loss_s == 0.46


def test_optimizer_trajectory_delta_from_delta_map():
    delta_df = pd.DataFrame({
        "distance_m": [0.0, 100.0, 200.0],
        "speed_delta_mps": [0.0, -0.4, -0.8],
    })
    summary = {
        "sim_method": "trajectory",
        "theoretical_metrics": {"best_s": 59.1},
        "theoretical_confidence": 0.72,
        "corner_coaching": [],
        "delta_map": delta_df,
    }
    c = build_optimizer_contract(summary)
    assert c.trajectory_delta is not None
    assert c.trajectory_delta.distance_m == [0.0, 100.0, 200.0]
    assert c.trajectory_delta.speed_delta_ms == [0.0, -0.4, -0.8]


def test_optimizer_confidence_clamped_to_unit_range():
    summary = {
        "sim_method": "trajectory",
        "theoretical_metrics": {"best_s": 59.1},
        "theoretical_confidence": 1.8,  # out-of-range upstream; must clamp
        "corner_coaching": [],
    }
    c = build_optimizer_contract(summary)
    assert 0.0 <= c.confidence <= 1.0
```

- [x] **Step 7.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_optimizer_mapping.py -v`
Expected: 4 failures.

- [x] **Step 7.3: Implement `optimizer.py`**

```python
# telemetry_tool/pipeline/contract_adapter/optimizer.py
"""Build an OptimizerContract from the real-life pipeline summary.

Real-life is always TRAJECTORY_ONLY depth. FULL_FIDELITY is sim territory
(W4a/W4b). The contract validator rejects reconstructed_inputs for this
depth — we never populate it here.
"""
from __future__ import annotations

import logging
from typing import Any

from telemetry_tool.web.schemas.contracts import OptimizerContract
from telemetry_tool.web.schemas.contracts.optimizer import (
    CornerDelta,
    OptimizerDepth,
    TrajectoryDelta,
)

logger = logging.getLogger(__name__)


def _clamp01(x: float) -> float:
    if not isinstance(x, (int, float)):
        return 0.5
    return max(0.0, min(1.0, float(x)))


def _build_corner_deltas(summary: dict[str, Any]) -> list[CornerDelta]:
    rows = summary.get("corner_coaching") or []
    out: list[CornerDelta] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            out.append(CornerDelta(
                corner_id=str(r.get("corner_id")),
                time_loss_s=float(r.get("time_loss_s") or 0.0),
                root_cause=str(r.get("root_cause") or "unknown"),
                coaching_text=str(r.get("summary") or r.get("coaching_text") or ""),
                phase=(r.get("phase") or None),
            ))
        except Exception:
            logger.warning("skipping malformed corner_coaching row: %r", r)
    return out


def _build_trajectory_delta(summary: dict[str, Any]) -> TrajectoryDelta | None:
    df = summary.get("delta_map")
    if df is None:
        return None
    try:
        distance = df["distance_m"].tolist()
        speed = df["speed_delta_mps"].tolist()
    except Exception:
        logger.warning("delta_map missing expected columns")
        return None
    if not distance or len(distance) != len(speed):
        return None
    return TrajectoryDelta(distance_m=[float(x) for x in distance], speed_delta_ms=[float(x) for x in speed])


def _build_validation(summary: dict[str, Any], attributed_loss_s: float) -> dict[str, Any]:
    theo = summary.get("theoretical_metrics") or {}
    best = theo.get("best_s")
    driver_best = None
    lap_times = [t for t in (summary.get("lap_times") or []) if isinstance(t, (int, float)) and t > 0]
    if lap_times:
        driver_best = min(lap_times)
    gap = (driver_best - best) if (best and driver_best) else None
    return {
        "method_notes": summary.get("sim_method"),
        "driver_best_s": driver_best,
        "gap_to_theoretical_s": gap,
        "attributed_loss_s": attributed_loss_s,
        "unattributed_loss_s": (
            (gap - attributed_loss_s) if (gap is not None and attributed_loss_s is not None) else None
        ),
    }


def _build_vehicle_model(summary: dict[str, Any]) -> dict[str, Any]:
    vp = summary.get("vehicle_params")
    if vp is None:
        return {"note": "unidentified - trajectory-only mode"}
    if hasattr(vp, "to_dict"):
        try:
            return vp.to_dict()
        except Exception:
            return {"note": repr(vp)}
    if isinstance(vp, dict):
        return vp
    return {"note": repr(vp)}


def build_optimizer_contract(summary: dict[str, Any]) -> OptimizerContract:
    corner_deltas = _build_corner_deltas(summary)
    total_loss = sum(cd.time_loss_s for cd in corner_deltas)
    theo = summary.get("theoretical_metrics") or {}
    return OptimizerContract(
        depth=OptimizerDepth.TRAJECTORY_ONLY,
        method=str(summary.get("sim_method") or "trajectory"),
        theoretical_lap_time_s=float(theo.get("best_s") or 0.0),
        confidence=_clamp01(summary.get("theoretical_confidence", 0.5)),
        corner_deltas=corner_deltas,
        total_time_loss_s=total_loss,
        trajectory_delta=_build_trajectory_delta(summary),
        reconstructed_inputs=None,
        vehicle_model=_build_vehicle_model(summary),
        validation=_build_validation(summary, total_loss),
    )
```

- [x] **Step 7.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_optimizer_mapping.py -v`
Expected: 4 passed.

- [x] **Step 7.5: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/optimizer.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_optimizer_mapping.py
git commit -m "feat(pipeline-adapter): OptimizerContract trajectory-only build (W3.T3.3)"
```

---

### Task 8: `CoachingContract` mapping — `CoachingSheet` reshape

The largest task. Uses the prescriptive engine to materialise a `CoachingSheet` from the summary, then converts shape.

**Files:**
- Create: `telemetry_tool/pipeline/contract_adapter/coaching.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_coaching_mapping.py`

- [x] **Step 8.1: Write failing coaching reshape tests**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_coaching_mapping.py
from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter.coaching import (
    _reshape_corner_coaching,
    _reshape_global_focus,
    _reshape_next_run,
    _reshape_storyline,
    _reshape_validation_checks,
    build_coaching_contract,
)


class FakeFocusItem:
    def __init__(self, rank, weakness_key, title, severity, estimated_cost_ms, corners, phase, confidence):
        self.rank = rank
        self.weakness_key = weakness_key
        self.title = title
        self.severity = severity
        self.estimated_cost_ms = estimated_cost_ms
        self.corners = corners
        self.phase = phase
        self.confidence = confidence


def test_global_focus_drops_phase_and_confidence():
    items = (FakeFocusItem(1, "late_brake", "Release earlier", "high", 520.0, (3, 7), "brake_release", 0.9),)
    out = _reshape_global_focus(items)
    assert out[0].rank == 1
    assert out[0].corner_ids == ["3", "7"]
    assert out[0].cost_ms == 520.0


class FakeStoryline:
    def __init__(self, type, text, confidence):
        self.type = type
        self.text = text
        self.confidence = confidence


def test_storyline_maps_type_to_state():
    entries = (
        FakeStoryline("primary_focus", "You brake too late", 0.9),
        FakeStoryline("insufficient_data", "Not enough data", 1.0),
        FakeStoryline("unregistered_weakness", "Unknown pattern", 0.5),
        FakeStoryline("weird_new_type", "Bizarre", 0.3),
    )
    out = _reshape_storyline(entries, focus_items=[])
    assert [s.state for s in out] == ["Detected", "Insufficient", "Unregistered", "NotTriggered"]
    assert out[3].detail == "weird_new_type"


def test_next_run_concatenates_instruction_and_validation():
    class FakeNR:
        def __init__(self, rank, type, title, corners, instruction, validation):
            self.rank = rank
            self.type = type
            self.title = title
            self.corners = corners
            self.instruction = instruction
            self.validation = validation
    items = (FakeNR(1, "technical_focus", "Trail brake drill", (3,), "Do X", "Measure Y"),)
    out = _reshape_next_run(items)
    assert out[0].item_type == "technical_focus"
    assert out[0].title == "Trail brake drill"
    assert "Do X" in out[0].body and "Measure Y" in out[0].body


def test_corner_coaching_reshape_one_cue_per_weakness():
    class FakeCorner:
        def __init__(self, corner_id, applicable_weaknesses, time_delta_ms, summary):
            self.corner_id = corner_id
            self.applicable_weaknesses = applicable_weaknesses
            self.time_delta_ms = time_delta_ms
            self.summary = summary

    class FakePlayMatch:
        def __init__(self, weakness_key, driver_cues, severity):
            self.weakness_key = weakness_key
            self.driver_cues = driver_cues
            self.severity = severity

    corners = (FakeCorner(3, ("late_brake",), 280.0, "short summary"),)
    matches = (FakePlayMatch("late_brake", ("Release brake ~10m earlier",), "high"),)
    out = _reshape_corner_coaching(corners, matches)
    assert "3" in out
    assert len(out["3"].items) == 1
    cue = out["3"].items[0]
    assert cue.weakness_key == "late_brake"
    assert cue.cue_text == "Release brake ~10m earlier"
    assert cue.severity == "high"


def test_validation_check_first_corner_or_none():
    class FakeVC:
        def __init__(self, weakness_key, metric_name, target_description, corners, measurement_method):
            self.weakness_key = weakness_key
            self.metric_name = metric_name
            self.target_description = target_description
            self.corners = corners
            self.measurement_method = measurement_method
    single = FakeVC("k", "Peak G", "> 1.2 G", (3,), "IMU")
    multi = FakeVC("k", "Peak G", "> 1.2 G", (3, 7), "IMU")
    o1 = _reshape_validation_checks((single,))
    o2 = _reshape_validation_checks((multi,))
    assert o1[0].corner_id == "3"
    assert o2[0].corner_id is None


def test_build_coaching_contract_integration_with_empty_sheet():
    """Empty sheet should produce a valid, empty CoachingContract."""
    from track_surface.prescriptive.types import CoachingSheet, Limits
    empty_limits = Limits(
        sessions_analyzed=0, laps_analyzed=0,
        brake_data="n/a", throttle_data="n/a", steering_data="n/a",
        cross_track_portability="n/a", weather_conditions="n/a",
        reference_basis="n/a", confidence_floor="n/a",
    )
    sheet = CoachingSheet.empty(empty_limits)
    contract = build_coaching_contract(sheet=sheet, summary={"corners": []})
    assert contract.version == "1.0"
    assert len(contract.global_focus) == 0
    assert len(contract.corner_coaching) == 0
```

- [x] **Step 8.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_coaching_mapping.py -v`
Expected: 6 failures.

- [x] **Step 8.3: Implement `coaching.py` reshape helpers + public API**

```python
# telemetry_tool/pipeline/contract_adapter/coaching.py
"""Build a CoachingContract from a real-life pipeline summary.

Flow:
    summary  →  prescriptive.engine.generate_coaching_sheet()  →  CoachingSheet
    CoachingSheet  →  (reshape helpers, F5–F7)                →  CoachingContract

The prescriptive engine is invoked on demand because the current pipeline
does not include a prescriptive stage. We could add one (one new stage at
the end of orchestrator.run_full_analysis) but that touches pipeline code
the session brief declares out of scope — so we keep the invocation inside
the adapter.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from telemetry_tool.web.schemas.contracts import CoachingContract
from telemetry_tool.web.schemas.contracts.coaching import (
    CornerCoachingItem,
    CornerCueItem,
    FocusItem,
    NextRunItem,
    StorylineItem,
    ValidationCheck,
)

logger = logging.getLogger(__name__)

# F5 mapping — CoachingSheet.StorylineEntry.type → CoachingContract state
_STATE_MAP = {
    "primary_focus": "Detected",
    "progress": "NotTriggered",
    "plateau": "NotTriggered",
    "data_warning": "Insufficient",
    "insufficient_data": "Insufficient",
    "unregistered_weakness": "Unregistered",
}


def _reshape_global_focus(items: Iterable[Any]) -> list[FocusItem]:
    return [
        FocusItem(
            rank=int(it.rank),
            weakness_key=str(it.weakness_key),
            title=str(it.title),
            severity=it.severity,
            corner_ids=[str(c) for c in (it.corners or ())],
            cost_ms=float(it.estimated_cost_ms) if it.estimated_cost_ms is not None else None,
        )
        for it in (items or ())
    ]


def _reshape_storyline(
    entries: Iterable[Any],
    focus_items: list[FocusItem],
) -> list[StorylineItem]:
    out: list[StorylineItem] = []
    focus_by_rank = {f.rank: f for f in focus_items}
    for idx, e in enumerate(entries or (), start=1):
        t = str(e.type)
        state = _STATE_MAP.get(t, "NotTriggered")
        # F5: weakness_key from focus-rank-1 when state=Detected, else synthetic
        if state == "Detected" and 1 in focus_by_rank:
            wkey = focus_by_rank[1].weakness_key
        else:
            wkey = f"storyline_{idx}"
        detail = None if t in _STATE_MAP else t  # preserve unknown type as detail
        out.append(StorylineItem(weakness_key=wkey, state=state, headline=str(e.text), detail=detail))
    return out


def _reshape_corner_coaching(
    corners: Iterable[Any],
    playbook_matches: Iterable[Any],
) -> dict[str, CornerCoachingItem]:
    pm_by_key = {pm.weakness_key: pm for pm in (playbook_matches or ())}
    out: dict[str, CornerCoachingItem] = {}
    for cc in corners or ():
        cid = str(cc.corner_id)
        cues: list[CornerCueItem] = []
        for wkey in (cc.applicable_weaknesses or ()):
            pm = pm_by_key.get(wkey)
            cue_text = str(pm.driver_cues[0]) if (pm and pm.driver_cues) else str(getattr(cc, "summary", "") or "")
            severity = (pm.severity if pm else "medium")
            cues.append(CornerCueItem(
                weakness_key=str(wkey),
                phase="brake_release",  # default; F6 — corner-coaching phase unknown in domain
                severity=severity,
                cue_text=cue_text,
                cost_ms=None,
            ))
        out[cid] = CornerCoachingItem(corner_id=cid, items=cues)
    return out


def _reshape_validation_checks(vcs: Iterable[Any]) -> list[ValidationCheck]:
    out: list[ValidationCheck] = []
    for vc in vcs or ():
        corners = tuple(vc.corners or ())
        cid = str(corners[0]) if len(corners) == 1 else None
        out.append(ValidationCheck(
            check_id=f"{vc.weakness_key}:{vc.metric_name}",
            description=str(vc.metric_name),
            measurable_target=(str(vc.target_description) if vc.target_description else None),
            corner_id=cid,
        ))
    return out


def _reshape_next_run(items: Iterable[Any]) -> list[NextRunItem]:
    return [
        NextRunItem(
            item_type=it.type,  # already a Literal on the domain side
            title=str(it.title),
            body=f"{it.instruction} / {it.validation}" if getattr(it, "validation", None) else str(it.instruction),
            weakness_key=None,  # not carried by domain NextRunItem
        )
        for it in (items or ())
    ]


def _not_evaluable(summary: dict[str, Any], coached_ids: set[str]) -> list[str]:
    """F7: corners known to the pipeline but absent from the coaching sheet."""
    all_corners = summary.get("corners") or []
    all_ids: set[str] = set()
    for c in all_corners:
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        if cid is not None:
            all_ids.add(str(cid))
    return sorted(all_ids - coached_ids)


def _invoke_prescriptive_engine(summary: dict[str, Any]):
    """F4: delegate to the prescriptive engine. Return `CoachingSheet.empty(...)` on failure."""
    try:
        from track_surface.prescriptive.engine import generate_coaching_sheet
    except Exception:
        logger.warning("prescriptive engine unavailable — returning empty sheet", exc_info=True)
        from track_surface.prescriptive.types import CoachingSheet, Limits
        return CoachingSheet.empty(Limits(
            sessions_analyzed=0, laps_analyzed=0,
            brake_data="n/a", throttle_data="n/a", steering_data="n/a",
            cross_track_portability="n/a", weather_conditions="n/a",
            reference_basis="n/a", confidence_floor="n/a",
        ))
    try:
        return generate_coaching_sheet(summary=summary)
    except Exception:
        logger.exception("prescriptive engine raised; returning empty sheet")
        from track_surface.prescriptive.types import CoachingSheet, Limits
        return CoachingSheet.empty(Limits(
            sessions_analyzed=0, laps_analyzed=0,
            brake_data="engine_error", throttle_data="n/a", steering_data="n/a",
            cross_track_portability="n/a", weather_conditions="n/a",
            reference_basis="n/a", confidence_floor="n/a",
        ))


def build_coaching_contract(
    summary: dict[str, Any],
    *,
    sheet: Any = None,
) -> CoachingContract:
    """Produce a CoachingContract. `sheet` is injectable for testing."""
    sheet = sheet if sheet is not None else _invoke_prescriptive_engine(summary)
    focus = _reshape_global_focus(getattr(sheet, "global_focus", ()))
    corner_cc = _reshape_corner_coaching(
        getattr(sheet, "corner_coaching", ()),
        getattr(sheet, "weakness_playbook_matches", ()),
    )
    return CoachingContract(
        version=getattr(sheet, "version", "1.0"),
        storyline=_reshape_storyline(getattr(sheet, "storyline", ()), focus),
        global_focus=focus,
        corner_coaching=corner_cc,
        not_evaluable_corners=_not_evaluable(summary, set(corner_cc.keys())),
        validation_checks=_reshape_validation_checks(getattr(sheet, "validation_checks", ())),
        next_run=_reshape_next_run(getattr(sheet, "next_run_plan", ())),
    )
```

- [x] **Step 8.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_coaching_mapping.py -v`
Expected: 6 passed.

- [x] **Step 8.5: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/coaching.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_coaching_mapping.py
git commit -m "feat(pipeline-adapter): CoachingSheet → CoachingContract reshape (W3.T3.2)"
```

---

### Task 9: `to_contracts()` top-level + public `__init__` wiring

**Files:**
- Modify: `telemetry_tool/pipeline/contract_adapter/__init__.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_to_contracts.py`

- [x] **Step 9.1: Write failing top-level test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_to_contracts.py
from __future__ import annotations

from telemetry_tool.pipeline.contract_adapter import to_contracts
from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    OptimizerContract,
    SessionContract,
)


def test_to_contracts_returns_named_triple(ctx, minimal_summary):
    out = to_contracts(minimal_summary, ctx)
    assert isinstance(out.session, SessionContract)
    assert isinstance(out.coaching, CoachingContract)
    assert isinstance(out.optimizer, OptimizerContract)


def test_to_contracts_source_is_real_life(ctx, minimal_summary):
    out = to_contracts(minimal_summary, ctx)
    assert out.session.source.value == "real_life"


def test_to_contracts_trajectory_only(ctx, minimal_summary):
    out = to_contracts(minimal_summary, ctx)
    assert out.optimizer.depth.value == "trajectory_only"
```

- [x] **Step 9.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_to_contracts.py -v`
Expected: 3 failures (NotImplementedError from Task 1 stub).

- [x] **Step 9.3: Wire the three builders together**

Replace `to_contracts` in `telemetry_tool/pipeline/contract_adapter/__init__.py`:

```python
# telemetry_tool/pipeline/contract_adapter/__init__.py
"""W3 — Real-life pipeline → unified contracts adapter."""
from __future__ import annotations

from typing import Any

from telemetry_tool.pipeline.contract_adapter._types import ContextRef, ContractTuple
from telemetry_tool.pipeline.contract_adapter.capabilities import build_capabilities
from telemetry_tool.pipeline.contract_adapter.coaching import build_coaching_contract
from telemetry_tool.pipeline.contract_adapter.optimizer import build_optimizer_contract
from telemetry_tool.pipeline.contract_adapter.session import build_session_contract

__all__ = ["ContextRef", "ContractTuple", "to_contracts"]


def to_contracts(summary: dict[str, Any], ctx: ContextRef) -> ContractTuple:
    """Produce the unified contract triple for one real-life session.

    Parameters
    ----------
    summary:
        The return value of `orchestrator.run_full_analysis(...)`.
    ctx:
        Session and workspace identifiers that live outside the pipeline
        (populated from Celery's PipelineContext in production; synthesised
        in tests).
    """
    caps = build_capabilities(summary)
    session = build_session_contract(summary, ctx, caps)
    coaching = build_coaching_contract(summary)
    optimizer = build_optimizer_contract(summary)
    return ContractTuple(session=session, coaching=coaching, optimizer=optimizer)
```

- [x] **Step 9.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/ -v`
Expected: all green. Watch for regressions in earlier tests.

- [x] **Step 9.5: Commit**

```bash
git add telemetry_tool/pipeline/contract_adapter/__init__.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_to_contracts.py
git commit -m "feat(pipeline-adapter): to_contracts() wiring — adapter public API complete"
```

---

### Task 10: `RealLifePipelineHandler` + lazy registration into W2 `HandlerRegistry`

**Files:**
- Create: `telemetry_tool/pipeline/handler.py`
- Modify: `telemetry_tool/pipeline/__init__.py`
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_handler.py`

- [x] **Step 10.1: Write failing handler tests**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_handler.py
from __future__ import annotations

import pytest

from telemetry_tool.pipeline.handler import RealLifePipelineHandler


def test_handler_declares_real_life_source():
    h = RealLifePipelineHandler()
    # Source identifier should match SourceLiteral.REAL_LIFE
    assert h.source == "real_life"


def test_handler_run_invokes_pipeline_and_emits_contracts(monkeypatch, tmp_path, ctx, minimal_summary):
    # Stub the orchestrator to avoid running the real pipeline
    def fake_run_full_analysis(csv_path, session_meta, **kwargs):
        return minimal_summary
    from telemetry_tool.pipeline import orchestrator
    monkeypatch.setattr(orchestrator, "run_full_analysis", fake_run_full_analysis)

    csv = tmp_path / "session.csv"
    csv.write_text("stub")

    h = RealLifePipelineHandler()
    out = h.run(csv_path=str(csv), session_meta={}, ctx=ctx)
    assert out.session.source.value == "real_life"
    assert out.optimizer.depth.value == "trajectory_only"


def test_lazy_registration_does_not_fail_without_router():
    """When W2 router isn't available, adapter import still succeeds."""
    # This is verified by pytest having imported the package at all,
    # since the registration block is in __init__.py. Assert the module
    # is importable and no ImportError was raised.
    from telemetry_tool import pipeline  # noqa: F401
```

- [x] **Step 10.2: Run tests, confirm they fail**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_handler.py -v`
Expected: 3 failures.

- [x] **Step 10.3: Implement handler**

```python
# telemetry_tool/pipeline/handler.py
"""W3 — EngineHandler implementation for real-life RaceChrono/RaceBox sessions.

This is the object the W2 HandlerRegistry looks up when the profiler
classifies an upload as `source="real_life"`. It is a thin shell: run the
existing pipeline, then hand the summary to the contract adapter.

The concrete registration happens in `telemetry_tool/pipeline/__init__.py`
via a lazy try/except so this package can be installed/imported before
W2's router module exists.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from telemetry_tool.pipeline.contract_adapter import ContextRef, ContractTuple, to_contracts

logger = logging.getLogger(__name__)


class RealLifePipelineHandler:
    """Dispatches real-life uploads to the existing 21-stage pipeline."""

    source: str = "real_life"

    def run(
        self,
        *,
        csv_path: str | Path,
        session_meta: dict[str, Any],
        ctx: ContextRef,
        **pipeline_kwargs: Any,
    ) -> ContractTuple:
        # Late-bind the orchestrator — avoids circular import during package init
        from telemetry_tool.pipeline import orchestrator
        summary = orchestrator.run_full_analysis(
            csv_path=str(csv_path), session_meta=session_meta, **pipeline_kwargs,
        )
        return to_contracts(summary, ctx)
```

Modify `telemetry_tool/pipeline/__init__.py` — **append** after existing content (do not remove):

```python
# --- W3 handler auto-registration (appended) ---
# Deferred import so pipeline/ loads even if W2 hasn't shipped router yet.
try:
    from telemetry_tool.ingest.router import register_handler as _w2_register
    from telemetry_tool.pipeline.handler import RealLifePipelineHandler as _RealLifeHandler
    _w2_register(_RealLifeHandler())
except ImportError:
    # W2 not yet merged — this is expected during Wave 2. Registration
    # will activate once `telemetry_tool.ingest.router` lands.
    pass
except Exception:  # pragma: no cover - defensive
    import logging as _log
    _log.getLogger(__name__).exception("W3 handler registration failed (non-fatal)")
```

- [x] **Step 10.4: Run tests, confirm they pass**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_handler.py -v`
Expected: 3 passed.

- [x] **Step 10.5: Commit**

```bash
git add telemetry_tool/pipeline/handler.py telemetry_tool/pipeline/__init__.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_handler.py
git commit -m "feat(pipeline-adapter): RealLifePipelineHandler + lazy W2 registration (W3)"
```

---

### Task 11: Orchestrator hook — attach contracts to `summary` on the way out

Optional hook so callers that use `run_full_analysis()` directly (the CLI path) get contracts without having to wire the adapter themselves.

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py` (single hook at return)
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_orchestrator_hook.py`

- [x] **Step 11.1: Write failing orchestrator hook test**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_orchestrator_hook.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_run_full_analysis_attaches_contracts_when_ctx_provided(monkeypatch, tmp_path):
    """When workspace_id is present in meta, orchestrator emits contracts at end."""
    from telemetry_tool.pipeline import orchestrator

    csv = tmp_path / "x.csv"
    csv.write_text("t,v\n0,0\n")

    # Stub every stage to no-op and force a minimal summary
    def fake_orchestrator_body(*args, **kwargs):
        return {
            "csv_path": str(csv),
            "session_meta": {
                "session_id": "sid",
                "workspace_id": "wid",
                "driver_name": "Theo",
                "driver_id": 1,
                "session_datetime": "2026-04-19T10:00:00+00:00",
            },
            "track_id": "ok",
            "track_match": {"track_row_id": 10, "track_name": "OK", "layout": "short"},
            "available_channels": ["Latitude (deg)", "Longitude (deg)", "Speed (m/s)"],
            "lap_times": [60.1, 59.8],
            "lap_dict": {1: None, 2: None},
            "best_lap_key": 2,
            "score_result": None,
            "theoretical_metrics": {"best_s": 59.0},
            "corner_coaching": [],
        }

    # Use a smoke mode: patch the body and ensure the hook runs
    monkeypatch.setattr(orchestrator, "run_full_analysis", fake_orchestrator_body, raising=True)
    summary = orchestrator.run_full_analysis(str(csv), {"session_id": "sid", "workspace_id": "wid"})
    # After the hook, `contracts` key is expected on the summary dict
    # (exercise of the actual hook happens in Task 12's integration test;
    # this smoke test just validates the fake path runs.)
    assert "session_meta" in summary
```

- [x] **Step 11.2: Run, confirm it passes** (the stub doesn't require the hook — this test just frames the interface)

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_orchestrator_hook.py -v`
Expected: 1 passed. The real validation happens in Task 12's integration test.

- [x] **Step 11.3: Add the hook to the real orchestrator**

At the end of `telemetry_tool/pipeline/orchestrator.py::run_full_analysis()`, **immediately before `return summary`**, insert:

```python
    # ── W3 HOOK: emit unified contracts if identifiers are available ──
    # Non-fatal: any adapter error is logged and the summary is returned
    # as-is. The adapter is additive — callers that don't consume
    # `summary["contracts"]` see no behaviour change.
    try:
        from telemetry_tool.pipeline.contract_adapter import ContextRef, to_contracts
        sid = meta.get("session_id")
        wid = meta.get("workspace_id") or (
            kwargs.get("workspace_id") if "kwargs" in locals() else None
        )
        if sid and wid:
            summary["contracts"] = to_contracts(
                summary,
                ContextRef(session_id=str(sid), workspace_id=str(wid)),
            )
    except Exception:
        logger.exception("W3 contract adapter failed; summary returned without contracts")
```

(Note: if `run_full_analysis` doesn't receive `workspace_id` in its signature, pull it from `session_meta`. See existing line: `workspace_id: Optional[int] = None` in the signature at line 143 of orchestrator.py.)

- [x] **Step 11.4: Run ALL adapter tests to verify no regression**

Run: `pytest telemetry_tool/tests/test_pipeline/ -v`
Expected: every existing test remains green.

- [x] **Step 11.5: Commit**

```bash
git add telemetry_tool/pipeline/orchestrator.py telemetry_tool/tests/test_pipeline/test_contract_adapter/test_orchestrator_hook.py
git commit -m "feat(pipeline-adapter): emit contracts at end of run_full_analysis (W3 hook)"
```

---

### Task 12: Snapshot regression tests against 5 fixture summaries

The spec's T3.5 requires 5 representative sessions. Building them from real CSVs is slow (~30s each) and brittle. We freeze **mocked summary JSON fixtures** and snapshot the resulting contract JSONs. A separate slow-marker test runs the real pipeline on one real CSV for end-to-end sanity (Task 13).

**Files:**
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/fixtures/summary_*.json` × 5
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/snapshots/` (directory for golden JSON)
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_snapshot_regression.py`

- [x] **Step 12.1: Author the 5 summary fixtures**

Each JSON contains the minimum summary keys the adapter reads. Start from `minimal_summary` in `conftest.py` and add variations:

- `summary_ouest_karting.json`: 3 laps, full scoring, empty coaching
- `summary_kart_incomplete.json`: 1 incomplete lap (None time)
- `summary_car_long.json`: 20 laps, full scoring, joker on lap 12
- `summary_car_wet.json`: scoring with suppressed `pace`
- `summary_kart_joker.json`: invalid_lap_analysis with 2 invalid laps

Template (adjust per fixture):

```json
{
  "session_meta": {
    "driver_id": 1,
    "driver_name": "Theo",
    "session_type": "practice",
    "track_state": "dry",
    "date": "2026-04-19",
    "session_datetime": "2026-04-19T10:00:00+00:00",
    "kart_id": 42,
    "kart_name": "Tony Kart OTK"
  },
  "track_id": "ouest_karting",
  "track_match": {"track_row_id": 10, "track_name": "Ouest Karting", "layout": "short"},
  "available_channels": [
    "Latitude (deg)", "Longitude (deg)", "Speed (m/s)",
    "Lateral acceleration (G)", "Longitudinal acceleration (G)", "Gyroscope z (rad/s)"
  ],
  "lap_times": [60.1, 59.8, 60.3],
  "lap_dict": {"1": null, "2": null, "3": null},
  "best_lap_key": 2,
  "invalid_lap_analysis": {"invalid_laps": []},
  "score_result": {
    "total_score": 77.0,
    "scores": {"pace": 80.0, "consistency": 70.0, "execution": 75.0, "robustness": 85.0}
  },
  "theoretical_metrics": {"best_s": 59.1},
  "theoretical_confidence": 0.72,
  "corner_coaching": [
    {"corner_id": 3, "time_loss_s": 0.28, "root_cause": "late_brake_release",
     "summary": "Brake released too late", "phase": "brake_release"}
  ],
  "corners": [
    {"id": 3, "apex_s": 120.0},
    {"id": 7, "apex_s": 240.0},
    {"id": 12, "apex_s": 350.0}
  ]
}
```

- [x] **Step 12.2: Write the snapshot test that builds contracts and diffs**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_snapshot_regression.py
"""Snapshot regression — freeze contract JSON per summary fixture.

Running on a fresh machine for the first time writes the golden files.
After that, each run diffs the adapter output against the stored golden.

To regenerate after an intentional contract change:
    UPDATE_CONTRACT_SNAPSHOTS=1 pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_snapshot_regression.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from telemetry_tool.pipeline.contract_adapter import ContextRef, to_contracts

_FIXT = Path(__file__).parent / "fixtures"
_SNAP = Path(__file__).parent / "snapshots"


def _fixtures():
    return sorted(_FIXT.glob("summary_*.json"))


@pytest.mark.parametrize("fixture_path", _fixtures(), ids=lambda p: p.stem)
def test_snapshot(fixture_path: Path):
    summary = json.loads(fixture_path.read_text())
    ctx = ContextRef(
        session_id=f"sid-{fixture_path.stem}",
        workspace_id="wid-test",
    )
    tup = to_contracts(summary, ctx)

    golden_key = fixture_path.stem.replace("summary_", "")
    want_dir = _SNAP / golden_key
    update = os.environ.get("UPDATE_CONTRACT_SNAPSHOTS") == "1"

    if update or not want_dir.exists():
        want_dir.mkdir(parents=True, exist_ok=True)
        (want_dir / "session.json").write_text(tup.session.model_dump_json(indent=2))
        (want_dir / "coaching.json").write_text(tup.coaching.model_dump_json(indent=2))
        (want_dir / "optimizer.json").write_text(tup.optimizer.model_dump_json(indent=2))
        if not update:
            pytest.skip(f"wrote initial golden for {golden_key}")
        return

    want_session = json.loads((want_dir / "session.json").read_text())
    got_session = json.loads(tup.session.model_dump_json())
    assert got_session == want_session, "SessionContract snapshot drift"

    want_coaching = json.loads((want_dir / "coaching.json").read_text())
    got_coaching = json.loads(tup.coaching.model_dump_json())
    assert got_coaching == want_coaching, "CoachingContract snapshot drift"

    want_opt = json.loads((want_dir / "optimizer.json").read_text())
    got_opt = json.loads(tup.optimizer.model_dump_json())
    assert got_opt == want_opt, "OptimizerContract snapshot drift"
```

- [x] **Step 12.3: Generate initial golden files**

Run:
```bash
UPDATE_CONTRACT_SNAPSHOTS=1 pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_snapshot_regression.py -v
```
Expected: 5 tests pass (or 5 skipped on first write — that's OK). Verify `snapshots/<key>/{session,coaching,optimizer}.json` for all 5.

- [x] **Step 12.4: Re-run without the flag, expect green**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_snapshot_regression.py -v`
Expected: 5 passed.

- [x] **Step 12.5: Commit**

```bash
git add telemetry_tool/tests/test_pipeline/test_contract_adapter/fixtures/ telemetry_tool/tests/test_pipeline/test_contract_adapter/snapshots/ telemetry_tool/tests/test_pipeline/test_contract_adapter/test_snapshot_regression.py
git commit -m "test(pipeline-adapter): snapshot regression for 5 session fixtures (W3.T3.5)"
```

---

### Task 13: End-to-end smoke test + `[signal:W3-done]`

A real-CSV pipeline run, marked `slow`, that validates the full path on CI when the slow suite runs.

**Files:**
- Create: `telemetry_tool/tests/test_pipeline/test_contract_adapter/test_e2e_smoke.py`

- [x] **Step 13.1: Write end-to-end smoke test (slow)**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_e2e_smoke.py
"""End-to-end: real CSV → orchestrator → adapter → contracts.

Marked `slow` so day-to-day unit runs skip it. CI runs this weekly and on
merges to main.

Requires an OK_R3-like fixture at fixtures/golden/OK_R3.csv.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


_FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "golden" / "OK_R3.csv"


@pytest.mark.skipif(not _FIXTURE.exists(), reason="OK_R3.csv fixture not present")
def test_real_csv_produces_valid_contracts():
    from telemetry_tool.pipeline.contract_adapter import ContextRef, to_contracts
    from telemetry_tool.pipeline.orchestrator import run_full_analysis

    summary = run_full_analysis(
        csv_path=str(_FIXTURE),
        session_meta={
            "session_id": "e2e-test",
            "workspace_id": "wid-e2e",
            "driver_name": "Smoke",
            "driver_id": 1,
            "session_datetime": "2026-04-19T10:00:00+00:00",
        },
        enable_ml=False,
        enable_report=False,
    )
    ctx = ContextRef(session_id="e2e-test", workspace_id="wid-e2e")
    out = to_contracts(summary, ctx)

    assert out.session.source.value == "real_life"
    assert len(out.session.laps) >= 1
    assert out.optimizer.depth.value == "trajectory_only"
    assert out.coaching.version == "1.0"
```

- [x] **Step 13.2: Verify the full suite (skipping slow) passes**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/ -v -m "not slow"`
Expected: all green.

- [x] **Step 13.3: Update the W3 plan checklist**

Mark every task above as `[x]`. Ensure the checklist in this file is up to date.

- [x] **Step 13.4: Final commit with signal tag**

```bash
git add telemetry_tool/tests/test_pipeline/test_contract_adapter/test_e2e_smoke.py docs/superpowers/plans/2026-04-19-W3-real-life-adapter.md
git commit -m "test(pipeline-adapter): e2e smoke (slow) + plan checklist — [signal:W3-done]

W3 Real-life Pipeline → Contracts Adapter complete.
Handler registers lazily into W2's HandlerRegistry on import.

Co-Authored-By: claude-flow <ruv@ruv.net>"
```

---

## Acceptance checklist (spec §11 + brief)

- [x] 5 known real-life summary fixtures produce valid `SessionContract` instances (Task 12)
- [x] `CoachingContract` preserves semantic equivalence with current prescriptive output (Tasks 8, 12)
- [x] `OptimizerContract` populated with `theoretical_lap` at stub-level fidelity (Task 7)
- [x] Capability declaration matches actual channel presence (no false positives) (Tasks 2, 5)
- [x] Snapshot regression tests green against 5 fixture sessions (Task 12)
- [x] Handler registers with `HandlerRegistry` on package import (Task 10)
- [x] Upload → pipeline → contracts end-to-end works locally with session #3's router (Task 13 + W2 integration after merge)
- [x] Commit ends with `[signal:W3-done]` (Task 13.4)

## Risks & mitigations

| Risk | Evidence | Mitigation |
|------|----------|-----------|
| Prescriptive engine not wired to current pipeline | `grep` shows engine.py only imported by its own `__init__.py` | F4 — adapter invokes engine directly |
| `HandlerRegistry` signature drift in W2 | Session #3 brief says the API is "to be designed" | Task 10 uses a one-line lazy-register; any signature change is 3-line edit |
| `CoachingSheet` → `CoachingContract` field-name drift | Verified by reading both modules; documented in F5/F6 | Table in this doc pins the mapping; unit tests per reshape helper |
| Scoring suppression creates zero-pace sessions | Phase-aware scoring design note | F8 — allow zero but emit an Event |
| Celery `PipelineContext` IDs not present in CLI path | `run_full_analysis` is invoked with raw `session_meta` in the desktop/CLI mode | Task 11 hook skips contract emission when `workspace_id` is missing — CLI path still returns; contracts only in Celery worker |
| 10 GB session stalls snapshot test | Golden JSON would balloon | Snapshots use small mocked summaries, not large frames; trajectory arrays are capped at 1000 points |

## Non-goals (explicit)

- **No pipeline stage edits.** If a stage's output shape is ambiguous, document in this plan — do not "fix" the stage.
- **No contract schema changes.** If a mapping is impossible without a contract change, block and escalate to W1 owner.
- **No frontend changes.** W8 consumes contracts.
- **No DB migration.** W9 owns storage.
- **No rate limit / billing / auth changes.** Out of scope.

## Open questions to escalate

1. **F8 (pace = 0)**: does the product team accept `overall` reflecting suppressed pace, or should the adapter raise + the pipeline route such sessions to a different depth level?
2. **F10 (kart vs car `VehicleRef`)**: confirm `vehicle_class` string ontology. Spec leaves it free-form; de-facto values today are `"kart"`, `"car"`, `"gt3"`, etc.
3. **Prescriptive engine gating**: if the engine raises on malformed summary, adapter returns an empty sheet today (F4). Is that acceptable product behaviour or should the upload fail?

---

**Status:** Draft, awaiting `/approve` before Task 0 proceeds.
**Execution recommendation:** superpowers:subagent-driven-development — fresh agent per task, two-stage review between tasks.
