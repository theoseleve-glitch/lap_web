"""032 -- Retention audit table and session pseudonym column.

Creates:
- retention_audit: dedicated table for retention enforcement audit trail
  with run_id, subject_type, subject_id, action, reason, actor, result,
  details, and request_id. Retention: 24 months (enforced by archival job).
- sessions.session_pid: HMAC-derived pseudonym for logs/exports

Idempotent: checks table/column existence before creating.

Revision ID: 032
Revises: 031
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return table in insp.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    columns = [c["name"] for c in insp.get_columns(table)]
    return column in columns


def upgrade() -> None:
    # ── 1. retention_audit table ──────────────────────────────────────
    if not _has_table("retention_audit"):
        op.create_table(
            "retention_audit",
            sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=True),
            sa.Column(
                "subject_type",
                sa.Text(),
                nullable=False,
                comment="session | export | artifact | cache",
            ),
            sa.Column("subject_id", sa.Text(), nullable=False),
            sa.Column(
                "action",
                sa.Text(),
                nullable=False,
                comment="identify | mark | delete | error | skip",
            ),
            sa.Column(
                "reason",
                sa.Text(),
                nullable=False,
                comment="retention_expired | user_request | admin | legal_hold",
            ),
            sa.Column("performed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column(
                "actor",
                sa.Text(),
                nullable=False,
                server_default="system",
                comment="system | user:<id> | admin:<id>",
            ),
            sa.Column(
                "result",
                sa.Text(),
                nullable=False,
                comment="success | fail | skipped",
            ),
            sa.Column("details_json", sa.Text(), nullable=True),
            sa.Column("request_id", sa.Text(), nullable=True),
        )
        op.create_index(
            "idx_retention_audit_run", "retention_audit", ["run_id"],
        )
        op.create_index(
            "idx_retention_audit_ws_performed",
            "retention_audit",
            ["workspace_id", "performed_at"],
        )
        op.create_index(
            "idx_retention_audit_subject",
            "retention_audit",
            ["subject_type", "subject_id"],
        )

    # ── 2. session_pid column on sessions ─────────────────────────────
    if _has_table("sessions") and not _has_column("sessions", "session_pid"):
        op.add_column(
            "sessions",
            sa.Column("session_pid", sa.String(32), nullable=True),
        )
        op.create_index(
            "idx_sessions_pid", "sessions", ["session_pid"], unique=False,
        )


def downgrade() -> None:
    if _has_table("sessions") and _has_column("sessions", "session_pid"):
        op.drop_index("idx_sessions_pid", table_name="sessions")
        op.drop_column("sessions", "session_pid")

    if _has_table("retention_audit"):
        op.drop_table("retention_audit")
