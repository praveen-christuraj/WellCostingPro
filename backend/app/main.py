import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.api import afe, auth, audit, business_dashboard, costing_sets, daily_cost, database_browser, fuel_cost, lih_cost, master_data, mud_cost, ndt_inspection, rbac, rig_well, security, service_master, sow_adjustment, usage_reports, vendor_master
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


# Bumped when the API surface changes in a way a browser tab could notice; the
# health probe and the error messages quote it so a stale deployment is obvious.
API_VERSION = "0.2.0"
app = FastAPI(title=settings.app_name, description=settings.app_tagline, version=API_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[s.strip() for s in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.include_router(auth.router, prefix="/api/v1")
app.include_router(security.router, prefix="/api/v1")
app.include_router(business_dashboard.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(database_browser.router, prefix="/api/v1")
app.include_router(rbac.router, prefix="/api/v1")
app.include_router(costing_sets.router, prefix="/api/v1")
# Specialized vendor, service, and PO/SO routes are registered before the generic
# /master-data/{module} routes so dynamic paths do not shadow them.
app.include_router(vendor_master.router, prefix="/api/v1")
app.include_router(service_master.router, prefix="/api/v1")
app.include_router(rig_well.router, prefix="/api/v1")
app.include_router(afe.router, prefix="/api/v1")
app.include_router(sow_adjustment.router, prefix="/api/v1")
app.include_router(daily_cost.router, prefix="/api/v1")
app.include_router(mud_cost.router, prefix="/api/v1")
app.include_router(lih_cost.router, prefix="/api/v1")
app.include_router(fuel_cost.router, prefix="/api/v1")
app.include_router(ndt_inspection.router, prefix="/api/v1")
app.include_router(usage_reports.router, prefix="/api/v1")
# Tangibles, consumables and catalogue lists are registered before the generic routes too.
app.include_router(catalogue_options_router, prefix="/api/v1")
for catalogue_router in ITEM_ROUTERS.values():
    app.include_router(catalogue_router, prefix="/api/v1")
app.add_exception_handler(CatalogueError, catalogue_error_handler)
app.include_router(master_data.router, prefix="/api/v1")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Apply browser hardening headers to API responses without changing payloads."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.secure_cookies:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/", include_in_schema=False)
def api_root():
    """A browser that lands on the API host gets directions, not a bare "Not Found"."""
    return {
        "application": settings.app_name,
        "message": f"{settings.app_name} serves the API on this host. Open the web application to sign in.",
        "api": "/api/v1",
        "health": "/api/health",
        "documentation": "/docs",
        "version": API_VERSION,
    }


@app.get("/api/health")
def health(db: Db):
    # admin_seeded lets a fresh install tell the operator that seeding is still pending.
    try:
        seeded = not provisioning.admin_missing(db)
    except Exception:  # a database problem must not turn liveness into a 500
        log.exception("Administrator check failed during health probe")
        seeded = False
    return {"status": "ok", "admin_seeded": seeded, "api_version": API_VERSION}


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    """Always answer with `{"detail": ...}` so the UI can show the message next to the data."""
    if isinstance(error.detail, dict) and "detail" in error.detail:
        detail = error.detail["detail"]
    else:
        detail = error.detail
    # FastAPI's own defaults ("Not Found", "Method Not Allowed") say nothing about
    # which call failed or why. Replace them with an actionable sentence — an
    # unmatched API path almost always means the page and the API are different
    # versions, which is exactly what a user needs to be told.
    if error.status_code == 404 and str(detail).strip().lower() == "not found":
        # Kept in the server log so an operator can see which call a browser is
        # making against a route this build does not serve.
        log.warning("Unmatched route: %s %s (API %s)", request.method, request.url.path, API_VERSION)
        detail = (
            f"The API has no {request.method} route at {request.url.path}. The page is probably newer than "
            f"the API build (API {API_VERSION}); reload after the API is updated, or report this to the administrator."
        )
    elif error.status_code == 405 and str(detail).strip().lower() == "method not allowed":
        detail = (
            f"This action ({request.method}) is not offered at {request.url.path}. The record may not "
            f"support it, or the page is newer than the API build (API {API_VERSION}). Reload the page and "
            "try again; report it if the message repeats."
        )
    elif error.status_code == 401 and str(detail).strip().lower() == "unauthorized":
        detail = "Authentication is required for this action. Sign in again to continue."
    return JSONResponse(status_code=error.status_code, content={"detail": detail})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
    """Last-resort handler.

    An unhandled failure is logged in full with a reference code and answered with a
    readable message, instead of the browser's bare "Failed to load resource … 500".
    Starlette still re-raises afterwards so the process log keeps the traceback.
    """
    reference = uuid4().hex[:12]
    log.exception("Unhandled API error [%s] on %s %s", reference, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "The server could not complete this request. The failure was recorded with "
                f"reference {reference}. Retry, and contact the administrator if it continues."
            )
        },
    )
