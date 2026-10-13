"""Other Management → Database Browser: read-only, tenant-scoped table catalogue, structure and data.

Every endpoint is gated by ``database-browser:read``; downloads and export audit entries
need ``database-browser:export``. Exports are written to the audit trail, and a full
download is audited in the same request that produces it.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import SQLAlchemyError
from app.api.deps import Current, Db, require
from app.schemas.database_browser import ColumnInfo, DatabaseExportAudit, IndexInfo, TableCatalogue, TableRows, TableStructure, TableSummary
from app.services import audit
from app.services.database_browser import (
    PREVIEW_ROW_LIMIT,
    BrowsableTable,
    DatabaseBrowserError,
    browsable_tables,
    column_kind,
    count_rows,
    export_csv,
    get_browsable,
    is_hidden_column,
    preview_rows,
    reflect,
)

router = APIRouter(tags=["Other Management"], prefix="/database-browser")
log = logging.getLogger("app.database_browser")


def _fail(error: DatabaseBrowserError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


def _database_failure(error: SQLAlchemyError) -> HTTPException:
    # The statement text is logged server-side only; the browser gets a readable message.
    log.exception("Database Browser query failed")
    return HTTPException(status_code=503, detail="The database could not be read. Retry, and contact the administrator if it continues.")


def _summary(db: Db, bt: BrowsableTable, organization_id: str) -> TableSummary:
    return TableSummary(
        name=bt.name,
        group=bt.group,
        column_count=len(bt.visible_columns),
        row_count=count_rows(db, bt, organization_id),
        scope=bt.scope_label,
        primary_key=bt.primary_key,
        has_timestamps="created_at" in bt.table.c and not is_hidden_column("created_at"),
    )


@router.get("/tables", response_model=TableCatalogue, dependencies=[Depends(require("database-browser:read"))])
def list_tables(db: Db, user: Current) -> TableCatalogue:
    """Every table in the database that belongs to the caller's workspace, with row counts."""
    engine = db.get_bind()
    try:
        tables = browsable_tables(engine)
        total_tables_in_database = len(reflect(engine).tables)
        items = [_summary(db, tables[name], user.organization_id) for name in sorted(tables)]
    except SQLAlchemyError as error:
        raise _database_failure(error) from error
    return TableCatalogue(
        items=items,
        total_tables=len(items),
        total_rows=sum(item.row_count for item in items),
        excluded_tables=total_tables_in_database - len(items),
        hidden_columns=sum(len(bt.table.columns) - len(bt.visible_columns) for bt in tables.values()),
    )


@router.get("/tables/{table_name}/structure", response_model=TableStructure, dependencies=[Depends(require("database-browser:read"))])
def table_structure(table_name: str, db: Db, user: Current) -> TableStructure:
    """Columns, types, keys and indexes of one table, as stored in the database."""
    try:
        bt = get_browsable(db.get_bind(), table_name)
        table = bt.table
        visible = {column.name for column in bt.visible_columns}
        unique_constraints = [constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint)]
        unique_columns = {list(constraint.columns)[0].name for constraint in unique_constraints if len(constraint.columns) == 1}
        indexed_columns = {column.name for index in table.indexes for column in index.columns}
        foreign_keys = {}
        for constraint in table.foreign_key_constraints:
            if len(constraint.columns) == 1:
                parent = list(constraint.columns)[0]
                reference = list(constraint.elements)[0].column
                foreign_keys[parent.name] = f"{reference.table.name}.{reference.name}"
        columns = []
        for position, column in enumerate(bt.visible_columns, start=1):
            length = getattr(column.type, "length", None)
            columns.append(ColumnInfo(
                position=position,
                name=column.name,
                data_type=column.type.compile(dialect=db.get_bind().dialect),
                kind=column_kind(column),
                nullable=bool(column.nullable),
                primary_key=column.primary_key,
                unique=column.name in unique_columns or (column.unique is True),
                indexed=column.name in indexed_columns or column.primary_key or column.index is True,
                foreign_key=foreign_keys.get(column.name, ""),
                default="" if column.server_default is None else str(column.server_default.arg),
                max_length=int(length) if length else None,
            ))
        indexes: list[IndexInfo] = []
        seen_names: set[str] = set()
        for index in list(table.indexes) + unique_constraints:
            names = [column.name for column in index.columns]
            if not names or any(name not in visible for name in names) or index.name in seen_names:
                continue
            seen_names.add(index.name or ",".join(names))
            unique = isinstance(index, UniqueConstraint) or bool(getattr(index, "unique", False))
            indexes.append(IndexInfo(name=index.name or f"unique ({', '.join(names)})", columns=", ".join(names), unique=unique))
        row_count = count_rows(db, bt, user.organization_id)
    except DatabaseBrowserError as error:
        raise _fail(error) from error
    except SQLAlchemyError as error:
        raise _database_failure(error) from error
    return TableStructure(
        name=bt.name,
        group=bt.group,
        scope=bt.scope_label,
        row_count=row_count,
        columns=columns,
        indexes=indexes,
        hidden_columns=len(table.columns) - len(visible),
    )


