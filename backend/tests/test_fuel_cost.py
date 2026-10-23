import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import (
    AuditLog,
    FuelCompany,
    FuelCompanyCategory,
    FuelCostCompanyLine,
    FuelCostEntry,
    Organization,
    Permission,
    Role,
    User,
)

PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        "submit", "reopen", "amend", "fuel-opening-stock",
    )),
    *(f"rig-well:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
    )),
    *(f"master-data:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
    )),
    "audit:read",
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
            role = Role(organization_id=organization.id, name="Owner", is_owner=True, permissions=permissions)
            db.add(User(
                organization_id=organization.id,
                email="owner@example.com",
                full_name="Test Owner",
                password_hash=hash_password("correct-password-123"),
                roles=[role],
            ))
        db.commit()
    yield


def login(client: TestClient, organization: str = "north") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={
        "organization": organization,
        "email": "owner@example.com",
        "password": "correct-password-123",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _post(client, path, headers, payload, status=201):
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == status, response.text
    return response.json()


def setup_register(client, headers) -> dict:
    """Two rigs, two vendors and a default company with two categories."""
    rig = _post(client, "/api/v1/rig-well/rigs", headers, {
        "rig_code": "RIG-01", "rig_name": "Rig One", "remarks": "",
    })
    second_rig = _post(client, "/api/v1/rig-well/rigs", headers, {
        "rig_code": "RIG-02", "rig_name": "Rig Two", "remarks": "",
    })
    vendor = _post(client, "/api/v1/master-data/vendors", headers, {
        "vendor_code": "VEN-01", "vendor_name": "Acme Fuel Services", "category": "Drilling",
        "status": "active",
    })
    second_vendor = _post(client, "/api/v1/master-data/vendors", headers, {
        "vendor_code": "VEN-02", "vendor_name": "Beta Logistics", "category": "Drilling",
        "status": "active",
    })
    acme = _post(client, "/api/v1/fuel-cost/companies", headers, {
        "company_name": "Acme Fuel Services", "vendor_id": vendor["id"], "is_default": True,
        "remarks": "Daily fuel supplier",
    })
    acme = _post(client, f"/api/v1/fuel-cost/companies/{acme['id']}/categories", headers, {
        "category_name": "Rig crew",
    })
    acme = _post(client, f"/api/v1/fuel-cost/companies/{acme['id']}/categories", headers, {
        "category_name": "Camp",
    })
    beta = _post(client, "/api/v1/fuel-cost/companies", headers, {
        "company_name": "Beta Logistics", "vendor_id": second_vendor["id"], "is_default": False,
    })
    return {
        "rig": rig, "second_rig": second_rig, "vendor": vendor, "second_vendor": second_vendor,
        "acme": acme, "beta": beta,
        "acme_categories": {category["category_name"]: category["id"] for category in acme["categories"]},
    }


def day_payload(rig_id: str, cost_date: str, **overrides):
    payload = {
        "rig_id": rig_id,
        "cost_date": cost_date,
        "rig_engine_consumption": "0",
        "rig_engine_remarks": "",
        "gas_consumption": "0",
        "gas_remarks": "",
        "receipt_quantity": "0",
        "receipt_remarks": "",
        "remarks": "",
        "lines": [],
    }
    payload.update(overrides)
    return payload


def test_fuel_register_material_balance_and_company_classification():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_register(client, headers)
        reference = client.get("/api/v1/fuel-cost/reference", headers=headers).json()
        assert [rig["rig_code"] for rig in reference["rigs"]] == ["RIG-01", "RIG-02"]
        assert len(reference["companies"]) == 2
        acme = next(company for company in reference["companies"] if company["company_name"] == "Acme Fuel Services")
        assert acme["is_default"] is True
        assert acme["vendor_code"] == "VEN-01"
        assert sorted(category["category_name"] for category in acme["categories"]) == ["Camp", "Rig crew"]
        assert all(vendor["registered"] for vendor in reference["vendors"])

        acme_categories = setup["acme_categories"]
        created = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-01",
            opening_stock="1000",
            opening_remarks="Dip reading at handover",
            rig_engine_consumption="100",
            rig_engine_remarks="Three engines",
            gas_consumption="25",
            gas_remarks="Gas recorded separately",
            receipt_quantity="500",
            receipt_remarks="Bulk delivery",
            closing_stock="1290",
            closing_remarks="Evening dip",
            remarks="First day of the register",
            lines=[
                {"company_id": setup["acme"]["id"], "category_id": acme_categories["Rig crew"], "litres": "80"},
                {"company_id": setup["acme"]["id"], "category_id": acme_categories["Camp"], "litres": "20"},
                {"company_id": setup["beta"]["id"], "litres": "50", "remarks": "Truck refuel"},
            ],
        ))
        entry = created["entry"]
        balance = created["balance"]
        # AGO consumption is rig engines + company lines; gas stays outside it.
        assert Decimal(balance["rig_engine_consumption"]) == Decimal("100")
        assert Decimal(balance["company_consumption"]) == Decimal("150")
        assert Decimal(balance["total_consumption"]) == Decimal("250")
        assert Decimal(balance["gas_consumption"]) == Decimal("25")
        assert Decimal(entry["gas_consumption"]) == Decimal("25")
        assert Decimal(balance["opening_stock"]) == Decimal("1000")
        assert Decimal(balance["receipt"]) == Decimal("500")
        assert Decimal(balance["book_closing_stock"]) == Decimal("1250")
        assert Decimal(balance["actual_closing_stock"]) == Decimal("1290")
        assert Decimal(balance["closing_adjustment"]) == Decimal("40")
        assert Decimal(balance["opening_adjustment"]) == Decimal("0")
        assert Decimal(balance["adjustments"]) == Decimal("40")
        assert balance["is_first_entry"] is True
        assert balance["previous_date"] is None
        assert entry["day_remarks"] if "day_remarks" in entry else True
        assert entry["remarks"] == "First day of the register"
        assert len(created["lines"]) == 3
        assert entry["line_count"] == 3

        # The day endpoint and the register agree.
        day = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-01",
        }).json()
        assert day["entry"]["id"] == entry["id"]
        assert Decimal(day["balance"]["total_consumption"]) == Decimal("250")
        register = client.get("/api/v1/fuel-cost/entries", headers=headers, params={
            "rig_id": setup["rig"]["id"],
        }).json()
        assert len(register) == 1
        assert Decimal(register[0]["balance"]["book_closing_stock"]) == Decimal("1250")

        # Company and category classification for the rig.
        report = client.get(
            f"/api/v1/fuel-cost/rigs/{setup['rig']['id']}/company-consumption", headers=headers,
        ).json()
        assert Decimal(report["total_litres"]) == Decimal("150")
        rows = {(row["company_name"], row["category_name"]): Decimal(row["litres"]) for row in report["rows"]}
        assert rows[("Acme Fuel Services", "Rig crew")] == Decimal("80")
        assert rows[("Acme Fuel Services", "Camp")] == Decimal("20")
        assert rows[("Beta Logistics", "")] == Decimal("50")

        # Day two carries the previous actual closing stock forward.
        second = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-02",
            rig_engine_consumption="50", receipt_quantity="200", closing_stock="1400",
            lines=[{"company_id": setup["beta"]["id"], "litres": "0"}],
        ))
        assert second["entry"]["opening_stock"] is None
        assert second["entry"]["opening_overridden"] is False
        assert second["balance"]["is_first_entry"] is False
        assert second["balance"]["previous_date"] == "2026-10-01"
        assert Decimal(second["balance"]["carried_opening"]) == Decimal("1290")
        assert Decimal(second["balance"]["opening_stock"]) == Decimal("1290")
        assert Decimal(second["balance"]["book_closing_stock"]) == Decimal("1440")
        assert Decimal(second["balance"]["closing_adjustment"]) == Decimal("-40")
        assert Decimal(second["balance"]["adjustments"]) == Decimal("-40")

        # A preview before saving shows the same carried opening.
        preview = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-03",
        }).json()
        assert preview["entry"] is None
        assert preview["balance"]["is_first_entry"] is False
        assert Decimal(preview["balance"]["opening_stock"]) == Decimal("1400")
        assert preview["balance"]["previous_date"] == "2026-10-02"

        # The first day of a different rig starts a new chain and must be anchored.
        assert client.post("/api/v1/fuel-cost/entries", headers=headers, json=day_payload(
            setup["second_rig"]["id"], "2026-10-01", rig_engine_consumption="5",
        )).status_code == 422
        other = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["second_rig"]["id"], "2026-10-01", opening_stock="750", closing_stock="750",
            rig_engine_consumption="0", receipt_quantity="0",
        ))
        assert other["balance"]["is_first_entry"] is True
        assert Decimal(other["balance"]["opening_adjustment"]) == Decimal("0")

        # Validation: duplicate company/category, negatives, empty day.
        assert client.post("/api/v1/fuel-cost/entries", headers=headers, json=day_payload(
            setup["rig"]["id"], "2026-10-04",
            lines=[
                {"company_id": setup["acme"]["id"], "category_id": acme_categories["Camp"], "litres": "10"},
                {"company_id": setup["acme"]["id"], "category_id": acme_categories["Camp"], "litres": "5"},
            ],
        )).status_code == 422
        assert client.post("/api/v1/fuel-cost/entries", headers=headers, json=day_payload(
            setup["rig"]["id"], "2026-10-04", rig_engine_consumption="-1",
        )).status_code == 422
        assert client.post("/api/v1/fuel-cost/entries", headers=headers, json=day_payload(
            setup["rig"]["id"], "2026-10-04",
        )).status_code == 422
        assert client.post("/api/v1/fuel-cost/entries", headers=headers, json=day_payload(
            setup["rig"]["id"], "2026-10-02", rig_engine_consumption="1",
        )).status_code == 409
        # A supplied balance is rejected: the server computes it.
        assert client.post("/api/v1/fuel-cost/entries", headers=headers, json=day_payload(
            setup["rig"]["id"], "2026-10-05", rig_engine_consumption="1", book_closing_stock="1",
        )).status_code == 422


