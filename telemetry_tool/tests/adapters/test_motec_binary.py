import pytest

ldparser = pytest.importorskip("ldparser", reason="ldparser library not installed")

from telemetry_tool.adapters.motec_binary_adapter import MoTeCBinaryAdapter


def test_detect_returns_zero_for_csv(tmp_path):
    csv = tmp_path / "session.csv"
    csv.write_text("Time,Speed\n0.0,10.0\n")
    assert MoTeCBinaryAdapter.detect(str(csv)) == 0.0


def test_extensions_set():
    assert ".ld" in MoTeCBinaryAdapter.EXTENSIONS
    assert ".ldx" in MoTeCBinaryAdapter.EXTENSIONS


def test_format_name():
    assert MoTeCBinaryAdapter.FORMAT_NAME == "motec_ld"
