"""Test dashboard builder module."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard_builder import (
    create_dashboard,
    delete_dashboard,
    get_dashboard,
    get_dashboards,
    get_default_layout,
    get_widget_data,
    get_widget_registry,
    update_dashboard,
)


@pytest.fixture
def dash_db(test_db):
    conn = test_db
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'D1')")
    conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)")
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date, n_laps, best_lap_time_s, grade) "
        "VALUES ('s1', 'x.csv', 1, 't1', '2024-01-01', 10, 60.0, 'B')"
    )
    for i in range(1, 11):
        conn.execute("INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) VALUES ('s1', ?, ?, 1)", (i, 60.0+i*0.1))
    conn.execute(
        "INSERT INTO score_details (session_id, pace_score, pace_max, consistency_score, consistency_max, "
        "execution_score, execution_max, robustness_score, robustness_max) "
        "VALUES ('s1', 20, 25, 18, 25, 20, 25, 22, 25)"
    )
    conn.commit()
    return conn


class TestDashboard:
    def test_widget_registry(self):
        widgets = get_widget_registry()
        assert len(widgets) >= 10

    def test_create_dashboard(self, dash_db):
        db = create_dashboard(dash_db, "Test", [{"type": "recent_sessions"}])
        assert db["id"] is not None

    def test_update_dashboard(self, dash_db):
        db = create_dashboard(dash_db, "Old", [{"type": "recent_sessions"}])
        updated = update_dashboard(dash_db, db["id"], name="New")
        assert updated["dashboard_name"] == "New"

    def test_delete_dashboard(self, dash_db):
        db = create_dashboard(dash_db, "Del", [{"type": "recent_sessions"}])
        assert delete_dashboard(dash_db, db["id"])
        assert get_dashboard(dash_db, db["id"]) is None

    def test_widget_data_recent_sessions(self, dash_db):
        data = get_widget_data(dash_db, "recent_sessions", {})
        assert "sessions" in data

    def test_widget_data_pace_chart(self, dash_db):
        data = get_widget_data(dash_db, "pace_chart", {"session_id": "s1"})
        assert len(data["laps"]) == 10

    def test_default_layout_valid(self):
        layout = get_default_layout()
        assert len(layout) >= 3

    def test_invalid_widget_type(self):
        from dashboard_builder import _validate_layout
        with pytest.raises(ValueError):
            _validate_layout([{"type": "bogus_widget"}])
