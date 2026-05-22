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


@lru_cache(maxsize=1)
def load_all_canonical_polygons() -> list[tuple[str, "object", tuple[float, float, float, float]]]:
    """Day-15 Stage B: load every gt_*.geojson in the corpus, combine
    left_boundary_gt + reversed(right_boundary_gt) into a closed
    Shapely Polygon, repair self-intersection at the seam via buffer(0)
    when needed.

    Returns ``[(canonical_id, Polygon, bbox), ...]``. Bbox is
    ``(minx, miny, maxx, maxy)`` matching Shapely's ``Polygon.bounds``.

    Cached at module level (lru_cache size 1) — gt files don't change at
    runtime; the build cost (Shapely Polygon construction + buffer(0)
    repair for ~6 of 8 tracks) is paid once per worker process.
    """
    from shapely.geometry import Polygon
    from shapely import make_valid

    results: list[tuple[str, "object", tuple[float, float, float, float]]] = []
    if not _GT_DIR.exists():
        logger.warning("gt corpus dir does not exist: %s — matcher will fall through", _GT_DIR)
        return results

    for gt_path in sorted(_GT_DIR.glob("gt_*.geojson")):
        try:
            with open(gt_path, encoding="utf-8") as fh:
                gt = json.load(fh)
        except Exception as exc:
            logger.warning("failed to load %s: %s — skipping", gt_path.name, exc)
            continue
        canon = (gt.get("properties", {}) or {}).get("track_name")
        if not canon:
            continue
        features = {
            f.get("properties", {}).get("role"): f.get("geometry", {}).get("coordinates")
            for f in gt.get("features", []) or []
        }
        left = features.get("left_boundary_gt")
        right = features.get("right_boundary_gt")
        if not left or not right:
            logger.warning("gt %s missing left/right_boundary_gt — skipping", gt_path.name)
            continue
        ring = list(left) + list(reversed(right))
        if ring[0] != ring[-1]:
            ring = ring + [ring[0]]
        try:
            poly = Polygon(ring)
        except Exception as exc:
            logger.warning("Polygon construction failed for %s: %s", gt_path.name, exc)
            continue
        if not poly.is_valid:
            fixed = poly.buffer(0)
            if not (fixed.is_valid and not fixed.is_empty):
                fixed = make_valid(poly)
            if not (fixed.is_valid and not fixed.is_empty):
                logger.warning("gt %s polygon invalid + unrepairable", gt_path.name)
                continue
            poly = fixed
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        results.append((str(canon).strip().lower(), poly, poly.bounds))
    return results


