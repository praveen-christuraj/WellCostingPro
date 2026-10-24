import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
# Set TEST_DATABASE_URL (a PostgreSQL URL, as CI does) to run this suite against
# a real server instead of the throwaway SQLite file.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import (
    AuditLog, DailyCostBaseline, DailyCostEntry, DailyCostWellRateBaseline, Organization,
    Permission, Role, User,
)
from app.services import daily_cost as daily_cost_service


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


def _setup_daily_sheet(client, headers, *, with_sub_activities=True, create_entry=True):
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
        "service_group": "Formation Evaluation", "provider_type": "Third Party Services", "vendor_id": vendor["id"], "description": "Wellsite logging crew",
    })
    rig = _post(client, "/api/v1/rig-well/rigs", headers, {"rig_code": "RIG-01", "rig_name": "Rig One", "remarks": ""})
    block = _post(client, "/api/v1/rig-well/blocks", headers, {
        "block_code": "BLOCK-A", "block_name": "Block A", "description": "",
    })
    well = _post(client, "/api/v1/rig-well/wells", headers, {
        "rig_id": rig["id"], "block_id": block["id"], "well_code": "WELL-01", "well_name": "Well One",
        "well_location": "North field", "objective": "Development", "remarks": "",
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

    def make_sub(code, activity_id):
        return _post(client, "/api/v1/rig-well/sub-activities", headers, {
            "well_id": well["id"], "sub_activity_code": code, "sub_activity_name": f"Sub activity {code}",
            "activity_id": activity_id, "responsible_party": "Operations team",
            "description": "Execute the planned work step.",
        })

    sub1 = make_sub("SA-D1", activity["id"]) if with_sub_activities else None
    sub2 = make_sub("SA-D2", activity["id"]) if with_sub_activities else None
    sub3 = make_sub("SA-D3", activity["id"]) if with_sub_activities else None
    sub_upa = make_sub("SA-U1", activity_upa["id"]) if with_sub_activities else None
    sub_npt = make_sub("SA-N1", activity_npt["id"]) if with_sub_activities else None
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
    setup = {
        "activity": activity,
        "activity_upa": activity_upa,
        "activity_npt": activity_npt,
        "sub1": sub1,
        "sub2": sub2,
        "sub3": sub3,
        "sub_upa": sub_upa,
        "sub_npt": sub_npt,
        "chemical": chemical,
        "vendor": vendor,
        "service": service,
        "hole": hole,
        "phase": phase,
        "rig": rig,
        "block": block,
        "well": well,
        "afe": afe,
    }
    if not create_entry:
        return setup
    created = _post(client, "/api/v1/daily-cost/entries", headers, {
        "well_id": well["id"], "afe_id": afe["id"], "cost_date": "2026-10-10", "remarks": "Night shift",
    })
    setup["entry"] = created["entry"]
    setup["baseline"] = client.get(f"/api/v1/daily-cost/entries/{created['entry']['id']}/baseline", headers=headers).json()
    return setup


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
                "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"],
                "vendor_id": setup["vendor"]["id"],
                "quantity": "12", "quantity_unit": "hours", "currency": "USD", "override_rate": "80",
                "override_reason": "Agreed reduced rate for night shift", "remarks": "Half-day operation",
                "service_id": setup["service"]["id"], "baseline_service_rate_id": rate["id"],
                "charging_basis": "Day Rate", "charge_category": "Operation",
            }],
            "consumables": [{
                "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
                "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"], "vendor_id": None,
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
        assert Decimal(result["services"][0]["captured_rate"]) == Decimal("100.0000")
        assert Decimal(result["services"][0]["override_rate"]) == Decimal("80.0000")
        assert result["consumables"][0]["rate_revision_number"] == 1
        assert result["consumables"][0]["baseline_budget_line_id"]
        bulk_budget = next(row for row in result["comparison"]["budget_lines"] if row["budget_kind"] == "consumable_category")
        assert bulk_budget["item_code"].startswith("BULK-")

        upline = {
            "activity_id": setup["activity_upa"]["id"], "hole_section_id": setup["hole"]["id"],
            "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub_upa"]["id"],
            "vendor_id": setup["vendor"]["id"],
            "quantity": "1", "quantity_unit": "days", "currency": "USD", "override_rate": "300",
            "override_reason": "Unplanned diagnostic call-out", "remarks": "", "service_id": setup["service"]["id"],
            "baseline_service_rate_id": None, "charging_basis": "Day Rate", "charge_category": "Operation",
        }
        payload["services"].append(upline)
        updated = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload)
        assert updated.status_code == 200, updated.text
        assert Decimal(updated.json()["entry"]["upa_total"]) == Decimal("300.00")
        assert updated.json()["services"][1]["service_group"] == "Formation Evaluation"
        unplanned_row = next(
            row for row in updated.json()["comparison"]["budget_lines"]
            if row["budget_key"].startswith("unplanned:service:")
        )
        # An unplanned service still prints in its Master Data group at entry time.
        assert unplanned_row["service_group"] == "Formation Evaluation"
        assert updated.json()["warnings"]

        imported = client.post(f"/api/v1/daily-cost/entries/{entry_id}/import", headers=headers, json={"rows": [{
            "line_type": "Service", "activity_code": "DRL", "sub_activity_code": "SA-D2", "service_code": "MUD-LOG",
            "baseline_service_rate_id": rate["id"], "charge_category": "Operation",
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
                "activity_id": setup["activity_upa"]["id"], "sub_activity_id": setup["sub_upa"]["id"],
                "quantity": "1", "currency": "USD", "service_id": setup["service"]["id"],
                "charging_basis": "Day Rate", "charge_category": "Operation", "quantity_unit": "days",
                "override_rate": "200", "override_reason": "", "party_name": "Acme Services",
            }], "consumables": [], "tangibles": [],
        })
        assert invalid.status_code == 422
        assert "reason" in invalid.text.lower()

        # UPA/NPT work (derived from the Master Data Activity) must identify who is responsible.
        unattributed = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=north, json={
            "remarks": "", "services": [{
                "activity_id": setup["activity_upa"]["id"], "sub_activity_id": setup["sub_upa"]["id"],
                "quantity": "1", "currency": "USD", "service_id": setup["service"]["id"],
                "charging_basis": "Day Rate", "charge_category": "Operation", "quantity_unit": "days",
                "override_rate": "200", "override_reason": "Unplanned call-out", "party_name": "",
            }], "consumables": [], "tangibles": [],
        })
        assert unattributed.status_code == 422
        assert "vendor or responsible party" in unattributed.text.lower()


def test_daily_cost_import_reports_an_unknown_charging_basis_instead_of_failing():
    """A typo in an imported sheet is a row error, never a 500."""
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]
        response = client.post(f"/api/v1/daily-cost/entries/{entry_id}/import", headers=headers, json={"rows": [{
            "line_type": "Service", "activity_code": "NPT", "sub_activity_code": "SA-N1", "service_code": "MUD-LOG",
            # A legacy "classification" column is accepted in files but ignored:
            # classification is derived from the selected Master Data Activity.
            "classification": "NPT", "charging_basis": "Monthly", "quantity": "1",
            "quantity_unit": "days", "currency": "USD", "override_rate": "150",
            "override_reason": "Unplanned call-out", "party_name": "Acme Services",
        }]})
        assert response.status_code == 200, response.text
        assert response.json()["success"] is False
        assert "Charging basis" in " ".join(response.json()["errors"])

        # The same value written the way an operator types it is accepted.
        accepted = client.post(f"/api/v1/daily-cost/entries/{entry_id}/import", headers=headers, json={"rows": [{
            "line_type": "Service", "activity_code": "NPT", "sub_activity_code": "SA-N1", "service_code": "MUD-LOG",
            "classification": "NPT", "charging_basis": "day rate", "quantity": "1",
            "quantity_unit": "days", "currency": "USD", "override_rate": "150",
            "override_reason": "Unplanned call-out", "party_name": "Acme Services",
        }]})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["success"] is True, accepted.text
        saved_line = client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers).json()["services"][0]
        assert saved_line["classification"] == "NPT"


def test_daily_cost_reference_and_sheet_survive_an_unusable_afe():
    """One broken AFE must not take the whole Daily Cost module down with a 500."""
    with SessionLocal() as db:
        organization_id = db.query(Organization).filter(Organization.slug == "north").one().id
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)

        from app.models import Afe
        from app.services import afe as afe_service

        with SessionLocal() as db:
            db.add(Afe(
                id="afe-broken", organization_id=organization_id, rig_id=setup["rig"]["id"],
                well_id=setup["well"]["id"], afe_code="AFE-BROKEN", afe_name="Broken estimate",
                afe_type="Drilling", status="draft",
            ))
            db.commit()

        original = afe_service.get_estimate

        def explode(db, organization_id, afe_id, *args, **kwargs):
            if afe_id == "afe-broken":
                raise RuntimeError("this stored estimate cannot be read")
            return original(db, organization_id, afe_id, *args, **kwargs)

        afe_service.get_estimate = explode
        try:
            reference = client.get("/api/v1/daily-cost/reference", headers=headers)
            assert reference.status_code == 200, reference.text
            assert [afe["afe_code"] for afe in reference.json()["afes"]] == ["AFE-01"]
            assert client.get("/api/v1/daily-cost/overview", headers=headers).status_code == 200
            assert client.get(f"/api/v1/daily-cost/entries/{setup['entry']['id']}", headers=headers).status_code == 200
        finally:
            afe_service.get_estimate = original


