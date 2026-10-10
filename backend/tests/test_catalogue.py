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



def _rate_list(client, headers, path):
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _option(client, headers, list_key, value, parent_id=None):
    payload = {"list_key": list_key, "value": value}
    if parent_id:
        payload["parent_id"] = parent_id
    response = client.post("/api/v1/master-data/catalogue-options", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _seed_masters(client, headers):
    assert client.post("/api/v1/master-data/currencies", headers=headers, json={"code": "usd", "name": "US Dollar", "symbol": "$"}).status_code == 201
    assert client.post("/api/v1/master-data/uom", headers=headers, json={"code": "ea", "name": "Each", "symbol": "ea"}).status_code == 201
    assert client.post("/api/v1/master-data/uom", headers=headers, json={"code": "mt", "name": "Metric tonne", "symbol": "MT"}).status_code == 201


def _tangible_payload(category_id, subcategory_id, manufacturer_id, **overrides):
    payload = {
        "tangible_code": "tng-0001",
        "tangible_name": "Casing centraliser 9-5/8in",
        "scope": "Drilling",
        "category_id": category_id,
        "subcategory_id": subcategory_id,
        "manufacturer_id": manufacturer_id,
        "uom": "ea",
        "po_number": "PO-4500123",
        "unit_rate": "1250",
        "cost_uplift": "120",
        "currency": "usd",
        "effective_date": "2026-01-31",
        "description": "Bow spring",
        "remarks": "",
    }
    payload.update(overrides)
    return payload


def _setup_tangible_lists(client, headers):
    category = _option(client, headers, "tangible_category", "Casing Accessories")
    subcategory = _option(client, headers, "tangible_subcategory", "Centralisers", category["id"])
    manufacturer = _option(client, headers, "manufacturer", "Weatherford")
    return category, subcategory, manufacturer


def test_tangible_code_is_manual_and_final_cost_uses_uplift():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)

        created = client.post(
            "/api/v1/master-data/tangibles",
            headers=headers,
            json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"]),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["tangible_code"] == "TNG-0001"
        assert body["currency"] == "USD"
        assert body["uom"] == "EA"
        assert str(body["final_cost"]) in {"1500", "1500.0000"}
        assert body["category_name"] == "Casing Accessories"
        assert body["subcategory_name"] == "Centralisers"
        assert body["current_revision_number"] == 1

        history = client.get(f"/api/v1/master-data/tangibles/{body['id']}/revisions", headers=headers).json()
        assert len(history) == 1
        assert history[0]["reason"] == "Initial rate"


def test_tangible_code_must_be_supplied_and_is_unique():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)

        missing = _tangible_payload(category["id"], subcategory["id"], manufacturer["id"], tangible_code="")
        assert client.post("/api/v1/master-data/tangibles", headers=headers, json=missing).status_code == 422

        first = client.post("/api/v1/master-data/tangibles", headers=headers, json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"]))
        assert first.status_code == 201
        again = client.post(
            "/api/v1/master-data/tangibles",
            headers=headers,
            json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"], tangible_name="Other name"),
        )
        assert again.status_code == 409
        assert "already exists" in again.json()["detail"]


def test_subcategory_must_belong_to_selected_category():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)
        other_category = _option(client, headers, "tangible_category", "Completion Tools")

        response = client.post(
            "/api/v1/master-data/tangibles",
            headers=headers,
            json=_tangible_payload(other_category["id"], subcategory["id"], manufacturer["id"]),
        )
        assert response.status_code == 422
        assert "must belong to the selected category" in response.json()["detail"]


