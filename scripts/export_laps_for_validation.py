"""Export per-lap parquet files in a sidecar's Frenet frame for OCP-2D validation.

Companion to ``scripts/validate_ocp2d.py`` (Task 8b real-data run). Takes a
RaceChrono session CSV (or a trackreco ``x_local``/``y_local`` triplet CSV),
projects each driven lap into the **sidecar's own local XY frame**, runs an
alignment sanity gate, and writes ``lap_NN.parquet`` files with the columns the
validation harness expects: ``pos_x_m``, ``pos_y_m``, ``speed_mps`` plus the
friction-envelope channels ``Speed (m/s)``, ``accel_long_mps2``,
``accel_lat_mps2`` (so the harness's no-spec resolver path can build the
driver's demonstrated longitudinal envelope without a hand-written vehicle JSON).

Why alignment matters
---------------------
The sidecar's ``FrenetFrame`` (``surface.frenet.centerline_xy``) lives in a fixed
local-metre frame produced by the track-surface pipeline. A driven lap projected
from raw GPS (equirectangular about a reference point) lands in *some* metric
frame, but not necessarily the sidecar's. We therefore estimate a 2-D rigid
transform (rotation + translation, reflection allowed) that maps the projected
lap cloud onto the centerline point cloud (ICP with multiple rotation seeds), and
apply it before splitting/exporting.

Sanity gate
-----------
After alignment, every lap is projected with ``frenet.xy_to_sn``. If fewer than
``--min-frac-inside`` of all samples fall within ``--half-width-m`` metres of the
centerline (|n|), the session geometry does not match the sidecar and the export
is **aborted** with diagnostics — exporting misaligned laps would silently poison
gate-2 (dry-plausibility) of the validation harness.

Input formats (auto-detected)
-----------------------------
* RaceChrono CSV  : header row begins ``Time (s)``; uses ``Latitude (deg)`` /
                    ``Longitude (deg)`` + ``Lap #`` + ``Speed (m/s)``.
* trackreco CSV   : flat header ``t,lat,lon,x_local,y_local,speed,heading,lap_id``.

Usage
-----
    python scripts/export_laps_for_validation.py \
        --session "<path to session.csv>" \
        --track f13294f0-... \
        --sidecar-root C:/.../data/sidecars \
        --vehicle-class generic --condition dry \
        --out-dir reports/laps_f13294f0

Add ``--diagnostics-json reports/alignment_f13294f0.json`` to persist the
alignment report. Nothing is written under ``--out-dir`` unless the sanity gate
passes (use ``--force`` to export anyway for debugging).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "telemetry_tool"))

_EQUIRECT_M_PER_DEG = 111_320.0  # metres per degree of latitude (WGS84 mean)


# ── session loading ──────────────────────────────────────────────────────────


def _load_session(path: Path) -> pd.DataFrame:
    """Return a frame with columns: lat, lon, speed_mps, lap (int), time_s.

    ``time_s`` carries the log's REAL timestamp (seconds; absolute or elapsed —
    only intra-lap differences are used downstream) so per-lap accel can be
    differentiated at the true sample rate instead of a hardcoded dt. It is NaN
    when the source has no time/``t`` column.

    Handles both RaceChrono exports and flat trackreco triplet CSVs.
    """
    # Peek at the first line to choose a reader.
    first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    if first.split(",")[0].strip().lower() in {"t", "time", "timestamp"} and "lat" in first.lower():
        # trackreco flat CSV
        df = pd.read_csv(path)
        cols = {c.lower(): c for c in df.columns}
        time_col = next((cols[k] for k in ("t", "time", "timestamp", "time_s", "t_s")
                         if k in cols), None)
        time_s = (pd.to_numeric(df[time_col], errors="coerce")
                  if time_col is not None else pd.Series(np.nan, index=df.index))
        return pd.DataFrame({
            "lat": pd.to_numeric(df[cols["lat"]], errors="coerce"),
            "lon": pd.to_numeric(df[cols["lon"]], errors="coerce"),
            "speed_mps": pd.to_numeric(df[cols.get("speed", "speed")], errors="coerce"),
            "lap": pd.to_numeric(df[cols.get("lap_id", "lap_id")], errors="coerce"),
            "time_s": time_s,
        }).dropna(subset=["lat", "lon"])

    # RaceChrono export — reuse the production reader.
    from telemetry_tool.io_racechrono import read_racechrono_csv
    df = read_racechrono_csv(path)

    def pick(*names: str) -> pd.Series:
        for n in names:
            if n in df.columns:
                return pd.to_numeric(df[n], errors="coerce")
        raise KeyError(f"none of {names} present in {list(df.columns)[:12]}")

    def pick_opt(*names: str) -> pd.Series:
        """Like pick, but returns an all-NaN column instead of raising."""
        for n in names:
            if n in df.columns:
                return pd.to_numeric(df[n], errors="coerce")
        return pd.Series(np.nan, index=df.index)

    return pd.DataFrame({
        "lat": pick("Latitude (deg)", "Latitude"),
        "lon": pick("Longitude (deg)", "Longitude"),
        "speed_mps": pick("Speed (m/s)", "Speed (m/s) *calc"),
        "lap": pick("Lap #", "lap_number"),
        # Real timestamp: RaceChrono fused logs carry a per-sample "Time (s)"
        # (absolute epoch) and an "Elapsed time (s)"; either gives the true dt.
        "time_s": pick_opt("Time (s)", "Elapsed time (s)", "time_s", "t_s"),
    }).dropna(subset=["lat", "lon"])


def _equirect(lat: np.ndarray, lon: np.ndarray,
              lat0: float, lon0: float) -> np.ndarray:
    """Project lat/lon to local metres about (lat0, lon0)."""
    x = (lon - lon0) * _EQUIRECT_M_PER_DEG * np.cos(np.radians(lat0))
    y = (lat - lat0) * _EQUIRECT_M_PER_DEG
    return np.column_stack([x, y])


# ── rigid alignment (ICP) ────────────────────────────────────────────────────


def _kabsch(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Best rotation+translation mapping ``src`` onto ``dst`` (paired points)."""
    cs, cd = src.mean(0), dst.mean(0)
    h = (src - cs).T @ (dst - cd)
    u, _, vt = np.linalg.svd(h)
    rot = vt.T @ u.T  # reflection allowed (no det correction)
    return rot, cd - rot @ cs


