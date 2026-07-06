"""082 -- track_onboarding_requests: email_count (bounded auto-resend).

Fast-follow to the Track Onboarding Loop (081): if the operator doesn't act
on the emailed annotator link before its token expires (default 72h,
``ONBOARDING_TOKEN_TTL_HOURS``), nothing previously recovered the request --
``reconcile_onboarding``'s existing backstop (``find_stale_unemailed``) only
re-drives rows with ``emailed_at IS NULL``, which an already-emailed row
never is.

``email_count`` tracks how many notification emails have gone out for a
request (the initial send counts as 1, see
``tasks.onboarding_tasks._run_draft_and_notify``), so a new bounded
auto-resend path (``onboarding.repo.find_expired_emailed`` /
``claim_resend``, ``tasks.onboarding_tasks._resend_expired_links``) can cap
total sends at ``MAX_EMAILS`` and stop nagging an ignored track forever.

Chains off the 081 head. Existing rows backfill to 0 (``server_default``),
which is intentionally wrong for any row already emailed before this
migration ran -- a one-time undercount, not a correctness bug: it only
means such a row gets its full resend budget instead of a partial one,
never fewer resends than intended.
"""
from alembic import op
import sqlalchemy as sa

revision = "082_onboarding_email_count"
down_revision = "081_track_onboarding_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "track_onboarding_requests",
        sa.Column(
            "email_count", sa.Integer, nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("track_onboarding_requests", "email_count")
