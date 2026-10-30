"""Report Builder (design) and Custom Reports (run) API.

Capabilities:

``report-builder:read``     see the designer's reports
``report-builder:create``   design, preview, duplicate, copy a starter
``report-builder:update``   redesign a report you own or were given edit access to
``report-builder:delete``   delete a report you created
``report-builder:publish``  put a report in the Reporting menu / take it out
``custom-reports:read``     run published reports shared with you
``custom-reports:export``   download the full result of a published report

Per-report grants narrow those capabilities further. A design that cannot be
seen answers 404, so the builder never leaks another user's report names.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.deps import Current, Db, granted, owner as is_owner, require, require_any
from app.models import ReportDefinition, ReportDefinitionVersion
from app.schemas.report_builder import (
    ReportDefinitionIn,
    ReportDefinitionList,
    ReportDefinitionOut,
    ReportExportAuditIn,
    ReportFromStarterIn,
    ReportGrantOut,
    ReportPublishIn,
    ReportRunIn,
    ReportRunOut,
    ReportVersionDetail,
    ReportVersionOut,
)
from app.services import audit
from app.services import report_engine as engine
from app.services import report_store as store
from app.services.report_catalog import catalog_payload, build_catalog

router = APIRouter(prefix="/report-builder", tags=["Report Builder"])

DESIGNER_ANY = ("report-builder:read", "report-builder:create", "report-builder:update")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _perform(error: engine.ReportError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


def _get_visible(db: Db, user: Current, definition_id: str) -> ReportDefinition:
    record = db.get(ReportDefinition, definition_id)
    if record is None or record.organization_id != user.organization_id or not store.can_view(record, user):
        raise HTTPException(404, "That report is not available to you. It may have been deleted or shared differently.")
    return record


def _can_run_design(record: ReportDefinition, user) -> bool:
    if record.organization_id != user.organization_id:
        return False
    if is_owner(user):
        return True
    if record.status == "published" and store.can_run_published(record, user):
        return True
    return store.can_view(record, user) and (
        store.can_edit(record, user) or "report-builder:read" in granted(user)
    )


def _definition_out(db: Db, record: ReportDefinition, user) -> ReportDefinitionOut:
    return ReportDefinitionOut(
        id=record.id,
        name=record.name,
        description=record.description,
        status=record.status,
        version=record.version,
        visibility=record.visibility,
        report_type=record.report_type,
        source_table=record.source_table,
        run_count=record.run_count,
        last_run_at=record.last_run_at,
        published_at=record.published_at,
        created_by_display=record.created_by_display,
        updated_by_display=record.updated_by_display,
        created_at=record.created_at,
        updated_at=record.updated_at,
        can_edit=store.can_edit(record, user),
        can_delete=store.can_delete(record, user),
        can_publish=store.can_publish(record, user),
        can_run=_can_run_design(record, user),
        grants=[ReportGrantOut(**label) for label in store.grant_labels(db, record)],
        design=engine.definition_from_record(record),
    )


def _audit(db: Db, user, action: str, record: ReportDefinition, summary: str, request: Request | None = None) -> None:
    audit.record(
        db, organization_id=user.organization_id, actor=user, action=action,
        entity_type="report_builder", entity_id=record.id, entity_label=record.name,
        summary=summary, request=request,
    )


def _design(payload: ReportDefinitionIn) -> dict:
    return payload.model_dump()


def _run_payload(payload: ReportRunIn) -> dict:
    return payload.model_dump()


# ---------------------------------------------------------------------------
# Catalogue and design-time helpers
# ---------------------------------------------------------------------------


@router.get("/catalog", dependencies=[Depends(require_any(*DESIGNER_ANY))])
def catalog(db: Db) -> dict:
    return catalog_payload(db.get_bind())


@router.get("/catalog/{table_name}", dependencies=[Depends(require_any(*DESIGNER_ANY))])
def catalog_table(table_name: str, db: Db) -> dict:
    catalog_index = build_catalog(db.get_bind())
    info = catalog_index.get(table_name)
    if info is None:
        raise HTTPException(404, "That table is not available for reports in this workspace.")
    return info.detail()


@router.get("/lookups", dependencies=[Depends(require_any(*DESIGNER_ANY))])
def lookups(db: Db, user: Current) -> dict:
    return store.lookups(db, user.organization_id)


@router.get("/starters", dependencies=[Depends(require_any(*DESIGNER_ANY))])
def starters(db: Db, user: Current) -> dict:
    catalog_index = build_catalog(db.get_bind())
    items = []
    for design in engine.starter_designs():
        info = catalog_index.get(design["source_table"])
        items.append({
            "key": design["name"].lower().replace(" ", "-").replace("(", "").replace(")", ""),
            "name": design["name"],
            "description": design["description"],
            "report_type": design["report_type"],
            "source_table": design["source_table"],
            "source_label": info.label if info else design["source_table"],
            "column_count": len(design["columns"]),
            "available": info is not None,
        })
    return {"items": items}


@router.get("/formula-help", dependencies=[Depends(require_any(*DESIGNER_ANY))])
def formula_help() -> dict:
    from app.services.report_formula import FUNCTION_HELP, FUNCTIONS

    return {
        "functions": [name for name in FUNCTIONS],
        "help": [{"signature": signature, "description": description} for signature, description in FUNCTION_HELP],
        "operators": ["+ - * / ^", "= <> > >= < <=", "AND OR NOT", "%  (percent of: a ÷ b × 100)"],
    }


@router.post("/validate", dependencies=[Depends(require_any(*DESIGNER_ANY))])
def validate(payload: ReportDefinitionIn, db: Db, user: Current) -> dict:
    try:
        design = engine.validate_definition(db, _design(payload), user.organization_id)
    except engine.ReportError as error:
        return {"valid": False, "problems": [error.detail], "design": None}
    return {"valid": True, "problems": [], "design": design}


@router.post("/preview", response_model=ReportRunOut, dependencies=[Depends(require_any(*DESIGNER_ANY))])
def preview(payload: dict, db: Db, user: Current) -> ReportRunOut:
    """Run an unsaved design against real data (first page only)."""
    raw = payload.get("design") if isinstance(payload, dict) and "design" in payload else payload
    params = payload.get("params") if isinstance(payload, dict) else {}
    try:
        design = engine.validate_definition(db, raw or {}, user.organization_id)
        params = {**(params or {}), "page": 1, "page_size": min(25, int((params or {}).get("page_size") or 25))}
        result = engine.run_report(db, design, params, user.organization_id)
    except engine.ReportError as error:
        raise _perform(error) from error
    return ReportRunOut(**result)


# ---------------------------------------------------------------------------
# Definitions (designer)
# ---------------------------------------------------------------------------


@router.get("/definitions", response_model=ReportDefinitionList, dependencies=[Depends(require_any(*DESIGNER_ANY))])
def list_definitions(
    db: Db,
    user: Current,
    scope: str = Query(default="all", pattern="^(all|mine|shared)$"),
    q: str = Query(default="", max_length=120),
) -> ReportDefinitionList:
    rows = store.visible_definitions(db, user.organization_id, user)
    mine = [record for record in rows if store.is_creator(record, user)]
    shared = [record for record in rows if not store.is_creator(record, user)]
    chosen = mine if scope == "mine" else shared if scope == "shared" else rows
    needle = q.strip().lower()
    if needle:
        chosen = [
            record for record in chosen
            if needle in record.name.lower() or needle in record.description.lower() or needle in record.source_table
        ]
    return ReportDefinitionList(
        items=[_definition_out(db, record, user) for record in chosen],
        counts={
            "all": len(rows),
            "mine": len(mine),
            "shared": len(shared),
            "draft": sum(1 for record in rows if record.status == "draft"),
            "published": sum(1 for record in rows if record.status == "published"),
        },
    )


@router.post("/definitions", response_model=ReportDefinitionOut, status_code=201, dependencies=[Depends(require("report-builder:create"))])
def create_definition(payload: ReportDefinitionIn, request: Request, db: Db, user: Current) -> ReportDefinitionOut:
    try:
        design = engine.validate_definition(db, _design(payload), user.organization_id)
        record = store.create_definition(db, user.organization_id, user, design)
    except engine.ReportError as error:
        db.rollback()
        raise _perform(error) from error
    _audit(db, user, "report_create", record, f"Created report “{record.name}” from {record.source_table} ({record.report_type})", request)
    db.commit()
    return _definition_out(db, record, user)


@router.post("/definitions/from-starter", response_model=ReportDefinitionOut, status_code=201, dependencies=[Depends(require("report-builder:create"))])
def create_from_starter(payload: ReportFromStarterIn, request: Request, db: Db, user: Current) -> ReportDefinitionOut:
    designs = {design["name"].lower().replace(" ", "-").replace("(", "").replace(")", ""): design for design in engine.starter_designs()}
    design = designs.get(payload.key.lower())
    if design is None:
        raise HTTPException(404, "That starter report does not exist.")
    if payload.name.strip():
        design = {**design, "name": payload.name.strip()}
    try:
        design = engine.validate_definition(db, design, user.organization_id)
        record = store.create_from_starter(db, user.organization_id, user, design)
    except engine.ReportError as error:
        db.rollback()
        raise _perform(error) from error
    _audit(db, user, "report_create", record, f"Created report “{record.name}” from a starter design", request)
    db.commit()
    return _definition_out(db, record, user)


@router.get("/definitions/{definition_id}", response_model=ReportDefinitionOut, dependencies=[Depends(require_any(*DESIGNER_ANY))])
def get_definition(definition_id: str, db: Db, user: Current) -> ReportDefinitionOut:
    return _definition_out(db, _get_visible(db, user, definition_id), user)


@router.put("/definitions/{definition_id}", response_model=ReportDefinitionOut, dependencies=[Depends(require("report-builder:update"))])
def update_definition(definition_id: str, payload: ReportDefinitionIn, request: Request, db: Db, user: Current) -> ReportDefinitionOut:
    record = _get_visible(db, user, definition_id)
    if not store.can_edit(record, user):
        raise HTTPException(403, "You can see this report but not redesign it. Ask its owner for edit access.")
    try:
        design = engine.validate_definition(db, _design(payload), user.organization_id)
        record = store.update_definition(db, record, design, user)
    except engine.ReportError as error:
        db.rollback()
        raise _perform(error) from error
    _audit(db, user, "report_update", record, f"Saved report “{record.name}” as version {record.version}", request)
    db.commit()
    return _definition_out(db, record, user)


@router.delete("/definitions/{definition_id}", status_code=204, dependencies=[Depends(require("report-builder:delete"))])
def delete_definition(definition_id: str, request: Request, db: Db, user: Current) -> None:
    record = _get_visible(db, user, definition_id)
    if not store.can_delete(record, user):
        raise HTTPException(403, "Only the person who created this report can delete it.")
    _audit(db, user, "report_delete", record, f"Deleted report “{record.name}”", request)
    db.delete(record)
    db.commit()


@router.post("/definitions/{definition_id}/duplicate", response_model=ReportDefinitionOut, status_code=201, dependencies=[Depends(require("report-builder:create"))])
def duplicate_definition(definition_id: str, request: Request, db: Db, user: Current) -> ReportDefinitionOut:
    record = _get_visible(db, user, definition_id)
    copy = store.duplicate_definition(db, record, user)
    _audit(db, user, "report_duplicate", copy, f"Copied “{record.name}” into “{copy.name}”", request)
    db.commit()
    return _definition_out(db, copy, user)


@router.post("/definitions/{definition_id}/publish", response_model=ReportDefinitionOut, dependencies=[Depends(require("report-builder:publish"))])
def publish(definition_id: str, payload: ReportPublishIn, request: Request, db: Db, user: Current) -> ReportDefinitionOut:
    record = _get_visible(db, user, definition_id)
    if not store.can_publish(record, user):
        raise HTTPException(403, "Publishing needs report-builder:publish.")
    try:
        record = store.publish(db, record, user, published=payload.published)
    except engine.ReportError as error:
        db.rollback()
        raise _perform(error) from error
    _audit(
        db, user, "report_publish" if payload.published else "report_unpublish", record,
        f"{'Published' if payload.published else 'Unpublished'} “{record.name}”", request,
    )
    db.commit()
    return _definition_out(db, record, user)


@router.get("/definitions/{definition_id}/versions", response_model=list[ReportVersionOut], dependencies=[Depends(require_any(*DESIGNER_ANY))])
def list_versions(definition_id: str, db: Db, user: Current) -> list[ReportVersionOut]:
    record = _get_visible(db, user, definition_id)
    return [
        ReportVersionOut(
            id=version.id, version=version.version, report_name=version.report_name,
            report_type=version.report_type, source_table=version.source_table,
            column_count=version.column_count, filter_count=version.filter_count,
            grouping_count=version.grouping_count, grant_count=version.grant_count,
            status=version.status, change_note=version.change_note,
            changed_by_display=version.changed_by_display, created_at=version.created_at,
        )
        for version in store.versions(db, record)
    ]


@router.get("/definitions/{definition_id}/versions/{version_id}", response_model=ReportVersionDetail, dependencies=[Depends(require_any(*DESIGNER_ANY))])
def version_detail(definition_id: str, version_id: str, db: Db, user: Current) -> ReportVersionDetail:
    record = _get_visible(db, user, definition_id)
    row = db.get(ReportDefinitionVersion, version_id)
    if row is None or row.definition_id != record.id:
        raise HTTPException(404, "That version is not part of this report.")
    import json

    design: dict[str, Any] | None = None
    try:
        design = json.loads(row.design_snapshot) if row.design_snapshot else None
    except json.JSONDecodeError:
        design = None
    return ReportVersionDetail(
        version=ReportVersionOut(
            id=row.id, version=row.version, report_name=row.report_name, report_type=row.report_type,
            source_table=row.source_table, column_count=row.column_count, filter_count=row.filter_count,
            grouping_count=row.grouping_count, grant_count=row.grant_count, status=row.status,
            change_note=row.change_note, changed_by_display=row.changed_by_display, created_at=row.created_at,
        ),
        design=design,
    )


@router.post("/definitions/{definition_id}/run", response_model=ReportRunOut, dependencies=[Depends(require_any(*DESIGNER_ANY))])
def run_definition(definition_id: str, payload: ReportRunIn, request: Request, db: Db, user: Current) -> ReportRunOut:
    record = _get_visible(db, user, definition_id)
    if not _can_run_design(record, user):
        raise HTTPException(403, "You can see this report but not run it.")
    try:
        design = engine.validate_definition(db, engine.definition_from_record(record), user.organization_id)
        result = engine.run_report(db, design, _run_payload(payload), user.organization_id)
    except engine.ReportError as error:
        raise _perform(error) from error
    store.record_run(db, record)
    _audit(db, user, "report_run", record, f"Ran “{record.name}” ({result['total_rows']:,} rows)", request)
    db.commit()
    return ReportRunOut(**result)


# ---------------------------------------------------------------------------
# Custom Reports (published, shared)
# ---------------------------------------------------------------------------


@router.get("/my-reports", response_model=ReportDefinitionList, dependencies=[Depends(require("custom-reports:read"))])
def my_reports(db: Db, user: Current) -> ReportDefinitionList:
    rows = store.published_reports(db, user.organization_id, user)
    return ReportDefinitionList(
        items=[_definition_out(db, record, user) for record in rows],
        counts={"all": len(rows), "mine": sum(1 for record in rows if store.is_creator(record, user))},
    )


def _get_runnable(db: Db, user: Current, definition_id: str) -> ReportDefinition:
    record = db.get(ReportDefinition, definition_id)
    if record is None or record.organization_id != user.organization_id or not store.can_run_published(record, user):
        raise HTTPException(404, "That report is not published for you. Ask its designer to share it.")
    return record


@router.get("/my-reports/{definition_id}", response_model=ReportDefinitionOut, dependencies=[Depends(require("custom-reports:read"))])
def get_my_report(definition_id: str, db: Db, user: Current) -> ReportDefinitionOut:
    return _definition_out(db, _get_runnable(db, user, definition_id), user)


@router.post("/my-reports/{definition_id}/run", response_model=ReportRunOut, dependencies=[Depends(require("custom-reports:read"))])
def run_my_report(definition_id: str, payload: ReportRunIn, request: Request, db: Db, user: Current) -> ReportRunOut:
    record = _get_runnable(db, user, definition_id)
    try:
        design = engine.validate_definition(db, engine.definition_from_record(record), user.organization_id)
        result = engine.run_report(db, design, _run_payload(payload), user.organization_id)
    except engine.ReportError as error:
        raise _perform(error) from error
    store.record_run(db, record)
    _audit(db, user, "report_run", record, f"Ran published report “{record.name}” ({result['total_rows']:,} rows)", request)
    db.commit()
    return ReportRunOut(**result)


@router.get("/my-reports/{definition_id}/export.csv", dependencies=[Depends(require("custom-reports:export"))])
def export_csv(
    definition_id: str,
    request: Request,
    db: Db,
    user: Current,
    date_from: str = Query(default="", max_length=10),
    date_to: str = Query(default="", max_length=10),
    search: str = Query(default="", max_length=120),
    filters: str = Query(default="{}", max_length=4000),
) -> Response:
    """Every matching row, server-generated, with the same rules as the screen."""
    import json

    record = _get_runnable(db, user, definition_id)
    try:
        answers = json.loads(filters or "{}")
        if not isinstance(answers, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(422, "The filter answers could not be read. Reload the report and try again.")
    try:
        design = engine.validate_definition(db, engine.definition_from_record(record), user.organization_id)
        result = engine.run_report(
            db, design,
            {
                "date_from": date_from, "date_to": date_to, "filters": answers,
                "search": search, "all_rows": True, "page": 1, "page_size": engine.MAX_PAGE_SIZE,
            },
            user.organization_id,
        )
    except engine.ReportError as error:
        raise _perform(error) from error
    if result["total_rows"] > engine.EXPORT_CAP:
        raise HTTPException(
            422,
            f"This report matches {result['total_rows']:,} rows, above the {engine.EXPORT_CAP:,}-row download limit. "
            "Narrow the date range or filters.",
        )
    payload = engine.export_csv(design, result, record.name)
    store.record_run(db, record)
    _audit(db, user, "report_export", record, f"Exported “{record.name}” as CSV ({result['total_rows']:,} rows)", request)
    db.commit()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    safe = "".join(character if character.isalnum() or character in "-_ " else "-" for character in record.name).strip() or "report"
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe.replace(" ", "-")}_{stamp}.csv"'},
    )


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("custom-reports:export"))])
def export_audit(payload: ReportExportAuditIn, request: Request, db: Db, user: Current) -> None:
    """Record a client-side XLSX/PDF export of a report result."""
    if payload.report_id:
        record = db.get(ReportDefinition, payload.report_id)
        if record is None or record.organization_id != user.organization_id or not store.can_view(record, user):
            raise HTTPException(404, "That report is not available to you.")
    entity_id = payload.report_id or None
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="report_export",
        entity_type="report_builder", entity_id=entity_id, entity_label=payload.report_name[:160],
        summary=f"Exported “{payload.report_name}” as {payload.format.upper()} ({payload.row_count:,} rows)",
        request=request,
    )
    db.commit()
    return None
