"""Add Celery pipeline columns, batch_jobs table, processing_version.

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"


def upgrade() -> None:
    # 1. Add columns to ingestion_jobs for Celery task tracking
    op.add_column("ingestion_jobs", sa.Column("celery_task_id", sa.Text))
    op.add_column("ingestion_jobs", sa.Column("processing_version", sa.Integer, server_default="1"))
    op.add_column("ingestion_jobs", sa.Column("stage_name", sa.Text))
    op.add_column("ingestion_jobs", sa.Column("stage_index", sa.Integer))
    op.add_column("ingestion_jobs", sa.Column("stage_total", sa.Integer))
    op.add_column("ingestion_jobs", sa.Column("progress_pct", sa.Float))
    op.add_column("ingestion_jobs", sa.Column("error_class", sa.Text))
    op.add_column("ingestion_jobs", sa.Column("pause_reason", sa.Text))
    op.add_column("ingestion_jobs", sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()))

    # 2. Add processing_version to sessions
    op.add_column("sessions", sa.Column("processing_version", sa.Integer, server_default="1"))

    # 3. Create batch_jobs table
    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("total_sessions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_sessions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_sessions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filter_criteria", sa.Text),  # JSON
        sa.Column("processing_version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
    )
    op.create_index("idx_batch_jobs_workspace", "batch_jobs", ["workspace_id"])
    op.create_index("idx_batch_jobs_status", "batch_jobs", ["status"])

    # 4. Add batch_job_id FK to ingestion_jobs
    op.add_column("ingestion_jobs", sa.Column("batch_job_id", sa.Integer))
    op.create_foreign_key(
        "fk_ingestion_jobs_batch", "ingestion_jobs", "batch_jobs",
        ["batch_job_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_ingestion_jobs_batch", "ingestion_jobs", type_="foreignkey")
    op.drop_column("ingestion_jobs", "batch_job_id")
    op.drop_index("idx_batch_jobs_status", "batch_jobs")
    op.drop_index("idx_batch_jobs_workspace", "batch_jobs")
    op.drop_table("batch_jobs")
    op.drop_column("sessions", "processing_version")
    op.drop_column("ingestion_jobs", "updated_at")
    op.drop_column("ingestion_jobs", "pause_reason")
    op.drop_column("ingestion_jobs", "error_class")
    op.drop_column("ingestion_jobs", "progress_pct")
    op.drop_column("ingestion_jobs", "stage_total")
    op.drop_column("ingestion_jobs", "stage_index")
    op.drop_column("ingestion_jobs", "stage_name")
    op.drop_column("ingestion_jobs", "processing_version")
    op.drop_column("ingestion_jobs", "celery_task_id")
