"""Add the model timestamp omitted from daily-cost amendments.

Revision ID: f9a2c7d4e611
Revises: e8c3a1f75d24
Create Date: 2026-10-30 20:00:00.000000

The amendment model has always exposed ``created_at``, but the migration that
created ``daily_cost_amendments`` omitted it.  PostgreSQL therefore rejected
every ORM SELECT for amendment history.  Existing rows inherit their
``reopened_at`` timestamp so the repair preserves their actual event time.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a2c7d4e611"
down_revision: Union[str, None] = "e8c3a1f75d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "daily_cost_amendments",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE daily_cost_amendments "
            "SET created_at = reopened_at "
            "WHERE created_at IS NULL"
        )
    )
    with op.batch_alter_table("daily_cost_amendments") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("daily_cost_amendments") as batch_op:
        batch_op.drop_column("created_at")
