from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from track_surface.gt_validate import validate_gt_geojson


def _gt(tmp_path: Path, *, drop_role=None, reviewed=True, open_gap_m=0.0,
        n=60) -> Path:
    lat0, lon0 = 47.388, 0.789
    mx, my = 111_320 * np.cos(np.radians(lat0)), 110_540
    def ring(r):
        th = np.linspace(0, 2 * np.pi, n, endpoint=False)
        pts = [[lon0 + r * np.cos(t) / mx, lat0 + r * np.sin(t) / my] for t in th]
        if open_gap_m == 0.0:
            pts.append(pts[0])
        else:  # displace the closing point by open_gap_m
            pts.append([pts[0][0] + open_gap_m / mx, pts[0][1]])
        return pts
    feats = []
    for role, r in (("left_boundary_gt", 60.0), ("right_boundary_gt", 52.0)):
        if role == drop_role:
            continue
        feats.append({"type": "Feature", "properties": {"role": role},
                      "geometry": {"type": "LineString", "coordinates": ring(r)}})
    props = {"schema": "trackreco_ground_truth_v1", "track_name": "t"}
    if reviewed:
        props["reviewed_by"] = "theo"
    p = tmp_path / "gt_t.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "properties": props,
                             "features": feats}), encoding="utf-8")
    return p


def test_valid_file_passes(tmp_path):
    assert validate_gt_geojson(_gt(tmp_path)) == []

def test_missing_role_fails(tmp_path):
    msgs = validate_gt_geojson(_gt(tmp_path, drop_role="right_boundary_gt"))
    assert any("right_boundary_gt" in m for m in msgs)

def test_unreviewed_fails(tmp_path):
    msgs = validate_gt_geojson(_gt(tmp_path, reviewed=False))
    assert any("reviewed_by" in m for m in msgs)

def test_wide_open_boundary_fails(tmp_path):
    msgs = validate_gt_geojson(_gt(tmp_path, open_gap_m=80.0))
    assert any("closure" in m.lower() for m in msgs)


# ---------------------------------------------------------------------------
# scripts/bless_gt.py — focused behavior tests.
#
# scripts/ lives at the repo root (sibling of telemetry_tool/), so it needs
# the repo root on sys.path explicitly — same pattern already used by
# telemetry_tool/tests/test_parity_comparisons.py for `from scripts.parity_harness
# import ...`. This test file is one directory deeper (test_track_surface/),
# hence parents[3] instead of that file's parent.parent.parent.
# ---------------------------------------------------------------------------
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from scripts.bless_gt import BlessError, bless_gt, main


def _seed_aliases_file(tmp_path: Path) -> Path:
    """A tmp track_aliases.json seeded with the real file's shape/style
    (schema_version + description + a couple of pre-existing tracks), so
    bless tests never touch the real registry."""
    p = tmp_path / "track_aliases.json"
    p.write_text(json.dumps({
        "schema_version": "1",
        "description": "Canonical track-id registry.",
        "tracks": {
            "kct": {
                "canonical_id": "kct",
                "aliases": ["kct", "karting-club-du-touraine"],
                "country": "FR",
            },
        },
    }, indent=2), encoding="utf-8")
    return p


def test_bless_refuses_unreviewed_even_with_force(tmp_path):
    src = _gt(tmp_path, reviewed=False)
    gt_dir = tmp_path / "gt_out"
    aliases_file = _seed_aliases_file(tmp_path)

    with pytest.raises(BlessError, match="reviewed_by"):
        bless_gt(src, "zz", force=True, gt_dir=gt_dir, aliases_file=aliases_file)

    # Absolute refusal: nothing written, even with --force.
    assert not (gt_dir / "gt_zz.geojson").exists()
    assert json.loads(aliases_file.read_text(encoding="utf-8"))["tracks"].keys() == {"kct"}


