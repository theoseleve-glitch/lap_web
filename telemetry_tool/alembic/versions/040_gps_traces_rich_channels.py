"""040 -- Add rich telemetry channel columns to gps_traces.

The insert_gps_traces() function writes throttle, brake, steering,
RPM, gear, tire temp/pressure, brake temp, wheel slip, and fuel
channels, but the table only had the original 8 data columns.

Revision ID: 040
Revises: 039
Create Date: 2026-03-11
"""
from sqlalchemy import text

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None

_COLUMNS = [
    "throttle_json",
    "brake_json",
    "steering_json",
    "rpm_json",
    "gear_json",
    "tire_temp_json",
    "tire_pressure_json",
    "brake_temp_json",
    "wheel_slip_json",
    "fuel_json",
]


def upgrade():
    for col in _COLUMNS:
        op.execute(
            text(f"ALTER TABLE gps_traces ADD COLUMN IF NOT EXISTS {col} TEXT")
        )


def downgrade():
    for col in _COLUMNS:
        op.execute(
            text(f"ALTER TABLE gps_traces DROP COLUMN IF EXISTS {col}")
        )
