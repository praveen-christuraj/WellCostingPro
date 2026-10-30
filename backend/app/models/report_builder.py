"""Report Builder definitions, access grants and design history.

The live design is stored column-wise across the `report_definition_*` tables —
never as a JSON blob — so a report can be inspected, audited and permission
scoped like any other business record. `report_definition_versions` keeps an
immutable archival snapshot per save (text, never queried as data) plus typed
summary facts, which is the one place a serialised design legitimately exists.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.entities import now, uid

REPORT_TYPES = ("TABULAR", "MATRIX")
REPORT_STATUSES = ("draft", "published", "archived")
COLUMN_KINDS = ("DATA", "RELATED", "CALCULATED")
DATA_TYPES = ("text", "number", "date", "boolean")
AGGREGATES = ("NONE", "SUM", "AVG", "COUNT", "COUNT_DISTINCT", "MIN", "MAX", "PRODUCT", "FIRST", "LAST")
BUCKETS = ("VALUE", "DAY", "WEEK", "MONTH", "QUARTER", "YEAR")
FILTER_OPERATORS = (
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "in",
    "not_in",
    "between",
    "is_blank",
    "is_not_blank",
)
RUNTIME_FILTER_TYPES = ("text", "number", "date", "boolean", "select")
GRANT_TYPES = ("user", "role")
ACCESS_LEVELS = ("view", "edit")
GROUPING_KINDS = ("group", "matrix_row", "matrix_column")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class ReportDefinition(Base):
    __tablename__ = "report_definitions"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_report_definitions_org_name"),
        CheckConstraint(_in("report_type", REPORT_TYPES), name="ck_report_definitions_type"),
        CheckConstraint(_in("status", REPORT_STATUSES), name="ck_report_definitions_status"),
        CheckConstraint(_in("date_basis", ("COLUMN", "CREATED_AT", "UPDATED_AT", "NONE")), name="ck_report_definitions_date_basis"),
        Index("ix_report_definitions_org_status", "organization_id", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), default="TABULAR", nullable=False)
    source_table: Mapped[str] = mapped_column(String(120), nullable=False)
    date_basis: Mapped[str] = mapped_column(String(20), default="NONE", nullable=False)
    date_column: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    filter_logic: Mapped[str] = mapped_column(String(5), default="AND", server_default="AND", nullable=False)
    show_totals: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    page_size: Mapped[int] = mapped_column(Integer, default=50, server_default="50", nullable=False)
    empty_text: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    matrix_value_key: Mapped[str] = mapped_column(String(80), default="", server_default="", nullable=False)
    matrix_aggregate: Mapped[str] = mapped_column(String(20), default="SUM", server_default="SUM", nullable=False)
    matrix_show_totals: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), default="private", server_default="private", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_display: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    updated_by_display: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False, index=True)

    columns: Mapped[list["ReportDefinitionColumn"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ReportDefinitionColumn.position", lazy="selectin",
    )
    filters: Mapped[list["ReportDefinitionFilter"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ReportDefinitionFilter.position", lazy="selectin",
    )
    runtime_filters: Mapped[list["ReportDefinitionRuntimeFilter"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ReportDefinitionRuntimeFilter.position", lazy="selectin",
    )
    groupings: Mapped[list["ReportDefinitionGrouping"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ReportDefinitionGrouping.position", lazy="selectin",
    )
    sorts: Mapped[list["ReportDefinitionSort"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ReportDefinitionSort.position", lazy="selectin",
    )
    grants: Mapped[list["ReportDefinitionGrant"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin",
    )


class ReportDefinitionColumn(Base):
    __tablename__ = "report_definition_columns"
    __table_args__ = (
        UniqueConstraint("definition_id", "key", name="uq_report_definition_columns_key"),
        CheckConstraint(_in("kind", COLUMN_KINDS), name="ck_report_definition_columns_kind"),
        CheckConstraint(_in("data_type", DATA_TYPES), name="ck_report_definition_columns_type"),
        CheckConstraint(_in("aggregate", AGGREGATES), name="ck_report_definition_columns_aggregate"),
        CheckConstraint(_in("condition_logic", ("AND", "OR")), name="ck_report_definition_columns_logic"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="DATA", nullable=False)
    # DATA: base table column. RELATED: one declared foreign-key hop, e.g. entry_id → wells.well_name.
    column_name: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    related_table: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    related_key_column: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    formula: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, default=2, server_default="2", nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), default="", server_default="", nullable=False)
    suffix: Mapped[str] = mapped_column(String(20), default="", server_default="", nullable=False)
    aggregate: Mapped[str] = mapped_column(String(20), default="NONE", server_default="NONE", nullable=False)
    show_total: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    condition_logic: Mapped[str] = mapped_column(String(5), default="AND", server_default="AND", nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    definition: Mapped[ReportDefinition] = relationship(back_populates="columns")
    conditions: Mapped[list["ReportDefinitionCondition"]] = relationship(
        back_populates="column", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ReportDefinitionCondition.position", lazy="selectin",
    )


class ReportDefinitionCondition(Base):
    """A rule that blanks one measure unless the row matches (comparison columns)."""

    __tablename__ = "report_definition_conditions"
    __table_args__ = (
        CheckConstraint(_in("operator", FILTER_OPERATORS), name="ck_report_definition_conditions_operator"),
        CheckConstraint(_in("source_kind", ("DATA", "RELATED")), name="ck_report_definition_conditions_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_id: Mapped[str] = mapped_column(
        ForeignKey("report_definition_columns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), default="DATA", nullable=False)
    column_name: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    related_table: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    related_key_column: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    operator: Mapped[str] = mapped_column(String(20), default="eq", nullable=False)
    value: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    value2: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    column: Mapped[ReportDefinitionColumn] = relationship(back_populates="conditions")


class ReportDefinitionFilter(Base):
    """A fixed condition that is always applied to the report."""

    __tablename__ = "report_definition_filters"
    __table_args__ = (
        CheckConstraint(_in("operator", FILTER_OPERATORS), name="ck_report_definition_filters_operator"),
        CheckConstraint(_in("source_kind", ("DATA", "RELATED")), name="ck_report_definition_filters_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    label: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), default="DATA", nullable=False)
    column_name: Mapped[str] = mapped_column(String(120), nullable=False)
    related_table: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    related_key_column: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    operator: Mapped[str] = mapped_column(String(20), default="eq", nullable=False)
    value: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    value2: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    definition: Mapped[ReportDefinition] = relationship(back_populates="filters")


class ReportDefinitionRuntimeFilter(Base):
    """A question asked when the report is run (date range is built in)."""

    __tablename__ = "report_definition_runtime_filters"
    __table_args__ = (
        CheckConstraint(_in("filter_type", RUNTIME_FILTER_TYPES), name="ck_report_definition_runtime_type"),
        CheckConstraint(_in("operator", FILTER_OPERATORS), name="ck_report_definition_runtime_operator"),
        CheckConstraint(_in("source_kind", ("DATA", "RELATED")), name="ck_report_definition_runtime_source"),
        UniqueConstraint("definition_id", "key", name="uq_report_definition_runtime_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    filter_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), default="DATA", nullable=False)
    column_name: Mapped[str] = mapped_column(String(120), nullable=False)
    related_table: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    related_key_column: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    operator: Mapped[str] = mapped_column(String(20), default="eq", nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    default_value: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    options_text: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)

    definition: Mapped[ReportDefinition] = relationship(back_populates="runtime_filters")


class ReportDefinitionGrouping(Base):
    __tablename__ = "report_definition_groupings"
    __table_args__ = (
        CheckConstraint(_in("kind", GROUPING_KINDS), name="ck_report_definition_groupings_kind"),
        CheckConstraint(_in("bucket", BUCKETS), name="ck_report_definition_groupings_bucket"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="group", nullable=False)
    column_key: Mapped[str] = mapped_column(String(80), nullable=False)
    bucket: Mapped[str] = mapped_column(String(20), default="VALUE", nullable=False)

    definition: Mapped[ReportDefinition] = relationship(back_populates="groupings")


class ReportDefinitionSort(Base):
    __tablename__ = "report_definition_sorts"
    __table_args__ = (CheckConstraint(_in("direction", ("ASC", "DESC")), name="ck_report_definition_sorts_direction"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_key: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), default="ASC", nullable=False)

    definition: Mapped[ReportDefinition] = relationship(back_populates="sorts")


class ReportDefinitionGrant(Base):
    __tablename__ = "report_definition_grants"
    __table_args__ = (
        CheckConstraint(_in("grant_type", GRANT_TYPES), name="ck_report_definition_grants_type"),
        CheckConstraint(_in("level", ACCESS_LEVELS), name="ck_report_definition_grants_level"),
        CheckConstraint(
            "(grant_type = 'user' AND user_id IS NOT NULL) OR (grant_type = 'role' AND role_id IS NOT NULL)",
            name="ck_report_definition_grants_target",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    grant_type: Mapped[str] = mapped_column(String(10), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(10), default="view", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    definition: Mapped[ReportDefinition] = relationship(back_populates="grants")


class ReportDefinitionVersion(Base):
    """Immutable design history. Typed facts plus an archival text snapshot."""

    __tablename__ = "report_definition_versions"
    __table_args__ = (
        UniqueConstraint("definition_id", "version", name="uq_report_definition_versions_definition_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    report_name: Mapped[str] = mapped_column(String(160), nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_table: Mapped[str] = mapped_column(String(120), nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    filter_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    grouping_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    grant_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    change_note: Mapped[str] = mapped_column(String(300), default="", server_default="", nullable=False)
    changed_by_display: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    design_snapshot: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
