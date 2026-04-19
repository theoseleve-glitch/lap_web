"""Typed exceptions for bundle intake.

Each exception maps to one ErrorCode in web/api_utils.py. Callers re-raise from
low-level exceptions so the HTTP layer can translate cleanly without
sprawling try/except.
"""
from __future__ import annotations


class BundleIntakeError(Exception):
    """Base class. Never raised directly."""
    code: str = "BUNDLE_INTAKE_ERROR"
    http_status: int = 400

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class BundleFileMissingError(BundleIntakeError):
    code = "BUNDLE_FILE_MISSING"
    http_status = 400


class BundleSizeExceededError(BundleIntakeError):
    code = "BUNDLE_SIZE_EXCEEDED"
    http_status = 413


class BundleContentInvalidError(BundleIntakeError):
    """ZIP integrity check failed, not a zip, etc."""
    code = "BUNDLE_CONTENT_INVALID"
    http_status = 415


class BundleManifestMissingError(BundleIntakeError):
    code = "BUNDLE_MANIFEST_MISSING"
    http_status = 422


class BundleManifestInvalidError(BundleIntakeError):
    code = "BUNDLE_MANIFEST_INVALID"
    http_status = 422


class BundleSchemaVersionUnsupportedError(BundleIntakeError):
    code = "BUNDLE_SCHEMA_VERSION_UNSUPPORTED"
    http_status = 422


class BundleChecksumMismatchError(BundleIntakeError):
    """Outer archive checksum doesn't match X-Bundle-Sha256."""
    code = "BUNDLE_CHECKSUM_MISMATCH"
    http_status = 422


class BundleInnerChecksumMismatchError(BundleIntakeError):
    """An inner file's checksum doesn't match its manifest.files[*].sha256."""
    code = "BUNDLE_INNER_CHECKSUM_MISMATCH"
    http_status = 422


class BundleDuplicateError(BundleIntakeError):
    code = "BUNDLE_DUPLICATE"
    http_status = 409


class ReadinessNotMetError(BundleIntakeError):
    """Raised when /analyze is invoked on a degraded bundle."""
    code = "READINESS_NOT_MET"
    http_status = 409
