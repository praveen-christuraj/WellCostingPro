"""Routes for the priced catalogue types (tangibles, drill bits, mud chemicals,
cement additives, fuel). One router factory serves all five so behaviour stays
identical; the per-type differences live in ``app/services/catalogue_specs.py``.

Route order matters: literal paths (``/overview``, ``/deleted``, ``/revisions``,
``/import``, ``/bulk-*``) are declared before ``/{item_id}``.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Current, Db, require
from app.schemas.catalogue import PricedItemOverview, RateRevisionOut
from app.schemas.master_data import MasterDataBulkActionResponse, MasterDataIDs, MasterDataImportRequest, MasterDataImportResponse
from app.services import catalogue as svc
from app.services.catalogue import CatalogueError, PricedSpec
from app.services.catalogue_specs import PRICED_SPECS


async def catalogue_error_handler(_request: Request, error: CatalogueError) -> JSONResponse:
    """Turn a rule violation into a 4xx response whose ``detail`` is shown next to the field."""
    return JSONResponse(status_code=error.status_code, content={"detail": error.message})


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This change conflicts with an existing record") from error


def _item_or_404(db: Session, spec: PricedSpec, organization_id: str, item_id: str, *, deleted: bool | None) -> Any:
    item = db.scalar(select(spec.model).where(spec.model.id == item_id, spec.model.organization_id == organization_id))
    if item is None or (deleted is not None and item.is_deleted != deleted):
        label = "deleted " if deleted else ""
        raise HTTPException(status_code=404, detail=f"{spec.item_type} not found in {label}records")
    return item


def _items_for_ids(db: Session, spec: PricedSpec, organization_id: str, ids: list[str], *, deleted: bool) -> list[Any]:
    return list(
        db.scalars(
            select(spec.model).where(
                spec.model.id.in_(ids),
                spec.model.organization_id == organization_id,
                spec.model.is_deleted.is_(deleted),
            )
        ).all()
    )


def build_item_router(spec: PricedSpec) -> APIRouter:
    router = APIRouter(prefix=f"/master-data/{spec.key}", tags=[f"Master Data Management · {spec.label}"])
    read = Depends(require("master-data:read"))

    def out_list(db: Session, organization_id: str, items: list[Any]) -> list[Any]:
        options = svc.options_by_id(db, organization_id)
        return [svc.item_out(spec, item, options) for item in items]

    def load_out(db: Session, organization_id: str, item: Any) -> Any:
        return svc.item_out(spec, item, svc.options_by_id(db, organization_id))

    # ----- reads (literal paths first) -----

    @router.get("", dependencies=[read])
    def list_active(db: Db, user: Current) -> list[Any]:
        if spec.seed is not None:
            spec.seed(db, user.organization_id)
        return out_list(db, user.organization_id, svc.list_items(db, spec, user.organization_id, deleted=False))

    @router.get("/overview", response_model=PricedItemOverview, dependencies=[read])
    def overview(db: Db, user: Current) -> PricedItemOverview:
        if spec.seed is not None:
            spec.seed(db, user.organization_id)
        return svc.item_overview(db, spec, user.organization_id)

    @router.get("/revisions", response_model=list[RateRevisionOut], dependencies=[read])
    def all_revisions(db: Db, user: Current, include_removed: bool = False) -> list[RateRevisionOut]:
        return svc.revision_history(db, spec, user.organization_id, include_removed=include_removed)

    if spec.lifecycle:

        @router.get("/deleted", dependencies=[read])
        def list_deleted(db: Db, user: Current) -> list[Any]:
            return out_list(db, user.organization_id, svc.list_items(db, spec, user.organization_id, deleted=True))

    @router.get("/{item_id}", dependencies=[read])
    def get_item(item_id: str, db: Db, user: Current) -> Any:
        item = _item_or_404(db, spec, user.organization_id, item_id, deleted=None)
        return load_out(db, user.organization_id, item)

    @router.get("/{item_id}/revisions", response_model=list[RateRevisionOut], dependencies=[read])
    def item_revisions(item_id: str, db: Db, user: Current) -> list[RateRevisionOut]:
        _item_or_404(db, spec, user.organization_id, item_id, deleted=None)
        return svc.revision_history(db, spec, user.organization_id, item_id, include_removed=True)

    # ----- writes -----

    if spec.lifecycle and spec.create_model is not None:

        @router.post("", status_code=201, dependencies=[Depends(require("master-data:create"))])
        def create(data: spec.create_model, request: Request, db: Db, user: Current) -> Any:
            item = svc.create_item(db, spec, user.organization_id, user, data.model_dump(), request)
            _commit(db)
            db.refresh(item)
            return load_out(db, user.organization_id, item)

        @router.post("/import", response_model=MasterDataImportResponse, dependencies=[Depends(require("master-data:import"))])
        def import_items(data: MasterDataImportRequest, request: Request, db: Db, user: Current) -> MasterDataImportResponse:
            imported, errors, _created = svc.import_rows(db, spec, user.organization_id, user, data.rows, request)
            _commit(db)
            return MasterDataImportResponse(
                imported_count=imported,
                error_count=len(errors),
                errors=errors[:100],
                success=not errors,
            )

        @router.post("/bulk-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:delete"))])
        def bulk_delete(data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
            items = _items_for_ids(db, spec, user.organization_id, data.ids, deleted=False)
            for item in items:
                svc.soft_delete_item(db, spec, user.organization_id, user, item, request, bulk=True)
            _commit(db)
            return MasterDataBulkActionResponse(affected_count=len(items))

        @router.post("/bulk-restore", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:restore"))])
        def bulk_restore(data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
            items = _items_for_ids(db, spec, user.organization_id, data.ids, deleted=True)
            for item in items:
                svc.restore_item(db, spec, user.organization_id, user, item, request, bulk=True)
            _commit(db)
            return MasterDataBulkActionResponse(affected_count=len(items))

        @router.post("/bulk-permanent-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:permanent-delete"))])
        def bulk_purge(data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
            items = _items_for_ids(db, spec, user.organization_id, data.ids, deleted=True)
            for item in items:
                svc.purge_item(db, spec, user.organization_id, user, item, request, bulk=True)
            _commit(db)
            return MasterDataBulkActionResponse(affected_count=len(items))

        @router.patch("/{item_id}", dependencies=[Depends(require("master-data:update"))])
        def update(item_id: str, data: spec.update_model, request: Request, db: Db, user: Current) -> Any:
            payload = data.model_dump(exclude_unset=True)
            if not payload:
                raise HTTPException(status_code=422, detail="Change at least one field before saving")
            item = _item_or_404(db, spec, user.organization_id, item_id, deleted=False)
            svc.update_item(db, spec, user.organization_id, user, item, payload, request)
            _commit(db)
            db.refresh(item)
            return load_out(db, user.organization_id, item)

        @router.delete("/{item_id}", dependencies=[Depends(require("master-data:delete"))])
        def soft_delete(item_id: str, request: Request, db: Db, user: Current) -> Any:
            item = _item_or_404(db, spec, user.organization_id, item_id, deleted=False)
            svc.soft_delete_item(db, spec, user.organization_id, user, item, request)
            _commit(db)
            db.refresh(item)
            return load_out(db, user.organization_id, item)

        @router.post("/{item_id}/restore", dependencies=[Depends(require("master-data:restore"))])
        def restore(item_id: str, request: Request, db: Db, user: Current) -> Any:
            item = _item_or_404(db, spec, user.organization_id, item_id, deleted=True)
            svc.restore_item(db, spec, user.organization_id, user, item, request)
            _commit(db)
            db.refresh(item)
            return load_out(db, user.organization_id, item)

        @router.delete("/{item_id}/permanent", status_code=204, dependencies=[Depends(require("master-data:permanent-delete"))])
        def purge(item_id: str, request: Request, db: Db, user: Current) -> Response:
            item = _item_or_404(db, spec, user.organization_id, item_id, deleted=True)
            svc.purge_item(db, spec, user.organization_id, user, item, request)
            _commit(db)
            return Response(status_code=204)

    if spec.revise_model is not None:

        @router.post("/{item_id}/revise", dependencies=[Depends(require("master-data:update"))])
        def revise(item_id: str, data: spec.revise_model, request: Request, db: Db, user: Current) -> Any:
            item = _item_or_404(db, spec, user.organization_id, item_id, deleted=None if not spec.lifecycle else False)
            svc.revise_item(db, spec, user.organization_id, user, item, data.model_dump(), request)
            _commit(db)
            db.refresh(item)
            return load_out(db, user.organization_id, item)

    return router


ITEM_ROUTERS: dict[str, APIRouter] = {key: build_item_router(spec) for key, spec in PRICED_SPECS.items()}
