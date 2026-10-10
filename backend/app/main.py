import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, audit, master_data, rbac, service_master, vendor_master
from app.api.catalogue_items import ITEM_ROUTERS, catalogue_error_handler
from app.api.catalogue_options import router as catalogue_options_router
from app.services.catalogue import CatalogueError
from app.api.deps import Db
from app.bootstrap import bootstrap_admin
from app.core.config import get_settings
from app.services import provisioning

log = logging.getLogger("app")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """On a new device the database is empty, so offer to create the first administrator."""
    result = bootstrap_admin()
    (log.warning if result.needs_attention else log.info)(result.message)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[s.strip() for s in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.include_router(auth.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(rbac.router, prefix="/api/v1")
# Specialized vendor, service, and PO/SO routes are registered before the generic
# /master-data/{module} routes so dynamic paths do not shadow them.
app.include_router(vendor_master.router, prefix="/api/v1")
app.include_router(service_master.router, prefix="/api/v1")
# Tangibles, consumables and catalogue lists are registered before the generic routes too.
app.include_router(catalogue_options_router, prefix="/api/v1")
for catalogue_router in ITEM_ROUTERS.values():
    app.include_router(catalogue_router, prefix="/api/v1")
app.add_exception_handler(CatalogueError, catalogue_error_handler)
app.include_router(master_data.router, prefix="/api/v1")


@app.get("/api/health")
def health(db: Db):
    # admin_seeded lets a fresh install tell the operator that seeding is still pending.
    try:
        seeded = not provisioning.admin_missing(db)
    except Exception:  # a database problem must not turn liveness into a 500
        log.exception("Administrator check failed during health probe")
        seeded = False
    return {"status": "ok", "admin_seeded": seeded}
