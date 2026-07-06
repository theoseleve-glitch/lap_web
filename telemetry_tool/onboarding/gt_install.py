"""onboarding/gt_install.py
----------------------------
Cross-process-safe GT install core: validate -> copy -> register-alias.

Extracted out of ``onboarding/bless_service.py`` (final-review finding M3)
for two reasons: (1) ``bless_service.py`` was at its 500-line file-size
budget, and (2) this is where the fix belongs -- see below.
``bless_service.py`` re-imports ``InstallError``/``install_gt_geojson`` back
in (for backward-compat re-export, so no external call site -- including
``scripts/bless_gt.py`` -- needs to change its import), and both it
(``bless_service.bless_geometry``, the web bless path) and the CLI
(``scripts/bless_gt.py``) call :func:`install_gt_geojson` here, sharing one
implementation, exactly as before this extraction.

M3 fix -- non-atomic alias-registry read-modify-write:
``install_gt_geojson`` does ``_load_aliases_registry`` -> mutate the dict ->
``_save_aliases_registry`` on the shared ``track_aliases.json``. Two
concurrent blesses of DIFFERENT tracks (multiple gunicorn workers) could
previously interleave: worker A loads, worker B loads (sees A's
pre-mutation state), A saves, B saves -- B's save silently overwrites A's
newly-added entry (trusted-store corruption, rare in practice since blessing
is operator-only with one open request per track, but real). This is now
serialized with :class:`_RegistryFileLock`, a minimal cross-process
advisory lock using the same ``O_CREAT | O_EXCL`` spin-with-timeout idiom
already proven elsewhere in this codebase (``parquet_manager._FileLock``,
used for exactly this class of problem) -- implemented locally rather than
imported, since it is a handful of lines and importing a private
underscore-prefixed class across unrelated modules would be more fragile
than just re-stating the (simple, well-understood) primitive here. No
``filelock``/``portalocker`` dependency exists in this codebase (grepped),
so no new third-party dependency was added.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from track_surface.gt_validate import validate_gt_geojson

logger = logging.getLogger(__name__)

__all__ = ["InstallError", "install_gt_geojson"]

_LOCK_TIMEOUT_S = 30      # seconds to wait for an existing lock to clear
_LOCK_POLL_S = 0.05       # polling interval while waiting


class InstallError(RuntimeError):
    """Raised when a GT install (validate->copy->register-alias) is refused."""


class _RegistryLockTimeout(TimeoutError):
    """Raised when the alias-registry lock cannot be acquired within the timeout."""


# Allow-list: canonical_id is interpolated into a filesystem path and an
# aliases-registry key, so path separators/".." must never reach either.
_CANONICAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _check_canonical_id_format(canonical_id: str) -> None:
    if not isinstance(canonical_id, str) or not _CANONICAL_ID_RE.fullmatch(canonical_id):
        raise InstallError(
            f"Refusing to bless: canonical_id {canonical_id!r} does not match "
            f"required format {_CANONICAL_ID_RE.pattern!r}"
        )


def _reviewed_by_missing(messages: list[str]) -> bool:
    return any("reviewed_by" in m for m in messages)


def _load_aliases_registry(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": "1", "description": "Canonical track-id registry.",
                "tracks": {}}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_aliases_registry(path: Path, registry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # No sort_keys -- preserve the registry's existing (non-alphabetical,
    # chronological) key order; json.dump keeps insertion order by default,
    # so pre-existing entries never move and new ones land at the end.
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


class _RegistryFileLock:
    """Minimal advisory cross-process lock, ``O_CREAT | O_EXCL`` atomicity.

    Sibling ``<target>.lock`` file. Works on Windows/macOS/Linux with no
    third-party package (same idiom as ``parquet_manager._FileLock``).
    Spins with a short poll interval up to ``timeout`` seconds; released in
    ``__exit__`` even when the ``with`` block raises.
    """

    def __init__(self, target: Path, timeout: float = _LOCK_TIMEOUT_S) -> None:
        self._lock_path = target.parent / (target.name + ".lock")
        self._timeout = timeout
        self._fd: Optional[int] = None

    def __enter__(self) -> "_RegistryFileLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                # O_EXCL guarantees atomicity: exactly one process succeeds.
                self._fd = os.open(
                    self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                try:
                    os.write(self._fd, str(os.getpid()).encode())
                except OSError:
                    pass  # best-effort diagnostics only
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise _RegistryLockTimeout(
                        f"Could not acquire alias-registry lock {self._lock_path} "
                        f"within {self._timeout}s. If this is a stale lock (e.g. a "
                        f"crashed process), delete it manually."
                    ) from None
                time.sleep(_LOCK_POLL_S)

    def __exit__(self, *_exc: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass  # already removed (e.g. by an external process)


def install_gt_geojson(
    geojson_path: Path,
    canonical_id: str,
    *,
    aliases: list[str] | None = None,
    force: bool = False,
    gt_dir: Path,
    aliases_file: Path,
) -> Path:
    """Validate + admit ``geojson_path`` into a gt corpus as ``canonical_id``.

    Returns the destination path on success. Raises :class:`InstallError` on
    any refusal -- this function never calls ``sys.exit``; CLI/web callers
    decide how to surface that.

    Refusals (mirrors the original ``scripts/bless_gt.py`` CLI behavior
    verbatim -- this IS that logic, moved here):
      - missing/empty ``reviewed_by`` -- ABSOLUTE, ``force`` cannot override.
      - any other validator message, unless ``force``.
      - ``canonical_id`` already registered in ``aliases_file``, unless
        ``force`` (in which case the existing entry is merged into, not
        replaced -- its other keys such as country/notes are preserved).

    M3: the alias-registry read -> mutate -> save (plus the duplicate-id
    check and the geojson copy, which both depend on/feed that same state)
    is one critical section guarded by :class:`_RegistryFileLock` on
    ``aliases_file`` -- see the module docstring for why.
    """
    geojson_path = Path(geojson_path)
    gt_dir = Path(gt_dir)
    aliases_file = Path(aliases_file)
    aliases = list(aliases or [])

    _check_canonical_id_format(canonical_id)

    messages = validate_gt_geojson(geojson_path)
    if _reviewed_by_missing(messages):
        raise InstallError(
            "Refusing to bless " + str(geojson_path) + ": reviewed_by is missing "
            "(absolute -- force does not override this). Validator messages:\n  "
            + "\n  ".join(messages)
        )
    if messages and not force:
        raise InstallError(
            "Refusing to bless " + str(geojson_path) + ": validator reported issues "
            "(force=True bypasses this). Validator messages:\n  "
            + "\n  ".join(messages)
        )

    gt_dir.mkdir(parents=True, exist_ok=True)
    dest = gt_dir / f"gt_{canonical_id}.geojson"

    with _RegistryFileLock(aliases_file):
        registry = _load_aliases_registry(aliases_file)
        tracks = registry.setdefault("tracks", {})
        if canonical_id in tracks and not force:
            raise InstallError(
                f"Refusing to bless: canonical_id '{canonical_id}' already exists in "
                f"{aliases_file} (force=True bypasses this)"
            )

        shutil.copy2(geojson_path, dest)

        existing = tracks.get(canonical_id)
        entry = existing if isinstance(existing, dict) else {}
        entry_aliases = list(entry.get("aliases", []))
        for a in (canonical_id, *aliases):  # id self-alias always included, first
            if a not in entry_aliases:
                entry_aliases.append(a)
        entry["canonical_id"] = canonical_id
        entry["aliases"] = entry_aliases
        tracks[canonical_id] = entry

        _save_aliases_registry(aliases_file, registry)

    return dest
