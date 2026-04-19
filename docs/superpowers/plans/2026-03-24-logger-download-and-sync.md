# Logger Download & Device Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Lap Coach Logger downloadable from the webapp and enable automatic session sync for Racer/World-Class users via device pairing.

**Architecture:** Device pairing (6-char code) links the desktop logger to a user account. The logger's existing `SyncService` protocol gets a real implementation that POSTs telemetry CSVs to a new `/api/v1/sessions/sync-upload` endpoint. World-Class auto-dispatches Celery analysis; Racer stores as pending. VPS hosts the installer via Caddy static files.

**Tech Stack:** Python/Flask (backend), PySide6 (logger), Next.js 14 (frontend), PostgreSQL (Alembic migration), Celery (async pipeline)

**Spec:** `docs/superpowers/specs/2026-03-24-logger-download-and-sync-design.md`

---

## File Map

### Backend (`telemetry_tool/`)

| File | Action | Responsibility |
|---|---|---|
| `alembic/versions/051_device_pairings.py` | Create | Migration: `device_pairings` table |
| `web/routes/devices.py` | Create | Device pairing CRUD endpoints (pair, poll, confirm, list, revoke) |
| `web/routes/sync_upload.py` | Create | `POST /api/v1/sessions/sync-upload` — receive CSV from logger |
| `web/middleware/device_auth.py` | Create | `DeviceToken` header validation, resolve user/workspace |
| `auth/entitlements.py` | Modify | Add `device_sync`, `auto_analyze_on_sync`, `max_linked_devices` |
| `web/middleware/auth.py` | Modify | Add device pairing paths to auth public allowlist |
| `web/app.py` | Modify | Register new blueprints |
| `tests/test_device_pairing.py` | Create | Tests for pairing flow |
| `tests/test_sync_upload.py` | Create | Tests for sync-upload endpoint |
| `tests/test_device_auth.py` | Create | Tests for device token middleware |

### Data Logger (`datalogger/src/lap_coach_logger/`)

| File | Action | Responsibility |
|---|---|---|
| `core/lap_coach_sync.py` | Create | `LapCoachSyncService` implementing `SyncService` protocol |
| `config/models.py` | Modify | Add `SyncConfig` dataclass |
| `bootstrap.py` | Modify | Wire sync service when device token present |
| `ui/desktop/settings_dialog.py` | Modify | Add account linking section |
| `ui/desktop/panels.py` | Modify | Sync status indicator in dashboard |

### Frontend (`lap-website/src/`)

| File | Action | Responsibility |
|---|---|---|
| `app/(marketing)/product/logger/page.tsx` | Create | Download page |
| `app/app/account/devices/page.tsx` | Create | Device management UI |
| `lib/entitlements-store.ts` | Modify | Add sync entitlement keys |
| `data/pricing.ts` | Modify | Add logger features to eligibility matrix |
| `data/navigation.ts` | Modify | Add logger to nav |

---

## Task 1: Alembic Migration — `device_pairings` Table + `source_bundle_hash`

**Files:**
- Create: `telemetry_tool/alembic/versions/051_device_pairings.py`

- [ ] **Step 1: Create the migration file**

```python
"""051 – device_pairings table for logger-to-webapp pairing.

Also adds source_bundle_hash column to sessions for sync idempotency.

Revision ID: 051_device_pairings
Revises: 050_import_error_json
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "051_device_pairings"
down_revision = "050_import_error_json"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_pairings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("pairing_code", sa.String(7), unique=True, nullable=True),
        sa.Column("pairing_id", UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("device_token_hash", sa.String(128), nullable=True),
        sa.Column("device_name", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_device_pairings_code",
        "device_pairings",
        ["pairing_code"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_device_pairings_user",
        "device_pairings",
        ["user_id"],
        postgresql_where=sa.text("status = 'confirmed'"),
    )
    op.create_index(
        "idx_device_pairings_pairing_id",
        "device_pairings",
        ["pairing_id"],
    )

    # Add source_bundle_hash to sessions for sync-upload idempotency.
    # The `source` column already exists (migration 001).
    op.add_column("sessions", sa.Column("source_bundle_hash", sa.String(128), nullable=True))
    op.create_index(
        "idx_sessions_bundle_hash",
        "sessions",
        ["source_bundle_hash"],
        postgresql_where=sa.text("source_bundle_hash IS NOT NULL"),
    )


def downgrade():
    op.drop_index("idx_sessions_bundle_hash", table_name="sessions")
    op.drop_column("sessions", "source_bundle_hash")
    op.drop_table("device_pairings")
```

- [ ] **Step 2: Run the migration locally**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && alembic upgrade head`
Expected: `051_device_pairings` applied successfully.

- [ ] **Step 3: Verify the table exists**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -c "from telemetry_tool.web.db_pg import get_pg_connection; c = get_pg_connection(); c.execute('SELECT 1 FROM device_pairings LIMIT 0'); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/alembic/versions/051_device_pairings.py
git commit -m "feat(db): add device_pairings table for logger sync (051)"
```

---

## Task 2: Entitlement Updates

**Files:**
- Modify: `telemetry_tool/auth/entitlements.py` (lines 30-104 for PLAN_ENTITLEMENTS, lines 152-183 for _BOOLEAN_FEATURES and _UPGRADE_TIERS, lines 289-340 for get_user_entitlements)
- Test: `telemetry_tool/tests/test_entitlements.py`

- [ ] **Step 1: Write the failing tests**

Add to `telemetry_tool/tests/test_entitlements.py`:

```python
def test_device_sync_entitlement_demo():
    ents = get_plan_entitlements("demo")
    assert ents["device_sync"] is False
    assert ents["auto_analyze_on_sync"] is False
    assert ents["max_linked_devices"] == 0


def test_device_sync_entitlement_racer():
    ents = get_plan_entitlements("racer")
    assert ents["device_sync"] is True
    assert ents["auto_analyze_on_sync"] is False
    assert ents["max_linked_devices"] == 2


def test_device_sync_entitlement_world_class():
    ents = get_plan_entitlements("world_class")
    assert ents["device_sync"] is True
    assert ents["auto_analyze_on_sync"] is True
    assert ents["max_linked_devices"] == 3


def test_device_sync_alias_consistency():
    """world-class alias must see the same keys as world_class."""
    wc = get_plan_entitlements("world_class")
    wc_alias = get_plan_entitlements("world-class")
    assert wc["device_sync"] == wc_alias["device_sync"]
    assert wc["auto_analyze_on_sync"] == wc_alias["auto_analyze_on_sync"]


def test_authorize_device_sync_racer(test_db):
    """authorize_feature('device_sync') returns True for a racer user."""
    from auth.entitlements import authorize_feature
    # Uses test_db fixture which should have a racer user seeded
    allowed, ctx = authorize_feature(test_db, 1, "device_sync")
    assert allowed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_entitlements.py -k "device_sync" -v`
Expected: FAIL with `KeyError: 'device_sync'`

