"""063 — add tracks.wet_pace_s (typed wet reference lap time for a track).

The June-8 upload flow lets a user register a brand-new track with a known wet
pace lap time (seconds). Stored as a nullable scalar on the tracks row — separate
from wet_ref_session_id (which references a session). Additive + nullable, so it
is safe on existing rows. Chains off 062_founding_slots.
"""
from alembic import op
import sqlalchemy as sa

revision = "063_track_wet_pace"
down_revision = "062_founding_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tracks", sa.Column("wet_pace_s", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("tracks", "wet_pace_s")
