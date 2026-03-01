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
    _gather_training_groups,
    _load_training_config,
    _reprocess_sessions,
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
    @patch("tasks.training_tasks._train_global_model")
    @patch("tasks.training_tasks._train_track_envelopes")
    @patch("tasks.training_tasks._gather_training_groups")
    @patch("tasks.training_tasks._get_pg_connection")
    def test_runs_all_three_tiers(
        self, mock_conn, mock_gather, mock_tier1, mock_tier2, mock_tier3
    ):
        """The main task calls all three tiers in order."""
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
        mock_tier3.return_value = {"succeeded": 2, "failed": 0, "errors": []}

        # Patch the _MODELS_DIR to a temp dir for the audit manifest
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tasks.training_tasks._MODELS_DIR", Path(tmpdir)):
                from tasks.training_tasks import weekly_retrain_and_reprocess

                audit = weekly_retrain_and_reprocess()

        mock_gather.assert_called_once()
        mock_tier1.assert_called_once()
        mock_tier2.assert_called_once()
        mock_tier3.assert_called_once()

        assert "tiers" in audit
        assert "envelopes" in audit["tiers"]
        assert "global_model" in audit["tiers"]
        assert "reprocess" in audit["tiers"]
        assert "elapsed_s" in audit
        assert "started_at" in audit
        assert "completed_at" in audit

    @patch("tasks.training_tasks._reprocess_sessions")
    @patch("tasks.training_tasks._train_global_model")
    @patch("tasks.training_tasks._train_track_envelopes")
    @patch("tasks.training_tasks._gather_training_groups")
    @patch("tasks.training_tasks._get_pg_connection")
    def test_audit_manifest_saved(
        self, mock_conn, mock_gather, mock_tier1, mock_tier2, mock_tier3
    ):
        """Audit manifest JSON file is written to disk."""
        mock_conn.return_value = MagicMock()
        mock_gather.return_value = []
        mock_tier1.return_value = {"trained": 0, "skipped": 0, "errors": []}
        mock_tier2.return_value = {"status": "ok"}
        mock_tier3.return_value = {"succeeded": 0, "failed": 0, "errors": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            models_dir = Path(tmpdir)
            with patch("tasks.training_tasks._MODELS_DIR", models_dir):
                from tasks.training_tasks import weekly_retrain_and_reprocess

                audit = weekly_retrain_and_reprocess()

            audit_dir = models_dir / "audit"
            assert audit_dir.exists()
            manifests = list(audit_dir.glob("training_*.json"))
            assert len(manifests) == 1

            with open(manifests[0]) as fh:
                saved = json.load(fh)
            assert saved["started_at"] == audit["started_at"]


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