def align_to_centerline(cloud: np.ndarray, centerline: np.ndarray,
                        n_init: int = 16, iters: int = 120,
                        max_pts: int = 4000) -> tuple[np.ndarray, np.ndarray, dict]:
    """ICP-fit a 2-D rigid transform from ``cloud`` onto ``centerline``.

    Tries ``n_init`` rotation seeds (and their reflections), keeps the lowest
    median nearest-neighbour distance. Returns ``(R, t, info)``; apply with
    ``cloud @ R.T + t``.
    """
    from scipy.spatial import cKDTree

    tree = cKDTree(centerline)
    src = cloud
    if len(src) > max_pts:
        src = src[np.linspace(0, len(src) - 1, max_pts).astype(int)]
    c_src, c_dst = src.mean(0), centerline.mean(0)

    best: tuple | None = None
    for k in range(n_init):
        theta = 2 * np.pi * k / n_init
        for reflect in (False, True):
            rot = np.array([[np.cos(theta), -np.sin(theta)],
                            [np.sin(theta), np.cos(theta)]])
            if reflect:
                rot = rot @ np.array([[1.0, 0.0], [0.0, -1.0]])
            t = c_dst - rot @ c_src
            pts = src @ rot.T + t
            for _ in range(iters):
                _, nn = tree.query(pts)
                rot, t = _kabsch(src, centerline[nn])
                pts = src @ rot.T + t
            dist, _ = tree.query(pts)
            med = float(np.median(dist))
            if best is None or med < best[0]:
                best = (med, rot, t)
    assert best is not None
    med, rot, t = best
    return rot, t, {"icp_median_nn_m": round(med, 4),
                    "n_seed_rotations": n_init, "iters_per_seed": iters}


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, help="session CSV path")
    ap.add_argument("--track", required=True, help="sidecar track_id")
    ap.add_argument("--sidecar-root", required=True)
    ap.add_argument("--vehicle-class", default="generic")
    ap.add_argument("--condition", default="dry")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--half-width-m", type=float, default=6.0,
                    help="|n| tolerance for the alignment sanity gate")
    ap.add_argument("--min-frac-inside", type=float, default=0.80,
                    help="min fraction of samples within half-width to pass")
    ap.add_argument("--min-lap-pts", type=int, default=200)
    ap.add_argument("--diagnostics-json", default=None)
    ap.add_argument("--force", action="store_true",
                    help="export laps even if the sanity gate fails")
    args = ap.parse_args()

    from track_surface.store import load_track_model

    surface = load_track_model(
        args.track, sidecar_root=args.sidecar_root,
        vehicle_class=args.vehicle_class, condition=args.condition)
    if surface is None:
        print(f"FAIL: no sidecar for track {args.track!r}")
        return 2
    frenet = surface.frenet
    centerline = frenet.centerline_xy

    sess = _load_session(Path(args.session))
    lat0, lon0 = float(sess["lat"].iloc[0]), float(sess["lon"].iloc[0])
    cloud = _equirect(sess["lat"].to_numpy(), sess["lon"].to_numpy(), lat0, lon0)

    rot, t, info = align_to_centerline(cloud, centerline)
    aligned = cloud @ rot.T + t
    _, n_all = frenet.xy_to_sn(aligned[:, 0], aligned[:, 1])
    frac_inside = float(np.mean(np.abs(n_all) <= args.half_width_m))

    diag = {
        "track": args.track, "session": str(args.session),
        "ref_lat": lat0, "ref_lon": lon0,
        "centerline_length_m": round(float(frenet.total_length_m), 2),
        "n_samples": int(len(n_all)),
        "frac_within_half_width": round(frac_inside, 4),
        "half_width_m": args.half_width_m,
        "median_abs_n_m": round(float(np.median(np.abs(n_all))), 3),
        "p90_abs_n_m": round(float(np.percentile(np.abs(n_all), 90)), 3),
        **info,
        "sanity_gate_passed": frac_inside >= args.min_frac_inside,
    }
    print(json.dumps(diag, indent=2))
    if args.diagnostics_json:
        Path(args.diagnostics_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.diagnostics_json).write_text(json.dumps(diag, indent=2))

    if not diag["sanity_gate_passed"] and not args.force:
        print(f"\nBLOCKED: only {frac_inside:.1%} of samples within "
              f"|n|<={args.half_width_m} m (need {args.min_frac_inside:.0%}). "
              f"Session geometry does not match this sidecar's Frenet frame; "
              f"not exporting. Re-run with --force to override.")
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n_exported = 0
    for lap_id in sorted(sess["lap"].dropna().unique()):
        mask = (sess["lap"] == lap_id).to_numpy()
        if mask.sum() < args.min_lap_pts:
            continue
        xy = aligned[mask]
        x = xy[:, 0]
        y = xy[:, 1]
        v = sess["speed_mps"].to_numpy()[mask]
        t_real = sess["time_s"].to_numpy()[mask]

        # ── friction-envelope channels ────────────────────────────────────
        # The validation harness's resolver path feeds these to
        # friction_envelope.compute_friction_envelope to build the driver's
        # DEMONSTRATED longitudinal envelope. accel_long = d(speed)/dt MUST be
        # differentiated at the log's REAL sample interval. RaceChrono fused
        # logs run at ~hundreds of Hz with non-uniform spacing; using a
        # hardcoded dt mis-scales accel_long by ~30x. When a real time column
        # exists we resample the lap onto a uniform 20 Hz grid (kills the fused
        # -log spike noise too) and differentiate on that base; geometry (x/y)
        # is resampled on the SAME grid so accel_lat stays aligned.
        DT_U = 0.05  # 20 Hz uniform resample step (s)
        have_time = np.isfinite(t_real).all() and len(t_real) > 1
        if have_time:
            t0, t1 = float(np.nanmin(t_real)), float(np.nanmax(t_real))
        if have_time and (t1 - t0) > 1.0:
            # Ensure strictly increasing time for np.interp (sort defensively).
            order = np.argsort(t_real)
            t_s, v_s = t_real[order], v[order]
            x_s, y_s = x[order], y[order]
            t_u = np.arange(t0, t1, DT_U)
            v = np.interp(t_u, t_s, v_s)
            x = np.interp(t_u, t_s, x_s)
            y = np.interp(t_u, t_s, y_s)
            accel_long = np.gradient(v) / DT_U
        else:
            # No usable real time: fall back to a uniform 10 Hz assumption.
            # accel scale is ASSUMED here and may be mis-scaled — warn loudly.
            print(f"WARNING: lap {lap_id}: no real time column; assuming 10 Hz "
                  f"(accel_long scale is unverified for this lap).")
            tt = np.arange(len(v)) * 0.1
            dt = np.gradient(tt)
            dt[dt <= 1e-6] = 1e-6
            accel_long = np.gradient(v) / dt
        dx, dy = np.gradient(x), np.gradient(y)
        ddx, ddy = np.gradient(dx), np.gradient(dy)
        denom = (dx * dx + dy * dy) ** 1.5
        denom[denom < 1e-9] = 1e-9
        kappa = (dx * ddy - dy * ddx) / denom
        accel_lat = v * v * kappa

        lap_df = pd.DataFrame({
            "pos_x_m": x,
            "pos_y_m": y,
            "speed_mps": v,
            # channels read by friction_envelope (vehicle_profile resolver)
            "Speed (m/s)": v,
            "accel_long_mps2": accel_long,
            "accel_lat_mps2": accel_lat,
        }).dropna()
        if len(lap_df) < args.min_lap_pts:
            continue
        n_exported += 1
        lap_df.to_parquet(out_dir / f"lap_{n_exported:02d}.parquet", index=False)

    print(f"\nExported {n_exported} lap parquet(s) to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