def test_fuel_opening_stock_override_permission_and_carry_forward():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_register(client, headers)
        first = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-01", opening_stock="1000", receipt_quantity="1000",
            rig_engine_consumption="200", closing_stock="1800",
        ))
        second = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-02", rig_engine_consumption="100", closing_stock="1700",
        ))
        assert Decimal(second["balance"]["opening_stock"]) == Decimal("1800")
        assert Decimal(second["balance"]["closing_adjustment"]) == Decimal("0")

        # Override the second day's opening: the difference is an adjustment.
        overridden = client.post(
            f"/api/v1/fuel-cost/entries/{second['entry']['id']}/opening-stock",
            headers=headers,
            json={"opening_stock": "1750", "remarks": "Measured stock in the day tank"},
        )
        assert overridden.status_code == 200, overridden.text
        result = overridden.json()
        assert Decimal(result["balance"]["carried_opening"]) == Decimal("1800")
        assert Decimal(result["balance"]["opening_stock"]) == Decimal("1750")
        assert Decimal(result["balance"]["opening_adjustment"]) == Decimal("-50")
        assert Decimal(result["balance"]["book_closing_stock"]) == Decimal("1650")
        assert Decimal(result["balance"]["actual_closing_stock"]) == Decimal("1700")
        assert Decimal(result["balance"]["closing_adjustment"]) == Decimal("50")
        assert Decimal(result["balance"]["adjustments"]) == Decimal("0")
        assert result["entry"]["opening_overridden"] is True
        assert result["entry"]["opening_remarks"] == "Measured stock in the day tank"

        # The override revises later days too.
        third = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-03", rig_engine_consumption="10",
        ))
        assert Decimal(third["balance"]["opening_stock"]) == Decimal("1700")

        # Clearing the override returns to the carried closing.
        cleared = client.post(
            f"/api/v1/fuel-cost/entries/{second['entry']['id']}/opening-stock",
            headers=headers, json={"clear_override": True},
        )
        assert cleared.status_code == 200, cleared.text
        assert Decimal(cleared.json()["balance"]["opening_stock"]) == Decimal("1800")
        assert cleared.json()["entry"]["opening_overridden"] is False
        # The first day is the anchor and cannot be cleared.
        assert client.post(
            f"/api/v1/fuel-cost/entries/{first['entry']['id']}/opening-stock",
            headers=headers, json={"clear_override": True},
        ).status_code == 422
        # Its opening can still be corrected (audited).
        corrected = client.post(
            f"/api/v1/fuel-cost/entries/{first['entry']['id']}/opening-stock",
            headers=headers, json={"opening_stock": "1050", "remarks": "Corrected handover dip"},
        )
        assert corrected.status_code == 200, corrected.text
        assert Decimal(corrected.json()["balance"]["opening_stock"]) == Decimal("1050")

        # The ordinary save can never move an opening stock without the override.
        assert client.put(
            f"/api/v1/fuel-cost/entries/{second['entry']['id']}", headers=headers,
            json=day_payload(setup["rig"]["id"], "2026-10-02", opening_stock="100", rig_engine_consumption="100"),
        ).status_code == 422

        # The day dialog can clear an override in its own save payload.
        reset = client.post(
            f"/api/v1/fuel-cost/entries/{second['entry']['id']}/opening-stock",
            headers=headers, json={"opening_stock": "1750"},
        )
        assert reset.status_code == 200, reset.text
        cleared_in_save = client.put(
            f"/api/v1/fuel-cost/entries/{second['entry']['id']}", headers=headers,
            json=day_payload(
                setup["rig"]["id"], "2026-10-02", rig_engine_consumption="100",
                closing_stock="1700", clear_opening_override=True,
            ),
        )
        assert cleared_in_save.status_code == 200, cleared_in_save.text
        assert cleared_in_save.json()["entry"]["opening_overridden"] is False
        assert Decimal(cleared_in_save.json()["balance"]["opening_stock"]) == Decimal("1800")

        # Without the separately assignable capability an override is refused.
        with SessionLocal() as db:
            north_id = select(Organization.id).where(Organization.slug == "north").scalar_subquery()
            role = db.scalar(select(Role).where(Role.organization_id == north_id))
            role.is_owner = False
            role.permissions = [
                permission for permission in role.permissions
                if permission.key in (
                    "daily-cost:read", "daily-cost:create", "daily-cost:update", "daily-cost:export",
                )
            ]
            db.commit()
        denied = client.post(
            f"/api/v1/fuel-cost/entries/{second['entry']['id']}/opening-stock",
            headers=headers, json={"opening_stock": "1600"},
        )
        assert denied.status_code == 403
        denied_save = client.put(
            f"/api/v1/fuel-cost/entries/{second['entry']['id']}", headers=headers,
            json=day_payload(
                setup["rig"]["id"], "2026-10-02", opening_stock="1600", opening_overridden=True,
                rig_engine_consumption="100",
            ),
        )
        assert denied_save.status_code == 403
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.organization_id == north_id))
            role.is_owner = True
            db.commit()

        # Audit trail records the override separately.
        with SessionLocal() as db:
            actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "fuel_cost")).all()
            assert "opening-stock" in actions


