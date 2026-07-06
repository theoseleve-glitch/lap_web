"""test_gt_runtime_dir.py — Phase-0 Task 2 (F2).

The gt corpus baked into the Docker image is read once via ``lru_cache``d
loaders in ``gt_loader.py``; a gt written at runtime (onboarding bless flow)
is invisible until redeploy+restart unless the loader (a) also consults a
runtime-writable directory (``GT_RUNTIME_DIR`` env var) and (b) exposes a
cache-invalidation hook so a freshly-written gt becomes visible without a
process restart.

The on-disk shape mirrored here (gt_<id>.geojson + track_aliases.json
``{"tracks": {id: {"canonical_id": id, "aliases": [...]}}}``) matches what
``scripts/bless_gt.py::bless_gt`` writes into the real corpus.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from track_surface import gt_loader


def _sample_gt_geojson(canonical_id: str) -> str:
    """A minimal, structurally-valid gt_*.geojson: closed left/right rings.

    Shape follows tests/test_track_surface/test_gt_validate.py's `_gt`
    helper (schema + reviewed_by + closed left_boundary_gt/right_boundary_gt
    LineStrings) so it parses cleanly through `_parse_gt_geojson` and the
    medial-axis / cross-section midline fallbacks in `_load_gt_canonical`.
    """
    lat0, lon0 = 47.388, 0.789
    mx, my = 111_320 * np.cos(np.radians(lat0)), 110_540

    def ring(r: float) -> list[list[float]]:
        th = np.linspace(0, 2 * np.pi, 60, endpoint=False)
        pts = [[lon0 + r * np.cos(t) / mx, lat0 + r * np.sin(t) / my] for t in th]
        pts.append(pts[0])
        return pts

    feats = [
        {"type": "Feature", "properties": {"role": role},
         "geometry": {"type": "LineString", "coordinates": ring(r)}}
        for role, r in (("left_boundary_gt", 60.0), ("right_boundary_gt", 52.0))
    ]
    props = {
        "schema": "trackreco_ground_truth_v1",
        "track_name": canonical_id,
        "reviewed_by": "theo",
    }
    return json.dumps({"type": "FeatureCollection", "properties": props, "features": feats})


def _write_alias(runtime_dir: Path, canonical_id: str) -> None:
    """Mirror bless_gt's alias registration shape in a runtime-dir
    track_aliases.json — same basename as the baked registry, so gt_loader
    can find + merge it via GT_RUNTIME_DIR."""
    registry = {
        "schema_version": "1",
        "description": "runtime-dir test registry",
        "tracks": {
            canonical_id: {"canonical_id": canonical_id, "aliases": [canonical_id]},
        },
    }
    (runtime_dir / "track_aliases.json").write_text(json.dumps(registry), encoding="utf-8")


def test_runtime_dir_gt_found_after_invalidate(tmp_path, monkeypatch):
    monkeypatch.setenv("GT_RUNTIME_DIR", str(tmp_path))
    gt_loader.invalidate_gt_cache()  # start each test from a clean cache

    cid = "unit_track"
    assert gt_loader.resolve_track_id(cid) is None  # not registered anywhere yet
    assert gt_loader.load_gt(cid) is None            # cache the miss

    (tmp_path / f"gt_{cid}.geojson").write_text(_sample_gt_geojson(cid), encoding="utf-8")
    _write_alias(tmp_path, cid)

    assert gt_loader.load_gt(cid) is None            # still cached miss (stale alias index)

    gt_loader.invalidate_gt_cache(cid)

    found = gt_loader.load_gt(cid)
    assert found is not None
    assert found.canonical_track_id == cid
    assert found.source_filename == f"gt_{cid}.geojson"

    # Cleanup: leave the module cache clean for any test that runs after this
    # one in the same process (GT_RUNTIME_DIR reverts via monkeypatch teardown,
    # but the lru_cache entries for "unit_track" would otherwise leak).
    gt_loader.invalidate_gt_cache()


def test_gt_runtime_dir_unset_behaves_as_before(monkeypatch):
    """No GT_RUNTIME_DIR set => baked-dir-only behavior, unchanged."""
    monkeypatch.delenv("GT_RUNTIME_DIR", raising=False)
    gt_loader.invalidate_gt_cache()
    assert gt_loader.load_gt("unit_track_never_blessed") is None
    gt_loader.invalidate_gt_cache()


def test_cross_process_staleness_fixed_by_entry_hook(tmp_path, monkeypatch):
    """Final-review finding I1: a bless in one process must not leave a
    stale ``None`` miss cached in ANOTHER process (e.g. a Celery pipeline
    worker) that never called ``invalidate_gt_cache`` itself.

    Simulates the cross-process scenario in a single process: prime the
    cache with the miss the ORIGINAL trigger run would have cached, then
    write the freshly-blessed GT the way ``bless_service.install_gt_geojson``
    does (gt_<id>.geojson + track_aliases.json in GT_RUNTIME_DIR) WITHOUT
    calling ``invalidate_gt_cache`` directly (that call lives only in the web
    process's ``bless_geometry``). Instead, invoke
    ``track_surface.gt_loader.refresh_runtime_gt_if_configured`` -- the
    helper ``track_surface.builder.build_track_surface`` now calls at its
    own entry, before ``load_gt`` -- and assert the GT is found instead of
    the stale cached miss.
    """
    monkeypatch.setenv("GT_RUNTIME_DIR", str(tmp_path))
    gt_loader.invalidate_gt_cache()  # start each test from a clean cache

    cid = "unit_track_xproc"
    assert gt_loader.resolve_track_id(cid) is None
    assert gt_loader.load_gt(cid) is None  # caches the miss (== the trigger's own lookup)

    # A DIFFERENT process just blessed this track: GT + alias appear on disk,
    # but nothing in THIS process's caches has been told about it yet.
    (tmp_path / f"gt_{cid}.geojson").write_text(_sample_gt_geojson(cid), encoding="utf-8")
    _write_alias(tmp_path, cid)

    assert gt_loader.load_gt(cid) is None  # still the stale cached miss

    # This is the entry-of-build guard, not a direct invalidate_gt_cache call.
    gt_loader.refresh_runtime_gt_if_configured()

    found = gt_loader.load_gt(cid)
    assert found is not None
    assert found.canonical_track_id == cid
    assert found.source_filename == f"gt_{cid}.geojson"

    gt_loader.invalidate_gt_cache()


def test_refresh_runtime_gt_is_noop_when_unset(monkeypatch):
    """No GT_RUNTIME_DIR => refresh_runtime_gt_if_configured must not touch
    the cache (verified indirectly: a cached miss for a track that is later
    "discoverable" only via a runtime dir stays cached, since there's no
    runtime dir to notice)."""
    monkeypatch.delenv("GT_RUNTIME_DIR", raising=False)
    gt_loader.invalidate_gt_cache()
    assert gt_loader.load_gt("unit_track_no_runtime_dir") is None
    gt_loader.refresh_runtime_gt_if_configured()  # should not raise or reset anything
    assert gt_loader.load_gt("unit_track_no_runtime_dir") is None
    gt_loader.invalidate_gt_cache()