def test_well_cost_summary_reports_daily_and_factor_views():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]
        baseline = setup["baseline"]
        rate = baseline["service_rates"][0]
        for index, day in enumerate(("2026-10-10", "2026-10-11")):
            if index:
                created = client.post("/api/v1/daily-cost/entries", headers=headers, json={
                    "well_id": setup["well"]["id"], "afe_id": setup["afe"]["id"],
                    "cost_date": day, "remarks": "",
                })
                assert created.status_code == 201, created.text
                entry_id = created.json()["entry"]["id"]
            saved = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json={
                "remarks": "day actuals",
                "services": [{
                    "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
                    "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"],
                    "vendor_id": setup["vendor"]["id"], "quantity": "12", "quantity_unit": "hours",
                    "currency": "USD", "service_id": setup["service"]["id"],
                    "baseline_service_rate_id": rate["id"], "charging_basis": "Day Rate",
                    "charge_category": "Operation",
                }],
                "consumables": [{
                    "activity_id": setup["activity_upa"]["id"], "hole_section_id": setup["hole"]["id"],
                    "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub_upa"]["id"],
                    "vendor_id": setup["vendor"]["id"], "quantity": "3", "currency": "USD",
                    "override_rate": "50", "override_reason": "Extra mud on the margin",
                    "category": "Mud Chemicals", "item_kind": "mud_chemical", "item_id": setup["chemical"]["id"],
                }],
                "tangibles": [],
            })
            assert saved.status_code == 200, saved.text
            assert client.post(f"/api/v1/daily-cost/entries/{entry_id}/submit", headers=headers,
                               json={"remarks": "reviewed"}).status_code == 200

        wells = client.get("/api/v1/daily-cost/wells", headers=headers)
        assert wells.status_code == 200, wells.text
        assert [well["id"] for well in wells.json()] == [setup["well"]["id"]]

        summary = client.get(f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-summary", headers=headers)
        assert summary.status_code == 200, summary.text
        data = summary.json()
        assert data["totals"]["currency"] == "USD"
        assert data["totals"]["recorded_days"] == 2
        assert data["totals"]["elapsed_days"] == 2
        assert data["totals"]["sheets"] == 2
        assert data["totals"]["submitted_sheets"] == 2
        assert data["totals"]["lines"] == 4
        assert Decimal(data["totals"]["actual"]) == Decimal("400.00")  # 2 x (50 day rate + 150 mud)
        assert Decimal(data["totals"]["services"]) == Decimal("100.00")
        assert Decimal(data["totals"]["consumables"]) == Decimal("300.00")
        assert Decimal(data["totals"]["upa"]) == Decimal("300.00")
        assert Decimal(data["totals"]["balance"]) == Decimal("5600.00")
        assert [row["cost_date"] for row in data["daily"]] == ["2026-10-10", "2026-10-11"]
        assert Decimal(data["daily"][-1]["cumulative"]) == Decimal(data["totals"]["actual"])
        assert Decimal(data["daily"][0]["budget_balance"]) == Decimal("5800.00")
        assert Decimal(data["daily"][0]["total"]) == Decimal("200.00")

        factors = {group["dimension"]: group for group in data["factors"]}
        assert factors["classification"]["rows"][0]["code"] == "UPA"
        assert {row["code"] for row in factors["classification"]["rows"]} == {"Planned", "UPA"}
        # Classification comes from the Master Data Activity (DRL = planned, UPA = unplanned).
        activity_rows = {row["code"]: row for row in factors["activity"]["rows"]}
        assert Decimal(activity_rows["DRL"]["amount"]) == Decimal("100.00")
        assert Decimal(activity_rows["UPA"]["amount"]) == Decimal("300.00")
        assert Decimal(factors["activity"]["rows"][0]["share"]) == Decimal("75.00")
        party = factors["party"]["rows"][0]
        assert party["name"] == "Acme Services"
        assert sorted(row["name"] for row in factors["rate_source"]["rows"]) == [
            "Daily override (justified)", "Locked AFE rate",
        ]
        assert sorted(row["name"] for row in factors["item"]["rows"]) == ["Barite", "Mud logging"]
        section = factors["section"]["rows"][0]
        assert section["code"] == "17-1/2" and Decimal(section["planned"]) == Decimal("5000.00")
        assert Decimal(factors["cost_group"]["total"]) == Decimal("6000.00")
        planned_keys = {row["budget_key"]: row for row in data["budget_lines"]}
        assert Decimal(planned_keys[f"service:{rate['source_afe_line_id']}"]["actual_to_date"]) == Decimal("100.00")

        # The service-wise report prints the cumulative actual split by the
        # activity classification of the daily lines (Planned / UPA / NPT).
        service_row = planned_keys[f"service:{rate['source_afe_line_id']}"]
        # The locked AFE snapshot carries the Master Data reporting group into the report.
        assert service_row["service_group"] == "Formation Evaluation"
        baseline_budget = client.get(f"/api/v1/daily-cost/entries/{entry_id}/baseline", headers=headers)
        assert baseline_budget.status_code == 200, baseline_budget.text
        assert next(
            row for row in baseline_budget.json()["budget_lines"] if row["budget_kind"] == "service"
        )["service_group"] == "Formation Evaluation"
        assert Decimal(service_row["actual_planned"]) == Decimal("100.00")
        assert Decimal(service_row["actual_upa"]) == Decimal("0.00")
        assert Decimal(service_row["actual_npt"]) == Decimal("0.00")
        # A budget key can mix classifications; the split still adds up to its actual.
        for row in data["budget_lines"]:
            assert Decimal(row["actual_planned"]) + Decimal(row["actual_upa"]) + Decimal(row["actual_npt"]) == Decimal(row["actual_to_date"])
        assert Decimal(data["totals"]["services_actual_planned"]) == Decimal("100.00")
        assert Decimal(data["totals"]["services_actual_upa"]) == Decimal("0.00")
        assert Decimal(data["totals"]["services_actual_npt"]) == Decimal("0.00")
        # The report title needs the well scope of the AFEs behind the sheets.
        assert [afe["configuration_scope"] for afe in data["well"]["afes"]] == ["drilling"]
        reference = client.get("/api/v1/daily-cost/reference", headers=headers)
        assert reference.status_code == 200, reference.text
        assert [afe["configuration_scope"] for afe in reference.json()["afes"]] == ["drilling"]

        # Submitted-only and date-range views narrow the same ledger.
        submitted_only = client.get(
            f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-summary?include_draft=false", headers=headers)
        assert submitted_only.status_code == 200
        assert submitted_only.json()["totals"]["actual"] == data["totals"]["actual"]
        single_day = client.get(
            f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-summary?from=2026-10-11&to=2026-10-11", headers=headers)
        assert len(single_day.json()["daily"]) == 1
        assert Decimal(single_day.json()["totals"]["actual"]) == Decimal("200.00")

        # The register filters daily: well, AFE, status and date range.
        filtered = client.get(
            f"/api/v1/daily-cost/entries?well_id={setup['well']['id']}&status=submitted&from=2026-10-11", headers=headers)
        assert filtered.status_code == 200, filtered.text
        assert [row["cost_date"] for row in filtered.json()] == ["2026-10-11"]
        assert client.get(
            "/api/v1/daily-cost/entries?status=submitted&from=2030-01-01", headers=headers).json() == []


def test_cost_report_exposes_the_well_scope_used_by_the_print_title():
    """A report titles itself "Drilling" or "Completions" from the AFE it costs."""
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)

        from app.models import Afe
        with SessionLocal() as db:
            afe = db.get(Afe, setup["afe"]["id"])
            afe.configuration_scope = "completion"
            db.commit()

        summary = client.get(f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-summary", headers=headers)
        assert summary.status_code == 200, summary.text
        assert [row["configuration_scope"] for row in summary.json()["well"]["afes"]] == ["completion"]

        report = client.get(
            f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-report?to=2026-10-10", headers=headers)
        assert report.status_code == 200, report.text
        assert [day["progress"]["scope"] for day in report.json()] == ["completion"]

        reference = client.get("/api/v1/daily-cost/reference", headers=headers)
        assert reference.status_code == 200, reference.text
        assert [row["configuration_scope"] for row in reference.json()["afes"]] == ["completion"]


def test_one_time_day_rate_is_charged_once_even_when_quantity_is_entered():
    """A unit-priced mobilisation must not multiply its rate by the UI quantity."""
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        one_time_afe = _post(client, "/api/v1/afe/afes", headers, {
            "rig_id": setup["rig"]["id"], "well_id": setup["well"]["id"], "afe_code": "AFE-MOB",
            "afe_name": "Mobilisation AFE", "afe_type": "Drilling", "remarks": "",
        }, status=200)
        estimate = client.put(f"/api/v1/afe/afes/{one_time_afe['id']}/estimate", headers=headers, json={
            "services": [{
                "client_key": "service-mobilisation", "service_id": setup["service"]["id"],
                "charging_basis": "Day Rate", "hole_section_id": None, "phase_id": None,
                "currency": "USD", "service_amount": "0", "remarks": "",
                "rates": [{"category": "Mobilization", "unit_rate": "250"}],
                "charges": [],
                "section_rates": [],
            }],
            "consumables": [], "tangibles": [], "standard_currency": "", "exchange_rates": [],
        })
        assert estimate.status_code == 200, estimate.text
        created = _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": setup["well"]["id"], "afe_id": one_time_afe["id"],
            "cost_date": "2026-10-12", "remarks": "Mobilisation day",
        })
        baseline = client.get(f"/api/v1/daily-cost/entries/{created['entry']['id']}/baseline", headers=headers)
        assert baseline.status_code == 200, baseline.text
        rate = next(row for row in baseline.json()["service_rates"] if row["charge_category"] == "Mobilization")
        payload = {
            "remarks": "Mobilisation actual",
            "services": [{
                "activity_id": setup["activity"]["id"], "hole_section_id": None, "phase_id": None,
                "sub_activity_id": setup["sub1"]["id"], "vendor_id": setup["vendor"]["id"], "party_name": "",
                # A quantity above one is intentionally supplied: the category is still one unit.
                "quantity": "7", "quantity_unit": "unit", "currency": "USD",
                "override_rate": None, "override_reason": "", "remarks": "",
                "service_id": setup["service"]["id"], "baseline_service_rate_id": rate["id"],
                "charging_basis": "Day Rate", "charge_category": "Mobilization",
            }],
            "consumables": [], "tangibles": [],
        }
        preview = client.put(f"/api/v1/daily-cost/entries/{created['entry']['id']}/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        assert Decimal(preview.json()["services_total"]) == Decimal("250.00")
        saved = client.put(f"/api/v1/daily-cost/entries/{created['entry']['id']}", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        assert Decimal(saved.json()["entry"]["services_total"]) == Decimal("250.00")


def test_daily_cost_flush_database_errors_return_an_actionable_conflict():
    """Baseline flush failures must be mapped, not leaked as an HTTP 500."""
    class BrokenSession:
        rolled_back = False

        def flush(self):
            raise IntegrityError("duplicate baseline", {}, RuntimeError("duplicate"))

        def rollback(self):
            self.rolled_back = True

    session = BrokenSession()
    with pytest.raises(HTTPException) as raised:
        daily_cost_service._flush(session, operation="test baseline")
    assert raised.value.status_code == 409
    assert session.rolled_back is True


def test_classify_activity_derives_planned_upa_and_npt():
    """Classification is the Activity's job; naming conventions map to Planned/UPA/NPT."""
    from types import SimpleNamespace

    classify = daily_cost_service.classify_activity
    assert classify(SimpleNamespace(activity_code="DRL", activity_name="Drilling")) == "Planned"
    assert classify(SimpleNamespace(activity_code="UPA", activity_name="Unplanned activity")) == "UPA"
    assert classify(SimpleNamespace(activity_code="X", activity_name="Unplanned fishing job")) == "UPA"
    assert classify(SimpleNamespace(activity_code="NPT", activity_name="Waiting on weather")) == "NPT"
    assert classify(SimpleNamespace(activity_code="X", activity_name="Non-Productive Time")) == "NPT"
    assert classify(SimpleNamespace(activity_code="X", activity_name="Non productive")) == "NPT"


def test_daily_cost_requires_configured_well_sub_activities():
    """Daily cost entry for a well is blocked until its sub activities exist in Rig & Well Management."""
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers, with_sub_activities=False, create_entry=False)
        blocked = client.post("/api/v1/daily-cost/entries", headers=headers, json={
            "well_id": setup["well"]["id"], "afe_id": setup["afe"]["id"], "cost_date": "2026-10-10", "remarks": "",
        })
        assert blocked.status_code == 422, blocked.text
        assert "sub activity" in blocked.text.lower()
        assert "rig & well management" in blocked.text.lower()

        _post(client, "/api/v1/rig-well/sub-activities", headers, {
            "well_id": setup["well"]["id"], "sub_activity_code": "SA-D1", "sub_activity_name": "Sub activity SA-D1",
            "activity_id": setup["activity"]["id"], "responsible_party": "Operations team",
            "description": "Execute the planned work step.",
        })
        created = client.post("/api/v1/daily-cost/entries", headers=headers, json={
            "well_id": setup["well"]["id"], "afe_id": setup["afe"]["id"], "cost_date": "2026-10-10", "remarks": "",
        })
        assert created.status_code == 201, created.text


def test_daily_cost_lines_require_sub_activity_and_split_service_by_sub_activity():
    """Same date + well: one service may repeat only when the sub activity changes (18h/3h/3h)."""
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]
        rate = setup["baseline"]["service_rates"][0]

        def line(sub_id, quantity):
            return {
                "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
                "phase_id": setup["phase"]["id"], "sub_activity_id": sub_id,
                "vendor_id": setup["vendor"]["id"], "quantity": quantity, "quantity_unit": "hours",
                "currency": "USD", "service_id": setup["service"]["id"],
                "baseline_service_rate_id": rate["id"], "charging_basis": "Day Rate",
                "charge_category": "Operation",
            }

        def save(services):
            return client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json={
                "remarks": "Split operation", "services": services, "consumables": [], "tangibles": [],
            })

        # Every line must name the well sub activity configured in Rig & Well Management.
        missing = save([{**line(setup["sub1"]["id"], "18"), "sub_activity_id": None}])
        assert missing.status_code == 422, missing.text
        assert "sub activity" in missing.text.lower()

        # The same service twice under the same sub activity is a duplicate entry.
        duplicate = save([line(setup["sub1"]["id"], "18"), line(setup["sub1"]["id"], "3")])
        assert duplicate.status_code == 422, duplicate.text
        assert "different sub activity" in duplicate.text.lower()

        # The same service split across sub activities is recorded as separate costed lines.
        saved = save([line(setup["sub1"]["id"], "18"), line(setup["sub2"]["id"], "3"), line(setup["sub3"]["id"], "3")])
        assert saved.status_code == 200, saved.text
        rows = saved.json()["services"]
        assert [row["sub_activity_code"] for row in rows] == ["SA-D1", "SA-D2", "SA-D3"]
        assert [Decimal(str(row["quantity"])) for row in rows] == [Decimal("18"), Decimal("3"), Decimal("3")]
        assert Decimal(saved.json()["entry"]["services_total"]) == Decimal("100.00")  # 24h = 1 x $100 day rate


def test_daily_cost_classification_is_derived_from_the_master_data_activity():
    """UPA/NPT totals come from the selected Activity; classification is not an input."""
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]
        rate = setup["baseline"]["service_rates"][0]
        planned = {
            "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
            "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"],
            "vendor_id": setup["vendor"]["id"], "quantity": "1", "quantity_unit": "days",
            "currency": "USD", "service_id": setup["service"]["id"],
            "baseline_service_rate_id": rate["id"], "charging_basis": "Day Rate",
            "charge_category": "Operation",
        }
        upa = {
            "activity_id": setup["activity_upa"]["id"], "hole_section_id": setup["hole"]["id"],
            "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub_upa"]["id"],
            "vendor_id": setup["vendor"]["id"], "quantity": "1", "quantity_unit": "days",
            "currency": "USD", "service_id": setup["service"]["id"], "baseline_service_rate_id": None,
            "charging_basis": "Day Rate", "charge_category": "Operation",
            "override_rate": "300", "override_reason": "Unplanned diagnostic call-out",
        }
        npt = {
            "activity_id": setup["activity_npt"]["id"], "hole_section_id": setup["hole"]["id"],
            "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub_npt"]["id"],
            "vendor_id": setup["vendor"]["id"], "quantity": "1", "quantity_unit": "days",
            "currency": "USD", "service_id": setup["service"]["id"], "baseline_service_rate_id": None,
            "charging_basis": "Day Rate", "charge_category": "Operation",
            "override_rate": "500", "override_reason": "Stuck downhole fishing job",
        }
        saved = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json={
            "remarks": "Classification derives from the Activity",
            "services": [planned, upa, npt], "consumables": [], "tangibles": [],
        })
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert [row["classification"] for row in result["services"]] == ["Planned", "UPA", "NPT"]
        assert Decimal(result["entry"]["upa_total"]) == Decimal("300.00")
        assert Decimal(result["entry"]["npt_total"]) == Decimal("500.00")

        # Classification is no longer an accepted line field.
        rejected = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json={
            "remarks": "", "services": [{**planned, "classification": "NPT"}], "consumables": [], "tangibles": [],
        })
        assert rejected.status_code == 422, rejected.text