def test_fuel_import_groups_rows_updates_idempotently_and_reports_errors():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_register(client, headers)
        response = client.post("/api/v1/fuel-cost/import", headers=headers, json={
            "rig_id": setup["rig"]["id"],
            "rows": [
                {"cost_date": "2026-10-10", "opening_stock": "900", "rig_engine_consumption": "100",
                 "gas_consumption": "12", "receipt_quantity": "300", "closing_stock": "1000",
                 "company_name": "Acme Fuel Services", "category_name": "Camp", "litres": "100"},
                {"cost_date": "2026-10-10", "company_name": "New Vendor Co", "category_name": "Water supply",
                 "litres": "20", "line_remarks": "Imported line"},
                {"cost_date": "2026-10-11", "rig_engine_consumption": "50", "company_name": "Acme Fuel Services",
                 "litres": "10"},
                # Errors: no opening on a second rig's first day, a negative quantity and a bad date.
                {"rig_code": "RIG-02", "cost_date": "2026-10-10", "rig_engine_consumption": "5"},
                {"cost_date": "2026-10-12", "rig_engine_consumption": "-5"},
                {"cost_date": "not-a-date", "rig_engine_consumption": "5"},
            ],
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["imported_count"] == 2
        assert result["day_count"] == 2
        assert result["line_count"] == 3
        assert result["success"] is False
        assert result["error_count"] == 3
        assert any("Opening stock is mandatory" in message for message in result["errors"])
        assert any("cannot be negative" in message for message in result["errors"])
        assert any("not a valid date" in message for message in result["errors"])

        first = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-10",
        }).json()
        assert len(first["lines"]) == 2
        assert Decimal(first["balance"]["opening_stock"]) == Decimal("900")
        assert Decimal(first["balance"]["company_consumption"]) == Decimal("120")
        assert Decimal(first["balance"]["gas_consumption"]) == Decimal("12")
        # Imported companies and categories are registered for future daily entry.
        reference = client.get("/api/v1/fuel-cost/reference", headers=headers).json()
        imported = next(company for company in reference["companies"] if company["company_name"] == "New Vendor Co")
        assert [category["category_name"] for category in imported["categories"]] == ["Water supply"]

        second = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-11",
        }).json()
        assert Decimal(second["balance"]["opening_stock"]) == Decimal("1000")

        # Re-importing the same rows updates in place instead of duplicating.
        again = client.post("/api/v1/fuel-cost/import", headers=headers, json={
            "rig_id": setup["rig"]["id"],
            "rows": [
                {"cost_date": "2026-10-10", "opening_stock": "900", "rig_engine_consumption": "120",
                 "gas_consumption": "12", "receipt_quantity": "300", "closing_stock": "1000",
                 "company_name": "Acme Fuel Services", "category_name": "Camp", "litres": "100"},
                {"cost_date": "2026-10-10", "company_name": "New Vendor Co", "category_name": "Water supply",
                 "litres": "40"},
                {"cost_date": "2026-10-11", "rig_engine_consumption": "50", "company_name": "Acme Fuel Services",
                 "litres": "10"},
            ],
        })
        assert again.status_code == 200, again.text
        assert again.json()["success"] is True
        again_first = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-10",
        }).json()
        assert len(again_first["lines"]) == 2
        assert Decimal(again_first["balance"]["rig_engine_consumption"]) == Decimal("120")

        with SessionLocal() as db:
            with_revision = db.scalar(select(FuelCostEntry).where(FuelCostEntry.cost_date == "2026-10-11"))
            assert with_revision is not None


