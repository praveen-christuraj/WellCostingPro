import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import (
    Afe, AuditLog, DailyCostBaseline, DailyCostConsumableLine, DailyCostEntry,
    DailyCostWellRateBaseline, Organization, Permission, Role, User,
)


PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete",
        "import", "export", "submit", "reopen",
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


def _json(client, method: str, path: str, headers: dict[str, str], payload: dict | None = None, status: int = 200) -> dict:
    response = getattr(client, method)(path, headers=headers, json=payload) if payload is not None else getattr(client, method)(path, headers=headers)
    assert response.status_code == status, response.text
    return response.json()


def setup_well(client: TestClient, headers: dict[str, str]) -> dict:
    _json(client, "post", "/api/v1/master-data/currencies", headers, {
        "code": "USD", "name": "US Dollar", "symbol": "$", "is_default": True,
    }, 201)
    _json(client, "post", "/api/v1/master-data/uom", headers, {
        "code": "BBL", "name": "Barrel", "symbol": "bbl",
    }, 201)
    holes = [
        _json(client, "post", "/api/v1/master-data/hole-sections", headers, {
            "code": code, "name": name,
        }, 201)
        for code, name in (("17-1/2", "Surface hole"), ("12-1/4", "Intermediate hole"))
    ]
    phase = _json(client, "post", "/api/v1/master-data/phases", headers, {
        "code": "DRILL", "name": "Drilling",
    }, 201)
    activity = _json(client, "post", "/api/v1/master-data/activities", headers, {
        "code": "DRL", "name": "Drilling",
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
                "phases": [{"phase_id": phase["id"], "days": "5", "remarks": ""}],
            },
            {
                "hole_section_id": holes[1]["id"], "from_depth": "1000", "to_depth": "2500", "remarks": "",
                "phases": [{"phase_id": phase["id"], "days": "10", "remarks": ""}],
            },
        ],
    })
    _json(client, "post", f"/api/v1/rig-well/wells/{well['id']}/transition", headers, {
        "action": "configure", "remarks": "Mud sections confirmed",
    })
    return {
        "rig": rig, "well": well, "sections": configured["sections"],
        "holes": holes, "phase": phase, "activity": activity,
    }


def line(code: str, amount: str, remarks: str = "") -> dict[str, str]:
    return {"line_code": code, "amount": amount, "remarks": remarks}


def create_mud_entry(client, headers, scope, entry_date, section_index, lines):
    return _json(client, "post", "/api/v1/mud-cost/entries", headers, {
        "rig_id": scope["rig"]["id"],
        "well_id": scope["well"]["id"],
        "section_id": scope["sections"][section_index]["id"],
        "entry_date": entry_date,
        "lines": lines,
    }, 201)


