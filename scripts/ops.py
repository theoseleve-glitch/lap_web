"""Ops CLI — registry / manifest / accumulator management.

Subcommands:
    add-vehicle-profile     Add a calibration profile to the registry
    deprecate-profile       Mark a profile deprecated
    activate-profile        Activate a profile (deactivates siblings)
    list-profiles           List all profiles in the registry
    add-dataset             Append a dataset to the manifest (JSON entry)
    validate-manifest       Validate the manifest end-to-end
    inspect-accumulator     Summarize all accumulators in a directory
    smoke-pick              Print the smoke-mode dataset selection

Examples:
    python scripts/ops.py list-profiles --registry data/vehicle_calibrations.json

    python scripts/ops.py add-vehicle-profile \\
        --registry data/vehicle_calibrations.json \\
        --profile-id audirs3lms_v1 --vehicle-key audirs3lms \\
        --vehicle-class TCR \\
        --tire-d1-lat 2.4 --tire-d1-long 2.3 \\
        --roll-compliance 0.004

    python scripts/ops.py validate-manifest --manifest data/cross_track_manifest.json

    python scripts/ops.py inspect-accumulator --accumulator-dir accumulators
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "telemetry_tool"))

from track_surface.validation import ops  # noqa: E402


def _print_result(result: ops.OpsResult, *, json_out: bool) -> int:
    if json_out:
        print(json.dumps({
            "ok": result.ok,
            "message": result.message,
            "details": result.details,
        }, indent=2))
    else:
        prefix = "OK" if result.ok else "ERROR"
        print(f"[{prefix}] {result.message}")
        if result.details:
            print()
            print(json.dumps(result.details, indent=2, default=str))
    return 0 if result.ok else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ops CLI for the friction estimation pipeline.")
    p.add_argument("--json", action="store_true", help="Emit JSON output (machine-readable).")
    sub = p.add_subparsers(dest="cmd", required=True)

    # add-vehicle-profile
    a = sub.add_parser("add-vehicle-profile",
                       help="Add a calibration profile to the registry.")
    a.add_argument("--registry", type=Path, required=True)
    a.add_argument("--profile-id", required=True)
    a.add_argument("--vehicle-key", required=True)
    a.add_argument("--vehicle-class", required=True)
    a.add_argument("--tire-d1-lat", type=float, required=True)
    a.add_argument("--tire-d1-long", type=float, required=True)
    a.add_argument("--roll-compliance", type=float, required=True)
    a.add_argument("--pitch-compliance", type=float, default=0.003)
    a.add_argument("--fit-method", default="manual")
    a.add_argument("--n-samples", type=int, default=0)
    a.add_argument("--notes", default="")
    a.add_argument("--no-activate", action="store_true",
                   help="Do not mark this profile active on insert.")

    # deprecate-profile
    d = sub.add_parser("deprecate-profile", help="Mark a profile deprecated.")
    d.add_argument("--registry", type=Path, required=True)
    d.add_argument("--profile-id", required=True)
    d.add_argument("--reason", default="")

    # activate-profile
    ac = sub.add_parser("activate-profile",
                        help="Activate a profile (deactivates other profiles for the same vehicle).")
    ac.add_argument("--registry", type=Path, required=True)
    ac.add_argument("--profile-id", required=True)

    # list-profiles
    lp = sub.add_parser("list-profiles", help="List all profiles in the registry.")
    lp.add_argument("--registry", type=Path, required=True)

    # add-dataset
    ad = sub.add_parser("add-dataset",
                        help="Append a dataset to the manifest. Reads JSON entry from --entry-file or stdin.")
    ad.add_argument("--manifest", type=Path, required=True)
    ad.add_argument("--entry-file", type=Path,
                    help="Path to a JSON file with the dataset entry. "
                         "Reads stdin if omitted.")

    # validate-manifest
    vm = sub.add_parser("validate-manifest", help="Validate the manifest.")
    vm.add_argument("--manifest", type=Path, required=True)

    # inspect-accumulator
    ia = sub.add_parser("inspect-accumulator",
                        help="Summarize all accumulators in a directory.")
    ia.add_argument("--accumulator-dir", type=Path, required=True)

    # smoke-pick
    sp = sub.add_parser("smoke-pick",
                        help="Print the dataset(s) the release gate would pick in smoke mode.")
    sp.add_argument("--manifest", type=Path, required=True)
    sp.add_argument("--max-datasets", type=int, default=1)
    sp.add_argument("--only", nargs="*", default=None)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    if args.cmd == "add-vehicle-profile":
        result = ops.add_vehicle_profile(
            registry_path=args.registry,
            profile_id=args.profile_id,
            vehicle_key=args.vehicle_key,
            vehicle_class=args.vehicle_class,
            tire_d1_lat=args.tire_d1_lat,
            tire_d1_long=args.tire_d1_long,
            roll_compliance=args.roll_compliance,
            pitch_compliance=args.pitch_compliance,
            fit_method=args.fit_method,
            n_samples=args.n_samples,
            notes=args.notes,
            activate=not args.no_activate,
        )
        return _print_result(result, json_out=args.json)

    if args.cmd == "deprecate-profile":
        result = ops.deprecate_profile(
            registry_path=args.registry,
            profile_id=args.profile_id,
            reason=args.reason,
        )
        return _print_result(result, json_out=args.json)

    if args.cmd == "activate-profile":
        result = ops.activate_profile(
            registry_path=args.registry,
            profile_id=args.profile_id,
        )
        return _print_result(result, json_out=args.json)

    if args.cmd == "list-profiles":
        result = ops.list_profiles(registry_path=args.registry)
        return _print_result(result, json_out=args.json)

    if args.cmd == "add-dataset":
        if args.entry_file:
            with open(args.entry_file, "r", encoding="utf-8") as f:
                entry = json.load(f)
        else:
            entry = json.load(sys.stdin)
        result = ops.add_dataset_to_manifest(
            manifest_path=args.manifest, entry=entry,
        )
        return _print_result(result, json_out=args.json)

    if args.cmd == "validate-manifest":
        result = ops.validate_manifest(manifest_path=args.manifest)
        return _print_result(result, json_out=args.json)

    if args.cmd == "inspect-accumulator":
        result = ops.inspect_accumulator(accumulator_dir=args.accumulator_dir)
        return _print_result(result, json_out=args.json)

    if args.cmd == "smoke-pick":
        result = ops.smoke_test_manifest(
            manifest_path=args.manifest,
            only=args.only,
            max_datasets=args.max_datasets,
        )
        return _print_result(result, json_out=args.json)

    print(f"unknown command: {args.cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
