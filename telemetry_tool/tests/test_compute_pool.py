"""Tests for TWO CONFIRMED HIGH compute-pool defects (customer readiness).

FIX #3 (HIGH): POST .../sessions/<id>/ocp-corner ran up to
MAX_OCP_TOTAL_SOLVES_PER_REQUEST synchronous solve_ocp_segment calls INLINE
on the web-worker thread, decorated only with @_safe_api. It fell through to
the data_v2 blueprint's blanket "write" rate tier (60/min, x5 multiplier for
world-class = 300/min — see web/routes/data_v2.py's _apply_rate_limit) with
no compute-budget check at all, and the `analyses` quota is unlimited (-1)
for world-class, so a single world-class tenant could pin every gunicorn
worker. Fixed by adding @rate_limit(tier="analyze") (mirrors
track_surface_analysis.py's /run route) plus a check_shared_compute_budget
gate before _run_corner_ocp runs.

FIX #5 (HIGH): tasks/pipeline_tasks.py's per-tier timeout fix threads
sig.set(time_limit=...) onto every pipeline stage signature, so the b2b
tier's hard limit (3600 + HARD_LIMIT_MARGIN_S = 3900s) now legitimately
exceeds the shared celery-pipeline worker's blanket --time-limit=2100
(docker-compose.prod.yml/.staging.yml, --concurrency=2). A single b2b upload
could occupy 1 of only 2 shared slots for ~65 minutes — two concurrent b2b
jobs fully stall the shared queue for every other tenant. Fixed by isolating
long-grace tiers onto a dedicated `pipeline_long` queue + `celery-pipeline-long`
worker (mirrors the earlier celery-endurance isolation), routed at dispatch
time via tasks.pipeline_tasks.pipeline_queue_for_tier
(web/routes/sessions_v2.py).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_REPO_ROOT = _PROJECT_ROOT.parent


# ══════════════════════════════════════════════════════════════════
# FIX #3 — ocp-corner rate limit + compute budget
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def data_v2_app():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.before_request
    def fake_tenant():
        g.workspace_id = 1
        g.current_user_id = 1
        g.plan_tier = "locked"
        g.request_id = "test-req-id"

    from web.routes.data_v2 import bp as data_v2_bp
    app.register_blueprint(data_v2_bp)
    return app


@pytest.fixture
def data_v2_client(data_v2_app):
    return data_v2_app.test_client()


class _FakeBudgetConn:
    """Minimal conn double for check_shared_compute_budget's SAVEPOINT-guarded
    per-table COUNT scan (mirrors tests/test_shared_compute_budget.py's
    _FakeConn). SAVEPOINT/RELEASE/ROLLBACK are accepted as no-ops so the real
    savepoint-guarded control flow in web/compute_budget.py is exercised."""

    def __init__(self, counts):
        self.counts = dict(counts)
        self._pending = {"cnt": 0}

    def execute(self, sql, params=None):
        s = str(sql).strip()
        if s.split(" ", 1)[0] in ("SAVEPOINT", "RELEASE", "ROLLBACK"):
            return self
        row = {"cnt": 0}
        for table, c in self.counts.items():
            if f"FROM {table} " in s:
                row = {"cnt": c}
        self._pending = row
        return self

    def fetchone(self):
        return self._pending


class TestOcpCornerRateLimitWired:
    """@rate_limit(tier="analyze") is now applied directly to solve_ocp_corner
    (previously only the blueprint's blanket "write" tier applied). The mock
    Redis differentiates by key so the pre-existing blueprint-wide "write"
    tier check passes (count=1) while the NEW "analyze" tier check is the one
    that trips — proving this specific decorator is wired, not just the
    pre-existing blueprint-level limiter."""

    @staticmethod
    def _make_redis(over_tier: str = "analyze", over_count: int = 999):
        mock_redis = MagicMock()

        def _eval(script, numkeys, key, *rest):
            if key.startswith(f"ratelimit:{over_tier}:"):
                return over_count
            return 1

        mock_redis.eval.side_effect = _eval
        return mock_redis

    def test_over_limit_analyze_tier_returns_429(self, data_v2_client):
        mock_redis = self._make_redis()
        with patch("web.rate_limit.get_redis", return_value=mock_redis):
            resp = data_v2_client.post(
                "/api/v1/sessions/42/ocp-corner",
                json={"corner_ids": [1, 2, 3]},
            )
        assert resp.status_code == 429
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "RATE_LIMITED"

    def test_under_limit_analyze_tier_passes_through(self, data_v2_client):
        """Under the analyze-tier limit, the request must reach past the
        rate limiter (a 404 on a nonexistent session proves it got there,
        not blocked by rate limiting)."""
        mock_redis = self._make_redis(over_count=1)
        with patch("web.rate_limit.get_redis", return_value=mock_redis), \
             patch("web.routes.data_v2.get_db_connection", return_value=MagicMock()), \
             patch("web.models.get_session_by_id", return_value=None):
            resp = data_v2_client.post(
                "/api/v1/sessions/999999/ocp-corner",
                json={"corner_ids": [1, 2, 3]},
            )
        assert resp.status_code == 404


class TestOcpCornerComputeBudget:
    """check_shared_compute_budget is now consulted before _run_corner_ocp
    runs, rejecting over-budget with the same clean 4xx the other
    heavy-compute routes (track_surface_analysis.py's /run,
    endurance_upload.py) use."""

    def test_rejected_when_over_compute_budget(self, data_v2_client):
        # plan_tier="locked" -> max_concurrent_jobs=1 (web/compute_budget.py);
        # one ingestion job already active -> 1 is NOT < 1 -> denied.
        conn = _FakeBudgetConn({"ingestion_jobs": 1})
        with patch("web.routes.data_v2.get_db_connection", return_value=conn), \
             patch("web.models.get_session_by_id", return_value={"session_id": "42"}):
            resp = data_v2_client.post(
                "/api/v1/sessions/42/ocp-corner",
                json={"corner_ids": [1, 2, 3]},
            )
        assert resp.status_code == 429
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "Compute budget exceeded" in body["error"]["message"]

    def test_allowed_under_compute_budget_reaches_solver(self, data_v2_client):
        # No active jobs of any kind -> running=0 < max_jobs(1) -> allowed;
        # request must proceed into _run_corner_ocp (mocked here).
        conn = _FakeBudgetConn({})
        with patch("web.routes.data_v2.get_db_connection", return_value=conn), \
             patch("web.models.get_session_by_id", return_value={"session_id": "42"}), \
             patch("web.routes.data_v2._run_corner_ocp",
                   return_value={"corner_results": [], "full_lap_ocp": None}) as mock_run:
            resp = data_v2_client.post(
                "/api/v1/sessions/42/ocp-corner",
                json={"corner_ids": [1, 2, 3]},
            )
        assert resp.status_code == 200
        mock_run.assert_called_once()

    def test_budget_check_error_fails_open(self, data_v2_client):
        """A metering error (e.g. an exception inside check_shared_compute_budget)
        must never block a legitimate solve — fail open, matching the other
        compute-budget call sites' documented behaviour."""
        with patch("web.routes.data_v2.get_db_connection", return_value=MagicMock()), \
             patch("web.models.get_session_by_id", return_value={"session_id": "42"}), \
             patch("web.compute_budget.check_shared_compute_budget",
                   side_effect=RuntimeError("redis down")), \
             patch("web.routes.data_v2._run_corner_ocp",
                   return_value={"corner_results": [], "full_lap_ocp": None}) as mock_run:
            resp = data_v2_client.post(
                "/api/v1/sessions/42/ocp-corner",
                json={"corner_ids": [1, 2, 3]},
            )
        assert resp.status_code == 200
        mock_run.assert_called_once()


class TestOcpCornerCapsStillApply:
    """Regression: the pre-existing hard caps (independent of the new rate
    limit / budget gate) must still be enforced."""

    def test_corner_ids_cap_still_enforced(self, data_v2_client):
        from web.routes.data_v2 import MAX_OCP_CORNER_IDS_PER_REQUEST
        corner_ids = list(range(MAX_OCP_CORNER_IDS_PER_REQUEST + 1))
        resp = data_v2_client.post(
            "/api/v1/sessions/42/ocp-corner",
            json={"corner_ids": corner_ids},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_total_solves_cap_still_enforced(self):
        from web.routes.data_v2 import MAX_OCP_TOTAL_SOLVES_PER_REQUEST
        assert MAX_OCP_TOTAL_SOLVES_PER_REQUEST == 500


# ══════════════════════════════════════════════════════════════════
# FIX #5 — pipeline_long queue isolation for long-grace tiers
# ══════════════════════════════════════════════════════════════════

from tasks.pipeline_tasks import (  # noqa: E402
    HARD_LIMIT_MARGIN_S,
    PIPELINE_LONG_QUEUE,
    PIPELINE_WORKER_TIME_LIMIT_S,
    TIER_TIMEOUTS_S,
    build_pipeline_chain,
    pipeline_queue_for_tier,
)


class TestPipelineQueueRouting:
    def test_b2b_routed_to_pipeline_long(self):
        assert pipeline_queue_for_tier("b2b") == PIPELINE_LONG_QUEUE == "pipeline_long"

    @pytest.mark.parametrize("tier", ["locked", "racer", "world-class", "world_class"])
    def test_short_tiers_stay_on_shared_pipeline_queue(self, tier):
        assert pipeline_queue_for_tier(tier) == "pipeline"

    def test_unknown_tier_falls_back_to_locked_and_shared_queue(self):
        assert pipeline_queue_for_tier("some_unknown_tier") == "pipeline"

    def test_build_pipeline_chain_threads_queue_onto_every_stage(self):
        built = build_pipeline_chain(
            "job-b2b-long",
            soft_time_limit=TIER_TIMEOUTS_S["b2b"],
            queue=pipeline_queue_for_tier("b2b"),
        )
        for sig in built.tasks:
            assert sig.options.get("queue") == "pipeline_long"
            # Both fixes must co-exist on the same signature.
            assert sig.options.get("soft_time_limit") == TIER_TIMEOUTS_S["b2b"]

    def test_short_tier_chain_stays_on_default_routing(self):
        built = build_pipeline_chain(
            "job-racer",
            soft_time_limit=TIER_TIMEOUTS_S["racer"],
            queue=pipeline_queue_for_tier("racer"),
        )
        for sig in built.tasks:
            assert sig.options.get("queue") == "pipeline"

    def test_no_queue_arg_leaves_stage_options_untouched(self):
        """queue=None (default) must not add a 'queue' key at all — callers
        that don't route by tier (retry / admin-retry / sync-upload) keep
        falling back to celery_app.py's static task_routes, unchanged from
        prior behaviour."""
        built = build_pipeline_chain("job-no-queue", soft_time_limit=600)
        for sig in built.tasks:
            assert "queue" not in sig.options


class TestPipelineOccupancyBoundInvariant:
    """The core #5 regression guard: no tier whose dispatch lands on the
    shared 'pipeline' queue may ever occupy a slot for longer than the
    shared celery-pipeline worker's own blanket --time-limit
    (PIPELINE_WORKER_TIME_LIMIT_S). If this test starts failing, either a
    new/changed tier needs isolating too, or pipeline_queue_for_tier's
    threshold logic regressed."""

    def test_documented_occupancy_bound_is_2100s(self):
        assert PIPELINE_WORKER_TIME_LIMIT_S == 2100

    def test_no_shared_queue_tier_exceeds_worker_ceiling(self):
        shared_queue_hard_limits = [
            TIER_TIMEOUTS_S[tier] + HARD_LIMIT_MARGIN_S
            for tier in TIER_TIMEOUTS_S
            if pipeline_queue_for_tier(tier) == "pipeline"
        ]
        assert shared_queue_hard_limits, "expected at least one tier on the shared queue"
        assert max(shared_queue_hard_limits) <= PIPELINE_WORKER_TIME_LIMIT_S

    def test_b2b_is_the_tier_actually_isolated(self):
        """The converse of the above: b2b's hard limit DOES exceed the
        ceiling, and it must NOT be in the shared-queue set — proving
        isolation is actually happening, not coincidentally satisfied."""
        b2b_hard = TIER_TIMEOUTS_S["b2b"] + HARD_LIMIT_MARGIN_S
        assert b2b_hard > PIPELINE_WORKER_TIME_LIMIT_S
        assert pipeline_queue_for_tier("b2b") != "pipeline"


class TestSessionsV2DispatchRoutesByTier:
    """Integration point: web/routes/sessions_v2.py must actually call
    pipeline_queue_for_tier() and thread the result into build_pipeline_chain
    — a helper function existing and being correct is not enough if the
    dispatch call site forgets to use it."""

    @pytest.fixture
    def app(self):
        from web.routes.sessions_v2 import bp
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["USE_PG"] = True
        app.register_blueprint(bp)
        return app

    _VALID_CSV = "Lap #,Time (s),Speed (m/s)\n" + "".join(
        f"1,{t / 10:.1f},{10.0 + (t % 20) * 0.1:.1f}\n" for t in range(60)
    )

    def _post_upload(self, client, plan_tier, app):
        import io

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"count": 0}
        mock_r = MagicMock()
        mock_chain = MagicMock()

        @app.before_request
        def _inject_auth():
            g.workspace_id = 1
            g.current_user_id = 42
            g.plan_tier = plan_tier

        # Represent an ENTITLED user whose tier/quota/storage checks pass, so
        # the request reaches the dispatch code under test. _check_tier_limits
        # is patched to None (its "no limit exceeded" return) rather than
        # weakening any real gate — the pre-existing HTTP-level 402 seen when
        # this returns a truthy MagicMock (get_storage arithmetic on a mock
        # conn) is an artifact of the mocked DB, not the code path we assert.
        # Mirrors tests/test_solver_entitlement.py's pattern of mocking the
        # entitlement layer to an allowed user.
        with patch("web.routes.sessions_v2._get_conn", return_value=mock_conn), \
             patch("web.routes.sessions_v2._check_tier_limits", return_value=None), \
             patch("redis.Redis.from_url", return_value=mock_r), \
             patch("pipeline_context.PipelineContext"), \
             patch("tasks.pipeline_tasks.build_pipeline_chain",
                   return_value=mock_chain) as mock_build, \
             patch("web.config.Config") as mock_cfg:
            mock_cfg.REDIS_URL = "redis://localhost:6379/0"
            resp = client.post(
                "/api/v1/sessions/upload",
                data={
                    "file": (io.BytesIO(self._VALID_CSV.encode()), "session.csv"),
                    "session_type": "practice",
                    "track_state": "dry",
                    "driver_name": "TestDriver",
                },
                content_type="multipart/form-data",
            )
        return resp, mock_build

    def test_b2b_upload_dispatches_to_pipeline_long(self, app):
        resp, mock_build = self._post_upload(app.test_client(), "b2b", app)
        assert resp.status_code == 202
        _, kwargs = mock_build.call_args
        assert kwargs.get("queue") == "pipeline_long"

    def test_racer_upload_dispatches_to_shared_pipeline(self, app):
        resp, mock_build = self._post_upload(app.test_client(), "racer", app)
        assert resp.status_code == 202
        _, kwargs = mock_build.call_args
        assert kwargs.get("queue") == "pipeline"


# ══════════════════════════════════════════════════════════════════
# FIX #5 — compose-file structural checks (YAML-level regression)
# ══════════════════════════════════════════════════════════════════

class TestComposeQueueIsolation:
    """The celery-pipeline-long worker must actually exist in both prod and
    staging compose files, sized to cover the b2b tier's hard limit, and the
    shared celery-pipeline worker's blanket --time-limit must match the
    PIPELINE_WORKER_TIME_LIMIT_S constant the routing logic is keyed on."""

    @pytest.mark.parametrize(
        "compose_file", ["docker-compose.prod.yml", "docker-compose.staging.yml"]
    )
    def test_pipeline_long_worker_present_and_sized(self, compose_file):
        import yaml

        path = _REPO_ROOT / compose_file
        assert path.is_file(), f"{compose_file} not found at {path}"
        with open(path) as f:
            doc = yaml.safe_load(f)
        services = doc["services"]
        assert "celery-pipeline-long" in services, (
            f"{compose_file} is missing the celery-pipeline-long worker"
        )
        cmd = services["celery-pipeline-long"]["command"]
        assert "-Q pipeline_long" in cmd
        m = re.search(r"--time-limit=(\d+)", cmd)
        assert m, f"celery-pipeline-long in {compose_file} has no --time-limit"
        assert int(m.group(1)) >= TIER_TIMEOUTS_S["b2b"] + HARD_LIMIT_MARGIN_S

    @pytest.mark.parametrize(
        "compose_file", ["docker-compose.prod.yml", "docker-compose.staging.yml"]
    )
    def test_shared_pipeline_worker_blanket_matches_constant(self, compose_file):
        import yaml

        path = _REPO_ROOT / compose_file
        with open(path) as f:
            doc = yaml.safe_load(f)
        cmd = doc["services"]["celery-pipeline"]["command"]
        m = re.search(r"--time-limit=(\d+)", cmd)
        assert m
        assert int(m.group(1)) == PIPELINE_WORKER_TIME_LIMIT_S
