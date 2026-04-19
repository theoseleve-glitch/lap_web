import pytest
from telemetry_tool.tests.adapters.conftest import (
    write_vbox_sample, write_racechrono_csv_sample,
)
from telemetry_tool.tests.adapters.contract import AdapterContractTests
from telemetry_tool.adapters.vbox_adapter import VboxAdapter


class TestVboxContract(AdapterContractTests):
    adapter_cls = VboxAdapter

    @pytest.fixture(autouse=True)
    def _setup_paths(self, tmp_path):
        self.__class__.sample_file_path = str(write_vbox_sample(tmp_path))
        self.__class__.wrong_format_path = str(write_racechrono_csv_sample(tmp_path))


class TestVboxSpecific:
    def test_velocity_knots_converted_to_mps(self, tmp_path):
        vbo = write_vbox_sample(tmp_path)
        adapter = VboxAdapter()
        df = adapter.parse(str(vbo))
        # 58 knots = 58 * 0.514444 ≈ 29.84 m/s
        assert 29.0 < df["speed_mps"].iloc[0] < 31.0

    def test_lat_long_converted_to_degrees(self, tmp_path):
        vbo = write_vbox_sample(tmp_path)
        adapter = VboxAdapter()
        df = adapter.parse(str(vbo))
        # 3060000 minutes*1e-5 = 3060000 / 60000 = 51.0 degrees
        assert 50.0 < df["lat_deg"].iloc[0] < 52.0

    def test_sections_parsed_correctly(self, tmp_path):
        vbo = write_vbox_sample(tmp_path)
        adapter = VboxAdapter()
        df = adapter.parse(str(vbo))
        assert len(df) == 3
        assert "time_s" in df.columns

    def test_detect_returns_high_for_vbo(self, tmp_path):
        vbo = write_vbox_sample(tmp_path)
        assert VboxAdapter.detect(str(vbo)) >= 0.8
