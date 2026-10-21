"""Add the six reporting service groups to Master Data and Daily Cost snapshots.

Existing services are deliberately classified as Miscellaneous Services until an
administrator assigns the right group; no record is guessed from its name. The
group is snapshotted on locked Daily Cost AFE budget lines and backfilled from
the service currently linked to each AFE line, so historical reports keep a
stable order without re-reading live Master Data.
"""

from alembic import op
import sqlalchemy as sa


revision = "b4d8e2c91a70"
down_revision = "a7b3c9d21e60"
branch_labels = None
depends_on = None

SERVICE_GROUPS = (
    "Rig Operations",
    "Formation Evaluation",
    "Well Services",
    "Land Facilities and Preparation",
    "Miscellaneous Services",
    "Supervisions",
)
DEFAULT_SERVICE_GROUP = "Miscellaneous Services"
SERVICES_NAME_INDEX = "uq_services_org_name_ci"


def _group_in_list(column: str = "service_group", allow_empty: bool = False) -> str:
    values = [f"'{group}'" for group in SERVICE_GROUPS]
    if allow_empty:
        values.insert(0, "''")
    return f"{column} IN (" + ", ".join(values) + ")"


def upgrade() -> None:
    # SQLite's batch rebuild cannot retain the case-insensitive expression index,
    # so it is dropped around the rebuild and recreated immediately afterwards.
    op.drop_index(SERVICES_NAME_INDEX, table_name="services")
    with op.batch_alter_table("services") as batch:
        batch.add_column(sa.Column("service_group", sa.String(60), nullable=False, server_default=DEFAULT_SERVICE_GROUP))
        batch.create_check_constraint("ck_services_group", _group_in_list())
    op.create_index(
        SERVICES_NAME_INDEX, "services", ["organization_id", sa.text("lower(service_name)")], unique=True
    )

    with op.batch_alter_table("daily_cost_baseline_budget_lines") as batch:
        batch.add_column(sa.Column("service_group", sa.String(60), nullable=False, server_default=""))
        batch.create_check_constraint("ck_daily_cost_budget_service_group", _group_in_list(allow_empty=True))

    with op.batch_alter_table("daily_cost_service_lines") as batch:
        batch.add_column(sa.Column("service_group_snapshot", sa.String(60), nullable=False, server_default=""))
        batch.create_check_constraint(
            "ck_daily_cost_service_group", _group_in_list("service_group_snapshot", allow_empty=True)
        )

    op.execute(
        sa.text(
            """
            UPDATE daily_cost_baseline_budget_lines
            SET service_group = COALESCE((
                SELECT services.service_group
                FROM afe_service_lines
                JOIN services ON services.id = afe_service_lines.service_id
                WHERE afe_service_lines.id = daily_cost_baseline_budget_lines.source_afe_line_id
            ), :fallback)
            WHERE cost_group = 'Services'
            """
        ).bindparams(fallback=DEFAULT_SERVICE_GROUP)
    )
    op.execute(
        sa.text(
            """
            UPDATE daily_cost_service_lines
            SET service_group_snapshot = COALESCE((
                SELECT services.service_group FROM services
                WHERE services.id = daily_cost_service_lines.service_id
            ), :fallback)
            """
        ).bindparams(fallback=DEFAULT_SERVICE_GROUP)
    )


def downgrade() -> None:
    with op.batch_alter_table("daily_cost_service_lines") as batch:
        batch.drop_constraint("ck_daily_cost_service_group", type_="check")
        batch.drop_column("service_group_snapshot")

    with op.batch_alter_table("daily_cost_baseline_budget_lines") as batch:
        batch.drop_constraint("ck_daily_cost_budget_service_group", type_="check")
        batch.drop_column("service_group")

    op.drop_index(SERVICES_NAME_INDEX, table_name="services")
    with op.batch_alter_table("services") as batch:
        batch.drop_constraint("ck_services_group", type_="check")
        batch.drop_column("service_group")
    op.create_index(
        SERVICES_NAME_INDEX, "services", ["organization_id", sa.text("lower(service_name)")], unique=True
    )
