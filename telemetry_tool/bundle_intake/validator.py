"""BundleValidator — implements intake steps 3-6 (archive + schema + inner checksums).

Called only AFTER the outer archive has been persisted to a temp file and its
outer SHA-256 has been verified against the uploader's declaration.
"""
from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from pathlib import Path

from pydantic import ValidationError

from bundle_intake.domain import BundleSchemaVersion
from bundle_intake.errors import (
    BundleContentInvalidError,
    BundleInnerChecksumMismatchError,
    BundleManifestInvalidError,
    BundleManifestMissingError,
    BundleSchemaVersionUnsupportedError,
)
from bundle_intake.manifest_schema import ManifestV2

logger = logging.getLogger(__name__)

_MANIFEST_FILENAME = "manifest.json"


class BundleValidator:
    """Validates a bundle that has already been persisted to ``path``.

    Every method raises a typed exception on failure. A successful run
    returns the parsed ManifestV2 model.
    """

    def validate_archive(self, path: Path) -> ManifestV2:
        """Steps 3 + 4 + 5: archive integrity, manifest parse, schema version.

        Returns the parsed ManifestV2 on success.
        """
        try:
            zf = zipfile.ZipFile(path, mode="r")
        except zipfile.BadZipFile as exc:
            raise BundleContentInvalidError(
                f"archive is not a valid ZIP: {exc}"
            ) from exc

        with zf:
            bad = zf.testzip()
            if bad is not None:
                raise BundleContentInvalidError(
                    f"archive integrity check failed on entry: {bad}"
                )

            names = set(zf.namelist())
            if _MANIFEST_FILENAME not in names:
                raise BundleManifestMissingError(
                    f"archive has no {_MANIFEST_FILENAME} at root"
                )

            try:
                raw = zf.read(_MANIFEST_FILENAME)
            except KeyError as exc:
                raise BundleManifestMissingError(str(exc)) from exc

            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BundleManifestInvalidError(
                    f"manifest.json is not valid UTF-8 JSON: {exc}"
                ) from exc

            # Schema-version check comes BEFORE Pydantic parse so we can emit a
            # precise error for legacy bundles rather than a Pydantic noise.
            version = parsed.get("schema_version")
            supported = BundleSchemaVersion.supported()
            if not isinstance(version, int) or version not in supported:
                raise BundleSchemaVersionUnsupportedError(
                    f"schema_version={version!r} not in supported set {sorted(supported)}"
                )

            try:
                manifest = ManifestV2.model_validate(parsed)
            except ValidationError as exc:
                raise BundleManifestInvalidError(
                    "manifest.json failed semantic validation",
                    details=[{"pydantic_errors": exc.errors()}],
                ) from exc

            return manifest

    def validate_inner_checksums(self, path: Path, manifest: ManifestV2) -> None:
        """Step 6: every manifest.files[*] must match the archive entry exactly."""
        with zipfile.ZipFile(path, mode="r") as zf:
            names = set(zf.namelist())
            for entry in manifest.files:
                if entry.path not in names:
                    raise BundleInnerChecksumMismatchError(
                        f"manifest lists file {entry.path!r} but it is not in archive",
                        details=[{"path": entry.path, "reason": "missing_in_archive"}],
                    )
                info = zf.getinfo(entry.path)
                if info.file_size != entry.size:
                    raise BundleInnerChecksumMismatchError(
                        f"size mismatch for {entry.path}: "
                        f"archive={info.file_size} manifest={entry.size}",
                        details=[{
                            "path": entry.path, "reason": "size_mismatch",
                            "archive_size": info.file_size,
                            "manifest_size": entry.size,
                        }],
                    )
                h = hashlib.sha256()
                with zf.open(entry.path, mode="r") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        h.update(chunk)
                actual = h.hexdigest()
                if actual != entry.sha256:
                    raise BundleInnerChecksumMismatchError(
                        f"sha256 mismatch for {entry.path}",
                        details=[{
                            "path": entry.path, "reason": "sha256_mismatch",
                            "expected": entry.sha256, "actual": actual,
                        }],
                    )