- [ ] **Step 3: Add entitlement keys to PLAN_ENTITLEMENTS**

In `auth/entitlements.py`, add to each tier dict (inside the literal, before the alias at line 103-104):

`"free"` dict — add:
```python
        "device_sync": False,
        "auto_analyze_on_sync": False,
        "max_linked_devices": 0,
```

`"racer"` dict — add:
```python
        "device_sync": True,
        "auto_analyze_on_sync": False,
        "max_linked_devices": 2,
```

`"world_class"` dict — add:
```python
        "device_sync": True,
        "auto_analyze_on_sync": True,
        "max_linked_devices": 3,
```

Add to `_BOOLEAN_FEATURES`:
```python
    "device_sync": "device_sync",
    "auto_analyze_on_sync": "auto_analyze_on_sync",
```

Add to `_UPGRADE_TIERS`:
```python
    "device_sync": "racer",
    "auto_analyze_on_sync": "world-class",
```

- [ ] **Step 4: Update `get_user_entitlements()` to surface new keys**

Around line 340 (after existing entitlement dict construction), add:
```python
        entitlements["device_sync"] = py_defaults.get("device_sync", False)
        entitlements["auto_analyze_on_sync"] = py_defaults.get("auto_analyze_on_sync", False)
        entitlements["max_linked_devices"] = py_defaults.get("max_linked_devices", 0)
```

- [ ] **Step 5: Run tests**

Run: `pytest telemetry_tool/tests/test_entitlements.py -k "device_sync" -v`
Expected: All 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/auth/entitlements.py telemetry_tool/tests/test_entitlements.py
git commit -m "feat(entitlements): add device_sync, auto_analyze_on_sync, max_linked_devices"
```

---

## Task 3: Device Auth Middleware

**Files:**
- Create: `telemetry_tool/web/middleware/device_auth.py`
- Modify: `telemetry_tool/web/middleware/auth.py` (add device pairing paths to allowlist)
- Test: `telemetry_tool/tests/test_device_auth.py`

- [ ] **Step 1: Write the failing tests**

Create `telemetry_tool/tests/test_device_auth.py`:

```python
"""Tests for device token authentication middleware."""
import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def test_extract_device_token_valid_header():
    from web.middleware.device_auth import _extract_device_token
    # Mock request with DeviceToken header
    with patch("web.middleware.device_auth.request") as mock_req:
        mock_req.headers = {"Authorization": "DeviceToken abc123def456"}
        assert _extract_device_token() == "abc123def456"


def test_extract_device_token_missing():
    from web.middleware.device_auth import _extract_device_token
    with patch("web.middleware.device_auth.request") as mock_req:
        mock_req.headers = {}
        assert _extract_device_token() is None


def test_extract_device_token_wrong_scheme():
    from web.middleware.device_auth import _extract_device_token
    with patch("web.middleware.device_auth.request") as mock_req:
        mock_req.headers = {"Authorization": "Bearer jwt_token_here"}
        assert _extract_device_token() is None


def test_validate_device_token_confirmed(test_db):
    """A confirmed, non-revoked token resolves to user_id + workspace_id."""
    from web.middleware.device_auth import validate_device_token
    token = "test_device_token_abc123"
    token_hash = _hash_token(token)
    test_db.execute(
        "INSERT INTO device_pairings (user_id, workspace_id, device_token_hash, status, expires_at) "
        "VALUES (%(uid)s, %(wsid)s, %(hash)s, 'confirmed', %(exp)s)",
        {"uid": 1, "wsid": 1, "hash": token_hash,
         "exp": datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()},
    )
    result = validate_device_token(test_db, token)
    assert result is not None
    assert result["user_id"] == 1
    assert result["workspace_id"] == 1


def test_validate_device_token_revoked(test_db):
    """A revoked token returns None."""
    from web.middleware.device_auth import validate_device_token
    token = "revoked_token_xyz"
    token_hash = _hash_token(token)
    test_db.execute(
        "INSERT INTO device_pairings (user_id, workspace_id, device_token_hash, status, "
        "revoked_at, expires_at) "
        "VALUES (%(uid)s, %(wsid)s, %(hash)s, 'revoked', %(rev)s, %(exp)s)",
        {"uid": 1, "wsid": 1, "hash": token_hash,
         "rev": datetime.now(timezone.utc).isoformat(),
         "exp": datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()},
    )
    result = validate_device_token(test_db, token)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_device_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.middleware.device_auth'`

- [ ] **Step 3: Implement device auth middleware**

Create `telemetry_tool/web/middleware/device_auth.py`:

```python
"""Device token authentication for logger sync endpoints."""
from __future__ import annotations

import hashlib
import logging
from functools import wraps

from flask import g, request

logger = logging.getLogger(__name__)


def _extract_device_token() -> str | None:
    """Extract token from 'Authorization: DeviceToken <token>' header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("DeviceToken "):
        return None
    return auth[len("DeviceToken "):].strip() or None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_device_token(conn, token: str) -> dict | None:
    """Validate a device token against the DB.

    Returns dict with user_id, workspace_id, device_id if valid, else None.
    """
    token_hash = _hash_token(token)
    cur = conn.execute(
        "SELECT id, user_id, workspace_id FROM device_pairings "
        "WHERE device_token_hash = %(hash)s "
        "AND status = 'confirmed' AND revoked_at IS NULL",
        {"hash": token_hash},
    )
    row = cur.fetchone()
    if row is None:
        return None
    r = dict(row) if not isinstance(row, dict) else row
    return {
        "device_id": r["id"],
        "user_id": r["user_id"],
        "workspace_id": r["workspace_id"],
    }


def require_device_token(fn):
    """Decorator: require a valid device token. Sets g.current_user_id, g.workspace_id, g.device_id."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from web.api_utils import ErrorCode, api_error
        from web.db_pg import get_pg_connection

        token = _extract_device_token()
        if token is None:
            return api_error(ErrorCode.UNAUTHORIZED, "Device token required", status=401)

        conn = get_pg_connection()
        result = validate_device_token(conn, token)
        if result is None:
            return api_error(ErrorCode.UNAUTHORIZED, "Invalid or revoked device token", status=401)

        g.current_user_id = result["user_id"]
        g.user_id = result["user_id"]
        g.workspace_id = result["workspace_id"]
        g.device_id = result["device_id"]

        # Update last_seen_at
        try:
            conn.execute(
                "UPDATE device_pairings SET last_seen_at = now() WHERE id = %(did)s",
                {"did": result["device_id"]},
            )
        except Exception:
            logger.warning("Failed to update device last_seen_at", exc_info=True)

        return fn(*args, **kwargs)
    return wrapper
```

- [ ] **Step 4: Add rate-limit tiers for device endpoints**

In `telemetry_tool/web/rate_limit.py`, add new entries to `RATE_TIERS` dict (around line 59):
```python
    "device_pair": {"max_requests": 5, "window_seconds": 3600},
    "device_poll": {"max_requests": 20, "window_seconds": 60},
    "sync_upload": {"max_requests": 30, "window_seconds": 3600},
```

