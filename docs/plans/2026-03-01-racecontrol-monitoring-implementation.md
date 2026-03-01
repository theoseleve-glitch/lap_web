# RaceControl Monitoring — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Training Status (full control) and User Resources (storage + compute time series) panels to the Race Control admin dashboard.

**Architecture:** Two new backend blueprints (`training.py`, `monitoring.py`) under the existing admin package serve JSON APIs. Two new frontend pages under `race-control/monitoring/` display the data using the existing `MetricCard`, `AdminTable`, `ActionButton`, and `StatusBadge` components. Training config stored in Redis, audit manifests read from disk.

**Tech Stack:** Python Flask (backend), TypeScript Next.js 14 (frontend), TanStack React Query 5, Tailwind CSS, Redis, PostgreSQL 16

---

## Context for the Implementer

### Key Files You Need to Know

| File | Purpose |
|------|---------|
| `telemetry_tool/web/routes/admin/__init__.py` | Registers all admin sub-blueprints. Add new ones here. |
| `telemetry_tool/web/routes/admin/middleware.py` | `require_superadmin` + `require_admin_role()` decorators. |
| `telemetry_tool/web/routes/admin/infra.py` | Reference pattern for admin routes (storage, maintenance). |
| `telemetry_tool/tasks/training_tasks.py` | The weekly training task. Reads config, saves audit manifests. |
| `lap-website/src/lib/admin-api.ts` | Frontend admin API client. `adminApi` object with typed methods. |
| `lap-website/src/app/app/race-control/layout.tsx` | Sidebar nav. `navGroups` array defines sections + items. |
| `lap-website/src/components/admin/MetricCard.tsx` | `MetricCard` — label, value, sub, status. |
| `lap-website/src/components/admin/AdminTable.tsx` | `AdminTable<T>` — columns, data, onRowClick, emptyMessage. |
| `lap-website/src/components/admin/ActionButton.tsx` | `ActionButton` — label, onConfirm(reason), variant, requireReason. |
| `lap-website/src/components/admin/StatusBadge.tsx` | `StatusBadge` — status string → colored pill. |

### Pattern Notes

- **Backend admin routes**: `Blueprint("admin_xxx", __name__)`, routes start with `/admin/xxx/...`, decorated with `@require_superadmin` then `@require_admin_role("root_admin", "sre_admin")`.
- **DB access**: `_get_conn()` returns PG connection via `web.db_pg.get_pg_connection()`. SQL uses `%(name)s` params (compat layer).
- **Redis**: `_get_redis()` returns Redis client from `Config.REDIS_URL`.
- **API responses**: `api_response(data)` and `api_error(ErrorCode.XXX, "msg", status=NNN)`.
- **Frontend API**: `api.get<T>(path)` and `api.post<T>(path, body)` return typed data.
- **Frontend pages**: `useQuery` for reads with `refetchInterval`, `useMutation` for writes.
- **Audit**: `from admin.audit import log_admin_action; log_admin_action(conn, admin_user_id, action, details)`.

---

### Task 1: Backend — Training Admin Blueprint

**Files:**
- Create: `telemetry_tool/web/routes/admin/training.py`
- Modify: `telemetry_tool/web/routes/admin/__init__.py`
- Test: `telemetry_tool/tests/test_admin_training.py` (new)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_admin_training.py`:

```python
"""Tests for the training admin blueprint."""
from unittest.mock import MagicMock, patch, mock_open
import json
import pytest


@pytest.fixture
def mock_admin_user():
    """Mock g.admin_user for superadmin access."""
    return {
        "is_superadmin": True,
        "admin_role": "root_admin",
        "totp_enabled": True,
    }


class TestTrainingStatus:
    def test_returns_never_run_when_no_manifests(self, mock_admin_user):
        """GET /admin/training/status returns never_run when no audit files."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        with patch("web.routes.admin.training._list_audit_manifests", return_value=[]), \
             patch("web.routes.admin.training.g") as mock_g:
            mock_g.admin_user = mock_admin_user
            mock_g.admin_verified = True
            mock_g.current_user_id = 1
            from web.routes.admin.training import _get_training_status
            result = _get_training_status()
            assert result["status"] == "never_run"
            assert result["last_run"] is None

    def test_returns_latest_manifest_data(self, mock_admin_user):
        """GET /admin/training/status returns data from the latest audit manifest."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        manifest = {
            "started_at": "2026-03-01T00:00:00+00:00",
            "completed_at": "2026-03-01T00:05:30+00:00",
            "elapsed_s": 330.0,
            "tiers": {
                "envelopes": {"trained": 3, "skipped": 1, "errors": []},
                "global_model": {"status": "ok"},
                "reprocess": {"succeeded": 10, "failed": 2, "errors": []},
            },
        }

        with patch("web.routes.admin.training._list_audit_manifests",
                    return_value=["/data/models/kart_envelope/audit/training_20260301.json"]), \
             patch("builtins.open", mock_open(read_data=json.dumps(manifest))):
            from web.routes.admin.training import _get_training_status
            result = _get_training_status()
            assert result["status"] == "completed"
            assert result["last_run"]["elapsed_s"] == 330.0
            assert result["last_run"]["tiers"]["envelopes"]["trained"] == 3


