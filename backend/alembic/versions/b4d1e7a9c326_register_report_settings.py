"""Save the printed report settings inside the daily cost register.

Two daily-report inputs used to be typed again on every print. They now live
with the records that own them:

* ``daily_cost_entries.lead_lag_kind`` / ``lead_lag_days`` — the report lead or
  lag, entered once with that day's sheet.
* ``wells.drilling_milestone_label`` / ``wells.completion_milestone_label`` —
  the wording the printed report uses for the spud milestone, saved once per
  well scope. Empty means the default "Spud date & time" wording.

Both are additive: existing rows default to an empty kind and an empty label,
so behaviour and the actual-days logic are unchanged.

Revision ID: b4d1e7a9c326
Revises: a3e8b5c91f42
Create Date: 2026-10-23 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b4d1e7a9c326"
down_revision: Union[str, None] = "a3e8b5c91f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("daily_cost_entries") as batch:
        batch.add_column(
            sa.Column("lead_lag_kind", sa.String(10), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("lead_lag_days", sa.Numeric(28, 10), nullable=True))
        batch.create_check_constraint(
            "ck_daily_cost_entries_lead_lag_kind",
            "lead_lag_kind IN ('', 'LEAD', 'LAG')",
        )
        batch.create_check_constraint(
            "ck_daily_cost_entries_lead_lag_days",
            "lead_lag_days IS NULL OR lead_lag_days >= 0",
        )

    with op.batch_alter_table("wells") as batch:
        for scope in ("drilling", "completion"):
            batch.add_column(
                sa.Column(
                    f"{scope}_milestone_label",
                    sa.String(80),
                    nullable=False,
                    server_default="",
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("wells") as batch:
        for scope in ("completion", "drilling"):
            batch.drop_column(f"{scope}_milestone_label")

    with op.batch_alter_table("daily_cost_entries") as batch:
        batch.drop_constraint("ck_daily_cost_entries_lead_lag_days", type_="check")
        batch.drop_constraint("ck_daily_cost_entries_lead_lag_kind", type_="check")
        batch.drop_column("lead_lag_days")
        batch.drop_column("lead_lag_kind")
