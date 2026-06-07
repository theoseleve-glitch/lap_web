"""Quest engine — facts extraction, generation, verification."""
import pytest

from telemetry_tool.gamification import quests


@pytest.fixture
def quests_conn(mem_conn):
    # corner_metrics: per-lap, per-corner; mastery: per-corner tier/score.
    mem_conn.execute("""
        CREATE TABLE IF NOT EXISTS corner_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, lap_number INT,
            corner_id INT, apex_speed_mps REAL, exit_speed_mps REAL, time_loss_ms REAL,
            workspace_id INT)
    """)
    mem_conn.execute("""
        CREATE TABLE IF NOT EXISTS corner_mastery (
            id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INT, driver_id INT,
            track_id TEXT, corner_id INT, condition TEXT DEFAULT 'dry', tier TEXT,
            best_score REAL DEFAULT 0)
    """)
    mem_conn.execute("""
        CREATE TABLE IF NOT EXISTS quests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INT, driver_id INT,
            spec TEXT, metric TEXT, comparator TEXT, target REAL, baseline REAL,
            human_text TEXT, xp INT, status TEXT DEFAULT 'active', focused INT DEFAULT 0,
            source_session_id TEXT, created_at TEXT, completed_at TEXT, expires_at TEXT)
    """)
    # Recreate sessions with the minimal schema the quest tests need so that
    # the positional INSERT VALUES ('s0', 1, 1, 46.0) in test_best_lap_improvement_vs_prior
    # matches (session_id, driver_id, workspace_id, best_lap_time_s) exactly.
    mem_conn.execute("DROP TABLE IF EXISTS sessions")
    mem_conn.execute("""
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, driver_id INT, workspace_id INT, best_lap_time_s REAL)
    """)
    return mem_conn


class TestExtractFacts:
    def test_corner_speed_and_session_metrics(self, quests_conn):
        quests_conn.execute(
            "INSERT INTO corner_metrics (session_id, lap_number, corner_id, apex_speed_mps, exit_speed_mps, time_loss_ms, workspace_id) "
            "VALUES ('s1', 1, 5, 15.0, 20.0, 800, 1)")
        quests_conn.execute(
            "INSERT INTO corner_metrics (session_id, lap_number, corner_id, apex_speed_mps, exit_speed_mps, time_loss_ms, workspace_id) "
            "VALUES ('s1', 2, 5, 15.0, 20.0, 600, 1)")
        result = {"score_result": {"total": 78}, "lap_times": [45.0, 45.4, 90.0],
                  "details": {"consistency": {"cv_pct": 4.2}}}
        facts = quests.extract_session_facts(quests_conn, result, "s1", driver_id=1, workspace_id=1)
        assert facts["session.score"] == 78
        assert facts["consistency_cv_pct"] == 4.2
        assert facts["laps_completed"] == 2  # only the two valid (>0, plausible) laps
        assert facts["corner.apex_speed_kmh@5"] == pytest.approx(54.0)   # 15 m/s * 3.6
        assert facts["corner.exit_speed_kmh@5"] == pytest.approx(72.0)
        assert facts["corner.time_loss_ms@5"] == 700.0                   # median of 800,600

    def test_best_lap_improvement_vs_prior(self, quests_conn):
        # prior best 46.0 on an earlier session; this session best 45.0 -> ~2.17% better
        quests_conn.execute("CREATE TABLE IF NOT EXISTS sessions (session_id TEXT, driver_id INT, workspace_id INT, best_lap_time_s REAL)")
        quests_conn.execute("INSERT INTO sessions VALUES ('s0', 1, 1, 46.0)")
        result = {"lap_times": [45.0, 45.5]}
        facts = quests.extract_session_facts(quests_conn, result, "s1", 1, 1)
        assert facts["best_lap_improvement_pct"] == pytest.approx((46.0 - 45.0) / 46.0 * 100, abs=0.1)


