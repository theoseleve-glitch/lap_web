"""Celery tasks for per-stint endurance processing."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from celery_app import celery as celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.endurance_tasks.process_endurance_session",
    queue="pipeline",
    bind=True,
    max_retries=0,
    soft_time_limit=3600,
)
def process_endurance_session(
    self,
    job_id: str,
    meta: dict[str, Any],
    stint_configs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Process each stint through the pipeline, then aggregate."""
    import redis as _redis
    from web.config import Config

    _r = _redis.Redis.from_url(Config.REDIS_URL)

    file_path = meta["file_path"]
    session_meta = meta.get("session_meta", {})
    total_stints = len(stint_configs)

    _publish(_r, job_id, {"status": "processing", "total_stints": total_stints})

    stint_results = []
    # Track per-stint statuses so frontend can always see the full picture
    stint_statuses: list[dict] = [
        {"stint_number": sc["stint_number"], "driver_name": sc.get("driver_name", ""), "status": "queued"}
        for sc in stint_configs
    ]

    def _publish_full(phase: str, extra: dict | None = None):
        """Publish full status including all stint statuses."""
        payload = {
            "status": phase,
            "total_stints": total_stints,
            "stints": stint_statuses,
            "progress_pct": round(sum(1 for s in stint_statuses if s["status"] == "complete") / total_stints * 100),
            **(extra or {}),
        }
        _publish(_r, job_id, payload)

    for i, stint_cfg in enumerate(stint_configs):
        stint_num = stint_cfg["stint_number"]
        start_lap = stint_cfg["start_lap"]
        end_lap = stint_cfg["end_lap"]
        driver_name = stint_cfg.get("driver_name", f"Driver {stint_num}")
        condition = stint_cfg.get("condition", "dry")
        valid_laps = stint_cfg.get("valid_laps")
        pit_lap_number = stint_cfg.get("pit_lap_number")
        pit_lap_time_s = stint_cfg.get("pit_lap_time_s")
        logger.info("Stint %d: start=%d end=%d valid_laps=%s driver=%s",
                     stint_num, start_lap, end_lap,
                     f"{len(valid_laps)} laps" if valid_laps else "None (using range)",
                     driver_name)

        # Mark this stint as processing
        stint_statuses[i]["status"] = "processing"
        _publish_full("processing_stint")

        try:
            result = _process_single_stint(
                file_path=file_path,
                start_lap=start_lap,
                end_lap=end_lap,
                stint_number=stint_num,
                driver_name=driver_name,
                condition=condition,
                valid_laps=valid_laps,
                session_meta=session_meta,
                workspace_id=meta.get("workspace_id", "1"),
                job_id=job_id,
            )
            # Add pit info from config (not from pipeline)
            result["pit_lap_number"] = pit_lap_number
            result["pit_lap_time_s"] = pit_lap_time_s
            result["pit_duration_s"] = stint_cfg.get("pit_duration_s")
            stint_results.append(result)

            # Mark complete with stats
            stint_statuses[i] = {
                **stint_statuses[i],
                "status": "complete",
                "best_lap_s": result.get("best_lap_s"),
                "lap_count": result.get("lap_count"),
            }
            _publish_full("stint_complete")
        except Exception as exc:
            logger.exception("Failed to process stint %d", stint_num)
            stint_statuses[i] = {**stint_statuses[i], "status": "error", "error": str(exc)[:200]}
            _publish_full("stint_error")
            stint_results.append({
                "stint_number": stint_num,
                "driver_name": driver_name,
                "error": str(exc)[:200],
                "lap_count": 0,
            })

    # Aggregate
    _publish_full("processing_drivers")

    from endurance_scoring import compute_driver_report, compute_team_report

    driver_stints: dict[str, list] = {}
    for r in stint_results:
        d = r.get("driver_name", "Unknown")
        if d not in driver_stints:
            driver_stints[d] = []
        driver_stints[d].append(r)

    driver_reports = {}
    for driver, stints in driver_stints.items():
        driver_reports[driver] = compute_driver_report(driver, stints)
        _publish_full("driver_complete", {"driver_name": driver})

    _publish_full("processing_team")

    total_laps = sum(r.get("lap_count", 0) for r in stint_results if not r.get("error"))
    total_time = sum(r.get("total_time_s", 0) for r in stint_results if not r.get("error"))
    team_report = compute_team_report(
        driver_reports, total_laps, total_stints, total_time,
        stint_results=stint_results,
        pit_threshold_s=meta.get("pit_threshold_s", 30),
    )

    full_report = {
        "team": team_report,
        "drivers": driver_reports,
        "stint_results": stint_results,
    }

    _r.set(f"endurance:report:{job_id}", json.dumps(full_report), ex=14400)

    # ── Persist master endurance session to DB ──────────────────
    # Creates a single session entry visible in the sessions list
    master_session_id = None
    try:
        master_session_id = _persist_master_session(
            job_id=job_id,
            meta=meta,
            team_report=team_report,
            driver_reports=driver_reports,
            stint_results=stint_results,
            total_laps=total_laps,
            total_time=total_time,
            workspace_id=meta.get("workspace_id", "1"),
        )
        logger.info("Persisted master endurance session: %s", master_session_id)
    except Exception:
        logger.exception("Failed to persist master endurance session")

    # ── Cleanup temp upload file ──────────────────────────────
    try:
        import shutil
        upload_dir = Path(file_path).parent
        if upload_dir.name.startswith("endurance_"):
            shutil.rmtree(upload_dir, ignore_errors=True)
            logger.info("Cleaned up endurance upload: %s", upload_dir)
    except Exception:
        pass

    _publish(_r, job_id, {
        "status": "completed",
        "job_id": job_id,
        "session_id": master_session_id,
    })
    return {"job_id": job_id, "stints_processed": len(stint_results), "session_id": master_session_id}


