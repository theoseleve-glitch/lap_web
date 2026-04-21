#!/usr/bin/env python3
"""Backfill `sessions.source` / `capabilities` / `data_profile` for pre-W1 rows.

Idempotent: only touches rows where `source IS NULL` (or the paired
columns are NULL). Migration 059 already runs a one-shot backfill as
part of the upgrade — this script exists for the edge case where new
rows get inserted by downgraded code paths after 059 has run.

Usage:
  TELEMETRY_PG_URL=postgresql://... python scripts/backfill_session_sources.py
"""
from __future__ import annotations

import logging
import os
import sys

import psycopg2


def main() -> int:
    dsn = os.environ.get("TELEMETRY_PG_URL")
    if not dsn:
        print("TELEMETRY_PG_URL env var required", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sessions
                   SET source       = COALESCE(source, 'real_life'),
                       data_profile = COALESCE(data_profile, '{}'::jsonb),
                       capabilities = COALESCE(capabilities,
                                     '{"channels":["gps"]}'::jsonb)
                 WHERE source IS NULL
                    OR data_profile IS NULL
                    OR capabilities IS NULL
                """
            )
            updated = cur.rowcount
            conn.commit()
    print(f"backfill_session_sources: updated {updated} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
