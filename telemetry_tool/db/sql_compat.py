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


def _translate_named_params(sql: str) -> str:
    """Convert ``:name`` to ``%(name)s``, skipping ``::`` casts."""
    return _NAMED_PARAM_RE.sub(r"%(\1)s", sql)


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


def _translate_insert_or_replace(sql: str) -> str:
    """
    ``INSERT OR REPLACE INTO tbl (a, b) VALUES (:a, :b)``
    ->
    ``INSERT INTO tbl (a, b) VALUES (:a, :b)
      ON CONFLICT DO UPDATE SET a = EXCLUDED.a, b = EXCLUDED.b``

    This is a *basic* translation that generates an unqualified
    ``ON CONFLICT DO UPDATE`` (no conflict target).  Callers with
    explicit ``ON CONFLICT(col)`` clauses should not use ``INSERT OR REPLACE``.
    """
    m = _INSERT_OR_REPLACE_RE.search(sql)
    if not m:
        return sql

    table = m.group(1)
    cols_raw = m.group(2)
    vals_raw = m.group(3)

    # Parse column names (strip whitespace).
    cols = [c.strip() for c in cols_raw.split(",")]

    # Build the ON CONFLICT ... DO UPDATE SET clause.
    set_parts = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)

    # Reconstruct.
    col_list = ", ".join(cols)
    result = (
        f"INSERT INTO {table} ({col_list}) VALUES ({vals_raw})\n"
        f"ON CONFLICT DO UPDATE SET {set_parts}"
    )

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
    sql = _translate_named_params(sql)
    sql = _translate_positional_params(sql)
    return sql
