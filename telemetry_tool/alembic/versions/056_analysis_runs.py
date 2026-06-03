"""056 — NEUTRALIZED (no-op).

ORIGINALLY created the ``analysis_runs`` table. It was NEVER applied to
production (prod ``alembic_version=060`` has no ``analysis_runs`` table) and it
carried a fatal bug: ``session_id`` was declared ``sa.Integer`` while
``sessions.session_id`` is ``TEXT``, so the FK constraint fails to build on a
fresh database.

This sits on the orphaned ``055 → 056 → 057 → 058`` branch (see 060's docstring:
"058 stays orphaned"). To converge the alembic graph to a SINGLE head without
reintroducing this never-applied / broken schema to production, the branch is
neutralized to no-ops and joined to the live ``059 → 060`` chain via a merge
revision (061_merge_heads).

The original DDL is preserved in git history. If analysis_runs / bundles /
app_events are revived, re-add them as a NEW forward migration after the current
single head — fixing the session_id type (TEXT) and the
``app.current_workspace_id`` GUC name first.
"""

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Neutralized — see module docstring. No schema change.
    pass


def downgrade() -> None:
    pass
