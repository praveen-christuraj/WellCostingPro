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


def login_as(client: TestClient, email: str, password: str, org: str = "north") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"organization": org, "email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_member(client: TestClient, owner: dict[str, str], email: str = "member@example.com") -> dict:
    """A plain account with no special capabilities, used to prove the barriers."""
    created = client.post("/api/v1/users", headers=owner, json={
        "email": email, "full_name": "Member One", "password": "Member-pass-123!",
    })
    assert created.status_code == 201, created.text
    return created.json()


def test_administrator_issues_reset_codes_without_a_user_request():
    with TestClient(app) as client:
        owner = login(client)
        account = client.get("/api/v1/security/users", headers=owner).json()[0]
        issued = client.post(
            f"/api/v1/security/users/{account['id']}/reset-code", headers=owner,
            json={"notes": "Suspected mailbox compromise"},
        )
        assert issued.status_code == 200, issued.text
        payload = issued.json()
        assert payload["request"]["initiated_by"] == "administrator"
        assert "Suspected mailbox compromise" in payload["request"]["review_notes"]
        # The account holder is told, so the action is never silent.
        inbox = client.get("/api/v1/notifications", headers=owner).json()
        assert any("reset code" in item["title"].lower() for item in inbox["items"])
        reset = client.post("/api/v1/auth/reset-password", json={
            "organization": "north", "email": "owner@example.com", "reset_code": payload["reset_code"],
            "new_password": "Rotated-password-789!", "confirm_password": "Rotated-password-789!",
        })
        assert reset.status_code == 204, reset.text
        login(client, password="Rotated-password-789!")
        audit_rows = client.get("/api/v1/audit?entity_type=password_reset", headers=login(client, password="Rotated-password-789!")).json()["items"]
        assert any("without a user request" in row["summary"] for row in audit_rows)


def test_forced_password_change_closes_the_workspace_until_completed():
    with TestClient(app) as client:
        owner = login(client)
        member = make_member(client, owner)
        member_headers = login_as(client, member["email"], "Member-pass-123!")
        assert client.get("/api/v1/notifications", headers=member_headers).status_code == 200

        forced = client.post(f"/api/v1/security/users/{member['id']}/force-password-change", headers=owner, json={"notes": "Laptop stolen"})
        assert forced.status_code == 200, forced.text
        assert forced.json()["must_change_password"] is True
        # The old access token dies immediately because the token version moved.
        assert client.get("/api/v1/notifications", headers=member_headers).status_code == 401

        fresh = login_as(client, member["email"], "Member-pass-123!")
        blocked = client.get("/api/v1/notifications", headers=fresh)
        assert blocked.status_code == 403
        assert "requires a new password" in blocked.json()["detail"]
        me = client.get("/api/v1/auth/me", headers=fresh).json()
        assert me["must_change_password"] is True

        changed = client.post("/api/v1/auth/change-password", headers=fresh, json={
            "current_password": "Member-pass-123!", "new_password": "Member-pass-456!",
        })
        assert changed.status_code == 204, changed.text
        reopened = login_as(client, member["email"], "Member-pass-456!")
        assert client.get("/api/v1/notifications", headers=reopened).status_code == 200
        assert client.get("/api/v1/auth/me", headers=reopened).json()["must_change_password"] is False


def test_password_reuse_is_refused():
    with TestClient(app) as client:
        owner = login(client)
        member = make_member(client, owner)
        first = login_as(client, member["email"], "Member-pass-123!")
        assert client.post("/api/v1/auth/change-password", headers=first, json={
            "current_password": "Member-pass-123!", "new_password": "Member-pass-456!",
        }).status_code == 204
        second = login_as(client, member["email"], "Member-pass-456!")
        # The password the account just replaced may not be restored.
        reused = client.post("/api/v1/auth/change-password", headers=second, json={
            "current_password": "Member-pass-456!", "new_password": "Member-pass-123!",
        })
        assert reused.status_code == 422
        assert "not used before" in reused.json()["detail"]


def test_lock_unlock_bulk_and_capability_boundaries():
    with TestClient(app) as client:
        owner = login(client)
        member = make_member(client, owner)
        member_headers = login_as(client, member["email"], "Member-pass-123!")
        # A plain account may not lock or force anything, not even itself.
        assert client.post(f"/api/v1/security/users/{member['id']}/lock", headers=member_headers, json={"notes": ""}).status_code == 403
        assert client.post("/api/v1/security/users/bulk", headers=member_headers, json={"user_ids": [member["id"]], "action": "lock", "notes": ""}).status_code == 403

        locked = client.post(f"/api/v1/security/users/{member['id']}/lock", headers=owner, json={"notes": "Under investigation"})
        assert locked.status_code == 200, locked.text
        assert locked.json()["locked_until"] is not None
        assert client.post("/api/v1/auth/login", json={
            "organization": "north", "email": member["email"], "password": "Member-pass-123!"}).status_code == 429
        assert client.post(f"/api/v1/security/users/{member['id']}/unlock", headers=owner).status_code == 204
        login_as(client, member["email"], "Member-pass-123!")

        bulk = client.post("/api/v1/security/users/bulk", headers=owner, json={
            "user_ids": [member["id"]], "action": "force-password-change", "notes": "Quarterly rotation",
        })
        assert bulk.status_code == 200 and bulk.json()["affected"] == 1
        accounts = {row["email"]: row for row in client.get("/api/v1/security/users", headers=owner).json()}
        assert accounts[member["email"]]["must_change_password"] is True
        assert accounts[member["email"]]["active_sessions"] == 0

        # The other workspace cannot see or act on this account at all.
        south = login(client, "south")
        assert client.post(f"/api/v1/security/users/{member['id']}/lock", headers=south, json={"notes": ""}).status_code == 404
        assert client.get("/api/v1/security/users", headers=south).json()[0]["email"] == "owner@example.com"


