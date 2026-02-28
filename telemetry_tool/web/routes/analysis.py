"""Analysis routes — trigger new pipeline runs from the browser."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from web.db import get_db_connection
from web.models import (
    get_all_tracks,
    insert_condition_phases,
    insert_corner_metrics,
    insert_gps_traces,
    insert_laps,
    insert_score_details,
    upsert_driver,
    upsert_session,
    upsert_track,
)

logger = logging.getLogger(__name__)
bp = Blueprint("analysis", __name__, url_prefix="/analyze")

# ── Redis-backed job registry ──────────────────────────────────────────
# Jobs are stored as Redis hashes: analysis:job:{job_id}
# TTL: 2 hours (auto-eviction replaces _evict_old_jobs)
# Joker threading.Events stay in-memory (per-worker, same process).

_JOB_KEY_PREFIX = "analysis:job:"
_JOB_TTL = 7200  # 2 hours

# Joker events are per-process (threading.Event can't be shared via Redis).
# Only the worker that started the pipeline thread can block on these.
_joker_events: dict[str, threading.Event] = {}
_joker_lock = threading.Lock()


def _get_redis():
    """Get the shared Redis client from Flask app extensions."""
    try:
        return current_app.extensions.get("redis")
    except RuntimeError:
        # Outside request context (e.g. background thread with app_context)
        return None


def _job_key(job_id: str) -> str:
    return f"{_JOB_KEY_PREFIX}{job_id}"


def _create_job(job_id: str, data: dict) -> None:
    """Create a new job in Redis."""
    r = _get_redis()
    if r is None:
        return
    key = _job_key(job_id)
    # Serialize complex values to JSON strings
    flat = {}
    for k, v in data.items():
        if v is None:
            flat[k] = ""
        elif isinstance(v, (dict, list)):
            flat[k] = json.dumps(v)
        elif isinstance(v, bool):
            flat[k] = "1" if v else "0"
        elif isinstance(v, (int, float)):
            flat[k] = str(v)
        else:
            flat[k] = str(v)
    r.hset(key, mapping=flat)
    r.expire(key, _JOB_TTL)


def _get_job(job_id: str) -> dict | None:
    """Retrieve a job from Redis. Returns None if not found."""
    r = _get_redis()
    if r is None:
        return None
    key = _job_key(job_id)
    raw = r.hgetall(key)
    if not raw:
        return None
    # Deserialize values
    result = {}
    for k, v in raw.items():
        if v == "":
            result[k] = None
        elif k in ("progress",):
            try:
                result[k] = int(v)
            except (ValueError, TypeError):
                result[k] = 0
        elif k in ("started_at", "created"):
            try:
                result[k] = float(v)
            except (ValueError, TypeError):
                result[k] = 0.0
        elif k in ("corners_ready", "joker_ready", "joker_confirmed",
                    "joker_timed_out", "_layout_delivered", "_joker_delivered",
                    "corners_submitted"):
            result[k] = v == "1"
        elif k in ("track_layout", "joker_candidates", "selected_corners"):
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = None
        else:
            result[k] = v
    return result

_STAGE_MAP = {
    "01_ingest":              {"label": "Loading CSV",              "pct": 5},
    "02_filter":              {"label": "Filtering GPS data",       "pct": 8},
    "03_derived_channels":    {"label": "Computing channels",       "pct": 12},
    "04_trim_session":        {"label": "Detecting laps",           "pct": 16},
    "05_detect_track":        {"label": "Identifying track",        "pct": 20},
    "06_segment_laps":        {"label": "Segmenting laps",          "pct": 24},
    "07_normalise":           {"label": "Resampling data",          "pct": 28},
    "06b_detect_corners":     {"label": "Building track layout",    "pct": 33},
    "08_compute_metrics":     {"label": "Computing metrics",        "pct": 45},
    "08b_consistency":        {"label": "Consistency analysis",      "pct": 48},
    "08j_joker_detection":    {"label": "Joker lap detection",       "pct": 50},
    "09a_reference_line":     {"label": "Computing reference line",  "pct": 55},
    "09c_friction_model":     {"label": "Building friction model",   "pct": 60},
    "10_theoretical":         {"label": "Physics simulation",        "pct": 70},
    "10c_corner_analysis":    {"label": "Corner analysis",           "pct": 75},
    "11_features":            {"label": "Building features",         "pct": 78},
    "12_ml":                  {"label": "Machine learning",          "pct": 82},
    "13_scoring":             {"label": "Scoring session",           "pct": 85},
    "14a_driver_profile":     {"label": "Driver profiling",          "pct": 88},
    "14b_html_report":        {"label": "Generating report",         "pct": 92},
    "15_persist_to_db":       {"label": "Saving to database",        "pct": 96},
}


def _update_job(job_id: str, **kwargs):
    """Update job fields in Redis."""
    r = _get_redis()
    if r is None:
        return
    key = _job_key(job_id)
    if not r.exists(key):
        return
    flat = {}
    for k, v in kwargs.items():
        # Skip non-serializable objects (threading.Event, etc.)
        if k == "joker_event":
            continue
        if v is None:
            flat[k] = ""
        elif isinstance(v, (dict, list)):
            flat[k] = json.dumps(v)
        elif isinstance(v, bool):
            flat[k] = "1" if v else "0"
        elif isinstance(v, (int, float)):
            flat[k] = str(v)
        else:
            flat[k] = str(v)
    if flat:
        r.hset(key, mapping=flat)


def _pipeline_progress_hook(job_id: str):
    """Return a callback that the pipeline can call after each step."""
    def hook(step_name: str, ok: bool):
        info = _STAGE_MAP.get(step_name, {})
        label = info.get("label", step_name)
        pct = info.get("pct", 50)
        _update_job(job_id, stage=label, progress=pct)
    return hook


def _run_analysis_bg(job_id: str, csv_path: str, meta: dict, app,
                     workspace_id: int | None = None):
    """Run the full pipeline in a background thread."""
    with app.app_context():
        try:
            _update_job(job_id, status="running", stage="Starting pipeline...", progress=2)

            import pipeline as p

            # Monkey-patch _record to capture stage progress in real-time.
            orig_analysis = p.run_full_analysis
            hook = _pipeline_progress_hook(job_id)

            # We wrap _safe_step to report progress.
            orig_safe_step = p._safe_step

            def patched_safe_step(step_name, fn, *a, **kw):
                result, err = orig_safe_step(step_name, fn, *a, **kw)
                hook(step_name, err is None)
                return result, err

            # Corner callback: called by pipeline after corner detection.
            # Stores track layout in the job dict for the frontend picker.
            def _on_corners_ready(track_layout):
                _update_job(
                    job_id,
                    corners_ready=True,
                    track_layout=track_layout,
                    track_id=track_layout.get("track_id"),
                )

            # Joker callback: called by pipeline after joker detection.
            # BLOCKS the pipeline thread until the user confirms/rejects.
            joker_event = threading.Event()
            with _joker_lock:
                _joker_events[job_id] = joker_event

            def _on_joker_ready(joker_result):
                from dataclasses import asdict
                _update_job(
                    job_id,
                    joker_ready=True,
                    joker_candidates=asdict(joker_result),
                    joker_confirmed=False,
                    joker_timed_out=False,
                )
                logger.info(
                    "Joker detection paused pipeline (job %s) — "
                    "waiting for user confirmation (timeout 300s).",
                    job_id,
                )
                # BLOCK here until user confirms or 5 min timeout.
                signalled = joker_event.wait(timeout=300)
                if not signalled:
                    logger.warning(
                        "Joker confirmation timed out for job %s.", job_id,
                    )
                    _update_job(job_id, joker_timed_out=True)
                    return None  # Pipeline continues without joker lap.

                # Read the user's decision from Redis.
                job_data = _get_job(job_id) or {}
                confirmed_lap = job_data.get("joker_confirmed_lap")
                if confirmed_lap is not None:
                    try:
                        confirmed_lap = int(confirmed_lap)
                    except (ValueError, TypeError):
                        confirmed_lap = None
                return confirmed_lap  # int or None (if rejected)

            # Use the app's configured RESULTS_DIR (writable in Docker)
            # instead of the pipeline's hardcoded "Results/" which fails
            # under non-root container users.
            results_dir = current_app.config.get("RESULTS_DIR", "Results")

            p._safe_step = patched_safe_step
            try:
                summary = orig_analysis(
                    csv_path=csv_path,
                    session_meta=meta,
                    enable_report=True,
                    output_dir=results_dir,
                    corner_callback=_on_corners_ready,
                    joker_callback=_on_joker_ready,
                )
            finally:
                p._safe_step = orig_safe_step

            # Persist to DB (pipeline step 15 may have already done this).
            db_session_id = summary.get("db_session_id")

            if not db_session_id:
                # Fallback persistence.
                _update_job(job_id, stage="Saving to database...", progress=95)
                try:
                    conn = get_db_connection()
                    # Set workspace context so RLS + column defaults work.
                    if workspace_id and os.environ.get("USE_PG", "0") == "1":
                        conn.execute(
                            "SET LOCAL app.current_workspace_id = %s",
                            (str(workspace_id),),
                        )
                    driver_name = meta.get("driver_name", "Driver_1")
                    driver_id = upsert_driver(conn, driver_name)

                    _tid = summary.get("track_id")
                    if _tid:
                        _track_entry = None
                        try:
                            from track_detection import load_track_database
                            for _te in load_track_database():
                                if _te.get("track_id") == _tid:
                                    _track_entry = _te
                                    break
                        except Exception:
                            pass
                        if _track_entry is None:
                            _tm = summary.get("track_match")
                            # Prefer user-provided track name over auto-detected
                            _user_tn = meta.get("track_name")
                            _auto_tn = (_tm or {}).get("track_name", _tid)
                            _track_entry = {
                                "track_id": _tid,
                                "track_name": _user_tn or _auto_tn,
                                "fingerprint": {
                                    "lap_length_m": (_tm or {}).get("lap_length_m", 0.0),
                                    "bbox": {},
                                    "start_lat": None,
                                    "start_lon": None,
                                    "sample_count": None,
                                    "lap_count": None,
                                },
                            }
                        elif meta.get("track_name"):
                            # User provided name overrides detected name
                            _track_entry["track_name"] = meta["track_name"]
                        upsert_track(conn, _track_entry)

                    db_session_id = upsert_session(conn, summary, driver_id)
                    insert_laps(conn, db_session_id, summary)
                    insert_gps_traces(conn, db_session_id, summary)
                    insert_score_details(conn, db_session_id, summary)
                    insert_condition_phases(conn, db_session_id, summary)
                    insert_corner_metrics(conn, db_session_id, summary)
                    conn.commit()
                except Exception as exc:
                    logger.exception("Fallback DB persist failed: %s", exc)
                    _update_job(
                        job_id,
                        status="done",
                        progress=100,
                        stage="Complete (DB save partial)",
                        session_id=None,
                        error=f"Analysis OK but DB save failed: {exc}",
                    )
                    return

            # Store track_id for corner persistence
            _track_id = summary.get("track_id")
            _update_job(
                job_id,
                status="done",
                progress=100,
                stage="Complete",
                session_id=db_session_id,
                track_id=_track_id,
            )

            # If corners were submitted while pipeline was running, persist now
            _job_data = _get_job(job_id) or {}
            _sel = _job_data.get("selected_corners")
            if _sel and _track_id:
                _persist_key_corners(_track_id, _sel)

            # Clean up joker event
            with _joker_lock:
                _joker_events.pop(job_id, None)

        except Exception as exc:
            logger.exception("Background analysis failed: %s", exc)
            _update_job(
                job_id,
                status="error",
                stage="Failed",
                error=str(exc),
            )
            with _joker_lock:
                _joker_events.pop(job_id, None)


def _list_csv_files() -> list[str]:
    """Return CSV files available in data/raw/."""
    raw_dir = Path(current_app.config["DATA_RAW_DIR"])
    if not raw_dir.is_dir():
        return []
    return sorted(
        f.name for f in raw_dir.iterdir()
        if f.suffix.lower() == ".csv"
    )


@bp.route("/", methods=["GET"])
def analyze_form():
    """Show the analysis configuration form."""
    csv_files = _list_csv_files()
    selected_file = request.args.get("selected", "")
    conn = get_db_connection()
    tracks = get_all_tracks(conn)
    # Fetch existing drivers for the dropdown
    driver_rows = conn.execute(
        "SELECT d.driver_id, d.driver_name, COUNT(s.session_id) AS session_count "
        "FROM drivers d LEFT JOIN sessions s ON d.driver_id = s.driver_id "
        "GROUP BY d.driver_id ORDER BY d.driver_name"
    ).fetchall()
    drivers = [dict(r) for r in driver_rows]
    return render_template(
        "analyze.html",
        csv_files=csv_files,
        selected_file=selected_file,
        tracks=tracks,
        drivers=drivers,
    )


# ── Async API endpoint ─────────────────────────────────────────────────

def _analyze_start_impl():
    """Start analysis in background thread. Returns JSON with job_id."""
    # Resolve CSV path.
    csv_name = request.form.get("csv_file", "").strip()
    raw_dir = Path(current_app.config["DATA_RAW_DIR"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Handle upload.
    from werkzeug.utils import secure_filename
    uploaded = request.files.get("csv_upload")
    csv_path = None
    if uploaded and uploaded.filename:
        safe_name = secure_filename(uploaded.filename) or "upload.csv"
        if not safe_name.lower().endswith(".csv"):
            safe_name += ".csv"
        csv_path = raw_dir / safe_name
        uploaded.save(str(csv_path))
        logger.info("Uploaded file saved: %s", csv_path)
    elif csv_name:
        csv_path = raw_dir / csv_name
    else:
        return jsonify({"error": "No CSV file selected."}), 400

    if csv_path is None or not csv_path.exists():
        if csv_name:
            for f in raw_dir.iterdir():
                if f.name.lower() == csv_name.lower() and f.suffix.lower() == ".csv":
                    csv_path = f
                    break
        if csv_path is None or not csv_path.exists():
            return jsonify({"error": f"File not found: {csv_name or '(none)'}"}), 404

    # Collect metadata.
    driver_name = request.form.get("driver_name", "Driver_1").strip()
    session_type = request.form.get("session_type", "practice")
    track_state = request.form.get("track_state", "dry")
    track_name = request.form.get("track_name", "").strip()
    session_date = request.form.get("session_date", "").strip()
    enable_joker = request.form.get("enable_joker") == "1"
    kart_model = request.form.get("kart_model", "").strip()

    drivers = []
    for idx in range(20):
        dname = request.form.get(f"driver_name_{idx}", "").strip()
        if not dname:
            continue
        try:
            ds = int(request.form.get(f"driver_lap_start_{idx}", "1") or "1")
            de = int(request.form.get(f"driver_lap_end_{idx}", "999") or "999")
        except ValueError:
            ds, de = 1, 999
        drivers.append({"name": dname, "lap_range": (ds, de)})

    if not drivers:
        lap_start = request.form.get("lap_start", "")
        lap_end = request.form.get("lap_end", "")
        lap_range = None
        if lap_start and lap_end:
            try:
                lap_range = (int(lap_start), int(lap_end))
            except ValueError:
                pass
        drivers = [{"name": driver_name, "lap_range": lap_range or (1, 999)}]
    else:
        driver_name = drivers[0]["name"]

    meta = {
        "session_type": session_type,
        "track_state": track_state,
        "driver_name": driver_name,
        "track_name": track_name or None,
        "session_date": session_date or None,
        "drivers": drivers,
        "enable_joker": enable_joker,
        "kart_model": kart_model or None,
    }

    # Create job and start background thread.
    job_id = uuid.uuid4().hex[:12]
    _create_job(job_id, {
        "status": "queued",
        "stage": "Queued",
        "progress": 0,
        "error": None,
        "session_id": None,
        "started_at": time.time(),
        "created": time.time(),
    })

    app = current_app._get_current_object()
    # Capture workspace_id from request context (set by tenant middleware)
    # so the background thread can set RLS context on its own connection.
    ws_id = getattr(g, "workspace_id", None)
    t = threading.Thread(
        target=_run_analysis_bg,
        args=(job_id, str(csv_path), meta, app),
        kwargs={"workspace_id": ws_id},
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id, "status": "queued"})


@bp.route("/api/start", methods=["POST"])
def analyze_start_api():
    """Legacy analyze start endpoint."""
    return _analyze_start_impl()


def _analyze_status_impl(job_id: str):
    """Poll analysis progress. Returns JSON with status/stage/progress/session_id.

    Translates internal status values to match the Next.js frontend expectations:
    - queued → pending, running → processing, done → complete, error → failed
    """
    job = _get_job(job_id)
    if job is None:
        return jsonify({"error": "Unknown job ID"}), 404

    # Status translation: backend → frontend
    _STATUS_MAP = {
        "queued": "pending",
        "running": "processing",
        "done": "complete",
        "error": "failed",
    }
    raw_status = job.get("status", "pending")
    frontend_status = _STATUS_MAP.get(raw_status, raw_status)

    started_at = job.get("started_at", 0.0)
    if isinstance(started_at, str):
        try:
            started_at = float(started_at)
        except (ValueError, TypeError):
            started_at = 0.0
    elapsed = int(time.time() - started_at) if started_at else 0

    resp = {
        "job_id": job_id,
        "status": frontend_status,
        "stage": job.get("stage", ""),
        "message": job.get("stage", ""),  # frontend reads "message"
        "progress": job.get("progress", 0),
        "error": job.get("error"),
        "session_id": job.get("session_id"),
        "elapsed": elapsed,
        "corners_ready": job.get("corners_ready", False),
        "joker_ready": job.get("joker_ready", False),
        "joker_confirmed": job.get("joker_confirmed", False),
        "joker_timed_out": job.get("joker_timed_out", False),
        "track_id": job.get("track_id"),
    }
    # Include track layout only once (first time corners_ready is polled)
    if job.get("corners_ready") and job.get("track_layout"):
        resp["track_layout"] = job["track_layout"]
        # Mark as delivered in Redis
        _update_job(job_id, _layout_delivered=True, track_layout=None)
    elif job.get("corners_ready") and job.get("_layout_delivered"):
        resp["track_layout"] = None  # already delivered

    # Include joker candidates only once (same deliver-once pattern)
    if job.get("joker_ready") and job.get("joker_candidates") and not job.get("_joker_delivered"):
        resp["joker_candidates"] = job["joker_candidates"]
        _update_job(job_id, _joker_delivered=True)
    elif job.get("joker_ready") and job.get("_joker_delivered"):
        resp["joker_candidates"] = None  # already delivered

    return jsonify(resp)


@bp.route("/api/status/<job_id>")
def analyze_status_api(job_id: str):
    """Legacy analyze status endpoint."""
    return _analyze_status_impl(job_id)


# ── Corner selection endpoint ──────────────────────────────────────────

@bp.route("/api/corners/<job_id>", methods=["POST"])
def submit_corners_api(job_id: str):
    """Save user-selected key corners for a running/completed analysis job.

    Body accepts either:
      - ``{"corners": [1, 2, 3]}``  (legacy: plain corner_id ints)
      - ``{"corners": [{"corner_id": 1, "lat": ..., "lon": ..., "dist_m": ..., "label": "T1"}, ...]}``
    """
    job = _get_job(job_id)
    if job is None:
        return jsonify({"error": "Unknown job ID"}), 404

    data = request.get_json(silent=True) or {}
    selected = data.get("corners", [])

    if not isinstance(selected, list) or len(selected) < 3 or len(selected) > 8:
        return jsonify({"error": "Select 3 to 8 areas of interest."}), 400

    # Normalize: accept both plain ints and full dicts
    normalized = []
    for item in selected:
        if isinstance(item, dict):
            normalized.append(item)
        else:
            normalized.append({"corner_id": int(item)})

    # Store in Redis so we can persist once session_id is known.
    _update_job(job_id, selected_corners=normalized, corners_submitted=True)

    # If the analysis is already done and session_id is available, persist now.
    session_id = job.get("session_id")
    track_id = job.get("track_id")
    if session_id and track_id:
        _persist_key_corners(track_id, normalized)

    return jsonify({"ok": True, "count": len(normalized)})


def _persist_key_corners(track_id: str, corners: list):
    """Save key corners to the database.

    ``corners`` is a list of dicts with at least ``corner_id``, and optionally
    ``lat``, ``lon``, ``dist_m``, ``label``.  Plain int lists are also accepted
    for backward compat.
    """
    try:
        conn = get_db_connection()
        conn.execute(
            "DELETE FROM track_key_corners WHERE track_id = ?", (track_id,)
        )
        for item in corners:
            if isinstance(item, dict):
                cid = int(item["corner_id"])
                conn.execute(
                    "INSERT OR IGNORE INTO track_key_corners "
                    "(track_id, corner_id, label, lat, lon, dist_m) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        track_id,
                        cid,
                        item.get("label"),
                        item.get("lat"),
                        item.get("lon"),
                        item.get("dist_m"),
                    ),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO track_key_corners "
                    "(track_id, corner_id) VALUES (?, ?)",
                    (track_id, int(item)),
                )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to persist key corners: %s", exc)


# ── Joker lap confirmation endpoint ───────────────────────────────────

@bp.route("/api/confirm-joker/<job_id>", methods=["POST"])
def confirm_joker_api(job_id: str):
    """Confirm or reject the detected joker lap, unblocking the pipeline.

    Expects JSON: ``{"action": "confirm", "lap_number": int}``
    or ``{"action": "reject"}``.
    """
    job = _get_job(job_id)
    if job is None:
        return jsonify({"error": "Unknown job ID"}), 404

    if not job.get("joker_ready"):
        return jsonify({"error": "Joker detection not ready yet."}), 409

    data = request.get_json(silent=True) or {}
    action = data.get("action", "").strip().lower()

    if action == "confirm":
        lap_number = data.get("lap_number")
        if lap_number is None:
            return jsonify({"error": "lap_number is required for confirm."}), 400
        try:
            lap_number = int(lap_number)
        except (TypeError, ValueError):
            return jsonify({"error": "lap_number must be an integer."}), 400
        _update_job(
            job_id,
            joker_confirmed=True,
            joker_confirmed_lap=lap_number,
        )
        logger.info("Joker lap %d confirmed for job %s.", lap_number, job_id)
    elif action == "reject":
        _update_job(
            job_id,
            joker_confirmed=True,
            joker_confirmed_lap=None,
        )
        logger.info("Joker lap rejected for job %s.", job_id)
    else:
        return jsonify({"error": "action must be 'confirm' or 'reject'."}), 400

    # Unblock the pipeline thread (only works if this worker started the job).
    with _joker_lock:
        joker_event = _joker_events.get(job_id)
    if joker_event is not None:
        joker_event.set()

    return jsonify({"ok": True, "action": action})


# ── Sync POST fallback (for no-JS / direct form submit) ────────────────

@bp.route("/sync", methods=["POST"])
def analyze_run():
    """Run the pipeline synchronously. Fallback when JS is unavailable."""
    csv_name = request.form.get("csv_file", "").strip()
    raw_dir = Path(current_app.config["DATA_RAW_DIR"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    uploaded = request.files.get("csv_upload")
    csv_path = None
    if uploaded and uploaded.filename:
        safe_name = secure_filename(uploaded.filename) or "upload.csv"
        if not safe_name.lower().endswith(".csv"):
            safe_name += ".csv"
        csv_path = raw_dir / safe_name
        uploaded.save(str(csv_path))
    elif csv_name:
        csv_path = raw_dir / csv_name
    else:
        flash("No CSV file selected.", "error")
        return redirect(url_for("analysis.analyze_form"))

    if csv_path is None or not csv_path.exists():
        if csv_name:
            for f in raw_dir.iterdir():
                if f.name.lower() == csv_name.lower() and f.suffix.lower() == ".csv":
                    csv_path = f
                    break
        if csv_path is None or not csv_path.exists():
            flash(f"File not found: {csv_name or '(none)'}.", "error")
            return redirect(url_for("analysis.analyze_form"))

    driver_name = request.form.get("driver_name", "Driver_1").strip()
    session_type = request.form.get("session_type", "practice")
    track_state = request.form.get("track_state", "dry")
    track_name = request.form.get("track_name", "").strip()
    enable_joker = request.form.get("enable_joker") == "1"
    kart_model = request.form.get("kart_model", "").strip()

    drivers = []
    for idx in range(20):
        dname = request.form.get(f"driver_name_{idx}", "").strip()
        if not dname:
            continue
        try:
            ds = int(request.form.get(f"driver_lap_start_{idx}", "1") or "1")
            de = int(request.form.get(f"driver_lap_end_{idx}", "999") or "999")
        except ValueError:
            ds, de = 1, 999
        drivers.append({"name": dname, "lap_range": (ds, de)})

    if not drivers:
        lap_start = request.form.get("lap_start", "")
        lap_end = request.form.get("lap_end", "")
        lap_range = None
        if lap_start and lap_end:
            try:
                lap_range = (int(lap_start), int(lap_end))
            except ValueError:
                pass
        drivers = [{"name": driver_name, "lap_range": lap_range or (1, 999)}]
    else:
        driver_name = drivers[0]["name"]

    meta = {
        "session_type": session_type,
        "track_state": track_state,
        "driver_name": driver_name,
        "track_name": track_name or None,
        "drivers": drivers,
        "enable_joker": enable_joker,
        "kart_model": kart_model or None,
    }

    try:
        import pipeline as p
        results_dir = current_app.config.get("RESULTS_DIR", "Results")
        summary = p.run_full_analysis(
            csv_path=str(csv_path),
            session_meta=meta,
            output_dir=results_dir,
        )
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        flash(f"Analysis failed: {exc}", "error")
        return redirect(url_for("analysis.analyze_form"))

    db_session_id = summary.get("db_session_id")
    if db_session_id:
        flash(f"Analysis complete! Session: {db_session_id}", "success")
        return redirect(url_for("sessions.session_detail", session_id=db_session_id))

    try:
        conn = get_db_connection()
        driver_id = upsert_driver(conn, driver_name)
        _tid = summary.get("track_id")
        if _tid:
            _track_entry = None
            try:
                from track_detection import load_track_database
                for _te in load_track_database():
                    if _te.get("track_id") == _tid:
                        _track_entry = _te
                        break
            except Exception:
                pass
            if _track_entry is None:
                _tm = summary.get("track_match")
                _user_tn = meta.get("track_name")
                _auto_tn = (_tm or {}).get("track_name", _tid)
                _track_entry = {
                    "track_id": _tid,
                    "track_name": _user_tn or _auto_tn,
                    "fingerprint": {
                        "lap_length_m": (_tm or {}).get("lap_length_m", 0.0),
                        "bbox": {},
                        "start_lat": None, "start_lon": None,
                        "sample_count": None, "lap_count": None,
                    },
                }
            elif meta.get("track_name"):
                _track_entry["track_name"] = meta["track_name"]
            upsert_track(conn, _track_entry)
        session_id = upsert_session(conn, summary, driver_id)
        insert_laps(conn, session_id, summary)
        insert_gps_traces(conn, session_id, summary)
        insert_score_details(conn, session_id, summary)
        insert_condition_phases(conn, session_id, summary)
        insert_corner_metrics(conn, session_id, summary)
        conn.commit()
        flash(f"Analysis complete! Session: {session_id}", "success")
        return redirect(url_for("sessions.session_detail", session_id=session_id))
    except Exception as exc:
        logger.exception("DB persistence failed: %s", exc)
        flash(f"Analysis ran but DB save failed: {exc}", "warning")
        return redirect(url_for("dashboard.index"))