# ---------------------------------------------------------------------------
# Production-parity guard: PostgreSQL rejects FOR UPDATE over an outer join.
#
# Every Daily Cost write locks a row. The models load several many-to-one
# references with ``lazy="joined"``, so an entity-shaped (or eager-loading)
# locked SELECT emits LEFT OUTER JOIN ... FOR UPDATE, which PostgreSQL refuses
# with "FOR UPDATE cannot be applied to the nullable side of an outer join"
# (SQLSTATE 0A000). SQLite ignores the clause, so the suite stayed green while
# production answered 503 on every create/save/submit/delete call. These tests
# re-compile each executed statement for the PostgreSQL dialect, which is what
# makes the difference visible without a PostgreSQL server in CI. Set
# TEST_DATABASE_URL to a PostgreSQL URL to run the whole suite on the real thing.
# --------------------------------------------------------------------------


@contextmanager
def _postgres_row_locks():
    """Collect the row-locking statements the API issues inside the block."""
    seen: list[str] = []

    def capture(conn, clauseelement, multiparams, params, execution_options):
        try:
            sql = str(clauseelement.compile(dialect=postgresql.dialect()))
        except Exception:  # non-SQL elements and raw text are never row locks
            return
        if "FOR UPDATE" in sql.upper():
            seen.append(sql)

    event.listen(engine, "before_execute", capture)
    try:
        yield seen
    finally:
        event.remove(engine, "before_execute", capture)


def test_row_lock_helper_stays_single_table_for_every_daily_cost_model():
    with TestClient(app):
        with _postgres_row_locks() as locked:
            with SessionLocal() as db:
                assert daily_cost_service._lock_row_id(db, DailyCostEntry, DailyCostEntry.id == "missing") is None
                assert daily_cost_service._lock_row_id(db, DailyCostBaseline, DailyCostBaseline.id == "missing") is None
                assert daily_cost_service._lock_row_id(
                    db, DailyCostWellRateBaseline, DailyCostWellRateBaseline.id == "missing"
                ) is None
    assert len(locked) == 3, "each lock must still reach the database with FOR UPDATE"
    offenders = [sql for sql in locked if " JOIN " in sql.upper()]
    assert offenders == [], "row locks must never join; PostgreSQL rejects FOR UPDATE over an outer join"


