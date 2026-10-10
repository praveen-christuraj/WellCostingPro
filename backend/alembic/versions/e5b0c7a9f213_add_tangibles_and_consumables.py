"""Add Tangibles, Consumables (drill bits, mud chemicals, cement additives, fuel),
user-managed catalogue lists and their rate-revision history.

Revision ID: e5b0c7a9f213
Revises: d8a12f47b903
Create Date: 2026-10-10 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5b0c7a9f213"
down_revision: Union[str, None] = "d8a12f47b903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _org_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE")


def _lifecycle_columns() -> list[sa.Column]:
    """Columns shared with MasterDataRecord."""
    return [
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("description", sa.String(500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _rate_columns() -> list[sa.Column]:
    """Columns shared by PricedRecord (uplift columns are null for unit-priced types)."""
    return [
        sa.Column("unit_rate", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("cost_uplift", sa.Numeric(9, 4), nullable=True),
        sa.Column("final_cost", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(10), server_default="", nullable=False),
        sa.Column("po_number", sa.String(100), server_default="", nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("current_revision_number", sa.Integer(), server_default="0", nullable=False),
    ]


def _revision_table(table: str, parent_fk: str, parent_table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column(parent_fk, sa.String(36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("unit_rate", sa.Numeric(18, 4), nullable=False),
        sa.Column("previous_unit_rate", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("cost_uplift", sa.Numeric(9, 4), nullable=True),
        sa.Column("final_cost", sa.Numeric(18, 4), nullable=True),
        sa.Column("previous_final_cost", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(10), server_default="", nullable=False),
        sa.Column("uom", sa.String(50), server_default="", nullable=False),
        sa.Column("po_number", sa.String(100), server_default="", nullable=False),
        sa.Column("reason", sa.String(500), server_default="", nullable=False),
        sa.Column("recorded_by", sa.String(255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint([parent_fk], [f"{parent_table}.id"], ondelete="CASCADE"),
        _org_fk(),
        sa.UniqueConstraint(parent_fk, "revision_number", name=f"uq_{table}_number"),
    )
    op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    op.create_index(f"ix_{table}_{parent_fk}", table, [parent_fk])
    op.create_index(f"ix_{table}_effective_date", table, ["effective_date"])


def upgrade() -> None:
    op.create_table(
        "catalogue_options",
        *_lifecycle_columns(),
        sa.Column("list_key", sa.String(40), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("parent_key", sa.String(36), server_default="", nullable=False),
        sa.Column("value", sa.String(120), nullable=False),
        sa.Column("value_key", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parent_id"], ["catalogue_options.id"], ondelete="CASCADE"),
        _org_fk(),
        sa.UniqueConstraint("organization_id", "list_key", "parent_key", "value_key", name="uq_catalogue_options_value"),
    )
    op.create_index("ix_catalogue_options_organization_id", "catalogue_options", ["organization_id"])
    op.create_index("ix_catalogue_options_parent_id", "catalogue_options", ["parent_id"])
    op.create_index("ix_catalogue_options_list", "catalogue_options", ["organization_id", "list_key"])

    op.create_table(
        "tangibles",
        *_lifecycle_columns(),
        *_rate_columns(),
        sa.Column("tangible_code", sa.String(50), nullable=False),
        sa.Column("tangible_name", sa.String(200), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("category_id", sa.String(36), nullable=False),
        sa.Column("subcategory_id", sa.String(36), nullable=False),
        sa.Column("manufacturer_id", sa.String(36), nullable=False),
        sa.Column("uom", sa.String(50), server_default="", nullable=False),
        sa.Column("remarks", sa.String(500), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["category_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subcategory_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manufacturer_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        _org_fk(),
        sa.UniqueConstraint("organization_id", "tangible_code", name="uq_tangibles_org_code"),
        sa.CheckConstraint("scope IN ('Drilling', 'Completion', 'Others')", name="ck_tangibles_scope"),
    )
    op.create_index("ix_tangibles_organization_id", "tangibles", ["organization_id"])
    op.create_index("ix_tangibles_tangible_name", "tangibles", ["tangible_name"])
    op.create_index("ix_tangibles_category_id", "tangibles", ["category_id"])
    op.create_index("ix_tangibles_subcategory_id", "tangibles", ["subcategory_id"])
    op.create_index("ix_tangibles_manufacturer_id", "tangibles", ["manufacturer_id"])
    _revision_table("tangible_rate_revisions", "tangible_id", "tangibles")

    op.create_table(
        "drill_bits",
        *_lifecycle_columns(),
        *_rate_columns(),
        sa.Column("bit_code", sa.String(50), nullable=False),
        sa.Column("bit_name", sa.String(200), nullable=False),
        sa.Column("bit_type_id", sa.String(36), nullable=False),
        sa.Column("manufacturer_id", sa.String(36), nullable=False),
        sa.Column("model_no", sa.String(100), nullable=False),
        sa.Column("size", sa.String(60), nullable=False),
        sa.Column("iadc_code", sa.String(20), server_default="", nullable=False),
        sa.Column("serial_number", sa.String(100), server_default="", nullable=False),
        sa.Column("remarks", sa.String(500), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["bit_type_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manufacturer_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        _org_fk(),
        sa.UniqueConstraint("organization_id", "bit_code", name="uq_drill_bits_org_code"),
    )
    op.create_index("ix_drill_bits_organization_id", "drill_bits", ["organization_id"])
    op.create_index("ix_drill_bits_bit_name", "drill_bits", ["bit_name"])
    op.create_index("ix_drill_bits_bit_type_id", "drill_bits", ["bit_type_id"])
    op.create_index("ix_drill_bits_manufacturer_id", "drill_bits", ["manufacturer_id"])
    op.create_index("ix_drill_bits_serial_number", "drill_bits", ["serial_number"])
    _revision_table("drill_bit_rate_revisions", "drill_bit_id", "drill_bits")

    op.create_table(
        "mud_chemicals",
        *_lifecycle_columns(),
        *_rate_columns(),
        sa.Column("chemical_code", sa.String(50), nullable=False),
        sa.Column("chemical_name", sa.String(200), nullable=False),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("manufacturer_id", sa.String(36), nullable=True),
        sa.Column("part_number", sa.String(100), server_default="", nullable=False),
        sa.Column("uom", sa.String(50), server_default="", nullable=False),
        sa.Column("remarks", sa.String(500), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["group_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manufacturer_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        _org_fk(),
        sa.UniqueConstraint("organization_id", "chemical_code", name="uq_mud_chemicals_org_code"),
    )
    op.create_index("ix_mud_chemicals_organization_id", "mud_chemicals", ["organization_id"])
    op.create_index("ix_mud_chemicals_chemical_name", "mud_chemicals", ["chemical_name"])
    op.create_index("ix_mud_chemicals_group_id", "mud_chemicals", ["group_id"])
    op.create_index("ix_mud_chemicals_manufacturer_id", "mud_chemicals", ["manufacturer_id"])
    _revision_table("mud_chemical_rate_revisions", "mud_chemical_id", "mud_chemicals")

    op.create_table(
        "cement_additives",
        *_lifecycle_columns(),
        *_rate_columns(),
        sa.Column("additive_code", sa.String(50), nullable=False),
        sa.Column("additive_name", sa.String(200), nullable=False),
        sa.Column("additive_type_id", sa.String(36), nullable=False),
        sa.Column("manufacturer_id", sa.String(36), nullable=True),
        sa.Column("part_number", sa.String(100), server_default="", nullable=False),
        sa.Column("uom", sa.String(50), server_default="", nullable=False),
        sa.Column("remarks", sa.String(500), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["additive_type_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manufacturer_id"], ["catalogue_options.id"], ondelete="RESTRICT"),
        _org_fk(),
        sa.UniqueConstraint("organization_id", "additive_code", name="uq_cement_additives_org_code"),
    )
    op.create_index("ix_cement_additives_organization_id", "cement_additives", ["organization_id"])
    op.create_index("ix_cement_additives_additive_name", "cement_additives", ["additive_name"])
    op.create_index("ix_cement_additives_additive_type_id", "cement_additives", ["additive_type_id"])
    op.create_index("ix_cement_additives_manufacturer_id", "cement_additives", ["manufacturer_id"])
    _revision_table("cement_additive_rate_revisions", "cement_additive_id", "cement_additives")

    op.create_table(
        "fuel_types",
        *_lifecycle_columns(),
        *_rate_columns(),
        sa.Column("fuel_code", sa.String(30), nullable=False),
        sa.Column("fuel_name", sa.String(150), nullable=False),
        sa.Column("uom", sa.String(50), server_default="L", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        _org_fk(),
        sa.UniqueConstraint("organization_id", "fuel_code", name="uq_fuel_types_org_code"),
    )
    op.create_index("ix_fuel_types_organization_id", "fuel_types", ["organization_id"])
    _revision_table("fuel_price_revisions", "fuel_type_id", "fuel_types")


def downgrade() -> None:
    op.drop_table("fuel_price_revisions")
    op.drop_table("fuel_types")
    op.drop_table("cement_additive_rate_revisions")
    op.drop_table("cement_additives")
    op.drop_table("mud_chemical_rate_revisions")
    op.drop_table("mud_chemicals")
    op.drop_table("drill_bit_rate_revisions")
    op.drop_table("drill_bits")
    op.drop_table("tangible_rate_revisions")
    op.drop_table("tangibles")
    op.drop_table("catalogue_options")
