"""046 — endurance stints and driver assignments."""
from alembic import op
import sqlalchemy as sa

revision = "046"
down_revision = "045"


def upgrade():
    op.create_table(
        "endurance_stints",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("stint_number", sa.Integer, nullable=False),
        sa.Column("start_lap", sa.Integer, nullable=False),
        sa.Column("end_lap", sa.Integer, nullable=False),
        sa.Column("lap_count", sa.Integer, nullable=False),
        sa.Column("pit_lap_number", sa.Integer, nullable=True),
        sa.Column("pit_lap_time_s", sa.Float, nullable=True),
        sa.Column("condition", sa.Text, nullable=True, server_default="dry"),
        sa.Column("driver_id", sa.Integer, nullable=True),
        sa.Column("driver_name", sa.Text, nullable=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
                  server_default=sa.text("current_setting('app.current_workspace_id')::integer")),
        sa.UniqueConstraint("session_id", "stint_number", name="uq_endurance_stint"),
    )
    op.create_index("idx_endurance_stints_session", "endurance_stints", ["session_id"])
    op.create_index("idx_endurance_stints_workspace", "endurance_stints", ["workspace_id"])

    # RLS policy
    op.execute("""
        ALTER TABLE endurance_stints ENABLE ROW LEVEL SECURITY;
        CREATE POLICY endurance_stints_tenant_isolation ON endurance_stints
            USING (workspace_id = current_setting('app.current_workspace_id')::integer)
            WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);
    """)

    # Add pit_threshold_s to sessions table for user-configured threshold
    op.add_column("sessions", sa.Column("pit_threshold_s", sa.Float, nullable=True))


def downgrade():
    op.drop_column("sessions", "pit_threshold_s")
    op.execute("DROP POLICY IF EXISTS endurance_stints_tenant_isolation ON endurance_stints")
    op.drop_table("endurance_stints")
