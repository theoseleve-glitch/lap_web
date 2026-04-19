import pytest
from telemetry_tool.tests.adapters.conftest import (
    write_qstarz_csv_sample, write_racechrono_csv_sample,
)
from telemetry_tool.tests.adapters.contract import AdapterContractTests
from telemetry_tool.adapters.qstarz_csv_adapter import QstarzCSVAdapter


class TestQstarzContract(AdapterContractTests):
    adapter_cls = QstarzCSVAdapter

    @pytest.fixture(autouse=True)
    def _setup_paths(self, tmp_path):
        self.__class__.sample_file_path = str(write_qstarz_csv_sample(tmp_path))
        self.__class__.wrong_format_path = str(write_racechrono_csv_sample(tmp_path))


class TestQstarzSpecific:
    def test_speed_converted_to_mps(self, tmp_path):
        csv = write_qstarz_csv_sample(tmp_path)
        adapter = QstarzCSVAdapter()
        df = adapter.parse(str(csv))
        # 80.5 km/h ≈ 22.36 m/s
        assert 22.0 < df["speed_mps"].iloc[0] < 23.0

    def test_lat_ns_parsed_correctly(self, tmp_path):
        csv = write_qstarz_csv_sample(tmp_path)
        adapter = QstarzCSVAdapter()
        df = adapter.parse(str(csv))
        assert df["lat_deg"].iloc[0] > 0  # N hemisphere

    def test_detect_score_high_for_qstarz(self, tmp_path):
        csv = write_qstarz_csv_sample(tmp_path)
        assert QstarzCSVAdapter.detect(str(csv)) >= 0.7
