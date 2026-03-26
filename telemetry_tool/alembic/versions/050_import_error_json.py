"""Add import_error_json column to ingestion_jobs.

Stores structured ImportFailure payloads as JSONB so the SSE stream
can forward rich error metadata to the frontend instead of collapsing
all failures into generic strings.

Revision ID: 050
Revises: 049
"""
from alembic import op
import sqlalchemy as sa

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs",
        sa.Column("import_error_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "import_error_json")
