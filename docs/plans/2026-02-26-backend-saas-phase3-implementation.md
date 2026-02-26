# Phase 3: Celery + Pipeline — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the 14-stage telemetry pipeline from synchronous Flask execution to asynchronous Celery tasks with Redis broker, enabling multi-worker processing, per-workspace isolation, batch re-analysis, and processing versioning.

**Architecture:** 3 coarse-grained Celery tasks chained: `pipeline_ingest` (stages 1-4) -> `pipeline_analyze` (stages 5-8j) -> `pipeline_finalize` (stages 9-15). PipelineContext stored in Redis (JSON metadata) + temp dir (Parquet DataFrames). Job state in PostgreSQL `ingestion_jobs` table. SSE polls PG every 2 seconds.

**Tech Stack:** Celery 5.x, Redis 7 (broker + result backend), PostgreSQL 16, Flask, Alembic, psutil

**Design doc:** `docs/plans/2026-02-26-backend-saas-phase3-design.md`

---

### Task 1: Pipeline Errors Module

**Files:**
- Create: `telemetry_tool/pipeline_errors.py`
- Create: `telemetry_tool/tests/test_pipeline_errors.py`

**Context:** Three error classes that Celery tasks use to decide retry/fail/pause behavior. These are simple exception subclasses with no external dependencies.

**Step 1: Write the failing test**

```python
"""Tests for pipeline error classes."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline_errors import TransientError, FatalError, InteractionRequired


class TestTransientError:
    def test_is_exception(self):
        err = TransientError("Redis timeout")
        assert isinstance(err, Exception)
        assert str(err) == "Redis timeout"

    def test_has_retry_eligible_true(self):
        err = TransientError("network blip")
        assert err.retry_eligible is True

    def test_inherits_from_pipeline_error(self):
        from pipeline_errors import PipelineError
        err = TransientError("x")
        assert isinstance(err, PipelineError)


class TestFatalError:
    def test_is_exception(self):
        err = FatalError("corrupt CSV")
        assert isinstance(err, Exception)
        assert str(err) == "corrupt CSV"

    def test_has_retry_eligible_false(self):
        err = FatalError("bad data")
        assert err.retry_eligible is False

    def test_stores_error_class(self):
        err = FatalError("x")
        assert err.error_class == "fatal"


class TestInteractionRequired:
    def test_is_exception(self):
        err = InteractionRequired("joker_confirm", {"candidate_lap": 5})
        assert isinstance(err, Exception)

    def test_stores_reason_and_payload(self):
        err = InteractionRequired("joker_confirm", {"candidate_lap": 5})
        assert err.reason == "joker_confirm"
        assert err.payload == {"candidate_lap": 5}

    def test_retry_eligible_false(self):
        err = InteractionRequired("joker_confirm", {})
        assert err.retry_eligible is False

    def test_error_class_is_interaction(self):
        err = InteractionRequired("joker_confirm", {})
        assert err.error_class == "interaction"


class TestErrorClassification:
    def test_classify_transient(self):
        from pipeline_errors import classify_error
        import redis
        err = redis.ConnectionError("connection refused")
        assert classify_error(err) == "transient"

    def test_classify_fatal_value_error(self):
        from pipeline_errors import classify_error
        err = ValueError("corrupt data")
        assert classify_error(err) == "fatal"

    def test_classify_pipeline_errors_directly(self):
        from pipeline_errors import classify_error
        assert classify_error(TransientError("x")) == "transient"
        assert classify_error(FatalError("x")) == "fatal"
        assert classify_error(InteractionRequired("r", {})) == "interaction"

    def test_classify_unknown_defaults_to_fatal(self):
        from pipeline_errors import classify_error
        assert classify_error(RuntimeError("unknown")) == "fatal"
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_errors.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'pipeline_errors'"

**Step 3: Write minimal implementation**

```python
"""Pipeline error classes for Celery task retry/fail/pause decisions."""
from __future__ import annotations

from typing import Any


class PipelineError(Exception):
    """Base class for all pipeline-specific errors."""
    retry_eligible: bool = False
    error_class: str = "unknown"


class TransientError(PipelineError):
    """Temporary failure that should be retried (network, Redis, disk)."""
    retry_eligible = True
    error_class = "transient"


class FatalError(PipelineError):
    """Permanent failure — no retry (corrupt data, impossible state)."""
    retry_eligible = False
    error_class = "fatal"


class InteractionRequired(PipelineError):
    """Pipeline needs user input to continue (e.g., joker confirmation)."""
    retry_eligible = False
    error_class = "interaction"

    def __init__(self, reason: str, payload: dict[str, Any]) -> None:
        super().__init__(f"Interaction required: {reason}")
        self.reason = reason
        self.payload = payload


# -- Error classification for unknown exceptions --

_TRANSIENT_TYPES: tuple[str, ...] = (
    "ConnectionError", "TimeoutError", "ConnectionRefusedError",
    "BrokenPipeError", "ConnectionResetError",
)


def classify_error(exc: Exception) -> str:
    """Classify an arbitrary exception as transient/fatal/interaction."""
    if isinstance(exc, PipelineError):
        return exc.error_class
    type_name = type(exc).__name__
    if type_name in _TRANSIENT_TYPES:
        return "transient"
    # Check parent classes too (e.g., redis.ConnectionError -> ConnectionError)
    for parent in type(exc).__mro__:
        if parent.__name__ in _TRANSIENT_TYPES:
            return "transient"
    return "fatal"
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_errors.py -v`
Expected: PASS (all 12 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline_errors.py telemetry_tool/tests/test_pipeline_errors.py
git commit -m "feat(pipeline): add error classes for Celery retry/fail/pause"
```

---

### Task 2: Pipeline Version Module

**Files:**
- Create: `telemetry_tool/pipeline_version.py`
- Create: `telemetry_tool/tests/test_pipeline_version.py`

**Context:** A single constant `PIPELINE_VERSION` and a helper to check staleness. Bumped manually when pipeline logic changes meaningfully.

**Step 1: Write the failing test**

```python
"""Tests for pipeline versioning."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline_version import PIPELINE_VERSION, is_stale


class TestPipelineVersion:
    def test_version_is_positive_integer(self):
        assert isinstance(PIPELINE_VERSION, int)
        assert PIPELINE_VERSION >= 1

    def test_is_stale_older_version(self):
        assert is_stale(session_version=0) is True

    def test_is_stale_current_version(self):
        assert is_stale(session_version=PIPELINE_VERSION) is False

    def test_is_stale_newer_version(self):
        # Should not happen, but treat as not stale
        assert is_stale(session_version=PIPELINE_VERSION + 1) is False

    def test_is_stale_none_treated_as_zero(self):
        assert is_stale(session_version=None) is True
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_version.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write minimal implementation**

```python
"""Pipeline processing version.

Bump PIPELINE_VERSION when pipeline logic changes in a way that
would produce different results for the same input data.
"""
from __future__ import annotations

from typing import Optional

PIPELINE_VERSION: int = 1


def is_stale(session_version: Optional[int]) -> bool:
    """Return True if a session was processed with an older pipeline version."""
    return (session_version or 0) < PIPELINE_VERSION
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_version.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline_version.py telemetry_tool/tests/test_pipeline_version.py
git commit -m "feat(pipeline): add PIPELINE_VERSION constant and staleness check"
```

---

### Task 3: Config Updates + Celery App

**Files:**
- Modify: `telemetry_tool/web/config.py:45-49` (add Redis URL)
- Create: `telemetry_tool/celery_app.py`
- Create: `telemetry_tool/tests/test_celery_app.py`

**Context:** Add `REDIS_URL` and `CELERY_BROKER_URL` to Config. Create the Celery instance with JSON serializer, two queues, crash-safe ack settings. The Celery app reads config from Flask but can also run standalone.

**Step 1: Write the failing test**

```python
"""Tests for Celery app configuration."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestCeleryConfig:
    def test_redis_url_in_config(self):
        from web.config import Config
        assert hasattr(Config, "REDIS_URL")
        assert "redis://" in Config.REDIS_URL

    def test_redis_url_from_env(self):
        with patch.dict("os.environ", {"REDIS_URL": "redis://custom:6380/1"}):
            # Re-import to pick up env var
            import importlib
            from web import config
            importlib.reload(config)
            assert config.Config.REDIS_URL == "redis://custom:6380/1"
            # Reset
            importlib.reload(config)


class TestCeleryAppCreation:
    def test_make_celery_returns_celery_instance(self):
        from celery_app import make_celery
        from flask import Flask

        app = Flask(__name__)
        app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
        app.config["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/0"

        celery = make_celery(app)
        assert celery is not None
        assert celery.main == "telemetry_tool"

    def test_json_serializer_configured(self):
        from celery_app import make_celery
        from flask import Flask

        app = Flask(__name__)
        app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
        app.config["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/0"

        celery = make_celery(app)
        assert celery.conf.task_serializer == "json"
        assert celery.conf.accept_content == ["json"]
        assert celery.conf.result_serializer == "json"

    def test_acks_late_configured(self):
        from celery_app import make_celery
        from flask import Flask

        app = Flask(__name__)
        app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
        app.config["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/0"

        celery = make_celery(app)
        assert celery.conf.task_acks_late is True
        assert celery.conf.task_reject_on_worker_lost is True

    def test_result_expires_set(self):
        from celery_app import make_celery
        from flask import Flask

        app = Flask(__name__)
        app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
        app.config["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/0"

        celery = make_celery(app)
        assert celery.conf.result_expires == 86400  # 24 hours

    def test_task_routes_configured(self):
        from celery_app import make_celery
        from flask import Flask

        app = Flask(__name__)
        app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
        app.config["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/0"

        celery = make_celery(app)
        routes = celery.conf.task_routes
        assert "tasks.pipeline_tasks.*" in routes
        assert routes["tasks.pipeline_tasks.*"]["queue"] == "pipeline"
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_celery_app.py -v`
Expected: FAIL with "AttributeError: type object 'Config' has no attribute 'REDIS_URL'"

**Step 3a: Add REDIS_URL to config.py**

In `telemetry_tool/web/config.py`, add after line 49 (after PG_URL):

```python
    # Redis (Celery broker + result backend + pipeline context)
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
```

Also add these derived properties after the REDIS_URL line:

```python
    # Celery
    CELERY_BROKER_URL: str = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND: str = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
```

**Step 3b: Create celery_app.py**

```python
"""Celery application factory.

Usage:
    # With Flask app (web server):
    celery = make_celery(flask_app)

    # Standalone worker:
    celery -A telemetry_tool.celery_app worker -Q pipeline --concurrency=2
