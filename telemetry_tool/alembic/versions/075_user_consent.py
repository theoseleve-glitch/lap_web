"""075 — user_consent.

Per-user consent record consulted by the consent gate before any behavioral
event is emitted. One row per user (PK = ``user_id`` FK to ``users(id)``).
Both consent flags default to ``false`` (opt-in). ``version`` records which
consent-text revision the user agreed to. Idempotent CREATE; downgrade drops.
"""
from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS user_consent (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    analytics BOOLEAN NOT NULL DEFAULT false,
    marketing BOOLEAN NOT NULL DEFAULT false,
    version INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_consent")
