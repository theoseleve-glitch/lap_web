"""074 — marketing_events (anonymous, GLOBAL, no RLS).

Front-of-funnel anonymous events (page views, CTA clicks, etc.). The table is
GLOBAL: it has NO workspace/tenant column and therefore NO Row-Level Security.
It deliberately captures NO identifying fields (no user_id / ip_address /
user_agent) — anything that lands here is anonymous by construction.

Partitioned by range on ``created_at`` (composite PK ``(id, created_at)`` because
Postgres requires the partition key to be part of every unique constraint).
Monthly partitions are seeded for 2026-06 / 2026-07 / 2026-08; later months are
added by ops/maintenance. All DDL is ``IF NOT EXISTS`` so the migration is
idempotent against partially-applied state.
"""
from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS marketing_events (
    id BIGSERIAL,
    event_type TEXT NOT NULL,
    path TEXT,
    properties JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at)""")

    op.execute("""CREATE TABLE IF NOT EXISTS marketing_events_2026_06
        PARTITION OF marketing_events
        FOR VALUES FROM ('2026-06-01') TO ('2026-07-01')""")
    op.execute("""CREATE TABLE IF NOT EXISTS marketing_events_2026_07
        PARTITION OF marketing_events
        FOR VALUES FROM ('2026-07-01') TO ('2026-08-01')""")
    op.execute("""CREATE TABLE IF NOT EXISTS marketing_events_2026_08
        PARTITION OF marketing_events
        FOR VALUES FROM ('2026-08-01') TO ('2026-09-01')""")

    op.execute("""CREATE INDEX IF NOT EXISTS ix_marketing_events_type_ts
        ON marketing_events (event_type, created_at)""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketing_events CASCADE")
