"""057 — Bundle intake tables + analysis_runs.bundle_id link.

Tables:
  uploaded_bundles           aggregate root (immutable core columns)
  bundle_session_metadata    normalized metadata for queries
  bundle_artifacts           inner-file manifest rows
  bundle_source_provenance   provenance record

All RLS-scoped by workspace_id. uploaded_bundles has a trigger enforcing
immutability of core columns.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "057"
down_revision = "056"


def upgrade():
    # ── uploaded_bundles ────────────────────────────────────
    op.create_table(
        "uploaded_bundles",
        sa.Column("bundle_id", sa.Text, primary_key=True),
        sa.Column(
            "workspace_id", sa.Integer,
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text("current_setting('app.current_workspace_id')::integer"),
        ),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("schema_version", sa.SmallInteger, nullable=False),
        sa.Column("checksum_sha256", sa.CHAR(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("raw_path", sa.Text, nullable=False),
        sa.Column("identity_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("intake_reasons", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.UniqueConstraint("workspace_id", "checksum_sha256", name="uq_bundles_ws_checksum"),
    )
    op.create_index("idx_bundles_workspace", "uploaded_bundles", ["workspace_id"])
    op.create_index("idx_bundles_fingerprint", "uploaded_bundles",
                    ["workspace_id", "identity_fingerprint"])
    op.execute(
        "CREATE INDEX idx_bundles_uploaded_at ON uploaded_bundles "
        "(workspace_id, uploaded_at DESC)"
    )
    op.execute("ALTER TABLE uploaded_bundles ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY uploaded_bundles_tenant ON uploaded_bundles "
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    )

    # Immutability trigger on core columns
    op.execute(
        """
        CREATE OR REPLACE FUNCTION _uploaded_bundles_immutable() RETURNS trigger AS $$
        BEGIN
          IF NEW.raw_path IS DISTINCT FROM OLD.raw_path
             OR NEW.checksum_sha256 IS DISTINCT FROM OLD.checksum_sha256
             OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
             OR NEW.schema_version IS DISTINCT FROM OLD.schema_version THEN
            RAISE EXCEPTION 'uploaded_bundles core columns are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_uploaded_bundles_immutable "
        "BEFORE UPDATE ON uploaded_bundles "
        "FOR EACH ROW EXECUTE FUNCTION _uploaded_bundles_immutable()"
    )

    # ── bundle_session_metadata ─────────────────────────────
    op.create_table(
        "bundle_session_metadata",
        sa.Column(
            "bundle_id", sa.Text,
            sa.ForeignKey("uploaded_bundles.bundle_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("workspace_id", sa.Integer, nullable=False),
        sa.Column("sim", sa.Text, nullable=False),
        sa.Column("vehicle_key", sa.Text, nullable=False),
        sa.Column("track_key", sa.Text, nullable=False),
        sa.Column("session_type", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vehicle_spec", JSONB, nullable=False),
        sa.Column("track_spec", JSONB, nullable=False),
        sa.Column("session_info", JSONB, nullable=False),
        sa.Column("channels_present", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("lap_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_s", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("readiness_is_ready", sa.Boolean, nullable=False),
        sa.Column("readiness_reasons", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("readiness_degraded", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("extra", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(
        "idx_bsm_sim_vehicle_track", "bundle_session_metadata",
        ["workspace_id", "sim", "vehicle_key", "track_key"],
    )
    op.execute("ALTER TABLE bundle_session_metadata ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY bsm_tenant ON bundle_session_metadata "
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    )

    # ── bundle_artifacts ────────────────────────────────────
    op.create_table(
        "bundle_artifacts",
        sa.Column(
            "bundle_id", sa.Text,
            sa.ForeignKey("uploaded_bundles.bundle_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Integer, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("checksum_sha256", sa.CHAR(64), nullable=False),
        sa.PrimaryKeyConstraint("bundle_id", "path", name="pk_bundle_artifacts"),
    )
    op.create_index("idx_bundle_artifacts_role", "bundle_artifacts", ["bundle_id", "role"])
    op.execute("ALTER TABLE bundle_artifacts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY ba_tenant ON bundle_artifacts "
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    )

    # ── bundle_source_provenance ────────────────────────────
    op.create_table(
        "bundle_source_provenance",
        sa.Column(
            "bundle_id", sa.Text,
            sa.ForeignKey("uploaded_bundles.bundle_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("workspace_id", sa.Integer, nullable=False),
        sa.Column("logger_version", sa.Text, nullable=False),
        sa.Column("logger_build", sa.Text),
        sa.Column("capture_method", sa.Text, nullable=False),
        sa.Column("captured_by_user_id", sa.Integer),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_hostname", sa.Text),
        sa.Column("client_os", sa.Text),
    )
    op.execute("ALTER TABLE bundle_source_provenance ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY bsp_tenant ON bundle_source_provenance "
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    )

    # ── Link analysis_runs → bundles (nullable, back-compat) ─
    op.add_column(
        "analysis_runs",
        sa.Column(
            "bundle_id", sa.Text,
            sa.ForeignKey("uploaded_bundles.bundle_id", ondelete="SET NULL"),
        ),
    )
    op.create_index("idx_analysis_runs_bundle", "analysis_runs", ["bundle_id"])


def downgrade():
    op.drop_index("idx_analysis_runs_bundle", table_name="analysis_runs")
    op.drop_column("analysis_runs", "bundle_id")

    for t in ("bundle_source_provenance", "bundle_artifacts",
              "bundle_session_metadata"):
        op.execute(f"DROP POLICY IF EXISTS {_policy_name(t)} ON {t}")
    op.execute("DROP POLICY IF EXISTS uploaded_bundles_tenant ON uploaded_bundles")

    op.execute("DROP TRIGGER IF EXISTS trg_uploaded_bundles_immutable ON uploaded_bundles")
    op.execute("DROP FUNCTION IF EXISTS _uploaded_bundles_immutable()")

    op.drop_table("bundle_source_provenance")
    op.drop_index("idx_bundle_artifacts_role", table_name="bundle_artifacts")
    op.drop_table("bundle_artifacts")
    op.drop_index("idx_bsm_sim_vehicle_track", table_name="bundle_session_metadata")
    op.drop_table("bundle_session_metadata")
    op.execute("DROP INDEX IF EXISTS idx_bundles_uploaded_at")
    op.drop_index("idx_bundles_fingerprint", table_name="uploaded_bundles")
    op.drop_index("idx_bundles_workspace", table_name="uploaded_bundles")
    op.drop_table("uploaded_bundles")


def _policy_name(table: str) -> str:
    return {
        "bundle_source_provenance": "bsp_tenant",
        "bundle_artifacts": "ba_tenant",
        "bundle_session_metadata": "bsm_tenant",
    }[table]
