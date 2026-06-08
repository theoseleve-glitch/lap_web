"""Tests for GET /api/v1/admin/overview — 4-lens consolidated cockpit payload."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_app():
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    from web.routes.admin.overview import bp as overview_bp
    app.register_blueprint(overview_bp, url_prefix="/api/v1/admin")
    return app


def _admin_ctx():
    from flask import g
    g.current_user_id = 99
    g.admin_user = {"is_superadmin": True, "admin_role": "root_admin", "totp_enabled": True}
    g.admin_verified = True


def _seeded_conn():
    """A conn whose every scalar aggregate returns a deterministic value."""
    conn = MagicMock()

    def _execute(sql, params=None):
        cur = MagicMock()
        s = " ".join(sql.split()).lower()
        if "from users" in s and "count" in s and "subscription_status = 'active'" in s:
            cur.fetchone.return_value = {"n": 7}
        elif "from users" in s and "count" in s:
            cur.fetchone.return_value = {"n": 42}
        elif "from app_events" in s and "count(distinct user_id)" in s and "current_date" in s:
            cur.fetchone.return_value = {"n": 5}
        elif "from app_events" in s and "count(distinct user_id)" in s:
            cur.fetchone.return_value = {"n": 11}
        elif "from app_events" in s:
            cur.fetchone.return_value = {"n": 300}
        elif "from marketing_events" in s:
            cur.fetchone.return_value = {"n": 1200}
        elif "from ingestion_jobs" in s:
            cur.fetchone.return_value = {"n": 3}
        else:
            cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        return cur

    conn.execute.side_effect = _execute
    return conn


class TestAdminOverview:
    def test_returns_four_lenses_with_seeded_counts(self):
        app = _make_app()
        with app.test_request_context("/api/v1/admin/overview"):
            _admin_ctx()
            with patch("web.routes.admin.overview._get_overview_conn", return_value=_seeded_conn()), \
                 patch("web.routes.admin.overview._get_redis", return_value=None), \
                 patch("web.routes.admin.overview.log_admin_action") as mock_audit:
                from web.routes.admin.overview import overview
                resp = overview()
                data = (resp[0] if isinstance(resp, tuple) else resp).get_json()

        assert data["ok"] is True
        d = data["data"]
        assert d["business"]["active_subscribers"] == 7
        assert d["product"]["dau_today"] == 5
        assert d["product"]["wau_7d"] == 11
        assert d["growth"]["marketing_pageviews_7d"] == 1200
        assert d["live_ops"]["jobs_active"] == 3
        assert d["cached"] is False
        mock_audit.assert_called_once()
        assert mock_audit.call_args.args[2] == "overview_viewed"

    def test_second_call_is_cache_hit(self):
        app = _make_app()
        store = {}
        redis = MagicMock()
        redis.get.side_effect = lambda k: store.get(k)
        redis.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v)

        with app.test_request_context("/api/v1/admin/overview"):
            _admin_ctx()
            with patch("web.routes.admin.overview._get_overview_conn", return_value=_seeded_conn()), \
                 patch("web.routes.admin.overview._get_redis", return_value=redis), \
                 patch("web.routes.admin.overview.log_admin_action"):
                from web.routes.admin.overview import overview
                first = (overview()).get_json() if not isinstance(overview(), tuple) else None

        # second request reuses the cached body
        with app.test_request_context("/api/v1/admin/overview"):
            _admin_ctx()
            with patch("web.routes.admin.overview._get_overview_conn") as conn2, \
                 patch("web.routes.admin.overview._get_redis", return_value=redis), \
                 patch("web.routes.admin.overview.log_admin_action"):
                from web.routes.admin.overview import overview
                resp = overview()
                data = (resp[0] if isinstance(resp, tuple) else resp).get_json()
                conn2.assert_not_called()  # no DB on cache hit

        assert data["data"]["cached"] is True