class TestTrainingConfig:
    def test_returns_defaults_when_redis_empty(self):
        """GET /admin/training/config returns defaults when Redis has no config."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {}

        with patch("web.routes.admin.training._get_redis", return_value=mock_redis):
            from web.routes.admin.training import _get_training_config
            config = _get_training_config()
            assert config["min_sessions_per_group"] == 3
            assert config["schedule_day_of_week"] == 0

    def test_returns_redis_overrides(self):
        """GET /admin/training/config returns Redis values over defaults."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "min_sessions_per_group": "5",
            "reprocess_pause_s": "30",
        }

        with patch("web.routes.admin.training._get_redis", return_value=mock_redis):
            from web.routes.admin.training import _get_training_config
            config = _get_training_config()
            assert config["min_sessions_per_group"] == 5
            assert config["reprocess_pause_s"] == 30


class TestTrainingTrigger:
    def test_dispatches_celery_task(self):
        """POST /admin/training/trigger dispatches the weekly task."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        with patch("web.routes.admin.training.weekly_retrain_and_reprocess") as mock_task:
            mock_result = MagicMock()
            mock_result.id = "celery-task-id-123"
            mock_task.apply_async.return_value = mock_result
            from web.routes.admin.training import _trigger_training
            result = _trigger_training()
            mock_task.apply_async.assert_called_once()
            assert result["task_id"] == "celery-task-id-123"
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_admin_training.py -v`
Expected: FAIL — module does not exist

**Step 3: Implement the training admin blueprint**

Create `telemetry_tool/web/routes/admin/training.py`:

```python
"""Admin training routes — training status, config, manual trigger.

