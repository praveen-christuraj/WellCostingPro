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
from app.models import AuditLog, Organization, User, Role, Permission
from app.core.security import hash_password


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        org = Organization(slug="north", name="North Energy")
        db.add(org)
        db.flush()
        keys = ["users:read", "users:create", "users:update", "roles:read", "roles:create", "roles:update", "roles:delete", "permissions:read", "permissions:create", "permissions:update", "permissions:delete", "assignments:write", "audit:read"]
        owner_role = Role(organization_id=org.id, name="Owner", is_owner=True, permissions=[Permission(organization_id=org.id, key=key, description=key) for key in keys])
        db.add(User(organization_id=org.id, email="owner@example.com", full_name="Test Owner", password_hash=hash_password("correct-password-123"), roles=[owner_role]))
        db.commit()
    yield


def login(client):
    response = client.post("/api/v1/auth/login", json={"organization": "north", "email": "owner@example.com", "password": "correct-password-123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def actions():
    with SessionLocal() as db:
        return list(db.scalars(select(AuditLog).order_by(AuditLog.created_at)).all())


def test_mutations_write_column_wise_audit_entries():
    with TestClient(app) as client:
        headers = login(client)
        role = client.post("/api/v1/roles", headers=headers, json={"name": "Analyst", "description": "Cost analyst"}).json()
        client.patch(f"/api/v1/roles/{role['id']}", headers=headers, json={"description": "Updated description"})
        client.post("/api/v1/users", headers=headers, json={"email": "analyst@example.com", "full_name": "Cost Analyst", "password": "analyst-secret-123"})
        entries = actions()
        kinds = [(e.action, e.entity_type) for e in entries]
        assert ("login", "auth") in kinds
        assert ("create", "role") in kinds
        assert ("update", "role") in kinds
        assert ("create", "user") in kinds
        create = next(e for e in entries if e.action == "create" and e.entity_type == "role")
        assert create.actor_email == "owner@example.com"
        assert create.entity_label == "Analyst"
        assert create.summary
        assert create.ip_address  # request metadata captured
        # Column-wise storage: the table must not carry a JSON payload column.
        assert not any(c.name in {"payload", "data", "details_json", "extra"} for c in AuditLog.__table__.columns)


def test_login_failures_are_audited_and_list_is_permission_gated():
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"organization": "north", "email": "owner@example.com", "password": "wrong-password"})
        headers = login(client)
        page = client.get("/api/v1/audit?page=1&page_size=20", headers=headers)
        assert page.status_code == 200, page.text
        payload = page.json()
        assert payload["page_size"] == 20
        assert any(e["action"] == "login_failed" for e in payload["items"])
        assert payload["total"] == len(payload["items"])
        filtered = client.get("/api/v1/audit?action=login", headers=headers).json()
        assert filtered["items"] and all(e["action"] == "login" for e in filtered["items"])
        # A user without audit:read cannot read the trail (owner bypass excluded).
        with SessionLocal() as db:
            org = db.scalar(select(Organization).where(Organization.slug == "north"))
            viewer = Role(organization_id=org.id, name="Viewer")
            db.add(User(organization_id=org.id, email="viewer@example.com", full_name="Plain Viewer", password_hash=hash_password("viewer-secret-123"), roles=[viewer]))
            db.commit()
        viewer_headers = {"Authorization": f"Bearer {client.post('/api/v1/auth/login', json={'organization': 'north', 'email': 'viewer@example.com', 'password': 'viewer-secret-123'}).json()['access_token']}"}
        assert client.get("/api/v1/audit", headers=viewer_headers).status_code == 403