def test_rates_change_only_through_revisions_with_reason_and_history():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)
        item = client.post("/api/v1/master-data/tangibles", headers=headers, json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"])).json()
        url = f"/api/v1/master-data/tangibles/{item['id']}"

        # Plain edits cannot change the price.
        assert client.patch(url, headers=headers, json={"unit_rate": "999"}).status_code == 422
        assert client.patch(url, headers=headers, json={"cost_uplift": "10"}).status_code == 422

        revise = {"unit_rate": "1300", "cost_uplift": "120", "currency": "USD", "po_number": "PO-4500999", "effective_date": "2026-03-01"}
        assert client.post(f"{url}/revise", headers=headers, json=revise).status_code == 422  # reason missing
        assert client.post(f"{url}/revise", headers=headers, json={**revise, "reason": "x"}).status_code == 422
        assert client.post(f"{url}/revise", headers=headers, json={**revise, "effective_date": "2025-12-01", "reason": "Vendor re-quote"}).status_code == 422
        assert client.post(f"{url}/revise", headers=headers, json={**revise, "effective_date": "2027-01-01", "reason": "Future"}).status_code == 422
        unchanged = {"unit_rate": "1250", "cost_uplift": "120", "currency": "USD", "po_number": "PO-4500123", "effective_date": "2026-03-01", "reason": "No change"}
        assert client.post(f"{url}/revise", headers=headers, json=unchanged).status_code == 422

        revised = client.post(f"{url}/revise", headers=headers, json={**revise, "reason": "Vendor re-quote"})
        assert revised.status_code == 200, revised.text
        assert str(revised.json()["final_cost"]).startswith("1560")
        assert revised.json()["current_revision_number"] == 2

        history = client.get(f"{url}/revisions", headers=headers).json()
        assert [row["revision_number"] for row in history] == [2, 1]
        assert str(history[0]["previous_unit_rate"]).startswith("1250")
        assert history[0]["reason"] == "Vendor re-quote"
        assert history[0]["po_number"] == "PO-4500999"

        all_history = client.get("/api/v1/master-data/tangibles/revisions", headers=headers).json()
        assert len(all_history) == 2


def test_relaxed_duplicate_rule_for_tangibles():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)
        base = _tangible_payload(category["id"], subcategory["id"], manufacturer["id"])
        assert client.post("/api/v1/master-data/tangibles", headers=headers, json=base).status_code == 201

        same_name_other_rate = client.post(
            "/api/v1/master-data/tangibles",
            headers=headers,
            json={**base, "tangible_code": "TNG-0002", "unit_rate": "900"},
        )
        assert same_name_other_rate.status_code == 201, same_name_other_rate.text

        identical = client.post(
            "/api/v1/master-data/tangibles",
            headers=headers,
            json={**base, "tangible_code": "TNG-0003"},
        )
        assert identical.status_code == 409
        assert "same manufacturer, rate, uplift and description" in identical.json()["detail"]


