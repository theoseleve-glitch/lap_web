"""
onboarding/repo.py
------------------
Data-access layer over ``track_onboarding_requests`` (migration 081).

Its hardest job is a de-duplicated, race-safe upsert: concurrent sessions for
the same unmapped track must produce ONE open request, with the loser
attaching its ``session_ref`` instead of erroring. That is done atomically in
SQL via the partial unique index ``ux_onboarding_open(track_key) WHERE status
<> 'blessed'`` as the ``ON CONFLICT`` arbiter -- no application-level locking
or retry loop is needed.

Connection-agnostic: accepts a raw psycopg2 connection (used in tests) or a
PgConnectionWrapper (used in production), matching the convention in
``track_surface/racing_line_repo.py``. Callers are responsible for
commit/rollback.

Consumed by: onboarding/service.py (Task 6), tasks/onboarding_tasks.py
(Task 10).
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Columns settable via set_status()'s **fields. Whitelisted so field names
# can never be interpolated from unchecked input into the SQL text.
_SETTABLE_FIELDS: dict[str, str] = {
    "track_label": "text",
    "fingerprint": "jsonb",
    "bbox": "jsonb",
    "first_session_ref": "text",
    "session_refs": "jsonb",
    "session_count": "int",
    "draft_status": "text",
    "draft_path": "text",
    "token_jti": "text",
    "error": "text",
    "emailed_at": "timestamp",
    "blessed_at": "timestamp",
}

_ALL_COLUMNS = (
    "id", "track_key", "track_label", "fingerprint", "status", "bbox",
    "draft_centerline", "first_session_ref", "session_refs", "session_count",
    "vehicle_classes", "draft_status", "draft_path", "token_jti", "error",
    "created_at", "updated_at", "emailed_at", "blessed_at",
)

_JSONB_COLUMNS = {
    "fingerprint", "bbox", "draft_centerline", "session_refs", "vehicle_classes",
}


def _row_to_dict(row: Any) -> dict:
    """Normalise a fetched row into a plain dict, decoding JSONB columns.

    Handles both dict-keyed rows (psycopg2 RealDictCursor, used in tests)
    and plain tuple rows (PgConnectionWrapper.cursor(), used in production)
    -- same dual-shape handling as ``racing_line_repo.get_racing_lines``.
    """
    if isinstance(row, dict):
        d = {col: row.get(col) for col in _ALL_COLUMNS}
    else:
        d = dict(zip(_ALL_COLUMNS, row))
    for col in _JSONB_COLUMNS:
        val = d.get(col)
        if isinstance(val, str):
            d[col] = json.loads(val)
    return d


def upsert_open_request(
    conn: Any,
    *,
    track_key: str,
    track_label: str | None,
    fingerprint: dict | None,
    bbox: dict | None,
    session_ref: str,
    draft_centerline: list | None = None,
    vehicle_classes: list | None = None,
) -> tuple[str, bool]:
    """Atomically create-or-attach-to the single open request for a track.

    Race-safe: the ``ON CONFLICT (track_key) WHERE status <> 'blessed'``
    arbiter matches the partial unique index ``ux_onboarding_open`` from
    migration 081 -- concurrent callers for the same open track_key resolve
    to one row, never an error. The predicate is restated here (Postgres
    requires the inference predicate to match the index definition exactly).

    On conflict, ``session_refs`` gets the new ``session_ref`` appended only
    if not already present (``@>`` containment check) and only up to 50
    entries, so a flapping/retried caller can't grow the array unbounded or
    duplicate itself. ``draft_centerline`` (the downsampled lon/lat polyline
    of one driven lap, migration 081) uses first-non-null-wins semantics on
    conflict (``COALESCE(existing, EXCLUDED)``) instead: it's a single
    representative geometry, not an accumulating log like ``session_refs``,
    so a later attaching session must never clobber the one already stored.

    ``vehicle_classes`` (final-review finding I2 -- migration 081 follow-up)
    is a small accumulating SET, same intent as ``session_refs`` but merged
    as a union rather than a single-value append (a track can be onboarded
    by sessions across several vehicle classes): on conflict, existing and
    incoming arrays are combined via ``jsonb_array_elements_text`` +
    ``array_agg(DISTINCT ...)`` so the result never contains duplicates.
    ``None``/absent is treated as an empty list on both insert and conflict.

    Returns ``(request_id, created)`` where ``created=False`` means this
    call attached to a pre-existing open row rather than inserting one.
    """
    fingerprint_json = json.dumps(fingerprint) if fingerprint is not None else None
    bbox_json = json.dumps(bbox) if bbox is not None else None
    draft_centerline_json = (
        json.dumps(draft_centerline) if draft_centerline is not None else None
    )
    vehicle_classes_json = (
        json.dumps(vehicle_classes) if vehicle_classes is not None else None
    )

    sql = """
        INSERT INTO track_onboarding_requests
            (id, track_key, track_label, fingerprint, status, bbox, draft_centerline,
             first_session_ref, session_refs, session_count, vehicle_classes,
             created_at, updated_at)
        VALUES
            (gen_random_uuid(), %(track_key)s, %(track_label)s, %(fingerprint)s::jsonb, 'requested', %(bbox)s::jsonb,
             %(draft_centerline)s::jsonb, %(session_ref)s, to_jsonb(ARRAY[%(session_ref)s]::text[]), 1,
             COALESCE(%(vehicle_classes)s::jsonb, '[]'::jsonb), now(), now())
        ON CONFLICT (track_key) WHERE status <> 'blessed'
        DO UPDATE SET
            draft_centerline = COALESCE(
                track_onboarding_requests.draft_centerline, EXCLUDED.draft_centerline
            ),
            session_refs = CASE
                WHEN track_onboarding_requests.session_refs @> to_jsonb(%(session_ref)s::text)
                     OR jsonb_array_length(track_onboarding_requests.session_refs) >= 50
                THEN track_onboarding_requests.session_refs
                ELSE track_onboarding_requests.session_refs || to_jsonb(ARRAY[%(session_ref)s]::text[])
            END,
            session_count = LEAST(track_onboarding_requests.session_count + 1, 999999),
            vehicle_classes = (
                SELECT COALESCE(to_jsonb(array_agg(DISTINCT v)), '[]'::jsonb)
                FROM jsonb_array_elements_text(
                    COALESCE(track_onboarding_requests.vehicle_classes, '[]'::jsonb)
                    || COALESCE(EXCLUDED.vehicle_classes, '[]'::jsonb)
                ) AS v
            ),
            updated_at = now()
        RETURNING id, (xmax = 0) AS created
    """
    params = {
        "track_key": track_key,
        "track_label": track_label,
        "fingerprint": fingerprint_json,
        "bbox": bbox_json,
        "draft_centerline": draft_centerline_json,
        "session_ref": session_ref,
        "vehicle_classes": vehicle_classes_json,
    }
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        row = cur.fetchone()
    finally:
        cur.close()

    if isinstance(row, dict):
        request_id, created = row["id"], row["created"]
    else:
        request_id, created = row[0], row[1]
    logger.debug(
        "upsert_open_request: track_key=%s session_ref=%s created=%s",
        track_key, session_ref, created,
    )
    return str(request_id), bool(created)


def set_status(
    conn: Any,
    request_id: str,
    new_status: str,
    **fields: Any,
) -> bool:
    """Conditionally set ``status`` (+ any whitelisted extra columns).

    ``WHERE id=%(id)s AND status <> 'blessed'`` -- a blessed request is
    terminal and can never be overwritten by a later worker/state write.

    ``**fields`` becomes additional ``SET`` columns; each key MUST be in
    ``_SETTABLE_FIELDS`` (raises ``ValueError`` otherwise) so column names
    are never taken from unchecked input and interpolated into SQL text.

    Returns True iff a row was actually updated (rowcount > 0) -- False
    means either the id doesn't exist or the row is already blessed.
    """
    unknown = set(fields) - set(_SETTABLE_FIELDS)
    if unknown:
        raise ValueError(f"set_status: unsupported field(s): {sorted(unknown)}")

    set_parts = ["status = %(status)s", "updated_at = now()"]
    params: dict[str, Any] = {"id": request_id, "status": new_status}
    for col, value in fields.items():
        kind = _SETTABLE_FIELDS[col]
        if kind == "jsonb" and value is not None and not isinstance(value, str):
            value = json.dumps(value)
        params[col] = value
        if kind == "jsonb":
            set_parts.append(f"{col} = %({col})s::jsonb")
        else:
            set_parts.append(f"{col} = %({col})s")

    sql = (
        "UPDATE track_onboarding_requests\n"
        f"SET {', '.join(set_parts)}\n"
        "WHERE id = %(id)s AND status <> 'blessed'"
    )
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        rowcount = cur.rowcount
    finally:
        cur.close()
    return bool(rowcount and rowcount > 0)


def claim_for_drafting(conn: Any, request_id: str) -> bool:
    """Compare-and-set claim used by the drafting Celery task.

    Only a request in ``requested`` or ``draft_failed`` can be claimed; a
    second concurrent/retried claim on the same id sees no matching row and
    returns False (idempotent -- the Celery task treats False as "someone
    else is already drafting this, or it's past that stage").
    """
    sql = """
        UPDATE track_onboarding_requests
        SET status = 'drafting', updated_at = now()
        WHERE id = %(id)s AND status IN ('requested', 'draft_failed')
        RETURNING id
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, {"id": request_id})
        row = cur.fetchone()
    finally:
        cur.close()
    return row is not None


