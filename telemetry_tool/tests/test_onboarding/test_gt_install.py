"""Tests for onboarding/gt_install.py (M3 final-review fix).

``install_gt_geojson`` (extracted here out of bless_service.py, which was at
its 500-line file-size budget) does a read-modify-write of the shared
``track_aliases.json`` registry: load -> mutate (add/merge one canonical_id
entry) -> save. Two concurrent blesses of DIFFERENT tracks (multiple
gunicorn workers) could previously interleave that read-modify-write and
silently drop one entry. This is now serialized with a cross-process file
lock (``_RegistryFileLock``, a sibling ``<aliases_file>.lock``).

True multi-process concurrency isn't simulated here (single-process test
run); instead: (1) two back-to-back installs of different tracks both
survive, and (2) the lock primitive itself is verified directly --
acquired, released, and blocking a second acquire until timeout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from onboarding import gt_install  # noqa: E402

_LAT0, _LON0 = 47.388, 0.789
_MX = 111_320 * np.cos(np.radians(_LAT0))
_MY = 110_540


def _ring(r: float, n: int = 60) -> list[list[float]]:
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pts = [[_LON0 + r * np.cos(t) / _MX, _LAT0 + r * np.sin(t) / _MY] for t in th]
    pts.append(pts[0])
    return pts


def _gt_geojson(track_name: str, reviewed_by: str = "theo") -> dict:
    return {
        "type": "FeatureCollection",
        "properties": {
            "schema": "trackreco_ground_truth_v1",
            "track_name": track_name,
            "reviewed_by": reviewed_by,
        },
        "features": [
            {"type": "Feature", "properties": {"role": "left_boundary_gt"},
             "geometry": {"type": "LineString", "coordinates": _ring(60.0)}},
            {"type": "Feature", "properties": {"role": "right_boundary_gt"},
             "geometry": {"type": "LineString", "coordinates": _ring(52.0)}},
        ],
    }


def _write(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class TestTwoSequentialInstallsDifferentTracksBothSurvive:
    def test_both_aliases_present_after_two_installs(self, tmp_path):
        gt_dir = tmp_path / "gt_out"
        aliases_file = tmp_path / "track_aliases.json"

        src_a = _write(tmp_path, "a.geojson", _gt_geojson("Track A"))
        src_b = _write(tmp_path, "b.geojson", _gt_geojson("Track B"))

        dest_a = gt_install.install_gt_geojson(
            src_a, "track_a", gt_dir=gt_dir, aliases_file=aliases_file,
        )
        dest_b = gt_install.install_gt_geojson(
            src_b, "track_b", gt_dir=gt_dir, aliases_file=aliases_file,
        )

        assert dest_a.exists()
        assert dest_b.exists()
        registry = json.loads(aliases_file.read_text(encoding="utf-8"))
        assert set(registry["tracks"].keys()) == {"track_a", "track_b"}
        assert registry["tracks"]["track_a"]["canonical_id"] == "track_a"
        assert registry["tracks"]["track_b"]["canonical_id"] == "track_b"

    def test_no_leftover_lock_file_and_second_install_still_succeeds(self, tmp_path):
        gt_dir = tmp_path / "gt_out"
        aliases_file = tmp_path / "track_aliases.json"
        lock_path = aliases_file.parent / (aliases_file.name + ".lock")
        src_a = _write(tmp_path, "a.geojson", _gt_geojson("Track A"))

        gt_install.install_gt_geojson(src_a, "track_a", gt_dir=gt_dir, aliases_file=aliases_file)
        assert not lock_path.exists()

        # A second install must still succeed -- the lock is reusable, not
        # left stuck from the first (a leaked lock would hang/timeout here).
        src_b = _write(tmp_path, "b.geojson", _gt_geojson("Track B"))
        dest_b = gt_install.install_gt_geojson(
            src_b, "track_b", gt_dir=gt_dir, aliases_file=aliases_file,
        )
        assert dest_b.exists()
        assert not lock_path.exists()
        registry = json.loads(aliases_file.read_text(encoding="utf-8"))
        assert set(registry["tracks"].keys()) == {"track_a", "track_b"}


class TestRegistryFileLockPrimitive:
    """Focused test of the lock primitive itself -- the critical section
    install_gt_geojson wraps its load -> mutate -> save in."""

    def test_lock_acquired_then_released(self, tmp_path):
        target = tmp_path / "track_aliases.json"
        lock_path = tmp_path / "track_aliases.json.lock"

        with gt_install._RegistryFileLock(target):
            assert lock_path.exists()
        assert not lock_path.exists()

    def test_held_lock_blocks_a_second_acquire_until_timeout(self, tmp_path):
        target = tmp_path / "track_aliases.json"
        lock_path = tmp_path / "track_aliases.json.lock"
        lock_path.write_text("held-by-another-process", encoding="utf-8")

        with pytest.raises(gt_install._RegistryLockTimeout):
            with gt_install._RegistryFileLock(target, timeout=0.2):
                pass  # pragma: no cover -- must never be entered

        lock_path.unlink()  # cleanup: this lock was never legitimately released
