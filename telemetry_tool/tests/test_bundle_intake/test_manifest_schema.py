"""Tests for ManifestV2 Pydantic model."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from bundle_intake.manifest_schema import ManifestV2


def _base_manifest(**overrides):
    data = {
        "schema_version": 2,
        "identity": {
            "sim": "iracing", "vehicle_key": "mx5", "track_key": "daytona",
            "session_type": "practice", "started_at": "2026-04-15T10:20:00+00:00",
        },
        "source": {
            "logger_version": "2.3.0", "logger_build": "abc",
            "capture_method": "iracing_ibt",
            "captured_at": "2026-04-15T10:20:00+00:00",
            "captured_by_user_id": 42,
        },
        "files": [{
            "path": "telemetry.ibt", "size": 100,
            "sha256": "a" * 64, "role": "telemetry",
        }],
        "metadata": {
            "vehicle_spec": {}, "track_spec": {}, "session_info": {},
            "channels_present": [], "lap_count": 0, "duration_s": 0.0, "extra": {},
        },
    }
    data.update(overrides)
    return data


class TestAcceptance:
    def test_parses_valid_manifest(self):
        manifest = ManifestV2.model_validate(_base_manifest())
        assert manifest.schema_version == 2
        assert manifest.identity.sim == "iracing"

    def test_sim_is_lowercased(self):
        data = _base_manifest()
        data["identity"]["sim"] = "IRACING"
        assert ManifestV2.model_validate(data).identity.sim == "iracing"


class TestRejection:
    def test_schema_version_1_rejected(self):
        with pytest.raises(ValidationError):
            ManifestV2.model_validate(_base_manifest(schema_version=1))

    def test_missing_schema_version(self):
        data = _base_manifest()
        del data["schema_version"]
        with pytest.raises(ValidationError):
            ManifestV2.model_validate(data)

    def test_empty_files_list_rejected(self):
        with pytest.raises(ValidationError):
            ManifestV2.model_validate(_base_manifest(files=[]))

    def test_duplicate_paths_rejected(self):
        data = _base_manifest()
        data["files"] = [
            {"path": "x.ibt", "size": 1, "sha256": "a" * 64, "role": "telemetry"},
            {"path": "x.ibt", "size": 1, "sha256": "b" * 64, "role": "aux"},
        ]
        with pytest.raises(ValidationError, match="duplicate paths"):
            ManifestV2.model_validate(data)

    def test_uppercase_sha_rejected(self):
        data = _base_manifest()
        data["files"][0]["sha256"] = "A" * 64
        # Lowercased by validator → OK
        parsed = ManifestV2.model_validate(data)
        assert parsed.files[0].sha256 == "a" * 64

    def test_non_hex_sha_rejected(self):
        data = _base_manifest()
        data["files"][0]["sha256"] = "z" * 64
        with pytest.raises(ValidationError):
            ManifestV2.model_validate(data)

    def test_unknown_top_level_field_rejected(self):
        data = _base_manifest()
        data["rogue_field"] = 1
        with pytest.raises(ValidationError):
            ManifestV2.model_validate(data)

    def test_unknown_role_rejected(self):
        data = _base_manifest()
        data["files"][0]["role"] = "not_a_role"
        with pytest.raises(ValidationError):
            ManifestV2.model_validate(data)