def test_fuel_register_lifecycle_tenant_isolation_and_audit():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_register(client, headers)
        first = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-01", opening_stock="1000", rig_engine_consumption="100",
            closing_stock="900",
        ))
        second = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-02", rig_engine_consumption="50", closing_stock="850",
        ))
        third = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-03", rig_engine_consumption="25", closing_stock="825",
        ))
        assert Decimal(third["balance"]["opening_stock"]) == Decimal("850")

        # Deleting a day removes it from the active chain; later days recalculate.
        assert client.delete(f"/api/v1/fuel-cost/entries/{second['entry']['id']}", headers=headers).status_code == 200
        active = client.get("/api/v1/fuel-cost/entries", headers=headers, params={
            "rig_id": setup["rig"]["id"],
        }).json()
        assert [row["cost_date"] for row in active] == ["2026-10-03", "2026-10-01"]
        resequenced = next(row for row in active if row["cost_date"] == "2026-10-03")
        assert Decimal(resequenced["balance"]["opening_stock"]) == Decimal("900")
        assert Decimal(resequenced["balance"]["actual_closing_stock"]) == Decimal("825")
        assert Decimal(resequenced["balance"]["closing_adjustment"]) == Decimal("-50")

        deleted = client.get("/api/v1/fuel-cost/entries/deleted", headers=headers).json()
        assert len(deleted) == 1 and deleted[0]["is_deleted"] is True
        assert client.post(f"/api/v1/fuel-cost/entries/{second['entry']['id']}/restore", headers=headers).status_code == 200
        restored = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-03",
        }).json()
        assert Decimal(restored["balance"]["opening_stock"]) == Decimal("850")

        # Tenant isolation: another workspace sees nothing and cannot register here.
        south = login(client, "south")
        assert client.get("/api/v1/fuel-cost/entries", headers=south).json() == []
        assert client.get("/api/v1/fuel-cost/entries", headers=south, params={
            "rig_id": setup["rig"]["id"],
        }).json() == []
        assert client.get("/api/v1/fuel-cost/day", headers=south, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-01",
        }).status_code == 404
        assert client.post("/api/v1/fuel-cost/entries", headers=south, json=day_payload(
            setup["rig"]["id"], "2026-10-05", opening_stock="10", rig_engine_consumption="1",
        )).status_code == 404
        south_reference = client.get("/api/v1/fuel-cost/reference", headers=south).json()
        assert south_reference["rigs"] == [] and south_reference["companies"] == []

        # Company removal is soft; historical lines keep their name snapshot.
        assert client.delete(f"/api/v1/fuel-cost/companies/{setup['beta']['id']}", headers=headers).status_code == 200
        companies = client.get("/api/v1/fuel-cost/companies", headers=headers).json()
        assert all(company["id"] != setup["beta"]["id"] for company in companies)
        deleted_companies = client.get("/api/v1/fuel-cost/companies/deleted", headers=headers).json()
        assert [company["id"] for company in deleted_companies] == [setup["beta"]["id"]]
        assert client.post(f"/api/v1/fuel-cost/companies/{setup['beta']['id']}/restore", headers=headers).status_code == 200
        assert len(client.get("/api/v1/fuel-cost/companies", headers=headers).json()) == 2

        # A category can be removed and restored, and a duplicate name is refused.
        camp_id = setup["acme_categories"]["Camp"]
        assert client.post(f"/api/v1/fuel-cost/companies/{setup['acme']['id']}/categories", headers=headers, json={
            "category_name": "Rig crew",
        }).status_code == 409
        assert client.delete(f"/api/v1/fuel-cost/categories/{camp_id}", headers=headers).status_code == 200
        assert client.post(f"/api/v1/fuel-cost/categories/{camp_id}/restore", headers=headers).status_code == 200

        # Permanent deletion only from Deleted Entries.
        assert client.delete(f"/api/v1/fuel-cost/entries/{second['entry']['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/fuel-cost/entries/{second['entry']['id']}/permanent", headers=headers).status_code == 204
        with SessionLocal() as db:
            assert db.scalar(select(FuelCostEntry.id).where(FuelCostEntry.id == second["entry"]["id"])) is None
            assert db.scalar(select(FuelCostCompanyLine.id).where(
                FuelCostCompanyLine.entry_id == second["entry"]["id"]
            )) is None
            entity_types = set(db.scalars(select(AuditLog.entity_type)).all())
            assert {"fuel_cost", "fuel_company", "fuel_company_category"} <= entity_types
            actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "fuel_cost")).all())
            assert {"create", "delete", "restore", "permanent-delete"} <= actions
            assert db.scalar(select(FuelCompany.id)) is not None
            assert db.scalar(select(FuelCompanyCategory.id)) is not None
        assert first["entry"]["id"]


