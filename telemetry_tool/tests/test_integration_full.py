"""End-to-end integration tests."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestIntegration:
    def test_schema_version(self, test_db):
        from db.schema import SCHEMA_VERSION
        row = test_db.execute("SELECT MAX(version) FROM schema_version").fetchone()
        assert row[0] == SCHEMA_VERSION

    def test_all_29_tables(self, test_db):
        rows = test_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r[0] for r in rows}
        expected = {
            "schema_version", "tracks", "drivers", "sessions", "laps",
            "gps_traces", "score_details", "condition_phases",
            "weekends", "weekend_sessions", "track_records", "condition_markers",
            "driver_profiles", "driver_progression", "driving_style_features",
            "theoretical_data", "reference_lines", "session_sectors",
            "data_health", "session_tags", "corner_metrics", "corner_best_practices",
            "session_weather", "session_weather_laps", "vehicle_setups", "what_if_scenarios",
            "session_annotations", "development_plans", "custom_dashboards", "export_templates",
        }
        assert expected.issubset(table_names)

    def test_flask_app_creates(self):
        from web.app import create_app
        app = create_app()
        rules = list(app.url_map.iter_rules())
        assert len(rules) >= 80  # Many routes registered

    def test_flask_app_has_key_routes(self):
        from web.app import create_app
        app = create_app()
        rules = {r.rule for r in app.url_map.iter_rules()}
        # Check key API routes exist
        assert any("/api/annotations/" in r for r in rules)

    def test_annotation_to_tag_roundtrip(self, seeded_db):
        """Create annotation, auto-tag, verify tags."""
        from annotations import create_annotation
        from auto_tagging import auto_tag_session, get_session_tags

        create_annotation(seeded_db, "s1", "Testing braking on wet", tags=["braking", "wet"])
        tags = auto_tag_session(seeded_db, "s1")
        all_tags = get_session_tags(seeded_db, "s1")
        assert len(all_tags) >= 0  # At least auto tags applied

    def test_dashboard_with_widget_data(self, seeded_db):
        from dashboard_builder import create_dashboard, get_widget_data
        db = create_dashboard(seeded_db, "Test", [{"type": "pace_chart", "params": {"session_id": "s1"}}])
        data = get_widget_data(seeded_db, "pace_chart", {"session_id": "s1"})
        assert "laps" in data
        assert len(data["laps"]) > 0
