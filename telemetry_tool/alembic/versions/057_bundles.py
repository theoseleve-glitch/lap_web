"""057 — NEUTRALIZED (no-op).

ORIGINALLY created the bundle-intake tables (``uploaded_bundles`` etc.) and
``op.add_column("analysis_runs", ...)`` — so it hard-depended on 056. NEVER
applied to production. Part of the orphaned ``055 → 056 → 057 → 058`` branch.

Neutralized (together with 056 and 058) so the alembic graph converges to a
single head without reintroducing never-applied schema to prod. Original DDL is
in git history; re-add as a NEW forward migration after the single head if the
feature is revived. See 056's docstring for the full rationale.
"""

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Neutralized — see module docstring. No schema change.
    pass


def downgrade() -> None:
    pass