def test_fuel_first_day_removal_keeps_the_carry_forward_and_import_revives_companies():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_register(client, headers)
        first = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-01", opening_stock="1000", rig_engine_consumption="100",
            closing_stock="900",
        ))
        second = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-02", rig_engine_consumption="50", closing_stock="850",
        ))
        third = _post(client, "/api/v1/fuel-cost/entries", headers, day_payload(
            setup["rig"]["id"], "2026-10-03", rig_engine_consumption="25", closing_stock="825",
        ))
        assert Decimal(third["balance"]["opening_stock"]) == Decimal("850")

        # Removing the earliest day re-anchors the next day at the carried stock,
        # so the physical stock is never reset to zero.
        assert client.delete(f"/api/v1/fuel-cost/entries/{first['entry']['id']}", headers=headers).status_code == 200
        promoted = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-02",
        }).json()
        assert promoted["balance"]["is_first_entry"] is True
        assert promoted["entry"]["opening_stock"] is not None
        assert Decimal(promoted["balance"]["opening_stock"]) == Decimal("900")
        assert Decimal(promoted["balance"]["opening_adjustment"]) == Decimal("0")
        later = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-03",
        }).json()
        assert Decimal(later["balance"]["opening_stock"]) == Decimal("850")

        # Restoring the anchor day puts the original chain back.
        assert client.post(f"/api/v1/fuel-cost/entries/{first['entry']['id']}/restore", headers=headers).status_code == 200
        restored_second = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": setup["rig"]["id"], "date": "2026-10-02",
        }).json()
        assert restored_second["balance"]["is_first_entry"] is False
        assert Decimal(restored_second["balance"]["opening_stock"]) == Decimal("900")

        # Import revives a soft-deleted company (and its category) instead of failing.
        company = _post(client, "/api/v1/fuel-cost/companies", headers, {
            "company_name": "Gamma Haulage", "is_default": True,
        })
        company = _post(client, f"/api/v1/fuel-cost/companies/{company['id']}/categories", headers, {
            "category_name": "Night shift",
        })
        category_id = next(category["id"] for category in company["categories"] if category["category_name"] == "Night shift")
        # A category can still be archived after its company is archived.
        assert client.delete(f"/api/v1/fuel-cost/companies/{company['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/fuel-cost/categories/{category_id}", headers=headers).status_code == 200
        revived = client.post("/api/v1/fuel-cost/import", headers=headers, json={
            "rig_id": setup["rig"]["id"],
            "rows": [{
                "cost_date": "2026-10-04", "rig_engine_consumption": "10",
                "company_name": "Gamma Haulage", "category_name": "Night shift", "litres": "15",
            }],
        })
        assert revived.status_code == 200, revived.text
        assert revived.json()["success"] is True, revived.text
        reference = client.get("/api/v1/fuel-cost/reference", headers=headers).json()
        gamma = next(item for item in reference["companies"] if item["company_name"] == "Gamma Haulage")
        assert [category["category_name"] for category in gamma["categories"]] == ["Night shift"]
        assert client.get("/api/v1/fuel-cost/companies/deleted", headers=headers).json() == []


