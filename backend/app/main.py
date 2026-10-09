import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, audit, master_data, rbac
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