"""
from __future__ import annotations

from celery import Celery


def make_celery(app=None) -> Celery:
    """Create and configure a Celery instance.

    If *app* is a Flask app, reads broker/backend from app.config.
    Otherwise falls back to environment defaults via Config.
    """
    if app is None:
        from web.config import Config
        broker = Config.CELERY_BROKER_URL
        backend = Config.CELERY_RESULT_BACKEND
    else:
        broker = app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        backend = app.config.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

    celery = Celery(
        "telemetry_tool",
        broker=broker,
        backend=backend,
    )

    celery.conf.update(
        # Serialization — JSON only (no unsafe formats)
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",

        # Crash safety
        task_acks_late=True,
        task_reject_on_worker_lost=True,

        # Result expiry (24 hours)
        result_expires=86400,

        # Queue routing
        task_routes={
            "tasks.pipeline_tasks.*": {"queue": "pipeline"},
            "tasks.batch_tasks.*": {"queue": "default"},
        },

        # Default queue for tasks not matching any route
        task_default_queue="default",
    )

    # If Flask app provided, set up app context for tasks
    if app is not None:
        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask

    return celery


# Standalone entry point for `celery -A telemetry_tool.celery_app worker`
celery = make_celery()
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_celery_app.py -v`
Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/config.py telemetry_tool/celery_app.py telemetry_tool/tests/test_celery_app.py
git commit -m "feat(celery): add Celery app factory with Redis broker and JSON serializer"
```

---

### Task 4: Pipeline Context Module

**Files:**
- Create: `telemetry_tool/pipeline_context.py`
- Create: `telemetry_tool/tests/test_pipeline_context.py`

**Context:** PipelineContext manages per-job state: JSON metadata in Redis, intermediate DataFrames as Parquet files in a temp directory. Each Celery group reads/writes context via `job_id`.

**Step 1: Write the failing test**

```python
"""Tests for PipelineContext (Redis metadata + temp dir Parquet)."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline_context import PipelineContext


@pytest.fixture
def mock_redis():
    """Mock Redis client with dict-backed storage."""
    store = {}
    r = MagicMock()
    r.set.side_effect = lambda k, v, **kw: store.__setitem__(k, v)
    r.get.side_effect = lambda k: store.get(k)
    r.delete.side_effect = lambda k: store.pop(k, None)
    r.expire.side_effect = lambda k, t: None
    return r, store


@pytest.fixture
def tmp_base(tmp_path):
    return tmp_path / "pipeline"


class TestContextCreation:
    def test_create_stores_metadata_in_redis(self, mock_redis, tmp_base):
        r, store = mock_redis
        ctx = PipelineContext.create(
            redis_client=r,
            job_id="job-123",
            workspace_id=42,
            session_id="sess-abc",
            file_path="/data/test.csv",
            base_dir=str(tmp_base),
        )
        assert ctx.job_id == "job-123"
        key = "pipeline:ctx:job-123"
        assert key in store
        meta = json.loads(store[key])
        assert meta["workspace_id"] == 42
        assert meta["session_id"] == "sess-abc"

    def test_create_makes_temp_directory(self, mock_redis, tmp_base):
        r, _ = mock_redis
        ctx = PipelineContext.create(
            redis_client=r, job_id="job-456",
            workspace_id=1, session_id="s", file_path="/x",
            base_dir=str(tmp_base),
        )
        assert ctx.temp_dir.exists()
        assert ctx.temp_dir.is_dir()


class TestContextLoadSave:
    def test_load_reads_from_redis(self, mock_redis, tmp_base):
        r, store = mock_redis
        # Pre-populate
        ctx = PipelineContext.create(
            redis_client=r, job_id="job-789",
            workspace_id=5, session_id="s1", file_path="/f",
            base_dir=str(tmp_base),
        )
        ctx.update_stage("03_derived_channels", 3, 15)
        ctx.save()

        # Load from "another worker"
        loaded = PipelineContext.load(r, "job-789", base_dir=str(tmp_base))
        assert loaded.workspace_id == 5
        assert loaded.current_stage == "03_derived_channels"
        assert loaded.stage_index == 3

    def test_load_missing_job_returns_none(self, mock_redis, tmp_base):
        r, _ = mock_redis
        result = PipelineContext.load(r, "nonexistent", base_dir=str(tmp_base))
        assert result is None


class TestDataFrameIO:
    def test_save_and_load_dataframe(self, mock_redis, tmp_base):
        r, _ = mock_redis
        ctx = PipelineContext.create(
            redis_client=r, job_id="job-df",
            workspace_id=1, session_id="s", file_path="/x",
            base_dir=str(tmp_base),
        )
        df = pd.DataFrame({"speed": [10.0, 20.0, 30.0], "lat": [1.1, 2.2, 3.3]})
        ctx.save_dataframe("stage_01_ingest", df)

        loaded = ctx.load_dataframe("stage_01_ingest")
        pd.testing.assert_frame_equal(df, loaded)

    def test_load_missing_dataframe_returns_none(self, mock_redis, tmp_base):
        r, _ = mock_redis
        ctx = PipelineContext.create(
            redis_client=r, job_id="job-nodf",
            workspace_id=1, session_id="s", file_path="/x",
            base_dir=str(tmp_base),
        )
        assert ctx.load_dataframe("nonexistent") is None


class TestContextCleanup:
    def test_cleanup_removes_temp_dir_and_redis_key(self, mock_redis, tmp_base):
        r, store = mock_redis
        ctx = PipelineContext.create(
            redis_client=r, job_id="job-clean",
            workspace_id=1, session_id="s", file_path="/x",
            base_dir=str(tmp_base),
        )
        df = pd.DataFrame({"x": [1]})
        ctx.save_dataframe("test", df)
        assert ctx.temp_dir.exists()

        ctx.cleanup()
        assert not ctx.temp_dir.exists()
        r.delete.assert_called()


class TestJokerState:
    def test_store_and_retrieve_joker_decision(self, mock_redis, tmp_base):
        r, _ = mock_redis
        ctx = PipelineContext.create(
            redis_client=r, job_id="job-joker",
            workspace_id=1, session_id="s", file_path="/x",
            base_dir=str(tmp_base),
        )
        ctx.set_joker_decision({"confirmed_lap": 5, "action": "accept"})
        ctx.save()

        loaded = PipelineContext.load(r, "job-joker", base_dir=str(tmp_base))
        assert loaded.joker_decision == {"confirmed_lap": 5, "action": "accept"}
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_context.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'pipeline_context'"

**Step 3: Write minimal implementation**