def test_notification_centre_filters_announcements_and_recall():
    with TestClient(app) as client:
        owner = login(client)
        member = make_member(client, owner)
        role = client.post("/api/v1/roles", headers=owner, json={"name": "Estimators", "description": ""}).json()
        client.put(f"/api/v1/users/{member['id']}/roles", headers=owner, json={"ids": [role["id"]]})

        sent = client.post("/api/v1/notifications", headers=owner, json={
            "title": "Month-end closing", "message": "Submit your daily sheets by Friday.",
            "severity": "warning", "recipient_role_ids": [role["id"]],
        })
        assert sent.status_code == 201, sent.text
        announcement = client.get("/api/v1/notifications/announcements", headers=owner).json()["items"][0]
        assert announcement["audience"] == "roles" and announcement["recipient_count"] == 1
        assert "Estimators" in announcement["audience_label"]

        member_headers = login_as(client, member["email"], "Member-pass-123!")
        inbox = client.get("/api/v1/notifications?status=unread", headers=member_headers).json()
        assert inbox["total"] == 1 and inbox["unread_count"] == 1
        assert client.get("/api/v1/notifications?status=read", headers=member_headers).json()["total"] == 0
        assert client.get("/api/v1/notifications?severity=error", headers=member_headers).json()["total"] == 0
        assert client.get("/api/v1/notifications?search=closing", headers=member_headers).json()["total"] == 1
        notification_id = inbox["items"][0]["id"]
        assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=member_headers).status_code == 204
        assert client.get("/api/v1/notifications/overview", headers=member_headers).json()["unread"] == 0
        assert client.post(f"/api/v1/notifications/{notification_id}/unread", headers=member_headers).status_code == 204
        assert client.get("/api/v1/notifications", headers=member_headers).json()["unread_count"] == 1

        # Recall withdraws unread copies only.
        recalled = client.post(f"/api/v1/notifications/announcements/{announcement['id']}/recall", headers=owner)
        assert recalled.status_code == 200 and recalled.json()["recalled_at"]
        assert client.get("/api/v1/notifications", headers=member_headers).json()["total"] == 0
        assert client.post(f"/api/v1/notifications/announcements/{announcement['id']}/recall", headers=owner).status_code == 409

        # Only the recipient can act on a personal notification, and a missing one
        # explains itself instead of answering a bare "Not found".
        empty = client.get("/api/v1/notifications", headers=owner).json()["items"]
        missing = client.post(f"/api/v1/notifications/{notification_id}/read", headers=owner)
        assert missing.status_code == 404 and "not in your inbox" in missing.json()["detail"]
        assert empty is not None


def grant_permissions(client: TestClient, owner: dict[str, str], member: dict, keys: tuple[str, ...], role_name: str):
    """Give a plain account exactly the capabilities a test needs, through the normal RBAC API."""
    permissions = {row["key"]: row["id"] for row in client.get("/api/v1/permissions", headers=owner).json()}
    role = client.post("/api/v1/roles", headers=owner, json={"name": role_name, "description": ""}).json()
    client.put(f"/api/v1/roles/{role['id']}/permissions", headers=owner, json={"ids": [permissions[key] for key in keys]})
    client.put(f"/api/v1/users/{member['id']}/roles", headers=owner, json={"ids": [role["id"]]})


