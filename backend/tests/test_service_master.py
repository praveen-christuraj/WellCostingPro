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
            permissions = [
                Permission(organization_id=organization.id, key=key, description=key)
                for key in MASTER_DATA_PERMISSIONS + ["audit:read"]
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


def create_vendor(
    client: TestClient,
    headers: dict[str, str],
    code: str = "VEND-01",
    *,
    category: str = "Completions",
) -> dict:
    response = client.post(
        "/api/v1/master-data/vendors",
        headers=headers,
        json={
            "vendor_code": code,
            "vendor_name": f"{code} Service Partner",
            "category": category,
            "status": "active",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_service(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "Cement Bond Logging",
    category: str = "Drilling Services",
    provider: str = "In House",
    vendor_id: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/master-data/services",
        headers=headers,
        json={
            "service_name": name,
            "service_category": category,
            "provider_type": provider,
            "vendor_id": vendor_id,
            "description": "Service master test record",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_services_are_tenant_scoped_and_validate_category_provider_and_vendor():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        vendor = create_vendor(client, north)
        south_vendor = create_vendor(client, south, "SOUTH-01")

        created = create_service(
            client,
            north,
            name="Wireline Cased Hole Evaluation",
            category="Completion services",
            provider="3rd Party",
            vendor_id=vendor["id"],
        )
        assert created["service_code"] == "SVC-0001"
        assert created["service_category"] == "Completion Services"
        assert created["provider_type"] == "Third Party Services"
        assert created["vendor_code"] == vendor["vendor_code"]
        assert client.get("/api/v1/master-data/services", headers=north).json()[0]["id"] == created["id"]
        assert client.get("/api/v1/master-data/services", headers=south).json() == []
        assert client.get(f"/api/v1/master-data/services/{created['id']}", headers=south).status_code == 404

        # A vendor ID from another workspace is not a valid provider assignment.
        cross_tenant_vendor = client.post(
            "/api/v1/master-data/services",
            headers=north,
            json={
                "service_name": "Foreign Vendor Service",
                "service_category": "Drilling Services",
                "provider_type": "Third Party",
                "vendor_id": south_vendor["id"],
            },
        )
        assert cross_tenant_vendor.status_code == 422

        missing_provider = client.post(
            "/api/v1/master-data/services",
            headers=north,
            json={
                "service_name": "Unassigned External Service",
                "service_category": "Drilling Services",
                "provider_type": "Third Party",
            },
        )
        assert missing_provider.status_code == 422
        invalid_category = client.post(
            "/api/v1/master-data/services",
            headers=north,
            json={
                "service_name": "Invalid Category Service",
                "service_category": "Well Services",
                "provider_type": "In House",
            },
        )
        assert invalid_category.status_code == 422

        duplicate_name = client.post(
            "/api/v1/master-data/services",
            headers=north,
            json={
                "service_name": "wireline cased hole evaluation",
                "service_category": "Drilling Services",
                "provider_type": "In House",
            },
        )
        assert duplicate_name.status_code == 409

        internal = create_service(client, north, name="Internal Wellsite Support")
        assert internal["service_code"] == "SVC-0002"
        updated = client.patch(
            f"/api/v1/master-data/services/{created['id']}",
            headers=north,
            json={"provider_type": "In House", "vendor_id": None, "service_category": "Drilling"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["provider_type"] == "In House Services"
        assert updated.json()["vendor_id"] is None
        assert updated.json()["service_category"] == "Drilling Services"

        summary = client.get("/api/v1/master-data/services/overview", headers=north)
        assert summary.status_code == 200, summary.text
        stats = summary.json()
        assert stats["active_count"] == 2
        assert next(item["count"] for item in stats["category_counts"] if item["key"] == "Drilling Services") == 2
        assert next(item["count"] for item in stats["provider_type_counts"] if item["key"] == "In House Services") == 2

        # Service numbering is workspace-local, just like each master-data code.
        south_service = create_service(client, south, name="South Service")
        assert south_service["service_code"] == "SVC-0001"


def test_services_soft_delete_restore_bulk_actions_and_audit_are_scoped():
    with TestClient(app) as client:
        headers = login(client)
        first = create_service(client, headers, name="Rig Inspection")
        second = create_service(client, headers, name="Mud Logging")

        duplicate_ids = client.post(
            "/api/v1/master-data/services/bulk-delete",
            headers=headers,
            json={"ids": [first["id"], first["id"]]},
        )
        assert duplicate_ids.status_code == 422
        assert client.post(
            "/api/v1/master-data/services/bulk-permanent-delete",
            headers=headers,
            json={"ids": [first["id"]]},
        ).status_code == 409

        removed = client.delete(f"/api/v1/master-data/services/{first['id']}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert removed.json()["is_deleted"] is True
        assert client.get("/api/v1/master-data/services", headers=headers).json()[0]["id"] == second["id"]
        assert client.get("/api/v1/master-data/services/deleted", headers=headers).json()[0]["id"] == first["id"]

        restored = client.post(f"/api/v1/master-data/services/{first['id']}/restore", headers=headers)
        assert restored.status_code == 200, restored.text
        assert restored.json()["is_deleted"] is False

        bulk = client.post(
            "/api/v1/master-data/services/bulk-delete",
            headers=headers,
            json={"ids": [first["id"], second["id"]]},
        )
        assert bulk.status_code == 200, bulk.text
        assert bulk.json()["affected_count"] == 2
        bulk_restore = client.post(
            "/api/v1/master-data/services/bulk-restore",
            headers=headers,
            json={"ids": [first["id"], second["id"]]},
        )
        assert bulk_restore.status_code == 200
        assert bulk_restore.json()["affected_count"] == 2

        # Only a deleted row can be purged.
        assert client.delete(
            f"/api/v1/master-data/services/{first['id']}/permanent", headers=headers
        ).status_code == 409
        assert client.delete(f"/api/v1/master-data/services/{first['id']}", headers=headers).status_code == 200
        assert client.delete(
            f"/api/v1/master-data/services/{first['id']}/permanent", headers=headers
        ).status_code == 204

        audit_response = client.get("/api/v1/audit?entity_type=service", headers=headers)
        assert audit_response.status_code == 200
        actions = {entry["action"] for entry in audit_response.json()["items"]}
        assert {"create", "soft_delete", "restore", "permanent_delete"}.issubset(actions)
        export = client.post(
            "/api/v1/master-data/export-audit",
            headers=headers,
            json={"module": "services", "format": "xlsx", "record_count": 1},
        )
        assert export.status_code == 204, export.text

        overview = client.get("/api/v1/master-data/overview", headers=headers).json()
        assert overview["module_count"] == 8
        services_stat = next(item for item in overview["modules"] if item["key"] == "services")
        assert services_stat["active_count"] == 1
        assert services_stat["deleted_count"] == 0


def test_service_import_accepts_legacy_provider_labels_and_restores_by_name():
    with TestClient(app) as client:
        headers = login(client)
        vendor = create_vendor(client, headers, "COMPLETIONS-01")
        imported = client.post(
            "/api/v1/master-data/services/import",
            headers=headers,
            json={
                "rows": [
                    {
                        "service_name": "Completion Wireline",
                        "service_category": "Completion Services",
                        "provider_type": "3rd Party",
                        "vendor_code": vendor["vendor_code"],
                        "description": "Third-party intervention crew",
                    },
                    {
                        "service_name": "Internal Rig Maintenance",
                        "provider_type": "Inhouse",
                        "description": "Scheduled internal maintenance",
                    },
                    {
                        "service_name": "Missing External Vendor",
                        "service_category": "Drilling Services",
                        "provider_type": "Third Party",
                    },
                ]
            },
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported_count"] == 2
        assert imported.json()["error_count"] == 1
        assert "vendor_code" in imported.json()["errors"][0].lower() or "provider" in imported.json()["errors"][0].lower()

        active = client.get("/api/v1/master-data/services", headers=headers).json()
        completion = next(item for item in active if item["service_name"] == "Completion Wireline")
        internal = next(item for item in active if item["service_name"] == "Internal Rig Maintenance")
        assert completion["service_category"] == "Completion Services"
        assert completion["provider_type"] == "Third Party Services"
        assert completion["vendor_code"] == vendor["vendor_code"]
        assert internal["service_category"] == "Drilling Services"  # legacy imports default to drilling
        original_code = internal["service_code"]

        assert client.delete(f"/api/v1/master-data/services/{internal['id']}", headers=headers).status_code == 200
        update = client.post(
            "/api/v1/master-data/services/import",
            headers=headers,
            json={
                "rows": [{
                    "service_name": "Internal Rig Maintenance",
                    "service_category": "Completion",
                    "provider_type": "Internal",
                    "description": "Updated internal scope",
                }]
            },
        )
        assert update.status_code == 200, update.text
        assert update.json()["imported_count"] == 1
        restored = next(
            item for item in client.get("/api/v1/master-data/services", headers=headers).json()
            if item["service_name"] == "Internal Rig Maintenance"
        )
        assert restored["service_code"] == original_code
        assert restored["service_category"] == "Completion Services"
        assert restored["provider_type"] == "In House Services"
        assert restored["description"] == "Updated internal scope"
        assert restored["is_deleted"] is False

        # Every committed import is represented in the typed audit trail.
        with SessionLocal() as db:
            organization = db.scalar(select(Organization).where(Organization.slug == "north"))
            entries = db.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == organization.id,
                    AuditLog.entity_type == "service",
                )
            ).all()
        assert any(entry.action == "import" for entry in entries)
        assert any("Restored and updated service" in entry.summary for entry in entries)


def test_vendor_lifecycle_protects_service_assignments_and_completion_category():
    with TestClient(app) as client:
        headers = login(client)
        vendor = create_vendor(client, headers, category="Completions")
        assert vendor["category"] == "Completions"
        option = client.get("/api/v1/master-data/vendors/options", headers=headers).json()[0]
        assert option["id"] == vendor["id"]

        service = create_service(
            client,
            headers,
            name="Completion Cementing Support",
            category="Completion Services",
            provider="Third Party",
            vendor_id=vendor["id"],
        )
        blocked_delete = client.delete(f"/api/v1/master-data/vendors/{vendor['id']}", headers=headers)
        assert blocked_delete.status_code == 409
        assert "active service" in blocked_delete.json()["detail"]

        assert client.delete(f"/api/v1/master-data/services/{service['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/master-data/vendors/{vendor['id']}", headers=headers).status_code == 200
        purge_vendor_early = client.delete(
            f"/api/v1/master-data/vendors/{vendor['id']}/permanent", headers=headers
        )
        assert purge_vendor_early.status_code == 409
        assert "service" in purge_vendor_early.json()["detail"].lower()

        restore_service_early = client.post(
            f"/api/v1/master-data/services/{service['id']}/restore", headers=headers
        )
        assert restore_service_early.status_code == 409
        assert client.post(f"/api/v1/master-data/vendors/{vendor['id']}/restore", headers=headers).status_code == 200
        assert client.post(f"/api/v1/master-data/services/{service['id']}/restore", headers=headers).status_code == 200

        assert client.delete(f"/api/v1/master-data/services/{service['id']}", headers=headers).status_code == 200
        assert client.delete(
            f"/api/v1/master-data/services/{service['id']}/permanent", headers=headers
        ).status_code == 204
        assert client.delete(f"/api/v1/master-data/vendors/{vendor['id']}", headers=headers).status_code == 200
        assert client.delete(
            f"/api/v1/master-data/vendors/{vendor['id']}/permanent", headers=headers
        ).status_code == 204


def test_service_endpoints_enforce_master_data_rbac():
    with TestClient(app) as client:
        owner_headers = login(client)
        service = create_service(client, owner_headers, name="RBAC Test Service")
        with SessionLocal() as db:
            organization = db.scalar(select(Organization).where(Organization.slug == "north"))
            read_permission = db.scalar(
                select(Permission).where(
                    Permission.organization_id == organization.id,
                    Permission.key == "master-data:read",
                )
            )
            role = Role(
                organization_id=organization.id,
                name="Service Reader",
                permissions=[read_permission],
            )
            reader = User(
                organization_id=organization.id,
                email="reader@example.com",
                full_name="Service Reader",
                password_hash=hash_password("correct-password-123"),
                roles=[role],
            )
            db.add(reader)
            db.commit()
        reader_login = client.post(
            "/api/v1/auth/login",
            json={"organization": "north", "email": "reader@example.com", "password": "correct-password-123"},
        )
        assert reader_login.status_code == 200, reader_login.text
        reader_headers = {"Authorization": f"Bearer {reader_login.json()['access_token']}"}

        assert client.get("/api/v1/master-data/services", headers=reader_headers).status_code == 200
        assert client.get("/api/v1/master-data/services/overview", headers=reader_headers).status_code == 200
        assert client.post(
            "/api/v1/master-data/services",
            headers=reader_headers,
            json={"service_name": "Forbidden", "service_category": "Drilling Services", "provider_type": "In House"},
        ).status_code == 403
        assert client.patch(
            f"/api/v1/master-data/services/{service['id']}",
            headers=reader_headers,
            json={"description": "Forbidden"},
        ).status_code == 403
        assert client.delete(
            f"/api/v1/master-data/services/{service['id']}", headers=reader_headers
        ).status_code == 403
        assert client.post(
            "/api/v1/master-data/services/import",
            headers=reader_headers,
            json={"rows": [{"service_name": "Forbidden", "provider_type": "In House"}]},
        ).status_code == 403
