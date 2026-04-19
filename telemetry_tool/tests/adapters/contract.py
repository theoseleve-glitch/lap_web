"""Universal contract tests every adapter must pass."""
from __future__ import annotations

import pandas as pd
import pytest


class AdapterContractTests:
    """Mixin of contract tests for telemetry format adapters.

    Subclass this alongside ``pytest`` test discovery (e.g.
    ``class TestMyAdapter(AdapterContractTests):``) and set the three
    class attributes to wire the tests up to your adapter.

    Class Attributes
    ----------------
    adapter_cls:
        The adapter class under test (a ``BaseAdapter`` subclass).
    sample_file_path:
        Path to a valid sample file for this format.
    wrong_format_path:
        Path to a file of a *different* format.
    """

    adapter_cls = None
    sample_file_path = None
    wrong_format_path = None

    def _make(self):
        assert self.adapter_cls is not None
        return self.adapter_cls()

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def test_detect_high_confidence_for_own_format(self):
        conf = self.adapter_cls.detect(self.sample_file_path)
        assert conf >= 0.5, f"Expected >=0.5, got {conf}"

    def test_detect_low_confidence_for_wrong_format(self):
        conf = self.adapter_cls.detect(self.wrong_format_path)
        assert conf < 0.5, f"Expected <0.5, got {conf}"

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def test_parse_returns_dataframe(self):
        df = self._make().parse(self.sample_file_path)
        assert isinstance(df, pd.DataFrame) and len(df) > 0

    def test_required_columns_present(self):
        df = self._make().parse(self.sample_file_path)
        assert "time_s" in df.columns, f"Missing time_s. Cols: {list(df.columns)}"
        assert "speed_mps" in df.columns, f"Missing speed_mps. Cols: {list(df.columns)}"

    def test_units_are_si(self):
        df = self._make().parse(self.sample_file_path)
        if "speed_mps" in df.columns:
            assert df["speed_mps"].max() < 150, "speed likely not m/s"

    def test_time_monotonically_increasing(self):
        df = self._make().parse(self.sample_file_path)
        if "time_s" in df.columns:
            diffs = df["time_s"].diff().dropna()
            assert (diffs >= 0).all()

    # ------------------------------------------------------------------
    # Metadata & channels
    # ------------------------------------------------------------------

    def test_metadata_returns_dict(self):
        a = self._make()
        a.parse(self.sample_file_path)
        assert isinstance(a.metadata(), dict)

    def test_available_channels_returns_list(self):
        a = self._make()
        a.parse(self.sample_file_path)
        assert isinstance(a.available_channels(), list)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def test_stream_yields_dataframes(self):
        chunks = list(self._make().stream(self.sample_file_path))
        assert len(chunks) >= 1
        for c in chunks:
            assert isinstance(c, pd.DataFrame)

    def test_stream_total_rows_match_parse(self):
        a1 = self._make()
        df = a1.parse(self.sample_file_path)
        a2 = self._make()
        chunks = list(a2.stream(self.sample_file_path))
        assert sum(len(c) for c in chunks) == len(df)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_file_returns_zero_confidence(self, tmp_path):
        ext = self.adapter_cls.EXTENSIONS[0] if self.adapter_cls.EXTENSIONS else ""
        empty = tmp_path / f"empty{ext}"
        empty.write_text("")
        assert self.adapter_cls.detect(str(empty)) == 0.0

    def test_nonexistent_file_returns_zero_confidence(self):
        assert self.adapter_cls.detect("/nonexistent/path/file.xyz") == 0.0
