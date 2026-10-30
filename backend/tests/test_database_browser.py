import os
import tempfile

# Set the database before importing app modules (engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from app.core.database import Base, SessionLocal, engine
from app.core.migrations import alembic_config
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User
from app.services import provisioning
from app.services.database_browser import (
    HIDDEN_TABLES,
    _csv_cell,
    browsable_tables,
    is_hidden_column,
    module_group,
)

PASSWORD = "correct-password-123"
BROWSE = ["database-browser:read"]
EXPORT = ["database-browser:read", "database-browser:export"]


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        north = Organization(slug="north", name="North Energy")
        south = Organization(slug="south", name="South Energy")
        db.add_all([north, south])
        db.flush()
        keys = ["audit:read", *BROWSE, "database-browser:export"]
        owner_role = Role(organization_id=north.id, name="Owner", is_owner=True, permissions=[Permission(organization_id=north.id, key=key, description=key) for key in keys])
        db.add(User(organization_id=north.id, email="owner@example.com", full_name="North Owner", password_hash=hash_password(PASSWORD), roles=[owner_role]))
        # A second tenant with its own user, role and grants, which must never appear for north.
        south_role = Role(organization_id=south.id, name="Analyst", permissions=[Permission(organization_id=south.id, key="database-browser:read", description="read")])
        db.add(User(organization_id=south.id, email="other@example.com", full_name="South Person", password_hash=hash_password("other-password-123"), roles=[south_role]))
        db.commit()
    yield
    Base.metadata.drop_all(bind=engine)


def login(client, email="owner@example.com", organization="north", password=PASSWORD):
    response = client.post("/api/v1/auth/login", json={"organization": organization, "email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def grant(email, keys, organization_slug="north"):
    """Give ``email`` a fresh role carrying exactly ``keys`` (a non-owner role)."""
    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == organization_slug))
        user = db.scalar(select(User).where(User.email == email, User.organization_id == org.id))
        permissions = []
        for key in keys:
            permission = db.scalar(select(Permission).where(Permission.organization_id == org.id, Permission.key == key))
            if permission is None:
                permission = Permission(organization_id=org.id, key=key, description=key)
                db.add(permission)
            permissions.append(permission)
        role = Role(organization_id=org.id, name=f"Role {len(user.roles)} {email}", permissions=permissions)
        user.roles = [*user.roles, role]
        db.commit()


def add_user(email, organization_slug="north"):
    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == organization_slug))
        db.add(User(organization_id=org.id, email=email, full_name=email.split("@")[0].title(), password_hash=hash_password(PASSWORD)))
        db.commit()


def audit_actions():
    with SessionLocal() as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.entity_type == "database_browser")).all())


# --- catalogue and tenant isolation ---------------------------------------------------

def test_catalogue_lists_workspace_tables_with_tenant_row_counts():
    with TestClient(app) as client:
        headers = login(client)
        catalogue = client.get("/api/v1/database-browser/tables", headers=headers).json()
        names = {item["name"]: item for item in catalogue["items"]}
        assert {"users", "roles", "permissions", "audit_logs", "organizations", "user_roles", "role_permissions"} <= set(names)
        # Internal and session-secret tables never appear.
        assert HIDDEN_TABLES.isdisjoint(names)
        # The workspace only counts its own users, even though the database holds two tenants.
        assert names["users"]["row_count"] == 1
        assert names["organizations"]["row_count"] == 1
        assert names["roles"]["row_count"] == 1
        assert names["user_roles"]["row_count"] == 1
        assert names["users"]["scope"] == "organization_id"
        assert catalogue["excluded_tables"] >= 1  # refresh_sessions is reflected but never shown
        assert catalogue["hidden_columns"] > 0


def test_child_tables_are_scoped_through_their_foreign_keys():
    scope = browsable_tables(engine)
    assert scope["user_roles"].scope_label.startswith("user_id")
    assert "→" in scope["role_permissions"].scope_label
    with TestClient(app) as client:
        headers = login(client)
        rows = client.get("/api/v1/database-browser/tables/role_permissions/rows", headers=headers).json()
        roles_seen = {row["role_id"] for row in rows["items"]}
        with SessionLocal() as db:
            south_role = db.scalar(select(Role).where(Role.name == "Analyst"))
        assert south_role.id not in roles_seen
        assert rows["total"] == len(rows["items"]) > 0


def test_rows_never_include_other_tenants_or_credentials():
    with TestClient(app) as client:
        headers = login(client)
        rows = client.get("/api/v1/database-browser/tables/users/rows", headers=headers).json()
        emails = {row["email"] for row in rows["items"]}
        assert emails == {"owner@example.com"}
        assert "password_hash" not in rows["columns"]
        assert all("password_hash" not in row for row in rows["items"])
        assert not {"failed_logins", "locked_until", "token_version"} & set(rows["columns"])


