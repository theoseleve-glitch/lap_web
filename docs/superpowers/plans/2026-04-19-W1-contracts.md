# W1 — Unified Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Ship the three canonical Pydantic v2 contracts (`SessionContract`, `CoachingContract`, `OptimizerContract`) plus capability enum, generated TypeScript types, Alembic migration for `sessions` table, and fixtures — the foundation that unblocks W2–W10.

**Architecture:** New `telemetry_tool/web/schemas/contracts/` package holds Pydantic models + a generator script that emits both JSON Schema and TypeScript. Migration `022_ws_w1_sessions_source_profile_caps` adds three JSONB/TEXT columns to `sessions`. Fixtures live inside the contracts package so Wave 2 workstreams mock against a shipped artifact, not a conceptual one.

**Tech Stack:** Pydantic v2 · Alembic · SQLAlchemy (PostgreSQL 16) · TypeScript (Next.js) · pytest

**Spec reference:** `docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md` §5 W1 (T1.1–T1.6)

**Branch:** `feat/ws-w1-contracts`

---

## Decisions requiring /approve before code

The user's brief defined the declared paths as:
- `telemetry_tool/web/schemas/contracts/*`
- `lap-website/src/types/contracts.ts` (generated)
- `alembic/versions/<timestamp>_ws_w1_*.py`

Three items fall outside those paths and need explicit approval:

| Flag | Need | Proposed resolution |
|------|------|---------------------|
| **F1 — Tests location** | Validation tests per T1.6 require test files somewhere | Place under `telemetry_tool/tests/test_contracts/` (follows project convention that all tests live under `telemetry_tool/tests/`). Adds ~5 test files; no other code touched. |
| **F2 — TS generator approach** | Acceptance says "TS regenerates" | Use Python-only generator inside contracts package (`_scripts/generate_ts.py`). No npm dep added. Hand-rolled JSON-Schema→TS converter targets only the subset we use (objects, enums, arrays, primitives). Alternative: add `json-schema-to-typescript` dev-dep to `lap-website/package.json` (more robust, but requires modifying shared module). |
| **F3 — Source literal domain** | `source` field values | Initial set: `"real_life" \| "iracing" \| "ac"`. Future sims append without migration. Confirm naming. |

**Stop and ask also if:** the existing `sessions` table column list differs from what the migration expects (will verify against live schema on first migration step — see Task 9).

---

## File Manifest

### Created

```
telemetry_tool/web/schemas/contracts/
├── __init__.py                    # Public exports
├── capabilities.py                # ChannelTag enum + SessionCapabilities model
├── common.py                      # TrajectorySample, Lap, Event, etc.
├── session.py                     # SessionContract
├── coaching.py                    # CoachingContract (harmonized with prescriptive)
├── optimizer.py                   # OptimizerContract
├── _scripts/
│   ├── __init__.py
│   ├── export_json_schema.py      # Pydantic → JSON Schema
│   └── generate_ts.py             # JSON Schema → TS (Python-only)
├── _schemas/                      # Generated JSON Schema output (committed)
│   ├── session.schema.json
│   ├── coaching.schema.json
│   └── optimizer.schema.json
└── fixtures/
    ├── session_realife.json       # one valid real-life session
    ├── session_iracing.json       # one valid iRacing session
    ├── coaching_realife.json
    ├── coaching_iracing.json
    ├── optimizer_trajectory.json
    └── optimizer_fullfidelity.json

lap-website/src/types/contracts.ts  # Generated from JSON Schemas

alembic/versions/022_ws_w1_sessions_source_profile_caps.py

telemetry_tool/tests/test_contracts/  [F1 — flagged]
├── __init__.py
├── conftest.py
├── test_capabilities.py
├── test_session_contract.py
├── test_coaching_contract.py
├── test_optimizer_contract.py
├── test_fixtures_roundtrip.py
└── test_migration_022.py
```

### Modified

```
telemetry_tool/web/schemas/__init__.py  # Re-export contracts subpackage
```

No other files touched.

---

## Tasks

### Task 1: Package scaffold + ChannelTag enum (T1.1 support, W6.T6.1 alignment)

**Files:**
- Create: `telemetry_tool/web/schemas/contracts/__init__.py`
- Create: `telemetry_tool/web/schemas/contracts/capabilities.py`
- Create: `telemetry_tool/tests/test_contracts/__init__.py`
- Create: `telemetry_tool/tests/test_contracts/test_capabilities.py`

- [x] **Step 1.1: Write failing test for ChannelTag enum**

```python
# telemetry_tool/tests/test_contracts/test_capabilities.py
from telemetry_tool.web.schemas.contracts.capabilities import ChannelTag, SessionCapabilities


def test_channel_tag_covers_w1_acceptance_set():
    """W1 acceptance: enum covers GPS, LAT_G, LON_G, YAW_RATE, THROTTLE, BRAKE, STEER, WHEEL_SPD, SHOCK_DEFL."""
    required = {"GPS", "LAT_G", "LON_G", "YAW_RATE", "THROTTLE", "BRAKE", "STEER", "WHEEL_SPD", "SHOCK_DEFL"}
    present = {tag.name for tag in ChannelTag}
    missing = required - present
    assert not missing, f"missing channel tags: {missing}"


def test_session_capabilities_empty_default():
    """Capabilities default to empty set — unknown until set."""
    caps = SessionCapabilities()
    assert caps.channels == frozenset()
    assert caps.has(ChannelTag.GPS) is False


def test_session_capabilities_has_check():
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.LAT_G}))
    assert caps.has(ChannelTag.GPS)
    assert caps.has(ChannelTag.LAT_G)
    assert not caps.has(ChannelTag.THROTTLE)
```

- [x] **Step 1.2: Run test, confirm it fails**

```bash
pytest telemetry_tool/tests/test_contracts/test_capabilities.py -v
```

Expected: `ModuleNotFoundError` on the import.

- [x] **Step 1.3: Create package + ChannelTag**

```python
# telemetry_tool/web/schemas/contracts/__init__.py
"""Unified contracts for the W1 workstream.

Exported:
    ChannelTag, SessionCapabilities — capability enum + flag model
    (Additional contracts land in later tasks.)
"""
from __future__ import annotations

from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)

__all__ = ["ChannelTag", "SessionCapabilities"]
```

```python
# telemetry_tool/web/schemas/contracts/capabilities.py
"""Channel capability enum + session capability flags.

Each detector in the coaching library declares which channels it needs
(`NEEDS: set[ChannelTag]`). At runtime, the coach assembler filters
detectors by the session's capabilities — depth scales with data.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field


class ChannelTag(str, Enum):
    """Canonical identifier for a telemetry channel family.

    Kept deliberately small. Add entries only when a detector needs a
    distinction that cannot be inferred from an existing tag. Extending
    this set is a contract-level change — version bump required.
    """
    GPS = "gps"                  # lat/lon/speed from GPS receiver
    LAT_G = "lat_g"              # lateral acceleration (m/s^2 or G)
    LON_G = "lon_g"              # longitudinal acceleration
    YAW_RATE = "yaw_rate"        # body yaw rate (rad/s)
    THROTTLE = "throttle"        # driver throttle input [0..1]
    BRAKE = "brake"              # driver brake input [0..1]
    STEER = "steer"              # steering angle or normalized input
    WHEEL_SPD = "wheel_spd"      # per-wheel speed (sim only)
    SHOCK_DEFL = "shock_defl"    # shock deflection per corner (sim only)


class SessionCapabilities(BaseModel):
    """Flags describing which channels are present in a given session.

    The set is populated by the data-profile detector (W2) at upload time.
    Coaches and optimizers consume this to pick the right analyzer subset.
    """
    model_config = ConfigDict(frozen=True)

    channels: frozenset[ChannelTag] = Field(default_factory=frozenset)

    def has(self, tag: ChannelTag) -> bool:
        return tag in self.channels

    def has_all(self, tags: Iterable[ChannelTag]) -> bool:
        return set(tags).issubset(self.channels)
```

