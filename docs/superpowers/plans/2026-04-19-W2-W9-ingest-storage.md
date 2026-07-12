# W2 + W9 — Ingest Router + Multi-source Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec anchor:** `docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md` (§1–§3, §5 W2 + W9, §11).

**Goal:** Make `POST /api/v1/sessions/upload` accept any supported telemetry file (RaceChrono CSV, iRacing IBT, AC CSV), classify it via a profiler, dispatch it to the correct engine handler through a registry, and persist the raw channel data as a Parquet sidecar so any session can be re-analyzed later. Every session row gains `source`, `data_profile`, `capabilities`.

**Architecture:**
- **W2** composes on the *existing* `telemetry_tool/adapters/registry.py` (which already detects 14 formats via magic bytes). A new `ingest/profiler.py` consumes the adapter result and a sampled column set to produce a `DataProfile` (source / channels_available / suggested_engine / confidence). A new `ingest/registry.py` holds a `HandlerRegistry`; `ingest/router.py` resolves `DataProfile → EngineHandler`. The real-life handler delegates to the existing `build_pipeline_chain`. Sim handlers are stub-injected here and replaced in sessions #4 (real-life productionisation) and #5 (iRacing + AC adapters).
- **W9** introduces `telemetry_tool/storage/sidecar_store.py` that writes raw DataFrames to `/data/sidecars/{workspace_id}/{session_id}/raw.parquet` (snappy, sha256-addressable), stores a `SidecarRef` on the `SessionContract`, enforces a configurable retention window (default 30 days), and ships a rerunnable backfill script + an Alembic-rollback runbook. W1's sessions-table migration is re-numbered (see §0).

**Tech Stack:** Python 3, Flask, Pydantic v2 (contracts from W1), Celery 5 (sim queue added), Alembic (Postgres 16), PyArrow (parquet), psycopg2, pytest.

---

## 0. Blockers — RESOLVE BEFORE APPROVAL

These were discovered during plan-time inventory. All must be resolved (by user decision or by me in a pre-amble commit) before any T-task below starts. Each has a concrete proposed fix and is tagged P0 (blocks the plan) or P1 (blocks merge).

| # | Severity | Finding | Proposed fix |
|---|----------|---------|--------------|
| B1 | **P0** | W1 branch `feat/ws-w1-contracts` is **not merged** to `main`. `git log --grep "signal:W1-done"` returns 0 results. The session prompt says this is a hard dependency. | Merge W1 first (either the integration driver does it from the launch README, or I can propose a rebase-onto-main PR). **Question to user**: do you want me to merge W1 as part of this work, or should I gate on external merge? |
| B2 | **P0** | W1's migration lives at **`alembic/versions/022_ws_w1_sessions_source_profile_caps.py`** (repo root). The project's actual alembic config is at `telemetry_tool/alembic.ini` with `script_location = alembic` → **`telemetry_tool/alembic/versions/`**. W1's migration is in the *wrong directory* and will not be picked up by `alembic upgrade head`. | Move the file to `telemetry_tool/alembic/versions/` during the W9.T1 verify step. Delete the top-level `alembic/` directory stub. |
| B3 | **P0** | `revision = "022"` on W1's migration **collides** with `telemetry_tool/alembic/versions/022_race_control.py` already on `main` (also `revision = "022"`, `down_revision = "021"`). W1 was planned before the admin race-control work landed. | Renumber W1's migration to **`059_ws_w1_sessions_source_profile_caps.py`** with `revision = "059"`, `down_revision = "058"`. Update `test_migration_022.py` to `test_migration_059.py` and bump the argv. |
| B4 | P1 | The launch README and session prompt reference `docs/architecture/2026-04-19-unified-coaching-architecture-design.md`. The actual path is `docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md`. | Already using the real path throughout this plan. Flag the README correction to the integration driver. |
| B5 | P1 | Launch README claims "contract fixtures committed to `fixtures/contracts/`". Actual path is `telemetry_tool/web/schemas/contracts/fixtures/*.json` (7 files: 2 session, 2 coaching, 2 optimizer + loader). | Use real path in tests. No code change needed. |
| B6 | P1 | Launch README worktree command uses `../worktrees/$ws`; the repo convention is **`.worktrees/`** (dot-prefix, inside repo root) — see existing `.worktrees/ws-w1-contracts` and `.worktrees/feat-ocp-solver`. | Follow repo convention: `git worktree add .worktrees/ws-w2-w9-ingest-storage -b feat/ws-w2-w9-ingest-storage main`. |
| B7 | P1 | Worktree `.worktrees/ws-w2-w9-ingest-storage` and branch `feat/ws-w2-w9-ingest-storage` do not yet exist. | Created in the "Bootstrap" step below, after W1 is merged. |
| B8 | P2 | `CLAUDE.md` (repo root) states that sessions_v2 runs the pipeline "synchronously in the request thread". Current implementation on `main` (`telemetry_tool/web/routes/sessions_v2.py`) uses Celery (`build_pipeline_chain(job_id).apply_async(...)`) and returns HTTP 202. The CLAUDE.md note is stale. | No code change from us — but T2.4 assumes the Celery-dispatch model and explicitly re-uses it, not the synchronous-request model. |

**Open product question (spec §10 Q3):** Sidecar retention default. I've set **30 days, env-overridable via `SIDECAR_RETENTION_DAYS`**, enforced by a daily Celery-beat job. Tiered retention (paid customers keep longer) is left for a follow-up because it requires plan-entitlement plumbing.

---

## 1. Design Decisions — Locked Down

### 1.1 HandlerRegistry interface (stable for #4 and #5)

Exactly the shape in the launch prompt, plus one tie-breaking rule. Keep the surface minimal:

```python
# telemetry_tool/ingest/registry.py
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.web.schemas.contracts import SourceLiteral


@runtime_checkable
class EngineHandler(Protocol):
    """One handler per engine family. Sessions #4 + #5 supply the real ones."""
    SOURCE: SourceLiteral
    PRIORITY: int  # higher wins on tie; default 0 (see 1.1.1)

    def can_handle(self, profile: DataProfile) -> bool: ...
    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str:
        """Return a job_id suitable for polling via /api/v1/jobs/<id>."""
        ...


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: list[EngineHandler] = []

    def register(self, handler: EngineHandler) -> None: ...
    def resolve(self, profile: DataProfile) -> EngineHandler: ...
    def unregister(self, source: SourceLiteral) -> None: ...  # test helper
```

#### 1.1.1 Resolution tie-break

If two handlers return `can_handle(profile) == True`:

1. Prefer the handler whose `SOURCE == profile.source`.
2. Otherwise prefer higher `PRIORITY` (default 0).
3. Ties after both = `NoHandlerResolvableError`.

> **Learning-mode contribution point — see Task T2.3, Step 4.** The resolution-tie code (~8 lines) is where you choose the rule. The default above favors explicit source-match; alternatives are registration-order, confidence-weighted, or "strictest match wins". The choice shapes how sessions #4/#5 register — document the rule in the docstring.

### 1.2 `DataProfile` — consumes W1's `SourceLiteral` and `ChannelTag`

```python
# telemetry_tool/ingest/profiler.py  (excerpt)
from pydantic import BaseModel, ConfigDict, Field
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


class DataProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: SourceLiteral
    parser: str                        # matches adapter FORMAT_NAME (e.g. "racechrono", "iracing_ibt")
    channels_available: frozenset[ChannelTag]
    suggested_engine: str              # "real_life_pipeline" | "sim_optimizer" | "ac_pipeline"
    confidence: float = Field(ge=0.0, le=1.0)
    sample_hz: float | None = None
    total_channels_detected: int | None = None  # distinct column count — sim only
```

Note on `channels_available`: uses W1's `ChannelTag` enum *literally* — only 9 canonical tags. The profiler maps adapter column names → tags; unknown columns don't appear.

### 1.3 Celery queue split

Current `telemetry_tool/celery_app.py:69-74` has `pipeline` + `default`. We add `sim`:

| Queue | Tasks routed | Concurrency | Memory ceiling | Rationale |
|-------|--------------|-------------|----------------|-----------|
| `pipeline` | `tasks.pipeline_tasks.*`, `tasks.training_tasks.*`, `tasks.ocp_tasks.*` | 2 | 2 GB/worker | Real-life 14-stage pipeline; peaks at ~1 GB for 200-col 10 GB CSVs. |
| `sim` *(new)* | `tasks.sim_tasks.*` | 2 | 4 GB/worker | iRacing IBT is 332 channels × 360 Hz; sessions can deserialise >500 MB into pandas. |
| `default` | `tasks.batch_tasks.*`, billing / gdpr / email / retention / rollups | 4 | 512 MB/worker | Light work; high concurrency. |

Memory limits enforced via `docker-compose.prod.yml` per-service `deploy.resources.limits.memory` (out-of-scope: document in runbook). Worker concurrency via `-c <n>` CLI arg in `command:`.

### 1.4 Sidecar path convention

