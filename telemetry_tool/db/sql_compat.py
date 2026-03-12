"""
SQL dialect compatibility layer.

When ``USE_PG=1``, translates SQLite-flavoured SQL into PostgreSQL-compatible
SQL at call time.  When the flag is off (or absent) the input is returned
unchanged so existing SQLite code is never affected.

Translations performed
----------------------
* Named parameters:  ``:name``  ->  ``%(name)s``
* Positional params:  ``?``     ->  ``%s``
* ``INSERT OR IGNORE INTO <table>``  ->  ``INSERT INTO <table> ... ON CONFLICT DO NOTHING``
* ``INSERT OR REPLACE INTO <table> (cols) VALUES (vals)``
  ->  ``INSERT INTO <table> (cols) VALUES (vals) ON CONFLICT DO UPDATE SET col=excluded.col, ...``

Safety
------
* LIKE patterns containing ``%`` are preserved (never confused with ``%s``).
* PostgreSQL ``::`` type-casts are preserved (never confused with ``:name``).
"""

from __future__ import annotations

import os
import re


def _is_pg() -> bool:
    """Check USE_PG at *call time* (not import time)."""
    return os.environ.get("USE_PG", "0") == "1"


# ---------------------------------------------------------------------------
# Parameter translation
# ---------------------------------------------------------------------------

# Matches :name but NOT ::typecast.
# Negative lookbehind for `:` ensures we skip `::text`, `::int`, etc.
# Negative lookbehind for `%` ensures we skip already-translated `%(name)s`.
_NAMED_PARAM_RE = re.compile(
    r"(?<!:)(?<!%)(?<!\w):([a-zA-Z_]\w*)"
)

# Matches a lone `?` that is a positional param placeholder.
# Negative lookbehind/ahead to avoid matching inside strings is hard in pure
# regex, but SQLite positional params never appear inside identifiers.
_POSITIONAL_PARAM_RE = re.compile(r"\?")

# INSERT OR IGNORE INTO <table>
_INSERT_OR_IGNORE_RE = re.compile(
    r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
    re.IGNORECASE,
)

# INSERT OR REPLACE INTO <table> (<cols>) VALUES (<vals>)
# Captures: table name, column list, everything after VALUES
_INSERT_OR_REPLACE_RE = re.compile(
    r"\bINSERT\s+OR\s+REPLACE\s+INTO\s+"  # keyword preamble
    r"(\w+)\s*"                             # group 1: table name
    r"\(([^)]+)\)\s*"                       # group 2: column list
    r"VALUES\s*"                            # VALUES keyword
    r"\(([^)]+)\)",                         # group 3: value list
    re.IGNORECASE | re.DOTALL,
)


_LITERAL_PERCENT_RE = re.compile(
    r"%(?!\([a-zA-Z_]\w*\)s)"  # % NOT followed by (name)s
    r"(?!%)"                    # NOT already doubled %%
    r"(?!s(?![a-zA-Z_]))"      # NOT %s positional param
)


def _translate_named_params(sql: str) -> str:
    """Convert ``:name`` to ``%(name)s``, skipping ``::`` casts.

    Also escapes literal ``%`` characters (e.g. in LIKE patterns) to ``%%``
    so psycopg2 doesn't treat them as format specifiers.
    """
    sql = _NAMED_PARAM_RE.sub(r"%(\1)s", sql)
    sql = _LITERAL_PERCENT_RE.sub("%%", sql)
    return sql


def _translate_positional_params(sql: str) -> str:
    """Convert ``?`` to ``%s``."""
    return _POSITIONAL_PARAM_RE.sub("%s", sql)


def _translate_insert_or_ignore(sql: str) -> str:
    """``INSERT OR IGNORE INTO tbl`` -> ``INSERT INTO tbl ... ON CONFLICT DO NOTHING``."""
    if not _INSERT_OR_IGNORE_RE.search(sql):
        return sql
    sql = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", sql)
    # Append ON CONFLICT DO NOTHING before the trailing semicolon (if any).
    sql = sql.rstrip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip() + "\nON CONFLICT DO NOTHING;"
    else:
        sql = sql + "\nON CONFLICT DO NOTHING"
    return sql



# Mapping of table name → conflict target columns for INSERT OR REPLACE
# translation.  These match the UNIQUE / PRIMARY KEY constraints defined
# in the Alembic migrations (001 + 008).
_PG_CONFLICT_TARGETS: dict[str, tuple[str, ...]] = {
    "sessions":              ("session_id",),
    "laps":                  ("session_id", "lap_number"),
    "gps_traces":            ("session_id", "lap_number"),
    "score_details":         ("session_id",),
    "condition_phases":      ("session_id", "phase_id"),
    "corner_metrics":        ("session_id", "lap_number", "corner_id"),
    "theoretical_data":      ("session_id",),
    "reference_lines":       ("session_id",),
    "session_sectors":       ("session_id", "sector_index"),
    "data_health":           ("session_id",),
    "session_tags":          ("session_id", "tag"),
    "session_weather":       ("session_id",),
    "weekend_sessions":      ("weekend_id", "session_id"),
    "condition_markers":     ("session_id", "lap_number"),
    "driver_progression":    ("driver_id", "session_id"),
    "driving_style_features": ("driver_id", "session_id"),
    "export_templates":      ("template_name",),
    "user_corners":          ("session_id", "corner_index"),
    "stint_analysis":        ("session_id", "stint_number"),
    "predefined_track_coords": ("track_name",),
}


