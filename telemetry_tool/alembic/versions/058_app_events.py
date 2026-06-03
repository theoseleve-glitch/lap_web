"""058 — NEUTRALIZED (no-op).

ORIGINALLY created the partitioned ``app_events`` table. NEVER applied to
production. It also carried the migration-044-class bug: its RLS policy used the
WRONG GUC ``current_setting('app.workspace_id')`` instead of the canonical
``app.current_workspace_id`` used everywhere else.

This is the orphaned head of the ``055 → 056 → 057 → 058`` branch (see 060's
docstring). Neutralized together with 056/057 so the alembic graph converges to
a single head via the 061_merge_heads merge revision, without reintroducing
never-applied / buggy schema to prod. Original DDL is in git history; re-add as
a NEW forward migration (with the correct GUC name) if app_events is revived.
"""

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Neutralized — see module docstring. No schema change.
    pass


def downgrade() -> None:
    pass
