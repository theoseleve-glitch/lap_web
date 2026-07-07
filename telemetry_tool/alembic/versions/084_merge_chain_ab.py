"""084 -- merge revision joining Chain B and Chain A (track-onboarding + honesty).

Two independent migration chains forked at 077 and were developed in
parallel on separate branches:

- Chain B (feat/chain-a-consolidated's own history): 077 -> 081_feeling_competition
  -> 082_user_corners_rls -> 083_ingest_policy_missing_ok.
- Chain A (feat/track-onboarding-loop): 077 -> 078_track_racing_lines ->
  079_track_geometry_audit -> 080_racing_line_honesty ->
  081_track_onboarding_requests -> 082_onboarding_email_count.

The two chains are table-disjoint (Chain B touches user_corners/ingestion_jobs
RLS + feeling/competition scoring tables; Chain A adds the
track_racing_lines / track_geometry_audit / racing_line honesty / onboarding
tables) so no schema conflict exists between them -- they were simply
authored against the same parent revision on separate branches. This is a
pure alembic merge point: it applies no schema changes itself, it only
collapses the resulting two heads (083_ingest_policy_missing_ok and
082_onboarding_email_count) back into one linear head so `alembic upgrade
head` is unambiguous again.
"""
from __future__ import annotations

revision = "084_merge_chain_ab"
down_revision = ("083_ingest_policy_missing_ok", "082_onboarding_email_count")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
