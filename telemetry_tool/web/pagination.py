"""Cursor-based keyset pagination utilities.

Implements composite-cursor pagination using ``(sort_value, id)`` pairs
encoded as base64url JSON blobs.  This avoids the OFFSET-drift problem
of traditional pagination while remaining fully stateless.

Usage::

    from web.pagination import paginate_query, pagination_meta

    rows, next_cursor, has_more = paginate_query(
        conn, "SELECT * FROM sessions", {},
        sort_col="created_at", id_col="id",
        cursor_str=request.args.get("cursor"),
        limit=25, descending=True,
    )
    meta = pagination_meta(next_cursor, has_more, 25)
    return api_response(rows, meta={"pagination": meta})
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_LIMIT = 100
_MIN_LIMIT = 1


# ---------------------------------------------------------------------------
# Cursor encode / decode
# ---------------------------------------------------------------------------

def encode_cursor(sort_value: Any, id_value: Any) -> str:
    """Encode a composite cursor as a base64url string.

    The cursor payload is ``{"s": sort_value, "id": id_value}`` — compact
    keys to keep the token short.
    """
    payload = json.dumps({"s": sort_value, "id": id_value}, default=str)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor_str: str | None) -> dict | None:
    """Decode a cursor string back to ``{"s": ..., "id": ...}``.

    Returns ``None`` for any invalid input (bad base64, bad JSON, missing
    keys) — callers treat ``None`` as "no cursor / first page".
    """
    if not cursor_str:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode())
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict) or "s" not in data or "id" not in data:
        return None
    return data


# ---------------------------------------------------------------------------
# SQL keyset clause builder
# ---------------------------------------------------------------------------

def build_keyset_clause(
    cursor: dict | None,
    sort_col: str,
    id_col: str = "id",
    descending: bool = True,
) -> tuple[str, dict]:
    """Build a SQL WHERE fragment for keyset pagination.

    Parameters
    ----------
    cursor : dict | None
        Decoded cursor (from :func:`decode_cursor`).  ``None`` means
        first page — returns an empty clause.
    sort_col : str
        Column name used for ordering (e.g. ``"created_at"``).
    id_col : str
        Tie-breaking column, usually the primary key.
    descending : bool
        ``True`` for ``ORDER BY sort_col DESC, id_col DESC``.

    Returns
    -------
    (clause, params)
        *clause* is a SQL fragment like
        ``AND (score, id) < (:cursor_sort, :cursor_id)``
        or an empty string when *cursor* is ``None``.
        *params* is a dict with ``cursor_sort`` and ``cursor_id`` keys
        (empty dict when *cursor* is ``None``).
    """
    if cursor is None:
        return "", {}

    op = "<" if descending else ">"
    clause = f"AND ({sort_col}, {id_col}) {op} (:cursor_sort, :cursor_id)"
    params = {"cursor_sort": cursor["s"], "cursor_id": cursor["id"]}
    return clause, params


# ---------------------------------------------------------------------------
# Query executor
# ---------------------------------------------------------------------------

def paginate_query(
    conn,
    base_sql: str,
    params: dict,
    sort_col: str,
    id_col: str,
    cursor_str: str | None,
    limit: int,
    descending: bool = True,
) -> tuple[list[dict], str | None, bool]:
    """Execute *base_sql* with keyset pagination.

    Parameters
    ----------
    conn
        A DB-API 2 connection (SQLite or similar) whose ``.execute()``
        accepts named parameters (``":name"`` style).
    base_sql : str
        The base ``SELECT`` statement.  Must NOT include ``ORDER BY``
        or ``LIMIT``.  May include ``WHERE`` clauses.
    params : dict
        Named parameters for *base_sql*.
    sort_col, id_col : str
        Columns used for ordering and cursor positioning.
    cursor_str : str | None
        Opaque cursor from the client (or ``None`` for first page).
    limit : int
        Requested page size.  Clamped to [1, 100].
    descending : bool
        Sort direction.

    Returns
    -------
    (rows, next_cursor, has_more)
        *rows* is a list of dicts (up to *limit* items).
        *next_cursor* is the cursor for the next page (or ``None``).
        *has_more* indicates whether more rows exist beyond this page.
    """
    # Clamp limit
    limit = max(_MIN_LIMIT, min(limit, _MAX_LIMIT))

    # Decode cursor and build keyset clause
    cursor = decode_cursor(cursor_str)
    keyset_clause, keyset_params = build_keyset_clause(
        cursor, sort_col, id_col, descending
    )

    # Merge params
    merged = {**params, **keyset_params}

    # Determine if base_sql already has a WHERE clause
    upper_sql = base_sql.upper().strip()
    if keyset_clause:
        if "WHERE" in upper_sql:
            sql = f"{base_sql} {keyset_clause}"
        else:
            # Replace leading "AND" with "WHERE"
            sql = f"{base_sql} WHERE {keyset_clause[4:]}"
    else:
        sql = base_sql

    # Add ORDER BY and LIMIT (fetch limit+1 to detect has_more)
    direction = "DESC" if descending else "ASC"
    sql += f" ORDER BY {sort_col} {direction}, {id_col} {direction}"
    sql += f" LIMIT {limit + 1}"

    # Execute
    cursor_db = conn.execute(sql, merged)
    raw_rows = cursor_db.fetchall()

    # Convert to list of dicts
    rows = [dict(r) for r in raw_rows]

    # Determine has_more
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    # Build next cursor from last row
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(last[sort_col], last[id_col])

    return rows, next_cursor, has_more


# ---------------------------------------------------------------------------
# Meta builder
# ---------------------------------------------------------------------------

def pagination_meta(
    next_cursor: str | None,
    has_more: bool,
    limit: int,
) -> dict[str, Any]:
    """Format pagination metadata for the response envelope.

    Returns a dict suitable for inclusion in the ``meta.pagination``
    field of the API response::

        {"next_cursor": "eyJz...", "has_more": true, "limit": 25}
    """
    return {
        "next_cursor": next_cursor,
        "has_more": has_more,
        "limit": limit,
    }
