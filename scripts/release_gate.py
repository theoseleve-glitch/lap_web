"""Release gate CLI.

Runs the cross-track validation suite + the configurable release gate
and emits machine-readable + human-readable artifacts. Exits with:

    0 = PASS
    1 = WARN
    2 = FAIL

Usage
-----
    python scripts/release_gate.py \\
        --manifest data/cross_track_manifest.json \\
        --thresholds data/release_thresholds.json \\
        --registry data/vehicle_calibrations.json \\
        --accumulator-dir accumulators \\
        --out release_artifacts/

Smoke mode (filters to one smallest dataset, fast for CI):

    python scripts/release_gate.py --smoke \\
        --manifest data/cross_track_manifest.json \\
        --thresholds data/release_thresholds.json \\
        --out release_artifacts/
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

from track_surface.validation import run_validation_suite  # noqa: E402
from track_surface.validation.manifest import load_manifest  # noqa: E402
from track_surface.validation.ops import smoke_test_manifest  # noqa: E402
from track_surface.validation.release_gate import (  # noqa: E402
    ReleaseDecision,
    ReleaseThresholds,
    evaluate_suite,
    render_markdown,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Release gate for the friction estimation pipeline.",
    )
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--thresholds", type=Path, default=None,
                   help="Path to release_thresholds.json (defaults if missing).")
    p.add_argument("--registry", type=Path, default=None)
    p.add_argument("--accumulator-dir", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True,
                   help="Output directory for artifacts (release.json, release.md).")
    p.add_argument("--smoke", action="store_true",
                   help="Smoke mode: filter to the smallest dataset on disk for a fast check.")
    p.add_argument("--smoke-max-datasets", type=int, default=1,
                   help="Number of datasets to include in smoke mode.")
    p.add_argument("--only", nargs="*", default=None, metavar="DATASET_ID",
                   help="Restrict to these dataset ids (overrides --smoke selection).")
    p.add_argument("--legacy-gate", action="store_true",
                   help="Use legacy single-axis transition gate.")
    p.add_argument("--verbose", "-v", action="count", default=0)
    return p


def _build_class_maps(manifest_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """From the manifest, build (dataset_id → track_class) and
    (dataset_id → vehicle_class) maps for the release gate."""
    manifest = load_manifest(manifest_path)
    track_classes = {e.id: e.track.regime for e in manifest.datasets}
    vehicle_classes = {e.id: e.vehicle.klass for e in manifest.datasets}
    return track_classes, vehicle_classes


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    args.out.mkdir(parents=True, exist_ok=True)

    # Decide which datasets to run
    only_datasets = args.only
    if args.smoke and not only_datasets:
        smoke = smoke_test_manifest(
            manifest_path=args.manifest, max_datasets=args.smoke_max_datasets,
        )
        if not smoke.ok:
            print(f"smoke selection failed: {smoke.message}", file=sys.stderr)
            return 2
        only_datasets = smoke.details["chosen_ids"]
        print(f"[smoke] Selected datasets: {only_datasets}")

    # Run the validation suite (frozen pass only — adaptive is not for releases)
    suite_results = run_validation_suite(
        manifest_path=args.manifest,
        out_dir=args.out / "validation_run",
        pass_2_adaptive=False,
        only_datasets=only_datasets,
        skip_missing=True,
        calibration_registry_path=args.registry,
        accumulator_dir=args.accumulator_dir,
        use_multi_criterion_gate=not args.legacy_gate,
    )
    frozen = suite_results.get("frozen")
    if frozen is None or frozen.n_total == 0:
        print("ERROR: no sessions ran (none of the requested .ibt files were present)",
              file=sys.stderr)
        return 2

    # Build class maps for threshold resolution
    track_classes, vehicle_classes = _build_class_maps(args.manifest)

    # Load thresholds
    thresholds = ReleaseThresholds.from_json(args.thresholds) if args.thresholds else ReleaseThresholds()

    # Evaluate gate
    metrics = [r["metrics"] for r in frozen.sessions]
    report = evaluate_suite(
        suite_session_metrics=metrics,
        track_classes=track_classes,
        vehicle_classes=vehicle_classes,
        thresholds=thresholds,
        smoke_mode=bool(args.smoke or only_datasets),
    )

    # Write artifacts
    json_path = args.out / "release.json"
    md_path = args.out / "release.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))

    # Console summary
    decision = report.decision
    print()
    print("=" * 70)
    print(f"RELEASE GATE: {decision.value.upper()}")
    print("=" * 70)
    print(f"Sessions: {report.n_sessions}  PASS={report.n_pass}  WARN={report.n_warn}  FAIL={report.n_fail}")
    if report.top_failures:
        print("\nTop failure causes:")
        for f in report.top_failures:
            print(f"  - {f}")
    if report.top_warnings:
        print("\nTop warning causes:")
        for w in report.top_warnings:
            print(f"  - {w}")
    print(f"\nArtifacts: {json_path}")
    print(f"           {md_path}")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
