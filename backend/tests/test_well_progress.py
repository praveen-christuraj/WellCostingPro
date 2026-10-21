"""Well progress milestones: Well Spud Date & Time → Progress Completed Date & Time.

Actual days start at the spud instant and end on the last cost-sheet date for
the scope, unless a progress completion instant freezes the count exactly.
"""

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
from app.models import AuditLog, Organization, Permission, Role, User


PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export", "submit", "reopen",
    )),
    *(f"afe:{action}" for action in ("read", "create", "update", "estimate", "submit", "approve")),
    *(f"rig-well:{action}" for action in ("read", "create", "update", "plan-adjust")),
    *(f"master-data:{action}" for action in ("read", "create")),
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


def setup_well(client, headers, *, scope="drilling", days="10"):
    """One rig, one configured well (with a completion mirror scope) and one AFE."""
    hole = _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "17-1/2", "name": "Surface hole"})
    hole_c = _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "8-1/2", "name": "Production hole"})
    phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
    activity = _post(client, "/api/v1/master-data/activities", headers, {"code": "DRL", "name": "Drilling"})
    vendor = _post(client, "/api/v1/master-data/vendors", headers, {
        "vendor_code": "VEND-01", "vendor_name": "Acme Services", "category": "Drilling", "status": "active",
    })
    service = _post(client, "/api/v1/master-data/services", headers, {
        "service_code": "RIG-DAY", "service_name": "Rig day rate", "service_category": "Drilling Services",
        "provider_type": "Third Party Services", "vendor_id": vendor["id"], "description": "",
    })
    rig = _post(client, "/api/v1/rig-well/rigs", headers, {"rig_code": "RIG-01", "rig_name": "Rig One", "remarks": ""})
    well = _post(client, "/api/v1/rig-well/wells", headers, {
        "rig_id": rig["id"], "well_code": "WELL-01", "well_name": "Well One", "well_location": "North field",
        "block": "A", "objective": "Development", "remarks": "",
    })
    sections = [
        {
            "hole_section_id": hole["id"], "from_depth": "0", "to_depth": "1000", "remarks": "",
            "phases": [{"phase_id": phase["id"], "days": days, "remarks": ""}],
        },
    ]
    if scope == "completion":
        sections.append({
            "hole_section_id": hole_c["id"], "scope": "completion", "from_depth": "1000", "to_depth": "1500",
            "remarks": "", "phases": [{"phase_id": phase["id"], "days": "5", "remarks": ""}],
        })
    config = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json={
        "depth_unit": "m", "sections": sections,
    })
    assert config.status_code == 200, config.text
    transition = client.post(f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers, json={
        "action": "configure", "remarks": "Plan checked",
    })
    assert transition.status_code == 200, transition.text
    _post(client, "/api/v1/rig-well/sub-activities", headers, {
        "well_id": well["id"], "sub_activity_code": "SA-1", "sub_activity_name": "Drill ahead",
        "activity_id": activity["id"], "responsible_party": "Operations team", "description": "Drill the section.",
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
            "charges": [{"category": "Operation", "quantity": days, "quantity_unit": "days"}],
            "section_rates": [],
        }],
        "consumables": [], "tangibles": [], "standard_currency": "", "exchange_rates": [],
    })
    assert estimate.status_code == 200, estimate.text
    return well, afe, service, hole, phase