def test_every_daily_cost_write_locks_without_a_join():
    """The whole write lifecycle, checked against the PostgreSQL dialect."""
    with TestClient(app) as client:
        headers = login(client)
        with _postgres_row_locks() as locked:
            setup = _setup_daily_sheet(client, headers)  # POST /entries locks both baselines
            entry_id = setup["entry"]["id"]
            rate = setup["baseline"]["service_rates"][0]
            payload = {
                "remarks": "Regression flow",
                "services": [{
                    "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
                    "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"],
                    "vendor_id": setup["vendor"]["id"],
                    "quantity": "12", "quantity_unit": "hours", "currency": "USD", "override_rate": None,
                    "override_reason": "", "remarks": "Drilling", "service_id": setup["service"]["id"],
                    "baseline_service_rate_id": rate["id"], "charging_basis": "Day Rate",
                    "charge_category": "Operation",
                }],
                "consumables": [], "tangibles": [],
            }
            assert client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload).status_code == 200
            assert client.post(f"/api/v1/daily-cost/entries/{entry_id}/submit", headers=headers,
                               json={"remarks": "Reviewed"}).status_code == 200
            assert client.post(f"/api/v1/daily-cost/entries/{entry_id}/reopen", headers=headers,
                               json={"remarks": "Correction"}).status_code == 200
            assert client.delete(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers).status_code == 200
            assert client.post(f"/api/v1/daily-cost/entries/{entry_id}/restore", headers=headers).status_code == 200

        assert locked, "the daily cost write paths must take row locks"
        offenders = [sql for sql in locked if " JOIN " in sql.upper()]
        assert offenders == [], (
            "PostgreSQL rejects FOR UPDATE over the nullable side of an outer join "
            "(HTTP 503 on every write). Keep row locks single-table:\n" + "\n".join(offenders)
        )


def test_well_cost_report_is_complete_scoped_and_respects_dates_status_and_deletion():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        well_id, entry_id = setup["well"]["id"], setup["entry"]["id"]
        saved = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json={
            "remarks": "Full shift record",
            "services": [{
                "activity_id": setup["activity"]["id"], "sub_activity_id": setup["sub1"]["id"],
                "hole_section_id": setup["hole"]["id"], "phase_id": setup["phase"]["id"],
                "vendor_id": setup["vendor"]["id"], "service_id": setup["service"]["id"],
                "baseline_service_rate_id": setup["baseline"]["service_rates"][0]["id"],
                "charging_basis": "Day Rate", "charge_category": "Operation", "quantity": "12",
                "quantity_unit": "hours", "currency": "USD", "remarks": "Service remarks",
            }], "consumables": [], "tangibles": [],
        })
        assert saved.status_code == 200, saved.text
        assert client.post(f"/api/v1/daily-cost/entries/{entry_id}/submit", headers=headers,
                           json={"remarks": "Reviewed"}).status_code == 200
        draft = _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": well_id, "afe_id": setup["afe"]["id"], "cost_date": "2026-10-11",
        })
        future = _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": well_id, "afe_id": setup["afe"]["id"], "cost_date": "2099-01-01",
        })
        path = f"/api/v1/daily-cost/wells/{well_id}/cost-report"
        report = client.get(path + "?to=2026-10-13", headers=headers)
        assert report.status_code == 200, report.text
        assert [day["entry"]["id"] for day in report.json()] == [entry_id, draft["entry"]["id"]]
        assert report.json()[0]["services"] == saved.json()["services"]
        assert report.json()[0]["entry"]["remarks"] == "Full shift record"
        assert report.json()[0]["entry"]["status_remarks"] == "Reviewed"
        assert report.json()[1]["services"] == []
        submitted = client.get(path + "?include_draft=false&to=2026-10-13", headers=headers).json()
        assert [day["entry"]["id"] for day in submitted] == [entry_id]
        single = client.get(path + "?from=2026-10-11&to=2026-10-11", headers=headers).json()
        assert [day["entry"]["id"] for day in single] == [draft["entry"]["id"]]
        assert client.get(path + "?from=2026-10-12&to=2026-10-11", headers=headers).status_code == 422
        assert future["entry"]["id"] not in [day["entry"]["id"] for day in client.get(path, headers=headers).json()]
        assert client.delete(f"/api/v1/daily-cost/entries/{draft['entry']['id']}", headers=headers).status_code == 200
        assert len(client.get(path + "?to=2026-10-13", headers=headers).json()) == 1
        assert client.get(path, headers=login(client, "south")).status_code == 404
        other_block = _post(client, "/api/v1/rig-well/blocks", headers, {
            "block_code": "BLOCK-B", "block_name": "Block B", "description": "",
        })
        other = _post(client, "/api/v1/rig-well/wells", headers, {
            "rig_id": setup["rig"]["id"], "block_id": other_block["id"], "well_code": "WELL-02",
            "well_name": "Other well", "well_location": "Other field", "objective": "Development",
        })
        assert client.get(f"/api/v1/daily-cost/wells/{other['id']}/cost-report", headers=headers).json() == []
        summary = client.get(f"/api/v1/daily-cost/wells/{well_id}/cost-summary?include_draft=false", headers=headers)
        assert summary.json()["totals"]["sheets"] == 1
        assert client.get(f"/api/v1/daily-cost/wells/{well_id}/cost-summary?from=2026-10-12&to=2026-10-11", headers=headers).status_code == 422


def test_well_cost_report_requires_read_and_export_and_audits_scope():
    from sqlalchemy import select
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        path = f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-report"
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "owner@example.com", User.organization_id == select(Organization.id).where(Organization.slug == "north").scalar_subquery()))
            role = user.roles[0]
            role.is_owner = False
            role.permissions = [permission for permission in role.permissions if permission.key != "daily-cost:export"]
            db.commit()
        assert client.get(path, headers=headers).status_code == 403
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.organization_id == select(Organization.id).where(Organization.slug == "north").scalar_subquery()))
            role.permissions.append(db.scalar(select(Permission).where(
                Permission.organization_id == role.organization_id, Permission.key == "daily-cost:export")))
            role.permissions = [permission for permission in role.permissions if permission.key != "daily-cost:read"]
            db.commit()
        assert client.get(path, headers=headers).status_code == 403
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.organization_id == select(Organization.id).where(Organization.slug == "north").scalar_subquery()))
            role.is_owner = True
            db.commit()
        assert client.post("/api/v1/daily-cost/export-audit", headers=headers, json={
            "module": "well-cost-sheet", "format": "pdf", "record_count": 1,
            "well_id": setup["well"]["id"], "date_from": "2026-10-10", "date_to": "2026-10-13",
            "include_draft": False,
        }).status_code == 204
        with SessionLocal() as db:
            audit = db.scalar(select(AuditLog).where(AuditLog.entity_type == "daily_cost_export"))
            assert setup["well"]["id"] in audit.summary
            assert "2026-10-10 to 2026-10-13" in audit.summary
            assert "include drafts: False" in audit.summary


def test_well_analysis_never_sums_mixed_standard_currencies():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        _post(client, "/api/v1/master-data/currencies", headers, {"code": "EUR", "name": "Euro", "symbol": "EUR"})
        afe = _post(client, "/api/v1/afe/afes", headers, {
            "rig_id": setup["rig"]["id"], "well_id": setup["well"]["id"],
            "afe_code": "AFE-EUR", "afe_name": "Euro AFE", "afe_type": "Drilling", "remarks": "",
        }, status=200)
        estimate = client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=headers, json={
            "services": [], "tangibles": [], "standard_currency": "EUR", "exchange_rates": [],
            "consumables": [{"category": "Mud Chemicals", "hole_section_id": setup["hole"]["id"],
                             "phase_id": setup["phase"]["id"], "estimated_amount": "500", "currency": "EUR"}],
        })
        assert estimate.status_code == 200, estimate.text
        _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": setup["well"]["id"], "afe_id": afe["id"], "cost_date": "2026-10-11",
        })
        path = f"/api/v1/daily-cost/wells/{setup['well']['id']}"
        response = client.get(path + "/cost-summary", headers=headers)
        assert response.status_code == 409
        assert "different standard currencies" in response.json()["detail"]
        response = client.get(path + "/cost-report?to=2026-10-13", headers=headers)
        assert response.status_code == 200, response.text
        assert [day["entry"]["standard_currency"] for day in response.json()] == ["USD", "EUR"]
        assert [Decimal(day["comparison"]["planned_total"]) for day in response.json()] == [Decimal("6000.00"), Decimal("500.00")]


# ---------------------------------------------------------------------------
# Other expenses: unexpected charges (LIH, hole problems, claims) that are
# accounted in their own group and deducted from the locked AFE total.
# ---------------------------------------------------------------------------


def _other_line(setup, *, expense_type="LIH", quantity="2", unit_rate="1500",
                remarks="Drill collar lost in hole on tripping", **overrides):
    line = {
        "activity_id": setup["activity_npt"]["id"], "hole_section_id": setup["hole"]["id"],
        "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub_npt"]["id"],
        "vendor_id": setup["vendor"]["id"], "party_name": "", "quantity": quantity,
        "quantity_unit": "unit", "currency": "USD", "expense_type": expense_type,
        "expense_description": "6 5/8 in BHA, three joints left in hole", "unit_rate": unit_rate,
        "override_rate": None, "override_reason": "", "remarks": remarks,
    }
    line.update(overrides)
    return line


def _service_line(setup, rate):
    return {
        "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
        "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"],
        "vendor_id": setup["vendor"]["id"], "quantity": "1", "quantity_unit": "days",
        "currency": "USD", "remarks": "Drilling day", "service_id": setup["service"]["id"],
        "baseline_service_rate_id": rate["id"], "charging_basis": "Day Rate", "charge_category": "Operation",
    }


