"""Tests for provenance run context (ProvenanceRecord + build_provenance)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.run_context import ProvenanceRecord, build_provenance


class TestProvenanceRecord:
    def test_to_dict_returns_all_fields(self):
        r = ProvenanceRecord(
            analysis_run_id="abc-123",
            input_fingerprint="deadbeef",
            file_hash="cafebabe",
            params_hash="12345678",
            pipeline_version="v2-aabbccdd",
            model_version="none",
            solver_version=None,
            method_used="telemetry_tool_v2",
            generated_at="2026-03-07T12:00:00Z",
            training_data_hash=None,
        )
        d = r.to_dict()
        assert d["analysis_run_id"] == "abc-123"
        assert d["input_fingerprint"] == "deadbeef"
        assert d["file_hash"] == "cafebabe"
        assert d["solver_version"] is None
        assert d["training_data_hash"] is None
        assert len(d) == 10  # all fields present


class TestBuildProvenance:
    def test_returns_provenance_record(self):
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        config = {"some_param": 42}
        record = build_provenance(
            input_df=df,
            config=config,
            method_used="telemetry_tool_v2",
        )
        assert isinstance(record, ProvenanceRecord)
        assert len(record.analysis_run_id) == 36  # UUID4 format
        assert len(record.input_fingerprint) == 64  # SHA-256
        assert len(record.params_hash) == 64
        assert record.method_used == "telemetry_tool_v2"
        assert record.generated_at.endswith("Z") or "+" in record.generated_at

    def test_same_inputs_same_fingerprint(self):
        df = pd.DataFrame({"a": [1.0, 2.0]})
        cfg = {"x": 1}
        r1 = build_provenance(df, cfg, method_used="test")
        r2 = build_provenance(df, cfg, method_used="test")
        assert r1.input_fingerprint == r2.input_fingerprint
        assert r1.params_hash == r2.params_hash
        # But run_ids differ (UUID4 is random)
        assert r1.analysis_run_id != r2.analysis_run_id

    def test_file_hash_populated_when_path_given(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        df = pd.DataFrame({"a": [1.0], "b": [2.0]})
        record = build_provenance(df, {}, method_used="test", file_path=str(f))
        assert record.file_hash is not None and len(record.file_hash) == 64

    def test_file_hash_none_when_no_path(self):
        df = pd.DataFrame({"a": [1.0]})
        record = build_provenance(df, {}, method_used="test")
        assert record.file_hash is None