def seed_daily_cost(scope: dict, *, section_costs: list[tuple[str, int, Decimal]]) -> None:
    """Insert daily cost sheets and mud-chemical lines directly.

    The reconciliation only depends on the Daily Cost register's persisted
    section-scoped standard amounts. Inserting those rows directly keeps this
    suite focused on the reconciliation rules instead of re-testing the whole
    AFE/daily-sheet workflow.
    """
    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.slug == "north"))
        afe = Afe(
            organization_id=org.id, rig_id=scope["rig"]["id"], well_id=scope["well"]["id"],
            afe_code="AFE-01", afe_name="Drilling AFE", afe_type="Drilling",
            configuration_scope="drilling", status="approval", standard_currency="USD",
            estimate_saved_at=datetime.now(timezone.utc),
        )
        db.add(afe)
        db.flush()
        rate_baseline = DailyCostWellRateBaseline(organization_id=org.id, well_id=scope["well"]["id"])
        db.add(rate_baseline)
        db.flush()
        baseline = DailyCostBaseline(
            organization_id=org.id, well_id=scope["well"]["id"], afe_id=afe.id,
            rate_baseline_id=rate_baseline.id, afe_code_snapshot=afe.afe_code,
            afe_name_snapshot=afe.afe_name, standard_currency="USD",
            services_total=Decimal("0"), consumables_total=Decimal("5000"),
            tangibles_total=Decimal("0"), total_amount=Decimal("5000"),
        )
        db.add(baseline)
        db.flush()
        for number, (cost_date, section_index, amount) in enumerate(section_costs, start=1):
            entry = DailyCostEntry(
                organization_id=org.id, rig_id=scope["rig"]["id"],
                rig_code_snapshot=scope["rig"]["rig_code"], rig_name_snapshot=scope["rig"]["rig_name"],
                well_id=scope["well"]["id"],
                well_code_snapshot=scope["well"]["well_code"], well_name_snapshot=scope["well"]["well_name"],
                afe_id=afe.id, afe_code_snapshot=afe.afe_code, afe_name_snapshot=afe.afe_name,
                afe_status_at_create=afe.status, rate_baseline_id=rate_baseline.id,
                baseline_id=baseline.id, daily_cost_code=f"DC-{number:03d}",
                cost_date=date.fromisoformat(cost_date), standard_currency="USD",
                status="submitted",
            )
            db.add(entry)
            db.flush()
            hole = scope["holes"][section_index]
            db.add(DailyCostConsumableLine(
                organization_id=org.id, entry_id=entry.id, activity_id=scope["activity"]["id"],
                activity_code_snapshot="DRL", activity_name_snapshot="Drilling",
                section_code_snapshot=hole["code"], section_name_snapshot=hole["name"],
                phase_code_snapshot="DRILL", phase_name_snapshot="Drilling",
                hole_section_id=hole["id"], phase_id=scope["phase"]["id"],
                quantity=Decimal("1"), currency="USD", amount=amount, standard_amount=amount,
                category="Mud Chemicals", item_kind="mud_chemical", item_id="chem-barite",
                item_code_snapshot="BARITE", item_name_snapshot="Barite",
            ))
        db.commit()


def configure_section(client, headers, scope, section_index, mud_type, base_rate, remarks="", status=200):
    return _json(client, "put", "/api/v1/mud-cost/section-settings", headers, {
        "rig_id": scope["rig"]["id"], "well_id": scope["well"]["id"],
        "section_id": scope["sections"][section_index]["id"],
        "mud_type": mud_type, "remarks": remarks,
        "base_rate": base_rate,
    }, status)


def test_section_mud_type_defaults_and_validation():
    with TestClient(app) as client:
        headers = login(client)
        scope = setup_well(client, headers)

        settings = _json(client, "get", f"/api/v1/mud-cost/section-settings?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}", headers)
        assert len(settings) == 2
        assert all(row["is_configured"] is False for row in settings)
        assert all(row["mud_type"] is None for row in settings)
        assert {row["section_id"] for row in settings} == {row["id"] for row in scope["sections"]}

        # OTHERS requires a remark.
        configure_section(client, headers, scope, 0, "OTHERS", "12.5", "", 422)
        # Every non-WBM type requires a positive base rate.
        configure_section(client, headers, scope, 0, "OBM", None, "OBM system", 422)
        configure_section(client, headers, scope, 0, "OBM", "0", "OBM system", 422)

        saved = configure_section(client, headers, scope, 0, "OTHERS", "12.5", "Clay-free synthetic system")
        assert saved["mud_type"] == "OTHERS"
        assert saved["remarks"] == "Clay-free synthetic system"
        assert saved["currency"] == "USD"
        assert saved["is_configured"] is True

        # The configuration is once per section: a second save updates it instead
        # of creating a duplicate row.
        updated = configure_section(client, headers, scope, 0, "SOBM", "10", "Synthetic oil system")
        assert updated["id"] == saved["id"]
        assert updated["mud_type"] == "SOBM"

        # WBM needs no base rate, and stores zero.
        wbm = configure_section(client, headers, scope, 1, "WBM", None)
        assert wbm["mud_type"] == "WBM"
        assert Decimal(wbm["base_rate"]) == 0

        with SessionLocal() as db:
            audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "mud_cost_section_setting")).all()
            assert len(audits) >= 3
            assert {row.action for row in audits} >= {"create", "update"}

        # Tenant boundary: the second workspace cannot see this well's setup.
        south = login(client, "south")
        response = client.get(
            f"/api/v1/mud-cost/section-settings?rig_id={scope['rig']['id']}&well_id={scope['well']['id']}",
            headers=south,
        )
        assert response.status_code == 404


