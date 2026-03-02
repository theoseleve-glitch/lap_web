"""Tests for the weekly retrain Celery task.

Validates that:
- _gather_training_groups groups sessions correctly by track_id
- _gather_training_groups returns sessions with correct structure
- _train_track_envelopes skips groups with < 3 sessions
- _reprocess_sessions calls run_full_analysis for each session
- _reprocess_sessions handles missing CSV gracefully
- _reprocess_sessions stores theoretical data on success
- weekly_retrain_and_reprocess runs all 3 tiers
- Audit manifest is saved
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tasks.training_tasks import (
    _MIN_SESSIONS_PER_GROUP,
    _SCHEDULE_INTERVAL_WEEKS,
    _gather_training_groups,
    _load_training_config,
    _reprocess_sessions,
    _train_ml_models,
    _train_track_envelopes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeCursor:
    """Minimal cursor that returns pre-set rows from fetchall()."""

    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    """Minimal PG connection mock that returns rows on execute().fetchall()."""

    def __init__(self, rows=None):
        self._cursor = FakeCursor(rows)

    def execute(self, sql, params=None):
        return self._cursor

    def commit(self):
        pass


# ---------------------------------------------------------------------------
# _gather_training_groups
# ---------------------------------------------------------------------------


class TestGatherTrainingGroups:
    def test_groups_sessions_by_track_id(self):
        """Sessions from two tracks produce two groups."""
        rows = [
            {"session_id": "s1", "track_id": "track_a", "csv_filename": "a1.csv"},
            {"session_id": "s2", "track_id": "track_a", "csv_filename": "a2.csv"},
            {"session_id": "s3", "track_id": "track_b", "csv_filename": "b1.csv"},
        ]
        conn = FakeConn(rows)
        groups = _gather_training_groups(conn)

        assert len(groups) == 2
        track_ids = {g["track_id"] for g in groups}
        assert track_ids == {"track_a", "track_b"}

    def test_sessions_have_correct_keys(self):
        """Each session dict has session_id, track_id, csv_filename."""
        rows = [
            {"session_id": "s1", "track_id": "t1", "csv_filename": "f1.csv"},
        ]
        conn = FakeConn(rows)
        groups = _gather_training_groups(conn)

        sess = groups[0]["sessions"][0]
        assert "session_id" in sess
        assert "track_id" in sess
        assert "csv_filename" in sess

    def test_null_track_id_becomes_unknown(self):
        """Sessions with NULL track_id are grouped under 'unknown'."""
        rows = [
            {"session_id": "s1", "track_id": None, "csv_filename": "f1.csv"},
        ]
        conn = FakeConn(rows)
        groups = _gather_training_groups(conn)

        assert groups[0]["track_id"] == "unknown"

    def test_empty_result(self):
        """No sessions yields empty groups list."""
        conn = FakeConn([])
        groups = _gather_training_groups(conn)
        assert groups == []


# ---------------------------------------------------------------------------
# _train_track_envelopes
# ---------------------------------------------------------------------------


class TestTrainTrackEnvelopes:
    def test_skips_groups_with_fewer_than_min_sessions(self):
        """Groups with < _MIN_SESSIONS_PER_GROUP sessions are skipped."""
        groups = [
            {
                "track_id": "track_a",
                "sessions": [
                    {"session_id": f"s{i}", "track_id": "track_a", "csv_filename": f"a{i}.csv"}
                    for i in range(_MIN_SESSIONS_PER_GROUP - 1)
                ],
            },
        ]
        result = _train_track_envelopes(groups)

        assert result["trained"] == 0
        assert result["skipped"] == 1
        assert result["errors"] == []

    @patch("tasks.training_tasks._DATA_RAW_DIR")
    @patch("tasks.training_tasks.Path.exists", return_value=True)
    def test_calls_train_library_when_enough_sessions(self, mock_exists, mock_raw_dir):
        """Groups with >= _MIN_SESSIONS_PER_GROUP call train_library."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Create fake CSV files
            for i in range(4):
                (tmp / f"a{i}.csv").write_text("fake")

            groups = [
                {
                    "track_id": "track_a",
                    "sessions": [
                        {"session_id": f"s{i}", "track_id": "track_a", "csv_filename": f"a{i}.csv"}
                        for i in range(4)
                    ],
                },
            ]

            with patch("tasks.training_tasks._DATA_RAW_DIR", tmp), \
                 patch("kart_envelope.pipeline.train_library", return_value={"ok": True}) as mock_train, \
                 patch("kart_envelope.ingest.metadata.SessionMetadata") as MockMeta:
                MockMeta.return_value = MagicMock()
                result = _train_track_envelopes(groups)

            assert result["trained"] == 1
            assert result["skipped"] == 0

    def test_catches_training_errors_gracefully(self):
        """Training errors are logged but don't crash the function."""
        groups = [
            {
                "track_id": "track_a",
                "sessions": [
                    {"session_id": f"s{i}", "track_id": "track_a", "csv_filename": f"a{i}.csv"}
                    for i in range(4)
                ],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for i in range(4):
                (tmp / f"a{i}.csv").write_text("fake")

            with patch("tasks.training_tasks._DATA_RAW_DIR", tmp), \
                 patch("kart_envelope.pipeline.train_library", side_effect=RuntimeError("boom")):
                result = _train_track_envelopes(groups)

        assert result["trained"] == 0
        assert len(result["errors"]) == 1
        assert "boom" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# _reprocess_sessions
# ---------------------------------------------------------------------------


class TestReprocessSessions:
    def test_calls_run_full_analysis_for_each_session(self):
        """run_full_analysis is called once per session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.csv").write_text("fake")
            (tmp / "b.csv").write_text("fake")

            sessions = [
                {"session_id": "s1", "csv_filename": "a.csv"},
                {"session_id": "s2", "csv_filename": "b.csv"},
            ]

            with patch("pipeline.run_full_analysis", return_value={}) as mock_rfa, \
                 patch("tasks.pipeline_tasks._store_theoretical_data"):
                result = _reprocess_sessions(sessions, data_dir=str(tmp))

            assert mock_rfa.call_count == 2
            assert result["succeeded"] == 2
            assert result["failed"] == 0

    def test_handles_missing_csv_gracefully(self):
        """Missing CSV files increment failed counter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions = [
                {"session_id": "s1", "csv_filename": "nonexistent.csv"},
            ]

            with patch("pipeline.run_full_analysis") as mock_rfa:
                result = _reprocess_sessions(sessions, data_dir=tmpdir)

            mock_rfa.assert_not_called()
            assert result["failed"] == 1
            assert result["succeeded"] == 0
            assert "CSV not found" in result["errors"][0]["error"]

    def test_stores_theoretical_data_on_success(self):
        """When theoretical_metrics present, _store_theoretical_data is called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.csv").write_text("fake")

            sessions = [{"session_id": "s1", "csv_filename": "a.csv"}]
            mock_result = {"theoretical_metrics": {"best_s": 42.0}}

            with patch("pipeline.run_full_analysis", return_value=mock_result), \
                 patch("tasks.pipeline_tasks._store_theoretical_data") as mock_store, \
                 patch("tasks.training_tasks._get_pg_connection") as mock_conn:
                result = _reprocess_sessions(sessions, data_dir=str(tmp))

            mock_store.assert_called_once()
            assert result["succeeded"] == 1

    def test_does_not_store_when_no_theoretical_metrics(self):
        """When no theoretical_metrics, _store_theoretical_data is NOT called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.csv").write_text("fake")

            sessions = [{"session_id": "s1", "csv_filename": "a.csv"}]

            with patch("pipeline.run_full_analysis", return_value={}), \
                 patch("tasks.pipeline_tasks._store_theoretical_data") as mock_store:
                result = _reprocess_sessions(sessions, data_dir=str(tmp))

            mock_store.assert_not_called()
            assert result["succeeded"] == 1

    def test_catches_reprocess_errors_gracefully(self):
        """Errors during reprocessing are caught and logged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.csv").write_text("fake")

            sessions = [{"session_id": "s1", "csv_filename": "a.csv"}]

            with patch("pipeline.run_full_analysis", side_effect=RuntimeError("pipeline boom")):
                result = _reprocess_sessions(sessions, data_dir=str(tmp))

            assert result["failed"] == 1
            assert result["succeeded"] == 0
            assert "pipeline boom" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# weekly_retrain_and_reprocess (integration)
# ---------------------------------------------------------------------------


class TestWeeklyRetrainAndReprocess:
    @patch("tasks.training_tasks._reprocess_sessions")
    @patch("tasks.training_tasks._train_ml_models")
    @patch("tasks.training_tasks._train_global_model")
    @patch("tasks.training_tasks._train_track_envelopes")
    @patch("tasks.training_tasks._gather_training_groups")
    @patch("tasks.training_tasks._get_pg_connection")
    def test_runs_all_four_tiers(
        self, mock_conn, mock_gather, mock_tier1, mock_tier2,
        mock_tier3, mock_tier4
    ):
        """The main task calls all four tiers in order."""
        mock_conn.return_value = MagicMock()
        mock_gather.return_value = [
            {
                "track_id": "t1",
                "sessions": [
                    {"session_id": "s1", "csv_filename": "a.csv"},
                    {"session_id": "s2", "csv_filename": "b.csv"},
                ],
            },
        ]
        mock_tier1.return_value = {"trained": 0, "skipped": 1, "errors": []}
        mock_tier2.return_value = {"status": "ok"}
        mock_tier3.return_value = {
            "global_model": None, "driver_models_trained": 0,
            "driver_models_skipped": 0, "anomaly_model": None, "errors": [],
        }
        mock_tier4.return_value = {"succeeded": 2, "failed": 0, "errors": []}

        # Patch the _MODELS_DIR to a temp dir for the audit manifest
        # Force even ISO week so the bi-weekly gate passes
        from datetime import datetime as dt_cls
        even_week_dt = MagicMock()
        even_week_dt.isocalendar.return_value = (2026, 2, 7)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tasks.training_tasks._MODELS_DIR", Path(tmpdir)), \
                 patch("tasks.training_tasks.datetime") as mock_dt:
                mock_dt.now.return_value = even_week_dt
                mock_dt.side_effect = lambda *a, **kw: dt_cls(*a, **kw)
                from tasks.training_tasks import weekly_retrain_and_reprocess

                audit = weekly_retrain_and_reprocess()

        mock_gather.assert_called_once()
        mock_tier1.assert_called_once()
        mock_tier2.assert_called_once()
        mock_tier3.assert_called_once()
        mock_tier4.assert_called_once()

        assert "tiers" in audit
        assert "envelopes" in audit["tiers"]
        assert "global_model" in audit["tiers"]
        assert "ml_models" in audit["tiers"]
        assert "reprocess" in audit["tiers"]
        assert "elapsed_s" in audit
        assert "started_at" in audit
        assert "completed_at" in audit

    @patch("tasks.training_tasks._reprocess_sessions")
    @patch("tasks.training_tasks._train_ml_models")
    @patch("tasks.training_tasks._train_global_model")
    @patch("tasks.training_tasks._train_track_envelopes")
    @patch("tasks.training_tasks._gather_training_groups")
    @patch("tasks.training_tasks._get_pg_connection")
    def test_audit_manifest_saved(
        self, mock_conn, mock_gather, mock_tier1, mock_tier2,
        mock_tier3, mock_tier4
    ):
        """Audit manifest JSON file is written to disk."""
        mock_conn.return_value = MagicMock()
        mock_gather.return_value = []
        mock_tier1.return_value = {"trained": 0, "skipped": 0, "errors": []}
        mock_tier2.return_value = {"status": "ok"}
        mock_tier3.return_value = {
            "global_model": None, "driver_models_trained": 0,
            "driver_models_skipped": 0, "anomaly_model": None, "errors": [],
        }
        mock_tier4.return_value = {"succeeded": 0, "failed": 0, "errors": []}

        from datetime import datetime as dt_cls
        even_week_dt = MagicMock()
        even_week_dt.isocalendar.return_value = (2026, 4, 7)
        even_week_dt.isoformat.return_value = "2026-01-25T00:00:00+00:00"
        even_week_dt.strftime.return_value = "20260125"

        with tempfile.TemporaryDirectory() as tmpdir:
            models_dir = Path(tmpdir)
            with patch("tasks.training_tasks._MODELS_DIR", models_dir), \
                 patch("tasks.training_tasks.datetime") as mock_dt:
                mock_dt.now.return_value = even_week_dt
                mock_dt.side_effect = lambda *a, **kw: dt_cls(*a, **kw)
                from tasks.training_tasks import weekly_retrain_and_reprocess

                audit = weekly_retrain_and_reprocess()

            audit_dir = models_dir / "audit"
            assert audit_dir.exists()
            manifests = list(audit_dir.glob("training_*.json"))
            assert len(manifests) == 1

            with open(manifests[0]) as fh:
                saved = json.load(fh)
            assert saved["started_at"] == audit["started_at"]

    def test_biweekly_gate_skips_odd_weeks(self):
        """Task returns early on odd ISO weeks when interval=2."""
        from datetime import datetime as dt_cls
        odd_week_dt = MagicMock()
        odd_week_dt.isocalendar.return_value = (2026, 3, 7)  # week 3 = odd

        with patch("tasks.training_tasks._load_training_config") as mock_cfg, \
             patch("tasks.training_tasks.datetime") as mock_dt:
            mock_cfg.return_value = {
                "min_sessions_per_group": 3,
                "reprocess_batch_size": 10,
                "reprocess_pause_s": 5,
                "schedule_interval_weeks": 2,
            }
            mock_dt.now.return_value = odd_week_dt
            mock_dt.side_effect = lambda *a, **kw: dt_cls(*a, **kw)

            from tasks.training_tasks import weekly_retrain_and_reprocess
            result = weekly_retrain_and_reprocess()

        assert result.get("skipped") is True
        assert "ISO week 3" in result.get("reason", "")

    def test_biweekly_gate_allows_even_weeks(self):
        """Task proceeds on even ISO weeks when interval=2."""
        from datetime import datetime as dt_cls
        even_week_dt = MagicMock()
        even_week_dt.isocalendar.return_value = (2026, 4, 7)  # week 4 = even

        with patch("tasks.training_tasks._load_training_config") as mock_cfg, \
             patch("tasks.training_tasks.datetime") as mock_dt, \
             patch("tasks.training_tasks._get_pg_connection") as mock_conn, \
             patch("tasks.training_tasks._gather_training_groups", return_value=[]), \
             patch("tasks.training_tasks._train_track_envelopes", return_value={"trained": 0, "skipped": 0, "errors": []}), \
             patch("tasks.training_tasks._train_global_model", return_value={"status": "ok"}), \
             patch("tasks.training_tasks._train_ml_models", return_value={"global_model": None, "driver_models_trained": 0, "driver_models_skipped": 0, "anomaly_model": None, "errors": []}), \
             patch("tasks.training_tasks._reprocess_sessions", return_value={"succeeded": 0, "failed": 0, "errors": []}), \
             tempfile.TemporaryDirectory() as tmpdir:
            mock_cfg.return_value = {
                "min_sessions_per_group": 3,
                "reprocess_batch_size": 10,
                "reprocess_pause_s": 5,
                "schedule_interval_weeks": 2,
            }
            mock_dt.now.return_value = even_week_dt
            mock_dt.side_effect = lambda *a, **kw: dt_cls(*a, **kw)
            mock_conn.return_value = MagicMock()

            with patch("tasks.training_tasks._MODELS_DIR", Path(tmpdir)):
                from tasks.training_tasks import weekly_retrain_and_reprocess
                result = weekly_retrain_and_reprocess()

        assert result.get("skipped") is not True
        assert "tiers" in result


# ---------------------------------------------------------------------------
# _load_training_config
# ---------------------------------------------------------------------------


class TestTrainingConfigRead:
    def test_reads_config_from_redis(self):
        """Training task reads overrides from Redis config hash."""
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "min_sessions_per_group": "5",
            "reprocess_pause_s": "30",
        }

        with patch("tasks.training_tasks._get_redis_config", return_value=mock_redis):
            config = _load_training_config()
            assert config["min_sessions_per_group"] == 5
            assert config["reprocess_pause_s"] == 30
            # Non-overridden key keeps default
            assert config["reprocess_batch_size"] == 10

    def test_falls_back_to_defaults_when_redis_unavailable(self):
        """Training task uses defaults if Redis is unavailable."""
        with patch("tasks.training_tasks._get_redis_config", return_value=None):
            config = _load_training_config()
            assert config["min_sessions_per_group"] == 3
            assert config["reprocess_pause_s"] == 5
            assert config["reprocess_batch_size"] == 10

    def test_falls_back_to_defaults_on_redis_error(self):
        """Training task uses defaults if Redis raises an exception."""
        mock_redis = MagicMock()
        mock_redis.hgetall.side_effect = ConnectionError("connection refused")

        with patch("tasks.training_tasks._get_redis_config", return_value=mock_redis):
            config = _load_training_config()
            assert config["min_sessions_per_group"] == 3

    def test_ignores_unknown_redis_keys(self):
        """Unknown keys in Redis hash are ignored."""
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "min_sessions_per_group": "7",
            "unknown_key": "999",
        }

        with patch("tasks.training_tasks._get_redis_config", return_value=mock_redis):
            config = _load_training_config()
            assert config["min_sessions_per_group"] == 7
            assert "unknown_key" not in config

    def test_schedule_interval_weeks_default(self):
        """Config includes schedule_interval_weeks with default 2."""
        with patch("tasks.training_tasks._get_redis_config", return_value=None):
            config = _load_training_config()
            assert config["schedule_interval_weeks"] == 2


# ---------------------------------------------------------------------------
# _train_ml_models
# ---------------------------------------------------------------------------


class TestTrainMlModels:
    def test_skips_when_no_feature_dataset(self):
        """Returns error when features.parquet doesn't exist."""
        conn = FakeConn([])
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tasks.training_tasks._ML_DATA_DIR", Path(tmpdir)):
                result = _train_ml_models(conn)

        assert len(result["errors"]) >= 1
        assert "not found" in result["errors"][0].lower()
        assert result["global_model"] is None

    def test_trains_global_model_when_dataset_exists(self):
        """Calls train_global_model when feature dataset exists."""
        conn = FakeConn([])
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "processed").mkdir()
            (tmp / "processed" / "features.parquet").write_text("fake")

            mock_meta = {"training_samples": 100, "mae": 0.5}
            with patch("tasks.training_tasks._ML_DATA_DIR", tmp), \
                 patch("ml_engine.train_global_model", return_value=mock_meta):
                result = _train_ml_models(conn)

        assert result["global_model"]["status"] == "ok"
        assert result["global_model"]["training_samples"] == 100

    def test_trains_per_driver_models(self):
        """Trains models for each distinct driver from PG."""
        rows = [
            {"driver_name": "Max"},
            {"driver_name": "Lewis"},
        ]
        conn = FakeConn(rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "processed").mkdir()
            (tmp / "processed" / "features.parquet").write_text("fake")

            mock_meta = {"training_samples": 50, "mae": 0.3}
            with patch("tasks.training_tasks._ML_DATA_DIR", tmp), \
                 patch("ml_engine.train_global_model", return_value=mock_meta), \
                 patch("ml_engine.train_driver_model", return_value=mock_meta) as mock_driver, \
                 patch("anomaly_detection.train_anomaly_model", side_effect=Exception("skip")):
                result = _train_ml_models(conn)

        assert result["driver_models_trained"] == 2
        assert mock_driver.call_count == 2

    def test_skips_drivers_with_insufficient_data(self):
        """Drivers with insufficient data are skipped, not errored."""
        rows = [{"driver_name": "Newbie"}]
        conn = FakeConn(rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "processed").mkdir()
            (tmp / "processed" / "features.parquet").write_text("fake")

            with patch("tasks.training_tasks._ML_DATA_DIR", tmp), \
                 patch("ml_engine.train_global_model", return_value={"training_samples": 10, "mae": 0.5}), \
                 patch("ml_engine.train_driver_model", side_effect=Exception("Insufficient data")) as mock_driver, \
                 patch("anomaly_detection.train_anomaly_model", side_effect=Exception("skip")):
                result = _train_ml_models(conn)

        assert result["driver_models_skipped"] == 1
        assert result["driver_models_trained"] == 0