```
/data/sidecars/{workspace_id}/{session_id}/raw.parquet
/data/sidecars/{workspace_id}/{session_id}/raw.parquet.sha256   # optional integrity file
```

- Root dir: `$SIDECAR_ROOT` env, default `/data/sidecars` (Docker volume).
- Compression: **snappy** (matches existing `parquet_manager.py:_PARQUET_COMPRESSION`).
- Schema: one row per telemetry sample, columns = raw canonical column names from the adapter (not normalised). Keeps re-analysis faithful.
- `SidecarRef.object_key` = relative path `"{workspace_id}/{session_id}/raw.parquet"` — prefixed with root at load time.

### 1.5 Backfill idempotency strategy

`scripts/backfill_session_sources.py` runs `UPDATE sessions SET source='real_life', capabilities='{"channels":["gps"]}'::jsonb, data_profile='{}'::jsonb WHERE source IS NULL` inside an explicit transaction, then prints the row count. Because migration 059 (née 022) already backfills on upgrade with the same WHERE guard, the script is a defensive rerun: the second run updates **0** rows. Proved by an integration test that asserts rowcount==0 on second invocation.

### 1.6 Rollback plan (also written to `docs/runbooks/W9-migration-rollback.md` in T9.5)

1. Disable the new router path at runtime: `INGEST_ROUTER_ENABLED=0` in `.env.production` → deploy. `sessions_v2.py` falls back to the pre-W2 real-life-only code path.
2. Stop the Celery `sim` worker service (no sim handlers registered → no task leakage).
3. Alembic downgrade: `alembic downgrade 058`. Drops `source`, `data_profile`, `capabilities`. Tested by `test_migration_059.py::test_059_upgrade_then_downgrade_is_clean`.
4. Sidecars stay on disk (harmless; wipe with `rm -rf /data/sidecars/` if desired).
5. Redeploy API with the old `sessions_v2.py` (git revert merge commit); frontend is unaffected because the response envelope is unchanged.

### 1.7 File structure

**New files:**

```
telemetry_tool/
├── ingest/
│   ├── profiler.py              (new: Profiler, DataProfile)
│   ├── router.py                (new: Router facade)
│   └── registry.py              (new: EngineHandler, HandlerRegistry, errors)
├── tasks/
│   └── sim_tasks.py             (new: placeholder task module so the `sim` queue has a target)
├── storage/
│   ├── __init__.py              (new)
│   └── sidecar_store.py         (new: SidecarStore.save/.load/.delete, path conventions)
└── alembic/versions/
    └── 059_ws_w1_sessions_source_profile_caps.py   (moved + renumbered from W1)

scripts/
└── backfill_session_sources.py  (new: idempotent backfill)

docs/runbooks/
└── W9-migration-rollback.md     (new: step-by-step rollback)

telemetry_tool/tests/
├── ingest/
│   ├── __init__.py              (new)
│   ├── test_profiler.py         (new: T2.1/T2.2)
│   ├── test_registry.py         (new: T2.3)
│   ├── test_router.py           (new: T2.3)
│   ├── test_upload_routing.py   (new: T2.4/T2.6)
│   └── fixtures/
│       ├── sample_racechrono.csv
│       ├── sample_iracing.ibt   (stub 4KB header-only; real big-file lives in perf bench)
│       └── sample_ac.csv
├── storage/
│   ├── __init__.py              (new)
│   ├── test_sidecar_store.py    (new: T9.2)
│   └── test_retention.py        (new: T9.3)
└── test_backfill_sources.py     (new: T9.4)
```

**Modified files:**

```
telemetry_tool/celery_app.py                 # add sim queue route + include tasks.sim_tasks
telemetry_tool/web/routes/sessions_v2.py     # delegate to profiler → router
telemetry_tool/tasks/retention_tasks.py      # add sidecar-retention beat task
telemetry_tool/tests/test_contracts/test_migration_022.py  # rename + renumber
```

**Untouched (per launch prompt "must not touch"):**
- `telemetry_tool/web/schemas/contracts/**` (W1)
- `telemetry_tool/shared/**` (W5)
- `telemetry_tool/pipeline/contract_adapter.py`, `telemetry_tool/sim_optimizer/contract_adapter.py`, `telemetry_tool/lap_oracle/ac_contract_adapter.py` (W3, W4)
- `telemetry_tool/coaching_v2/**` (W6), `telemetry_tool/optimizer_v2/**` (W7)
- `lap-website/**` (W8)

---

## Bootstrap (run once, before Task 1)

- [x] **Step B.1: Confirm W1 merged to main.**

```bash
git fetch origin
git log --oneline --grep "signal:W1-done" main | head -3
```

Expected: at least one commit. If empty, STOP — resolve B1 above first.

- [x] **Step B.2: Create worktree + branch.**

```bash
git worktree add .worktrees/ws-w2-w9-ingest-storage -b feat/ws-w2-w9-ingest-storage main
cd .worktrees/ws-w2-w9-ingest-storage
```

- [x] **Step B.3: Apply pre-W1 blocker fixes (B2, B3) as a single prep commit.**

```bash
# from the worktree root
git mv alembic/versions/022_ws_w1_sessions_source_profile_caps.py \
       telemetry_tool/alembic/versions/059_ws_w1_sessions_source_profile_caps.py
rmdir -p alembic/versions alembic 2>/dev/null || true
```

Edit `telemetry_tool/alembic/versions/059_ws_w1_sessions_source_profile_caps.py`:

```python
# at the top of the file, replace the revision block with:
revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None
```

Rename test:

```bash
git mv telemetry_tool/tests/test_contracts/test_migration_022.py \
       telemetry_tool/tests/test_contracts/test_migration_059.py
```

Edit `test_migration_059.py`: replace all `022`→`059` and `021`→`058`.

- [x] **Step B.4: Run alembic upgrade against disposable PG to prove no collision.**

```bash
TELEMETRY_PG_URL_TEST=postgresql://telemetry:telemetry@localhost:5433/telemetry_test \
  pytest telemetry_tool/tests/test_contracts/test_migration_059.py -v
```

Expected: PASS. If the env var isn't set the test skips — that's fine for non-PG dev boxes.

- [x] **Step B.5: Commit bootstrap.**

```bash
git add -A
git commit -m "chore(ingest): rebase W1 migration to 059 + correct alembic path (B2+B3)"
```

---

## 2. Tasks — W2 (Ingest Router)

### Task T2.1: Profiler — detect file type + canonical channels

**Files:**
- Create: `telemetry_tool/ingest/profiler.py`
- Create: `telemetry_tool/ingest/__init__.py` (if not present — it is, append the new exports)
- Test: `telemetry_tool/tests/ingest/test_profiler.py`
- Test: `telemetry_tool/tests/ingest/__init__.py` (empty)
- Fixtures: `telemetry_tool/tests/ingest/fixtures/sample_racechrono.csv`, `sample_iracing.ibt`, `sample_ac.csv`

- [x] **Step 1: Create fixture files.**

```bash
mkdir -p telemetry_tool/tests/ingest/fixtures
```

Write `telemetry_tool/tests/ingest/fixtures/sample_racechrono.csv`:

```csv
Session "test","GMT Date","2026-04-20",
"Lap","Time","Lat","Lon","Speed (m/s)","LatAcc (G)","LonAcc (G)"
1,0.000,43.1234,5.6789,12.3,0.10,0.20
1,0.100,43.1235,5.6789,12.4,0.11,0.19
```

Write `telemetry_tool/tests/ingest/fixtures/sample_ac.csv`:

```csv
# Assetto Corsa Telemetry Export
Time,Speed,Throttle,Brake,Steer,RPM,Gear
0.000,12.3,0.80,0.00,-0.10,6500,3
0.010,12.5,0.82,0.00,-0.09,6550,3
```

