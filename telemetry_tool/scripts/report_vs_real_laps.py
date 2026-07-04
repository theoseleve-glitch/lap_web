"""Predicted-vs-real lap comparison report (spec C, Task 6) — NON-GATING.

Compares each track's predicted optimal lap time against the best real lap and
surfaces a "physics smell" when the prediction is SLOWER than a lap a human
actually drove (the optimum should never be beatable). This is a diagnostic for
human judgment, NOT a release gate: it ALWAYS exits 0. A conservative
prediction can be legitimate, so automating a block here would be dishonest —
that is the release gate's job (validate_racing_lines.py), not this report's.

Usage:
    python -m scripts.report_vs_real_laps [--json] [--out-dir DIR]
Exit code: always 0.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BANNER = "REPORT ONLY — NOT A RELEASE GATE"
_DEFAULT_OUT = "Results/optimizer_reports"


def compare_lap(track_id: str, predicted_s: float | None, best_real_s: float | None) -> dict:
    """Compare one track's predicted optimal vs best real lap.

    ``delta_s`` = predicted - best_real (positive => predicted is slower).
    ``predicted_slower`` is the physics smell: the modelled optimum being
    slower than a real lap. Missing either time => no comparison (delta None,
    smell False — absence of data is never a smell).
    """
    if predicted_s is None or best_real_s is None:
        return {
            "track_id": track_id,
            "predicted_s": predicted_s,
            "best_real_s": best_real_s,
            "delta_s": None,
            "predicted_slower": False,
        }
    delta = float(predicted_s) - float(best_real_s)
    return {
        "track_id": track_id,
        "predicted_s": float(predicted_s),
        "best_real_s": float(best_real_s),
        "delta_s": delta,
        "predicted_slower": delta > 0.0,
    }


def gather_rows(conn: Any, vehicle_class: str = "generic") -> list[dict]:
    """Best-effort: predicted optimal lap (track_racing_lines) vs best real lap.

    PG-backed and schema-tolerant — a missing real-lap source degrades to
    ``best_real_s=None`` (no comparison) rather than raising. Not unit-tested;
    the pure ``compare_lap`` + the exit-0 contract are.
    """
    from track_surface.racing_line_repo import get_racing_lines

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

    rows: list[dict] = []
    for tid in track_ids:
        predicted = None
        for line in get_racing_lines(conn, tid, vehicle_class):
            if line.get("status") == "ok" and line.get("lap_time_s") is not None:
                predicted = line["lap_time_s"]
                break
        best_real = _best_real_lap(conn, tid, vehicle_class)
        rows.append(compare_lap(tid, predicted, best_real))
    return rows


def _best_real_lap(conn: Any, track_id: str, vehicle_class: str) -> float | None:
    """Best real lap time for a track, or None if no source/lap is available."""
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT MIN(lap_time_s) FROM laps WHERE track_id = %s AND lap_time_s > 0",
                (track_id,),
            )
            row = cur.fetchone()
        finally:
            cur.close()
        if not row:
            return None
        val = row[0] if not isinstance(row, dict) else next(iter(row.values()))
        return float(val) if val is not None else None
    except Exception as exc:  # noqa: BLE001 — no real-lap source is not an error
        logger.debug("no real-lap source for %s: %s", track_id, exc)
        return None


def _print_report(rows: list[dict]) -> None:
    print("=" * 60)
    print(BANNER)
    print("=" * 60)
    width = max((len(r["track_id"]) for r in rows), default=8)
    for r in rows:
        if r["delta_s"] is None:
            print(f"  {r['track_id']:<{width}}  (no comparison — missing data)")
            continue
        smell = "  <-- SMELL: predicted slower than real" if r["predicted_slower"] else ""
        print(f"  {r['track_id']:<{width}}  pred={r['predicted_s']:.3f}s "
              f"real={r['best_real_s']:.3f}s  delta={r['delta_s']:+.3f}s{smell}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Predicted-vs-real lap report (non-gating)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--vehicle-class", default="generic")
    ap.add_argument("--out-dir", default=_DEFAULT_OUT)
    args = ap.parse_args(argv)

    from web.db_pg import get_maint_connection, return_pg_connection
    conn = get_maint_connection()
    try:
        rows = gather_rows(conn, args.vehicle_class)
    finally:
        return_pg_connection(conn)

    out_dir = Path(args.out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "vs_real_laps.json").write_text(
            json.dumps({"banner": BANNER, "rows": rows}, indent=2, default=str)
        )
    except Exception as exc:  # noqa: BLE001 — a report that can't write its file still reports
        logger.warning("could not write report file: %s", exc)

    if args.json:
        print(json.dumps({"banner": BANNER, "rows": rows}, default=str))
    else:
        _print_report(rows)

    # NON-GATING: always succeed, whatever the smells.
    return 0


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    import sys
    sys.exit(main())
