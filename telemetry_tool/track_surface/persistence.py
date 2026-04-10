"""
track_surface/persistence.py
-----------------------------
Aggregate track surface model -- persistent per-meter physics properties
built incrementally from session grip maps.

Each time a session is processed, its grip_map output is merged into the
track_surfaces table via online weighted averaging.  Over many sessions
the aggregate converges on the true physical grip ceiling at each meter.

Functions
---------
upsert_session_grip : Merge one session's grip_map into the aggregate.
get_track_surface   : Read the aggregate surface for API responses.
get_aggregate_grip  : Build a GripMap-compatible object from aggregate data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AggregateGrip:
    """GripMap-compatible view of the aggregate track surface.

    Has the same ``mu_at()`` interface as grip_map.GripMap so it can be
    used as a drop-in replacement in the theoretical solver.
    """
    distance_bins: np.ndarray
    mu_p95: np.ndarray
    mu_mean: np.ndarray
    mu_lon_accel: np.ndarray
    mu_lon_brake: np.ndarray
    session_count: int
    track_id: str
    is_global_fallback: bool = False

    def mu_at(self, distance: float, percentile: str = "p95") -> float:
        """Interpolate mu at arbitrary distance -- same API as GripMap."""
        if len(self.distance_bins) == 0:
            return 1.0
        arr = self.mu_p95 if percentile == "p95" else self.mu_mean
        d = max(self.distance_bins[0], min(self.distance_bins[-1], distance))
        return float(np.interp(d, self.distance_bins, arr))

    def to_dict(self) -> dict:
        return {
            "distance_bins": self.distance_bins.tolist(),
            "mu_p95": self.mu_p95.tolist(),
            "mu_mean": self.mu_mean.tolist(),
            "mu_lon_accel": self.mu_lon_accel.tolist(),
            "mu_lon_brake": self.mu_lon_brake.tolist(),
            "session_count": self.session_count,
            "track_id": self.track_id,
            "bin_count": len(self.distance_bins),
        }


# -- Upsert (write path) ----------------------------------------------------


def upsert_session_grip(
    conn: Any,
    track_id: str,
    grip_map: Any,
    friction_envelope: Any = None,
    *,
    workspace_id: int | None = None,
    vehicle_class: str = "car",
    condition: str = "dry",
) -> int:
    """Merge a session's grip_map into the aggregate track surface.

    Uses online weighted averaging: each bin's aggregate is updated
    incrementally without needing to re-scan historical sessions.

    Parameters
    ----------
    conn : database connection (PG via PgConnectionWrapper)
    track_id : which track this data belongs to
    grip_map : GripMap from grip_map.py (must have bin_stats)
    friction_envelope : optional FrictionEnvelope for longitudinal data
    workspace_id : explicit workspace_id (uses RLS default if None)
    vehicle_class : vehicle category (e.g. "car", "kart", "gt3")
    condition : track condition (e.g. "dry", "wet", "damp")

    Returns
    -------
    Number of bins upserted.
    """
    if grip_map is None or grip_map.is_global_fallback:
        logger.debug("Skipping track surface upsert -- grip_map is None or global fallback")
        return 0

    if not track_id or track_id == "unknown_track":
        logger.debug("Skipping track surface upsert -- no valid track_id")
        return 0

    if not hasattr(grip_map, "bin_stats") or not grip_map.bin_stats:
        logger.debug("Skipping track surface upsert -- no bin_stats")
        return 0

    # Build longitudinal lookup from friction_envelope if available
    lon_accel_global = None
    lon_brake_global = None
    if friction_envelope is not None and hasattr(friction_envelope, "friction_bins"):
        accels = [fb.accel_max_g for fb in friction_envelope.friction_bins
                  if fb.accel_max_g > 0 and fb.confidence > 0]
        brakes = [fb.brake_max_g for fb in friction_envelope.friction_bins
                  if fb.brake_max_g > 0 and fb.confidence > 0]
        if accels:
            lon_accel_global = float(np.median(accels))
        if brakes:
            lon_brake_global = float(np.median(brakes))

    updated = 0
    now = datetime.now(timezone.utc).isoformat()

    for stat in grip_map.bin_stats:
        if stat.confidence < 0.3 or stat.sample_count < 3:
            continue

        params = {
            "track_id": track_id,
            "distance_m": round(stat.distance_m, 1),
            "mu_lat_p95": round(stat.mu_p95, 4),
            "mu_lat_mean": round(stat.mu_mean, 4),
            "mu_lon_accel": lon_accel_global,
            "mu_lon_brake": lon_brake_global,
            "sample_count": stat.sample_count,
            "now": now,
            "vehicle_class": vehicle_class,
            "condition": condition,
        }

        # ON CONFLICT -> online weighted merge
        sql = """
            INSERT INTO track_surfaces
                (track_id, distance_m, mu_lat_p95, mu_lat_mean,
                 mu_lon_accel, mu_lon_brake,
                 sample_count, session_count, last_updated,
                 vehicle_class, condition)
            VALUES
                (%(track_id)s, %(distance_m)s, %(mu_lat_p95)s, %(mu_lat_mean)s,
                 %(mu_lon_accel)s, %(mu_lon_brake)s,
                 %(sample_count)s, 1, %(now)s,
                 %(vehicle_class)s, %(condition)s)
            ON CONFLICT (track_id, distance_m, vehicle_class, condition, workspace_id)
            DO UPDATE SET
                mu_lat_p95 = (
                    track_surfaces.mu_lat_p95 * track_surfaces.sample_count
                    + EXCLUDED.mu_lat_p95 * EXCLUDED.sample_count
                ) / NULLIF(track_surfaces.sample_count + EXCLUDED.sample_count, 0),
                mu_lat_mean = (
                    track_surfaces.mu_lat_mean * track_surfaces.sample_count
                    + EXCLUDED.mu_lat_mean * EXCLUDED.sample_count
                ) / NULLIF(track_surfaces.sample_count + EXCLUDED.sample_count, 0),
                mu_lon_accel = COALESCE(
                    (track_surfaces.mu_lon_accel * track_surfaces.session_count
                     + EXCLUDED.mu_lon_accel)
                    / NULLIF(track_surfaces.session_count + 1, 0),
                    EXCLUDED.mu_lon_accel,
                    track_surfaces.mu_lon_accel
                ),
                mu_lon_brake = COALESCE(
                    (track_surfaces.mu_lon_brake * track_surfaces.session_count
                     + EXCLUDED.mu_lon_brake)
                    / NULLIF(track_surfaces.session_count + 1, 0),
                    EXCLUDED.mu_lon_brake,
                    track_surfaces.mu_lon_brake
                ),
                sample_count = track_surfaces.sample_count + EXCLUDED.sample_count,
                session_count = track_surfaces.session_count + 1,
                last_updated = EXCLUDED.last_updated
        """

        try:
            conn.execute(sql, params)
            updated += 1
        except Exception as exc:
            logger.warning("Track surface upsert failed for d=%.1f: %s",
                           stat.distance_m, exc)

    if updated > 0:
        logger.info(
            "Track surface updated: track=%s, bins=%d/%d, sessions+1",
            track_id, updated, len(grip_map.bin_stats),
        )

    return updated


def upsert_global_grip(
    conn: Any,
    track_id: str,
    grip_map: Any,
    friction_envelope: Any = None,
    *,
    vehicle_class: str = "car",
    condition: str = "dry",
) -> int:
    """Merge a session's grip_map into the global (cross-workspace) surface.

    Same logic as ``upsert_session_grip`` but targets ``track_surfaces_global``
    with conflict key ``(track_id, distance_m)`` -- no workspace_id.

    Parameters
    ----------
    conn : database connection (PG via PgConnectionWrapper)
    track_id : which track this data belongs to
    grip_map : GripMap from grip_map.py (must have bin_stats)
    friction_envelope : optional FrictionEnvelope for longitudinal data

    Returns
    -------
    Number of bins upserted.
    """
    if grip_map is None or grip_map.is_global_fallback:
        logger.debug("Skipping global track surface upsert -- grip_map is None or global fallback")
        return 0

    if not track_id or track_id == "unknown_track":
        logger.debug("Skipping global track surface upsert -- no valid track_id")
        return 0

    if not hasattr(grip_map, "bin_stats") or not grip_map.bin_stats:
        logger.debug("Skipping global track surface upsert -- no bin_stats")
        return 0

    # Build longitudinal lookup from friction_envelope if available
    lon_accel_global = None
    lon_brake_global = None
    if friction_envelope is not None and hasattr(friction_envelope, "friction_bins"):
        accels = [fb.accel_max_g for fb in friction_envelope.friction_bins
                  if fb.accel_max_g > 0 and fb.confidence > 0]
        brakes = [fb.brake_max_g for fb in friction_envelope.friction_bins
                  if fb.brake_max_g > 0 and fb.confidence > 0]
        if accels:
            lon_accel_global = float(np.median(accels))
        if brakes:
            lon_brake_global = float(np.median(brakes))

    updated = 0
    now = datetime.now(timezone.utc).isoformat()

    for stat in grip_map.bin_stats:
        if stat.confidence < 0.3 or stat.sample_count < 3:
            continue

        params = {
            "track_id": track_id,
            "distance_m": round(stat.distance_m, 1),
            "mu_lat_p95": round(stat.mu_p95, 4),
            "mu_lat_mean": round(stat.mu_mean, 4),
            "mu_lon_accel": lon_accel_global,
            "mu_lon_brake": lon_brake_global,
            "sample_count": stat.sample_count,
            "now": now,
            "vehicle_class": vehicle_class,
            "condition": condition,
        }

        sql = """
            INSERT INTO track_surfaces_global
                (track_id, distance_m, mu_lat_p95, mu_lat_mean,
                 mu_lon_accel, mu_lon_brake,
                 sample_count, session_count, last_updated,
                 vehicle_class, condition)
            VALUES
                (%(track_id)s, %(distance_m)s, %(mu_lat_p95)s, %(mu_lat_mean)s,
                 %(mu_lon_accel)s, %(mu_lon_brake)s,
                 %(sample_count)s, 1, %(now)s,
                 %(vehicle_class)s, %(condition)s)
            ON CONFLICT (track_id, distance_m, vehicle_class, condition)
            DO UPDATE SET
                mu_lat_p95 = (
                    track_surfaces_global.mu_lat_p95 * track_surfaces_global.sample_count
                    + EXCLUDED.mu_lat_p95 * EXCLUDED.sample_count
                ) / NULLIF(track_surfaces_global.sample_count + EXCLUDED.sample_count, 0),
                mu_lat_mean = (
                    track_surfaces_global.mu_lat_mean * track_surfaces_global.sample_count
                    + EXCLUDED.mu_lat_mean * EXCLUDED.sample_count
                ) / NULLIF(track_surfaces_global.sample_count + EXCLUDED.sample_count, 0),
                mu_lon_accel = COALESCE(
                    (track_surfaces_global.mu_lon_accel * track_surfaces_global.session_count
                     + EXCLUDED.mu_lon_accel)
                    / NULLIF(track_surfaces_global.session_count + 1, 0),
                    EXCLUDED.mu_lon_accel,
                    track_surfaces_global.mu_lon_accel
                ),
                mu_lon_brake = COALESCE(
                    (track_surfaces_global.mu_lon_brake * track_surfaces_global.session_count
                     + EXCLUDED.mu_lon_brake)
                    / NULLIF(track_surfaces_global.session_count + 1, 0),
                    EXCLUDED.mu_lon_brake,
                    track_surfaces_global.mu_lon_brake
                ),
                sample_count = track_surfaces_global.sample_count + EXCLUDED.sample_count,
                session_count = track_surfaces_global.session_count + 1,
                last_updated = EXCLUDED.last_updated
        """

        try:
            conn.execute(sql, params)
            updated += 1
        except Exception as exc:
            logger.warning("Global track surface upsert failed for d=%.1f: %s",
                           stat.distance_m, exc)

    if updated > 0:
        logger.info(
            "Global track surface updated: track=%s, bins=%d/%d, sessions+1",
            track_id, updated, len(grip_map.bin_stats),
        )

    return updated


# -- Read path ---------------------------------------------------------------


def get_track_surface(
    conn: Any,
    track_id: str,
    *,
    vehicle_class: str = "car",
    condition: str = "dry",
) -> dict | None:
    """Read the aggregate track surface for an API response.

    Returns a dict suitable for JSON serialization, or None if no data.
    RLS handles workspace filtering automatically.
    """
    sql = """
        SELECT distance_m, mu_lat_p95, mu_lat_mean,
               mu_lon_accel, mu_lon_brake,
               elevation_m, lateral_scatter_m,
               sample_count, session_count, last_updated
        FROM track_surfaces
        WHERE track_id = %(track_id)s
          AND vehicle_class = %(vehicle_class)s
          AND condition = %(condition)s
        ORDER BY distance_m
    """
    try:
        rows = conn.execute(sql, {
            "track_id": track_id,
            "vehicle_class": vehicle_class,
            "condition": condition,
        }).fetchall()
    except Exception:
        return None

    if not rows:
        return None

    bins = []
    for r in rows:
        bins.append({
            "distance_m": r[0],
            "mu_lat_p95": r[1],
            "mu_lat_mean": r[2],
            "mu_lon_accel": r[3],
            "mu_lon_brake": r[4],
            "elevation_m": r[5],
            "lateral_scatter_m": r[6],
            "sample_count": r[7],
            "session_count": r[8],
        })

    total_sessions = max((b["session_count"] for b in bins), default=0)
    total_samples = sum(b["sample_count"] for b in bins)

    return {
        "track_id": track_id,
        "bins": bins,
        "bin_count": len(bins),
        "total_sessions": total_sessions,
        "total_samples": total_samples,
        "last_updated": str(rows[-1][9]) if rows else None,
    }


def get_aggregate_grip(
    conn: Any,
    track_id: str,
    *,
    vehicle_class: str = "car",
    condition: str = "dry",
) -> AggregateGrip | None:
    """Build a GripMap-compatible object from the aggregate surface.

    Returns an AggregateGrip that has the same ``mu_at()`` interface
    as grip_map.GripMap, so it can be passed to the theoretical solver.
    """
    sql = """
        SELECT distance_m, mu_lat_p95, mu_lat_mean,
               mu_lon_accel, mu_lon_brake, session_count
        FROM track_surfaces
        WHERE track_id = %(track_id)s
          AND vehicle_class = %(vehicle_class)s
          AND condition = %(condition)s
        ORDER BY distance_m
    """
    try:
        rows = conn.execute(sql, {
            "track_id": track_id,
            "vehicle_class": vehicle_class,
            "condition": condition,
        }).fetchall()
    except Exception:
        return None

    if not rows or len(rows) < 5:
        return None

    distance = np.array([r[0] for r in rows])
    mu_p95 = np.array([r[1] for r in rows])
    mu_mean = np.array([r[2] for r in rows])
    mu_lon_accel = np.array([r[3] if r[3] is not None else 0.0 for r in rows])
    mu_lon_brake = np.array([r[4] if r[4] is not None else 0.0 for r in rows])
    session_count = max(r[5] for r in rows)

    return AggregateGrip(
        distance_bins=distance,
        mu_p95=mu_p95,
        mu_mean=mu_mean,
        mu_lon_accel=mu_lon_accel,
        mu_lon_brake=mu_lon_brake,
        session_count=session_count,
        track_id=track_id,
    )


def get_global_aggregate_grip(
    conn: Any,
    track_id: str,
    *,
    vehicle_class: str = "car",
    condition: str = "dry",
) -> AggregateGrip | None:
    """Build a GripMap-compatible object from the global (cross-workspace) surface.

    Same as ``get_aggregate_grip`` but queries ``track_surfaces_global``.
    """
    sql = """
        SELECT distance_m, mu_lat_p95, mu_lat_mean,
               mu_lon_accel, mu_lon_brake, session_count
        FROM track_surfaces_global
        WHERE track_id = %(track_id)s
          AND vehicle_class = %(vehicle_class)s
          AND condition = %(condition)s
        ORDER BY distance_m
    """
    try:
        rows = conn.execute(sql, {
            "track_id": track_id,
            "vehicle_class": vehicle_class,
            "condition": condition,
        }).fetchall()
    except Exception:
        return None

    if not rows or len(rows) < 5:
        return None

    distance = np.array([r[0] for r in rows])
    mu_p95 = np.array([r[1] for r in rows])
    mu_mean = np.array([r[2] for r in rows])
    mu_lon_accel = np.array([r[3] if r[3] is not None else 0.0 for r in rows])
    mu_lon_brake = np.array([r[4] if r[4] is not None else 0.0 for r in rows])
    session_count = max(r[5] for r in rows)

    return AggregateGrip(
        distance_bins=distance,
        mu_p95=mu_p95,
        mu_mean=mu_mean,
        mu_lon_accel=mu_lon_accel,
        mu_lon_brake=mu_lon_brake,
        session_count=session_count,
        track_id=track_id,
    )