- [x] **Step 1.4: Run tests to verify they pass**

```bash
pytest telemetry_tool/tests/test_contracts/test_capabilities.py -v
```

Expected: 3 passed.

- [x] **Step 1.5: Commit**

```bash
git add telemetry_tool/web/schemas/contracts/__init__.py \
        telemetry_tool/web/schemas/contracts/capabilities.py \
        telemetry_tool/tests/test_contracts/__init__.py \
        telemetry_tool/tests/test_contracts/test_capabilities.py
git commit -m "feat(contracts): ChannelTag enum + SessionCapabilities (W1.T1.1)"
```

---

### Task 2: Common contract primitives

**Files:**
- Create: `telemetry_tool/web/schemas/contracts/common.py`
- Create: `telemetry_tool/tests/test_contracts/test_common.py`

**Rationale:** Types shared by multiple contracts — avoid duplicating between `session.py`, `coaching.py`, `optimizer.py`.

- [x] **Step 2.1: Write failing test**

```python
# telemetry_tool/tests/test_contracts/test_common.py
import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts.common import (
    SourceLiteral,
    TrajectorySample,
    LapSummary,
    DriverRef,
    TrackRef,
    VehicleRef,
    Scores,
)


def test_source_literal_values():
    """Source is constrained to known engine keys."""
    # valid
    assert SourceLiteral.REAL_LIFE.value == "real_life"
    assert SourceLiteral.IRACING.value == "iracing"
    assert SourceLiteral.AC.value == "ac"


def test_trajectory_sample_requires_time_and_distance():
    TrajectorySample(t_s=1.23, s_m=45.0, speed_ms=30.0)
    with pytest.raises(ValidationError):
        TrajectorySample(t_s=None, s_m=45.0, speed_ms=30.0)


def test_lap_summary_basic():
    lap = LapSummary(lap_number=1, lap_time_s=95.123, is_valid=True)
    assert lap.lap_number == 1
    assert lap.is_valid


def test_scores_range_0_100():
    Scores(pace=80.0, consistency=75.0, execution=90.0, robustness=82.0, overall=82.0)
    with pytest.raises(ValidationError):
        Scores(pace=120.0, consistency=75.0, execution=90.0, robustness=82.0, overall=82.0)
```

- [x] **Step 2.2: Run test to see it fail**

```bash
pytest telemetry_tool/tests/test_contracts/test_common.py -v
```

Expected: ImportError.

- [x] **Step 2.3: Implement common.py**

```python
# telemetry_tool/web/schemas/contracts/common.py
"""Shared primitives used across Session/Coaching/Optimizer contracts."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceLiteral(str, Enum):
    """Engine family that produced this session."""
    REAL_LIFE = "real_life"   # RaceChrono / RaceBox GPS+IMU
    IRACING = "iracing"       # iRacing IBT
    AC = "ac"                 # Assetto Corsa CSV/binary
    # Extend carefully — adding a value is a contract change.


class DriverRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    driver_id: int
    name: str


class TrackRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    track_id: int
    name: str
    layout: str | None = None


class VehicleRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    vehicle_id: int | None = None
    vehicle_class: str | None = None
    model: str | None = None


class TrajectorySample(BaseModel):
    """A single sample along the driven trajectory.

    The full trajectory array is typically stored in a sidecar Parquet
    file; the contract carries a reference + summary, not the full array.
    """
    model_config = ConfigDict(frozen=True)
    t_s: float = Field(..., description="Elapsed time since session start, seconds")
    s_m: float = Field(..., description="Distance travelled, metres")
    speed_ms: float = Field(..., description="Longitudinal speed, m/s")
    lat: float | None = None
    lon: float | None = None
    lat_g: float | None = None
    lon_g: float | None = None


class LapSummary(BaseModel):
    """Per-lap summary. Detailed per-sample data lives in sidecar storage."""
    model_config = ConfigDict(frozen=True)
    lap_number: int
    lap_time_s: float | None = Field(None, description="None for incomplete laps")
    is_valid: bool = True
    is_best: bool = False
    flags: list[str] = Field(default_factory=list)


class Event(BaseModel):
    """A detected incident or coaching-relevant moment during the session."""
    model_config = ConfigDict(frozen=True)
    event_type: str  # free-form for now; narrowed in W6
    lap_number: int | None = None
    t_s: float | None = None
    s_m: float | None = None
    severity: str | None = None
    detector: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Scores(BaseModel):
    """Top-line session scoring. Each dimension is /100."""
    model_config = ConfigDict(frozen=True)
    pace: float
    consistency: float
    execution: float
    robustness: float
    overall: float

    @field_validator("pace", "consistency", "execution", "robustness", "overall")
    @classmethod
    def _range_0_100(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError(f"score must be in [0, 100], got {v}")
        return v


class SidecarRef(BaseModel):
    """Pointer to a raw-channel Parquet sidecar kept outside the contract."""
    model_config = ConfigDict(frozen=True)
    object_key: str
    format: str = "parquet"
    sha256: str | None = None
    size_bytes: int | None = None
```

- [x] **Step 2.4: Run tests**

```bash
pytest telemetry_tool/tests/test_contracts/test_common.py -v
```

Expected: 4 passed.

- [x] **Step 2.5: Commit**

```bash
git add telemetry_tool/web/schemas/contracts/common.py \
        telemetry_tool/tests/test_contracts/test_common.py
git commit -m "feat(contracts): common primitives (SourceLiteral, TrajectorySample, LapSummary, Scores)"
```

---

### Task 3: SessionContract (T1.1)

**Files:**
- Create: `telemetry_tool/web/schemas/contracts/session.py`
- Create: `telemetry_tool/tests/test_contracts/test_session_contract.py`
- Modify: `telemetry_tool/web/schemas/contracts/__init__.py` (add re-exports)

- [x] **Step 3.1: Write failing tests**

```python
# telemetry_tool/tests/test_contracts/test_session_contract.py
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts import (
    ChannelTag,
    DriverRef,
    LapSummary,
    Scores,
    SessionCapabilities,
    SessionContract,
    SourceLiteral,
    TrackRef,
    VehicleRef,
)


def _minimal_session(**overrides) -> SessionContract:
    base = {
        "session_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "source": SourceLiteral.REAL_LIFE,
        "capabilities": SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G})),
        "driver": DriverRef(driver_id=1, name="Theo"),
        "track": TrackRef(track_id=10, name="Ouest Karting"),
        "vehicle": VehicleRef(vehicle_class="kart"),
        "session_start": datetime.now(timezone.utc),
        "duration_s": 1234.5,
        "laps": [LapSummary(lap_number=1, lap_time_s=60.1)],
        "scores": Scores(pace=80, consistency=70, execution=75, robustness=85, overall=77),
        "data_profile": {"parser": "racechrono", "columns_detected": 14},
    }
    base.update(overrides)
    return SessionContract(**base)


def test_session_contract_constructs():
    s = _minimal_session()
    assert s.source is SourceLiteral.REAL_LIFE
    assert s.laps[0].lap_number == 1


def test_session_contract_json_roundtrip():
    s = _minimal_session()
    payload = s.model_dump_json()
    restored = SessionContract.model_validate_json(payload)
    assert restored == s


def test_session_contract_rejects_unknown_source():
    with pytest.raises(ValidationError):
        _minimal_session(source="lmu_not_yet_supported")


def test_session_contract_laps_can_be_empty():
    s = _minimal_session(laps=[])
    assert s.laps == []


def test_session_contract_capabilities_match_source_for_realife():
    """Real-life sessions MUST NOT claim THROTTLE/BRAKE/STEER — those are inferred, not measured."""
    with pytest.raises(ValidationError):
        _minimal_session(
            source=SourceLiteral.REAL_LIFE,
            capabilities=SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.THROTTLE})),
        )
```

