"""Retain itemized actual service charges."""
from alembic import op
import sqlalchemy as sa
revision = "b729f61a"
down_revision = "f6b9c2d4e810"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("daily_cost_service_cost_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("service_line_id", sa.String(36), sa.ForeignKey("daily_cost_service_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(24, 6), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_service_cost_item_amount"))
    op.create_index("ix_daily_cost_service_cost_items_service_line_id", "daily_cost_service_cost_items", ["service_line_id"])

def downgrade():
    op.drop_table("daily_cost_service_cost_items")