Write `telemetry_tool/tests/ingest/fixtures/sample_iracing.ibt` as 256 bytes of `\x03\x00` magic + zero padding (enough for magic-byte detection; full decode is the adapter's job and is out of scope for the profiler test):

```python
# generate_ibt_fixture.py — run once locally, commit the file
from pathlib import Path
p = Path("telemetry_tool/tests/ingest/fixtures/sample_iracing.ibt")
p.write_bytes(b"\x03\x00" + b"\x00" * 254)
```

- [x] **Step 2: Write failing profiler test for RaceChrono CSV.**

`telemetry_tool/tests/ingest/test_profiler.py`:

```python
from pathlib import Path

import pytest

from telemetry_tool.ingest.profiler import Profiler, DataProfile
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


FIX = Path(__file__).parent / "fixtures"


def test_racechrono_csv_profiles_to_real_life():
    profile = Profiler().profile(FIX / "sample_racechrono.csv")
    assert isinstance(profile, DataProfile)
    assert profile.source is SourceLiteral.REAL_LIFE
    assert profile.parser == "racechrono"
    assert profile.confidence >= 0.9
    assert {ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G}.issubset(profile.channels_available)
    assert profile.suggested_engine == "real_life_pipeline"
```

- [x] **Step 3: Run test; expect `ImportError: cannot import name 'Profiler'`.**

```bash
pytest telemetry_tool/tests/ingest/test_profiler.py -v
```

- [x] **Step 4: Implement `DataProfile` + `Profiler`.**

`telemetry_tool/ingest/profiler.py`:

```python
"""Data-profile detector (W2.T2.1/T2.2).

Composes on top of :mod:`telemetry_tool.adapters.registry` — the profiler
decides *which engine* should process the file, not *how to parse* it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from telemetry_tool.adapters.registry import detect_format_two_pass
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


# Adapter FORMAT_NAME → SourceLiteral + suggested engine.
_PARSER_ROUTING: Final[dict[str, tuple[SourceLiteral, str]]] = {
    "racechrono": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "racechrono_rcz": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "racebox": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "vbox": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "qstarz_csv": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "generic_csv": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
    "iracing_ibt": (SourceLiteral.IRACING, "sim_optimizer"),
    "iracing_ascii": (SourceLiteral.IRACING, "sim_optimizer"),
    "ac": (SourceLiteral.AC, "ac_pipeline"),
    "acc": (SourceLiteral.AC, "ac_pipeline"),   # provisional — ACC decision in spec §10
    "lmu": (SourceLiteral.AC, "ac_pipeline"),   # provisional
    "f1": (SourceLiteral.AC, "ac_pipeline"),    # provisional
    "motec": (SourceLiteral.AC, "ac_pipeline"),
    "motec_binary": (SourceLiteral.AC, "ac_pipeline"),
    "aim": (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
}

# Column-name → ChannelTag mapping. Case-insensitive substring match.
# Order matters for substrings like "lat_g" which must beat "lat".
_COL_TAGS: Final[list[tuple[str, ChannelTag]]] = [
    ("lat_g", ChannelTag.LAT_G),
    ("latacc", ChannelTag.LAT_G),
    ("accel_lat", ChannelTag.LAT_G),
    ("lon_g", ChannelTag.LON_G),
    ("longacc", ChannelTag.LON_G),
    ("lonacc", ChannelTag.LON_G),
    ("accel_long", ChannelTag.LON_G),
    ("yaw", ChannelTag.YAW_RATE),
    ("throttle", ChannelTag.THROTTLE),
    ("brake", ChannelTag.BRAKE),
    ("steer", ChannelTag.STEER),
    ("wheel_spd", ChannelTag.WHEEL_SPD),
    ("wheelspeed", ChannelTag.WHEEL_SPD),
    ("shock", ChannelTag.SHOCK_DEFL),
    # gps last so columns like "speed" don't steal it
    ("lat", ChannelTag.GPS),
    ("lon", ChannelTag.GPS),
]

_HEADER_SAMPLE_ROWS = 5


class DataProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: SourceLiteral
    parser: str
    channels_available: frozenset[ChannelTag]
    suggested_engine: str
    confidence: float = Field(ge=0.0, le=1.0)
    sample_hz: float | None = None
    total_channels_detected: int | None = None


class UnknownFormatError(ValueError):
    """Raised when no adapter matches and no fallback is configured."""


class Profiler:
    """Classify an uploaded file and declare its channel set."""

    def profile(self, file_path: str | Path) -> DataProfile:
        file_path = Path(file_path)
        adapter_cls, confidence = detect_format_two_pass(str(file_path))
        if adapter_cls is None:
            raise UnknownFormatError(
                f"No adapter matched {file_path.name}. "
                "Check the supported-formats list in telemetry_tool.adapters.registry."
            )
        parser = adapter_cls.FORMAT_NAME
        source, engine = _PARSER_ROUTING.get(
            parser, (SourceLiteral.REAL_LIFE, "real_life_pipeline"),
        )
        channels, total = self._channels_from_header(file_path, adapter_cls)
        return DataProfile(
            source=source,
            parser=parser,
            channels_available=channels,
            suggested_engine=engine,
            confidence=confidence,
            total_channels_detected=total,
        )

    def _channels_from_header(
        self, file_path: Path, adapter_cls,
    ) -> tuple[frozenset[ChannelTag], int | None]:
        """Read the first few rows to enumerate columns, then tag them.

        Falls back to `{GPS}` for files we can't cheaply sample.
        """
        suffix = file_path.suffix.lower()
        if suffix in {".csv", ".txt"}:
            try:
                header = pd.read_csv(
                    file_path, nrows=_HEADER_SAMPLE_ROWS, engine="python",
                    on_bad_lines="skip", skip_blank_lines=True,
                )
            except Exception:
                return frozenset({ChannelTag.GPS}), None
            columns = [c.lower() for c in header.columns]
            tags: set[ChannelTag] = set()
            for name in columns:
                for needle, tag in _COL_TAGS:
                    if needle in name:
                        tags.add(tag)
            if not tags:
                tags.add(ChannelTag.GPS)
            return frozenset(tags), len(columns)
        if suffix == ".ibt":
            # iRacing IBT — full channel list requires the `ibt` lib.
            # Trust the spec-declared set; the adapter will validate on parse.
            return frozenset({
                ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
                ChannelTag.YAW_RATE, ChannelTag.THROTTLE, ChannelTag.BRAKE,
                ChannelTag.STEER, ChannelTag.WHEEL_SPD,
            }), None
        return frozenset({ChannelTag.GPS}), None
```

Append exports to `telemetry_tool/ingest/__init__.py`:

```python
from telemetry_tool.ingest.profiler import DataProfile, Profiler, UnknownFormatError  # noqa: F401
```

- [x] **Step 5: Run the profiler test; expect PASS.**

```bash
pytest telemetry_tool/tests/ingest/test_profiler.py::test_racechrono_csv_profiles_to_real_life -v
```

- [x] **Step 6: Add iRacing IBT + AC CSV tests in the same file.**

```python
def test_iracing_ibt_profiles_to_sim_optimizer():
    profile = Profiler().profile(FIX / "sample_iracing.ibt")
    assert profile.source is SourceLiteral.IRACING
    assert profile.parser == "iracing_ibt"
    assert profile.suggested_engine == "sim_optimizer"
    assert profile.confidence >= 0.9
    assert {ChannelTag.THROTTLE, ChannelTag.BRAKE, ChannelTag.STEER}.issubset(
        profile.channels_available,
    )


def test_ac_csv_profiles_to_ac_pipeline():
    profile = Profiler().profile(FIX / "sample_ac.csv")
    assert profile.source is SourceLiteral.AC
    assert profile.suggested_engine == "ac_pipeline"
    assert profile.confidence >= 0.9
    assert {ChannelTag.THROTTLE, ChannelTag.BRAKE}.issubset(profile.channels_available)


def test_unknown_extension_raises():
    tmp = FIX / "garbage.bin"
    tmp.write_bytes(b"\xff\xff\xff\xff")
    with pytest.raises(ValueError):
        Profiler().profile(tmp)
    tmp.unlink()
```

- [x] **Step 7: Run all T2.1 tests.**

```bash
pytest telemetry_tool/tests/ingest/test_profiler.py -v
```

Expected: 4 PASS. If AC fails because no AC adapter is registered by default, register it in a conftest (see Step 8).

- [x] **Step 8: Ensure adapters are registered for tests.**

Add `telemetry_tool/tests/ingest/conftest.py`:

```python
"""Register all adapters so profiler tests see the full registry."""
from __future__ import annotations

from telemetry_tool.adapters.registry import register_adapter
from telemetry_tool.adapters.racechrono_adapter import RaceChronoAdapter
from telemetry_tool.adapters.iracing_binary_adapter import IRacingBinaryAdapter
from telemetry_tool.adapters.acc_adapter import ACCAdapter


def _register_once() -> None:
    for cls in (RaceChronoAdapter, IRacingBinaryAdapter, ACCAdapter):
        register_adapter(cls)


_register_once()
```

Re-run Step 7. Expected: 4 PASS.

- [x] **Step 9: Commit.**

```bash
git add telemetry_tool/ingest/profiler.py telemetry_tool/ingest/__init__.py \
        telemetry_tool/tests/ingest/__init__.py \
        telemetry_tool/tests/ingest/test_profiler.py \
        telemetry_tool/tests/ingest/conftest.py \
        telemetry_tool/tests/ingest/fixtures/
git commit -m "feat(ingest): DataProfile + format profiler (W2.T2.1/T2.2)"
```

---

### Task T2.3: HandlerRegistry + Router

**Files:**
- Create: `telemetry_tool/ingest/registry.py`
- Create: `telemetry_tool/ingest/router.py`
- Test: `telemetry_tool/tests/ingest/test_registry.py`
- Test: `telemetry_tool/tests/ingest/test_router.py`

- [x] **Step 1: Write the failing registry test.**

`telemetry_tool/tests/ingest/test_registry.py`:

```python
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.ingest.registry import (
    HandlerRegistry, EngineHandler, NoHandlerResolvableError,
    DuplicateHandlerError,
)
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


class _FakeHandler:
    SOURCE = SourceLiteral.REAL_LIFE
    PRIORITY = 0
    last_job: str | None = None

    def can_handle(self, profile: DataProfile) -> bool:
        return profile.source is self.SOURCE

    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str:
        self.last_job = str(session_id)
        return self.last_job


def _rc_profile() -> DataProfile:
    return DataProfile(
        source=SourceLiteral.REAL_LIFE, parser="racechrono",
        channels_available=frozenset({ChannelTag.GPS}),
        suggested_engine="real_life_pipeline", confidence=0.95,
    )


def test_register_then_resolve_roundtrip():
    reg = HandlerRegistry()
    h = _FakeHandler()
    reg.register(h)
    assert reg.resolve(_rc_profile()) is h


def test_duplicate_register_rejects():
    reg = HandlerRegistry()
    reg.register(_FakeHandler())
    with pytest.raises(DuplicateHandlerError):
        reg.register(_FakeHandler())


def test_resolve_raises_when_empty():
    with pytest.raises(NoHandlerResolvableError):
        HandlerRegistry().resolve(_rc_profile())
```

- [x] **Step 2: Run the test; expect import errors.**

```bash
pytest telemetry_tool/tests/ingest/test_registry.py -v
```

- [x] **Step 3: Implement the registry without tie-break logic yet.**

`telemetry_tool/ingest/registry.py`:

```python
"""Engine handler registry (W2.T2.3).

Sessions #4 and #5 replace the stubs via `register_handler()` when their
adapter packages import. Keep this interface stable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.web.schemas.contracts import SourceLiteral


class DuplicateHandlerError(ValueError):
    """Two handlers registered for the same SOURCE."""


class NoHandlerResolvableError(LookupError):
    """No registered handler can handle the profile."""


@runtime_checkable
class EngineHandler(Protocol):
    SOURCE: SourceLiteral
    PRIORITY: int

    def can_handle(self, profile: DataProfile) -> bool: ...
    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str: ...


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: list[EngineHandler] = []

    def register(self, handler: EngineHandler) -> None:
        for existing in self._handlers:
            if existing.SOURCE == handler.SOURCE:
                raise DuplicateHandlerError(
                    f"Handler for {handler.SOURCE} already registered "
                    f"({type(existing).__name__})"
                )
        self._handlers.append(handler)

    def resolve(self, profile: DataProfile) -> EngineHandler:
        candidates = [h for h in self._handlers if h.can_handle(profile)]
        if not candidates:
            raise NoHandlerResolvableError(
                f"No registered handler accepts profile {profile.source.value} "
                f"(parser={profile.parser}, registered={[h.SOURCE.value for h in self._handlers]})"
            )
        # TODO (Step 4): tie-break when len(candidates) > 1
        return candidates[0]

    def unregister(self, source: SourceLiteral) -> None:
        self._handlers = [h for h in self._handlers if h.SOURCE is not source]


# Global singleton — sessions #4/#5 register into this at import time.
_registry: HandlerRegistry = HandlerRegistry()


def get_registry() -> HandlerRegistry:
    return _registry
```

- [x] **Step 4: *(Learning-mode contribution)* Implement the tie-break rule.**

> **Context**: Sessions #4 and #5 will register multiple handlers in the global registry. For an edge case — e.g. an `.ibt` file that could theoretically route to either a generic "simracing" handler OR the iRacing-specific one — `can_handle()` may return `True` for more than one. You get to pick the rule.
>
> **Location**: `telemetry_tool/ingest/registry.py`, method `HandlerRegistry.resolve()`. Replace the `return candidates[0]` line.
>
> **Tradeoffs**:
>  - *Source-match first* (default I'd pick): handlers whose `SOURCE == profile.source` win over generic matches. Safe, predictable, but prevents a "fallback sim handler" pattern.
>  - *Highest `PRIORITY`*: dependency-injected scoring. More flexible but every handler author has to reason about global priority.
>  - *Registration order*: trivial but fragile to import-order changes.
>  - *Composite*: `(source_matches, PRIORITY)` descending — combines both.
>
> **Ask yourself**: if #5 registers an `iRacingHandler(SOURCE=IRACING, PRIORITY=10)` and a generic `SimFallbackHandler(SOURCE=IRACING, PRIORITY=0)`, which should win for a known IBT file? What about a proprietary ACC file whose profile we classify as `AC` but where the fallback handler accepts everything?
>
> Write the 5-10 lines, add a docstring explaining the chosen rule, and add one test per outcome in `test_registry.py`.

After your edit, run the full registry test suite:

```bash
pytest telemetry_tool/tests/ingest/test_registry.py -v
```

Expected: 3+N PASS (N = additional tests for tie-break).

- [x] **Step 5: Write the Router facade + test.**

`telemetry_tool/tests/ingest/test_router.py`:

```python
from pathlib import Path
from uuid import uuid4

from telemetry_tool.ingest.profiler import DataProfile, Profiler
from telemetry_tool.ingest.registry import HandlerRegistry
from telemetry_tool.ingest.router import route_upload
from telemetry_tool.web.schemas.contracts import ChannelTag, SourceLiteral


class _SpyHandler:
    SOURCE = SourceLiteral.REAL_LIFE
    PRIORITY = 0
    enqueued: list[str] = []

    def can_handle(self, profile): return profile.source is self.SOURCE

    def enqueue(self, *, session_id, workspace_id, file_path, profile, session_meta):
        self.enqueued.append(str(session_id))
        return str(session_id)


def test_route_upload_dispatches_to_handler(tmp_path):
    csv = tmp_path / "rc.csv"
    csv.write_text(
        'Session "x"\n'
        '"Lap","Time","Lat","Lon","Speed (m/s)","LatAcc (G)"\n'
        '1,0.0,43.1,5.6,12.0,0.0\n'
    )
    reg = HandlerRegistry()
    spy = _SpyHandler()
    reg.register(spy)

    sid = uuid4()
    job_id = route_upload(
        file_path=csv, session_id=sid, workspace_id="ws-1",
        session_meta={"driver_name": "Theo"},
        profiler=Profiler(), registry=reg,
    )
    assert job_id == str(sid)
    assert spy.enqueued == [str(sid)]
```

- [x] **Step 6: Implement `router.py`.**

`telemetry_tool/ingest/router.py`:

```python
"""Router facade (W2.T2.3).

`route_upload()` profiles the file, picks a handler, and delegates.
The upload endpoint (T2.4) calls this and returns the job_id as-is.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from telemetry_tool.ingest.profiler import DataProfile, Profiler
from telemetry_tool.ingest.registry import HandlerRegistry, get_registry


def route_upload(
    *,
    file_path: Path,
    session_id: UUID,
    workspace_id: str,
    session_meta: dict,
    profiler: Profiler | None = None,
    registry: HandlerRegistry | None = None,
) -> str:
    profiler = profiler or Profiler()
    registry = registry or get_registry()
    profile: DataProfile = profiler.profile(file_path)
    handler = registry.resolve(profile)
    return handler.enqueue(
        session_id=session_id,
        workspace_id=workspace_id,
        file_path=file_path,
        profile=profile,
        session_meta=session_meta,
    )
```

- [x] **Step 7: Run router test.**

```bash
pytest telemetry_tool/tests/ingest/test_router.py -v
```

Expected: 1 PASS.

- [x] **Step 8: Commit.**

```bash
git add telemetry_tool/ingest/registry.py telemetry_tool/ingest/router.py \
        telemetry_tool/tests/ingest/test_registry.py \
        telemetry_tool/tests/ingest/test_router.py
git commit -m "feat(ingest): HandlerRegistry + route_upload facade (W2.T2.3)"
```

---

### Task T2.4: Wire upload endpoint to profiler → router

**Files:**
- Modify: `telemetry_tool/web/routes/sessions_v2.py:349-664`
- Create: `telemetry_tool/ingest/handlers_real_life.py` (the real-life handler that wraps existing `build_pipeline_chain`)
- Test: `telemetry_tool/tests/ingest/test_upload_routing.py`

- [x] **Step 1: Write the real-life handler.**

`telemetry_tool/ingest/handlers_real_life.py`:

```python
"""Real-life engine handler — wraps the existing 14-stage Celery pipeline.

Registered on import; sessions #4 and #5 replace the iRacing / AC stubs
by importing their own adapter modules which in turn call `register()`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import UUID

import redis

# Imported at module scope so tests can patch them via
# `@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")`.
from pipeline_context import PipelineContext
from tasks.pipeline_tasks import build_pipeline_chain
from web.config import Config

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.ingest.registry import get_registry
from telemetry_tool.web.schemas.contracts import SourceLiteral

logger = logging.getLogger(__name__)


def _redis_from_url(url: str) -> redis.Redis:
    """Thin wrapper so tests can monkeypatch the redis client factory."""
    return redis.Redis.from_url(url)


class RealLifeHandler:
    SOURCE = SourceLiteral.REAL_LIFE
    PRIORITY = 10  # canonical match for real_life profiles

    def can_handle(self, profile: DataProfile) -> bool:
        return profile.source is SourceLiteral.REAL_LIFE

    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str:
        job_id = str(session_id)  # sessions_v2 treats job_id as opaque
        r = _redis_from_url(Config.REDIS_URL)
        PipelineContext.create(
            redis_client=r,
            job_id=job_id,
            workspace_id=workspace_id,
            session_id=job_id,
            file_path=str(file_path),
        )
        meta = dict(session_meta)
        meta["data_profile"] = profile.model_dump()
        meta["capabilities"] = sorted(t.value for t in profile.channels_available)
        meta["source"] = profile.source.value
        r.set(f"pipeline:meta:{job_id}", json.dumps(meta), ex=7200)

        # Soft timeout is tier-specific; the caller propagates it.
        build_pipeline_chain(job_id).apply_async(
            soft_time_limit=meta.get("_soft_timeout_s", 600),
        )
        logger.info("Real-life pipeline dispatched: job_id=%s ws=%s", job_id, workspace_id)
        return job_id


# Register on import.
get_registry().register(RealLifeHandler())
```

- [x] **Step 2: Import the handler from `ingest/__init__.py`.**

Append to `telemetry_tool/ingest/__init__.py`:

```python
# Auto-register handlers. Order: real-life first, sim stubs registered by
# sessions #4/#5 via their own adapter modules.
from telemetry_tool.ingest import handlers_real_life  # noqa: F401
```

- [x] **Step 3: Write sim stub handlers.**

`telemetry_tool/ingest/handlers_sim_stubs.py`:

```python
"""Stub handlers for iRacing and AC — sessions #5 replaces these."""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from telemetry_tool.ingest.profiler import DataProfile
from telemetry_tool.ingest.registry import get_registry
from telemetry_tool.web.schemas.contracts import SourceLiteral


class _Stub:
    PRIORITY = 0

    def can_handle(self, profile: DataProfile) -> bool:
        return profile.source is self.SOURCE

    def enqueue(self, *, session_id: UUID, workspace_id: str, file_path: Path,
                profile: DataProfile, session_meta: dict) -> str:
        raise NotImplementedError(
            f"{type(self).__name__} is a stub; session #5 must replace it "
            f"via `get_registry().unregister({self.SOURCE}); register(RealHandler())`."
        )


class IRacingStubHandler(_Stub):
    SOURCE = SourceLiteral.IRACING


class ACStubHandler(_Stub):
    SOURCE = SourceLiteral.AC


get_registry().register(IRacingStubHandler())
get_registry().register(ACStubHandler())
```

Append to `telemetry_tool/ingest/__init__.py`:

```python
from telemetry_tool.ingest import handlers_sim_stubs  # noqa: F401
```

- [x] **Step 4: Write the upload-routing test (mocks Celery).**

`telemetry_tool/tests/ingest/test_upload_routing.py`:

```python
import io
from unittest.mock import patch

import pytest


@pytest.fixture
def flask_client():
    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _upload(client, data: bytes, filename: str):
    return client.post(
        "/api/v1/sessions/upload",
        data={"file": (io.BytesIO(data), filename), "driver_name": "Theo"},
        content_type="multipart/form-data",
        headers={"X-Workspace-Id": "00000000-0000-0000-0000-000000000001"},
    )


@patch("telemetry_tool.ingest.handlers_real_life._redis_from_url")
@patch("telemetry_tool.ingest.handlers_real_life.PipelineContext")
@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")
def test_rc_csv_routes_to_real_life_handler(mock_chain, mock_ctx, mock_redis, flask_client):
    payload = (
        b'Session "x"\n'
        b'"Lap","Time","Lat","Lon","Speed (m/s)","LatAcc (G)"\n'
        b'1,0.0,43.1,5.6,12.0,0.0\n'
    )
    resp = _upload(flask_client, payload, "sample.csv")
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["status"] == "pending"
    assert mock_chain.called  # real-life handler ran


@patch("telemetry_tool.ingest.handlers_real_life._redis_from_url")
@patch("telemetry_tool.ingest.handlers_real_life.PipelineContext")
@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")
def test_ibt_routes_to_iracing_stub_and_502s(mock_chain, mock_ctx, mock_redis, flask_client):
    # Magic bytes only; adapter detect succeeds; stub raises NotImplementedError
    resp = _upload(flask_client, b"\x03\x00" + b"\x00" * 254, "sample.ibt")
    assert resp.status_code in (501, 502, 503)  # NotImplementedError → 5xx
    assert not mock_chain.called
```

- [x] **Step 5: Modify `sessions_v2.py` to delegate through the router.**

Replace the block `sessions_v2.py:579-635` (from "# ── 5. Create job record ──" down to the `return api_response(...)` call) with:

```python
        # ── 5. Route through profiler + handler registry (W2.T2.4) ──
        import uuid as _uuid

        from telemetry_tool.ingest.registry import NoHandlerResolvableError
        from telemetry_tool.ingest.router import route_upload
        from telemetry_tool.ingest.profiler import UnknownFormatError

        session_uuid = _uuid.uuid4()
        # Persist initial job row so the frontend can poll from 0%.
        conn.execute(
            """INSERT INTO ingestion_jobs
               (job_id, workspace_id, file_path, file_size, sha256_partial,
                status, stage_name, stage_index, stage_total, updated_at)
               VALUES (%(job_id)s, %(ws)s, %(fpath)s, %(fsize)s, '',
                       'pending', 'Queued', 0, 14, NOW())""",
            {
                "job_id": session_uuid.hex,
                "ws": str(g.workspace_id),
                "fpath": str(tmp_path),
                "fsize": tmp_path.stat().st_size,
            },
        )
        conn.commit()

        try:
            session_meta["_soft_timeout_s"] = _TIER_TIMEOUTS.get(plan_tier, 120)
            job_id = route_upload(
                file_path=tmp_path,
                session_id=session_uuid,
                workspace_id=str(g.workspace_id),
                session_meta=session_meta,
            )
        except UnknownFormatError as exc:
            logger.info("Upload format unrecognised: %s", exc)
            return api_error(
                ErrorCode.UNSUPPORTED_FORMAT, str(exc), status=400,
            )
        except NoHandlerResolvableError as exc:
            logger.error("No handler for profile: %s", exc)
            return api_error(
                ErrorCode.ANALYSIS_FAILED,
                "No engine available for this file type yet.",
                status=503,
            )
        except NotImplementedError as exc:
            logger.warning("Stub handler fired — sessions #5 not merged: %s", exc)
            return api_error(
                ErrorCode.ANALYSIS_FAILED,
                "This source is not yet supported in this environment.",
                status=501,
            )

        logger.info(
            "Upload accepted: job_id=%s ws=%s file=%s tier=%s",
            job_id, g.workspace_id, safe_name, plan_tier,
        )
        return api_response(
            {"job_id": job_id, "status": "pending",
             "message": "Upload accepted. Processing started."},
            status=202,
        )
```

(The pre-existing blocks 1–4b — tier limits, temp save, preflight, session_meta build — stay unchanged.)

- [x] **Step 6: Run upload-routing tests.**

```bash
pytest telemetry_tool/tests/ingest/test_upload_routing.py -v
```

Expected: 2 PASS. If the auth middleware blocks the test, add `AUTH_REQUIRED=0` to the test-env fixture (matches existing `test_data_api_v2.py` convention).

- [x] **Step 7: Run the old upload-sync test suite to catch regressions.**

```bash
pytest telemetry_tool/tests/test_upload_sync.py -v
```

Expected: all previously-passing tests still pass.

- [x] **Step 8: Commit.**

```bash
git add telemetry_tool/ingest/handlers_real_life.py \
        telemetry_tool/ingest/handlers_sim_stubs.py \
        telemetry_tool/ingest/__init__.py \
        telemetry_tool/web/routes/sessions_v2.py \
        telemetry_tool/tests/ingest/test_upload_routing.py
git commit -m "feat(ingest): wire /sessions/upload through profiler + handler registry (W2.T2.4)"
```

---

### Task T2.5: Celery `sim` queue

**Files:**
- Modify: `telemetry_tool/celery_app.py:45-75`
- Create: `telemetry_tool/tasks/sim_tasks.py` (placeholder task; session #5 adds real tasks)
- Create: `docs/runbooks/celery-queues.md`

- [x] **Step 1: Write the placeholder task module.**

`telemetry_tool/tasks/sim_tasks.py`:

```python
"""Celery tasks that run on the `sim` queue.

Session #5 (iRacing + AC adapters) adds real tasks here. This placeholder
ensures the queue has at least one registered task so `celery inspect`
doesn't complain on an empty worker.
"""
from __future__ import annotations

from celery_app import celery


@celery.task(name="tasks.sim_tasks.noop", queue="sim")
def noop(session_id: str) -> str:
    """Health-probe no-op. Session #5 wires the real IBT/AC entrypoint."""
    return session_id
```

- [x] **Step 2: Modify `celery_app.py` to include + route the new module.**

Edit `telemetry_tool/celery_app.py`:

```python
# add to `include=[...]` (line 45-60 block):
    "tasks.sim_tasks",

# add to `task_routes` (line 69-74 block):
    "tasks.sim_tasks.*": {"queue": "sim"},
```

- [x] **Step 3: Verify route wiring.**

```bash
python -c "from celery_app import celery; \
           print([(n, celery.conf.task_routes.get(n, celery.conf.task_routes)) \
                  for n in ('tasks.pipeline_tasks.run', 'tasks.sim_tasks.noop', 'tasks.batch_tasks.run')])"
```

Expected output: `pipeline_tasks → queue='pipeline'`, `sim_tasks → queue='sim'`, `batch_tasks → queue='default'`.

- [x] **Step 4: Write the queue runbook.**

`docs/runbooks/celery-queues.md` (one page):

```markdown
# Celery queues — operational reference

| Queue | Worker service | Concurrency | Mem ceiling | Typical task | SLA |
|-------|---------------|-------------|-------------|--------------|-----|
| `pipeline` | `celery_pipeline` | 2 | 2 GB | 14-stage real-life pipeline | 5 min p95 |
| `sim` | `celery_sim` *(add to docker-compose.prod.yml)* | 2 | 4 GB | iRacing IBT / AC | 10 min p95 |
| `default` | `celery_default` | 4 | 512 MB | billing, email, gdpr | 30 s p95 |

## Adding the `sim` worker service (docker-compose.prod.yml)

```yaml
celery_sim:
  build: .
  command: celery -A telemetry_tool.celery_app worker -Q sim -c 2 -l info
  environment:
    - CELERY_BROKER_URL=${REDIS_URL}
  depends_on: [redis, postgres]
  deploy:
    resources:
      limits:
        memory: 4G
```

## Symptom → fix

- `Queue sim is empty but tasks are being enqueued` → worker not running; `docker compose ps` then `docker compose up -d celery_sim`.
- `pipeline workers OOM under concurrent IBT + CSV load` → verify sim tasks actually route to `sim` (`celery inspect active_queues`), not `pipeline`.
- `sim worker import error` → `tasks.sim_tasks` not in `include=[...]` in `celery_app.py`.
```

- [x] **Step 5: Commit.**

```bash
git add telemetry_tool/celery_app.py telemetry_tool/tasks/sim_tasks.py \
        docs/runbooks/celery-queues.md
git commit -m "feat(tasks): split sim + pipeline Celery queues (W2.T2.5)"
```

---

### Task T2.6: Integration test — 3 sample formats route correctly

**Files:**
- Modify: `telemetry_tool/tests/ingest/test_upload_routing.py` (extend with AC)

- [x] **Step 1: Add the third integration test.**

Append to `test_upload_routing.py`:

```python
@patch("telemetry_tool.ingest.handlers_real_life._redis_from_url")
@patch("telemetry_tool.ingest.handlers_real_life.PipelineContext")
@patch("telemetry_tool.ingest.handlers_real_life.build_pipeline_chain")
def test_ac_csv_routes_to_ac_stub_and_501s(mock_chain, mock_ctx, mock_redis, flask_client):
    payload = (
        b"# AC Telemetry\n"
        b"Time,Speed,Throttle,Brake,Steer,RPM,Gear\n"
        b"0.0,12.3,0.8,0.0,-0.1,6500,3\n"
    )
    resp = _upload(flask_client, payload, "sample.ac.csv")
    # AC stub raises NotImplementedError → 501
    assert resp.status_code == 501
    assert not mock_chain.called


def test_three_sample_uploads_distinct_routes(flask_client):
    """Acceptance-criteria test: each sample routes to its correct handler."""
    from telemetry_tool.ingest.registry import get_registry
    from telemetry_tool.web.schemas.contracts import SourceLiteral

    # Real-life routes to real-life handler
    rc_payload = (
        b'Session "x"\n"Lap","Time","Lat","Lon","Speed (m/s)","LatAcc (G)"\n'
        b'1,0.0,43.1,5.6,12.0,0.0\n'
    )
    ibt_payload = b"\x03\x00" + b"\x00" * 254
    ac_payload = (
        b"# AC Telemetry\nTime,Speed,Throttle,Brake,Steer,RPM,Gear\n"
        b"0.0,12.3,0.8,0.0,-0.1,6500,3\n"
    )
    r1 = _upload(flask_client, rc_payload, "x.csv")
    r2 = _upload(flask_client, ibt_payload, "x.ibt")
    r3 = _upload(flask_client, ac_payload, "x.ac.csv")
    # real-life OK, sim stubs return 501
    assert r1.status_code == 202
    assert r2.status_code == 501
    assert r3.status_code == 501
```

- [x] **Step 2: Run the full ingest test suite.**

```bash
pytest telemetry_tool/tests/ingest/ -v
```

Expected: all PASS.

- [x] **Step 3: Commit.**

```bash
git add telemetry_tool/tests/ingest/test_upload_routing.py
git commit -m "test(ingest): 3-format integration routing assertion (W2.T2.6)"
```

---

## 3. Tasks — W9 (Multi-source Storage)

### Task T9.1: Verify + integrate W1's sessions migration

This task already *started* in the Bootstrap block (Steps B.3 + B.4). Confirm integration here.

**Files:**
- Already touched: `telemetry_tool/alembic/versions/059_ws_w1_sessions_source_profile_caps.py`
- Already touched: `telemetry_tool/tests/test_contracts/test_migration_059.py`

- [x] **Step 1: Run the end-to-end alembic head sanity check.**

```bash
# Against disposable PG (docker-compose.yml test DB is fine):
TELEMETRY_PG_URL=postgresql://telemetry:telemetry@localhost:5433/telemetry_test \
  alembic upgrade head
TELEMETRY_PG_URL=postgresql://telemetry:telemetry@localhost:5433/telemetry_test \
  alembic current
```

Expected: `current` prints `059 (head)` (or the next rebased number if other migrations landed meanwhile).

- [x] **Step 2: Confirm no orphaned top-level alembic dir.**

```bash
test ! -d alembic || { echo "ERROR: stray top-level alembic/"; exit 1; }
```

- [x] **Step 3: Commit a no-op marker if you made further tweaks; otherwise skip.**

(This task is mostly verification. If Bootstrap was clean, no commit is needed here.)

---

### Task T9.2: `SidecarStore` — parquet save/load

**Files:**
- Create: `telemetry_tool/storage/__init__.py`
- Create: `telemetry_tool/storage/sidecar_store.py`
- Test: `telemetry_tool/tests/storage/__init__.py`
- Test: `telemetry_tool/tests/storage/test_sidecar_store.py`

- [x] **Step 1: Write the failing test.**

`telemetry_tool/tests/storage/test_sidecar_store.py`:

```python
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from telemetry_tool.storage.sidecar_store import SidecarStore
from telemetry_tool.web.schemas.contracts import SidecarRef, SourceLiteral


@pytest.fixture
def store(tmp_path) -> SidecarStore:
    return SidecarStore(root=tmp_path)


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "time_s": [0.0, 0.1, 0.2],
        "speed_mps": [12.0, 12.5, 13.0],
        "lat": [43.1, 43.1, 43.2],
        "lon": [5.6, 5.6, 5.6],
    })