def get(conn: Any, request_id: str) -> dict | None:
    """Fetch one request row as a plain dict, or None if it doesn't exist."""
    sql = f"""
        SELECT {', '.join(_ALL_COLUMNS)}
        FROM track_onboarding_requests
        WHERE id = %(id)s
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, {"id": request_id})
        row = cur.fetchone()
    finally:
        cur.close()
    if row is None:
        return None
    return _row_to_dict(row)


def find_stale_unemailed(conn: Any, older_than_minutes: int = 60) -> list[str]:
    """IDs of requests stuck mid-flight: not blessed, never emailed, and not
    touched for ``older_than_minutes`` minutes.

    Backstop for a worker crash between drafting and emailing (e.g. between
    the ``drafted``/``token_jti`` write and the final ``emailed`` write in
    ``tasks.onboarding_tasks._run_draft_and_notify``) that would otherwise
    leave the request un-emailable forever. Used by the ``reconcile_onboarding``
    beat task.
    """
    sql = """
        SELECT id
        FROM track_onboarding_requests
        WHERE status <> 'blessed'
          AND emailed_at IS NULL
          AND updated_at < now() - (%(mins)s || ' minutes')::interval
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, {"mins": older_than_minutes})
        rows = cur.fetchall()
    finally:
        cur.close()
    ids = []
    for row in rows:
        if isinstance(row, dict):
            ids.append(str(row["id"]))
        else:
            ids.append(str(row[0]))
    return ids


def reset_for_retry(conn: Any, request_id: str) -> bool:
    """Reset a stale request back to ``requested`` so it can be re-drafted.

    Idempotent and guarded exactly like ``set_status``: the
    ``WHERE id = %(id)s AND status <> 'blessed' AND emailed_at IS NULL``
    clause means a request that has already been blessed or already emailed
    is never touched, even if this is called on it by mistake (e.g. a race
    where the original task finished between ``find_stale_unemailed`` and
    this call). Clears the drafting artifacts (``draft_status``,
    ``draft_path``, ``token_jti``) so ``draft_and_notify`` starts clean.

    Returns True iff a row was actually reset (rowcount > 0).
    """
    sql = """
        UPDATE track_onboarding_requests
        SET status = 'requested',
            draft_status = NULL,
            draft_path = NULL,
            token_jti = NULL,
            updated_at = now()
        WHERE id = %(id)s AND status <> 'blessed' AND emailed_at IS NULL
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, {"id": request_id})
        rowcount = cur.rowcount
    finally:
        cur.close()
    return bool(rowcount and rowcount > 0)
