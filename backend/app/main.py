import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import afe, auth, audit, backup, business_dashboard, costing_sets, daily_cost, database_browser, fuel_cost, lih_cost, master_data, mud_cost, ndt_inspection, rbac, report_builder, rig_well, security, service_master, sow_adjustment, usage_reports, vendor_master
from app.api.catalogue_items import ITEM_ROUTERS, catalogue_error_handler
from app.api.catalogue_options import router as catalogue_options_router
from app.bootstrap import bootstrap_admin
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services import backup as backup_service
from app.services.catalogue import CatalogueError

log = logging.getLogger("app")
settings = get_settings()
configure_logging()

# Bumped when the API surface changes in a way a browser tab could notice; the
# health probe and the error messages quote it so a stale deployment is obvious.
API_VERSION = "0.3.0"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Writes that authenticate with the refresh cookie are the only ones a cross-site
# request could ride on; every other write needs a bearer token the browser does
# not attach automatically.
COOKIE_WRITE_PREFIX = "/api/v1/auth/"
MAX_JSON_BODY = settings.max_json_body_mb * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    """On a new device the database is empty, so offer to create the first administrator."""
    log.info("Starting %s in %s mode; settings %s", settings.app_name, settings.environment, settings.safe_summary())
    if settings.is_production and settings.bootstrap_admin_on_startup and not settings.seed_admin_email:
        log.warning("Bootstrap is enabled in production; remove SEED_ADMIN_PASSWORD after the first start")
    result = bootstrap_admin()
    (log.warning if result.needs_attention else log.info)(result.message)
    # The backup scheduler is process-local and only acts when a workspace has
    # enabled a schedule; in-process workers are single-instance by design.
    if backup_service.start_scheduler():
        log.info("Backup scheduler started")
    yield


app = FastAPI(
    title=settings.app_name,
    description=settings.app_tagline,
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    expose_headers=["Retry-After"],
    max_age=600,
)


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    """Reject cross-site writes that rely on the browser's refresh cookie.

    SameSite=Lax already blocks most cross-site form posts, but it is a browser
    default rather than an authorisation decision. Any request that carries an
    ``Origin`` (or, failing that, a ``Referer``) must match the configured
    front-end origin exactly. Non-browser clients that send neither header — CLI
    and integration callers — keep working.
    """
    if request.method not in SAFE_METHODS and request.url.path.startswith(COOKIE_WRITE_PREFIX):
        allowed = set(settings.cors_origin_list)
        site = (request.headers.get("sec-fetch-site") or "").lower()
        if site == "cross-site":
            return JSONResponse(status_code=403, content={"detail": "Cross-site requests are not accepted."})
        origin = request.headers.get("origin")
        if origin and origin not in allowed:
            return JSONResponse(status_code=403, content={"detail": "This origin is not allowed to call the API."})
        if not origin:
            referer = request.headers.get("referer")
            if referer:
                parts = urlsplit(referer)
                candidate = f"{parts.scheme}://{parts.netloc}"
                if candidate not in allowed:
                    return JSONResponse(status_code=403, content={"detail": "This origin is not allowed to call the API."})
    return await call_next(request)


@app.middleware("http")
async def body_size_guard(request: Request, call_next):
    """Refuse oversized JSON bodies before a parser allocates them.

    Multipart uploads have their own bounded readers (documents, backup archives)
    because their size limit depends on the feature.
    """
    if request.method not in SAFE_METHODS:
        content_type = request.headers.get("content-type", "").lower()
        if not content_type.startswith("multipart/"):
            try:
                length = int(request.headers.get("content-length") or 0)
            except ValueError:
                length = 0
            if length > MAX_JSON_BODY:
                return JSONResponse(status_code=413, content={"detail": "The request body is too large."})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Apply browser hardening headers and forbid caching of API payloads."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if settings.secure_cookies:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(auth.router, prefix="/api/v1")
app.include_router(security.router, prefix="/api/v1")
app.include_router(business_dashboard.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(database_browser.router, prefix="/api/v1")
app.include_router(backup.router, prefix="/api/v1")
app.include_router(report_builder.router, prefix="/api/v1")
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


@app.get("/", include_in_schema=False)
def api_root():
    """A browser that lands on the API host gets directions, not a bare "Not Found"."""
    return {
        "application": settings.app_name,
        "message": f"{settings.app_name} serves the API on this host. Open the web application to sign in.",
        "api": "/api/v1",
        "health": "/api/health",
        "version": API_VERSION,
    }


@app.get("/api/health")
def health():
    """Liveness and version only.

    Deliberately says nothing about whether an administrator exists: that fact
    tells an unauthenticated caller whether a deployment is still unclaimed. The
    first-run guidance lives in the deployment documentation.
    """
    return {"status": "ok", "api_version": API_VERSION}


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


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    """Describe a rejected field without echoing the value that was sent.

    FastAPI's default body includes the rejected ``input`` — which, for a login or
    password form, is the password itself. The browser only needs the location,
    rule and message, so the raw value is removed here.
    """
    details = []
    for item in error.errors():
        clean = {key: value for key, value in item.items() if key not in {"input", "url"}}
        context = clean.get("ctx")
        if isinstance(context, dict):
            clean["ctx"] = {key: value if isinstance(value, (str, int, float, bool)) else str(value) for key, value in context.items()}
        details.append(clean)
    return JSONResponse(status_code=422, content={"detail": details})


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, error: IntegrityError) -> JSONResponse:
    """Map a database uniqueness/foreign-key conflict to a generic 409.

    The driver message names columns, values and sometimes the statement, so it is
    never returned to the caller. The database remains the final guard against
    concurrent inserts that both passed an in-application existence check.
    """
    log.warning("Database conflict on %s", getattr(getattr(request, "url", None), "path", "unknown"))
    return JSONResponse(
        status_code=409,
        content={"detail": "This change conflicts with a record that already exists. Refresh the page and try again."},
    )


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
