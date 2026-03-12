"""Track repository — track CRUD, records, sectors, start/finish, merge."""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Optional

from db import queries as Q
from web.repos._helpers import _safe_float

import logging

logger = logging.getLogger(__name__)


def upsert_track(conn: sqlite3.Connection, track: dict) -> None:
    """Insert or update a track from a fingerprint dict."""
    fp = track.get("fingerprint", {})
    bbox = fp.get("bbox", {})
    conn.execute(Q.UPSERT_TRACK, {
        "track_id":     track["track_id"],
        "track_name":   track.get("track_name", track["track_id"]),
        "lap_length_m": fp.get("lap_length_m", 0.0),
        "bbox_lat_min": bbox.get("lat_min"),
        "bbox_lat_max": bbox.get("lat_max"),
        "bbox_lon_min": bbox.get("lon_min"),
        "bbox_lon_max": bbox.get("lon_max"),
        "start_lat":    fp.get("start_lat"),
        "start_lon":    fp.get("start_lon"),
        "sample_count": fp.get("sample_count"),
        "lap_count":    fp.get("lap_count"),
        "has_joker":    bool(track.get("has_joker", False)),
        "joker_distance_delta_m": track.get("joker_distance_delta_m"),
        "joker_time_delta_s":     track.get("joker_time_delta_s"),
    })


def upsert_track_by_name(
    conn: sqlite3.Connection,
    track_name: str,
    details: Optional[dict] = None,
) -> str:
    """Find a track by name (case-insensitive) or create a minimal entry.

    Returns track_id.  When creating, ``details`` may contain
    lap_length_m to pre-populate.
    """
    import uuid
    clean = track_name.strip()
    row = conn.execute(
        "SELECT track_id FROM tracks WHERE LOWER(track_name) = LOWER(?)",
        (clean,),
    ).fetchone()
    if row:
        return row["track_id"]
    d = details or {}
    track_id = str(uuid.uuid4())[:12]
    lap_length = d.get("lap_length_m") or 0
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES (?, ?, ?)",
        (track_id, clean, lap_length),
    )
    return track_id


