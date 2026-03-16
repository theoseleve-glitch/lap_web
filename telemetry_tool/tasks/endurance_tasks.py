"""Celery tasks for per-stint endurance processing."""
from __future__ import annotations

import json
import logging
import os
import tempfile
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
    team_report = compute_team_report(driver_reports, total_laps, total_stints, total_time)

    _r.set(f"endurance:report:{job_id}", json.dumps({
        "team": team_report,
        "drivers": driver_reports,
        "stint_results": stint_results,
    }), ex=14400)

    _publish(_r, job_id, {"status": "completed", "job_id": job_id})
    return {"job_id": job_id, "stints_processed": len(stint_results)}


def _process_single_stint(
    file_path: str,
    start_lap: int,
    end_lap: int,
    stint_number: int,
    driver_name: str,
    condition: str,
    valid_laps: list[int] | None = None,
    session_meta: dict,
    workspace_id: str,
    job_id: str,
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
            "scores": {
                "pace": round(subs.get("pace", {}).get("score", 0), 1),
                "consistency": round(subs.get("consistency", {}).get("score", 0), 1),
                "robustness": round(subs.get("robustness", {}).get("score", 0), 1),
            },
            "session_id": summary.get("db_session_id"),
        }
    finally:
        try:
            os.unlink(stint_csv_path)
        except OSError:
            pass


def _publish(redis_client, job_id: str, data: dict) -> None:
    """Publish status update for endurance job progress."""
    redis_client.set(f"endurance:status:{job_id}", json.dumps(data), ex=7200)
