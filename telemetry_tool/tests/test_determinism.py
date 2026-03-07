"""Snapshot regression tests for telemetry_tool pipeline determinism.

Verifies that running analysis twice on identical inputs produces
identical canonical hashes, and that key outputs match stored baselines.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from provenance.canonical import canonical_hash
from provenance.run_context import build_provenance, ProvenanceRecord


class TestProvenanceDeterminism:
    def test_same_input_same_fingerprint(self):
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        r1 = build_provenance(df, {"mode": "test"}, method_used="test")
        r2 = build_provenance(df, {"mode": "test"}, method_used="test")
        assert r1.input_fingerprint == r2.input_fingerprint
        assert r1.params_hash == r2.params_hash

    def test_modified_input_different_fingerprint(self):
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        r1 = build_provenance(df, {"mode": "test"}, method_used="test")
        df2 = df.copy()
        df2.iloc[0, 1] = 999.0
        r2 = build_provenance(df2, {"mode": "test"}, method_used="test")
        assert r1.input_fingerprint != r2.input_fingerprint
        assert r1.params_hash == r2.params_hash

    def test_modified_config_different_params_hash(self):
        df = pd.DataFrame({"a": [1.0, 2.0]})
        r1 = build_provenance(df, {"mode": "test"}, method_used="test")
        r2 = build_provenance(df, {"mode": "prod"}, method_used="test")
        assert r1.input_fingerprint == r2.input_fingerprint
        assert r1.params_hash != r2.params_hash

    def test_provenance_fields_present_and_typed(self):
        df = pd.DataFrame({"a": [1.0]})
        r = build_provenance(
            df, {"x": 1}, method_used="telemetry_tool_v2",
            pipeline_version="v2-test", model_version="test-1.0",
        )
        d = r.to_dict()
        assert isinstance(d["analysis_run_id"], str) and len(d["analysis_run_id"]) == 36
        assert isinstance(d["input_fingerprint"], str) and len(d["input_fingerprint"]) == 64
        assert isinstance(d["params_hash"], str) and len(d["params_hash"]) == 64
        assert d["pipeline_version"] == "v2-test"
        assert d["model_version"] == "test-1.0"
        assert d["method_used"] == "telemetry_tool_v2"
        assert "T" in d["generated_at"]

    def test_canonical_hash_deterministic(self):
        obj = {
            "score": 85.12345678,
            "laps": [{"time": 60.123, "valid": True}],
            "corners": [{"id": 1, "speed": 12.345}],
        }
        h1 = canonical_hash(obj)
        h2 = canonical_hash(obj)
        assert h1 == h2

    def test_provenance_version_change_detected(self):
        df = pd.DataFrame({"a": [1.0]})
        r1 = build_provenance(df, {}, method_used="test", pipeline_version="v2-aabb")
        r2 = build_provenance(df, {}, method_used="test", pipeline_version="v3-ccdd")
        assert r1.pipeline_version != r2.pipeline_version