- [x] **Step 3.2: Run to confirm failure**

```bash
pytest telemetry_tool/tests/test_contracts/test_session_contract.py -v
```

Expected: ImportError (`SessionContract` not defined).

- [x] **Step 3.3: Implement `session.py`**

```python
# telemetry_tool/web/schemas/contracts/session.py
"""SessionContract — the source-agnostic descriptor of a driven session."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)
from telemetry_tool.web.schemas.contracts.common import (
    DriverRef,
    Event,
    LapSummary,
    Scores,
    SidecarRef,
    SourceLiteral,
    TrackRef,
    VehicleRef,
)

CONTRACT_VERSION = "1.0"

# Channels that CAN NOT be directly measured on real-life hardware today.
# If a real_life session claims one of these, the profile detector is wrong.
_REAL_LIFE_FORBIDDEN: frozenset[ChannelTag] = frozenset({
    ChannelTag.THROTTLE,
    ChannelTag.BRAKE,
    ChannelTag.STEER,
    ChannelTag.WHEEL_SPD,
    ChannelTag.SHOCK_DEFL,
})


class SessionContract(BaseModel):
    """Unified, source-agnostic descriptor of one driven session."""
    model_config = ConfigDict(frozen=True)

    contract_version: str = Field(default=CONTRACT_VERSION, frozen=True)

    session_id: UUID | str
    workspace_id: UUID | str
    source: SourceLiteral
    capabilities: SessionCapabilities
    data_profile: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form dict describing how the file was detected + parsed. "
                    "Shape defined by W2 (profiler).",
    )

    driver: DriverRef
    track: TrackRef
    vehicle: VehicleRef

    session_start: datetime
    duration_s: float

    laps: list[LapSummary] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    scores: Scores | None = None

    sidecar: SidecarRef | None = Field(
        None,
        description="Pointer to raw-channel Parquet sidecar. Absent until W9 storage lands.",
    )

    @model_validator(mode="after")
    def _check_realife_capabilities(self) -> "SessionContract":
        if self.source is SourceLiteral.REAL_LIFE:
            illegal = self.capabilities.channels & _REAL_LIFE_FORBIDDEN
            if illegal:
                raise ValueError(
                    f"source=real_life may not claim capabilities {illegal} — "
                    "these are inferred, not measured, on real-life hardware"
                )
        return self
```

- [x] **Step 3.4: Re-export from package `__init__`**

```python
# telemetry_tool/web/schemas/contracts/__init__.py
"""Unified contracts for the W1 workstream."""
from __future__ import annotations

from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)
from telemetry_tool.web.schemas.contracts.common import (
    DriverRef,
    Event,
    LapSummary,
    Scores,
    SidecarRef,
    SourceLiteral,
    TrackRef,
    TrajectorySample,
    VehicleRef,
)
from telemetry_tool.web.schemas.contracts.session import (
    CONTRACT_VERSION,
    SessionContract,
)

__all__ = [
    "ChannelTag",
    "SessionCapabilities",
    "DriverRef",
    "Event",
    "LapSummary",
    "Scores",
    "SidecarRef",
    "SourceLiteral",
    "TrackRef",
    "TrajectorySample",
    "VehicleRef",
    "SessionContract",
    "CONTRACT_VERSION",
]
```

- [x] **Step 3.5: Run tests — expect green**

```bash
pytest telemetry_tool/tests/test_contracts/test_session_contract.py -v
```

Expected: 5 passed.

- [x] **Step 3.6: Commit**

```bash
git add telemetry_tool/web/schemas/contracts/session.py \
        telemetry_tool/web/schemas/contracts/__init__.py \
        telemetry_tool/tests/test_contracts/test_session_contract.py
git commit -m "feat(contracts): SessionContract + real_life capability guard (W1.T1.1)"
```

---

### Task 4: CoachingContract (T1.2) — harmonize with prescriptive

**Files:**
- Create: `telemetry_tool/web/schemas/contracts/coaching.py`
- Create: `telemetry_tool/tests/test_contracts/test_coaching_contract.py`
- Modify: `telemetry_tool/web/schemas/contracts/__init__.py`

**Rationale:** The existing `track_surface/prescriptive/types.py` defines dataclasses that shape `prescriptive_coaching` in `track-surface-ok-data.json`. We rebuild the same shape as Pydantic here, matching field names 1:1 so the existing viewers (`lap-studio-live.html`, `ouest-karting-live.html`) keep working when consumers switch to the contract. `COACHING_SHEET_VERSION = "1.0"` is the frozen anchor.

- [x] **Step 4.1: Write failing tests**

```python
# telemetry_tool/tests/test_contracts/test_coaching_contract.py
import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    FocusItem,
    StorylineItem,
    CornerCoachingItem,
    ValidationCheck,
    NextRunItem,
)


def test_coaching_contract_version_frozen_at_1_0():
    c = CoachingContract(
        storyline=[],
        global_focus=[],
        corner_coaching={},
        not_evaluable_corners=[],
        validation_checks=[],
        next_run=[],
    )
    assert c.version == "1.0"


def test_storyline_item_state_values():
    """State mirrors prescriptive refactor: Detected / NotTriggered / Insufficient / Unregistered."""
    valid = ["Detected", "NotTriggered", "Insufficient", "Unregistered"]
    for s in valid:
        StorylineItem(weakness_key="w.test", state=s, headline="hi")
    with pytest.raises(ValidationError):
        StorylineItem(weakness_key="w.test", state="Bogus", headline="hi")


def test_focus_item_severity_enum():
    FocusItem(rank=1, weakness_key="w.x", title="t", severity="high")
    FocusItem(rank=1, weakness_key="w.x", title="t", severity="low")
    with pytest.raises(ValidationError):
        FocusItem(rank=1, weakness_key="w.x", title="t", severity="critical")


def test_corner_coaching_map_accepts_string_ids():
    c = CoachingContract(
        storyline=[],
        global_focus=[],
        corner_coaching={"3": CornerCoachingItem(corner_id="3", items=[])},
        not_evaluable_corners=["5"],
        validation_checks=[],
        next_run=[],
    )
    assert "3" in c.corner_coaching
    assert c.not_evaluable_corners == ["5"]
```

- [x] **Step 4.2: Run to confirm failure**

```bash
pytest telemetry_tool/tests/test_contracts/test_coaching_contract.py -v
```

Expected: ImportError.

- [x] **Step 4.3: Implement `coaching.py`**

