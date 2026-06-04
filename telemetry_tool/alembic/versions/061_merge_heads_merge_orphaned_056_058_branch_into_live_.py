"""061 — merge the neutralized 056-058 branch into the live 059->060 chain.

Converges the alembic graph to a SINGLE head. Background:
  - 055 forked into two branches: an ORPHANED 056->057->058 branch (analysis_runs
    / bundles / app_events; never applied to prod; fatal FK-type bug in 056,
    wrong-GUC bug in 058) and the LIVE 059->060 chain production runs.
  - 056/057/058 are NEUTRALIZED to no-ops (see those files), so this merge does
    NOT reintroduce their never-applied schema to prod: production (at 060)
    upgrades through three no-ops + this empty merge with ZERO schema change.
This is an empty (no-DDL) merge revision; its only job is to unify the two heads.

Revision ID: 061_merge_heads
Revises: 058, 060
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '061_merge_heads'
down_revision: Union[str, None] = ('058', '060')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