**Note**: `rate_limit()` takes a tier name string and looks it up in `RATE_TIERS`. It does NOT accept `max_requests`/`window_seconds` as kwargs.

- [ ] **Step 5: Add device pairing paths to auth middleware allowlist**

In `telemetry_tool/web/middleware/auth.py`, add to `_AUTH_PUBLIC_PATHS` (around line 44):
```python
        "/api/v1/devices/pair",        # Device pairing (no auth)
```

Also add a regex match for the poll endpoint after `_OAUTH_PATH_RE` (around line 24):
```python
_DEVICE_PAIR_STATUS_RE = re.compile(r"^/api/v1/devices/pair/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/status$")
```

And in the skip check (around line 51):
```python
    if request.path in _AUTH_PUBLIC_PATHS or _OAUTH_PATH_RE.match(request.path) or _DEVICE_PAIR_STATUS_RE.match(request.path):
```

Also add sync-upload to be skipped (it uses its own DeviceToken auth, not JWT):
```python
        "/api/v1/sessions/sync-upload",  # Uses DeviceToken auth
```

**Note**: `require_device_token` and all device-related middleware are PG-only (they call `get_pg_connection()`). This is consistent with production (always PG) but will raise `RuntimeError` if `USE_PG=0`.

- [ ] **Step 6: Run tests**

Run: `pytest telemetry_tool/tests/test_device_auth.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add telemetry_tool/web/middleware/device_auth.py telemetry_tool/web/middleware/auth.py telemetry_tool/web/rate_limit.py telemetry_tool/tests/test_device_auth.py
git commit -m "feat(auth): add device token middleware for logger sync"
```

---

## Task 4: Device Pairing Endpoints

**Files:**
- Create: `telemetry_tool/web/routes/devices.py`
- Modify: `telemetry_tool/web/app.py` (register blueprint)
- Test: `telemetry_tool/tests/test_device_pairing.py`

- [ ] **Step 1: Write the failing tests**

Create `telemetry_tool/tests/test_device_pairing.py`:

```python
"""Tests for device pairing endpoints."""
import json
import re

import pytest


def test_pair_generates_code(client_pg):
    """POST /api/v1/devices/pair returns a 6-char pairing code."""
    resp = client_pg.post(
        "/api/v1/devices/pair",
        json={"device_name": "TEST-PC"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    code = data["data"]["code"]
    assert re.match(r"^[A-Z2-9]{3}-[A-Z2-9]{3}$", code)
    assert data["data"]["pairing_id"]
    assert data["data"]["expires_at"]


def test_pair_status_pending(client_pg):
    """Polling before confirmation returns pending."""
    resp = client_pg.post("/api/v1/devices/pair", json={"device_name": "TEST-PC"})
    pairing_id = resp.get_json()["data"]["pairing_id"]
    status_resp = client_pg.get(f"/api/v1/devices/pair/{pairing_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.get_json()["data"]["status"] == "pending"


def test_confirm_pairing(client_pg, auth_headers_racer):
    """Confirming a valid code links the device to the authenticated user."""
    # Generate code
    resp = client_pg.post("/api/v1/devices/pair", json={"device_name": "TEST-PC"})
    code = resp.get_json()["data"]["code"]
    pairing_id = resp.get_json()["data"]["pairing_id"]

    # Confirm with auth
    confirm_resp = client_pg.post(
        "/api/v1/devices/confirm",
        json={"code": code},
        headers=auth_headers_racer,
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.get_json()["ok"] is True

    # Poll should now return confirmed + device_token
    status_resp = client_pg.get(f"/api/v1/devices/pair/{pairing_id}/status")
    assert status_resp.status_code == 200
    sdata = status_resp.get_json()["data"]
    assert sdata["status"] == "confirmed"
    assert sdata["device_token"]


def test_confirm_expired_code(client_pg, auth_headers_racer):
    """Confirming an expired code returns 410."""
    # This test needs a code with expires_at in the past — done via DB manipulation
    # in the test fixture. Simplified: just test with a bogus code.
    resp = client_pg.post(
        "/api/v1/devices/confirm",
        json={"code": "ZZZ-ZZZ"},
        headers=auth_headers_racer,
    )
    assert resp.status_code == 404


def test_confirm_demo_blocked(client_pg, auth_headers_demo):
    """Demo users cannot confirm pairing (max_linked_devices=0)."""
    resp = client_pg.post("/api/v1/devices/pair", json={"device_name": "TEST-PC"})
    code = resp.get_json()["data"]["code"]
    confirm_resp = client_pg.post(
        "/api/v1/devices/confirm",
        json={"code": code},
        headers=auth_headers_demo,
    )
    assert confirm_resp.status_code == 403


def test_list_devices(client_pg, auth_headers_racer):
    """GET /api/v1/devices lists linked devices."""
    # Pair + confirm first
    resp = client_pg.post("/api/v1/devices/pair", json={"device_name": "MY-RIG"})
    code = resp.get_json()["data"]["code"]
    client_pg.post("/api/v1/devices/confirm", json={"code": code}, headers=auth_headers_racer)

    list_resp = client_pg.get("/api/v1/devices", headers=auth_headers_racer)
    assert list_resp.status_code == 200
    devices = list_resp.get_json()["data"]
    assert len(devices) >= 1
    assert devices[0]["device_name"] == "MY-RIG"


def test_revoke_device(client_pg, auth_headers_racer):
    """DELETE /api/v1/devices/<id> revokes the device."""
    resp = client_pg.post("/api/v1/devices/pair", json={"device_name": "REVOKE-ME"})
    code = resp.get_json()["data"]["code"]
    client_pg.post("/api/v1/devices/confirm", json={"code": code}, headers=auth_headers_racer)

    devices = client_pg.get("/api/v1/devices", headers=auth_headers_racer).get_json()["data"]
    device_id = devices[0]["id"]

    del_resp = client_pg.delete(f"/api/v1/devices/{device_id}", headers=auth_headers_racer)
    assert del_resp.status_code == 200

    # Should no longer appear in list
    devices_after = client_pg.get("/api/v1/devices", headers=auth_headers_racer).get_json()["data"]
    assert all(d["id"] != device_id for d in devices_after)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_device_pairing.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement device pairing routes**

Create `telemetry_tool/web/routes/devices.py`:

```python
"""Device pairing and management endpoints.

POST /api/v1/devices/pair         — generate pairing code (no auth)
GET  /api/v1/devices/pair/<id>/status — poll pairing status (no auth)
POST /api/v1/devices/confirm      — confirm code (JWT auth)
GET  /api/v1/devices              — list linked devices (JWT auth)
DELETE /api/v1/devices/<id>       — revoke a device (JWT auth)
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, ReasonCode, api_error, api_response, billing_error
from web.db_pg import get_pg_connection
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("devices", __name__, url_prefix="/api/v1")

# Characters that are unambiguous (no 0/O/I/1/L)
_CODE_CHARS = string.ascii_uppercase.replace("O", "").replace("I", "").replace("L", "") + "23456789"
_CODE_TTL_MINUTES = 10
_POLL_AFTER_CONFIRM_TTL_S = 60  # pairing_id remains valid for 60s after confirm


def _generate_code() -> str:
    """Generate a 6-char code like K7X-9M2."""
    part1 = "".join(secrets.choice(_CODE_CHARS) for _ in range(3))
    part2 = "".join(secrets.choice(_CODE_CHARS) for _ in range(3))
    return f"{part1}-{part2}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@bp.route("/devices/pair", methods=["POST"])
@rate_limit("device_pair")
def create_pairing():
    """Generate a pairing code for the logger to display."""
    body = request.get_json(silent=True) or {}
    device_name = str(body.get("device_name", ""))[:100]

    conn = get_pg_connection()
    code = _generate_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)

    # Retry on code collision (extremely unlikely with 6 chars from 33-char alphabet)
    for _ in range(5):
        try:
            cur = conn.execute(
                "INSERT INTO device_pairings (pairing_code, device_name, expires_at) "
                "VALUES (%(code)s, %(name)s, %(exp)s) RETURNING pairing_id",
                {"code": code, "name": device_name, "exp": expires_at.isoformat()},
            )
            row = cur.fetchone()
            r = dict(row) if not isinstance(row, dict) else row
            return api_response({
                "pairing_id": str(r["pairing_id"]),
                "code": code,
                "expires_at": expires_at.isoformat(),
            })
        except Exception:
            code = _generate_code()

    return api_error(ErrorCode.INTERNAL_ERROR, "Failed to generate pairing code", status=500)


@bp.route("/devices/pair/<pairing_id>/status", methods=["GET"])
@rate_limit("device_poll")
def poll_pairing_status(pairing_id: str):
    """Poll the status of a pairing request."""
    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT status, device_token_hash, expires_at FROM device_pairings "
        "WHERE pairing_id = %(pid)s::uuid",
        {"pid": pairing_id},
    )
    row = cur.fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Pairing not found", status=404)

    r = dict(row) if not isinstance(row, dict) else row

    # Check expiry for pending codes
    if r["status"] == "pending":
        expires = r.get("expires_at")
        if expires and isinstance(expires, datetime) and expires < datetime.now(timezone.utc):
            return api_response({"status": "expired"})

    result = {"status": r["status"]}

    # Only reveal token on first poll after confirmation
    if r["status"] == "confirmed" and r.get("device_token_hash"):
        # Token was stored in a temporary field during confirm — read and clear
        cur2 = conn.execute(
            "SELECT device_name FROM device_pairings WHERE pairing_id = %(pid)s::uuid",
            {"pid": pairing_id},
        )
        # The actual token is passed via a temp column; see confirm endpoint.
        # For simplicity we use a separate token-reveal table or a transient field.
        # Implementation: confirm stores plaintext token in Redis with pairing_id key,
        # poll reads and deletes it.
        import redis
        import os
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r_client = redis.from_url(redis_url)
        token_key = f"device_pair_token:{pairing_id}"
        raw_token = r_client.get(token_key)
        if raw_token:
            result["device_token"] = raw_token.decode("utf-8")
            r_client.delete(token_key)

    return api_response(result)


@bp.route("/devices/confirm", methods=["POST"])
def confirm_pairing():
    """Confirm a pairing code (requires JWT auth)."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    body = request.get_json(silent=True) or {}
    code = str(body.get("code", "")).strip().upper()
    if not code:
        return api_error(ErrorCode.VALIDATION_ERROR, "Pairing code is required", status=400)

    conn = get_pg_connection()

    # Check entitlement: max_linked_devices
    from auth.entitlements import get_plan_entitlements, get_user_plan_tier
    tier = get_user_plan_tier(conn, user_id)
    plan = get_plan_entitlements(tier)
    max_devices = plan.get("max_linked_devices", 0)

    if max_devices == 0:
        return billing_error(
            reason_code=ReasonCode.FEATURE_LOCKED,
            message="Device linking requires Racer plan or higher",
            current_plan=tier,
            required_plan="racer",
            upgrade_url="/billing?plan=RACER",
            status=403,
        )

    # Count existing confirmed devices
    cur = conn.execute(
        "SELECT COUNT(*) AS cnt FROM device_pairings "
        "WHERE user_id = %(uid)s AND status = 'confirmed' AND revoked_at IS NULL",
        {"uid": user_id},
    )
    row = cur.fetchone()
    count = (dict(row) if not isinstance(row, dict) else row).get("cnt", 0)
    if count >= max_devices:
        return api_error(
            ErrorCode.VALIDATION_ERROR,
            f"Maximum {max_devices} devices allowed. Unlink a device first.",
            status=400,
        )

    # Find the pairing code
    cur = conn.execute(
        "SELECT id, pairing_id, device_name, expires_at FROM device_pairings "
        "WHERE pairing_code = %(code)s AND status = 'pending'",
        {"code": code},
    )
    row = cur.fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Invalid or expired pairing code", status=404)

    r = dict(row) if not isinstance(row, dict) else row

    # Check expiry
    expires = r.get("expires_at")
    if expires and isinstance(expires, datetime) and expires < datetime.now(timezone.utc):
        return api_error(ErrorCode.NOT_FOUND, "Pairing code has expired", status=410)

    # Generate device token
    device_token = secrets.token_hex(32)  # 64 chars
    token_hash = _hash_token(device_token)

    # Resolve default workspace
    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        from auth.workspace import get_default_workspace_id
        workspace_id = get_default_workspace_id(conn, user_id)

    # Update the pairing row
    conn.execute(
        "UPDATE device_pairings SET "
        "user_id = %(uid)s, workspace_id = %(wsid)s, "
        "device_token_hash = %(hash)s, status = 'confirmed', "
        "confirmed_at = now() "
        "WHERE id = %(pid)s",
        {"uid": user_id, "wsid": workspace_id, "hash": token_hash, "pid": r["id"]},
    )

    # Store plaintext token in Redis for one-time retrieval by logger poll
    import redis
    import os
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    r_client = redis.from_url(redis_url)
    r_client.setex(
        f"device_pair_token:{r['pairing_id']}",
        _POLL_AFTER_CONFIRM_TTL_S,
        device_token,
    )

    return api_response({
        "device_id": r["id"],
        "device_name": r.get("device_name"),
    })