def test_save_then_load_roundtrips(store):
    sid, ws = uuid4().hex, "ws-1"
    ref = store.save(session_id=sid, workspace_id=ws,
                     source=SourceLiteral.REAL_LIFE, df=_sample_df())
    assert isinstance(ref, SidecarRef)
    assert ref.format == "parquet"
    assert ref.object_key.endswith(f"{ws}/{sid}/raw.parquet")
    assert ref.sha256 and len(ref.sha256) == 64
    assert ref.size_bytes and ref.size_bytes > 0

    df2 = store.load(ref)
    pd.testing.assert_frame_equal(df2, _sample_df())


def test_load_missing_raises(store):
    from telemetry_tool.storage.sidecar_store import SidecarMissing
    bogus = SidecarRef(object_key="nope/nope/raw.parquet")
    with pytest.raises(SidecarMissing):
        store.load(bogus)


def test_save_is_idempotent_on_identical_df(store):
    sid, ws = uuid4().hex, "ws-1"
    ref1 = store.save(session_id=sid, workspace_id=ws,
                      source=SourceLiteral.REAL_LIFE, df=_sample_df())
    ref2 = store.save(session_id=sid, workspace_id=ws,
                      source=SourceLiteral.REAL_LIFE, df=_sample_df())
    # Same content → same sha256, same path, same size
    assert ref1.sha256 == ref2.sha256
    assert ref1.object_key == ref2.object_key
    assert ref1.size_bytes == ref2.size_bytes
