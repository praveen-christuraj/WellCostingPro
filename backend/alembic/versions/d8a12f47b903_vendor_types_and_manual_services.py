"""Add vendor types and allow vendor links for in-house services.

Existing unassigned in-house services are preserved for explicit user assignment.
"""
from alembic import op
import sqlalchemy as sa

revision = "d8a12f47b903"
down_revision = "c6e2a9b41f70"
branch_labels = None
depends_on = None


def _provider_constraint(expression):
    # SQLite reflection cannot retain expression indexes during a batch rebuild.
    op.drop_index("uq_services_org_name_ci", table_name="services")
    with op.batch_alter_table("services") as batch:
        batch.drop_constraint("ck_services_provider_vendor", type_="check")
        batch.create_check_constraint("ck_services_provider_vendor", expression)
    op.create_index("uq_services_org_name_ci", "services", ["organization_id", sa.text("lower(service_name)")], unique=True)


def upgrade():
    with op.batch_alter_table("vendors") as batch:
        batch.add_column(sa.Column("vendor_type", sa.String(20), nullable=False, server_default="Third party"))
        batch.create_check_constraint("ck_vendors_type", "vendor_type IN ('Inhouse', 'Third party')")
    _provider_constraint("(provider_type = 'Third Party Services' AND vendor_id IS NOT NULL) OR provider_type = 'In House Services'")


def downgrade():
    # Refuse to silently discard vendor accounting links that the old schema forbids.
    linked = op.get_bind().execute(sa.text("SELECT count(*) FROM services WHERE provider_type = 'In House Services' AND vendor_id IS NOT NULL")).scalar()
    if linked:
        raise RuntimeError("Cannot downgrade while in-house services have vendor assignments")
    _provider_constraint("(provider_type = 'Third Party Services' AND vendor_id IS NOT NULL) OR (provider_type = 'In House Services' AND vendor_id IS NULL)")
    with op.batch_alter_table("vendors") as batch:
        batch.drop_constraint("ck_vendors_type", type_="check")
        batch.drop_column("vendor_type")
