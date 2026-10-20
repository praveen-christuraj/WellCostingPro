"""Well progress milestone columns for the daily cost register.

Adds the Well Spud Date & Time and Progress Completed Date & Time pair per
configuration scope (drilling / completion) to ``wells``. The daily cost
register counts actual days from the spud instant instead of the first sheet
date, and stops counting once the progress completion instant is entered.

Revision ID: e9a4c7b15d38
Revises: b729f61a
Create Date: 2026-10-20
"""

from alembic import op
import sqlalchemy as sa


revision = "e9a4c7b15d38"
down_revision = "b729f61a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for scope in ("drilling", "completion"):
        op.add_column("wells", sa.Column(f"{scope}_spud_at", sa.DateTime(), nullable=True))
        op.add_column("wells", sa.Column(f"{scope}_progress_completed_at", sa.DateTime(), nullable=True))
    # b729f61a created this user-entered amount at (24, 6); the ledger-wide
    # contract keeps every decimal at (28, 10) so entered digits are retained.
    with op.batch_alter_table("daily_cost_service_cost_items") as batch:
        batch.alter_column(
            "amount", existing_type=sa.Numeric(24, 6), existing_nullable=False,
            type_=sa.Numeric(28, 10),
        )


def downgrade() -> None:
    with op.batch_alter_table("daily_cost_service_cost_items") as batch:
        batch.alter_column(
            "amount", existing_type=sa.Numeric(28, 10), existing_nullable=False,
            type_=sa.Numeric(24, 6),
        )
    for scope in ("drilling", "completion"):
        op.drop_column("wells", f"{scope}_progress_completed_at")
        op.drop_column("wells", f"{scope}_spud_at")
