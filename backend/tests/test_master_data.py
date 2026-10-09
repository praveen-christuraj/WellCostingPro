import os
import tempfile

# Set the database before importing app modules (the engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User


MASTER_DATA_PERMISSIONS = [
    "master-data:read",
    "master-data:create",
    "master-data:update",
    "master-data:delete",
    "master-data:restore",
    "master-data:permanent-delete",
    "master-data:import",
    "master-data:export",
]


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for slug in ("north", "south"):
            organization = Organization(slug=slug, name=f"{slug.title()} Energy")
            db.add(organization)
            db.flush()
            permission_keys = MASTER_DATA_PERMISSIONS + ["audit:read"]
            permissions = [
                Permission(organization_id=organization.id, key=key, description=key)
                for key in permission_keys
            ]
            owner_role = Role(
                organization_id=organization.id,
                name="Owner",
                is_owner=True,
                permissions=permissions,
            )
            db.add(
                User(
                    organization_id=organization.id,
                    email="owner@example.com",
                    full_name="Test Owner",
                    password_hash=hash_password("correct-password-123"),
                    roles=[owner_role],
                )
            )
        db.commit()
    yield


def login(client: TestClient, organization: str = "north") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "organization": organization,
            "email": "owner@example.com",
            "password": "correct-password-123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_all_five_reference_master_data_types_use_the_common_contract_and_tenant_scope():
    payloads = [
        ("uom", {"code": "bbl", "name": "Barrel", "symbol": "bbl"}, "BBL", "bbl"),
        ("currencies", {"code": "usd", "name": "US Dollar", "symbol": "$"}, "USD", "$"),
        ("phases", {"code": "drill", "name": "Drilling"}, "DRILL", None),
        ("hole-sections", {"code": "17-1/2", "name": "Surface hole"}, "17-1/2", None),
        ("activities", {"code": "drill", "name": "Drilling activity"}, "DRILL", None),
    ]
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        for module, data, normalized_code, symbol in payloads:
            created = client.post(f"/api/v1/master-data/{module}", headers=north, json=data)
            assert created.status_code == 201, created.text
            assert created.json()["code"] == normalized_code
            assert created.json()["symbol"] == symbol
            assert created.json()["is_deleted"] is False
            assert client.get(f"/api/v1/master-data/{module}", headers=north).json()[0]["id"] == created.json()["id"]
            assert client.get(f"/api/v1/master-data/{module}", headers=south).json() == []
            # Codes are unique inside a workspace, not across the whole platform.
            same_code_in_south = client.post(f"/api/v1/master-data/{module}", headers=south, json=data)
            assert same_code_in_south.status_code == 201
            assert client.delete(
                f"/api/v1/master-data/{module}/{created.json()['id']}", headers=south
            ).status_code == 404


