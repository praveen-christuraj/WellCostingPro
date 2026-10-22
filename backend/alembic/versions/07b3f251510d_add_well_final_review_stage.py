"""Add a Marked for final review stage to each well configuration scope.

A scope now moves draft -> configured -> marked for final review -> completed,
with drilling and completion tracked independently through their own
config_status / completion_config_status columns. Existing draft and configured
values are untouched.
"""

from alembic import op
import sqlalchemy as sa

revision = "07b3f251510d"
down_revision = "d5c9e1a7b382"
branch_labels = None
depends_on = None

NEW_CONFIG_STATUSES = "('draft', 'configured', 'final_review')"
OLD_CONFIG_STATUSES = "('draft', 'configured')"


def upgrade() -> None:
    with op.batch_alter_table("wells") as batch:
        batch.drop_constraint("ck_wells_config_status", type_="check")
        batch.create_check_constraint(
            "ck_wells_config_status", f"config_status IN {NEW_CONFIG_STATUSES}"
        )
        batch.drop_constraint("ck_wells_completion_config_status", type_="check")
        batch.create_check_constraint(
            "ck_wells_completion_config_status",
            f"completion_config_status IN {NEW_CONFIG_STATUSES}",
        )


def downgrade() -> None:
    # Normalise any scope left in final review back to configured so the
    # narrower check constraint can be restored.
    op.execute("UPDATE wells SET config_status = 'configured' WHERE config_status = 'final_review'")
    op.execute(
        "UPDATE wells SET completion_config_status = 'configured' "
        "WHERE completion_config_status = 'final_review'"
    )
    with op.batch_alter_table("wells") as batch:
        batch.drop_constraint("ck_wells_config_status", type_="check")
        batch.create_check_constraint(
            "ck_wells_config_status", f"config_status IN {OLD_CONFIG_STATUSES}"
        )
        batch.drop_constraint("ck_wells_completion_config_status", type_="check")
        batch.create_check_constraint(
            "ck_wells_completion_config_status",
            f"completion_config_status IN {OLD_CONFIG_STATUSES}",
        )
