"""Usage aggregation and cleanup Celery tasks.

- ``aggregate_monthly_usage``: daily task — materializes ``usage_monthly``
  from ``usage_events`` for the current month (repair/reconcile).
- ``cleanup_old_usage_events``: weekly task — deletes ``usage_events``
  older than 90 days (aggregates in ``usage_monthly`` are kept).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def _get_pg_conn():
    """Raw psycopg2 connection on the maintenance DSN (telemetry_maint).

    Usage aggregation GROUPs across ALL workspaces by design, so it needs
    the BYPASSRLS (but non-superuser) maintenance role.
    """
    import psycopg2
    import psycopg2.extras

    from web.db_pg import _get_maint_url

    conn = psycopg2.connect(_get_maint_url())
    conn.autocommit = False
    # Use RealDictCursor for dict-like rows
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


try:
    from celery_app import celery

    @celery.task(queue="default", bind=True, max_retries=2)
    def aggregate_monthly_usage(self):
        """Reconcile usage_monthly from usage_events for current month.

        This is a repair/idempotent task: it recalculates totals from raw
        events to fix any drift caused by partial failures.

        Runs daily via Celery Beat.
        """
        conn = _get_pg_conn()
        try:
            first_of_month = date.today().replace(day=1)

            cur = conn.cursor()

            # Aggregate current month events by workspace + type
            cur.execute(
                """
                SELECT workspace_id, event_type, COALESCE(SUM(cost), 0) AS total
                FROM usage_events
                WHERE created_at >= %s
                GROUP BY workspace_id, event_type
                """,
                (first_of_month,),
            )
            rows = cur.fetchall()

            updated = 0
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO usage_monthly (workspace_id, period_start, event_type, total)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (workspace_id, period_start, event_type)
                    DO UPDATE SET total = %s
                    """,
                    (row["workspace_id"], first_of_month, row["event_type"],
                     row["total"], row["total"]),
                )
                updated += 1

            conn.commit()
            logger.info("Monthly usage aggregation complete: %d rows reconciled", updated)
            return {"reconciled": updated}

        except Exception as exc:
            conn.rollback()
            logger.error("Monthly usage aggregation failed: %s", exc, exc_info=True)
            raise self.retry(exc=exc, countdown=60)
        finally:
            conn.close()

    @celery.task(queue="default", bind=True, max_retries=2)
    def reconcile_storage_usage(self):
        """Recompute each workspace's on-disk storage and grow its elastic
        allocation (2 GiB base, +1 GiB at 80%). Keeps the per-user storage
        figure 'regularly updated to match consumption' even if an upload/
        delete missed its inline refresh. Runs daily via Celery Beat.

        Commits PER WORKSPACE inside the loop, each isolated in its own
        try/except: one workspace failing (transient DB error, etc.) is logged
        and skipped — it must NOT roll back the whole fleet's progress nor force
        a full re-walk of every workspace's disk on retry. recompute_and_store
        threads the connection through so usage reflects the session-keyed
        sidecar footprint (not the empty legacy dirs).
        """
        from web.db_pg import PgConnectionWrapper
        from web.storage_quota import recompute_and_store

        raw = _get_pg_conn()  # maint DSN (BYPASSRLS): workspaces not RLS-scoped,
        conn = PgConnectionWrapper(raw)  # and we must read sessions across all tenants
        updated = skipped = 0
        try:
            cur = raw.cursor()
            cur.execute("SELECT id FROM workspaces")
            ws_ids = [r["id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
            cur.close()
            for ws_id in ws_ids:
                try:
                    recompute_and_store(conn, ws_id)
                    raw.commit()
                    updated += 1
                except Exception as exc:  # noqa: BLE001 — skip one, keep the fleet
                    try:
                        raw.rollback()
                    except Exception:
                        pass
                    skipped += 1
                    logger.warning("Storage reconcile skipped ws=%s: %s", ws_id, exc)
            logger.info("Storage reconcile: updated %d, skipped %d", updated, skipped)
            return {"reconciled": updated, "skipped": skipped}
        finally:
            raw.close()

    @celery.task(queue="default", bind=True, max_retries=1)
    def cleanup_old_usage_events(self):
        """Delete usage_events older than 90 days (manual/admin tool — NOT
        on the beat schedule).

        Monthly aggregates in ``usage_monthly`` are preserved — they provide
        the historical data. Raw events are only needed for debugging.

        Deliberately NOT scheduled: the ``archive_old_usage_events`` beat task
        (tasks.archival_tasks, monthly) already owns the usage_events
        lifecycle and ARCHIVES partitions to Parquet before dropping them at
        12 months. A 90-day DELETE here would destroy raw events the archival
        would otherwise preserve, so this stays an explicit, on-demand purge.
        """
        conn = _get_pg_conn()
        try:
            cutoff = date.today() - timedelta(days=90)

            cur = conn.cursor()
            cur.execute(
                "DELETE FROM usage_events WHERE created_at < %s",
                (cutoff,),
            )
            deleted = cur.rowcount
            conn.commit()

            logger.info("Usage events cleanup: deleted %d events older than %s",
                        deleted, cutoff)
            return {"deleted": deleted, "cutoff": cutoff.isoformat()}

        except Exception as exc:
            conn.rollback()
            logger.error("Usage events cleanup failed: %s", exc, exc_info=True)
            raise self.retry(exc=exc, countdown=120)
        finally:
            conn.close()

except ImportError:
    # Celery not available (e.g., desktop mode or tests without celery)
    logger.debug("Celery not available — usage tasks not registered")

    def aggregate_monthly_usage():
        """Stub when Celery is not available."""
        pass

    def cleanup_old_usage_events():
        """Stub when Celery is not available."""
        pass
