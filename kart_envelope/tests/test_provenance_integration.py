"""Test provenance injection into kart_envelope pipeline summary."""
import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TT_ROOT = _PROJECT_ROOT / "telemetry_tool"
if str(_TT_ROOT) not in sys.path:
    sys.path.insert(0, str(_TT_ROOT))

from provenance.run_context import build_provenance


def test_kart_provenance_record():
    """Verify provenance record can be built for kart_envelope."""
    df = pd.DataFrame({
        "Distance (m)": [0.0, 0.5, 1.0],
        "Speed (m/s)": [10.0, 11.0, 12.0],
    })
    record = build_provenance(
        df,
        {"model_version": "1.0", "solver_backend": "scipy"},
        method_used="kart_envelope_v2.2",
        solver_version="scipy",
        pipeline_version="v2.2",
        model_version="1.0",
    )
    d = record.to_dict()
    assert d["method_used"] == "kart_envelope_v2.2"
    assert d["solver_version"] == "scipy"
    assert d["pipeline_version"] == "v2.2"
    assert d["model_version"] == "1.0"
    assert len(d["analysis_run_id"]) == 36
    assert len(d["input_fingerprint"]) == 64


def test_provenance_record_to_dict_keys():
    """Verify all expected keys are present in the provenance dict."""
    df = pd.DataFrame({"col_a": [1, 2, 3]})
    record = build_provenance(
        df,
        {"key": "value"},
        method_used="test_method",
        pipeline_version="0.1",
        model_version="0.1",
    )
    d = record.to_dict()
    expected_keys = {
        "analysis_run_id",
        "input_fingerprint",
        "file_hash",
        "params_hash",
        "pipeline_version",
        "model_version",
        "solver_version",
        "method_used",
        "generated_at",
        "training_data_hash",
    }
    assert set(d.keys()) == expected_keys


def test_provenance_no_file_path():
    """file_hash should be None when no file_path is provided."""
    df = pd.DataFrame({"x": [1.0]})
    record = build_provenance(
        df,
        {},
        method_used="kart_envelope_v2.2",
        pipeline_version="2.2",
        model_version="1.0",
    )
    assert record.file_hash is None


def test_provenance_empty_dataframe():
    """Provenance should handle empty DataFrames gracefully."""
    df = pd.DataFrame()
    record = build_provenance(
        df,
        {"solver_backend": "scipy"},
        method_used="kart_envelope_v2.2",
        pipeline_version="2.2",
        model_version="1.0",
    )
    d = record.to_dict()
    assert len(d["input_fingerprint"]) == 64
    assert len(d["analysis_run_id"]) == 36
