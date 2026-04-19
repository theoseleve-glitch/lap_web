"""Tests for the RaceBox CSV adapter."""
import pytest
from telemetry_tool.tests.adapters.conftest import (
    write_racebox_csv_sample, write_racechrono_csv_sample,
)
from telemetry_tool.tests.adapters.contract import AdapterContractTests
from telemetry_tool.adapters.racebox_adapter import RaceBoxCSVAdapter


class TestRaceBoxContract(AdapterContractTests):
    adapter_cls = RaceBoxCSVAdapter

    @pytest.fixture(autouse=True)
    def _setup_paths(self, tmp_path):
        self.__class__.sample_file_path = str(write_racebox_csv_sample(tmp_path))
        self.__class__.wrong_format_path = str(write_racechrono_csv_sample(tmp_path))


class TestRaceBoxSpecific:
    def test_speed_kmh_converted_to_mps(self, tmp_path):
        csv = write_racebox_csv_sample(tmp_path)
        adapter = RaceBoxCSVAdapter()
        df = adapter.parse(str(csv))
        # 80.5 km/h = ~22.36 m/s
        assert 22.0 < df["speed_mps"].iloc[0] < 23.0

    def test_utc_time_parsed_to_seconds(self, tmp_path):
        csv = write_racebox_csv_sample(tmp_path)
        adapter = RaceBoxCSVAdapter()
        df = adapter.parse(str(csv))
        assert df["time_s"].iloc[0] == 0.0
        assert df["time_s"].iloc[1] == pytest.approx(0.1, abs=0.01)

    def test_detect_rejects_racechrono(self, tmp_path):
        csv = write_racechrono_csv_sample(tmp_path)
        assert RaceBoxCSVAdapter.detect(str(csv)) < 0.5