```

- [x] **Step 2: Run; expect import errors.**

```bash
pytest telemetry_tool/tests/storage/test_sidecar_store.py -v
```

- [x] **Step 3: Implement `SidecarStore`.**

`telemetry_tool/storage/__init__.py`:

```python
from telemetry_tool.storage.sidecar_store import SidecarStore, SidecarMissing  # noqa: F401
```

`telemetry_tool/storage/sidecar_store.py`:

```python
"""Raw-channel Parquet sidecar storage (W9.T9.2).

Path layout: `{root}/{workspace_id}/{session_id}/raw.parquet`
Compression: snappy (matches `parquet_manager._PARQUET_COMPRESSION`).
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Final

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from telemetry_tool.web.schemas.contracts import SidecarRef, SourceLiteral

logger = logging.getLogger(__name__)

_COMPRESSION: Final[str] = "snappy"
_FILENAME: Final[str] = "raw.parquet"


class SidecarMissing(FileNotFoundError):
    """Sidecar referenced but not found on disk."""


class SidecarStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or os.environ.get("SIDECAR_ROOT", "/data/sidecars"))

    def _path(self, workspace_id: str, session_id: str) -> Path:
        return self.root / workspace_id / session_id / _FILENAME

    def save(
        self,
        *,
        session_id: str,
        workspace_id: str,
        source: SourceLiteral,
        df: pd.DataFrame,
    ) -> SidecarRef:
        target = self._path(workspace_id, session_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, target, compression=_COMPRESSION)
        size_bytes = target.stat().st_size
        sha256 = _sha256_of_file(target)
        logger.info(
            "Sidecar saved: ws=%s session=%s bytes=%d sha=%s... source=%s",
            workspace_id, session_id, size_bytes, sha256[:8], source.value,
        )
        return SidecarRef(
            object_key=str(target.relative_to(self.root)).replace(os.sep, "/"),
            format="parquet",
            sha256=sha256,
            size_bytes=size_bytes,
        )

    def load(self, ref: SidecarRef) -> pd.DataFrame:
        path = self.root / ref.object_key
        if not path.exists():
            raise SidecarMissing(f"Sidecar not found at {path}")
        return pq.read_table(path).to_pandas()

    def delete(self, ref: SidecarRef) -> bool:
        path = self.root / ref.object_key
        if not path.exists():
            return False
        path.unlink()
        # Prune empty parents (session dir, then workspace dir).
        try:
            path.parent.rmdir()
            path.parent.parent.rmdir()
        except OSError:
            pass
        return True


def _sha256_of_file(path: Path, chunk_size: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            blk = f.read(chunk_size)
            if not blk:
                break
            h.update(blk)
    return h.hexdigest()
```

- [x] **Step 4: Run; expect PASS.**

```bash
pytest telemetry_tool/tests/storage/test_sidecar_store.py -v
```

- [x] **Step 5: Commit.**

```bash
git add telemetry_tool/storage/ telemetry_tool/tests/storage/
git commit -m "feat(storage): SidecarStore parquet save/load (W9.T9.2)"
```

---

### Task T9.3: Retention policy + Celery-beat enforcement

**Files:**
- Modify: `telemetry_tool/tasks/retention_tasks.py` (add `enforce_sidecar_retention` task)
- Modify: `telemetry_tool/celery_app.py` (add beat entry)
- Test: `telemetry_tool/tests/storage/test_retention.py`

- [x] **Step 1: Write the failing retention test.**

`telemetry_tool/tests/storage/test_retention.py`:

```python
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from telemetry_tool.storage.sidecar_store import SidecarStore
from telemetry_tool.web.schemas.contracts import SourceLiteral
from tasks.retention_tasks import enforce_sidecar_retention


def test_sidecars_older_than_retention_are_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDECAR_ROOT", str(tmp_path))
    monkeypatch.setenv("SIDECAR_RETENTION_DAYS", "30")
    store = SidecarStore(root=tmp_path)
    df = pd.DataFrame({"a": [1, 2, 3]})

    fresh_ref = store.save(session_id="sfresh", workspace_id="w1",
                           source=SourceLiteral.REAL_LIFE, df=df)
    stale_ref = store.save(session_id="sstale", workspace_id="w1",
                           source=SourceLiteral.REAL_LIFE, df=df)
    # Age the stale file by setting its mtime to 45 days ago.
    stale_path = tmp_path / stale_ref.object_key
    old_time = time.time() - 45 * 86400
    os.utime(stale_path, (old_time, old_time))

    deleted = enforce_sidecar_retention()  # runs synchronously — no Celery needed
    assert deleted == 1
    assert not stale_path.exists()
    assert (tmp_path / fresh_ref.object_key).exists()
```

- [x] **Step 2: Implement the retention task.**

Append to `telemetry_tool/tasks/retention_tasks.py`:

```python
# ── Sidecar retention (W9.T9.3) ────────────────────────────────────────
import os
import time
from pathlib import Path

from celery_app import celery


_DEFAULT_RETENTION_DAYS = 30


@celery.task(name="tasks.retention_tasks.enforce_sidecar_retention")
def enforce_sidecar_retention() -> int:
    """Delete raw Parquet sidecars older than SIDECAR_RETENTION_DAYS.

    Returns the number of files deleted. 0 when the root dir doesn't
    exist (local dev or fresh deploy).
    """
    root = Path(os.environ.get("SIDECAR_ROOT", "/data/sidecars"))
    if not root.is_dir():
        return 0
    cutoff = time.time() - (
        int(os.environ.get("SIDECAR_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS)) * 86400
    )
    deleted = 0
    for pq in root.rglob("raw.parquet"):
        try:
            if pq.stat().st_mtime < cutoff:
                pq.unlink()
                # prune empty parents
                for p in (pq.parent, pq.parent.parent):
                    try:
                        p.rmdir()
                    except OSError:
                        break
                deleted += 1
        except OSError:
            continue
    return deleted
```

- [x] **Step 3: Wire the beat schedule.**

In `telemetry_tool/celery_app.py` `beat_schedule={...}` block, add (alongside `enforce-tiered-retention`):

```python
        "enforce-sidecar-retention": {
            "task": "tasks.retention_tasks.enforce_sidecar_retention",
            "schedule": crontab(hour=3, minute=30),   # 30 min after tier retention
            "options": {"queue": "default"},
        },
```

- [x] **Step 4: Run.**

```bash
pytest telemetry_tool/tests/storage/test_retention.py -v
```

Expected: PASS.

- [x] **Step 5: Commit.**

```bash
git add telemetry_tool/tasks/retention_tasks.py \
        telemetry_tool/celery_app.py \
        telemetry_tool/tests/storage/test_retention.py
git commit -m "feat(storage): sidecar retention (default 30d, env-override) (W9.T9.3)"
```

---

### Task T9.4: Backfill script — idempotent

**Files:**
- Create: `scripts/backfill_session_sources.py`
- Test: `telemetry_tool/tests/test_backfill_sources.py`

- [x] **Step 1: Write the failing test.**

`telemetry_tool/tests/test_backfill_sources.py`:

```python
"""Idempotency contract for the backfill script.

