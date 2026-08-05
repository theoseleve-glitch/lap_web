"""086 -- driving_events table (Phase 2 of driving-pattern-recognition).

Holds MULTIPLE events per (session, lap, corner) -- corner_metrics cannot,
since it carries UNIQUE(session_id, lap_number, corner_id). Each row is a
single detected driving event (e.g. over_slowing, late_apex) within a corner,
scoped to a normalized-distance window [s_norm_start, s_norm_end].

UNIQUE(session_id, lap_number, corner_id, event_type) is required, not
optional: nothing in the repo deletes corner rows before rewriting, so
without it every reprocess doubles the table. It also gives sql_compat's
INSERT OR REPLACE -> ON CONFLICT translation a conflict target to target on
PostgreSQL.

RLS pattern mirrors 081_feeling_competition (itself mirroring
046_endurance_stints + the 064/069 hardening): workspace_id NOT NULL FK,
ENABLE + FORCE RLS, tenant_isolation policy on the canonical
app.current_workspace_id GUC, guarded grants to telemetry_app/telemetry_maint.

⛔ DEPLOY ORDERING IS LOAD-BEARING. `db/queries.py`'s INSERT_DRIVING_EVENT
names this table unconditionally, so code serving before this revision is
applied raises UndefinedTable on every session that produces events. On the
`s15_persist` path that is ONE transaction, so an unguarded failure there
aborts it and the later COMMIT becomes a silent ROLLBACK -- losing laps, GPS
traces, scores, theoretical data and corner metrics as well, behind a single
WARNING line naming only driving events. `_persist_driving_events` now
contains that with a SAVEPOINT, but the ordering is still mandatory: with
this table missing, every driving event in the window is lost anyway.
Procedure: ``docs/runbooks/driving-events-085-086-deploy.md`` (§1b, §3 check
3, §5). The downgrade DROPS the table and everything in it.
"""
from alembic import op
import sqlalchemy as sa

revision = "086_driving_events"
down_revision = "085_grip_anchor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driving_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("lap_number", sa.Integer, nullable=False),
        sa.Column("corner_id", sa.Integer, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("s_norm_start", sa.Float, nullable=True),
        sa.Column("s_norm_end", sa.Float, nullable=True),
        sa.Column("magnitude", sa.Float, nullable=True),
        sa.Column("magnitude_unit", sa.Text, nullable=True),
        sa.Column("time_cost_s", sa.Float, nullable=True),
        sa.Column("validity", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("n_samples_in_window", sa.Integer, nullable=True),
        # Spec SS5.1: mandatory on every event -- no number is quoted
        # without saying what it was measured against. Nullable in the
        # DDL only so a pre-086 row could never block the migration;
        # every writer supplies it and DrivingEvent refuses to construct
        # without one.
        sa.Column("anchor_tier", sa.Text, nullable=True),
        sa.Column("anchor_reason", sa.Text, nullable=True),
        sa.Column("evidence_json", sa.Text, nullable=True),
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
                  server_default=sa.text("current_setting('app.current_workspace_id')::integer")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "session_id", "lap_number", "corner_id", "event_type",
            name="uq_driving_events_session_lap_corner_event",
        ),
    )
    op.create_index("idx_driving_events_session", "driving_events", ["session_id"])
    op.create_index("idx_driving_events_workspace", "driving_events", ["workspace_id"])
    # The ranked read orders by cost.
    op.create_index("idx_driving_events_session_cost", "driving_events", ["session_id", "time_cost_s"])

    # RLS: ENABLE + FORCE (064 already ran, so FORCE must be set here explicitly).
    op.execute("ALTER TABLE driving_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE driving_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY driving_events_tenant_isolation ON driving_events "
        "USING (workspace_id = current_setting('app.current_workspace_id', true)::int) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id', true)::int)"
    )

    # Grants guarded so a dev DB without the roles still migrates (pattern: 077).
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE, DELETE ON driving_events TO telemetry_app;
            GRANT USAGE, SELECT ON SEQUENCE driving_events_id_seq TO telemetry_app;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE, DELETE ON driving_events TO telemetry_maint;
            GRANT USAGE, SELECT ON SEQUENCE driving_events_id_seq TO telemetry_maint;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS driving_events_tenant_isolation ON driving_events")
    op.drop_table("driving_events")
