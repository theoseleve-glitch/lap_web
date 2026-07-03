"""081 — driver feeling + competition data model (W3 Feeling→Scoring).

Adds subjective/result columns to sessions and a session-scoped, RLS-enabled
session_competitors table. Session-scoped (no dependency on W2 race_configs) so
W3 builds in parallel. Chains off the deployed head 077.

Migration numbering: 078/079 are taken on the optimizer branches and 080 is
reserved for the optimizer C-layer; W3 claims 081. Integration across the
parallel W/optimizer branches will produce multiple heads off 077 and needs a
merge migration at that time (precedent: 061_merge_heads_*).

RLS pattern mirrors 046_endurance_stints + the 064/069 hardening: workspace_id
NOT NULL FK, ENABLE + FORCE RLS, tenant_isolation policy on the canonical
app.current_workspace_id GUC, guarded grants to telemetry_app/telemetry_maint.
"""
from alembic import op
import sqlalchemy as sa

revision = "081_feeling_competition"
down_revision = "077_stripe_pending_entitlements"
branch_labels = None
depends_on = None

_SESSION_COLUMNS = [
    ("result_tags", sa.Text),                    # JSON array of result tags
    ("driver_perceived_conditions", sa.Text),    # free string
    ("felt_performance_rating", sa.Integer),     # 1-10 self rating
    ("race_position", sa.Integer),
    ("race_total_competitors", sa.Integer),
    ("race_gap_to_leader_s", sa.Float),
    ("race_gap_to_nearest_s", sa.Float),
    ("race_laps_completed", sa.Integer),
    ("race_is_dnf", sa.Integer),                 # 0/1
]


def upgrade() -> None:
    # ── 1. sessions reflection/result columns (sessions already has RLS) ──
    for name, coltype in _SESSION_COLUMNS:
        op.add_column("sessions", sa.Column(name, coltype, nullable=True))

    # ── 2. session_competitors (session-scoped, RLS) ──
    op.create_table(
        "session_competitors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text,
                  sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("competitor_name", sa.Text, nullable=False),
        sa.Column("final_position", sa.Integer, nullable=True),
        sa.Column("gap_to_this_driver_s", sa.Float, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("workspace_id", sa.Integer,
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
                  server_default=sa.text("current_setting('app.current_workspace_id')::integer")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_session_competitors_session", "session_competitors", ["session_id"])
    op.create_index("idx_session_competitors_workspace", "session_competitors", ["workspace_id"])

    # RLS: ENABLE + FORCE (064 already ran, so FORCE must be set here explicitly).
    op.execute("ALTER TABLE session_competitors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE session_competitors FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY session_competitors_tenant_isolation ON session_competitors "
        "USING (workspace_id = current_setting('app.current_workspace_id', true)::int) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id', true)::int)"
    )

    # Grants guarded so a dev DB without the roles still migrates (pattern: 077).
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE, DELETE ON session_competitors TO telemetry_app;
            GRANT USAGE, SELECT ON SEQUENCE session_competitors_id_seq TO telemetry_app;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE, DELETE ON session_competitors TO telemetry_maint;
            GRANT USAGE, SELECT ON SEQUENCE session_competitors_id_seq TO telemetry_maint;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS session_competitors_tenant_isolation ON session_competitors")
    op.drop_table("session_competitors")
    for name, _ in reversed(_SESSION_COLUMNS):
        op.drop_column("sessions", name)