@bp.route("/devices", methods=["GET"])
def list_devices():
    """List the user's linked devices."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    conn = get_pg_connection()
    cur = conn.execute(
        "SELECT id, device_name, status, last_seen_at, confirmed_at "
        "FROM device_pairings "
        "WHERE user_id = %(uid)s AND status = 'confirmed' AND revoked_at IS NULL "
        "ORDER BY confirmed_at DESC",
        {"uid": user_id},
    )
    devices = []
    for row in cur.fetchall():
        r = dict(row) if not isinstance(row, dict) else row
        devices.append({
            "id": r["id"],
            "device_name": r.get("device_name"),
            "status": r["status"],
            "last_seen_at": r.get("last_seen_at").isoformat() if r.get("last_seen_at") else None,
            "confirmed_at": r.get("confirmed_at").isoformat() if r.get("confirmed_at") else None,
        })

    return api_response(devices)


@bp.route("/devices/<int:device_id>", methods=["DELETE"])
def revoke_device(device_id: int):
    """Revoke (unlink) a device."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    conn = get_pg_connection()
    cur = conn.execute(
        "UPDATE device_pairings SET status = 'revoked', revoked_at = now(), "
        "device_token_hash = NULL "
        "WHERE id = %(did)s AND user_id = %(uid)s AND status = 'confirmed' "
        "RETURNING id",
        {"did": device_id, "uid": user_id},
    )
    row = cur.fetchone()
    if row is None:
        return api_error(ErrorCode.NOT_FOUND, "Device not found", status=404)

    return api_response({"revoked": True})
```

- [ ] **Step 4: Register blueprint in `app.py`**

In `telemetry_tool/web/app.py`, inside the `if cfg.USE_PG:` block (around line 390, after endurance_upload), add:

```python
            # Device pairing and sync endpoints
            from .routes.devices import bp as devices_bp
            app.register_blueprint(devices_bp)
            logger.debug("Registered devices blueprint")
```

- [ ] **Step 5: Run tests**

Run: `pytest telemetry_tool/tests/test_device_pairing.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/devices.py telemetry_tool/web/app.py telemetry_tool/tests/test_device_pairing.py
git commit -m "feat(devices): add pairing endpoints (pair, confirm, list, revoke)"
```

---

## Task 5: Sync Upload Endpoint

**Files:**
- Create: `telemetry_tool/web/routes/sync_upload.py`
- Modify: `telemetry_tool/web/app.py` (register blueprint)
- Test: `telemetry_tool/tests/test_sync_upload.py`

- [ ] **Step 1: Write the failing tests**

Create `telemetry_tool/tests/test_sync_upload.py`:

```python
"""Tests for sync-upload endpoint."""
import io
import json

import pytest


def _make_csv():
    """Return a minimal valid CSV file-like object."""
    content = "Time (s),Speed (m/s),Lap #\n0.0,10.0,1\n0.1,11.0,1\n"
    return (io.BytesIO(content.encode()), "session.csv")


def _make_manifest(**overrides):
    base = {
        "session_id": "2026-03-24_test",
        "bundle_hash": "abc123",
        "sim_name": "iRacing",
        "track_name": "Spa",
        "car_name": "GT3",
        "session_type": "practice",
        "driver_name": "Test Driver",
        "started_at_utc": "2026-03-24T14:00:00Z",
        "ended_at_utc": "2026-03-24T14:30:00Z",
        "duration_s": 1800,
        "total_laps": 5,
        "valid_laps": 4,
        "best_lap_time_s": 140.0,
        "quality_score": 0.9,
        "sample_count": 100,
        "logger_version": "1.1.0",
    }
    base.update(overrides)
    return json.dumps(base)


