import os
import tempfile
from decimal import Decimal

_db_path = tempfile.mktemp(suffix=".sqlite3")
# Set TEST_DATABASE_URL (a PostgreSQL URL, as CI does) to run this suite against
# a real server instead of the throwaway SQLite file.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import Organization, Permission, Role, User


PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export", "submit", "reopen",
    )),
    *(f"afe:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        "estimate", "submit", "review", "approve", "reopen", "sow-adjust", "sow-approve",
    )),
    *(f"rig-well:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export", "plan-adjust",
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
        "code": "EA", "name": "Each", "symbol": "ea",
    }).status_code == 201
    hole = _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "17-1/2", "name": "Surface hole"})
    phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
    activity = _post(client, "/api/v1/master-data/activities", headers, {"code": "DRL", "name": "Drilling"})
    vendor = _post(client, "/api/v1/master-data/vendors", headers, {
        "vendor_code": "VEND-01", "vendor_name": "Acme Services", "category": "Drilling", "status": "active",
    })
    service = _post(client, "/api/v1/master-data/services", headers, {
        "service_code": "MUD-LOG", "service_name": "Mud logging", "service_category": "Drilling Services",
        "provider_type": "Third Party Services", "vendor_id": vendor["id"], "description": "Wellsite logging crew",
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
    _post(client, "/api/v1/rig-well/sub-activities", headers, {
        "well_id": well["id"], "sub_activity_code": "SA-D1", "sub_activity_name": "Sub activity SA-D1",
        "activity_id": activity["id"], "responsible_party": "Operations team",
        "description": "Execute the planned work step.",
    })
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
        "consumables": [], "tangibles": [], "standard_currency": "", "exchange_rates": [],
    })
    assert estimate.status_code == 200, estimate.text
    return {"hole": hole, "phase": phase, "activity": activity, "service": service, "rig": rig, "well": well, "afe": afe}


def _approve_afe(client, headers, afe_id):
    for action, remarks in (("submit", ""), ("review", ""), ("approve", "Budget authorised")):
        response = client.post(f"/api/v1/afe/afes/{afe_id}/status", headers=headers, json={"action": action, "remarks": remarks})
        assert response.status_code == 200, response.text
    return response.json()


def _service_line(service_id, *, pair_key="sv0", unit_rate="200", quantity="10"):
    """One Day Rate service line — the same entry shape as the AFE estimate."""
    return {
        "pair_key": pair_key,
        "client_key": pair_key,
        "service_id": service_id,
        "charging_basis": "Day Rate",
        "hole_section_id": None,
        "phase_id": None,
        "currency": "USD",
        "service_amount": "0",
        "remarks": "",
        "rates": [{"category": "Operation", "unit_rate": unit_rate}],
        "charges": [{"category": "Operation", "quantity": quantity, "quantity_unit": "days"}],
        "section_rates": [],
    }


def _adjustment_payload(setup, **overrides):
    # The revised entry reworks the entered estimate line: 200/day x 10 days
    # against the entered 100/day x 10 days. Totals derive from these lines.
    payload = {
        "reason": "Extra logging unit added to the scope",
        "sow_summary": "Added one mud logging unit for the intermediate hole",
        "standard_currency": "",
        "exchange_rates": [],
        "services": [_service_line(setup["service"]["id"])],
        "consumables": [],
        "tangibles": [],
    }
    payload.update(overrides)
    return payload


def test_draft_afe_rejects_sow_adjustment():
    client = TestClient(app)
    headers = login(client)
    setup = _setup(client, headers)
    response = client.post(
        f"/api/v1/afe/afes/{setup['afe']['id']}/sow-adjustments", headers=headers, json=_adjustment_payload(setup),
    )
    assert response.status_code == 409, response.text
    assert "Draft" in response.json()["detail"]


