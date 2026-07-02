"""gt_validate.py — Validator for hand-traced ground-truth geojson files.

Enforces the ``trackreco_ground_truth_v1`` contract before a gt file is
eligible to be "blessed" into the corpus (see ``scripts/bless_gt.py``):
schema tag correct, both boundary roles present with enough points,
coordinates sane (finite, world-range WGS84), each boundary a near-closed
loop, the two boundaries never crossing each other, and — the one honesty
gate — ``reviewed_by`` actually present (only a human-reviewed export may
ship to prod).

Pure function: reads the one file passed in, no other I/O or side effects.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# Reused rather than reimplemented — the same proper-intersection test the
# geometry gates use for centerline self-intersection (Task 1). Importing
# the underscore-prefixed name is intentional per the task brief; there is
# no public wrapper for it in geometry_gates.py.
from track_surface.geometry_gates import _segments_intersect

SCHEMA_EXPECTED = "trackreco_ground_truth_v1"
BOUNDARY_ROLES = ("left_boundary_gt", "right_boundary_gt")
MIN_BOUNDARY_POINTS = 20
MAX_CLOSURE_GAP_M = 25.0

_EARTH_RADIUS_M = 6_371_000.0
"""Same equirectangular convention as track_surface.gt_loader._EARTH_RADIUS_M."""


def _project_equirect(coords, lat_ref_rad: float, lon_ref_rad: float) -> np.ndarray:
    """WGS84 [lon, lat] pairs -> local XY metres (equirectangular)."""
    arr = np.asarray(coords, dtype=float)
    lon_r = np.radians(arr[:, 0])
    lat_r = np.radians(arr[:, 1])
    x = _EARTH_RADIUS_M * (lon_r - lon_ref_rad) * np.cos(lat_ref_rad)
    y = _EARTH_RADIUS_M * (lat_r - lat_ref_rad)
    return np.column_stack([x, y])


def _polylines_intersect(a: np.ndarray, b: np.ndarray) -> bool:
    """True if any segment of polyline ``a`` properly crosses any segment of ``b``.

    Brute-force O(len(a) * len(b)); hand-traced gt boundaries are at most a
    few hundred points so this is cheap, and it avoids repurposing
    geometry_gates._has_self_intersection's grid hash + closing-segment
    exemption logic, which is specific to a single polyline checked against
    itself rather than two independent boundaries.
    """
    for i in range(len(a) - 1):
        for j in range(len(b) - 1):
            if _segments_intersect(a[i], a[i + 1], b[j], b[j + 1]):
                return True
    return False


def validate_gt_geojson(path: Path) -> list[str]:
    """Validate a ``gt_*.geojson`` file against the ground-truth contract.

    Returns an empty list when the file is valid; otherwise a list of
    human-readable failure messages (a file can fail more than one gate at
    once — every applicable check runs and all messages are collected).
    """
    path = Path(path)

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: could not read file ({exc})"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{path.name}: not valid JSON ({exc})"]

    if not isinstance(data, dict):
        return [f"{path.name}: top-level JSON is not an object"]

    messages: list[str] = []

    props = data.get("properties")
    props = props if isinstance(props, dict) else {}

    schema = props.get("schema")
    if schema != SCHEMA_EXPECTED:
        messages.append(
            f"schema property is {schema!r}, expected {SCHEMA_EXPECTED!r}"
        )

    features = data.get("features")
    features = features if isinstance(features, list) else []

    boundary_coords: dict[str, list] = {}
    for feat in features:
        if not isinstance(feat, dict):
            continue
        role = (feat.get("properties") or {}).get("role")
        if role not in BOUNDARY_ROLES:
            continue
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        if isinstance(coords, list):
            boundary_coords[role] = coords

    # Only roles that are present, well-formed, finite and in world-range
    # feed the shared local projection used for closure + intersection —
    # keeps those checks from running on garbage coordinates.
    xy_by_role: dict[str, np.ndarray] = {}
    all_lon: list[float] = []
    all_lat: list[float] = []

    for role in BOUNDARY_ROLES:
        coords = boundary_coords.get(role)
        if coords is None:
            messages.append(f"missing required boundary feature with role '{role}'")
            continue
        if len(coords) < MIN_BOUNDARY_POINTS:
            messages.append(
                f"{role} has {len(coords)} points, need >= {MIN_BOUNDARY_POINTS}"
            )

        try:
            arr = np.asarray(coords, dtype=float)
        except (ValueError, TypeError):
            messages.append(
                f"{role}: coordinates are malformed (expected [lon, lat] pairs)"
            )
            continue
        if arr.ndim != 2 or arr.shape[1] < 2:
            messages.append(
                f"{role}: coordinates are malformed (expected [lon, lat] pairs)"
            )
            continue

        lon, lat = arr[:, 0], arr[:, 1]
        finite_ok = bool(np.all(np.isfinite(lon)) and np.all(np.isfinite(lat)))
        if not finite_ok:
            messages.append(f"{role}: contains non-finite coordinate values")

        in_range = finite_ok and not (
            np.any(lon < -180.0) or np.any(lon > 180.0)
            or np.any(lat < -90.0) or np.any(lat > 90.0)
        )
        if finite_ok and not in_range:
            messages.append(
                f"{role}: coordinates outside world range "
                "(lon must be in [-180, 180], lat in [-90, 90])"
            )

        if in_range and len(coords) >= 2:
            all_lon.extend(lon.tolist())
            all_lat.extend(lat.tolist())
            xy_by_role[role] = arr

    if xy_by_role:
        lat_ref_rad = float(np.radians((min(all_lat) + max(all_lat)) / 2.0))
        lon_ref_rad = float(np.radians((min(all_lon) + max(all_lon)) / 2.0))

        xy_local = {
            role: _project_equirect(arr, lat_ref_rad, lon_ref_rad)
            for role, arr in xy_by_role.items()
        }

        for role, xy in xy_local.items():
            gap_m = float(np.linalg.norm(xy[-1] - xy[0]))
            if gap_m > MAX_CLOSURE_GAP_M:
                messages.append(
                    f"{role}: closure gap {gap_m:.1f} m exceeds "
                    f"{MAX_CLOSURE_GAP_M:.0f} m maximum"
                )

        if len(xy_local) == len(BOUNDARY_ROLES):
            left = xy_local[BOUNDARY_ROLES[0]]
            right = xy_local[BOUNDARY_ROLES[1]]
            if _polylines_intersect(left, right):
                messages.append(
                    f"{BOUNDARY_ROLES[0]} and {BOUNDARY_ROLES[1]} "
                    "boundaries intersect each other"
                )

    reviewed_by = props.get("reviewed_by")
    if not reviewed_by or not str(reviewed_by).strip():
        messages.append(
            "reviewed_by is missing or empty — only reviewed files may be blessed"
        )

    return messages
