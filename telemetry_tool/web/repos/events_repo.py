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
import logging
import math
import sqlite3
from statistics import median
from typing import Any, Iterable

import numpy as np

from db import queries as Q
from web.repos._helpers import _safe_float

logger = logging.getLogger(__name__)


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
            # Spec SS5.1 provenance. Bound unconditionally: a row without
            # it is a percentage nobody can trace to a baseline.
            "anchor_tier": ev.anchor_tier,
            "anchor_reason": ev.anchor_reason,
            "evidence_json": json.dumps(_json_safe(ev.evidence or {})),
        })
        count += 1
    return count


def _row_to_dict(row: Any) -> dict:
    """One event row as a payload dict.

    Two derived fields are added here rather than stored, because both are
    properties of the event TYPE, not of the row -- storing them would let
    one row disagree with its own detector's contract:

    ``time_cost_attribution`` -- may a consumer present ``time_cost_s`` as
    CAUSED by this event's own ``magnitude``? See
    ``driving_events.TIME_COST_ATTRIBUTION``. ``late_throttle`` is
    ``"context"``: its cost is the identical corner-time gap ``over_slowing``
    reports for the same corner-lap, and its added information beyond apex
    speed is not distinguishable from zero, so rendering the metres as a
    standalone claim or as the cause of the cost attributes one measurement
    twice. That prohibition previously lived only in a source comment, and
    Phase 3 reads this response, not the source.

    ``magnitude_is_standalone_quotable`` -- the same constraint stated for
    the magnitude on its own, so a renderer does not have to infer it from
    the attribution value.
    """
    import driving_events as de

    d = dict(row)
    raw = d.pop("evidence_json", None)
    # POPPED, not read: the payload used to carry the evidence TWICE, once
    # parsed as `evidence` and once as the raw JSON string. Dropping the raw
    # copy halves the response size and the per-row memory the ranked read
    # holds while deduping.
    if isinstance(raw, str):
        try:
            d["evidence"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            d["evidence"] = {}
    else:
        d["evidence"] = raw or {}

    attribution = de.TIME_COST_ATTRIBUTION.get(
        d.get("event_type"), de.ATTRIBUTION_CONTEXT)
    d["time_cost_attribution"] = attribution
    d["magnitude_is_standalone_quotable"] = (
        attribution != de.ATTRIBUTION_CONTEXT)
    return d


_DEDUPE_PRIORITY: dict[str, int] = {
    "over_slowing": 0,
    "late_throttle": 1,
    "re_braking": 2,
    "envelope_under_use": 3,
}
"""Which detector's label survives when several fire on one (lap, corner).

Kept as an explicit ordering rather than derived from ``EVENT_TYPES`` (a
frozenset has no order), but its COVERAGE is checked against ``EVENT_TYPES``
so a newly-registered detector cannot silently fall through to first-seen --
see ``_dedupe_by_lap_corner`` and ``_assert_dedupe_priority_is_total``.
"""


def _assert_dedupe_priority_is_total() -> None:
    """Fail loudly if a detector exists with no dedupe priority."""
    import driving_events as de

    missing = de.EVENT_TYPES - set(_DEDUPE_PRIORITY)
    extra = set(_DEDUPE_PRIORITY) - de.EVENT_TYPES
    if missing or extra:
        raise AssertionError(
            f"_DEDUPE_PRIORITY does not cover EVENT_TYPES exactly: "
            f"missing={sorted(missing)} unknown={sorted(extra)} -- an "
            f"unranked event type falls back to first-row-wins, which makes "
            f"the surviving label depend on database row order")


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
    from it -- in the canonical distance frame the onset's partial correlation
    with corner time after controlling for apex speed is +0.098 (t = 0.81),
    i.e. NOT distinguishable from zero, so what a late_throttle event says is
    what over_slowing already said. (An earlier revision of this docstring
    said "~0.36, real but small"; that figure was measured before the
    coordinate-frame fix and was largely lap length.) See s10b_corners'
    `_assign_throttle_onsets` block comment for the before/after table.

    THE LOSER IS NOT DISCARDED. Its type and magnitude are recorded on the
    survivor's ``evidence["also_fired"]`` so a read surface can render ONE
    item carrying both facets ("you were 1.4 m/s down at the apex AND 12.4 m
    later back on the power") instead of two competing ones. Dropping it
    outright would have been the second way to lose the same information.

    ``also_fired`` deliberately carries the loser's TYPE, MAGNITUDE and UNIT
    only -- NOT its own ``evidence`` blob. That is a decision, not an
    oversight: the loser's evidence duplicates the survivor's reference
    values (both detectors quote the same corner-time reference for the same
    corner-lap) and nesting one event's full evidence inside another's
    invites a read surface to present the pair as two independent
    measurements, which is precisely what the priority exists to prevent. A
    consumer that needs the loser in full can query ``driving_events``
    directly; the row is still there.

    Order-independent by construction: the survivor is chosen by priority,
    not by position, so any permutation of ``rows`` yields the same result.
    Rows within one key that share a priority (there is at most one row per
    (lap, corner, event_type) -- the table's UNIQUE key -- so this only
    arises for an unrecognised type) fall back to first-seen, and the
    surviving ORDER of distinct keys still follows the caller's sort.
    """
    # Lower number wins. Unlisted types sort last but still beat nothing.
    #
    # COVERAGE IS ASSERTED, NOT ASSUMED (fix round 2). An unranked type falls
    # back to first-seen, so a FIFTH detector added to `driving_events.
    # EVENT_TYPES` without a line here would reintroduce exactly the row-order
    # nondeterminism this function exists to remove -- verified: two unranked
    # types on one key produce two different outputs depending on input order.
    # Failing loudly at import of the first dedupe is far better than shipping
    # a silently arbitrary choice to a driver.
    _assert_dedupe_priority_is_total()
    priority = _DEDUPE_PRIORITY

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


# ── row budgets: the read surfaces are bounded, and provably so ──────────
#
# Final review, deferred minor 4. Both queries used to fetch EVERY qualifying
# row so the Python layer could dedupe before slicing. Measured here through
# the real path (tracemalloc, real SQLite, realistic evidence blobs):
# 2,937 B/row on the ranked surface and 439 B/row on the consistency one, so
# 20,000 rows peak at 58.7 MB and 8.8 MB respectively. Row count is
# `laps x corners x 2` with no cap on either anywhere in the pipeline, while
# `max_upload_size_mb` is -1 (unlimited) on the world-class and b2b plans: a
# 1,200-lap endurance session over 15 corners extrapolates to ~106 MB per
# request, times 32 gunicorn threads. With the bound, the same call peaks at
# 64 KB.

_MAX_COST_BEARING_ROWS_PER_KEY = 2
"""How many rows for ONE (lap_number, corner_id) can carry a time_cost_s.

This is what makes the ranked query's `limit*2+2` bound provably safe rather
than a guess: the table's UNIQUE key caps rows per key at one per event type,
and only this many event types ever compute a cost. Asserted against
`driving_events.TIME_COST_ATTRIBUTION` below so a fifth detector that starts
emitting a cost cannot silently invalidate the arithmetic."""

_CONSISTENCY_ROW_CAP = 20000
"""Hard ceiling for the corner-consistency surface.

It aggregates rather than slices, so there is no caller-supplied N to scale
from. 20,000 rows is ~8.8 MB peak by the measurement above (this
surface selects four columns, not the whole row), and it is far beyond any
plausible session: the real fixture produces 99 cost-bearing rows,
and even a 1,000-lap endurance run over 20 corners produces ~40,000 -- which
is exactly the case that must be capped rather than served. Hitting it is
logged as a WARNING because the aggregate is then computed over a truncated
set and is no longer representative."""


def _assert_cost_bearing_row_bound() -> None:
    """The ranked query's LIMIT is arithmetic, not a guess -- keep it true."""
    import driving_events as de

    cost_bearing = {t for t, a in de.TIME_COST_ATTRIBUTION.items()
                    if a != de.ATTRIBUTION_NO_COST}
    if len(cost_bearing) > _MAX_COST_BEARING_ROWS_PER_KEY:
        raise AssertionError(
            f"{len(cost_bearing)} event types now carry a time_cost_s "
            f"({sorted(cost_bearing)}), but SELECT_RANKED_EVENTS' "
            f"LIMIT limit*{_MAX_COST_BEARING_ROWS_PER_KEY}+2 assumes at most "
            f"{_MAX_COST_BEARING_ROWS_PER_KEY} cost-bearing rows per "
            f"(lap, corner). The bound no longer guarantees `limit` distinct "
            f"keys survive the dedupe -- raise the factor with it.")


def _ranked_row_budget(limit: int) -> int:
    """SQL row budget that provably yields >= `limit` distinct (lap, corner)
    keys after `_dedupe_by_lap_corner`."""
    _assert_cost_bearing_row_bound()
    return limit * _MAX_COST_BEARING_ROWS_PER_KEY + 2


def get_driving_events_capability(
    conn: sqlite3.Connection,
    session_id: str,
) -> dict:
    """This session's per-detector capability record, or ``{}``.

    Final review, IMPORTANT 2. `run_registry` computes "detected" /
    "not_triggered" / "insufficient" for every registered detector, the stage
    puts it on the summary, and it used to stop there -- never written, never
    served. So a session whose `10d2_grip_anchor` failed came back from the
    API as ``{"events": [], "available": false}`` with zero consistency rows,
    which is exactly what a clean session with nothing to fix returns.

    Stored in ``sessions.analysis_json`` rather than in its own table: it is
    four short strings per session, it is written by the same two blob
    writers that already run on both persistence paths, and a table would
    need its own migration, RLS policy, cascade registrations and retention
    entry to carry less information than one JSON key.

    Returns ``{}`` -- never None -- when the blob is absent, unparseable, or
    predates this field. The caller distinguishes "no record" from "every
    detector reported" by the emptiness, which is why the endpoint also
    serves `capability_available` explicitly.

    Reads through the RLS-scoped request connection the caller already
    resolved the session on, so it inherits that tenancy check.
    """
    try:
        from web.repos.analysis_repo import get_analysis_json

        analysis = get_analysis_json(conn, session_id) or {}
    except Exception:
        return {}
    cap = analysis.get("driving_events_capability")
    return cap if isinstance(cap, dict) else {}


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
    limit = _safe_int(limit) or 10
    limit = max(1, limit)
    rows = conn.execute(Q.SELECT_RANKED_EVENTS, {
        "session_id": session_id,
        "row_budget": _ranked_row_budget(limit),
    }).fetchall()
    events = _dedupe_by_lap_corner([_row_to_dict(r) for r in rows])
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
        "row_budget": _CONSISTENCY_ROW_CAP,
    }).fetchall()
    if len(rows) >= _CONSISTENCY_ROW_CAP:
        # Loudly, because a truncated aggregate is a WRONG aggregate: the
        # per-corner median would be computed over an arbitrary prefix of the
        # session. Logged rather than raised so the surface still answers,
        # but nobody gets to read a skewed median as a measured one.
        logger.warning(
            "corner-consistency hit the %d-row cap for session %s -- the "
            "per-corner aggregates are computed over a TRUNCATED set and are "
            "not representative of the whole session",
            _CONSISTENCY_ROW_CAP, session_id,
        )
    rows = _dedupe_by_lap_corner([dict(r) for r in rows])

    by_corner: dict[Any, list[float]] = {}
    anchors_by_corner: dict[Any, set] = {}
    for r in rows:
        cid = r.get("corner_id")
        cost = _safe_float(r.get("time_cost_s"))
        if cid is None or cost is None:
            continue
        by_corner.setdefault(cid, []).append(cost)
        anchors_by_corner.setdefault(cid, set()).add(r.get("anchor_tier"))

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
            # Spec SS5.1 applies to AGGREGATES too -- these four numbers are
            # quoted to a driver, so they must say what they were measured
            # against. A LIST, not a scalar: the aggregate is over several
            # events and nothing guarantees they share a tier, so collapsing
            # a mixed set to one label would be the fabrication this field
            # exists to prevent. In practice both cost-bearing detectors
            # anchor on `driver_best_session`, so this is normally a
            # one-element list -- and a second element is real information.
            "anchor_tiers": sorted(anchors_by_corner.get(cid, set()),
                                   key=lambda t: (t is None, str(t))),
        })
    out.sort(key=lambda r: r["corner_id"])
    return out
