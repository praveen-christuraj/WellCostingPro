"""Password lifetime, refresh-token replay and boundary regressions.

These cases cover the controls an IT reviewer will ask about directly: what
happens when a password ages out, what a stolen refresh token can do after the
real one rotates, what an archive may contain, and where a client address may
come from.
"""
import gzip
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_security_workflows import fresh_database, login  # noqa: F401 - pytest fixtures
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password, password_is_expired, validate_password
from app.core.spreadsheets import safe_csv_cell
from app.core.time import as_utc, utcnow
from app.main import app
from app.models import Organization, User
from app.services import backup as backup_service
from app.services import report_engine


def _set_password_age(days: int) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "owner@example.com"))
        user.password_changed_at = utcnow() - timedelta(days=days)
        user.password_expires_at = utcnow() - timedelta(days=days - 89)
        db.commit()


def test_an_expired_password_forces_a_change_before_the_workspace_reopens():
    with TestClient(app) as client:
        _set_password_age(120)
        response = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "owner@example.com", "password": "correct-password-123",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["password_expired"] is True and body["must_change_password"] is True
        headers = {"Authorization": f"Bearer {body['access_token']}"}

        # Containment: nothing except the password endpoints is reachable.
        assert client.get("/api/v1/auth/me", headers=headers).json()["password_expired"] is True
        blocked = client.get("/api/v1/users", headers=headers)
        assert blocked.status_code == 403 and "requires a new password" in blocked.json()["detail"]

        changed = client.post("/api/v1/auth/change-password", headers=headers, json={
            "current_password": "correct-password-123", "new_password": "Replacement-pass-2026!",
        })
        assert changed.status_code == 204, changed.text
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "owner@example.com"))
            assert not password_is_expired(user)
            assert as_utc(user.password_expires_at) > utcnow()

        fresh = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "owner@example.com", "password": "Replacement-pass-2026!",
        })
        assert fresh.status_code == 200
        assert fresh.json()["password_expired"] is False
        reopened = {"Authorization": f"Bearer {fresh.json()['access_token']}"}
        assert client.get("/api/v1/users", headers=reopened).status_code == 200


def test_a_replayed_refresh_token_revokes_every_session():
    with TestClient(app) as client:
        first = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "owner@example.com", "password": "correct-password-123",
        })
        assert first.status_code == 200
        original = first.cookies["refresh_token"]

        rotated = client.post("/api/v1/auth/refresh")
        assert rotated.status_code == 200, rotated.text
        replacement = rotated.cookies["refresh_token"]

        # The legitimate client presents the consumed token (as an attacker with a
        # stolen copy would): the answer is a 401 *and* every session dies.
        client.cookies.clear()
        client.cookies.set("refresh_token", original, domain="testserver", path="/api/v1/auth")
        replay = client.post("/api/v1/auth/refresh")
        assert replay.status_code == 401

        client.cookies.clear()
        client.cookies.set("refresh_token", replacement, domain="testserver", path="/api/v1/auth")
        assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_all_invalidates_the_access_token():
    with TestClient(app) as client:
        headers = login(client)
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout-all", headers=headers).status_code == 204
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("value", ["password", "Password123!", "=1+1", "abcdefghijkl", "Qwerty12345!"])
def test_weak_passwords_are_rejected(value):
    with pytest.raises(ValueError):
        validate_password(value, identity="owner@example.com")


def test_a_strong_password_is_accepted():
    assert validate_password("Grey-harbour-72!", identity="owner@example.com")


def test_proxy_identity_is_only_believed_from_a_configured_proxy(monkeypatch):
    from fastapi import Request
    from app.core.request_security import client_ip

    request = Request({
        "type": "http",
        "client": ("203.0.113.9", 1234),
        "headers": [(b"x-forwarded-for", b"198.51.100.7, 10.0.0.4")],
    })
    assert client_ip(request) == "203.0.113.9"  # header ignored: peer is not a proxy

    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.0/8")
    proxied = Request({
        "type": "http",
        "client": ("10.0.0.4", 1234),
        "headers": [(b"x-forwarded-for", b"198.51.100.7, 10.0.0.4")],
    })
    assert client_ip(proxied) == "198.51.100.7"  # rightmost non-proxy hop


def test_archives_never_carry_credentials_or_access_control():
    with SessionLocal() as db:
        organization = db.scalar(select(Organization).where(Organization.slug == "north"))
        plan = backup_service.backup_plan(db, "workspace", organization.id)
    names = set(plan)
    assert {"vendors", "wells"} <= names
    assert not names & backup_service.CREDENTIAL_TABLES
    assert "password_history" not in names and "refresh_sessions" not in names


def test_backup_paths_refuse_symlinks_and_escape_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "backup_directory", str(tmp_path / "root"))
    root = backup_service.backup_root()
    inside = root / "archive.jsonl.gz"
    inside.write_bytes(b"")
    assert backup_service.ensure_within_root(inside) == inside.resolve()

    link = root / "link.jsonl.gz"
    link.symlink_to(inside)
    with pytest.raises(backup_service.BackupError):
        backup_service.ensure_within_root(link)
    with pytest.raises(backup_service.BackupError):
        backup_service.ensure_within_root(tmp_path / "outside.jsonl.gz")