```python
# telemetry_tool/web/schemas/contracts/coaching.py
"""CoachingContract — harmonized with track_surface.prescriptive.types.

Field names mirror the existing ``prescriptive_coaching`` node in
``track-surface-ok-data.json`` so viewers that already consume that shape
keep working when they switch to the contract-typed API.

Version anchor mirrors ``track_surface.prescriptive.types.COACHING_SHEET_VERSION``.
If that anchor changes, bump the one here in the same commit + ADR.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

COACHING_SHEET_VERSION = "1.0"

Severity = Literal["high", "medium", "low"]
PhaseTag = Literal["entry", "brake_release", "apex", "exit", "straight"]
StorylineState = Literal["Detected", "NotTriggered", "Insufficient", "Unregistered"]
NextRunItemType = Literal[
    "technical_focus", "execution_focus", "validation_metric", "anti_overload"
]


class FocusItem(BaseModel):
    """One entry in ``global_focus`` — the top-3 ranked prescriptions."""
    model_config = ConfigDict(frozen=True)
    rank: int
    weakness_key: str
    title: str
    severity: Severity
    corner_ids: list[str] = Field(default_factory=list)
    cost_ms: float | None = None


class StorylineItem(BaseModel):
    """One narrative line in the coaching storyline."""
    model_config = ConfigDict(frozen=True)
    weakness_key: str
    state: StorylineState
    headline: str
    detail: str | None = None


class CornerCueItem(BaseModel):
    """A single cue attached to a corner within ``corner_coaching``."""
    model_config = ConfigDict(frozen=True)
    weakness_key: str
    phase: PhaseTag
    severity: Severity
    cue_text: str
    cost_ms: float | None = None


class CornerCoachingItem(BaseModel):
    """All cues that apply to one corner."""
    model_config = ConfigDict(frozen=True)
    corner_id: str
    items: list[CornerCueItem] = Field(default_factory=list)


class ValidationCheck(BaseModel):
    """A measurable target the driver can validate on the next run."""
    model_config = ConfigDict(frozen=True)
    check_id: str
    description: str
    measurable_target: str | None = None
    corner_id: str | None = None


class NextRunItem(BaseModel):
    """A structured next-run item (focus / metric / anti-overload)."""
    model_config = ConfigDict(frozen=True)
    item_type: NextRunItemType
    title: str
    body: str
    weakness_key: str | None = None


class CoachingContract(BaseModel):
    """Published, frontend-facing coaching sheet.

    Shape mirrors track_surface.prescriptive's ``prescriptive_coaching``
    node — see module docstring.
    """
    model_config = ConfigDict(frozen=True)

    version: str = Field(default=COACHING_SHEET_VERSION, frozen=True)

    storyline: list[StorylineItem]
    global_focus: list[FocusItem]
    corner_coaching: dict[str, CornerCoachingItem]
    not_evaluable_corners: list[str]
    validation_checks: list[ValidationCheck]
    next_run: list[NextRunItem]
```

- [x] **Step 4.4: Extend `__init__.py` re-exports**

Append to `__all__` and imports:

```python
from telemetry_tool.web.schemas.contracts.coaching import (
    COACHING_SHEET_VERSION,
    CoachingContract,
    CornerCoachingItem,
    CornerCueItem,
    FocusItem,
    NextRunItem,
    PhaseTag,
    Severity,
    StorylineItem,
    StorylineState,
    ValidationCheck,
)
```

Update `__all__` to include every new name.

- [x] **Step 4.5: Run tests**

```bash
pytest telemetry_tool/tests/test_contracts/test_coaching_contract.py -v
```

Expected: 4 passed.

- [x] **Step 4.6: Commit**

```bash
git add telemetry_tool/web/schemas/contracts/coaching.py \
        telemetry_tool/web/schemas/contracts/__init__.py \
        telemetry_tool/tests/test_contracts/test_coaching_contract.py
git commit -m "feat(contracts): CoachingContract harmonized with prescriptive (W1.T1.2)"
```

---

### Task 5: OptimizerContract (T1.3)

**Files:**
- Create: `telemetry_tool/web/schemas/contracts/optimizer.py`
- Create: `telemetry_tool/tests/test_contracts/test_optimizer_contract.py`
- Modify: `telemetry_tool/web/schemas/contracts/__init__.py`

- [x] **Step 5.1: Write failing tests**

```python
# telemetry_tool/tests/test_contracts/test_optimizer_contract.py
import pytest
from pydantic import ValidationError

from telemetry_tool.web.schemas.contracts import (
    OptimizerContract,
    OptimizerDepth,
    CornerDelta,
    ReconstructedInputs,
    TrajectoryDelta,
)


def _minimal_optimizer(**overrides) -> OptimizerContract:
    base = {
        "depth": OptimizerDepth.TRAJECTORY_ONLY,
        "method": "trajectory",
        "theoretical_lap_time_s": 90.123,
        "confidence": 0.82,
        "corner_deltas": [],
        "total_time_loss_s": 0.0,
    }
    base.update(overrides)
    return OptimizerContract(**base)


def test_optimizer_minimal():
    o = _minimal_optimizer()
    assert o.depth is OptimizerDepth.TRAJECTORY_ONLY
    assert o.reconstructed_inputs is None


def test_optimizer_confidence_range():
    _minimal_optimizer(confidence=0.0)
    _minimal_optimizer(confidence=1.0)
    with pytest.raises(ValidationError):
        _minimal_optimizer(confidence=1.5)


def test_full_fidelity_requires_reconstructed_inputs():
    """If depth is FULL_FIDELITY, reconstructed_inputs must be provided."""
    with pytest.raises(ValidationError):
        _minimal_optimizer(depth=OptimizerDepth.FULL_FIDELITY, reconstructed_inputs=None)

    _minimal_optimizer(
        depth=OptimizerDepth.FULL_FIDELITY,
        method="qss_enhanced",
        reconstructed_inputs=ReconstructedInputs(
            throttle=[], brake=[], steer=[], distance_m=[]
        ),
    )


def test_corner_delta_fields():
    cd = CornerDelta(corner_id="3", time_loss_s=0.42, root_cause="late_brake_release",
                    coaching_text="Release the brake ~10m earlier")
    assert cd.time_loss_s == 0.42
```

- [x] **Step 5.2: Run to confirm failure**

```bash
pytest telemetry_tool/tests/test_contracts/test_optimizer_contract.py -v
```

Expected: ImportError.

- [x] **Step 5.3: Implement `optimizer.py`**

```python
# telemetry_tool/web/schemas/contracts/optimizer.py
"""OptimizerContract — theoretical lap + delta attribution.

Two depth levels:

- TRAJECTORY_ONLY: computed from GPS + accelerations only (real-life).
  Produces a theoretical lap time and corner-level time loss. No driver-
  input traces.

- FULL_FIDELITY: uses param-ID'd physics + solver (sim racing).
  Produces everything above PLUS reconstructed input traces (optimal
  throttle/brake/steer at each distance step), enabling input-level
  delta coaching.

Field names align with ``sim_optimizer/output/summary.py`` where the sim
pipeline already emits a compatible shape.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OptimizerDepth(str, Enum):
    TRAJECTORY_ONLY = "trajectory_only"
    FULL_FIDELITY = "full_fidelity"


class CornerDelta(BaseModel):
    """Per-corner time loss attribution."""
    model_config = ConfigDict(frozen=True)
    corner_id: str
    time_loss_s: float
    root_cause: str
    coaching_text: str = ""
    phase: str | None = None


class TrajectoryDelta(BaseModel):
    """Distance-indexed speed delta between driver and theoretical."""
    model_config = ConfigDict(frozen=True)
    distance_m: list[float]
    speed_delta_ms: list[float]

    @model_validator(mode="after")
    def _equal_lengths(self) -> "TrajectoryDelta":
        if len(self.distance_m) != len(self.speed_delta_ms):
            raise ValueError("distance_m and speed_delta_ms must have equal length")
        return self


class ReconstructedInputs(BaseModel):
    """Theoretical throttle/brake/steer traces (only available in FULL_FIDELITY)."""
    model_config = ConfigDict(frozen=True)
    distance_m: list[float]
    throttle: list[float]
    brake: list[float]
    steer: list[float]

    @model_validator(mode="after")
    def _equal_lengths(self) -> "ReconstructedInputs":
        n = len(self.distance_m)
        if not (len(self.throttle) == len(self.brake) == len(self.steer) == n):
            raise ValueError("all input arrays must have the same length as distance_m")
        return self


class OptimizerContract(BaseModel):
    """Unified optimizer result."""
    model_config = ConfigDict(frozen=True)

    depth: OptimizerDepth
    method: str = Field(..., description="Underlying solver identifier, e.g. 'qss_enhanced' or 'trajectory'")
    theoretical_lap_time_s: float
    confidence: float = Field(..., description="Overall result confidence, 0..1")

    corner_deltas: list[CornerDelta] = Field(default_factory=list)
    total_time_loss_s: float = 0.0

    trajectory_delta: TrajectoryDelta | None = None
    reconstructed_inputs: ReconstructedInputs | None = None

    vehicle_model: dict[str, Any] = Field(default_factory=dict, description="Identified model params, free-form until W5")
    validation: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0,1], got {v}")
        return v

    @model_validator(mode="after")
    def _full_fidelity_requires_inputs(self) -> "OptimizerContract":
        if self.depth is OptimizerDepth.FULL_FIDELITY and self.reconstructed_inputs is None:
            raise ValueError("FULL_FIDELITY depth requires reconstructed_inputs")
        return self
```

