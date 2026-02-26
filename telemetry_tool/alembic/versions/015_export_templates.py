"""Add export_jobs table for asynchronous report generation.

Extends the existing export_templates table (from migration 001, which
defines reusable report templates) with an export_jobs table that tracks
the lifecycle of individual export requests — queuing, rendering, storage,
and download.

NOTE: export_templates already exists from 001_initial_schema; this
migration only creates the new export_jobs table.

Revision ID: 015
Revises: 014
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "015"
down_revision = "014"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # export_jobs — tracks asynchronous export/report generation tasks.
    # A job references an export_template and one or more sessions,
    # progressing through pending → running → completed / failed states.
    # ------------------------------------------------------------------
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "template_id",
            sa.Integer,
            sa.ForeignKey("export_templates.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "session_id",
            sa.Text,
            sa.ForeignKey("sessions.session_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "driver_id",
            sa.Integer,
            sa.ForeignKey("drivers.driver_id", ondelete="SET NULL"),
        ),
        sa.Column("job_name", sa.Text),  # human-readable label
        sa.Column("format", sa.Text, nullable=False, server_default="pdf"),  # pdf, csv, xlsx, png
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),  # pending, running, completed, failed, cancelled
        sa.Column("progress_pct", sa.Float, server_default="0"),
        sa.Column("parameters_json", JSONB),  # template variable overrides, date range, filters
        sa.Column("session_ids_json", JSONB),  # array of session IDs when exporting multiple
        sa.Column("include_sections_json", JSONB),  # which sections of the template to render
        sa.Column("file_path", sa.Text),  # path to generated file on disk / object storage
        sa.Column("file_size_bytes", sa.BigInteger),
        sa.Column("file_hash", sa.Text),  # SHA-256 of generated file for integrity check
        sa.Column("mime_type", sa.Text),
        sa.Column("download_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text),
        sa.Column("error_class", sa.Text),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default="3"),
        sa.Column("requested_by", sa.Text),  # username or user_id who initiated
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
        ),  # auto-cleanup after this time
    )
    op.create_index("ix_export_jobs_template_id", "export_jobs", ["template_id"])
    op.create_index("ix_export_jobs_session_id", "export_jobs", ["session_id"])
    op.create_index("ix_export_jobs_driver_id", "export_jobs", ["driver_id"])
    op.create_index("ix_export_jobs_status", "export_jobs", ["status"])
    op.create_index("ix_export_jobs_created_at", "export_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_created_at", "export_jobs")
    op.drop_index("ix_export_jobs_status", "export_jobs")
    op.drop_index("ix_export_jobs_driver_id", "export_jobs")
    op.drop_index("ix_export_jobs_session_id", "export_jobs")
    op.drop_index("ix_export_jobs_template_id", "export_jobs")
    op.drop_table("export_jobs")