class TestGenerate:
    def _facts(self):
        return {
            "session.score": 70.0, "consistency_cv_pct": 6.0, "laps_completed": 20.0,
            "corner.apex_speed_kmh@5": 54.0, "corner.time_loss_ms@5": 900.0,
            "corner.apex_speed_kmh@2": 60.0, "corner.time_loss_ms@2": 100.0,
        }

    def test_generates_corner_quest_for_weakest_corner(self, quests_conn):
        created = quests.generate_quests(quests_conn, self._facts(), driver_id=1, workspace_id=1, session_id="s1")
        # weakest corner = highest time_loss = corner 5 → apex-speed quest target = 54+3
        corner_q = [q for q in created if q["metric"] == "corner.apex_speed_kmh"]
        assert corner_q and corner_q[0]["scope"]["corner_id"] == 5
        assert corner_q[0]["target"] == 57.0
        assert corner_q[0]["baseline"] == 54.0
        assert corner_q[0]["comparator"] == ">="
        assert corner_q[0]["xp"] == 150

    def test_generates_consistency_quest_when_cv_high(self, quests_conn):
        created = quests.generate_quests(quests_conn, self._facts(), 1, 1, "s1")
        cq = [q for q in created if q["metric"] == "consistency_cv_pct"]
        assert cq and cq[0]["comparator"] == "<=" and cq[0]["target"] == 5.5  # 6.0 - 0.5

    def test_no_duplicate_active_quest_for_same_metric_scope(self, quests_conn):
        quests.generate_quests(quests_conn, self._facts(), 1, 1, "s1")
        quests_conn.commit()
        again = quests.generate_quests(quests_conn, self._facts(), 1, 1, "s2")
        # corner 5 apex quest already active → not regenerated
        assert not any(q["metric"] == "corner.apex_speed_kmh" and q["scope"].get("corner_id") == 5 for q in again)

    def test_activity_fallback_when_no_signal(self, quests_conn):
        flat = {"laps_completed": 10.0}  # nothing actionable
        created = quests.generate_quests(quests_conn, flat, 1, 1, "s1")
        assert any(q["metric"] == "laps_completed" for q in created)

    def test_caps_at_three(self, quests_conn):
        created = quests.generate_quests(quests_conn, self._facts(), 1, 1, "s1")
        assert len(created) <= 3

    def test_generated_quests_have_id(self, quests_conn):
        """Each dict returned by generate_quests must contain a non-None 'id'
        (the newly inserted row id).  Missing id → key=undefined in React."""
        created = quests.generate_quests(quests_conn, self._facts(), 1, 1, "s1")
        assert created, "expected at least one quest to be generated"
        for q in created:
            assert "id" in q, f"quest dict missing 'id' key: {q}"
            assert q["id"] is not None, f"quest 'id' is None: {q}"


class TestVerify:
    def _make_active(self, conn, metric, comparator, target, corner_id=None):
        import json as _j
        scope = {"corner_id": corner_id} if corner_id is not None else {}
        spec = {"metric": metric, "comparator": comparator, "target": target, "baseline": 0, "scope": scope}
        conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, spec, metric, comparator, target, baseline, human_text, xp, status, source_session_id, created_at) "
            "VALUES (1,1,:s,:m,:c,:t,0,'x',150,'active','s0','2026-06-01')",
            {"s": _j.dumps(spec), "m": metric, "c": comparator, "t": target})

    def test_passing_quest_completes_and_awards(self, quests_conn):
        self._make_active(quests_conn, "corner.apex_speed_kmh", ">=", 57.0, corner_id=5)
        facts = {"corner.apex_speed_kmh@5": 58.0}
        done = quests.verify_quests(quests_conn, facts, driver_id=1, workspace_id=1, session_id="s1")
        assert len(done) == 1 and done[0]["xp"] == 150
        row = quests_conn.execute("SELECT status FROM quests WHERE metric='corner.apex_speed_kmh'").fetchone()
        assert (row["status"] if isinstance(row, dict) else row[0]) == "completed"

    def test_failing_quest_stays_active(self, quests_conn):
        self._make_active(quests_conn, "consistency_cv_pct", "<=", 5.0)
        done = quests.verify_quests(quests_conn, {"consistency_cv_pct": 6.0}, 1, 1, "s1")
        assert done == []
        row = quests_conn.execute("SELECT status FROM quests WHERE metric='consistency_cv_pct'").fetchone()
        assert (row["status"] if isinstance(row, dict) else row[0]) == "active"

    def test_idempotent_rerun_awards_nothing(self, quests_conn):
        self._make_active(quests_conn, "session.score", ">=", 75.0)
        quests.verify_quests(quests_conn, {"session.score": 80.0}, 1, 1, "s1")
        quests_conn.commit()
        again = quests.verify_quests(quests_conn, {"session.score": 80.0}, 1, 1, "s1")
        assert again == []   # already completed → not re-evaluated

    def test_missing_fact_does_not_complete(self, quests_conn):
        self._make_active(quests_conn, "corner.apex_speed_kmh", ">=", 57.0, corner_id=9)
        done = quests.verify_quests(quests_conn, {}, 1, 1, "s1")  # corner 9 not driven
        assert done == []

    def test_expire_stale(self, quests_conn):
        quests_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, spec, metric, comparator, target, baseline, human_text, xp, status, source_session_id, created_at, expires_at) "
            "VALUES (1,1,'{}','session.score','>=',75,0,'x',100,'active','s0','2026-01-01','2026-01-15')")
        n = quests.expire_stale_quests(quests_conn, 1, 1, now_iso="2026-06-01T00:00:00")
        assert n == 1
        row = quests_conn.execute("SELECT status FROM quests WHERE metric='session.score'").fetchone()
        assert (row["status"] if isinstance(row, dict) else row[0]) == "expired"
