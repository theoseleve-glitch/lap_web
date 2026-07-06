"""onboarding/bless_service.py
------------------------------
Server-side "bless" for the Track Onboarding Loop (Phase 1, Task 8).

``bless_geometry`` is what the save endpoint (a later task) calls when an
operator POSTs a hand-corrected ``trackreco_ground_truth_v1`` geojson back
from the annotator. It is the SECURITY-CRITICAL boundary between an
untrusted HTTP body and the trusted ground-truth (GT) store: every gate a
human-blessed GT goes through here, fail-closed, with `force` hard-wired to
``False`` -- the web path can never bypass a gate the CLI (``scripts/
bless_gt.py``) would also have to pass with `--force`.

Flow (each step below returns ``BlessResult(ok=False, failures=[...])`` and
writes a REJECT audit row -- nothing is installed -- on any failure; an
unexpected exception anywhere is caught and treated the same way):

  1. Load the submitted geojson. If ``auto_draft_geojson`` is given and the
     submitted geometry (boundary coordinates only -- see
     ``_geometry_signature``) is unchanged from it, reject
     ``["unreviewed_draft"]``: the operator must actually edit the draft,
     not just re-submit it (``onboarding/draft.py``'s module docstring
     calls this out as bless_service's job -- ``reviewed_by`` alone is not
     a sufficient gate since ``gps_only_draft`` already sets a synthetic
     ``reviewed_by`` on its own machine-generated output).
  2. ``reviewed_by`` must be non-empty and must not start with
     ``"auto_draft:"`` -- defense-in-depth against a client replaying the
     draft's own sentinel reviewer as if it were a human name.
  3. Overwrite ``properties.reviewed_by`` on the submitted geojson with the
     SERVER-supplied ``reviewed_by`` -- a client-supplied value in the body
     is never trusted.
  4. ``track_surface.gt_validate.validate_gt_geojson`` on the corrected
     file -- the same hard schema/closure/crossing/reviewed_by gate a
     hand-traced gt file must pass to be CLI-blessed.
  5. Build a ``TrackSurface`` from the corrected boundaries alone (see
     ``_geojson_to_surface`` -- no GPS laps needed, reusing the exact
     midline/width construction ``track_surface.gt_loader`` already uses
     for the ``gt_anchored`` builder path) and run
     ``track_surface.geometry_gates.run_geometry_gates`` against it.
  6. Install: copy the corrected file into ``GT_RUNTIME_DIR`` and register
     the canonical_id/alias -- via ``install_gt_geojson``, the core
     extracted out of ``scripts/bless_gt.py`` so the CLI and this web path
     share one code path. ``force`` is always ``False`` here (Global
     Constraint) -- re-blessing an id that already has GT under this loop
     is refused; only a human operator running the CLI with ``--force``
     can do that.
  7. Write an ACCEPT audit row, then invalidate_gt_cache (logged not raised
     on failure). Return ``BlessResult(ok=True, failures=[])``.

``tracks.canonical_id`` is intentionally NOT set here -- that is
``onboarding/reprocess.py``'s job (a later task), not this one's.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from onboarding.gt_install import (
    InstallError,
    _check_canonical_id_format,
    install_gt_geojson,
)
from track_surface.frenet import FrenetFrame
from track_surface.geometry_gates import run_geometry_gates
from track_surface.gt_loader import (
    _compute_cross_section_midline_and_widths,
    _local_equirect,
    invalidate_gt_cache,
)
from track_surface.gt_validate import validate_gt_geojson
from track_surface.medial_axis import build_medial_axis_spine
from track_surface.model import TrackSurface

logger = logging.getLogger(__name__)

__all__ = [
    "BlessResult",
    "InstallError",
    "install_gt_geojson",
    "bless_geometry",
]

_AUDIT_TABLE_INSERT = (
    "INSERT INTO track_geometry_audit "
    "(track_id, vehicle_class, condition, gate, details) "
    "VALUES (%s,%s,%s,%s,%s::jsonb)"
)


@dataclass
class BlessResult:
    ok: bool
    failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared install core -- originally extracted from scripts/bless_gt.py
# (Task 8) so the CLI and the web bless path call the SAME
# validate -> copy -> register-alias code; moved again (final-review finding
# M3) into onboarding/gt_install.py, both to fix a non-atomic alias-registry
# read-modify-write race (see that module's docstring) and to keep this file
# under its 500-line budget. Imported back in above so nothing that already
# imports ``InstallError``/``install_gt_geojson`` from this module (e.g.
# ``scripts/bless_gt.py``) needs to change.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# geojson -> TrackSurface adapter (Task 8 new code)
# ---------------------------------------------------------------------------


def _geometry_signature(geojson: dict) -> str:
    """Canonical string of ONLY the boundary role+coordinates.

    Used to decide whether the operator actually changed anything relative
    to the stored auto-draft. Deliberately ignores ``properties`` (schema,
    reviewed_by, review_source, timestamps, ...) -- those always differ
    between the draft and the submission (the server itself overwrites
    ``reviewed_by``), so comparing full documents would make the
    unreviewed-draft gate never fire. Only a change to the actual boundary
    geometry counts as "reviewed".

    Keyed by role (``left_boundary_gt``/``right_boundary_gt``, each unique)
    rather than a list -- ``sort_keys=True`` only sorts dict keys, never
    list order, so a list-based signature would let byte-identical geometry
    evade this gate by resubmitting the two boundary features swapped. A
    role-keyed dict (role coerced to ``str`` so a missing/None role still
    serializes) is invariant to feature order and still changes whenever
    the coordinates actually change.
    """
    features = geojson.get("features") if isinstance(geojson, dict) else None
    sig: dict[str, object] = {}
    for feat in (features or []):
        if not isinstance(feat, dict):
            continue
        role = (feat.get("properties") or {}).get("role")
        coords = (feat.get("geometry") or {}).get("coordinates")
        sig[str(role)] = coords
    return json.dumps(sig, sort_keys=True)


def _geojson_to_surface(geojson: dict, *, track_id: str = "onboarding_candidate") -> TrackSurface:
    """Build a minimal ``TrackSurface`` from a GT geojson's boundaries alone.

    No GPS laps required: reuses the SAME midline/width construction
    ``track_surface.gt_loader._load_gt_canonical`` uses for the
    ``gt_anchored`` surface-builder path (``track_surface/builder.py``,
    ``surface_frame == "gt_anchored"``) -- the medial-axis spine
    (``track_surface.medial_axis.build_medial_axis_spine``), falling back
    to the cross-section pairing (``gt_loader._compute_cross_section_
    midline_and_widths``) exactly as ``_load_gt_canonical`` does. The local
    equirectangular projection reference is the GT boundaries' own bbox
    centroid (the same internal convention ``medial_axis``/cross-section
    already use) rather than a GPS session's mean lat/lon -- there is no
    GPS session at bless time, and arc length, closure error,
    self-intersection, and width bounds (the gates that matter here) are
    all invariant to that reference choice.

    Raises ``ValueError`` on any malformed/degenerate input (missing
    boundaries, too few points, collapsed projection, spine + fallback both
    failing) -- ``bless_geometry`` treats every exception from this
    function as a reject.
    """
    left: list[tuple[float, float]] | None = None
    right: list[tuple[float, float]] | None = None
    for feat in (geojson.get("features") or []):
        if not isinstance(feat, dict):
            continue
        role = (feat.get("properties") or {}).get("role")
        coords = (feat.get("geometry") or {}).get("coordinates")
        if not isinstance(coords, list):
            continue
        if role == "left_boundary_gt":
            left = [(float(c[0]), float(c[1])) for c in coords]
        elif role == "right_boundary_gt":
            right = [(float(c[0]), float(c[1])) for c in coords]

    if not left or not right:
        raise ValueError("geojson missing left_boundary_gt/right_boundary_gt LineString feature")
    if len(left) < 4 or len(right) < 4:
        raise ValueError("boundary polylines too short to build a surface (need >= 4 points)")

    left_arr = np.asarray(left, dtype=float)
    right_arr = np.asarray(right, dtype=float)
    all_lon = np.concatenate([left_arr[:, 0], right_arr[:, 0]])
    all_lat = np.concatenate([left_arr[:, 1], right_arr[:, 1]])
    lat_ref_rad = float(np.deg2rad((all_lat.min() + all_lat.max()) * 0.5))
    lon_ref_rad = float(np.deg2rad((all_lon.min() + all_lon.max()) * 0.5))

    midline_lonlat, diag = build_medial_axis_spine(left, right)
    if midline_lonlat is not None:
        width_arr = np.asarray(diag["half_width_per_station_m"], dtype=float)
        width_left_m = width_arr
        width_right_m = width_arr
    else:
        midline_lonlat, width_left_m, width_right_m, diag2 = (
            _compute_cross_section_midline_and_widths(left, right)
        )
        if midline_lonlat is None:
            raise ValueError(
                "midline construction failed via both medial-axis "
                f"({diag.get('fallback_reason')}) and cross-section pairing "
                f"({diag2.get('error')})"
            )

    cl_xy = _local_equirect(midline_lonlat, lat_ref_rad, lon_ref_rad)
    if len(cl_xy) < 3:
        raise ValueError("derived centerline collapsed to < 3 points")

    frenet = FrenetFrame.from_centerline(cl_xy)

    gt_n = len(width_left_m)
    gt_s_stations = np.linspace(0.0, frenet.total_length_m, gt_n)
    width_left = np.interp(frenet.s_grid, gt_s_stations, width_left_m)
    width_right = np.interp(frenet.s_grid, gt_s_stations, width_right_m)

    return TrackSurface(
        track_id=track_id,
        frenet=frenet,
        width_left=width_left,
        width_right=width_right,
        boundary_source="gt_anchored_native",
        n_laps=0,
        sim_sources=[],
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _write_audit(conn, canonical_id: str, gate: str, details: dict) -> None:
    """Insert one row into ``track_geometry_audit`` for this bless attempt.

    Reuses the migration-079 audit table and the same raw-cursor
    insert-then-commit pattern as ``pipeline/stages/s10d_surface.py``'s
    ``_record_geometry_rejection`` -- the only existing writer of this
    table. Never raises: an audit-write failure must not turn an
    otherwise-valid accept into a crash, nor mask a reject's real reason
    (both already computed by the caller before this is called).
    """
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                _AUDIT_TABLE_INSERT,
                (canonical_id, None, None, gate, json.dumps(details, default=str)),
            )
        finally:
            cur.close()
        conn.commit()
    except Exception:
        logger.exception(
            "bless_geometry: failed to write audit row (gate=%s, canonical_id=%s)",
            gate, canonical_id,
        )


def _reject(conn, canonical_id: str, gate: str, failures: list[str]) -> BlessResult:
    logger.info(
        "bless_geometry: reject canonical_id=%s gate=%s failures=%s",
        canonical_id, gate, failures,
    )
    _write_audit(conn, canonical_id, f"bless_reject:{gate}", {"failures": failures})
    return BlessResult(ok=False, failures=list(failures))


def _load_geojson(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON is not an object")
    return data


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def bless_geometry(
    *,
    geojson_path: Path,
    canonical_id: str,
    reviewed_by: str,
    auto_draft_geojson: dict | None = None,
    conn,
) -> BlessResult:
    """Bless an operator-corrected geojson into the runtime GT store.

    ``force`` is always ``False`` -- not exposed as a parameter at all, so
    the web path can never pass it. See the module docstring for the full
    gate order. Any unhandled exception is caught and converted into a
    reject (fail-closed); nothing is ever installed on a reject.
    """
    try:
        _check_canonical_id_format(canonical_id)
    except InstallError as exc:
        return _reject(conn, canonical_id, "invalid_canonical_id", [str(exc)])

    try:
        submitted = _load_geojson(geojson_path)
    except Exception as exc:
        return _reject(
            conn, canonical_id, "malformed_geojson",
            [f"could not read/parse submitted geojson: {exc}"],
        )

    try:
        if auto_draft_geojson is not None and (
            _geometry_signature(submitted) == _geometry_signature(auto_draft_geojson)
        ):
            return _reject(conn, canonical_id, "unreviewed_draft", ["unreviewed_draft"])

        if (
            not reviewed_by
            or not str(reviewed_by).strip()
            or str(reviewed_by).strip().lower().startswith("auto_draft:")
        ):
            return _reject(conn, canonical_id, "invalid_reviewer", ["invalid_reviewer"])

        corrected = copy.deepcopy(submitted)
        props = corrected.get("properties")
        if not isinstance(props, dict):
            props = {}
        props["reviewed_by"] = reviewed_by  # server-derived; overwrites any client value
        corrected["properties"] = props

        gt_runtime_dir = os.environ.get("GT_RUNTIME_DIR")
        if not gt_runtime_dir:
            return _reject(
                conn, canonical_id, "gt_runtime_dir_unset",
                ["GT_RUNTIME_DIR is not set -- refusing to install (fail-closed)"],
            )
        gt_dir = Path(gt_runtime_dir)
        aliases_file = gt_dir / "track_aliases.json"

        with tempfile.TemporaryDirectory(prefix="bless_geometry_") as tmp_dir:
            tmp_path = Path(tmp_dir) / f"gt_{canonical_id}.geojson"
            tmp_path.write_text(json.dumps(corrected), encoding="utf-8")

            errs = validate_gt_geojson(tmp_path)
            if errs:
                return _reject(conn, canonical_id, "validate_gt_geojson", errs)

            try:
                surface = _geojson_to_surface(corrected, track_id=canonical_id)
            except Exception as exc:
                return _reject(conn, canonical_id, "surface_build_error", [str(exc)])

            report = run_geometry_gates(surface, closed=True)
            if not report.passed:
                msgs = [f"{f.gate}: {f.message}" for f in report.failures]
                return _reject(conn, canonical_id, "geometry_gates", msgs)

            dest = install_gt_geojson(
                tmp_path, canonical_id,
                force=False, gt_dir=gt_dir, aliases_file=aliases_file,
            )

            # ACCEPT audit written right after the durable install, BEFORE
            # invalidate_gt_cache -- so a later raise there can't make the
            # outer `except Exception` record a REJECT for an install that
            # already succeeded.
            _write_audit(
                conn, canonical_id, "bless_accept",
                {"reviewed_by": reviewed_by, "dest": str(dest)},
            )

        try:
            invalidate_gt_cache(canonical_id)
        except Exception:
            # Must not flip an already-audited successful install to reject.
            logger.exception(
                "bless_geometry: invalidate_gt_cache failed after successful "
                "install canonical_id=%s", canonical_id,
            )

        return BlessResult(ok=True, failures=[])

    except InstallError as exc:
        return _reject(conn, canonical_id, "install_refused", [str(exc)])
    except Exception as exc:
        logger.exception("bless_geometry: unexpected failure canonical_id=%s", canonical_id)
        return _reject(conn, canonical_id, "internal_error", [f"internal_error: {exc}"])
