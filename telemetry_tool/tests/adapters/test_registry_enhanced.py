"""Tests for registry enhancements: supported_extensions, detect_format_two_pass, stream_file."""
from __future__ import annotations

import pandas as pd
import pytest

from telemetry_tool.adapters.base import BaseAdapter
from telemetry_tool.adapters.registry import (
    _ADAPTERS,
    detect_format_two_pass,
    register_adapter,
    stream_file,
    supported_extensions,
)


class FakeVboxAdapter(BaseAdapter):
    FORMAT_NAME = "fake_vbox"
    EXTENSIONS = [".vbo"]

    @staticmethod
    def detect(file_path):
        return 0.9 if file_path.endswith(".vbo") else 0.0

    def parse(self, file_path, progress_cb=None):
        return pd.DataFrame({"time_s": [1.0], "speed_mps": [10.0]})

    def metadata(self):
        return {"format": "vbox"}

    def available_channels(self):
        return ["time_s", "speed_mps"]


@pytest.fixture(autouse=True)
def _isolate_registry():
    saved = list(_ADAPTERS)
    yield
    _ADAPTERS.clear()
    _ADAPTERS.extend(saved)


def test_supported_extensions_includes_registered():
    register_adapter(FakeVboxAdapter)
    assert ".vbo" in supported_extensions()


def test_supported_extensions_returns_set():
    assert isinstance(supported_extensions(), set)


def test_detect_two_pass_matches_by_extension(tmp_path):
    register_adapter(FakeVboxAdapter)
    vbo = tmp_path / "session.vbo"
    vbo.write_text("sats,time,lat\n1,0.0,51.0\n")
    cls, conf = detect_format_two_pass(str(vbo))
    assert cls is FakeVboxAdapter
    assert conf == 0.9


def test_detect_two_pass_falls_back(tmp_path):
    register_adapter(FakeVboxAdapter)
    csv = tmp_path / "session.csv"
    csv.write_text("nothing,here\n1,2\n")
    cls, conf = detect_format_two_pass(str(csv))
    # FakeVbox won't match .csv, falls back to all adapters, still 0.0
    assert conf < 0.5


def test_stream_file_yields_dataframes(tmp_path):
    register_adapter(FakeVboxAdapter)
    vbo = tmp_path / "session.vbo"
    vbo.write_text("fake data")
    chunks = list(stream_file(str(vbo)))
    assert len(chunks) >= 1
    assert isinstance(chunks[0], pd.DataFrame)
