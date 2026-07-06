"""session_competitors is workspace-isolated by RLS (functional, PG-only)."""
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PG_URL = os.environ.get("TELEMETRY_PG_URL")
pg_required = pytest.mark.skipif(not PG_URL, reason="TELEMETRY_PG_URL not set")


@pg_required
def test_competitor_rows_are_invisible_across_workspaces():
    import psycopg
    # Connect as the non-superuser app role so RLS is enforced (FORCE covers owner too).
    dsn = os.environ.get("TELEMETRY_PG_APP_URL", PG_URL)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # workspace 1 inserts a competitor for one of its sessions
            cur.execute("SET LOCAL app.current_workspace_id = '1'")
            cur.execute(
                "INSERT INTO session_competitors (session_id, competitor_name, workspace_id) "
                "VALUES ('rls-test-sess-1', 'Rival A', 1) RETURNING id"
            )
            row_id = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM session_competitors WHERE id = %s", (row_id,))
            assert cur.fetchone()[0] == 1  # visible to owner workspace
        conn.rollback()

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_workspace_id = '2'")
            cur.execute("SELECT count(*) FROM session_competitors WHERE competitor_name = 'Rival A'")
            assert cur.fetchone()[0] == 0  # workspace 2 cannot see workspace 1's row
        conn.rollback()


@pg_required
def test_insert_check_rejects_foreign_workspace_id():
    import psycopg
    dsn = os.environ.get("TELEMETRY_PG_APP_URL", PG_URL)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_workspace_id = '1'")
            with pytest.raises(psycopg.errors.Error):
                # WITH CHECK forbids writing a row owned by another workspace
                cur.execute(
                    "INSERT INTO session_competitors (session_id, competitor_name, workspace_id) "
                    "VALUES ('rls-test-sess-1', 'Rival B', 2)"
                )
        conn.rollback()