Runs twice; asserts the second run touches zero rows.
"""
import os
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("TELEMETRY_PG_URL_TEST"),
    reason="needs disposable PG; set TELEMETRY_PG_URL_TEST",
)


def _run(args: list[str]) -> tuple[int, str]:
    env = {**os.environ, "TELEMETRY_PG_URL": os.environ["TELEMETRY_PG_URL_TEST"]}
    p = subprocess.run(
        [sys.executable, "scripts/backfill_session_sources.py", *args],
        capture_output=True, text=True, env=env, check=False,
    )
    return p.returncode, p.stdout + p.stderr


def test_backfill_is_idempotent(disposable_pg):  # fixture from conftest — seeds 2 rows with source=NULL
    rc1, out1 = _run([])
    assert rc1 == 0
    assert "updated 2 row(s)" in out1

    rc2, out2 = _run([])
    assert rc2 == 0
    assert "updated 0 row(s)" in out2
```

- [x] **Step 2: Write the script.**

`scripts/backfill_session_sources.py`:

```python
#!/usr/bin/env python3
"""Backfill `sessions.source` / `capabilities` / `data_profile` for pre-W1 rows.

Idempotent: only touches rows where `source IS NULL`. Migration 059 has
already run a one-shot backfill as part of upgrade — this script exists
for the edge case where new rows are inserted by downgraded code paths.

