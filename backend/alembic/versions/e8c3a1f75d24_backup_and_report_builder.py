"""Backup & Recovery and Report Builder.

Adds the two modules' typed tables and seeds their capabilities for every
existing workspace. Owner roles receive the new capabilities; other roles stay
unchanged until an administrator grants them.

Revision ID: e8c3a1f75d24
Revises: d1f4b8c27e93
Create Date: 2026-10-30 12:00:00.000000
"""

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "e8c3a1f75d24"
down_revision: Union[str, None] = "d1f4b8c27e93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_CAPABILITIES = {
    # Backup & Recovery: taking, downloading, deleting and restoring are separate hands.
    "backup:read": "View backups, restore requests and readiness",
    "backup:create": "Take a backup, verify its checksum and import an archive",
    "backup:download": "Download a backup archive",
    "backup:delete": "Delete an archive or apply retention",
    "backup:settings": "Change the backup schedule, retention and destination",
    "backup:restore-request": "Raise or cancel a restore request",
    "backup:restore-approve": "Approve/reject a restore request and validate its archive",
    "backup:restore-execute": "Apply a validated restore to the workspace",
    # Report Builder (design) and Custom Reports (run what was published).
    "report-builder:read": "View report designs shared with you",
    "report-builder:create": "Design, preview and copy reports",
    "report-builder:update": "Redesign reports you own or were given edit access to",
    "report-builder:delete": "Delete reports you created",
    "report-builder:publish": "Publish or withdraw a report from the Reporting menu",
    "custom-reports:read": "Run published custom reports shared with you",
    "custom-reports:export": "Export the full result of a custom report",
}


def _seed_capabilities() -> None:
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
    roles = sa.table("roles", sa.column("id", sa.String(36)), sa.column("organization_id", sa.String(36)), sa.column("is_owner", sa.Boolean()))
    role_permissions = sa.table("role_permissions", sa.column("role_id", sa.String(36)), sa.column("permission_id", sa.String(36)))

    for (organization_id,) in bind.execute(sa.select(organizations.c.id)):
        owner_role_id = bind.execute(
            sa.select(roles.c.id).where(roles.c.organization_id == organization_id, roles.c.is_owner.is_(True))
        ).scalar_one_or_none()
        for key, description in NEW_CAPABILITIES.items():
            permission_id = bind.execute(
                sa.select(permissions.c.id).where(permissions.c.organization_id == organization_id, permissions.c.key == key)
            ).scalar_one_or_none()
            if permission_id is None:
                permission_id = str(uuid4())
                bind.execute(permissions.insert().values(
                    id=permission_id,
                    organization_id=organization_id,
                    key=key,
                    description=description,
                    created_at=datetime.now(timezone.utc),
                ))
            if owner_role_id:
                assigned = bind.execute(
                    sa.select(role_permissions.c.role_id).where(
                        role_permissions.c.role_id == owner_role_id,
                        role_permissions.c.permission_id == permission_id,
                    )
                ).first()
                if assigned is None:
                    bind.execute(role_permissions.insert().values(role_id=owner_role_id, permission_id=permission_id))