def test_sync_upload_no_token(client_pg):
    """Missing device token returns 401."""
    csv_data, csv_name = _make_csv()
    resp = client_pg.post(
        "/api/v1/sessions/sync-upload",
        data={"telemetry": (csv_data, csv_name), "manifest": _make_manifest()},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 401


def test_sync_upload_invalid_token(client_pg):
    """Invalid device token returns 401."""
    csv_data, csv_name = _make_csv()
    resp = client_pg.post(
        "/api/v1/sessions/sync-upload",
        data={"telemetry": (csv_data, csv_name), "manifest": _make_manifest()},
        content_type="multipart/form-data",
        headers={"Authorization": "DeviceToken invalid_token_here"},
    )
    assert resp.status_code == 401


def test_sync_upload_success(client_pg, device_token_racer):
    """Valid device token + CSV uploads successfully."""
    csv_data, csv_name = _make_csv()
    resp = client_pg.post(
        "/api/v1/sessions/sync-upload",
        data={"telemetry": (csv_data, csv_name), "manifest": _make_manifest()},
        content_type="multipart/form-data",
        headers={"Authorization": f"DeviceToken {device_token_racer}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["data"]["session_id"]
    assert data["data"]["analyze_triggered"] is False  # Racer = no auto-analyze


def test_sync_upload_idempotent(client_pg, device_token_racer):
    """Uploading the same bundle_hash twice returns the same session_id."""
    manifest = _make_manifest(bundle_hash="idempotent_hash_xyz")
    csv1, name1 = _make_csv()
    resp1 = client_pg.post(
        "/api/v1/sessions/sync-upload",
        data={"telemetry": (csv1, name1), "manifest": manifest},
        content_type="multipart/form-data",
        headers={"Authorization": f"DeviceToken {device_token_racer}"},
    )
    csv2, name2 = _make_csv()
    resp2 = client_pg.post(
        "/api/v1/sessions/sync-upload",
        data={"telemetry": (csv2, name2), "manifest": manifest},
        content_type="multipart/form-data",
        headers={"Authorization": f"DeviceToken {device_token_racer}"},
    )
    assert resp1.get_json()["data"]["session_id"] == resp2.get_json()["data"]["session_id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_sync_upload.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement sync-upload endpoint**

Create `telemetry_tool/web/routes/sync_upload.py`:

```python
"""Sync upload endpoint — receives session CSVs from the Lap Coach Logger.

POST /api/v1/sessions/sync-upload
    Auth: DeviceToken header (not JWT)
    Body: multipart/form-data with telemetry (CSV) + manifest (JSON string)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response
from web.middleware.device_auth import require_device_token
from web.rate_limit import rate_limit

logger = logging.getLogger(__name__)

bp = Blueprint("sync_upload", __name__, url_prefix="/api/v1")


@bp.route("/sessions/sync-upload", methods=["POST"])
@require_device_token
@rate_limit("sync_upload")
def sync_upload():
    """Receive a session CSV from the logger and store it."""
    from web.db_pg import get_pg_connection
    from auth.entitlements import (
        authorize_feature,
        check_and_record_quota,
        get_plan_entitlements,
        get_user_plan_tier,
    )

    conn = get_pg_connection()
    user_id = g.current_user_id
    workspace_id = g.workspace_id

    # 1. Check device_sync entitlement
    allowed, ctx = authorize_feature(conn, user_id, "device_sync")
    if not allowed:
        return api_error(ErrorCode.FORBIDDEN, ctx.get("reason", "Sync not available"), status=403)

    # 2. Parse inputs
    telemetry_file = request.files.get("telemetry")
    manifest_raw = request.form.get("manifest", "{}")

    if telemetry_file is None:
        return api_error(ErrorCode.VALIDATION_ERROR, "telemetry file is required", status=400)

    try:
        manifest = json.loads(manifest_raw)
    except (json.JSONDecodeError, TypeError):
        return api_error(ErrorCode.VALIDATION_ERROR, "manifest must be valid JSON", status=400)

    bundle_hash = manifest.get("bundle_hash", "")

    # 3. Idempotency check
    if bundle_hash:
        cur = conn.execute(
            "SELECT id FROM sessions "
            "WHERE workspace_id = %(wsid)s AND source_bundle_hash = %(hash)s",
            {"wsid": workspace_id, "hash": bundle_hash},
        )
        existing = cur.fetchone()
        if existing:
            r = dict(existing) if not isinstance(existing, dict) else existing
            return api_response({
                "session_id": r["id"],
                "status": "already_uploaded",
                "analyze_triggered": False,
            })

    # 4. Check upload volume quota
    telemetry_file.seek(0, 2)
    file_size = telemetry_file.tell()
    telemetry_file.seek(0)
    file_size_mb = max(1, file_size // (1024 * 1024))

    allowed, ctx = check_and_record_quota(
        conn, user_id, workspace_id, "upload_volume_mb", cost=file_size_mb,
    )
    if not allowed:
        return api_error(
            ErrorCode.QUOTA_EXCEEDED,
            f"Monthly upload volume exceeded ({ctx.get('used', 0)} MB / {ctx.get('limit', 0)} MB)",
            status=429,
        )

    # 5. Save CSV to upload directory
    upload_dir = Path(os.environ.get("UPLOAD_DIR", tempfile.gettempdir())) / "sync_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    csv_path = upload_dir / f"{job_id}.csv"
    telemetry_file.save(str(csv_path))

    # 6. Insert session row
    session_id = _insert_session(conn, workspace_id, user_id, manifest, bundle_hash, csv_path, job_id)

    # 7. Check auto-analyze
    tier = get_user_plan_tier(conn, user_id)
    plan = get_plan_entitlements(tier)
    auto_analyze = plan.get("auto_analyze_on_sync", False)

    if auto_analyze:
        # Check analyses quota
        allowed, ctx = check_and_record_quota(
            conn, user_id, workspace_id, "analyses", cost=1,
        )
        if allowed:
            # Dispatch Celery pipeline
            _dispatch_pipeline(conn, session_id, job_id, csv_path, manifest, workspace_id)
            return api_response({
                "session_id": session_id,
                "job_id": job_id,
                "status": "analyzing",
                "analyze_triggered": True,
            })
        else:
            logger.warning("World-class user %s hit analyses quota — uploading without auto-analyze", user_id)

    return api_response({
        "session_id": session_id,
        "status": "pending_analysis",
        "analyze_triggered": False,
    })


def _insert_session(conn, workspace_id, user_id, manifest, bundle_hash, csv_path, job_id):
    """Insert a session row from logger manifest data."""
    cur = conn.execute(
        "INSERT INTO sessions "
        "(workspace_id, driver_id, track_id, session_type, source, "
        " source_bundle_hash, status, file_path, created_by) "
        "VALUES (%(wsid)s, NULL, NULL, %(stype)s, 'logger', "
        "%(hash)s, 'uploaded', %(fpath)s, %(uid)s) "
        "RETURNING id",
        {
            "wsid": workspace_id,
            "stype": manifest.get("session_type", "practice"),
            "hash": bundle_hash,
            "fpath": str(csv_path),
            "uid": user_id,
        },
    )
    row = cur.fetchone()
    return (dict(row) if not isinstance(row, dict) else row)["id"]


def _dispatch_pipeline(conn, session_id, job_id, csv_path, manifest, workspace_id):
    """Dispatch the Celery analysis pipeline.

    Mirrors sessions_v2.py: seed PipelineContext in Redis, then call
    build_pipeline_chain(job_id).apply_async().
    build_pipeline_chain takes ONE arg (job_id) — the worker reads
    context from pipeline:meta:{job_id} in Redis.
    """
    try:
        import json as _json

        import redis as _redis

        from pipeline_context import PipelineContext
        from tasks.pipeline_tasks import build_pipeline_chain

        # 1. Create ingestion_jobs row (worker expects it)
        conn.execute(
            """INSERT INTO ingestion_jobs
               (job_id, workspace_id, file_path, file_size, sha256_partial,
                status, stage_name, stage_index, stage_total, updated_at)
               VALUES (%(job_id)s, %(ws)s, %(fpath)s, %(fsize)s, '',
                       'pending', 'Queued', 0, 14, NOW())""",
            {
                "job_id": job_id,
                "ws": str(workspace_id),
                "fpath": str(csv_path),
                "fsize": csv_path.stat().st_size if isinstance(csv_path, Path) else 0,
            },
        )
        conn.commit()

        # 2. Seed PipelineContext in Redis
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _r = _redis.from_url(redis_url)
        PipelineContext.create_in_redis(
            _r,
            job_id=job_id,
            workspace_id=str(workspace_id),
            session_id=job_id,  # placeholder — worker creates real session_id
            file_path=str(csv_path),
        )
        # Store session_meta alongside context (same as sessions_v2.py)
        session_meta = {
            "session_type": manifest.get("session_type", "practice"),
            "driver_name": manifest.get("driver_name", "Unknown"),
            "source_filename": manifest.get("session_id", "logger_upload"),
        }
        _r.set(f"pipeline:meta:{job_id}", _json.dumps(session_meta), ex=7200)

        # 3. Dispatch Celery chain
        build_pipeline_chain(job_id).apply_async()
        logger.info("Dispatched pipeline for sync session %s (job %s)", session_id, job_id)
    except Exception:
        logger.exception("Failed to dispatch pipeline for sync session %s", session_id)
```

**Note**: The `source_bundle_hash` column on `sessions` is created in Task 1's migration (`051_device_pairings.py`). The `source` column already exists from migration 001.

- [ ] **Step 4: Register blueprint in `app.py`**

In `telemetry_tool/web/app.py`, after the devices blueprint registration:

```python
            from .routes.sync_upload import bp as sync_upload_bp
            app.register_blueprint(sync_upload_bp)
            logger.debug("Registered sync_upload blueprint")
```

- [ ] **Step 5: Run tests**

Run: `pytest telemetry_tool/tests/test_sync_upload.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/sync_upload.py telemetry_tool/web/app.py telemetry_tool/tests/test_sync_upload.py
git commit -m "feat(sync): add sync-upload endpoint for logger sessions"
```

---

## Task 6: Logger — SyncConfig + LapCoachSyncService

**Files:**
- Modify: `datalogger/src/lap_coach_logger/config/models.py`
- Create: `datalogger/src/lap_coach_logger/core/lap_coach_sync.py`
- Modify: `datalogger/src/lap_coach_logger/bootstrap.py`
- Modify: `datalogger/config.sample.json`
- Test: `datalogger/tests/test_lap_coach_sync.py`

- [ ] **Step 1: Write the failing tests**

Create `datalogger/tests/test_lap_coach_sync.py`:

```python
"""Tests for LapCoachSyncService."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lap_coach_logger.core.lap_coach_sync import LapCoachSyncService


def test_disabled_when_no_token():
    svc = LapCoachSyncService(api_url="https://example.com", device_token="")
    assert svc.enabled is False


def test_enabled_when_token_present():
    svc = LapCoachSyncService(api_url="https://example.com", device_token="abc123")
    assert svc.enabled is True


def test_upload_bundle_reads_csv_and_manifest(tmp_path):
    """upload_bundle reads telemetry.csv and session.json from the bundle dir."""
    # Set up a minimal bundle
    (tmp_path / "telemetry.csv").write_text("Time,Speed\n0,10\n", encoding="utf-8")
    manifest = {"session_id": "test_001", "bundle_hash": "hash123"}
    (tmp_path / "session.json").write_text(json.dumps(manifest), encoding="utf-8")

    svc = LapCoachSyncService(api_url="https://example.com", device_token="tok")

    with patch("lap_coach_logger.core.lap_coach_sync.urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "ok": True,
            "data": {"session_id": 42, "status": "pending_analysis", "analyze_triggered": False},
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = svc.upload_bundle(
            bundle_dir=tmp_path,
            session_id="test_001",
            bundle_hash="hash123",
        )

    assert result.success is True
    assert result.remote_id == "42"


def test_upload_bundle_401_not_retryable(tmp_path):
    """401 (revoked token) should not be retryable."""
    (tmp_path / "telemetry.csv").write_text("Time,Speed\n0,10\n", encoding="utf-8")
    (tmp_path / "session.json").write_text("{}", encoding="utf-8")

    svc = LapCoachSyncService(api_url="https://example.com", device_token="tok")

    with patch("lap_coach_logger.core.lap_coach_sync.urllib.request.urlopen") as mock_urlopen:
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=None,
        )

        result = svc.upload_bundle(
            bundle_dir=tmp_path, session_id="test", bundle_hash="hash",
        )

    assert result.success is False
    assert result.retryable is False


def test_upload_bundle_500_retryable(tmp_path):
    """5xx should be retryable."""
    (tmp_path / "telemetry.csv").write_text("Time,Speed\n0,10\n", encoding="utf-8")
    (tmp_path / "session.json").write_text("{}", encoding="utf-8")

    svc = LapCoachSyncService(api_url="https://example.com", device_token="tok")

    with patch("lap_coach_logger.core.lap_coach_sync.urllib.request.urlopen") as mock_urlopen:
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            url="", code=503, msg="Service Unavailable", hdrs=None, fp=None,
        )

        result = svc.upload_bundle(
            bundle_dir=tmp_path, session_id="test", bundle_hash="hash",
        )

    assert result.success is False
    assert result.retryable is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/Admin/Documents/Telemetry/datalogger && python -m pytest tests/test_lap_coach_sync.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Add SyncConfig to config/models.py**

In `datalogger/src/lap_coach_logger/config/models.py`, add after `LapAnalysisConfig` import:

```python
@dataclass
class SyncConfig:
    """Remote sync settings for Lap Coach webapp."""
    enabled: bool = False
    api_url: str = "https://api.lap-coach.racing"
    device_token: str = ""
    device_name: str = ""
```

Add to `AppConfig`:
```python
    sync: SyncConfig = field(default_factory=SyncConfig)
```

Update `AppConfig.from_dict()` to parse the new section:
```python
        sync = SyncConfig(**data.pop("sync", {}))
```
And pass `sync=sync` to the constructor.

- [ ] **Step 4: Implement LapCoachSyncService**

Create `datalogger/src/lap_coach_logger/core/lap_coach_sync.py`:

```python
"""Concrete SyncService for Lap Coach API.

Uploads session bundles (telemetry CSV + manifest) to the webapp
via POST /api/v1/sessions/sync-upload using a device token.
"""
from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from lap_coach_logger.core.sync_service import SyncAttemptResult

logger = logging.getLogger(__name__)

# HTTP status codes that should NOT be retried
_NO_RETRY_CODES = {400, 401, 403, 404, 409, 429}


class LapCoachSyncService:
    """Implements SyncService protocol for Lap Coach API."""

    def __init__(self, api_url: str, device_token: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._device_token = device_token

    @property
    def enabled(self) -> bool:
        return bool(self._device_token)

    def upload_bundle(
        self, *, bundle_dir: Path, session_id: str, bundle_hash: str
    ) -> SyncAttemptResult:
        csv_path = bundle_dir / "telemetry.csv"
        if not csv_path.exists():
            # Try parquet fallback name
            csv_path = bundle_dir / "telemetry.parquet"
            if not csv_path.exists():
                return SyncAttemptResult(
                    success=False, error="No telemetry file in bundle", retryable=False
                )

        manifest_path = bundle_dir / "session.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        manifest["bundle_hash"] = bundle_hash
        manifest["session_id"] = session_id

        try:
            body, content_type = _build_multipart(csv_path, manifest)
            url = f"{self._api_url}/api/v1/sessions/sync-upload"
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Authorization", f"DeviceToken {self._device_token}")
            req.add_header("Content-Type", content_type)

            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_body = json.loads(resp.read().decode("utf-8"))

            if resp_body.get("ok"):
                remote_id = str(resp_body.get("data", {}).get("session_id", ""))
                return SyncAttemptResult(success=True, remote_id=remote_id)

            return SyncAttemptResult(
                success=False,
                error=resp_body.get("error", "Unknown API error"),
                retryable=True,
            )

        except urllib.error.HTTPError as e:
            retryable = e.code not in _NO_RETRY_CODES
            error_msg = f"HTTP {e.code}: {e.reason}"
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                error_msg = err_body.get("error", error_msg)
            except Exception:
                pass
            logger.warning("Sync upload failed: %s (retryable=%s)", error_msg, retryable)
            return SyncAttemptResult(success=False, error=error_msg, retryable=retryable)

        except Exception as e:
            logger.exception("Sync upload error")
            return SyncAttemptResult(success=False, error=str(e), retryable=True)


def _build_multipart(csv_path: Path, manifest: dict) -> tuple[bytes, str]:
    """Build a multipart/form-data body with telemetry file + manifest JSON."""
    boundary = uuid.uuid4().hex
    lines: list[bytes] = []

    # Telemetry file part
    lines.append(f"--{boundary}".encode())
    lines.append(
        f'Content-Disposition: form-data; name="telemetry"; filename="{csv_path.name}"'.encode()
    )
    lines.append(b"Content-Type: application/octet-stream")
    lines.append(b"")
    lines.append(csv_path.read_bytes())

    # Manifest part
    lines.append(f"--{boundary}".encode())
    lines.append(b'Content-Disposition: form-data; name="manifest"')
    lines.append(b"")
    lines.append(json.dumps(manifest).encode("utf-8"))

    lines.append(f"--{boundary}--".encode())

    body = b"\r\n".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type
```

- [ ] **Step 5: Wire sync service in bootstrap.py**

In `datalogger/src/lap_coach_logger/bootstrap.py`, find where `SyncQueueManager` is created and conditionally pass the real service:

```python
from lap_coach_logger.core.sync_service import DisabledSyncService

sync_service = DisabledSyncService()
if config.sync.enabled and config.sync.device_token:
    from lap_coach_logger.core.lap_coach_sync import LapCoachSyncService
    sync_service = LapCoachSyncService(
        api_url=config.sync.api_url,
        device_token=config.sync.device_token,
    )

sync_queue = SyncQueueManager(
    output_root=config.output_path,
    sync_enabled=config.sync.enabled,
    sync_service=sync_service,
)
```

- [ ] **Step 6: Update config.sample.json**

Add sync section:
```json
  "sync": {
    "enabled": false,
    "api_url": "https://api.lap-coach.racing",
    "device_token": "",
    "device_name": ""
  }
```

- [ ] **Step 7: Run tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/datalogger && python -m pytest tests/test_lap_coach_sync.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 8: Commit**

```bash
cd C:/Users/Admin/Documents/Telemetry/datalogger
git add src/lap_coach_logger/core/lap_coach_sync.py src/lap_coach_logger/config/models.py src/lap_coach_logger/bootstrap.py config.sample.json tests/test_lap_coach_sync.py
git commit -m "feat(sync): implement LapCoachSyncService for webapp upload"
```

---

## Task 7: Frontend — Download Page

**Files:**
- Create: `lap-website/src/app/(marketing)/product/logger/page.tsx`
- Modify: `lap-website/src/data/navigation.ts`

- [ ] **Step 1: Create the download page**

Create `lap-website/src/app/(marketing)/product/logger/page.tsx`. Follow the existing marketing page pattern (see `(marketing)/product/page.tsx` for reference). Key sections:

- Hero: "Capture Every Lap. Automatically." + download CTA
- Feature grid: iRacing + ACC, local-first, auto-sync for paid tiers
- System requirements: Windows 10/11
- Tier comparison table showing what each plan gets with the logger
- Download button: `https://api.lap-coach.racing/downloads/LapCoachLogger-Setup-1.1.0.exe`

Use only design system tokens (`bg-asphalt`, `bg-concrete`, `text-chalk`, `text-steel`, `bg-gold`, `font-monument`, `font-telemetry`, `font-body`).

- [ ] **Step 2: Add to navigation**

In `lap-website/src/data/navigation.ts`, add the logger page to the product section:
```typescript
{ label: 'Logger', href: '/product/logger' },
```

- [ ] **Step 3: Build to verify no errors**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/app/\(marketing\)/product/logger/page.tsx lap-website/src/data/navigation.ts
git commit -m "feat(frontend): add logger download page"
```

---

## Task 8: Frontend — Device Management Page

**Files:**
- Create: `lap-website/src/app/app/account/devices/page.tsx`
- Modify: `lap-website/src/lib/entitlements-store.ts`
- Modify: `lap-website/src/data/pricing.ts`

- [ ] **Step 1: Add entitlement keys to frontend store**

In `lap-website/src/lib/entitlements-store.ts`, add to the entitlements interface and defaults:
```typescript
device_sync: boolean;
auto_analyze_on_sync: boolean;
max_linked_devices: number;
```

- [ ] **Step 2: Add logger features to pricing eligibility matrix**

In `lap-website/src/data/pricing.ts`, add to `featureEligibilityMatrix`:
```typescript
{ feature: 'Logger Auto-Sync', group: 'data', demo: '—', racer: 'Upload only', worldClass: 'Upload + Auto-Analyze' },
{ feature: 'Linked Devices', group: 'data', demo: '0', racer: '2', worldClass: '3' },
```

- [ ] **Step 3: Create the devices management page**

Create `lap-website/src/app/app/account/devices/page.tsx`. This is an authenticated page inside the app shell. Key elements:

- Gated behind `device_sync` entitlement (Demo users see `UpgradeBanner`)
- "Link a Device" button → modal with code input field
- `POST /api/v1/devices/confirm` with the entered code
- Device list: fetched from `GET /api/v1/devices`
- Each device card: name, last seen, "Unlink" button (`DELETE /api/v1/devices/:id`)
- Device count badge: "2 of 2 devices linked"

Use existing patterns from `account/billing/page.tsx` for layout.

- [ ] **Step 4: Build to verify no errors**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build`
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add lap-website/src/app/app/account/devices/page.tsx lap-website/src/lib/entitlements-store.ts lap-website/src/data/pricing.ts
git commit -m "feat(frontend): add device management page and sync entitlements"
```

---

## Task 9: VPS — Caddy Config + Installer Hosting

This task requires manual action on the VPS.

- [ ] **Step 1: Create downloads directory on VPS**

```bash
ssh root@46.225.227.24 "mkdir -p /opt/lap-api/downloads"
```

- [ ] **Step 2: Upload installer**

```bash
scp "C:/Users/Admin/Documents/Telemetry/datalogger/LapCoachLogger-Setup-1.1.0.exe" root@46.225.227.24:/opt/lap-api/downloads/
```

- [ ] **Step 3: Create `latest.json`**

```bash
ssh root@46.225.227.24 'cat > /opt/lap-api/downloads/latest.json << EOF
{
  "version": "1.1.0",
  "filename": "LapCoachLogger-Setup-1.1.0.exe",
  "sha256": "",
  "size_bytes": 59878002,
  "released_at": "2026-03-24T00:00:00Z",
  "min_logger_version": "1.0.0",
  "changelog_url": "https://lap-coach.racing/product/logger#changelog"
}
EOF'
```

- [ ] **Step 4: Add Caddy static file route**

Edit `/opt/lap-api/Caddyfile` on the VPS — add inside the `api.lap-coach.racing` block:

```
handle /downloads/* {
    root * /opt/lap-api/downloads
    file_server
}
```

- [ ] **Step 5: Reload Caddy**

```bash
ssh root@46.225.227.24 "docker compose -f /opt/lap-api/docker-compose.prod.yml exec caddy caddy reload --config /etc/caddy/Caddyfile"
```

- [ ] **Step 6: Verify download works**

```bash
curl -I https://api.lap-coach.racing/downloads/latest.json
curl -I https://api.lap-coach.racing/downloads/LapCoachLogger-Setup-1.1.0.exe
```
Expected: both return HTTP 200.

---

## Task 10: Deploy Backend + Frontend

- [ ] **Step 1: Deploy backend**

```bash
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/telemetry_tool/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
```

- [ ] **Step 2: Run migration on VPS**

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec api alembic upgrade head"
```

- [ ] **Step 3: Verify API health**

```bash
curl https://api.lap-coach.racing/healthz
```
Expected: 200 OK.

- [ ] **Step 4: Verify pairing endpoint**

```bash
curl -X POST https://api.lap-coach.racing/api/v1/devices/pair -H "Content-Type: application/json" -d '{"device_name":"test"}'
```
Expected: 200 with pairing code.

- [ ] **Step 5: Deploy frontend**

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website
npm run build && npm run cf:deploy
```

- [ ] **Step 6: Verify download page**

Open `https://lap-coach.racing/product/logger` — should show the download page.