- [x] **Step 5.4: Extend `__init__.py` re-exports**

Append to `__init__.py`:

```python
from telemetry_tool.web.schemas.contracts.optimizer import (
    CornerDelta,
    OptimizerContract,
    OptimizerDepth,
    ReconstructedInputs,
    TrajectoryDelta,
)
```

Update `__all__` accordingly.

- [x] **Step 5.5: Run tests**

```bash
pytest telemetry_tool/tests/test_contracts/test_optimizer_contract.py -v
```

Expected: 4 passed.

- [x] **Step 5.6: Commit**

```bash
git add telemetry_tool/web/schemas/contracts/optimizer.py \
        telemetry_tool/web/schemas/contracts/__init__.py \
        telemetry_tool/tests/test_contracts/test_optimizer_contract.py
git commit -m "feat(contracts): OptimizerContract with depth-gated invariants (W1.T1.3)"
```

---

### Task 6: JSON Schema export (T1.4 part A)

**Files:**
- Create: `telemetry_tool/web/schemas/contracts/_scripts/__init__.py`
- Create: `telemetry_tool/web/schemas/contracts/_scripts/export_json_schema.py`
- Create: `telemetry_tool/web/schemas/contracts/_schemas/.gitkeep`
- Create: `telemetry_tool/tests/test_contracts/test_schema_export.py`

- [x] **Step 6.1: Write failing test**

```python
# telemetry_tool/tests/test_contracts/test_schema_export.py
import json
from pathlib import Path

from telemetry_tool.web.schemas.contracts._scripts.export_json_schema import (
    export_all_schemas,
    SCHEMAS_DIR,
)


def test_export_produces_three_schemas(tmp_path: Path):
    out_dir = tmp_path / "schemas"
    written = export_all_schemas(out_dir)
    assert {p.name for p in written} == {
        "session.schema.json", "coaching.schema.json", "optimizer.schema.json",
    }
    for p in written:
        data = json.loads(p.read_text())
        assert "$schema" in data
        assert "title" in data


def test_committed_schemas_up_to_date():
    """If this fails, run: python -m telemetry_tool.web.schemas.contracts._scripts.export_json_schema"""
    from telemetry_tool.web.schemas.contracts.session import SessionContract
    committed = json.loads((SCHEMAS_DIR / "session.schema.json").read_text())
    fresh = SessionContract.model_json_schema()
    assert committed == fresh, "session.schema.json drifted — regenerate"
```

- [x] **Step 6.2: Run tests to confirm failure**

```bash
pytest telemetry_tool/tests/test_contracts/test_schema_export.py -v
```

Expected: ImportError.

- [x] **Step 6.3: Implement exporter**

```python
# telemetry_tool/web/schemas/contracts/_scripts/export_json_schema.py
"""Export Pydantic contracts to JSON Schema files.

Run as module:
    python -m telemetry_tool.web.schemas.contracts._scripts.export_json_schema

The output files are checked in under ``_schemas/`` so frontend builds do
not require a Python step. CI enforces freshness via
``test_committed_schemas_up_to_date``.
"""
from __future__ import annotations

import json
from pathlib import Path

from telemetry_tool.web.schemas.contracts.coaching import CoachingContract
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerContract
from telemetry_tool.web.schemas.contracts.session import SessionContract

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "_schemas"

_TARGETS = {
    "session.schema.json": SessionContract,
    "coaching.schema.json": CoachingContract,
    "optimizer.schema.json": OptimizerContract,
}


def export_all_schemas(out_dir: Path = SCHEMAS_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fname, model in _TARGETS.items():
        schema = model.model_json_schema()
        # Ensure deterministic ordering for diffable commits.
        text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        path = out_dir / fname
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for p in export_all_schemas():
        print(f"wrote {p}")
```

Also create `_schemas/.gitkeep` as an empty file so the directory is tracked.

- [x] **Step 6.4: Run exporter once, commit schemas**

```bash
python -m telemetry_tool.web.schemas.contracts._scripts.export_json_schema
```

Verify three `.schema.json` files appeared in `_schemas/`.

- [x] **Step 6.5: Run tests**

```bash
pytest telemetry_tool/tests/test_contracts/test_schema_export.py -v
```

Expected: 2 passed.

- [x] **Step 6.6: Commit**

```bash
git add telemetry_tool/web/schemas/contracts/_scripts/ \
        telemetry_tool/web/schemas/contracts/_schemas/ \
        telemetry_tool/tests/test_contracts/test_schema_export.py
git commit -m "feat(contracts): JSON Schema export + drift detection (W1.T1.4a)"
```

---

### Task 7: TypeScript types generation (T1.4 part B)

**Files:**
- Create: `telemetry_tool/web/schemas/contracts/_scripts/generate_ts.py`
- Create: `lap-website/src/types/contracts.ts`
- Create: `telemetry_tool/tests/test_contracts/test_ts_generation.py`

**Approach:** Python-only JSON-Schema→TS converter. Handles the subset we use: named objects, enums, literals, arrays, primitives, optional fields, unions. No npm dep (F2 resolution).

- [x] **Step 7.1: Write failing test**

```python
# telemetry_tool/tests/test_contracts/test_ts_generation.py
from pathlib import Path

from telemetry_tool.web.schemas.contracts._scripts.generate_ts import (
    generate_ts_file,
    TS_OUTPUT_PATH,
)


def test_generator_writes_typescript(tmp_path: Path):
    out = tmp_path / "contracts.ts"
    generate_ts_file(out)
    text = out.read_text()

    # Presence of the three top-level interfaces
    for name in ("SessionContract", "CoachingContract", "OptimizerContract"):
        assert f"export interface {name}" in text, f"missing interface: {name}"

    # ChannelTag enum
    assert "export enum ChannelTag" in text or "export type ChannelTag" in text
    # SourceLiteral enum/union
    for v in ("real_life", "iracing", "ac"):
        assert v in text, f"source value missing: {v}"


def test_committed_ts_up_to_date():
    """CI gate: if this fails, regenerate with:
        python -m telemetry_tool.web.schemas.contracts._scripts.generate_ts
    """
    from telemetry_tool.web.schemas.contracts._scripts.generate_ts import (
        generate_ts_string,
    )
    fresh = generate_ts_string()
    on_disk = TS_OUTPUT_PATH.read_text()
    assert fresh == on_disk, "contracts.ts drifted — regenerate"
```