@router.get("/tables/{table_name}/rows", response_model=TableRows, dependencies=[Depends(require("database-browser:read"))])
def table_rows(table_name: str, db: Db, user: Current, limit: int = Query(PREVIEW_ROW_LIMIT, ge=1, le=PREVIEW_ROW_LIMIT)) -> TableRows:
    """The newest rows of one table in this workspace, capped for the on-screen grid.

    Full data is available through the CSV download, which streams every row.
    """
    try:
        bt = get_browsable(db.get_bind(), table_name)
        items, total = preview_rows(db, bt, user.organization_id, limit)
    except DatabaseBrowserError as error:
        raise _fail(error) from error
    except SQLAlchemyError as error:
        raise _database_failure(error) from error
    return TableRows(
        name=bt.name,
        columns=[column.name for column in bt.visible_columns],
        primary_key=bt.primary_key,
        items=items,
        shown=len(items),
        total=total,
        truncated=total > len(items),
        preview_limit=PREVIEW_ROW_LIMIT,
    )


@router.get("/tables/{table_name}/download.csv", dependencies=[Depends(require("database-browser:export"))])
def download_table(table_name: str, request: Request, db: Db, user: Current) -> StreamingResponse:
    """Every row of one table in this workspace as UTF-8 CSV, for Power BI and other tools."""
    try:
        bt = get_browsable(db.get_bind(), table_name)
        buffer, total = export_csv(db, bt, user.organization_id)
    except DatabaseBrowserError as error:
        raise _fail(error) from error
    except SQLAlchemyError as error:
        raise _database_failure(error) from error
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="export",
        entity_type="database_browser",
        entity_label=bt.name,
        summary=f"Downloaded full table {bt.name} as CSV ({total:,} rows)",
        request=request,
    )
    db.commit()

    def chunks():
        try:
            while True:
                block = buffer.read(1024 * 1024)
                if not block:
                    break
                yield block
        finally:
            buffer.close()

    filename = f"{bt.name}.csv"
    return StreamingResponse(chunks(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("database-browser:export"))])
def audit_export(data: DatabaseExportAudit, request: Request, db: Db, user: Current) -> None:
    """Record a client-side CSV, XLSX or PDF export of the browser grid, structure or catalogue."""
    if data.scope == "catalogue":
        label = "Table catalogue"
    else:
        if not data.table:
            raise HTTPException(status_code=422, detail="Choose a table to export")
        try:
            label = get_browsable(db.get_bind(), data.table).name
        except DatabaseBrowserError as error:
            raise _fail(error) from error
        except SQLAlchemyError as error:
            raise _database_failure(error) from error
    noun = {"rows": "row", "structure": "column", "catalogue": "table"}[data.scope]
    noun = noun if data.record_count == 1 else f"{noun}s"
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="export",
        entity_type="database_browser",
        entity_label=label,
        summary=f"Exported {data.record_count:,} {noun} of {label} as {data.format.upper()} ({data.scope})",
        request=request,
    )
    db.commit()
    return None