def test_reconciliation_uses_actual_daily_cost_and_latest_cost_per_bbl():
    with TestClient(app) as client:
        headers = login(client)
        scope = setup_well(client, headers)

        create_mud_entry(client, headers, scope, "2026-10-11", 0, [
            line("extra_obm_received", "50"),
            line("drill_water", "100"),
            line("shakers", "10"),
        ])
        create_mud_entry(client, headers, scope, "2026-10-12", 0, [
            line("barite", "50"),
            line("centrifuge", "20"),
        ])
        create_mud_entry(client, headers, scope, "2026-10-13", 1, [
            line("drill_water", "10"),
            line("shakers", "5"),
        ])
        seed_daily_cost(scope, section_costs=[
            ("2026-10-11", 0, Decimal("1000")),
            ("2026-10-12", 0, Decimal("500")),
            ("2026-10-13", 1, Decimal("200")),
        ])
        configure_section(client, headers, scope, 0, "OBM", "2", "Oil based system")
        configure_section(client, headers, scope, 1, "WBM", None)

        params = f"rig_id={scope['rig']['id']}&well_id={scope['well']['id']}&to=2026-10-13"
        result = _json(client, "get", f"/api/v1/mud-cost/reconciliation?{params}", headers)

        assert result["currency"] == "USD"
        assert result["selected_section_count"] == 2
        assert result["configured_section_count"] == 2
        assert result["unconfigured_section_count"] == 0
        assert Decimal(result["total_actual_cost"]) == Decimal("1700")
        assert Decimal(result["total_reconciled_cost"]) == Decimal("440")
        assert Decimal(result["total_adjustment"]) == Decimal("-1260")
        assert Decimal(result["latest_cost_per_bbl"]) == Decimal("20")

        obm = next(row for row in result["sections"] if row["mud_type"] == "OBM")
        assert Decimal(obm["base_rate"]) == Decimal("2")
        assert Decimal(obm["additions"]) == Decimal("150")
        assert Decimal(obm["extra_obm_received"]) == Decimal("50")
        assert Decimal(obm["total_mud"]) == Decimal("200")
        assert Decimal(obm["alpha"]) == Decimal("100")
        assert Decimal(obm["beta"]) == Decimal("1600")
        assert Decimal(obm["actual_cost"]) == Decimal("1500")
        assert Decimal(obm["consumption_losses"]) == Decimal("30")
        assert Decimal(obm["cost_per_bbl"]) == Decimal("8")
        assert Decimal(obm["reconciled_cost"]) == Decimal("240")
        assert Decimal(obm["adjustment"]) == Decimal("-1260")

        wbm = next(row for row in result["sections"] if row["mud_type"] == "WBM")
        assert Decimal(wbm["cost_per_bbl"]) == Decimal("20")
        assert wbm["alpha"] is None and wbm["beta"] is None
        assert Decimal(wbm["reconciled_cost"]) == Decimal("200")
        assert Decimal(wbm["actual_cost"]) == Decimal("200")
        wbm_daily = next(row for row in result["rows"] if row["mud_type"] == "WBM")
        assert Decimal(wbm_daily["cumulative_additions"]) == Decimal("10")
        assert Decimal(wbm_daily["cumulative_actual_cost"]) == Decimal("200")
        assert Decimal(wbm_daily["cost_per_bbl"]) == Decimal("20")

        # Day rows carry the cumulative position to that date. The latest rate is
        # applied to the cumulative consumption for the cumulative amount.
        obm_rows = [row for row in result["rows"] if row["mud_type"] == "OBM"]
        first, second = obm_rows
        assert first["cost_date"] == "2026-10-11"
        assert Decimal(first["total_mud"]) == Decimal("150")
        assert Decimal(first["beta"]) == Decimal("1100")
        assert Decimal(first["cost_per_bbl"]) == Decimal("7.3333333333")
        assert Decimal(first["reconciled_cost"]) == Decimal("73.333333333")
        assert Decimal(first["cumulative_reconciled_cost"]) == Decimal("73.333333333")
        assert second["cost_date"] == "2026-10-12"
        assert Decimal(second["cumulative_total_mud"]) == Decimal("200")
        assert Decimal(second["cost_per_bbl"]) == Decimal("8")
        assert Decimal(second["reconciled_cost"]) == Decimal("160")
        assert Decimal(second["cumulative_reconciled_cost"]) == Decimal("240")

        # Section filtering never mixes another section into the total.
        filtered = _json(client, "get", f"/api/v1/mud-cost/reconciliation?{params}&section_id={scope['sections'][0]['id']}", headers)
        assert filtered["selected_section_count"] == 1
        assert all(row["mud_type"] == "OBM" for row in filtered["rows"])

        # The well cost analysis carries both numbers and compares with the
        # reconciled mud cost only.
        summary = _json(client, "get", f"/api/v1/daily-cost/wells/{scope['well']['id']}/cost-summary", headers)
        assert summary["mud_cost"]["available"] is True
        assert Decimal(summary["mud_cost"]["actual_cost"]) == Decimal("1700")
        assert Decimal(summary["mud_cost"]["reconciled_cost"]) == Decimal("440")
        assert Decimal(summary["mud_cost"]["comparison_cost"]) == Decimal("440")
        assert Decimal(summary["totals"]["actual"]) == Decimal("1700")
        assert Decimal(summary["totals"]["actual_mud_chemicals"]) == Decimal("1700")
        assert Decimal(summary["totals"]["comparison_actual"]) == Decimal("440")
        assert Decimal(summary["totals"]["comparison_consumables"]) == Decimal("440")
        assert Decimal(summary["totals"]["comparison_balance"]) == Decimal("4560")
        assert summary["totals"]["has_mud_reconciliation"] is True
        assert Decimal(summary["mud_cost"]["latest_cost_per_bbl"]) == Decimal("20")

        export = client.post("/api/v1/mud-cost/export-audit", headers=headers, json={
            "module": "reconciliation", "format": "csv", "record_count": len(result["rows"]),
            "rig_id": scope["rig"]["id"], "well_id": scope["well"]["id"],
            "section_id": "", "view": "daily",
            "date_from": None, "date_to": "2026-10-13",
        })
        assert export.status_code == 204, export.text
        with SessionLocal() as db:
            exported = db.scalar(select(AuditLog).where(
                AuditLog.entity_type == "mud_cost_export",
                AuditLog.summary.like("%mud cost reconciliation%"),
            ))
            assert exported is not None


