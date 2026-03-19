import pandas as pd
import pytest
from telemetry_tool.adapters.base import BaseAdapter

class ConcreteAdapter(BaseAdapter):
    FORMAT_NAME = "test"
    EXTENSIONS = [".test"]
    @staticmethod
    def detect(file_path): return 0.0
    def parse(self, file_path, progress_cb=None):
        return pd.DataFrame({"time_s": [1.0, 2.0], "speed_mps": [10.0, 20.0]})
    def metadata(self): return {}
    def available_channels(self): return ["time_s", "speed_mps"]

class StreamingAdapter(ConcreteAdapter):
    FORMAT_NAME = "test_streaming"
    def stream(self, file_path, *, config=None, progress_cb=None):
        df = self.parse(file_path)
        yield df.iloc[:1]
        yield df.iloc[1:]

def test_base_has_extensions_default():
    assert BaseAdapter.EXTENSIONS == []

def test_base_has_magic_bytes_default():
    assert BaseAdapter.MAGIC_BYTES is None

def test_concrete_extensions():
    assert ConcreteAdapter().EXTENSIONS == [".test"]

def test_default_stream_yields_single_dataframe():
    chunks = list(ConcreteAdapter().stream("/fake"))
    assert len(chunks) == 1
    assert len(chunks[0]) == 2

def test_supports_streaming_false_for_default():
    assert ConcreteAdapter().supports_streaming is False

def test_supports_streaming_true_for_override():
    assert StreamingAdapter().supports_streaming is True

def test_overridden_stream_yields_multiple():
    chunks = list(StreamingAdapter().stream("/fake"))
    assert len(chunks) == 2
    assert sum(len(c) for c in chunks) == 2
