#!/usr/bin/env python3
"""Audit stored track-geometry sidecars against the hard geometry gates
(spec 2026-07-01 A3) and optionally quarantine the ones that fail.

Geometry (centerline, boundaries, elevation) is shared across vehicle
class/condition, so each track is audited once via its default
(generic/dry) load — grip parquets are untouched by this script.

Usage:
    python scripts/audit_track_geometry.py [--sidecar-root PATH] [--quarantine] [--json]

Exit code: 0 if every audited track passes, 2 if any track fails.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "telemetry_tool"))

from track_surface import store  # noqa: E402
from track_surface.geometry_gates import run_geometry_gates  # noqa: E402


def audit_sidecars(sidecar_root: Path, quarantine: bool) -> dict:
    """Run geometry gates against every ``track_model.parquet`` under
    ``sidecar_root/track_models/<track_id>/``.

    Loads each track once via ``store.load_track_model`` (default
    vehicle_class="generic", condition="dry" — geometry is class/condition
    -independent so this is sufficient). Load exceptions, and a ``None``
    return from a missing/unreadable model, are recorded as a FAIL with
    gate ``load_error``.

    With ``quarantine=True``, every FAILing track's ``track_model.parquet``
    is renamed to ``track_model.parquet.quarantined-<YYYYMMDD>`` (grip
    parquets are never touched) and the ``INSERT INTO track_geometry_audit``
    SQL for that track is printed to stdout — printed only, never executed,
    so this script is safe to run where Postgres is unreachable.

    Returns ``{track_id: {"passed": bool, "failures": [...], "quarantined": bool}}``.
    """
    sidecar_root = Path(sidecar_root)
    track_models_dir = sidecar_root / "track_models"
    results: dict = {}
    if not track_models_dir.is_dir():
        return results

    today = datetime.date.today().strftime("%Y%m%d")

    for track_dir in sorted(p for p in track_models_dir.iterdir() if p.is_dir()):
        model_path = track_dir / "track_model.parquet"
        if not model_path.exists():
            continue
        track_id = track_dir.name

        try:
            surface = store.load_track_model(track_id, sidecar_root=str(sidecar_root))
        except Exception as exc:  # noqa: BLE001 - any load failure is an audit FAIL
            surface = None
            load_error = str(exc)
        else:
            load_error = None if surface is not None else "load_track_model returned None"

        if load_error is not None:
            details = {
                "passed": False,
                "failures": [{"gate": "load_error", "message": load_error, "values": {}}],
            }
        else:
            report = run_geometry_gates(surface)
            details = report.to_details()

        details["quarantined"] = False

        if not details["passed"] and quarantine:
            quarantined_path = model_path.with_name(f"track_model.parquet.quarantined-{today}")
            os.replace(str(model_path), str(quarantined_path))
            details["quarantined"] = True
            gates = [f["gate"] for f in details["failures"]]
            track_id_esc = track_id.replace("'", "''")
            gates_str = json.dumps(gates).replace("'", "''")
            print(
                "INSERT INTO track_geometry_audit "
                "(track_id, passed, failed_gates, audited_at) VALUES "
                f"('{track_id_esc}', FALSE, '{gates_str}', NOW());"
            )

        results[track_id] = details

    return results


def _print_text_report(results: dict) -> None:
    for track_id, result in results.items():
        if result["passed"]:
            print(f"{track_id}: PASS")
        else:
            gates = ", ".join(f["gate"] for f in result["failures"])
            print(f"{track_id}: FAIL {gates}")

    n_pass = sum(1 for r in results.values() if r["passed"])
    n_fail = len(results) - n_pass
    print(f"\n{n_pass} passed, {n_fail} failed, {len(results)} total")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sidecar-root", type=Path, default=None,
        help="Sidecar root directory (default: store's own resolution — "
             "SIDECAR_ROOT env var, else <repo>/data/sidecars).",
    )
    parser.add_argument(
        "--quarantine", action="store_true",
        help="Rename FAILing track_model.parquet files; grip parquets untouched.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print machine-readable JSON results instead of the text report.",
    )
    args = parser.parse_args(argv)

    sidecar_root = args.sidecar_root if args.sidecar_root is not None else store._default_sidecar_root()
    results = audit_sidecars(Path(sidecar_root), quarantine=args.quarantine)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        _print_text_report(results)

    n_fail = sum(1 for r in results.values() if not r["passed"])
    return 2 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
