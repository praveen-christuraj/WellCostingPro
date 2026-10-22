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
from app.models import AuditLog, LihCostEntry, LihCostLine, Organization, Permission, Role, User


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


def setup_well(client, headers, *, with_daily_sheet: bool = True) -> dict:
    _post(client, "/api/v1/master-data/currencies", headers, {"code": "USD", "name": "US Dollar", "symbol": "$"})
    _post(client, "/api/v1/master-data/uom", headers, {"code": "EA", "name": "Each", "symbol": "ea"})
    hole = _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "17-1/2", "name": "Surface hole"})
    phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
    activity = _post(client, "/api/v1/master-data/activities", headers, {"code": "DRL", "name": "Drilling"})
    vendor = _post(client, "/api/v1/master-data/vendors", headers, {
        "vendor_code": "VEND-01", "vendor_name": "Acme Services", "category": "Drilling", "status": "active",
    })
    service = _post(client, "/api/v1/master-data/services", headers, {
        "service_code": "MUD-LOG", "service_name": "Mud logging", "service_category": "Drilling Services",
        "service_group": "Formation Evaluation", "provider_type": "Third Party Services",
        "vendor_id": vendor["id"], "description": "Wellsite logging crew",
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
    assert client.post(f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers, json={
        "action": "configure", "remarks": "Plan checked",
    }).status_code == 200
    sub = _post(client, "/api/v1/rig-well/sub-activities", headers, {
        "well_id": well["id"], "sub_activity_code": "SA-1", "sub_activity_name": "Drill ahead",
        "activity_id": activity["id"], "responsible_party": "Operations team", "description": "Execute the step.",
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
        "consumables": [{
            "client_key": "bulk-mud", "category": "Mud Chemicals", "hole_section_id": hole["id"],
            "phase_id": phase["id"], "drill_bit_id": None, "quantity": "1", "override_rate": None,
            "estimated_amount": "5000", "currency": "USD", "remarks": "Bulk chemicals allowance",
        }],
        "tangibles": [], "standard_currency": "", "exchange_rates": [],
    })
    assert estimate.status_code == 200, estimate.text
    setup = {
        "rig": rig, "well": well, "afe": afe, "activity": activity, "hole": hole, "phase": phase,
        "service": service, "sub": sub, "vendor": vendor,
    }
    if not with_daily_sheet:
        return setup
    created = _post(client, "/api/v1/daily-cost/entries", headers, {
        "well_id": well["id"], "afe_id": afe["id"], "cost_date": "2026-10-10", "remarks": "Night shift",
    })
    setup["entry"] = created["entry"]
    baseline = client.get(f"/api/v1/daily-cost/entries/{created['entry']['id']}/baseline", headers=headers).json()
    rate = baseline["service_rates"][0]
    saved = client.put(f"/api/v1/daily-cost/entries/{created['entry']['id']}", headers=headers, json={
        "remarks": "Night shift actuals",
        "services": [{
            "activity_id": activity["id"], "hole_section_id": hole["id"], "phase_id": phase["id"],
            "sub_activity_id": sub["id"], "vendor_id": vendor["id"], "quantity": "1", "quantity_unit": "days",
            "currency": "USD", "override_rate": None, "override_reason": "", "remarks": "",
            "service_id": service["id"], "baseline_service_rate_id": rate["id"],
            "charging_basis": "Day Rate", "charge_category": "Operation",
        }],
        "consumables": [], "tangibles": [],
    })
    assert saved.status_code == 200, saved.text
    assert Decimal(saved.json()["entry"]["total_cost"]) == Decimal("100.00")
    return setup


def _line(**overrides):
    payload = {
        "item_description": "6 5/8 in drill collar",
        "od_size": "6.625", "id_size": "2.8125", "fish_neck_od": "4.5", "fish_neck_length": "24",
        "serial_number": "DC-0091", "connection": "NC50", "length": "9.5",
        "no_of_units": "2", "unit": "EA", "unit_cost": "1250.50", "remarks": "Left in hole while reaming",
    }
    payload.update(overrides)
    return payload


def test_lih_register_reference_items_totals_and_deletion_lifecycle():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_well(client, headers)
        reference = client.get("/api/v1/lih-cost/reference", headers=headers).json()
        assert reference["rigs"][0]["rig_code"] == "RIG-01"
        assert reference["wells"][0]["rig_id"] == setup["rig"]["id"]
        assert reference["afes"][0]["standard_currency"] == "USD"
        assert reference["uoms"][0]["code"] == "EA"
        assert reference["default_currency"] == "USD"

        created = _post(client, "/api/v1/lih-cost/entries", headers, {
            "well_id": setup["well"]["id"], "rig_id": setup["rig"]["id"], "cost_date": "2026-10-12",
            "remarks": "Fishing job",
        })
        entry_id = created["entry"]["id"]
        assert created["entry"]["afe_id"] == setup["afe"]["id"]
        assert created["entry"]["currency"] == "USD"
        assert Decimal(created["entry"]["total_cost"]) == 0

        # One register per well and date.
        duplicate = client.post("/api/v1/lih-cost/entries", headers=headers, json={
            "well_id": setup["well"]["id"], "cost_date": "2026-10-12",
        })
        assert duplicate.status_code == 409

        first = _post(client, f"/api/v1/lih-cost/entries/{entry_id}/lines", headers, _line())
        assert Decimal(first["lines"][0]["total_cost"]) == Decimal("2501.00")  # 2 × 1250.50
        assert first["entry"]["line_count"] == 1
        second = _post(client, f"/api/v1/lih-cost/entries/{entry_id}/lines", headers, _line(
            item_description="Stabilizer", no_of_units="3", unit="EA", unit_cost="99.99",
            serial_number="", connection="", remarks="", od_size=None,
        ))
        assert second["entry"]["line_count"] == 2
        assert Decimal(second["entry"]["total_cost"]) == Decimal("2800.97")
        assert second["lines"][1]["od_size"] is None

        # The system computes the total; a client-supplied total is rejected.
        supplied = client.post(f"/api/v1/lih-cost/entries/{entry_id}/lines", headers=headers, json=_line(
            item_description="Extra", total_cost="1",
        ))
        assert supplied.status_code == 422
        # Mandatory fields are enforced.
        assert client.post(f"/api/v1/lih-cost/entries/{entry_id}/lines", headers=headers, json=_line(
            item_description="   ",
        )).status_code == 422
        assert client.post(f"/api/v1/lih-cost/entries/{entry_id}/lines", headers=headers, json=_line(
            no_of_units="0",
        )).status_code == 422

        first_id = first["lines"][0]["id"]
        updated = client.put(f"/api/v1/lih-cost/entries/{entry_id}/lines/{first_id}", headers=headers, json=_line(
            unit_cost="1000", length="9.75",
        ))
        assert updated.status_code == 200, updated.text
        assert Decimal(updated.json()["entry"]["total_cost"]) == Decimal("2299.97")

        removed = client.delete(f"/api/v1/lih-cost/entries/{entry_id}/lines/{first_id}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert removed.json()["entry"]["line_count"] == 1
        assert Decimal(removed.json()["entry"]["total_cost"]) == Decimal("299.97")

        day = client.get("/api/v1/lih-cost/day", headers=headers, params={
            "well_id": setup["well"]["id"], "date": "2026-10-12",
        }).json()
        assert day["entry"]["id"] == entry_id
        assert len(day["lines"]) == 1
        register = client.get("/api/v1/lih-cost/entries", headers=headers, params={
            "well_id": setup["well"]["id"],
        }).json()
        assert len(register) == 1

        # Tenant isolation.
        south = login(client, "south")
        assert client.get(f"/api/v1/lih-cost/entries/{entry_id}", headers=south).status_code == 404
        assert client.get(f"/api/v1/lih-cost/entries/{entry_id}", headers=headers).status_code == 200

        # Soft delete → deleted entries → restore → soft delete → permanent delete.
        assert client.delete(f"/api/v1/lih-cost/entries/{entry_id}", headers=headers).status_code == 200
        assert client.get("/api/v1/lih-cost/entries", headers=headers).json() == []
        deleted = client.get("/api/v1/lih-cost/entries/deleted", headers=headers).json()
        assert len(deleted) == 1 and deleted[0]["is_deleted"]
        assert client.post(f"/api/v1/lih-cost/entries/{entry_id}/restore", headers=headers).status_code == 200
        assert len(client.get("/api/v1/lih-cost/entries", headers=headers).json()) == 1
        assert client.delete(f"/api/v1/lih-cost/entries/{entry_id}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/lih-cost/entries/{entry_id}/permanent", headers=headers).status_code == 204
        with SessionLocal() as db:
            assert db.scalar(select(LihCostEntry.id).where(LihCostEntry.id == entry_id)) is None
            assert db.scalars(select(LihCostLine.id)).all() == []
            actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "lih_cost")).all()
            assert "create" in actions and "restore" in actions and "permanent-delete" in actions


def test_lih_cost_is_added_to_actual_and_deducted_from_the_afe_everywhere():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_well(client, headers)
        entry = _post(client, "/api/v1/lih-cost/entries", headers, {
            "well_id": setup["well"]["id"], "cost_date": "2026-10-10",
        })
        # 2 × 1250.50 + 3 × 99.99 = 2800.97
        _post(client, f"/api/v1/lih-cost/entries/{entry['entry']['id']}/lines", headers, _line())
        _post(client, f"/api/v1/lih-cost/entries/{entry['entry']['id']}/lines", headers, _line(
            item_description="Stabilizer", no_of_units="3", unit="EA", unit_cost="99.99",
        ))

        day = client.get(f"/api/v1/daily-cost/entries/{setup['entry']['id']}", headers=headers).json()
        comparison = day["comparison"]
        # Planned AFE = 10 days × 100 + 5000 bulk allowance.
        assert Decimal(comparison["planned_total"]) == Decimal("6000.00")
        assert Decimal(comparison["actual_to_date"]) == Decimal("100.00")
        assert Decimal(comparison["lih_cost_to_date"]) == Decimal("2800.97")
        assert Decimal(comparison["actual_including_lih"]) == Decimal("2900.97")
        assert Decimal(comparison["afe_available"]) == Decimal("3199.03")
        assert Decimal(comparison["balance"]) == Decimal("3099.03")
        assert any(item["code"] == "lih-cost-deducted" for item in day["warnings"])

        summary = client.get(
            f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-summary", headers=headers,
        ).json()
        totals = summary["totals"]
        assert Decimal(totals["lih_cost"]) == Decimal("2800.97")
        assert totals["lih_line_count"] == 2
        assert totals["lih_entries"] == 1
        assert Decimal(totals["afe_available"]) == Decimal("3199.03")
        assert Decimal(totals["actual_including_lih"]) == Decimal("2900.97")
        assert Decimal(totals["comparison_actual_including_lih"]) == Decimal("2900.97")
        assert Decimal(totals["comparison_balance_including_lih"]) == Decimal("3099.03")
        position = summary["afes"][0]
        assert Decimal(position["lih_cost"]) == Decimal("2800.97")
        assert Decimal(position["balance_including_lih"]) == Decimal("3099.03")
        assert Decimal(position["afe_available"]) == Decimal("3199.03")
        dashboard_day = next(row for row in summary["daily"] if row["cost_date"] == "2026-10-10")
        assert Decimal(dashboard_day["lih"]) == Decimal("2800.97")
        assert Decimal(dashboard_day["budget_balance_including_lih"]) == Decimal("3099.03")
        lih_block = summary["lih_cost"]
        assert lih_block["available"] and Decimal(lih_block["total"]) == Decimal("2800.97")
        assert lih_block["days"][0]["cost_date"] == "2026-10-10"
        cost_group = next(group for group in summary["factors"] if group["dimension"] == "cost_group")
        lih_row = next(row for row in cost_group["rows"] if row["code"] == "LIH")
        assert Decimal(lih_row["amount"]) == Decimal("2800.97")
        assert any(item["code"] == "lih-cost-deducted" for item in summary["warnings"])

        report = client.get(f"/api/v1/lih-cost/wells/{setup['well']['id']}/report", headers=headers).json()
        assert Decimal(report["total"]) == Decimal("2800.97")
        assert report["line_count"] == 2 and report["entry_count"] == 1
        assert report["currency"] == "USD"
        assert report["days"][0]["lines"][0]["item_description"] == "6 5/8 in drill collar"

        assert client.post("/api/v1/lih-cost/export-audit", headers=headers, json={
            "module": "well-report", "format": "pdf", "record_count": 1, "well_id": setup["well"]["id"],
        }).status_code == 204
        overview = client.get("/api/v1/daily-cost/overview", headers=headers).json()
        assert Decimal(overview["lih_cost_by_currency"]["USD"]) == Decimal("2800.97")
        assert overview["lih_entries"] == 1 and overview["lih_lines"] == 2
        with SessionLocal() as db:
            audit_row = db.scalars(
                select(AuditLog).where(AuditLog.entity_type == "lih_cost_export")
            ).first()
        assert audit_row is not None and "2800" not in audit_row.summary

        # A second AFE on the same well must be chosen explicitly, and only that
        # AFE's own LIH cost is deducted from it.
        second_afe = _post(client, "/api/v1/afe/afes", headers, {
            "rig_id": setup["rig"]["id"], "well_id": setup["well"]["id"], "afe_code": "AFE-02",
            "afe_name": "Completion AFE", "afe_type": "Completion", "remarks": "",
        }, status=200)
        assert client.post("/api/v1/lih-cost/entries", headers=headers, json={
            "well_id": setup["well"]["id"], "cost_date": "2026-10-13",
        }).status_code == 422
        second = _post(client, "/api/v1/lih-cost/entries", headers, {
            "well_id": setup["well"]["id"], "afe_id": second_afe["id"], "cost_date": "2026-10-13",
        })
        _post(client, f"/api/v1/lih-cost/entries/{second['entry']['id']}/lines", headers, _line(
            item_description="Completion packer", no_of_units="1", unit_cost="500",
        ))
        summary = client.get(
            f"/api/v1/daily-cost/wells/{setup['well']['id']}/cost-summary", headers=headers,
        )
        # Two AFE currencies are still USD, so the well summary stays combined.
        assert summary.status_code == 200, summary.text
        positions = {row["afe_code"]: row for row in summary.json()["afes"]}
        # AFE-01 carries the daily sheets, so its position deducts only its own LIH.
        assert Decimal(positions["AFE-01"]["lih_cost"]) == Decimal("2800.97")
        assert Decimal(positions["AFE-01"]["balance_including_lih"]) == Decimal("3099.03")
        # The register's second AFE has no daily sheet yet, so it appears in the
        # LIH deductions rather than in the daily AFE positions, and the well
        # total still includes it.
        deductions = {row["afe_code"]: row for row in summary.json()["lih_cost"]["deductions_by_afe"]}
        assert Decimal(deductions["AFE-01"]["lih_cost"]) == Decimal("2800.97")
        assert Decimal(deductions["AFE-02"]["lih_cost"]) == Decimal("500.00")
        assert Decimal(summary.json()["totals"]["lih_cost"]) == Decimal("3300.97")


def _input_from(line: dict, **overrides) -> dict:
    """Rebuild a worksheet input row from a saved line, as the UI would send it."""
    payload = {
        key: line[key]
        for key in (
            "item_description", "od_size", "id_size", "fish_neck_od", "fish_neck_length",
            "serial_number", "connection", "length", "no_of_units", "unit", "unit_cost", "remarks",
        )
    }
    payload["id"] = line["id"]
    payload.update(overrides)
    return payload


def test_worksheet_save_posts_many_items_at_once_and_only_touches_changed_rows():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_well(client, headers)
        payload = {
            "well_id": setup["well"]["id"],
            "rig_id": setup["rig"]["id"],
            "cost_date": "2026-10-14",
            "remarks": "Fishing job after a twist-off",
            "lines": [
                _line(item_description="6 5/8 in drill collar", no_of_units="2", unit_cost="1250.50"),
                _line(item_description="Stabilizer", no_of_units="3", unit_cost="99.99", source="duplicate"),
                _line(item_description="Bit sub", no_of_units="1", unit_cost="450"),
            ],
        }
        saved = client.put("/api/v1/lih-cost/day", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        day = saved.json()
        # Three items, one save, one register day.
        assert day["entry"]["line_count"] == 3
        assert Decimal(day["entry"]["total_cost"]) == Decimal("3250.97")
        assert day["entry"]["revision"] == 1
        assert day["entry"]["remarks"] == "Fishing job after a twist-off"
        assert day["entry"]["afe_id"] == setup["afe"]["id"]
        assert [line["item_description"] for line in day["lines"]] == [
            "6 5/8 in drill collar", "Stabilizer", "Bit sub",
        ]
        assert [line["sort_order"] for line in day["lines"]] == [0, 1, 2]
        assert [line["source"] for line in day["lines"]] == ["manual", "duplicate", "manual"]
        with SessionLocal() as db:
            created = db.scalars(select(AuditLog).where(AuditLog.entity_type == "lih_cost")).all()
        assert len(created) == 1 and "3 item(s)" in created[0].summary

        # Save again: keep two rows (one edited), drop one, add one, reorder.
        by_description = {line["item_description"]: line for line in day["lines"]}
        second = client.put("/api/v1/lih-cost/day", headers=headers, json={
            "well_id": setup["well"]["id"],
            "cost_date": "2026-10-14",
            "expected_revision": 1,
            "remarks": "Fishing job closed",
            "lines": [
                _line(item_description="Jar", no_of_units="1", unit_cost="700", serial_number="JAR-1"),
                _input_from(by_description["6 5/8 in drill collar"], unit_cost="1300.00"),
                _input_from(by_description["Bit sub"]),
            ],
        })
        assert second.status_code == 200, second.text
        updated = second.json()
        assert updated["entry"]["revision"] == 2
        assert updated["entry"]["line_count"] == 3
        assert [line["item_description"] for line in updated["lines"]] == [
            "Jar", "6 5/8 in drill collar", "Bit sub",
        ]
        assert [line["sort_order"] for line in updated["lines"]] == [0, 1, 2]
        assert Decimal(updated["entry"]["total_cost"]) == Decimal("3750.00")
        # The edited row keeps its identity and its original capture source.
        assert updated["lines"][1]["id"] == by_description["6 5/8 in drill collar"]["id"]
        assert Decimal(updated["lines"][1]["unit_cost"]) == Decimal("1300")
        assert updated["lines"][0]["source"] == "manual"
        assert all(line["item_description"] != "Stabilizer" for line in updated["lines"])

        # A stale worksheet cannot overwrite the newer save.
        stale = client.put("/api/v1/lih-cost/day", headers=headers, json={**payload, "expected_revision": 1})
        assert stale.status_code == 409 and "saved by someone else" in stale.json()["detail"]
        # A row that is no longer on the day is refused, not silently re-created.
        gone = client.put("/api/v1/lih-cost/day", headers=headers, json={
            "well_id": setup["well"]["id"], "cost_date": "2026-10-14",
            "lines": [{"id": by_description["Stabilizer"]["id"], **_line()}],
        })
        assert gone.status_code == 422 and "no longer on this day" in gone.json()["detail"]
        # Totals are never client supplied.
        assert client.put("/api/v1/lih-cost/day", headers=headers, json={
            "well_id": setup["well"]["id"], "cost_date": "2026-10-14",
            "lines": [{**_line(), "total_cost": "1"}],
        }).status_code == 422
        # A day is never created empty by the worksheet endpoint.
        assert client.put("/api/v1/lih-cost/day", headers=headers, json={
            "well_id": setup["well"]["id"], "cost_date": "2026-10-20", "lines": [],
        }).status_code == 422

        # Bulk removal of selected rows in one call.
        keep = updated["lines"][0]["id"]
        others = [line["id"] for line in updated["lines"][1:]]
        removed = client.post(
            f"/api/v1/lih-cost/entries/{updated['entry']['id']}/lines/bulk-delete",
            headers=headers, json={"line_ids": others},
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["entry"]["line_count"] == 1
        assert [line["id"] for line in removed.json()["lines"]] == [keep]
        assert Decimal(removed.json()["entry"]["total_cost"]) == Decimal("700.00")
        assert removed.json()["entry"]["revision"] == 3
        assert client.post(
            f"/api/v1/lih-cost/entries/{updated['entry']['id']}/lines/bulk-delete",
            headers=headers, json={"line_ids": others},
        ).status_code == 422

        # Tenant isolation and RBAC.
        south = login(client, "south")
        assert client.put("/api/v1/lih-cost/day", headers=south, json=payload).status_code == 404
        assert client.get("/api/v1/lih-cost/entries", headers=south).json() == []
        with SessionLocal() as db:
            north_id = select(Organization.id).where(Organization.slug == "north").scalar_subquery()
            role = db.scalar(select(Role).where(Role.organization_id == north_id))
            role.is_owner = False
            role.permissions = [permission for permission in role.permissions
                                if permission.key in ("daily-cost:read", "daily-cost:export")]
            db.commit()
        assert client.put("/api/v1/lih-cost/day", headers=headers, json=payload).status_code == 403
        assert client.post("/api/v1/lih-cost/import", headers=headers, json={
            "well_id": setup["well"]["id"], "rows": [{"item_description": "X", "no_of_units": "1", "unit_cost": "1"}],
        }).status_code == 403
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.organization_id == north_id))
            role.is_owner = True
            db.commit()


def test_lih_import_saves_rows_per_date_and_reports_row_errors_beside_the_row():
    with TestClient(app) as client:
        headers = login(client)
        setup = setup_well(client, headers)
        response = client.post("/api/v1/lih-cost/import", headers=headers, json={
            "well_id": setup["well"]["id"],
            "rows": [
                {"cost_date": "2026-10-15", "item_description": "Drill pipe", "serial_number": "DP-1",
                 "od_size": "5", "no_of_units": "10", "unit": "EA", "unit_cost": "100"},
                {"cost_date": "2026-10-15", "item_description": "Drill pipe joint", "no_of_units": "2",
                 "unit": "EA", "unit_cost": "250.25", "remarks": "Imported from the rig report"},
                {"cost_date": "2026-10-16", "item_description": "Completion packer", "no_of_units": "1",
                 "unit": "EA", "unit_cost": "5000"},
                {"cost_date": "2026-10-16", "item_description": "Blank units"},
                {"item_description": "Row without a date", "no_of_units": "1", "unit_cost": "5"},
            ],
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["imported_count"] == 3
        assert result["day_count"] == 2
        assert result["error_count"] == 2
        assert result["success"] is False
        assert any(message.startswith("Row 4") for message in result["errors"])
        assert any(message.startswith("Row 5") and "date" in message for message in result["errors"])
        assert all("Row 1" not in message for message in result["errors"])

        register = client.get("/api/v1/lih-cost/entries", headers=headers, params={
            "well_id": setup["well"]["id"],
        }).json()
        assert [row["cost_date"] for row in register] == ["2026-10-16", "2026-10-15"]
        by_date = {row["cost_date"]: row for row in register}
        assert by_date["2026-10-15"]["line_count"] == 2
        assert Decimal(by_date["2026-10-15"]["total_cost"]) == Decimal("1500.50")
        day = client.get(f"/api/v1/lih-cost/entries/{by_date['2026-10-15']['id']}", headers=headers).json()
        assert {line["source"] for line in day["lines"]} == {"import"}
        assert day["lines"][1]["remarks"] == "Imported from the rig report"

        # Importing into an existing date appends instead of replacing the day.
        appended = client.post("/api/v1/lih-cost/import", headers=headers, json={
            "well_id": setup["well"]["id"], "cost_date": "2026-10-15",
            "rows": [{"item_description": "Jar", "no_of_units": "1", "unit_cost": "900"}],
        }).json()
        assert appended["imported_count"] == 1 and appended["success"] is True
        day = client.get(f"/api/v1/lih-cost/entries/{by_date['2026-10-15']['id']}", headers=headers).json()
        assert [line["item_description"] for line in day["lines"]] == ["Drill pipe", "Drill pipe joint", "Jar"]
        assert day["entry"]["revision"] == 2

        # Previously used items are offered for quick re-entry, without a serial number.
        reference = client.get("/api/v1/lih-cost/reference", headers=headers).json()
        suggestions = {item["item_description"]: item for item in reference["previous_items"]}
        assert "Drill pipe" in suggestions and "Completion packer" in suggestions
        assert suggestions["Drill pipe"]["unit_cost"] == "100.0000000000"
        assert "serial_number" not in suggestions["Drill pipe"]
        assert len(suggestions) == len(reference["previous_items"])

        with SessionLocal() as db:
            imported = db.scalars(select(AuditLog).where(AuditLog.entity_type == "lih_cost_import")).all()
            assert len(imported) == 2
            assert "3 LIH item(s) into 2 day(s)" in imported[0].summary