def test_removing_values_in_use_keeps_records_and_blocks_purge():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)
        item = client.post("/api/v1/master-data/tangibles", headers=headers, json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"])).json()

        blocked = client.delete(f"/api/v1/master-data/catalogue-options/{category['id']}", headers=headers)
        assert blocked.status_code == 422
        assert "active subcategor" in blocked.json()["detail"]

        removed = client.delete(f"/api/v1/master-data/catalogue-options/{manufacturer['id']}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert removed.json()["usage_count"] == 1
        shown = client.get(f"/api/v1/master-data/tangibles/{item['id']}", headers=headers).json()
        assert shown["manufacturer_name"] == "Weatherford"

        # Removed values are not offered for new records, but existing records keep them.
        assert client.post("/api/v1/master-data/tangibles", headers=headers, json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"], tangible_code="TNG-9")).status_code == 422

        purge = client.delete(f"/api/v1/master-data/catalogue-options/{manufacturer['id']}/permanent", headers=headers)
        assert purge.status_code == 422
        assert "still used" in purge.json()["detail"]

        restore = client.post(f"/api/v1/master-data/catalogue-options/{manufacturer['id']}/restore", headers=headers)
        assert restore.status_code == 200
        assert client.post("/api/v1/master-data/catalogue-options/bulk", headers=headers, json={"list_key": "manufacturer", "values": ["Weatherford", "Baker Hughes", "baker hughes"]}).json()["created_count"] == 1


def test_soft_delete_restore_and_permanent_delete_removes_history():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)
        item = client.post("/api/v1/master-data/tangibles", headers=headers, json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"])).json()
        url = f"/api/v1/master-data/tangibles/{item['id']}"

        assert client.delete(url, headers=headers).status_code == 200
        assert client.get("/api/v1/master-data/tangibles", headers=headers).json() == []
        deleted = client.get("/api/v1/master-data/tangibles/deleted", headers=headers).json()
        assert [row["id"] for row in deleted] == [item["id"]]

        assert client.post(f"{url}/restore", headers=headers).status_code == 200
        assert client.delete(url, headers=headers).status_code == 200
        assert client.delete(f"{url}/permanent", headers=headers).status_code == 204
        assert client.get("/api/v1/master-data/tangibles/deleted", headers=headers).json() == []
        assert client.get(f"/api/v1/master-data/tangibles/revisions?include_removed=true", headers=headers).json() == []


def test_bulk_delete_restore_and_purge():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)
        ids = []
        for index in range(3):
            ids.append(client.post("/api/v1/master-data/tangibles", headers=headers, json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"], tangible_code=f"BLK-{index}", unit_rate=str(100 + index * 10), tangible_name=f"Item {index}")).json()["id"])

        assert client.post("/api/v1/master-data/tangibles/bulk-delete", headers=headers, json={"ids": ids}).json()["affected_count"] == 3
        assert client.post("/api/v1/master-data/tangibles/bulk-restore", headers=headers, json={"ids": ids}).json()["affected_count"] == 3
        assert client.post("/api/v1/master-data/tangibles/bulk-delete", headers=headers, json={"ids": ids}).json()["affected_count"] == 3
        assert client.post("/api/v1/master-data/tangibles/bulk-permanent-delete", headers=headers, json={"ids": ids}).json()["affected_count"] == 3
        assert client.get("/api/v1/master-data/tangibles/deleted", headers=headers).json() == []


def test_drill_bit_serial_is_unique_and_priced_like_tangibles():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        bit_type = _option(client, headers, "drill_bit_type", "PDC")
        manufacturer = _option(client, headers, "manufacturer", "Halliburton")
        payload = {
            "bit_code": "db-0001",
            "bit_name": "PDC bit 8-1/2in",
            "bit_type_id": bit_type["id"],
            "manufacturer_id": manufacturer["id"],
            "model_no": "M1365",
            "size": "8-1/2 in",
            "iadc_code": "M423",
            "serial_number": "SN-88421",
            "po_number": "PO-1",
            "unit_rate": "85000",
            "cost_uplift": "100",
            "currency": "USD",
            "effective_date": "2026-02-01",
        }
        created = client.post("/api/v1/master-data/drill-bits", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        assert created.json()["bit_code"] == "DB-0001"
        assert created.json()["bit_type_name"] == "PDC"
        clash = client.post("/api/v1/master-data/drill-bits", headers=headers, json={**payload, "bit_code": "DB-0002", "serial_number": "sn-88421"})
        assert clash.status_code == 409
        assert "serial number" in clash.json()["detail"].lower()

        revised = client.post(
            f"/api/v1/master-data/drill-bits/{created.json()['id']}/revise",
            headers=headers,
            json={"unit_rate": "90000", "cost_uplift": "110", "currency": "USD", "po_number": "PO-2", "effective_date": "2026-04-01", "reason": "Price increase"},
        )
        assert revised.status_code == 200, revised.text
        assert str(revised.json()["final_cost"]).startswith("99000")


def test_mud_chemicals_and_cement_additives_enforce_unique_names_and_unit_rates():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        group = _option(client, headers, "mud_chemical_group", "Weighting agent")
        additive_type = _option(client, headers, "cement_additive_type", "Accelerator")
        payload = {
            "chemical_code": "mc-01",
            "chemical_name": "Barite",
            "group_id": group["id"],
            "part_number": "BR-25",
            "uom": "mt",
            "unit_rate": "420.5",
            "currency": "USD",
            "effective_date": "2026-01-15",
        }
        created = client.post("/api/v1/master-data/mud-chemicals", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        assert created.json()["chemical_code"] == "MC-01"
        assert "final_cost" not in created.json()  # unit-priced: no uplift
        assert client.post("/api/v1/master-data/mud-chemicals", headers=headers, json={**payload, "chemical_code": "MC-02", "chemical_name": "BARITE"}).status_code == 409

        additive = {
            "additive_code": "ca-01",
            "additive_name": "Calcium chloride",
            "additive_type_id": additive_type["id"],
            "unit_rate": "610",
            "currency": "USD",
            "effective_date": "2026-01-15",
        }
        created_additive = client.post("/api/v1/master-data/cement-additives", headers=headers, json=additive)
        assert created_additive.status_code == 201, created_additive.text
        url = f"/api/v1/master-data/cement-additives/{created_additive.json()['id']}"
        assert client.patch(url, headers=headers, json={"additive_name": "Calcium chloride (CaCl2)"}).json()["additive_name"] == "Calcium chloride (CaCl2)"
        revise = client.post(f"{url}/revise", headers=headers, json={"unit_rate": "640", "currency": "USD", "effective_date": "2026-05-01", "reason": "Market change"})
        assert revise.status_code == 200, revise.text
        assert revise.json()["current_revision_number"] == 2


def test_fuel_has_fixed_types_and_only_price_updates():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        fuel = client.get("/api/v1/master-data/fuel-types", headers=headers).json()
        assert sorted(row["fuel_code"] for row in fuel) == ["DIESEL", "JET-A1", "KEROSENE", "PETROL"]
        assert all(row["uom"] == "L" for row in fuel)

        diesel = next(row for row in fuel if row["fuel_code"] == "DIESEL")
        created_fuel = client.post("/api/v1/master-data/fuel-types", headers=headers, json={"fuel_code": "X"})
        assert created_fuel.status_code >= 400  # fixed list: no create
        assert len(client.get("/api/v1/master-data/fuel-types", headers=headers).json()) == 4
        assert client.delete(f"/api/v1/master-data/fuel-types/{diesel['id']}", headers=headers).status_code in {404, 405}

        price = client.post(f"/api/v1/master-data/fuel-types/{diesel['id']}/revise", headers=headers, json={"unit_rate": "1.25", "currency": "USD", "effective_date": "2026-06-01", "reason": "Weekly index"})
        assert price.status_code == 200, price.text
        assert price.json()["unit_rate"] in {"1.25", "1.2500"}
        assert len(client.get(f"/api/v1/master-data/fuel-types/{diesel['id']}/revisions", headers=headers).json()) == 1


def test_import_creates_lists_updates_existing_and_reports_row_errors():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        rows = [
            {
                "tangible_code": "imp-1",
                "tangible_name": "Float collar",
                "scope": "completion",
                "category": "Float Equipment",
                "subcategory": "Collars",
                "manufacturer": "Baker Hughes",
                "uom": "EA",
                "po_number": "PO-9",
                "rate_as_per_po": "2,500",
                "cost_uplift": "100",
                "currency": "usd",
                "effective_date": "31/01/2026",
            },
            {
                "tangible_code": "IMP-2",
                "tangible_name": "Bad currency",
                "scope": "Drilling",
                "category": "Float Equipment",
                "subcategory": "Shoes",
                "manufacturer": "Baker Hughes",
                "unit_rate": "10",
                "currency": "XYZ",
            },
            {
                "tangible_code": "IMP-3",
                "tangible_name": "Bad scope",
                "scope": "Mud",
                "category": "Float Equipment",
                "subcategory": "Shoes",
                "manufacturer": "Baker Hughes",
                "unit_rate": "10",
                "currency": "USD",
            },
        ]
        response = client.post("/api/v1/master-data/tangibles/import", headers=headers, json={"rows": rows})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["imported_count"] == 1
        assert result["error_count"] == 2
        assert any("Row 2" in error and "Currency" in error for error in result["errors"])
        assert any("Row 3" in error and "Scope" in error for error in result["errors"])

        imported = client.get("/api/v1/master-data/tangibles", headers=headers).json()
        assert [row["tangible_code"] for row in imported] == ["IMP-1"]
        assert imported[0]["final_cost"] is not None and str(imported[0]["final_cost"]).startswith("2500")
        assert imported[0]["scope"] == "Completion"

        # Same code with a new rate creates a revision; blank cells keep current values.
        again = client.post(
            "/api/v1/master-data/tangibles/import",
            headers=headers,
            json={"rows": [{"tangible_code": "IMP-1", "tangible_name": "", "unit_rate": "2600", "effective_date": "2026-02-15", "reason": "Re-quote"}]},
        )
        assert again.json()["imported_count"] == 1, again.text
        updated = client.get(f"/api/v1/master-data/tangibles/{imported[0]['id']}", headers=headers).json()
        assert updated["current_revision_number"] == 2
        assert updated["tangible_name"] == "Float collar"

        lists = {row["key"]: row for row in client.get("/api/v1/master-data/catalogue-options/lists", headers=headers).json()}
        assert lists["tangible_subcategory"]["active_count"] >= 1
        assert lists["manufacturer"]["active_count"] == 1


def test_overview_audit_and_rbac():
    with TestClient(app) as client:
        headers = login(client)
        _seed_masters(client, headers)
        category, subcategory, manufacturer = _setup_tangible_lists(client, headers)
        item = client.post("/api/v1/master-data/tangibles", headers=headers, json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"])).json()
        client.post(f"/api/v1/master-data/tangibles/{item['id']}/revise", headers=headers, json={"unit_rate": "1300", "cost_uplift": "120", "currency": "USD", "effective_date": "2026-03-01", "reason": "Quote update"})

        overview = client.get("/api/v1/master-data/tangibles/overview", headers=headers).json()
        assert overview["active_count"] == 1
        assert overview["revisions_last_30_days"] == 2
        assert overview["breakdown"][0]["label"] == "Casing Accessories"
        assert len(overview["recent_revisions"]) == 2

        master = client.get("/api/v1/master-data/overview", headers=headers).json()
        keys = {module["key"] for module in master["modules"]}
        assert {"tangibles", "drill-bits", "mud-chemicals", "cement-additives", "fuel-types"} <= keys

        audit_rows = client.get("/api/v1/audit?entity_type=tangible", headers=headers).json()
        actions = {row["action"] for row in audit_rows.get("items", audit_rows) if isinstance(row, dict)}
        assert {"create", "revise_rate"} <= actions

        # A user without create permission cannot create tangibles.
        with SessionLocal() as db:
            org = db.scalar(select(Organization).where(Organization.slug == "north"))
            read_only = Role(organization_id=org.id, name="Viewer", is_owner=False, permissions=[
                db.scalar(select(Permission).where(Permission.organization_id == org.id, Permission.key == "master-data:read")),
            ])
            db.add(read_only)
            db.add(User(organization_id=org.id, email="viewer@example.com", full_name="Viewer", password_hash=hash_password("correct-password-123"), roles=[read_only]))
            db.commit()
        viewer = client.post("/api/v1/auth/login", json={"organization": "north", "email": "viewer@example.com", "password": "correct-password-123"}).json()
        viewer_headers = {"Authorization": f"Bearer {viewer['access_token']}"}
        assert client.get("/api/v1/master-data/tangibles", headers=viewer_headers).status_code == 200
        forbidden = client.post("/api/v1/master-data/tangibles", headers=viewer_headers, json=_tangible_payload(category["id"], subcategory["id"], manufacturer["id"], tangible_code="NOPE"))
        assert forbidden.status_code == 403
