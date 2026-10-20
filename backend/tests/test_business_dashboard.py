import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User


PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export", "submit", "reopen",
    )),
    *(f"afe:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        "estimate", "submit", "review", "approve", "reopen",
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
            permissions = [Permission(organization_id=organization.id, key=key, description=key) for key in PERMISSIONS]
            owner_role = Role(organization_id=organization.id, name="Owner", is_owner=True, permissions=permissions)
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
    response = client.post("/api/v1/auth/login", json={
        "organization": organization,
        "email": email,
        "password": "correct-password-123",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _post(client, path, headers, payload, status=201):
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == status, response.text
    return response.json()


def _setup(client, headers):
    assert client.post("/api/v1/master-data/currencies", headers=headers, json={
        "code": "USD", "name": "US Dollar", "symbol": "$",
    }).status_code == 201
    assert client.post("/api/v1/master-data/uom", headers=headers, json={
        "code": "MT", "name": "Metric tonne", "symbol": "MT",
    }).status_code == 201
    hole = _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "17-1/2", "name": "Surface hole"})
    phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
    activity = _post(client, "/api/v1/master-data/activities", headers, {"code": "DRL", "name": "Drilling"})
    activity_upa = _post(client, "/api/v1/master-data/activities", headers, {"code": "UPA", "name": "Unplanned activity"})
    activity_npt = _post(client, "/api/v1/master-data/activities", headers, {"code": "NPT", "name": "Non-productive time"})
    group = _post(client, "/api/v1/master-data/catalogue-options", headers, {
        "list_key": "mud_chemical_group", "value": "Weighting agent",
    })
    chemical = _post(client, "/api/v1/master-data/mud-chemicals", headers, {
        "chemical_code": "BARITE", "chemical_name": "Barite", "group_id": group["id"],
        "part_number": "BR-25", "uom": "MT", "unit_rate": "10", "currency": "USD",
        "effective_date": "2026-01-15",
    })
    vendor = _post(client, "/api/v1/master-data/vendors", headers, {
        "vendor_code": "VEND-01", "vendor_name": "Acme Services", "category": "Drilling", "status": "active",
    })
    service = _post(client, "/api/v1/master-data/services", headers, {
        "service_code": "MUD-LOG", "service_name": "Mud logging", "service_category": "Drilling Services",
        "provider_type": "Third Party Services", "vendor_id": vendor["id"], "description": "Wellsite logging crew",
    })
    rig = _post(client, "/api/v1/rig-well/rigs", headers, {"rig_code": "RIG-01", "rig_name": "Rig One", "remarks": ""})
    well = _post(client, "/api/v1/rig-well/wells", headers, {
        "rig_id": rig["id"], "well_code": "WELL-01", "well_name": "Well One", "well_location": "North field",
        "block": "A", "objective": "Development", "remarks": "",
    })
    config = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json={
        "depth_unit": "m",
        "sections": [{
            "hole_section_id": hole["id"], "from_depth": "0", "to_depth": "1000", "remarks": "",
            "phases": [{"phase_id": phase["id"], "days": "10", "remarks": ""}],
        }],
    })
    assert config.status_code == 200, config.text
    transition = client.post(f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers, json={
        "action": "configure", "remarks": "Plan checked",
    })
    assert transition.status_code == 200, transition.text

    def sub(code, activity_id):
        return _post(client, "/api/v1/rig-well/sub-activities", headers, {
            "well_id": well["id"], "sub_activity_code": code, "sub_activity_name": f"Sub activity {code}",
            "activity_id": activity_id, "responsible_party": "Operations team",
            "description": "Execute the planned work step.",
        })

    sub_planned = sub("SA-D1", activity["id"])
    sub_upa = sub("SA-U1", activity_upa["id"])
    sub_npt = sub("SA-N1", activity_npt["id"])

    afe = _post(client, "/api/v1/afe/afes", headers, {
        "rig_id": rig["id"], "well_id": well["id"], "afe_code": "AFE-01", "afe_name": "Drilling AFE",
        "afe_type": "Drilling", "remarks": "",
    }, status=200)
    estimate = client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=headers, json={
        "services": [{
            "client_key": "service-day", "service_id": service["id"], "charging_basis": "Day Rate",
            "hole_section_id": hole["id"], "phase_id": phase["id"], "currency": "USD", "service_amount": "0",
            "remarks": "", "rates": [{"category": "Operation", "unit_rate": "100"}],
            "charges": [{"category": "Operation", "quantity": "10", "quantity_unit": "days"}],
            "section_rates": [],
        }],
        "consumables": [{
            "client_key": "bulk-mud", "category": "Mud Chemicals", "hole_section_id": hole["id"],
            "phase_id": phase["id"], "drill_bit_id": None, "quantity": "1", "override_rate": None,
            "estimated_amount": "5000", "currency": "USD", "remarks": "Bulk chemicals allowance",
        }],
        "tangibles": [], "standard_currency": "", "exchange_rates": [],
    })
    assert estimate.status_code == 200, estimate.text
    setup = {
        "activity": activity, "activity_upa": activity_upa, "activity_npt": activity_npt,
        "sub_planned": sub_planned, "sub_upa": sub_upa, "sub_npt": sub_npt,
        "chemical": chemical, "vendor": vendor, "service": service, "hole": hole, "phase": phase,
        "rig": rig, "well": well, "afe": afe,
    }

    # Two cost days: 100 planned service on each, plus a 300 UPA and a 200 NPT service.
    for index, cost_day in enumerate(("2026-10-10", "2026-10-11")):
        created = _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": well["id"], "afe_id": afe["id"], "cost_date": cost_day, "remarks": "",
        })
        entry_id = created["entry"]["id"]
        baseline = client.get(f"/api/v1/daily-cost/entries/{entry_id}/baseline", headers=headers).json()
        rate = baseline["service_rates"][0]

        def line(activity, sub_activity, override_rate, reason, quantity="1", unit="days"):
            return {
                "activity_id": activity["id"], "hole_section_id": hole["id"],
                "phase_id": phase["id"], "sub_activity_id": sub_activity["id"],
                "vendor_id": vendor["id"], "quantity": quantity, "quantity_unit": unit,
                "currency": "USD", "override_rate": override_rate, "override_reason": reason,
                "remarks": "", "service_id": service["id"], "baseline_service_rate_id": rate["id"],
                "charging_basis": "Day Rate", "charge_category": "Operation",
            }

        payload = {
            "remarks": "shift actuals",
            "services": [
                {
                    "activity_id": activity["id"], "hole_section_id": hole["id"],
                    "phase_id": phase["id"], "sub_activity_id": sub_planned["id"],
                    "vendor_id": vendor["id"], "quantity": "1", "quantity_unit": "days",
                    "currency": "USD", "service_id": service["id"],
                    "baseline_service_rate_id": rate["id"], "charging_basis": "Day Rate",
                    "charge_category": "Operation",
                },
                line(activity_upa, sub_upa, "300", "Unplanned diagnostic call-out"),
            ],
            "consumables": [],
            "tangibles": [],
        }
        if index == 0:
            payload["services"].append(line(activity_npt, sub_npt, "200", "Rig repair standby"))
        saved = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
    return setup


