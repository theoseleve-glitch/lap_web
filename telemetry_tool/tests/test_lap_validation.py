"""Tests for lap validity detection — pipeline-based + rolling-average fallback."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema
from web.models import insert_laps
from web.repos.lap_repo import _rolling_avg_validity, _pipeline_validity


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')"
    )
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, session_date) "
        "VALUES ('s1', 'test.csv', 1, 'practice', '2026-01-01')"
    )
    conn.commit()
    yield conn
    conn.close()


def _make_laps(
    n=10,
    base_time=60.0,
    base_dist=500.0,
    time_overrides=None,
    dist_overrides=None,
):
    """Build lap_metrics list with optional per-lap time/distance overrides."""
    time_overrides = time_overrides or {}
    dist_overrides = dist_overrides or {}
    return [
        {
            "lap_number": i,
            "lap_time_s": time_overrides.get(i, base_time + (i - 1) * 0.05),
            "speed_mean_mps": 20.0,
            "speed_max_mps": 30.0,
            "braking_max_mps2": 10.0,
            "accel_max_mps2": 5.0,
            "line_length_m": dist_overrides.get(i, base_dist),
        }
        for i in range(1, n + 1)
    ]


def _make_summary(
    lap_metrics=None,
    n_laps=10,
    best_key=1,
    joker_lap=None,
    dist_flagged=None,
    time_flagged=None,
    outlap_numbers=None,
    inlap_numbers=None,
    flagged_only=None,
    deviated_laps=None,
    incomplete_laps=None,
    invalid_laps=None,
    track_cuts=None,
    incidents=None,
    manual_exclusions=None,
    session_type="practice",
    drivers=None,
):
    """Build a pipeline summary dict for insert_laps."""
    if lap_metrics is None:
        lap_metrics = _make_laps(n=n_laps)
    return {
        "lap_metrics": lap_metrics,
        "best_lap_key": best_key,
        "lap_to_phase": {},
        "joker_lap_number": joker_lap,
        "trim_report": {
            "outlap_analysis": {
                "outlap_numbers": outlap_numbers or [],
                "inlap_numbers": inlap_numbers or [],
                "flagged_only": flagged_only or [],
            },
        },
        "invalid_lap_analysis": {
            "invalid_laps": invalid_laps or [],
            "track_cuts": track_cuts or [],
            "incidents": incidents or [],
            "manual": manual_exclusions or [],
        },
        "incomplete_lap_analysis": {
            "incomplete_laps": incomplete_laps or [],
        },
        "anomalous_lap_analysis": {
            "flagged_laps": (dist_flagged or []) + (time_flagged or []),
            "dist_flagged": dist_flagged or [],
            "time_flagged": time_flagged or [],
        },
        "line_deviation_analysis": {
            "deviated_laps": deviated_laps or [],
        },
        "session_meta": {
            "session_type": session_type,
            "drivers": drivers or [],
        },
    }


def _get_laps(conn, session_id="s1"):
    rows = conn.execute(
        "SELECT * FROM laps WHERE session_id = ? ORDER BY lap_number",
        (session_id,),
    ).fetchall()
    return {r["lap_number"]: dict(r) for r in rows}


# ═══════════════════════════════════════════════════════════════
# Pipeline-based detection tests
# ═══════════════════════════════════════════════════════════════


class TestDistanceFirst:
    """Distance anomalies should be checked before time anomalies."""

    def test_dist_flagged_before_time(self, db):
        """A lap in both dist and time sets gets the distance label."""
        summary = _make_summary(
            dist_flagged=[3], time_flagged=[3], outlap_numbers=[3]
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[3]["is_valid"] == 0
        assert laps[3]["invalid_reason"] == "Outlap"

    def test_pure_time_anomaly(self, db):
        """A lap only in time_flagged gets 'Time anomaly'."""
        summary = _make_summary(time_flagged=[5])
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[5]["is_valid"] == 0
        assert laps[5]["invalid_reason"] == "Time anomaly"

    def test_dist_sub_labels_preserved(self, db):
        """Distance anomalies carry specific sub-labels."""
        summary = _make_summary(
            dist_flagged=[2, 4],
            outlap_numbers=[2],
            deviated_laps=[4],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[2]["invalid_reason"] == "Outlap"
        assert laps[4]["invalid_reason"] == "Track deviation"

    def test_inlap_label(self, db):
        summary = _make_summary(
            dist_flagged=[1],
            outlap_numbers=[1],
            inlap_numbers=[1],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[1]["invalid_reason"] == "Inlap"

    def test_pit_lap_label(self, db):
        summary = _make_summary(
            dist_flagged=[6],
            flagged_only=[6],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[6]["invalid_reason"] == "Pit lap"

    def test_valid_laps_untouched(self, db):
        """Laps not in any flagged set remain valid."""
        summary = _make_summary(dist_flagged=[1], time_flagged=[10])
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[5]["is_valid"] == 1
        assert laps[5]["invalid_reason"] is None


class TestEndurancePitDetection:
    """In endurance mode, anomalous laps near stint boundaries → 'Pitted lap'."""

    def test_near_boundary_relabeled(self, db):
        summary = _make_summary(
            n_laps=20,
            dist_flagged=[10],
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[10]["invalid_reason"] == "Pitted lap"

    def test_time_anomaly_near_boundary(self, db):
        summary = _make_summary(
            n_laps=20,
            time_flagged=[11],
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[11]["invalid_reason"] == "Pitted lap"

    def test_far_from_boundary_keeps_label(self, db):
        summary = _make_summary(
            n_laps=20,
            dist_flagged=[5],
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[5]["invalid_reason"] == "Distance anomaly"

    def test_non_endurance_no_relabel(self, db):
        summary = _make_summary(
            n_laps=20,
            dist_flagged=[10],
            session_type="practice",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[10]["invalid_reason"] == "Distance anomaly"


class TestInvalidLapAnalysis:
    """Track cuts, incidents, and manual exclusions."""

    def test_track_cut_flagged_invalid(self, db):
        summary = _make_summary(invalid_laps=[4], track_cuts=[4])
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[4]["is_valid"] == 0
        assert laps[4]["invalid_reason"] == "Track cut"

    def test_incident_flagged_invalid(self, db):
        summary = _make_summary(invalid_laps=[7], incidents=[7])
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[7]["is_valid"] == 0
        assert laps[7]["invalid_reason"] == "Incident"

    def test_manual_exclusion_flagged_invalid(self, db):
        summary = _make_summary(invalid_laps=[2], manual_exclusions=[2])
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[2]["is_valid"] == 0
        assert laps[2]["invalid_reason"] == "Manual exclusion"

    def test_invalid_wins_over_dist_anomaly(self, db):
        summary = _make_summary(
            invalid_laps=[3], track_cuts=[3], dist_flagged=[3],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[3]["is_valid"] == 0
        assert laps[3]["invalid_reason"] == "Track cut"

    def test_joker_still_wins_over_invalid(self, db):
        summary = _make_summary(
            invalid_laps=[3], track_cuts=[3], joker_lap=3,
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[3]["is_valid"] == 0
        assert laps[3]["invalid_reason"] == "Joker lap"
        assert laps[3]["is_joker"] == 1

    def test_valid_laps_unaffected(self, db):
        summary = _make_summary(
            invalid_laps=[3, 8], track_cuts=[3], incidents=[8],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        for n in [1, 2, 4, 5, 6, 7, 9, 10]:
            assert laps[n]["is_valid"] == 1, f"Lap {n} should be valid"
            assert laps[n]["invalid_reason"] is None


# ═══════════════════════════════════════════════════════════════
# Rolling-average fallback tests (when pipeline dicts are empty)
# ═══════════════════════════════════════════════════════════════


class TestRollingAvgUnit:
    """Unit tests for _rolling_avg_validity() directly."""

    def test_all_consistent_laps_valid(self):
        metrics = _make_laps(n=10)
        result = _rolling_avg_validity(metrics)
        for i in range(1, 11):
            assert result[i][0] is True, f"Lap {i} should be valid"

    def test_time_anomaly_detected(self):
        metrics = _make_laps(n=8, time_overrides={6: 120.0})
        result = _rolling_avg_validity(metrics)
        assert result[6][0] is False
        assert "Time" in result[6][1]

    def test_distance_anomaly_detected(self):
        metrics = _make_laps(n=8, dist_overrides={5: 250.0})
        result = _rolling_avg_validity(metrics)
        assert result[5][0] is False
        assert "Distance" in result[5][1]

    def test_both_anomalies(self):
        metrics = _make_laps(n=8, time_overrides={5: 120.0}, dist_overrides={5: 250.0})
        result = _rolling_avg_validity(metrics)
        assert result[5][0] is False
        assert "Time" in result[5][1]
        assert "Distance" in result[5][1]

    def test_invalid_doesnt_poison_window(self):
        metrics = _make_laps(n=10, time_overrides={5: 120.0})
        result = _rolling_avg_validity(metrics)
        assert result[5][0] is False
        assert result[6][0] is True
        assert result[7][0] is True

    def test_first_two_laps_always_accepted(self):
        metrics = _make_laps(n=5)
        result = _rolling_avg_validity(metrics)
        assert result[1][0] is True
        assert result[2][0] is True

    def test_missing_time_invalid(self):
        metrics = _make_laps(n=5, time_overrides={3: None})
        result = _rolling_avg_validity(metrics)
        assert result[3][0] is False
        assert result[3][1] == "No lap time"

    def test_zero_time_invalid(self):
        metrics = _make_laps(n=5, time_overrides={3: 0.0})
        result = _rolling_avg_validity(metrics)
        assert result[3][0] is False


class TestRollingAvgFallbackIntegration:
    """When pipeline dicts are empty, rolling-average kicks in."""

    def test_fallback_used_when_no_pipeline_data(self, db):
        """Summary with no analysis dicts → rolling-average fallback."""
        metrics = _make_laps(n=8, time_overrides={5: 120.0})
        summary = {
            "lap_metrics": metrics,
            "best_lap_key": 1,
            "lap_to_phase": {},
            "joker_lap_number": None,
        }
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[5]["is_valid"] == 0
        assert laps[5]["invalid_reason"] is not None

    def test_normal_session_all_valid(self, db):
        metrics = _make_laps(n=8)
        summary = {
            "lap_metrics": metrics,
            "best_lap_key": 1,
            "lap_to_phase": {},
            "joker_lap_number": None,
        }
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        for n in range(1, 9):
            assert laps[n]["is_valid"] == 1, f"Lap {n} should be valid"

    def test_best_lap_flag(self, db):
        metrics = _make_laps(n=5)
        summary = {
            "lap_metrics": metrics,
            "best_lap_key": 2,
            "lap_to_phase": {},
            "joker_lap_number": None,
        }
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[2]["is_best"] == 1
        assert laps[1]["is_best"] == 0

    def test_count_returned(self, db):
        metrics = _make_laps(n=6)
        summary = {
            "lap_metrics": metrics,
            "best_lap_key": 1,
            "lap_to_phase": {},
            "joker_lap_number": None,
        }
        count = insert_laps(db, "s1", summary)
        assert count == 6
