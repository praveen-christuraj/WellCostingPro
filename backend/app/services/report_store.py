"""Saving, versioning and sharing Report Builder definitions.

The live design lives in typed rows (see ``app/models/report_builder.py``); this
module turns a validated design dictionary into those rows and back, keeps one
immutable version snapshot per save, and answers the access questions the API
and the menus share.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import granted, owner as is_owner
from app.models import (
    ReportDefinition,
    ReportDefinitionColumn,
    ReportDefinitionCondition,
    ReportDefinitionFilter,
    ReportDefinitionGrant,
    ReportDefinitionGrouping,
    ReportDefinitionRuntimeFilter,
    ReportDefinitionSort,
    ReportDefinitionVersion,
    Role,
    User,
)
from app.services.report_engine import ReportError, definition_from_record


def _display(user: User | None) -> str:
    return (user.full_name or user.email) if user else ""


def _apply_children(db: Session, record: ReportDefinition, design: dict, organization_id: str) -> None:
    """Replace every child row with the validated design (cascades remove the old ones)."""
    record.columns.clear()
    record.filters.clear()
    record.runtime_filters.clear()
    record.groupings.clear()
    record.sorts.clear()
    record.grants.clear()
    db.flush()

    for position, item in enumerate(design["columns"], start=1):
        column = ReportDefinitionColumn(
            organization_id=organization_id,
            definition_id=record.id,
            position=position,
            key=item["key"],
            label=item["label"][:160],
            kind=item["kind"],
            column_name=item.get("column_name", "")[:120],
            related_table=item.get("related_table", "")[:120],
            related_key_column=item.get("related_key_column", "")[:120],
            formula=item.get("formula", "")[:2000],
            data_type=item["data_type"],
            decimals=int(item.get("decimals", 2)),
            prefix=item.get("prefix", "")[:20],
            suffix=item.get("suffix", "")[:20],
            aggregate=item.get("aggregate", "NONE"),
            show_total=bool(item.get("show_total")),
            hidden=bool(item.get("hidden")),
            condition_logic=item.get("condition_logic", "AND"),
            width=int(item.get("width") or 0),
        )
        for condition_position, rule in enumerate(item.get("conditions") or [], start=1):
            column.conditions.append(ReportDefinitionCondition(
                organization_id=organization_id,
                position=condition_position,
                source_kind=rule.get("source_kind", "DATA"),
                column_name=rule.get("column_name", "")[:120],
                related_table=rule.get("related_table", "")[:120],
                related_key_column=rule.get("related_key_column", "")[:120],
                operator=rule.get("operator", "eq"),
                value=str(rule.get("value", ""))[:500],
                value2=str(rule.get("value2", ""))[:500],
            ))
        record.columns.append(column)

    for position, item in enumerate(design["filters"], start=1):
        record.filters.append(ReportDefinitionFilter(
            organization_id=organization_id,
            position=position,
            label=item.get("label", "")[:160],
            source_kind=item.get("source_kind", "DATA"),
            column_name=item.get("column_name", "")[:120],
            related_table=item.get("related_table", "")[:120],
            related_key_column=item.get("related_key_column", "")[:120],
            operator=item.get("operator", "eq"),
            value=str(item.get("value", ""))[:500],
            value2=str(item.get("value2", ""))[:500],
        ))
    for position, item in enumerate(design["runtime_filters"], start=1):
        record.runtime_filters.append(ReportDefinitionRuntimeFilter(
            organization_id=organization_id,
            position=position,
            key=item["key"],
            label=item["label"][:160],
            filter_type=item["filter_type"],
            source_kind=item.get("source_kind", "DATA"),
            column_name=item.get("column_name", "")[:120],
            related_table=item.get("related_table", "")[:120],
            related_key_column=item.get("related_key_column", "")[:120],
            operator=item.get("operator", "eq"),
            required=bool(item.get("required")),
            default_value=str(item.get("default_value", ""))[:500],
            options_text="\n".join(item.get("options") or [])[:2000],
        ))
    for position, item in enumerate(design["groupings"], start=1):
        record.groupings.append(ReportDefinitionGrouping(
            organization_id=organization_id,
            position=position,
            kind=item["kind"],
            column_key=item["column_key"],
            bucket=item["bucket"],
        ))
    for position, item in enumerate(design["sorts"], start=1):
        record.sorts.append(ReportDefinitionSort(
            organization_id=organization_id,
            position=position,
            column_key=item["column_key"],
            direction=item["direction"],
        ))
    for item in design["grants"]:
        record.grants.append(ReportDefinitionGrant(
            organization_id=organization_id,
            grant_type=item["grant_type"],
            user_id=item.get("user_id") or None,
            role_id=item.get("role_id") or None,
            level=item["level"],
        ))
    db.flush()


def _assign_fields(record: ReportDefinition, design: dict) -> None:
    record.name = design["name"]
    record.description = design["description"]
    record.report_type = design["report_type"]
    record.source_table = design["source_table"]
    record.date_basis = design["date_basis"]
    record.date_column = design["date_column"]
    record.filter_logic = design["filter_logic"]
    record.show_totals = design["show_totals"]
    record.page_size = design["page_size"]
    record.empty_text = design["empty_text"]
    record.matrix_value_key = design["matrix_value_key"]
    record.matrix_aggregate = design["matrix_aggregate"]
    record.matrix_show_totals = design["matrix_show_totals"]
    record.visibility = design["visibility"]


def _write_version(db: Session, record: ReportDefinition, design: dict, user: User | None, note: str) -> None:
    db.add(ReportDefinitionVersion(
        organization_id=record.organization_id,
        definition_id=record.id,
        version=record.version,
        report_name=record.name,
        report_type=record.report_type,
        source_table=record.source_table,
        column_count=len(design["columns"]),
        filter_count=len(design["filters"]) + sum(len(column.get("conditions") or []) for column in design["columns"]),
        grouping_count=len(design["groupings"]),
        grant_count=len(design["grants"]),
        status=record.status,
        change_note=note[:300],
        changed_by_display=_display(user),
        design_snapshot=json.dumps(design, ensure_ascii=False, separators=(",", ":")),
    ))
    db.flush()


def _name_taken(db: Session, organization_id: str, name: str, exclude_id: str | None = None) -> bool:
    statement = select(ReportDefinition.id).where(
        ReportDefinition.organization_id == organization_id,
        ReportDefinition.name == name,
    )
    if exclude_id:
        statement = statement.where(ReportDefinition.id != exclude_id)
    return db.scalar(statement) is not None


def unique_name(db: Session, organization_id: str, name: str, exclude_id: str | None = None) -> str:
    """Keep report names unique per workspace, the way every register does."""
    base = name.strip()[:150] or "Custom report"
    candidate = base
    suffix = 2
    while _name_taken(db, organization_id, candidate, exclude_id):
        candidate = f"{base} ({suffix})"[:160]
        suffix += 1
    return candidate


def create_definition(db: Session, organization_id: str, user: User, design: dict, *, publisher: bool = False) -> ReportDefinition:
    record = ReportDefinition(
        organization_id=organization_id,
        name=unique_name(db, organization_id, design["name"]),
        report_type=design["report_type"],
        source_table=design["source_table"],
        status="published" if publisher else "draft",
        published_at=datetime.now(timezone.utc) if publisher else None,
        version=1,
        created_by_user_id=user.id,
        created_by_display=_display(user),
        updated_by_display=_display(user),
    )
    _assign_fields(record, design)
    db.add(record)
    db.flush()
    _apply_children(db, record, design, organization_id)
    record.version = 1
    _write_version(db, record, design, user, "Created")
    db.flush()
    return record


def update_definition(db: Session, record: ReportDefinition, design: dict, user: User, note: str = "") -> ReportDefinition:
    if design["name"] != record.name:
        design = {**design, "name": unique_name(db, record.organization_id, design["name"], exclude_id=record.id)}
    record.version += 1
    _assign_fields(record, design)
    _apply_children(db, record, design, record.organization_id)
    record.updated_by_display = _display(user)
    record.updated_at = datetime.now(timezone.utc)
    if record.status == "published":
        # An edited published report stays published; the new version is already
        # what every viewer will run.
        record.published_at = record.published_at or datetime.now(timezone.utc)
    _write_version(db, record, design, user, note or f"Saved version {record.version}")
    db.flush()
    return record


def duplicate_definition(db: Session, record: ReportDefinition, user: User) -> ReportDefinition:
    design = definition_from_record(record)
    design["name"] = f"{record.name} copy"
    design["visibility"] = "private"
    design["grants"] = []
    copy = ReportDefinition(
        organization_id=record.organization_id,
        name=unique_name(db, record.organization_id, design["name"]),
        report_type=record.report_type,
        source_table=record.source_table,
        status="draft",
        version=1,
        created_by_user_id=user.id,
        created_by_display=_display(user),
        updated_by_display=_display(user),
    )
    _assign_fields(copy, design)
    db.add(copy)
    db.flush()
    _apply_children(db, copy, design, record.organization_id)
    _write_version(db, copy, design, user, f"Copied from {record.name}")
    db.flush()
    return copy


def create_from_starter(db: Session, organization_id: str, user: User, design: dict) -> ReportDefinition:
    design["visibility"] = "private"
    design["grants"] = []
    return create_definition(db, organization_id, user, design)


def publish(db: Session, record: ReportDefinition, user: User, *, published: bool) -> ReportDefinition:
    record.status = "published" if published else "draft"
    record.published_at = datetime.now(timezone.utc) if published else None
    record.updated_by_display = _display(user)
    record.updated_at = datetime.now(timezone.utc)
    # Publishing is a design event of its own, so it earns its own version row.
    record.version += 1
    _write_version(db, record, definition_from_record(record), user, "Published" if published else "Unpublished")
    db.flush()
    return record


def versions(db: Session, record: ReportDefinition) -> list[ReportDefinitionVersion]:
    return list(db.scalars(
        select(ReportDefinitionVersion)
        .where(ReportDefinitionVersion.definition_id == record.id)
        .order_by(ReportDefinitionVersion.version.desc())
    ).all())


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


def _user_role_ids(user: User) -> set[str]:
    return {role.id for role in user.roles}


def grant_level(record: ReportDefinition, user: User) -> str:
    """Highest level this user was granted directly or through a role."""
    role_ids = _user_role_ids(user)
    level = ""
    for grant in record.grants:
        if grant.grant_type == "user" and grant.user_id == user.id:
            level = "edit" if grant.level == "edit" else "view"
        elif grant.grant_type == "role" and grant.role_id in role_ids:
            if grant.level == "edit":
                return "edit"
            level = level or "view"
        if level == "edit":
            return level
    return level


def is_creator(record: ReportDefinition, user: User) -> bool:
    return record.created_by_user_id == user.id


def can_view(record: ReportDefinition, user: User) -> bool:
    if record.organization_id != user.organization_id:
        return False
    if is_owner(user) or is_creator(record, user) or grant_level(record, user):
        return True
    if record.visibility == "internal":
        return is_owner(user) or "custom-reports:read" in granted(user) or "report-builder:read" in granted(user)
    return False


def can_edit(record: ReportDefinition, user: User) -> bool:
    if record.organization_id != user.organization_id:
        return False
    if is_owner(user):
        return True
    if "report-builder:update" not in granted(user):
        return False
    return is_creator(record, user) or grant_level(record, user) == "edit"


def can_delete(record: ReportDefinition, user: User) -> bool:
    if record.organization_id != user.organization_id:
        return False
    if is_owner(user):
        return True
    return "report-builder:delete" in granted(user) and is_creator(record, user)


def can_publish(record: ReportDefinition, user: User) -> bool:
    return record.organization_id == user.organization_id and (
        is_owner(user) or "report-builder:publish" in granted(user)
    )


def can_run_published(record: ReportDefinition, user: User) -> bool:
    """Running a published report needs the reporting capability plus access."""
    if record.status != "published":
        return False
    if not (is_owner(user) or "custom-reports:read" in granted(user)):
        return False
    return can_view(record, user)


def visible_definitions(db: Session, organization_id: str, user: User, include_archived: bool = False) -> list[ReportDefinition]:
    statement = select(ReportDefinition).where(ReportDefinition.organization_id == organization_id)
    if not include_archived:
        statement = statement.where(ReportDefinition.status != "archived")
    rows = list(db.scalars(statement.order_by(ReportDefinition.updated_at.desc())).all())
    return [record for record in rows if can_view(record, user)]


def published_reports(db: Session, organization_id: str, user: User) -> list[ReportDefinition]:
    rows = list(db.scalars(
        select(ReportDefinition)
        .where(ReportDefinition.organization_id == organization_id, ReportDefinition.status == "published")
        .order_by(ReportDefinition.name)
    ).all())
    return [record for record in rows if can_run_published(record, user)]


def grant_labels(db: Session, record: ReportDefinition) -> list[dict]:
    """Resolve grant targets to readable names for the editor and viewer."""
    labels = []
    for grant in record.grants:
        if grant.grant_type == "user":
            target = db.get(User, grant.user_id) if grant.user_id else None
            labels.append({
                "grant_type": "user", "id": grant.user_id or "", "level": grant.level,
                "name": (target.full_name or target.email) if target else "Removed account",
                "detail": target.email if target else "",
            })
        else:
            target = db.get(Role, grant.role_id) if grant.role_id else None
            labels.append({
                "grant_type": "role", "id": grant.role_id or "", "level": grant.level,
                "name": target.name if target else "Removed role",
                "detail": "Role",
            })
    return labels


def lookups(db: Session, organization_id: str) -> dict:
    users = list(db.scalars(
        select(User).where(User.organization_id == organization_id, User.is_active.is_(True)).order_by(User.full_name)
    ).all())
    roles = list(db.scalars(select(Role).where(Role.organization_id == organization_id).order_by(Role.name)).all())
    return {
        "users": [{"id": user.id, "name": user.full_name or user.email, "email": user.email} for user in users],
        "roles": [{"id": role.id, "name": role.name, "is_owner": role.is_owner} for role in roles],
    }


def record_run(db: Session, record: ReportDefinition) -> None:
    record.run_count = (record.run_count or 0) + 1
    record.last_run_at = datetime.now(timezone.utc)
    db.commit()


def definition_error(error: Exception) -> ReportError:
    if isinstance(error, ReportError):
        return error
    return ReportError(f"The report could not be run: {error}")
