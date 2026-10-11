"""AFE standard currency and per-currency conversion rates.

Revision ID: b2c8f1d4a9e6
Revises: a9d4e2f7c138
Create Date: 2026-10-11 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c8f1d4a9e6"
down_revision: Union[str, None] = "a9d4e2f7c138"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("afes") as batch:
        batch.add_column(sa.Column("standard_currency", sa.String(length=10), server_default="", nullable=False))

    op.create_table(
        "afe_exchange_rates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("afe_id", sa.String(length=36), nullable=False),
        sa.Column("currency_code", sa.String(length=10), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rate > 0", name="ck_afe_exchange_rates_rate"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["afe_id"], ["afes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("afe_id", "currency_code", name="uq_afe_exchange_rates_currency"),
    )
    op.create_index("ix_afe_exchange_rates_organization_id", "afe_exchange_rates", ["organization_id"])
    op.create_index("ix_afe_exchange_rates_afe", "afe_exchange_rates", ["afe_id"])


def downgrade() -> None:
    op.drop_index("ix_afe_exchange_rates_afe", table_name="afe_exchange_rates")
    op.drop_index("ix_afe_exchange_rates_organization_id", table_name="afe_exchange_rates")
    op.drop_table("afe_exchange_rates")
    with op.batch_alter_table("afes") as batch:
        batch.drop_column("standard_currency")
