import os
import tempfile

# Set the database before importing app modules (the engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User


RIG_WELL_PERMISSIONS = [
    "rig-well:read",
    "rig-well:create",
    "rig-well:update",
    "rig-well:delete",
    "rig-well:restore",
    "rig-well:permanent-delete",
    "rig-well:import",
    "rig-well:export",
]
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
            permission_keys = RIG_WELL_PERMISSIONS + MASTER_DATA_PERMISSIONS + ["audit:read"]
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


def create_rig(client: TestClient, headers: dict[str, str], code: str = "RIG-01") -> dict:
    response = client.post(
        "/api/v1/rig-well/rigs",
        headers=headers,
        json={"rig_code": code, "rig_name": f"Rig {code}", "remarks": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_well(client: TestClient, headers: dict[str, str], rig_id: str, code: str = "WELL-01") -> dict:
    response = client.post(
        "/api/v1/rig-well/wells",
        headers=headers,
        json={
            "rig_id": rig_id,
            "well_code": code,
            "well_name": f"Well {code}",
            "well_location": "North field",
            "block": "Block A",
            "objective": "Production appraisal",
            "remarks": "",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_activity(client: TestClient, headers: dict[str, str], code: str = "DRILL") -> dict:
    response = client.post(
        "/api/v1/master-data/activities",
        headers=headers,
        json={"code": code, "name": f"{code.title()} operations"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_sub_activity(
    client: TestClient,
    headers: dict[str, str],
    well_id: str,
    activity_id: str,
    code: str = "SA-01",
) -> dict:
    response = client.post(
        "/api/v1/rig-well/sub-activities",
        headers=headers,
        json={
            "well_id": well_id,
            "sub_activity_code": code,
            "sub_activity_name": f"Sub activity {code}",
            "activity_id": activity_id,
            "responsible_party": "Operations team",
            "description": "Execute the planned work step.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_rigs_and_rig_scoped_wells_are_tenant_scoped_and_audited():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        rig = create_rig(client, north, "rig-a")
        assert rig["rig_code"] == "RIG-A"
        assert client.get("/api/v1/rig-well/rigs", headers=north).json()[0]["id"] == rig["id"]
        assert client.get("/api/v1/rig-well/rigs", headers=south).json() == []
        assert client.post(
            "/api/v1/rig-well/rigs",
            headers=north,
            json={"rig_code": "RIG-A", "rig_name": "Duplicate"},
        ).status_code == 409

        well = create_well(client, north, rig["id"])
        assert well["rig_code"] == "RIG-A"
        assert well["rig_name"] == "Rig rig-a"
        assert well["status"] == "active"
        assert client.get("/api/v1/rig-well/wells", headers=north).json()[0]["id"] == well["id"]
        assert client.get("/api/v1/rig-well/wells", headers=south).json() == []
        assert client.post(
            "/api/v1/rig-well/wells",
            headers=south,
            json={
                "rig_id": rig["id"], "well_code": "FOREIGN", "well_name": "Foreign",
                "well_location": "Elsewhere", "block": "X", "objective": "Y",
            },
        ).status_code == 404
        assert client.patch(
            f"/api/v1/rig-well/wells/{well['id']}",
            headers=south,
            json={"well_name": "Cross-tenant edit"},
        ).status_code == 404

        dashboard = client.get("/api/v1/rig-well/overview", headers=north)
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["active_rigs"] == 1
        assert dashboard.json()["active_wells"] == 1
        assert client.post(
            "/api/v1/rig-well/export-audit",
            headers=north,
            json={"module": "wells", "format": "csv", "record_count": 1},
        ).status_code == 204
        with SessionLocal() as db:
            entity_types = {entry.entity_type for entry in db.query(AuditLog).all()}
            assert {"rig", "well", "rig_well_export"}.issubset(entity_types)


def test_configuration_uses_workspace_master_data_and_enforces_lifecycle_and_depth_order():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        hole = client.post(
            "/api/v1/master-data/hole-sections", headers=headers,
            json={"code": "17-1/2", "name": "Surface hole"},
        ).json()
        second_hole = client.post(
            "/api/v1/master-data/hole-sections", headers=headers,
            json={"code": "12-1/4", "name": "Intermediate hole"},
        ).json()
        phase = client.post(
            "/api/v1/master-data/phases", headers=headers,
            json={"code": "DRILL", "name": "Drilling"},
        ).json()
        options = client.get("/api/v1/rig-well/configuration-options", headers=headers)
        assert options.status_code == 200
        assert {item["id"] for item in options.json()["hole_sections"]} == {hole["id"], second_hole["id"]}
        assert options.json()["phases"][0]["id"] == phase["id"]

        def section(hole_id: str, start: str, end: str, days: str) -> dict:
            return {
                "hole_section_id": hole_id,
                "from_depth": start,
                "to_depth": end,
                "remarks": "",
                "phases": [{"phase_id": phase["id"], "days": days, "remarks": ""}],
            }

        payload = {"depth_unit": "m", "sections": [section(hole["id"], "0", "100", "2.5"), section(second_hole["id"], "100", "500", "4")]}
        saved = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        assert saved.json()["total_depth"] == "500"
        assert saved.json()["total_days"] == "6.50"
        assert [item["section_code"] for item in saved.json()["sections"]] == ["17-1/2", "12-1/4"]

        overlapping = {"depth_unit": "m", "sections": [section(hole["id"], "0", "100", "2"), section(second_hole["id"], "99", "500", "4")]}
        invalid = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json=overlapping)
        assert invalid.status_code == 422
        assert "previous section" in invalid.json()["detail"]
        assert client.post(
            f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers,
            json={"action": "configure", "remarks": "Plan checked"},
        ).status_code == 200
        completed = client.post(
            f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers,
            json={"action": "complete", "remarks": "Operations complete"},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "completed"
        lifecycle = client.get("/api/v1/rig-well/overview", headers=headers).json()
        assert lifecycle["active_wells"] == 0
        assert lifecycle["configured_wells"] == 0
        assert lifecycle["completed_wells"] == 1
        locked = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json=payload)
        assert locked.status_code == 409
        assert client.post(
            f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers,
            json={"action": "activate", "remarks": "Restart well"},
        ).status_code == 200
        assert client.post(
            f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers,
            json={"action": "draft", "remarks": "Update plan"},
        ).status_code == 200


def test_sub_activities_are_well_scoped_activity_categorized_and_hierarchical():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        first = create_well(client, headers, rig["id"], "WELL-01")
        second = create_well(client, headers, rig["id"], "WELL-02")
        activity = create_activity(client, headers)
        first_item = create_sub_activity(client, headers, first["id"], activity["id"], "SHARED-CODE")
        second_item = create_sub_activity(client, headers, second["id"], activity["id"], "SHARED-CODE")
        assert first_item["well_code"] == "WELL-01"
        assert first_item["activity_display"].startswith("DRILL")
        assert first_item["id"] != second_item["id"]
        duplicate = client.post(
            "/api/v1/rig-well/sub-activities", headers=headers,
            json={
                "well_id": first["id"], "sub_activity_code": "SHARED-CODE", "sub_activity_name": "Duplicate",
                "activity_id": activity["id"], "responsible_party": "Team", "description": "Details",
            },
        )
        assert duplicate.status_code == 409
        listing = client.get(f"/api/v1/rig-well/sub-activities?well_id={first['id']}", headers=headers)
        assert [item["id"] for item in listing.json()] == [first_item["id"]]
        cross_scope_patch = client.patch(
            f"/api/v1/rig-well/sub-activities/{first_item['id']}?well_id={second['id']}",
            headers=headers, json={"sub_activity_name": "Cross-well edit"},
        )
        assert cross_scope_patch.status_code == 404

        active_child_block = client.delete(f"/api/v1/rig-well/wells/{first['id']}", headers=headers)
        assert active_child_block.status_code == 409
        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{first_item['id']}?well_id={first['id']}", headers=headers
        ).status_code == 200
        assert client.post(
            f"/api/v1/rig-well/sub-activities/{first_item['id']}/restore", headers=headers
        ).status_code == 200
        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{first_item['id']}/permanent", headers=headers
        ).status_code == 409


def test_import_deleted_entries_bulk_restore_and_permanent_purge_are_atomic():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        imported_wells = client.post(
            "/api/v1/rig-well/wells/import", headers=headers,
            json={"rows": [
                {"rig_code": rig["rig_code"], "well_code": "IMPORTED-01", "well_name": "Imported well", "well_location": "North", "block": "A", "objective": "Production"},
                {"rig_code": "MISSING", "well_code": "IMPORTED-02", "well_name": "Bad well", "well_location": "North", "block": "A", "objective": "Production"},
            ]},
        )
        assert imported_wells.status_code == 200, imported_wells.text
        assert imported_wells.json()["imported_count"] == 1
        assert imported_wells.json()["error_count"] == 1
        well = client.get("/api/v1/rig-well/wells", headers=headers).json()[0]
        activity = create_activity(client, headers)
        imported_subs = client.post(
            f"/api/v1/rig-well/sub-activities/import?well_id={well['id']}", headers=headers,
            json={"rows": [{
                "sub_activity_code": "IMPORT-01", "sub_activity_name": "Imported task", "activity": "DRILL",
                "responsible_party": "Team", "description": "Imported details",
            }]},
        )
        assert imported_subs.status_code == 200, imported_subs.text
        assert imported_subs.json()["imported_count"] == 1
        item = client.get(f"/api/v1/rig-well/sub-activities?well_id={well['id']}", headers=headers).json()[0]
        assert item["activity_id"] == activity["id"]

        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{item['id']}?well_id={well['id']}", headers=headers
        ).status_code == 200
        assert client.delete(f"/api/v1/rig-well/wells/{well['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}", headers=headers).status_code == 200
        deleted = client.get("/api/v1/rig-well/deleted", headers=headers)
        assert deleted.status_code == 200
        assert {row["entity_type"] for row in deleted.json()} == {"rig", "well", "well_sub_activity"}
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}/permanent", headers=headers).status_code == 409

        records = [
            {"entity_type": "rig", "id": rig["id"]},
            {"entity_type": "well", "id": well["id"]},
            {"entity_type": "well_sub_activity", "id": item["id"]},
        ]
        restored = client.post("/api/v1/rig-well/deleted/bulk-restore", headers=headers, json={"records": records})
        assert restored.status_code == 200, restored.text
        assert restored.json()["affected_count"] == 3
        assert client.get("/api/v1/rig-well/deleted", headers=headers).json() == []

        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{item['id']}?well_id={well['id']}", headers=headers
        ).status_code == 200
        assert client.delete(f"/api/v1/rig-well/wells/{well['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}", headers=headers).status_code == 200
        purged = client.post(
            "/api/v1/rig-well/deleted/bulk-permanent-delete", headers=headers, json={"records": records}
        )
        assert purged.status_code == 200, purged.text
        assert purged.json()["affected_count"] == 3
        assert client.get("/api/v1/rig-well/deleted", headers=headers).json() == []


def test_rig_well_read_capability_does_not_grant_mutation():
    with TestClient(app) as client:
        headers = login(client)
        create_rig(client, headers, "PRIVATE-AUDIT")
        with SessionLocal() as db:
            organization = db.query(Organization).filter_by(slug="north").one()
            permission = db.query(Permission).filter_by(organization_id=organization.id, key="rig-well:read").one()
            role = Role(organization_id=organization.id, name="Read only", permissions=[permission])
            db.add(User(
                organization_id=organization.id,
                email="reader@example.com",
                full_name="Read Only",
                password_hash=hash_password("correct-password-123"),
                roles=[role],
            ))
            db.commit()
        reader_login = client.post(
            "/api/v1/auth/login",
            json={"organization": "north", "email": "reader@example.com", "password": "correct-password-123"},
        )
        assert reader_login.status_code == 200, reader_login.text
        reader = {"Authorization": f"Bearer {reader_login.json()['access_token']}"}
        overview = client.get("/api/v1/rig-well/overview", headers=reader)
        assert overview.status_code == 200
        assert overview.json()["recent_activity"] == []
        denied = client.post(
            "/api/v1/rig-well/rigs", headers=reader,
            json={"rig_code": "NO-WRITE", "rig_name": "Denied"},
        )
        assert denied.status_code == 403
        assert client.get("/api/v1/rig-well/overview", headers=headers).status_code == 200
