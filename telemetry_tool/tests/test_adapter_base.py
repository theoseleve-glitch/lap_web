"""Tests for the adapter base class and registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure project root is on the path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.adapters import registry as adapter_registry
from telemetry_tool.adapters.base import BaseAdapter


# ---------------------------------------------------------------------------
# Mock adapter for testing
# ---------------------------------------------------------------------------
class _MockAdapter(BaseAdapter):
    """Minimal concrete adapter for testing the ABC contract."""

    FORMAT_NAME = "mock_format"

    def __init__(self) -> None:
        self._channels: list[str] = []
        self._metadata: dict = {}

    @staticmethod
    def detect(file_path: str) -> float:
        """Return 0.9 confidence for any .mock file."""
        if str(file_path).endswith(".mock"):
            return 0.9
        return 0.0

    def parse(self, file_path: str, progress_cb=None) -> pd.DataFrame:
        df = pd.DataFrame({
            "time_s": [0.0, 0.1, 0.2],
            "speed_mps": [10.0, 15.0, 20.0],
            "lat_deg": [50.0, 50.001, 50.002],
            "lon_deg": [6.0, 6.001, 6.002],
            "accel_long_mps2": [1.0, 2.0, 3.0],
            "accel_lat_mps2": [0.5, 1.0, 1.5],
        })
        self._channels = list(df.columns)
        return df

    def metadata(self) -> dict:
        return {"source": "mock"}

    def available_channels(self) -> list[str]:
        return list(self._channels)


class _NeverMatchAdapter(BaseAdapter):
    """Adapter that never matches any file."""

    FORMAT_NAME = "never_match"

    def __init__(self) -> None:
        self._channels: list[str] = []

    @staticmethod
    def detect(file_path: str) -> float:
        return 0.0

    def parse(self, file_path: str, progress_cb=None) -> pd.DataFrame:
        return pd.DataFrame()

    def metadata(self) -> dict:
        return {}

    def available_channels(self) -> list[str]:
        return []


# ---------------------------------------------------------------------------
# BaseAdapter ABC tests
# ---------------------------------------------------------------------------
class TestBaseAdapterABC:
    """Verify that BaseAdapter cannot be instantiated directly."""

    def test_cannot_instantiate_base_adapter(self):
        """BaseAdapter is abstract and raises TypeError on direct instantiation."""
        with pytest.raises(TypeError):
            BaseAdapter()  # type: ignore[abstract]

    def test_mock_adapter_instantiates(self):
        """A concrete subclass can be instantiated."""
        adapter = _MockAdapter()
        assert adapter.FORMAT_NAME == "mock_format"

    def test_format_name_default(self):
        """Default FORMAT_NAME on the base class is 'unknown'."""
        assert BaseAdapter.FORMAT_NAME == "unknown"


# ---------------------------------------------------------------------------
# MockAdapter functionality tests
# ---------------------------------------------------------------------------
class TestMockAdapter:
    """Verify the mock adapter implements the full contract."""

    def test_detect_returns_high_confidence_for_matching_file(self):
        conf = _MockAdapter.detect("session.mock")
        assert conf == pytest.approx(0.9)

    def test_detect_returns_zero_for_non_matching_file(self):
        conf = _MockAdapter.detect("session.csv")
        assert conf == pytest.approx(0.0)

    def test_parse_returns_dataframe(self):
        adapter = _MockAdapter()
        df = adapter.parse("session.mock")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "time_s" in df.columns
        assert "speed_mps" in df.columns

    def test_available_channels_after_parse(self):
        adapter = _MockAdapter()
        adapter.parse("session.mock")
        channels = adapter.available_channels()
        assert "time_s" in channels
        assert "speed_mps" in channels
        assert "accel_long_mps2" in channels

    def test_metadata_returns_dict(self):
        adapter = _MockAdapter()
        meta = adapter.metadata()
        assert isinstance(meta, dict)
        assert meta["source"] == "mock"

    def test_data_tier_returns_at_least_2(self):
        """Mock adapter has time+speed+accel -> tier 2."""
        adapter = _MockAdapter()
        adapter.parse("session.mock")
        tier = adapter.data_tier()
        assert tier >= 2


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------
class TestRegistry:
    """Test the adapter registry: register, detect_format, parse_file."""

    def setup_method(self):
        """Save and clear the global registry before each test."""
        self._saved = list(adapter_registry._ADAPTERS)
        adapter_registry._ADAPTERS.clear()

    def teardown_method(self):
        """Restore the global registry after each test."""
        adapter_registry._ADAPTERS.clear()
        adapter_registry._ADAPTERS.extend(self._saved)

    def test_register_adapter_adds_to_list(self):
        adapter_registry.register_adapter(_MockAdapter)
        assert _MockAdapter in adapter_registry._ADAPTERS

    def test_register_adapter_prevents_duplicates(self):
        adapter_registry.register_adapter(_MockAdapter)
        adapter_registry.register_adapter(_MockAdapter)
        count = adapter_registry._ADAPTERS.count(_MockAdapter)
        assert count == 1

    def test_detect_format_finds_matching_adapter(self):
        adapter_registry.register_adapter(_MockAdapter)
        cls, confidence = adapter_registry.detect_format("session.mock")
        assert cls is _MockAdapter
        assert confidence >= 0.5

    def test_detect_format_returns_none_when_no_match(self):
        adapter_registry.register_adapter(_NeverMatchAdapter)
        cls, confidence = adapter_registry.detect_format("session.xyz")
        assert cls is None
        assert confidence < 0.5

    def test_detect_format_returns_best_match(self):
        """When multiple adapters match, the highest confidence wins."""
        adapter_registry.register_adapter(_MockAdapter)
        adapter_registry.register_adapter(_NeverMatchAdapter)
        cls, confidence = adapter_registry.detect_format("session.mock")
        assert cls is _MockAdapter

    def test_parse_file_raises_on_no_match(self):
        adapter_registry.register_adapter(_NeverMatchAdapter)
        with pytest.raises(ValueError, match="No adapter"):
            adapter_registry.parse_file("session.xyz")

    def test_parse_file_returns_dataframe_and_adapter(self):
        adapter_registry.register_adapter(_MockAdapter)
        df, adapter = adapter_registry.parse_file("session.mock")
        assert isinstance(df, pd.DataFrame)
        assert isinstance(adapter, _MockAdapter)
        assert len(df) == 3

    def test_detect_format_empty_registry(self):
        """Empty registry returns None."""
        cls, confidence = adapter_registry.detect_format("anything.csv")
        assert cls is None
        assert confidence == 0.0
