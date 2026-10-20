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
from sqlalchemy import func, select
from app.core.database import Base, engine, SessionLocal
from app.main import app
from app.models import AuditLog, Organization, RefreshSession, User, Role, Permission
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


# --- User deletion -----------------------------------------------------------
# Administrators create workspace members, so they must be able to remove them.
# Owner accounts and the signed-in account stay protected.


def make_user(client, headers, email="member@example.com", role_ids=None):
    response = client.post("/api/v1/users", headers=headers, json={
        "email": email, "full_name": "Workspace Member", "password": "member-password-123", "role_ids": role_ids or [],
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_can_delete_a_created_user_and_the_email_is_reusable():
    with TestClient(app) as client:
        headers = login(client)
        user = make_user(client, headers)
        assert client.delete(f"/api/v1/users/{user['id']}", headers=headers).status_code == 204
        emails = [row["email"] for row in client.get("/api/v1/users", headers=headers).json()]
        assert user["email"] not in emails
        assert client.delete(f"/api/v1/users/{user['id']}", headers=headers).status_code == 404
        # The audit trail keeps the deletion, attributed to the administrator.
        with SessionLocal() as db:
            entry = db.scalar(select(AuditLog).where(
                AuditLog.entity_type == "user", AuditLog.entity_id == user["id"], AuditLog.action == "delete"))
            assert entry is not None and entry.actor_email == "owner@example.com"
        # A permanently deleted account frees its e-mail address for re-invitation.
        assert make_user(client, headers)["email"] == user["email"]


def test_deleted_user_cannot_sign_in_and_sessions_are_revoked():
    with TestClient(app) as client:
        headers = login(client)
        user = make_user(client, headers)
        assert client.post("/api/v1/auth/login", json={"organization": "north", "email": user["email"], "password": "member-password-123"}).status_code == 200
        with SessionLocal() as db:
            assert db.scalar(select(func.count(RefreshSession.id)).where(RefreshSession.user_id == user["id"])) > 0
        assert client.delete(f"/api/v1/users/{user['id']}", headers=headers).status_code == 204
        with SessionLocal() as db:
            assert db.get(User, user["id"]) is None
            assert db.scalar(select(func.count(RefreshSession.id)).where(RefreshSession.user_id == user["id"])) == 0
        assert client.post("/api/v1/auth/login", json={"organization": "north", "email": user["email"], "password": "member-password-123"}).status_code == 401


def test_owner_and_self_are_protected_from_deletion():
    with TestClient(app) as client:
        headers = login(client)
        me = client.get("/api/v1/auth/me", headers=headers).json()
        assert client.delete(f"/api/v1/users/{me['id']}", headers=headers).status_code == 403
        # A second owner is still an owner: the RBAC baseline never leaves the
        # workspace without an administrator through this endpoint.
        with SessionLocal() as db:
            org_id = db.get(User, me["id"]).organization_id
            owner_role = db.scalar(select(Role).where(Role.organization_id == org_id, Role.is_owner.is_(True)))
            second = User(organization_id=org_id, email="second-owner@example.com", full_name="Second Owner",
                          password_hash=hash_password("second-owner-pass-123"), roles=[owner_role])
            db.add(second)
            db.commit()
            second_id = second.id
        response = client.delete(f"/api/v1/users/{second_id}", headers=headers)
        assert response.status_code == 403
        assert "owner" in response.json()["detail"].lower()
        with SessionLocal() as db:
            assert db.get(User, second_id) is not None


def test_cross_tenant_user_deletion_is_not_found():
    with TestClient(app) as client:
        north, south = login(client), login(client, "south")
        user = make_user(client, north)
        assert client.delete(f"/api/v1/users/{user['id']}", headers=south).status_code == 404
        assert client.post("/api/v1/users/bulk-delete", headers=south, json={"ids": [user["id"]]}).status_code == 422
        assert client.delete(f"/api/v1/users/{user['id']}", headers=north).status_code == 204


def test_user_deletion_requires_the_users_delete_capability():
    with TestClient(app) as client:
        admin = login(client)
        member = make_user(client, admin)
        permission = client.post("/api/v1/permissions", headers=admin, json={"key": "users:delete", "description": "Delete users"})
        assert permission.status_code == 201
        remover_role = client.post("/api/v1/roles", headers=admin, json={"name": "User Administrator"}).json()["id"]
        assert client.put(f"/api/v1/roles/{remover_role}/permissions", headers=admin, json={"ids": [permission.json()["id"]]}).status_code == 200
        remover = make_user(client, admin, email="remover@example.com", role_ids=[remover_role])
        token = client.post("/api/v1/auth/login", json={"organization": "north", "email": remover["email"], "password": "member-password-123"}).json()["access_token"]
        remover_headers = {"Authorization": f"Bearer {token}"}
        # A member without the capability cannot delete anybody, even with a link.
        reader_role = client.post("/api/v1/roles", headers=admin, json={"name": "Reader"}).json()["id"]
        reader = make_user(client, admin, email="reader@example.com", role_ids=[reader_role])
        reader_token = client.post("/api/v1/auth/login", json={"organization": "north", "email": reader["email"], "password": "member-password-123"}).json()["access_token"]
        assert client.delete(f"/api/v1/users/{member['id']}", headers={"Authorization": f"Bearer {reader_token}"}).status_code == 403
        # A capability holder may remove an ordinary member.
        assert client.delete(f"/api/v1/users/{member['id']}", headers=remover_headers).status_code == 204
        # But not an account holding capabilities the deleter does not hold.
        privileged_permission = client.post("/api/v1/permissions", headers=admin, json={"key": "reports:approve", "description": "Approve reports"}).json()["id"]
        privileged_role = client.post("/api/v1/roles", headers=admin, json={"name": "Approver"}).json()["id"]
        client.put(f"/api/v1/roles/{privileged_role}/permissions", headers=admin, json={"ids": [privileged_permission]})
        approver = make_user(client, admin, email="approver@example.com", role_ids=[privileged_role])
        assert client.delete(f"/api/v1/users/{approver['id']}", headers=remover_headers).status_code == 403
        # And never an organization owner.
        me = client.get("/api/v1/auth/me", headers=admin).json()
        assert client.delete(f"/api/v1/users/{me['id']}", headers=remover_headers).status_code == 403


def test_bulk_user_deletion_reports_protected_accounts():
    with TestClient(app) as client:
        headers = login(client)
        me = client.get("/api/v1/auth/me", headers=headers).json()
        first = make_user(client, headers, email="first@example.com")
        second = make_user(client, headers, email="second@example.com")
        response = client.post("/api/v1/users/bulk-delete", headers=headers, json={"ids": [first["id"], me["id"]]})
        assert response.status_code == 409
        assert me["email"] in response.json()["detail"]
        with SessionLocal() as db:
            assert db.get(User, first["id"]) is not None
        result = client.post("/api/v1/users/bulk-delete", headers=headers, json={"ids": [first["id"], second["id"]]})
        assert result.status_code == 200, result.text
        assert result.json() == {"deleted_count": 2, "deleted_emails": sorted([first["email"], second["email"]])}
        emails = [row["email"] for row in client.get("/api/v1/users", headers=headers).json()]
        assert first["email"] not in emails and second["email"] not in emails
