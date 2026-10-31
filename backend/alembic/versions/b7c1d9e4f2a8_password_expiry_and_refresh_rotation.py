"""Password expiry and refresh-token replay detection.

Two additions that make the account lifecycle auditable:

* ``users.password_expires_at`` records the instant the current password stops
  being accepted. Existing accounts get their expiry from ``password_changed_at``
  (or ``created_at`` when the change predates password-age tracking), so a dormant
  account cannot retain an old password forever.
* ``refresh_sessions.revoked_at`` / ``replaced_by_hash`` keep a rotated token as a
  tombstone. Presenting it again is treated as token theft and revokes every
  session for that account instead of being indistinguishable from an unknown
  token.

Revision ID: b7c1d9e4f2a8
Revises: f9a2c7d4e611
Create Date: 2026-10-31 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c1d9e4f2a8"
down_revision: Union[str, None] = "f9a2c7d4e611"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("users", sa.Column("password_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("refresh_sessions", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("refresh_sessions", sa.Column("replaced_by_hash", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_refresh_sessions_expires_at", "refresh_sessions", ["expires_at"], unique=False
    )
    # Deliberately no backfill statement: SQLite and PostgreSQL spell date
    # arithmetic differently, and the application derives an expiry from
    # password_changed_at/created_at when the column is NULL (see
    # app.core.security.effective_expiry). The next password change writes it.


def downgrade() -> None:
    op.drop_index("ix_refresh_sessions_expires_at", table_name="refresh_sessions")
    with op.batch_alter_table("refresh_sessions") as batch_op:
        batch_op.drop_column("replaced_by_hash")
        batch_op.drop_column("revoked_at")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("password_expires_at")