def test_crud_soft_delete_restore_and_permanent_delete_are_audited():
    with TestClient(app) as client:
        headers = login(client)
        created = client.post(
            "/api/v1/master-data/uom",
            headers=headers,
            json={"code": "m", "name": "Metre", "symbol": "m", "description": "Length"},
        )
        assert created.status_code == 201, created.text
        record = created.json()
        record_id = record["id"]
        assert record["code"] == "M"
        assert record["description"] == "Length"

        updated = client.patch(
            f"/api/v1/master-data/uom/{record_id}",
            headers=headers,
            json={"name": "Meter", "symbol": "metre"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Meter"

        removed = client.delete(f"/api/v1/master-data/uom/{record_id}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert removed.json()["is_deleted"] is True
        assert removed.json()["deleted_at"]
        assert client.get("/api/v1/master-data/uom", headers=headers).json() == []
        assert len(client.get("/api/v1/master-data/uom/deleted", headers=headers).json()) == 1
        assert client.patch(
            f"/api/v1/master-data/uom/{record_id}",
            headers=headers,
            json={"name": "Edited in trash"},
        ).json()["is_deleted"] is True
        duplicate = client.post(
            "/api/v1/master-data/uom",
            headers=headers,
            json={"code": "M", "name": "Duplicate", "symbol": "m"},
        )
        assert duplicate.status_code == 409

        restored = client.post(f"/api/v1/master-data/uom/{record_id}/restore", headers=headers)
        assert restored.status_code == 200, restored.text
        assert restored.json()["is_deleted"] is False
        assert client.get("/api/v1/master-data/uom/deleted", headers=headers).json() == []
        assert client.delete(
            f"/api/v1/master-data/uom/{record_id}/permanent", headers=headers
        ).status_code == 409

        assert client.delete(f"/api/v1/master-data/uom/{record_id}", headers=headers).status_code == 200
        assert client.delete(
            f"/api/v1/master-data/uom/{record_id}/permanent", headers=headers
        ).status_code == 204
        assert client.get("/api/v1/master-data/uom/deleted", headers=headers).json() == []

        events = client.get("/api/v1/audit?entity_type=master_data", headers=headers)
        assert events.status_code == 200, events.text
        actions = {entry["action"] for entry in events.json()["items"]}
        assert {"create", "update", "soft_delete", "restore", "permanent_delete"}.issubset(actions)
        exported = client.post(
            "/api/v1/master-data/export-audit",
            headers=headers,
            json={"module": "uom", "format": "pdf", "record_count": 0},
        )
        assert exported.status_code == 204, exported.text
        events = client.get("/api/v1/audit?entity_type=master_data&action=export", headers=headers)
        assert events.status_code == 200 and events.json()["items"]


def test_bulk_selection_actions_validate_all_ids_and_never_permanently_delete_active_rows():
    with TestClient(app) as client:
        headers = login(client)
        ids = []
        for code in ("A1", "A2", "A3"):
            response = client.post(
                "/api/v1/master-data/activities",
                headers=headers,
                json={"code": code, "name": f"Activity {code}"},
            )
            assert response.status_code == 201, response.text
            ids.append(response.json()["id"])

        duplicate_ids = client.post(
            "/api/v1/master-data/activities/bulk-delete",
            headers=headers,
            json={"ids": [ids[0], ids[0]]},
        )
        assert duplicate_ids.status_code == 422
        assert client.post(
            "/api/v1/master-data/activities/bulk-permanent-delete",
            headers=headers,
            json={"ids": [ids[0]]},
        ).status_code == 409

        deleted = client.post(
            "/api/v1/master-data/activities/bulk-delete",
            headers=headers,
            json={"ids": ids[:2]},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["affected_count"] == 2
        assert len(client.get("/api/v1/master-data/activities", headers=headers).json()) == 1
        assert len(client.get("/api/v1/master-data/activities/deleted", headers=headers).json()) == 2

        restored = client.post(
            "/api/v1/master-data/activities/bulk-restore",
            headers=headers,
            json={"ids": ids[:2]},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["affected_count"] == 2
        assert client.post(
            "/api/v1/master-data/activities/bulk-delete",
            headers=headers,
            json={"ids": [ids[0]]},
        ).status_code == 200
        purged = client.post(
            "/api/v1/master-data/activities/bulk-permanent-delete",
            headers=headers,
            json={"ids": [ids[0]]},
        )
        assert purged.status_code == 200, purged.text
        assert purged.json()["affected_count"] == 1
        assert client.delete(
            f"/api/v1/master-data/activities/{ids[2]}", headers=headers
        ).status_code == 200


def test_deleted_entries_bulk_actions_span_modules_without_partial_purges():
    with TestClient(app) as client:
        headers = login(client)
        selections = []
        for module, payload in (
            ("uom", {"code": "M", "name": "Metre", "symbol": "m"}),
            ("phases", {"code": "DRILL", "name": "Drilling"}),
        ):
            created = client.post(f"/api/v1/master-data/{module}", headers=headers, json=payload)
            assert created.status_code == 201, created.text
            record_id = created.json()["id"]
            assert client.delete(f"/api/v1/master-data/{module}/{record_id}", headers=headers).status_code == 200
            selections.append({"module": module, "id": record_id})

        restored = client.post(
            "/api/v1/master-data/bulk-restore",
            headers=headers,
            json={"records": selections},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["affected_count"] == 2
        assert client.delete(f"/api/v1/master-data/uom/{selections[0]['id']}", headers=headers).status_code == 200
        mixed_state = client.post(
            "/api/v1/master-data/bulk-permanent-delete",
            headers=headers,
            json={"records": selections},
        )
        assert mixed_state.status_code == 409
        assert len(client.get("/api/v1/master-data/uom/deleted", headers=headers).json()) == 1
        assert len(client.get("/api/v1/master-data/phases", headers=headers).json()) == 1

        assert client.delete(f"/api/v1/master-data/phases/{selections[1]['id']}", headers=headers).status_code == 200
        purged = client.post(
            "/api/v1/master-data/bulk-permanent-delete",
            headers=headers,
            json={"records": selections},
        )
        assert purged.status_code == 200, purged.text
        assert purged.json()["affected_count"] == 2
        assert client.get("/api/v1/master-data/uom/deleted", headers=headers).json() == []
        assert client.get("/api/v1/master-data/phases/deleted", headers=headers).json() == []


def test_import_is_upsert_compatible_row_aware_and_tenant_scoped():
    with TestClient(app) as client:
        headers = login(client)
        imported = client.post(
            "/api/v1/master-data/currencies/import",
            headers=headers,
            json={
                "rows": [
                    {"code": "", "name": "Missing code", "symbol": "?"},
                    {"code": "usd", "name": "US Dollar", "symbol": "$", "description": "USD"},
                    {"code": "eur", "name": "Euro", "symbol": "€"},
                    {"code": "EUR", "name": "Duplicate in file", "symbol": "E"},
                ]
            },
        )
        assert imported.status_code == 200, imported.text
        result = imported.json()
        assert result["imported_count"] == 2
        assert result["error_count"] == 2
        assert any("Row 1" in error for error in result["errors"])
        assert any("Row 4" in error for error in result["errors"])

        updated = client.post(
            "/api/v1/master-data/currencies/import",
            headers=headers,
            json={"rows": [{"currency_code": "USD", "currency_name": "US Dollar (updated)", "currency_symbol": "$"}]},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["imported_count"] == 1
        usd = next(row for row in client.get("/api/v1/master-data/currencies", headers=headers).json() if row["code"] == "USD")
        assert usd["name"] == "US Dollar (updated)"
        assert len(client.get("/api/v1/master-data/currencies", headers=login(client, "south")).json()) == 0


def test_overview_and_read_permissions_are_workspace_scoped():
    with TestClient(app) as client:
        owner_headers = login(client)
        phase = client.post(
            "/api/v1/master-data/phases",
            headers=owner_headers,
            json={"code": "DRILL", "name": "Drilling"},
        ).json()
        summary = client.get("/api/v1/master-data/overview", headers=owner_headers)
        assert summary.status_code == 200, summary.text
        payload = summary.json()
        assert payload["module_count"] == 5
        assert payload["active_records"] == 1
        assert next(item for item in payload["modules"] if item["key"] == "phases")["active_count"] == 1
        assert payload["recent_activity"]

        with SessionLocal() as db:
            organization = db.scalar(select(Organization).where(Organization.slug == "north"))
            permission = db.scalar(
                select(Permission).where(
                    Permission.organization_id == organization.id,
                    Permission.key == "master-data:read",
                )
            )
            reader_role = Role(
                organization_id=organization.id,
                name="Master Data Reader",
                permissions=[permission],
            )
            reader = User(
                organization_id=organization.id,
                email="reader@example.com",
                full_name="Data Reader",
                password_hash=hash_password("reader-secret-123"),
                roles=[reader_role],
            )
            db.add(reader)
            db.commit()

        reader_login = client.post(
            "/api/v1/auth/login",
            json={"organization": "north", "email": "reader@example.com", "password": "reader-secret-123"},
        )
        reader_headers = {"Authorization": f"Bearer {reader_login.json()['access_token']}"}
        assert client.get("/api/v1/master-data/overview", headers=reader_headers).status_code == 200
        assert client.get("/api/v1/master-data/phases", headers=reader_headers).status_code == 200
        assert client.post(
            "/api/v1/master-data/phases",
            headers=reader_headers,
            json={"code": "COMP", "name": "Completion"},
        ).status_code == 403
        assert client.patch(
            f"/api/v1/master-data/phases/{phase['id']}",
            headers=reader_headers,
            json={"name": "Not allowed"},
        ).status_code == 403
        assert client.delete(
            f"/api/v1/master-data/phases/{phase['id']}", headers=reader_headers
        ).status_code == 403
        assert client.post(
            f"/api/v1/master-data/phases/{phase['id']}/restore", headers=reader_headers
        ).status_code == 403
        assert client.delete(
            f"/api/v1/master-data/phases/{phase['id']}/permanent", headers=reader_headers
        ).status_code == 403
        assert client.post(
            "/api/v1/master-data/phases/import",
            headers=reader_headers,
            json={"rows": [{"code": "COMP", "name": "Completion"}]},
        ).status_code == 403
        assert client.post(
            "/api/v1/master-data/export-audit",
            headers=reader_headers,
            json={"module": "phases", "format": "csv", "record_count": 1},
        ).status_code == 403
