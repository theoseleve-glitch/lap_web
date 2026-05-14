"""gt_loader.py — Hand-traced ground-truth polyline loader.

Loads ``gt_*.geojson`` files (schema ``trackreco_ground_truth_v1``) from
``Analysis/trackreco-main/data/ground_truth/`` and resolves any input name
to a canonical track id via the alias registry at
``telemetry_tool/track_surface/track_aliases.json``.

Public API
~~~~~~~~~~

``resolve_track_id(input_name)``
    Resolve any alias (case-insensitive, whitespace-tolerant) to canonical_id.
    Returns ``None`` for unknown inputs.

``load_gt(track_input)``
    Return a frozen :class:`GroundTruth` with left + right polylines in
    WGS84 ``(lon, lat)``. Returns ``None`` when the track is unknown OR when
    no ``gt_*.geojson`` exists for any of its aliases on disk. Raises
    :class:`GTLoaderError` only on structurally-invalid gt files (e.g.,
    not a FeatureCollection, missing a boundary feature).

The alias-aware lookup means slk-fp1 → slk → tries gt_slk.geojson then
gt_slk-fp1.geojson — finds the variant filename automatically. Same for
ouest-karting → ok → tries gt_ok.geojson (currently absent, returns None).

Design constraints
~~~~~~~~~~~~~~~~~~

- Pure read; no side effects on disk
- Polyline order preserved (do NOT resort or reproject in this module —
  Frenet projection is the consumer's responsibility in boundary.py)
- WGS84 (lon, lat) preserved per GeoJSON spec
- Registry + alias index cached for the process lifetime via ``lru_cache``
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]  # Analysis/V2_claude_ai/ OR lap_web/
_ALIAS_REGISTRY_PATH = _REPO_ROOT / "telemetry_tool" / "track_surface" / "track_aliases.json"


def _resolve_gt_dir() -> Path:
    """Pick the first gt directory that exists.

    Layouts supported:
      1. ``$LAP_GT_DIR`` (explicit override; absolute path).
      2. ``<repo_root>/data/ground_truth/`` — self-contained
         (lap_web carries its own copy under ``lap_web/data/``).
      3. ``<repo_root>/../trackreco-main/data/ground_truth/`` — sibling
         layout that V2 uses (``Analysis/V2_claude_ai/`` next to
         ``Analysis/trackreco-main/``).

    Falls back to layout 3 if none match (callers see ``load_gt`` return
    None for any track).
    """
    env = os.environ.get("LAP_GT_DIR")
    if env:
        return Path(env)
    candidates = [
        _REPO_ROOT / "data" / "ground_truth",
        _REPO_ROOT.parent / "trackreco-main" / "data" / "ground_truth",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


_GT_DIR = _resolve_gt_dir()

_SCHEMA_VERSION_EXPECTED = "trackreco_ground_truth_v1"


class GTLoaderError(ValueError):
    """Raised when a gt file is structurally invalid."""


@dataclass(frozen=True)
class GroundTruth:
    """Hand-traced ground truth for a single track.

    Attributes
    ----------
    canonical_track_id : str
        The registry's canonical id (e.g., "kct", "slk", "ok").
    source_filename : str
        Basename of the gt file actually loaded (e.g., "gt_slk-fp1.geojson").
    left_polyline : list[tuple[float, float]]
        WGS84 (lon, lat) per GeoJSON spec, in order of annotation.
    right_polyline : list[tuple[float, float]]
        WGS84 (lon, lat).
    annotated_at : str
        ISO-8601 timestamp from the file's properties (empty string if absent).
    schema_version : str
        Schema string from the file's properties (e.g., "trackreco_ground_truth_v1").
    """

    canonical_track_id: str
    source_filename: str
    left_polyline: list[tuple[float, float]]
    right_polyline: list[tuple[float, float]]
    annotated_at: str
    schema_version: str


# ---------------------------------------------------------------------------
# Registry + alias index
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, dict]:
    """Return the ``tracks`` block from track_aliases.json."""
    with open(_ALIAS_REGISTRY_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    tracks = data.get("tracks", {})
    if not isinstance(tracks, dict):
        raise GTLoaderError(
            f"{_ALIAS_REGISTRY_PATH.name}: 'tracks' is not a dict"
        )
    return tracks


@lru_cache(maxsize=1)
def _build_alias_index() -> dict[str, str]:
    """Return ``{lowercased_alias: canonical_id}``.

    Raises :class:`GTLoaderError` if an alias collision is detected
    (same lowercased alias mapping to two different canonical_ids).
    """
    registry = _load_registry()
    index: dict[str, str] = {}
    for canonical_id, entry in registry.items():
        target = entry.get("canonical_id", canonical_id)
        for alias in entry.get("aliases", []) or []:
            key = str(alias).strip().lower()
            if not key:
                continue
            existing = index.get(key)
            if existing is not None and existing != target:
                raise GTLoaderError(
                    f"Alias collision: '{key}' resolves to both "
                    f"'{existing}' and '{target}'"
                )
            index[key] = target
    return index


def resolve_track_id(input_name: str | None) -> str | None:
    """Resolve any alias to canonical_id.

    Case-insensitive, whitespace-tolerant. Returns ``None`` for unknown
    inputs (empty string, whitespace-only, not in the registry).
    """
    if not input_name or not str(input_name).strip():
        return None
    key = str(input_name).strip().lower()
    return _build_alias_index().get(key)


# ---------------------------------------------------------------------------
# gt file parsing
# ---------------------------------------------------------------------------


def _parse_gt_geojson(
    path: Path,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], str, str]:
    """Parse a gt_*.geojson and return its boundary polylines + metadata.

    Returns
    -------
    (left_polyline, right_polyline, annotated_at, schema_version)
        Each polyline is a list of (lon, lat) WGS84 points.

    Raises
    ------
    GTLoaderError
        - top-level JSON is not an object
        - ``type`` is not ``"FeatureCollection"``
        - missing ``left_boundary_gt`` feature with LineString geometry
        - missing ``right_boundary_gt`` feature with LineString geometry
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise GTLoaderError(f"{path.name}: top-level JSON is not an object")
    if data.get("type") != "FeatureCollection":
        raise GTLoaderError(
            f"{path.name}: type is '{data.get('type')}', expected 'FeatureCollection'"
        )

    props = data.get("properties") or {}
    schema_version = str(props.get("schema", ""))
    annotated_at = str(props.get("annotated_at", ""))

    left: list[tuple[float, float]] | None = None
    right: list[tuple[float, float]] | None = None

    for feat in data.get("features") or []:
        if not isinstance(feat, dict):
            continue
        role = (feat.get("properties") or {}).get("role", "")
        geom = feat.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        polyline = [(float(c[0]), float(c[1])) for c in coords]
        if role == "left_boundary_gt":
            left = polyline
        elif role == "right_boundary_gt":
            right = polyline

    if left is None:
        raise GTLoaderError(
            f"{path.name}: missing left_boundary_gt LineString feature"
        )
    if right is None:
        raise GTLoaderError(
            f"{path.name}: missing right_boundary_gt LineString feature"
        )

    return left, right, annotated_at, schema_version


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_gt(track_input: str | None) -> GroundTruth | None:
    """Load gt for a track identified by any alias.

    Resolves ``track_input`` to canonical_id, then probes the on-disk gt
    directory for ``gt_<alias>.geojson`` for each alias of that canonical_id.
    Returns the first hit as a :class:`GroundTruth`.

    Returns ``None`` when:
      - the input doesn't resolve to a canonical_id (unknown track)
      - no gt file exists on disk for any alias of the resolved track

    Raises :class:`GTLoaderError` only on structurally-invalid gt files.
    """
    canonical_id = resolve_track_id(track_input)
    if canonical_id is None:
        logger.debug("Unknown track input: %r", track_input)
        return None

    registry = _load_registry()
    entry = registry.get(canonical_id, {}) or {}
    # Always probe canonical_id first; then any additional aliases.
    aliases: list[str] = [canonical_id]
    for alias in entry.get("aliases", []) or []:
        if alias not in aliases:
            aliases.append(str(alias))

    for alias in aliases:
        candidate = _GT_DIR / f"gt_{alias}.geojson"
        if not candidate.exists():
            continue
        left, right, annotated_at, schema_version = _parse_gt_geojson(candidate)
        logger.info(
            "Loaded gt for canonical_id=%s from %s (left=%d pts, right=%d pts, "
            "schema=%s, annotated=%s)",
            canonical_id, candidate.name, len(left), len(right),
            schema_version, annotated_at,
        )
        return GroundTruth(
            canonical_track_id=canonical_id,
            source_filename=candidate.name,
            left_polyline=left,
            right_polyline=right,
            annotated_at=annotated_at,
            schema_version=schema_version,
        )

    logger.info(
        "No gt file found for canonical_id=%r (searched %d aliases at %s)",
        canonical_id, len(aliases), _GT_DIR,
    )
    return None
