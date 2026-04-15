"""053 — extend track_surfaces_global with surface properties.

Adds slope, vertical curvature, track width, and camber columns
for the cross-session track model accumulation system.
"""
from alembic import op
import sqlalchemy as sa

revision = "053"
down_revision = "052"


def upgrade():
    with op.batch_alter_table("track_surfaces_global") as batch:
        batch.add_column(sa.Column("slope_pct", sa.Float, nullable=True))
        batch.add_column(sa.Column("vert_curvature_1pm", sa.Float, nullable=True))
        batch.add_column(sa.Column("width_left_m", sa.Float, nullable=True))
        batch.add_column(sa.Column("width_right_m", sa.Float, nullable=True))
        batch.add_column(sa.Column("camber_rad", sa.Float, nullable=True))


def downgrade():
    with op.batch_alter_table("track_surfaces_global") as batch:
        batch.drop_column("camber_rad")
        batch.drop_column("width_right_m")
        batch.drop_column("width_left_m")
        batch.drop_column("vert_curvature_1pm")
        batch.drop_column("slope_pct")
