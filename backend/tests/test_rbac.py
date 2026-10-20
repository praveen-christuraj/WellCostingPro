import os
import tempfile

# Set the database before importing app modules (engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
# Set TEST_DATABASE_URL (a PostgreSQL URL, as CI does) to run this suite against
# a real server instead of the throwaway SQLite file.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.core.database import Base, engine, SessionLocal
from app.main import app
from app.models import Organization, User, Role, Permission, AuditLog, RefreshSession, UserCostingSet, UserCostingSetItem
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
            keys = ["users:read", "users:create", "users:update", "users:delete", "roles:read", "roles:create", "roles:update", "roles:delete", "permissions:read", "permissions:create", "permissions:update", "permissions:delete", "assignments:write"]
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


def test_delete_user_cascades_private_data_revokes_sessions_and_preserves_audit():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")
        new_user = client.post("/api/v1/users", headers=north, json={
            "email": "person@example.com", "full_name": "New Person", "password": "person-secret-123"
        }).json()
        user_id = new_user["id"]
        auth = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "person@example.com", "password": "person-secret-123"
        })
        assert auth.status_code == 200
        token = {"Authorization": f"Bearer {auth.json()['access_token']}"}
        old_refresh = client.cookies.get("refresh_token")
        with SessionLocal() as db:
            org_id = db.get(User, user_id).organization_id
            saved = UserCostingSet(organization_id=org_id, user_id=user_id,
                                   name="Saved", name_key="saved", item_group="services",
                                   items=[UserCostingSetItem(organization_id=org_id, item_kind="service",
                                                              item_id="test", item_code_snapshot="S-01",
                                                              item_name_snapshot="Service", sort_order=0)])
            db.add(saved)
            db.commit()
            saved_id = saved.id
        assert client.delete(f"/api/v1/users/{user_id}", headers=south).status_code == 404
        assert client.delete(f"/api/v1/users/{user_id}", headers=token).status_code == 403
        assert client.delete(f"/api/v1/users/{user_id}", headers=north).status_code == 204
        assert client.delete(f"/api/v1/users/{user_id}", headers=north).status_code == 404
        assert client.get("/api/v1/auth/me", headers=token).status_code == 401
        client.cookies.set("refresh_token", old_refresh, path="/api/v1/auth")
        assert client.post("/api/v1/auth/refresh").status_code == 401
        with SessionLocal() as db:
            assert db.get(User, user_id) is None
            assert db.get(UserCostingSet, saved_id) is None
            assert db.scalar(select(RefreshSession).where(RefreshSession.user_id == user_id)) is None
            records = db.scalars(select(AuditLog).where(AuditLog.entity_type == "user", AuditLog.entity_id == user_id)).all()
            assert any(record.action == "create" for record in records)
            assert any(record.action == "delete" and record.actor_email == "owner@example.com" for record in records)
            assert any(record.actor_user_id == user_id for record in db.scalars(
                select(AuditLog).where(AuditLog.actor_user_id == user_id)).all())
        assert client.post("/api/v1/users", headers=north, json={
            "email": "person@example.com", "full_name": "Replacement", "password": "person-secret-123"
        }).status_code == 201


def test_delete_user_requires_permission_and_protects_owners():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")
        owner_id = client.get("/api/v1/auth/me", headers=north).json()["id"]
        south_owner_id = client.get("/api/v1/auth/me", headers=south).json()["id"]
        target_id = client.post("/api/v1/users", headers=north, json={
            "email": "target@example.com", "full_name": "Target", "password": "target-secret-123"
        }).json()["id"]
        assert client.delete(f"/api/v1/users/{owner_id}", headers=north).status_code == 403
        assert client.delete(f"/api/v1/users/{south_owner_id}", headers=north).status_code == 404
        with SessionLocal() as db:
            north_org = db.get(User, owner_id).organization_id
            second_owner = User(organization_id=north_org, email="second@example.com", full_name="Second Owner",
                                password_hash=hash_password("second-secret-123"),
                                roles=[db.scalar(select(Role).where(Role.organization_id == north_org, Role.is_owner.is_(True)))])
            db.add(second_owner)
            db.commit()
            second_owner_id = second_owner.id
        assert client.delete(f"/api/v1/users/{second_owner_id}", headers=north).status_code == 403
        role_id = client.post("/api/v1/roles", headers=north, json={"name": "Manager"}).json()["id"]
        permissions = {p["key"]: p["id"] for p in client.get("/api/v1/permissions", headers=north).json()}
        assert client.put(f"/api/v1/roles/{role_id}/permissions", headers=north,
                          json={"ids": [permissions["users:read"]]}).status_code == 200
        manager_id = client.post("/api/v1/users", headers=north, json={
            "email": "manager@example.com", "full_name": "Manager", "password": "manager-secret-123", "role_ids": [role_id]
        }).json()["id"]
        manager_token = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "manager@example.com", "password": "manager-secret-123"
        }).json()["access_token"]
        manager = {"Authorization": f"Bearer {manager_token}"}
        assert client.delete(f"/api/v1/users/{target_id}", headers=manager).status_code == 403
        assert client.put(f"/api/v1/roles/{role_id}/permissions", headers=north,
                          json={"ids": [permissions["users:read"], permissions["users:delete"]]}).status_code == 200
        assert client.delete(f"/api/v1/users/{second_owner_id}", headers=manager).status_code == 403
        assert client.delete(f"/api/v1/users/{manager_id}", headers=manager).status_code == 403
        assert client.delete(f"/api/v1/users/{target_id}", headers=manager).status_code == 204
