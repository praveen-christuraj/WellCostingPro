"""vendors, po/so orders and their attached documents

Revision ID: b7f4c2d91e05
Revises: a4c86b91e712
Create Date: 2026-10-10 09:15:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "b7f4c2d91e05"
down_revision: Union[str, None] = "a4c86b91e712"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Document custody is grantable on its own: reading master data does not imply
# permission to attach, download or remove the scanned PO/SO copies.
DOCUMENT_CAPABILITIES = {
    "master-data:document-upload": "Attach documents to PO/SO orders",
    "master-data:document-download": "Download documents from PO/SO orders",
    "master-data:document-delete": "Remove documents from PO/SO orders",
}


def _backfill_capabilities() -> None:
    """Make the new capabilities assignable in existing workspaces as well."""
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
        "role_permissions",
        sa.column("role_id", sa.String(36)),
        sa.column("permission_id", sa.String(36)),
    )

    for (organization_id,) in bind.execute(sa.select(organizations.c.id)):
        owner_role_id = bind.execute(
            sa.select(roles.c.id).where(
                roles.c.organization_id == organization_id,
                roles.c.is_owner.is_(True),
            )
        ).scalar_one_or_none()
        for key, description in DOCUMENT_CAPABILITIES.items():
            permission_id = bind.execute(
                sa.select(permissions.c.id).where(
                    permissions.c.organization_id == organization_id,
                    permissions.c.key == key,
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
                assignment = bind.execute(
                    sa.select(role_permissions.c.role_id).where(
                        role_permissions.c.role_id == owner_role_id,
                        role_permissions.c.permission_id == permission_id,
                    )
                ).first()
                if assignment is None:
                    bind.execute(
                        role_permissions.insert().values(
                            role_id=owner_role_id,
                            permission_id=permission_id,
                        )
                    )


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vendor_code", sa.String(length=50), nullable=False),
        sa.Column("vendor_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=80), server_default="", nullable=False),
        sa.Column("contact_person", sa.String(length=150), server_default="", nullable=False),
        sa.Column("email", sa.String(length=255), server_default="", nullable=False),
        sa.Column("phone", sa.String(length=60), server_default="", nullable=False),
        sa.Column("website", sa.String(length=255), server_default="", nullable=False),
        sa.Column("country", sa.String(length=100), server_default="", nullable=False),
        sa.Column("tax_registration_no", sa.String(length=60), server_default="", nullable=False),
        sa.Column("address", sa.String(length=500), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("credit_terms_days", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "vendor_code", name="uq_vendors_org_code"),
    )
    op.create_index(op.f("ix_vendors_organization_id"), "vendors", ["organization_id"], unique=False)

    op.create_table(
        "po_so_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_number", sa.String(length=100), nullable=False),
        sa.Column("order_type", sa.String(length=20), server_default="PO", nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=False),
        sa.Column("parent_order_id", sa.String(length=36), nullable=True),
        sa.Column("revision_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("revision_note", sa.String(length=500), server_default="", nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_order_id"], ["po_so_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "order_number",
            "revision_number",
            name="uq_po_so_orders_org_number_revision",
        ),
    )
    op.create_index(op.f("ix_po_so_orders_organization_id"), "po_so_orders", ["organization_id"], unique=False)
    op.create_index(op.f("ix_po_so_orders_order_number"), "po_so_orders", ["order_number"], unique=False)
    op.create_index(op.f("ix_po_so_orders_order_type"), "po_so_orders", ["order_type"], unique=False)
    op.create_index(op.f("ix_po_so_orders_vendor_id"), "po_so_orders", ["vendor_id"], unique=False)
    op.create_index(op.f("ix_po_so_orders_parent_order_id"), "po_so_orders", ["parent_order_id"], unique=False)
    op.create_index(op.f("ix_po_so_orders_status"), "po_so_orders", ["status"], unique=False)

    op.create_table(
        "po_so_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=300), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=120),
            server_default="application/octet-stream",
            nullable=False,
        ),
        sa.Column("size_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), server_default="", nullable=False),
        sa.Column("document_kind", sa.String(length=30), server_default="po_copy", nullable=False),
        sa.Column("label", sa.String(length=200), server_default="", nullable=False),
        sa.Column("revision_number", sa.Integer(), server_default="0", nullable=False),
        # The file payload itself. The deployed API filesystem is ephemeral, so the
        # workspace database is the durable store; metadata stays column-wise.
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("uploaded_by_name", sa.String(length=160), server_default="", nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["po_so_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_po_so_documents_organization_id"), "po_so_documents", ["organization_id"], unique=False)
    op.create_index(op.f("ix_po_so_documents_order_id"), "po_so_documents", ["order_id"], unique=False)

    _backfill_capabilities()


def downgrade() -> None:
    bind = op.get_bind()
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String(36)),
        sa.column("key", sa.String(100)),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String(36)),
        sa.column("permission_id", sa.String(36)),
    )
    permission_ids = list(
        bind.execute(
            sa.select(permissions.c.id).where(
                permissions.c.key.in_(tuple(DOCUMENT_CAPABILITIES))
            )
        ).scalars()
    )
    if permission_ids:
        bind.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids)))
        bind.execute(permissions.delete().where(permissions.c.id.in_(permission_ids)))

    op.drop_index(op.f("ix_po_so_documents_order_id"), table_name="po_so_documents")
    op.drop_index(op.f("ix_po_so_documents_organization_id"), table_name="po_so_documents")
    op.drop_table("po_so_documents")
    op.drop_index(op.f("ix_po_so_orders_status"), table_name="po_so_orders")
    op.drop_index(op.f("ix_po_so_orders_parent_order_id"), table_name="po_so_orders")
    op.drop_index(op.f("ix_po_so_orders_vendor_id"), table_name="po_so_orders")
    op.drop_index(op.f("ix_po_so_orders_order_type"), table_name="po_so_orders")
    op.drop_index(op.f("ix_po_so_orders_order_number"), table_name="po_so_orders")
    op.drop_index(op.f("ix_po_so_orders_organization_id"), table_name="po_so_orders")
    op.drop_table("po_so_orders")
    op.drop_index(op.f("ix_vendors_organization_id"), table_name="vendors")
    op.drop_table("vendors")