def test_spud_sets_fractional_actual_days_from_the_spud_instant():
    """Spudded 19/10/2026 10:00 hrs: the 19/10/2026 report counts 0.583 days."""
    with TestClient(app) as client:
        headers = login(client)
        well, afe, service, hole, phase = setup_well(client, headers)
        path = f"/api/v1/daily-cost/wells/{well['id']}/progress"

        report = client.get(path, headers=headers)
        assert report.status_code == 200, report.text
        body = report.json()
        assert [row["scope"] for row in body["scopes"]] == ["drilling", "completion"]
        drilling = body["scopes"][0]
        assert drilling["spud_at"] is None and drilling["actual_days"] is None
        assert Decimal(drilling["planned_days"]) == Decimal("10")
        assert drilling["progress_label"] == "Drilling operations completion date & time"

        entered = client.put(path, headers=headers, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00",
        })
        assert entered.status_code == 200, entered.text
        drilling = entered.json()["scopes"][0]
        assert drilling["spud_at"].startswith("2026-10-19T10:00")
        assert drilling["is_completed"] is False
        assert drilling["actual_days"] is None and drilling["as_of_date"] is None

        # Without an explicit report date, the latest saved cost sheet is the
        # inclusive end point; printing later must not keep increasing the days.
        _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": well["id"], "afe_id": afe["id"], "cost_date": "2026-10-20", "remarks": "",
        })
        latest_sheet = client.get(path, headers=headers).json()["scopes"][0]
        assert latest_sheet["as_of_date"] == "2026-10-20"
        assert Decimal(latest_sheet["actual_days"]) == Decimal("1.583")

        # The user's example: the report prepared for 19-10-2026 counts 0.583 days.
        same_day = client.get(path, headers=headers, params={"as_of": "2026-10-19"})
        assert same_day.status_code == 200, same_day.text
        drilling = same_day.json()["scopes"][0]
        assert Decimal(drilling["actual_days"]) == Decimal("0.583")
        assert drilling["as_of_date"] == "2026-10-19"
        assert Decimal(drilling["days_variance"]) == Decimal("0.583") - Decimal("10")

        # The count advances with the report date: end of the 20th = 1 day 14 hrs.
        next_day = client.get(path, headers=headers, params={"as_of": "2026-10-20"})
        assert Decimal(next_day.json()["scopes"][0]["actual_days"]) == Decimal("1.583")

        # A report dated before the spud instant has not counted anything yet.
        before = client.get(path, headers=headers, params={"as_of": "2026-10-18"})
        assert Decimal(before.json()["scopes"][0]["actual_days"]) == Decimal("0.000")


def test_spud_cannot_be_cleared_only_edited_and_days_recalculate():
    with TestClient(app) as client:
        headers = login(client)
        well, *_ = setup_well(client, headers)
        path = f"/api/v1/daily-cost/wells/{well['id']}/progress"
        assert client.put(path, headers=headers, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00",
        }).status_code == 200

        cleared = client.put(path, headers=headers, json={"scope": "drilling", "spud_at": None})
        assert cleared.status_code == 422
        assert "cannot be cleared" in cleared.json()["detail"]

        edited = client.put(path, headers=headers, json={
            "scope": "drilling", "spud_at": "2026-10-17T22:00:00",
        })
        assert edited.status_code == 200, edited.text
        drilling = client.get(path, headers=headers, params={"as_of": "2026-10-20"}).json()["scopes"][0]
        # 17/10 22:00 → 20/10 24:00 = 3 days 2 hours = 3.083 days.
        assert Decimal(drilling["actual_days"]) == Decimal("3.083")
        assert Decimal(drilling["days_variance"]) == Decimal("3.083") - Decimal("10")


def test_progress_completed_stops_the_count_and_freezes_the_variance():
    with TestClient(app) as client:
        headers = login(client)
        well, afe, *_ = setup_well(client, headers)
        path = f"/api/v1/daily-cost/wells/{well['id']}/progress"
        assert client.put(path, headers=headers, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00",
        }).status_code == 200
        _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": well["id"], "afe_id": afe["id"], "cost_date": "2026-10-20", "remarks": "",
        })

        completed = client.put(path, headers=headers, json={
            "scope": "drilling", "progress_completed_at": "2026-10-21T08:00:00",
        })
        assert completed.status_code == 200, completed.text
        drilling = completed.json()["scopes"][0]
        # 19/10 10:00 → 21/10 08:00 = 1 day 22 hours = 1.917 days, frozen.
        assert drilling["is_completed"] is True
        assert Decimal(drilling["actual_days"]) == Decimal("1.917")
        assert Decimal(drilling["days_variance"]) == Decimal("1.917") - Decimal("10")
        assert drilling["as_of_date"] == "2026-10-20"

        later = client.get(path, headers=headers, params={"as_of": "2026-10-30"})
        assert Decimal(later.json()["scopes"][0]["actual_days"]) == Decimal("1.917")

        resumed = client.put(path, headers=headers, json={
            "scope": "drilling", "progress_completed_at": None,
        })
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["scopes"][0]["is_completed"] is False
        assert Decimal(resumed.json()["scopes"][0]["actual_days"]) == Decimal("1.583")
        rolling = client.get(path, headers=headers, params={"as_of": "2026-10-30"})
        assert Decimal(rolling.json()["scopes"][0]["actual_days"]) == Decimal("11.583")