def test_sow_adjustment_lifecycle_and_effective_totals():
    client = TestClient(app)
    headers = login(client)
    setup = _setup(client, headers)
    afe_id = setup["afe"]["id"]
    _approve_afe(client, headers, afe_id)

    created = _post(client, f"/api/v1/afe/afes/{afe_id}/sow-adjustments", headers, _adjustment_payload(setup), status=201)
    assert created["revision_number"] == 1
    assert created["status"] == "draft"
    assert Decimal(created["original_services_total"]) == Decimal("1000.00")
    # The adjusted totals derive from the revised lines: 200/day x 10 days.
    assert Decimal(created["adjusted_services_total"]) == Decimal("2000.00")
    assert Decimal(created["adjusted_total"]) == Decimal("2000.00")
    assert Decimal(created["delta_total"]) == Decimal("1000.00")

    # The revision stores both sides of the entry: the entered line is snapshotted
    # on the before side, the revised line on the after side, linked by pair key.
    before = created["before"]
    after = created["after"]
    assert [line["client_key"] for line in before["services"]] == ["sv0"]
    assert [line["client_key"] for line in after["services"]] == ["sv0"]
    assert Decimal(before["services"][0]["amount"]) == Decimal("1000.00")
    assert Decimal(after["services"][0]["amount"]) == Decimal("2000.00")

    # A second draft is blocked while the first is still open.
    blocked = client.post(f"/api/v1/afe/afes/{afe_id}/sow-adjustments", headers=headers, json=_adjustment_payload(setup))
    assert blocked.status_code == 409, blocked.text

    # Drafts do not affect the register totals.
    register = client.get("/api/v1/afe/afes", headers=headers).json()
    assert register[0]["has_sow_adjustment"] is False
    assert register[0]["adjusted_total"] is None

    updated = client.patch(f"/api/v1/afe/sow-adjustments/{created['id']}", headers=headers, json={
        "services": [_service_line(setup["service"]["id"], unit_rate="250")],
        "consumables": [],
        "tangibles": [],
        "reason": "Extra logging unit and standby cover",
    })
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["adjusted_total"]) == Decimal("2500.00")

    # A partial module update is rejected: all three modules travel together.
    partial = client.patch(f"/api/v1/afe/sow-adjustments/{created['id']}", headers=headers, json={
        "services": [_service_line(setup["service"]["id"], unit_rate="300")],
    })
    assert partial.status_code == 422, partial.text

    approved = client.post(
        f"/api/v1/afe/sow-adjustments/{created['id']}/approve", headers=headers, json={"remarks": "Scope change verified"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    register = client.get("/api/v1/afe/afes", headers=headers).json()
    assert register[0]["has_sow_adjustment"] is True
    assert Decimal(register[0]["adjusted_total"]) == Decimal("2500.00")
    assert register[0]["sow_revision"] == 1
    # The saved estimate itself never changes.
    assert Decimal(register[0]["total_cost"]) == Decimal("1000.00")

    # A newer approved revision supersedes the older one.
    second = _post(client, f"/api/v1/afe/afes/{afe_id}/sow-adjustments", headers, _adjustment_payload(setup,
        reason="Standby cover removed again",
        services=[_service_line(setup["service"]["id"], unit_rate="180")],
    ), status=201)
    assert second["revision_number"] == 2
    # The original snapshot is carried forward from the first revision, not re-taken.
    assert Decimal(second["original_services_total"]) == Decimal("1000.00")
    assert Decimal(second["adjusted_total"]) == Decimal("1800.00")
    approve_second = client.post(
        f"/api/v1/afe/sow-adjustments/{second['id']}/approve", headers=headers, json={"remarks": "Revised scope agreed"},
    )
    assert approve_second.status_code == 200, approve_second.text
    register = client.get("/api/v1/afe/afes", headers=headers).json()
    assert Decimal(register[0]["adjusted_total"]) == Decimal("1800.00")
    assert register[0]["sow_revision"] == 2

    # Voiding the latest revision restores the earlier approved revision.
    voided = client.post(
        f"/api/v1/afe/sow-adjustments/{second['id']}/void", headers=headers, json={"remarks": "Entered in error"},
    )
    assert voided.status_code == 200, voided.text
    register = client.get("/api/v1/afe/afes", headers=headers).json()
    assert Decimal(register[0]["adjusted_total"]) == Decimal("2500.00")
    assert register[0]["sow_revision"] == 1

    history = client.get(f"/api/v1/afe/afes/{afe_id}/sow-adjustments", headers=headers).json()
    assert [row["revision_number"] for row in history] == [2, 1]
    assert [row["status"] for row in history] == ["void", "approved"]


def test_sow_adjustment_add_and_remove_estimate_lines():
    client = TestClient(app)
    headers = login(client)
    setup = _setup(client, headers)
    afe_id = setup["afe"]["id"]
    _approve_afe(client, headers, afe_id)

    # The revised entry keeps the entered line, adds a second one and lets the
    # user work every value against what was entered — same as the estimate.
    created = _post(client, f"/api/v1/afe/afes/{afe_id}/sow-adjustments", headers, _adjustment_payload(setup,
        services=[
            _service_line(setup["service"]["id"], pair_key="sv0", unit_rate="150", quantity="10"),
            _service_line(setup["service"]["id"], pair_key="new-1", unit_rate="50", quantity="6"),
        ],
    ), status=201)
    assert Decimal(created["adjusted_services_total"]) == Decimal("1800.00")

    after_keys = [line["client_key"] for line in created["after"]["services"]]
    assert after_keys == ["sv0", "new-1"]
    before_keys = [line["client_key"] for line in created["before"]["services"]]
    assert before_keys == ["sv0"]

    # Dropping the added line in a draft edit leaves the paired line working.
    updated = client.patch(f"/api/v1/afe/sow-adjustments/{created['id']}", headers=headers, json={
        "services": [_service_line(setup["service"]["id"], pair_key="sv0", unit_rate="120", quantity="10")],
        "consumables": [],
        "tangibles": [],
        "reason": "Second logging unit dropped from the revision",
    })
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert Decimal(body["adjusted_services_total"]) == Decimal("1200.00")
    assert [line["client_key"] for line in body["after"]["services"]] == ["sv0"]

    # A revision may also drop an entered line entirely: before-only rows are removals.
    emptied = client.patch(f"/api/v1/afe/sow-adjustments/{created['id']}", headers=headers, json={
        "services": [],
        "consumables": [],
        "tangibles": [],
        "reason": "Logging service removed from the revised scope",
    })
    assert emptied.status_code == 200, emptied.text
    body = emptied.json()
    assert body["after"]["services"] == []
    assert [line["client_key"] for line in body["before"]["services"]] == ["sv0"]
    assert Decimal(body["adjusted_total"]) == Decimal("0.00")


def test_sow_adjustment_preview_prices_without_saving():
    client = TestClient(app)
    headers = login(client)
    setup = _setup(client, headers)
    _approve_afe(client, headers, setup["afe"]["id"])

    preview = client.post(
        f"/api/v1/afe/afes/{setup['afe']['id']}/sow-adjustments/preview",
        headers=headers, json=_adjustment_payload(setup),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert Decimal(body["adjusted_total"]) == Decimal("2000.00")
    assert body["standard_currency"] == "USD"

    history = client.get(f"/api/v1/afe/afes/{setup['afe']['id']}/sow-adjustments", headers=headers).json()
    assert history == []


def test_plan_adjustment_revises_planned_days_without_touching_the_plan():
    client = TestClient(app)
    headers = login(client)
    setup = _setup(client, headers)
    well_id = setup["well"]["id"]

    created = _post(client, f"/api/v1/rig-well/wells/{well_id}/plan-adjustments", headers, {
        "reason": "Hole problems added two rig days",
        "sow_summary": "Intermediate hole reamed an extra two days",
        "sections": [{
            "pair_key": "s0",
            "hole_section_id": setup["hole"]["id"],
            "from_depth": "0", "to_depth": "1000", "remarks": "",
            "phases": [{"pair_key": "p0-0", "phase_id": setup["phase"]["id"], "days": "12", "remarks": ""}],
        }],
    }, status=201)
    assert created["revision_number"] == 1
    # Days and section count derive from the revised grid — nothing is typed in.
    assert Decimal(created["planned_days_before"]) == Decimal("10.00")
    assert Decimal(created["planned_days_after"]) == Decimal("12.00")
    assert Decimal(created["delta_days"]) == Decimal("2.00")
    assert created["section_count_before"] == 1
    assert created["section_count_after"] == 1

    # The two-sided grid reads every revised value against the entered one.
    before = created["sections_before"][0]
    after = created["sections_after"][0]
    assert before["pair_key"] == "s0" and after["pair_key"] == "s0"
    assert before["change"] == "modified" and after["change"] == "modified"
    assert Decimal(before["phases"][0]["days"]) == Decimal("10.00")
    assert Decimal(after["phases"][0]["days"]) == Decimal("12.00")
    assert before["phases"][0]["change"] == "modified"
    assert after["phases"][0]["change"] == "modified"

    wells = client.get("/api/v1/rig-well/wells", headers=headers).json()
    assert wells[0]["has_plan_adjustment"] is False
    assert Decimal(wells[0]["total_days"]) == Decimal("10.00")

    approved = client.post(
        f"/api/v1/rig-well/plan-adjustments/{created['id']}/approve", headers=headers, json={"remarks": "Days verified"},
    )
    assert approved.status_code == 200, approved.text

    wells = client.get("/api/v1/rig-well/wells", headers=headers).json()
    assert Decimal(wells[0]["total_days"]) == Decimal("10.00")
    assert wells[0]["has_plan_adjustment"] is True
    assert Decimal(wells[0]["adjusted_total_days"]) == Decimal("12.00")
    assert wells[0]["plan_revision"] == 1

    summary = client.get(f"/api/v1/rig-well/wells/{well_id}/adjusted-summary?scope=drilling", headers=headers).json()
    assert Decimal(summary["planned_days_before"]) == Decimal("10.00")
    assert Decimal(summary["planned_days_after"]) == Decimal("12.00")
    assert summary["has_plan_adjustment"] is True
    assert summary["plan_revision"] == 1


def test_plan_adjustment_adds_sections_and_phases_like_the_configuration():
    client = TestClient(app)
    headers = login(client)
    setup = _setup(client, headers)
    well_id = setup["well"]["id"]

    second_hole = _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "8-1/2", "name": "Production hole"})
    second_phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "COMP", "name": "Completion"})

    created = _post(client, f"/api/v1/rig-well/wells/{well_id}/plan-adjustments", headers, {
        "reason": "Production hole added to the revised scope",
        "sow_summary": "Added the 8-1/2 section with a completion phase and extended the surface phase",
        "sections": [
            {
                "pair_key": "s0",
                "hole_section_id": setup["hole"]["id"],
                "from_depth": "0", "to_depth": "1200", "remarks": "",
                "phases": [
                    {"pair_key": "p0-0", "phase_id": setup["phase"]["id"], "days": "14", "remarks": ""},
                    {"pair_key": "p0-1", "phase_id": second_phase["id"], "days": "3", "remarks": ""},
                ],
            },
            {
                "pair_key": "s1",
                "hole_section_id": second_hole["id"],
                "from_depth": "1200", "to_depth": "2500", "remarks": "",
                "phases": [{"pair_key": "p1-0", "phase_id": second_phase["id"], "days": "5", "remarks": ""}],
            },
        ],
    }, status=201)
    assert created["section_count_before"] == 1
    assert created["section_count_after"] == 2
    assert Decimal(created["planned_days_before"]) == Decimal("10.00")
    assert Decimal(created["planned_days_after"]) == Decimal("22.00")

    after = {row["pair_key"]: row for row in created["sections_after"]}
    before = {row["pair_key"]: row for row in created["sections_before"]}
    assert after["s0"]["change"] == "modified"
    assert after["s1"]["change"] == "added"
    assert "s1" not in before
    phase_changes = [(row["pair_key"], row["change"]) for row in after["s0"]["phases"]]
    assert phase_changes == [("p0-0", "modified"), ("p0-1", "added")]

    # The configured plan itself never changes.
    wells = client.get("/api/v1/rig-well/wells", headers=headers).json()
    assert Decimal(wells[0]["total_days"]) == Decimal("10.00")
    assert wells[0]["section_count"] == 1

    # Dropping a whole section in a draft edit records it as a removal.
    updated = client.patch(f"/api/v1/rig-well/plan-adjustments/{created['id']}", headers=headers, json={
        "sections": [{
            "pair_key": "s0",
            "hole_section_id": setup["hole"]["id"],
            "from_depth": "0", "to_depth": "1200", "remarks": "",
            "phases": [{"pair_key": "p0-0", "phase_id": setup["phase"]["id"], "days": "14", "remarks": ""}],
        }],
        "reason": "Production hole dropped again from the revised scope",
    })
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["section_count_after"] == 1
    assert Decimal(body["planned_days_after"]) == Decimal("14.00")
    assert body["sections_before"][0]["pair_key"] == "s0"
    assert all(row["change"] == "removed" for row in body["sections_before"] if row["pair_key"] == "s1")
    assert [row["pair_key"] for row in body["sections_after"]] == ["s0"]