def match_session_to_canonical(
    lats: list[float] | None,
    lons: list[float] | None,
    *,
    sample_n_min: int = 500,
    threshold_abs: float = 0.30,
    threshold_gap: float = 0.30,
) -> dict:
    """Day-15 Stage B: match a session's GPS to a canonical_id by
    point-in-polygon against the hand-traced gt corpus.

    Algorithm (Phase 1 dry-run validated, 2026-05-21):
      1. Build session bbox from lats/lons.
      2. Adaptive sampling: max(sample_n_min, len(points)//50) target.
      3. For each gt polygon: bbox-prefilter (O(1) reject), then
         point-in-polygon on sampled points → confidence = in_poly / n.
      4. Pick best canonical_id; require confidence >= threshold_abs
         AND (best - runner_up) >= threshold_gap to declare a match.

    Returns dict with keys:
      canonical_id, confidence, in_bbox_frac, runner_up,
      runner_up_confidence, status ("matched" | "pending"), reason.

    Pure read-only; safe to call from anywhere.
    """
    if not lats or not lons or len(lats) < 10:
        return {
            "canonical_id": None, "confidence": 0.0, "in_bbox_frac": 0.0,
            "runner_up": None, "runner_up_confidence": 0.0,
            "status": "pending", "reason": "no_gps_data",
        }

    from shapely.geometry import Point

    polys = load_all_canonical_polygons()
    if not polys:
        return {
            "canonical_id": None, "confidence": 0.0, "in_bbox_frac": 0.0,
            "runner_up": None, "runner_up_confidence": 0.0,
            "status": "pending", "reason": "gt_corpus_empty",
        }

    s_min_lon, s_max_lon = min(lons), max(lons)
    s_min_lat, s_max_lat = min(lats), max(lats)
    target = max(sample_n_min, len(lats) // 50)
    step = max(1, len(lats) // target)
    sampled = [(lons[i], lats[i]) for i in range(0, len(lats), step)]
    n = len(sampled)

    scores: list[tuple[str, float, float]] = []  # (canon, in_poly_frac, in_bbox_frac)
    for canon, poly, (minx, miny, maxx, maxy) in polys:
        if s_max_lon < minx or s_min_lon > maxx or s_max_lat < miny or s_min_lat > maxy:
            scores.append((canon, 0.0, 0.0))
            continue
        in_bbox = sum(1 for lon, lat in sampled if minx <= lon <= maxx and miny <= lat <= maxy)
        in_poly = sum(1 for p in sampled if poly.contains(Point(p)))
        scores.append((canon, in_poly / n, in_bbox / n))

    scores.sort(key=lambda x: -x[1])
    best = scores[0]
    runner = scores[1] if len(scores) > 1 else ("", 0.0, 0.0)

    if best[1] >= threshold_abs and (best[1] - runner[1]) >= threshold_gap:
        return {
            "canonical_id": best[0], "confidence": round(best[1], 4),
            "in_bbox_frac": round(best[2], 4),
            "runner_up": runner[0] or None,
            "runner_up_confidence": round(runner[1], 4),
            "status": "matched", "reason": None,
        }
    return {
        "canonical_id": None, "confidence": round(best[1], 4),
        "in_bbox_frac": round(best[2], 4),
        "runner_up": (best[0] or None) if best[1] > 0 else None,
        "runner_up_confidence": round(runner[1], 4),
        "status": "pending",
        "reason": "low_polygon_coverage" if best[1] < threshold_abs else "ambiguous_match",
    }


def resolve_canonical_via_pg(track_id: str | None) -> str | None:
    """Bridge PG `tracks.track_id` → `tracks.canonical_id` for sessions
    keyed by UUID rather than a registry alias.

    Day-15 Phase 2 Stage B: the pipeline passes the PG `track_id` (UUID
    or sentinel) down to the surface build, but `resolve_track_id`
    only matches strings present in `track_aliases.json`. This helper
    closes that gap by doing a single read-only lookup against the
    `tracks.canonical_id` column (added in migration 060).

    Connection sourcing: uses its OWN raw psycopg2 connection with
    `autocommit=True` so this query cannot poison and cannot be poisoned
    by any surrounding transaction state (the surface-build context has
    a history of txn-abort cascades — this lookup must stay isolated).

    Error handling:
      - track_id falsy → return None (no log).
      - Row found, `canonical_id` IS NULL → return None (no log; this
        is the expected case for placeholder tracks like the
        `unknown_track` sentinel and pipeline-auto-registered UUIDs).
      - Row not found → return None (no log; unknown track is expected).
      - Connection / query exception → log WARNING and return None
        (never silently swallow). The surface build falls back to the
        data_derived envelope, which is the safe default.
    """
    if not track_id:
        return None
    raw = None
    try:
        # Lazy import — web.db_pg is in a sibling package; keeping it out of
        # module-load avoids any circular-dep risk in the track_surface tree.
        from web.db_pg import _new_connection
        # _new_connection() returns a fresh psycopg2 conn (RealDictCursor).
        # We force autocommit ON for this single SELECT so we never share
        # txn state with anything upstream/downstream.
        raw = _new_connection()
        raw.autocommit = True
        with raw.cursor() as cur:
            cur.execute(
                "SELECT canonical_id FROM tracks WHERE track_id = %(t)s",
                {"t": track_id},
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning(
            "canonical_id bridge query failed for track_id=%r: %s",
            track_id, exc,
        )
        return None
    finally:
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass
    if row is None:
        return None
    val = row.get("canonical_id") if hasattr(row, "get") else row[0]
    if val is None or not str(val).strip():
        return None
    return str(val).strip().lower()


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