def get_all_tracks(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(Q.SELECT_ALL_TRACKS).fetchall()
    return [dict(r) for r in rows]


def rename_track(conn: sqlite3.Connection, track_id: str, new_name: str) -> None:
    """Rename a track in the tracks table and persist to tracks.json.

    If another track already has the same name (case-insensitive),
    merge the current track into the existing one instead of renaming.
    """
    clean_name = new_name.strip()

    # Check if another track already has this name (case-insensitive)
    existing = conn.execute(
        "SELECT track_id FROM tracks "
        "WHERE LOWER(track_name) = LOWER(?) AND track_id != ?",
        (clean_name, track_id),
    ).fetchone()

    if existing:
        # Merge: reassign sessions + children from this track to existing
        keep_id = existing["track_id"] if isinstance(existing, dict) else existing[0]
        conn.execute(
            "UPDATE sessions SET track_id = ? WHERE track_id = ?",
            (keep_id, track_id),
        )
        for child_table in (
            "track_sectors", "track_records", "track_key_corners",
            "corner_best_practices",
        ):
            try:
                conn.execute(
                    f"UPDATE {child_table} SET track_id = ? WHERE track_id = ?",
                    (keep_id, track_id),
                )
            except Exception:
                try:
                    conn.execute(
                        f"DELETE FROM {child_table} WHERE track_id = ?",
                        (track_id,),
                    )
                except Exception:
                    pass
        conn.execute("DELETE FROM tracks WHERE track_id = ?", (track_id,))
        logger.info("Renamed track %s merged into existing %s (%s)", track_id, keep_id, clean_name)
        return

    conn.execute(
        "UPDATE tracks SET track_name = :name, updated_at = datetime('now') "
        "WHERE track_id = :tid",
        {"name": clean_name, "tid": track_id},
    )
    # Persist to tracks.json so the rename survives server restarts.
    _update_tracks_json(track_id, clean_name)


def _update_tracks_json(track_id: str, new_name: str) -> None:
    """Update the track name in the file-based tracks.json."""
    try:
        from track_detection import load_track_database, save_track_database
        db = load_track_database()
        for entry in db:
            if entry.get("track_id") == track_id:
                entry["track_name"] = new_name
                break
        save_track_database(db)
    except Exception as exc:
        logger.warning("Could not update tracks.json for %s: %s", track_id, exc)


def merge_named_duplicate_tracks(conn: sqlite3.Connection) -> int:
    """Merge tracks that share the same name (case-insensitive).

    For each group of duplicates, keeps the track with the most sessions
    (ties broken by earliest created_at).  Reassigns all child rows
    from duplicates to the keeper, then deletes the duplicates.

    Returns the number of duplicate tracks merged away.
    """
    # Find groups with >1 track sharing the same lowercased name
    groups = conn.execute(
        "SELECT LOWER(track_name) AS lname, COUNT(*) AS cnt "
        "FROM tracks GROUP BY LOWER(track_name) HAVING COUNT(*) > 1"
    ).fetchall()

    if not groups:
        return 0

    merged = 0
    for g in groups:
        lname = g["lname"] if isinstance(g, dict) else g[0]

        # Get all tracks in this group, ordered by session count desc, then oldest first
        tracks = conn.execute(
            "SELECT t.track_id, t.track_name, "
            "  COUNT(s.session_id) AS sess_count "
            "FROM tracks t "
            "LEFT JOIN sessions s ON t.track_id = s.track_id AND s.deleted_at IS NULL "
            "WHERE LOWER(t.track_name) = ? "
            "GROUP BY t.track_id "
            "ORDER BY sess_count DESC, t.created_at ASC",
            (lname,),
        ).fetchall()

        if len(tracks) < 2:
            continue

        keep_id = tracks[0]["track_id"] if isinstance(tracks[0], dict) else tracks[0][0]

        for dup_row in tracks[1:]:
            dup_id = dup_row["track_id"] if isinstance(dup_row, dict) else dup_row[0]

            # Reassign sessions
            conn.execute(
                "UPDATE sessions SET track_id = ? WHERE track_id = ?",
                (keep_id, dup_id),
            )
            # Reassign child tables
            for child_table in (
                "track_sectors", "track_records", "track_key_corners",
                "corner_best_practices",
            ):
                try:
                    conn.execute(
                        f"UPDATE {child_table} SET track_id = ? WHERE track_id = ?",
                        (keep_id, dup_id),
                    )
                except Exception:
                    # Table may not exist or have unique constraint — skip
                    try:
                        conn.execute(
                            f"DELETE FROM {child_table} WHERE track_id = ?",
                            (dup_id,),
                        )
                    except Exception:
                        pass

            # Delete the duplicate track
            conn.execute("DELETE FROM tracks WHERE track_id = ?", (dup_id,))
            merged += 1
            logger.info(
                "Merged duplicate track %s into %s (name=%s)",
                dup_id, keep_id, lname,
            )

    return merged


def merge_duplicate_tracks(conn: sqlite3.Connection) -> int:
    """
    Merge duplicate 'Unknown Track' entries that share overlapping GPS.

    Groups Unknown Tracks by bbox overlap (centroid within 500m).
    For each group, keeps the first entry and reassigns all sessions
    from duplicate entries to the kept entry, then deletes duplicates.

    Returns the number of tracks merged away.
    """
    import math

    unknowns = conn.execute(
        "SELECT track_id, track_name, start_lat, start_lon, "
        "       bbox_lat_min, bbox_lat_max, bbox_lon_min, bbox_lon_max, "
        "       lap_length_m "
        "FROM tracks WHERE track_name LIKE '%nknown%' OR track_name LIKE '%unknown%' "
        "ORDER BY created_at"
    ).fetchall()
    unknowns = [dict(r) for r in unknowns]

    if len(unknowns) < 2:
        return 0

    def _haversine(lat1, lon1, lat2, lon2):
        if any(v is None for v in (lat1, lon1, lat2, lon2)):
            return float("inf")
        R = 6371000.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _centroid(t):
        """Get centroid from start coords, or fallback to bbox center."""
        lat = t.get("start_lat")
        lon = t.get("start_lon")
        if lat is not None and lon is not None:
            return lat, lon
        # Fallback to bbox centroid
        lat_min = t.get("bbox_lat_min")
        lat_max = t.get("bbox_lat_max")
        lon_min = t.get("bbox_lon_min")
        lon_max = t.get("bbox_lon_max")
        if all(v is not None for v in (lat_min, lat_max, lon_min, lon_max)):
            return (lat_min + lat_max) / 2, (lon_min + lon_max) / 2
        return None, None

    # Group by proximity (centroid within 500m) or all-null coords
    groups: list[list[dict]] = []
    assigned = set()
    null_group: list[dict] = []  # tracks with no GPS at all
    for i, t in enumerate(unknowns):
        if i in assigned:
            continue
        lat, lon = _centroid(t)
        if lat is None:
            null_group.append(t)
            assigned.add(i)
            continue
        group = [t]
        assigned.add(i)
        for j, other in enumerate(unknowns):
            if j in assigned:
                continue
            olat, olon = _centroid(other)
            if olat is None:
                continue
            dist = _haversine(lat, lon, olat, olon)
            if dist < 500:
                group.append(other)
                assigned.add(j)
        if len(group) > 1:
            groups.append(group)
    # Group all no-GPS unknowns together
    if len(null_group) > 1:
        groups.append(null_group)

    merged = 0
    for group in groups:
        keep = group[0]
        for dup in group[1:]:
            # Reassign sessions from dup -> keep
            conn.execute(
                "UPDATE sessions SET track_id = :keep WHERE track_id = :dup",
                {"keep": keep["track_id"], "dup": dup["track_id"]},
            )
            # Delete the duplicate track entry
            conn.execute(
                "DELETE FROM tracks WHERE track_id = :tid",
                {"tid": dup["track_id"]},
            )
            merged += 1

    return merged


def get_track_by_id(conn: sqlite3.Connection, track_id: str) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_TRACK_BY_ID, {"track_id": track_id}
    ).fetchone()
    return dict(row) if row else None


