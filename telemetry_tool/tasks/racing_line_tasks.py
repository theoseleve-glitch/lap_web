"""Celery task: compute optimal racing lines per track + condition.

Lane 2 orchestration task.  Loads grip sidecars, runs the ported 2D OCP
solver, converts the result to the racing-line DTO, and writes through the
repo.  Degrades to ``status="failed"`` on insufficient laps or solver error —
never raises into the pipeline.

Wet-condition grip model (spec §4/§8):
  The wet solve loads the DRY grip sidecar, not a separate wet sidecar.
  build_wet_mu_field then INVERTS the dry grip map (high dry mu = rubber = slick
  in wet) to derive a wet field.  Elevation-based puddle zones are computed here
  via compute_drainage and passed to solve_optimal_line_2d, which applies them as
  both soft mu=0.2 field penalties (build_wet_mu_field) and hard corridor
  exclusions (puddles_to_n_windows).  When no 3D elevation surface is available
  on the loaded TrackSurface, puddles defaults to [] (no exclusions).

Registration idiom: ``from celery_app import celery`` (the working pattern;
see archival_tasks.py).  Do NOT use the ``_get_celery()`` guard from
ocp_tasks.py — that imports the nonexistent ``tasks.celery_app`` and silently
degrades to an unregistered plain function.
"""
from __future__ import annotations

import hashlib
import logging

import numpy as np

from celery_app import celery  # working idiom (archival_tasks.py)
from web.db_pg import get_maint_connection, return_pg_connection
from track_surface.drainage import compute_drainage
from track_surface.store import load_track_model
from track_surface.solver_bridge import solve_optimal_line_2d
from track_surface.racing_line_dto import racing_line_from_solution
from track_surface.racing_line_repo import (
    upsert_racing_line,
    set_racing_line_status,
    get_racing_lines,
)
from track_surface.honesty import decide_tier, build_provenance

logger = logging.getLogger(__name__)

SOLVER_VERSION = "ocp2d-stitched-v1"
GEOMETRY_GATES_VERSION = "a3-2026-07"


def _validate_solution_safe(sol, surface) -> tuple[bool, dict]:
    """Run the physics self-consistency validator (spec §5). Fail-SAFE: any
    error -> (False, {...}), so an un-validatable line can never be labelled
    optimal_line."""
    try:
        from track_surface.solution_validator import validate_solution
        from track_surface.solver_bridge import surface_to_track_model
        report = validate_solution(sol, surface_to_track_model(surface))
        return bool(report.passed), report.to_dict()
    except Exception as exc:  # noqa: BLE001 — fail-safe by design
        logger.warning("racing-line validation could not run: %s", exc)
        return False, {"error": str(exc)[:200]}


def _grip_conf_summary(grip) -> dict:
    """min/mean/p90 of the grip confidence grid, for provenance."""
    try:
        conf = getattr(grip, "confidence", None)
        if conf is None or getattr(conf, "size", 0) == 0:
            return {}
        c = np.asarray(conf, dtype=float)
        return {
            "min": float(c.min()),
            "mean": float(c.mean()),
            "p90": float(np.percentile(c, 90)),
        }
    except Exception:  # noqa: BLE001
        return {}

# Map each solved condition to the sidecar condition label used by load_track_model.
# - dry  loads the dry sidecar (measured grip).
# - damp loads the REAL damp sidecar (measured grip from damp-labelled sessions),
#   solved like dry — a distinct tier, not a wet alias. Fails gracefully (status
#   =failed) until damp sessions accumulate for a track.
# - wet  loads the DRY sidecar: build_wet_mu_field inverts the dry grip map to
#   derive the wet field (rubber line = hydrophobic = slick in wet; clean asphalt
#   preferred), because prod rarely has enough real wet laps.
_SIDECAR_FOR: dict[str, str] = {"dry": "dry", "damp": "damp", "wet": "dry"}


def _grip_hash(grip) -> str:
    """Stable 16-hex hash of a Grip2D object (mu_grid + count_grid)."""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(grip.mu_grid).tobytes())
    if grip.count_grid is not None:
        h.update(np.ascontiguousarray(grip.count_grid).tobytes())
    return h.hexdigest()[:16]


