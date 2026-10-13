"""Currency default flag.

Revision ID: c9b7e4a2d518
Revises: 7c1f4a8d92b6
Create Date: 2026-10-13 08:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9b7e4a2d518"
down_revision: Union[str, None] = "7c1f4a8d92b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("currencies") as batch:
        batch.add_column(sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False))
    op.create_index(
        "uq_currencies_org_default",
        "currencies",
        ["organization_id"],
        unique=True,
        sqlite_where=sa.text("is_default"),
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index("uq_currencies_org_default", table_name="currencies")
    with op.batch_alter_table("currencies") as batch:
        batch.drop_column("is_default")