def _persist_stint_session(
    summary: dict[str, Any],
    driver_name: str,
    workspace_id: str,
    stint_number: int,
    job_id: str,
) -> str | None:
    """Persist a stint's pipeline results to PG using the same path as normal uploads.

    Mirrors ``pipeline_tasks._persist_session_data`` — connection-scoped SET,
    independent commits per step, graceful degradation on non-critical failures.
    Falls back to s15_persist for SQLite mode.
    """
    if os.environ.get("USE_PG", "0") != "1":
        # SQLite mode: delegate to s15_persist
        from pipeline.stages.s15_persist import run_persist_to_db
        meta = summary.get("session_meta") or {}
        return run_persist_to_db(
            summary, meta,
            summary.get("track_id", ""),
            score_result=summary.get("score_result"),
            driving_style_result=summary.get("driving_style_result"),
            driver_tag=driver_name,
            force_persist=True,
        )

    from web.db_pg import get_pg_connection
    from web.models import (
        insert_corner_metrics,
        insert_gps_traces,
        insert_laps,
        insert_reference_line,
        insert_score_details,
        upsert_driver,
        upsert_session,
        upsert_track,
    )

    conn = get_pg_connection()
    try:
        # Connection-scoped SET survives COMMIT (same as _persist_session_data)
        conn.execute(
            "SET app.current_workspace_id = %(ws)s",
            {"ws": str(workspace_id)},
        )

        # 1. Upsert driver
        driver_id = upsert_driver(conn, driver_name)
        conn.commit()

        # 2. Ensure track exists (FK constraint)
        meta = summary.get("session_meta") or {}
        user_track_name = meta.get("track_name") or meta.get("user_track_name")
        track_match = summary.get("track_match")

        if track_match and isinstance(track_match, dict):
            try:
                upsert_track(conn, track_match)
                conn.commit()
            except Exception:
                conn.rollback()

        # Use user-provided track name when pipeline detection falls back to unknown
        track_id = summary.get("track_id", "unknown_track")
        if user_track_name and track_id == "unknown_track":
            import hashlib
            track_id = hashlib.md5(user_track_name.encode()).hexdigest()[:16]
            summary["track_id"] = track_id

        display_name = user_track_name or (
            track_match.get("track_name") if track_match else track_id
        )
        try:
            conn.execute(
                "INSERT INTO tracks (track_id, track_name, lap_length_m) "
                "VALUES (%(track_id)s, %(track_name)s, %(lap_length_m)s) "
                "ON CONFLICT (track_id) DO NOTHING",
                {"track_id": track_id, "track_name": display_name, "lap_length_m": 0.0},
            )
            conn.commit()
        except Exception:
            conn.rollback()

        # Set kart from session meta (if provided in endurance upload form)
        kart_name = meta.get("kart_name")
        if kart_name and kart_name.strip():
            try:
                from web.models import upsert_kart_by_name
                kart_id = upsert_kart_by_name(conn, kart_name.strip())
                conn.commit()
                meta["kart_id"] = kart_id
            except Exception:
                conn.rollback()

        # 3. Upsert session
        session_id = upsert_session(conn, summary, driver_id)
        conn.commit()
        logger.info("Stint %d: persisted session %s (driver_id=%d)", stint_number, session_id, driver_id)

        # 4. Insert laps
        try:
            n_laps = insert_laps(conn, session_id, summary)
            conn.commit()
            logger.info("Stint %d: inserted %s laps", stint_number, n_laps)
        except Exception:
            logger.warning("Stint %d: laps insert failed", stint_number, exc_info=True)
            conn.rollback()

        # 5. Insert GPS traces
        try:
            n_gps = insert_gps_traces(conn, session_id, summary)
            conn.commit()
            logger.info("Stint %d: inserted %s GPS rows", stint_number, n_gps)
        except Exception:
            logger.warning("Stint %d: GPS insert failed", stint_number, exc_info=True)
            conn.rollback()

        # 6. Insert corner metrics
        try:
            if summary.get("corners"):
                insert_corner_metrics(conn, session_id, summary)
                conn.commit()
        except Exception:
            conn.rollback()

        # 7. Insert score details
        try:
            if summary.get("score_result"):
                insert_score_details(conn, session_id, summary)
                conn.commit()
        except Exception:
            conn.rollback()

        # 8. Insert reference line
        try:
            if summary.get("reference_line") is not None:
                insert_reference_line(conn, session_id, summary)
                conn.commit()
        except Exception:
            conn.rollback()

        return session_id

    except Exception:
        logger.exception("Stint %d PG persist failed (job %s)", stint_number, job_id)
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _process_single_stint(
    file_path: str,
    start_lap: int,
    end_lap: int,
    stint_number: int,
    driver_name: str,
    condition: str,
    session_meta: dict,
    workspace_id: str,
    job_id: str,
    valid_laps: list[int] | None = None,
) -> dict[str, Any]:
    """Run the pipeline on a single stint's rows.

    Reads only rows belonging to laps [start_lap, end_lap],
    writes a temp CSV, runs pipeline on it.
    """
    csv_path = Path(file_path)

    header_lines: list[str] = []
    stint_lines: list[str] = []
    lap_col_idx: int | None = None

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                header_lines.append(line)
                continue
            lower = stripped.lower()
            if "lap" in lower and ("time" in lower or "speed" in lower):
                header_lines.append(line)
                parts = [c.strip().lower() for c in stripped.split(",")]
                for i, col in enumerate(parts):
                    if col in ("lap #", "lap", "lap number"):
                        lap_col_idx = i
                        break
                break
            header_lines.append(line)

        if lap_col_idx is None:
            raise ValueError("Cannot find Lap # column in CSV header")

        _valid_set = set(valid_laps) if valid_laps else set()
        logger.info("Row filter: valid_set=%s (len=%d), range=%d-%d",
                     _valid_set if len(_valid_set) < 20 else f"{len(_valid_set)} laps",
                     len(_valid_set), start_lap, end_lap)

        for line in f:
            parts = line.split(",")
            if len(parts) <= lap_col_idx:
                continue
            try:
                lap_num = int(float(parts[lap_col_idx].strip()))
            except (ValueError, TypeError):
                continue
            # Use explicit valid_laps list if provided, else fall back to range
            if _valid_set:
                if lap_num not in _valid_set:
                    continue
            elif not (start_lap <= lap_num <= end_lap):
                continue
            stint_lines.append(line)

    if not stint_lines:
        return {
            "stint_number": stint_number,
            "driver_name": driver_name,
            "lap_count": 0,
            "best_lap_s": None,
            "mean_lap_s": None,
            "total_time_s": 0,
            "scores": {"pace": 0, "consistency": 0, "robustness": 0},
        }

    logger.info(
        "Stint %d (%s): %d rows from laps %d-%d",
        stint_number, driver_name, len(stint_lines), start_lap, end_lap,
    )

    # Write stint CSV
    fd, stint_csv_path = tempfile.mkstemp(
        suffix=".csv", prefix=f"endurance_stint{stint_number}_",
    )
    os.close(fd)
    with open(stint_csv_path, "w", encoding="utf-8") as out:
        out.writelines(header_lines)
        out.writelines(stint_lines)

    try:
        from pipeline.orchestrator import run_full_analysis

        summary = run_full_analysis(
            csv_path=stint_csv_path,
            session_meta={
                **session_meta,
                "driver_name": driver_name,
                "session_type": "endurance_stint",
                "track_state": condition,
            },
            enable_report=False,
        )

        score = summary.get("score_result") or {}
        subs = score.get("sub_scores", {})
        lap_metrics = summary.get("lap_metrics") or []
        valid_times = [
            lm["lap_time_s"] for lm in lap_metrics
            if lm.get("lap_time_s") and lm["lap_time_s"] > 0
        ]

        # Track-evolution-aware pace: if lap times show a clear improvement
        # trend, compare each lap against the running PB instead of the
        # final PB.  Use whichever score is higher (rewards the driver).
        rpb_details = {}
        try:
            from endurance_scoring import running_pb_pace
            rpb_score, rpb_details = running_pb_pace(valid_times, condition=condition)
            if rpb_score is not None:
                scorer_pace = subs.get("pace", {}).get("score", 0)
                if rpb_score > scorer_pace:
                    logger.info(
                        "Stint %d: track evolution detected (slope=%.3f s/lap, R²=%.2f) — "
                        "running-PB pace %.1f > scorer pace %.1f",
                        stint_number, rpb_details.get("slope_s_per_lap", 0),
                        rpb_details.get("r_squared", 0), rpb_score, scorer_pace,
                    )
                    subs.setdefault("pace", {})["score"] = rpb_score
        except Exception:
            pass  # non-fatal — fall back to standard pace

        # Persist stint session to DB (same path as normal uploads)
        stint_session_id = summary.get("db_session_id")
        if not stint_session_id:
            try:
                stint_session_id = _persist_stint_session(
                    summary, driver_name, workspace_id, stint_number, job_id,
                )
                summary["db_session_id"] = stint_session_id
                if stint_session_id:
                    logger.info("Persisted stint %d session: %s", stint_number, stint_session_id)
            except Exception as persist_err:
                logger.warning("Stint %d persist failed (non-fatal): %s", stint_number, persist_err)

        # Traffic time loss: running-PB + degradation cancellation
        from endurance_scoring import compute_traffic_losses
        traffic_losses, traffic_total_s, traffic_count, track_degradation = compute_traffic_losses(valid_times)

        return {
            "stint_number": stint_number,
            "driver_name": driver_name,
            "condition": condition,
            "start_lap": start_lap,
            "end_lap": end_lap,
            "lap_count": len(valid_times),
            "best_lap_s": round(min(valid_times), 3) if valid_times else None,
            "mean_lap_s": round(sum(valid_times) / len(valid_times), 3) if valid_times else None,
            "total_time_s": round(sum(valid_times), 3) if valid_times else 0,
            "traffic_losses": traffic_losses,
            "traffic_total_s": round(traffic_total_s, 3),
            "traffic_count": len(traffic_losses),
            "scores": {
                "pace": round(subs.get("pace", {}).get("score", 0), 1),
                "consistency": round(subs.get("consistency", {}).get("score", 0), 1),
                "robustness": round(subs.get("robustness", {}).get("score", 0), 1),
            },
            "track_evolution": rpb_details if rpb_details.get("trend") else None,
            "track_degradation": track_degradation,
            "session_id": summary.get("db_session_id"),
        }
    finally:
        try:
            os.unlink(stint_csv_path)
        except OSError:
            pass