- [x] **Step 7.2: Run to confirm failure**

```bash
pytest telemetry_tool/tests/test_contracts/test_ts_generation.py -v
```

Expected: ImportError.

- [x] **Step 7.3: Implement generator**

```python
# telemetry_tool/web/schemas/contracts/_scripts/generate_ts.py
"""Python-only JSON-Schema → TypeScript generator for our contracts.

Scope is deliberately narrow — we only translate the subset emitted by
our Pydantic models:
  - object types → `export interface`
  - string enums → `export enum` (backed by string values)
  - $ref references → reference by `title`
  - arrays, primitives, optional fields, anyOf with a single type + null
  - Literal unions → string union types

If Pydantic emits something outside this subset, the generator raises
loudly rather than silently skipping, so the test suite catches drift.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from telemetry_tool.web.schemas.contracts._scripts.export_json_schema import (
    SCHEMAS_DIR,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
TS_OUTPUT_PATH = _REPO_ROOT / "lap-website" / "src" / "types" / "contracts.ts"

_HEADER = """\
// AUTO-GENERATED — DO NOT EDIT BY HAND.
// Source: telemetry_tool/web/schemas/contracts/_schemas/*.schema.json
// Regenerate with:
//   python -m telemetry_tool.web.schemas.contracts._scripts.generate_ts

"""


def _ts_primitive(js_type: str) -> str:
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }[js_type]


def _resolve_type(node: dict[str, Any], root: dict[str, Any]) -> str:
    """Translate one JSON-Schema node to a TS type expression."""
    if "$ref" in node:
        ref = node["$ref"]  # e.g. "#/$defs/DriverRef"
        name = ref.rsplit("/", 1)[-1]
        return name
    if "enum" in node:
        return " | ".join(json.dumps(v) for v in node["enum"])
    if "const" in node:
        return json.dumps(node["const"])
    if "anyOf" in node:
        parts = [_resolve_type(sub, root) for sub in node["anyOf"]]
        return " | ".join(parts)
    if "type" in node:
        t = node["type"]
        if t == "array":
            item = _resolve_type(node.get("items", {"type": "string"}), root)
            return f"Array<{item}>"
        if t == "object":
            # Inline object — fall back to Record<string, unknown>
            if "additionalProperties" in node:
                ap = node["additionalProperties"]
                if isinstance(ap, dict):
                    return f"Record<string, {_resolve_type(ap, root)}>"
                return "Record<string, unknown>"
            return "Record<string, unknown>"
        return _ts_primitive(t)
    # Fallback
    return "unknown"


def _render_object(name: str, schema: dict[str, Any], root: dict[str, Any]) -> str:
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines = [f"export interface {name} {{"]
    for prop_name, prop_schema in props.items():
        opt = "" if prop_name in required else "?"
        ts_type = _resolve_type(prop_schema, root)
        desc = prop_schema.get("description")
        if desc:
            lines.append(f"  /** {desc} */")
        lines.append(f"  {prop_name}{opt}: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


def _render_enum(name: str, values: list[str]) -> str:
    lines = [f"export type {name} ="]
    for v in values:
        lines.append(f"  | {json.dumps(v)}")
    return "\n".join(lines) + ";"


def _emit_schema(schema: dict[str, Any]) -> list[str]:
    """Emit top-level interface + every $def as an interface or enum."""
    blocks: list[str] = []
    defs = schema.get("$defs", {})
    for name, sub in defs.items():
        if "enum" in sub and sub.get("type") == "string":
            blocks.append(_render_enum(name, sub["enum"]))
        else:
            blocks.append(_render_object(name, sub, schema))
    # Top-level
    title = schema.get("title", "Unknown")
    blocks.append(_render_object(title, schema, schema))
    return blocks


def generate_ts_string() -> str:
    seen: set[str] = set()
    blocks: list[str] = []
    for fname in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(fname.read_text())
        for block in _emit_schema(schema):
            # Dedup by first line header
            header = block.split("\n", 1)[0]
            if header in seen:
                continue
            seen.add(header)
            blocks.append(block)
    return _HEADER + "\n\n".join(blocks) + "\n"


def generate_ts_file(out_path: Path = TS_OUTPUT_PATH) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate_ts_string(), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    p = generate_ts_file()
    print(f"wrote {p}")
```

- [x] **Step 7.4: Run the generator to produce `contracts.ts`**

```bash
python -m telemetry_tool.web.schemas.contracts._scripts.generate_ts
```

Verify: `lap-website/src/types/contracts.ts` exists, starts with `// AUTO-GENERATED`, contains three `export interface` declarations.

- [x] **Step 7.5: Verify frontend still type-checks**

```bash
cd lap-website && npm run build 2>&1 | tail -20
```

Expected: build succeeds, no TS errors referencing `contracts.ts`.

- [x] **Step 7.6: Run tests**

```bash
pytest telemetry_tool/tests/test_contracts/test_ts_generation.py -v
```

Expected: 2 passed.

- [x] **Step 7.7: Commit**

```bash
git add telemetry_tool/web/schemas/contracts/_scripts/generate_ts.py \
        lap-website/src/types/contracts.ts \
        telemetry_tool/tests/test_contracts/test_ts_generation.py
git commit -m "feat(contracts): Python-only TS generator + contracts.ts (W1.T1.4b)"
```

---

### Task 8: Alembic migration 022 (T1.5)

**Files:**
- Create: `alembic/versions/022_ws_w1_sessions_source_profile_caps.py`
- Create: `telemetry_tool/tests/test_contracts/test_migration_022.py`

**Blocker check:** Before writing the migration, verify current sessions schema matches assumptions.

- [x] **Step 8.1: Inspect current sessions table structure**

```bash
alembic current
```

Expected: `021 (head)` — if different, stop and ask.

```bash
psql "$TELEMETRY_PG_URL" -c "\d sessions" | head -40
```

Confirm `source`, `data_profile`, `capabilities` columns do NOT exist. If they do, stop and ask.

- [x] **Step 8.2: Write failing test**

```python
# telemetry_tool/tests/test_contracts/test_migration_022.py
"""Validates the 022 migration upgrades and downgrades cleanly.

Uses a temp PG database when TELEMETRY_PG_URL_TEST is set; otherwise
skips (keeps CI green on sqlite-only environments).
"""
from __future__ import annotations

import os
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TELEMETRY_PG_URL_TEST"),
    reason="needs a disposable PG; set TELEMETRY_PG_URL_TEST",
)


def _alembic(args: list[str]):
    env = {**os.environ, "TELEMETRY_PG_URL": os.environ["TELEMETRY_PG_URL_TEST"]}
    return subprocess.check_call(["alembic", *args], env=env)


def test_022_upgrade_then_downgrade_is_clean():
    _alembic(["upgrade", "021"])
    _alembic(["upgrade", "022"])
    _alembic(["downgrade", "021"])
    # Reapplying should still succeed.
    _alembic(["upgrade", "022"])


def test_022_adds_expected_columns():
    import psycopg2
    _alembic(["upgrade", "022"])
    conn = psycopg2.connect(os.environ["TELEMETRY_PG_URL_TEST"])
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name='sessions'
              AND column_name IN ('source', 'data_profile', 'capabilities')
        """)
        rows = dict(cur.fetchall())
    assert rows.get("source") == "text"
    assert rows.get("data_profile") == "jsonb"
    assert rows.get("capabilities") == "jsonb"
```

- [x] **Step 8.3: Write migration**

