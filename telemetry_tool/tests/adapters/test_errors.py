import pytest
from telemetry_tool.adapters.errors import (
    ParseError, UnrecognizedFormat, MissingColumns,
    CorruptedFile, MissingDependency, InsufficientData,
)

def test_all_errors_inherit_parse_error():
    for cls in (UnrecognizedFormat, MissingColumns, CorruptedFile, MissingDependency, InsufficientData):
        assert issubclass(cls, ParseError)

def test_unrecognized_format_carries_candidates():
    err = UnrecognizedFormat("No match", format_name="unknown", file_path="/tmp/x.bin", candidates=[("racechrono", 0.3)])
    assert err.candidates[0] == ("racechrono", 0.3)
    assert "No match" in str(err)

def test_missing_dependency_carries_install_hint():
    err = MissingDependency("Library not found", format_name="motec_ld", file_path="/tmp/x.ld", package="ldparser", install_hint="pip install ldparser")
    assert err.package == "ldparser"
    assert "pip install" in err.install_hint

def test_missing_columns_carries_lists():
    err = MissingColumns("Missing cols", format_name="vbox", file_path="/tmp/x.vbo", missing=["time_s"], available=["speed_mps"])
    assert err.missing == ["time_s"]

def test_insufficient_data_carries_counts():
    err = InsufficientData("Too few", format_name="vbox", file_path="/tmp/x.vbo", row_count=5, minimum=100)
    assert err.row_count == 5