def test_consumption_loss_report_groups_totals_drills_and_exports():
    with TestClient(app) as client:
        headers = login(client)
        scope = setup_well(client, headers)
        configure_section(client, headers, scope, 0, "OBM", "2", "Oil based system")
        configure_section(client, headers, scope, 1, "WBM", None)

        create_mud_entry(client, headers, scope, "2026-10-11", 0, [
            line("verti_g_mud_on_cuttings", "1"),
            line("centrifuge", "2"),
            line("by_pass", "3"),
            line("evaporation", "4"),
            line("trips", "5"),
            line("mud_cleaner", "6"),
            line("formation_seepage", "7"),
            line("pit_cleaning_dump", "8"),
            line("left_in_hole", "9"),
            line("consumption_losses_others", "10"),
            # Historical loss fields remain represented in the requested
            # matrix by rolling into the final Other-loss row.
            line("shakers", "11"),
            line("offline_centrifuge_loss", "12"),
        ])
        create_mud_entry(client, headers, scope, "2026-10-13", 1, [
            line("trips", "3"),
            line("left_in_hole", "4"),
        ])
        create_mud_entry(client, headers, scope, "2026-11-02", 0, [
            line("centrifuge", "1"),
            line("mud_cleaner", "2"),
        ])

        query = f"rig_id={scope['rig']['id']}&well_id={scope['well']['id']}"
        daily = _json(client, "get", f"/api/v1/mud-cost/consumption-losses?{query}&view=daily", headers)
        assert daily["view"] == "daily"
        assert daily["selected_section_count"] == 2
        assert daily["entry_count"] == 3
        assert Decimal(daily["surface_loss_total"]) == 19
        assert Decimal(daily["other_loss_total"]) == 69
        assert Decimal(daily["total_losses"]) == 88

        first = next(row for row in daily["rows"] if row["cost_date"] == "2026-10-11")
        assert first["mud_type"] == "OBM"
        assert Decimal(first["surface_loss_total"]) == 15
        assert Decimal(first["other_losses"]) == 33
        assert Decimal(first["other_loss_total"]) == 63
        assert Decimal(first["total_losses"]) == 78
        assert Decimal(first["surface_loss_total"]) + Decimal(first["other_loss_total"]) == Decimal(first["total_losses"])

        monthly = _json(client, "get", f"/api/v1/mud-cost/consumption-losses?{query}&view=monthly", headers)
        assert monthly["entry_count"] == 3
        assert len(monthly["rows"]) == 3  # October has one row per section; November one.
        october_obm = next(row for row in monthly["rows"] if row["period_label"] == "October 2026" and row["mud_type"] == "OBM")
        assert october_obm["entry_count"] == 1
        assert Decimal(october_obm["total_losses"]) == 78

        section_id = scope["sections"][0]["id"]
        ranged = _json(
            client, "get",
            f"/api/v1/mud-cost/consumption-losses?{query}&section_id={section_id}&view=section&from=2026-10-01&to=2026-10-31",
            headers,
        )
        assert ranged["selected_section_count"] == 1
        assert ranged["entry_count"] == 1
        assert len(ranged["rows"]) == 1
        assert ranged["rows"][0]["period_label"].startswith("Selected range")
        assert Decimal(ranged["total_losses"]) == 78

        inception = _json(
            client, "get",
            f"/api/v1/mud-cost/consumption-losses?{query}&section_id={section_id}&view=inception&from=2026-11-01",
            headers,
        )
        assert inception["from_date"] is None
        assert inception["entry_count"] == 2  # Inception intentionally ignores From.
        assert Decimal(inception["total_losses"]) == 81

        reconciliation = _json(client, "get", f"/api/v1/mud-cost/reconciliation?{query}&to=2026-11-30", headers)
        obm = next(row for row in reconciliation["sections"] if row["mud_type"] == "OBM")
        assert Decimal(obm["surface_loss_total"]) == 16
        assert Decimal(obm["other_loss_total"]) == 65
        assert Decimal(obm["total_losses"]) == 81

        invalid = client.get(
            f"/api/v1/mud-cost/consumption-losses?{query}&section_id=missing", headers=headers,
        )
        assert invalid.status_code == 404
        south = client.get(
            f"/api/v1/mud-cost/consumption-losses?{query}", headers=login(client, "south"),
        )
        assert south.status_code == 404

        export = client.post("/api/v1/mud-cost/export-audit", headers=headers, json={
            "module": "consumption_losses", "format": "xlsx", "record_count": len(daily["rows"]),
            "rig_id": scope["rig"]["id"], "well_id": scope["well"]["id"],
            "section_id": "", "view": "daily", "date_from": None, "date_to": None,
        })
        assert export.status_code == 204, export.text
        with SessionLocal() as db:
            exported = db.scalar(select(AuditLog).where(
                AuditLog.entity_type == "mud_cost_export",
                AuditLog.summary.like("%consumption and losses%"),
            ))
            assert exported is not None


