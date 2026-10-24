"""Versioned current service rates and workspace-shared costing sets.

Revision ID: c7a1d9e4b205
Revises: b4d1e7a9c326
"""
from alembic import op
import sqlalchemy as sa
revision = "c7a1d9e4b205"
down_revision = "b4d1e7a9c326"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("daily_cost_baseline_service_rates", sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user_costing_sets", sa.Column("is_global", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("user_costing_sets", "is_global")
    op.drop_column("daily_cost_baseline_service_rates", "is_current")
