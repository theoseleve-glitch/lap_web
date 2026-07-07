"""IDOR regression tests -- two confirmed cross-tenant BLOCKERs.

BLOCKER #1 (web/routes/theoretical.py): ``_load_session_raw_data`` built
``<sidecar_root>/<session_id>/raw_sidecar.parquet`` directly from the
client-supplied ``session_id`` path param with NO DB query at all, so the
RLS backstop (which only guards rows reached through the request's
RLS-scoped connection) never applied. Any authenticated tenant could read
another tenant's raw telemetry off disk via GET .../theoretical{,/delta,
/corners}. Fixed by resolving ``session_id`` via
``models.get_session_by_id()`` on the RLS-scoped request connection *before*
any filesystem access -- the same ownership check ~20 sibling routes in
data_v2.py already use. A ``None`` result (RLS-hidden or genuinely missing)
now fails closed with the route's existing "not available" 404 shape.

BLOCKER #2 (web/routes/data_v2.py): GET/POST
``/api/v1/sessions/<id>/user-corners`` queried/wrote the ``user_corners``
table filtered ONLY by client ``session_id``, skipping the
``models.get_session_by_id`` ownership check every sibling route uses --
and the table itself carried no RLS (migration 059 created it, but it was
never covered by 007/064/068/069/073). Tenant A could read AND overwrite
tenant B's corner apex/entry/exit GPS. Fixed with (a) migration
``082_user_corners_rls`` (FK-child RLS policy, mirroring 068's USING-via-
parent idiom + 069/073/081's FORCE + WITH CHECK) and (b) the same
app-level 404-if-not-visible guard as (1), as defense-in-depth for
SQLite/no-RLS deployments.

Mock-based tests follow tests/test_api_contracts.py's ``mock_client`` /
``patch("web.routes.<module>.models")`` convention: deterministic, no real
DB. A PG-gated class at the bottom (skipped without ``TELEMETRY_PG_URL_TEST``)
additionally proves migration 082's policy itself -- not just the app-level
guard -- blocks a cross-workspace row, mirroring
tests/test_rls_isolation.py and tests/integration/test_corner_mastery_pg.py.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _session(session_id: str = "s1") -> dict:
    """Minimal session dict shape returned by models.get_session_by_id."""
    return {
        "session_id": session_id,
        "csv_filename": f"{session_id}.csv",
        "driver_id": 1,
        "track_id": "t1",
        "session_date": "2024-01-01",
        "workspace_id": 1,
    }


def _assert_error_envelope(body: dict, expected_code: str | None = None) -> None:
    assert body["ok"] is False
    assert isinstance(body["error"], dict)
    assert len(body["error"]["message"]) > 0
    if expected_code is not None:
        assert body["error"]["code"] == expected_code, body["error"]


# ══════════════════════════════════════════════════════════════════════
# BLOCKER #1 -- theoretical.py raw-sidecar read guard
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def theoretical_client():
    """Minimal Flask app with only the theoretical blueprint -- no real DB."""
    from flask import Flask
    from web.routes.theoretical import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app.test_client()


_THEORETICAL_PATHS = [
    "/api/v1/sessions/foreign-session/theoretical",
    "/api/v1/sessions/foreign-session/theoretical/delta",
    "/api/v1/sessions/foreign-session/theoretical/corners",
]


class TestTheoreticalIdorGuard:

    @pytest.mark.parametrize("path", _THEORETICAL_PATHS)
    def test_404_when_session_not_visible_to_caller(self, theoretical_client, path):
        """A session_id outside the caller's workspace must 404 and must
        NEVER reach the filesystem sidecar loader."""
        with patch("web.routes.theoretical.get_db_connection") as mock_db, \
                patch("web.routes.theoretical.models") as mock_models, \
                patch("web.routes.theoretical._get_sidecar_root") as mock_root:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None  # not visible

            resp = theoretical_client.get(path)

            assert resp.status_code == 404, resp.get_data(as_text=True)
            body = resp.get_json()
            _assert_error_envelope(body)
            assert "Session not found" in body["error"]["message"]
            mock_root.assert_not_called()  # guard fires before any disk access

    @pytest.mark.parametrize("path", [p.replace("foreign-session", "owned-session")
                                       for p in _THEORETICAL_PATHS])
    def test_owned_session_passes_guard(self, theoretical_client, path, tmp_path):
        """A session visible to the caller must pass the ownership guard and
        reach the (here empty, so still 404) sidecar lookup -- proving the
        guard doesn't block legitimate same-tenant access."""
        with patch("web.routes.theoretical.get_db_connection") as mock_db, \
                patch("web.routes.theoretical.models") as mock_models, \
                patch("web.routes.theoretical._get_sidecar_root", return_value=tmp_path):
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = _session("owned-session")

            resp = theoretical_client.get(path)

            assert resp.status_code == 404, resp.get_data(as_text=True)
            body = resp.get_json()
            # 404 here is "sidecar not available" (no parquet in tmp_path),
            # NOT the ownership guard -- proves the guard was passed.
            assert "Session not found" not in body["error"]["message"]