Endpoints:
- GET  /admin/training/status  — latest training run results
- GET  /admin/training/history — list of past training runs
- POST /admin/training/trigger — manually dispatch training task
- GET  /admin/training/config  — current training parameters
- PUT  /admin/training/config  — update training parameters
"""
from __future__ import annotations

import json
import logging
from glob import glob
from pathlib import Path

from flask import Blueprint, g, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_training", __name__)

_AUDIT_DIR = Path("/data/models/kart_envelope/audit")
_CONFIG_REDIS_KEY = "lap:training:config"

_DEFAULT_CONFIG = {
    "schedule_day_of_week": 0,
    "schedule_hour": 0,
    "schedule_minute": 0,
    "min_sessions_per_group": 3,
    "reprocess_batch_size": 10,
    "reprocess_pause_s": 5,
}


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _get_redis():
    try:
        import redis
        from web.config import Config
        return redis.Redis.from_url(
            Config.REDIS_URL, socket_timeout=2, decode_responses=True,
        )
    except Exception:
        return None


def _list_audit_manifests() -> list[str]:
    """List audit manifest files sorted by date descending."""
    pattern = str(_AUDIT_DIR / "training_*.json")
    files = sorted(glob(pattern), reverse=True)
    return files


def _get_training_status() -> dict:
    """Read the latest audit manifest and return status."""
    manifests = _list_audit_manifests()
    if not manifests:
        return {"status": "never_run", "last_run": None, "runs_available": 0}

    try:
        with open(manifests[0]) as fh:
            latest = json.load(fh)
        return {
            "status": "completed",
            "last_run": latest,
            "runs_available": len(manifests),
        }
    except Exception as exc:
        return {
            "status": "error",
            "last_run": None,
            "runs_available": len(manifests),
            "error": str(exc),
        }


def _get_training_config() -> dict:
    """Read training config from Redis, falling back to defaults."""
    config = dict(_DEFAULT_CONFIG)
    r = _get_redis()
    if r:
        try:
            overrides = r.hgetall(_CONFIG_REDIS_KEY)
            for key, val in overrides.items():
                if key in config:
                    config[key] = int(val)
        except Exception:
            pass
    return config


def _trigger_training() -> dict:
    """Dispatch the weekly training task manually."""
    from tasks.training_tasks import weekly_retrain_and_reprocess
    result = weekly_retrain_and_reprocess.apply_async(queue="pipeline")
    return {"task_id": result.id, "status": "dispatched"}


@bp.route("/training/status", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def training_status():
    """Get the latest training run status."""
    return api_response(_get_training_status())


@bp.route("/training/history", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def training_history():
    """List past training runs."""
    manifests = _list_audit_manifests()
    limit = request.args.get("limit", 20, type=int)
    runs = []
    for path in manifests[:limit]:
        try:
            with open(path) as fh:
                data = json.load(fh)
            runs.append({
                "file": Path(path).name,
                "started_at": data.get("started_at"),
                "completed_at": data.get("completed_at"),
                "elapsed_s": data.get("elapsed_s"),
                "envelopes_trained": data.get("tiers", {}).get("envelopes", {}).get("trained", 0),
                "sessions_reprocessed": data.get("tiers", {}).get("reprocess", {}).get("succeeded", 0),
                "sessions_failed": data.get("tiers", {}).get("reprocess", {}).get("failed", 0),
            })
        except Exception:
            runs.append({"file": Path(path).name, "error": "unreadable"})
    return api_response(runs)


@bp.route("/training/trigger", methods=["POST"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def trigger_training():
    """Manually dispatch a training run. Audited."""
    try:
        result = _trigger_training()
    except Exception as exc:
        return api_error(
            ErrorCode.SERVICE_UNAVAILABLE,
            f"Failed to dispatch training: {exc}",
            status=503,
        )

    # Audit
    try:
        conn = _get_conn()
        from admin.audit import log_admin_action
        log_admin_action(
            conn,
            admin_user_id=getattr(g, "current_user_id", 0),
            action="training_triggered",
            details=result,
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log training trigger", exc_info=True)

    return api_response(result)


@bp.route("/training/config", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def get_config():
    """Get current training configuration."""
    return api_response(_get_training_config())


@bp.route("/training/config", methods=["PUT"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def update_config():
    """Update training configuration. Audited."""
    body = request.get_json(silent=True) or {}
    r = _get_redis()
    if not r:
        return api_error(ErrorCode.SERVICE_UNAVAILABLE, "Redis not available", status=503)

    updates = {}
    for key in _DEFAULT_CONFIG:
        if key in body:
            val = body[key]
            if not isinstance(val, int) or val < 0:
                return api_error(
                    ErrorCode.VALIDATION_ERROR,
                    f"Invalid value for {key}: must be a non-negative integer",
                    status=400,
                )
            updates[key] = str(val)

    if not updates:
        return api_error(ErrorCode.VALIDATION_ERROR, "No valid config keys provided", status=400)

    r.hset(_CONFIG_REDIS_KEY, mapping=updates)

    # Audit
    try:
        conn = _get_conn()
        from admin.audit import log_admin_action
        log_admin_action(
            conn,
            admin_user_id=getattr(g, "current_user_id", 0),
            action="training_config_updated",
            details=updates,
        )
        conn.commit()
    except Exception:
        logger.debug("Failed to log config update", exc_info=True)

    return api_response(_get_training_config())
```

**Step 4: Register the blueprint**

In `telemetry_tool/web/routes/admin/__init__.py`, add after the `infra` import (line 35):

```python
from .training import bp as training_bp  # noqa: E402
```

And add `training_bp` to the registration loop (line 37-38):

```python
for _sub_bp in [health_bp, users_bp, jobs_bp, billing_admin_bp,
                entitlements_bp, email_bp, security_bp, infra_bp, training_bp]:
```

**Step 5: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_admin_training.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/admin/training.py \
       telemetry_tool/web/routes/admin/__init__.py \
       telemetry_tool/tests/test_admin_training.py
git commit -m "feat(admin): add training status, config, and trigger endpoints"
```

---

### Task 2: Backend — User Monitoring Blueprint

**Files:**
- Create: `telemetry_tool/web/routes/admin/monitoring.py`
- Modify: `telemetry_tool/web/routes/admin/__init__.py`
- Test: `telemetry_tool/tests/test_admin_monitoring.py` (new)

**Step 1: Write the failing test**

Create `telemetry_tool/tests/test_admin_monitoring.py`:

```python
"""Tests for the user monitoring admin blueprint."""
from unittest.mock import MagicMock, patch
import pytest


class TestUserMonitoringTotals:
    def test_returns_system_totals(self):
        """GET /admin/monitoring/totals returns system-wide totals."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {
            "total_users": 42,
            "total_sessions": 150,
            "total_storage_bytes": 1073741824,  # 1 GB
            "total_compute_seconds": 3600.0,
        }

        with patch("web.routes.admin.monitoring._get_conn", return_value=mock_conn):
            from web.routes.admin.monitoring import _get_totals
            result = _get_totals()
            assert result["total_users"] == 42
            assert result["total_storage_bytes"] == 1073741824


