"""Racing-line release gate (spec C, §5).

Runs the physics self-consistency validator over persisted racing lines. ANY
red -> non-zero exit == no deploy. This is the gate the release runbook calls
before shipping a solver/geometry change to prod.

Design: a pure, testable core (``evaluate_lines``) that validates an iterable
of ``(label, sol, track_model)`` items, plus a PG-backed ``gather_gt_items``
that reconstructs those items from the ``track_racing_lines`` store. The core
is fail-SAFE: a validator that errors counts as a RED (never a silent pass).

Usage:
    python -m scripts.validate_racing_lines [--json] [--vehicle-class generic]
Exit codes: 0 = all green; 2 = at least one red (or no lines to check when
--require-lines is set).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from types import SimpleNamespace
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


def sol_from_points(points: list[dict]) -> SimpleNamespace:
    """Reconstruct the minimal solution trajectory the validator reads
    (distance_m, lateral_offset_m, speed_mps) from stored DTO points [{d,n,v}]."""
    import numpy as np
    d = np.array([p["d"] for p in points], dtype=float)
    n = np.array([p["n"] for p in points], dtype=float)
    v = np.array([p["v"] for p in points], dtype=float)
    return SimpleNamespace(distance_m=d, lateral_offset_m=n, speed_mps=v)


def evaluate_lines(
    items: Iterable[tuple[str, Any, Any]],
    validate: Callable[[Any, Any], Any] | None = None,
) -> tuple[bool, list[dict]]:
    """Validate each (label, sol, track_model). Returns (all_passed, rows).

    Fail-SAFE: a validator exception marks that line RED (recorded, not raised).
    """
    if validate is None:  # lazy import so the module loads without casadi
        from track_surface.solution_validator import validate_solution as validate

    rows: list[dict] = []
    all_ok = True
    for label, sol, track in items:
        try:
            report = validate(sol, track)
            passed = bool(report.passed)
            detail = report.to_dict() if hasattr(report, "to_dict") else None
        except Exception as exc:  # noqa: BLE001 — fail-safe
            passed = False
            detail = {"error": str(exc)[:200]}
        all_ok = all_ok and passed
        rows.append({"label": label, "passed": passed, "detail": detail})
    return all_ok, rows


def gather_gt_items(conn: Any, vehicle_class: str = "generic") -> list[tuple[str, Any, Any]]:
    """Build (label, sol, track_model) for every persisted ``status='ok'`` line.

    PG-backed (not unit-tested here — the synthetic gate test covers the core).
    """
    from track_surface.racing_line_repo import get_racing_lines
    from track_surface.store import load_track_model
    from track_surface.solver_bridge import surface_to_track_model

    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT DISTINCT track_id FROM track_racing_lines "
            "WHERE vehicle_class = %s AND status = 'ok'",
            (vehicle_class,),
        )
        track_ids = [r[0] if not isinstance(r, dict) else r["track_id"] for r in cur.fetchall()]
    finally:
        cur.close()

    items: list[tuple[str, Any, Any]] = []
    for tid in track_ids:
        for line in get_racing_lines(conn, tid, vehicle_class):
            if line.get("status") != "ok" or not line.get("points"):
                continue
            cond = line["condition"]
            surface = load_track_model(tid, vehicle_class=vehicle_class, condition=cond)
            if surface is None:
                items.append((f"{tid}/{cond}", None, None))
                continue
            try:
                track_model = surface_to_track_model(surface)
                sol = sol_from_points(line["points"])
                items.append((f"{tid}/{cond}", sol, track_model))
            except Exception as exc:  # noqa: BLE001
                logger.warning("gather: %s/%s reconstruction failed: %s", tid, cond, exc)
                items.append((f"{tid}/{cond}", None, None))
    return items


def _print_table(rows: list[dict]) -> None:
    width = max((len(r["label"]) for r in rows), default=10)
    for r in rows:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  {r['label']:<{width}}  {mark}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Racing-line physics self-consistency release gate")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--vehicle-class", default="generic")
    ap.add_argument("--require-lines", action="store_true",
                    help="exit non-zero if there are no lines to check")
    args = ap.parse_args(argv)

    from web.db_pg import get_maint_connection, return_pg_connection
    conn = get_maint_connection()
    try:
        items = gather_gt_items(conn, args.vehicle_class)
    finally:
        return_pg_connection(conn)

    all_ok, rows = evaluate_lines(items)

    if args.json:
        print(json.dumps({"all_passed": all_ok, "n": len(rows), "rows": rows}, default=str))
    else:
        print(f"Racing-line release gate: {len(rows)} line(s)")
        _print_table(rows)
        print("RESULT:", "GREEN — safe to deploy" if all_ok else "RED — DO NOT DEPLOY")

    if not rows and args.require_lines:
        return 2
    return 0 if all_ok else 2


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
