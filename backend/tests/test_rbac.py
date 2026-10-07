import os
import tempfile

# Set the database before importing app modules (engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.core.database import Base, engine, SessionLocal
from app.main import app
from app.models import Organization, User, Role, Permission
from app.core.security import hash_password


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for slug in ("north", "south"):
            org = Organization(slug=slug, name=f"{slug.title()} Energy")
            db.add(org)
            db.flush()
            keys = ["users:read", "users:create", "users:update", "roles:read", "roles:create", "roles:update", "roles:delete", "permissions:read", "permissions:create", "permissions:update", "permissions:delete", "assignments:write"]
            permissions = [Permission(organization_id=org.id, key=key, description=key) for key in keys]
            owner = Role(organization_id=org.id, name="Owner", is_owner=True, permissions=permissions)
            db.add(User(organization_id=org.id, email="owner@example.com", full_name="Test Owner", password_hash=hash_password("correct-password-123"), roles=[owner]))
        db.commit()
    yield


def login(client, org="north", password="correct-password-123"):
    response = client.post("/api/v1/auth/login", json={"organization": org, "email": "owner@example.com", "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_refresh_logout_and_password_change():
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={"organization": "north", "email": "owner@example.com", "password": "wrong"}).status_code == 401
        headers = login(client)
        assert client.get("/api/v1/auth/me", headers=headers).json()["organization_slug"] == "north"
        old_cookie = client.cookies.get("refresh_token")
        assert client.post("/api/v1/auth/refresh").status_code == 200
        client.cookies.set("refresh_token", old_cookie, path="/api/v1/auth")
        assert client.post("/api/v1/auth/refresh").status_code == 401
        headers = login(client)
        assert client.post("/api/v1/auth/change-password", headers=headers, json={"current_password": "correct-password-123", "new_password": "another-password-456"}).status_code == 204
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        assert client.post("/api/v1/auth/login", json={"organization": "north", "email": "owner@example.com", "password": "correct-password-123"}).status_code == 401
        headers = login(client, password="another-password-456")
        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.post("/api/v1/auth/refresh").status_code == 401
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200  # access valid until expiry


def test_crud_assignments_permissions_and_tenant_isolation():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")
        create = client.post("/api/v1/roles", headers=north, json={"name": "Analyst", "description": "Cost analyst"})
        assert create.status_code == 201, create.text
        role_id = create.json()["id"]
        p = client.post("/api/v1/permissions", headers=north, json={"key": "reports:export", "description": "Export reports"})
        assert p.status_code == 201, p.text
        pid = p.json()["id"]
        assert client.put(f"/api/v1/roles/{role_id}/permissions", headers=north, json={"ids": [pid]}).status_code == 200
        user = client.post("/api/v1/users", headers=north, json={"email": "analyst@example.com", "full_name": "Cost Analyst", "password": "analyst-secret-123", "role_ids": [role_id]})
        assert user.status_code == 201, user.text
        user_id = user.json()["id"]
        assert client.get("/api/v1/users", headers=south).json() and len(client.get("/api/v1/users", headers=south).json()) == 1
        assert client.put(f"/api/v1/users/{user_id}/roles", headers=south, json={"ids": []}).status_code == 404
        assert client.put(f"/api/v1/roles/{role_id}/permissions", headers=south, json={"ids": []}).status_code == 404
        assert client.put(f"/api/v1/roles/{role_id}/permissions", headers=north, json={"ids": [pid, pid]}).status_code == 422
        assert client.post("/api/v1/roles", headers=north, json={"name": "Analyst"}).status_code == 409
        with SessionLocal() as db:
            owner_role = db.scalar(select(Role).where(Role.organization_id == db.get(User, user_id).organization_id, Role.is_owner.is_(True)))
            assert client.delete(f"/api/v1/roles/{owner_role.id}", headers=north).status_code == 403
            assert client.put(f"/api/v1/users/{user_id}/roles", headers=north, json={"ids": [owner_role.id]}).status_code == 403
        assert client.delete(f"/api/v1/permissions/{pid}", headers=north).status_code == 204
        assert client.delete(f"/api/v1/roles/{role_id}", headers=north).status_code == 204


def test_nonowner_cannot_escalate_or_read_other_resources():
    with TestClient(app) as client:
        admin = login(client)
        keys = {p["key"]: p["id"] for p in client.get("/api/v1/permissions", headers=admin).json()}
        role_id = client.post("/api/v1/roles", headers=admin, json={"name": "Manager"}).json()["id"]
        limited = ["users:read", "roles:read", "roles:create", "permissions:read", "assignments:write"]
        assert client.put(f"/api/v1/roles/{role_id}/permissions", headers=admin, json={"ids": [keys[k] for k in limited]}).status_code == 200
        user = client.post("/api/v1/users", headers=admin, json={"email": "manager@example.com", "full_name": "Limited Manager", "password": "manager-pass-123", "role_ids": [role_id]}).json()
        response = client.post("/api/v1/auth/login", json={"organization": "north", "email": user["email"], "password": "manager-pass-123"})
        manager = {"Authorization": f"Bearer {response.json()['access_token']}"}
        assert client.get("/api/v1/users", headers=manager).status_code == 200
        assert client.post("/api/v1/users", headers=manager, json={"email": "a@b.com", "full_name": "Not Allowed", "password": "not-allowed-123"}).status_code == 403
        assert client.get("/api/v1/permissions", headers=manager).status_code == 200
        assert client.post("/api/v1/permissions", headers=manager, json={"key": "reports:read"}).status_code == 403
        other_role = client.post("/api/v1/roles", headers=manager, json={"name": "Other"}).json()["id"]
        assert client.put(f"/api/v1/roles/{other_role}/permissions", headers=manager, json={"ids": [keys["users:update"]]}).status_code == 403
        assert client.put(f"/api/v1/users/{user['id']}/roles", headers=manager, json={"ids": [other_role, role_id]}).status_code == 200


def test_lockout_owner_protection_and_bad_payloads():
    with TestClient(app) as client:
        headers = login(client)
        me = client.get("/api/v1/auth/me", headers=headers).json()
        assert client.patch(f"/api/v1/users/{me['id']}", headers=headers, json={"is_active": False}).status_code == 403
        assert client.post("/api/v1/permissions", headers=headers, json={"key": "invalid key"}).status_code == 422
        assert client.post("/api/v1/users", headers=headers, json={"email": "person@example.com", "full_name": "New Person", "password": "short"}).status_code == 422
        for _ in range(5):
            assert client.post("/api/v1/auth/login", json={"organization": "north", "email": "owner@example.com", "password": "wrong-password"}).status_code == 401
        assert client.post("/api/v1/auth/login", json={"organization": "north", "email": "owner@example.com", "password": "correct-password-123"}).status_code == 429
