#!/usr/bin/env python3
"""Reprocess theoretical data for all sessions that have GPS traces.

Usage (inside Docker container):
    python3 /app/scripts/reprocess_theoretical.py

This re-runs the pipeline's theoretical computation (S10) for each session
and re-persists with normalized 0-based distances + best-lap scalars.
"""
import json
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reprocess")


def main():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    pg_url = os.environ.get("TELEMETRY_PG_URL", "postgresql://telemetry:telemetry@postgres:5432/telemetry")
    conn = psycopg2.connect(pg_url, cursor_factory=RealDictCursor)
    conn.autocommit = True

    # Find all sessions with GPS traces
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT g.session_id
        FROM gps_traces g
        JOIN sessions s ON s.session_id = g.session_id
        ORDER BY g.session_id
    """)
    session_ids = [row["session_id"] for row in cur.fetchall()]
    logger.info("Found %d sessions with GPS traces", len(session_ids))

    for sid in session_ids:
        try:
            reprocess_session(conn, sid)
        except Exception:
            logger.error("Failed to reprocess %s", sid, exc_info=True)

    conn.close()
    logger.info("Done")


def reprocess_session(conn, session_id: str):
    """Re-run theoretical computation for one session."""
    from psycopg2.extras import RealDictCursor
    import numpy as np
    import pandas as pd

    cur = conn.cursor()

    # Load GPS traces (all laps)
    cur.execute(
        "SELECT lap_number, distances_json, speeds_json, latitudes_json, longitudes_json "
        "FROM gps_traces WHERE session_id = %s ORDER BY lap_number",
        (session_id,),
    )
    rows = cur.fetchall()
    if not rows:
        logger.info("%s: no GPS traces, skipping", session_id[:12])
        return

    resampled_laps = {}
    for row in rows:
        lap = row["lap_number"]
        dists = json.loads(row["distances_json"]) if isinstance(row["distances_json"], str) else row["distances_json"]
        speeds = json.loads(row["speeds_json"]) if isinstance(row["speeds_json"], str) else row["speeds_json"]
        lats = json.loads(row["latitudes_json"]) if isinstance(row["latitudes_json"], str) else row["latitudes_json"]
        lons = json.loads(row["longitudes_json"]) if isinstance(row["longitudes_json"], str) else row["longitudes_json"]

        if not dists or not speeds:
            continue

        df = pd.DataFrame({
            "Distance (m)": dists,
            "Speed (m/s)": speeds,
        })
        if lats and len(lats) == len(dists):
            df["Latitude (deg)"] = lats
        if lons and len(lons) == len(dists):
            df["Longitude (deg)"] = lons

        resampled_laps[lap] = df

    if not resampled_laps:
        logger.info("%s: no valid laps, skipping", session_id[:12])
        return

    # Try to run theoretical adapter
    try:
        from telemetry_tool.theoretical_adapter import compute_theoretical_via_envelope
        from telemetry_tool.pipeline.helpers import build_curvature_from_laps
    except ImportError:
        logger.warning("Cannot import theoretical_adapter; skipping reprocess")
        return

    # Build curvature from best lap
    best_lap_key = min(resampled_laps.keys(), key=lambda k: _lap_time(resampled_laps[k]))
    best_df = resampled_laps[best_lap_key]

    try:
        curvature_profile = build_curvature_from_laps(resampled_laps)
    except Exception:
        # Fallback: compute curvature from best lap GPS
        logger.warning("%s: curvature build failed, computing from GPS", session_id[:12])
        curvature_profile = _curvature_from_gps(best_df)

    if curvature_profile is None:
        logger.info("%s: no curvature, skipping", session_id[:12])
        return

    try:
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            friction_circle=None,
            vehicle_params=None,
            data_quality_rpt=None,
        )
    except Exception:
        logger.error("%s: theoretical computation failed", session_id[:12], exc_info=True)
        return

    if result is None:
        logger.info("%s: theoretical returned None", session_id[:12])
        return

    theo_lap, sim_method, sim_result, corner_coaching, delta_map, session_scalars, _ = result

    # Build summary dict for persistence
    summary = {
        "theoretical_lap": theo_lap,
        "theoretical_metrics": {
            "simulation_method": sim_method,
            "best_s": float(theo_lap["Distance (m)"].iloc[-1] / theo_lap["Speed (m/s)"].mean()) if theo_lap is not None else None,
        },
        "corner_coaching": corner_coaching,
        "delta_map": delta_map,
        "session_scalars": session_scalars,
        "lap_times": [],
        "resampled_laps": resampled_laps,
    }

    # Delete old and re-insert
    cur.execute("DELETE FROM theoretical_data WHERE session_id = %s", (session_id,))

    from telemetry_tool.web.repos.theoretical_repo import insert_theoretical_data
    insert_theoretical_data(conn, session_id, summary)

    logger.info(
        "%s: reprocessed — scalars mu=%.3f p=%.3f b=%.3f",
        session_id[:12],
        session_scalars.get("mu", 0) if isinstance(session_scalars, dict) else getattr(session_scalars, "mu_session", 0),
        session_scalars.get("p", 0) if isinstance(session_scalars, dict) else getattr(session_scalars, "p_session", 0),
        session_scalars.get("b", 0) if isinstance(session_scalars, dict) else getattr(session_scalars, "b_session", 0),
    )


def _lap_time(df):
    d = df["Distance (m)"].values
    s = df["Speed (m/s)"].values
    t = 0.0
    for i in range(len(d) - 1):
        v = (s[i] + s[i + 1]) / 2
        if v > 0.5:
            t += abs(d[i + 1] - d[i]) / v
    return t if t > 0 else float("inf")


def _curvature_from_gps(df):
    """Compute curvature from lat/lon if available."""
    import numpy as np
    if "Latitude (deg)" not in df.columns or "Longitude (deg)" not in df.columns:
        return None
    lat = np.radians(df["Latitude (deg)"].values)
    lon = np.radians(df["Longitude (deg)"].values)
    R = 6371000
    x = R * lon * np.cos(np.mean(lat))
    y = R * lat
    dist = df["Distance (m)"].values

    n = len(x)
    kappa = np.zeros(n)
    for i in range(1, n - 1):
        ds = dist[i + 1] - dist[i - 1]
        if ds > 0.1:
            dx = x[i + 1] - 2 * x[i] + x[i - 1]
            dy = y[i + 1] - 2 * y[i] + y[i - 1]
            kappa[i] = 2 * np.sqrt(dx**2 + dy**2) / (ds**2)

    import pandas as pd
    return pd.DataFrame({"Distance (m)": dist, "curvature_1pm": kappa})


if __name__ == "__main__":
    main()
