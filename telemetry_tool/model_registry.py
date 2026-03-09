"""
model_registry.py
-----------------
Model versioning, metadata tracking, and persistence for the telemetry
ML pipeline.

Directory layout (under the base models dir from path_manager)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Data/models/
`---- <model_type>/
    `---- <identifier>/
        |---- v1/
        |   |---- model.joblib
        |   `---- metadata.json
        |---- v2/
        |   |---- model.joblib
        |   `---- metadata.json
        `---- latest -> v2          # plain text pointer, not a symlink

Design notes
~~~~~~~~~~~~
- Versions are monotonically incrementing integers (v1, v2, ...).
- "latest" is a small text file holding the current version string so that
  symlinks (which require elevated privileges on Windows) are never needed.
- Metadata is validated at both save and load time to catch drift early.
- should_retrain() uses a configurable growth-ratio threshold so the trigger
  is data-driven, not arbitrary.
- All I/O goes through pathlib; no hard-coded separators.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from feature_schema import FEATURE_COLUMNS
from path_manager import get_models_dir

logger = logging.getLogger(__name__)

# -- -

# Constants

# -- -


_MODEL_FILENAME    = "model.joblib"
_METADATA_FILENAME = "metadata.json"
_LATEST_FILENAME   = "latest"
_VERSION_PREFIX    = "v"
_VERSION_PATTERN   = re.compile(r"^v(\d+)$")

# Retrain when the new sample pool is this many times larger than what the

# current model was trained on.

_DEFAULT_RETRAIN_GROWTH_RATIO = 1.20   # 20 % more data -> retrain

# Bump when the registry metadata schema changes in a backwards-incompatible

# way.  ``load_model`` will refuse to load entries with a different version.

REGISTRY_SCHEMA_VERSION: str = "1"

# Required top-level keys in every metadata record.

_REQUIRED_METADATA_KEYS: frozenset[str] = frozenset(
    ["training_samples", "mae", "created_at", "feature_list"]
)


# -- -

# Exceptions

# -- -


class ModelNotFoundError(FileNotFoundError):
    """Raised when no saved model exists for the requested type/identifier."""


class MetadataValidationError(ValueError):
    """Raised when a metadata dict is missing required keys or has bad values."""


# -- -

# Internal helpers

# -- -


def _registry_root(model_type: str, identifier: str) -> Path:
    """Return  Data/models/<model_type>/<identifier>"""
    return get_models_dir() / model_type / identifier


def _version_dir(model_type: str, identifier: str, version: str) -> Path:
    return _registry_root(model_type, identifier) / version


def _latest_pointer(model_type: str, identifier: str) -> Path:
    return _registry_root(model_type, identifier) / _LATEST_FILENAME


def _parse_version_number(version: str) -> int:
    """Extract the integer from a version string like 'v3', or raise ValueError."""
    m = _VERSION_PATTERN.match(version)
    if not m:
        raise ValueError(f"Invalid version string: {version!r}")
    return int(m.group(1))


def _next_version(model_type: str, identifier: str) -> str:
    """
    Return the next version string (e.g. 'v3') by scanning existing version
    directories.  Returns 'v1' when the registry is empty.
    """
    root = _registry_root(model_type, identifier)
    if not root.exists():
        return f"{_VERSION_PREFIX}1"

    existing_numbers = [
        _parse_version_number(d.name)
        for d in root.iterdir()
        if d.is_dir() and _VERSION_PATTERN.match(d.name)
    ]
    return f"{_VERSION_PREFIX}{max(existing_numbers, default=0) + 1}"


def _validate_metadata(metadata: dict[str, Any]) -> None:
    """
    Raise MetadataValidationError if *metadata* is missing required keys or
    contains obviously invalid values.
    """
    missing = sorted(_REQUIRED_METADATA_KEYS - metadata.keys())
    if missing:
        raise MetadataValidationError(
            f"Metadata is missing required key(s): {missing}"
        )

    errors: list[str] = []

    ts = metadata.get("training_samples")
    if not isinstance(ts, int) or ts < 1:
        errors.append(f"'training_samples' must be a positive int, got {ts!r}")

    mae = metadata.get("mae")
    if not isinstance(mae, (int, float)) or mae < 0:
        errors.append(f"'mae' must be a non-negative number, got {mae!r}")

    ca = metadata.get("created_at")
    if not isinstance(ca, str) or not ca.strip():
        errors.append(f"'created_at' must be a non-empty ISO-8601 string, got {ca!r}")

    fl = metadata.get("feature_list")
    if not isinstance(fl, list) or not fl:
        errors.append(f"'feature_list' must be a non-empty list, got {fl!r}")

    if errors:
        raise MetadataValidationError(
            "Metadata validation failed:\n  " + "\n  ".join(errors)
        )


# -- -

# Public API

# -- -


def save_model(
    model: Any,
    metadata: dict[str, Any],
    model_type: str,
    identifier: str,
) -> str:
    """
    Persist *model* and *metadata* as a new version in the registry.

    Parameters
    ----------
    model:
        Any scikit-learn-compatible model (or pipeline) that joblib can
        serialise.
    metadata:
        Dict containing at minimum:
          - ``training_samples`` (int)  -- number of rows used for training
          - ``mae``              (float) -- mean absolute error on validation set
          - ``created_at``      (str)   -- ISO-8601 timestamp; auto-filled if absent
          - ``feature_list``    (list)  -- ordered list of feature column names
        Additional keys are preserved as-is.
    model_type:
        Logical model category, e.g. ``"lap_time"`` or ``"race_outcome"``.
    identifier:
        Scope of the model, e.g. a driver ID (``"VER"``) or ``"global"``.

    Returns
    -------
    str
        The version string that was assigned (e.g. ``"v3"``).

    Raises
    ------
    MetadataValidationError
        If *metadata* fails validation.
    """
    # Auto-fill created_at if the caller omitted it.

    metadata.setdefault("created_at", datetime.now(timezone.utc).isoformat())

    _validate_metadata(metadata)

    version   = _next_version(model_type, identifier)
    vdir      = _version_dir(model_type, identifier, version)
    vdir.mkdir(parents=True, exist_ok=True)

    model_path    = vdir / _MODEL_FILENAME
    metadata_path = vdir / _METADATA_FILENAME

    # Enrich with registry-managed fields before writing.

    stored_metadata = {
        **metadata,
        "model_type":     model_type,
        "identifier":     identifier,
        "version":        version,
        "schema_version": REGISTRY_SCHEMA_VERSION,
    }

    joblib.dump(model, model_path)
    metadata_path.write_text(
        json.dumps(stored_metadata, indent=2, default=str), encoding="utf-8"
    )

    # Update the "latest" pointer.

    _latest_pointer(model_type, identifier).write_text(version, encoding="utf-8")

    logger.info(
        "Saved model  type=%r  identifier=%r  version=%s  "
        "samples=%d  MAE=%.4f  path=%s",
        model_type, identifier, version,
        metadata["training_samples"], metadata["mae"], vdir,
    )
    return version


def load_model(
    model_type: str,
    identifier: str,
    version: str | None = None,
    *,
    expected_features: list[str] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """
    Load a saved model and its metadata.

    Parameters
    ----------
    model_type:
        Logical model category used when the model was saved.
    identifier:
        Scope used when the model was saved.
    version:
        Specific version to load (e.g. ``"v2"``).  Defaults to the latest
        version when omitted.
    expected_features:
        If given, the loaded metadata's ``feature_list`` is compared to this
        list.  A mismatch raises ``MetadataValidationError`` so the caller
        can retrain.

    Returns
    -------
    (model, metadata) : tuple
        The deserialised model object and its metadata dict.

    Raises
    ------
    ModelNotFoundError
        If no model has been saved for *model_type* / *identifier*, or if
        the requested *version* does not exist.
    MetadataValidationError
        If the on-disk metadata is corrupt, missing required keys, or the
        schema version / feature list does not match expectations.
    """
    if version is None:
        version = get_latest_model_version(model_type, identifier)

    vdir = _version_dir(model_type, identifier, version)
    if not vdir.exists():
        raise ModelNotFoundError(
            f"No model found for type={model_type!r}, identifier={identifier!r}, "
            f"version={version!r}.  Directory does not exist: {vdir}"
        )

    model_path    = vdir / _MODEL_FILENAME
    metadata_path = vdir / _METADATA_FILENAME

    for p in (model_path, metadata_path):
        if not p.exists():
            raise ModelNotFoundError(
                f"Registry entry is incomplete -- missing file: {p}"
            )

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _validate_metadata(metadata)

    # --- schema version gate
    saved_schema = metadata.get("schema_version", "")
    if saved_schema and saved_schema != REGISTRY_SCHEMA_VERSION:
        raise MetadataValidationError(
            f"Registry schema version mismatch: saved {saved_schema!r} "
            f"!= current {REGISTRY_SCHEMA_VERSION!r} for "
            f"type={model_type!r}, identifier={identifier!r}, version={version!r}"
        )

    # --- feature list gate
    if expected_features is not None:
        saved_features = metadata.get("feature_list", [])
        if sorted(saved_features) != sorted(expected_features):
            raise MetadataValidationError(
                f"Feature list mismatch for type={model_type!r}, "
                f"identifier={identifier!r}: model has "
                f"{len(saved_features)} features, caller expects "
                f"{len(expected_features)}.  "
                f"Extra in model: {sorted(set(saved_features) - set(expected_features))}  "
                f"Missing from model: {sorted(set(expected_features) - set(saved_features))}"
            )

    model = joblib.load(model_path)

    logger.info(
        "Loaded model  type=%r  identifier=%r  version=%s  "
        "samples=%d  MAE=%.4f",
        model_type, identifier, version,
        metadata["training_samples"], metadata["mae"],
    )
    return model, metadata


def get_latest_model_version(model_type: str, identifier: str) -> str:
    """
    Return the version string of the most recently saved model.

    Reads the ``latest`` pointer file written by :func:`save_model`.
    Falls back to scanning version directories if the pointer is absent
    (e.g. the registry was created externally).

    Raises
    ------
    ModelNotFoundError
        If no versions exist for *model_type* / *identifier*.
    """
    pointer = _latest_pointer(model_type, identifier)
    if pointer.exists():
        version = pointer.read_text(encoding="utf-8").strip()
        if _VERSION_PATTERN.match(version):
            return version

    # Fallback: scan directories.

    root = _registry_root(model_type, identifier)
    if not root.exists():
        raise ModelNotFoundError(
            f"No registry entry found for type={model_type!r}, "
            f"identifier={identifier!r}.  Expected path: {root}"
        )

    version_numbers = [
        _parse_version_number(d.name)
        for d in root.iterdir()
        if d.is_dir() and _VERSION_PATTERN.match(d.name)
    ]
    if not version_numbers:
        raise ModelNotFoundError(
            f"Registry directory exists but contains no versions: {root}"
        )

    latest = f"{_VERSION_PREFIX}{max(version_numbers)}"
    # Repair the pointer for next time.

    pointer.write_text(latest, encoding="utf-8")
    return latest


def should_retrain(
    old_metadata: dict[str, Any],
    new_sample_count: int,
    *,
    growth_ratio: float = _DEFAULT_RETRAIN_GROWTH_RATIO,
) -> bool:
    """
    Decide whether the model should be retrained based on data growth.

    The rule is intentionally simple and transparent:

        retrain  <-  new_sample_count  >=  old_training_samples x growth_ratio

    This means a model trained on 1 000 rows with the default 1.20 ratio will
    trigger a retrain once 1 200 rows are available.

    Parameters
    ----------
    old_metadata:
        Metadata dict returned by :func:`load_model` (or equivalent).
    new_sample_count:
        Current number of available training rows.
    growth_ratio:
        Multiplier above which retraining is triggered (default: 1.20).
        Must be > 1.0.

    Returns
    -------
    bool
        True if retraining is recommended.

    Raises
    ------
    MetadataValidationError
        If *old_metadata* is missing ``training_samples``.
    ValueError
        If *growth_ratio* <= 1.0 or *new_sample_count* < 0.
    """
    if growth_ratio <= 1.0:
        raise ValueError(
            f"growth_ratio must be > 1.0 to be meaningful, got {growth_ratio}"
        )
    if new_sample_count < 0:
        raise ValueError(
            f"new_sample_count must be non-negative, got {new_sample_count}"
        )

    if "training_samples" not in old_metadata:
        raise MetadataValidationError(
            "old_metadata is missing 'training_samples' -- cannot determine retrain need."
        )

    old_count  = old_metadata["training_samples"]
    threshold  = old_count * growth_ratio
    retrain    = new_sample_count >= threshold

    logger.debug(
        "should_retrain: old_samples=%d  new_samples=%d  "
        "threshold=%.1f  decision=%s",
        old_count, new_sample_count, threshold,
        "RETRAIN" if retrain else "SKIP",
    )
    return retrain


# -- -

# Quick self-test / debug entry-point

# -- -


if __name__ == "__main__":  # pragma: no cover
    import tempfile
    import unittest.mock as mock

    from sklearn.linear_model import Ridge

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Redirect the registry to a temp directory so the test is self-contained.

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_models = Path(tmpdir) / "Data" / "models"
        with mock.patch("model_registry.get_models_dir", return_value=tmp_models):

            MODEL_TYPE = "lap_time"
            IDENT      = "VER"

            meta_v1 = {
                "training_samples": 1000,
                "mae":              0.312,
                "created_at":       datetime.now(timezone.utc).isoformat(),
                "feature_list":     FEATURE_COLUMNS,
                "notes":            "baseline Ridge",
            }
            meta_v2 = {
                "training_samples": 1500,
                "mae":              0.289,
                "feature_list":     FEATURE_COLUMNS,
            }

            model_v1 = Ridge(alpha=1.0)
            model_v2 = Ridge(alpha=0.5)

            print("-- Save v1 --")
            v1 = save_model(model_v1, meta_v1, MODEL_TYPE, IDENT)
            print(f"   Saved as {v1}")

            print("\n-- Save v2 --")
            v2 = save_model(model_v2, meta_v2, MODEL_TYPE, IDENT)
            print(f"   Saved as {v2}")

            print("\n-- get_latest_model_version --")
            latest = get_latest_model_version(MODEL_TYPE, IDENT)
            print(f"   Latest: {latest}")
            assert latest == "v2", f"Expected v2, got {latest}"

            print("\n-- Load latest (no version arg) --")
            loaded_model, loaded_meta = load_model(MODEL_TYPE, IDENT)
            assert loaded_meta["version"] == "v2"
            assert loaded_meta["training_samples"] == 1500
            print(f"   Loaded version={loaded_meta['version']}  MAE={loaded_meta['mae']}")

            print("\n-- Load specific version v1 --")
            _, meta = load_model(MODEL_TYPE, IDENT, version="v1")
            assert meta["version"] == "v1"
            print(f"   Loaded version={meta['version']}  MAE={meta['mae']}")

            print("\n-- should_retrain --")
            print(f"   1200 samples (20 % growth):  {should_retrain(loaded_meta, 1200)}")   # False
            print(f"   1800 samples (20 % growth):  {should_retrain(loaded_meta, 1800)}")   # True
            print(f"   1800 samples (30 % growth):  {should_retrain(loaded_meta, 1800, growth_ratio=1.30)}")  # False

            print("\n-- ModelNotFoundError on unknown identifier --")
            try:
                load_model(MODEL_TYPE, "UNKNOWN_DRIVER")
            except ModelNotFoundError as exc:
                print(f"   Caught expected error: {exc}")

            print("\n-- MetadataValidationError on bad metadata --")
            try:
                save_model(Ridge(), {"training_samples": -5, "mae": 0.1,
                                     "feature_list": FEATURE_COLUMNS}, MODEL_TYPE, IDENT)
            except MetadataValidationError as exc:
                print(f"   Caught expected error: {exc}")

            print("\nOK All checks passed.")