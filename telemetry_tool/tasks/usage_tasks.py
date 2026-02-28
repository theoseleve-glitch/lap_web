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
    """Get a raw psycopg2 connection (outside Flask request context)."""
    import os
    import psycopg2
    import psycopg2.extras

    url = os.environ.get(
        "TELEMETRY_PG_URL",
        "postgresql://telemetry:telemetry@localhost:5432/telemetry",
    )
    conn = psycopg2.connect(url)
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

    @celery.task(queue="default", bind=True, max_retries=1)
    def cleanup_old_usage_events(self):
        """Delete usage_events older than 90 days.

        Monthly aggregates in ``usage_monthly`` are preserved — they
        provide the historical data. Raw events are only needed for
        debugging and are safe to purge.

        Runs weekly via Celery Beat.
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
