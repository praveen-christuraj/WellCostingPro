import os
import tempfile

# Set the database before importing app modules (engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.bootstrap import Outcome, bootstrap_admin, env_credentials, inspect_admin
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.migrations import MISSING, READY, schema_status, upgrade_head
from app.main import app
from app.seed import EXIT_FAILED, EXIT_MISSING, EXIT_OK, EXIT_SCHEMA, main
from app.services import provisioning


def reset_schema(migrate: bool = True):
    """Empty database, then optionally the real Alembic schema (as on a new device)."""
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.drop_all(bind=engine)
    if migrate:
        upgrade_head()


@pytest.fixture
def migrated_database():
    reset_schema()
    yield
    reset_schema(migrate=False)


@pytest.fixture
def scripted_terminal(monkeypatch):
    """Feed `input()` from a queue and answer every password prompt identically."""
    def script(answers, password="correct-password-123"):
        queue = iter(answers)
        monkeypatch.setattr("builtins.input", lambda prompt="": str(next(queue)))
        monkeypatch.setattr("getpass.getpass", lambda prompt="": password)
    return script


def owners():
    with SessionLocal() as db:
        return provisioning.administrators(db)


def test_missing_admin_is_reported_without_writing(migrated_database):
    assert schema_status() == READY
    with SessionLocal() as db:
        assert provisioning.admin_missing(db)
    result = bootstrap_admin(interactive=False)
    assert result.outcome is Outcome.SKIPPED and result.needs_attention
    assert "python -m app.seed" in result.message
    assert inspect_admin().outcome is Outcome.SKIPPED
    assert owners() == []


def test_interactive_setup_seeds_a_working_administrator(migrated_database, scripted_terminal):
    scripted_terminal(["y", "Bad Slug!", "acme-energy", "Acme Energy", "Jane Smith", "jane@example.com"])
    result = bootstrap_admin(interactive=True)
    assert result.outcome is Outcome.SEEDED and not result.needs_attention
    assert result.admin_email == "jane@example.com"
    admin = owners()[0]
    assert admin.email == "jane@example.com" and admin.full_name == "Jane Smith"
    assert any(role.is_owner for role in admin.roles)
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={"organization": "acme-energy", "email": "jane@example.com", "password": "correct-password-123"}).status_code == 200
        assert client.get("/api/health").json()["admin_seeded"] is True
    # A second run must be a no-op, not a duplicate owner.
    assert bootstrap_admin(interactive=False).outcome is Outcome.ADMIN_PRESENT
    assert len(owners()) == 1


def test_declining_the_prompt_changes_nothing(migrated_database, scripted_terminal):
    scripted_terminal(["n"])
    result = bootstrap_admin(interactive=True)
    assert result.outcome is Outcome.DECLINED and result.needs_attention
    assert owners() == []


def test_env_variables_seed_without_a_terminal(migrated_database, monkeypatch):
    monkeypatch.setattr("app.bootstrap.get_settings", lambda: get_settings().model_copy(update={
        "seed_org_slug": "env-org", "seed_org_name": "Env Org", "seed_owner_name": "Env Owner",
        "seed_admin_email": "Env@Example.COM", "seed_admin_password": "correct-password-123"}))
    assert env_credentials()["email"] == "Env@Example.COM"
    result = bootstrap_admin(interactive=False)
    assert result.outcome is Outcome.SEEDED and result.admin_email == "env@example.com"
    # An incomplete set must never seed a half-configured administrator.
    monkeypatch.setattr("app.bootstrap.get_settings", lambda: get_settings().model_copy(update={
        "seed_org_slug": "env-org", "seed_org_name": "", "seed_owner_name": "", "seed_admin_email": "", "seed_admin_password": ""}))
    assert env_credentials() is None


def test_bootstrap_is_disabled_on_request(migrated_database, monkeypatch):
    monkeypatch.setattr("app.bootstrap.get_settings", lambda: get_settings().model_copy(update={"bootstrap_admin_on_startup": False}))
    assert bootstrap_admin(interactive=True).outcome is Outcome.DISABLED
    assert owners() == []


def test_unmigrated_database_is_reported_and_can_be_migrated(migrated_database, monkeypatch):
    reset_schema(migrate=False)
    assert schema_status() == MISSING
    assert bootstrap_admin(interactive=False).outcome is Outcome.NEEDS_MIGRATION
    assert main(["--check"]) == EXIT_SCHEMA
    asked = []
    monkeypatch.setattr("app.services.console.confirm", lambda prompt, default=True: asked.append(prompt) or False)
    assert bootstrap_admin(interactive=True).outcome is Outcome.NEEDS_MIGRATION
    assert "migrations" in asked[0].lower()
    reset_schema()
    assert schema_status() == READY


def test_check_and_flag_modes_of_the_cli(migrated_database, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "correct-password-123")
    assert main(["--check"]) == EXIT_MISSING
    assert main(["--slug", "only-a-slug"]) == EXIT_FAILED
    assert main(["--slug", "flag-org", "--name", "Flag Org", "--email", "owner@example.com", "--owner-name", "Flag Owner"]) == EXIT_OK
    assert main(["--check", "--quiet"]) == EXIT_OK
    assert owners()[0].email == "owner@example.com"
    # A duplicate slug is refused unless the operator asks to attach to the existing workspace.
    assert main(["--slug", "flag-org", "--name", "Flag Org", "--email", "second@example.com", "--owner-name", "Second Owner"]) == EXIT_FAILED
    assert len(owners()) == 1
    assert main(["--slug", "flag-org", "--name", "Flag Org", "--email", "second@example.com", "--owner-name", "Second Owner", "--attach-existing"]) == EXIT_OK
    assert sorted(user.email for user in owners()) == ["owner@example.com", "second@example.com"]


def test_guided_run_without_a_terminal_reports_instead_of_guessing(migrated_database, monkeypatch):
    monkeypatch.setattr("app.services.console.is_interactive", lambda: False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "correct-password-123")
    assert main([]) == EXIT_MISSING  # nothing to ask, nothing seeded yet
    assert main(["--slug", "acme-energy", "--name", "Acme Energy", "--email", "jane@example.com", "--owner-name", "Jane Smith"]) == EXIT_OK
    assert main([]) == EXIT_OK  # an administrator exists: report success, do not prompt


def test_provisioning_rejects_invalid_input(migrated_database):
    valid = {"slug": "acme-energy", "name": "Acme Energy", "email": "jane@example.com", "password": "correct-password-123", "owner_name": "Jane Smith"}
    for field, value in (("slug", "Not A Slug"), ("email", "not-an-email"), ("password", "short"), ("name", "x"), ("owner_name", "x")):
        with pytest.raises(ValueError):
            provisioning.provision(**{**valid, field: value})
    assert owners() == []


def test_startup_on_an_empty_database_never_blocks_or_prompts(migrated_database):
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok", "admin_seeded": False}
        assert client.post("/api/v1/auth/login", json={"organization": "acme-energy", "email": "jane@example.com", "password": "correct-password-123"}).status_code == 401
    assert owners() == []