```python
# alembic/versions/022_ws_w1_sessions_source_profile_caps.py
"""Add source, data_profile, capabilities to sessions (W1.T1.5).

Backfill policy:
  - source          = 'real_life'   (every existing session came from GPS+IMU)
  - data_profile    = '{}'::jsonb   (unknown; profiler will enrich on next re-ingest)
  - capabilities    = '{"channels": ["gps"]}'::jsonb  (safe minimum; GPS always present)

Rollback drops the three columns.

Revision ID: 022
Revises: 021
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("source", sa.Text(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("data_profile", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("capabilities", sa.dialects.postgresql.JSONB(), nullable=True),
    )

    # Backfill existing rows
    op.execute(
        """
        UPDATE sessions
           SET source = 'real_life'
         WHERE source IS NULL
        """
    )
    op.execute(
        """
        UPDATE sessions
           SET data_profile = '{}'::jsonb
         WHERE data_profile IS NULL
        """
    )
    op.execute(
        """
        UPDATE sessions
           SET capabilities = '{"channels": ["gps"]}'::jsonb
         WHERE capabilities IS NULL
        """
    )

    # Lock in NOT NULL now that backfill is done
    op.alter_column("sessions", "source", nullable=False)
    op.alter_column("sessions", "data_profile", nullable=False)
    op.alter_column("sessions", "capabilities", nullable=False)


def downgrade():
    op.drop_column("sessions", "capabilities")
    op.drop_column("sessions", "data_profile")
    op.drop_column("sessions", "source")
```

- [x] **Step 8.4: Apply migration on local dev DB**

```bash
alembic upgrade head
```

Expected: `021 -> 022` in output. No errors.

- [x] **Step 8.5: Verify + rollback cleanly**

```bash
alembic downgrade 021
alembic upgrade 022
```

Both must succeed.

- [x] **Step 8.6: Run migration tests (skipped locally unless TELEMETRY_PG_URL_TEST set)**

```bash
pytest telemetry_tool/tests/test_contracts/test_migration_022.py -v
```

- [x] **Step 8.7: Commit**

```bash
git add alembic/versions/022_ws_w1_sessions_source_profile_caps.py \
        telemetry_tool/tests/test_contracts/test_migration_022.py
git commit -m "feat(db): migration 022 — sessions.source/data_profile/capabilities (W1.T1.5)"
```

---

### Task 9: Contract fixtures (W1 downstream deliverable)

**Files:**
- Create: `telemetry_tool/web/schemas/contracts/fixtures/session_realife.json`
- Create: `telemetry_tool/web/schemas/contracts/fixtures/session_iracing.json`
- Create: `telemetry_tool/web/schemas/contracts/fixtures/coaching_realife.json`
- Create: `telemetry_tool/web/schemas/contracts/fixtures/coaching_iracing.json`
- Create: `telemetry_tool/web/schemas/contracts/fixtures/optimizer_trajectory.json`
- Create: `telemetry_tool/web/schemas/contracts/fixtures/optimizer_fullfidelity.json`
- Create: `telemetry_tool/web/schemas/contracts/fixtures/__init__.py` (loader helpers)
- Create: `telemetry_tool/tests/test_contracts/test_fixtures_roundtrip.py`

**Rationale:** Wave 2 workstreams mock against these JSON files. Each fixture is one valid instance. They're loaded, validated, and round-tripped in the test.

- [x] **Step 9.1: Write fixtures loader + roundtrip test**

```python
# telemetry_tool/web/schemas/contracts/fixtures/__init__.py
"""Fixtures for downstream workstreams — each JSON validates against its contract."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def load_fixture(name: str) -> dict:
    """Load a fixture by bare name (e.g. 'session_realife')."""
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))
```

```python
# telemetry_tool/tests/test_contracts/test_fixtures_roundtrip.py
import json

import pytest

from telemetry_tool.web.schemas.contracts import (
    CoachingContract,
    OptimizerContract,
    SessionContract,
)
from telemetry_tool.web.schemas.contracts.fixtures import load_fixture

_CASES = [
    ("session_realife", SessionContract),
    ("session_iracing", SessionContract),
    ("coaching_realife", CoachingContract),
    ("coaching_iracing", CoachingContract),
    ("optimizer_trajectory", OptimizerContract),
    ("optimizer_fullfidelity", OptimizerContract),
]


@pytest.mark.parametrize("name,model", _CASES)
def test_fixture_validates_and_roundtrips(name, model):
    raw = load_fixture(name)
    parsed = model.model_validate(raw)
    # Roundtrip must preserve JSON shape
    emitted = json.loads(parsed.model_dump_json())
    # Compare as sets of top-level keys to absorb datetime serialization differences.
    assert set(emitted.keys()) == set(raw.keys()), f"{name}: key drift"
```

- [x] **Step 9.2: Write the 6 fixture JSONs**

Each fixture must validate against its contract. Build them by running the contracts' constructors with representative data, then serializing. Example for `session_realife.json`:

```python
# Generate then save — run as a one-off in a Python shell or notebook:
from datetime import datetime, timezone
from telemetry_tool.web.schemas.contracts import *

s = SessionContract(
    session_id="11111111-1111-1111-1111-111111111111",
    workspace_id="22222222-2222-2222-2222-222222222222",
    source=SourceLiteral.REAL_LIFE,
    capabilities=SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G})),
    data_profile={"parser": "racechrono", "columns_detected": 14},
    driver=DriverRef(driver_id=1, name="Theo"),
    track=TrackRef(track_id=10, name="Ouest Karting"),
    vehicle=VehicleRef(vehicle_class="kart"),
    session_start=datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc),
    duration_s=1234.5,
    laps=[LapSummary(lap_number=1, lap_time_s=60.1, is_best=True)],
    events=[],
    scores=Scores(pace=80, consistency=70, execution=75, robustness=85, overall=77),
)
print(s.model_dump_json(indent=2))
```

Save the printed JSON verbatim to the fixture file.

**Rules for each fixture:**
- `session_realife.json` — source="real_life", capabilities GPS/LAT_G/LON_G only
- `session_iracing.json` — source="iracing", capabilities include THROTTLE/BRAKE/STEER/WHEEL_SPD/SHOCK_DEFL/YAW_RATE
- `coaching_realife.json` — shape reflects "limited depth" (storyline has some `Insufficient` state entries, fewer cues)
- `coaching_iracing.json` — shape reflects full-depth coaching
- `optimizer_trajectory.json` — depth="trajectory_only", no reconstructed_inputs
- `optimizer_fullfidelity.json` — depth="full_fidelity", includes `reconstructed_inputs` arrays (≥3 samples each for schema correctness)

- [x] **Step 9.3: Run the roundtrip test**

```bash
pytest telemetry_tool/tests/test_contracts/test_fixtures_roundtrip.py -v
```

Expected: 6 passed.

- [x] **Step 9.4: Commit**

```bash
git add telemetry_tool/web/schemas/contracts/fixtures/ \
        telemetry_tool/tests/test_contracts/test_fixtures_roundtrip.py
git commit -m "feat(contracts): reference fixtures for downstream mocking (W1 deliverable)"
```

---

### Task 10: Backward-compat for existing session data (T1.6)

**Files:**
- Create: `telemetry_tool/tests/test_contracts/test_backcompat.py`

**Rationale:** Existing sessions predate the contract. Any routine that constructs a `SessionContract` from a legacy DB row must survive missing fields (use defaults). Acceptance requires backward-compat.

- [x] **Step 10.1: Write the back-compat test**