def test_other_expenses_are_accounted_separately_and_deducted_from_the_afe():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]
        rate = setup["baseline"]["service_rates"][0]
        payload = {
            "remarks": "Tripping incident",
            "services": [_service_line(setup, rate)],
            "consumables": [], "tangibles": [],
            # 2 units at $1,500 = $3,000 on top of the $100 service day.
            "other_expenses": [_other_line(setup)],
        }

        preview = client.put(f"/api/v1/daily-cost/entries/{entry_id}/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        assert Decimal(preview.json()["services_total"]) == Decimal("100.00")
        assert Decimal(preview.json()["other_expenses_total"]) == Decimal("3000.00")
        assert Decimal(preview.json()["total_cost"]) == Decimal("3100.00")
        assert any(row["code"] == "other-expenses-preview" for row in preview.json()["warnings"])

        saved = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        entry = result["entry"]
        # The group is stored on its own, yet it belongs to the day's actual cost.
        assert Decimal(entry["other_expenses_total"]) == Decimal("3000.00")
        assert entry["other_expenses_count"] == 1
        assert Decimal(entry["total_cost"]) == Decimal("3100.00")
        assert Decimal(entry["npt_total"]) == Decimal("3000.00")  # NPT follows the Master Data Activity
        assert entry["warning_count"] == 2  # the NPT charges and the deduction

        line = result["other_expenses"][0]
        assert line["expense_type"] == "LIH"
        assert line["expense_type_label"] == "Lost In Hole (LIH)"
        assert line["expense_description"] == "6 5/8 in BHA, three joints left in hole"
        assert Decimal(line["quantity"]) == Decimal("2.0000") and line["quantity_unit"] == "unit"
        assert Decimal(line["captured_rate"]) == Decimal("1500.0000")
        assert line["override_rate"] is None and line["rate_source"] == "other_expense"
        assert Decimal(line["amount"]) == Decimal("3000.00")
        assert Decimal(line["standard_amount"]) == Decimal("3000.00")
        assert Decimal(line["exchange_rate"]) == Decimal("1.000000")
        assert line["budget_key"] == "other:LIH"
        assert line["budget_name"] == "Other expenses — Lost In Hole (LIH)"
        assert line["baseline_budget_line_id"] is None
        assert line["classification"] == "NPT" and line["sub_activity_code"] == "SA-N1"
        assert line["section_code"] == "17-1/2" and line["phase_code"] == "DRILL"
        assert line["vendor_code"] == "VEND-01" and line["remarks"].startswith("Drill collar lost")

        comparison = result["comparison"]
        # The locked AFE is 6,000.00 and the 3,000.00 deduction is explicit, not hidden.
        assert Decimal(comparison["planned_total"]) == Decimal("6000.00")
        assert Decimal(comparison["tracked_actual_to_date"]) == Decimal("100.00")
        assert Decimal(comparison["other_expenses_to_date"]) == Decimal("3000.00")
        assert Decimal(comparison["actual_to_date"]) == Decimal("3100.00")
        assert Decimal(comparison["balance"]) == Decimal("2900.00")
        groups = {group["cost_group"]: group for group in comparison["groups"]}
        assert set(groups) == {"Services", "Consumables", "Tangibles", "Other Expenses"}
        # Classification split per group: the service is planned, the LIH charge NPT.
        assert Decimal(groups["Services"]["actual_planned"]) == Decimal("100.00")
        assert Decimal(groups["Services"]["actual_upa"]) == Decimal("0.00")
        assert Decimal(groups["Services"]["actual_npt"]) == Decimal("0.00")
        assert Decimal(groups["Other Expenses"]["actual_planned"]) == Decimal("0.00")
        assert Decimal(groups["Other Expenses"]["actual_npt"]) == Decimal("3000.00")
        assert Decimal(groups["Other Expenses"]["planned"]) == Decimal("0.00")
        assert Decimal(groups["Other Expenses"]["actual_to_date"]) == Decimal("3000.00")
        assert Decimal(groups["Other Expenses"]["balance"]) == Decimal("-3000.00")
        assert Decimal(groups["Services"]["balance"]) == Decimal("900.00")
        deduction = next(row for row in comparison["budget_lines"] if row["cost_group"] == "Other Expenses")
        assert deduction["budget_kind"] == "other"
        assert deduction["budget_key"] == "other:LIH"
        assert deduction["item_code"] == "LIH"
        assert deduction["item_name"] == "Lost In Hole (LIH)"
        assert Decimal(deduction["planned"]) == Decimal("0.00")
        assert Decimal(deduction["actual_to_date"]) == Decimal("3000.00")
        assert Decimal(deduction["actual_planned"]) == Decimal("0.00")
        assert Decimal(deduction["actual_upa"]) == Decimal("0.00")
        assert Decimal(deduction["actual_npt"]) == Decimal("3000.00")
        assert deduction["is_planned"] is False
        assert any(row["code"] == "other-expenses-deducted" for row in result["warnings"])

        # Editing the charge moves the deduction with it; removing it restores the balance.
        payload["other_expenses"] = [_other_line(setup, quantity="1", unit_rate="1000", remarks="Reduced to one joint")]
        edited = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload).json()
        assert Decimal(edited["entry"]["other_expenses_total"]) == Decimal("1000.00")
        assert Decimal(edited["comparison"]["balance"]) == Decimal("4900.00")
        payload["other_expenses"] = []
        cleared = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload).json()
        assert Decimal(cleared["entry"]["other_expenses_total"]) == Decimal("0.00")
        assert Decimal(cleared["entry"]["total_cost"]) == Decimal("100.00")
        assert Decimal(cleared["comparison"]["balance"]) == Decimal("5900.00")
        assert cleared["other_expenses"] == []
        assert cleared["entry"]["warning_count"] == 0


def test_other_expense_entry_rules_remarks_scope_and_rate():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]

        def save(line):
            return client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json={
                "remarks": "", "services": [], "consumables": [], "tangibles": [], "other_expenses": [line],
            })

        # Remarks are mandatory: they are the only narrative that explains the charge.
        missing = save(_other_line(setup, remarks=""))
        assert missing.status_code == 422, missing.text
        assert "remarks" in missing.text.lower()
        assert save(_other_line(setup, remarks="x")).status_code == 422
        assert save(_other_line(setup, remarks="   ")).status_code == 422

        # The well sub activity and its Activity are required, as on every line.
        assert save(_other_line(setup, sub_activity_id=None)).status_code == 422
        assert save(_other_line(setup, sub_activity_id=setup["sub1"]["id"])).status_code == 422  # wrong activity
        # The hole section must belong to the locked well plan.
        assert save(_other_line(setup, hole_section_id="00000000-0000-0000-0000-000000000000")).status_code == 422

        # The charge is priced from its own unit rate: no zero, no unknown type, no override.
        assert save(_other_line(setup, unit_rate="0")).status_code == 422
        assert save(_other_line(setup, expense_type="TOTALLY_MADE_UP")).status_code == 422
        assert save(_other_line(setup, override_rate="10", override_reason="Not applicable here")).status_code == 422

        # Only currencies the locked AFE can convert are accepted; blank means the standard currency.
        refused = save(_other_line(setup, currency="EUR"))
        assert refused.status_code == 422, refused.text
        assert "currency" in refused.text.lower()
        defaulted = save(_other_line(setup, currency=""))
        assert defaulted.status_code == 200, defaulted.text
        assert defaulted.json()["other_expenses"][0]["currency"] == "USD"

        # An UPA/NPT charge must say who is responsible, like every other line.
        assert save(_other_line(setup, vendor_id=None, party_name="")).status_code == 422
        assert save(_other_line(setup, vendor_id=None, party_name="Operator")).status_code == 200

        # Every expense type on the picklist can be booked.
        for code in ("LIH", "HOLE_PROBLEM", "FISHING", "SIDE_TRACK", "EQUIPMENT_DAMAGE",
                     "THIRD_PARTY_CLAIM", "PENALTY", "MISC"):
            response = save(_other_line(setup, expense_type=code, remarks=f"{code} charge"))
            assert response.status_code == 200, response.text
            assert response.json()["other_expenses"][0]["expense_type"] == code


def test_other_expenses_flow_into_well_analysis_register_and_print():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]
        rate = setup["baseline"]["service_rates"][0]
        payload = {
            "remarks": "Incident day", "services": [_service_line(setup, rate)],
            "consumables": [], "tangibles": [],
            "other_expenses": [
                _other_line(setup),
                _other_line(setup, expense_type="FISHING", quantity="1", unit_rate="500",
                           remarks="Fishing assembly recovered the string"),
            ],
        }
        assert client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload).status_code == 200

        well = setup["well"]["id"]
        summary = client.get(f"/api/v1/daily-cost/wells/{well}/cost-summary", headers=headers)
        assert summary.status_code == 200, summary.text
        data = summary.json()
        # 100 service + 3,000 LIH + 500 fishing against a 6,000 AFE.
        assert Decimal(data["totals"]["actual"]) == Decimal("3600.00")
        assert Decimal(data["totals"]["other_expenses"]) == Decimal("3500.00")
        assert Decimal(data["totals"]["balance"]) == Decimal("2400.00")
        day = data["daily"][0]
        assert Decimal(day["services"]) == Decimal("100.00")
        assert Decimal(day["other_expenses"]) == Decimal("3500.00")
        assert Decimal(day["total"]) == Decimal("3600.00")
        assert Decimal(data["afes"][0]["other_expenses"]) == Decimal("3500.00")
        assert Decimal(data["afes"][0]["balance"]) == Decimal("2400.00")
        cost_groups = {row["name"]: row for row in
                       next(group for group in data["factors"] if group["dimension"] == "cost_group")["rows"]}
        assert Decimal(cost_groups["Other Expenses"]["amount"]) == Decimal("3500.00")
        assert Decimal(cost_groups["Other Expenses"]["planned"]) == Decimal("0.00")
        assert Decimal(cost_groups["Services"]["amount"]) == Decimal("100.00")
        items = next(group for group in data["factors"] if group["dimension"] == "item")["rows"]
        assert {"Lost In Hole (LIH)", "Fishing & Recovery"} <= {row["name"] for row in items}
        assert any(row["code"] == "other-expenses-deducted" for row in data["warnings"])

        listed = client.get("/api/v1/daily-cost/entries", headers=headers).json()[0]
        assert Decimal(listed["other_expenses_total"]) == Decimal("3500.00")
        assert listed["other_expenses_count"] == 2

        report = client.get(f"/api/v1/daily-cost/wells/{well}/cost-report", headers=headers).json()
        printed = report[0]["other_expenses"]
        assert [row["expense_type"] for row in printed] == ["LIH", "FISHING"]
        assert all(row["remarks"] for row in printed)
        assert Decimal(report[0]["entry"]["other_expenses_total"]) == Decimal("3500.00")

        overview = client.get("/api/v1/daily-cost/overview", headers=headers).json()
        usd_groups = {row["cost_group"]: row for row in overview["groups"] if row["currency"] == "USD"}
        assert Decimal(usd_groups["Other Expenses"]["planned"]) == Decimal("0.00")
        assert Decimal(usd_groups["Other Expenses"]["actual"]) == Decimal("3500.00")
        assert Decimal(usd_groups["Other Expenses"]["balance"]) == Decimal("-3500.00")

        reference = client.get("/api/v1/daily-cost/reference", headers=headers).json()
        assert {"code": "LIH", "label": "Lost In Hole (LIH)"} in reference["other_expense_types"]
        assert len(reference["other_expense_types"]) == 8


