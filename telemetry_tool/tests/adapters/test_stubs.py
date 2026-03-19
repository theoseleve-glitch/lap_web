"""Tests for binary-format stub adapters: AiM, RaceChrono RCZ, Qstarz."""
import pytest

from telemetry_tool.adapters.errors import MissingDependency
from telemetry_tool.adapters.aim_adapter import AiMAdapter
from telemetry_tool.adapters.racechrono_rcz_adapter import RaceChronoRCZAdapter
from telemetry_tool.adapters.qstarz_binary_stub import QstarzBinaryStub


class TestAiMStub:
    def test_extensions(self):
        assert ".xrk" in AiMAdapter.EXTENSIONS
        assert ".xrz" in AiMAdapter.EXTENSIONS

    def test_detect_nonexistent(self):
        assert AiMAdapter.detect("/nonexistent.xrk") == 0.0

    def test_detect_returns_nonzero_for_xrk(self, tmp_path):
        xrk = tmp_path / "session.xrk"
        xrk.write_bytes(b"\x00" * 100)
        assert AiMAdapter.detect(str(xrk)) == 0.3

    def test_detect_returns_nonzero_for_xrz(self, tmp_path):
        xrz = tmp_path / "session.xrz"
        xrz.write_bytes(b"\x00" * 100)
        assert AiMAdapter.detect(str(xrz)) == 0.3

    def test_detect_returns_nonzero_for_drk(self, tmp_path):
        drk = tmp_path / "session.drk"
        drk.write_bytes(b"\x00" * 100)
        assert AiMAdapter.detect(str(drk)) == 0.3

    def test_detect_returns_zero_for_empty_file(self, tmp_path):
        xrk = tmp_path / "empty.xrk"
        xrk.write_bytes(b"")
        assert AiMAdapter.detect(str(xrk)) == 0.0

    def test_detect_returns_zero_for_wrong_extension(self, tmp_path):
        csv = tmp_path / "session.csv"
        csv.write_bytes(b"data")
        assert AiMAdapter.detect(str(csv)) == 0.0

    def test_parse_raises_missing_dependency(self, tmp_path):
        xrk = tmp_path / "session.xrk"
        xrk.write_bytes(b"\x00" * 100)
        adapter = AiMAdapter()
        with pytest.raises(MissingDependency, match="AiM SDK"):
            adapter.parse(str(xrk))

    def test_parse_error_has_correct_format_name(self, tmp_path):
        xrk = tmp_path / "session.xrk"
        xrk.write_bytes(b"\x00" * 100)
        adapter = AiMAdapter()
        with pytest.raises(MissingDependency) as exc_info:
            adapter.parse(str(xrk))
        assert exc_info.value.format_name == "aim_xrk"

    def test_metadata_returns_empty(self):
        adapter = AiMAdapter()
        assert adapter.metadata() == {}

    def test_available_channels_returns_empty(self):
        adapter = AiMAdapter()
        assert adapter.available_channels() == []

    def test_format_name(self):
        assert AiMAdapter.FORMAT_NAME == "aim_xrk"


class TestRCZStub:
    def test_extensions(self):
        assert ".rcz" in RaceChronoRCZAdapter.EXTENSIONS

    def test_detect_nonexistent(self):
        assert RaceChronoRCZAdapter.detect("/nonexistent.rcz") == 0.0

    def test_detect_returns_nonzero_for_rcz(self, tmp_path):
        rcz = tmp_path / "session.rcz"
        rcz.write_bytes(b"\x00" * 100)
        assert RaceChronoRCZAdapter.detect(str(rcz)) == 0.3

    def test_detect_returns_zero_for_empty_file(self, tmp_path):
        rcz = tmp_path / "empty.rcz"
        rcz.write_bytes(b"")
        assert RaceChronoRCZAdapter.detect(str(rcz)) == 0.0

    def test_detect_returns_zero_for_wrong_extension(self, tmp_path):
        csv = tmp_path / "session.csv"
        csv.write_bytes(b"data")
        assert RaceChronoRCZAdapter.detect(str(csv)) == 0.0

    def test_parse_raises_missing_dependency(self, tmp_path):
        rcz = tmp_path / "session.rcz"
        rcz.write_bytes(b"\x00" * 50)
        adapter = RaceChronoRCZAdapter()
        with pytest.raises(MissingDependency, match="RaceChrono"):
            adapter.parse(str(rcz))

    def test_parse_error_has_correct_format_name(self, tmp_path):
        rcz = tmp_path / "session.rcz"
        rcz.write_bytes(b"\x00" * 50)
        adapter = RaceChronoRCZAdapter()
        with pytest.raises(MissingDependency) as exc_info:
            adapter.parse(str(rcz))
        assert exc_info.value.format_name == "racechrono_rcz"

    def test_metadata_returns_empty(self):
        adapter = RaceChronoRCZAdapter()
        assert adapter.metadata() == {}

    def test_available_channels_returns_empty(self):
        adapter = RaceChronoRCZAdapter()
        assert adapter.available_channels() == []

    def test_format_name(self):
        assert RaceChronoRCZAdapter.FORMAT_NAME == "racechrono_rcz"


class TestQstarzBinaryStub:
    def test_extensions(self):
        assert ".rcnx" in QstarzBinaryStub.EXTENSIONS
        assert ".rcn" in QstarzBinaryStub.EXTENSIONS

    def test_detect_nonexistent(self):
        assert QstarzBinaryStub.detect("/nonexistent.rcnx") == 0.0

    def test_detect_returns_nonzero_for_rcnx(self, tmp_path):
        rcnx = tmp_path / "session.rcnx"
        rcnx.write_bytes(b"\x00" * 50)
        assert QstarzBinaryStub.detect(str(rcnx)) == 0.3

    def test_detect_returns_nonzero_for_rcn(self, tmp_path):
        rcn = tmp_path / "session.rcn"
        rcn.write_bytes(b"\x00" * 50)
        assert QstarzBinaryStub.detect(str(rcn)) == 0.3

    def test_detect_returns_zero_for_empty_file(self, tmp_path):
        rcnx = tmp_path / "empty.rcnx"
        rcnx.write_bytes(b"")
        assert QstarzBinaryStub.detect(str(rcnx)) == 0.0

    def test_detect_returns_zero_for_wrong_extension(self, tmp_path):
        csv = tmp_path / "session.csv"
        csv.write_bytes(b"data")
        assert QstarzBinaryStub.detect(str(csv)) == 0.0

    def test_parse_raises_missing_dependency(self, tmp_path):
        rcnx = tmp_path / "session.rcnx"
        rcnx.write_bytes(b"\x00" * 50)
        stub = QstarzBinaryStub()
        with pytest.raises(MissingDependency, match="QRacing"):
            stub.parse(str(rcnx))

    def test_parse_error_has_correct_format_name(self, tmp_path):
        rcnx = tmp_path / "session.rcnx"
        rcnx.write_bytes(b"\x00" * 50)
        stub = QstarzBinaryStub()
        with pytest.raises(MissingDependency) as exc_info:
            stub.parse(str(rcnx))
        assert exc_info.value.format_name == "qstarz_binary"

    def test_metadata_returns_empty(self):
        stub = QstarzBinaryStub()
        assert stub.metadata() == {}

    def test_available_channels_returns_empty(self):
        stub = QstarzBinaryStub()
        assert stub.available_channels() == []

    def test_format_name(self):
        assert QstarzBinaryStub.FORMAT_NAME == "qstarz_binary"
