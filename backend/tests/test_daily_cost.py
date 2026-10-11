import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
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


def _setup_daily_sheet(client, headers):
    assert client.post("/api/v1/master-data/currencies", headers=headers, json={
        "code": "USD", "name": "US Dollar", "symbol": "$",
    }).status_code == 201
    assert client.post("/api/v1/master-data/uom", headers=headers, json={
        "code": "MT", "name": "Metric tonne", "symbol": "MT",
    }).status_code == 201
    hole = _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "17-1/2", "name": "Surface hole"})
    phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
    activity = _post(client, "/api/v1/master-data/activities", headers, {"code": "DRL", "name": "Drilling"})
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
    afe = _post(client, "/api/v1/afe/afes", headers, {
        "rig_id": rig["id"], "well_id": well["id"], "afe_code": "AFE-01", "afe_name": "Drilling AFE",
        "afe_type": "Drilling", "remarks": "",
    }, status=200)
    estimate = client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=headers, json={
        "services": [{
            "client_key": "service-day", "service_id": service["id"], "charging_basis": "Day Rate",
            "hole_section_id": None, "phase_id": None, "currency": "USD", "service_amount": "0",
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
    created = _post(client, "/api/v1/daily-cost/entries", headers, {
        "well_id": well["id"], "afe_id": afe["id"], "cost_date": "2026-10-10", "remarks": "Night shift",
    })
    return {
        "activity": activity,
        "chemical": chemical,
        "vendor": vendor,
        "service": service,
        "hole": hole,
        "phase": phase,
        "rig": rig,
        "well": well,
        "afe": afe,
        "entry": created["entry"],
        "baseline": client.get(f"/api/v1/daily-cost/entries/{created['entry']['id']}/baseline", headers=headers).json(),
    }


def test_daily_cost_locks_rates_prices_bulk_actuals_and_tracks_submission():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]
        rate = setup["baseline"]["service_rates"][0]

        # Master Data changes after tracking begins do not flow into the daily sheet.
        revised = client.post(
            f"/api/v1/master-data/mud-chemicals/{setup['chemical']['id']}/revise", headers=headers,
            json={"unit_rate": "20", "currency": "USD", "effective_date": "2026-10-11", "reason": "Market increase"},
        )
        assert revised.status_code == 200, revised.text

        payload = {
            "remarks": "Night shift actuals",
            "services": [{
                "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
                "phase_id": setup["phase"]["id"], "classification": "Planned", "vendor_id": setup["vendor"]["id"],
                "quantity": "12", "quantity_unit": "hours", "currency": "USD", "override_rate": "80",
                "override_reason": "Agreed reduced rate for night shift", "remarks": "Half-day operation",
                "service_id": setup["service"]["id"], "baseline_service_rate_id": rate["id"],
                "charging_basis": "Day Rate", "charge_category": "Operation",
            }],
            "consumables": [{
                "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
                "phase_id": setup["phase"]["id"], "classification": "Planned", "vendor_id": None,
                "quantity": "10", "currency": "USD", "override_rate": None, "override_reason": "",
                "remarks": "Barite usage", "category": "Mud Chemicals", "item_kind": "mud_chemical",
                "item_id": setup["chemical"]["id"],
            }],
            "tangibles": [],
        }
        preview = client.put(f"/api/v1/daily-cost/entries/{entry_id}/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        assert Decimal(preview.json()["services_total"]) == Decimal("40.00")  # 12h / 24 × $80 override
        assert Decimal(preview.json()["consumables_total"]) == Decimal("100.00")  # frozen $10/unit, not current $20

        saved = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert Decimal(result["entry"]["total_cost"]) == Decimal("140.00")
        assert Decimal(result["comparison"]["actual_to_date"]) == Decimal("140.00")
        assert Decimal(result["comparison"]["balance"]) == Decimal("5860.00")
        assert result["services"][0]["rate_source"] == "daily_override"
        assert result["services"][0]["captured_rate"] == "100.0000"
        assert result["services"][0]["override_rate"] == "80.0000"
        assert result["consumables"][0]["rate_revision_number"] == 1
        assert result["consumables"][0]["baseline_budget_line_id"]
        bulk_budget = next(row for row in result["comparison"]["budget_lines"] if row["budget_kind"] == "consumable_category")
        assert bulk_budget["item_code"].startswith("BULK-")

        upline = {
            "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
            "phase_id": setup["phase"]["id"], "classification": "UPA", "vendor_id": setup["vendor"]["id"],
            "quantity": "1", "quantity_unit": "days", "currency": "USD", "override_rate": "300",
            "override_reason": "Unplanned diagnostic call-out", "remarks": "", "service_id": setup["service"]["id"],
            "baseline_service_rate_id": None, "charging_basis": "Day Rate", "charge_category": "Operation",
        }
        payload["services"].append(upline)
        updated = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload)
        assert updated.status_code == 200, updated.text
        assert Decimal(updated.json()["entry"]["upa_total"]) == Decimal("300.00")
        assert updated.json()["warnings"]

        imported = client.post(f"/api/v1/daily-cost/entries/{entry_id}/import", headers=headers, json={"rows": [{
            "line_type": "Service", "activity_code": "DRL", "service_code": "MUD-LOG",
            "baseline_service_rate_id": rate["id"], "classification": "Planned", "charge_category": "Operation",
            "quantity": "1", "quantity_unit": "days", "currency": "USD", "remarks": "Imported day",
        }]})
        assert imported.status_code == 200, imported.text
        assert imported.json()["success"] is True
        assert imported.json()["imported_count"] == 1
        # Imports validate the complete file before saving any row.
        rejected = client.post(f"/api/v1/daily-cost/entries/{entry_id}/import", headers=headers, json={"rows": [{
            "line_type": "Consumable", "activity_code": "UNKNOWN", "category": "Mud Chemicals",
            "item_code": "BARITE", "quantity": "1",
        }]})
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["success"] is False
        assert rejected.json()["error_count"] == 1
        assert len(client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers).json()["services"]) == 3

        submitted = client.post(f"/api/v1/daily-cost/entries/{entry_id}/submit", headers=headers, json={"remarks": "Reviewed"})
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["entry"]["status"] == "submitted"
        assert client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload).status_code == 409
        reopened = client.post(f"/api/v1/daily-cost/entries/{entry_id}/reopen", headers=headers, json={"remarks": "Correcting shift report"})
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["entry"]["status"] == "draft"

        overview = client.get("/api/v1/daily-cost/overview", headers=headers)
        assert overview.status_code == 200, overview.text
        assert overview.json()["active_entries"] == 1
        assert "USD" in overview.json()["actual_to_date_by_currency"]

        assert client.delete(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers).status_code == 200
        assert client.get("/api/v1/daily-cost/entries", headers=headers).json() == []
        assert len(client.get("/api/v1/daily-cost/entries/deleted", headers=headers).json()) == 1
        assert client.post(f"/api/v1/daily-cost/entries/{entry_id}/restore", headers=headers).status_code == 200
        assert client.get("/api/v1/daily-cost/entries", headers=headers).json()[0]["id"] == entry_id

        # The closest earlier sheet of the same well and AFE feeds the copy-forward flow.
        day_two = client.post("/api/v1/daily-cost/entries", headers=headers, json={
            "well_id": setup["well"]["id"], "afe_id": setup["afe"]["id"], "cost_date": "2026-10-11", "remarks": "Next day",
        })
        assert day_two.status_code == 201, day_two.text
        day_two_id = day_two.json()["entry"]["id"]
        previous = client.get(f"/api/v1/daily-cost/entries/{day_two_id}/previous", headers=headers)
        assert previous.status_code == 200, previous.text
        assert previous.json()["entry"]["id"] == entry_id
        assert len(previous.json()["services"]) == 3
        # A first sheet has nothing earlier to copy from.
        first_sheet_previous = client.get(f"/api/v1/daily-cost/entries/{entry_id}/previous", headers=headers)
        assert first_sheet_previous.status_code == 404
        assert "no earlier daily cost sheet" in first_sheet_previous.json()["detail"]

        with SessionLocal() as db:
            actions = {row.action for row in db.query(AuditLog).all()}
            assert {"rate_override", "import", "submit", "reopen", "soft_delete", "restore"}.issubset(actions)


