"""Snapshot regression tests for kart_envelope pipeline determinism.

Uses the synthetic_oval_laps fixture from conftest.py (seeded with
np.random.seed(42)) to verify reproducible outputs.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TT_ROOT = _PROJECT_ROOT / "telemetry_tool"
if str(_TT_ROOT) not in sys.path:
    sys.path.insert(0, str(_TT_ROOT))

from provenance.canonical import canonical_hash
from provenance.run_context import build_provenance


class TestKartProvenanceDeterminism:
    def test_same_input_same_fingerprint(self, synthetic_oval_laps):
        lap_df = synthetic_oval_laps[1]
        r1 = build_provenance(
            lap_df, {"solver": "scipy"}, method_used="kart_envelope_v2.2",
            pipeline_version="v2.2", model_version="1.0",
        )
        r2 = build_provenance(
            lap_df, {"solver": "scipy"}, method_used="kart_envelope_v2.2",
            pipeline_version="v2.2", model_version="1.0",
        )
        assert r1.input_fingerprint == r2.input_fingerprint
        assert r1.params_hash == r2.params_hash

    def test_different_lap_different_fingerprint(self, synthetic_oval_laps):
        r1 = build_provenance(
            synthetic_oval_laps[1], {}, method_used="test",
            pipeline_version="v2.2", model_version="1.0",
        )
        modified = synthetic_oval_laps[1].copy()
        modified.iloc[0, 0] = 999.0
        r2 = build_provenance(
            modified, {}, method_used="test",
            pipeline_version="v2.2", model_version="1.0",
        )
        assert r1.input_fingerprint != r2.input_fingerprint

    def test_provenance_fields_present(self, synthetic_oval_laps):
        lap_df = synthetic_oval_laps[1]
        r = build_provenance(
            lap_df,
            {"solver": "scipy", "model_version": "1.0"},
            method_used="kart_envelope_v2.2",
            pipeline_version="v2.2",
            model_version="1.0",
            solver_version="scipy",
        )
        d = r.to_dict()
        assert d["method_used"] == "kart_envelope_v2.2"
        assert d["solver_version"] == "scipy"
        assert d["pipeline_version"] == "v2.2"
        assert d["model_version"] == "1.0"
        assert len(d["analysis_run_id"]) == 36
        assert len(d["input_fingerprint"]) == 64
        assert len(d["params_hash"]) == 64

    def test_canonical_hash_stable_for_kart_output(self):
        summary_fragment = {
            "version": "2.2",
            "theoretical_lap_time_s": 42.567891234,
            "corner_perfs": [
                {"corner_id": 1, "speed_m_s": 12.345, "rating": "good"},
                {"corner_id": 2, "speed_m_s": 10.123, "rating": "fair"},
            ],
            "coaching_text": "Brake later into T1",
        }
        h1 = canonical_hash(summary_fragment)
        h2 = canonical_hash(summary_fragment)
        assert h1 == h2
