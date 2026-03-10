"""Add workspace_id + RLS to tracks, track_records, track_sectors.

Enables multi-tenant isolation for track data using the same pattern
as migrations 004-008 for other workspace-scoped tables.

Revision ID: 021
Revises: 020
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None

_TABLES = ("tracks", "track_records", "track_sectors")


def upgrade():
    # -- Step 1: Add nullable workspace_id columns --
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("workspace_id", sa.dialects.postgresql.UUID(), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_workspace_id",
            table,
            "workspaces",
            ["workspace_id"],
            ["workspace_id"],
        )

    # -- Step 2: Backfill from sessions --
    op.execute(
        """
        UPDATE tracks t
        SET workspace_id = (
            SELECT DISTINCT s.workspace_id
            FROM sessions s
            WHERE s.track_id = t.track_id AND s.workspace_id IS NOT NULL
            LIMIT 1
        )
        WHERE t.workspace_id IS NULL
        """
    )
    # Orphan tracks: assign to first workspace
    op.execute(
        """
        UPDATE tracks
        SET workspace_id = (
            SELECT workspace_id FROM workspaces ORDER BY created_at LIMIT 1
        )
        WHERE workspace_id IS NULL
        """
    )
    # Backfill track_records and track_sectors from tracks
    for table in ("track_records", "track_sectors"):
        op.execute(
            f"""
            UPDATE {table} r
            SET workspace_id = (
                SELECT t.workspace_id FROM tracks t WHERE t.track_id = r.track_id
            )
            WHERE r.workspace_id IS NULL
            """
        )

    # -- Step 3: Set NOT NULL --
    for table in _TABLES:
        op.alter_column(table, "workspace_id", nullable=False)

    # -- Step 4: RLS policies --
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_workspace_isolation ON {table}
            USING (workspace_id = current_setting('app.workspace_id')::uuid)
            WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid)
            """
        )

    # -- Step 5: Workspace-scoped unique constraint on track names --
    op.create_unique_constraint(
        "uq_tracks_workspace_name", "tracks", ["workspace_id", "track_name"]
    )


def downgrade():
    op.drop_constraint("uq_tracks_workspace_name", "tracks")
    for table in _TABLES:
        op.execute(
            f"DROP POLICY IF EXISTS {table}_workspace_isolation ON {table}"
        )
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_constraint(f"fk_{table}_workspace_id", table, type_="foreignkey")
        op.drop_column(table, "workspace_id")
