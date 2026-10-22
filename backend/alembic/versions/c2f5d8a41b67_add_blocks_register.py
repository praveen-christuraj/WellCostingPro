"""Add the tenant-scoped Blocks register and bind wells to a block.

Revision ID: c2f5d8a41b67
Revises: c5e9a1d47b82
Create Date: 2026-10-22

A block (concession / field area) is a workspace record with a unique code, a
name and a description, maintained under Rig & Well Management → Blocks. Every
well now belongs to exactly one block instead of carrying free text, so wells
can be segregated by block. Existing free-text values are converted into block
records before the text column is removed; no well loses its block.
"""
import re
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "c2f5d8a41b67"
down_revision: Union[str, None] = "c5e9a1d47b82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UNASSIGNED_CODE = "UNASSIGNED"
UNASSIGNED_NAME = "Unassigned"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _block_code(label: str, used: set[str]) -> str:
    """Deterministic, workspace-unique code derived from the legacy free text."""
    code = re.sub(r"[^A-Z0-9]+", "-", (label or "").upper()).strip("-")[:50] or UNASSIGNED_CODE
    if code not in used:
        return code
    for index in range(2, 1000):
        suffix = f"-{index}"
        candidate = f"{code[: 50 - len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
    return f"{code[:40]}-{uuid4().hex[:6].upper()}"


def _backfill_blocks() -> None:
    """Turn every distinct wells.block value into a block and re-point the wells."""
    bind = op.get_bind()
    wells = sa.table(
        "wells",
        sa.column("id", sa.String(36)),
        sa.column("organization_id", sa.String(36)),
        sa.column("block", sa.String(200)),
        sa.column("block_id", sa.String(36)),
    )
    blocks = sa.table(
        "blocks",
        sa.column("id", sa.String(36)),
        sa.column("organization_id", sa.String(36)),
        sa.column("block_code", sa.String(50)),
        sa.column("block_name", sa.String(200)),
        sa.column("description", sa.String(1000)),
        sa.column("is_deleted", sa.Boolean()),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    rows = bind.execute(
        sa.select(wells.c.id, wells.c.organization_id, wells.c.block)
        .order_by(wells.c.organization_id, wells.c.block, wells.c.id)
    ).all()

    used_codes: dict[str, set[str]] = {}
    created: dict[tuple[str, str], str] = {}
    timestamp = _now()
    for well_id, organization_id, raw_label in rows:
        label = (raw_label or "").strip()
        key = (organization_id, label.casefold())
        block_id = created.get(key)
        if block_id is None:
            used = used_codes.setdefault(organization_id, set())
            name = label[:200] or UNASSIGNED_NAME
            code = _block_code(label if label else UNASSIGNED_NAME, used)
            used.add(code)
            block_id = str(uuid4())
            bind.execute(
                blocks.insert().values(
                    id=block_id,
                    organization_id=organization_id,
                    block_code=code,
                    block_name=name,
                    description=(
                        f"Created from existing well block '{label}'" if label
                        else "Created for wells that had no block recorded"
                    )[:1000],
                    is_deleted=False,
                    deleted_at=None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            created[key] = block_id
        bind.execute(
            wells.update().where(wells.c.id == well_id).values(block_id=block_id)
        )


def upgrade() -> None:
    op.create_table(
        "blocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("block_code", sa.String(length=50), nullable=False),
        sa.Column("block_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), server_default="", nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "block_code", name="uq_blocks_org_code"),
    )
    op.create_index("ix_blocks_organization_id", "blocks", ["organization_id"])
    op.create_index("ix_blocks_org_deleted", "blocks", ["organization_id", "is_deleted"])

    # Add the nullable key first so existing rows survive the backfill.
    with op.batch_alter_table("wells") as batch_op:
        batch_op.add_column(sa.Column("block_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_wells_block_id_blocks", "blocks", ["block_id"], ["id"], ondelete="RESTRICT"
        )

    _backfill_blocks()

    with op.batch_alter_table("wells") as batch_op:
        batch_op.alter_column("block_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.drop_column("block")

    op.create_index("ix_wells_block_id", "wells", ["block_id"])
    op.create_index("ix_wells_org_block", "wells", ["organization_id", "block_id"])


def downgrade() -> None:
    op.add_column("wells", sa.Column("block", sa.String(length=200), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE wells SET block = COALESCE("
            "(SELECT blocks.block_name FROM blocks WHERE blocks.id = wells.block_id), '')"
        )
    )
    bind.execute(sa.text("UPDATE wells SET block = 'Unassigned' WHERE block IS NULL OR block = ''"))

    op.drop_index("ix_wells_org_block", table_name="wells")
    op.drop_index("ix_wells_block_id", table_name="wells")
    with op.batch_alter_table("wells") as batch_op:
        batch_op.alter_column("block", existing_type=sa.String(length=200), nullable=False)
        batch_op.drop_constraint("fk_wells_block_id_blocks", type_="foreignkey")
        batch_op.drop_column("block_id")

    op.drop_index("ix_blocks_org_deleted", table_name="blocks")
    op.drop_index("ix_blocks_organization_id", table_name="blocks")
    op.drop_table("blocks")