class TestUserMonitoringList:
    def test_returns_per_user_aggregation(self):
        """GET /admin/monitoring/users returns per-user storage + compute."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {
                "user_id": 1, "email": "alice@test.com", "display_name": "Alice",
                "session_count": 10, "total_storage_bytes": 500000000,
                "total_compute_seconds": 120.5, "last_upload": "2026-03-01T10:00:00",
            },
            {
                "user_id": 2, "email": "bob@test.com", "display_name": "Bob",
                "session_count": 5, "total_storage_bytes": 250000000,
                "total_compute_seconds": 60.0, "last_upload": "2026-02-28T15:00:00",
            },
        ]

        with patch("web.routes.admin.monitoring._get_conn", return_value=mock_conn):
            from web.routes.admin.monitoring import _get_user_resources
            result = _get_user_resources()
            assert len(result) == 2
            assert result[0]["email"] == "alice@test.com"
            assert result[0]["total_storage_bytes"] == 500000000


class TestUserTimeSeries:
    def test_returns_daily_usage(self):
        """GET /admin/monitoring/users/<id>/timeseries returns daily usage."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"day": "2026-02-28", "uploads": 3, "storage_bytes": 150000000, "compute_seconds": 45.0},
            {"day": "2026-03-01", "uploads": 2, "storage_bytes": 100000000, "compute_seconds": 30.0},
        ]

        with patch("web.routes.admin.monitoring._get_conn", return_value=mock_conn):
            from web.routes.admin.monitoring import _get_user_timeseries
            result = _get_user_timeseries(1, days=30)
            assert len(result) == 2
            assert result[0]["day"] == "2026-02-28"
            assert result[0]["uploads"] == 3
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_admin_monitoring.py -v`
Expected: FAIL — module does not exist

**Step 3: Implement the monitoring admin blueprint**

Create `telemetry_tool/web/routes/admin/monitoring.py`:

```python
"""Admin monitoring routes — per-user storage and compute tracking.

Endpoints:
- GET /admin/monitoring/totals          — system-wide resource totals
- GET /admin/monitoring/users           — per-user resource aggregation
- GET /admin/monitoring/users/<id>/timeseries — daily usage for a user
"""
from __future__ import annotations

import logging

from flask import Blueprint, request

from web.api_utils import api_response, api_error, ErrorCode
from .middleware import require_superadmin, require_admin_role

logger = logging.getLogger(__name__)

bp = Blueprint("admin_monitoring", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _serialize_row(row):
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _get_totals() -> dict:
    """System-wide resource totals."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT "
        "  (SELECT COUNT(*) FROM users) AS total_users, "
        "  (SELECT COUNT(*) FROM sessions) AS total_sessions, "
        "  COALESCE((SELECT SUM(file_size) FROM ingestion_jobs), 0) AS total_storage_bytes, "
        "  COALESCE((SELECT SUM(EXTRACT(EPOCH FROM (completed_at - created_at))) "
        "    FROM ingestion_jobs WHERE completed_at IS NOT NULL), 0) AS total_compute_seconds"
    ).fetchone()
    return _serialize_row(row)


def _get_user_resources(sort_by: str = "total_storage_bytes", limit: int = 100) -> list[dict]:
    """Per-user storage and compute aggregation."""
    conn = _get_conn()

    # Validate sort column to prevent SQL injection
    allowed_sorts = {
        "total_storage_bytes", "total_compute_seconds",
        "session_count", "last_upload", "email",
    }
    if sort_by not in allowed_sorts:
        sort_by = "total_storage_bytes"

    rows = conn.execute(
        "SELECT u.id AS user_id, u.email, u.display_name, "
        "  COUNT(DISTINCT j.job_id) AS session_count, "
        "  COALESCE(SUM(j.file_size), 0) AS total_storage_bytes, "
        "  COALESCE(SUM(EXTRACT(EPOCH FROM (j.completed_at - j.created_at))), 0) "
        "    AS total_compute_seconds, "
        "  MAX(j.created_at) AS last_upload "
        "FROM users u "
        "LEFT JOIN ingestion_jobs j ON j.user_id = u.id "
        "GROUP BY u.id, u.email, u.display_name "
        f"ORDER BY {sort_by} DESC NULLS LAST "
        "LIMIT %(lim)s",
        {"lim": limit},
    ).fetchall()
    return [_serialize_row(r) for r in rows]


def _get_user_timeseries(user_id: int, days: int = 30) -> list[dict]:
    """Daily usage time series for a specific user."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT date_trunc('day', j.created_at)::date AS day, "
        "  COUNT(*) AS uploads, "
        "  COALESCE(SUM(j.file_size), 0) AS storage_bytes, "
        "  COALESCE(SUM(EXTRACT(EPOCH FROM (j.completed_at - j.created_at))), 0) "
        "    AS compute_seconds "
        "FROM ingestion_jobs j "
        "WHERE j.user_id = %(uid)s "
        "  AND j.created_at >= now() - interval '%(days)s days' "
        "GROUP BY date_trunc('day', j.created_at)::date "
        "ORDER BY day",
        {"uid": user_id, "days": days},
    ).fetchall()
    return [_serialize_row(r) for r in rows]


