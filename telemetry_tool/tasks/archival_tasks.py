"""Archival and partition management tasks.

Manages table partitioning for high-write tables (usage_events, audit_log)
and archives old partitions to Parquet for long-term storage.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Retention periods before archival
USAGE_EVENTS_RETENTION_MONTHS = 12
AUDIT_LOG_RETENTION_MONTHS = 24

# How far ahead to create partitions
PARTITION_LOOKAHEAD_MONTHS = 3

# Archive storage path. Archival DROPs partitions after exporting them, so it
# must only run when ARCHIVE_PATH points at a DURABLE, persistent location
# (a mounted Docker volume). If it's left at the default, the export would land
# on the container's ephemeral overlay and be lost on restart — so we require
# the operator to opt in by setting ARCHIVE_PATH explicitly (see
# ARCHIVE_PATH_CONFIGURED). The default exists only so create_future_partitions
# / non-dropping callers have a path.
ARCHIVE_BASE_PATH = os.environ.get(
    "ARCHIVE_PATH", "/opt/lap-api/archives"
)
ARCHIVE_PATH_CONFIGURED = "ARCHIVE_PATH" in os.environ


def _month_range(start_date: date, months_ahead: int):
    """Yield (year, month) tuples for the next N months from start_date."""
    y, m = start_date.year, start_date.month
    for _ in range(months_ahead):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def _partition_name(table: str, year: int, month: int) -> str:
    return f"{table}_{year}_{month:02d}"


def _partition_bounds(year: int, month: int):
    """Return (start, end) date strings for a monthly partition."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def _create_partitions_impl(table: str, months_ahead: int = PARTITION_LOOKAHEAD_MONTHS):
    """Create monthly partitions for the next N months if they don't exist."""
    # Partition DDL needs table ownership — runs on the migration/owner DSN
    # (the RLS-scoped app role deliberately cannot CREATE/DROP tables).
    from web.db_pg import get_migration_connection, return_pg_connection

    conn = get_migration_connection()
    try:
        today = date.today()
        created = []
        for year, month in _month_range(today, months_ahead):
            part_name = _partition_name(table, year, month)
            start, end = _partition_bounds(year, month)

            # Check if partition exists
            cur = conn.execute(
                "SELECT 1 FROM pg_class WHERE relname = :name",
                {"name": part_name},
            )
            if cur.fetchone():
                continue

            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{part_name}" '
                f'PARTITION OF "{table}" '
                f"FOR VALUES FROM ('{start}') TO ('{end}')"
            )
            created.append(part_name)

        conn.raw_connection.commit()
        if created:
            logger.info("Created partitions: %s", ", ".join(created))
        return created
    except Exception:
        conn.raw_connection.rollback()
        raise
    finally:
        return_pg_connection(conn)


def _archive_old_partitions_impl(
    table: str,
    retention_months: int,
    archive_subdir: str,
):
    """Archive partitions older than retention_months to Parquet, then drop."""
    # DROP TABLE on partitions needs ownership — migration/owner DSN.
    from web.db_pg import get_migration_connection, return_pg_connection

    # Never drop a partition unless we have a DURABLE place to archive it first.
    # Without an explicit ARCHIVE_PATH the export would go to an ephemeral
    # container path and vanish on restart, so we'd be dropping data with no
    # recoverable copy. Skip cleanly (partitions stay; no data loss) and tell
    # the operator how to enable it.
    if not ARCHIVE_PATH_CONFIGURED:
        logger.warning(
            "Partition archival for %s SKIPPED: ARCHIVE_PATH is not set. Point it "
            "at a persistent, mounted volume to enable archive-then-drop; until "
            "then partitions are retained (no data loss, but they accumulate).",
            table,
        )
        return []

    conn = get_migration_connection()
    try:
        cutoff = date.today().replace(day=1)
        # Walk back retention_months
        for _ in range(retention_months):
            m = cutoff.month - 1
            if m < 1:
                m = 12
                cutoff = cutoff.replace(year=cutoff.year - 1)
            cutoff = cutoff.replace(month=m)

        # Find partitions older than cutoff
        cur = conn.execute(
            "SELECT relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "AND relname LIKE :pattern "
            "ORDER BY relname",
            {"pattern": f"{table}_%"},
        )
        archived = []
        for row in cur.fetchall():
            part_name = row["relname"]
            # Parse year_month from partition name
            try:
                parts = part_name.replace(f"{table}_", "").split("_")
                part_year, part_month = int(parts[0]), int(parts[1])
                part_date = date(part_year, part_month, 1)
            except (ValueError, IndexError):
                continue

            if part_date >= cutoff:
                continue

            # Each partition is isolated: a failure to export one must NOT abort
            # the sweep or drop the partition. We DROP only after confirming the
            # Parquet was durably written (exists + non-empty), then commit that
            # partition so a later failure can't roll back an already-archived
            # drop.
            try:
                archive_dir = os.path.join(ARCHIVE_BASE_PATH, archive_subdir)
                os.makedirs(archive_dir, exist_ok=True)
                archive_path = os.path.join(
                    archive_dir, f"{part_year}-{part_month:02d}.parquet"
                )

                import pandas as pd
                df = pd.read_sql(f'SELECT * FROM "{part_name}"', conn.raw_connection)
                df.to_parquet(archive_path, index=False)

                # Durability guard: NEVER drop unless the archive is really there.
                if not (os.path.exists(archive_path) and os.path.getsize(archive_path) > 0):
                    raise RuntimeError(f"archive not durably written: {archive_path}")
                logger.info("Archived %s → %s (%d rows)", part_name, archive_path, len(df))

                conn.execute(f'DROP TABLE IF EXISTS "{part_name}"')
                conn.raw_connection.commit()
                archived.append(part_name)
            except Exception as exc:  # noqa: BLE001 — skip this partition, keep the rest
                conn.raw_connection.rollback()
                logger.warning(
                    "Skipped archival of partition %s (kept, not dropped): %s",
                    part_name, exc,
                )
                continue

        return archived
    except Exception:
        conn.raw_connection.rollback()
        raise
    finally:
        return_pg_connection(conn)


# ---------------------------------------------------------------------------
# Celery task registration
# ---------------------------------------------------------------------------

try:
    from celery_app import celery

    @celery.task(name="tasks.archival_tasks.create_future_partitions", queue="default")
    def create_future_partitions():
        """Monthly task: create partitions for usage_events and audit_log."""
        usage = _create_partitions_impl("usage_events")
        audit = _create_partitions_impl("audit_log")
        return {"usage_events": usage, "audit_log": audit}

    @celery.task(name="tasks.archival_tasks.archive_old_usage_events", queue="default")
    def archive_old_usage_events():
        """Monthly task: archive usage_events older than 12 months."""
        return _archive_old_partitions_impl(
            "usage_events", USAGE_EVENTS_RETENTION_MONTHS, "usage"
        )

    @celery.task(name="tasks.archival_tasks.archive_old_audit_logs", queue="default")
    def archive_old_audit_logs():
        """Monthly task: archive audit_log older than 24 months."""
        return _archive_old_partitions_impl(
            "audit_log", AUDIT_LOG_RETENTION_MONTHS, "audit"
        )

except ImportError:
    pass