def _persist_master_session(
    job_id: str,
    meta: dict,
    team_report: dict,
    driver_reports: dict,
    stint_results: list[dict],
    total_laps: int,
    total_time: float,
    workspace_id: str,
) -> str | None:
    """Create a master session entry in the DB for the endurance race.

    This makes the endurance report visible in the sessions list.
    """
    import uuid
    from web.db import get_db_connection

    conn = get_db_connection()
    # Set RLS workspace context
    conn.execute("SET LOCAL app.current_workspace_id = :wid", {"wid": str(workspace_id)})
    session_id = uuid.uuid4().hex
    session_meta = meta.get("session_meta", {})
    drivers = team_report.get("drivers", [])
    driver_label = " + ".join(drivers) if drivers else "Endurance"

    # Find overall best lap across all stints
    best_times = [r["best_lap_s"] for r in stint_results if r.get("best_lap_s")]
    best_lap = min(best_times) if best_times else None
    mean_times = [r["mean_lap_s"] for r in stint_results if r.get("mean_lap_s")]
    mean_lap = sum(t * r.get("lap_count", 1) for t, r in zip(mean_times, stint_results) if r.get("mean_lap_s")) / total_laps if total_laps > 0 else None

    # Team score
    scores = team_report.get("scores", {})
    total_score = sum(scores.values())
    grade = "A+" if total_score >= 90 else "A" if total_score >= 80 else "B" if total_score >= 65 else "C" if total_score >= 50 else "D" if total_score >= 35 else "F"

    # Find or create driver for the team label
    driver_row = conn.execute(
        "SELECT driver_id FROM drivers WHERE driver_name = :dn",
        {"dn": driver_label},
    ).fetchone()
    if driver_row:
        driver_id = driver_row["driver_id"]
    else:
        conn.execute(
            "INSERT INTO drivers (driver_name) VALUES (:dn)",
            {"dn": driver_label},
        )
        driver_row = conn.execute(
            "SELECT driver_id FROM drivers WHERE driver_name = :dn",
            {"dn": driver_label},
        ).fetchone()
        driver_id = driver_row["driver_id"]

    # Find or create track
    track_name = session_meta.get("track_name", "Unknown Track")
    track_row = conn.execute(
        "SELECT track_id FROM tracks WHERE track_name = :tn",
        {"tn": track_name},
    ).fetchone()
    if track_row:
        track_id = track_row["track_id"]
    else:
        import hashlib
        track_id = hashlib.md5(track_name.encode()).hexdigest()[:16]
        conn.execute(
            "INSERT INTO tracks (track_id, track_name) VALUES (:tid, :tn)",
            {"tid": track_id, "tn": track_name},
        )

    conn.execute(
        "INSERT INTO sessions "
        "(session_id, display_name, driver_id, track_id, session_type, track_state, "
        " session_date, best_lap_time_s, mean_lap_time_s, n_laps, total_score, grade, "
        " csv_filename, analysis_json) "
        "VALUES (:sid, :dn, :did, :tid, :st, :ts, :sd, :blt, :mlt, :tl, :tscore, :grade, :fn, :aj)",
        {
            "sid": session_id,
            "dn": driver_label,
            "did": driver_id,
            "tid": track_id,
            "st": "endurance",
            "ts": session_meta.get("track_state", "dry"),
            "sd": session_meta.get("session_date") or datetime.now().strftime("%Y-%m-%d"),
            "blt": best_lap,
            "mlt": mean_lap,
            "tl": total_laps,
            "tscore": round(total_score, 1),
            "grade": grade,
            "fn": meta.get("file_name", "endurance.csv"),
            "aj": json.dumps({
                "endurance_job_id": job_id,
                "endurance_report": {
                    "team": team_report,
                    "drivers": driver_reports,
                    "stint_results": stint_results,
                },
            }),
        },
    )

    # Insert score_details
    conn.execute(
        "INSERT INTO score_details "
        "(session_id, pace_score, pace_max, consistency_score, consistency_max, "
        " execution_score, execution_max, robustness_score, robustness_max, adaptation_score) "
        "VALUES (:sid, :ps, :pm, :cs, :cm, :es, :em, :rs, :rm, :as_)",
        {
            "sid": session_id,
            "ps": scores.get("pace", 0),
            "pm": 25,
            "cs": scores.get("consistency", 0),
            "cm": 25,
            "es": 0,
            "em": 0,
            "rs": scores.get("robustness", 0),
            "rm": 25,
            "as_": 0,
        },
    )

    conn.commit()
    try:
        conn.close()
    except Exception:
        pass
    return session_id


def _publish(redis_client, job_id: str, data: dict) -> None:
    """Publish status update for endurance job progress."""
    redis_client.set(f"endurance:status:{job_id}", json.dumps(data), ex=7200)
