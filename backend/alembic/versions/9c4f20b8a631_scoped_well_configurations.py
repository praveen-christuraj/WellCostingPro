"""Separate Drilling and Completion well plans and AFE configuration selection.

Existing well fields, sections and AFEs remain Drilling baselines, including
historical Completion-type AFEs that previously priced against Drilling plans.
"""
from alembic import op
import sqlalchemy as sa

revision = "9c4f20b8a631"
down_revision = "e2664cd07e88"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("wells") as batch:
        batch.add_column(sa.Column("completion_status", sa.String(20), nullable=False, server_default="active"))
        batch.add_column(sa.Column("completion_config_status", sa.String(20), nullable=False, server_default="draft"))
        batch.add_column(sa.Column("completion_depth_unit", sa.String(10), nullable=False, server_default="m"))
        batch.create_check_constraint("ck_wells_completion_status", "completion_status IN ('active', 'completed')")
        batch.create_check_constraint("ck_wells_completion_config_status", "completion_config_status IN ('draft', 'configured')")
        batch.create_check_constraint("ck_wells_completion_depth_unit", "completion_depth_unit IN ('m', 'ft')")
    with op.batch_alter_table("well_sections") as batch:
        batch.add_column(sa.Column("scope", sa.String(20), nullable=False, server_default="drilling"))
        batch.drop_constraint("uq_well_sections_order", type_="unique")
        batch.create_unique_constraint("uq_well_sections_order", ["well_id", "scope", "sort_order"])
        batch.create_check_constraint("ck_well_sections_scope", "scope IN ('drilling', 'completion')")
    with op.batch_alter_table("afes") as batch:
        batch.add_column(sa.Column("configuration_scope", sa.String(20), nullable=False, server_default="drilling"))
        batch.create_check_constraint("ck_afes_configuration_scope", "configuration_scope IN ('drilling', 'completion')")


def downgrade():
    # Completion plans have no representation in the preceding schema.
    op.execute("DELETE FROM well_phases WHERE section_id IN (SELECT id FROM well_sections WHERE scope = 'completion')")
    op.execute("DELETE FROM well_sections WHERE scope = 'completion'")
    with op.batch_alter_table("afes") as batch:
        batch.drop_constraint("ck_afes_configuration_scope", type_="check")
        batch.drop_column("configuration_scope")
    with op.batch_alter_table("well_sections") as batch:
        batch.drop_constraint("ck_well_sections_scope", type_="check")
        batch.drop_constraint("uq_well_sections_order", type_="unique")
        batch.create_unique_constraint("uq_well_sections_order", ["well_id", "sort_order"])
        batch.drop_column("scope")
    with op.batch_alter_table("wells") as batch:
        for name in ("completion_status", "completion_config_status", "completion_depth_unit"):
            batch.drop_constraint(f"ck_wells_{name}", type_="check")
            batch.drop_column(name)
