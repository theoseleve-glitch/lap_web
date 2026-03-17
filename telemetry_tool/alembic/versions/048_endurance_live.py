"""048 — endurance live tracking: race anchor for real-time clock."""
from alembic import op
import sqlalchemy as sa

revision = "048"
down_revision = "047"


def upgrade():
    op.create_table(
        "endurance_race_anchors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("race_start_iso", sa.Text, nullable=False),
        sa.Column("lap_duration_s", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False,
                  server_default=sa.text("current_setting('app.current_workspace_id')::integer")),
    )
    op.create_index("idx_endurance_race_anchors_session", "endurance_race_anchors", ["session_id"])
    op.create_index("idx_endurance_race_anchors_workspace", "endurance_race_anchors", ["workspace_id"])

    # RLS policy
    op.execute("""
        ALTER TABLE endurance_race_anchors ENABLE ROW LEVEL SECURITY;
        CREATE POLICY endurance_race_anchors_tenant_isolation ON endurance_race_anchors
            USING (workspace_id = current_setting('app.current_workspace_id')::integer)
            WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS endurance_race_anchors_tenant_isolation ON endurance_race_anchors")
    op.drop_table("endurance_race_anchors")