def test_structure_describes_columns_keys_and_indexes_without_secrets():
    with TestClient(app) as client:
        headers = login(client)
        structure = client.get("/api/v1/database-browser/tables/user_roles/structure", headers=headers).json()
        columns = {column["name"]: column for column in structure["columns"]}
        assert set(columns) == {"user_id", "role_id"}
        assert columns["user_id"]["primary_key"] and columns["user_id"]["foreign_key"] == "users.id"
        assert columns["role_id"]["foreign_key"] == "roles.id"
        assert columns["user_id"]["kind"] == "text"
        users = client.get("/api/v1/database-browser/tables/users/structure", headers=headers).json()
        names = [column["name"] for column in users["columns"]]
        assert "password_hash" not in names and "email" in names
        assert users["hidden_columns"] >= 1
        kinds = {column["name"]: column["kind"] for column in users["columns"]}
        assert kinds["is_active"] == "boolean" and kinds["created_at"] == "date"
        assert any(index["unique"] for index in users["indexes"])


@pytest.mark.parametrize("name", ["refresh_sessions", "alembic_version", "sqlite_master", "users;DROP TABLE users", "../users", "nope"])
def test_unknown_or_hidden_tables_are_not_found(name):
    with TestClient(app) as client:
        headers = login(client)
        for suffix in ("structure", "rows", "download.csv"):
            response = client.get(f"/api/v1/database-browser/tables/{name}/{suffix}", headers=headers)
            assert response.status_code in (404, 422), (name, suffix, response.status_code)
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "owner@example.com")) is not None


def test_row_preview_is_capped_and_reports_truncation():
    with TestClient(app) as client:
        headers = login(client)
        add_user("second@example.com")
        page = client.get("/api/v1/database-browser/tables/users/rows?limit=1", headers=headers).json()
        assert page["shown"] == 1 and len(page["items"]) == 1
        assert page["total"] == 2 and page["truncated"] is True
        assert client.get("/api/v1/database-browser/tables/users/rows?limit=99999", headers=headers).status_code == 422


# --- permissions ----------------------------------------------------------------------

def test_requires_authentication_and_the_read_permission():
    with TestClient(app) as client:
        assert client.get("/api/v1/database-browser/tables").status_code == 401
        add_user("plain@example.com")
        headers = login(client, email="plain@example.com")
        assert client.get("/api/v1/database-browser/tables", headers=headers).status_code == 403
        assert client.get("/api/v1/database-browser/tables/users/rows", headers=headers).status_code == 403


def test_read_only_grant_cannot_download_or_export():
    add_user("reader@example.com")
    grant("reader@example.com", BROWSE)
    with TestClient(app) as client:
        headers = login(client, email="reader@example.com")
        assert client.get("/api/v1/database-browser/tables/users/rows", headers=headers).status_code == 200
        assert client.get("/api/v1/database-browser/tables/users/download.csv", headers=headers).status_code == 403
        assert client.post("/api/v1/database-browser/export-audit", headers=headers, json={"scope": "catalogue", "format": "csv", "record_count": 1}).status_code == 403


def test_other_tenant_grants_do_not_open_this_workspace():
    with TestClient(app) as client:
        headers = login(client, email="other@example.com", organization="south", password="other-password-123")
        rows = client.get("/api/v1/database-browser/tables/users/rows", headers=headers).json()
        assert {row["email"] for row in rows["items"]} == {"other@example.com"}
        assert "owner@example.com" not in str(rows)


# --- exports and audit trail ----------------------------------------------------------

