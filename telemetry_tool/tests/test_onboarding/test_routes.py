"""Test web/routes/onboarding_routes.py (Task 12): the two token-authed
onboarding HTTP endpoints, the auth-middleware allowlist entries for them,
and OPTIONS/CORS preflight.

Token auth is exercised for REAL -- a real ``ONBOARDING_TOKEN_SECRET`` plus
real ``onboarding.tokens.mint``/``verify`` -- since that IS the security
boundary under test (mocking it would test nothing). ``repo``,
``load_draft``, ``bless_geometry``, and ``reprocess_after_bless`` are
monkeypatched on the ``onboarding_routes`` module: there is no live
Postgres/Celery broker in this environment (same constraint documented by
every other onboarding task's tests, e.g. ``test_reprocess.py``).

Imports are bare (``from web.routes... import ...``, no manual sys.path/
``telemetry_tool.`` prefix) to match ``tests/test_auth_middleware.py`` --
the closest existing analog (a Flask-test-client route test) -- and, more
importantly, so the module object under test here is the SAME one
``onboarding_routes.py`` itself uses internally (its own imports are bare,
e.g. ``from onboarding import repo``); a mixed bare/``telemetry_tool.``-
prefixed import would load two separate copies and monkeypatching one
would silently not affect the other.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

from onboarding.bless_service import BlessResult
from onboarding.draft import DraftError
from onboarding.tokens import mint
from web.api_utils import init_request_id
from web.middleware.auth import auth_middleware
from web.middleware.cors import init_cors
from web.routes import onboarding_routes

_SECRET = "test-onboarding-secret"
_ANNOTATOR_HOST = "https://annotator.example.com"


def _make_app(*, auth_required: bool = True, cors_origins: str = _ANNOTATOR_HOST) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["AUTH_REQUIRED"] = auth_required
    app.config["JWT_SECRET"] = "unrelated-jwt-secret"
    app.config["CORS_ALLOWED_ORIGINS"] = cors_origins
    init_request_id(app)
    init_cors(app)
    if auth_required:
        app.before_request(auth_middleware)
    app.register_blueprint(onboarding_routes.bp)
    return app


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ONBOARDING_TOKEN_SECRET", _SECRET)
    monkeypatch.setenv("ONBOARDING_OPERATOR_EMAIL", "ops@example.com")


def _row(**overrides) -> dict:
    base = dict(
        id="req-1", track_key="kct_onb", track_label="KCT", fingerprint=None,
        status="emailed", bbox=None, first_session_ref="sess-1",
        session_refs=["sess-1", "sess-2"], session_count=2,
        vehicle_classes=[],
        draft_status="gps_only", draft_path="/tmp/req-1.geojson",
        token_jti=None, error=None, created_at=None, updated_at=None,
        emailed_at=None, blessed_at=None,
    )
    base.update(overrides)
    return base


@pytest.fixture
def fake_repo(monkeypatch):
    fake = MagicMock(name="repo")
    monkeypatch.setattr(onboarding_routes, "repo", fake)
    return fake


@pytest.fixture(autouse=True)
def fake_conn_helpers(monkeypatch):
    conn = MagicMock(name="conn")
    monkeypatch.setattr(onboarding_routes, "get_maint_connection", MagicMock(return_value=conn))
    monkeypatch.setattr(onboarding_routes, "return_pg_connection", MagicMock())
    return conn


@pytest.fixture
def fake_draft(monkeypatch):
    fake = MagicMock(
        name="load_draft",
        return_value={"type": "FeatureCollection", "features": []},
    )
    monkeypatch.setattr(onboarding_routes, "load_draft", fake)
    return fake


@pytest.fixture
def fake_bless(monkeypatch):
    fake = MagicMock(name="bless_geometry", return_value=BlessResult(ok=True, failures=[]))
    monkeypatch.setattr(onboarding_routes, "bless_geometry", fake)
    return fake


@pytest.fixture
def fake_reprocess(monkeypatch):
    fake = MagicMock(name="reprocess_after_bless")
    monkeypatch.setattr(onboarding_routes, "reprocess_after_bless", fake)
    return fake


# ---------------------------------------------------------------------------
# Auth-middleware allowlist: exact-match, not prefix
# ---------------------------------------------------------------------------

class TestAuthMiddlewareAllowlist:
    def test_draft_path_bypasses_jwt_reaches_route(self, fake_repo):
        fake_repo.get.return_value = None  # -> route's own generic 401
        app = _make_app(auth_required=True)
        resp = app.test_client().get("/api/v1/onboarding/draft?req=req-1")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["message"] == onboarding_routes._GENERIC_AUTH_ERROR

    def test_save_path_bypasses_jwt_reaches_route(self, fake_repo):
        fake_repo.get.return_value = None  # -> route's own generic 401
        app = _make_app(auth_required=True)
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={"request_id": "req-1", "geometry": {}},
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"]["message"] == onboarding_routes._GENERIC_AUTH_ERROR

    def test_sibling_onboarding_path_still_requires_jwt(self):
        """Exact-match allowlist: a made-up neighbour path is NOT exempted."""
        app = _make_app(auth_required=True)
        resp = app.test_client().get("/api/v1/onboarding/other")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["message"] == "Authentication required"


# ---------------------------------------------------------------------------
# GET /api/v1/onboarding/draft
# ---------------------------------------------------------------------------

class TestGetDraft:
    def test_valid_token_returns_draft(self, fake_repo, fake_draft):
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().get(
            "/api/v1/onboarding/draft?req=req-1",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"] == {"type": "FeatureCollection", "features": []}
        fake_draft.assert_called_once_with("req-1")

    def test_missing_token_401(self, fake_repo):
        fake_repo.get.return_value = _row(token_jti="whatever")
        app = _make_app()
        resp = app.test_client().get("/api/v1/onboarding/draft?req=req-1")
        assert resp.status_code == 401

    def test_expired_token_401(self, fake_repo, monkeypatch):
        monkeypatch.setenv("ONBOARDING_TOKEN_TTL_HOURS", "-1")
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().get(
            "/api/v1/onboarding/draft?req=req-1",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 401

    def test_tampered_token_401(self, fake_repo):
        tok, jti = mint("req-1")
        payload_b64, _sig_b64 = tok.split(".")
        tampered = payload_b64 + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().get(
            "/api/v1/onboarding/draft?req=req-1",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert resp.status_code == 401

    def test_wrong_request_id_401(self, fake_repo):
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().get(
            "/api/v1/onboarding/draft?req=req-OTHER",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 401

    def test_jti_mismatch_401(self, fake_repo):
        """Row's token_jti no longer matches the presented token (already
        consumed by a prior save, or rotated) -- must be refused."""
        tok, _jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti="a-different-jti")
        app = _make_app()
        resp = app.test_client().get(
            "/api/v1/onboarding/draft?req=req-1",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/onboarding/save
# ---------------------------------------------------------------------------

class TestPostSave:
    def test_valid_bless_ok_blesses_revokes_token_and_reprocesses(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess,
    ):
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(
            token_jti=jti, track_key="kct_onb", session_refs=["s1", "s2"],
        )
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["status"] == "blessed"

        fake_repo.set_status.assert_called_once()
        args, kwargs = fake_repo.set_status.call_args
        assert args[1] == "req-1"
        assert args[2] == "blessed"
        assert kwargs["token_jti"] is None  # single-use token revoked

        fake_reprocess.assert_called_once()
        _, rkwargs = fake_reprocess.call_args
        assert rkwargs["track_key"] == "kct_onb"
        assert rkwargs["canonical_id"] == "kct_onb"
        assert rkwargs["session_refs"] == ["s1", "s2"]

    def test_missing_operator_email_env_returns_503_not_500(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess, monkeypatch,
    ):
        """Final-review M2: an unset ONBOARDING_OPERATOR_EMAIL must degrade to
        a clean 503 (deny-safe: nothing blessed), not KeyError->500."""
        monkeypatch.delenv("ONBOARDING_OPERATOR_EMAIL", raising=False)
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti, track_key="kct_onb")
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 503
        fake_bless.assert_not_called()          # nothing reaches the trust store
        fake_repo.set_status.assert_not_called()  # nothing blessed

    def test_vehicle_classes_row_derived_reach_reprocess_after_bless(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess,
    ):
        """Final-review finding I2: the row's vehicle_classes (now that
        migration 081 has the column and s10d_surface's trigger populates
        it) must actually flow into reprocess_after_bless, or the 30-min
        fast-path compute_racing_lines enqueue never fires for a non-generic
        class."""
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(
            token_jti=jti, track_key="kct_onb", vehicle_classes=["gt3", "gt4"],
        )
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200

        fake_reprocess.assert_called_once()
        _, rkwargs = fake_reprocess.call_args
        assert rkwargs["vehicle_classes"] == ["gt3", "gt4"]

    def test_missing_vehicle_classes_forwards_empty_list(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess,
    ):
        """A row predating the vehicle_classes column (or a NULL value)
        must forward [] rather than raising."""
        tok, jti = mint("req-1")
        row = _row(token_jti=jti, track_key="kct_onb")
        del row["vehicle_classes"]
        fake_repo.get.return_value = row
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200

        _, rkwargs = fake_reprocess.call_args
        assert rkwargs["vehicle_classes"] == []

    def test_bless_not_ok_returns_422_and_does_not_revoke_token(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess,
    ):
        fake_bless.return_value = BlessResult(ok=False, failures=["unreviewed_draft"])
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["details"] == [{"failure": "unreviewed_draft"}]
        fake_repo.set_status.assert_not_called()  # retry-able: token stays valid
        fake_reprocess.assert_not_called()

    def test_canonical_id_is_row_derived_not_body(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess,
    ):
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti, track_key="real_canonical")
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
                "canonical_id": "attacker",
                "track_key": "attacker-track",
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200
        _, bkwargs = fake_bless.call_args
        assert bkwargs["canonical_id"] == "real_canonical"

    def test_missing_token_401(self, fake_repo):
        fake_repo.get.return_value = _row(token_jti="whatever")
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={"request_id": "req-1", "geometry": {}},
        )
        assert resp.status_code == 401

    def test_query_string_only_token_401_save_is_header_only(self, fake_repo):
        """Finding 1: unlike GET /draft, POST /save must NOT accept a
        ``?token=`` fallback -- a valid token supplied ONLY via the query
        string (no Authorization header) must be refused."""
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().post(
            f"/api/v1/onboarding/save?token={tok}",
            json={"request_id": "req-1", "geometry": {"type": "FeatureCollection", "features": []}},
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"]["message"] == onboarding_routes._GENERIC_AUTH_ERROR

    def test_bless_called_with_load_draft_result(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess,
    ):
        """Finding 2 (wiring): ``bless_geometry`` must be given the SAME
        auto-draft that ``load_draft(request_id)`` returned, not some
        derived/None value."""
        sentinel_draft = {"type": "FeatureCollection", "features": [{"id": "sentinel"}]}
        fake_draft.return_value = sentinel_draft
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200
        _, bkwargs = fake_bless.call_args
        assert bkwargs["auto_draft_geojson"] is sentinel_draft

    def test_missing_draft_returns_422_draft_missing_no_bless_no_revoke(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess,
    ):
        """Finding 2: a missing draft file must NOT silently disable the
        unreviewed-draft gate (``auto_draft=None`` bypass) -- it must 422
        with ``draft_missing`` and leave the token/bless/reprocess alone so
        the operator can retry once the draft is restored."""
        fake_draft.side_effect = DraftError("no draft on disk for request_id")
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["details"] == [{"failure": "draft_missing"}]
        fake_bless.assert_not_called()
        fake_repo.set_status.assert_not_called()  # token NOT revoked
        fake_reprocess.assert_not_called()

    def test_set_status_noop_returns_200_idempotent_without_reprocess(
        self, fake_repo, fake_draft, fake_bless, fake_reprocess,
    ):
        """Minor 4: if ``set_status`` updates no row (already blessed by a
        concurrent/duplicate save), the route must still report success
        idempotently but must NOT re-run reprocess for a bless it didn't
        perform."""
        fake_repo.set_status.return_value = False
        tok, jti = mint("req-1")
        fake_repo.get.return_value = _row(token_jti=jti)
        app = _make_app()
        resp = app.test_client().post(
            "/api/v1/onboarding/save",
            json={
                "request_id": "req-1",
                "geometry": {"type": "FeatureCollection", "features": []},
            },
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["status"] == "blessed"
        fake_reprocess.assert_not_called()


# ---------------------------------------------------------------------------
# Rate-limit bucket key (Finding 3): IP-only, no request_id
# ---------------------------------------------------------------------------

class TestScopedRateLimitKey:
    def test_workspace_id_key_is_ip_only_regardless_of_request_id(self):
        """A caller varying ``request_id`` (attacker-controlled, read
        pre-auth) across requests must land in the SAME rate-limit bucket
        -- the key must be derived from client IP alone."""
        probe_app = Flask(__name__)

        @probe_app.route("/x", methods=["POST"])
        @onboarding_routes._scoped_rate_limit
        def _probe():
            from flask import g as flask_g
            return {"workspace_id": flask_g.workspace_id}

        client = probe_app.test_client()
        resp_a = client.post("/x", json={"request_id": "req-A-attacker-controlled"})
        resp_b = client.post("/x", json={"request_id": "req-B-different-guess"})

        key_a = resp_a.get_json()["workspace_id"]
        key_b = resp_b.get_json()["workspace_id"]
        assert key_a == key_b
        assert "req-A" not in key_a
        assert "req-B" not in key_b
        assert key_a == "onboarding:127.0.0.1"


# ---------------------------------------------------------------------------
# OPTIONS preflight / CORS
# ---------------------------------------------------------------------------

class TestOptionsCors:
    def test_options_draft_returns_cors_headers_for_annotator_origin(self):
        app = _make_app()
        resp = app.test_client().options(
            "/api/v1/onboarding/draft",
            headers={"Origin": _ANNOTATOR_HOST, "Access-Control-Request-Method": "GET"},
        )
        assert resp.status_code == 204
        assert resp.headers.get("Access-Control-Allow-Origin") == _ANNOTATOR_HOST

    def test_options_save_returns_cors_headers_for_annotator_origin(self):
        app = _make_app()
        resp = app.test_client().options(
            "/api/v1/onboarding/save",
            headers={"Origin": _ANNOTATOR_HOST, "Access-Control-Request-Method": "POST"},
        )
        assert resp.status_code == 204
        assert resp.headers.get("Access-Control-Allow-Origin") == _ANNOTATOR_HOST

    def test_options_rejects_unrecognised_origin(self):
        app = _make_app()
        resp = app.test_client().options(
            "/api/v1/onboarding/draft",
            headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
        )
        assert resp.status_code == 204
        assert "Access-Control-Allow-Origin" not in resp.headers
