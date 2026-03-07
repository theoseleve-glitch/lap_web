"""Add analysis_provenance table for queryable provenance tracking.

Stores denormalised provenance records alongside the summary JSON
embedded in sessions.analysis_json.  PG-only write; SQLite/desktop
uses only the embedded JSON.

Revision ID: 020
Revises: 019
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_provenance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("analysis_run_id", sa.Text, nullable=False, unique=True),
        sa.Column("session_id", sa.Text, sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("workspace_id", sa.Integer, nullable=True),
        sa.Column("input_fingerprint", sa.Text, nullable=False),
        sa.Column("file_hash", sa.Text, nullable=True),
        sa.Column("params_hash", sa.Text, nullable=False),
        sa.Column("pipeline_version", sa.Text, nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("solver_version", sa.Text, nullable=True),
        sa.Column("method_used", sa.Text, nullable=False),
        sa.Column("training_data_hash", sa.Text, nullable=True),
        sa.Column("generated_at", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_provenance_session", "analysis_provenance", ["session_id"])
    op.create_index("idx_provenance_fingerprint", "analysis_provenance", ["input_fingerprint"])
    op.create_index("idx_provenance_pipeline_ver", "analysis_provenance", ["pipeline_version"])

    # RLS policy (PG only, silently skipped on SQLite)
    try:
        op.execute("ALTER TABLE analysis_provenance ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY workspace_isolation ON analysis_provenance "
            "USING (workspace_id = current_setting('app.workspace_id')::INTEGER)"
        )
    except Exception:
        pass  # SQLite — no RLS support


def downgrade() -> None:
    try:
        op.execute("DROP POLICY IF EXISTS workspace_isolation ON analysis_provenance")
    except Exception:
        pass
    op.drop_index("idx_provenance_pipeline_ver")
    op.drop_index("idx_provenance_fingerprint")
    op.drop_index("idx_provenance_session")
    op.drop_table("analysis_provenance")