def test_other_expense_rows_import_with_aliases_and_are_audited():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]

        imported = client.post(f"/api/v1/daily-cost/entries/{entry_id}/import", headers=headers, json={"rows": [
            {"line_type": "Other", "activity_code": "NPT", "sub_activity_code": "SA-N1", "vendor_code": "VEND-01",
             "expense_type": "lost in hole", "expense_description": "BHA left in hole", "unit_rate": "250000",
             "quantity": "1", "quantity_unit": "unit", "currency": "USD",
             "remarks": "Tools lost in hole while tripping"},
            # A file written in the operator's own words still resolves, and the
            # standard currency is implied when the column is blank.
            {"line_type": "Other Expense", "activity_code": "NPT", "sub_activity_code": "SA-N1",
             "vendor_code": "VEND-01", "expense_type": "Hole Problem", "rate": "40", "quantity": "3",
             "remarks": "Wiper trip and ream to clear the hole"},
        ]})
        assert imported.status_code == 200, imported.text
        assert imported.json()["success"] is True, imported.json()
        assert imported.json()["imported_count"] == 2
        saved = client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers).json()
        assert Decimal(saved["entry"]["other_expenses_total"]) == Decimal("250120.00")
        assert {row["expense_type"] for row in saved["other_expenses"]} == {"LIH", "HOLE_PROBLEM"}
        assert saved["other_expenses"][1]["currency"] == "USD"
        assert saved["other_expenses"][1]["expense_type_label"] == "Hole Problem"
        # Nothing was budgeted for it, so the AFE position goes negative.
        assert Decimal(saved["comparison"]["balance"]) == Decimal("-244120.00")
        assert saved["entry"]["total_cost"] == saved["entry"]["other_expenses_total"]

        # Missing remarks, an unknown type or a missing rate are row errors, never a 500.
        rejected = client.post(f"/api/v1/daily-cost/entries/{entry_id}/import", headers=headers, json={"rows": [
            {"line_type": "Other", "activity_code": "NPT", "sub_activity_code": "SA-N1",
             "expense_type": "LIH", "unit_rate": "10"},
            {"line_type": "Other", "activity_code": "NPT", "sub_activity_code": "SA-N1",
             "expense_type": "DROPPED_OBJECT", "unit_rate": "10", "remarks": "Made up expense type"},
            {"line_type": "Other", "activity_code": "NPT", "sub_activity_code": "SA-N1",
             "expense_type": "LIH", "remarks": "No rate at all on this row"},
        ]})
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["success"] is False
        assert rejected.json()["error_count"] == 3
        errors = " ".join(rejected.json()["errors"])
        assert "remarks" in errors.lower() and "Unknown expense type" in errors and "unit_rate" in errors
        # Nothing was written by the failed import.
        assert len(client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers).json()["other_expenses"]) == 2

        with SessionLocal() as db:
            summaries = [row.summary for row in db.query(AuditLog).filter(
                AuditLog.entity_type == "daily_cost", AuditLog.action == "other_expense").all()]
        assert any("Lost In Hole" in text for text in summaries)
        assert any("deducted from AFE AFE-01" in text for text in summaries)


def test_other_expenses_follow_the_sheet_tenant_rbac_and_workflow_rules():
    from sqlalchemy import func, select
    from app.models import DailyCostOtherExpenseLine
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        setup = _setup_daily_sheet(client, north)
        entry_id = setup["entry"]["id"]
        assert client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=north, json={
            "remarks": "", "services": [], "consumables": [], "tangibles": [],
            "other_expenses": [_other_line(setup)],
        }).status_code == 200
        assert client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=south).status_code == 404
        assert client.get("/api/v1/daily-cost/entries", headers=south).json() == []
        other = _setup_daily_sheet(client, south)  # same codes, another workspace
        assert client.get(f"/api/v1/daily-cost/entries/{other['entry']['id']}", headers=north).status_code == 404
        assert Decimal(other["entry"]["other_expenses_total"]) == Decimal("0")

        # A read-only viewer cannot post a deduction against the AFE.
        with SessionLocal() as db:
            north_id = select(Organization.id).where(Organization.slug == "north").scalar_subquery()
            user = db.scalar(select(User).where(User.email == "owner@example.com", User.organization_id == north_id))
            role = user.roles[0]
            role.is_owner = False
            role.permissions = [permission for permission in role.permissions
                                if permission.key in ("daily-cost:read", "daily-cost:export")]
            db.commit()
        blocked = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=north, json={
            "remarks": "", "services": [], "consumables": [], "tangibles": [],
            "other_expenses": [_other_line(setup, unit_rate="99")],
        })
        assert blocked.status_code == 403
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.organization_id == select(Organization.id).where(
                Organization.slug == "north").scalar_subquery()))
            role.is_owner = True
            db.commit()

        # A submitted sheet is frozen including its deductions; reopening unlocks it.
        assert client.post(f"/api/v1/daily-cost/entries/{entry_id}/submit", headers=north,
                           json={"remarks": "Reviewed"}).status_code == 200
        frozen = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=north, json={
            "remarks": "", "services": [], "consumables": [], "tangibles": [], "other_expenses": [],
        })
        assert frozen.status_code == 409
        reopened = client.post(f"/api/v1/daily-cost/entries/{entry_id}/reopen", headers=north,
                               json={"remarks": "Charge was mis-keyed"})
        assert reopened.status_code == 200, reopened.text
        assert len(reopened.json()["other_expenses"]) == 1

        # A soft delete keeps the lines so the sheet can be restored whole...
        assert client.delete(f"/api/v1/daily-cost/entries/{entry_id}", headers=north).status_code == 200
        assert client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=north).status_code == 404
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(DailyCostOtherExpenseLine)) == 1
        assert client.get("/api/v1/daily-cost/entries/deleted", headers=north).json()[0]["id"] == entry_id
        assert client.post(f"/api/v1/daily-cost/entries/{entry_id}/restore", headers=north).status_code == 200
        assert len(client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=north).json()["other_expenses"]) == 1

        # ...while purging from Deleted Entries takes the unexpected charges with it.
        assert client.delete(f"/api/v1/daily-cost/entries/{entry_id}", headers=north).status_code == 200
        assert client.delete(f"/api/v1/daily-cost/entries/{entry_id}/permanent", headers=north).status_code == 204
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(DailyCostOtherExpenseLine)) == 0


def test_other_expense_remarks_are_enforced_by_the_database_too():
    """The API is not the only writer: the schema itself refuses a blank remark."""
    from sqlalchemy import func, insert, select
    from app.models import DailyCostOtherExpenseLine
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup["entry"]["id"]
        assert client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json={
            "remarks": "", "services": [], "consumables": [], "tangibles": [],
            "other_expenses": [_other_line(setup)],
        }).status_code == 200
        with SessionLocal() as db:
            organization_id = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            base = {"organization_id": organization_id, "entry_id": entry_id,
                    "activity_id": setup["activity_npt"]["id"], "expense_type": "LIH",
                    "expense_type_label": "Lost In Hole (LIH)", "quantity": "1", "sort_order": 1,
                    "remarks": "Drill collar lost in hole"}
            for override in ({"remarks": "   "}, {"expense_type": "DROPPED_OBJECT"}, {"quantity": "-1"}):
                with pytest.raises(IntegrityError):
                    db.execute(insert(DailyCostOtherExpenseLine).values(**{**base, **override}))
                db.rollback()
            assert db.scalar(select(func.count()).select_from(DailyCostOtherExpenseLine)) == 1