def sync_tracks_from_json(conn: sqlite3.Connection) -> int:
    """
    Import tracks from the file-based tracks.json into SQLite.

    Returns the number of tracks synced.
    """
    try:
        from track_detection import load_track_database
        db = load_track_database()
    except (ImportError, Exception) as exc:
        logger.debug("Could not load tracks.json: %s", exc)
        return 0

    count = 0
    for entry in db:
        upsert_track(conn, entry)
        count += 1
    conn.commit()
    logger.info("Synced %d tracks from tracks.json to SQLite.", count)
    return count


def upsert_track_record(
    conn: sqlite3.Connection,
    track_id: str,
    record_time_s: float,
    record_holder: Optional[str] = None,
    record_date: Optional[str] = None,
    vehicle_class: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    conn.execute(Q.UPSERT_TRACK_RECORD, {
        "track_id":       track_id,
        "record_time_s":  record_time_s,
        "record_holder":  record_holder,
        "record_date":    record_date,
        "vehicle_class":  vehicle_class or "default",
        "source":         source,
    })


def delete_track_record(conn: sqlite3.Connection, record_id: int) -> None:
    conn.execute(Q.DELETE_TRACK_RECORD, {"id": record_id})


def get_track_records(
    conn: sqlite3.Connection,
    track_id: str,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_TRACK_RECORDS, {"track_id": track_id}
    ).fetchall()
    return [dict(r) for r in rows]


def update_track_start_finish(
    conn: sqlite3.Connection, track_id: str, lat: float, lon: float
) -> None:
    """Update start/finish position; preserve originals on first edit."""
    row = conn.execute(
        "SELECT start_lat, start_lon, original_start_lat FROM tracks WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    if row is None:
        return
    # On first edit, save originals.
    if row["original_start_lat"] is None:
        conn.execute(
            "UPDATE tracks SET original_start_lat = start_lat, "
            "original_start_lon = start_lon WHERE track_id = ?",
            (track_id,),
        )
    conn.execute(
        "UPDATE tracks SET start_lat = ?, start_lon = ?, "
        "updated_at = datetime('now') WHERE track_id = ?",
        (lat, lon, track_id),
    )


def reset_track_start_finish(conn: sqlite3.Connection, track_id: str) -> None:
    """Reset start/finish to auto-detected originals."""
    conn.execute(
        "UPDATE tracks SET start_lat = original_start_lat, "
        "start_lon = original_start_lon WHERE track_id = ? "
        "AND original_start_lat IS NOT NULL",
        (track_id,),
    )


def get_track_sectors(conn: sqlite3.Connection, track_id: str) -> list[dict]:
    """Return sectors for a track ordered by sector_index."""
    rows = conn.execute(
        "SELECT * FROM track_sectors WHERE track_id = ? ORDER BY sector_index",
        (track_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_track_sector(
    conn: sqlite3.Connection, track_id: str, lat: float, lon: float,
    distance_m: Optional[float] = None,
) -> int:
    """Add a sector point and auto-assign next index. Returns new sector ID."""
    _row = conn.execute(
        "SELECT COALESCE(MAX(sector_index), -1) + 1 AS next_idx FROM track_sectors WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    next_idx = (_row.get("next_idx", 0) if isinstance(_row, dict) else _row[0]) if _row else 0
    label = f"S{next_idx + 1}"
    cur = conn.execute(
        "INSERT INTO track_sectors (track_id, sector_index, latitude, longitude, distance_m, label) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (track_id, next_idx, lat, lon, distance_m, label),
    )
    _row = cur.fetchone()
    if _row is None:
        return None
    return _row[0] if not isinstance(_row, dict) else _row.get("id")


def delete_track_sector(conn: sqlite3.Connection, track_id: str, sector_id: int) -> None:
    """Delete a sector and re-index remaining sectors."""
    conn.execute("DELETE FROM track_sectors WHERE id = ? AND track_id = ?", (sector_id, track_id))
    # Re-index remaining sectors.
    rows = conn.execute(
        "SELECT id FROM track_sectors WHERE track_id = ? ORDER BY sector_index",
        (track_id,),
    ).fetchall()
    for i, r in enumerate(rows):
        conn.execute(
            "UPDATE track_sectors SET sector_index = ?, label = ? WHERE id = ?",
            (i, f"S{i + 1}", r["id"]),
        )


def delete_track_cascade(conn: sqlite3.Connection, track_id: str) -> dict:
    """Delete a track and all dependent data. Returns counts of deleted rows."""
    counts = {}
    # Order matters: delete children before parent.
    for table, col in [
        ("corner_metrics", "session_id"),
        ("corner_best_practices", "track_id"),
        ("gps_traces", "session_id"),
        ("score_details", "session_id"),
        ("condition_phases", "session_id"),
        ("laps", "session_id"),
        ("data_health", "session_id"),
        ("session_tags", "session_id"),
        ("session_sectors", "session_id"),
        ("theoretical_data", "session_id"),
        ("reference_lines", "session_id"),
        ("stint_analysis", "session_id"),
        ("session_annotations", "session_id"),
        ("session_weather", "session_id"),
        ("vehicle_setups", "session_id"),
        ("what_if_scenarios", "session_id"),
        ("driving_style_features", "session_id"),
        ("driver_progression", "session_id"),
        ("weekend_sessions", "session_id"),
        ("condition_markers", "session_id"),
    ]:
        if col == "track_id":
            c = conn.execute(f"DELETE FROM {table} WHERE track_id = ?", (track_id,))
        else:
            c = conn.execute(
                f"DELETE FROM {table} WHERE {col} IN "
                f"(SELECT session_id FROM sessions WHERE track_id = ?)",
                (track_id,),
            )
        counts[table] = c.rowcount

    # Sessions themselves.
    c = conn.execute("DELETE FROM sessions WHERE track_id = ?", (track_id,))
    counts["sessions"] = c.rowcount

    # Track-level tables.
    c = conn.execute("DELETE FROM track_key_corners WHERE track_id = ?", (track_id,))
    counts["track_key_corners"] = c.rowcount
    c = conn.execute("DELETE FROM track_sectors WHERE track_id = ?", (track_id,))
    counts["track_sectors"] = c.rowcount
    c = conn.execute("DELETE FROM track_records WHERE track_id = ?", (track_id,))
    counts["track_records"] = c.rowcount

    # The track itself.
    conn.execute("DELETE FROM tracks WHERE track_id = ?", (track_id,))
    counts["tracks"] = 1

    return counts


def create_track_from_predefined(
    conn: sqlite3.Connection, predefined_track_id: int, custom_name: str | None = None,
) -> str:
    """Create a tracks entry linked to a predefined track. Returns track_id."""
    import uuid
    ref = conn.execute(
        "SELECT * FROM predefined_tracks WHERE predefined_track_id = ?",
        (predefined_track_id,),
    ).fetchone()
    if ref is None:
        raise ValueError("Predefined track not found")
    ref = dict(ref)

    track_id = str(uuid.uuid4())[:12]
    name = custom_name or f"{ref['track_name']} — {ref['layout_name'] or 'Default'}"
    length = ref.get("layout_length_m")

    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m, predefined_track_id) "
        "VALUES (?, ?, ?, ?)",
        (track_id, name, length or 0, predefined_track_id),
    )
    return track_id


def auto_set_track_reference(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[str]:
    """Auto-assign this session as the track's dry/wet reference line.

    Called after a reference line is successfully persisted. If the track
    does not already have a reference for this session's condition
    (dry or wet), adopt this session's reference line.

    Returns the condition column set ('dry'/'wet') or None if no change.
    """
    row = conn.execute(
        "SELECT s.track_id, s.track_state "
        "FROM sessions s WHERE s.session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return None

    track_id = row["track_id"]
    track_state = (row["track_state"] or "dry").lower().strip()

    if not track_id:
        return None

    # Map condition to column: 'dry' for dry/damp, 'wet' for wet/greasy/mixed
    if track_state in ("wet", "greasy", "mixed"):
        col = "wet_ref_session_id"
        condition = "wet"
    else:
        col = "dry_ref_session_id"
        condition = "dry"

    # Check if the track already has a reference for this condition.
    track = conn.execute(
        f"SELECT {col} FROM tracks WHERE track_id = :tid",
        {"tid": track_id},
    ).fetchone()
    if track is None:
        return None

    if track[col] is not None:
        return None  # Already has a reference for this condition

    # Set this session as the track's condition reference.
    conn.execute(
        f"UPDATE tracks SET {col} = :sid, updated_at = datetime('now') "
        "WHERE track_id = :tid",
        {"sid": session_id, "tid": track_id},
    )
    return condition


def save_session_corners_to_track(
    conn: sqlite3.Connection,
    session_id: str,
    track_id: str,
) -> int:
    """Persist detected corner positions from a session into track_key_corners.

    Uses corner_metrics for corner IDs, GPS trace + brake/throttle distances
    to estimate apex positions.  Replaces any existing corners for this track.
    Returns number of corners saved.
    """
    import bisect

    corner_rows = conn.execute(
        "SELECT corner_id, AVG(brake_point_m) AS avg_brake_m, "
        "AVG(throttle_onset_m) AS avg_throttle_m "
        "FROM corner_metrics WHERE session_id = ? "
        "GROUP BY corner_id ORDER BY corner_id",
        (session_id,),
    ).fetchall()
    if not corner_rows:
        return 0

    best = conn.execute(
        "SELECT lap_number FROM laps WHERE session_id = ? AND is_best = 1 LIMIT 1",
        (session_id,),
    ).fetchone()
    if not best:
        return 0

    gps = conn.execute(
        "SELECT latitude, longitude, distance_m FROM gps_traces "
        "WHERE session_id = ? AND lap_number = ? ORDER BY elapsed_s",
        (session_id, best["lap_number"]),
    ).fetchall()
    if not gps:
        return 0

    dists = [float(g["distance_m"] or 0) for g in gps]
    lats = [float(g["latitude"] or 0) for g in gps]
    lons = [float(g["longitude"] or 0) for g in gps]

    if not dists:
        return 0

    conn.execute("DELETE FROM track_key_corners WHERE track_id = ?", (track_id,))

    count = 0
    for row in corner_rows:
        cid = row["corner_id"]
        brake_m = _safe_float(row["avg_brake_m"])
        throttle_m = _safe_float(row["avg_throttle_m"])

        if brake_m is not None and throttle_m is not None:
            dist_m = (brake_m + throttle_m) / 2
        elif brake_m is not None:
            dist_m = brake_m
        else:
            continue

        idx = bisect.bisect_left(dists, dist_m)
        idx = min(idx, len(dists) - 1)

        conn.execute(
            "INSERT OR REPLACE INTO track_key_corners "
            "(track_id, corner_id, label, lat, lon, dist_m) VALUES (?, ?, ?, ?, ?, ?)",
            (track_id, cid, f"T{cid}", lats[idx], lons[idx], dist_m),
        )
        count += 1

    return count


def populate_track_from_session_gps(
    conn: sqlite3.Connection,
    session_id: str,
    track_id: str,
) -> None:
    """Auto-populate a track's fingerprint from session GPS data.

    Only fills empty fields (lap_length_m == 0) — won't overwrite existing.
    """
    track = get_track_by_id(conn, track_id)
    if not track:
        return
    if track.get("lap_length_m") and float(track["lap_length_m"]) > 0:
        return

    best = conn.execute(
        "SELECT line_length_m FROM laps WHERE session_id = ? AND is_best = 1 LIMIT 1",
        (session_id,),
    ).fetchone()
    lap_length = _safe_float(best["line_length_m"]) if best else 0

    gps_agg = conn.execute(
        "SELECT MIN(latitude) AS lat_min, MAX(latitude) AS lat_max, "
        "MIN(longitude) AS lon_min, MAX(longitude) AS lon_max "
        "FROM gps_traces WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    start_pt = conn.execute(
        "SELECT latitude, longitude FROM gps_traces "
        "WHERE session_id = ? ORDER BY elapsed_s LIMIT 1",
        (session_id,),
    ).fetchone()

    sets: list[str] = []
    vals: list[Any] = []

    if lap_length and lap_length > 0:
        sets.append("lap_length_m = ?")
        vals.append(lap_length)

    if gps_agg and gps_agg["lat_min"] is not None:
        sets.extend([
            "bbox_lat_min = ?", "bbox_lat_max = ?",
            "bbox_lon_min = ?", "bbox_lon_max = ?",
        ])
        vals.extend([
            gps_agg["lat_min"], gps_agg["lat_max"],
            gps_agg["lon_min"], gps_agg["lon_max"],
        ])

    if start_pt and start_pt["latitude"] is not None:
        sets.extend(["start_lat = ?", "start_lon = ?"])
        vals.extend([start_pt["latitude"], start_pt["longitude"]])

    if sets:
        vals.append(track_id)
        conn.execute(
            f"UPDATE tracks SET {', '.join(sets)}, updated_at = datetime('now') "
            "WHERE track_id = ?",
            vals,
        )


def check_track_gps_match(
    conn: sqlite3.Connection,
    session_id: str,
    track_id: str,
) -> dict:
    """Compare session GPS fingerprint vs stored track fingerprint.

    Returns dict with match status and detail fields.
    """
    track = get_track_by_id(conn, track_id)
    if not track:
        return {"match": True, "reason": "no_track_data"}

    track_length = _safe_float(track.get("lap_length_m")) or 0

    best = conn.execute(
        "SELECT line_length_m FROM laps WHERE session_id = ? AND is_best = 1 LIMIT 1",
        (session_id,),
    ).fetchone()
    session_length = _safe_float(best["line_length_m"]) if best else 0

    # Track has no fingerprint yet — can't compare
    if track_length == 0:
        return {"match": True, "reason": "new_track"}

    # Lap length comparison: 6% tolerance (same as track_detection.py)
    length_ok = True
    if track_length > 0 and session_length and session_length > 0:
        ratio = session_length / track_length
        length_ok = 0.94 <= ratio <= 1.06

    # Bbox IoU comparison
    bbox_ok = True
    t_bb = {
        "lat_min": _safe_float(track.get("bbox_lat_min")),
        "lat_max": _safe_float(track.get("bbox_lat_max")),
        "lon_min": _safe_float(track.get("bbox_lon_min")),
        "lon_max": _safe_float(track.get("bbox_lon_max")),
    }

    if all(v is not None for v in t_bb.values()):
        gps_agg = conn.execute(
            "SELECT MIN(latitude) AS lat_min, MAX(latitude) AS lat_max, "
            "MIN(longitude) AS lon_min, MAX(longitude) AS lon_max "
            "FROM gps_traces WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if gps_agg and gps_agg["lat_min"] is not None:
            o_lat = max(0, min(t_bb["lat_max"], gps_agg["lat_max"])
                        - max(t_bb["lat_min"], gps_agg["lat_min"]))
            o_lon = max(0, min(t_bb["lon_max"], gps_agg["lon_max"])
                        - max(t_bb["lon_min"], gps_agg["lon_min"]))
            overlap = o_lat * o_lon

            t_area = ((t_bb["lat_max"] - t_bb["lat_min"])
                      * (t_bb["lon_max"] - t_bb["lon_min"]))
            s_area = ((gps_agg["lat_max"] - gps_agg["lat_min"])
                      * (gps_agg["lon_max"] - gps_agg["lon_min"]))
            union = t_area + s_area - overlap
            iou = overlap / union if union > 0 else 0
            bbox_ok = iou >= 0.5

    return {
        "match": length_ok and bbox_ok,
        "track_length_m": round(track_length, 1),
        "session_length_m": round(session_length, 1) if session_length else None,
        "length_match": length_ok,
        "bbox_match": bbox_ok,
    }
