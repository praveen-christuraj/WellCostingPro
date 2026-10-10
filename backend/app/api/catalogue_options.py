"""Catalogue Lists: the user-managed dropdown values used by tangibles and consumables.

Values are never hard-coded. A value that is in use can be removed (it is kept on
existing records and shown as removed), but cannot be permanently deleted until
no record references it.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.catalogue_items import _commit
from app.api.deps import Current, Db, require
from app.models.catalogue import CATALOGUE_LISTS, CatalogueOption
from app.schemas.catalogue import (
    CatalogueBulkCreateResult,
    CatalogueListSummary,
    CatalogueOptionBulkCreate,
    CatalogueOptionCreate,
    CatalogueOptionOut,
    CatalogueOptionUpdate,
)
from app.schemas.master_data import MasterDataBulkActionResponse, MasterDataIDs
from app.services import catalogue as svc
from app.services.catalogue import CatalogueError

router = APIRouter(prefix="/master-data/catalogue-options", tags=["Master Data Management · Catalogue Lists"])


def _option_or_404(db: Session, organization_id: str, option_id: str) -> CatalogueOption:
    option = db.scalar(
        select(CatalogueOption).where(
            CatalogueOption.id == option_id,
            CatalogueOption.organization_id == organization_id,
        )
    )
    if option is None:
        raise HTTPException(status_code=404, detail="Catalogue value not found")
    return option


def _options_out(db: Session, organization_id: str, options: list[CatalogueOption]) -> list[CatalogueOptionOut]:
    by_id = svc.options_by_id(db, organization_id)
    usage: dict[str, int] = {}
    for list_key in {option.list_key for option in options}:
        usage.update(svc.option_usage_counts(db, organization_id, list_key))
    children: dict[str, int] = {}
    for option in options:
        if option.parent_id:
            children[option.parent_id] = children.get(option.parent_id, 0) + 1
    result = []
    for option in options:
        parent = by_id.get(option.parent_id) if option.parent_id else None
        result.append(
            CatalogueOptionOut(
                id=option.id,
                list_key=option.list_key,
                list_label=svc.list_label(option.list_key),
                value=option.value,
                parent_id=option.parent_id,
                parent_value=parent.value if parent else None,
                usage_count=usage.get(option.id, 0),
                is_deleted=option.is_deleted,
                deleted_at=option.deleted_at,
                created_at=option.created_at,
                updated_at=option.updated_at,
            )
        )
    return result


@router.get("/lists", response_model=list[CatalogueListSummary], dependencies=[Depends(require("master-data:read"))])
def list_summaries(db: Db, user: Current) -> list[CatalogueListSummary]:
    options = db.scalars(select(CatalogueOption).where(CatalogueOption.organization_id == user.organization_id)).all()
    summaries = []
    for key, (label, parent_key) in CATALOGUE_LISTS.items():
        in_list = [option for option in options if option.list_key == key]
        usage = svc.option_usage_counts(db, user.organization_id, key)
        parent_label = CATALOGUE_LISTS[parent_key][0] if parent_key else None
        summaries.append(
            CatalogueListSummary(
                key=key,
                label=label,
                parent_key=parent_key,
                parent_label=parent_label,
                active_count=sum(1 for option in in_list if not option.is_deleted),
                removed_count=sum(1 for option in in_list if option.is_deleted),
                usage_count=sum(usage.values()),
            )
        )
    return summaries


@router.get("", response_model=list[CatalogueOptionOut], dependencies=[Depends(require("master-data:read"))])
def list_options(
    db: Db,
    user: Current,
    list_key: str | None = Query(default=None, max_length=40),
    parent_id: str | None = Query(default=None, max_length=36),
    deleted: bool = False,
) -> list[CatalogueOptionOut]:
    statement = select(CatalogueOption).where(
        CatalogueOption.organization_id == user.organization_id,
        CatalogueOption.is_deleted.is_(deleted),
    )
    if list_key:
        if list_key not in CATALOGUE_LISTS:
            raise HTTPException(status_code=404, detail="Unknown catalogue list")
        statement = statement.where(CatalogueOption.list_key == list_key)
    if parent_id:
        statement = statement.where(CatalogueOption.parent_id == parent_id)
    options = db.scalars(statement.order_by(CatalogueOption.list_key, CatalogueOption.value_key)).all()
    return _options_out(db, user.organization_id, list(options))


@router.post("", response_model=CatalogueOptionOut, status_code=201, dependencies=[Depends(require("master-data:create"))])
def create_option(data: CatalogueOptionCreate, request: Request, db: Db, user: Current) -> CatalogueOptionOut:
    option = svc.create_option(db, user.organization_id, data.list_key, data.value, data.parent_id, user, request)
    _commit(db)
    db.refresh(option)
    return _options_out(db, user.organization_id, [option])[0]


@router.post("/bulk", response_model=CatalogueBulkCreateResult, status_code=201, dependencies=[Depends(require("master-data:create"))])
def bulk_create_options(data: CatalogueOptionBulkCreate, request: Request, db: Db, user: Current) -> CatalogueBulkCreateResult:
    """Add many values at once (one per line). Duplicates are skipped and reported, not fatal."""
    created = 0
    skipped: list[str] = []
    seen: set[str] = set()
    for raw in data.values:
        value = " ".join(raw.split())
        if not value:
            continue
        if value.casefold() in seen:
            skipped.append(f"{value} (repeated in your list)")
            continue
        seen.add(value.casefold())
        try:
            with db.begin_nested():
                svc.create_option(db, user.organization_id, data.list_key, value, data.parent_id, user, request)
            created += 1
        except CatalogueError as error:
            skipped.append(f"{value} ({error.message})")
    _commit(db)
    return CatalogueBulkCreateResult(created_count=created, skipped=skipped)


@router.patch("/{option_id}", response_model=CatalogueOptionOut, dependencies=[Depends(require("master-data:update"))])
def rename_option(option_id: str, data: CatalogueOptionUpdate, request: Request, db: Db, user: Current) -> CatalogueOptionOut:
    option = _option_or_404(db, user.organization_id, option_id)
    if option.is_deleted:
        raise HTTPException(status_code=409, detail="Restore this value before renaming it")
    svc.rename_option(db, user.organization_id, option, data.value, user, request)
    _commit(db)
    db.refresh(option)
    return _options_out(db, user.organization_id, [option])[0]


@router.delete("/{option_id}", response_model=CatalogueOptionOut, dependencies=[Depends(require("master-data:delete"))])
def remove_option(option_id: str, request: Request, db: Db, user: Current) -> CatalogueOptionOut:
    option = _option_or_404(db, user.organization_id, option_id)
    svc.remove_option(db, user.organization_id, option, user, request)
    _commit(db)
    db.refresh(option)
    return _options_out(db, user.organization_id, [option])[0]


@router.post("/{option_id}/restore", response_model=CatalogueOptionOut, dependencies=[Depends(require("master-data:restore"))])
def restore_option(option_id: str, request: Request, db: Db, user: Current) -> CatalogueOptionOut:
    option = _option_or_404(db, user.organization_id, option_id)
    svc.restore_option(db, user.organization_id, option, user, request)
    _commit(db)
    db.refresh(option)
    return _options_out(db, user.organization_id, [option])[0]


@router.delete("/{option_id}/permanent", status_code=204, dependencies=[Depends(require("master-data:permanent-delete"))])
def purge_option(option_id: str, request: Request, db: Db, user: Current) -> None:
    option = _option_or_404(db, user.organization_id, option_id)
    svc.purge_option(db, user.organization_id, option, user, request)
    _commit(db)


def _options_for_ids(db: Session, organization_id: str, ids: list[str], *, deleted: bool) -> list[CatalogueOption]:
    return list(
        db.scalars(
            select(CatalogueOption).where(
                CatalogueOption.id.in_(ids),
                CatalogueOption.organization_id == organization_id,
                CatalogueOption.is_deleted.is_(deleted),
            )
        ).all()
    )


@router.post("/bulk-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:delete"))])
def bulk_remove(data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
    options = _options_for_ids(db, user.organization_id, data.ids, deleted=False)
    for option in options:
        svc.remove_option(db, user.organization_id, option, user, request)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(options))


@router.post("/bulk-restore", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:restore"))])
def bulk_restore_options(data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
    options = _options_for_ids(db, user.organization_id, data.ids, deleted=True)
    for option in options:
        svc.restore_option(db, user.organization_id, option, user, request)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(options))


@router.post("/bulk-permanent-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:permanent-delete"))])
def bulk_purge_options(data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
    options = _options_for_ids(db, user.organization_id, data.ids, deleted=True)
    for option in options:
        svc.purge_option(db, user.organization_id, option, user, request)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(options))
