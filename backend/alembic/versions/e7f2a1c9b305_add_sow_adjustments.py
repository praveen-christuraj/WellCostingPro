"""Add AFE SOW adjustments, well plan adjustments and daily-cost amendments.

Revision ID: e7f2a1c9b305
Revises: d2f8a6c9b104
Create Date: 2026-10-19 09:00:00.000000

New tables record scope-of-work revisions separately from the approved AFE
estimates and configured well plans they revise: only the latest *approved*
revision per AFE (or per well and scope) affects cost comparisons. Existing
workspaces also receive the four new permission records, granted to their
owner role; other roles stay unchanged until an administrator assigns them.
"""

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision: str = "e7f2a1c9b305"
down_revision: Union[str, None] = "d2f8a6c9b104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOW_CAPABILITIES = {
    "afe:sow-adjust": "Record SOW adjustments against approved AFE estimates",
    "afe:sow-approve": "Approve or void AFE SOW adjustments",
    "rig-well:plan-adjust": "Record and approve well plan (planned days) adjustments",
    "daily-cost:amend": "Reopen submitted daily cost sheets older than 30 days",
}


def _tables() -> None:
    op.create_table(
        "afe_sow_adjustments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("afe_id", sa.String(36), sa.ForeignKey("afes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("well_id", sa.String(36), sa.ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rig_id", sa.String(36), sa.ForeignKey("rigs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("configuration_scope", sa.String(20), nullable=False, server_default="drilling"),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("sow_summary", sa.Text, nullable=False, server_default=""),
        sa.Column("standard_currency", sa.String(10), nullable=False),
        sa.Column("original_services_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("original_consumables_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("original_tangibles_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("original_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("adjusted_services_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("adjusted_consumables_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("adjusted_tangibles_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("adjusted_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(160), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(160), nullable=False, server_default=""),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_remarks", sa.String(1000), nullable=False, server_default=""),
        sa.CheckConstraint("configuration_scope IN ('drilling', 'completion')", name="ck_afe_sow_adj_scope"),
        sa.CheckConstraint("status IN ('draft', 'approved', 'void')", name="ck_afe_sow_adj_status"),
        sa.UniqueConstraint("organization_id", "afe_id", "revision_number", name="uq_afe_sow_adj_revision"),
    )
    op.create_table(
        "well_plan_adjustments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("well_id", sa.String(36), sa.ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rig_id", sa.String(36), sa.ForeignKey("rigs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("configuration_scope", sa.String(20), nullable=False, server_default="drilling"),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("planned_days_before", sa.Numeric(12, 2), nullable=False),
        sa.Column("planned_days_after", sa.Numeric(12, 2), nullable=False),
        sa.Column("sections_before", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sections_after", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(160), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(160), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(160), nullable=False, server_default=""),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_remarks", sa.String(1000), nullable=False, server_default=""),
        sa.CheckConstraint("configuration_scope IN ('drilling', 'completion')", name="ck_well_plan_adj_scope"),
        sa.CheckConstraint("status IN ('draft', 'approved', 'void')", name="ck_well_plan_adj_status"),
        sa.UniqueConstraint("organization_id", "well_id", "configuration_scope", "revision_number", name="uq_well_plan_adj_revision"),
    )
    op.create_table(
        "daily_cost_amendments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("entry_id", sa.String(36), sa.ForeignKey("daily_cost_entries.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("well_id", sa.String(36), sa.ForeignKey("wells.id", ondelete="CASCADE"), nullable=False),
        sa.Column("afe_id", sa.String(36), sa.ForeignKey("afes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amendment_number", sa.Integer, nullable=False),
        sa.Column("cost_date", sa.Date, nullable=False),
        sa.Column("days_after_cost_date", sa.Integer, nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("reopened_by", sa.String(160), nullable=False, server_default=""),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "entry_id", "amendment_number", name="uq_daily_cost_amendment_no"),
    )


def _capabilities() -> None:
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
        "roles",
        sa.column("id", sa.String(36)),
        sa.column("organization_id", sa.String(36)),
        sa.column("is_owner", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("role_id", sa.String(36)), sa.column("permission_id", sa.String(36))
    )

    for (organization_id,) in bind.execute(sa.select(organizations.c.id)):
        owner_role_id = bind.execute(
            sa.select(roles.c.id).where(roles.c.organization_id == organization_id, roles.c.is_owner.is_(True))
        ).scalar_one_or_none()
        for key, description in SOW_CAPABILITIES.items():
            permission_id = bind.execute(
                sa.select(permissions.c.id).where(
                    permissions.c.organization_id == organization_id, permissions.c.key == key
                )
            ).scalar_one_or_none()
            if permission_id is None:
                permission_id = str(uuid4())
                bind.execute(
                    permissions.insert().values(
                        id=permission_id,
                        organization_id=organization_id,
                        key=key,
                        description=description,
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
                    bind.execute(role_permissions.insert().values(role_id=owner_role_id, permission_id=permission_id))


def upgrade() -> None:
    _tables()
    _capabilities()


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE key IN "
            "('afe:sow-adjust', 'afe:sow-approve', 'rig-well:plan-adjust', 'daily-cost:amend'))"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM permissions WHERE key IN "
            "('afe:sow-adjust', 'afe:sow-approve', 'rig-well:plan-adjust', 'daily-cost:amend')"
        )
    )
    op.drop_table("daily_cost_amendments")
    op.drop_table("well_plan_adjustments")
    op.drop_table("afe_sow_adjustments")