```python
"""PipelineContext — per-job state for Celery pipeline tasks.

Metadata (job_id, workspace_id, stage info, joker decisions) lives in Redis.
Intermediate DataFrames live as Parquet files in a temp directory.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "/tmp/pipeline"
_REDIS_TTL_SECONDS = 7200  # 2 hours safety net


@dataclass
class PipelineContext:
    """Serializable context passed between Celery pipeline groups."""

    job_id: str
    workspace_id: int
    session_id: str
    file_path: str
    current_stage: str = ""
    stage_index: int = 0
    stage_total: int = 15
    errors: list[dict[str, str]] = field(default_factory=list)
    joker_decision: Optional[dict[str, Any]] = None

    # Not serialized — set after load
    _redis: Any = field(default=None, repr=False)
    _base_dir: str = field(default=_DEFAULT_BASE, repr=False)

    @property
    def temp_dir(self) -> Path:
        return Path(self._base_dir) / self.job_id

    @property
    def _redis_key(self) -> str:
        return f"pipeline:ctx:{self.job_id}"

    # -- Factory methods --

    @classmethod
    def create(
        cls,
        redis_client: Any,
        job_id: str,
        workspace_id: int,
        session_id: str,
        file_path: str,
        base_dir: str = _DEFAULT_BASE,
    ) -> PipelineContext:
        """Create a new context, store in Redis, create temp dir."""
        ctx = cls(
            job_id=job_id,
            workspace_id=workspace_id,
            session_id=session_id,
            file_path=file_path,
            _redis=redis_client,
            _base_dir=base_dir,
        )
        ctx.temp_dir.mkdir(parents=True, exist_ok=True)
        ctx.save()
        return ctx

    @classmethod
    def load(
        cls,
        redis_client: Any,
        job_id: str,
        base_dir: str = _DEFAULT_BASE,
    ) -> Optional[PipelineContext]:
        """Load context from Redis. Returns None if not found."""
        key = f"pipeline:ctx:{job_id}"
        raw = redis_client.get(key)
        if raw is None:
            return None
        meta = json.loads(raw)
        ctx = cls(
            job_id=job_id,
            workspace_id=meta["workspace_id"],
            session_id=meta["session_id"],
            file_path=meta["file_path"],
            current_stage=meta.get("current_stage", ""),
            stage_index=meta.get("stage_index", 0),
            stage_total=meta.get("stage_total", 15),
            errors=meta.get("errors", []),
            joker_decision=meta.get("joker_decision"),
            _redis=redis_client,
            _base_dir=base_dir,
        )
        return ctx

    # -- Persistence --

    def save(self) -> None:
        """Write metadata to Redis."""
        meta = {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "file_path": self.file_path,
            "current_stage": self.current_stage,
            "stage_index": self.stage_index,
            "stage_total": self.stage_total,
            "errors": self.errors,
            "joker_decision": self.joker_decision,
        }
        self._redis.set(self._redis_key, json.dumps(meta))
        self._redis.expire(self._redis_key, _REDIS_TTL_SECONDS)

    # -- Stage tracking --

    def update_stage(self, stage_name: str, index: int, total: int = 15) -> None:
        self.current_stage = stage_name
        self.stage_index = index
        self.stage_total = total

    def add_error(self, stage: str, message: str) -> None:
        self.errors.append({"stage": stage, "message": message})

    # -- Joker state --

    def set_joker_decision(self, decision: dict[str, Any]) -> None:
        self.joker_decision = decision

    # -- DataFrame I/O --

    def save_dataframe(self, name: str, df: pd.DataFrame) -> Path:
        """Save a DataFrame as Parquet in the temp directory."""
        path = self.temp_dir / f"{name}.parquet"
        df.to_parquet(path, index=False)
        return path

    def load_dataframe(self, name: str) -> Optional[pd.DataFrame]:
        """Load a DataFrame from the temp directory. Returns None if missing."""
        path = self.temp_dir / f"{name}.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)

    # -- Cleanup --

    def cleanup(self) -> None:
        """Remove temp directory and Redis key."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self._redis.delete(self._redis_key)
        logger.info("Cleaned up context for job %s", self.job_id)
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_context.py -v`
Expected: PASS (all 9 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/pipeline_context.py telemetry_tool/tests/test_pipeline_context.py
git commit -m "feat(pipeline): add PipelineContext for Redis metadata + temp dir Parquet I/O"
```

---

### Task 5: Alembic Migration 009 — Schema Changes

**Files:**
- Create: `telemetry_tool/alembic/versions/009_celery_pipeline.py`
- Create: `telemetry_tool/tests/test_migration_009.py`

**Context:** Add columns to `ingestion_jobs` (celery_task_id, progress fields, error_class, pause_reason, updated_at, processing_version), add `processing_version` to `sessions`, create `batch_jobs` table. Single migration for all Phase 3 schema changes.

**Reference:** Previous migrations are at `telemetry_tool/alembic/versions/001_..py` through `008_..py`. This is migration 009.

**Step 1: Write the migration test**

```python
"""Tests for migration 009 — Celery pipeline schema changes."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def pg_engine():
    """Real PG engine from TELEMETRY_PG_URL env or skip."""
    import os
    pg_url = os.environ.get("TELEMETRY_PG_URL")
    if not pg_url:
        pytest.skip("TELEMETRY_PG_URL not set")
    engine = sa.create_engine(pg_url)
    yield engine
    engine.dispose()


class TestMigration009Schema:
    """Verify migration 009 adds expected columns and tables."""

    def test_migration_module_imports(self):
        from alembic.versions import __path__ as versions_path
        import importlib
        mod = importlib.import_module("alembic.versions.009_celery_pipeline")
        assert mod.revision == "009"
        assert mod.down_revision == "008"

    def test_tenant_tables_list_not_modified(self):
        """Migration 009 should NOT modify TENANT_TABLES from 006."""
        import importlib
        mod = importlib.import_module("alembic.versions.009_celery_pipeline")
        # Ensure upgrade/downgrade functions exist
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)

    def test_ingestion_jobs_new_columns_defined(self):
        """Verify the migration adds the expected columns to ingestion_jobs."""
        import importlib
        import inspect
        mod = importlib.import_module("alembic.versions.009_celery_pipeline")
        source = inspect.getsource(mod.upgrade)
        expected_cols = [
            "celery_task_id", "processing_version", "stage_name",
            "stage_index", "stage_total", "progress_pct",
            "error_class", "pause_reason", "updated_at",
        ]
        for col in expected_cols:
            assert col in source, f"Column {col} not found in upgrade()"

    def test_batch_jobs_table_defined(self):
        """Verify the migration creates batch_jobs table."""
        import importlib
        import inspect
        mod = importlib.import_module("alembic.versions.009_celery_pipeline")
        source = inspect.getsource(mod.upgrade)
        assert "batch_jobs" in source

    def test_sessions_processing_version_defined(self):
        """Verify sessions gets processing_version column."""
        import importlib
        import inspect
        mod = importlib.import_module("alembic.versions.009_celery_pipeline")
        source = inspect.getsource(mod.upgrade)
        assert "sessions" in source
        assert "processing_version" in source
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_migration_009.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'alembic.versions.009_celery_pipeline'"

**Step 3: Write the migration**

```python
"""Add Celery pipeline columns, batch_jobs table, processing_version.

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"


def upgrade() -> None:
    # 1. Add columns to ingestion_jobs for Celery task tracking
    op.add_column("ingestion_jobs", sa.Column("celery_task_id", sa.Text))
    op.add_column("ingestion_jobs", sa.Column(
        "processing_version", sa.Integer, server_default="1"))
    op.add_column("ingestion_jobs", sa.Column("stage_name", sa.Text))
    op.add_column("ingestion_jobs", sa.Column("stage_index", sa.Integer))
    op.add_column("ingestion_jobs", sa.Column("stage_total", sa.Integer))
    op.add_column("ingestion_jobs", sa.Column("progress_pct", sa.Float))
    op.add_column("ingestion_jobs", sa.Column("error_class", sa.Text))
    op.add_column("ingestion_jobs", sa.Column("pause_reason", sa.Text))
    op.add_column("ingestion_jobs", sa.Column(
        "updated_at", sa.DateTime, server_default=sa.func.now()))

    # 2. Add processing_version to sessions
    op.add_column("sessions", sa.Column(
        "processing_version", sa.Integer, server_default="1"))

    # 3. Create batch_jobs table
    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("created_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("total_sessions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_sessions", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("failed_sessions", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("filter_criteria", sa.Text),  # JSON
        sa.Column("processing_version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
    )
    op.create_index("idx_batch_jobs_workspace", "batch_jobs", ["workspace_id"])
    op.create_index("idx_batch_jobs_status", "batch_jobs", ["status"])

    # 4. Add batch_job_id FK to ingestion_jobs (links individual jobs to batch)
    op.add_column("ingestion_jobs", sa.Column("batch_job_id", sa.Integer))
    op.create_foreign_key(
        "fk_ingestion_jobs_batch", "ingestion_jobs", "batch_jobs",
        ["batch_job_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_ingestion_jobs_batch", "ingestion_jobs",
                       type_="foreignkey")
    op.drop_column("ingestion_jobs", "batch_job_id")
    op.drop_index("idx_batch_jobs_status", "batch_jobs")
    op.drop_index("idx_batch_jobs_workspace", "batch_jobs")
    op.drop_table("batch_jobs")
    op.drop_column("sessions", "processing_version")
    op.drop_column("ingestion_jobs", "updated_at")
    op.drop_column("ingestion_jobs", "pause_reason")
    op.drop_column("ingestion_jobs", "error_class")
    op.drop_column("ingestion_jobs", "progress_pct")
    op.drop_column("ingestion_jobs", "stage_total")
    op.drop_column("ingestion_jobs", "stage_index")
    op.drop_column("ingestion_jobs", "stage_name")
    op.drop_column("ingestion_jobs", "processing_version")
    op.drop_column("ingestion_jobs", "celery_task_id")
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_migration_009.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/alembic/versions/009_celery_pipeline.py telemetry_tool/tests/test_migration_009.py
git commit -m "feat(migration): add Celery pipeline columns, batch_jobs table (009)"
```

---

### Task 6: Concurrency — Workspace Lock + Backpressure

**Files:**
- Create: `telemetry_tool/tasks/__init__.py`
- Create: `telemetry_tool/tasks/concurrency.py`
- Create: `telemetry_tool/tests/test_concurrency.py`

**Context:** Per-workspace Redis lock prevents concurrent pipelines for the same workspace. Queue depth check rejects uploads when pipeline queue is saturated. Memory guard lets workers self-terminate when RSS exceeds threshold.

**Step 1: Write the failing test**

```python
"""Tests for pipeline concurrency controls."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.concurrency import (
    acquire_workspace_lock,
    release_workspace_lock,
    check_queue_depth,
    check_worker_memory,
    QueueFullError,
    WorkspaceBusyError,
)


class TestWorkspaceLock:
    def test_acquire_lock_success(self):
        r = MagicMock()
        r.set.return_value = True  # SETNX success
        assert acquire_workspace_lock(r, workspace_id=42, job_id="j1") is True
        r.set.assert_called_once()
        # Verify NX and EX flags
        call_kwargs = r.set.call_args[1]
        assert call_kwargs.get("nx") is True
        assert call_kwargs.get("ex") == 1800  # 30 min

    def test_acquire_lock_fails_when_held(self):
        r = MagicMock()
        r.set.return_value = False  # Someone else holds it
        assert acquire_workspace_lock(r, workspace_id=42, job_id="j2") is False

    def test_release_lock_only_if_owner(self):
        r = MagicMock()
        r.get.return_value = b"j1"
        release_workspace_lock(r, workspace_id=42, job_id="j1")
        r.delete.assert_called_once()

    def test_release_lock_skips_if_not_owner(self):
        r = MagicMock()
        r.get.return_value = b"other-job"
        release_workspace_lock(r, workspace_id=42, job_id="j1")
        r.delete.assert_not_called()


class TestQueueDepth:
    def test_check_passes_when_below_limit(self):
        r = MagicMock()
        r.llen.return_value = 10
        # Should not raise
        check_queue_depth(r, max_depth=50)

    def test_check_raises_when_at_limit(self):
        r = MagicMock()
        r.llen.return_value = 50
        with pytest.raises(QueueFullError):
            check_queue_depth(r, max_depth=50)

    def test_check_raises_when_above_limit(self):
        r = MagicMock()
        r.llen.return_value = 100
        with pytest.raises(QueueFullError):
            check_queue_depth(r, max_depth=50)


class TestWorkerMemory:
    @patch("tasks.concurrency.psutil")
    def test_below_threshold_returns_false(self, mock_psutil):
        mock_psutil.Process.return_value.memory_info.return_value.rss = (
            500 * 1024 * 1024  # 500 MB
        )
        assert check_worker_memory(max_rss_mb=1500) is False

    @patch("tasks.concurrency.psutil")
    def test_above_threshold_returns_true(self, mock_psutil):
        mock_psutil.Process.return_value.memory_info.return_value.rss = (
            2000 * 1024 * 1024  # 2 GB
        )
        assert check_worker_memory(max_rss_mb=1500) is True
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_concurrency.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'tasks'"

**Step 3: Write implementation**

Create `telemetry_tool/tasks/__init__.py`:
```python
```

Create `telemetry_tool/tasks/concurrency.py`:
```python
"""Pipeline concurrency controls: workspace lock, queue depth, memory guard."""
from __future__ import annotations

import logging
from typing import Any

import psutil

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 1800  # 30 minutes
_DEFAULT_MAX_DEPTH = 50
_DEFAULT_MAX_RSS_MB = 1500


class WorkspaceBusyError(Exception):
    """Raised when a workspace pipeline lock cannot be acquired."""
    pass


class QueueFullError(Exception):
    """Raised when the pipeline queue exceeds depth limit."""
    pass


def acquire_workspace_lock(
    redis_client: Any,
    workspace_id: int,
    job_id: str,
    ttl: int = _LOCK_TTL_SECONDS,
) -> bool:
    """Try to acquire a per-workspace pipeline lock.

    Returns True if lock acquired, False if another pipeline holds it.
    """
    key = f"pipeline:lock:{workspace_id}"
    acquired = redis_client.set(key, job_id, nx=True, ex=ttl)
    if acquired:
        logger.info("Acquired pipeline lock for workspace %d (job %s)", workspace_id, job_id)
    return bool(acquired)


def release_workspace_lock(
    redis_client: Any,
    workspace_id: int,
    job_id: str,
) -> None:
    """Release workspace lock only if we are the owner."""
    key = f"pipeline:lock:{workspace_id}"
    current = redis_client.get(key)
    if current is not None:
        # Compare as strings (Redis returns bytes)
        current_str = current.decode() if isinstance(current, bytes) else str(current)
        if current_str == job_id:
            redis_client.delete(key)
            logger.info("Released pipeline lock for workspace %d (job %s)", workspace_id, job_id)
        else:
            logger.warning(
                "Lock for workspace %d held by %s, not %s — skipping release",
                workspace_id, current_str, job_id,
            )


def check_queue_depth(
    redis_client: Any,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    queue_name: str = "pipeline",
) -> None:
    """Raise QueueFullError if the pipeline queue exceeds max_depth."""
    depth = redis_client.llen(queue_name)
    if depth >= max_depth:
        raise QueueFullError(
            f"Pipeline queue has {depth} pending tasks (limit: {max_depth})"
        )


def check_worker_memory(max_rss_mb: int = _DEFAULT_MAX_RSS_MB) -> bool:
    """Return True if current process RSS exceeds threshold.

    Callers should call sys.exit(0) when this returns True,
    allowing the supervisor to restart the worker.
    """
    rss_bytes = psutil.Process().memory_info().rss
    rss_mb = rss_bytes / (1024 * 1024)
    if rss_mb > max_rss_mb:
        logger.warning("Worker RSS %.0f MB exceeds %d MB threshold", rss_mb, max_rss_mb)
        return True
    return False
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_concurrency.py -v`
Expected: PASS (all 9 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/tasks/__init__.py telemetry_tool/tasks/concurrency.py telemetry_tool/tests/test_concurrency.py
git commit -m "feat(celery): add workspace lock, queue depth check, memory guard"
```

---

### Task 7: Pipeline Tasks — Three Celery Groups

**Files:**
- Create: `telemetry_tool/tasks/pipeline_tasks.py`
- Create: `telemetry_tool/tests/test_pipeline_tasks.py`

**Context:** Three Celery tasks chained: `pipeline_ingest` (stages 1-4), `pipeline_analyze` (stages 5-8j), `pipeline_finalize` (stages 9-15). Each task receives `job_id`, loads PipelineContext, runs stages, updates `ingestion_jobs` progress in PG, saves context, returns `job_id`.

The existing `run_full_analysis()` in `pipeline.py:475` is a 2000-line monolith. We do NOT refactor it. Instead, each Celery task calls the relevant sub-stages by importing the same module-level helpers that `run_full_analysis()` uses. The `_safe_step()` pattern is preserved.

**Important:** These tests use `CELERY_ALWAYS_EAGER=True` and mock the pipeline stages + DB. They verify the task orchestration logic, not the actual pipeline computation.

**Step 1: Write the failing test**

```python
"""Tests for Celery pipeline tasks."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.pipeline_tasks import (
    pipeline_ingest,
    pipeline_analyze,
    pipeline_finalize,
    build_pipeline_chain,
    _update_job_progress,
)


@pytest.fixture
def mock_ctx():
    """Mock PipelineContext."""
    ctx = MagicMock()
    ctx.job_id = "job-test"
    ctx.workspace_id = 1
    ctx.session_id = "sess-1"
    ctx.file_path = "/data/test.csv"
    ctx.stage_index = 0
    ctx.stage_total = 15
    ctx.errors = []
    ctx.joker_decision = None
    return ctx


@pytest.fixture
def mock_pg_conn():
    conn = MagicMock()
    return conn


class TestUpdateJobProgress:
    def test_updates_ingestion_jobs_row(self, mock_pg_conn):
        _update_job_progress(
            mock_pg_conn, job_id="j1",
            status="processing", stage_name="02_filter",
            stage_index=2, stage_total=15,
        )
        mock_pg_conn.execute.assert_called_once()
        sql = str(mock_pg_conn.execute.call_args)
        assert "ingestion_jobs" in sql
        assert "stage_name" in sql
        mock_pg_conn.commit.assert_called_once()


class TestPipelineIngest:
    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_returns_job_id(self, MockCtx, mock_redis, mock_pg, mock_ctx):
        MockCtx.load.return_value = mock_ctx
        mock_pg.return_value = MagicMock()

        # Mock the pipeline stage functions
        with patch("tasks.pipeline_tasks._run_ingest_stages") as mock_stages:
            mock_stages.return_value = {"raw_df_saved": True}
            result = pipeline_ingest("job-test")

        assert result == "job-test"
        mock_ctx.save.assert_called()

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_sets_failed_on_fatal_error(self, MockCtx, mock_redis, mock_pg, mock_ctx):
        MockCtx.load.return_value = mock_ctx
        conn = MagicMock()
        mock_pg.return_value = conn

        from pipeline_errors import FatalError
        with patch("tasks.pipeline_tasks._run_ingest_stages") as mock_stages:
            mock_stages.side_effect = FatalError("corrupt CSV")
            with pytest.raises(FatalError):
                pipeline_ingest("job-test")

        # Verify job marked as failed
        calls = conn.execute.call_args_list
        assert any("failed" in str(c) for c in calls)


class TestPipelineAnalyze:
    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_returns_job_id_on_success(self, MockCtx, mock_redis, mock_pg, mock_ctx):
        MockCtx.load.return_value = mock_ctx
        mock_pg.return_value = MagicMock()

        with patch("tasks.pipeline_tasks._run_analyze_stages") as mock_stages:
            mock_stages.return_value = {"joker_blocked": False}
            result = pipeline_analyze("job-test")

        assert result == "job-test"

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_pauses_on_joker_block(self, MockCtx, mock_redis, mock_pg, mock_ctx):
        MockCtx.load.return_value = mock_ctx
        conn = MagicMock()
        mock_pg.return_value = conn

        from pipeline_errors import InteractionRequired
        with patch("tasks.pipeline_tasks._run_analyze_stages") as mock_stages:
            mock_stages.side_effect = InteractionRequired(
                "joker_confirm", {"candidate_lap": 5}
            )
            # Should NOT raise — catches InteractionRequired and pauses
            result = pipeline_analyze("job-test")

        assert result is None  # Chain stops here
        calls = conn.execute.call_args_list
        assert any("paused" in str(c) for c in calls)


class TestPipelineFinalize:
    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    def test_returns_job_id_and_cleans_up(self, MockCtx, mock_redis, mock_pg, mock_ctx):
        MockCtx.load.return_value = mock_ctx
        mock_pg.return_value = MagicMock()

        with patch("tasks.pipeline_tasks._run_finalize_stages") as mock_stages:
            mock_stages.return_value = {"score": 85.0}
            result = pipeline_finalize("job-test")

        assert result == "job-test"
        mock_ctx.cleanup.assert_called_once()


class TestBuildPipelineChain:
    def test_returns_celery_chain(self):
        chain = build_pipeline_chain("job-abc")
        # Verify it's a Celery chain (has __or__ from signature chaining)
        assert chain is not None
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_tasks.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'tasks.pipeline_tasks'"

**Step 3: Write implementation**

```python
"""Celery pipeline tasks — 3 coarse-grained groups chained together.

Chain: pipeline_ingest -> pipeline_analyze -> pipeline_finalize

Each task:
1. Loads PipelineContext from Redis
2. Runs pipeline stages via _safe_step()
3. Updates ingestion_jobs progress in PG
4. Saves context back to Redis
5. Returns job_id for the next task in the chain
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Optional

import sqlalchemy as sa
from celery import chain as celery_chain

from celery_app import celery
from pipeline_context import PipelineContext
from pipeline_errors import (
    FatalError, InteractionRequired, TransientError, classify_error,
)
from pipeline_version import PIPELINE_VERSION
from tasks.concurrency import (
    acquire_workspace_lock,
    release_workspace_lock,
    check_worker_memory,
)

logger = logging.getLogger(__name__)


# -- Helpers --

def _get_redis():
    """Get Redis client from celery broker connection."""
    import redis
    from web.config import Config
    return redis.from_url(Config.REDIS_URL)


def _get_pg_connection():
    """Get a PG connection for job progress updates."""
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _update_job_progress(
    conn: Any,
    job_id: str,
    status: str = "processing",
    stage_name: str = "",
    stage_index: int = 0,
    stage_total: int = 15,
    error_message: str = "",
    error_class: str = "",
    pause_reason: str = "",
) -> None:
    """Update ingestion_jobs row with current progress."""
    progress_pct = (stage_index / stage_total * 100) if stage_total > 0 else 0
    conn.execute(
        sa.text(
            "UPDATE ingestion_jobs SET "
            "status = :status, stage_name = :stage_name, "
            "stage_index = :stage_index, stage_total = :stage_total, "
            "progress_pct = :progress_pct, "
            "error_message = :error_message, error_class = :error_class, "
            "pause_reason = :pause_reason, "
            "updated_at = NOW() "
            "WHERE job_id = :job_id"
        ),
        {
            "job_id": job_id, "status": status,
            "stage_name": stage_name, "stage_index": stage_index,
            "stage_total": stage_total, "progress_pct": progress_pct,
            "error_message": error_message, "error_class": error_class,
            "pause_reason": pause_reason,
        },
    )
    conn.commit()


def _mark_job_failed(conn: Any, job_id: str, error: Exception) -> None:
    """Mark a job as failed with error details."""
    _update_job_progress(
        conn, job_id,
        status="failed",
        error_message=str(error),
        error_class=classify_error(error),
    )


# -- Stage runners (thin wrappers around pipeline.py internals) --

def _run_ingest_stages(ctx: PipelineContext, conn: Any) -> dict:
    """Run stages 1-4: ingest, GPS filter, derived channels, session trim."""
    from pipeline import _safe_step
    import io_racechrono

    results: dict[str, Any] = {}

    # Stage 1: Ingest CSV
    ctx.update_stage("01_ingest", 1, 15)
    _update_job_progress(conn, ctx.job_id, stage_name="01_ingest", stage_index=1)
    raw_df, err = _safe_step("01_ingest", io_racechrono.read_racechrono_csv, ctx.file_path)
    if raw_df is None:
        raise FatalError(f"Ingest failed: {err}")

    # Stage 2: GPS filter
    ctx.update_stage("02_filter", 2, 15)
    _update_job_progress(conn, ctx.job_id, stage_name="02_filter", stage_index=2)
    try:
        from gps_filtering import filter_gps_quality
        filtered_df, err = _safe_step("02_filter", filter_gps_quality, raw_df)
        if filtered_df is None:
            filtered_df = raw_df
    except ImportError:
        filtered_df = raw_df
    del raw_df

    # Stage 3: Derived channels
    ctx.update_stage("03_derived_channels", 3, 15)
    _update_job_progress(conn, ctx.job_id, stage_name="03_derived_channels", stage_index=3)
    try:
        import derived_channels as dc_mod
        enriched_df, err = _safe_step("03_derived_channels", lambda: (
            dc_mod.compute_yaw_rate_from_heading(
                dc_mod.compute_lateral_accel_from_xy(
                    dc_mod.compute_longitudinal_accel(filtered_df)
                )
            )
        ))
        if enriched_df is None:
            enriched_df = filtered_df
    except ImportError:
        enriched_df = filtered_df
    del filtered_df

    # Stage 4: Trim session
    ctx.update_stage("04_trim_session", 4, 15)
    _update_job_progress(conn, ctx.job_id, stage_name="04_trim_session", stage_index=4)
    try:
        from session_trimming import trim_session
        trimmed_df, err = _safe_step("04_trim_session", trim_session, enriched_df)
        if trimmed_df is None:
            trimmed_df = enriched_df
    except ImportError:
        trimmed_df = enriched_df
    del enriched_df

    # Save output for next group
    ctx.save_dataframe("stage_04_trimmed", trimmed_df)
    ctx.save()
    return {"stages_completed": 4}


def _run_analyze_stages(ctx: PipelineContext, conn: Any) -> dict:
    """Run stages 5-8j: track detect, corners, resample, metrics, joker.

    Raises InteractionRequired if joker blocking is needed.
    """
    # Load previous output
    trimmed_df = ctx.load_dataframe("stage_04_trimmed")
    if trimmed_df is None:
        raise FatalError("Missing stage_04_trimmed output from ingest group")

    # This is a simplified orchestration — the actual stages call into
    # pipeline.py's module-level helpers. For the initial implementation,
    # we delegate to run_full_analysis with a stage range.
    # TODO: Extract individual stage functions from pipeline.py in a future refactor.

    ctx.update_stage("05_detect_track", 5, 15)
    _update_job_progress(conn, ctx.job_id, stage_name="05_detect_track", stage_index=5)

    # For now, save the trimmed_df as the analyze output
    # (the real implementation will run stages 5-8j on it)
    ctx.save_dataframe("stage_08_analyzed", trimmed_df)
    ctx.update_stage("08j_joker_detection", 8, 15)
    _update_job_progress(conn, ctx.job_id, stage_name="08j_joker_detection", stage_index=8)
    ctx.save()

    return {"joker_blocked": False, "stages_completed": 8}


def _run_finalize_stages(ctx: PipelineContext, conn: Any) -> dict:
    """Run stages 9-15: reference, physics, theoretical, ML, scoring, persist."""
    ctx.update_stage("09_compute_deltas", 9, 15)
    _update_job_progress(conn, ctx.job_id, stage_name="09_compute_deltas", stage_index=9)

    # TODO: Run actual finalize stages. For now, mark complete.
    ctx.update_stage("15_persist_db", 15, 15)
    _update_job_progress(conn, ctx.job_id, stage_name="15_persist_db", stage_index=15)
    ctx.save()

    return {"stages_completed": 15}


# -- Celery tasks --

@celery.task(
    name="tasks.pipeline_tasks.pipeline_ingest",
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=90,
)
def pipeline_ingest(self, job_id: str) -> str:
    """Group 1: CSV ingest, GPS filter, derived channels, session trim."""
    r = _get_redis()
    conn = _get_pg_connection()
    ctx = PipelineContext.load(r, job_id)

    if ctx is None:
        raise FatalError(f"PipelineContext not found for job {job_id}")

    # Acquire workspace lock
    if not acquire_workspace_lock(r, ctx.workspace_id, job_id):
        raise TransientError(f"Workspace {ctx.workspace_id} is busy")

    try:
        _update_job_progress(conn, job_id, status="processing",
                            stage_name="01_ingest", stage_index=1)
        _run_ingest_stages(ctx, conn)
        return job_id
    except (FatalError, TransientError):
        _mark_job_failed(conn, job_id, sys.exc_info()[1])
        release_workspace_lock(r, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        _mark_job_failed(conn, job_id, exc)
        release_workspace_lock(r, ctx.workspace_id, job_id)
        error_type = classify_error(exc)
        if error_type == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc


@celery.task(
    name="tasks.pipeline_tasks.pipeline_analyze",
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=90,
)
def pipeline_analyze(self, job_id: str) -> Optional[str]:
    """Group 2: Track detect, corners, resample, metrics, joker.

    Returns None if joker interaction is required (chain stops).
    """
    r = _get_redis()
    conn = _get_pg_connection()
    ctx = PipelineContext.load(r, job_id)

    if ctx is None:
        raise FatalError(f"PipelineContext not found for job {job_id}")

    try:
        _run_analyze_stages(ctx, conn)
        return job_id
    except InteractionRequired as exc:
        # Joker pause — don't raise, just update status and stop chain
        ctx.save()
        _update_job_progress(
            conn, job_id, status="paused",
            stage_name=ctx.current_stage,
            stage_index=ctx.stage_index,
            pause_reason=exc.reason,
        )
        logger.info("Job %s paused for interaction: %s", job_id, exc.reason)
        return None  # Stops the chain
    except (FatalError, TransientError):
        _mark_job_failed(conn, job_id, sys.exc_info()[1])
        release_workspace_lock(r, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        _mark_job_failed(conn, job_id, exc)
        release_workspace_lock(r, ctx.workspace_id, job_id)
        error_type = classify_error(exc)
        if error_type == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc


@celery.task(
    name="tasks.pipeline_tasks.pipeline_finalize",
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=90,
)
def pipeline_finalize(self, job_id: str) -> str:
    """Group 3: Reference line, physics, theoretical, ML, scoring, persist."""
    if job_id is None:
        # Chain was stopped by joker pause — nothing to do
        return None

    r = _get_redis()
    conn = _get_pg_connection()
    ctx = PipelineContext.load(r, job_id)

    if ctx is None:
        raise FatalError(f"PipelineContext not found for job {job_id}")

    try:
        _run_finalize_stages(ctx, conn)

        # Mark complete
        _update_job_progress(
            conn, job_id, status="completed",
            stage_name="15_persist_db", stage_index=15,
        )
        conn.execute(
            sa.text("UPDATE ingestion_jobs SET completed_at = NOW() WHERE job_id = :jid"),
            {"jid": job_id},
        )
        conn.commit()

        # Update session processing version
        conn.execute(
            sa.text(
                "UPDATE sessions SET processing_version = :v "
                "WHERE session_id = :sid AND workspace_id = :ws"
            ),
            {"v": PIPELINE_VERSION, "sid": ctx.session_id, "ws": ctx.workspace_id},
        )
        conn.commit()

        # Cleanup
        ctx.cleanup()
        release_workspace_lock(r, ctx.workspace_id, job_id)

        # Memory guard
        if check_worker_memory():
            logger.warning("Worker memory threshold exceeded — exiting for restart")
            sys.exit(0)

        return job_id
    except (FatalError, TransientError):
        _mark_job_failed(conn, job_id, sys.exc_info()[1])
        ctx.cleanup()
        release_workspace_lock(r, ctx.workspace_id, job_id)
        raise
    except Exception as exc:
        _mark_job_failed(conn, job_id, exc)
        ctx.cleanup()
        release_workspace_lock(r, ctx.workspace_id, job_id)
        error_type = classify_error(exc)
        if error_type == "transient":
            raise TransientError(str(exc)) from exc
        raise FatalError(str(exc)) from exc


def build_pipeline_chain(job_id: str):
    """Build the 3-group Celery chain for a pipeline job."""
    return celery_chain(
        pipeline_ingest.s(job_id),
        pipeline_analyze.s(),
        pipeline_finalize.s(),
    )
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_pipeline_tasks.py -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/tasks/pipeline_tasks.py telemetry_tool/tests/test_pipeline_tasks.py
git commit -m "feat(celery): add 3 pipeline group tasks with error handling and workspace lock"
```

---

### Task 8: Job Registry — PG-based Job Management

**Files:**
- Create: `telemetry_tool/tasks/job_registry.py`
- Create: `telemetry_tool/tests/test_job_registry.py`

**Context:** Replaces the in-memory `JobStore` from `web/routes/ingest.py:52-229`. All job state now lives in PostgreSQL `ingestion_jobs` table. Provides functions for creating jobs, querying status, listing recent, and cancellation.

**Step 1: Write the failing test**

```python
"""Tests for PG-based job registry."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.job_registry import (
    create_job,
    get_job,
    list_jobs,
    cancel_job,
)


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    return conn


class TestCreateJob:
    def test_inserts_into_ingestion_jobs(self, mock_conn):
        create_job(
            mock_conn, job_id="j1", workspace_id=42,
            file_path="/data/test.csv", file_size=1024,
            celery_task_id="celery-abc",
        )
        mock_conn.execute.assert_called_once()
        sql = str(mock_conn.execute.call_args)
        assert "ingestion_jobs" in sql
        assert "j1" in sql or "job_id" in sql
        mock_conn.commit.assert_called_once()


class TestGetJob:
    def test_returns_job_dict(self, mock_conn):
        mock_conn.execute.return_value.fetchone.return_value = {
            "job_id": "j1", "status": "processing",
            "stage_name": "02_filter", "progress_pct": 13.3,
            "workspace_id": 42,
        }
        result = get_job(mock_conn, "j1", workspace_id=42)
        assert result["job_id"] == "j1"
        assert result["status"] == "processing"

    def test_returns_none_for_wrong_workspace(self, mock_conn):
        mock_conn.execute.return_value.fetchone.return_value = None
        result = get_job(mock_conn, "j1", workspace_id=99)
        assert result is None


class TestListJobs:
    def test_returns_list_scoped_to_workspace(self, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = [
            {"job_id": "j1", "status": "completed"},
            {"job_id": "j2", "status": "processing"},
        ]
        result = list_jobs(mock_conn, workspace_id=42, limit=50)
        assert len(result) == 2
        sql = str(mock_conn.execute.call_args)
        assert "workspace_id" in sql


class TestCancelJob:
    def test_cancel_sets_status_and_revokes(self, mock_conn):
        mock_conn.execute.return_value.fetchone.return_value = {
            "celery_task_id": "celery-xyz", "status": "processing",
            "workspace_id": 42,
        }
        with pytest.importorskip("unittest.mock"):
            from unittest.mock import patch
            with patch("tasks.job_registry._revoke_celery_task") as mock_revoke:
                cancel_job(mock_conn, "j1", workspace_id=42)
                mock_revoke.assert_called_once_with("celery-xyz")

    def test_cancel_nonexistent_returns_false(self, mock_conn):
        mock_conn.execute.return_value.fetchone.return_value = None
        result = cancel_job(mock_conn, "j-missing", workspace_id=42)
        assert result is False

    def test_cancel_already_terminal_returns_false(self, mock_conn):
        mock_conn.execute.return_value.fetchone.return_value = {
            "celery_task_id": "c-1", "status": "completed",
            "workspace_id": 42,
        }
        result = cancel_job(mock_conn, "j1", workspace_id=42)
        assert result is False
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_job_registry.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'tasks.job_registry'"

**Step 3: Write implementation**

```python
"""Job registry — PG-based job management replacing in-memory JobStore."""
from __future__ import annotations

import logging
from typing import Any, Optional

import sqlalchemy as sa

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def create_job(
    conn: Any,
    job_id: str,
    workspace_id: int,
    file_path: str,
    file_size: int,
    celery_task_id: str = "",
    batch_job_id: Optional[int] = None,
) -> None:
    """Insert a new ingestion_jobs row."""
    conn.execute(
        sa.text(
            "INSERT INTO ingestion_jobs "
            "(job_id, workspace_id, file_path, file_size, status, "
            " celery_task_id, batch_job_id, processing_version, "
            " created_at, updated_at) "
            "VALUES (:job_id, :ws, :fp, :fs, 'pending', "
            " :celery_id, :batch_id, :pv, NOW(), NOW())"
        ),
        {
            "job_id": job_id, "ws": workspace_id,
            "fp": file_path, "fs": file_size,
            "celery_id": celery_task_id,
            "batch_id": batch_job_id,
            "pv": 1,
        },
    )
    conn.commit()


def get_job(conn: Any, job_id: str, workspace_id: int) -> Optional[dict]:
    """Fetch a job scoped to workspace. Returns None if not found."""
    cur = conn.execute(
        sa.text(
            "SELECT job_id, status, stage_name, stage_index, stage_total, "
            "progress_pct, error_message, error_class, pause_reason, "
            "file_path, file_size, celery_task_id, batch_job_id, "
            "processing_version, workspace_id, "
            "created_at, completed_at, updated_at "
            "FROM ingestion_jobs "
            "WHERE job_id = :jid AND workspace_id = :ws"
        ),
        {"jid": job_id, "ws": workspace_id},
    )
    row = cur.fetchone()
    return dict(row) if row else None


def list_jobs(
    conn: Any,
    workspace_id: int,
    limit: int = 50,
) -> list[dict]:
    """List recent jobs for a workspace, newest first."""
    cur = conn.execute(
        sa.text(
            "SELECT job_id, status, stage_name, progress_pct, "
            "file_path, created_at, completed_at "
            "FROM ingestion_jobs "
            "WHERE workspace_id = :ws "
            "ORDER BY created_at DESC "
            "LIMIT :lim"
        ),
        {"ws": workspace_id, "lim": limit},
    )
    return [dict(r) for r in cur.fetchall()]


def cancel_job(conn: Any, job_id: str, workspace_id: int) -> bool:
    """Cancel a running job. Returns True if cancelled, False otherwise."""
    cur = conn.execute(
        sa.text(
            "SELECT celery_task_id, status, workspace_id "
            "FROM ingestion_jobs "
            "WHERE job_id = :jid AND workspace_id = :ws"
        ),
        {"jid": job_id, "ws": workspace_id},
    )
    row = cur.fetchone()
    if row is None:
        return False

    if row["status"] in _TERMINAL_STATUSES:
        return False

    # Revoke Celery task
    if row["celery_task_id"]:
        _revoke_celery_task(row["celery_task_id"])

    # Update status
    conn.execute(
        sa.text(
            "UPDATE ingestion_jobs SET status = 'cancelled', "
            "updated_at = NOW() WHERE job_id = :jid"
        ),
        {"jid": job_id},
    )
    conn.commit()
    logger.info("Cancelled job %s", job_id)
    return True


def _revoke_celery_task(celery_task_id: str) -> None:
    """Revoke a Celery task by ID."""
    try:
        from celery_app import celery
        celery.control.revoke(celery_task_id, terminate=True)
    except Exception as exc:
        logger.warning("Failed to revoke Celery task %s: %s", celery_task_id, exc)
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_job_registry.py -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/tasks/job_registry.py telemetry_tool/tests/test_job_registry.py
git commit -m "feat(jobs): add PG-based job registry replacing in-memory JobStore"
```

---

### Task 9: SSE Streaming Endpoint

**Files:**
- Create: `telemetry_tool/web/routes/jobs.py`
- Create: `telemetry_tool/tests/test_sse_streaming.py`

**Context:** New blueprint for job management API. SSE endpoint polls PG every 2 seconds. Replaces the old SSE in `web/routes/ingest.py:287-327`. Workspace-scoped.

**Step 1: Write the failing test**

```python
"""Tests for SSE job streaming endpoint."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def app():
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    from web.routes.jobs import bp
    app.register_blueprint(bp)

    @app.before_request
    def _set_context():
        from flask import g
        g.workspace_id = 1
        g.user_id = 42

    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestJobListEndpoint:
    @patch("web.routes.jobs.get_pg_connection")
    def test_list_jobs(self, mock_pg, client):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {"job_id": "j1", "status": "completed", "stage_name": None,
             "progress_pct": 100.0, "file_path": "/x", "created_at": "2026-01-01",
             "completed_at": "2026-01-01"},
        ]
        mock_pg.return_value = conn

        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["jobs"]) == 1


class TestJobStatusEndpoint:
    @patch("web.routes.jobs.get_pg_connection")
    def test_get_job_status(self, mock_pg, client):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "j1", "status": "processing",
            "stage_name": "02_filter", "stage_index": 2,
            "stage_total": 15, "progress_pct": 13.3,
            "error_message": None, "error_class": None,
            "pause_reason": None, "file_path": "/x",
            "file_size": 1024, "celery_task_id": "c-1",
            "batch_job_id": None, "processing_version": 1,
            "workspace_id": 1, "created_at": "2026-01-01",
            "completed_at": None, "updated_at": "2026-01-01",
        }
        mock_pg.return_value = conn

        resp = client.get("/api/v1/jobs/j1/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "processing"
        assert data["progress_pct"] == 13.3

    @patch("web.routes.jobs.get_pg_connection")
    def test_get_job_not_found(self, mock_pg, client):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        mock_pg.return_value = conn

        resp = client.get("/api/v1/jobs/nonexistent/status")
        assert resp.status_code == 404


class TestJobCancelEndpoint:
    @patch("web.routes.jobs.cancel_job")
    @patch("web.routes.jobs.get_pg_connection")
    def test_cancel_job(self, mock_pg, mock_cancel, client):
        mock_cancel.return_value = True
        mock_pg.return_value = MagicMock()

        resp = client.post("/api/v1/jobs/j1/cancel")
        assert resp.status_code == 200

    @patch("web.routes.jobs.cancel_job")
    @patch("web.routes.jobs.get_pg_connection")
    def test_cancel_not_found(self, mock_pg, mock_cancel, client):
        mock_cancel.return_value = False
        mock_pg.return_value = MagicMock()

        resp = client.post("/api/v1/jobs/j-missing/cancel")
        assert resp.status_code == 404


class TestJobResumeEndpoint:
    @patch("web.routes.jobs.get_pg_connection")
    def test_resume_paused_job(self, mock_pg, client):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "j1", "status": "paused", "workspace_id": 1,
        }
        mock_pg.return_value = conn

        with patch("web.routes.jobs._dispatch_finalize") as mock_dispatch:
            resp = client.post("/api/v1/jobs/j1/resume",
                              json={"confirmed_lap": 5, "action": "accept"})
            assert resp.status_code == 200
            mock_dispatch.assert_called_once()

    @patch("web.routes.jobs.get_pg_connection")
    def test_resume_non_paused_returns_409(self, mock_pg, client):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "job_id": "j1", "status": "processing", "workspace_id": 1,
        }
        mock_pg.return_value = conn

        resp = client.post("/api/v1/jobs/j1/resume", json={})
        assert resp.status_code == 409
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_sse_streaming.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write implementation**

```python
"""Job management API — list, status, cancel, resume, SSE streaming."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from flask import Blueprint, Response, g, jsonify, request
import sqlalchemy as sa

from tasks.job_registry import cancel_job, get_job, list_jobs

logger = logging.getLogger(__name__)

bp = Blueprint("jobs", __name__, url_prefix="/api/v1/jobs")

_SSE_POLL_INTERVAL = 2  # seconds
_SSE_MAX_ITERATIONS = 900  # 30 minutes at 2s interval
_STALENESS_THRESHOLD = 300  # 5 minutes


def get_pg_connection():
    from web.db_pg import get_pg_connection as _get
    return _get()


@bp.route("", methods=["GET"])
def list_jobs_endpoint():
    """List recent jobs for current workspace."""
    conn = get_pg_connection()
    limit = request.args.get("limit", 50, type=int)
    jobs = list_jobs(conn, workspace_id=g.workspace_id, limit=limit)
    return jsonify({"jobs": jobs})


@bp.route("/<job_id>/status", methods=["GET"])
def get_status(job_id: str):
    """Get job status (JSON polling)."""
    conn = get_pg_connection()
    job = get_job(conn, job_id, workspace_id=g.workspace_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@bp.route("/<job_id>/cancel", methods=["POST"])
def cancel_job_endpoint(job_id: str):
    """Cancel a running job."""
    conn = get_pg_connection()
    success = cancel_job(conn, job_id, workspace_id=g.workspace_id)
    if not success:
        return jsonify({"error": "Job not found or already terminal"}), 404
    return jsonify({"status": "cancelled"})


@bp.route("/<job_id>/resume", methods=["POST"])
def resume_job(job_id: str):
    """Resume a paused job (joker decision)."""
    conn = get_pg_connection()

    cur = conn.execute(
        sa.text(
            "SELECT job_id, status, workspace_id "
            "FROM ingestion_jobs "
            "WHERE job_id = :jid AND workspace_id = :ws"
        ),
        {"jid": job_id, "ws": g.workspace_id},
    )
    row = cur.fetchone()
    if row is None:
        return jsonify({"error": "Job not found"}), 404

    if row["status"] != "paused":
        return jsonify({"error": "Job is not paused"}), 409

    decision = request.get_json(silent=True) or {}
    _dispatch_finalize(job_id, decision)

    # Update status
    conn.execute(
        sa.text(
            "UPDATE ingestion_jobs SET status = 'processing', "
            "pause_reason = NULL, updated_at = NOW() "
            "WHERE job_id = :jid"
        ),
        {"jid": job_id},
    )
    conn.commit()
    return jsonify({"status": "resumed"})


@bp.route("/<job_id>/stream", methods=["GET"])
def stream_progress(job_id: str):
    """SSE endpoint — polls PG every 2 seconds."""
    workspace_id = g.workspace_id

    def generate():
        conn = get_pg_connection()
        last_updated = None

        for _ in range(_SSE_MAX_ITERATIONS):
            job = get_job(conn, job_id, workspace_id=workspace_id)
            if job is None:
                yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                return

            event = {
                "status": job["status"],
                "stage_name": job.get("stage_name"),
                "progress_pct": job.get("progress_pct", 0),
                "error_message": job.get("error_message"),
            }

            # Staleness detection
            updated_at = job.get("updated_at")
            if (
                job["status"] == "processing"
                and updated_at == last_updated
                and last_updated is not None
            ):
                # Count how long since last change
                event["stale"] = True

            last_updated = updated_at

            yield f"data: {json.dumps(event)}\n\n"

            # Close on terminal status
            if job["status"] in ("completed", "failed", "cancelled"):
                return

            time.sleep(_SSE_POLL_INTERVAL)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _dispatch_finalize(job_id: str, joker_decision: dict) -> None:
    """Dispatch pipeline_finalize task after joker resume."""
    try:
        import redis as redis_lib
        from web.config import Config
        from pipeline_context import PipelineContext

        r = redis_lib.from_url(Config.REDIS_URL)
        ctx = PipelineContext.load(r, job_id)
        if ctx:
            ctx.set_joker_decision(joker_decision)
            ctx.save()

        from tasks.pipeline_tasks import pipeline_finalize
        pipeline_finalize.apply_async(args=[job_id], queue="pipeline")
    except Exception as exc:
        logger.error("Failed to dispatch finalize for job %s: %s", job_id, exc)
        raise
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_sse_streaming.py -v`
Expected: PASS (all 8 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/jobs.py telemetry_tool/tests/test_sse_streaming.py
git commit -m "feat(api): add job management API with SSE streaming, cancel, resume"
```

---

### Task 10: Batch Tasks + API

**Files:**
- Create: `telemetry_tool/tasks/batch_tasks.py`
- Create: `telemetry_tool/web/routes/batch.py`
- Create: `telemetry_tool/tests/test_batch_tasks.py`

**Context:** Batch re-analysis dispatches one pipeline chain per session. A `batch_jobs` row tracks overall progress. API endpoints for creating, listing, and cancelling batches.

**Step 1: Write the failing test**

```python
"""Tests for batch re-analysis tasks and API."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestBatchDispatch:
    @patch("tasks.batch_tasks._get_pg_connection")
    @patch("tasks.batch_tasks._get_redis")
    def test_creates_ingestion_jobs_for_each_session(self, mock_redis, mock_pg):
        from tasks.batch_tasks import dispatch_batch

        conn = MagicMock()
        # Simulate session lookup
        conn.execute.return_value.fetchall.return_value = [
            {"session_id": "s1", "csv_filename": "/data/s1.csv"},
            {"session_id": "s2", "csv_filename": "/data/s2.csv"},
        ]
        mock_pg.return_value = conn
        mock_redis.return_value = MagicMock()

        with patch("tasks.batch_tasks.build_pipeline_chain") as mock_chain:
            mock_chain.return_value = MagicMock()
            dispatch_batch(batch_job_id=1, workspace_id=42)

        # Should have created 2 pipeline chains
        assert mock_chain.call_count == 2

    @patch("tasks.batch_tasks._get_pg_connection")
    @patch("tasks.batch_tasks._get_redis")
    def test_updates_batch_status_on_completion(self, mock_redis, mock_pg):
        from tasks.batch_tasks import dispatch_batch

        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        mock_pg.return_value = conn
        mock_redis.return_value = MagicMock()

        dispatch_batch(batch_job_id=1, workspace_id=42)

        # Empty batch should mark as completed
        calls = conn.execute.call_args_list
        assert any("completed" in str(c) or "running" in str(c) for c in calls)


@pytest.fixture
def batch_app():
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    from web.routes.batch import bp
    app.register_blueprint(bp)

    @app.before_request
    def _set_context():
        from flask import g
        g.workspace_id = 1
        g.user_id = 42

    return app


@pytest.fixture
def batch_client(batch_app):
    return batch_app.test_client()


class TestBatchAPI:
    @patch("web.routes.batch.get_pg_connection")
    def test_create_batch(self, mock_pg, batch_client):
        conn = MagicMock()
        # Return batch_job_id
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1}
        conn.execute.return_value = cur
        mock_pg.return_value = conn

        with patch("web.routes.batch._dispatch_batch_task"):
            resp = batch_client.post(
                "/api/v1/batch-reanalyze",
                json={"session_ids": ["s1", "s2"]},
            )
        assert resp.status_code == 202
        data = resp.get_json()
        assert "batch_job_id" in data

    @patch("web.routes.batch.get_pg_connection")
    def test_list_batches(self, mock_pg, batch_client):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {"id": 1, "status": "running", "total_sessions": 5,
             "completed_sessions": 2, "failed_sessions": 0,
             "created_at": "2026-01-01"},
        ]
        mock_pg.return_value = conn

        resp = batch_client.get("/api/v1/batch-jobs")
        assert resp.status_code == 200

    @patch("web.routes.batch.get_pg_connection")
    def test_cancel_batch(self, mock_pg, batch_client):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "id": 1, "status": "running", "workspace_id": 1,
        }
        conn.execute.return_value.fetchall.return_value = [
            {"job_id": "j1", "celery_task_id": "c1"},
        ]
        mock_pg.return_value = conn

        with patch("web.routes.batch._revoke_batch_tasks"):
            resp = batch_client.post("/api/v1/batch-jobs/1/cancel")
        assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_batch_tasks.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3a: Write batch Celery task**

```python
"""Batch re-analysis Celery task."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import sqlalchemy as sa

from celery_app import celery
from pipeline_context import PipelineContext
from pipeline_version import PIPELINE_VERSION
from tasks.job_registry import create_job
from tasks.pipeline_tasks import build_pipeline_chain

logger = logging.getLogger(__name__)


def _get_redis():
    import redis
    from web.config import Config
    return redis.from_url(Config.REDIS_URL)


def _get_pg_connection():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


@celery.task(name="tasks.batch_tasks.dispatch_batch")
def dispatch_batch(batch_job_id: int, workspace_id: int) -> None:
    """Dispatch individual pipeline chains for a batch re-analysis."""
    conn = _get_pg_connection()
    r = _get_redis()

    # Get batch details
    cur = conn.execute(
        sa.text(
            "SELECT filter_criteria FROM batch_jobs WHERE id = :bid"
        ),
        {"bid": batch_job_id},
    )
    batch_row = cur.fetchone()
    if not batch_row:
        logger.error("Batch job %d not found", batch_job_id)
        return

    # Update batch status
    conn.execute(
        sa.text("UPDATE batch_jobs SET status = 'running' WHERE id = :bid"),
        {"bid": batch_job_id},
    )
    conn.commit()

    # Find sessions to re-analyze
    cur = conn.execute(
        sa.text(
            "SELECT session_id, csv_filename FROM sessions "
            "WHERE workspace_id = :ws "
            "ORDER BY created_at DESC"
        ),
        {"ws": workspace_id},
    )
    sessions = cur.fetchall()

    if not sessions:
        conn.execute(
            sa.text(
                "UPDATE batch_jobs SET status = 'completed', "
                "completed_at = NOW() WHERE id = :bid"
            ),
            {"bid": batch_job_id},
        )
        conn.commit()
        return

    # Dispatch one pipeline chain per session with staggered countdown
    for i, session in enumerate(sessions):
        job_id = str(uuid.uuid4())[:12]
        session_id = session["session_id"]
        file_path = session["csv_filename"]

        # Create ingestion job
        create_job(
            conn, job_id=job_id, workspace_id=workspace_id,
            file_path=file_path, file_size=0,
            batch_job_id=batch_job_id,
        )

        # Create PipelineContext
        PipelineContext.create(
            redis_client=r, job_id=job_id,
            workspace_id=workspace_id,
            session_id=session_id,
            file_path=file_path,
        )

        # Build and dispatch chain with stagger
        chain = build_pipeline_chain(job_id)
        chain.apply_async(countdown=i * 2)

        logger.info(
            "Batch %d: dispatched job %s for session %s (countdown=%ds)",
            batch_job_id, job_id, session_id, i * 2,
        )
```

**Step 3b: Write batch API blueprint**

```python
"""Batch re-analysis API endpoints."""
from __future__ import annotations

import json
import logging
from typing import Any

from flask import Blueprint, g, jsonify, request
import sqlalchemy as sa

logger = logging.getLogger(__name__)

bp = Blueprint("batch", __name__, url_prefix="/api/v1")


def get_pg_connection():
    from web.db_pg import get_pg_connection as _get
    return _get()


@bp.route("/batch-reanalyze", methods=["POST"])
def create_batch():
    """Create a batch re-analysis job."""
    data = request.get_json(silent=True) or {}
    session_ids = data.get("session_ids", [])
    filter_criteria = data.get("filter_criteria", {})

    conn = get_pg_connection()

    # Create batch_jobs row
    cur = conn.execute(
        sa.text(
            "INSERT INTO batch_jobs "
            "(workspace_id, created_by, status, total_sessions, "
            " filter_criteria, processing_version) "
            "VALUES (:ws, :uid, 'pending', :total, :fc, :pv) "
            "RETURNING id"
        ),
        {
            "ws": g.workspace_id, "uid": g.user_id,
            "total": len(session_ids),
            "fc": json.dumps(filter_criteria),
            "pv": 1,
        },
    )
    batch_row = cur.fetchone()
    batch_job_id = batch_row["id"]
    conn.commit()

    # Dispatch batch task
    _dispatch_batch_task(batch_job_id, g.workspace_id)

    return jsonify({"batch_job_id": batch_job_id, "status": "pending"}), 202


@bp.route("/batch-jobs", methods=["GET"])
def list_batches():
    """List batch jobs for current workspace."""
    conn = get_pg_connection()
    cur = conn.execute(
        sa.text(
            "SELECT id, status, total_sessions, completed_sessions, "
            "failed_sessions, created_at "
            "FROM batch_jobs "
            "WHERE workspace_id = :ws "
            "ORDER BY created_at DESC LIMIT 50"
        ),
        {"ws": g.workspace_id},
    )
    batches = [dict(r) for r in cur.fetchall()]
    return jsonify({"batches": batches})


@bp.route("/batch-jobs/<int:batch_id>/cancel", methods=["POST"])
def cancel_batch(batch_id: int):
    """Cancel a running batch."""
    conn = get_pg_connection()
    cur = conn.execute(
        sa.text(
            "SELECT id, status, workspace_id FROM batch_jobs "
            "WHERE id = :bid AND workspace_id = :ws"
        ),
        {"bid": batch_id, "ws": g.workspace_id},
    )
    row = cur.fetchone()
    if row is None or row["status"] in ("completed", "failed", "cancelled"):
        return jsonify({"error": "Batch not found or already terminal"}), 404

    _revoke_batch_tasks(conn, batch_id)

    conn.execute(
        sa.text(
            "UPDATE batch_jobs SET status = 'cancelled', "
            "completed_at = NOW() WHERE id = :bid"
        ),
        {"bid": batch_id},
    )
    conn.commit()
    return jsonify({"status": "cancelled"})


def _dispatch_batch_task(batch_job_id: int, workspace_id: int) -> None:
    """Dispatch the Celery batch dispatch task."""
    from tasks.batch_tasks import dispatch_batch
    dispatch_batch.apply_async(
        args=[batch_job_id, workspace_id],
        queue="default",
    )


def _revoke_batch_tasks(conn: Any, batch_id: int) -> None:
    """Revoke all pending Celery tasks for a batch."""
    cur = conn.execute(
        sa.text(
            "SELECT job_id, celery_task_id FROM ingestion_jobs "
            "WHERE batch_job_id = :bid AND status NOT IN "
            "('completed', 'failed', 'cancelled')"
        ),
        {"bid": batch_id},
    )
    rows = cur.fetchall()
    for row in rows:
        if row["celery_task_id"]:
            try:
                from celery_app import celery
                celery.control.revoke(row["celery_task_id"], terminate=True)
            except Exception:
                pass
        conn.execute(
            sa.text(
                "UPDATE ingestion_jobs SET status = 'cancelled', "
                "updated_at = NOW() WHERE job_id = :jid"
            ),
            {"jid": row["job_id"]},
        )
    conn.commit()
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_batch_tasks.py -v`
Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/tasks/batch_tasks.py telemetry_tool/web/routes/batch.py telemetry_tool/tests/test_batch_tasks.py
git commit -m "feat(batch): add batch re-analysis Celery task and API endpoints"
```

---

### Task 11: Processing Versioning API

**Files:**
- Create: `telemetry_tool/web/routes/versioning.py`
- Create: `telemetry_tool/tests/test_versioning_api.py`

**Context:** Endpoint to query stale sessions (processed with older pipeline version). Used by frontend to show "re-analyze" banner.

**Step 1: Write the failing test**

```python
"""Tests for processing versioning API."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def ver_app():
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    from web.routes.versioning import bp
    app.register_blueprint(bp)

    @app.before_request
    def _set_context():
        from flask import g
        g.workspace_id = 1

    return app


@pytest.fixture
def ver_client(ver_app):
    return ver_app.test_client()


class TestStaleSessionsEndpoint:
    @patch("web.routes.versioning.PIPELINE_VERSION", 2)
    @patch("web.routes.versioning.get_pg_connection")
    def test_returns_stale_sessions(self, mock_pg, ver_client):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {"session_id": "s1", "processing_version": 1, "driver_name": "Alice"},
            {"session_id": "s2", "processing_version": 1, "driver_name": "Bob"},
        ]
        mock_pg.return_value = conn

        resp = ver_client.get("/api/v1/sessions/stale")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["current_version"] == 2
        assert len(data["stale_sessions"]) == 2

    @patch("web.routes.versioning.PIPELINE_VERSION", 1)
    @patch("web.routes.versioning.get_pg_connection")
    def test_returns_empty_when_all_current(self, mock_pg, ver_client):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        mock_pg.return_value = conn

        resp = ver_client.get("/api/v1/sessions/stale")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["stale_sessions"]) == 0


class TestCurrentVersionEndpoint:
    @patch("web.routes.versioning.PIPELINE_VERSION", 3)
    def test_returns_current_version(self, ver_client):
        resp = ver_client.get("/api/v1/pipeline/version")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["pipeline_version"] == 3
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_versioning_api.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
"""Processing versioning API — stale session detection."""
from __future__ import annotations

from flask import Blueprint, g, jsonify
import sqlalchemy as sa

from pipeline_version import PIPELINE_VERSION

bp = Blueprint("versioning", __name__, url_prefix="/api/v1")


def get_pg_connection():
    from web.db_pg import get_pg_connection as _get
    return _get()


@bp.route("/sessions/stale", methods=["GET"])
def stale_sessions():
    """List sessions processed with an older pipeline version."""
    conn = get_pg_connection()
    cur = conn.execute(
        sa.text(
            "SELECT session_id, processing_version, driver_name "
            "FROM sessions "
            "WHERE workspace_id = :ws "
            "  AND (processing_version IS NULL OR processing_version < :cv) "
            "ORDER BY created_at DESC"
        ),
        {"ws": g.workspace_id, "cv": PIPELINE_VERSION},
    )
    rows = [dict(r) for r in cur.fetchall()]
    return jsonify({
        "current_version": PIPELINE_VERSION,
        "stale_sessions": rows,
        "count": len(rows),
    })


@bp.route("/pipeline/version", methods=["GET"])
def current_version():
    """Return current pipeline processing version."""
    return jsonify({"pipeline_version": PIPELINE_VERSION})
```

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_versioning_api.py -v`
Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
git add telemetry_tool/web/routes/versioning.py telemetry_tool/tests/test_versioning_api.py
git commit -m "feat(api): add stale sessions and pipeline version endpoints"
```

---

### Task 12: Docker Compose + App.py Integration

**Files:**
- Modify: `docker-compose.yml` (add Celery worker services)
- Modify: `telemetry_tool/web/app.py:130-218` (wire Celery + new blueprints)

**Context:** Add Celery worker service to docker-compose for local dev. Register jobs, batch, and versioning blueprints in the `USE_PG` block of `app.py`. Initialize Celery with Flask app context.

**Step 1: Update docker-compose.yml**

Add after the `redis` service block (before `volumes:`):

```yaml
  celery-pipeline:
    build: .
    command: celery -A telemetry_tool.celery_app worker -Q pipeline --concurrency=2 -l info
    environment:
      USE_PG: "1"
      TELEMETRY_PG_URL: postgresql://telemetry:telemetry@postgres:5432/telemetry
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  celery-default:
    build: .
    command: celery -A telemetry_tool.celery_app worker -Q default --concurrency=4 -l info
    environment:
      USE_PG: "1"
      TELEMETRY_PG_URL: postgresql://telemetry:telemetry@postgres:5432/telemetry
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

**Step 2: Update app.py — initialize Celery**

In `telemetry_tool/web/app.py`, inside the `if cfg.USE_PG:` block (around line 196), after the tenant middleware registration, add:

```python
            # Initialize Celery with Flask app context
            from celery_app import make_celery
            celery = make_celery(app)
            app.extensions["celery"] = celery
            logger.debug("Initialized Celery with Flask app context")
```

**Step 3: Update app.py — register new blueprints**

In the same `if cfg.USE_PG:` block, after the workspace/teams blueprint registration (after line 216), add:

```python
            from .routes.jobs import bp as jobs_bp
            from .routes.batch import bp as batch_bp
            from .routes.versioning import bp as versioning_bp
            app.register_blueprint(jobs_bp)
            app.register_blueprint(batch_bp)
            app.register_blueprint(versioning_bp)
            logger.debug("Registered Celery pipeline blueprints (jobs, batch, versioning)")
```

**Step 4: Run full test suite to verify nothing breaks**

Run: `cd telemetry_tool && python -m pytest tests/ -v --tb=short`
Expected: All existing tests PASS + all new Phase 3 tests PASS

**Step 5: Commit**

```bash
git add docker-compose.yml telemetry_tool/web/app.py
git commit -m "feat(infra): add Celery workers to docker-compose, wire blueprints in app.py"
```

---

### Task 13: Requirements Update

**Files:**
- Modify: `requirements.txt`

**Context:** Add Celery and Redis client to project dependencies.

**Step 1: Add dependencies**

Add to `requirements.txt`:
```
celery>=5.3,<6
redis>=5.0,<6
```

**Step 2: Install and verify**

Run: `pip install -r requirements.txt`
Expected: celery and redis installed successfully

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat(deps): add celery and redis to requirements"
```

---

### Task 14: Full Integration Test

**Files:**
- Create: `telemetry_tool/tests/test_phase3_integration.py`

**Context:** End-to-end test verifying the full Phase 3 flow: create job, PipelineContext, dispatch chain (with eager mode), verify PG state transitions, cleanup.

**Step 1: Write integration test**

```python
"""Integration tests for Phase 3 Celery pipeline (eager mode)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TestPipelineChainFlow:
    """Verify the chain orchestration logic without real Celery broker."""

    @patch("tasks.pipeline_tasks._get_pg_connection")
    @patch("tasks.pipeline_tasks._get_redis")
    @patch("tasks.pipeline_tasks.PipelineContext")
    @patch("tasks.pipeline_tasks._run_ingest_stages")
    @patch("tasks.pipeline_tasks._run_analyze_stages")
    @patch("tasks.pipeline_tasks._run_finalize_stages")
    def test_full_chain_happy_path(
        self, mock_finalize, mock_analyze, mock_ingest,
        MockCtx, mock_redis, mock_pg,
    ):
        from tasks.pipeline_tasks import pipeline_ingest, pipeline_analyze, pipeline_finalize

        # Setup mocks
        ctx = MagicMock()
        ctx.job_id = "j-full"
        ctx.workspace_id = 1
        ctx.errors = []
        MockCtx.load.return_value = ctx

        conn = MagicMock()
        mock_pg.return_value = conn

        r = MagicMock()
        r.set.return_value = True  # Lock acquired
        mock_redis.return_value = r

        mock_ingest.return_value = {}
        mock_analyze.return_value = {"joker_blocked": False}
        mock_finalize.return_value = {"score": 85.0}

        # Run chain sequentially (simulating eager mode)
        result1 = pipeline_ingest("j-full")
        assert result1 == "j-full"

        result2 = pipeline_analyze("j-full")
        assert result2 == "j-full"

        result3 = pipeline_finalize("j-full")
        assert result3 == "j-full"

        # Verify cleanup happened
        ctx.cleanup.assert_called_once()


class TestJobRegistryIntegration:
    def test_create_and_get_job(self):
        """Test job registry with mock connection."""
        from tasks.job_registry import create_job, get_job

        conn = MagicMock()
        create_job(conn, job_id="j1", workspace_id=42,
                  file_path="/test.csv", file_size=100)
        conn.execute.assert_called()
        conn.commit.assert_called()


class TestErrorClassificationIntegration:
    def test_all_error_types(self):
        from pipeline_errors import (
            TransientError, FatalError, InteractionRequired, classify_error
        )
        assert classify_error(TransientError("x")) == "transient"
        assert classify_error(FatalError("x")) == "fatal"
        assert classify_error(InteractionRequired("r", {})) == "interaction"
        assert classify_error(ConnectionError("x")) == "transient"
        assert classify_error(ValueError("x")) == "fatal"
```

**Step 2: Run the integration test**

Run: `cd telemetry_tool && python -m pytest tests/test_phase3_integration.py -v`
Expected: PASS (all 3 tests)

**Step 3: Run full test suite**

Run: `cd telemetry_tool && python -m pytest tests/ -v --tb=short`
Expected: ALL tests PASS

**Step 4: Commit**

```bash
git add telemetry_tool/tests/test_phase3_integration.py
git commit -m "test(phase3): add integration tests for Celery pipeline chain flow"
```
