"""Tests for pipeline_status module — step capture, degradation, versioning."""

from __future__ import annotations

import time

import pytest

from pipeline_status import (
    PIPELINE_STEP_NAMES,
    PipelineState,
    PipelineStatus,
    StepState,
    StepStatus,
    compute_pipeline_hash,
    compute_pipeline_version_string,
    get_model_version,
)

# ---------------------------------------------------------------------------
# StepStatus
# ---------------------------------------------------------------------------


class TestStepStatus:
    def test_ok_step_to_dict(self):
        s = StepStatus(
            name="01_ingest",
            status=StepState.OK,
            started_at=1000.0,
            duration_ms=42.3,
        )
        d = s.to_dict()
        assert d["name"] == "01_ingest"
        assert d["status"] == "ok"
        assert d["duration_ms"] == 42.3
        assert "message_code" not in d  # omitted when None

    def test_fail_step_includes_message(self):
        s = StepStatus(
            name="02_filter",
            status=StepState.FAIL,
            started_at=1000.0,
            duration_ms=100.0,
            message_code="ValueError",
            message="bad data",
        )
        d = s.to_dict()
        assert d["status"] == "fail"
        assert d["message_code"] == "ValueError"
        assert d["message"] == "bad data"

    def test_metrics_included_when_present(self):
        s = StepStatus(
            name="08_compute_metrics",
            status=StepState.OK,
            started_at=1000.0,
            duration_ms=50.0,
            metrics={"rows_in": 5000, "rows_out": 4800},
        )
        d = s.to_dict()
        assert d["metrics"]["rows_in"] == 5000


# ---------------------------------------------------------------------------
# PipelineStatus
# ---------------------------------------------------------------------------


class TestPipelineStatus:
    def test_all_ok_steps_not_degraded(self):
        ps = PipelineStatus(pipeline_version="v2-abc12345")
        ps.record_step(StepStatus(name="01_ingest", status=StepState.OK))
        ps.record_step(StepStatus(name="02_filter", status=StepState.OK))
        d = ps.to_dict()
        assert d["status"] == "ok"
        assert d["degraded"] is False
        assert d["degraded_steps"] == []
        assert d["user_message"] is None

    def test_warn_step_sets_degraded(self):
        ps = PipelineStatus(pipeline_version="v2-abc12345")
        ps.record_step(StepStatus(name="01_ingest", status=StepState.OK))
        ps.record_step(StepStatus(name="09a_reference_line", status=StepState.WARN))
        d = ps.to_dict()
        assert d["status"] == "degraded"
        assert d["degraded"] is True
        assert "09a_reference_line" in d["degraded_steps"]
        assert "degraded" in d["user_message"].lower()

    def test_fail_step_sets_degraded(self):
        ps = PipelineStatus(pipeline_version="v2-abc12345")
        ps.record_step(StepStatus(name="12a_ml_train", status=StepState.FAIL,
                                  message_code="ImportError", message="sklearn missing"))
        d = ps.to_dict()
        assert d["status"] == "degraded"
        assert d["degraded"] is True
        assert "12a_ml_train" in d["degraded_steps"]

    def test_mark_failed_overrides_to_failed(self):
        ps = PipelineStatus(pipeline_version="v2-abc12345")
        ps.record_step(StepStatus(name="01_ingest", status=StepState.FAIL))
        ps.mark_failed()
        d = ps.to_dict()
        assert d["status"] == "failed"

    def test_steps_array_includes_all_recorded(self):
        ps = PipelineStatus(pipeline_version="v2-abc12345")
        ps.record_step(StepStatus(name="01_ingest", status=StepState.OK, duration_ms=10))
        ps.record_step(StepStatus(name="02_filter", status=StepState.OK, duration_ms=20))
        ps.record_step(StepStatus(name="03_derived", status=StepState.FAIL, duration_ms=5))
        d = ps.to_dict()
        assert len(d["steps"]) == 3
        names = [s["name"] for s in d["steps"]]
        assert names == ["01_ingest", "02_filter", "03_derived"]

    def test_user_message_truncates_many_degraded(self):
        """When more than 5 steps degrade, user_message shows +N more."""
        ps = PipelineStatus(pipeline_version="v2-abc12345")
        for i in range(8):
            ps.record_step(StepStatus(name=f"step_{i}", status=StepState.WARN))
        d = ps.to_dict()
        assert "+3 more" in d["user_message"]

    def test_pipeline_version_and_model_in_output(self):
        ps = PipelineStatus(pipeline_version="v2-abc12345", model_version="v3")
        d = ps.to_dict()
        assert d["pipeline_version"] == "v2-abc12345"
        assert d["model_version"] == "v3"