def test_report_csv_neutralises_formula_text_end_to_end():
    design = {"name": "Test"}
    result = {
        "columns": [{"key": "vendor", "label": "=Vendor"}, {"key": "amount", "label": "Amount"}],
        "rows": [{"vendor": "=HYPERLINK(\"http://evil\")", "amount": -12}, {"vendor": "  @cmd", "amount": 3}],
        "totals": {"amount": 1},
    }
    payload = report_engine.export_csv(design, result, "Test").decode("utf-8-sig")
    lines = payload.splitlines()
    assert lines[0].startswith("'=Vendor")
    assert "'=HYPERLINK" in payload and "'  @cmd" in payload
    assert safe_csv_cell("=x") == "'=x"
    # A negative number keeps its exact numeric text so downstream sums still work.
    assert ",-12" in payload


def test_settings_never_render_secrets():
    settings = Settings(secret_key="s" * 40, seed_admin_password="Owner-pass-123!")
    assert "s" * 40 not in repr(settings)
    assert "Owner-pass-123!" not in repr(settings)
    assert "s" * 40 not in str(settings.safe_summary())


def test_production_turns_api_documentation_off():
    settings = Settings(environment="production", secret_key="p" * 48, secure_cookies=True,
                        cors_origins="https://app.example.com")
    assert settings.docs_enabled is False
    assert Settings().docs_enabled is True


def _delegated_security_admin() -> tuple[str, str]:
    """Create a non-owner account holding the password-reset capabilities.

    This is the realistic delegation boundary: an IT security administrator works
    the reset queue without being the workspace Owner.
    """
    from app.models import Permission, Role

    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == "north"))
        keys = ["security:read", "security:password-reset", "security:unlock"]
        permissions = list(db.scalars(select(Permission).where(
            Permission.organization_id == org.id, Permission.key.in_(keys)
        )).all())
        role = Role(organization_id=org.id, name="Security Administrator", permissions=permissions)
        db.add(User(
            organization_id=org.id, email="security@example.com", full_name="Delegated Security",
            password_hash=hash_password("Delegate-pass-2026!"), roles=[role],
        ))
        db.commit()
    return "security@example.com", "Delegate-pass-2026!"


def _owner_id() -> str:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == "owner@example.com"))


def test_a_delegated_administrator_cannot_act_on_the_owner_account():
    email, password = _delegated_security_admin()
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": email, "password": password,
        })
        assert response.status_code == 200, response.text
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        owner_id = _owner_id()

        reason = {"notes": "Routine queue work"}
        for path in ("reset-code", "force-password-change", "revoke-sessions", "lock", "unlock"):
            denied = client.post(f"/api/v1/security/users/{owner_id}/{path}", headers=headers, json=reason)
            assert denied.status_code == 403, f"{path}: {denied.status_code} {denied.text}"
            assert "owner" in denied.json()["detail"].lower()

        bulk = client.post("/api/v1/security/users/bulk", headers=headers, json={
            "action": "force-password-change", "user_ids": [owner_id], "notes": "Bulk attempt",
        })
        assert bulk.status_code == 200, bulk.text
        assert bulk.json() == {"action": "force-password-change", "affected": 0, "skipped": 1}

    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.email == "owner@example.com"))
        assert owner.must_change_password is False
        assert owner.locked_until is None


def test_the_same_delegated_administrator_can_still_serve_a_normal_account():
    _delegated_security_admin()
    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == "north"))
        colleague = User(
            organization_id=org.id, email="colleague@example.com", full_name="Normal Colleague",
            password_hash=hash_password("Colleague-pass-2026!"),
        )
        db.add(colleague)
        db.commit()
        colleague_id = colleague.id

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "security@example.com", "password": "Delegate-pass-2026!",
        })
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        forced = client.post(f"/api/v1/security/users/{colleague_id}/force-password-change",
                             headers=headers, json={"notes": "Lost device"})
        assert forced.status_code == 200, forced.text
        assert forced.json()["must_change_password"] is True
        # Containment is immediate: the old password is expired, not merely flagged.
        assert forced.json()["password_expired"] is True
        refused = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "colleague@example.com", "password": "Colleague-pass-2026!",
        })
        assert refused.status_code == 200  # authentication still proves identity ...
        body = refused.json()
        assert body["password_expired"] is True and body["must_change_password"] is True
        gate = {"Authorization": f"Bearer {body['access_token']}"}
        assert client.get("/api/v1/users", headers=gate).status_code == 403  # ... but the workspace stays shut


def test_an_account_created_by_an_administrator_can_be_forced_to_choose_its_own_password():
    """The create path must apply the same policy, history and expiry as every other path.

    ``require_password_change`` is what production uses by default
    (``force_password_change_on_create``): the administrator who types the initial
    value must not keep a working credential for somebody else's account.
    """
    with TestClient(app) as client:
        owner_headers = login(client)
        created = client.post("/api/v1/users", headers=owner_headers, json={
            "email": "newstarter@example.com", "full_name": "New Starter",
            "password": "Initial-pass-2026!", "require_password_change": True,
        })
        assert created.status_code == 201, created.text
        assert created.json()["must_change_password"] is True

        first = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "newstarter@example.com", "password": "Initial-pass-2026!",
        })
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["must_change_password"] is True
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        assert client.get("/api/v1/users", headers=headers).status_code == 403

        # The initial value is now history: it cannot be chosen again on the way through.
        reused = client.post("/api/v1/auth/change-password", headers=headers, json={
            "current_password": "Initial-pass-2026!", "new_password": "Initial-pass-2026!",
        })
        assert reused.status_code == 400 and "different" in reused.json()["detail"].lower()

        changed = client.post("/api/v1/auth/change-password", headers=headers, json={
            "current_password": "Initial-pass-2026!", "new_password": "Chosen-by-me-2026!",
        })
        assert changed.status_code == 204, changed.text

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "newstarter@example.com"))
        assert user.must_change_password is False
        assert as_utc(user.password_expires_at) > utcnow()