def _make_entry(client, headers, setup, cost_date):
    created = _post(client, "/api/v1/daily-cost/entries", headers, {
        "well_id": setup["well"]["id"], "afe_id": setup["afe"]["id"], "cost_date": cost_date, "remarks": "",
    })
    entry_id = created["entry"]["id"]
    submitted = client.post(f"/api/v1/daily-cost/entries/{entry_id}/submit", headers=headers, json={"remarks": ""})
    assert submitted.status_code == 200, submitted.text
    return entry_id


def test_late_reopen_is_logged_as_an_amendment():
    client = TestClient(app)
    headers = login(client)
    setup = _setup(client, headers)
    old_date = (date.today() - timedelta(days=45)).isoformat()
    entry_id = _make_entry(client, headers, setup, old_date)

    reopened = client.post(
        f"/api/v1/daily-cost/entries/{entry_id}/reopen", headers=headers, json={"remarks": "Correct the standby hours"},
    )
    assert reopened.status_code == 200, reopened.text

    amendments = client.get(f"/api/v1/daily-cost/entries/{entry_id}/amendments", headers=headers).json()
    assert len(amendments) == 1
    assert amendments[0]["amendment_number"] == 1
    assert amendments[0]["days_after_cost_date"] == 45
    assert amendments[0]["reason"] == "Correct the standby hours"


