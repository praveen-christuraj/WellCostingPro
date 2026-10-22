"""Add two-sided revision lines for SOW adjustments.

Revision ID: d5c9e1a7b382
Revises: c2f5d8a41b67
Create Date: 2026-10-22 10:00:00.000000

SOW adjustments used to carry only derived aggregates (planned days, section
counts, cost-group totals) plus a free-text narrative. This migration adds the
line tables that hold the actual revision entries, entered through the same
modules as the original records they revise:

* ``well_plan_adjustment_sections`` / ``well_plan_adjustment_phases`` mirror
  the well configuration grid (hole sections with depths and phases with
  planned days).
* ``afe_sow_service_lines`` (with ``afe_sow_service_rates``,
  ``afe_sow_service_charges``, ``afe_sow_service_section_rates``),
  ``afe_sow_consumable_lines`` and ``afe_sow_tangible_lines`` mirror the AFE
  estimate line tables.

Every table stores both sides of the revision: ``plan_side`` is ``before`` for
the snapshot of the entered values being revised and ``after`` for the revised
entries, and ``pair_key`` links an after row to the before row it replaces.
``afe_sow_exchange_rates`` snapshots the conversion rates each side was priced
with so either side reprices exactly as entered.

Parent aggregate columns are unchanged and keep working as derived snapshots;
existing rows simply have no revision lines. Nothing is dropped or rewritten.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5c9e1a7b382"
down_revision: Union[str, None] = "c2f5d8a41b67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _side() -> list[sa.Column]:
    return [
        sa.Column("plan_side", sa.String(10), nullable=False),
        sa.Column("pair_key", sa.String(64), nullable=False),
    ]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # AFE SOW revision lines (mirroring the AFE estimate line tables)
    # ------------------------------------------------------------------
    op.create_table(
        "afe_sow_service_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("adjustment_id", sa.String(36), sa.ForeignKey("afe_sow_adjustments.id", ondelete="CASCADE"), nullable=False, index=True),
        *_side(),
        sa.Column("service_id", sa.String(36), sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("charging_basis", sa.String(30), nullable=False),
        sa.Column("hole_section_id", sa.String(36), sa.ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=True, index=True),
        sa.Column("phase_id", sa.String(36), sa.ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default=""),
        sa.Column("service_amount", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("remarks", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_service_side"),
        sa.CheckConstraint("charging_basis IN ('Day Rate', 'Per Service Rate', 'Per Section Rate')", name="ck_afe_sow_service_basis"),
        sa.CheckConstraint("service_amount >= 0", name="ck_afe_sow_service_amount"),
        sa.UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_afe_sow_service_pair"),
    )
    op.create_index("ix_afe_sow_service_adjustment", "afe_sow_service_lines", ["adjustment_id"])

    op.create_table(
        "afe_sow_service_rates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        *_side(),
        sa.Column("line_id", sa.String(36), sa.ForeignKey("afe_sow_service_lines.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("charge_category", sa.String(40), nullable=False),
        sa.Column("unit_rate", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_rates_side"),
        sa.CheckConstraint("unit_rate >= 0", name="ck_afe_sow_service_rates_rate"),
        sa.UniqueConstraint("line_id", "charge_category", name="uq_afe_sow_service_rates_category"),
    )

    op.create_table(
        "afe_sow_service_charges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        *_side(),
        sa.Column("line_id", sa.String(36), sa.ForeignKey("afe_sow_service_lines.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("charge_category", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("quantity_unit", sa.String(10), nullable=False, server_default="days"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_charges_side"),
        sa.CheckConstraint("quantity >= 0", name="ck_afe_sow_service_charges_qty"),
        sa.CheckConstraint("quantity_unit IN ('days', 'hours')", name="ck_afe_sow_service_charges_unit"),
    )

    op.create_table(
        "afe_sow_service_section_rates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        *_side(),
        sa.Column("line_id", sa.String(36), sa.ForeignKey("afe_sow_service_lines.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("hole_section_id", sa.String(36), sa.ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("phase_id", sa.String(36), sa.ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True),
        sa.Column("amount", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_section_rates_side"),
        sa.CheckConstraint("amount >= 0", name="ck_afe_sow_service_section_rates_amount"),
    )

    op.create_table(
        "afe_sow_consumable_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("adjustment_id", sa.String(36), sa.ForeignKey("afe_sow_adjustments.id", ondelete="CASCADE"), nullable=False, index=True),
        *_side(),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("hole_section_id", sa.String(36), sa.ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("phase_id", sa.String(36), sa.ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True),
        sa.Column("drill_bit_id", sa.String(36), sa.ForeignKey("drill_bits.id", ondelete="RESTRICT"), nullable=True, index=True),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False, server_default="1"),
        sa.Column("captured_rate", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("override_rate", sa.Numeric(28, 10), nullable=True),
        sa.Column("estimated_amount", sa.Numeric(28, 10), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default=""),
        sa.Column("remarks", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_consumable_side"),
        sa.CheckConstraint("quantity >= 0", name="ck_afe_sow_consumable_qty"),
        sa.CheckConstraint(
            "(category = 'Drill Bits' AND drill_bit_id IS NOT NULL AND estimated_amount IS NULL) OR "
            "(category <> 'Drill Bits' AND drill_bit_id IS NULL AND estimated_amount IS NOT NULL)",
            name="ck_afe_sow_consumable_kind",
        ),
        sa.UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_afe_sow_consumable_pair"),
    )
    op.create_index("ix_afe_sow_consumable_adjustment", "afe_sow_consumable_lines", ["adjustment_id"])

    op.create_table(
        "afe_sow_tangible_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("adjustment_id", sa.String(36), sa.ForeignKey("afe_sow_adjustments.id", ondelete="CASCADE"), nullable=False, index=True),
        *_side(),
        sa.Column("tangible_id", sa.String(36), sa.ForeignKey("tangibles.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False, server_default="1"),
        sa.Column("captured_rate", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("override_rate", sa.Numeric(28, 10), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default=""),
        sa.Column("uom", sa.String(50), nullable=False, server_default=""),
        sa.Column("remarks", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_tangible_side"),
        sa.CheckConstraint("quantity >= 0", name="ck_afe_sow_tangible_qty"),
        sa.UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_afe_sow_tangible_pair"),
    )
    op.create_index("ix_afe_sow_tangible_adjustment", "afe_sow_tangible_lines", ["adjustment_id"])

    op.create_table(
        "afe_sow_exchange_rates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("adjustment_id", sa.String(36), sa.ForeignKey("afe_sow_adjustments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("plan_side", sa.String(10), nullable=False),
        sa.Column("currency_code", sa.String(10), nullable=False),
        sa.Column("rate", sa.Numeric(28, 10), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_rates_side"),
        sa.CheckConstraint("rate > 0", name="ck_afe_sow_rates_rate"),
        sa.UniqueConstraint("adjustment_id", "plan_side", "currency_code", name="uq_afe_sow_rates_currency"),
    )
    op.create_index("ix_afe_sow_rates_adjustment", "afe_sow_exchange_rates", ["adjustment_id"])

    # ------------------------------------------------------------------
    # Well plan revision lines (mirroring the well configuration grid)
    # ------------------------------------------------------------------
    op.create_table(
        "well_plan_adjustment_sections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("adjustment_id", sa.String(36), sa.ForeignKey("well_plan_adjustments.id", ondelete="CASCADE"), nullable=False, index=True),
        *_side(),
        sa.Column("hole_section_id", sa.String(36), sa.ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("from_depth", sa.Numeric(28, 10), nullable=False),
        sa.Column("to_depth", sa.Numeric(28, 10), nullable=False),
        sa.Column("remarks", sa.String(1000), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_well_plan_adj_section_side"),
        sa.CheckConstraint("from_depth >= 0 AND to_depth >= 0", name="ck_well_plan_adj_section_depth"),
        sa.UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_well_plan_adj_section_pair"),
    )
    op.create_index("ix_well_plan_adj_section_adjustment", "well_plan_adjustment_sections", ["adjustment_id"])

    op.create_table(
        "well_plan_adjustment_phases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("adjustment_id", sa.String(36), sa.ForeignKey("well_plan_adjustments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("section_id", sa.String(36), sa.ForeignKey("well_plan_adjustment_sections.id", ondelete="CASCADE"), nullable=False, index=True),
        *_side(),
        sa.Column("phase_id", sa.String(36), sa.ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("days", sa.Numeric(28, 10), nullable=False),
        sa.Column("remarks", sa.String(1000), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint("plan_side IN ('before', 'after')", name="ck_well_plan_adj_phase_side"),
        sa.CheckConstraint("days >= 0", name="ck_well_plan_adj_phase_days"),
        sa.UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_well_plan_adj_phase_pair"),
    )
    op.create_index("ix_well_plan_adj_phase_adjustment", "well_plan_adjustment_phases", ["adjustment_id"])
    op.create_index("ix_well_plan_adj_phase_section", "well_plan_adjustment_phases", ["section_id"])


def downgrade() -> None:
    op.drop_table("well_plan_adjustment_phases")
    op.drop_table("well_plan_adjustment_sections")
    op.drop_table("afe_sow_exchange_rates")
    op.drop_table("afe_sow_tangible_lines")
    op.drop_table("afe_sow_consumable_lines")
    op.drop_table("afe_sow_service_section_rates")
    op.drop_table("afe_sow_service_charges")
    op.drop_table("afe_sow_service_rates")
    op.drop_table("afe_sow_service_lines")