Usage:
  TELEMETRY_PG_URL=postgresql://... python scripts/backfill_session_sources.py
"""
from __future__ import annotations

import logging
import os
import sys

import psycopg2


def main() -> int:
    dsn = os.environ.get("TELEMETRY_PG_URL")
    if not dsn:
        print("TELEMETRY_PG_URL env var required", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sessions
                   SET source       = COALESCE(source, 'real_life'),
                       data_profile = COALESCE(data_profile, '{}'::jsonb),
                       capabilities = COALESCE(capabilities,
                                     '{"channels":["gps"]}'::jsonb)
                 WHERE source IS NULL
                    OR data_profile IS NULL
                    OR capabilities IS NULL
                """
            )
            updated = cur.rowcount
            conn.commit()
    print(f"backfill_session_sources: updated {updated} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make executable:

```bash
chmod +x scripts/backfill_session_sources.py
```

- [x] **Step 3: Add the disposable-PG conftest fixture.**

Append to `telemetry_tool/tests/conftest.py` (or create if no PG section exists):

```python
@pytest.fixture
def disposable_pg():
    """Seed 2 sessions with source=NULL on a disposable PG."""
    dsn = os.environ.get("TELEMETRY_PG_URL_TEST")
    if not dsn:
        pytest.skip("TELEMETRY_PG_URL_TEST not set")
    import psycopg2
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE sessions ALTER COLUMN source DROP NOT NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN data_profile DROP NOT NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN capabilities DROP NOT NULL")
            cur.execute(
                "INSERT INTO sessions (session_id, workspace_id, source, data_profile, capabilities) "
                "VALUES (%s, %s, NULL, NULL, NULL), (%s, %s, NULL, NULL, NULL)",
                ("00000000-0000-0000-0000-0000000000a1", "ws-test",
                 "00000000-0000-0000-0000-0000000000a2", "ws-test"),
            )
        conn.commit()
    yield
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE workspace_id = 'ws-test'")
            cur.execute("ALTER TABLE sessions ALTER COLUMN source SET NOT NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN data_profile SET NOT NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN capabilities SET NOT NULL")
        conn.commit()
```

- [x] **Step 4: Run.**

```bash
TELEMETRY_PG_URL_TEST=postgresql://telemetry:telemetry@localhost:5433/telemetry_test \
  pytest telemetry_tool/tests/test_backfill_sources.py -v
```

Expected: PASS (or SKIP if no PG). CI must set the env var.

- [x] **Step 5: Commit.**

```bash
git add scripts/backfill_session_sources.py \
        telemetry_tool/tests/test_backfill_sources.py \
        telemetry_tool/tests/conftest.py
git commit -m "feat(storage): idempotent source/capabilities backfill (W9.T9.4)"
```

---

### Task T9.5: Rollback runbook

**Files:**
- Create: `docs/runbooks/W9-migration-rollback.md`

- [x] **Step 1: Write the runbook.**

`docs/runbooks/W9-migration-rollback.md`:

```markdown
# W9 — Unified Ingest/Storage Rollback Runbook

## When to use this

Any of:
- `POST /api/v1/sessions/upload` error rate > 5% over 10 min after deploy.
- Celery `sim` workers crash-looping.
- Alembic 059 post-deploy leaves rows with NULL source/capabilities.
- User reports "session missing from list" after upload.

## Level 1 — runtime kill switch (≤ 2 min)

1. SSH to VPS: `ssh root@46.225.227.24`.
2. Edit `/opt/lap-api/.env.production` and set:
   ```
   INGEST_ROUTER_ENABLED=0
   ```
3. `docker compose -f /opt/lap-api/docker-compose.prod.yml restart api`
4. Verify: `curl https://api.lap-coach.racing/healthz` = 200.

At this point the new routing path is bypassed — the pre-W2 real-life-only upload path runs.

## Level 2 — revert the merge (≤ 15 min)

1. `cd /opt/lap-api && git log --oneline | head -20`, find the W2+W9 merge commit.
2. On your dev box: `git revert -m 1 <merge-sha> && git push origin main`.
3. Trigger the regular deploy pipeline.
4. Workers will re-deploy without the `sim` queue; this is safe — no `tasks.sim_tasks.*` messages are in flight unless session #5 has landed.

## Level 3 — Alembic downgrade (≤ 30 min, invasive)

Only use if migration 059 is causing schema-level issues (unlikely — it only adds three columns with defaults).

1. Take a DB backup FIRST: `/opt/lap-api/scripts/backup_pg.sh now`.
2. Stop the API: `docker compose stop api celery_pipeline celery_default celery_sim`.
3. Downgrade:
   ```bash
   docker compose run --rm api alembic downgrade 058
   ```
4. Restart with reverted code (Level 2 already done).
5. Verify `\d sessions` in psql — columns `source / data_profile / capabilities` should be gone.

## Level 4 — nuke sidecars (optional, data-loss)

Only if `/data/sidecars` is full or corrupted.

```bash
docker exec lap-api-1 rm -rf /data/sidecars
```

Raw re-analysis capability is lost for affected sessions until they are re-uploaded.

## Contacts

- Deploy + infra: `ssh root@46.225.227.24`
- Alembic + schema: backend lead
- Celery behaviour: see `docs/runbooks/celery-queues.md`
```

- [x] **Step 2: Sanity-check the runbook by running the downgrade on a disposable DB.**

```bash
TELEMETRY_PG_URL_TEST=postgresql://telemetry:telemetry@localhost:5433/telemetry_test \
  python -c "
import subprocess
subprocess.check_call(['alembic', 'upgrade', '059'])
subprocess.check_call(['alembic', 'downgrade', '058'])
subprocess.check_call(['alembic', 'upgrade', '059'])
print('rollback runbook step 3 is valid')
"
```

Expected output: `rollback runbook step 3 is valid`.

- [x] **Step 3: Commit.**

```bash
git add docs/runbooks/W9-migration-rollback.md
git commit -m "docs(runbooks): W9 migration rollback (W9.T9.5)"
```

---

## 4. Integration + signal commit

- [x] **Step 1: Run the full changed-surface test slate.**

```bash
pytest telemetry_tool/tests/ingest/ telemetry_tool/tests/storage/ \
       telemetry_tool/tests/test_backfill_sources.py \
       telemetry_tool/tests/test_contracts/test_migration_059.py -v
```

Expected: all PASS (PG-gated tests may SKIP on non-PG dev box — fine).

- [x] **Step 2: Run the existing upload + data-API suite to catch regressions.**

```bash
pytest telemetry_tool/tests/test_upload_sync.py \
       telemetry_tool/tests/test_data_api_v2.py -v
```

Expected: all previously-passing tests still PASS.

- [x] **Step 3: Ship it live.**

Per `CLAUDE.md` "Ship It Live" rule — any code change must be verified stable and deployed:

```bash
# Backend
scp telemetry_tool/ingest/*.py telemetry_tool/storage/*.py \
    telemetry_tool/web/routes/sessions_v2.py \
    telemetry_tool/celery_app.py \
    telemetry_tool/tasks/sim_tasks.py telemetry_tool/tasks/retention_tasks.py \
    telemetry_tool/alembic/versions/059_ws_w1_sessions_source_profile_caps.py \
    scripts/backfill_session_sources.py \
    root@46.225.227.24:/opt/lap-api/...
ssh root@46.225.227.24 "cd /opt/lap-api && \
    docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head && \
    docker compose -f docker-compose.prod.yml build api celery_pipeline && \
    docker compose -f docker-compose.prod.yml up -d api celery_pipeline celery_default"
curl -fsS https://api.lap-coach.racing/healthz
```

(The `celery_sim` service is added in session #5's deploy, not here — our placeholder task module is fine on the existing pipeline worker because the `sim` route is not hit until a stub handler is replaced.)

- [x] **Step 4: Final signal commit.**

```bash
git commit --allow-empty -m "[signal:W2-W9-done] — W2 router + W9 storage ready for real-life merge"
git push origin feat/ws-w2-w9-ingest-storage
```

Per the launch README: merge to `main` when session #4 (real-life adapter) is also merged and full E2E works for at least the real-life path.

---

## 5. Self-review checklist (run before handing back)

**Spec coverage** — every spec task maps to a plan task:

- §5 W2.T2.1 / T2.2 (profiler + DataProfile) → Task T2.1 ✅
- §5 W2.T2.3 (Router + HandlerRegistry) → Task T2.3 ✅
- §5 W2.T2.4 (upload endpoint) → Task T2.4 ✅
- §5 W2.T2.5 (Celery sim queue) → Task T2.5 ✅
- §5 W2.T2.6 (integration test 3 formats) → Task T2.6 ✅
- §5 W9.T9.1 (migration verify) → Bootstrap B.3/B.4 + Task T9.1 ✅
- §5 W9.T9.2 (SidecarStore) → Task T9.2 ✅
- §5 W9.T9.3 (retention) → Task T9.3 ✅
- §5 W9.T9.4 (backfill) → Task T9.4 ✅
- §5 W9.T9.5 (rollback) → Task T9.5 ✅
- §11 Acceptance criteria — covered by Tasks T2.6 (3-format routing) + T9.2 (save/reload) + T9.4 (backfill idempotent).

**Placeholder scan:** no "TBD / implement later / similar to Task N" appears in any step.

**Type consistency:** `DataProfile` / `EngineHandler` / `SidecarRef` have the same field names throughout. `ChannelTag` / `SourceLiteral` imported from `telemetry_tool.web.schemas.contracts` (W1) — no parallel definitions.

**Signals emitted per README:** final commit message contains `[signal:W2-W9-done]` ✅.

**Must-not-touch paths:** no task edits `telemetry_tool/web/schemas/contracts/**`, `telemetry_tool/shared/**`, `telemetry_tool/pipeline/contract_adapter.py`, any `contract_adapter.py` in sim_optimizer/lap_oracle, `coaching_v2/`, `optimizer_v2/`, or `lap-website/`.

---

## Execution handoff

Plan complete. Awaiting `/approve`.

Options after approval:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Fits this plan's granularity.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch with checkpoints.

**Which approach?** (Also still needed: your decision on the P0 blockers above — particularly B1: does this session merge W1, or wait?)