def test_business_dashboard_aggregates_plan_budget_and_actuals():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup(client, headers)

        response = client.get("/api/v1/dashboard/business", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["currency"] == "USD"
        assert data["capabilities"] == {"plan": True, "budget": True, "actuals": True}
        kpis = data["kpis"]
        assert kpis["wells"] == 1
        assert kpis["rigs"] == 1
        assert kpis["afes"] == 1
        assert Decimal(kpis["planned_days"]) == Decimal("10.00")
        assert Decimal(kpis["afe_amount"]) == Decimal("6000.00")
        assert kpis["sow_adjusted_amount"] is None
        assert Decimal(kpis["effective_afe_amount"]) == Decimal("6000.00")
        # 2 x (planned 100 + UPA 300) + NPT 200 once = 1000
        assert Decimal(kpis["actual_amount"]) == Decimal("1000.00")
        assert Decimal(kpis["afe_balance"]) == Decimal("5000.00")
        assert kpis["actual_days"] == 2          # 2026-10-10 .. 2026-10-11
        assert kpis["recorded_days"] == 2
        assert kpis["npt_days"] == 1
        assert kpis["upa_days"] == 2
        assert Decimal(kpis["npt_amount"]) == Decimal("200.00")
        assert Decimal(kpis["upa_amount"]) == Decimal("600.00")
        assert Decimal(kpis["planned_depth"]) == Decimal("1000.00")
        assert Decimal(kpis["actual_depth"]) == Decimal("1000.00")
        assert Decimal(kpis["depth_progress_percent"]) == Decimal("100.00")
        assert kpis["over_budget_wells"] == 0

        well = data["wells"][0]
        assert well["well_code"] == "WELL-01"
        assert well["rig_code"] == "RIG-01"
        assert well["status"] == "active"
        assert well["config_status"] == "configured"
        assert well["drilling_planned_days"] == "10.00"
        assert well["completion_planned_days"] is None
        assert well["first_cost_date"] == "2026-10-10"
        assert well["last_cost_date"] == "2026-10-11"
        assert well["drilling_afe_count"] == 1

        afe = data["afes"][0]
        assert afe["afe_code"] == "AFE-01"
        assert afe["afe_amount"] == "6000.00"
        assert afe["actual_amount"] == "1000.00"
        assert afe["afe_balance"] == "5000.00"
        assert afe["npt_days"] == 1
        assert afe["upa_days"] == 2
        assert afe["conversion_pending"] is False

        # Charts and tables are real aggregations, not placeholders.
        assert [point["cost_date"] for point in data["daily"]] == ["2026-10-10", "2026-10-11"]
        assert Decimal(data["daily"][-1]["cumulative"]) == Decimal("1000.00")
        assert data["daily"][0]["npt"] == "200.00"
        groups = {row["key"]: row for row in data["cost_groups"]}
        assert Decimal(groups["services"]["planned"]) == Decimal("1000.00")
        assert Decimal(groups["consumables"]["planned"]) == Decimal("5000.00")
        assert Decimal(groups["services"]["actual"]) == Decimal("1000.00")
        assert Decimal(groups["services"]["balance"]) == Decimal("0.00")
        assert Decimal(groups["other_expenses"]["planned"]) == Decimal("0.00")
        classification = {row["key"]: row for row in data["classification"]}
        assert classification["NPT"]["days"] == 1
        assert classification["UPA"]["days"] == 2
        assert Decimal(classification["NPT"]["actual"]) == Decimal("200.00")
        assert data["rigs"][0]["wells"] == 1
        assert Decimal(data["rigs"][0]["afe_amount"]) == Decimal("6000.00")

        # Filter options are filled from the workspace.
        assert [row["code"] for row in data["filters"]["rigs"]] == ["RIG-01"]
        assert [row["code"] for row in data["filters"]["afes"]] == ["AFE-01"]
        assert data["filters"]["default_currency"] == "USD"

        # ---- date range narrows actuals only --------------------------------------
        narrowed = client.get(
            "/api/v1/dashboard/business?from=2026-10-11&to=2026-10-11", headers=headers,
        ).json()
        assert Decimal(narrowed["kpis"]["actual_amount"]) == Decimal("400.00")  # 100 planned + 300 UPA
        assert narrowed["kpis"]["actual_days"] == 1
        assert narrowed["kpis"]["npt_days"] == 0
        assert narrowed["kpis"]["upa_days"] == 1
        # Planned/AFE figures are plan-level and stay whole.
        assert Decimal(narrowed["kpis"]["planned_days"]) == Decimal("10.00")
        assert Decimal(narrowed["kpis"]["afe_amount"]) == Decimal("6000.00")

        # ---- filtering by rig, well, AFE and type -------------------------------
        by_rig = client.get(f"/api/v1/dashboard/business?rig_id={setup['rig']['id']}", headers=headers).json()
        assert by_rig["kpis"]["wells"] == 1
        by_well = client.get(f"/api/v1/dashboard/business?well_id={setup['well']['id']}", headers=headers).json()
        assert by_well["kpis"]["wells"] == 1
        by_afe = client.get(f"/api/v1/dashboard/business?afe_id={setup['afe']['id']}", headers=headers).json()
        assert by_afe["kpis"]["afes"] == 1
        drilling = client.get("/api/v1/dashboard/business?afe_type=Drilling", headers=headers).json()
        assert drilling["kpis"]["wells"] == 1
        completion = client.get("/api/v1/dashboard/business?afe_type=Completion", headers=headers).json()
        assert completion["kpis"]["wells"] == 0
        assert completion["kpis"]["afes"] == 0
        completed = client.get("/api/v1/dashboard/business?well_status=completed", headers=headers).json()
        assert completed["kpis"]["wells"] == 0

        # ---- submitted-only toggle ----------------------------------------------
        drafts = client.get("/api/v1/dashboard/business?include_draft=false", headers=headers).json()
        assert Decimal(drafts["kpis"]["actual_amount"]) == Decimal("0.00")
        assert drafts["kpis"]["wells_with_actuals"] == 0
        assert drafts["wells"][0]["sheets"] == 0

        # ---- drill-through -------------------------------------------------------
        detail = client.get(
            f"/api/v1/dashboard/business/wells/{setup['well']['id']}", headers=headers,
        )
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload["well"]["well_code"] == "WELL-01"
        assert len(payload["afes"]) == 1
        assert [point["cost_date"] for point in payload["daily"]] == ["2026-10-10", "2026-10-11"]
        activities = {row["activity_code"]: row for row in payload["activities"]}
        assert set(activities) == {"DRL", "UPA", "NPT"}
        assert Decimal(activities["UPA"]["amount"]) == Decimal("600.00")
        assert activities["NPT"]["classification"] == "NPT"
        assert activities["NPT"]["active_days"] == 1
        assert payload["sections"][0]["section_code"] == "17-1/2"
        assert payload["sections"][0]["reached"] is True
        assert payload["sections"][0]["active_days"] == 2
        assert Decimal(payload["sections"][0]["planned_days"]) == Decimal("10.00")
        assert any("Actual days run from the first" in note for note in payload["notes"])

        # Every daily sheet behind the trend can be opened from the panel.
        sheets = payload["sheets"]
        assert [row["cost_date"] for row in sheets] == ["2026-10-11", "2026-10-10"]
        assert sheets[0]["status"] == "draft"
        assert sheets[0]["afe_code"] == "AFE-01"
        assert Decimal(sheets[0]["total"]) == Decimal("400.00")
        assert Decimal(sheets[0]["upa"]) == Decimal("300.00")
        assert Decimal(sheets[0]["npt"]) == Decimal("0.00")
        assert Decimal(sheets[1]["npt"]) == Decimal("200.00")
        ranged_detail = client.get(
            f"/api/v1/dashboard/business/wells/{setup['well']['id']}?from=2026-10-11&to=2026-10-11",
            headers=headers,
        ).json()
        assert [row["cost_date"] for row in ranged_detail["sheets"]] == ["2026-10-11"]

        # ---- validation and auditing ---------------------------------------------
        assert client.get(
            "/api/v1/dashboard/business?from=2026-10-11&to=2026-10-10", headers=headers,
        ).status_code == 422
        assert client.post("/api/v1/dashboard/business/export-audit", headers=headers, json={
            "format": "csv", "record_count": 1,
        }).status_code == 204
        with SessionLocal() as db:
            assert db.query(AuditLog).filter(
                AuditLog.entity_type == "business_dashboard", AuditLog.action == "export",
            ).count() == 1


def test_business_dashboard_respects_rbac_and_tenant_scope():
    with TestClient(app) as client:
        owner_headers = login(client)
        setup = _setup(client, owner_headers)

        # A reader of daily costs only sees the actuals, never AFE or plan figures.
        with SessionLocal() as db:
            organization = db.query(Organization).filter(Organization.slug == "north").one()
            permission = db.query(Permission).filter(
                Permission.organization_id == organization.id, Permission.key == "daily-cost:read",
            ).one()
            role = Role(organization_id=organization.id, name="Cost reader", permissions=[permission])
            db.add(role)
            db.flush()
            db.add(User(
                organization_id=organization.id,
                email="reader@example.com",
                full_name="Cost Reader",
                password_hash=hash_password("correct-password-123"),
                roles=[role],
            ))
            # A user with no source-module read permission at all.
            empty_role = Role(organization_id=organization.id, name="No access")
            db.add(empty_role)
            db.flush()
            db.add(User(
                organization_id=organization.id,
                email="blocked@example.com",
                full_name="Blocked User",
                password_hash=hash_password("correct-password-123"),
                roles=[empty_role],
            ))
            db.commit()

        reader_headers = login(client, email="reader@example.com")
        reader = client.get("/api/v1/dashboard/business", headers=reader_headers)
        assert reader.status_code == 200, reader.text
        payload = reader.json()
        assert payload["capabilities"] == {"plan": False, "budget": False, "actuals": True}
        assert payload["kpis"]["afe_amount"] is None
        assert payload["kpis"]["planned_days"] is None
        assert payload["kpis"]["actual_amount"] == "1000.00"
        assert payload["kpis"]["npt_days"] == 1
        assert payload["afes"] == []
        assert payload["wells"][0]["afe_amount"] is None
        assert payload["wells"][0]["planned_days"] is None
        assert payload["wells"][0]["actual_amount"] == "1000.00"

        blocked_headers = login(client, email="blocked@example.com")
        assert client.get("/api/v1/dashboard/business", headers=blocked_headers).status_code == 403
        assert client.get(
            f"/api/v1/dashboard/business/wells/{setup['well']['id']}", headers=blocked_headers,
        ).status_code == 403
        # Exports are audited only for callers who may export a source module.
        assert client.post("/api/v1/dashboard/business/export-audit", headers=blocked_headers, json={
            "format": "csv", "record_count": 1,
        }).status_code == 403

        # Another workspace sees nothing of this one.
        south_headers = login(client, organization="south")
        south = client.get("/api/v1/dashboard/business", headers=south_headers)
        assert south.status_code == 200, south.text
        assert south.json()["kpis"]["wells"] == 0
        assert south.json()["wells"] == []
        assert south.json()["afes"] == []
        assert client.get(
            f"/api/v1/dashboard/business/wells/{setup['well']['id']}", headers=south_headers,
        ).status_code == 404
