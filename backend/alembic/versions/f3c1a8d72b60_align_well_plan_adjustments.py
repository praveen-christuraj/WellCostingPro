"""Align well_plan_adjustments with the ORM.

Revision ID: f3c1a8d72b60
Revises: 6b8e4f1a2c90
Create Date: 2026-10-20 09:20:00.000000

Migration ``e7f2a1c9b305`` created ``well_plan_adjustments`` with
``sections_before``/``sections_after`` and no ``sow_summary``, while the
SQLAlchemy model (and therefore every API write) uses ``sow_summary``,
``section_count_before`` and ``section_count_after``, and made the unused
``rig_id``/``updated_by`` columns NOT NULL even though the API never writes
them. On a migrated database that made recording or approving a well plan
adjustment fail with a driver error, so this migration brings the table back
in line with the model and copies the existing section counts across. The two
unused columns become nullable rather than being dropped, so any rig
reference already stored stays available for reporting. No business values
change.

SQLite cannot ALTER/DROP columns in place, so both operations run through
Alembic's batch mode (a table copy) there; PostgreSQL uses ordinary ALTERs.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f3c1a8d72b60"
down_revision: Union[str, None] = "6b8e4f1a2c90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("well_plan_adjustments") as batch:
        batch.add_column(sa.Column("sow_summary", sa.String(2000), nullable=False, server_default=""))
        batch.add_column(sa.Column("section_count_before", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("section_count_after", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        "UPDATE well_plan_adjustments "
        "SET section_count_before = sections_before, section_count_after = sections_after"
    )
    with op.batch_alter_table("well_plan_adjustments") as batch:
        batch.alter_column("rig_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column("updated_by", existing_type=sa.String(255), nullable=True, server_default="")
        batch.drop_column("sections_before")
        batch.drop_column("sections_after")


def downgrade() -> None:
    with op.batch_alter_table("well_plan_adjustments") as batch:
        batch.add_column(sa.Column("sections_before", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("sections_after", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        "UPDATE well_plan_adjustments "
        "SET sections_before = section_count_before, sections_after = section_count_after"
    )
    with op.batch_alter_table("well_plan_adjustments") as batch:
        batch.drop_column("sow_summary")
        batch.drop_column("section_count_before")
        batch.drop_column("section_count_after")
