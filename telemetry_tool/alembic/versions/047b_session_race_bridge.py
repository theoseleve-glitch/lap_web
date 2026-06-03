"""047 — session-to-race bridge: link sessions to race configs + race actuals."""
from alembic import op
import sqlalchemy as sa

revision = "047b"
down_revision = "047"


def upgrade():
    # Add session_id and is_retrospective to race_configs
    op.add_column(
        "race_configs",
        sa.Column(
            "session_id", sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "race_configs",
        sa.Column("is_retrospective", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "idx_race_configs_session_id",
        "race_configs",
        ["session_id"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )

    # New race_actuals table
    op.create_table(
        "race_actuals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer,
                  sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("stint_order", sa.Integer, nullable=False),
        sa.Column("actual_start_s", sa.Integer, nullable=True),
        sa.Column("actual_end_s", sa.Integer, nullable=True),
        sa.Column("actual_duration_s", sa.Integer, nullable=True),
        sa.Column("actual_lap_count", sa.Integer, nullable=True),
        sa.Column("actual_best_lap_s", sa.Float, nullable=True),
        sa.Column("actual_mean_lap_s", sa.Float, nullable=True),
        sa.Column("actual_consistency_cv_pct", sa.Float, nullable=True),
        sa.Column("actual_pace_fade_pct", sa.Float, nullable=True),
        sa.Column("delta_duration_s", sa.Integer, nullable=True),
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False,
                  server_default=sa.text("current_setting('app.current_workspace_id')::integer")),
        sa.UniqueConstraint("race_id", "stint_order", name="uq_race_actual_stint"),
    )
    op.create_index("idx_race_actuals_race_id", "race_actuals", ["race_id"])
    op.create_index("idx_race_actuals_workspace", "race_actuals", ["workspace_id"])

    # RLS policy
    op.execute("""
        ALTER TABLE race_actuals ENABLE ROW LEVEL SECURITY;
        CREATE POLICY race_actuals_tenant_isolation ON race_actuals
            USING (workspace_id = current_setting('app.current_workspace_id')::integer)
            WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS race_actuals_tenant_isolation ON race_actuals")
    op.drop_table("race_actuals")
    op.drop_index("idx_race_configs_session_id", table_name="race_configs")
    op.drop_column("race_configs", "is_retrospective")
    op.drop_column("race_configs", "session_id")
