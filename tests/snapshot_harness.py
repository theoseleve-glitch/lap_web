"""Snapshot regression test harness.

Hybrid comparison: canonical hash for fast pass/fail,
semantic deep-compare with float tolerance for debugging diffs.

Usage:
    assert_snapshot_match(result_dict, "test_name")

Update snapshots:
    pytest --update-snapshots
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TT_ROOT = _PROJECT_ROOT / "telemetry_tool"
for p in (_PROJECT_ROOT, _TT_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from provenance.canonical import canonical_hash, canonicalize

_DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def _deep_compare(
    a: Any,
    b: Any,
    rtol: float = 1e-6,
    path: str = "",
) -> list[str]:
    """Recursively compare two objects, returning a list of diff descriptions."""
    diffs: list[str] = []

    if type(a) != type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            pass  # fall through to float comparison
        else:
            diffs.append(f"{path}: type mismatch {type(a).__name__} vs {type(b).__name__}")
            return diffs

    if isinstance(a, dict):
        all_keys = set(a.keys()) | set(b.keys())
        for k in sorted(all_keys):
            if k not in a:
                diffs.append(f"{path}.{k}: missing in actual")
            elif k not in b:
                diffs.append(f"{path}.{k}: missing in expected")
            else:
                diffs.extend(_deep_compare(a[k], b[k], rtol, f"{path}.{k}"))
        return diffs

    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            diffs.append(f"{path}: length {len(a)} vs {len(b)}")
            return diffs
        for i, (va, vb) in enumerate(zip(a, b)):
            diffs.extend(_deep_compare(va, vb, rtol, f"{path}[{i}]"))
        return diffs

    if isinstance(a, float) or isinstance(b, float):
        fa, fb = float(a), float(b)
        if math.isnan(fa) and math.isnan(fb):
            return diffs
        if math.isinf(fa) and math.isinf(fb) and (fa > 0) == (fb > 0):
            return diffs
        if not math.isclose(fa, fb, rel_tol=rtol, abs_tol=1e-12):
            diffs.append(f"{path}: {fa} vs {fb} (rtol={rtol})")
        return diffs

    if a != b:
        diffs.append(f"{path}: {a!r} vs {b!r}")

    return diffs


def assert_snapshot_match(
    result: dict,
    snapshot_name: str,
    *,
    snapshot_dir: Path | None = None,
    rtol: float = 1e-6,
    update: bool = False,
) -> None:
    """Assert result matches a stored snapshot.

    On first run (or when ``update=True``), the snapshot is created.
    On subsequent runs the canonical hash is compared first (fast path).
    If hashes differ, a semantic deep-compare produces human-readable diffs.

    Parameters
    ----------
    result:
        The dict to compare against the stored snapshot.
    snapshot_name:
        Unique name used as the file stem for .json and .hash files.
    snapshot_dir:
        Override the default snapshot directory.
    rtol:
        Relative tolerance for floating-point comparisons.
    update:
        When True, overwrite the stored snapshot with *result*.
    """
    sdir = Path(snapshot_dir) if snapshot_dir else _DEFAULT_SNAPSHOT_DIR
    sdir.mkdir(parents=True, exist_ok=True)

    json_path = sdir / f"{snapshot_name}.json"
    hash_path = sdir / f"{snapshot_name}.hash"

    current_canonical = canonicalize(result)
    current_hash = canonical_hash(result)

    # First run or update mode: create snapshot
    if not json_path.exists() or update:
        json_path.write_text(current_canonical, encoding="utf-8")
        hash_path.write_text(current_hash, encoding="utf-8")
        return

    # Fast path: compare hashes
    stored_hash = hash_path.read_text(encoding="utf-8").strip()
    if current_hash == stored_hash:
        return

    # Slow path: semantic comparison for diff output
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    current_normalised = json.loads(current_canonical)
    diffs = _deep_compare(current_normalised, stored, rtol=rtol)

    if not diffs:
        # Hashes differ but values within tolerance -- update hash
        hash_path.write_text(current_hash, encoding="utf-8")
        return

    diff_report = "\n".join(f"  {d}" for d in diffs[:20])
    extra = f"\n  ... and {len(diffs) - 20} more" if len(diffs) > 20 else ""
    raise AssertionError(
        f"Snapshot '{snapshot_name}' mismatch "
        f"(hash {current_hash[:12]}... vs {stored_hash[:12]}...):\n"
        f"{diff_report}{extra}\n\n"
        f"Run with --update-snapshots to accept the new baseline."
    )
