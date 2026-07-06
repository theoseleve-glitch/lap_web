"""081 -- track_onboarding_requests: state for the track onboarding loop.

Tracks a track_key from GT-miss detection through auto-draft, operator email,
and human bless (spec: docs/superpowers/specs/2026-07-06-track-onboarding-loop-design.md).

Global operational table: no workspace_id, no RLS (same rationale as 078/079 --
this is derived/operational state keyed on track_key, not tenant data). Chains
off the 080 head.

Indexes:
  ux_onboarding_open           partial UNIQUE on track_key, active while the
                                request has not yet been blessed -- this is
                                the atomic-upsert dedup key so only one open
                                request exists per track at a time. A track
                                can be re-onboarded (e.g. GT revoked) only
                                after the prior request reaches 'blessed'.
  ix_onboarding_status_created  operator/worker queue scans by status, oldest
                                first.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "081_track_onboarding_requests"
down_revision = "080_racing_line_honesty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "track_onboarding_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("track_key", sa.Text, nullable=False),
        sa.Column("track_label", sa.Text, nullable=True),
        sa.Column("fingerprint", JSONB, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("bbox", JSONB, nullable=True),
        sa.Column("draft_centerline", JSONB, nullable=True),
        sa.Column("first_session_ref", sa.Text, nullable=True),
        sa.Column("session_refs", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("session_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("draft_status", sa.Text, nullable=True),
        sa.Column("draft_path", sa.Text, nullable=True),
        sa.Column("token_jti", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("emailed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("blessed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Partial unique index: only one non-blessed (open) request per track_key.
    # This is the atomic-upsert dedup key referenced by onboarding/repo.py.
    op.create_index(
        "ux_onboarding_open",
        "track_onboarding_requests",
        ["track_key"],
        unique=True,
        postgresql_where=sa.text("status <> 'blessed'"),
    )
    op.create_index(
        "ix_onboarding_status_created",
        "track_onboarding_requests",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_onboarding_status_created", table_name="track_onboarding_requests")
    op.drop_index("ux_onboarding_open", table_name="track_onboarding_requests")
    op.drop_table("track_onboarding_requests")