@pytest.mark.parametrize("mud_type", ["OBM", "SOBM", "OTHERS"])
def test_opening_stock_is_valued_once_and_zero_total_mud_has_no_rate(mud_type):
    from app.domain.mud_cost import reconcile_mud

    values = dict(mud_type=mud_type, base_rate=Decimal("2"), opening_stock=Decimal("100"),
                  extra_obm_received=Decimal("50"), additions=Decimal("150"),
                  actual_cost=Decimal("1500"), consumption_losses=Decimal("30"))
    result = reconcile_mud(**values)
    assert result.total_mud == Decimal("300")  # opening stock IS in total mud per updated spec
    assert result.alpha == Decimal("300")
    assert result.beta == Decimal("1800")
    assert result.cost_per_bbl == Decimal("6")
    assert result.reconciled_cost == Decimal("180")
    empty = reconcile_mud(**{**values, "extra_obm_received": Decimal("0"), "additions": Decimal("0")})
    assert empty.total_mud == Decimal("100")
    assert empty.alpha == Decimal("200")
    assert empty.beta == Decimal("1700")
    assert empty.cost_per_bbl == Decimal("17")
    assert empty.reconciled_cost == Decimal("510")


def test_wbm_cost_per_bbl_is_actual_mud_cost_divided_by_additions():
    from app.domain.mud_cost import reconcile_mud

    values = dict(
        mud_type="WBM", base_rate=None, opening_stock=Decimal("100"),
        extra_obm_received=Decimal("0"), additions=Decimal("12.5"),
        actual_cost=Decimal("250"), consumption_losses=Decimal("7"),
    )
    result = reconcile_mud(**values)
    assert result.alpha is None and result.beta is None
    assert result.cost_per_bbl == Decimal("20")
    assert result.reconciled_cost == Decimal("250")

    no_additions = reconcile_mud(**{**values, "additions": Decimal("0")})
    assert no_additions.cost_per_bbl is None
    assert no_additions.reconciled_cost == Decimal("250")