def test_fuel_recent_five_days_rig_saving_summary_rollups_and_large_ledger():
    from datetime import date, timedelta

    with TestClient(app) as client:
        headers = login(client)
        setup = setup_register(client, headers)
        rig_id = setup["rig"]["id"]

        # Bulk-import 30 days x 12 companies = 360 company lines using Rig Saving litres.
        start_day = date(2026, 9, 1)
        import_rows = []
        for day_offset in range(30):
            day_iso = (start_day + timedelta(days=day_offset)).isoformat()
            for comp_index in range(12):
                row = {
                    "cost_date": day_iso,
                    "company_name": f"Contractor {comp_index + 1:02d}",
                    "category_name": "Crew" if comp_index % 2 == 0 else ("Camp" if comp_index % 3 == 0 else ""),
                    "litres": "10",
                    "line_remarks": f"Batch {day_offset}-{comp_index}",
                }
                if comp_index == 0:
                    row["rig_engine_consumption"] = "100"
                    row["rig_saving_litres"] = "35"
                    row["rig_saving_remarks"] = "AGO saved via gas"
                    row["receipt_quantity"] = "300" if day_offset % 5 == 0 else "0"
                    if day_offset == 0:
                        row["opening_stock"] = "10000"
                import_rows.append(row)

        imported = client.post("/api/v1/fuel-cost/import", headers=headers, json={
            "rig_id": rig_id,
            "rows": import_rows,
        })
        assert imported.status_code == 200, imported.text
        body = imported.json()
        assert body["success"] is True, body["errors"]
        assert body["imported_count"] == 30
        assert body["line_count"] == 360

        # Add day 31 directly via rig_saving_litres alias, and verify previous_lines preview first.
        day_31_iso = (start_day + timedelta(days=30)).isoformat()
        preview = client.get("/api/v1/fuel-cost/day", headers=headers, params={
            "rig_id": rig_id, "date": day_31_iso,
        }).json()
        assert len(preview["previous_lines"]) == 12
        assert preview["balance"]["is_first_entry"] is False

        # Daily total consumption per imported day = 100 engine + 12*10 company = 220 L.
        # Over 30 days: 10000 opening + 6*300 receipts (1800) - 30*220 AGO (6600) = 5200 L closing!
        assert Decimal(preview["balance"]["carried_opening"]) == Decimal("5200")

        saved_31 = _post(client, "/api/v1/fuel-cost/entries", headers, {
            "rig_id": rig_id,
            "cost_date": day_31_iso,
            "rig_engine_consumption": "80",
            "rig_saving_litres": "45",
            "rig_saving_remarks": "Dual fuel generator",
            "receipt_quantity": "0",
            "closing_stock": "5090",
            "lines": [
                {"company_id": setup["acme"]["id"], "category_id": setup["acme_categories"]["Rig crew"], "litres": "15"},
                {"company_id": setup["acme"]["id"], "category_id": setup["acme_categories"]["Camp"], "litres": "10"},
            ],
        })
        assert Decimal(saved_31["entry"]["rig_saving_litres"]) == Decimal("45")
        assert Decimal(saved_31["entry"]["gas_consumption"]) == Decimal("45")
        assert saved_31["entry"]["rig_saving_remarks"] == "Dual fuel generator"
        assert Decimal(saved_31["balance"]["rig_saving_litres"]) == Decimal("45")
        # Book closing on day 31 = 5200 - (80 + 25) = 5095; actual = 5090 -> closing adjustment = -5.
        assert Decimal(saved_31["balance"]["book_closing_stock"]) == Decimal("5095")
        assert Decimal(saved_31["balance"]["closing_adjustment"]) == Decimal("-5")

        # Main landing view requests limit=5 and receives ONLY the latest 5 days with exact carry-forward!
        recent_five = client.get("/api/v1/fuel-cost/entries", headers=headers, params={
            "rig_id": rig_id, "limit": 5,
        }).json()
        assert len(recent_five) == 5
        assert recent_five[0]["cost_date"] == day_31_iso
        assert Decimal(recent_five[0]["balance"]["opening_stock"]) == Decimal("5200")
        assert Decimal(recent_five[0]["balance"]["actual_closing_stock"]) == Decimal("5090")

        # Rig summary reconciles inception and filtered windows without fetching all rows.
        summary = client.get(f"/api/v1/fuel-cost/rigs/{rig_id}/summary", headers=headers).json()
        assert summary["total_active_days"] == 31
        assert summary["period_days"] == 31
        assert Decimal(summary["opening_stock"]) == Decimal("10000")
        assert Decimal(summary["receipt"]) == Decimal("1800")
        assert Decimal(summary["total_consumption"]) == Decimal("6705")  # 6600 + 105
        assert Decimal(summary["expected_closing_stock"]) == Decimal("5095")
        assert Decimal(summary["actual_closing_stock"]) == Decimal("5090")
        assert Decimal(summary["adjustments"]) == Decimal("-5")
        assert Decimal(summary["rig_saving_litres"]) == Decimal("1095")  # 30*35 + 45

        # Company & category roll-ups: Acme has 2 categories on day 31 -> day_count must be 1, not 2!
        comp_report = client.get(f"/api/v1/fuel-cost/rigs/{rig_id}/company-consumption", headers=headers).json()
        assert comp_report["active_day_count"] == 31
        assert Decimal(comp_report["total_litres"]) == Decimal("3625")  # 360*10 + 25
        assert Decimal(comp_report["rig_engine_litres"]) == Decimal("3080")
        assert Decimal(comp_report["total_ago_litres"]) == Decimal("6705")
        acme_summary = next(row for row in comp_report["company_rows"] if row["company_name"] == "Acme Fuel Services")
        assert acme_summary["day_count"] == 1
        assert acme_summary["line_count"] == 2
        assert acme_summary["category_count"] == 2
        assert Decimal(acme_summary["litres"]) == Decimal("25")
        assert any(row["category_name"] == "Crew" for row in comp_report["category_rows"])
        assert any(row["category_name"] == "Uncategorised" for row in comp_report["category_rows"])

        # Server-paginated lines ledger (20 / 50 / 100) + search + filters + export audit.
        page_1 = client.get(f"/api/v1/fuel-cost/rigs/{rig_id}/lines", headers=headers, params={
            "page": 1, "page_size": 20,
        }).json()
        assert page_1["total_count"] == 362
        assert Decimal(page_1["total_litres"]) == Decimal("3625")
        assert len(page_1["rows"]) == 20

        filtered_acme = client.get(f"/api/v1/fuel-cost/rigs/{rig_id}/lines", headers=headers, params={
            "company_id": setup["acme"]["id"], "page": 1, "page_size": 20,
        }).json()
        assert filtered_acme["total_count"] == 2
        assert Decimal(filtered_acme["total_litres"]) == Decimal("25")

        filtered_uncat = client.get(f"/api/v1/fuel-cost/rigs/{rig_id}/lines", headers=headers, params={
            "category_id": "__none__", "page": 1, "page_size": 50,
        }).json()
        assert filtered_uncat["total_count"] == 120  # 4 uncategorised contractors * 30 days
        assert len(filtered_uncat["rows"]) == 50

        for export_module in ("recent-register", "material-balance", "company-consumption", "category-consumption", "company-lines"):
            audit_res = client.post("/api/v1/fuel-cost/export-audit", headers=headers, json={
                "module": export_module,
                "format": "xlsx",
                "record_count": 20,
                "rig_id": rig_id,
            })
            assert audit_res.status_code == 204, audit_res.text

