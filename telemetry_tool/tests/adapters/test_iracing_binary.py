import pytest

ibt = pytest.importorskip("ibt", reason="ibt library not installed")

from telemetry_tool.adapters.iracing_binary_adapter import IRacingBinaryAdapter


def test_detect_returns_zero_for_csv(tmp_path):
    csv = tmp_path / "session.csv"
    csv.write_text("Time,Speed\n0.0,10.0\n")
    assert IRacingBinaryAdapter.detect(str(csv)) == 0.0


def test_detect_returns_zero_for_nonexistent():
    assert IRacingBinaryAdapter.detect("/nonexistent/file.ibt") == 0.0


def test_extensions_set():
    assert ".ibt" in IRacingBinaryAdapter.EXTENSIONS


def test_format_name():
    assert IRacingBinaryAdapter.FORMAT_NAME == "iracing_ibt"