```python
# telemetry_tool/tests/test_contracts/test_backcompat.py
"""Ensure contracts accept legacy-shaped dicts that existing code still emits."""
from datetime import datetime, timezone

from telemetry_tool.web.schemas.contracts import (
    ChannelTag,
    CoachingContract,
    DriverRef,
    OptimizerContract,
    OptimizerDepth,
    Scores,
    SessionCapabilities,
    SessionContract,
    SourceLiteral,
    TrackRef,
    VehicleRef,
)


def test_session_contract_accepts_pre_migration_row():
    """A session row that existed before migration 022 — no source, no profile, no caps.
    Adapters should default source to 'real_life' + minimal caps + empty profile."""
    legacy = {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "workspace_id": "22222222-2222-2222-2222-222222222222",
        "source": "real_life",
        "capabilities": {"channels": ["gps"]},
        "data_profile": {},
        "driver": {"driver_id": 1, "name": "Theo"},
        "track": {"track_id": 10, "name": "OK"},
        "vehicle": {"vehicle_class": "kart"},
        "session_start": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
        "duration_s": 1000.0,
        "laps": [],
        "scores": None,
    }
    s = SessionContract.model_validate(legacy)
    assert s.source is SourceLiteral.REAL_LIFE


def test_coaching_contract_accepts_empty_sheets():
    """Real-life sessions with insufficient data emit an empty-ish sheet; still valid."""
    c = CoachingContract(
        storyline=[],
        global_focus=[],
        corner_coaching={},
        not_evaluable_corners=[],
        validation_checks=[],
        next_run=[],
    )
    assert c.version == "1.0"


def test_optimizer_trajectory_only_from_legacy_real_life():
    """A real-life session can emit a minimal OptimizerContract without inputs."""
    o = OptimizerContract(
        depth=OptimizerDepth.TRAJECTORY_ONLY,
        method="trajectory",
        theoretical_lap_time_s=60.0,
        confidence=0.5,
    )
    assert o.reconstructed_inputs is None
```

- [x] **Step 10.2: Run**

```bash
pytest telemetry_tool/tests/test_contracts/test_backcompat.py -v
```

Expected: 3 passed.

- [x] **Step 10.3: Commit**

```bash
git add telemetry_tool/tests/test_contracts/test_backcompat.py
git commit -m "test(contracts): backward-compat + empty-sheet validation (W1.T1.6)"
```

---

### Task 11: Full suite green + update plan checklist

- [x] **Step 11.1: Run the whole new test module**

```bash
pytest telemetry_tool/tests/test_contracts/ -v
```

Expected: all passing (approx 25–30 tests total across 8 files).

- [x] **Step 11.2: Regenerate artefacts to catch drift**

```bash
python -m telemetry_tool.web.schemas.contracts._scripts.export_json_schema
python -m telemetry_tool.web.schemas.contracts._scripts.generate_ts
git diff --exit-code telemetry_tool/web/schemas/contracts/_schemas/ lap-website/src/types/contracts.ts
```

Expected: no diff (schemas and TS already up to date). If diff: commit regeneration.

- [x] **Step 11.3: Update this plan file with checkbox status**

Mark every `- [x]` → `- [x]` in this document and commit:

```bash
git add docs/superpowers/plans/2026-04-19-W1-contracts.md
git commit -m "docs(plan): W1 contracts — all tasks complete"
```

- [x] **Step 11.4: Announce handoff to downstream workstreams**

Post the following summary to the team channel / issue (human step, not a commit):

> W1 (contracts) delivered on `feat/ws-w1-contracts`:
> - `telemetry_tool/web/schemas/contracts/` package exporting `SessionContract`, `CoachingContract`, `OptimizerContract`, `ChannelTag`, `SessionCapabilities`.
> - `_schemas/*.schema.json` (committed, drift-gated).
> - `lap-website/src/types/contracts.ts` (committed, drift-gated).
> - `alembic/versions/022_ws_w1_sessions_source_profile_caps.py` — applies + rolls back cleanly.
> - `fixtures/*.json` — 6 valid instances for Wave 2 mocking.
> Downstream (W2–W9) can now import from `telemetry_tool.web.schemas.contracts`.

---

## Acceptance check (mirrors user brief)

| Criterion | Covered by |
|-----------|-----------|
| Contracts importable | Task 1, 3, 4, 5 + `__init__.py` re-exports |
| Validation tests pass | Tasks 3, 4, 5, 9, 10 + Task 11.1 full-suite |
| TS regenerates | Task 7 + drift gate in Task 11.2 |
| Migration applies and rolls back cleanly | Task 8.5 + migration test 8.6 |
| Capability flags enum covers GPS, LAT_G, LON_G, YAW_RATE, THROTTLE, BRAKE, STEER, WHEEL_SPD, SHOCK_DEFL | Task 1.1 test + enum definition 1.3 |
| Fixtures shipped (one per contract) | Task 9 (6 fixtures — two per contract, one lite + one full) |

## Post-implementation summary for Wave 2

Downstream workstreams (W2 router, W3/W4 adapters, W6 coaches, W7 optimizer, W8 frontend) should:

1. Import contracts exclusively from `telemetry_tool.web.schemas.contracts`
2. Use fixtures from `telemetry_tool/web/schemas/contracts/fixtures/` for integration tests
3. Consume generated TS types from `lap-website/src/types/contracts.ts`
4. Do NOT re-define `ChannelTag`, `SourceLiteral`, or any contract field names
5. Extensions require a new contract version + ADR, not silent field additions

---

## W1 Delivery Summary (completed 2026-04-19)

**Branch:** `feat/ws-w1-contracts`

**Final test count:** 44 passed, 2 skipped (0 failed). The 2 skipped tests require `TELEMETRY_PG_URL_TEST` for the Alembic migration and will run in CI.

**Deliverables shipped:**
- `telemetry_tool/web/schemas/contracts/` package — SessionContract, CoachingContract, OptimizerContract, ChannelTag/SessionCapabilities, plus common primitives and 4 Literal type aliases
- `_schemas/*.schema.json` — drift-gated, parametrized across all 3 contracts
- `lap-website/src/types/contracts.ts` — generated via Python-only converter, drift-gated, UTF-8 portable
- `alembic/versions/022_ws_w1_sessions_source_profile_caps.py` — adds source, data_profile, capabilities to sessions with backfill; clean up+down
- 6 reference fixtures in `fixtures/*.json` — two per contract (lite / full), validating against contracts and roundtripping via JSON

**Decisions recorded during implementation:**
- `session_id`/`workspace_id` narrowed from `UUID | str` to `str` due to Pydantic 2.12.5 smart-union roundtrip bug (union coerces str → UUID on deserialise, breaking equality).
- Python-only TS generator chosen over npm `json-schema-to-typescript` to avoid modifying `lap-website/package.json` — generator handles current Pydantic-v2 output subset and raises loudly on unrecognised node shapes.
- Fixtures use `contextlib.closing` for psycopg2 connection in migration test to avoid resource leaks.
- Real-life sessions are validated at the contract boundary to forbid claiming THROTTLE/BRAKE/STEER/WHEEL_SPD/SHOCK_DEFL capabilities (these are inferred in real-life, not measured).
- Symmetric depth/inputs guard on OptimizerContract: TRAJECTORY_ONLY rejects reconstructed_inputs; FULL_FIDELITY requires them.

**Downstream (W2–W10) — how to consume:**
- Import contracts from `telemetry_tool.web.schemas.contracts` (single barrel)
- Load fixtures via `telemetry_tool.web.schemas.contracts.fixtures.load_fixture(name)` — see `fixtures/__init__.py`
- Use generated TS types from `lap-website/src/types/contracts.ts`
- If a Pydantic model changes, regenerate BOTH `_schemas/*.json` (via `export_json_schema`) and `contracts.ts` (via `generate_ts`). The drift gate tests will fail CI if either drifts.
- Contract extensions require a new contract version + ADR — do not silently add fields.
