"""session_weather_laps table and session_datetime column

Revision ID: 017
Revises: 016
Create Date: 2026-02-27
"""
import sqlalchemy as sa

from alembic import op

revision = "017"
down_revision = "016"


def upgrade():
    op.create_table(
        "session_weather_laps",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("lap_number", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.Text()),
        sa.Column("air_temp_c", sa.Float()),
        sa.Column("humidity_pct", sa.Float()),
        sa.Column("wind_speed_mps", sa.Float()),
        sa.Column("wind_dir_deg", sa.Float()),
        sa.Column("rain_mm", sa.Float()),
        sa.Column("cloud_cover_pct", sa.Float()),
        sa.Column("weather_code", sa.Integer()),
        sa.Column("grip_score", sa.Float()),
        sa.Column("track_state", sa.Text()),
        sa.Column("track_temp_est_c", sa.Float()),
        sa.Column("workspace_id", sa.Text()),
        sa.PrimaryKeyConstraint("session_id", "lap_number"),
    )
    op.execute(sa.text("ALTER TABLE session_weather_laps ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY session_weather_laps_tenant ON session_weather_laps "
        "USING (workspace_id = current_setting('app.workspace_id', true))"
    ))
    op.add_column("sessions", sa.Column("session_datetime", sa.Text()))


def downgrade():
    op.drop_column("sessions", "session_datetime")
    op.execute(sa.text("DROP POLICY IF EXISTS session_weather_laps_tenant ON session_weather_laps"))
    op.drop_table("session_weather_laps")
