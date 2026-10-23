"""Scope well sub activities by drilling/completion and allow per-scope well deletion.

Existing well sub activities default to the drilling scope for backward
compatibility, and existing soft-deleted wells mirror their deleted state onto
both scopes.
"""

from alembic import op
import sqlalchemy as sa

revision = "a3e8b5c91f42"
down_revision = "07b3f251510d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wells") as batch:
        batch.add_column(
            sa.Column(
                "drilling_is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "drilling_deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "drilling_purged",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "completion_is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "completion_deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "completion_purged",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    with op.batch_alter_table("well_sub_activities") as batch:
        batch.add_column(
            sa.Column(
                "scope",
                sa.String(20),
                nullable=False,
                server_default="drilling",
            )
        )
        batch.drop_constraint("uq_well_sub_activities_org_well_code", type_="unique")
        batch.create_unique_constraint(
            "uq_well_sub_activities_org_well_code",
            ["organization_id", "well_id", "scope", "sub_activity_code"],
        )
        batch.create_check_constraint(
            "ck_well_sub_activities_scope",
            "scope IN ('drilling', 'completion')",
        )
        batch.create_index(
            "ix_well_sub_activities_well_scope",
            ["organization_id", "well_id", "scope"],
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM well_sub_activities "
            "WHERE scope = 'completion' AND EXISTS ("
            "  SELECT 1 FROM well_sub_activities d "
            "  WHERE d.organization_id = well_sub_activities.organization_id "
            "    AND d.well_id = well_sub_activities.well_id "
            "    AND d.scope = 'drilling' "
            "    AND d.sub_activity_code = well_sub_activities.sub_activity_code"
            ")"
        )
    )
    with op.batch_alter_table("well_sub_activities") as batch:
        batch.drop_index("ix_well_sub_activities_well_scope")
        batch.drop_constraint("ck_well_sub_activities_scope", type_="check")
        batch.drop_constraint("uq_well_sub_activities_org_well_code", type_="unique")
        batch.create_unique_constraint(
            "uq_well_sub_activities_org_well_code",
            ["organization_id", "well_id", "sub_activity_code"],
        )
        batch.drop_column("scope")

    with op.batch_alter_table("wells") as batch:
        batch.drop_column("completion_purged")
        batch.drop_column("completion_deleted_at")
        batch.drop_column("completion_is_deleted")
        batch.drop_column("drilling_purged")
        batch.drop_column("drilling_deleted_at")
        batch.drop_column("drilling_is_deleted")