@bp.route("/monitoring/totals", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def get_totals():
    """System-wide resource totals."""
    return api_response(_get_totals())


@bp.route("/monitoring/users", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def list_user_resources():
    """Per-user resource aggregation."""
    sort_by = request.args.get("sort", "total_storage_bytes")
    limit = request.args.get("limit", 100, type=int)
    return api_response(_get_user_resources(sort_by=sort_by, limit=limit))


@bp.route("/monitoring/users/<int:user_id>/timeseries", methods=["GET"])
@require_superadmin
@require_admin_role("root_admin", "sre_admin")
def user_timeseries(user_id: int):
    """Daily usage time series for a specific user."""
    days = request.args.get("days", 30, type=int)
    if days < 1 or days > 365:
        return api_error(ErrorCode.VALIDATION_ERROR, "days must be 1-365", status=400)
    return api_response(_get_user_timeseries(user_id, days=days))
```

**Step 4: Register the blueprint**

In `telemetry_tool/web/routes/admin/__init__.py`, add after the training import:

```python
from .monitoring import bp as monitoring_bp  # noqa: E402
```

And add `monitoring_bp` to the registration loop:

```python
for _sub_bp in [health_bp, users_bp, jobs_bp, billing_admin_bp,
                entitlements_bp, email_bp, security_bp, infra_bp,
                training_bp, monitoring_bp]:
```

**Step 5: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_admin_monitoring.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add telemetry_tool/web/routes/admin/monitoring.py \
       telemetry_tool/web/routes/admin/__init__.py \
       telemetry_tool/tests/test_admin_monitoring.py
git commit -m "feat(admin): add user monitoring endpoints (storage + compute + timeseries)"
```

---

### Task 3: Backend — Wire Training Config to Training Task

**Files:**
- Modify: `telemetry_tool/tasks/training_tasks.py`
- Test: `telemetry_tool/tests/test_training_tasks.py` (existing, add tests)

**Step 1: Write the failing test**

Add to `telemetry_tool/tests/test_training_tasks.py`:

```python
class TestTrainingConfigRead:
    def test_reads_config_from_redis(self):
        """Training task reads min_sessions_per_group from Redis config."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "min_sessions_per_group": "5",
            "reprocess_pause_s": "30",
        }

        with patch("tasks.training_tasks._get_redis_config", return_value=mock_redis):
            from tasks.training_tasks import _load_training_config
            config = _load_training_config()
            assert config["min_sessions_per_group"] == 5
            assert config["reprocess_pause_s"] == 30

    def test_falls_back_to_defaults_when_redis_unavailable(self):
        """Training task uses defaults if Redis is unavailable."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

        with patch("tasks.training_tasks._get_redis_config", return_value=None):
            from tasks.training_tasks import _load_training_config
            config = _load_training_config()
            assert config["min_sessions_per_group"] == 3
            assert config["reprocess_pause_s"] == 5
```

**Step 2: Run test to verify it fails**

Run: `cd telemetry_tool && python -m pytest tests/test_training_tasks.py::TestTrainingConfigRead -v`
Expected: FAIL — `_load_training_config` does not exist

**Step 3: Add config loading to training_tasks.py**

Add these functions to `telemetry_tool/tasks/training_tasks.py`:

```python
_CONFIG_REDIS_KEY = "lap:training:config"

def _get_redis_config():
    """Get a Redis client for config reading."""
    try:
        import redis
        from web.config import Config
        return redis.Redis.from_url(
            Config.REDIS_URL, socket_timeout=2, decode_responses=True,
        )
    except Exception:
        return None


def _load_training_config() -> dict:
    """Load training config from Redis, fallback to hardcoded defaults."""
    defaults = {
        "min_sessions_per_group": _MIN_SESSIONS_PER_GROUP,
        "reprocess_batch_size": _REPROCESS_BATCH_SIZE,
        "reprocess_pause_s": _REPROCESS_PAUSE_S,
    }
    r = _get_redis_config()
    if r:
        try:
            overrides = r.hgetall(_CONFIG_REDIS_KEY)
            for key, val in overrides.items():
                if key in defaults:
                    defaults[key] = int(val)
        except Exception:
            pass
    return defaults
```

Then update `weekly_retrain_and_reprocess()` to use it:

```python
def weekly_retrain_and_reprocess() -> dict:
    # ... existing start ...
    config = _load_training_config()
    # ... pass config values to _train_track_envelopes and _reprocess_sessions ...
```

And update `_train_track_envelopes` and `_reprocess_sessions` to accept `min_sessions` and `pause_s` parameters instead of using module constants.

**Step 4: Run test to verify it passes**

Run: `cd telemetry_tool && python -m pytest tests/test_training_tasks.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add telemetry_tool/tasks/training_tasks.py telemetry_tool/tests/test_training_tasks.py
git commit -m "feat(training): read config from Redis for dynamic parameter tuning"
```

---

### Task 4: Frontend — Admin API Client Methods

**Files:**
- Modify: `lap-website/src/lib/admin-api.ts`

**Step 1: Add types and API methods**

At the end of the types section (before `export const adminApi`), add:

```typescript
export interface TrainingStatus {
  status: 'never_run' | 'completed' | 'error';
  last_run: {
    started_at: string;
    completed_at: string;
    elapsed_s: number;
    tiers: {
      envelopes: { trained: number; skipped: number; errors: unknown[] };
      global_model: { status: string; error?: string };
      reprocess: { succeeded: number; failed: number; errors: unknown[] };
    };
  } | null;
  runs_available: number;
  error?: string;
}

export interface TrainingHistoryEntry {
  file: string;
  started_at?: string;
  completed_at?: string;
  elapsed_s?: number;
  envelopes_trained?: number;
  sessions_reprocessed?: number;
  sessions_failed?: number;
  error?: string;
}

export interface TrainingConfig {
  schedule_day_of_week: number;
  schedule_hour: number;
  schedule_minute: number;
  min_sessions_per_group: number;
  reprocess_batch_size: number;
  reprocess_pause_s: number;
}

export interface UserResource {
  user_id: number;
  email: string;
  display_name: string | null;
  session_count: number;
  total_storage_bytes: number;
  total_compute_seconds: number;
  last_upload: string | null;
}

export interface ResourceTotals {
  total_users: number;
  total_sessions: number;
  total_storage_bytes: number;
  total_compute_seconds: number;
}

export interface DailyUsage {
  day: string;
  uploads: number;
  storage_bytes: number;
  compute_seconds: number;
}
```

Then add to `adminApi` (before the closing `};`):

```typescript
  // Training
  trainingStatus: () => api.get<TrainingStatus>('/admin/training/status'),
  trainingHistory: (limit = 20) => api.get<TrainingHistoryEntry[]>(`/admin/training/history?limit=${limit}`),
  triggerTraining: (reason: string) => api.post<{ task_id: string }>('/admin/training/trigger', { reason }),
  trainingConfig: () => api.get<TrainingConfig>('/admin/training/config'),
  updateTrainingConfig: (config: Partial<TrainingConfig>) =>
    api.put<TrainingConfig>('/admin/training/config', config),

  // Monitoring
  monitoringTotals: () => api.get<ResourceTotals>('/admin/monitoring/totals'),
  userResources: (params?: { sort?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.sort) qs.set('sort', params.sort);
    if (params?.limit) qs.set('limit', String(params.limit));
    return api.get<UserResource[]>(`/admin/monitoring/users?${qs}`);
  },
  userTimeseries: (userId: number, days = 30) =>
    api.get<DailyUsage[]>(`/admin/monitoring/users/${userId}/timeseries?days=${days}`),
```

**NOTE:** Check if `api.put` exists in `api-client.ts`. If not, the training config update can use `api.post` instead, or add a `put` method that mirrors `post` but uses `PUT`.

**Step 2: Commit**

```bash
cd lap-website && git add src/lib/admin-api.ts
git commit -m "feat(admin): add training and monitoring API client methods"
```

---

### Task 5: Frontend — Sidebar Navigation Update

**Files:**
- Modify: `lap-website/src/app/app/race-control/layout.tsx:7-49`

**Step 1: Add MONITORING section to navGroups**

After the INFRASTRUCTURE group (line 44-49), add:

```typescript
  {
    label: 'MONITORING',
    items: [
      { href: '/app/race-control/monitoring/training', label: 'Training', icon: '\u2699' },
      { href: '/app/race-control/monitoring/resources', label: 'User Resources', icon: '\u25A4' },
    ],
  },
```

**Step 2: Commit**

```bash
cd lap-website && git add src/app/app/race-control/layout.tsx
git commit -m "feat(admin): add MONITORING section to Race Control sidebar"
```

---

### Task 6: Frontend — Training Status Page

**Files:**
- Create: `lap-website/src/app/app/race-control/monitoring/training/page.tsx`

**Step 1: Implement the training page**

```tsx
'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi, type TrainingConfig } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { AdminTable } from '@/components/admin/AdminTable';
import { ActionButton } from '@/components/admin/ActionButton';
import { StatusBadge } from '@/components/admin/StatusBadge';

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}

export default function TrainingPage() {
  const queryClient = useQueryClient();
  const [editConfig, setEditConfig] = useState(false);
  const [configDraft, setConfigDraft] = useState<Partial<TrainingConfig>>({});

  const { data: status, isLoading } = useQuery({
    queryKey: ['admin-training-status'],
    queryFn: adminApi.trainingStatus,
    refetchInterval: 30000,
  });

  const { data: history } = useQuery({
    queryKey: ['admin-training-history'],
    queryFn: () => adminApi.trainingHistory(10),
  });

  const { data: config } = useQuery({
    queryKey: ['admin-training-config'],
    queryFn: adminApi.trainingConfig,
  });

  const triggerMutation = useMutation({
    mutationFn: (reason: string) => adminApi.triggerTraining(reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-training-status'] });
    },
  });

  const configMutation = useMutation({
    mutationFn: (cfg: Partial<TrainingConfig>) => adminApi.updateTrainingConfig(cfg),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-training-config'] });
      setEditConfig(false);
      setConfigDraft({});
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  const lastRun = status?.last_run;
  const tiers = lastRun?.tiers;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold text-chalk">Training Engine</h1>
        <ActionButton
          label="Trigger Training"
          variant="primary"
          onConfirm={async (reason) => {
            await triggerMutation.mutateAsync(reason);
          }}
        />
      </div>

      {/* Status cards */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="Status"
          value={status?.status === 'never_run' ? 'Never Run' : status?.status ?? 'Unknown'}
          status={status?.status === 'completed' ? 'ok' : status?.status === 'error' ? 'error' : 'warning'}
        />
        <MetricCard
          label="Last Run"
          value={lastRun?.completed_at ? new Date(lastRun.completed_at).toLocaleDateString() : 'N/A'}
          sub={lastRun?.elapsed_s ? formatDuration(lastRun.elapsed_s) : undefined}
          status="ok"
        />
        <MetricCard
          label="Envelopes Trained"
          value={tiers?.envelopes?.trained ?? 0}
          sub={`${tiers?.envelopes?.skipped ?? 0} skipped`}
          status={(tiers?.envelopes?.errors?.length ?? 0) > 0 ? 'warning' : 'ok'}
        />
        <MetricCard
          label="Sessions Reprocessed"
          value={tiers?.reprocess?.succeeded ?? 0}
          sub={`${tiers?.reprocess?.failed ?? 0} failed`}
          status={(tiers?.reprocess?.failed ?? 0) > 0 ? 'warning' : 'ok'}
        />
      </div>

      {/* Global model status */}
      {tiers?.global_model && (
        <div className="mb-6 rounded-lg border border-white/10 bg-concrete p-4">
          <h2 className="mb-2 text-sm font-semibold text-steel">Global Model Bundle</h2>
          <StatusBadge status={tiers.global_model.status} />
          {tiers.global_model.error && (
            <p className="mt-1 text-xs text-red-400">{tiers.global_model.error}</p>
          )}
        </div>
      )}

      {/* Config panel */}
      <div className="mb-6 rounded-lg border border-white/10 bg-concrete p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-steel">Configuration</h2>
          <button
            onClick={() => { setEditConfig(!editConfig); setConfigDraft(config ?? {}); }}
            className="rounded px-2 py-0.5 text-xs text-acid-green hover:bg-acid-green/10"
          >
            {editConfig ? 'Cancel' : 'Edit'}
          </button>
        </div>
        {config && !editConfig && (
          <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
            <div><span className="text-steel">Schedule:</span> <span className="text-chalk">{DAY_NAMES[config.schedule_day_of_week]} {String(config.schedule_hour).padStart(2,'0')}:{String(config.schedule_minute).padStart(2,'0')} UTC</span></div>
            <div><span className="text-steel">Min Sessions:</span> <span className="text-chalk">{config.min_sessions_per_group}</span></div>
            <div><span className="text-steel">Batch Size:</span> <span className="text-chalk">{config.reprocess_batch_size}</span></div>
            <div><span className="text-steel">Pause Between Batches:</span> <span className="text-chalk">{config.reprocess_pause_s}s</span></div>
          </div>
        )}
        {editConfig && (
          <div className="space-y-2">
            {Object.entries(configDraft).map(([key, val]) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <span className="w-48 text-steel">{key.replace(/_/g, ' ')}</span>
                <input
                  type="number"
                  value={val as number}
                  onChange={(e) => setConfigDraft(d => ({ ...d, [key]: Number(e.target.value) }))}
                  className="w-20 rounded border border-white/10 bg-white/5 px-2 py-0.5 text-chalk"
                />
              </label>
            ))}
            <button
              onClick={() => configMutation.mutate(configDraft)}
              disabled={configMutation.isPending}
              className="mt-2 rounded bg-acid-green/20 px-3 py-1 text-xs text-acid-green hover:bg-acid-green/30 disabled:opacity-50"
            >
              {configMutation.isPending ? 'Saving...' : 'Save Config'}
            </button>
          </div>
        )}
      </div>

      {/* History table */}
      <h2 className="mb-2 text-sm font-semibold text-steel">Training History</h2>
      <AdminTable
        columns={[
          { key: 'started_at', label: 'Date', render: (r) => r.started_at ? new Date(r.started_at).toLocaleString() : '-' },
          { key: 'elapsed_s', label: 'Duration', render: (r) => r.elapsed_s ? formatDuration(r.elapsed_s) : '-' },
          { key: 'envelopes_trained', label: 'Envelopes' },
          { key: 'sessions_reprocessed', label: 'Reprocessed' },
          { key: 'sessions_failed', label: 'Failed' },
        ]}
        data={history ?? []}
        emptyMessage="No training runs recorded yet"
      />
    </div>
  );
}
```

**Step 2: Commit**

```bash
cd lap-website && git add src/app/app/race-control/monitoring/training/page.tsx
git commit -m "feat(admin): add Training Status page to Race Control"
```

---

### Task 7: Frontend — User Resources Page

**Files:**
- Create: `lap-website/src/app/app/race-control/monitoring/resources/page.tsx`

**Step 1: Implement the resources page**

```tsx
'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { AdminTable } from '@/components/admin/AdminTable';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export default function UserResourcesPage() {
  const [selectedUser, setSelectedUser] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState('total_storage_bytes');

  const { data: totals } = useQuery({
    queryKey: ['admin-monitoring-totals'],
    queryFn: adminApi.monitoringTotals,
    refetchInterval: 60000,
  });

  const { data: users } = useQuery({
    queryKey: ['admin-monitoring-users', sortBy],
    queryFn: () => adminApi.userResources({ sort: sortBy }),
  });

  const { data: timeseries } = useQuery({
    queryKey: ['admin-monitoring-timeseries', selectedUser],
    queryFn: () => adminApi.userTimeseries(selectedUser!, 30),
    enabled: selectedUser !== null,
  });

  return (
    <div>
      <h1 className="mb-6 text-xl font-bold text-chalk">User Resources</h1>

      {/* System totals */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Total Users" value={totals?.total_users ?? 0} status="ok" />
        <MetricCard label="Total Sessions" value={totals?.total_sessions ?? 0} status="ok" />
        <MetricCard
          label="Total Storage"
          value={formatBytes(totals?.total_storage_bytes ?? 0)}
          status="ok"
        />
        <MetricCard
          label="Total Compute"
          value={formatDuration(totals?.total_compute_seconds ?? 0)}
          status="ok"
        />
      </div>

      {/* Sort controls */}
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs text-steel">Sort by:</span>
        {[
          { key: 'total_storage_bytes', label: 'Storage' },
          { key: 'total_compute_seconds', label: 'Compute' },
          { key: 'session_count', label: 'Sessions' },
          { key: 'last_upload', label: 'Last Upload' },
        ].map(opt => (
          <button
            key={opt.key}
            onClick={() => setSortBy(opt.key)}
            className={`rounded px-2 py-0.5 text-xs transition-colors ${
              sortBy === opt.key
                ? 'bg-acid-green/20 text-acid-green'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* User table */}
      <AdminTable
        columns={[
          { key: 'email', label: 'Email' },
          { key: 'display_name', label: 'Name', render: (r) => r.display_name ?? '-' },
          { key: 'session_count', label: 'Sessions' },
          { key: 'total_storage_bytes', label: 'Storage', render: (r) => formatBytes(r.total_storage_bytes) },
          { key: 'total_compute_seconds', label: 'Compute', render: (r) => formatDuration(r.total_compute_seconds) },
          { key: 'last_upload', label: 'Last Upload', render: (r) => r.last_upload ? new Date(r.last_upload).toLocaleDateString() : '-' },
        ]}
        data={users ?? []}
        onRowClick={(row) => setSelectedUser(row.user_id)}
        emptyMessage="No users found"
      />

      {/* Time series panel */}
      {selectedUser && timeseries && (
        <div className="mt-6 rounded-lg border border-white/10 bg-concrete p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-steel">
              Daily Usage — {users?.find(u => u.user_id === selectedUser)?.email ?? `User #${selectedUser}`}
            </h2>
            <button
              onClick={() => setSelectedUser(null)}
              className="text-xs text-steel hover:text-chalk"
            >
              Close
            </button>
          </div>

          {timeseries.length === 0 ? (
            <p className="text-sm text-steel/60">No usage data for this period</p>
          ) : (
            <div className="overflow-x-auto">
              {/* Simple bar chart using CSS */}
              <div className="flex items-end gap-1" style={{ height: '120px' }}>
                {timeseries.map((d, i) => {
                  const maxBytes = Math.max(...timeseries.map(t => t.storage_bytes), 1);
                  const pct = (d.storage_bytes / maxBytes) * 100;
                  return (
                    <div key={i} className="group relative flex-1 min-w-[8px]">
                      <div
                        className="w-full rounded-t bg-acid-green/40 transition-colors group-hover:bg-acid-green/60"
                        style={{ height: `${Math.max(pct, 2)}%` }}
                      />
                      <div className="absolute -top-16 left-1/2 -translate-x-1/2 hidden group-hover:block rounded bg-concrete border border-white/10 px-2 py-1 text-[10px] text-chalk whitespace-nowrap z-10">
                        {d.day}<br />{formatBytes(d.storage_bytes)}<br />{d.uploads} uploads
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-steel/40">
                <span>{timeseries[0]?.day}</span>
                <span>{timeseries[timeseries.length - 1]?.day}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
cd lap-website && git add src/app/app/race-control/monitoring/resources/page.tsx
git commit -m "feat(admin): add User Resources page with storage/compute tracking"
```

---

## Summary

| Task | What | Files Changed | Tests |
|------|------|---------------|-------|
| 1 | Training admin blueprint | `admin/training.py` (new), `admin/__init__.py` | `test_admin_training.py` |
| 2 | Monitoring admin blueprint | `admin/monitoring.py` (new), `admin/__init__.py` | `test_admin_monitoring.py` |
| 3 | Wire training config to task | `training_tasks.py`, `test_training_tasks.py` | Yes (existing + new) |
| 4 | Frontend API client methods | `admin-api.ts` | — |
| 5 | Sidebar navigation update | `layout.tsx` | — |
| 6 | Training Status page | `monitoring/training/page.tsx` (new) | — |
| 7 | User Resources page | `monitoring/resources/page.tsx` (new) | — |

Total: ~950 lines across 9 files (5 new, 4 modified).