def test_milestone_order_and_future_dates_are_rejected():
    with TestClient(app) as client:
        headers = login(client)
        well, *_ = setup_well(client, headers)
        path = f"/api/v1/daily-cost/wells/{well['id']}/progress"

        # Completion before a spud date, and a completion without any spud date.
        assert client.put(path, headers=headers, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00", "progress_completed_at": "2026-10-19T09:00:00",
        }).status_code == 422
        assert client.put(path, headers=headers, json={
            "scope": "drilling", "progress_completed_at": "2026-10-19T09:00:00",
        }).status_code == 422
        # Future-dated milestones are refused for either field.
        assert client.put(path, headers=headers, json={
            "scope": "drilling", "spud_at": "2099-01-01T10:00:00",
        }).status_code == 422
        assert client.put(path, headers=headers, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00",
        }).status_code == 200
        assert client.put(path, headers=headers, json={
            "scope": "drilling", "progress_completed_at": "2099-01-01T10:00:00",
        }).status_code == 422
        # Unknown fields are rejected outright.
        assert client.put(path, headers=headers, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00", "unexpected": "x",
        }).status_code == 422


def test_day_sheet_summary_and_plan_adjustment_report_progress():
    with TestClient(app) as client:
        headers = login(client)
        well, afe, service, hole, phase = setup_well(client, headers)
        assert client.put(f"/api/v1/daily-cost/wells/{well['id']}/progress", headers=headers, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00",
        }).status_code == 200
        created = _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": well["id"], "afe_id": afe["id"], "cost_date": "2026-10-19", "remarks": "",
        })
        day = client.get(f"/api/v1/daily-cost/entries/{created['entry']['id']}", headers=headers).json()
        assert day["progress"] is not None
        assert day["progress"]["scope"] == "drilling"
        assert day["progress"]["as_of_date"] == "2026-10-19"
        assert Decimal(day["progress"]["actual_days"]) == Decimal("0.583")

        summary = client.get(f"/api/v1/daily-cost/wells/{well['id']}/cost-summary", headers=headers).json()
        assert [row["scope"] for row in summary["progress"]] == ["drilling", "completion"]
        assert summary["progress"][0]["as_of_date"] == "2026-10-19"
        assert Decimal(summary["totals"]["spud_actual_days"]) == Decimal("0.583")

        # An approved plan adjustment replaces the configured planned days.
        adjustment = _post(client, f"/api/v1/rig-well/wells/{well['id']}/plan-adjustments", headers, {
            "configuration_scope": "drilling", "planned_days_after": "12.5",
            "section_count_after": 1, "reason": "Added a contingency window",
        })
        approved = client.post(
            f"/api/v1/rig-well/plan-adjustments/{adjustment['id']}/approve", headers=headers, json={"remarks": ""},
        )
        assert approved.status_code == 200, approved.text
        drilling = client.get(
            f"/api/v1/daily-cost/wells/{well['id']}/progress", headers=headers, params={"as_of": "2026-10-19"},
        ).json()["scopes"][0]
        assert Decimal(drilling["planned_days"]) == Decimal("12.5")
        assert Decimal(drilling["days_variance"]) == Decimal("0.583") - Decimal("12.5")


def test_permissions_and_tenant_scope_guard_the_milestones():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        well, *_ = setup_well(client, north)
        path = f"/api/v1/daily-cost/wells/{well['id']}/progress"

        # Another workspace cannot see or edit the well's milestones.
        assert client.get(path, headers=south).status_code == 404
        assert client.put(path, headers=south, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00",
        }).status_code == 404

        # A read-only user can read but not enter or edit the milestones.
        with SessionLocal() as db:
            north_id = select(Organization.id).where(Organization.slug == "north").scalar_subquery()
            user = db.scalar(select(User).where(User.email == "owner@example.com", User.organization_id == north_id))
            role = user.roles[0]
            role.is_owner = False
            role.permissions = [permission for permission in role.permissions if permission.key == "daily-cost:read"]
            db.commit()
        assert client.get(path, headers=north).status_code == 200
        blocked = client.put(path, headers=north, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00",
        })
        assert blocked.status_code == 403
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.organization_id == north_id))
            role.is_owner = True
            db.commit()

        entered = client.put(path, headers=north, json={
            "scope": "drilling", "spud_at": "2026-10-19T10:00:00",
        })
        assert entered.status_code == 200, entered.text

        audits = client.get("/api/v1/audit", headers=north, params={"page_size": 50}).json()
        entries = audits["items"] if isinstance(audits, dict) else audits
        progress_audits = [row for row in entries if row.get("entity_type") == "well_progress"]
        assert progress_audits, "the spud entry must be audited"
        assert "spud" in progress_audits[0]["summary"].lower()
