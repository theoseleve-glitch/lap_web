"""037 -- Dead letter queue for failed Celery tasks.

Captures tasks that exhaust their retry budget so ops can inspect,
replay, or alert on persistent failures.

Roadmap item #0557.
"""

import sqlalchemy as sa
from alembic import op

revision = "037"
down_revision = "036"


def upgrade() -> None:
    op.create_table(
        "dead_letter_queue",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("task_name", sa.String(255), nullable=False),
        sa.Column("queue", sa.String(100), nullable=True),
        sa.Column("args", sa.Text, nullable=True),
        sa.Column("kwargs", sa.Text, nullable=True),
        sa.Column("exception_type", sa.String(255), nullable=True),
        sa.Column("exception_message", sa.Text, nullable=True),
        sa.Column("traceback", sa.Text, nullable=True),
        sa.Column("retries", sa.Integer, server_default=sa.text("0"), nullable=False),
        sa.Column("max_retries", sa.Integer, nullable=True),
        sa.Column("failed_at", sa.DateTime, server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'dead'"),
            nullable=False,
        ),
        sa.Column("replayed_at", sa.DateTime, nullable=True),
        sa.Column("workspace_id", sa.Integer, nullable=True),
    )
    op.create_index("idx_dlq_status", "dead_letter_queue", ["status"])
    op.create_index("idx_dlq_task_name", "dead_letter_queue", ["task_name"])
    op.create_index("idx_dlq_failed_at", "dead_letter_queue", ["failed_at"])


def downgrade() -> None:
    op.drop_table("dead_letter_queue")