def test_daily_cost_is_tenant_scoped_and_rejects_unjustified_upa():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        setup = _setup_daily_sheet(client, north)
        entry_id = setup["entry"]["id"]
        assert client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=south).status_code == 404
        assert client.get("/api/v1/daily-cost/entries", headers=south).json() == []

        invalid = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=north, json={
            "remarks": "", "services": [{
                "activity_id": setup["activity"]["id"], "classification": "UPA", "quantity": "1",
                "currency": "USD", "service_id": setup["service"]["id"], "charging_basis": "Day Rate",
                "charge_category": "Operation", "quantity_unit": "days", "override_rate": "200",
                "override_reason": "", "party_name": "Acme Services",
            }], "consumables": [], "tangibles": [],
        })
        assert invalid.status_code == 422
        assert "reason" in invalid.text.lower()


def test_locked_queries_stay_single_table_for_postgresql():
    """Row locks must never ride on an outer join.

    PostgreSQL rejects ``SELECT ... FOR UPDATE`` over the nullable side of a
    LEFT OUTER JOIN with ``FeatureNotSupported``; SQLite silently accepts it.
    The daily-cost models declare ``lazy="joined"`` references, so every locked
    statement must override them with selectin loads. This was a live
    production 500 on ``POST /api/v1/daily-cost/entries`` (and on save, submit,
    reopen, delete and restore) for PostgreSQL deployments.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.services import daily_cost as service

    # The statement builders used by every write path must produce a
    # single-table statement: FOR UPDATE without any JOIN.
    for statement in (
        service._entry_statement(deleted=False, lock=True),
        service._baseline_statement("org-1", "afe-1", lock=True),
    ):
        sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))
        assert "FOR UPDATE" in sql
        assert "JOIN" not in sql, f"Locked daily-cost query must stay single-table, got: {sql}"