def _translate_insert_or_replace(sql: str) -> str:
    """
    ``INSERT OR REPLACE INTO tbl (a, b) VALUES (:a, :b)``
    ->
    ``INSERT INTO tbl (a, b) VALUES (:a, :b)
      ON CONFLICT (pk_col) DO UPDATE SET b = EXCLUDED.b``

    Uses ``_PG_CONFLICT_TARGETS`` to look up the correct conflict columns
    for each table.  Falls back to stripping OR REPLACE (with a warning)
    for unknown tables.
    """
    m = _INSERT_OR_REPLACE_RE.search(sql)
    if not m:
        return sql

    table = m.group(1)
    cols_raw = m.group(2)
    vals_raw = m.group(3)
    cols = [c.strip() for c in cols_raw.split(",")]

    conflict_cols = _PG_CONFLICT_TARGETS.get(table)
    if conflict_cols is None:
        import logging
        logging.getLogger(__name__).warning(
            "INSERT OR REPLACE: no conflict target for table %r — "
            "stripping OR REPLACE (may fail on duplicates): %s",
            table, sql[:120],
        )
        col_list = ", ".join(cols)
        result = f"INSERT INTO {table} ({col_list}) VALUES ({vals_raw})"
    else:
        conflict_target = ", ".join(conflict_cols)
        conflict_set = set(conflict_cols)
        update_cols = [c for c in cols if c not in conflict_set]

        col_list = ", ".join(cols)
        result = f"INSERT INTO {table} ({col_list}) VALUES ({vals_raw})"
        if update_cols:
            update_clause = ", ".join(
                f"{c} = EXCLUDED.{c}" for c in update_cols
            )
            result += f"\nON CONFLICT ({conflict_target}) DO UPDATE SET {update_clause}"
        else:
            result += f"\nON CONFLICT ({conflict_target}) DO NOTHING"

    # Preserve trailing semicolon.
    tail = sql[m.end():].strip()
    if tail.startswith(";"):
        result += ";"
        tail = tail[1:].strip()
    if tail:
        result += "\n" + tail

    # Preserve any SQL before the INSERT (e.g. leading whitespace/comments).
    head = sql[:m.start()]
    return head + result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SQLITE_DATETIME_NOW_RE = re.compile(
    r"\bdatetime\(\s*'now'\s*\)", re.IGNORECASE
)

# Boolean literal comparison: SQLite uses 1/0, PG uses true/false.
# Matches column_name = 1 or column_name = 0 for known boolean columns.
_BOOL_COLUMNS = {"is_valid", "is_best", "is_joker", "is_active", "is_deleted",
                 "email_verified", "two_factor_enabled", "setup_complete"}
_BOOL_COMPARE_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in _BOOL_COLUMNS) + r")\s*=\s*([01])\b"
)


def _translate_sqlite_functions(sql: str) -> str:
    """Convert SQLite functions to PostgreSQL equivalents.

    ``datetime('now')`` -> ``NOW()``
    """
    return _SQLITE_DATETIME_NOW_RE.sub("NOW()", sql)


def _translate_boolean_literals(sql: str) -> str:
    """Convert ``is_valid = 1`` -> ``is_valid = true``, ``= 0`` -> ``= false``.

    SQLite stores booleans as integers 0/1; PostgreSQL boolean columns
    reject integer comparison.
    """
    def _bool_repl(m: re.Match) -> str:
        col = m.group(1)
        val = "true" if m.group(2) == "1" else "false"
        return f"{col} = {val}"
    return _BOOL_COMPARE_RE.sub(_bool_repl, sql)


def translate_params(sql: str) -> str:
    """
    Translate a SQLite-flavoured SQL string for PostgreSQL.

    Checks ``USE_PG`` at **call time** so tests can toggle the flag
    per-test without import-time caching.

    When ``USE_PG`` is not ``"1"`` the input is returned unchanged.
    """
    if not _is_pg():
        return sql

    sql = _translate_insert_or_ignore(sql)
    sql = _translate_insert_or_replace(sql)
    sql = _translate_sqlite_functions(sql)
    sql = _translate_boolean_literals(sql)
    sql = _translate_named_params(sql)
    sql = _translate_positional_params(sql)
    return sql
