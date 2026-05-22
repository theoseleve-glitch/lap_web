"""060 — tracks.canonical_id column for GeoJSON-geometric matching bridge.

Adds a nullable ``canonical_id`` TEXT column to ``tracks`` so PG canonical
rows can bridge to the gt_*.geojson polygon files (keyed by canonical_id
like "kct" / "ok"). Day-15 Phase 2 Stage A foundation.

Resolution of 2-head alembic state (058 orphan + 059 applied):
This migration continues the LIVE chain (parent = 059) rather than
declaring a merge of 058+059. A true merge would require first fixing
056's FK type bug (analysis_runs.session_id declared sa.Integer but
sessions.session_id is TEXT) and applying the 056→057→058 chain. That
work is logged as Day-15+ cleanup. For now 058 stays orphaned in the
codebase; alembic heads will continue to warn but upgrades target the
059→060→… chain unambiguously.

Revision ID: 060
Revises: 059
"""
from alembic import op
import sqlalchemy as sa


revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS canonical_id TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracks_canonical_id "
        "ON tracks (canonical_id) WHERE canonical_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tracks_canonical_id")
    op.execute("ALTER TABLE tracks DROP COLUMN IF EXISTS canonical_id")