def test_opening_stock_correction_permission_recalculates_balances_and_well_cost():
    with TestClient(app) as client:
        headers = login(client)
        scope = setup_well(client, headers)
        first = create_mud_entry(client, headers, scope, "2026-10-11", 0, [
            line("opening_stock", "100", "Initial inventory"),
            line("extra_obm_received", "50"), line("drill_water", "100"), line("shakers", "10"),
        ])
        later = create_mud_entry(client, headers, scope, "2026-10-12", 0, [
            line("barite", "50"), line("centrifuge", "20"),
        ])
        other = create_mud_entry(client, headers, scope, "2026-10-13", 1, [
            line("opening_stock", "900"), line("drill_water", "10"), line("shakers", "5"),
        ])
        seed_daily_cost(scope, section_costs=[
            ("2026-10-11", 0, Decimal("1000")), ("2026-10-12", 0, Decimal("500")),
            ("2026-10-13", 1, Decimal("200")),
        ])
        configure_section(client, headers, scope, 0, "OBM", "2")
        configure_section(client, headers, scope, 1, "SOBM", "1")
        params = f"rig_id={scope['rig']['id']}&well_id={scope['well']['id']}&to=2026-10-13"
        recon_path = f"/api/v1/mud-cost/reconciliation?{params}"
        before = _json(client, "get", recon_path, headers)
        obm = next(row for row in before["sections"] if row["mud_type"] == "OBM")
        assert Decimal(obm["opening_stock"]) == 100
        assert Decimal(obm["cost_per_bbl"]) == 6
        assert Decimal(obm["reconciled_cost"]) == 180
        other_before = next(row for row in before["sections"] if row["mud_type"] == "SOBM")

        endpoint = f"/api/v1/mud-cost/entries/{first['id']}/opening-stock"
        assert client.put(endpoint, json={"amount": "200"}).status_code == 401
        assert client.put(endpoint, headers=login(client, "south"), json={"amount": "200"}).status_code == 404
        assert client.put(f"/api/v1/mud-cost/entries/{later['id']}/opening-stock", headers=headers,
                          json={"amount": "200"}).status_code == 409
        for invalid in ("-1", "0.00000000001", "1000000000000000", "NaN"):
            assert client.put(endpoint, headers=headers, json={"amount": invalid}).status_code == 422

        # An ordinary editor cannot correct inventory. Assigning just the new
        # capability (plus read) allows corrections without general entry edits.
        with SessionLocal() as db:
            org = db.scalar(select(Organization).where(Organization.slug == "north"))
            editor_role = Role(organization_id=org.id, name="Mud editor", permissions=[
                db.scalar(select(Permission).where(Permission.organization_id == org.id,
                                                   Permission.key == "daily-cost:read")),
                db.scalar(select(Permission).where(Permission.organization_id == org.id,
                                                   Permission.key == "daily-cost:update")),
            ])
            db.add(User(organization_id=org.id, email="editor@example.com", full_name="Mud editor",
                        password_hash=hash_password("correct-password-123"), roles=[editor_role]))
            db.commit()
        signed_in = client.post("/api/v1/auth/login", json={"organization": "north", "email": "editor@example.com",
                                                           "password": "correct-password-123"})
        editor = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
        assert client.put(endpoint, headers=editor, json={"amount": "200"}).status_code == 403
        # Ordinary entry updates reject a saved opening instead of silently ignoring it.
        ordinary_update = client.put(f"/api/v1/mud-cost/entries/{first['id']}", headers=editor, json={
            "entry_date": "2026-10-11", "lines": [line("opening_stock", "999"),
            line("extra_obm_received", "50"), line("drill_water", "100"), line("shakers", "10")],
        })
        assert ordinary_update.status_code == 409
        assert "Edit opening stock" in ordinary_update.json()["detail"]
        assert Decimal(_json(client, "get", f"/api/v1/mud-cost/entries/{first['id']}", headers)["opening_stock"]) == 100
        with SessionLocal() as db:
            role = db.scalar(select(Role).where(Role.name == "Mud editor"))
            permission = Permission(organization_id=role.organization_id, key="mud-cost:opening-stock-update",
                                    description="Correct mud opening stock")
            role.permissions = [p for p in role.permissions if p.key == "daily-cost:read"] + [permission]
            db.commit()
        corrected = _json(client, "put", endpoint, editor, {"amount": "200", "remarks": "Corrected tank survey"})
        assert Decimal(corrected["opening_stock"]) == 200
        assert corrected["opening_stock_remarks"] == "Corrected tank survey"
        later_after = _json(client, "get", f"/api/v1/mud-cost/entries/{later['id']}", headers)
        assert Decimal(later_after["opening_stock"]) == 340
        assert Decimal(later_after["closing_stock"]) == 370
        assert Decimal(_json(client, "get", f"/api/v1/mud-cost/entries/{other['id']}", headers)["opening_stock"]) == 900

        after = _json(client, "get", recon_path, headers)
        obm = next(row for row in after["sections"] if row["mud_type"] == "OBM")
        assert Decimal(obm["alpha"]) == 500
        assert Decimal(obm["beta"]) == 2000
        assert Decimal(obm["total_mud"]) == 400
        assert Decimal(obm["cost_per_bbl"]) == 5
        assert Decimal(obm["reconciled_cost"]) == 150
        assert next(row for row in after["sections"] if row["mud_type"] == "SOBM") == other_before
        daily = [row for row in after["rows"] if row["mud_type"] == "OBM"]
        assert all(Decimal(row["opening_stock"]) == 200 for row in daily)
        assert all(Decimal(row["alpha"]) == 500 for row in daily)  # never use carried-forward 340
        window = _json(client, "get", recon_path + "&from=2026-10-12", headers)
        obm_window = next(row for row in window["sections"] if row["mud_type"] == "OBM")
        assert Decimal(obm_window["opening_stock"]) == 200
        assert Decimal(obm_window["cost_per_bbl"]) == 5
        assert Decimal(obm_window["reconciled_cost"]) == 100
        summary = _json(client, "get", f"/api/v1/daily-cost/wells/{scope['well']['id']}/cost-summary", headers)
        assert Decimal(summary["mud_cost"]["reconciled_cost"]) == Decimal(after["total_reconciled_cost"])
        with SessionLocal() as db:
            audit = db.scalar(select(AuditLog).where(AuditLog.entity_type == "mud_cost_opening_stock"))
            assert audit.actor_email == "editor@example.com"
            assert "100" in audit.summary and "200" in audit.summary
            assert "Corrected tank survey" in audit.summary
