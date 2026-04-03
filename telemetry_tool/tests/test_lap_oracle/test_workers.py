"""Tests for lap_oracle worker modules."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.workers.base import BaseWorker
from telemetry_tool.lap_oracle.workers.harvest import HarvestWorker


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def oracle_env(tmp_path):
    """Create a temporary oracle environment (config + lake)."""
    config = OracleConfig(
        data_dir=tmp_path / "oracle_data",
        db_path=tmp_path / "oracle_data" / "test.db",
    )
    lake = DataLake(config)
    return config, lake


# =========================================================================
# BaseWorker
# =========================================================================

class _DummyWorker(BaseWorker):
    """Concrete worker that counts ticks."""

    worker_type = "dummy"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tick_count = 0
        self.max_ticks = 5
        self.slow = False  # When True, tick returns False to trigger backoff

    def tick(self) -> bool:
        self.tick_count += 1
        if self.tick_count >= self.max_ticks:
            self._running = False
        return not self.slow


class _ErrorWorker(BaseWorker):
    """Worker that raises on every tick."""

    worker_type = "error"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tick_count = 0

    def tick(self) -> bool:
        self.tick_count += 1
        raise ValueError("deliberate error")


class TestBaseWorker:
    """Tests for BaseWorker lifecycle."""

    def test_start_stop(self, oracle_env):
        config, lake = oracle_env
        worker = _DummyWorker("test-0", lake, config)
        worker.max_ticks = 10_000
        worker.slow = True  # triggers 2s backoff, keeps thread alive
        assert not worker.alive
        worker.start()
        # Allow thread to actually start
        time.sleep(0.2)
        assert worker.alive
        worker.stop()
        assert not worker.alive
        assert worker.tick_count > 0

    def test_double_start_ignored(self, oracle_env):
        config, lake = oracle_env
        worker = _DummyWorker("test-1", lake, config)
        worker.start()
        worker.start()  # second call should be no-op
        time.sleep(0.2)
        worker.stop()

    def test_stop_without_start(self, oracle_env):
        config, lake = oracle_env
        worker = _DummyWorker("test-2", lake, config)
        # Should not raise
        worker.stop()
        assert not worker.alive

    def test_tick_not_implemented(self, oracle_env):
        config, lake = oracle_env
        worker = BaseWorker("base-0", lake, config)
        with pytest.raises(NotImplementedError):
            worker.tick()

    def test_error_recovery(self, oracle_env):
        """Worker should keep running after tick errors."""
        config, lake = oracle_env
        worker = _ErrorWorker("err-0", lake, config)
        worker.start()
        time.sleep(1.0)  # Let it hit a few errors with backoff
        assert worker.alive
        assert worker.tick_count >= 1
        assert worker._error_count > 0
        worker.stop()

    def test_natural_exit(self, oracle_env):
        """Worker exits when it sets _running = False."""
        config, lake = oracle_env
        worker = _DummyWorker("exit-0", lake, config)
        worker.max_ticks = 3
        worker.start()
        # Wait for it to finish naturally
        time.sleep(1.0)
        assert not worker.alive
        assert worker.tick_count >= 3


# =========================================================================
# HarvestWorker
# =========================================================================

class TestHarvestWorker:
    """Tests for HarvestWorker."""

    def test_enqueue_discovery_jobs(self, oracle_env):
        """First tick should enqueue discovery jobs for all sources."""
        config, lake = oracle_env
        worker = HarvestWorker("harvest-0", lake, config)

        # Before tick: no harvest jobs
        assert lake.count_jobs("harvest") == 0

        # Call _enqueue_discovery_jobs directly
        worker._enqueue_discovery_jobs()

        count = lake.count_jobs("harvest")
        assert count >= 7  # at least 7 data sources

    def test_enqueue_is_idempotent(self, oracle_env):
        """Calling _enqueue_discovery_jobs twice should not double jobs."""
        config, lake = oracle_env
        worker = HarvestWorker("harvest-1", lake, config)

        worker._enqueue_discovery_jobs()
        count_first = lake.count_jobs("harvest")

        worker._enqueue_discovery_jobs()
        count_second = lake.count_jobs("harvest")

        assert count_first == count_second

    def test_tick_enqueues_on_first_call(self, oracle_env):
        """First tick should enqueue, return True."""
        config, lake = oracle_env
        worker = HarvestWorker("harvest-2", lake, config)

        result = worker.tick()
        assert result is True
        assert worker._discovery_enqueued is True
        assert lake.count_jobs("harvest") >= 7

    def test_tick_claims_job(self, oracle_env):
        """Second tick should claim and process a harvest job."""
        config, lake = oracle_env
        worker = HarvestWorker("harvest-3", lake, config)

        # First tick: enqueue
        worker.tick()

        # Second tick: should claim a job
        result = worker.tick()
        assert result is True

        # At least one job should now be completed or failed
        completed = lake.count_jobs("harvest", status="completed")
        failed = lake.count_jobs("harvest", status="failed")
        assert completed + failed >= 1

    def test_harvest_existing_data(self, oracle_env):
        """_harvest_existing_data should load TUMFTM tracks if present."""
        config, lake = oracle_env
        worker = HarvestWorker("harvest-4", lake, config)

        result = worker._harvest_existing_data()
        # Even if TUMFTM dir is missing, should return a dict
        assert isinstance(result, dict)
        assert "saved" in result

    def test_start_stop_lifecycle(self, oracle_env):
        """HarvestWorker can start and stop cleanly."""
        config, lake = oracle_env
        worker = HarvestWorker("harvest-5", lake, config)
        worker.start()
        assert worker.alive
        time.sleep(0.5)
        worker.stop()
        assert not worker.alive

    def test_dispatch_unknown_source(self, oracle_env):
        """Unknown source should return error dict, not raise."""
        config, lake = oracle_env
        worker = HarvestWorker("harvest-6", lake, config)
        result = worker._dispatch("nonexistent_source", {})
        assert "error" in result
