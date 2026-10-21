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
    AuditLog, MudCostEntry, MudCostEntryLine, Organization, Permission, Role, User,
)


PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
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
            role = Role(
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


def _json(client, method: str, path: str, headers: dict[str, str], payload: dict, status: int = 200) -> dict:
    response = client.get(path, headers=headers) if method == "get" else getattr(client, method)(path, headers=headers, json=payload)
    assert response.status_code == status, response.text
    return response.json()


def setup_well(client: TestClient, headers: dict[str, str]) -> dict:
    holes = []
    for code, name in (("17-1/2", "Surface hole"), ("12-1/4", "Intermediate hole")):
        holes.append(_json(client, "post", "/api/v1/master-data/hole-sections", headers, {
            "code": code, "name": name,
        }, 201))
    phase = _json(client, "post", "/api/v1/master-data/phases", headers, {
        "code": "DRILL", "name": "Drilling",
    }, 201)
    rig = _json(client, "post", "/api/v1/rig-well/rigs", headers, {
        "rig_code": "RIG-01", "rig_name": "Rig One", "remarks": "",
    }, 201)
    well = _json(client, "post", "/api/v1/rig-well/wells", headers, {
        "rig_id": rig["id"], "well_code": "WELL-01", "well_name": "Well One",
        "well_location": "North field", "block": "Block A", "objective": "Development",
        "remarks": "",
    }, 201)
    configured = _json(client, "put", f"/api/v1/rig-well/wells/{well['id']}/configuration", headers, {
        "depth_unit": "m",
        "sections": [
            {
                "hole_section_id": holes[0]["id"], "from_depth": "0", "to_depth": "1000", "remarks": "",
                "phases": [{"phase_id": phase["id"], "days": "10", "remarks": ""}],
            },
            {
                "hole_section_id": holes[1]["id"], "from_depth": "1000", "to_depth": "2500", "remarks": "",
                "phases": [{"phase_id": phase["id"], "days": "15", "remarks": ""}],
            },
        ],
    })
    transitioned = _json(client, "post", f"/api/v1/rig-well/wells/{well['id']}/transition", headers, {
        "action": "configure", "remarks": "Mud sections confirmed",
    })
    assert transitioned["config_status"] == "configured"
    sections = configured["sections"]
    assert len(sections) == 2
    reference = _json(client, "get", "/api/v1/mud-cost/reference", headers, {})
    well_reference = next(item for item in reference["wells"] if item["id"] == well["id"])
    assert {item["id"] for item in well_reference["sections"]} == {item["id"] for item in sections}
    return {"rig": rig, "well": well, "sections": sections, "reference": reference}


def line(code: str, amount: str | None, remarks: str = "") -> dict[str, str | None]:
    return {"line_code": code, "amount": amount, "remarks": remarks}


def create_entry(client, headers, scope, entry_date, section_index=0, lines=None, status=201):
    return _json(client, "post", "/api/v1/mud-cost/entries", headers, {
        "rig_id": scope["rig"]["id"],
        "well_id": scope["well"]["id"],
        "section_id": scope["sections"][section_index]["id"],
        "entry_date": entry_date,
        "lines": lines or [],
    }, status)


def test_daily_lines_persist_and_balances_carry_forward_inside_each_section():
    with TestClient(app) as client:
        headers = login(client)
        scope = setup_well(client, headers)
        first = create_entry(client, headers, scope, "2026-10-10", lines=[
            line("opening_stock", "500", "Initial pit inventory"),
            line("extra_obm_received", "30", "Supplier delivery ticket 1048"),
            line("barite", "5", "Weighting agent addition"),
            line("shakers", "8", "Cuttings at shakers"),
            line("offline_centrifuge_loss", "2", "Offline centrifuge dump"),
        ])
        assert Decimal(first["opening_stock"]) == Decimal("500")
        assert Decimal(first["receipt"]) == Decimal("30")
        assert Decimal(first["additions"]) == Decimal("5")
        assert Decimal(first["consumption_losses"]) == Decimal("8")
        assert Decimal(first["others"]) == Decimal("2")
        assert Decimal(first["closing_stock"]) == Decimal("525")
        assert "variance" not in first and "actual_closing_stock" not in first
        assert first["opening_stock_remarks"] == "Initial pit inventory"
        assert len(first["lines"]) == 24

        second = create_entry(client, headers, scope, "2026-10-11", lines=[
            line("other_receipts", "10", "Recovered mud return"),
        ])
        assert Decimal(second["opening_stock"]) == Decimal("525")
        assert second["opening_stock_remarks"] == ""
        assert Decimal(second["closing_stock"]) == Decimal("535")

        other_section = create_entry(client, headers, scope, "2026-10-12", section_index=1, lines=[
            line("opening_stock", "700", "First stock in this section"),
        ])
        assert Decimal(other_section["opening_stock"]) == Decimal("700")
        assert Decimal(other_section["closing_stock"]) == Decimal("700")

        listed = client.get(
            f"/api/v1/mud-cost/entries?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}",
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        by_date = {row["entry_date"]: row for row in listed.json()}
        assert Decimal(by_date["2026-10-11"]["opening_stock"]) == Decimal("525")
        assert Decimal(by_date["2026-10-12"]["opening_stock"]) == Decimal("700")

        daily = client.get(
            f"/api/v1/mud-cost/material-balance?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}&view=daily",
            headers=headers,
        )
        assert daily.status_code == 200, daily.text
        assert daily.json()["entry_count"] == 3
        assert daily.json()["selected_section_count"] == 2
        assert len(daily.json()["rows"]) == 3
        section_ids = {row["section_id"] for row in daily.json()["rows"]}
        assert section_ids == {item["id"] for item in scope["sections"]}

        monthly = client.get(
            f"/api/v1/mud-cost/material-balance?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}&view=monthly&from=2026-10-01&to=2026-10-31",
            headers=headers,
        )
        assert monthly.status_code == 200, monthly.text
        assert monthly.json()["entry_count"] == 3
        assert len(monthly.json()["rows"]) == 2
        monthly_by_section = {row["section_id"]: row for row in monthly.json()["rows"]}
        first_section_id, second_section_id = [item["id"] for item in scope["sections"]]
        assert Decimal(monthly_by_section[first_section_id]["opening_stock"]) == Decimal("500")
        assert Decimal(monthly_by_section[first_section_id]["closing_stock"]) == Decimal("535")
        assert Decimal(monthly_by_section[second_section_id]["opening_stock"]) == Decimal("700")

        section_view = client.get(
            f"/api/v1/mud-cost/material-balance?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}&view=section",
            headers=headers,
        )
        inception = client.get(
            f"/api/v1/mud-cost/material-balance?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}&view=inception",
            headers=headers,
        )
        assert section_view.status_code == 200, section_view.text
        assert inception.status_code == 200, inception.text
        assert len(section_view.json()["rows"]) == len(inception.json()["rows"]) == 2
        assert all(row["entry_count"] >= 1 for row in inception.json()["rows"])

        with SessionLocal() as db:
            organization = db.scalar(select(Organization).where(Organization.slug == "north"))
            stored_entry = db.scalar(select(MudCostEntry).where(
                MudCostEntry.organization_id == organization.id,
                MudCostEntry.id == first["id"],
            ))
            assert stored_entry is not None
            stored_lines = db.scalars(select(MudCostEntryLine).where(
                MudCostEntryLine.organization_id == organization.id,
                MudCostEntryLine.entry_id == first["id"],
            )).all()
            assert len(stored_lines) == 24
            stored = {row.line_code: row for row in stored_lines}
            assert stored["extra_obm_received"].amount == Decimal("30.000")
            assert stored["extra_obm_received"].remarks == "Supplier delivery ticket 1048"
            assert stored["opening_stock"].amount == Decimal("500.000")
            carried = db.scalar(select(MudCostEntryLine).where(
                MudCostEntryLine.entry_id == second["id"],
                MudCostEntryLine.line_code == "opening_stock",
            ))
            assert carried is not None
            assert carried.amount == Decimal("525.000")
            assert carried.remarks == ""


def test_one_well_date_and_tenant_boundaries_are_enforced():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        scope = setup_well(client, north)

        created = create_entry(client, north, scope, "2026-10-10", lines=[
            line("opening_stock", "10"),
        ])
        duplicate = create_entry(client, north, scope, "2026-10-10", section_index=1, lines=[
            line("opening_stock", "999", "Must not replace"),
        ], status=409)
        assert "already exists" in duplicate["detail"] and "Open or restore" in duplicate["detail"]

        assert client.get("/api/v1/mud-cost/entries", headers=south).json() == []
        foreign = client.get(
            f"/api/v1/mud-cost/entries?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}",
            headers=south,
        )
        assert foreign.status_code == 404
        assert client.get(f"/api/v1/mud-cost/entries/{created['id']}", headers=south).status_code == 404

        second_rig = _json(client, "post", "/api/v1/rig-well/rigs", north, {
            "rig_code": "RIG-02", "rig_name": "Rig Two", "remarks": "",
        }, 201)
        reassignment = client.patch(
            f"/api/v1/rig-well/wells/{scope['well']['id']}", headers=north,
            json={"rig_id": second_rig["id"]},
        )
        assert reassignment.status_code == 409
        assert "retained Mud Cost" in reassignment.json()["detail"]

        blocked_well = client.delete(f"/api/v1/rig-well/wells/{scope['well']['id']}", headers=north)
        assert blocked_well.status_code == 409
        assert "active Mud Cost" in blocked_well.json()["detail"]


def test_bulk_import_delete_restore_and_export_audit_keep_balances_consistent():
    with TestClient(app) as client:
        headers = login(client)
        scope = setup_well(client, headers)
        imported = _json(client, "post", "/api/v1/mud-cost/entries/import", headers, {
            "rig_id": scope["rig"]["id"],
            "well_id": scope["well"]["id"],
            "section_id": scope["sections"][0]["id"],
            "rows": [
                {
                    "entry_date": "2026-10-11",
                    "other_receipts": "10",
                    "other_receipts_remarks": "",
                    "actual_closing_stock": "530",
                    "actual_closing_stock_remarks": "Daily tank reading",
                },
                {
                    "entry_date": "2026-10-10",
                    "opening_stock": "500",
                    "opening_stock_remarks": "Initial tank measurement",
                    "extra_obm_received": "30",
                    "extra_obm_received_remarks": "",
                    "actual_closing_stock": "520",
                    "actual_closing_stock_remarks": "Daily tank reading",
                },
                {
                    "entry_date": "2026-10-12",
                    "extra_obm_received": "-5",
                    "actual_closing_stock": "535",
                    "actual_closing_stock_remarks": "Remark absent on receipt",
                },
            ],
        })
        assert imported["imported_count"] == 2
        assert imported["error_count"] == 1
        assert imported["success"] is False
        assert imported["errors"][0].startswith("Row 3:")

        entries_response = client.get(
            f"/api/v1/mud-cost/entries?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}",
            headers=headers,
        )
        entries = entries_response.json()
        assert [row["entry_date"] for row in entries] == ["2026-10-11", "2026-10-10"]
        assert Decimal(entries[0]["opening_stock"]) == Decimal("530")

        ids = [row["id"] for row in entries]
        bulk_deleted = _json(client, "post", "/api/v1/mud-cost/entries/bulk-delete", headers, {"ids": ids})
        assert bulk_deleted["affected_count"] == 2
        assert client.get("/api/v1/mud-cost/entries", headers=headers).json() == []
        retained = client.get("/api/v1/mud-cost/entries/deleted", headers=headers).json()
        assert len(retained) == 2
        blocked_date = create_entry(client, headers, scope, "2026-10-10", lines=[], status=409)
        assert "already exists" in blocked_date["detail"]

        restored = _json(client, "post", "/api/v1/mud-cost/entries/bulk-restore", headers, {"ids": ids})
        assert restored["affected_count"] == 2
        restored_entries = client.get(
            f"/api/v1/mud-cost/entries?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}",
            headers=headers,
        ).json()
        assert len(restored_entries) == 2
        assert {row["entry_date"] for row in restored_entries} == {"2026-10-10", "2026-10-11"}

        audited = client.post("/api/v1/mud-cost/export-audit", headers=headers, json={
            "module": "material_balance", "format": "csv", "record_count": 2,
            "rig_id": scope["rig"]["id"], "well_id": scope["well"]["id"],
            "section_id": scope["sections"][0]["id"], "view": "daily",
            "date_from": "2026-10-01", "date_to": "2026-10-31",
        })
        assert audited.status_code == 204, audited.text
        with SessionLocal() as db:
            organization = db.scalar(select(Organization).where(Organization.slug == "north"))
            log = db.scalar(select(AuditLog).where(
                AuditLog.organization_id == organization.id,
                AuditLog.entity_type == "mud_cost_export",
            ))
            assert log is not None
            assert "material balance" in log.summary
            assert scope["sections"][0]["id"] in log.summary


def test_daily_cost_permission_set_covers_mud_cost_workflow():
    from app.services.provisioning import CAPABILITIES

    assert "daily-cost" in CAPABILITIES
    assert set(CAPABILITIES["daily-cost"]) >= {
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
    }


def test_skipped_days_locked_openings_and_recalculation_after_changes():
    with TestClient(app) as client:
        headers = login(client)
        scope = setup_well(client, headers)
        first = create_entry(client, headers, scope, "2026-10-15", lines=[
            line("opening_stock", "100"), line("extra_obm_received", "25"),
        ])
        # No entry on the 16th: both its opening and closing are implicitly 125.
        later = create_entry(client, headers, scope, "2026-10-17", lines=[
            line("opening_stock", "999"), line("shakers", "5", "x"),
        ])
        assert Decimal(later["opening_stock"]) == Decimal("125")
        assert Decimal(later["closing_stock"]) == Decimal("120")

        def get_later():
            return _json(client, "get", f"/api/v1/mud-cost/entries/{later['id']}", headers, {})

        def update(entry, entry_date, lines):
            return _json(client, "put", f"/api/v1/mud-cost/entries/{entry['id']}", headers, {
                "entry_date": entry_date, "lines": lines,
            })

        # The original opening cannot be overwritten through the API either.
        changed = update(first, "2026-10-15", [line("opening_stock", "999"), line("extra_obm_received", "30")])
        assert Decimal(changed["opening_stock"]) == Decimal("100")
        assert Decimal(get_later()["opening_stock"]) == Decimal("130")

        inserted = create_entry(client, headers, scope, "2026-10-16", lines=[line("barite", "2")])
        assert Decimal(inserted["opening_stock"]) == Decimal("130")
        assert Decimal(get_later()["opening_stock"]) == Decimal("132")
        assert Decimal(get_later()["closing_stock"]) == Decimal("127")

        # Filtering out prior days must not reset the opening stock.
        for view in ("daily", "monthly", "section", "inception"):
            balance = client.get("/api/v1/mud-cost/material-balance", headers=headers, params={
                "rig_id": scope["rig"]["id"], "well_id": scope["well"]["id"],
                "view": view, "from": "2026-10-17", "to": "2026-10-17",
            })
            assert balance.status_code == 200, balance.text
            row = balance.json()["rows"][0]
            assert Decimal(row["opening_stock"]) == Decimal("100" if view == "inception" else "132")
            assert Decimal(row["closing_stock"]) == Decimal("127")
            assert "variance" not in row and "actual_closing_stock" not in row

        _json(client, "post", "/api/v1/mud-cost/entries/bulk-delete", headers, {"ids": [inserted["id"]]})
        assert Decimal(get_later()["opening_stock"]) == Decimal("130")
        _json(client, "post", "/api/v1/mud-cost/entries/bulk-restore", headers, {"ids": [inserted["id"]]})
        assert Decimal(get_later()["opening_stock"]) == Decimal("132")

        # Moving a transaction to after the 17th removes it from that day's opening.
        update(inserted, "2026-10-18", [line("barite", "2")])
        assert Decimal(get_later()["opening_stock"]) == Decimal("130")
        # A new earlier date also reuses the initial stock instead of accepting another seed.
        earlier = create_entry(client, headers, scope, "2026-10-14", lines=[
            line("opening_stock", "999"), line("base_oil", "3"),
        ])
        assert Decimal(earlier["opening_stock"]) == Decimal("100")
        assert Decimal(get_later()["opening_stock"]) == Decimal("133")


def test_all_remarks_optional_and_legacy_closing_never_drives_balance():
    from app.domain.mud_cost import MUD_COST_LINE_SPECS

    with TestClient(app) as client:
        headers = login(client)
        scope = setup_well(client, headers)
        first = create_entry(client, headers, scope, "2026-10-15", lines=[
            line(spec.code, "1") for spec in MUD_COST_LINE_SPECS
        ])
        assert all(row["remarks"] == "" for row in first["lines"])
        # Negative calculated stock is not clamped to zero on carry-forward.
        assert Decimal(first["closing_stock"]) < 0
        with SessionLocal() as db:
            stored = db.get(MudCostEntry, first["id"])
            db.add(MudCostEntryLine(
                organization_id=stored.organization_id, entry_id=stored.id,
                line_code="actual_closing_stock", category="closing_stock",
                line_label="Actual Closing Stock", amount=Decimal("999"), remarks="Legacy measurement", sort_order=24,
            ))
            db.commit()
        later = create_entry(client, headers, scope, "2026-10-17")
        assert Decimal(later["opening_stock"]) == Decimal(first["closing_stock"])
        assert Decimal(later["closing_stock"]) == Decimal(first["closing_stock"])
        assert all(row["line_code"] != "actual_closing_stock" for row in later["lines"])
        rejected = create_entry(client, headers, scope, "2026-10-18", lines=[
            line("actual_closing_stock", "100"),
        ], status=422)
        assert "Unknown Mud Cost Analysis row" in str(rejected)


def test_loss_report_counts_consumption_other_but_excludes_separate_others_section():
    from app.domain.mud_cost import loss_breakdown

    values = {
        "centrifuge": Decimal("3"),
        "consumption_losses_others": Decimal("4"),
        "offline_centrifuge_loss": Decimal("5"),
        "backloads": Decimal("6"),
        "obm_left_in_hole": Decimal("7"),
        "other_losses_others": Decimal("8"),
    }
    losses = loss_breakdown(values)
    assert losses["centrifuge"] == Decimal("3")
    assert losses["other_losses"] == Decimal("4")
    assert losses["surface_loss_total"] == Decimal("3")
    assert losses["other_loss_total"] == Decimal("4")
    assert losses["total_losses"] == Decimal("7")
