"""062 — Founding-50 capacity slots (hard, race-safe ≤50 cap for the launch offer).

The launch offer is €14.90/mo for the FIRST 50 sales (standard €19.90/mo).
This table is the source of truth for the cap. Exactly 50 rows are seeded
(slot_no 1..50). A checkout claims the lowest available slot via
``FOR UPDATE SKIP LOCKED`` inside the request transaction:

    UPDATE founding_slots SET status='held', ...
    WHERE slot_no = (
        SELECT slot_no FROM founding_slots
        WHERE status='open' OR (status='held' AND expires_at < now())
        ORDER BY slot_no FOR UPDATE SKIP LOCKED LIMIT 1
    ) RETURNING slot_no;

Because only 50 rows ever exist and each is claimable once, the offer CANNOT
oversell — concurrent checkouts skip locked candidate rows and each grabs a
distinct slot; when all 50 are held/claimed the query returns nothing and the
buyer is routed to the €19.90 standard price.

Lifecycle: open --(checkout)--> held --(webhook paid)--> claimed
                       held --(cancel / TTL expiry)--> open (re-offerable)

Not workspace-scoped (it is global offer capacity, touched only server-side),
so no RLS. Chains off the converged single head 061_merge_heads.
"""
from alembic import op
import sqlalchemy as sa

revision = "062_founding_slots"
down_revision = "061_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "founding_slots",
        sa.Column("slot_no", sa.Integer, primary_key=True),  # 1..50
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("holder_email", sa.Text),
        sa.Column("stripe_session_id", sa.Text),
        sa.Column("stripe_subscription_id", sa.Text),
        sa.Column("held_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("slot_no BETWEEN 1 AND 50", name="founding_slots_range_ck"),
        sa.CheckConstraint("status IN ('open','held','claimed')", name="founding_slots_status_ck"),
    )
    # Seed exactly 50 slots — the hard cap is structural (only 50 rows exist).
    op.execute("INSERT INTO founding_slots (slot_no, status) SELECT generate_series(1, 50), 'open'")
    # One claimed slot per paid subscription (lets the webhook confirm idempotently).
    op.execute(
        "CREATE UNIQUE INDEX uq_founding_slots_subscription "
        "ON founding_slots (stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL"
    )
    # Fast lookup of claimable (open or expired-held) slots.
    op.execute(
        "CREATE INDEX idx_founding_slots_claimable ON founding_slots (slot_no) "
        "WHERE status <> 'claimed'"
    )


def downgrade() -> None:
    op.drop_table("founding_slots")