def upgrade() -> None:
    op.create_table('backup_jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('backup_number', sa.String(length=40), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('trigger_source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('description', sa.String(length=500), server_default='', nullable=False),
    sa.Column('file_name', sa.String(length=255), server_default='', nullable=False),
    sa.Column('file_path', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('file_size_bytes', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('checksum_sha256', sa.String(length=64), server_default='', nullable=False),
    sa.Column('format_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('compression', sa.String(length=20), server_default='gzip', nullable=False),
    sa.Column('app_version', sa.String(length=40), server_default='', nullable=False),
    sa.Column('schema_revision', sa.String(length=40), server_default='', nullable=False),
    sa.Column('organization_slug', sa.String(length=80), server_default='', nullable=False),
    sa.Column('table_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('row_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('audit_row_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('requested_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('requested_by_display', sa.String(length=160), server_default='', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('checksum_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('checksum_verified_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('error_message', sa.String(length=2000), server_default='', nullable=False),
    sa.Column('retention_hold', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("scope IN ('workspace', 'full')", name='ck_backup_jobs_scope'),
    sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'checksum_mismatch')", name='ck_backup_jobs_status'),
    sa.CheckConstraint("trigger_source IN ('manual', 'scheduled', 'pre-restore', 'import')", name='ck_backup_jobs_trigger'),
    sa.ForeignKeyConstraint(['checksum_verified_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'backup_number', name='uq_backup_jobs_org_number')
    )
    op.create_table('backup_settings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('schedule_mode', sa.String(length=20), server_default='daily', nullable=False),
    sa.Column('interval_value', sa.Integer(), server_default='1', nullable=False),
    sa.Column('run_time', sa.String(length=5), server_default='02:00', nullable=False),
    sa.Column('retention_days', sa.Integer(), server_default='30', nullable=False),
    sa.Column('keep_minimum', sa.Integer(), server_default='5', nullable=False),
    sa.Column('backup_directory', sa.String(length=120), server_default='', nullable=False),
    sa.Column('scope', sa.String(length=20), server_default='workspace', nullable=False),
    sa.Column('compression_enabled', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("schedule_mode IN ('minutes', 'hours', 'daily', 'weekly')", name='ck_backup_settings_mode'),
    sa.CheckConstraint("scope IN ('workspace', 'full')", name='ck_backup_settings_scope'),
    sa.CheckConstraint('interval_value >= 1', name='ck_backup_settings_interval'),
    sa.CheckConstraint('keep_minimum >= 1 AND keep_minimum <= 100', name='ck_backup_settings_keep'),
    sa.CheckConstraint('retention_days >= 1 AND retention_days <= 3650', name='ck_backup_settings_retention'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', name='uq_backup_settings_organization')
    )
    op.create_table('report_definitions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('report_type', sa.String(length=20), nullable=False),
    sa.Column('source_table', sa.String(length=120), nullable=False),
    sa.Column('date_basis', sa.String(length=20), nullable=False),
    sa.Column('date_column', sa.String(length=120), server_default='', nullable=False),
    sa.Column('filter_logic', sa.String(length=5), server_default='AND', nullable=False),
    sa.Column('show_totals', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('page_size', sa.Integer(), server_default='50', nullable=False),
    sa.Column('empty_text', sa.String(length=200), server_default='', nullable=False),
    sa.Column('matrix_value_key', sa.String(length=80), server_default='', nullable=False),
    sa.Column('matrix_aggregate', sa.String(length=20), server_default='SUM', nullable=False),
    sa.Column('matrix_show_totals', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('visibility', sa.String(length=20), server_default='private', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('run_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('created_by_display', sa.String(length=160), server_default='', nullable=False),
    sa.Column('updated_by_display', sa.String(length=160), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("date_basis IN ('COLUMN', 'CREATED_AT', 'UPDATED_AT', 'NONE')", name='ck_report_definitions_date_basis'),
    sa.CheckConstraint("report_type IN ('TABULAR', 'MATRIX')", name='ck_report_definitions_type'),
    sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name='ck_report_definitions_status'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_report_definitions_org_name')
    )
    op.create_table('backup_job_tables',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('table_name', sa.String(length=120), nullable=False),
    sa.Column('module_group', sa.String(length=80), server_default='', nullable=False),
    sa.Column('row_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('column_count', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['backup_jobs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'table_name', name='uq_backup_job_tables_job_table')
    )
    op.create_table('backup_restore_requests',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('request_number', sa.String(length=40), nullable=False),
    sa.Column('backup_job_id', sa.String(length=36), nullable=True),
    sa.Column('backup_number', sa.String(length=40), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('reason', sa.String(length=1000), nullable=False),
    sa.Column('business_impact', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('requested_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('requested_by_display', sa.String(length=160), server_default='', nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reviewed_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('reviewed_by_display', sa.String(length=160), server_default='', nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_remarks', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('executed_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('executed_by_display', sa.String(length=160), server_default='', nullable=False),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('execution_remarks', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('pre_restore_backup_number', sa.String(length=40), server_default='', nullable=False),
    sa.Column('tables_restored', sa.Integer(), server_default='0', nullable=False),
    sa.Column('rows_restored', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error_message', sa.String(length=2000), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending_approval', 'approved', 'rejected', 'cancelled', 'validation_running', 'validated', 'validation_failed', 'restore_running', 'restored', 'restore_failed')", name='ck_backup_restore_requests_status'),
    sa.ForeignKeyConstraint(['backup_job_id'], ['backup_jobs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['executed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'request_number', name='uq_backup_restore_requests_org_number')
    )
    op.create_table('report_definition_columns',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('definition_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('column_name', sa.String(length=120), server_default='', nullable=False),
    sa.Column('related_table', sa.String(length=120), server_default='', nullable=False),
    sa.Column('related_key_column', sa.String(length=120), server_default='', nullable=False),
    sa.Column('formula', sa.String(length=2000), server_default='', nullable=False),
    sa.Column('data_type', sa.String(length=20), nullable=False),
    sa.Column('decimals', sa.Integer(), server_default='2', nullable=False),
    sa.Column('prefix', sa.String(length=20), server_default='', nullable=False),
    sa.Column('suffix', sa.String(length=20), server_default='', nullable=False),
    sa.Column('aggregate', sa.String(length=20), server_default='NONE', nullable=False),
    sa.Column('show_total', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('hidden', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('condition_logic', sa.String(length=5), server_default='AND', nullable=False),
    sa.Column('width', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("aggregate IN ('NONE', 'SUM', 'AVG', 'COUNT', 'COUNT_DISTINCT', 'MIN', 'MAX', 'PRODUCT', 'FIRST', 'LAST')", name='ck_report_definition_columns_aggregate'),
    sa.CheckConstraint("condition_logic IN ('AND', 'OR')", name='ck_report_definition_columns_logic'),
    sa.CheckConstraint("data_type IN ('text', 'number', 'date', 'boolean')", name='ck_report_definition_columns_type'),
    sa.CheckConstraint("kind IN ('DATA', 'RELATED', 'CALCULATED')", name='ck_report_definition_columns_kind'),
    sa.ForeignKeyConstraint(['definition_id'], ['report_definitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('definition_id', 'key', name='uq_report_definition_columns_key')
    )
    op.create_table('report_definition_filters',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('definition_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=160), server_default='', nullable=False),
    sa.Column('source_kind', sa.String(length=20), nullable=False),
    sa.Column('column_name', sa.String(length=120), nullable=False),
    sa.Column('related_table', sa.String(length=120), server_default='', nullable=False),
    sa.Column('related_key_column', sa.String(length=120), server_default='', nullable=False),
    sa.Column('operator', sa.String(length=20), nullable=False),
    sa.Column('value', sa.String(length=500), server_default='', nullable=False),
    sa.Column('value2', sa.String(length=500), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("operator IN ('eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains', 'starts_with', 'ends_with', 'in', 'not_in', 'between', 'is_blank', 'is_not_blank')", name='ck_report_definition_filters_operator'),
    sa.CheckConstraint("source_kind IN ('DATA', 'RELATED')", name='ck_report_definition_filters_source'),
    sa.ForeignKeyConstraint(['definition_id'], ['report_definitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('report_definition_grants',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('definition_id', sa.String(length=36), nullable=False),
    sa.Column('grant_type', sa.String(length=10), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('role_id', sa.String(length=36), nullable=True),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(grant_type = 'user' AND user_id IS NOT NULL) OR (grant_type = 'role' AND role_id IS NOT NULL)", name='ck_report_definition_grants_target'),
    sa.CheckConstraint("grant_type IN ('user', 'role')", name='ck_report_definition_grants_type'),
    sa.CheckConstraint("level IN ('view', 'edit')", name='ck_report_definition_grants_level'),
    sa.ForeignKeyConstraint(['definition_id'], ['report_definitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('report_definition_groupings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('definition_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('column_key', sa.String(length=80), nullable=False),
    sa.Column('bucket', sa.String(length=20), nullable=False),
    sa.CheckConstraint("bucket IN ('VALUE', 'DAY', 'WEEK', 'MONTH', 'QUARTER', 'YEAR')", name='ck_report_definition_groupings_bucket'),
    sa.CheckConstraint("kind IN ('group', 'matrix_row', 'matrix_column')", name='ck_report_definition_groupings_kind'),
    sa.ForeignKeyConstraint(['definition_id'], ['report_definitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('report_definition_runtime_filters',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('definition_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('filter_type', sa.String(length=20), nullable=False),
    sa.Column('source_kind', sa.String(length=20), nullable=False),
    sa.Column('column_name', sa.String(length=120), nullable=False),
    sa.Column('related_table', sa.String(length=120), server_default='', nullable=False),
    sa.Column('related_key_column', sa.String(length=120), server_default='', nullable=False),
    sa.Column('operator', sa.String(length=20), nullable=False),
    sa.Column('required', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('default_value', sa.String(length=500), server_default='', nullable=False),
    sa.Column('options_text', sa.String(length=2000), server_default='', nullable=False),
    sa.CheckConstraint("filter_type IN ('text', 'number', 'date', 'boolean', 'select')", name='ck_report_definition_runtime_type'),
    sa.CheckConstraint("operator IN ('eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains', 'starts_with', 'ends_with', 'in', 'not_in', 'between', 'is_blank', 'is_not_blank')", name='ck_report_definition_runtime_operator'),
    sa.CheckConstraint("source_kind IN ('DATA', 'RELATED')", name='ck_report_definition_runtime_source'),
    sa.ForeignKeyConstraint(['definition_id'], ['report_definitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('definition_id', 'key', name='uq_report_definition_runtime_key')
    )
    op.create_table('report_definition_sorts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('definition_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('column_key', sa.String(length=80), nullable=False),
    sa.Column('direction', sa.String(length=5), nullable=False),
    sa.CheckConstraint("direction IN ('ASC', 'DESC')", name='ck_report_definition_sorts_direction'),
    sa.ForeignKeyConstraint(['definition_id'], ['report_definitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('report_definition_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('definition_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('report_name', sa.String(length=160), nullable=False),
    sa.Column('report_type', sa.String(length=20), nullable=False),
    sa.Column('source_table', sa.String(length=120), nullable=False),
    sa.Column('column_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('filter_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('grouping_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('grant_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('change_note', sa.String(length=300), server_default='', nullable=False),
    sa.Column('changed_by_display', sa.String(length=160), server_default='', nullable=False),
    sa.Column('design_snapshot', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['definition_id'], ['report_definitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('definition_id', 'version', name='uq_report_definition_versions_definition_version')
    )
    op.create_table('backup_validations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('validation_number', sa.String(length=40), nullable=False),
    sa.Column('restore_request_id', sa.String(length=36), nullable=False),
    sa.Column('backup_job_id', sa.String(length=36), nullable=True),
    sa.Column('backup_number', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('checksum_matched', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('dry_run_performed', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('table_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('row_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('missing_tables', sa.String(length=2000), server_default='', nullable=False),
    sa.Column('changed_tables', sa.String(length=2000), server_default='', nullable=False),
    sa.Column('started_by_user_id', sa.String(length=36), nullable=True),
    sa.Column('started_by_display', sa.String(length=160), server_default='', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.String(length=2000), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('running', 'passed', 'passed_with_warnings', 'failed')", name='ck_backup_validations_status'),
    sa.ForeignKeyConstraint(['backup_job_id'], ['backup_jobs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['restore_request_id'], ['backup_restore_requests.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['started_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'validation_number', name='uq_backup_validations_org_number')
    )
    op.create_table('report_definition_conditions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('column_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('source_kind', sa.String(length=20), nullable=False),
    sa.Column('column_name', sa.String(length=120), server_default='', nullable=False),
    sa.Column('related_table', sa.String(length=120), server_default='', nullable=False),
    sa.Column('related_key_column', sa.String(length=120), server_default='', nullable=False),
    sa.Column('operator', sa.String(length=20), nullable=False),
    sa.Column('value', sa.String(length=500), server_default='', nullable=False),
    sa.Column('value2', sa.String(length=500), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("operator IN ('eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains', 'starts_with', 'ends_with', 'in', 'not_in', 'between', 'is_blank', 'is_not_blank')", name='ck_report_definition_conditions_operator'),
    sa.CheckConstraint("source_kind IN ('DATA', 'RELATED')", name='ck_report_definition_conditions_source'),
    sa.ForeignKeyConstraint(['column_id'], ['report_definition_columns.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('backup_validation_tables',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('validation_id', sa.String(length=36), nullable=False),
    sa.Column('table_name', sa.String(length=120), nullable=False),
    sa.Column('archive_rows', sa.Integer(), server_default='0', nullable=False),
    sa.Column('database_rows', sa.Integer(), server_default='0', nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['validation_id'], ['backup_validations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('validation_id', 'table_name', name='uq_backup_validation_tables_validation_table')
    )
    op.create_index(op.f('ix_backup_jobs_backup_number'), 'backup_jobs', ['backup_number'], unique=False)
    op.create_index(op.f('ix_backup_jobs_created_at'), 'backup_jobs', ['created_at'], unique=False)
    op.create_index('ix_backup_jobs_org_status', 'backup_jobs', ['organization_id', 'status', 'created_at'], unique=False)
    op.create_index(op.f('ix_backup_jobs_organization_id'), 'backup_jobs', ['organization_id'], unique=False)
    op.create_index(op.f('ix_backup_jobs_status'), 'backup_jobs', ['status'], unique=False)
    op.create_index(op.f('ix_backup_settings_next_run_at'), 'backup_settings', ['next_run_at'], unique=False)
    op.create_index(op.f('ix_backup_settings_organization_id'), 'backup_settings', ['organization_id'], unique=False)
    op.create_index('ix_report_definitions_org_status', 'report_definitions', ['organization_id', 'status', 'updated_at'], unique=False)
    op.create_index(op.f('ix_report_definitions_organization_id'), 'report_definitions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_report_definitions_updated_at'), 'report_definitions', ['updated_at'], unique=False)
    op.create_index(op.f('ix_backup_job_tables_job_id'), 'backup_job_tables', ['job_id'], unique=False)
    op.create_index(op.f('ix_backup_job_tables_organization_id'), 'backup_job_tables', ['organization_id'], unique=False)
    op.create_index(op.f('ix_backup_restore_requests_backup_job_id'), 'backup_restore_requests', ['backup_job_id'], unique=False)
    op.create_index('ix_backup_restore_requests_org_status', 'backup_restore_requests', ['organization_id', 'status', 'requested_at'], unique=False)
    op.create_index(op.f('ix_backup_restore_requests_organization_id'), 'backup_restore_requests', ['organization_id'], unique=False)
    op.create_index(op.f('ix_backup_restore_requests_request_number'), 'backup_restore_requests', ['request_number'], unique=False)
    op.create_index(op.f('ix_backup_restore_requests_status'), 'backup_restore_requests', ['status'], unique=False)
    op.create_index(op.f('ix_report_definition_columns_definition_id'), 'report_definition_columns', ['definition_id'], unique=False)
    op.create_index(op.f('ix_report_definition_columns_organization_id'), 'report_definition_columns', ['organization_id'], unique=False)
    op.create_index(op.f('ix_report_definition_filters_definition_id'), 'report_definition_filters', ['definition_id'], unique=False)
    op.create_index(op.f('ix_report_definition_filters_organization_id'), 'report_definition_filters', ['organization_id'], unique=False)
    op.create_index(op.f('ix_report_definition_grants_definition_id'), 'report_definition_grants', ['definition_id'], unique=False)
    op.create_index(op.f('ix_report_definition_grants_organization_id'), 'report_definition_grants', ['organization_id'], unique=False)
    op.create_index(op.f('ix_report_definition_grants_role_id'), 'report_definition_grants', ['role_id'], unique=False)
    op.create_index(op.f('ix_report_definition_grants_user_id'), 'report_definition_grants', ['user_id'], unique=False)
    op.create_index(op.f('ix_report_definition_groupings_definition_id'), 'report_definition_groupings', ['definition_id'], unique=False)
    op.create_index(op.f('ix_report_definition_groupings_organization_id'), 'report_definition_groupings', ['organization_id'], unique=False)
    op.create_index(op.f('ix_report_definition_runtime_filters_definition_id'), 'report_definition_runtime_filters', ['definition_id'], unique=False)
    op.create_index(op.f('ix_report_definition_runtime_filters_organization_id'), 'report_definition_runtime_filters', ['organization_id'], unique=False)
    op.create_index(op.f('ix_report_definition_sorts_definition_id'), 'report_definition_sorts', ['definition_id'], unique=False)
    op.create_index(op.f('ix_report_definition_sorts_organization_id'), 'report_definition_sorts', ['organization_id'], unique=False)
    op.create_index(op.f('ix_report_definition_versions_definition_id'), 'report_definition_versions', ['definition_id'], unique=False)
    op.create_index(op.f('ix_report_definition_versions_organization_id'), 'report_definition_versions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_backup_validations_backup_job_id'), 'backup_validations', ['backup_job_id'], unique=False)
    op.create_index(op.f('ix_backup_validations_organization_id'), 'backup_validations', ['organization_id'], unique=False)
    op.create_index(op.f('ix_backup_validations_restore_request_id'), 'backup_validations', ['restore_request_id'], unique=False)
    op.create_index(op.f('ix_backup_validations_validation_number'), 'backup_validations', ['validation_number'], unique=False)
    op.create_index(op.f('ix_report_definition_conditions_column_id'), 'report_definition_conditions', ['column_id'], unique=False)
    op.create_index(op.f('ix_report_definition_conditions_organization_id'), 'report_definition_conditions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_backup_validation_tables_organization_id'), 'backup_validation_tables', ['organization_id'], unique=False)
    op.create_index(op.f('ix_backup_validation_tables_validation_id'), 'backup_validation_tables', ['validation_id'], unique=False)
    _seed_capabilities()


def downgrade() -> None:
    # Remove the seeded capabilities before their tables go away (there is no FK
    # from permissions, so order only matters for readability).
    op.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key LIKE 'backup:%' OR key LIKE 'report-builder:%' OR key LIKE 'custom-reports:%')"))
    op.execute(sa.text("DELETE FROM permissions WHERE key LIKE 'backup:%' OR key LIKE 'report-builder:%' OR key LIKE 'custom-reports:%'"))

    op.drop_table("report_definition_versions")
    op.drop_table("report_definition_grants")
    op.drop_table("report_definition_sorts")
    op.drop_table("report_definition_groupings")
    op.drop_table("report_definition_runtime_filters")
    op.drop_table("report_definition_filters")
    op.drop_table("report_definition_conditions")
    op.drop_table("report_definition_columns")
    op.drop_table("report_definitions")
    op.drop_table("backup_validation_tables")
    op.drop_table("backup_validations")
    op.drop_table("backup_restore_requests")
    op.drop_table("backup_job_tables")
    op.drop_table("backup_jobs")
    op.drop_table("backup_settings")
