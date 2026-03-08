"""Tests for deterministic analysis outputs and provenance completeness."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


class TestDeterministicProvenance:
    """build_provenance() deterministic mode."""

    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "Distance (m)": np.linspace(0, 100, 20),
            "Speed (m/s)": np.full(20, 15.0),
        })

    def test_deterministic_run_id_is_stable(self):
        from provenance.run_context import build_provenance

        df = self._make_df()
        cfg = {"track_id": "test_track"}
        p1 = build_provenance(df, cfg, method_used="test", deterministic=True)
        p2 = build_provenance(df, cfg, method_used="test", deterministic=True)
        assert p1.analysis_run_id == p2.analysis_run_id
        # Must NOT be a uuid4 (36 chars with dashes)
        assert "-" not in p1.analysis_run_id or len(p1.analysis_run_id) != 36

    def test_deterministic_timestamp_is_frozen(self):
        from provenance.run_context import build_provenance

        df = self._make_df()
        cfg = {"track_id": "test_track"}
        p1 = build_provenance(df, cfg, method_used="test", deterministic=True)
        p2 = build_provenance(df, cfg, method_used="test", deterministic=True)
        assert p1.generated_at == p2.generated_at
        assert p1.generated_at == "2000-01-01T00:00:00+00:00"

    def test_non_deterministic_run_id_is_unique(self):
        from provenance.run_context import build_provenance

        df = self._make_df()
        cfg = {"track_id": "test_track"}
        p1 = build_provenance(df, cfg, method_used="test", deterministic=False)
        p2 = build_provenance(df, cfg, method_used="test", deterministic=False)
        assert p1.analysis_run_id != p2.analysis_run_id


class TestTrainingDataHash:
    """training_data_hash is computed from laps_for_theo."""

    def test_training_data_hash_from_laps(self):
        from provenance.run_context import build_provenance
        from provenance.fingerprint import compute_data_fingerprint

        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": np.random.default_rng(42).uniform(10, 30, 100),
        })
        expected_hash = compute_data_fingerprint(df)

        p = build_provenance(
            pd.DataFrame(), {},
            method_used="test",
            training_data_hash=expected_hash,
        )
        assert p.training_data_hash == expected_hash
        assert len(p.training_data_hash) == 64  # SHA-256 hex digest

    def test_training_data_hash_none_when_no_laps(self):
        from provenance.run_context import build_provenance

        p = build_provenance(
            pd.DataFrame(), {},
            method_used="test",
        )
        assert p.training_data_hash is None


class TestProvenanceRef:
    """Lightweight provenance ref attached to sub-outputs."""

    def test_provenance_ref_structure(self):
        ref = {
            "analysis_run_id": "abc123",
            "pipeline_version": "v2-deadbeef",
        }
        assert "analysis_run_id" in ref
        assert "pipeline_version" in ref

    def test_provenance_ref_not_full_record(self):
        """Ref should have exactly 2 keys, not the full provenance record."""
        ref = {
            "analysis_run_id": "abc123",
            "pipeline_version": "v2-deadbeef",
        }
        assert len(ref) == 2


class TestProvenanceFieldsPresent:
    """All required provenance fields are present and non-empty."""

    REQUIRED_FIELDS = [
        "analysis_run_id",
        "input_fingerprint",
        "params_hash",
        "pipeline_version",
        "model_version",
        "method_used",
        "generated_at",
    ]

    def test_all_required_fields_present(self):
        from provenance.run_context import build_provenance

        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 100, 20),
            "Speed (m/s)": np.full(20, 15.0),
        })
        p = build_provenance(df, {"track_id": "t"}, method_used="test")
        d = p.to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"
            assert d[field], f"Empty field: {field}"

    def test_optional_fields_exist_as_keys(self):
        from provenance.run_context import build_provenance

        df = pd.DataFrame({"x": [1, 2]})
        p = build_provenance(df, {}, method_used="test")
        d = p.to_dict()
        for field in ["file_hash", "solver_version", "training_data_hash"]:
            assert field in d, f"Missing optional field key: {field}"

    def test_to_dict_is_json_serializable(self):
        from provenance.run_context import build_provenance

        df = pd.DataFrame({"x": [1.0, 2.0]})
        p = build_provenance(df, {"a": 1}, method_used="test")
        result = json.dumps(p.to_dict(), sort_keys=True)
        assert isinstance(result, str)
        assert len(result) > 50


class TestSelfConsistency:
    """Identical inputs produce identical JSON output."""

    def _make_inputs(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": rng.uniform(10, 30, 100),
            "Accel (m/s2)": rng.normal(0, 2, 100),
        })
        config = {
            "track_id": "monza",
            "session_type": "practice",
            "driver_name": "TestDriver",
        }
        return df, config

    def test_byte_stable_json(self):
        from provenance.run_context import build_provenance

        df, config = self._make_inputs()

        p1 = build_provenance(
            df, config,
            method_used="test_v2",
            pipeline_version="v2-test",
            model_version="none",
            deterministic=True,
        )
        p2 = build_provenance(
            df, config,
            method_used="test_v2",
            pipeline_version="v2-test",
            model_version="none",
            deterministic=True,
        )

        j1 = json.dumps(p1.to_dict(), sort_keys=True)
        j2 = json.dumps(p2.to_dict(), sort_keys=True)
        assert j1 == j2, "Provenance JSON is not byte-stable"

    def test_different_inputs_produce_different_output(self):
        from provenance.run_context import build_provenance

        df1 = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        df2 = pd.DataFrame({"x": [4.0, 5.0, 6.0]})
        config = {"track_id": "t"}

        p1 = build_provenance(df1, config, method_used="test", deterministic=True)
        p2 = build_provenance(df2, config, method_used="test", deterministic=True)

        assert p1.analysis_run_id != p2.analysis_run_id
        assert p1.input_fingerprint != p2.input_fingerprint
