"""059 — user_corners (PG) + track_surfaces_global mu_lat defaults.

Two unrelated but bundled changes, both additive / non-destructive:

1. Create the ``user_corners`` table on PostgreSQL. Mirrors the SQLite
   definition in ``db/schema.py:1052``. Until now this table existed in
   SQLite (desktop) mode only — the PG migration was never written. The
   pipeline's ``run_track_decomposition_v2`` (step 10g) silently tried
   ``SELECT * FROM user_corners …``, hit ``UndefinedTable``, swallowed
   it at DEBUG level, and left the connection in ``InFailedSqlTransaction``
   state — which then poisoned downstream queries including
   ``S10h_fetch_user_corners`` and the per-bin loop inside
   ``upsert_global_surface``. (Day-14 root-cause investigation.)

2. ``ALTER TABLE track_surfaces_global`` to give ``mu_lat_p95`` and
   ``mu_lat_mean`` default values of ``0.0``. Both columns are
   ``NOT NULL`` but have no default. The expected workflow was:
   ``upsert_global_grip`` runs first (inserts mu_lat values from the
   grip_map), then ``upsert_global_surface`` runs and UPDATEs the same
   row with elevation/slope/etc. via ``ON CONFLICT … DO UPDATE``. When
   the grip path is skipped or fails, the surface path's INSERT
   violates NOT NULL on mu_lat_*. Defaulting to 0.0 lets the surface
   row be created standalone (sample_count=0 means the placeholder mu
   values are weighted as zero by the online-merge math in
   ``upsert_global_grip`` whenever it does later succeed). The
   ``TrackSurface`` object passed to ``upsert_global_surface`` does NOT
   carry mu_lat per bin — those live on ``surface.grip_2d`` which is
   not bin-aligned — so data-correct population from the surface
   producer is not possible without a deeper refactor (logged as
   Day-15 follow-up in CLEANUP_LOG).

Revision ID: 059
Revises: 055

Forks the chain off 055 (current prod head) rather than 058. Migrations
056-058 were committed to the codebase but never applied to prod because
056 has a pre-existing type-mismatch bug in its foreign-key definition
(``analysis_runs.session_id INTEGER`` vs ``sessions.session_id TEXT``).
Rebasing 059 directly off 055 lets the Day-14 unblock land without first
fixing or skipping the broken 056. This creates two alembic heads
(058 unapplied + 059 applied) — flagged for Day-15 to either fix 056-058
or write a merge migration.
"""
from alembic import op
import sqlalchemy as sa


revision = "059"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) user_corners on PG (mirrors db/schema.py:1052 SQLite definition).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_corners (
            id              SERIAL PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES sessions(session_id),
            corner_index    INTEGER NOT NULL,
            lat_entry       DOUBLE PRECISION,
            lon_entry       DOUBLE PRECISION,
            lat_apex        DOUBLE PRECISION,
            lon_apex        DOUBLE PRECISION,
            lat_exit        DOUBLE PRECISION,
            lon_exit        DOUBLE PRECISION,
            s_entry         DOUBLE PRECISION,
            s_apex          DOUBLE PRECISION,
            s_exit          DOUBLE PRECISION,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (session_id, corner_index)
        )
        """
    )
    # Index for the pipeline's session-keyed lookup.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_corners_session "
        "ON user_corners (session_id)"
    )

    # 2) track_surfaces_global mu_lat default 0.0. Placeholder values
    # written by upsert_global_surface when grip path hasn't seeded the
    # row; weighted as zero by the online-merge math when grip later
    # succeeds.
    op.execute(
        "ALTER TABLE track_surfaces_global "
        "ALTER COLUMN mu_lat_p95 SET DEFAULT 0.0"
    )
    op.execute(
        "ALTER TABLE track_surfaces_global "
        "ALTER COLUMN mu_lat_mean SET DEFAULT 0.0"
    )


def downgrade() -> None:
    # Reverse #2 first (column defaults), then #1 (drop user_corners).
    op.execute(
        "ALTER TABLE track_surfaces_global "
        "ALTER COLUMN mu_lat_mean DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE track_surfaces_global "
        "ALTER COLUMN mu_lat_p95 DROP DEFAULT"
    )
    op.execute("DROP INDEX IF EXISTS idx_user_corners_session")
    op.execute("DROP TABLE IF EXISTS user_corners")
