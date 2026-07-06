"""onboarding/draft.py
--------------------
Auto-draft module for the Track Onboarding Loop (Phase 1, Task 7).

When ``record_missing_geometry`` (Task 6) enqueues a request, the Celery
task (``tasks.onboarding_tasks.draft_and_notify``, Task 10) tries a SAM2
satellite draft first (:func:`sam2_draft`) and falls back INLINE to a
GPS-only draft (:func:`gps_only_draft`) when SAM2 is unavailable or fails.

Both draft kinds are meant to end up as a ``trackreco_ground_truth_v1``
geojson file that a human corrects in the annotator and then blesses
(``onboarding/bless_service.py``, Task 8) -- but only :func:`gps_only_draft`
is REQUIRED to pass ``track_surface.gt_validate.validate_gt_geojson`` on its
own, unreviewed output (see the module-level note on ``reviewed_by`` below).
:func:`sam2_draft`'s raw output (straight from the trackreco pipeline's
``write_satellite_gt``) intentionally does NOT set ``reviewed_by`` -- it is
even less "reviewed" than the GPS fallback and must go through the
annotator like any other draft.

``gps_only_draft`` has NO heavy dependency beyond numpy (already a hard
dependency of ``telemetry_tool``), so it always works even when the SAM2 /
trackreco-main environment (torch, imagery fetch, ...) is absent.
``sam2_draft`` shells out to a SIBLING repo (``Analysis/trackreco-main``,
not vendored into ``lap_web``) and is best-effort: any failure anywhere --
missing checkout, missing heavy deps in the child process, timeout,
non-zero exit, unreadable output -- simply yields ``None``, never raises.

Honesty-layer note on ``reviewed_by``: ``gt_validate.validate_gt_geojson``
treats a non-empty ``properties.reviewed_by`` as its one "a human actually
looked at this" gate. ``gps_only_draft`` is machine-generated and NOT
human-reviewed, yet Task 7's acceptance test requires its raw output to
pass the validator outright (so it round-trips through the same
schema/closure/crossing checks the annotator export does). We satisfy that
literally but stamp a clearly-synthetic sentinel
(``reviewed_by="auto_draft:gps_only"``) rather than a real name, and mark
``properties.review_source="gps_only_draft"`` so it is unambiguous, byte-
for-byte, that no human reviewed this file. It is ``bless_service``'s job
(Task 8, per the plan's global constraint) to refuse a bless whose
submitted geometry does not *differ* from the stored auto-draft -- i.e. to
make sure a human actually edited it -- rather than rely on ``reviewed_by``
alone to gate blessing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import numpy as np

# Reused rather than reimplemented -- the same proper-intersection helpers
# gt_validate.py (and geometry_gates.py itself) use for boundary crossing /
# self-intersection checks. Both are numpy-only (no heavy dependency).
from track_surface.geometry_gates import _has_self_intersection, _segments_intersect
from track_surface.gt_validate import MAX_CLOSURE_GAP_M, MIN_BOUNDARY_POINTS

logger = logging.getLogger(__name__)

__all__ = [
    "DraftError",
    "DEFAULT_HALF_WIDTH_M",
    "MAX_BBOX_SPAN_DEG",
    "validate_bbox",
    "gps_only_draft",
    "sam2_draft",
    "save_draft",
    "load_draft",
]

DEFAULT_HALF_WIDTH_M = 4.0
MAX_BBOX_SPAN_DEG = 0.2

_SCHEMA = "trackreco_ground_truth_v1"
_LEFT_ROLE = "left_boundary_gt"
_RIGHT_ROLE = "right_boundary_gt"
_GPS_ONLY_REVIEWED_BY = "auto_draft:gps_only"
_GPS_ONLY_REVIEW_SOURCE = "gps_only_draft"

# Local equirectangular metre conversion at the centerline centroid --
# same convention lap_track_to_draft.py's thinning step uses.
_M_PER_DEG_LAT = 110_540.0
_M_PER_DEG_LON = 111_320.0

# Comfortably clears gt_validate.MIN_BOUNDARY_POINTS (20) even after the
# closing-point duplicate is added.
_RING_RESAMPLE_MIN = MIN_BOUNDARY_POINTS + 5

_SAM2_TIMEOUT_S = 900
_SAM2_SCRIPT_RELPATH = ("scripts", "lap_track_to_draft.py")

# request_id is server-derived (a uuid, per repo.py's gen_random_uuid()) --
# this is intentionally stricter than "no path separators": no dots either,
# so accidental "../.." style values are rejected outright rather than
# pattern-matched away.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class DraftError(Exception):
    """Raised for an invalid bbox/centerline/request_id, or an unsafe draft."""


# ── bbox validation ──────────────────────────────────────────────────────

def validate_bbox(bbox: dict) -> None:
    """Validate a ``{min_lat, max_lat, min_lon, max_lon}`` bbox dict.

    Raises :class:`DraftError` if any value is missing/non-numeric/non-finite,
    a latitude is outside [-90, 90], a longitude is outside [-180, 180], a
    min bound is >= its max bound, or either span exceeds
    ``MAX_BBOX_SPAN_DEG`` -- this is a sanity guard against passing a
    whole-country bbox to imagery fetch/segmentation, not a precise limit.
    """
    if not isinstance(bbox, dict):
        raise DraftError(f"bbox must be a dict, got {type(bbox).__name__}")

    required = ("min_lat", "max_lat", "min_lon", "max_lon")
    missing = [k for k in required if k not in bbox]
    if missing:
        raise DraftError(f"bbox missing required key(s): {missing}")

    values: dict[str, float] = {}
    for key in required:
        raw = bbox[key]
        try:
            values[key] = float(raw)
        except (TypeError, ValueError):
            raise DraftError(f"bbox[{key!r}]={raw!r} is not numeric")
        if not np.isfinite(values[key]):
            raise DraftError(f"bbox[{key!r}]={raw!r} is not finite")

    min_lat, max_lat = values["min_lat"], values["max_lat"]
    min_lon, max_lon = values["min_lon"], values["max_lon"]

    for name, lat in (("min_lat", min_lat), ("max_lat", max_lat)):
        if not (-90.0 <= lat <= 90.0):
            raise DraftError(f"bbox[{name!r}]={lat} outside [-90, 90]")
    for name, lon in (("min_lon", min_lon), ("max_lon", max_lon)):
        if not (-180.0 <= lon <= 180.0):
            raise DraftError(f"bbox[{name!r}]={lon} outside [-180, 180]")

    if min_lat >= max_lat:
        raise DraftError(f"bbox degenerate: min_lat ({min_lat}) >= max_lat ({max_lat})")
    if min_lon >= max_lon:
        raise DraftError(f"bbox degenerate: min_lon ({min_lon}) >= max_lon ({max_lon})")

    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon
    if lat_span > MAX_BBOX_SPAN_DEG:
        raise DraftError(f"bbox lat span {lat_span} > MAX_BBOX_SPAN_DEG ({MAX_BBOX_SPAN_DEG})")
    if lon_span > MAX_BBOX_SPAN_DEG:
        raise DraftError(f"bbox lon span {lon_span} > MAX_BBOX_SPAN_DEG ({MAX_BBOX_SPAN_DEG})")


# ── local projection (equirectangular, centroid reference) ─────────────

def _lonlat_to_local(lonlat: np.ndarray, lat0: float, lon0: float) -> tuple[np.ndarray, float, float]:
    mx = np.cos(np.radians(lat0)) * _M_PER_DEG_LON
    my = _M_PER_DEG_LAT
    x = (lonlat[:, 0] - lon0) * mx
    y = (lonlat[:, 1] - lat0) * my
    return np.column_stack([x, y]), mx, my


def _local_to_lonlat(xy: np.ndarray, lat0: float, lon0: float, mx: float, my: float) -> np.ndarray:
    lon = lon0 + xy[:, 0] / mx
    lat = lat0 + xy[:, 1] / my
    return np.column_stack([lon, lat])


def _resample_closed_ring(xy: np.ndarray, n_target: int) -> np.ndarray:
    """Evenly resample a closed ring (no duplicated closing vertex) to ``n_target`` points."""
    ring = np.vstack([xy, xy[0:1]])
    seg = np.diff(ring, axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = float(cum[-1])
    if total <= 0.0:
        raise DraftError("centerline has zero perimeter; cannot offset into boundaries")

    targets = np.linspace(0.0, total, n_target, endpoint=False)
    out = np.empty((n_target, 2), dtype=float)
    for k, t in enumerate(targets):
        idx = int(np.searchsorted(cum, t, side="right") - 1)
        idx = min(max(idx, 0), len(seg_len) - 1)
        span = seg_len[idx]
        frac = 0.0 if span <= 0.0 else float(t - cum[idx]) / span
        out[k] = ring[idx] + frac * (ring[idx + 1] - ring[idx])
    return out


def _ring_normals(xy: np.ndarray) -> np.ndarray:
    """Unit left-normal at each vertex of a closed ring, via wraparound central difference."""
    nxt = np.roll(xy, -1, axis=0)
    prv = np.roll(xy, 1, axis=0)
    tangent = nxt - prv
    norm = np.hypot(tangent[:, 0], tangent[:, 1])
    norm[norm <= 0.0] = 1.0
    tangent = tangent / norm[:, None]
    return np.column_stack([-tangent[:, 1], tangent[:, 0]])


def _dedupe_consecutive(xy: np.ndarray, tol_m: float = 0.05) -> np.ndarray:
    if len(xy) == 0:
        return xy
    keep = [0]
    for i in range(1, len(xy)):
        if np.hypot(*(xy[i] - xy[keep[-1]])) > tol_m:
            keep.append(i)
    return xy[keep]


# ── GPS-only fallback draft (no heavy dependency) ───────────────────────

def gps_only_draft(centerline_lonlat, half_width_m: float = DEFAULT_HALF_WIDTH_M) -> dict:
    """Offset a driven centerline into left/right boundary loops.

    ``centerline_lonlat`` is a ``list[[lon, lat]]`` polyline (a driven lap,
    roughly closed). Returns a ``trackreco_ground_truth_v1`` FeatureCollection
    dict that satisfies every structural gate in
    ``track_surface.gt_validate.validate_gt_geojson`` -- schema, both
    boundary roles present with >= ``MIN_BOUNDARY_POINTS`` points, closure
    gap ~0 (loops are closed by construction), non-crossing boundaries, and
    a non-empty ``reviewed_by`` (see the module docstring's honesty-layer
    note on why that sentinel is set here).

    Raises :class:`DraftError` if the centerline is degenerate (fewer than
    3 usable points, zero perimeter) or if offsetting at ``half_width_m``
    would make either boundary self-intersect or cross the other boundary
    (e.g. a hairpin tighter than the requested half-width) -- we refuse to
    emit invalid/self-crossing geometry rather than silently ship it.
    """
    if half_width_m <= 0:
        raise DraftError(f"half_width_m must be > 0, got {half_width_m}")

    raw = np.asarray(centerline_lonlat, dtype=float)
    if raw.ndim != 2 or raw.shape[1] < 2 or len(raw) < 3:
        raise DraftError("centerline_lonlat must have >= 3 [lon, lat] points")
    if not np.all(np.isfinite(raw)):
        raise DraftError("centerline_lonlat contains non-finite coordinates")

    lon0 = float(np.mean(raw[:, 0]))
    lat0 = float(np.mean(raw[:, 1]))
    local, mx, my = _lonlat_to_local(raw, lat0, lon0)

    ring = _dedupe_consecutive(local)
    # If the input is literally closed (first == last within a couple of
    # metres, typical of a start/finish-line lap trace), drop the duplicate
    # so ring vertices are unique -- wraparound tangents supply the closure.
    if len(ring) >= 2 and np.hypot(*(ring[-1] - ring[0])) < 2.0:
        ring = ring[:-1]
    if len(ring) < 3:
        raise DraftError("centerline_lonlat has too few distinct points to offset")

    n_target = max(len(ring), _RING_RESAMPLE_MIN)
    ring = _resample_closed_ring(ring, n_target)

    normals = _ring_normals(ring)
    left_xy = ring + normals * half_width_m
    right_xy = ring - normals * half_width_m

    # Close each loop by repeating the first vertex -- guarantees a closure
    # gap of exactly 0, well under gt_validate.MAX_CLOSURE_GAP_M.
    left_closed = np.vstack([left_xy, left_xy[0:1]])
    right_closed = np.vstack([right_xy, right_xy[0:1]])
    assert float(np.hypot(*(left_closed[-1] - left_closed[0]))) <= MAX_CLOSURE_GAP_M
    assert float(np.hypot(*(right_closed[-1] - right_closed[0]))) <= MAX_CLOSURE_GAP_M

    if _has_self_intersection(left_closed, closed=True):
        raise DraftError(
            "gps_only_draft: left boundary self-intersects at this half_width_m "
            "(track likely has a corner tighter than half_width_m); try a smaller half_width_m"
        )
    if _has_self_intersection(right_closed, closed=True):
        raise DraftError(
            "gps_only_draft: right boundary self-intersects at this half_width_m "
            "(track likely has a corner tighter than half_width_m); try a smaller half_width_m"
        )
    if _polylines_cross(left_closed, right_closed):
        raise DraftError(
            "gps_only_draft: left/right boundaries cross each other at this half_width_m"
        )

    left_lonlat = _local_to_lonlat(left_closed, lat0, lon0, mx, my)
    right_lonlat = _local_to_lonlat(right_closed, lat0, lon0, mx, my)

    return {
        "type": "FeatureCollection",
        "properties": {
            "schema": _SCHEMA,
            "reviewed_by": _GPS_ONLY_REVIEWED_BY,
            "review_source": _GPS_ONLY_REVIEW_SOURCE,
            "half_width_m": float(half_width_m),
        },
        "features": [
            _boundary_feature(_LEFT_ROLE, left_lonlat),
            _boundary_feature(_RIGHT_ROLE, right_lonlat),
        ],
    }


def _boundary_feature(role: str, coords_lonlat: np.ndarray) -> dict:
    return {
        "type": "Feature",
        "properties": {"role": role, "point_count": int(len(coords_lonlat))},
        "geometry": {
            "type": "LineString",
            "coordinates": [[float(lon), float(lat)] for lon, lat in coords_lonlat],
        },
    }


def _polylines_cross(a: np.ndarray, b: np.ndarray) -> bool:
    """Brute-force proper-intersection check between two independent closed rings.

    Mirrors gt_validate._polylines_intersect (not imported: that name is
    private to gt_validate and not meant for reuse across modules); both
    boundaries here are at most a few hundred points so O(len(a)*len(b)) is
    cheap.
    """
    for i in range(len(a) - 1):
        for j in range(len(b) - 1):
            if _segments_intersect(a[i], a[i + 1], b[j], b[j + 1]):
                return True
    return False


# ── SAM2 satellite draft (best-effort, shells a sibling repo) ───────────

def _trackreco_script() -> Path | None:
    """Locate ``lap_track_to_draft.py``; ``None`` if that checkout isn't present.

    ``Analysis/trackreco-main`` is a SIBLING repo to ``lap_web`` (not a
    subpath reachable via a fixed relative walk from this file, which may
    be running from any of several ``lap_web`` worktrees) -- so the
    location is env-overridable via ``ONBOARDING_TRACKRECO_DIR``, falling
    back to this machine's known layout.
    """
    candidates = []
    override = os.environ.get("ONBOARDING_TRACKRECO_DIR")
    if override:
        candidates.append(Path(override))
    candidates.append(Path(r"C:\Users\Admin\Documents\Telemetry\Analysis\trackreco-main"))

    for base in candidates:
        script = base.joinpath(*_SAM2_SCRIPT_RELPATH)
        if script.is_file():
            return script
    return None


def sam2_draft(bbox: dict, session_gps) -> dict | None:
    """Best-effort SAM2 satellite draft. Returns the geojson dict, or ``None``.

    NEVER raises: an invalid bbox, an absent trackreco-main checkout, a
    session with too few GPS points, missing heavy deps (numpy/pandas/torch)
    inside the child process, a timeout, a non-zero exit, or an unreadable/
    malformed output file all simply produce ``None`` so the caller falls
    back to :func:`gps_only_draft`.

    Shells ``Analysis/trackreco-main/scripts/lap_track_to_draft.py --name
    <slug> --session-csv <tmp.csv> --zoom 19 --backend auto``, which itself
    invokes ``build_satellite_gt.py`` and writes
    ``data/satellite_gt/<slug>/gt_<slug>.geojson`` (verified by reading
    both scripts) -- that file is parsed and returned as-is.
    """
    try:
        validate_bbox(bbox)

        points = list(session_gps) if session_gps else []
        if len(points) < 10:
            logger.info("sam2_draft: skip (only %d session GPS points, need >= 10)", len(points))
            return None

        script = _trackreco_script()
        if script is None:
            logger.info("sam2_draft: skip (trackreco-main checkout not found)")
            return None
        repo_root = script.parents[1]

        with tempfile.TemporaryDirectory(prefix="onboarding_sam2_") as tmp:
            csv_path = Path(tmp) / "session.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as fh:
                fh.write("latitude,longitude\n")
                for lon, lat in points:
                    fh.write(f"{float(lat)},{float(lon)}\n")

            slug = "obdraft" + uuid.uuid4().hex[:16]
            cmd = [
                sys.executable, str(script),
                "--name", slug,
                "--session-csv", str(csv_path),
                "--zoom", "19",
                "--backend", "auto",
            ]
            result = subprocess.run(
                cmd, cwd=str(repo_root), capture_output=True,
                timeout=_SAM2_TIMEOUT_S, check=False,
            )
            if result.returncode != 0:
                logger.info(
                    "sam2_draft: lap_track_to_draft.py exited %d: %s",
                    result.returncode,
                    (result.stderr or b"").decode("utf-8", errors="replace")[-2000:],
                )
                return None

            out_path = repo_root / "data" / "satellite_gt" / slug / f"gt_{slug}.geojson"
            if not out_path.is_file():
                logger.info("sam2_draft: expected output missing at %s", out_path)
                return None
            return json.loads(out_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("sam2_draft: failed, falling back to gps_only_draft")
        return None


# ── draft persistence ────────────────────────────────────────────────────

def _sanitize_request_id(request_id: str) -> str:
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise DraftError(f"invalid request_id: {request_id!r}")
    return request_id


def _draft_dir() -> Path:
    override = os.environ.get("ONBOARDING_DRAFT_DIR")
    if override:
        return Path(override)
    gt_runtime = os.environ.get("GT_RUNTIME_DIR")
    if gt_runtime:
        return Path(gt_runtime).parent / "onboarding_drafts"
    return Path(tempfile.gettempdir()) / "lap_onboarding_drafts"


def save_draft(request_id: str, geojson: dict) -> str:
    """Write ``geojson`` under the draft dir, named only from ``request_id``.

    Returns the written path (str). Raises :class:`DraftError` for an
    invalid ``request_id`` -- never accepts a path from the caller.
    """
    safe_id = _sanitize_request_id(request_id)
    directory = _draft_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_id}.geojson"
    path.write_text(json.dumps(geojson), encoding="utf-8")
    return str(path)


def load_draft(request_id: str) -> dict:
    """Read back a draft saved by :func:`save_draft`.

    Raises :class:`DraftError` for an invalid ``request_id`` (including any
    containing a path separator or ``..``) or if no draft exists for it.
    """
    safe_id = _sanitize_request_id(request_id)
    path = _draft_dir() / f"{safe_id}.geojson"
    if not path.is_file():
        raise DraftError(f"no draft found for request_id={request_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))
