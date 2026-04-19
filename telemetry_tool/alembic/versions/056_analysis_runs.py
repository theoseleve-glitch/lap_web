"""056 — Create analysis_runs table for track-surface analysis lifecycle.

Per-session analysis run records (queued → running → succeeded/failed), with
support-tier + artifact index. Workspace-scoped via RLS.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "056"
down_revision = "055"


def upgrade():
    op.create_table(
        "analysis_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer,
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer,
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text("current_setting('app.current_workspace_id')::integer"),
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("support_tier", sa.Text),
        sa.Column("support_reason", sa.Text),
        sa.Column("confidence_level", sa.Text),
        sa.Column("fallback_depth_distribution", JSONB),
        sa.Column("validated_vehicle_profile", sa.Text),
        sa.Column("validated_track_profile", sa.Text),
        sa.Column("planner_mode_availability", JSONB),
        sa.Column("warnings", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("artifacts_index", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("release_decision", sa.Text),
        sa.Column("pipeline_summary", JSONB),
        sa.Column("error_code", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_analysis_runs_session", "analysis_runs", ["session_id"])
    op.create_index("idx_analysis_runs_workspace", "analysis_runs", ["workspace_id"])
    op.execute(
        "CREATE INDEX idx_analysis_runs_status ON analysis_runs (status) "
        "WHERE status IN ('queued', 'running')"
    )

    op.execute("ALTER TABLE analysis_runs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY analysis_runs_tenant ON analysis_runs "
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS analysis_runs_tenant ON analysis_runs")
    op.drop_index("idx_analysis_runs_status", table_name="analysis_runs")
    op.drop_index("idx_analysis_runs_workspace", table_name="analysis_runs")
    op.drop_index("idx_analysis_runs_session", table_name="analysis_runs")
    op.drop_table("analysis_runs")
