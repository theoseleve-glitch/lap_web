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