def test_task_manager_filters_comments_and_bulk_actions():
    with TestClient(app) as client:
        owner = login(client)
        member = make_member(client, owner)
        grant_permissions(client, owner, member, ("tasks:read",), "Task readers")
        created = client.post("/api/v1/tasks", headers=owner, json={
            "title": "Reconcile mud stock", "description": "Check the closing balance", "priority": "high",
            "assignee_user_id": member["id"], "due_at": "2020-01-01T00:00:00Z",
        })
        assert created.status_code == 201, created.text
        task = created.json()
        assert task["assignee_name"] == "Member One" and task["overdue"] is True

        member_headers = login_as(client, member["email"], "Member-pass-123!")
        mine = client.get("/api/v1/tasks?assignee=me", headers=member_headers).json()
        assert mine["total"] == 1 and mine["items"][0]["is_mine"] is True
        assert client.get("/api/v1/tasks?due=overdue", headers=owner).json()["total"] == 1
        assert client.get("/api/v1/tasks?search=mud", headers=owner).json()["total"] == 1
        assert client.get("/api/v1/tasks?priority=low", headers=owner).json()["total"] == 0
        overview = client.get("/api/v1/tasks/overview", headers=owner).json()
        assert overview["open"] == 1 and overview["overdue"] == 1 and overview["by_priority"]["high"] == 1

        comment = client.post(f"/api/v1/tasks/{task['id']}/comments", headers=member_headers, json={"notes": "Balance checked"})
        assert comment.status_code == 201, comment.text
        events = client.get(f"/api/v1/tasks/{task['id']}/events", headers=member_headers).json()
        assert [event["event_type"] for event in events] == ["created", "comment"]

        bulk = client.post("/api/v1/tasks/bulk", headers=owner, json={"task_ids": [task["id"]], "action": "complete", "notes": "Closed"})
        assert bulk.status_code == 200 and bulk.json()["affected"] == 1
        assert client.get("/api/v1/tasks?status=completed", headers=owner).json()["total"] == 1
        reopened = client.patch(f"/api/v1/tasks/{task['id']}", headers=owner, json={"status": "open", "notes": "Not reconciled"})
        assert reopened.status_code == 200 and reopened.json()["status"] == "open"

        # A member who is not assigned sees no tasks and gets a helpful refusal.
        other = make_member(client, owner, email="other@example.com")
        other_headers = login_as(client, other["email"], "Member-pass-123!")
        # Without tasks:read the queue is not even listed, and a named task is invisible.
        assert client.get("/api/v1/tasks", headers=other_headers).status_code == 403
        grant_permissions(client, owner, other, ("tasks:read",), "Task observers")
        other_headers = login_as(client, other["email"], "Member-pass-123!")
        assert client.get("/api/v1/tasks", headers=other_headers).json()["total"] == 0
        denied = client.patch(f"/api/v1/tasks/{task['id']}", headers=other_headers, json={"status": "completed"})
        assert denied.status_code == 404


def test_not_found_answers_explain_themselves():
    with TestClient(app) as client:
        owner = login(client)
        unknown = client.get("/api/v1/security/not-a-real-endpoint", headers=owner)
        assert unknown.status_code == 404
        detail = unknown.json()["detail"]
        assert "not-a-real-endpoint" in detail and detail.strip().lower() != "not found"
        missing_user = client.patch("/api/v1/users/00000000-0000-0000-0000-000000000000", headers=owner, json={"full_name": "Ghost"})
        assert missing_user.status_code == 404
        assert "user account" in missing_user.json()["detail"]
        assert "refresh the list" in missing_user.json()["detail"]
        # An unsupported method is a different sentence from a missing route: the
        # user needs to know the action is not offered here, not that the address
        # does not exist.
        wrong_method = client.get("/api/v1/users/00000000-0000-0000-0000-000000000000", headers=owner)
        assert wrong_method.status_code == 405
        assert "GET" in wrong_method.json()["detail"] and "not offered" in wrong_method.json()["detail"]
        health = client.get("/api/health").json()
        assert health["api_version"]


def test_reset_reviewer_reaches_the_queue_without_the_account_register():
    """security:password-reset alone must open the queue it is meant to work on.

    A reviewer hired to clear recovery requests has no business reading every
    account, and must not be shown a page that can only answer 403.
    """
    with TestClient(app) as client:
        owner = login(client)
        with SessionLocal() as db:
            org = db.scalar(select(Organization).where(Organization.slug == "north"))
            capability = db.scalar(select(Permission).where(
                Permission.organization_id == org.id, Permission.key == "security:password-reset"))
            reviewer_role = Role(organization_id=org.id, name="Reset reviewer", permissions=[capability])
            db.add(User(
                organization_id=org.id, email="reviewer@example.com", full_name="Reset Reviewer",
                password_hash=hash_password("Reviewer-pass-123!"), roles=[reviewer_role],
            ))
            db.commit()
        reviewer = login_as(client, "reviewer@example.com", "Reviewer-pass-123!")

        assert client.post("/api/v1/auth/forgot-password", json={
            "organization": "north", "email": "owner@example.com", "reason": "Locked out"}).status_code == 202

        summary = client.get("/api/v1/security/overview", headers=reviewer)
        assert summary.status_code == 200, summary.text
        assert summary.json()["pending_requests"] == 1
        queue = client.get("/api/v1/security/password-reset-requests", headers=reviewer)
        assert queue.status_code == 200 and len(queue.json()) == 1
        approved = client.post(
            f"/api/v1/security/password-reset-requests/{queue.json()[0]['id']}/approve",
            headers=reviewer, json={"notes": "Verified by phone"},
        )
        assert approved.status_code == 200, approved.text

        # Reading every account, or locking one, still needs its own capability.
        denied = client.get("/api/v1/security/users", headers=reviewer)
        assert denied.status_code == 403
        assert "security:read" in denied.json()["detail"]
        assert client.post(
            f"/api/v1/security/users/{queue.json()[0]['user_id']}/lock", headers=reviewer, json={"notes": ""},
        ).status_code == 403
