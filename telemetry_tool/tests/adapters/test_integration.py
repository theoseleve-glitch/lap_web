"""End-to-end: file → detect → parse → canonical DataFrame with derived columns."""
import pytest
from telemetry_tool.adapters.registry import (
    parse_file, stream_file, supported_extensions, detect_format_two_pass,
)
from telemetry_tool.tests.adapters.conftest import (
    write_vbox_sample, write_racebox_csv_sample,
    write_qstarz_csv_sample, write_racechrono_csv_sample,
)


def test_supported_extensions_includes_all():
    exts = supported_extensions()
    assert ".vbo" in exts
    assert ".csv" in exts


def test_vbox_detected_and_parsed(tmp_path):
    vbo = write_vbox_sample(tmp_path)
    cls, conf = detect_format_two_pass(str(vbo))
    assert cls is not None
    assert cls.FORMAT_NAME == "vbox"
    assert conf >= 0.8

    df, adapter = parse_file(str(vbo))
    assert "time_s" in df.columns or "Time (s)" in df.columns
    assert len(df) > 0


def test_racebox_detected_and_parsed(tmp_path):
    csv = write_racebox_csv_sample(tmp_path)
    cls, conf = detect_format_two_pass(str(csv))
    assert cls is not None
    assert conf >= 0.5

    df, adapter = parse_file(str(csv))
    assert len(df) > 0


def test_racechrono_still_detected(tmp_path):
    csv = write_racechrono_csv_sample(tmp_path)
    cls, conf = detect_format_two_pass(str(csv))
    assert cls is not None
    assert cls.FORMAT_NAME == "racechrono"


def test_stream_file_yields_chunks(tmp_path):
    vbo = write_vbox_sample(tmp_path)
    chunks = list(stream_file(str(vbo)))
    assert len(chunks) >= 1
    total_rows = sum(len(c) for c in chunks)
    assert total_rows > 0
