import os
import tempfile

# Use an isolated database for this API suite.
_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import Organization, Permission, Role, User


PERMISSIONS = [
    "master-data:read", "master-data:create", "master-data:update", "master-data:delete",
    "master-data:restore", "master-data:permanent-delete", "master-data:import", "master-data:export",
    "costing-sets:read", "costing-sets:create", "costing-sets:update", "costing-sets:delete",
    "costing-sets:import", "costing-sets:export", "audit:read",
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
                for key in PERMISSIONS
            ]
            owner_role = Role(
                organization_id=organization.id,
                name="Owner",
                is_owner=True,
                permissions=permissions,
            )
            db.add(User(
                organization_id=organization.id,
                email="owner@example.com",
                full_name="Test Owner",
                password_hash=hash_password("correct-password-123"),
                roles=[owner_role],
            ))
        db.commit()
    yield


def login(client: TestClient, organization: str = "north", email: str = "owner@example.com") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"organization": organization, "email": email, "password": "correct-password-123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_vendor(client: TestClient, headers: dict[str, str], code: str = "VEND-01") -> dict:
    response = client.post("/api/v1/master-data/vendors", headers=headers, json={
        "vendor_code": code,
        "vendor_name": f"{code} Service Partner",
        "category": "Drilling",
        "contact_person": "Operations Lead",
        "email": "ops@example.com",
        "phone": "+234 800 000 0000",
        "country": "Nigeria",
        "status": "active",
        "credit_terms_days": 30,
        "description": "Reusable service provider",
    })
    assert response.status_code == 201, response.text
    return response.json()


def create_service(client: TestClient, headers: dict[str, str], vendor_id: str, *, code: str = "MUD-LOG") -> dict:
    response = client.post("/api/v1/master-data/services", headers=headers, json={
        "service_code": code,
        "service_name": f"{code} Service",
        "service_category": "Drilling Services",
        "provider_type": "In House Services",
        "vendor_id": vendor_id,
        "description": "Costing set test service",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_costing_sets_are_private_tenant_scoped_and_keep_stale_item_snapshots():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        north_vendor = create_vendor(client, north)
        south_vendor = create_vendor(client, south)
        service = create_service(client, north, north_vendor["id"])
        south_service = create_service(client, south, south_vendor["id"], code="SOUTH-SVC")

        options = client.get("/api/v1/costing-sets/options?item_group=services", headers=north)
        assert options.status_code == 200, options.text
        assert {item["item_id"] for item in options.json()} == {service["id"]}

        created = client.post("/api/v1/costing-sets", headers=north, json={
            "name": "Night shift package",
            "item_group": "services",
            "description": "Common logging services",
            "items": [{"item_kind": "service", "item_id": service["id"]}],
        })
        assert created.status_code == 201, created.text
        costing_set = created.json()
        assert costing_set["item_count"] == 1
        assert costing_set["items"][0]["is_available"] is True
        assert client.get("/api/v1/costing-sets", headers=south).json() == []
        assert client.get("/api/v1/costing-sets", headers=north).json()[0]["id"] == costing_set["id"]

        # Sets are private even to another user inside the same organization.
        with SessionLocal() as db:
            organization = db.query(Organization).filter_by(slug="north").one()
            permission = db.query(Permission).filter_by(
                organization_id=organization.id, key="costing-sets:read",
            ).one()
            role = Role(organization_id=organization.id, name="Set reader", permissions=[permission])
            db.add(User(
                organization_id=organization.id,
                email="reader@example.com",
                full_name="Set Reader",
                password_hash=hash_password("correct-password-123"),
                roles=[role],
            ))
            db.commit()
        reader = login(client, "north", "reader@example.com")
        assert client.get("/api/v1/costing-sets", headers=reader).json() == []

        duplicate_name = client.post("/api/v1/costing-sets", headers=north, json={
            "name": "NIGHT SHIFT PACKAGE",
            "item_group": "services",
            "items": [{"item_kind": "service", "item_id": service["id"]}],
        })
        assert duplicate_name.status_code == 409
        foreign_item = client.post("/api/v1/costing-sets", headers=north, json={
            "name": "Foreign item",
            "item_group": "services",
            "items": [{"item_kind": "service", "item_id": south_service["id"]}],
        })
        assert foreign_item.status_code == 422
        wrong_group = client.post("/api/v1/costing-sets", headers=north, json={
            "name": "Wrong group",
            "item_group": "tangibles",
            "items": [{"item_kind": "service", "item_id": service["id"]}],
        })
        assert wrong_group.status_code == 422

        # A deleted master-data item remains visible as unavailable; the set can
        # retain its snapshot, and the item can still follow its normal purge path.
        assert client.delete(f"/api/v1/master-data/services/{service['id']}", headers=north).status_code == 200
        update_payload = {
            "name": costing_set["name"],
            "item_group": "services",
            "description": costing_set["description"],
            "items": [{"item_kind": "service", "item_id": service["id"]}],
        }
        updated = client.put(f"/api/v1/costing-sets/{costing_set['id']}", headers=north, json=update_payload)
        assert updated.status_code == 200, updated.text
        assert updated.json()["items"][0]["is_available"] is False
        assert client.delete(f"/api/v1/master-data/services/{service['id']}/permanent", headers=north).status_code == 204
        stale_set = client.get("/api/v1/costing-sets", headers=north).json()[0]
        assert stale_set["items"][0]["item_code"] == service["service_code"]
        assert stale_set["items"][0]["item_id"] == service["id"]
        assert stale_set["items"][0]["is_available"] is False

        # Editing a set after a permanent purge must retain its original
        # polymorphic item id rather than replacing it with the snapshot row id.
        stale_update = client.put(f"/api/v1/costing-sets/{costing_set['id']}", headers=north, json={
            **update_payload,
            "name": "Night shift package revised",
            "description": "Keep the unavailable historical shortcut",
        })
        assert stale_update.status_code == 200, stale_update.text
        retained_item = stale_update.json()["items"][0]
        assert retained_item["item_id"] == service["id"]
        assert retained_item["item_code"] == service["service_code"]
        assert retained_item["is_available"] is False

        assert client.delete(f"/api/v1/costing-sets/{costing_set['id']}", headers=north).status_code == 204
        assert client.get("/api/v1/costing-sets", headers=north).json() == []
