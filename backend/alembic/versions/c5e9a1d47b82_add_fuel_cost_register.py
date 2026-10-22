"""Add the Fuel Cost Register and its opening-stock capability.

Revision ID: c5e9a1d47b82
Revises: f1a7c3d95b28
Create Date: 2026-10-22

The Fuel Cost Register is a rig-scoped daily AGO ledger under Daily Cost
Management. Four column-wise tables are added:

* ``fuel_companies`` — the registered companies (usually extracted from
  Master Data vendors) plus the daily entry set flag,
* ``fuel_company_categories`` — each company's own categories,
* ``fuel_cost_entries`` — one rig/day with rig engine AGO, gas recording,
  opening/closing stock and receipts,
* ``fuel_cost_company_lines`` — company (and optional category) consumption.

No JSON is stored and no price/currency column is introduced: the register is
measured in litres, and its material balance is derived at read time.

The migration also grants every workspace owner the separately assignable
``daily-cost:fuel-opening-stock`` capability, which guards the opening-stock
override that breaks the physical carry-forward chain.
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "c5e9a1d47b82"
down_revision: Union[str, None] = "f1a7c3d95b28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPENING_STOCK_CAPABILITY = "daily-cost:fuel-opening-stock"


def upgrade() -> None:
    op.create_table(
        "fuel_companies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=True),
        sa.Column("vendor_code_snapshot", sa.String(length=50), server_default="", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('vendor', 'manual', 'import')", name="ck_fuel_companies_source"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "company_name", name="uq_fuel_companies_org_name"),
    )
    op.create_index(
        "ix_fuel_companies_organization_id", "fuel_companies", ["organization_id"], unique=False
    )
    op.create_index("ix_fuel_companies_vendor_id", "fuel_companies", ["vendor_id"], unique=False)
    op.create_index(
        "ix_fuel_companies_org_deleted", "fuel_companies", ["organization_id", "is_deleted"], unique=False
    )
    op.create_index(
        "ix_fuel_companies_org_default", "fuel_companies", ["organization_id", "is_default"], unique=False
    )

    op.create_table(
        "fuel_company_categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("category_name", sa.String(length=120), nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["fuel_companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "category_name", name="uq_fuel_company_categories_company_name"
        ),
    )
    op.create_index(
        "ix_fuel_company_categories_organization_id",
        "fuel_company_categories",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_fuel_company_categories_company_id",
        "fuel_company_categories",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_fuel_company_categories_org",
        "fuel_company_categories",
        ["organization_id", "company_id"],
        unique=False,
    )

    op.create_table(
        "fuel_cost_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("rig_id", sa.String(length=36), nullable=False),
        sa.Column("rig_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("rig_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("cost_date", sa.Date(), nullable=False),
        sa.Column(
            "rig_engine_consumption", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False
        ),
        sa.Column("rig_engine_remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column(
            "gas_consumption", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False
        ),
        sa.Column("gas_remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("opening_stock", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("opening_overridden", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("opening_remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column(
            "receipt_quantity", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False
        ),
        sa.Column("receipt_remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("closing_stock", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("closing_remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("remarks", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rig_engine_consumption >= 0", name="ck_fuel_cost_entries_engine"),
        sa.CheckConstraint("gas_consumption >= 0", name="ck_fuel_cost_entries_gas"),
        sa.CheckConstraint(
            "opening_stock IS NULL OR opening_stock >= 0", name="ck_fuel_cost_entries_opening"
        ),
        sa.CheckConstraint("receipt_quantity >= 0", name="ck_fuel_cost_entries_receipt"),
        sa.CheckConstraint(
            "closing_stock IS NULL OR closing_stock >= 0", name="ck_fuel_cost_entries_closing"
        ),
        sa.CheckConstraint("revision >= 0", name="ck_fuel_cost_entries_revision"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "rig_id", "cost_date", name="uq_fuel_cost_entries_org_rig_date"
        ),
    )
    op.create_index(
        "ix_fuel_cost_entries_organization_id", "fuel_cost_entries", ["organization_id"], unique=False
    )
    op.create_index("ix_fuel_cost_entries_rig_id", "fuel_cost_entries", ["rig_id"], unique=False)
    op.create_index("ix_fuel_cost_entries_cost_date", "fuel_cost_entries", ["cost_date"], unique=False)
    op.create_index(
        "ix_fuel_cost_entries_org_date", "fuel_cost_entries", ["organization_id", "cost_date"], unique=False
    )
    op.create_index(
        "ix_fuel_cost_entries_org_deleted_date",
        "fuel_cost_entries",
        ["organization_id", "is_deleted", "cost_date"],
        unique=False,
    )

    op.create_table(
        "fuel_cost_company_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("company_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("category_name_snapshot", sa.String(length=120), server_default="", nullable=False),
        sa.Column("litres", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("source", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("litres >= 0", name="ck_fuel_cost_company_lines_litres"),
        sa.CheckConstraint(
            "source IN ('manual', 'import')", name="ck_fuel_cost_company_lines_source"
        ),
        sa.ForeignKeyConstraint(["category_id"], ["fuel_company_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["fuel_companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entry_id"], ["fuel_cost_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entry_id",
            "company_id",
            "category_id",
            name="uq_fuel_cost_company_lines_entry_company_category",
        ),
    )
    op.create_index(
        "ix_fuel_cost_company_lines_organization_id",
        "fuel_cost_company_lines",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_fuel_cost_company_lines_entry_id", "fuel_cost_company_lines", ["entry_id"], unique=False
    )
    op.create_index(
        "ix_fuel_cost_company_lines_company_id", "fuel_cost_company_lines", ["company_id"], unique=False
    )
    op.create_index(
        "ix_fuel_cost_company_lines_category_id", "fuel_cost_company_lines", ["category_id"], unique=False
    )
    op.create_index(
        "ix_fuel_cost_company_lines_entry_order",
        "fuel_cost_company_lines",
        ["entry_id", "sort_order"],
        unique=False,
    )
    op.create_index(
        "ix_fuel_cost_company_lines_org_company_date",
        "fuel_cost_company_lines",
        ["organization_id", "company_id", "created_at"],
        unique=False,
    )

    # Grant the separately assignable opening-stock override to every owner role.
    bind = op.get_bind()
    organizations = sa.table("organizations", sa.column("id", sa.String(36)))
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String(36)),
        sa.column("organization_id", sa.String(36)),
        sa.column("key", sa.String(100)),
        sa.column("description", sa.String(500)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    roles = sa.table(
        "roles", sa.column("id", sa.String(36)), sa.column("organization_id", sa.String(36)),
        sa.column("is_owner", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("role_id", sa.String(36)), sa.column("permission_id", sa.String(36))
    )
    for (organization_id,) in bind.execute(sa.select(organizations.c.id)):
        owner_role_id = bind.execute(
            sa.select(roles.c.id).where(
                roles.c.organization_id == organization_id, roles.c.is_owner.is_(True)
            )
        ).scalar_one_or_none()
        permission_id = bind.execute(
            sa.select(permissions.c.id).where(
                permissions.c.organization_id == organization_id,
                permissions.c.key == OPENING_STOCK_CAPABILITY,
            )
        ).scalar_one_or_none()
        if permission_id is None:
            permission_id = str(uuid4())
            bind.execute(
                permissions.insert().values(
                    id=permission_id,
                    organization_id=organization_id,
                    key=OPENING_STOCK_CAPABILITY,
                    description="Override the Fuel Cost Register opening stock and recalculate the material balance",
                    created_at=datetime.now(timezone.utc),
                )
            )
        if owner_role_id:
            assigned = bind.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == owner_role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).first()
            if assigned is None:
                bind.execute(
                    role_permissions.insert().values(role_id=owner_role_id, permission_id=permission_id)
                )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE key = 'daily-cost:fuel-opening-stock')"
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE key = 'daily-cost:fuel-opening-stock'"))
    for index in (
        "ix_fuel_cost_company_lines_org_company_date",
        "ix_fuel_cost_company_lines_entry_order",
        "ix_fuel_cost_company_lines_category_id",
        "ix_fuel_cost_company_lines_company_id",
        "ix_fuel_cost_company_lines_entry_id",
        "ix_fuel_cost_company_lines_organization_id",
    ):
        op.drop_index(index, table_name="fuel_cost_company_lines")
    op.drop_table("fuel_cost_company_lines")
    for index in (
        "ix_fuel_cost_entries_org_deleted_date",
        "ix_fuel_cost_entries_org_date",
        "ix_fuel_cost_entries_cost_date",
        "ix_fuel_cost_entries_rig_id",
        "ix_fuel_cost_entries_organization_id",
    ):
        op.drop_index(index, table_name="fuel_cost_entries")
    op.drop_table("fuel_cost_entries")
    for index in (
        "ix_fuel_company_categories_org",
        "ix_fuel_company_categories_company_id",
        "ix_fuel_company_categories_organization_id",
    ):
        op.drop_index(index, table_name="fuel_company_categories")
    op.drop_table("fuel_company_categories")
    for index in (
        "ix_fuel_companies_org_default",
        "ix_fuel_companies_org_deleted",
        "ix_fuel_companies_vendor_id",
        "ix_fuel_companies_organization_id",
    ):
        op.drop_index(index, table_name="fuel_companies")
    op.drop_table("fuel_companies")