# ---------------------------------------------------------------------------
# Deterministic versioning
# ---------------------------------------------------------------------------


class TestVersioning:
    def test_pipeline_hash_is_stable(self):
        """Same code produces the same hash across runs."""
        h1 = compute_pipeline_hash()
        h2 = compute_pipeline_hash()
        assert h1 == h2
        assert len(h1) == 8  # 8-char hex prefix

    def test_pipeline_version_string_format(self):
        """Version string matches pattern vN-hexhash."""
        vs = compute_pipeline_version_string()
        assert vs.startswith("v")
        assert "-" in vs
        parts = vs.split("-", 1)
        int(parts[0][1:])  # should be an integer after 'v'
        assert len(parts[1]) == 8

    def test_pipeline_version_changes_with_steps(self):
        """If step names change, the hash must change."""
        original = compute_pipeline_hash()
        # Temporarily modify step list
        saved = PIPELINE_STEP_NAMES.copy()
        PIPELINE_STEP_NAMES.append("99_new_step")
        try:
            modified = compute_pipeline_hash()
            assert original != modified
        finally:
            PIPELINE_STEP_NAMES.clear()
            PIPELINE_STEP_NAMES.extend(saved)

    def test_model_version_returns_string(self):
        """get_model_version() returns a string (may be 'none' without models dir)."""
        mv = get_model_version()
        assert isinstance(mv, str)


# ---------------------------------------------------------------------------
# Integration: _safe_step populates _last_step_status
# ---------------------------------------------------------------------------


class TestSafeStepIntegration:
    def test_safe_step_ok_sets_status(self):
        import pipeline.helpers as ph

        r, e = ph._safe_step("test_ok", lambda: 42)
        assert r == 42
        assert e is None
        assert ph._last_step_status is not None
        assert ph._last_step_status.name == "test_ok"
        assert ph._last_step_status.status == StepState.OK
        assert ph._last_step_status.duration_ms >= 0

    def test_safe_step_fail_sets_status(self):
        import pipeline.helpers as p

        def _boom():
            raise ValueError("test boom")

        r, e = p._safe_step("test_fail", _boom)
        assert r is None
        assert "boom" in e
        assert p._last_step_status is not None
        assert p._last_step_status.name == "test_fail"
        assert p._last_step_status.status == StepState.FAIL
        assert p._last_step_status.message_code == "ValueError"
        assert "test boom" in p._last_step_status.message

    def test_safe_step_captures_timing(self):
        import pipeline.helpers as p

        def _slow():
            time.sleep(0.01)
            return "done"

        r, e = p._safe_step("test_timing", _slow)
        assert r == "done"
        # Should have taken at least 10ms
        assert p._last_step_status.duration_ms >= 5.0

    def test_safe_step_started_at_is_epoch(self):
        import pipeline.helpers as p

        before = time.time()
        r, e = p._safe_step("test_epoch", lambda: 1)
        after = time.time()
        assert before <= p._last_step_status.started_at <= after


# ---------------------------------------------------------------------------
# Pipeline summary integration (lightweight — no real CSV)
# ---------------------------------------------------------------------------


class TestPipelineSummaryIntegration:
    """Verify the pipeline dict includes the 'pipeline' key."""

    def test_failed_ingest_includes_pipeline_status(self, tmp_path):
        """When ingest fails, summary['pipeline'] should be present and failed."""
        from pipeline import run_full_analysis

        fake_csv = tmp_path / "nonexistent.csv"
        fake_csv.write_text("bad")

        result = run_full_analysis(
            csv_path=str(fake_csv),
            session_meta={"driver_name": "Test"},
            enable_ml=False,
            enable_report=False,
        )
        assert "pipeline" in result
        p = result["pipeline"]
        assert p["status"] in ("degraded", "failed")
        assert isinstance(p["steps"], list)
        assert p["pipeline_version"].startswith("v")
        assert isinstance(p["degraded"], bool)

    def test_pipeline_version_stable_across_runs(self, tmp_path):
        """Two runs with the same code produce the same pipeline_version."""
        from pipeline import run_full_analysis

        fake_csv = tmp_path / "dummy.csv"
        fake_csv.write_text("bad")

        r1 = run_full_analysis(
            csv_path=str(fake_csv),
            session_meta={"driver_name": "Test"},
            enable_ml=False,
            enable_report=False,
        )
        r2 = run_full_analysis(
            csv_path=str(fake_csv),
            session_meta={"driver_name": "Test"},
            enable_ml=False,
            enable_report=False,
        )
        assert r1["pipeline"]["pipeline_version"] == r2["pipeline"]["pipeline_version"]