def test_bless_refuses_invalid_without_force(tmp_path):
    src = _gt(tmp_path, drop_role="right_boundary_gt")  # reviewed, but missing a role
    gt_dir = tmp_path / "gt_out"
    aliases_file = _seed_aliases_file(tmp_path)

    with pytest.raises(BlessError, match="right_boundary_gt"):
        bless_gt(src, "zz", force=False, gt_dir=gt_dir, aliases_file=aliases_file)

    assert not (gt_dir / "gt_zz.geojson").exists()
    assert "zz" not in json.loads(aliases_file.read_text(encoding="utf-8"))["tracks"]


def test_bless_success_writes_gt_and_registers_alias(tmp_path):
    src = _gt(tmp_path)  # valid + reviewed
    gt_dir = tmp_path / "gt_out"
    aliases_file = _seed_aliases_file(tmp_path)

    dest = bless_gt(src, "zz", aliases=["zed"], gt_dir=gt_dir, aliases_file=aliases_file)

    assert dest == gt_dir / "gt_zz.geojson"
    assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")

    registry = json.loads(aliases_file.read_text(encoding="utf-8"))
    assert registry["tracks"]["kct"]["aliases"] == ["kct", "karting-club-du-touraine"]  # untouched
    zz = registry["tracks"]["zz"]
    assert zz["canonical_id"] == "zz"
    assert zz["aliases"] == ["zz", "zed"]  # id self-alias always present, first


def test_bless_refuses_duplicate_canonical_id_without_force(tmp_path):
    src = _gt(tmp_path)
    gt_dir = tmp_path / "gt_out"
    aliases_file = _seed_aliases_file(tmp_path)

    with pytest.raises(BlessError, match="kct"):
        bless_gt(src, "kct", force=False, gt_dir=gt_dir, aliases_file=aliases_file)
    assert not (gt_dir / "gt_kct.geojson").exists()

    # With --force it proceeds and merges into the existing entry.
    dest = bless_gt(src, "kct", force=True, gt_dir=gt_dir, aliases_file=aliases_file)
    assert dest.exists()
    registry = json.loads(aliases_file.read_text(encoding="utf-8"))
    assert registry["tracks"]["kct"]["aliases"] == ["kct", "karting-club-du-touraine"]
    assert registry["tracks"]["kct"]["country"] == "FR"  # pre-existing key preserved


def test_bless_cli_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Crossing boundaries validator test
# ---------------------------------------------------------------------------

def test_crossing_boundaries_fail(tmp_path):
    """Test that left/right boundaries intersecting fails validation.

    Creates a GT file where the left and right boundary polylines deliberately
    cross by swapping half of the coordinates between them.
    """
    lat0, lon0 = 47.388, 0.789
    mx, my = 111_320 * np.cos(np.radians(lat0)), 110_540
    n = 60

    def ring(r):
        th = np.linspace(0, 2 * np.pi, n, endpoint=False)
        pts = [[lon0 + r * np.cos(t) / mx, lat0 + r * np.sin(t) / my] for t in th]
        pts.append(pts[0])  # close the ring
        return pts

    left_ring = ring(60.0)
    right_ring = ring(52.0)

    # Swap the middle half of coordinates between left and right to make them cross
    swap_start = n // 4
    swap_end = n // 2
    for i in range(swap_start, swap_end):
        left_ring[i], right_ring[i] = right_ring[i], left_ring[i]

    feats = [
        {"type": "Feature", "properties": {"role": "left_boundary_gt"},
         "geometry": {"type": "LineString", "coordinates": left_ring}},
        {"type": "Feature", "properties": {"role": "right_boundary_gt"},
         "geometry": {"type": "LineString", "coordinates": right_ring}},
    ]
    props = {"schema": "trackreco_ground_truth_v1", "track_name": "t",
             "reviewed_by": "theo"}
    p = tmp_path / "gt_crossing.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "properties": props,
                             "features": feats}), encoding="utf-8")

    msgs = validate_gt_geojson(p)
    assert any("intersect" in m.lower() for m in msgs), \
        f"Expected 'intersect' in validation messages, got: {msgs}"
