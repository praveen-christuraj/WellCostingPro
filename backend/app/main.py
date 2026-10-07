from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, rbac
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[s.strip() for s in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.include_router(auth.router, prefix="/api/v1")
app.include_router(rbac.router, prefix="/api/v1")


@app.get("/api/health")
def health():
    return {"status": "ok"}
