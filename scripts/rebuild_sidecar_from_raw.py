"""Rebuild a track-surface sidecar from a raw RaceChrono CSV via the CURRENT pipeline.

Task 8b helper. Replicates the production pipeline's sidecar-build path
(``pipeline/stages/s10d_surface.py``) minimally, without dragging in the DB /
celery / 14-stage orchestrator:

  raw RaceChrono CSV
    → read_racechrono_csv (legacy in-memory path; set TELEMETRY_INGEST_V2=0)
    → split by ``Lap #`` into {lap_number: DataFrame}
    → resampling.resample_all_laps  (uniform distance grid, pipeline default)
    → track_surface.builder.build_track_surface(laps, track_id, adapter_format)
    → track_surface.store.merge_track_model(... sidecar_root=<scratch>)

The build frame is whatever ``build_track_surface`` constructs: gt_anchored when
a GT alias resolves for ``track_id`` (real-track geometry), driven_median
otherwise. This is exactly the production behaviour — no projection done here.

Usage
-----
    SIDECAR_ROOT not needed; pass --sidecar-root explicitly.

    python scripts/rebuild_sidecar_from_raw.py \
        --csv  C:/.../MKR_R.csv \
        --track-id mkr \
        --sidecar-root reports/sidecars_rebuild \
        --vehicle-class kart --condition dry \
        --adapter-format racechrono --n-points 1000 --max-laps 0

``--max-laps N`` caps the number of laps fed to the builder (0 = all). Multiple
``--csv`` flags accumulate laps across sessions into ONE build (needed when a
single session has < the grip-surface lap threshold).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "telemetry_tool"))

# Canonical column names produced by RaceChronoAdapter.parse(). The
# resampler's required distance column is the RAW "Distance (m)" name (see
# resampling._COL_DIST), so we keep that one un-renamed by re-adding it.
_LAP_COL = "lap_number"
_DIST_CANON = "distance_m"
_DIST_RAW = "Distance (m)"


def _load_and_split(csv_path: Path, n_points: int) -> dict[int, pd.DataFrame]:
    """Parse one RaceChrono CSV through the production adapter, split by lap,
    resample each lap.

    Uses ``RaceChronoAdapter.parse`` (NOT the bare ``read_racechrono_csv``) so
    the canonical channels the surface builder + grip-2d step consume are
    present — crucially ``accel_lat_mps2`` (G→m/s² converted) for the dynamics
    inversion, plus ``speed_mps``, ``lat_deg``/``lon_deg``. This mirrors the
    s10d pipeline path exactly; the bare reader leaves grip_2d empty because
    it never derives ``accel_lat_mps2``.
    """
    # Force the legacy in-memory reader for determinism/robustness on these files.
    os.environ.setdefault("TELEMETRY_INGEST_V2", "0")
    from telemetry_tool.adapters.racechrono_adapter import RaceChronoAdapter
    from resampling import resample_all_laps

    df = RaceChronoAdapter().parse(str(csv_path))
    if _LAP_COL not in df.columns:
        raise SystemExit(f"{csv_path}: no {_LAP_COL!r} column (have {list(df.columns)[:8]})")
    # The resampler keys off the RAW distance column name; re-add it from the
    # canonical one if the adapter renamed it.
    if _DIST_RAW not in df.columns:
        if _DIST_CANON in df.columns:
            df[_DIST_RAW] = pd.to_numeric(df[_DIST_CANON], errors="coerce")
        else:
            raise SystemExit(f"{csv_path}: no distance column for resampling")

    lap_raw = pd.to_numeric(df[_LAP_COL], errors="coerce")
    lap_dict: dict[int, pd.DataFrame] = {}
    for lap_val in sorted(lap_raw.dropna().unique()):
        sub = df[lap_raw == lap_val].copy()
        if len(sub) < 50:
            continue
        # A valid closed lap needs a non-trivial distance span.
        d = pd.to_numeric(sub[_DIST_RAW], errors="coerce")
        if not np.isfinite(d).any() or (d.max() - d.min()) < 50.0:
            continue
        lap_dict[int(lap_val)] = sub

    resampled = resample_all_laps(lap_dict, n_points=n_points)
    return resampled


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", action="append", required=True,
                    help="raw RaceChrono CSV (repeatable to accumulate sessions)")
    ap.add_argument("--track-id", required=True)
    ap.add_argument("--sidecar-root", required=True)
    ap.add_argument("--vehicle-class", default="kart")
    ap.add_argument("--condition", default="dry")
    ap.add_argument("--adapter-format", default="racechrono")
    ap.add_argument("--n-points", type=int, default=1000)
    ap.add_argument("--max-laps", type=int, default=0,
                    help="cap laps fed to the builder (0 = all)")
    ap.add_argument("--summary-json", default=None)
    args = ap.parse_args()

    from track_surface.builder import build_track_surface
    from track_surface.store import merge_track_model, load_track_model

    # Accumulate laps across all --csv inputs into one renumbered dict.
    all_laps: dict[int, pd.DataFrame] = {}
    next_id = 1
    for csv in args.csv:
        laps = _load_and_split(Path(csv), args.n_points)
        print(f"{csv}: {len(laps)} usable laps after resample")
        for _, lap_df in sorted(laps.items()):
            all_laps[next_id] = lap_df
            next_id += 1

    if args.max_laps and len(all_laps) > args.max_laps:
        kept = dict(list(sorted(all_laps.items()))[: args.max_laps])
        all_laps = {i + 1: v for i, (_, v) in enumerate(sorted(kept.items()))}
    print(f"Total laps fed to builder: {len(all_laps)}")

    surface = build_track_surface(all_laps, args.track_id, args.adapter_format)

    ok = merge_track_model(
        args.track_id, surface,
        sidecar_root=args.sidecar_root,
        vehicle_class=args.vehicle_class, condition=args.condition,
    )
    print(f"merge_track_model -> {ok}")

    # Reload from disk to report the persisted summary (round-trips parquet).
    reloaded = load_track_model(
        args.track_id, sidecar_root=args.sidecar_root,
        vehicle_class=args.vehicle_class, condition=args.condition,
    )
    summary = (reloaded or surface).to_summary_dict()
    # Add geometry diagnostics for the old-vs-new comparison.
    cl = (reloaded or surface).frenet.centerline_xy
    c = cl - cl.mean(0)
    _, _, vt = np.linalg.svd(c, full_matrices=False)
    pc1, pc2 = c @ vt[0], c @ vt[1]
    summary["pca_major_axis_m"] = round(float(pc1.max() - pc1.min()), 1)
    summary["pca_minor_axis_m"] = round(float(pc2.max() - pc2.min()), 1)
    summary["surface_frame"] = (
        "gt_anchored" if surface.boundary_source == "gt_anchored_native"
        else "driven_median"
    )

    print(json.dumps(summary, indent=2))
    if args.summary_json:
        Path(args.summary_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary_json).write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
