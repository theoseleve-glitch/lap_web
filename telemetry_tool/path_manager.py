"""
path_manager.py
---------------
Centralizes all filesystem paths for the project.

Handles three runtime contexts:

1. **Normal Python** → base dir is the folder containing this file.
2. **PyInstaller 6.x frozen bundle** → two roots:
   - *Writable base* (``sys.executable.parent``): next to the .exe.
     Used for ``data/``, ``models/``, ``results/`` — anything that
     must persist or be updated across runs.
   - *Bundle base* (``sys._MEIPASS``): the ``_internal/`` folder
     containing read-only assets packed by PyInstaller.  Used as a
     **fallback** seed for first-run bootstrapping only.
3. **Older PyInstaller (<6)** → same as 2, but ``_MEIPASS`` points
   to a temp directory (no ``_internal/``).

First-run bootstrap
~~~~~~~~~~~~~~~~~~~
When the .exe runs for the first time the writable ``models/`` dir
won't exist yet.  ``bootstrap_frozen_dirs()`` copies bundled seed data
from ``_MEIPASS`` and creates empty skeleton directories so everything
works immediately.

All paths are built with pathlib — Windows, macOS, and Linux safe.
No hard-coded strings; every directory name is defined once as a constant.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# -- -

# Directory-name constants  (single source of truth)

# -- -

_DIR_DATA       = "data"
_DIR_RAW        = "raw"
_DIR_PROCESSED  = "processed"
_DIR_MODELS     = "models"
_DIR_RESULTS    = "results"


# -- -

# Base-directory resolution

# -- -


def get_base_dir() -> Path:
    """
    Return the **writable** project root.

    * Frozen (PyInstaller) → folder containing the ``.exe``.
    * Normal Python run    → folder containing *this* file.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def get_bundle_dir() -> Path | None:
    """
    Return the PyInstaller bundle extraction directory, or ``None``
    if not running frozen.

    In PyInstaller 6.x this is the ``_internal/`` subfolder next to
    the ``.exe``.  In older versions it is a temp directory.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        return Path(meipass).resolve()
    return None


# -- -

# Data directories

# -- -


def get_data_raw_dir() -> Path:
    """Return  ``<base>/data/raw``."""
    return get_base_dir() / _DIR_DATA / _DIR_RAW


def get_data_processed_dir() -> Path:
    """Return  ``<base>/data/processed``."""
    return get_base_dir() / _DIR_DATA / _DIR_PROCESSED


# -- -

# Models directory

# -- -


def get_models_dir() -> Path:
    """Return  ``<base>/models``."""
    return get_base_dir() / _DIR_MODELS


# -- -

# Results directory (per-track)

# -- -


def get_db_path() -> Path:
    """Return  ``<base>/telemetry.db``."""
    return get_base_dir() / "telemetry.db"


def get_results_dir(track_id: str) -> Path:
    """
    Return  ``<base>/results/<track_id>``.

    Raises ``ValueError`` if *track_id* is empty or contains path separators.
    """
    if not track_id or not track_id.strip():
        raise ValueError("track_id must be a non-empty string.")
    if any(sep in track_id for sep in ("/", "\\")):
        raise ValueError(
            f"track_id must not contain path separators, got: {track_id!r}"
        )
    return get_base_dir() / _DIR_RESULTS / track_id


# -- -

# Convenience helper

# -- -


def ensure_dirs(*paths: Path) -> None:
    """Create each directory (and parents).  Safe if already exists."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


# -- -

# First-run bootstrap for frozen builds

# -- -


def bootstrap_frozen_dirs() -> None:
    """
    Create the writable directory skeleton next to the ``.exe`` and
    seed it with any bundled data from ``_MEIPASS``.

    Safe to call repeatedly — only copies files that don't already exist.
    Does nothing when not running as a frozen PyInstaller build.
    """
    if not getattr(sys, "frozen", False):
        return

    base    = get_base_dir()
    bundle  = get_bundle_dir()

    # 1. Create skeleton directories

    for sub in (
        _DIR_DATA,
        f"{_DIR_DATA}/{_DIR_RAW}",
        f"{_DIR_DATA}/{_DIR_PROCESSED}",
        _DIR_MODELS,
        _DIR_RESULTS,
    ):
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)

    # 2. Copy bundled seed data from _MEIPASS → writable base

    if bundle is None:
        return

    for dir_name in (_DIR_MODELS, _DIR_DATA):
        src = bundle / dir_name
        dst = base / dir_name
        if not src.is_dir():
            continue
        _copy_tree_no_overwrite(src, dst)

    logger.info("Bootstrap complete: %s", base)


def _copy_tree_no_overwrite(src: Path, dst: Path) -> None:
    """
    Recursively copy *src* into *dst*, skipping files that already exist
    in *dst*.  This preserves user-modified data (e.g. updated tracks.json)
    while seeding new files from the bundle.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            _copy_tree_no_overwrite(item, target)
        elif not target.exists():
            shutil.copy2(item, target)
            logger.debug("Seeded: %s", target)


# -- -

# Self-test

# -- -


if __name__ == "__main__":  # pragma: no cover
    print("Frozen:            ", getattr(sys, "frozen", False))
    print("Base dir:          ", get_base_dir())
    print("Bundle dir:        ", get_bundle_dir())
    print("Data raw dir:      ", get_data_raw_dir())
    print("Data processed dir:", get_data_processed_dir())
    print("Models dir:        ", get_models_dir())
    print("Results dir [run1]:", get_results_dir("run1"))