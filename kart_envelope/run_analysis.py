#!/usr/bin/env python3
"""
run_analysis.py
---------------
Run the full kart_envelope analysis pipeline on a session CSV.

Uses trained capability envelopes to:
1. Infer session conditions (grip/power/brake scalars)
2. Compute the theoretical minimum-time lap
3. Compute delta maps (actual vs theoretical)
4. Generate corner-by-corner coaching tips

Usage:
    python kart_envelope/run_analysis.py
    python kart_envelope/run_analysis.py --session OK_R4.csv
    python kart_envelope/run_analysis.py --all --all-lap-optimal
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

# Ensure project root on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from kart_envelope.config import default_config
from kart_envelope.ingest.metadata import SessionMetadata, parse_metadata
from kart_envelope.pipeline import analyze_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_one(
    session_meta: SessionMetadata,
    *,
    data_dir: Path,
    models_dir: Path,
    tracks_dir: Path,
    output_dir: Path,
    optimize_all_laps: bool,
    fast_inference: bool,
    no_cache: bool,
    solver_backend: str | None,
    solver_fallback: bool,
    product_tier: str | None,
    b2b_whitelist_tracks: str | None,
    b2b_whitelist_karts: str | None,
    b2b_whitelist_layouts: str | None,
    strict_domain: bool,
) -> dict | None:
    """Run analysis for a single session."""
    csv_path = data_dir / session_meta.session_file
    if not csv_path.exists():
        logger.error("CSV not found: %s", csv_path)
        return None

    logger.info("=" * 70)
    logger.info("ANALYSING: %s", session_meta.session_file)
    logger.info("  Track: %s | Kart: %s | Condition: %s | Record: %s",
                session_meta.track_name, session_meta.kart_id,
                session_meta.condition_label, session_meta.track_record_s)
    logger.info("=" * 70)

    config = default_config()
    if solver_backend:
        config = replace(config, solver_backend=solver_backend)
    if not solver_fallback:
        config = replace(config, solver_backend_fallback_to_qss=False)
    if fast_inference:
        config = replace(config, fast_inference_mode=True)
    if no_cache:
        config = replace(config, reuse_cached_session_outputs=False)
    if product_tier:
        config = replace(config, product_tier=product_tier)
        session_meta.product_tier = product_tier
    if b2b_whitelist_tracks is not None:
        config = replace(config, b2b_whitelist_track_ids=b2b_whitelist_tracks)
    if b2b_whitelist_karts is not None:
        config = replace(config, b2b_whitelist_kart_ids=b2b_whitelist_karts)
    if b2b_whitelist_layouts is not None:
        config = replace(config, b2b_whitelist_layout_ids=b2b_whitelist_layouts)
    if strict_domain:
        config = replace(config, domain_soft_gate_enable=False)
    t0 = time.time()

    result = analyze_session(
        csv_path=csv_path,
        metadata=session_meta,
        config=config,
        models_dir=models_dir,
        tracks_dir=tracks_dir,
        output_dir=output_dir,
        optimize_all_laps=optimize_all_laps,
    )

    elapsed = time.time() - t0

    # Print results
    logger.info("-" * 70)
    logger.info("RESULTS for %s (%.1f s):", session_meta.session_file, elapsed)

    if result.get("errors"):
        for err in result["errors"]:
            logger.error("  ERROR: %s", err)

    if "session_scalars" in result:
        sc = result["session_scalars"]
        logger.info("  Session scalars: grip=%.2f, power=%.2f, brake=%.2f (%s)",
                     sc["mu"], sc["p"], sc["b"], sc["condition"])

    if "theoretical_lap_time_s" in result:
        logger.info("  Theoretical lap time: %.3f s", result["theoretical_lap_time_s"])
    if "solver_meta" in result and isinstance(result["solver_meta"], dict):
        sm = result["solver_meta"]
        logger.info(
            "  Solver backend: requested=%s used=%s status=%s",
            sm.get("requested_backend", "?"),
            sm.get("used_backend", sm.get("backend", "?")),
            sm.get("status", "?"),
        )
    if "ideal_lap_time_s" in result:
        logger.info("  Sensitivity ideal lap: %.3f s", result["ideal_lap_time_s"])
    if "bundle_v2_optimal_lap_time_s" in result:
        logger.info("  Bundle v2 optimal lap: %.3f s", result["bundle_v2_optimal_lap_time_s"])
    if "all_lap_optimal_count" in result:
        logger.info("  All-lap optimal rows: %d", result["all_lap_optimal_count"])
    if "policy_meta" in result and isinstance(result["policy_meta"], dict):
        pm = result["policy_meta"]
        logger.info(
            "  Policy: %s (confidence %.2f)",
            pm.get("selected_policy", "unknown"),
            float(pm.get("confidence", 0.0)),
        )
    if "validation_meta" in result and isinstance(result["validation_meta"], dict):
        vm = result["validation_meta"]
        gates = vm.get("gates", {}) if isinstance(vm.get("gates"), dict) else {}
        logger.info(
            "  Validation release gate: %s",
            "PASS" if bool(gates.get("release_pass", False)) else "FAIL",
        )

    if "coaching_text" in result:
        logger.info("  Coaching summary:")
        for line in result["coaching_text"].split("\n"):
            logger.info("    %s", line)

    if "output_dir" in result:
        logger.info("  Outputs written to: %s", result["output_dir"])

    logger.info("-" * 70)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run kart envelope session analysis")
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data") / "session_metadata.csv",
        help="Metadata file (CSV/JSON/YAML).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory containing telemetry CSV files.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("data") / "models" / "kart_envelope",
        help="Directory for trained envelope models.",
    )
    parser.add_argument(
        "--tracks-dir",
        type=Path,
        default=Path("data") / "models" / "tracks",
        help="Directory for track geometry cache.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data") / "outputs",
        help="Directory for per-session outputs.",
    )
    parser.add_argument("--session", type=str, default=None,
                        help="Session CSV filename (e.g. CKS_FP+Q.csv)")
    parser.add_argument("--all", action="store_true",
                        help="Analyse all sessions in metadata")
    parser.add_argument(
        "--all-lap-optimal",
        action="store_true",
        help="Run corner sensitivity optimizer for every clean lap (slower).",
    )
    parser.add_argument(
        "--fast-inference",
        action="store_true",
        help="Enable low-latency mode (smaller search + optional all-lap skip).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable reuse of cached session outputs.",
    )
    parser.add_argument(
        "--solver-backend",
        type=str,
        choices=("qss", "casadi_ocp"),
        default=None,
        help="Minimum-time solver backend to use.",
    )
    parser.add_argument(
        "--no-solver-fallback",
        action="store_true",
        help="Disable fallback to QSS if the configured backend fails.",
    )
    parser.add_argument("--product-tier", type=str, choices=("b2c", "b2b_basic", "b2b_premium"), default=None)
    parser.add_argument("--b2b-whitelist-tracks", type=str, default=None)
    parser.add_argument("--b2b-whitelist-karts", type=str, default=None)
    parser.add_argument("--b2b-whitelist-layouts", type=str, default=None)
    parser.add_argument("--strict-domain", action="store_true")
    args = parser.parse_args()

    meta_data = parse_metadata(args.metadata)
    by_file = {m.session_file: m for m in meta_data}
    by_stem = {Path(m.session_file).stem: m for m in meta_data}

    if args.all:
        # Run all sessions
        results = {}
        for meta in meta_data:
            result = run_one(
                meta,
                data_dir=args.data_dir,
                models_dir=args.models_dir,
                tracks_dir=args.tracks_dir,
                output_dir=args.output_dir,
                optimize_all_laps=args.all_lap_optimal,
                fast_inference=args.fast_inference,
                no_cache=args.no_cache,
                solver_backend=args.solver_backend,
                solver_fallback=not args.no_solver_fallback,
                product_tier=args.product_tier,
                b2b_whitelist_tracks=args.b2b_whitelist_tracks,
                b2b_whitelist_karts=args.b2b_whitelist_karts,
                b2b_whitelist_layouts=args.b2b_whitelist_layouts,
                strict_domain=args.strict_domain,
            )
            if result:
                results[meta.session_file] = result

        logger.info("\n" + "=" * 70)
        logger.info("ALL SESSIONS COMPLETE (%d/%d)", len(results), len(meta_data))
        logger.info("=" * 70)

        # Summary table
        logger.info("%-20s %-8s %-8s %-10s %-10s %-10s",
                     "Session", "Track", "Cond", "Theory(s)", "Grip", "Power")
        for name, res in results.items():
            sc = res.get("session_scalars", {})
            theo = res.get("theoretical_lap_time_s", 0)
            logger.info("%-20s %-8s %-8s %-10.3f %-10.2f %-10.2f",
                         name[:20],
                         res.get("track_id", "?"),
                         sc.get("condition", "?"),
                         theo,
                         sc.get("mu", 0),
                         sc.get("p", 0))
    else:
        # Run single session
        session_name = args.session or "CKS_FP+Q.csv"
        entry = by_file.get(session_name) or by_stem.get(Path(session_name).stem)
        if entry is None:
            logger.error("Session '%s' not found in metadata. Available sessions:", session_name)
            for m in meta_data:
                logger.info("  %s", m.session_file)
            sys.exit(1)

        run_one(
            entry,
            data_dir=args.data_dir,
            models_dir=args.models_dir,
            tracks_dir=args.tracks_dir,
            output_dir=args.output_dir,
            optimize_all_laps=args.all_lap_optimal,
            fast_inference=args.fast_inference,
            no_cache=args.no_cache,
            solver_backend=args.solver_backend,
            solver_fallback=not args.no_solver_fallback,
            product_tier=args.product_tier,
            b2b_whitelist_tracks=args.b2b_whitelist_tracks,
            b2b_whitelist_karts=args.b2b_whitelist_karts,
            b2b_whitelist_layouts=args.b2b_whitelist_layouts,
            strict_domain=args.strict_domain,
        )


if __name__ == "__main__":
    main()
