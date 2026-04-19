"""Tests for BundleValidator — archive / schema / inner-checksum rules."""
from __future__ import annotations

import pytest

from bundle_intake.errors import (
    BundleContentInvalidError,
    BundleInnerChecksumMismatchError,
    BundleManifestInvalidError,
    BundleManifestMissingError,
    BundleSchemaVersionUnsupportedError,
)
from bundle_intake.validator import BundleValidator


class TestValidateArchive:
    def test_good_bundle_returns_parsed_manifest(self, good_bundle):
        manifest = BundleValidator().validate_archive(good_bundle["path"])
        assert manifest.schema_version == 2
        assert manifest.identity.sim == "iracing"

    def test_not_a_zip_file_rejected(self, tmp_path):
        junk = tmp_path / "junk.zip"
        junk.write_bytes(b"this is not a zip archive at all")
        with pytest.raises(BundleContentInvalidError):
            BundleValidator().validate_archive(junk)

    def test_missing_manifest_rejected(self, no_manifest_bundle):
        with pytest.raises(BundleManifestMissingError):
            BundleValidator().validate_archive(no_manifest_bundle["path"])

    def test_invalid_json_manifest_rejected(self, invalid_json_bundle):
        with pytest.raises(BundleManifestInvalidError):
            BundleValidator().validate_archive(invalid_json_bundle["path"])

    def test_v1_schema_version_rejected(self, v1_legacy_bundle):
        with pytest.raises(BundleSchemaVersionUnsupportedError):
            BundleValidator().validate_archive(v1_legacy_bundle["path"])


class TestValidateInnerChecksums:
    def test_good_bundle_passes(self, good_bundle):
        manifest = BundleValidator().validate_archive(good_bundle["path"])
        BundleValidator().validate_inner_checksums(good_bundle["path"], manifest)

    def test_bad_inner_checksum_rejected(self, bad_checksum_bundle):
        manifest = BundleValidator().validate_archive(bad_checksum_bundle["path"])
        with pytest.raises(BundleInnerChecksumMismatchError):
            BundleValidator().validate_inner_checksums(bad_checksum_bundle["path"], manifest)

    def test_degraded_bundle_inner_checksums_still_valid(self, degraded_bundle):
        # Degraded bundle should still have matching inner checksums
        manifest = BundleValidator().validate_archive(degraded_bundle["path"])
        BundleValidator().validate_inner_checksums(degraded_bundle["path"], manifest)
