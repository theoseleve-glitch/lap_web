"""Tests for telemetry_tool.track_surface.gt_loader.

Covers:
    - resolve_track_id: canonical, aliases, case-insensitive, unknown
    - load_gt: returns GroundTruth for kct, None gracefully for missing files,
      raises only on structurally-invalid gt
    - GroundTruth is a frozen dataclass
    - Alias-to-filename resolution handles the gt_slk-fp1 variant

These tests intentionally land BEFORE the implementation (test-first
discipline per Day 5 brief). The first commit will show pytest failing
on missing module; the second commit will show all green.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Wire both V2 root + telemetry_tool/ onto sys.path so that:
#   - `from telemetry_tool.track_surface.gt_loader import ...` resolves
#   - the package's own bare `from track_surface.X import Y` imports resolve
#     (see telemetry_tool/track_surface/__init__.py lines 11-25 — bare-import
#     quirk flagged by Day 4 audit).
_V2_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _V2_ROOT / "telemetry_tool"
for _p in (_V2_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ── resolve_track_id ─────────────────────────────────────────────────────


def test_resolve_track_id_canonical():
    from telemetry_tool.track_surface.gt_loader import resolve_track_id

    assert resolve_track_id("kct") == "kct"
    assert resolve_track_id("ok") == "ok"
    assert resolve_track_id("jv") == "jv"
    assert resolve_track_id("auxois-sud") == "auxois-sud"


def test_resolve_track_id_alias():
    from telemetry_tool.track_surface.gt_loader import resolve_track_id

    # Ouest Karting aliases all resolve to "ok"
    assert resolve_track_id("ouest-karting") == "ok"
    assert resolve_track_id("ouest_karting") == "ok"
    assert resolve_track_id("circuit-essay") == "ok"
    assert resolve_track_id("circuit_essay") == "ok"
    assert resolve_track_id("essay") == "ok"

    # SLK variants
    assert resolve_track_id("slk-fp1") == "slk"
    assert resolve_track_id("slk_fp1") == "slk"

    # Auxois variants
    assert resolve_track_id("auxois_sud") == "auxois-sud"
    assert resolve_track_id("auxois") == "auxois-sud"


def test_resolve_track_id_case_insensitive():
    from telemetry_tool.track_surface.gt_loader import resolve_track_id

    assert resolve_track_id("KCT") == "kct"
    assert resolve_track_id("Ouest-Karting") == "ok"
    assert resolve_track_id("OUEST-KARTING") == "ok"
    assert resolve_track_id("SLK-FP1") == "slk"
    assert resolve_track_id("Essay") == "ok"


def test_resolve_track_id_whitespace_handling():
    from telemetry_tool.track_surface.gt_loader import resolve_track_id

    assert resolve_track_id("  kct  ") == "kct"
    assert resolve_track_id("  ouest-karting") == "ok"


def test_resolve_track_id_unknown():
    from telemetry_tool.track_surface.gt_loader import resolve_track_id

    assert resolve_track_id("nonexistent") is None
    assert resolve_track_id("") is None
    assert resolve_track_id("   ") is None


# ── load_gt — happy path ──────────────────────────────────────────────────


def test_load_gt_kct_returns_groundtruth():
    from telemetry_tool.track_surface.gt_loader import GroundTruth, load_gt

    gt = load_gt("kct")
    assert gt is not None
    assert isinstance(gt, GroundTruth)
    assert gt.canonical_track_id == "kct"
    assert gt.source_filename == "gt_kct.geojson"
    assert gt.schema_version == "trackreco_ground_truth_v1"


def test_load_gt_kct_left_polyline_60_points():
    """KCT gt has 60 left points per audit Section 1.4."""
    from telemetry_tool.track_surface.gt_loader import load_gt

    gt = load_gt("kct")
    assert gt is not None
    assert len(gt.left_polyline) == 60

    # Each point is (lon, lat); KCT is in France ~ 0.78°E, 47.39°N
    for lon, lat in gt.left_polyline:
        assert 0.7 < lon < 0.8, f"lon out of KCT range: {lon}"
        assert 47.3 < lat < 47.4, f"lat out of KCT range: {lat}"


def test_load_gt_kct_right_polyline_93_points():
    """KCT gt has 93 right points per audit Section 1.4."""
    from telemetry_tool.track_surface.gt_loader import load_gt

    gt = load_gt("kct")
    assert gt is not None
    assert len(gt.right_polyline) == 93


def test_load_gt_resolves_slk_alias_to_fp1_filename():
    """gt_slk-fp1.geojson is the actual filename; 'slk' must resolve to it."""
    from telemetry_tool.track_surface.gt_loader import load_gt

    gt = load_gt("slk")
    assert gt is not None
    assert gt.canonical_track_id == "slk"
    # Source filename contains the alias variant
    assert "slk" in gt.source_filename.lower()


def test_groundtruth_is_frozen():
    """GroundTruth dataclass is immutable."""
    from telemetry_tool.track_surface.gt_loader import load_gt

    gt = load_gt("kct")
    assert gt is not None
    with pytest.raises((AttributeError, TypeError, Exception)):
        gt.canonical_track_id = "other"  # type: ignore[misc]


# ── load_gt — fallback semantics ─────────────────────────────────────────


def test_load_gt_missing_file_returns_none(tmp_path, monkeypatch):
    """Known track in registry but no gt file on disk → None gracefully.

    Updated Day 8: 'ok' now has gt_circuit-d-essay.geojson on disk, so the
    original assertion (load_gt('ok') is None) no longer holds. To still
    exercise the "registered but no file" branch, we point _GT_DIR at an
    empty tmp_path and probe a registry track — every probe miss must
    return None without raising.
    """
    import telemetry_tool.track_surface.gt_loader as gl

    monkeypatch.setattr(gl, "_GT_DIR", tmp_path)
    gl._load_registry.cache_clear()
    gl._build_alias_index.cache_clear()

    assert gl.load_gt("ok") is None
    assert gl.load_gt("ouest-karting") is None
    assert gl.load_gt("kct") is None  # would normally succeed; empty dir → None


def test_load_gt_unknown_track_returns_none():
    """Unknown track input → None, no exception."""
    from telemetry_tool.track_surface.gt_loader import load_gt

    assert load_gt("nonexistent") is None
    assert load_gt("") is None


# ── _parse_gt_geojson — schema validation ────────────────────────────────


def test_parse_gt_geojson_rejects_non_feature_collection(tmp_path: Path):
    from telemetry_tool.track_surface.gt_loader import GTLoaderError, _parse_gt_geojson

    bad = tmp_path / "gt_bad.geojson"
    bad.write_text('{"type": "Point", "coordinates": [0, 0]}', encoding="utf-8")
    with pytest.raises(GTLoaderError):
        _parse_gt_geojson(bad)


def test_parse_gt_geojson_rejects_missing_left(tmp_path: Path):
    from telemetry_tool.track_surface.gt_loader import GTLoaderError, _parse_gt_geojson

    incomplete = tmp_path / "gt_incomplete.geojson"
    incomplete.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "properties": {
                    "schema": "trackreco_ground_truth_v1",
                    "track_name": "test",
                },
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"role": "right_boundary_gt"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0.0, 0.0], [1.0, 1.0]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(GTLoaderError):
        _parse_gt_geojson(incomplete)


def test_parse_gt_geojson_rejects_missing_right(tmp_path: Path):
    from telemetry_tool.track_surface.gt_loader import GTLoaderError, _parse_gt_geojson

    incomplete = tmp_path / "gt_incomplete2.geojson"
    incomplete.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "properties": {
                    "schema": "trackreco_ground_truth_v1",
                    "track_name": "test",
                },
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"role": "left_boundary_gt"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0.0, 0.0], [1.0, 1.0]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(GTLoaderError):
        _parse_gt_geojson(incomplete)


def test_parse_gt_geojson_accepts_valid_minimum(tmp_path: Path):
    """Smallest valid file: 2-point left + 2-point right LineStrings."""
    from telemetry_tool.track_surface.gt_loader import _parse_gt_geojson

    valid = tmp_path / "gt_min.geojson"
    valid.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "properties": {
                    "schema": "trackreco_ground_truth_v1",
                    "track_name": "min_test",
                    "annotated_at": "2026-05-12T00:00:00Z",
                },
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"role": "left_boundary_gt"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0.0, 0.0], [1.0, 1.0]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"role": "right_boundary_gt"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[2.0, 2.0], [3.0, 3.0]],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    left, right, annotated_at, schema_version = _parse_gt_geojson(valid)
    assert left == [(0.0, 0.0), (1.0, 1.0)]
    assert right == [(2.0, 2.0), (3.0, 3.0)]
    assert annotated_at == "2026-05-12T00:00:00Z"
    assert schema_version == "trackreco_ground_truth_v1"


# ── Day-8 additions: gt_ok / circuit-d-essay alias resolution ──


def test_resolve_track_id_circuit_d_essay_alias():
    """Day-8: filename slug 'circuit-d-essay' resolves to canonical 'ok'."""
    from telemetry_tool.track_surface.gt_loader import _build_alias_index, resolve_track_id

    _build_alias_index.cache_clear()
    assert resolve_track_id("circuit-d-essay") == "ok"


def test_resolve_track_id_kart_essay_alias():
    """Day-8: internal track_id 'kart_essay' resolves to canonical 'ok'."""
    from telemetry_tool.track_surface.gt_loader import _build_alias_index, resolve_track_id

    _build_alias_index.cache_clear()
    assert resolve_track_id("kart_essay") == "ok"


def test_load_gt_ok_via_circuit_d_essay_filename():
    """Day-8: load_gt('ok') finds gt_circuit-d-essay.geojson via alias probe."""
    from telemetry_tool.track_surface.gt_loader import _build_alias_index, _load_registry, load_gt

    _build_alias_index.cache_clear()
    _load_registry.cache_clear()
    gt = load_gt("ok")
    assert gt is not None, "load_gt('ok') should now resolve gt_circuit-d-essay.geojson"
    assert gt.canonical_track_id == "ok"
    assert gt.source_filename == "gt_circuit-d-essay.geojson"
    assert len(gt.left_polyline) == 163
    assert len(gt.right_polyline) == 160