def test_itemized_service_costs_roundtrip_preview_and_submit():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        base = f"/api/v1/daily-cost/entries/{setup['entry']['id']}"
        payload = {"services": [{
            "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
            "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"],
            "quantity": "12", "quantity_unit": "hours", "currency": "USD",
            "service_id": setup["service"]["id"],
            "baseline_service_rate_id": setup["baseline"]["service_rates"][0]["id"],
            "charging_basis": "Day Rate", "charge_category": "Operation",
            "cost_items": [{"description": "Crew", "amount": "123.45"}, {"description": "Transport", "amount": "20.10"}],
        }]}
        preview = client.put(base + "/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        assert Decimal(preview.json()["services"][0]["amount"]) == Decimal("143.55")
        saved = client.put(base, headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        fetched = client.get(base, headers=headers).json()["services"][0]
        assert [item["description"] for item in fetched["cost_items"]] == ["Crew", "Transport"]
        assert Decimal(fetched["usd_amount"]) == Decimal("143.55")
        submitted = client.post(base + "/submit", headers=headers, json={"remarks": "Reviewed"})
        assert submitted.status_code == 200, submitted.text
        assert Decimal(submitted.json()["services"][0]["amount"]) == Decimal("143.55")
        assert len(submitted.json()["services"][0]["cost_items"]) == 2


def test_deleted_entries_purge_cascades_locked_baselines_afe_well_and_rig():
    """Purging a daily sheet must not leave an immutable baseline that blocks its AFE.

    Baselines belong to the AFE/well they snapshot: they are retained while the
    owner is retained and purged with it, so the Deleted Entries flow always
    terminates (AFE -> well -> rig) after the sheets are purged.
    """
    from sqlalchemy import func, select
    from app.models import (
        DailyCostBaseline, DailyCostCatalogueRateSnapshot, DailyCostWellRateBaseline,
        MudCostSectionSetting,
    )

    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        afe, well, rig = setup["afe"], setup["well"], setup["rig"]
        entry_id = setup["entry"]["id"]

        # Baselines exist as soon as the first sheet locks the AFE/well rates.
        with SessionLocal() as db:
            before = {
                "afe": db.scalar(select(func.count()).select_from(DailyCostBaseline)),
                "rate": db.scalar(select(func.count()).select_from(DailyCostWellRateBaseline)),
                "snapshots": db.scalar(select(func.count()).select_from(DailyCostCatalogueRateSnapshot)),
            }
        assert before["afe"] == 1 and before["rate"] == 1 and before["snapshots"] > 0

        # An active sheet keeps its AFE in the register.
        blocked = client.delete(f"/api/v1/afe/afes/{afe['id']}", headers=headers)
        assert blocked.status_code == 409
        assert "active daily-cost sheet" in blocked.json()["detail"].lower()

        # Soft-deleting the sheet is not enough: it could still be restored, so the
        # AFE purge asks for the sheet to be permanently deleted first.
        assert client.delete(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/afe/afes/{afe['id']}", headers=headers).status_code == 200
        kept = client.delete(f"/api/v1/afe/afes/{afe['id']}/permanent", headers=headers)
        assert kept.status_code == 409
        assert "Deleted entries" in kept.json()["detail"]

        # Purging the sheet clears the sheet, then the AFE can go with its baseline.
        assert client.delete(f"/api/v1/daily-cost/entries/{entry_id}/permanent", headers=headers).status_code == 204
        assert client.delete(f"/api/v1/afe/afes/{afe['id']}/permanent", headers=headers).status_code == 204
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(DailyCostBaseline)) == 0
            assert db.scalar(select(func.count()).select_from(DailyCostWellRateBaseline)) == 1

        # Per-well mud configuration is owned by the well and has no delete path of
        # its own; without this it would block the well purge forever.
        with SessionLocal() as db:
            db.add(MudCostSectionSetting(
                organization_id=db.scalar(select(Organization.id).where(Organization.slug == "north")),
                rig_id=rig["id"], well_id=well["id"], section_id="section-1",
                hole_section_id=setup["hole"]["id"], section_scope="drilling",
                section_code_snapshot=setup["hole"]["code"], section_name_snapshot=setup["hole"]["name"],
                mud_type="WBM", remarks="", base_rate=Decimal("12.5"), currency="USD",
                created_by="Test", updated_by="Test",
            ))
            db.commit()

        # The well still owns its rate book; the well purge removes it (and the well).
        for key in ("sub1", "sub2", "sub3", "sub_upa", "sub_npt"):
            sub = setup[key]
            assert client.delete(
                f"/api/v1/rig-well/sub-activities/{sub['id']}?well_id={well['id']}", headers=headers
            ).status_code == 200
            assert client.delete(f"/api/v1/rig-well/sub-activities/{sub['id']}/permanent", headers=headers).status_code == 204
        assert client.delete(f"/api/v1/rig-well/wells/{well['id']}", headers=headers).status_code == 200
        well_purge = client.delete(f"/api/v1/rig-well/wells/{well['id']}/permanent", headers=headers)
        assert well_purge.status_code == 204, well_purge.text
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(DailyCostWellRateBaseline)) == 0
            assert db.scalar(select(func.count()).select_from(DailyCostCatalogueRateSnapshot)) == 0
            assert db.scalar(select(func.count()).select_from(MudCostSectionSetting)) == 0

        # Finally the rig is free: no dangling wells, AFEs or sheets.
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}/permanent", headers=headers).status_code == 204

        with SessionLocal() as db:
            actions = [row.summary for row in db.scalars(
                select(AuditLog).where(AuditLog.entity_type.in_(("afe", "well", "rig")))
            )]
        assert any("locked AFE baseline" in summary for summary in actions)
        assert any("well rate baseline" in summary for summary in actions)


def test_purge_owns_afe_revisions_and_names_other_modules_instead_of_failing_with_500():
    """AFE-owned snapshots go with the AFE; foreign module records are named in a 409."""
    from datetime import date
    from sqlalchemy import func, select
    from app.models import AfeSowAdjustment, LihCostEntry

    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers, create_entry=False)
        afe, well, rig = setup["afe"], setup["well"], setup["rig"]
        organization_id = select(Organization.id).where(Organization.slug == "north").scalar_subquery()
        with SessionLocal() as db:
            organization_id = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            db.add(AfeSowAdjustment(
                organization_id=organization_id,
                afe_id=afe["id"], well_id=well["id"], rig_id=rig["id"],
                configuration_scope="drilling", revision_number=1, status="draft",
                reason="Scope change", sow_summary="", standard_currency="USD",
                adjusted_services_total=Decimal("0"), adjusted_consumables_total=Decimal("0"),
                adjusted_tangibles_total=Decimal("0"), adjusted_total=Decimal("0"),
            ))
            db.add(LihCostEntry(
                organization_id=organization_id, rig_id=rig["id"], rig_code_snapshot=rig["rig_code"],
                rig_name_snapshot=rig["rig_name"], well_id=well["id"], well_code_snapshot=well["well_code"],
                well_name_snapshot=well["well_name"], afe_id=afe["id"], cost_date=date(2026, 10, 11),
                currency="USD", remarks="", line_count=0, total_cost=Decimal("0"),
            ))
            db.commit()

        assert client.delete(f"/api/v1/afe/afes/{afe['id']}", headers=headers).status_code == 200
        blocked = client.delete(f"/api/v1/afe/afes/{afe['id']}/permanent", headers=headers)
        assert blocked.status_code == 409
        assert "LIH cost entry/entries" in blocked.json()["detail"]
        assert "still referenced by" in blocked.json()["detail"]

        # The LIH entry lives in its own module: purging it clears the way, and the
        # AFE's own SOW revisions are removed together with the AFE.
        with SessionLocal() as db:
            for row in db.scalars(select(LihCostEntry)).all():
                db.delete(row)
            db.commit()
        assert client.delete(f"/api/v1/afe/afes/{afe['id']}/permanent", headers=headers).status_code == 204
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(AfeSowAdjustment)) == 0
            summary = db.scalar(
                select(AuditLog.summary).where(
                    AuditLog.entity_type == "afe", AuditLog.action == "permanent_delete"
                ).order_by(AuditLog.created_at.desc())
            )
        assert "SOW revision(s)" in summary


def test_bulk_deleted_entries_purge_clears_owned_baselines_too():
    """The bulk Deleted Entries purge follows the same ownership rule."""
    from sqlalchemy import func, select
    from app.models import DailyCostBaseline, DailyCostWellRateBaseline

    def records(*pairs):
        return [{"entity_type": entity_type, "id": record_id} for entity_type, record_id in pairs]

    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        afe, well, rig = setup["afe"], setup["well"], setup["rig"]
        entry_id = setup["entry"]["id"]

        assert client.post("/api/v1/daily-cost/entries/bulk-delete", headers=headers, json={"ids": [entry_id]}).status_code == 200
        purged = client.post("/api/v1/daily-cost/entries/bulk-permanent-delete", headers=headers, json={"ids": [entry_id]})
        assert purged.status_code == 200, purged.text
        assert client.post("/api/v1/afe/afes/bulk-delete", headers=headers, json={"ids": [afe["id"]]}).status_code == 200
        purged = client.post("/api/v1/afe/afes/bulk-permanent-delete", headers=headers, json={"ids": [afe["id"]]})
        assert purged.status_code == 200, purged.text
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(DailyCostBaseline)) == 0

        sub_pairs = []
        for key in ("sub1", "sub2", "sub3", "sub_upa", "sub_npt"):
            sub = setup[key]
            assert client.delete(
                f"/api/v1/rig-well/sub-activities/{sub['id']}?well_id={well['id']}", headers=headers
            ).status_code == 200
            sub_pairs.append(("well_sub_activity", sub["id"]))
        assert client.delete(f"/api/v1/rig-well/wells/{well['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}", headers=headers).status_code == 200

        # Purge every child in one request, exactly as the Deleted Entries page does.
        purge = client.post("/api/v1/rig-well/deleted/bulk-permanent-delete", headers=headers, json={
            "records": records(*sub_pairs, ("well", well["id"]), ("rig", rig["id"])),
        })
        assert purge.status_code == 200, purge.text
        assert purge.json()["affected_count"] == 7
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(DailyCostWellRateBaseline)) == 0
            assert db.scalar(select(func.count()).select_from(DailyCostBaseline)) == 0
        assert client.get("/api/v1/rig-well/deleted", headers=headers).json() == []


