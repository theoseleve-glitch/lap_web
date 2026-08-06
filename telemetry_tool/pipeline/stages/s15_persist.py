"""
Stage 15 — Persist to Database
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Save pipeline results to SQLite for the desktop/CLI mode.
Skipped when ``USE_PG=1`` (PostgreSQL mode — Celery handles persistence).
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from pipeline.helpers import lazy_import

logger = logging.getLogger(__name__)


def run_persist_to_db(
    summary: dict[str, Any],
    meta: dict[str, Any],
    track_id: str,
    *,
    score_result: Optional[dict[str, Any]] = None,
    driving_style_result: Optional[dict[str, Any]] = None,
    weather_timeline: Optional[pd.DataFrame] = None,
    driver_tag: str = "",
    force_persist: bool = False,
) -> Optional[str]:
    """Persist results to SQLite DB.

    Returns the session_id string, or ``None`` if persistence was
    skipped or failed.

    When ``USE_PG=1`` this function returns immediately — PostgreSQL
    persistence is handled by the Celery finalize task.
    Pass ``force_persist=True`` to override this skip (e.g. for endurance stints).
    """
    # Skip when running under PostgreSQL (unless forced)
    if os.environ.get("USE_PG", "0") == "1" and not force_persist:
        logger.info("Skipping SQLite persist (USE_PG=1; Celery handles DB persistence).")
        return None

    try:
        from web.db import get_db_connection, init_db, set_default_db_path
        from web.models import (
            insert_condition_markers,
            insert_condition_phases,
            insert_driver_progression,
            insert_driving_style_features,
            insert_gps_traces,
            insert_laps,
            insert_reference_line,
            insert_score_details,
            insert_theoretical_data,
            upsert_driver,
            upsert_driver_profile,
            upsert_session,
            upsert_track,
        )
    except ImportError:
        logger.debug("Web layer not available; skipping DB persistence.")
        return None

    use_pg = os.environ.get("USE_PG", "0") == "1"

    if use_pg:
        # PG mode with force_persist: schema managed by Alembic, skip SQLite init.
        conn = get_db_connection()
        wid = meta.get("workspace_id")
        if wid:
            conn.execute(
                "SET LOCAL app.current_workspace_id = :wid",
                {"wid": str(wid)},
            )
    else:
        try:
            from path_manager import get_db_path
            db_path = get_db_path()
        except (ImportError, AttributeError):
            db_path = Path(__file__).resolve().parent.parent.parent / "telemetry.db"

        set_default_db_path(db_path)
        init_db(db_path)
        conn = get_db_connection()

    theo_metrics = summary.get("theoretical_metrics", {})

    # Atomic persist — explicit try/commit/rollback (works for both
    # sqlite3.Connection and PgConnectionWrapper).
    try:
        driver_name = meta.get("driver_name", "Driver_1")
        driver_id = upsert_driver(conn, driver_name)

        # Ensure track exists in DB (FK constraint)
        _upsert_track_record(conn, summary, track_id, upsert_track)

        session_id = upsert_session(conn, summary, driver_id)
        insert_laps(conn, session_id, summary)
        insert_gps_traces(conn, session_id, summary)
        insert_score_details(conn, session_id, summary)
        insert_condition_phases(conn, session_id, summary)

        # Theoretical data + reference line
        _persist_theoretical(conn, session_id, summary, insert_theoretical_data, insert_reference_line)

        # Per-lap corner metrics
        _persist_corner_metrics(conn, session_id, summary)

        # Driving events (Phase 2 of driving-pattern-recognition, Task 10)
        _persist_driving_events(conn, session_id, summary)

        # Manual condition markers
        manual_cc = meta.get("manual_condition_changes")
        if manual_cc:
            insert_condition_markers(conn, session_id, manual_cc)

        # Historical enrichment
        _enrich_historical(conn, session_id, track_id, driver_id, score_result, summary)

        # Driving style features
        if driving_style_result:
            try:
                insert_driving_style_features(
                    conn, driver_id, session_id, driving_style_result,
                )
                logger.info(
                    "Persisted driving style: %s",
                    driving_style_result.get("style_label"),
                )
            except Exception as exc:
                logger.warning("Driving style persistence skipped: %s", exc)

        # Driver progression snapshot
        _persist_driver_progression(
            conn, driver_id, session_id, summary, theo_metrics,
            driving_style_result, score_result,
            insert_driver_progression, upsert_driver_profile,
        )

        # Weather timeline
        _persist_weather(conn, session_id, weather_timeline)

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if use_pg:
            try:
                conn.close()
            except Exception:
                pass

    logger.info(
        "Persisted session %s to %s.", session_id,
        "PostgreSQL" if use_pg else "SQLite",
    )
    return session_id


# ── Internal helpers ───────────────────────────────────────────────────


def _upsert_track_record(conn: Any, summary: dict, track_id: str, upsert_track: Any) -> None:
    """Ensure track record exists before session insert."""
    if not track_id:
        return

    track_entry = None
    try:
        track_det = lazy_import("track_detection")
        if track_det is not None:
            for te in track_det.load_track_database():
                if te.get("track_id") == track_id:
                    track_entry = te
                    break
    except Exception:
        pass

    if track_entry is None:
        tm = summary.get("track_match")
        track_entry = {
            "track_id": track_id,
            "track_name": (tm or {}).get("track_name", track_id),
            "fingerprint": {
                "lap_length_m": (tm or {}).get("lap_length_m", 0.0),
                "bbox": {},
                "start_lat": None,
                "start_lon": None,
                "sample_count": None,
                "lap_count": None,
            },
        }
    upsert_track(conn, track_entry)


def _persist_theoretical(
    conn: Any,
    session_id: str,
    summary: dict,
    insert_theoretical_data: Any,
    insert_reference_line: Any,
) -> None:
    """Persist theoretical data and reference line."""
    try:
        insert_theoretical_data(conn, session_id, summary)
        logger.info("Persisted theoretical data for session %s.", session_id)
    except Exception as exc:
        logger.warning("Theoretical data persistence FAILED: %s", exc, exc_info=True)

    try:
        insert_reference_line(conn, session_id, summary)
        logger.info("Persisted reference line for session %s.", session_id)
        # Auto-set track condition reference if first for this condition
        try:
            from web.models import auto_set_track_reference
            cond = auto_set_track_reference(conn, session_id)
            if cond:
                logger.info(
                    "Set %s reference line for track from session %s.", cond, session_id,
                )
        except Exception as exc:
            logger.debug("Auto-set track reference skipped: %s", exc)
    except Exception as exc:
        logger.warning("Reference line persistence FAILED: %s", exc, exc_info=True)


# ── SAVEPOINT-GUARDED CHILD WRITES ───────────────────────────────────────
#
# `run_persist_to_db` is ONE transaction: a single `conn.commit()` at the end
# and a single `conn.rollback()` in its handler, and psycopg2 does not
# autocommit (`web/db_pg.py`). So ANY child write that fails and is then
# SWALLOWED leaves the PostgreSQL transaction in the aborted state, and the
# later `COMMIT` in an aborted block is a silent `ROLLBACK` -- the entire
# session disappears behind one WARNING line naming a single child table.
#
# BOTH of this branch's migrations open that window during their own deploy:
#
#   085  adds four columns that `db/queries.py`'s INSERT_CORNER_METRIC names
#        unconditionally -> UndefinedColumn in `_persist_corner_metrics`
#   086  adds a table that INSERT_DRIVING_EVENT names unconditionally
#        -> UndefinedTable in `_persist_driving_events`
#
# Both were PROVEN on a real PostgreSQL 16 with the shipped code: with 085's
# columns dropped, `run_persist_to_db` left sessions / laps / gps_traces /
# score_details / condition_phases / driving_events ALL AT ZERO.
#
# One helper rather than two hand-rolled copies, deliberately: the guard has
# a non-obvious branch (see `sp_taken` below) that a third writer copying the
# shape by eye would very likely get wrong, and getting it wrong is not a
# degraded write -- it is the whole session.
_SAVEPOINT_CORNER_METRICS = "sp_corner_metrics"
_SAVEPOINT_DRIVING_EVENTS = "sp_driving_events"


def _write_in_savepoint(conn: Any, savepoint: str, label: str, write: Any) -> Any:
    """Run ``write()`` inside a SAVEPOINT so a failure cannot poison the
    outer transaction. Returns ``write()``'s value, or None if it failed and
    was contained.

    IF THE SAVEPOINT CANNOT BE TAKEN, THE EXCEPTION IS RE-RAISED RATHER THAN
    SWALLOWED. That branch is the point of the helper and it is the opposite
    of what looks safe: without isolation, swallowing is the DANGEROUS
    choice, because the caller then commits an aborted transaction and
    reports success. A loud failure that rolls the session back is strictly
    better than a silent one that discards it. (Verified on real PG: this is
    what turned a silent total loss into an `InFailedSqlTransaction` the
    operator can see.)

    ``savepoint`` is always a module-level constant, never caller data.
    """
    sp_taken = False
    try:
        conn.execute(f"SAVEPOINT {savepoint}")
        sp_taken = True
    except Exception as exc:
        logger.warning(
            "%s: could not open a savepoint (%s); a write failure will now "
            "propagate rather than be swallowed, because without isolation a "
            "swallowed failure discards the whole session.", label, exc,
        )

    try:
        result = write()
        if sp_taken:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return result
    except Exception as exc:
        if not sp_taken:
            # No isolation: do not pretend this was contained.
            raise
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            logger.error(
                "%s: rollback to savepoint FAILED after %s — the outer "
                "transaction may be aborted and this session's other data "
                "lost at COMMIT.", label, exc, exc_info=True,
            )
            raise
        # exc_info=True (unlike endurance_tasks.py's bare except at the same
        # call site) so a skipped write is diagnosable rather than merely
        # survivable.
        logger.warning(
            "%s persistence skipped (rolled back to savepoint, the rest of "
            "the session is unaffected): %s", label, exc, exc_info=True,
        )
        return None


def _persist_corner_metrics(conn: Any, session_id: str, summary: dict) -> None:
    """Persist per-lap corner metrics, contained by a SAVEPOINT.

    This guard used to be a bare swallow, and it is reachable in THIS
    branch's own deploy window: migration 085 adds four columns that
    `INSERT_CORNER_METRIC` names unconditionally, so code serving before the
    migration raises UndefinedColumn here. Proven on real PostgreSQL 16 with
    085's columns dropped: `run_persist_to_db` returned None and left every
    child table at ZERO rows.

    See `_write_in_savepoint` and
    `docs/runbooks/driving-events-085-086-deploy.md` §1b.
    """
    def _write():
        from web.models import insert_corner_metrics
        return insert_corner_metrics(conn, session_id, summary)

    cm_count = _write_in_savepoint(
        conn, _SAVEPOINT_CORNER_METRICS, "Corner metrics", _write)
    if cm_count:
        logger.info(
            "Persisted %d corner metrics for session %s.", cm_count, session_id,
        )


def _persist_driving_events(conn: Any, session_id: str, summary: dict) -> None:
    """Persist Phase 2 driving events (over_slowing, late_throttle,
    re_braking, envelope_under_use) — see s10d3_driving_events.py.

    Contained by a SAVEPOINT for the same reason as
    `_persist_corner_metrics` above, and against the same class of failure:
    code deployed before `alembic upgrade` runs 086 hits UndefinedTable on
    every session that produces events, and a swallowed failure there used to
    take laps, GPS traces, scores, theoretical data and corner metrics with
    it. See `_write_in_savepoint`.

    An earlier revision of this comment described the swallow as benign
    parity with `_persist_corner_metrics`'s sibling guard. That was wrong on
    the part that mattered: the sibling had the SAME defect, so matching it
    propagated a bug rather than a convention. Both are now guarded, by one
    implementation.
    """
    events = summary.get("driving_events")
    if not events:
        return

    def _write():
        from web.repos.events_repo import insert_driving_events
        return insert_driving_events(conn, session_id, events)

    n = _write_in_savepoint(
        conn, _SAVEPOINT_DRIVING_EVENTS, "Driving events", _write)
    if n:
        logger.info(
            "Persisted %d driving events for session %s.", n, session_id,
        )


def _enrich_historical(
    conn: Any,
    session_id: str,
    track_id: str,
    driver_id: Any,
    score_result: Optional[dict],
    summary: dict,
) -> None:
    """Enrich score_result with historical context."""
    try:
        cross_mod = lazy_import("cross_session")
        if cross_mod is None:
            return
        if score_result and track_id:
            enriched = cross_mod.enrich_with_historical(
                conn, session_id, track_id, driver_id, score_result,
            )
            summary["score_result"] = enriched
            logger.info("Enriched score with historical context.")
    except Exception as exc:
        logger.warning("Historical enrichment skipped: %s", exc)


def _persist_driver_progression(
    conn: Any,
    driver_id: Any,
    session_id: str,
    summary: dict,
    theo_metrics: dict,
    driving_style_result: Optional[dict],
    score_result: Optional[dict],
    insert_driver_progression: Any,
    upsert_driver_profile: Any,
) -> None:
    """Persist driver progression snapshot and update driver profile."""
    try:
        lap_times = summary.get("lap_times") or []
        valid_lt = [
            t
            for t in lap_times
            if t and isinstance(t, (int, float)) and math.isfinite(t) and t > 0
        ]
        n_laps = len(valid_lt)
        best_s = min(valid_lt) if valid_lt else None
        mean_s = sum(valid_lt) / n_laps if n_laps > 0 else None

        # Pace delta: best - theoretical (positive = slower)
        pace_delta = None
        if best_s and theo_metrics:
            theo_t = theo_metrics.get("best_s")
            if theo_t and isinstance(theo_t, (int, float)):
                pace_delta = best_s - theo_t

        # Consistency: CV% of valid lap times
        cv_pct = None
        if n_laps >= 3:
            std = float(np.std(valid_lt))
            cv_pct = (std / mean_s * 100.0) if mean_s else None

        # Style indices
        aggression = None
        smoothness = None
        if driving_style_result:
            feat = driving_style_result.get("features", {})
            aggression = feat.get("turn_in_aggressiveness")
            smoothness = feat.get("smoothness_composite")

        total_score = None
        if score_result:
            total_score = score_result.get("total_score")

        prog_data = {
            "session_date": session_id[:10],
            "track_id": summary.get("track_id", ""),
            "pace_delta_s": pace_delta,
            "consistency_cv_pct": cv_pct,
            "aggression_index": aggression,
            "smoothness_index": smoothness,
            "total_score": total_score,
            "n_laps": n_laps,
        }
        insert_driver_progression(conn, driver_id, session_id, prog_data)
        logger.info("Persisted driver progression for session %s.", session_id)
    except Exception as exc:
        logger.warning("Driver progression persistence skipped: %s", exc)

    # Update driver profile computed fields
    try:
        all_prog = conn.execute(
            "SELECT pace_delta_s, consistency_cv_pct, aggression_index, "
            "smoothness_index, total_score, n_laps "
            "FROM driver_progression WHERE driver_id = ?",
            (driver_id,),
        ).fetchall()

        if all_prog:
            deltas = [r[0] for r in all_prog if r[0] is not None]
            cvs = [r[1] for r in all_prog if r[1] is not None]
            aggs = [r[2] for r in all_prog if r[2] is not None]
            smos = [r[3] for r in all_prog if r[3] is not None]
            total_laps = sum(r[5] for r in all_prog if r[5])
            total_sess = len(all_prog)

            # Trend: compare mean score of last 3 vs first 3
            scores = [r[4] for r in all_prog if r[4] is not None]
            trend = "stable"
            if len(scores) >= 4:
                early = np.mean(scores[:3])
                late = np.mean(scores[-3:])
                if late > early * 1.05:
                    trend = "improving"
                elif late < early * 0.95:
                    trend = "declining"

            # Best-ever time across all sessions
            best_row = conn.execute(
                "SELECT best_lap_time_s, track_id FROM sessions "
                "WHERE driver_id = ? AND best_lap_time_s IS NOT NULL "
                "ORDER BY best_lap_time_s ASC LIMIT 1",
                (driver_id,),
            ).fetchone()

            profile_data = {
                "pace_delta_mean_s": float(np.mean(deltas)) if deltas else None,
                "consistency_rating": float(np.mean(cvs)) if cvs else None,
                "aggression_index": float(np.mean(aggs)) if aggs else None,
                "smoothness_index": float(np.mean(smos)) if smos else None,
                "improvement_trend": trend,
                "total_sessions": total_sess,
                "total_laps": total_laps,
                "best_ever_time_s": best_row[0] if best_row else None,
                "best_ever_track_id": best_row[1] if best_row else None,
            }
            upsert_driver_profile(conn, driver_id, profile_data)
            logger.info(
                "Updated driver profile (sessions=%d, laps=%d).",
                total_sess,
                total_laps,
            )
    except Exception as exc:
        logger.warning("Driver profile update skipped: %s", exc)


def _persist_weather(
    conn: Any,
    session_id: str,
    weather_timeline: Optional[pd.DataFrame],
) -> None:
    """Persist weather timeline to session_weather_laps."""
    if weather_timeline is None or weather_timeline.empty:
        return

    try:
        for _, wrow in weather_timeline.iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO session_weather_laps "
                "(session_id, lap_number, timestamp, air_temp_c, "
                "humidity_pct, wind_speed_mps, wind_dir_deg, "
                "rain_mm, cloud_cover_pct, weather_code, "
                "grip_score, track_state, track_temp_est_c) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    int(wrow["lap_number"]),
                    wrow.get("timestamp"),
                    wrow.get("air_temp_c"),
                    wrow.get("humidity_pct"),
                    wrow.get("wind_speed_mps"),
                    wrow.get("wind_dir_deg"),
                    wrow.get("rain_mm"),
                    wrow.get("cloud_cover_pct"),
                    wrow.get("weather_code"),
                    wrow.get("grip_score"),
                    wrow.get("track_state"),
                    wrow.get("track_temp_est_c"),
                ),
            )
        logger.info("Saved weather timeline for %d laps", len(weather_timeline))
    except Exception as exc:
        logger.warning("Failed to persist weather timeline: %s", exc)