def _compute_racing_lines_impl(
    track_id: str,
    vehicle_class: str = "generic",
) -> dict:
    """Plain function that executes the racing-line computation.

    Split from the Celery task wrapper so tests can call it directly without
    a running Celery broker.  All external dependencies are imported at
    module level and can therefore be patched in tests.

    Returns a dict with ``ok`` and ``failed`` lists of conditions.
    """
    conn = get_maint_connection()
    written: dict[str, list[str]] = {"ok": [], "failed": []}
    try:
        existing = {
            r["condition"]: r.get("grip_snapshot_hash")
            for r in get_racing_lines(conn, track_id, vehicle_class)
        }

        for cond, sidecar_cond in _SIDECAR_FOR.items():
            surface = load_track_model(
                track_id, vehicle_class=vehicle_class, condition=sidecar_cond
            )

            if surface is None or surface.grip_2d is None:
                set_racing_line_status(
                    conn, track_id, vehicle_class, cond,
                    "failed", reason="insufficient_laps", tier="refused",
                )
                written["failed"].append(cond)
                continue

            snap = _grip_hash(surface.grip_2d)
            if existing.get(cond) == snap:
                # Grip unchanged since last solve — skip (no-op)
                logger.debug(
                    "racing-line: no-op %s/%s/%s (hash unchanged)", track_id, vehicle_class, cond
                )
                continue

            # For wet condition, derive puddle zones from the 3D elevation surface
            # (if present) so the solver can apply corridor exclusions.
            puddles = None
            if cond == "wet" and surface.elevation_surface is not None:
                try:
                    puddles = compute_drainage(surface.elevation_surface)
                except Exception as exc:
                    logger.warning(
                        "racing-line: puddle derivation failed %s/%s/%s: %s — "
                        "continuing without puddle exclusions",
                        track_id, vehicle_class, cond, exc,
                    )

            try:
                sol = solve_optimal_line_2d(surface, condition=cond, puddles=puddles)
            except Exception as exc:
                # Solver failure must never error the pipeline
                logger.warning(
                    "racing-line solve failed %s/%s/%s: %s",
                    track_id, vehicle_class, cond, exc,
                )
                set_racing_line_status(
                    conn, track_id, vehicle_class, cond,
                    "failed", reason=str(exc)[:120], tier="refused",
                )
                written["failed"].append(cond)
                continue

            dto = racing_line_from_solution(sol, condition=cond)
            n_laps = (
                int(np.max(surface.grip_2d.count_grid))
                if surface.grip_2d.count_grid is not None
                else 0
            )
            solved_status = (
                "ok"
                if dto["solver_meta"]["status"] in ("solved", "optimal", "Solve_Succeeded")
                else "failed"
            )

            # Honesty layer (spec C §5): the tier a consumer may trust. Physics
            # self-consistency is validated here (fail-safe); an optimal_line
            # requires human-verified GT geometry AND grip>=gold AND validation
            # green AND a solved status — else it degrades to speed_profile_only
            # (never drawable as a line) or refused.
            validation_ok, validation_report = _validate_solution_safe(sol, surface)
            geometry_source = getattr(surface, "boundary_source", None)
            tier, tier_reason = decide_tier(
                boundary_source=geometry_source,
                grip_tier=getattr(surface, "quality_tier", None),
                validation_ok=validation_ok,
                solve_status=solved_status,
            )
            provenance = build_provenance(
                laps_used=n_laps,
                grip_confidence_summary=_grip_conf_summary(surface.grip_2d),
                geometry_gates_version=GEOMETRY_GATES_VERSION,
                solver_name=SOLVER_VERSION,
                solver_version=SOLVER_VERSION,
                validation=validation_report,
                warm_start_source=None,
            )
            if tier_reason:
                provenance["tier_reason"] = tier_reason

            upsert_racing_line(
                conn, track_id, vehicle_class, cond, dto,
                solver_version=SOLVER_VERSION,
                grip_snapshot_hash=snap,
                n_laps_used=n_laps,
                status=solved_status,
                geometry_source=geometry_source,
                tier=tier,
                provenance=provenance,
            )
            written["ok"].append(cond)

        conn.commit()
        return written
    finally:
        return_pg_connection(conn)


@celery.task(
    name="tasks.racing_line_tasks.compute_racing_lines",
    queue="pipeline",
    soft_time_limit=600,
    time_limit=720,
)
def compute_racing_lines(track_id: str, vehicle_class: str = "generic") -> dict:
    """Celery task: compute dry + wet racing lines for one (track, vehicle_class) pair.

    Enqueued by the pipeline after a grip-sidecar update, and by the nightly
    beat ``compute_all_racing_lines`` for all tracks that have surface data.
    """
    return _compute_racing_lines_impl(track_id, vehicle_class)


@celery.task(
    name="tasks.racing_line_tasks.compute_all_racing_lines",
    queue="pipeline",
    soft_time_limit=300,
    time_limit=360,
)
def compute_all_racing_lines(vehicle_class: str = "generic") -> dict:
    """Nightly beat: re-solve racing lines for every track that has surface data.

    Iterates distinct track_ids from ``track_surfaces_global`` (tracks that
    have been processed at least once) and fans out a ``compute_racing_lines``
    task for each.  Individual tasks degrade gracefully when grip is still
    insufficient.
    """
    conn = get_maint_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT track_id FROM track_surfaces_global ORDER BY track_id"
        ).fetchall()
        track_ids = [
            (row["track_id"] if isinstance(row, dict) else row[0])
            for row in rows
        ]
    finally:
        return_pg_connection(conn)

    dispatched = 0
    for tid in track_ids:
        compute_racing_lines.delay(tid, vehicle_class)
        dispatched += 1

    logger.info(
        "compute_all_racing_lines: dispatched %d tasks (vehicle_class=%s)",
        dispatched, vehicle_class,
    )
    return {"dispatched": dispatched, "vehicle_class": vehicle_class}
