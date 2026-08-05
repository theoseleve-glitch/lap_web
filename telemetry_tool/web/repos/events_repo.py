"""Events repository — persistence + the two read surfaces for driving events.

Phase 2 of driving-pattern-recognition: ``driving_events.py`` detects
located, quantified driver mistakes into ``DrivingEvent`` dataclass
instances (see that module's docstring for the "no confidence field"
design rationale) and ``pipeline/stages/s10d3_driving_events.py`` puts them
in the run summary. This module is the only place those become rows, and
the only place a caller reads them back.

Two read surfaces, one data model: ``get_ranked_events`` answers "what
should I fix next" (ordered by ``time_cost_s`` DESC); ``get_corner_consistency``
answers "where am I unreliable" (best/median/worst/spread of
``time_cost_s`` per corner).

IMPORTANT — what ``time_cost_s`` does NOT mean: Task 9's review established
that reference aggregation is PER-FIELD INDEPENDENT — an event's
``reference_apex_speed_mps`` and ``reference_corner_time_s`` can come from
DIFFERENT admissible laps (whichever lap happened to set each field's own
best; see ``s10d3_driving_events.py``'s ``_build_references``). So
``time_cost_s`` means "gap to your own best-ever time at this corner", NOT
"what you would save by closing this event's specific magnitude deficit".
Nothing in this module — field names, docstrings, or the read surfaces
built on top of it — may assert that causal link.
"""
from __future__ import annotations

import json
import math
import sqlite3
from statistics import median
from typing import Any, Iterable

import numpy as np

from db import queries as Q
from web.repos._helpers import _safe_float


def _safe_int(v: Any) -> int | None:
    """Convert to int; return None for NaN / None / missing / non-finite.

    Routed through ``_safe_float`` first so a numpy integer/float scalar
    (e.g. ``lap_number`` threaded through from a pandas-derived value)
    coerces the same way a plain Python number does, rather than needing a
    second numpy-aware code path.
    """
    f = _safe_float(v)
    return int(f) if f is not None else None


def _json_safe(obj: Any) -> Any:
    """Recursively coerce a value into something ``json.dumps`` can handle.

    ``evidence`` dicts are built by detectors from window/reference values
    -- plain Python floats in this codebase's detectors today, but nothing
    stops a future detector (or a differently-configured numpy) from
    putting a numpy scalar or array in there directly. ``np.float64``
    happens to subclass Python's ``float`` on this platform so it
    serializes fine on its own, but ``np.int64``/``np.bool_``/``np.float32``
    do NOT subclass ``int``/``bool``/``float`` and ``json.dumps`` raises
    ``TypeError`` on them -- confirmed empirically in this repo's own venv.
    Phase 1 lost an entire corner-metrics write to exactly this class of
    bug (see ``web/repos/score_repo.py``'s ``grip_anchor_pct`` comment),
    silently, because the persistence call is wrapped in a bare
    ``except Exception``. Coerce here, once, rather than trust every
    future detector to only ever produce plain Python types.

    Non-finite floats (NaN/+-inf) become ``None``: valid JSON has no NaN/
    Infinity token, and ``DrivingEvent.__post_init__`` only guards
    ``magnitude``/``time_cost_s`` -- arbitrary nested evidence values are
    not covered by that check.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def insert_driving_events(
    conn: sqlite3.Connection,
    session_id: str,
    events: Iterable[Any],
) -> int:
    """Persist one row per ``DrivingEvent``. Returns the number of rows
    written (including no-op overwrites of an identical row).

    Idempotent by construction: ``driving_events``' UNIQUE(session_id,
    lap_number, corner_id, event_type) (migration 086) gives ``INSERT OR
    REPLACE`` -- translated to ``ON CONFLICT (...) DO UPDATE`` on
    PostgreSQL by ``db/sql_compat.py`` -- a conflict target to overwrite
    on, so a reprocess of the same session updates each event's row in
    place instead of duplicating it.

    Every numeric bind goes through ``_safe_float``/``_safe_int``: a raw
    numpy scalar bound directly as a query parameter raises psycopg2's
    "can't adapt type" on PostgreSQL (the bind-time twin of ``_json_safe``'s
    JSON-serialization problem above — same root cause, different failure
    site).
    """
    count = 0
    for ev in events or []:
        conn.execute(Q.INSERT_DRIVING_EVENT, {
            "session_id": session_id,
            "lap_number": _safe_int(ev.lap_number),
            "corner_id": _safe_int(ev.corner_id),
            "event_type": ev.event_type,
            "s_norm_start": _safe_float(ev.s_norm_start),
            "s_norm_end": _safe_float(ev.s_norm_end),
            "magnitude": _safe_float(ev.magnitude),
            "magnitude_unit": ev.magnitude_unit,
            "time_cost_s": _safe_float(ev.time_cost_s),
            "validity": ev.validity,
            "reason": ev.reason,
            "n_samples_in_window": _safe_int(ev.n_samples_in_window),
            "evidence_json": json.dumps(_json_safe(ev.evidence or {})),
        })
        count += 1
    return count


def _row_to_dict(row: Any) -> dict:
    d = dict(row)
    raw = d.get("evidence_json")
    if isinstance(raw, str):
        try:
            d["evidence"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            d["evidence"] = {}
    else:
        d["evidence"] = raw or {}
    return d


def get_ranked_events(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int = 10,
) -> list[dict]:
    """The ranked "what should I fix next" surface: this session's driving
    events ordered by ``time_cost_s`` DESC (biggest gap-to-own-best-time
    first). See ``SELECT_RANKED_EVENTS`` for why NULL-cost events (
    re_braking, envelope_under_use) are excluded rather than sorted last.
    """
    rows = conn.execute(Q.SELECT_RANKED_EVENTS, {
        "session_id": session_id,
        "limit": _safe_int(limit) or 10,
    }).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_corner_consistency(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """The "where am I unreliable" surface: per corner_id, best/median/
    worst/spread of ``time_cost_s`` across this session's events.

    ``worst_s`` is the largest (costliest) ``time_cost_s`` seen at that
    corner, ``best_s`` the smallest, ``spread_s = worst_s - best_s``. A
    corner with no cost-bearing events (only re_braking/envelope_under_use
    fired there) has nothing to aggregate and is omitted, not zero-filled.
    """
    rows = conn.execute(Q.SELECT_TIME_COSTS_FOR_CONSISTENCY, {
        "session_id": session_id,
    }).fetchall()

    by_corner: dict[Any, list[float]] = {}
    for r in rows:
        d = dict(r)
        cid = d.get("corner_id")
        cost = _safe_float(d.get("time_cost_s"))
        if cid is None or cost is None:
            continue
        by_corner.setdefault(cid, []).append(cost)

    out = []
    for cid, costs in by_corner.items():
        costs.sort()
        best = costs[0]
        worst = costs[-1]
        out.append({
            "corner_id": cid,
            "best_s": best,
            "worst_s": worst,
            "median_s": median(costs),
            "spread_s": worst - best,
        })
    out.sort(key=lambda r: r["corner_id"])
    return out
