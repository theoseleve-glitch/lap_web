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
