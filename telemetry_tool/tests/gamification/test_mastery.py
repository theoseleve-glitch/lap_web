"""Corner mastery: score derivation + star tier upserts."""
import pytest

from telemetry_tool.gamification import mastery
from telemetry_tool.gamification.catalog import XP_STAR


@pytest.fixture
def mastery_conn(mem_conn):
    mem_conn.execute("""
        CREATE TABLE IF NOT EXISTS corner_mastery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            track_id TEXT NOT NULL,
            corner_id INTEGER NOT NULL,
            condition TEXT NOT NULL DEFAULT 'dry',
            tier TEXT NOT NULL DEFAULT 'none',
            best_score REAL NOT NULL DEFAULT 0,
            sessions_at_silver TEXT NOT NULL DEFAULT '[]',
            first_session_id TEXT,
            achieved_at TEXT,
            updated_at TEXT,
            UNIQUE (workspace_id, driver_id, track_id, corner_id, condition)
        )
    """)
    return mem_conn


class TestCornerScore:
    def test_zero_loss_is_100(self):
        assert mastery.corner_score_from_time_loss(0.0) == 100.0

    def test_full_penalty_is_0(self):
        assert mastery.corner_score_from_time_loss(1500.0) == 0.0

    def test_midpoint(self):
        assert mastery.corner_score_from_time_loss(750.0) == 50.0

    def test_overflow_clamps(self):
        assert mastery.corner_score_from_time_loss(99999.0) == 0.0


class TestStarUpsert:
    def _scores(self, score):
        # one corner (id 3) on track 'spa' with the given score
        return {3: score}

    def test_bronze_awarded_at_60(self, mastery_conn):
        events = mastery.update_corner_mastery(
            mastery_conn, driver_id=1, workspace_id=1,
            track_id="spa", condition="dry",
            corner_scores=self._scores(62.0), session_id="s1",
        )
        assert events == [
            {"track_id": "spa", "corner_id": 3, "tier": "bronze",
             "xp": XP_STAR["bronze"], "score": 62.0}
        ]

    def test_below_bronze_no_event(self, mastery_conn):
        events = mastery.update_corner_mastery(
            mastery_conn, 1, 1, "spa", "dry", self._scores(40.0), "s1")
        assert events == []

    def test_silver_needs_two_sessions(self, mastery_conn):
        e1 = mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(80.0), "s1")
        assert [e["tier"] for e in e1] == ["bronze"]  # first 75+ session: bronze only
        e2 = mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(78.0), "s2")
        assert [e["tier"] for e in e2] == ["silver"]

    def test_silver_same_session_twice_does_not_count(self, mastery_conn):
        mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(80.0), "s1")
        e = mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(80.0), "s1")
        assert e == []  # idempotent: re-running the same session changes nothing

    def test_gold_requires_85_after_silver(self, mastery_conn):
        mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(90.0), "s1")
        mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(90.0), "s2")
        e3 = mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(91.0), "s3")
        assert [e["tier"] for e in e3] == ["gold"]

    def test_tiers_never_lost(self, mastery_conn):
        mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(62.0), "s1")
        e = mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(10.0), "s2")
        assert e == []
        row = mastery_conn.execute(
            "SELECT tier FROM corner_mastery WHERE corner_id = 3").fetchone()
        tier = row["tier"] if isinstance(row, dict) else row[0]
        assert tier == "bronze"

    def test_wet_is_a_separate_star(self, mastery_conn):
        mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "dry", self._scores(62.0), "s1")
        e = mastery.update_corner_mastery(mastery_conn, 1, 1, "spa", "wet", self._scores(62.0), "s2")
        assert [x["tier"] for x in e] == ["bronze"]
