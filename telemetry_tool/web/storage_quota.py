"""Per-workspace elastic storage quota.

Each workspace is allocated disk space to store its sessions. The allocation
starts at 2 GiB and AUTO-GROWS by 1 GiB every time consumption crosses 80% of
the current allocation — so the allocation is "regularly updated to match
consumption" (it tracks the user rather than hard-blocking them). Consumption
is measured from the ACTUAL on-disk footprint of the workspace's data dirs, so
it stays truthful across uploads, deletes, and retention cleanup.

Source of truth: ``workspaces.storage_used_bytes`` /
``workspaces.storage_allocation_bytes`` (migration 066). Recomputed from disk
on upload-finalize, on delete, and by a daily reconcile task.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

GIB = 1024 ** 3
BASE_ALLOCATION_BYTES = 2 * GIB     # every workspace starts with 2 GiB
GROWTH_STEP_BYTES = 1 * GIB         # add 1 GiB each time usage crosses the threshold
GROWTH_THRESHOLD = 0.80            # grow when used >= 80% of allocation


def _workspace_base_dirs() -> list[Path]:
    """Base dirs whose ``<workspace_id>/`` subtree holds a workspace's data."""
    raw = os.environ.get("TELEMETRY_RAW_DIR", "data/raw")
    cache = os.environ.get("TELEMETRY_CACHE_DIR", "data/cache")
    results = os.environ.get("TELEMETRY_RESULTS_DIR", "results")
    # De-dup (raw and upload dirs are often the same path).
    seen, out = set(), []
    for d in (raw, cache, results):
        p = Path(d).resolve()
        if p not in seen:
            seen.add(p)
            out.append(Path(d))
    return out


def _dir_bytes(path: Path) -> int:
    """Recursive sum of file sizes under *path* (0 if missing). Never raises."""
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def workspace_disk_bytes(workspace_id: int) -> int:
    """Actual bytes stored on disk for a workspace (raw + cache + results)."""
    ws = str(workspace_id)
    return sum(_dir_bytes(base / ws) for base in _workspace_base_dirs())


def delete_session_files(workspace_id: int, session_id: str) -> int:
    """Unlink a session's files across the workspace dirs; return bytes freed.

    Replaces the count-only ``retention_tasks._delete_session_files`` for paths
    that also need the byte total (so storage can be reconciled afterwards).
    """
    freed = 0
    ws = str(workspace_id)
    for base in _workspace_base_dirs():
        ws_dir = base / ws
        if not ws_dir.is_dir():
            continue
        for p in ws_dir.glob(f"*{session_id}*"):
            try:
                if p.is_file():
                    sz = p.stat().st_size
                    p.unlink()
                    freed += sz
            except OSError as exc:
                logger.warning("storage_quota: failed to delete %s: %s", p, exc)
    return freed


def purge_workspace_files(workspace_id: int) -> int:
    """Recursively delete ALL on-disk data for a workspace; return bytes freed.

    Used by the GDPR account-purge sweep: once the workspace's DB rows are
    gone, its ``<base>/<workspace_id>/`` subtree under every data dir
    (raw + cache + results) must be erased too, or the files outlive the
    account. Never raises — best-effort, logs what it can't remove.
    """
    import shutil

    freed = 0
    ws = str(workspace_id)
    for base in _workspace_base_dirs():
        ws_dir = base / ws
        if not ws_dir.is_dir():
            continue
        freed += _dir_bytes(ws_dir)
        try:
            shutil.rmtree(ws_dir, ignore_errors=False)
        except OSError as exc:
            logger.warning("storage_quota: failed to purge %s: %s", ws_dir, exc)
            # Fall back to per-file unlink so we erase as much as possible.
            for p in sorted(ws_dir.rglob("*"), reverse=True):
                try:
                    p.unlink() if p.is_file() else p.rmdir()
                except OSError:
                    pass
    return freed


def _grow_allocation(used: int, allocation: int) -> int:
    """Elastic rule: while used >= 80% of allocation, add 1 GiB. Monotonic."""
    if allocation < BASE_ALLOCATION_BYTES:
        allocation = BASE_ALLOCATION_BYTES
    # Loop so a large jump (e.g. a big import) expands in one pass.
    while used >= int(GROWTH_THRESHOLD * allocation):
        allocation += GROWTH_STEP_BYTES
    return allocation


def recompute_and_store(conn, workspace_id: int) -> dict:
    """Re-measure disk usage, grow the allocation if needed, persist both.

    Returns {used_bytes, allocation_bytes}. Safe to call on every upload/
    delete and from the reconcile task — it never shrinks the allocation.
    """
    used = workspace_disk_bytes(workspace_id)
    row = conn.execute(
        "SELECT storage_allocation_bytes FROM workspaces WHERE id = %(ws)s",
        {"ws": workspace_id},
    ).fetchone()
    if row is None:
        return {"used_bytes": used, "allocation_bytes": BASE_ALLOCATION_BYTES}
    current = (dict(row) if not isinstance(row, dict) else row).get(
        "storage_allocation_bytes"
    ) or BASE_ALLOCATION_BYTES
    allocation = _grow_allocation(used, int(current))
    conn.execute(
        "UPDATE workspaces SET storage_used_bytes = %(used)s, "
        "storage_allocation_bytes = %(alloc)s WHERE id = %(ws)s",
        {"used": used, "alloc": allocation, "ws": workspace_id},
    )
    return {"used_bytes": used, "allocation_bytes": allocation}


def get_storage(conn, workspace_id: int) -> dict:
    """Read the persisted figures for display (used/allocation/pct/remaining)."""
    row = conn.execute(
        "SELECT storage_used_bytes, storage_allocation_bytes "
        "FROM workspaces WHERE id = %(ws)s",
        {"ws": workspace_id},
    ).fetchone()
    if row is None:
        used, allocation = 0, BASE_ALLOCATION_BYTES
    else:
        r = dict(row) if not isinstance(row, dict) else row
        used = int(r.get("storage_used_bytes") or 0)
        allocation = int(r.get("storage_allocation_bytes") or BASE_ALLOCATION_BYTES)
    pct = round(used / allocation * 100, 1) if allocation else 0.0
    return {
        "used_bytes": used,
        "allocation_bytes": allocation,
        "used_mb": round(used / (1024 * 1024), 1),
        "allocation_mb": round(allocation / (1024 * 1024), 1),
        "pct": pct,
        "remaining_bytes": max(0, allocation - used),
    }