# ══════════════════════════════════════════════════════════════════════
# BLOCKER #2 -- user_corners ownership guard (data_v2.py)
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def data_v2_client():
    """Minimal Flask app with only the data_v2 blueprint -- no real DB."""
    from flask import Flask
    from web.routes.data_v2 import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.register_blueprint(bp)
    return app.test_client()


class TestUserCornersIdorGuard:

    def test_get_404_on_foreign_session(self, data_v2_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models:
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.return_value = None

            resp = data_v2_client.get("/api/v1/sessions/foreign-session/user-corners")

        assert resp.status_code == 404, resp.get_data(as_text=True)
        _assert_error_envelope(resp.get_json(), expected_code="NOT_FOUND")
        mock_conn.execute.assert_not_called()  # never touched user_corners

    def test_post_404_on_foreign_session(self, data_v2_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models:
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.return_value = None

            resp = data_v2_client.post(
                "/api/v1/sessions/foreign-session/user-corners",
                json={"corners": [{"corner_index": 1, "lat_entry": 45.0, "lon_entry": 7.0}]},
            )

        assert resp.status_code == 404, resp.get_data(as_text=True)
        _assert_error_envelope(resp.get_json(), expected_code="NOT_FOUND")
        mock_conn.execute.assert_not_called()  # guard fires before the INSERT

    def test_get_200_on_owned_session(self, data_v2_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.return_value = _session("owned-session")

            resp = data_v2_client.get("/api/v1/sessions/owned-session/user-corners")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["corners"] == []

    def test_post_200_on_owned_session(self, data_v2_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models:
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            mock_models.get_session_by_id.return_value = _session("owned-session")

            resp = data_v2_client.post(
                "/api/v1/sessions/owned-session/user-corners",
                json={"corners": [{"corner_index": 1, "lat_entry": 45.0, "lon_entry": 7.0}]},
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["saved"] == 1
        mock_conn.execute.assert_called()  # the INSERT was actually attempted


# ══════════════════════════════════════════════════════════════════════
# PG-gated -- migration 082's RLS policy itself blocks cross-tenant access
#
# Assumes the disposable DB pointed to by TELEMETRY_PG_URL_TEST is already
# migrated to head (same assumption as
# tests/integration/test_corner_mastery_pg.py) -- run
# `python -m alembic upgrade head` against TELEMETRY_PG_URL_TEST first if
# starting from an empty database. Never point this at production.
# ══════════════════════════════════════════════════════════════════════

_pg_test_url = os.environ.get("TELEMETRY_PG_URL_TEST", "")
_skip_no_pg = pytest.mark.skipif(
    not _pg_test_url,
    reason="needs a disposable PG; set TELEMETRY_PG_URL_TEST",
)


def _app_role_dsn() -> str:
    """Swap the DSN's user for telemetry_app (trust auth, no password)."""
    url = os.environ["TELEMETRY_PG_URL_TEST"]
    scheme, rest = url.split("://", 1)
    hostpart = rest.split("@", 1)[-1]
    return f"{scheme}://telemetry_app@{hostpart}"


@_skip_no_pg
class TestUserCornersRlsPolicy:
    """Real PG, real telemetry_app role -- proves the migration 082 policy,
    not just the app-level guard, blocks cross-tenant user_corners access."""

    @pytest.fixture()
    def seeded_two_workspaces(self):
        import psycopg2
        import psycopg2.extras

        orig_use_pg = os.environ.get("USE_PG")
        os.environ["USE_PG"] = "1"

        dsn = os.environ["TELEMETRY_PG_URL_TEST"]
        raw = psycopg2.connect(dsn)
        raw.cursor_factory = psycopg2.extras.RealDictCursor
        raw.autocommit = False

        from web.db_pg import PgConnectionWrapper
        conn = PgConnectionWrapper(raw)

        pid = os.getpid()
        suffix = uuid.uuid4().hex[:8]
        seeded: dict[str, list] = {"user": [], "ws": [], "driver": [], "track": [], "session": []}

        def _seed_workspace(tag: str):
            email = f"uc{pid}_{suffix}_{tag}@t.local"
            driver_name = f"drv_uc_{pid}_{suffix}_{tag}"
            track_id = f"trk-uc-{pid}-{suffix}-{tag}"
            session_id = f"ses-uc-{pid}-{suffix}-{tag}"

            cur = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (:email, 'x') RETURNING id",
                {"email": email},
            )
            user_id = cur.fetchone()["id"]
            cur = conn.execute(
                "INSERT INTO workspaces (type, owner_user_id, display_name) "
                "VALUES ('personal', :uid, 'WS') RETURNING id",
                {"uid": user_id},
            )
            ws_id = cur.fetchone()["id"]
            conn.execute("SET app.current_workspace_id = %s" % int(ws_id))
            cur = conn.execute(
                "INSERT INTO drivers (driver_name, workspace_id) "
                "VALUES (:name, :ws) RETURNING driver_id",
                {"name": driver_name, "ws": ws_id},
            )
            driver_id = cur.fetchone()["driver_id"]
            conn.execute(
                "INSERT INTO tracks (track_id, track_name, lap_length_m, workspace_id) "
                "VALUES (:tid, 'T', 1.0, :ws)",
                {"tid": track_id, "ws": ws_id},
            )
            conn.execute(
                "INSERT INTO sessions "
                "(session_id, csv_filename, driver_id, track_id, session_date, workspace_id) "
                "VALUES (:sid, 'f.csv', :drv, :trk, '2026-06-07', :ws)",
                {"sid": session_id, "drv": driver_id, "trk": track_id, "ws": ws_id},
            )
            seeded["user"].append(user_id)
            seeded["ws"].append(ws_id)
            seeded["driver"].append(driver_id)
            seeded["track"].append(track_id)
            seeded["session"].append(session_id)
            return ws_id, session_id

        try:
            ws_a, sid_a = _seed_workspace("a")
            ws_b, sid_b = _seed_workspace("b")

            # Seed a user_corners row for A's session as the migration/owner
            # role (bypasses RLS for setup, mirrors test_rls_isolation.py).
            conn.execute(
                "INSERT INTO user_corners (session_id, corner_index, lat_entry, lon_entry) "
                "VALUES (:sid, 1, 45.0, 7.0)",
                {"sid": sid_a},
            )
            raw.commit()

            yield ws_a, sid_a, ws_b, sid_b

        finally:
            try:
                for sid in seeded["session"]:
                    conn.execute("DELETE FROM user_corners WHERE session_id = :sid", {"sid": sid})
                for sid in seeded["session"]:
                    conn.execute("DELETE FROM sessions WHERE session_id = :sid", {"sid": sid})
                for tid in seeded["track"]:
                    conn.execute("DELETE FROM tracks WHERE track_id = :tid", {"tid": tid})
                for drv in seeded["driver"]:
                    conn.execute("DELETE FROM drivers WHERE driver_id = :drv", {"drv": drv})
                for ws in seeded["ws"]:
                    conn.execute("DELETE FROM workspaces WHERE id = :ws", {"ws": ws})
                for uid in seeded["user"]:
                    conn.execute("DELETE FROM users WHERE id = :uid", {"uid": uid})
                raw.commit()
            except Exception:
                raw.rollback()
            finally:
                try:
                    raw.close()
                except Exception:
                    pass
                if orig_use_pg is None:
                    os.environ.pop("USE_PG", None)
                else:
                    os.environ["USE_PG"] = orig_use_pg

    def test_cross_workspace_select_returns_nothing(self, seeded_two_workspaces):
        import psycopg2

        ws_a, sid_a, ws_b, sid_b = seeded_two_workspaces

        app_conn = psycopg2.connect(_app_role_dsn())
        cur = app_conn.cursor()
        cur.execute("SET LOCAL app.current_workspace_id = %s", (str(ws_b),))
        cur.execute("SELECT count(*) FROM user_corners WHERE session_id = %s", (sid_a,))
        count = cur.fetchone()[0]
        app_conn.close()

        assert count == 0, "workspace B must not see workspace A's user_corners row"

    def test_cross_workspace_insert_rejected(self, seeded_two_workspaces):
        import psycopg2

        ws_a, sid_a, ws_b, sid_b = seeded_two_workspaces

        app_conn = psycopg2.connect(_app_role_dsn())
        cur = app_conn.cursor()
        cur.execute("SET LOCAL app.current_workspace_id = %s", (str(ws_b),))
        with pytest.raises(psycopg2.Error) as exc_info:
            cur.execute(
                "INSERT INTO user_corners (session_id, corner_index, lat_entry) "
                "VALUES (%s, 2, 1.0)",
                (sid_a,),
            )
        app_conn.close()

        assert "row-level security" in str(exc_info.value).lower()
