import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import Organization, PasswordResetRequest, Permission, Role, User, UserNotification, WorkflowTask


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for slug in ("north", "south"):
            org = Organization(slug=slug, name=f"{slug.title()} Energy")
            db.add(org)
            db.flush()
            keys = ["security:read", "security:password-reset", "security:unlock", "notifications:manage", "tasks:read", "tasks:create", "tasks:manage"]
            permissions = [Permission(organization_id=org.id, key=key, description=key) for key in keys]
            owner = Role(organization_id=org.id, name="Owner", is_owner=True, permissions=permissions)
            db.add(User(organization_id=org.id, email="owner@example.com", full_name="Test Owner", password_hash=hash_password("correct-password-123"), roles=[owner]))
        db.commit()
    yield


def login(client: TestClient, org: str = "north", password: str = "correct-password-123") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"organization": org, "email": "owner@example.com", "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_approved_password_recovery_is_one_time_and_revokes_sessions():
    with TestClient(app) as client:
        headers = login(client)
        known = client.post("/api/v1/auth/forgot-password", json={"organization": "north", "email": "owner@example.com", "reason": "Lost password manager"})
        unknown = client.post("/api/v1/auth/forgot-password", json={"organization": "north", "email": "missing@example.com", "reason": "Unknown"})
        assert known.status_code == unknown.status_code == 202
        assert known.json() == unknown.json()

        requests = client.get("/api/v1/security/password-reset-requests", headers=headers).json()
        assert len(requests) == 1
        assert requests[0]["status"] == "pending"
        tasks = client.get("/api/v1/tasks?page_size=20", headers=headers).json()["items"]
        assert tasks[0]["task_type"] == "password_reset"

        approved = client.post(f"/api/v1/security/password-reset-requests/{requests[0]['id']}/approve", headers=headers, json={"notes": "Identity verified by supervisor"})
        assert approved.status_code == 200, approved.text
        code = approved.json()["reset_code"]
        reset = client.post("/api/v1/auth/reset-password", json={
            "organization": "north", "email": "owner@example.com", "reset_code": code,
            "new_password": "Safer-password-456!", "confirm_password": "Safer-password-456!",
        })
        assert reset.status_code == 204, reset.text
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        assert client.post("/api/v1/auth/reset-password", json={
            "organization": "north", "email": "owner@example.com", "reset_code": code,
            "new_password": "Another-password-789!", "confirm_password": "Another-password-789!",
        }).status_code == 400
        login(client, password="Safer-password-456!")

        with SessionLocal() as db:
            row = db.scalar(select(PasswordResetRequest))
            assert row.status == "completed" and row.reset_token_hash is None
            assert db.scalar(select(WorkflowTask)).status == "completed"
            assert db.scalar(select(UserNotification).where(UserNotification.title == "Password reset completed"))


def test_notifications_tasks_and_tenant_boundaries():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")
        for _ in range(5):
            assert client.post("/api/v1/auth/login", json={"organization": "north", "email": "owner@example.com", "password": "wrong-password"}).status_code == 401
        accounts = client.get("/api/v1/security/users", headers=north).json()
        assert len(accounts) == 1 and accounts[0]["locked_until"]
        assert client.post(f"/api/v1/security/users/{accounts[0]['id']}/unlock", headers=south).status_code == 404
        assert client.post(f"/api/v1/security/users/{accounts[0]['id']}/unlock", headers=north).status_code == 204
        assert client.get("/api/v1/security/users", headers=north).json()[0]["locked_until"] is None
        created = client.post("/api/v1/tasks", headers=north, json={"title": "Review cost exception", "description": "Verify the supporting records", "priority": "high"})
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert client.patch(f"/api/v1/tasks/{task_id}", headers=south, json={"status": "completed"}).status_code == 404
        assert client.patch(f"/api/v1/tasks/{task_id}", headers=north, json={"status": "in_progress", "notes": "Claimed"}).status_code == 200

        sent = client.post("/api/v1/notifications", headers=north, json={"title": "Maintenance notice", "message": "The workspace will be read-only tonight.", "severity": "warning", "recipient_user_ids": []})
        assert sent.status_code == 201 and len(sent.json()) == 1
        inbox = client.get("/api/v1/notifications", headers=north).json()
        assert inbox["unread_count"] == 1
        assert client.post("/api/v1/notifications/read-all", headers=north).status_code == 204
        assert client.get("/api/v1/notifications", headers=south).json()["items"] == []