def test_full_csv_download_is_scoped_audited_and_safe():
    add_user("colleague@example.com")
    with TestClient(app) as client:
        headers = login(client)
        response = client.get("/api/v1/database-browser/tables/users/download.csv", headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert 'filename="users.csv"' in response.headers["content-disposition"]
        body = response.content.decode("utf-8-sig")
        lines = body.strip().splitlines()
        assert "password_hash" not in lines[0]
        assert "owner@example.com" in body and "colleague@example.com" in body
        assert "other@example.com" not in body and "South Person" not in body
        exports = [entry for entry in audit_actions() if entry.action == "export" and entry.entity_label == "users"]
        assert exports and "Downloaded full table users as CSV" in exports[-1].summary
        assert exports[-1].actor_email == "owner@example.com"


def test_export_audit_records_grid_structure_and_catalogue_exports():
    with TestClient(app) as client:
        headers = login(client)
        assert client.post("/api/v1/database-browser/export-audit", headers=headers, json={"scope": "rows", "format": "xlsx", "record_count": 1, "table": "users"}).status_code == 204
        assert client.post("/api/v1/database-browser/export-audit", headers=headers, json={"scope": "structure", "format": "pdf", "record_count": 5, "table": "users"}).status_code == 204
        assert client.post("/api/v1/database-browser/export-audit", headers=headers, json={"scope": "catalogue", "format": "csv", "record_count": 9}).status_code == 204
        summaries = [entry.summary for entry in audit_actions()]
        assert "Exported 1 row of users as XLSX (rows)" in summaries
        assert "Exported 5 columns of users as PDF (structure)" in summaries
        assert "Exported 9 tables of Table catalogue as CSV (catalogue)" in summaries


def test_export_audit_rejects_bad_input_and_unknown_tables():
    with TestClient(app) as client:
        headers = login(client)
        bad_format = client.post("/api/v1/database-browser/export-audit", headers=headers, json={"scope": "rows", "format": "exe", "record_count": 1, "table": "users"})
        assert bad_format.status_code == 422
        extra_field = client.post("/api/v1/database-browser/export-audit", headers=headers, json={"scope": "rows", "format": "csv", "record_count": 1, "table": "users", "sql": "DROP"})
        assert extra_field.status_code == 422
        unknown = client.post("/api/v1/database-browser/export-audit", headers=headers, json={"scope": "rows", "format": "csv", "record_count": 1, "table": "refresh_sessions"})
        assert unknown.status_code == 404
        no_table = client.post("/api/v1/database-browser/export-audit", headers=headers, json={"scope": "rows", "format": "csv", "record_count": 1})
        assert no_table.status_code == 422


def test_export_limit_is_enforced_before_streaming(monkeypatch):
    from app.services import database_browser as service
    monkeypatch.setattr(service, "EXPORT_ROW_LIMIT", 0)
    with TestClient(app) as client:
        headers = login(client)
        response = client.get("/api/v1/database-browser/tables/users/download.csv", headers=headers)
        assert response.status_code == 422
        assert "row download limit" in response.json()["detail"]


# --- helpers ----------------------------------------------------------------------------

def test_csv_cells_neutralise_formulas_and_format_values():
    assert _csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _csv_cell("+1") == "'+1"
    assert _csv_cell("plain") == "plain"
    assert _csv_cell(None) == ""
    assert _csv_cell(True) == "true" and _csv_cell(False) == "false"
    assert _csv_cell(-5) == "-5"


def test_hidden_column_rules_and_grouping():
    assert is_hidden_column("password_hash") and is_hidden_column("token_hash") and is_hidden_column("token_version")
    assert not is_hidden_column("email") and not is_hidden_column("created_at")
    assert module_group("daily_cost_entries") == "Daily Cost Management"
    assert module_group("wells") == "Rig & Well Management"
    assert module_group("audit_logs") == "Other Managements"
    assert module_group("brand_new_table") == "Other"


def test_permissions_are_declared_and_owners_receive_them():
    assert provisioning.CAPABILITIES["database-browser"] == ("read", "export")
    with SessionLocal() as db:
        owner = db.scalar(select(Role).where(Role.is_owner.is_(True)))
        keys = {permission.key for permission in owner.permissions}
    assert {"database-browser:read", "database-browser:export"} <= keys


def insert_legacy_owner_sql(organization_id: str, email: str) -> None:
    """A pre-existing owner written with SQL only.

    The test stops at an old revision, so today's ORM models (which carry columns
    that revision has never seen) cannot be used to seed the legacy row.
    """
    import uuid
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, 'Legacy Energy', :slug, CURRENT_TIMESTAMP)"
        ), {"id": organization_id, "slug": f"legacy-{organization_id[:8]}"})
        role_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
        connection.execute(text(
            "INSERT INTO roles (id, organization_id, name, description, is_owner, created_at) "
            "VALUES (:id, :org, 'Owner', '', 1, CURRENT_TIMESTAMP)"
        ), {"id": role_id, "org": organization_id})
        connection.execute(text(
            "INSERT INTO users (id, organization_id, email, full_name, password_hash, is_active, "
            "token_version, failed_logins, locked_until, created_at) "
            "VALUES (:id, :org, :email, 'Legacy Owner', :password, 1, 0, 0, NULL, CURRENT_TIMESTAMP)"
        ), {"id": user_id, "org": organization_id, "email": email, "password": hash_password(PASSWORD)})
        connection.execute(text("INSERT INTO user_roles (user_id, role_id) VALUES (:user, :role)"),
                           {"user": user_id, "role": role_id})


def test_migration_backfills_existing_owners():
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.drop_all(bind=engine)
    command.upgrade(alembic_config(), "9c4f20b8a631")
    legacy_org_id = "legacy-database-browser-org"
    insert_legacy_owner_sql(legacy_org_id, "legacy@example.com")
    command.upgrade(alembic_config(), "head")
    organization = type("Org", (), {"id": legacy_org_id})
    with SessionLocal() as db:
        owner_role = db.scalar(select(Role).where(Role.is_owner.is_(True), Role.name == "Owner", Role.organization_id == organization.id))
        keys = {permission.key for permission in owner_role.permissions}
    assert {"database-browser:read", "database-browser:export"} <= keys
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
