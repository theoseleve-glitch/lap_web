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


def _dedupe_by_lap_corner(rows: list[dict]) -> list[dict]:
    """Collapse multiple event rows for the same (lap_number, corner_id)
    into one (fix round 1, IMPORTANT #1).

    ``over_slowing`` and ``late_throttle`` both set ``time_cost_s =
    corner_time - reference_corner_time`` for the SAME (lap, corner) --
    see ``driving_events.py``'s ``_OverSlowing.detect`` (line ~376) and
    ``_LateThrottle.detect`` (line ~450). So two DIFFERENT ``event_type``
    rows can carry the IDENTICAL ``time_cost_s`` for one lap's pass through
    one corner. Treating each row as an independent observation
    double-counts that lap: a corner-consistency median gets pulled toward
    whichever corner happened to fire the most detectors rather than
    reflecting genuine per-lap variance, and a ranked top-N can surface the
    same (lap, corner) twice under two labels instead of naming two
    distinct places to fix.

    Decision (recorded per the fix request): both read surfaces dedupe to
    ONE entry per (lap_number, corner_id) -- a driver wants N distinct
    places to work on, not the same corner twice with two labels.

    WHICH ROW SURVIVES IS NOT ARBITRARY (fix round 2). The original kept
    "the first row seen", on the reasoning that duplicates share a
    ``time_cost_s`` so the choice cannot move an aggregate. True for the
    aggregates -- and irrelevant to the driver, who is shown the surviving
    row's ``event_type`` and told to work on THAT. Measured on
    data/raw/OK_R4.csv after the onset fix, ``over_slowing`` and
    ``late_throttle`` co-fire on 39 of 57 measured late_throttle events
    (68%), and those co-firing events carry the weight (median 9.0 m /
    0.181 s versus 7.5 m / 0.057 s for the 18 that fire alone). So on 68% of
    them, WHICH OF
    TWO DIFFERENT CORRECTIONS the driver is shown was being decided by SQL
    row order.

    The priority below is explicit and documented. ``over_slowing`` wins:
    it is the direct measurement (this lap's apex speed against the driver's
    own best at this corner), whereas ``late_throttle`` is largely derived
    from it -- the onset's partial correlation with corner time after
    controlling for apex speed is ~0.36, i.e. real but small, so most of what
    a late_throttle event says is what over_slowing already said. See
    s10b_corners' `_assign_throttle_onsets` block comment for the numbers.

    THE LOSER IS NOT DISCARDED. Its type and magnitude are recorded on the
    survivor's ``evidence["also_fired"]`` so a read surface can render ONE
    item carrying both facets ("you were 1.4 m/s down at the apex AND 12.4 m
    later back on the power") instead of two competing ones. Dropping it
    outright would have been the second way to lose the same information.

    Order-independent by construction: the survivor is chosen by priority,
    not by position, so any permutation of ``rows`` yields the same result.
    Rows within one key that share a priority (there is at most one row per
    (lap, corner, event_type) -- the table's UNIQUE key -- so this only
    arises for an unrecognised type) fall back to first-seen, and the
    surviving ORDER of distinct keys still follows the caller's sort.
    """
    # Lower number wins. Unlisted types sort last but still beat nothing.
    priority = {
        "over_slowing": 0,
        "late_throttle": 1,
        "re_braking": 2,
        "envelope_under_use": 3,
    }

    def _rank(row: dict) -> int:
        return priority.get(row.get("event_type"), len(priority))

    best: dict[tuple[Any, Any], dict] = {}
    order: list[tuple[Any, Any]] = []
    companions: dict[tuple[Any, Any], list[dict]] = {}
    for r in rows:
        key = (r.get("lap_number"), r.get("corner_id"))
        if key not in best:
            best[key] = r
            order.append(key)
            companions[key] = []
            continue
        incumbent = best[key]
        if _rank(r) < _rank(incumbent):
            best[key] = r
            companions[key].append(incumbent)
        else:
            companions[key].append(r)

    out = []
    for key in order:
        survivor = dict(best[key])
        # Only rows that actually carry a type can contribute a facet.
        # `SELECT_TIME_COSTS_FOR_CONSISTENCY` selects lap/corner/cost only, so
        # its rows have no `event_type` -- recording an `also_fired` entry of
        # `{"event_type": None}` there would dress a cost-only row up as
        # carrying detector detail it never had.
        losers = [l for l in (companions.get(key) or []) if l.get("event_type")]
        if losers and survivor.get("event_type"):
            evidence = dict(survivor.get("evidence") or {})
            evidence["also_fired"] = [
                {
                    "event_type": l.get("event_type"),
                    "magnitude": l.get("magnitude"),
                    "magnitude_unit": l.get("magnitude_unit"),
                }
                for l in sorted(losers, key=_rank)
            ]
            survivor["evidence"] = evidence
        out.append(survivor)
    return out


def get_ranked_events(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int = 10,
) -> list[dict]:
    """The ranked "what should I fix next" surface: this session's driving
    events ordered by ``time_cost_s`` DESC (biggest gap-to-own-best-time
    first), one entry per distinct (lap_number, corner_id) -- see
    ``_dedupe_by_lap_corner``. See ``SELECT_RANKED_EVENTS`` for why
    NULL-cost events (re_braking, envelope_under_use) are excluded rather
    than sorted last.

    Dedup happens BEFORE the limit is applied (fix round 1): the query
    fetches every qualifying row, then this function dedupes the full set
    and only THEN slices to ``limit``. Limiting first would let a
    duplicate pair consume two of the caller's requested slots and return
    fewer than ``limit`` distinct problems while the response still looked
    full.
    """
    rows = conn.execute(Q.SELECT_RANKED_EVENTS, {
        "session_id": session_id,
    }).fetchall()
    events = _dedupe_by_lap_corner([_row_to_dict(r) for r in rows])
    limit = _safe_int(limit) or 10
    return events[:limit]


def get_corner_consistency(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """The "where am I unreliable" surface: per corner_id, best/median/
    worst/spread of ``time_cost_s`` across this session's events, one
    observation per distinct (lap_number, corner_id) -- see
    ``_dedupe_by_lap_corner``.

    ``worst_s`` is the largest (costliest) ``time_cost_s`` seen at that
    corner, ``best_s`` the smallest, ``spread_s = worst_s - best_s``. A
    corner with no cost-bearing events (only re_braking/envelope_under_use
    fired there) has nothing to aggregate and is omitted, not zero-filled.
    """
    rows = conn.execute(Q.SELECT_TIME_COSTS_FOR_CONSISTENCY, {
        "session_id": session_id,
    }).fetchall()
    rows = _dedupe_by_lap_corner([dict(r) for r in rows])

    by_corner: dict[Any, list[float]] = {}
    for r in rows:
        cid = r.get("corner_id")
        cost = _safe_float(r.get("time_cost_s"))
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
