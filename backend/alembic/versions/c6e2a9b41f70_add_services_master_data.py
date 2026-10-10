"""Add tenant-scoped Services to Master Data Management.

Revision ID: c6e2a9b41f70
Revises: b7f4c2d91e05
Create Date: 2026-10-10 10:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6e2a9b41f70"
down_revision: Union[str, None] = "b7f4c2d91e05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service_code", sa.String(length=50), nullable=False),
        sa.Column("service_name", sa.String(length=200), nullable=False),
        sa.Column("service_category", sa.String(length=50), nullable=False),
        sa.Column("provider_type", sa.String(length=30), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "service_category IN ('Drilling Services', 'Completion Services')",
            name="ck_services_category",
        ),
        sa.CheckConstraint(
            "provider_type IN ('In House Services', 'Third Party Services')",
            name="ck_services_provider_type",
        ),
        sa.CheckConstraint(
            "(provider_type = 'Third Party Services' AND vendor_id IS NOT NULL) OR "
            "(provider_type = 'In House Services' AND vendor_id IS NULL)",
            name="ck_services_provider_vendor",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "service_code", name="uq_services_org_code"),
    )
    op.create_index(op.f("ix_services_organization_id"), "services", ["organization_id"], unique=False)
    op.create_index(op.f("ix_services_vendor_id"), "services", ["vendor_id"], unique=False)
    op.create_index(
        "uq_services_org_name_ci",
        "services",
        ["organization_id", sa.text("lower(service_name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_services_org_name_ci", table_name="services")
    op.drop_index(op.f("ix_services_vendor_id"), table_name="services")
    op.drop_index(op.f("ix_services_organization_id"), table_name="services")
    op.drop_table("services")
