"""Tests for build_session_bundle."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from desktop_sync.bundle_builder import build_session_bundle, compute_bundle_checksum


class TestBuildSessionBundle:
    def test_produces_valid_manifest_v2_zip(self, tmp_path):
        ibt = tmp_path / "input" / "session.ibt"
        ibt.parent.mkdir()
        ibt.write_bytes(b"FAKE_IBT" * 100)

        out = build_session_bundle(
            ibt_path=ibt,
            track_name="Daytona Road Course",
            car_name="McLaren 570S GT4",
            output_dir=tmp_path / "bundles",
        )
        assert out.is_file()
        assert out.suffix == ".zip"

        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names
            assert "telemetry.ibt" in names

            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["schema_version"] == 2
            assert manifest["identity"]["sim"] == "iracing"
            assert manifest["identity"]["vehicle_key"] == "mclaren_570s_gt4"
            assert manifest["identity"]["track_key"] == "daytona_road_course"
            assert manifest["metadata"]["vehicle_spec"] == {}

    def test_ibt_content_preserved(self, tmp_path):
        payload = b"REAL_IBT_CONTENT" * 50
        ibt = tmp_path / "session.ibt"
        ibt.write_bytes(payload)

        out = build_session_bundle(
            ibt_path=ibt,
            track_name="Spa",
            car_name="MX5",
        )
        with zipfile.ZipFile(out) as zf:
            assert zf.read("telemetry.ibt") == payload

    def test_includes_capture_meta_as_aux(self, tmp_path):
        ibt = tmp_path / "session.ibt"
        ibt.write_bytes(b"x" * 16)
        meta = {"track_name": "Spa", "car_name": "MX5", "collected_at": "2026-04-16T10:00:00Z"}

        out = build_session_bundle(
            ibt_path=ibt,
            track_name="Spa",
            car_name="MX5",
            capture_meta=meta,
        )
        with zipfile.ZipFile(out) as zf:
            assert "capture_meta.json" in zf.namelist()
            manifest = json.loads(zf.read("manifest.json"))
            aux_files = [f for f in manifest["files"] if f["role"] == "aux"]
            assert len(aux_files) == 1

    def test_ibt_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_session_bundle(
                ibt_path=tmp_path / "nonexistent.ibt",
                track_name="X",
                car_name="Y",
            )

    def test_checksum_is_deterministic(self, tmp_path):
        ibt = tmp_path / "session.ibt"
        ibt.write_bytes(b"DETERMINISTIC" * 10)
        out = build_session_bundle(ibt_path=ibt, track_name="X", car_name="Y",
                                   output_dir=tmp_path / "a")
        c1 = compute_bundle_checksum(out)
        assert len(c1) == 64
        assert all(ch in "0123456789abcdef" for ch in c1)