def test_report_settings_and_day_split_live_in_the_register():
    """Lead / lag is saved with the sheet; the report day is split from the total.

    The printed daily report shows the AFE, the cost up to the previous day, the
    cost on the report day and the cumulative cost. Those two halves and the
    register's cumulative column must come from saved data — no print-time entry.
    """
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        rate = setup["baseline"]["service_rates"][0]

        def service_line(days: str) -> dict:
            return {
                "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
                "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"],
                "vendor_id": setup["vendor"]["id"], "quantity": days, "quantity_unit": "days",
                "currency": "USD", "override_rate": None, "override_reason": "",
                "remarks": "", "service_id": setup["service"]["id"],
                "baseline_service_rate_id": rate["id"], "charging_basis": "Day Rate",
                "charge_category": "Operation",
            }

        first = client.put(
            f"/api/v1/daily-cost/entries/{setup['entry']['id']}", headers=headers,
            json={
                "remarks": "First day", "lead_lag_kind": "LEAD", "lead_lag_days": "2.75",
                "services": [service_line("2")], "consumables": [], "tangibles": [],
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["entry"]["lead_lag_kind"] == "LEAD"
        assert Decimal(first.json()["entry"]["lead_lag_days"]) == Decimal("2.75")
        assert Decimal(first.json()["entry"]["total_cost"]) == Decimal("200.00")

        second_day = _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": setup["well"]["id"], "afe_id": setup["afe"]["id"],
            "cost_date": "2026-10-11", "remarks": "Second day",
        })
        second = client.put(
            f"/api/v1/daily-cost/entries/{second_day['entry']['id']}", headers=headers,
            json={
                "remarks": "Second day", "lead_lag_kind": "LAG", "lead_lag_days": "0.5",
                "services": [service_line("1")], "consumables": [], "tangibles": [],
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["entry"]["lead_lag_kind"] == "LAG"
        assert Decimal(second.json()["entry"]["lead_lag_days"]) == Decimal("0.5")

        # The comparison splits the report day from everything before it.
        comparison = second.json()["comparison"]
        service_row = next(row for row in comparison["budget_lines"] if row["cost_group"] == "Services")
        assert Decimal(service_row["actual_prior"]) == Decimal("200.00")
        assert Decimal(service_row["actual_today"]) == Decimal("100.00")
        assert Decimal(service_row["actual_to_date"]) == Decimal("300.00")
        assert (
            Decimal(service_row["actual_prior"]) + Decimal(service_row["actual_today"])
            == Decimal(service_row["actual_to_date"])
        )
        services_group = next(row for row in comparison["groups"] if row["cost_group"] == "Services")
        assert Decimal(services_group["actual_prior"]) == Decimal("200.00")
        assert Decimal(services_group["actual_today"]) == Decimal("100.00")

        # The register shows the day's own cost beside the running cumulative cost.
        rows = client.get("/api/v1/daily-cost/entries", headers=headers).json()
        by_date = {row["cost_date"]: row for row in rows}
        assert Decimal(by_date["2026-10-10"]["total_cost"]) == Decimal("200.00")
        assert Decimal(by_date["2026-10-10"]["cumulative_cost"]) == Decimal("200.00")
        assert Decimal(by_date["2026-10-11"]["total_cost"]) == Decimal("100.00")
        assert Decimal(by_date["2026-10-11"]["cumulative_cost"]) == Decimal("300.00")

        # A lead / lag kind without days (or days without a kind) is rejected.
        assert client.put(
            f"/api/v1/daily-cost/entries/{second_day['entry']['id']}", headers=headers,
            json={"remarks": "", "lead_lag_kind": "LEAD", "services": [], "consumables": [], "tangibles": []},
        ).status_code == 422
        assert client.put(
            f"/api/v1/daily-cost/entries/{second_day['entry']['id']}", headers=headers,
            json={"remarks": "", "lead_lag_kind": "", "lead_lag_days": "3", "services": [], "consumables": [], "tangibles": []},
        ).status_code == 422

        # The well summary exposes the same split for the printed well report.
        summary = client.get(
            f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-summary", headers=headers,
            params={"to": "2026-10-11"},
        )
        assert summary.status_code == 200, summary.text
        summary_row = next(row for row in summary.json()["budget_lines"] if row["cost_group"] == "Services")
        assert Decimal(summary_row["actual_prior"]) == Decimal("200.00")
        assert Decimal(summary_row["actual_today"]) == Decimal("100.00")


def test_report_lines_follow_the_afe_estimate_order():
    """The printed schedule lists AFE allowances in the estimate's own sequence."""
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        day = client.get(f"/api/v1/daily-cost/entries/{setup['entry']['id']}", headers=headers).json()
        service_lines = [
            row for row in day["comparison"]["budget_lines"] if row["cost_group"] == "Services"
        ]
        assert service_lines, "the AFE service allowance is listed before any cost is recorded"
        # Every allowance carries its estimate position so the print can keep the
        # AFE's own sequence and still show 0 where nothing was spent.
        assert all(row["sort_order"] >= 0 for row in service_lines)
        ordered = sorted(service_lines, key=lambda row: row["sort_order"])
        assert [row["budget_key"] for row in ordered] == [row["budget_key"] for row in service_lines]
        assert all(Decimal(row["planned"]) > 0 for row in service_lines)
        assert all(Decimal(row["actual_to_date"]) == Decimal("0") for row in service_lines)


def test_current_afe_rates_are_versioned_without_repricing_history():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        entry_id = setup['entry']['id']
        original = setup['baseline']['service_rates'][0]
        # AFE saves replace line identities; change to section rate first.
        afe_id = setup['afe']['id']
        source_id = original['source_afe_line_id']
        def estimate(basis):
            section = basis == 'Per Section Rate'
            response = client.put(f'/api/v1/afe/afes/{afe_id}/estimate', headers=headers, json={
                'services': [{'client_key': source_id, 'service_id': setup['service']['id'], 'charging_basis': basis,
                    'currency': 'USD', 'service_amount': '0', 'hole_section_id': None, 'phase_id': None,
                    'rates': [] if section else [{'category': 'Operation', 'unit_rate': '240'}, {'category': 'Mobilization', 'unit_rate': '500'}],
                    'charges': [] if section else [{'category': 'Operation', 'quantity': '10', 'quantity_unit': 'days'}],
                    'section_rates': [{'hole_section_id': setup['hole']['id'], 'phase_id': setup['phase']['id'], 'amount': '600'}] if section else []}],
                'consumables': [], 'tangibles': [], 'standard_currency': 'USD', 'exchange_rates': []})
            assert response.status_code == 200, response.text
        estimate('Per Section Rate')
        refreshed = client.post(f'/api/v1/daily-cost/entries/{entry_id}/refresh-service-rates', headers=headers)
        assert refreshed.status_code == 200, refreshed.text
        section_rate = next(row for row in refreshed.json()['service_rates'] if row['is_current'])
        assert section_rate['charging_basis'] == 'Per Section Rate'
        line = {'service_id': setup['service']['id'], 'baseline_service_rate_id': section_rate['id'],
            'charging_basis': 'Per Section Rate', 'charge_category': 'Operation',
            'activity_id': setup['activity']['id'], 'sub_activity_id': setup['sub1']['id'],
            'hole_section_id': setup['hole']['id'], 'phase_id': setup['phase']['id'],
            'quantity': '1', 'quantity_unit': 'section', 'currency': 'USD'}
        saved = client.put(f'/api/v1/daily-cost/entries/{entry_id}', headers=headers, json={'services': [line]})
        assert saved.status_code == 200, saved.text
        assert Decimal(saved.json()['entry']['services_total']) == 600
        old_id = saved.json()['services'][0]['id']
        estimate('Day Rate')
        url = f'/api/v1/daily-cost/entries/{entry_id}/refresh-service-rates'
        current = client.post(url, headers=headers)
        assert current.status_code == 200, current.text
        rates = current.json()['service_rates']
        assert len([rate for rate in rates if rate['is_current']]) == 2
        assert next(rate for rate in rates if rate['id'] == section_rate['id'])['is_current'] is False
        # Refresh is idempotent, and cannot affect historical actuals or budget.
        again = client.post(url, headers=headers).json()
        assert {row['id'] for row in again['service_rates']} == {row['id'] for row in rates}
        assert again['total_amount'] == setup['baseline']['total_amount']
        day = client.get(f'/api/v1/daily-cost/entries/{entry_id}', headers=headers).json()
        assert Decimal(day['entry']['services_total']) == 600
        assert day['services'][0]['charging_basis'] == 'Per Section Rate'
        operation = next(rate for rate in rates if rate['is_current'] and rate['charge_category'] == 'Operation')
        mob = next(rate for rate in rates if rate['is_current'] and rate['charge_category'] == 'Mobilization')
        allocations = []
        for index, (activity, sub, hours) in enumerate((('activity', 'sub1', '10'), ('activity_npt', 'sub_npt', '11'), ('activity_upa', 'sub_upa', '3'))):
            allocations.append({**line, 'id': old_id if index == 0 else None,
                'activity_id': setup[activity]['id'], 'sub_activity_id': setup[sub]['id'],
                'baseline_service_rate_id': operation['id'], 'charging_basis': 'Day Rate', 'quantity': hours,
                'quantity_unit': 'hours', 'party_name': 'Operations team'})
        allocations.append({**allocations[0], 'id': None, 'baseline_service_rate_id': mob['id'],
                            'charge_category': 'Mobilization', 'quantity': '1', 'quantity_unit': 'unit'})
        result = client.put(f'/api/v1/daily-cost/entries/{entry_id}', headers=headers, json={'services': allocations})
        assert result.status_code == 200, result.text
        assert Decimal(result.json()['entry']['services_total']) == 740
        assert [Decimal(row['amount']) for row in result.json()['services']] == [100, 110, 30, 500]
        assert all(row['baseline_budget_line_id'] for row in result.json()['services'])
        assert len({row['budget_key'] for row in result.json()['services']}) == 1
        assert Decimal(result.json()['entry']['npt_total']) == 110
        assert Decimal(result.json()['entry']['upa_total']) == 30
        allocations[2]['quantity'] = '4'
        rejected = client.put(f'/api/v1/daily-cost/entries/{entry_id}/preview', headers=headers, json={'services': allocations})
        assert rejected.status_code == 422, rejected.text
        assert '24' in rejected.text
        foreign = client.post(url, headers=login(client, 'south'))
        assert foreign.status_code == 404