def test_recent_reopen_needs_no_amendment_right():
    client = TestClient(app)
    headers = login(client)
    setup = _setup(client, headers)

    # A cost controller who may reopen sheets but holds no amendment right.
    with SessionLocal() as db:
        organization = db.query(Organization).filter_by(slug="north").one()
        keys = ["daily-cost:read", "daily-cost:update", "daily-cost:submit", "daily-cost:reopen"]
        permissions = db.query(Permission).filter(
            Permission.organization_id == organization.id, Permission.key.in_(keys),
        ).all()
        assert len(permissions) == len(keys)
        role = Role(organization_id=organization.id, name="Cost controller", permissions=permissions)
        db.add(User(
            organization_id=organization.id,
            email="controller@example.com",
            full_name="Cost Controller",
            password_hash=hash_password("correct-password-123"),
            roles=[role],
        ))
        db.commit()
    controller = login(client, email="controller@example.com")

    recent_id = _make_entry(client, headers, setup, date.today().isoformat())
    reopened = client.post(
        f"/api/v1/daily-cost/entries/{recent_id}/reopen", headers=controller, json={"remarks": "Fix today's typo"},
    )
    assert reopened.status_code == 200, reopened.text
    assert client.get(f"/api/v1/daily-cost/entries/{recent_id}/amendments", headers=headers).json() == []

    old_id = _make_entry(client, headers, setup, (date.today() - timedelta(days=60)).isoformat())
    denied = client.post(
        f"/api/v1/daily-cost/entries/{old_id}/reopen", headers=controller, json={"remarks": "Fix an old typo"},
    )
    assert denied.status_code == 403, denied.text
    assert "amendment" in denied.json()["detail"].lower()
