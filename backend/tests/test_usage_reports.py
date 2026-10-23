"""End-to-end coverage for the Reports module usage/cost matrix reports."""
import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuditLog, Organization, Permission, Role, User  # noqa: E402

PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export", "submit", "reopen",
    )),
    *(f"afe:{action}" for action in (
        "read", "create", "update", "delete", "estimate", "submit", "review", "approve", "reopen", "import", "export",
        "restore", "permanent-delete",
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


def _option(client, headers, list_key, value, parent_id=None):
    payload = {"list_key": list_key, "value": value}
    if parent_id:
        payload["parent_id"] = parent_id
    return _post(client, "/api/v1/master-data/catalogue-options", headers, payload)


def _make_well(client, headers, *, rig_code, block_code, well_code, sections, activities, phase):
    rig = _post(client, "/api/v1/rig-well/rigs", headers,
                {"rig_code": rig_code, "rig_name": f"{rig_code} Rig", "remarks": ""})
    block = _post(client, "/api/v1/rig-well/blocks", headers,
                  {"block_code": block_code, "block_name": f"{block_code} Block", "description": ""})
    well = _post(client, "/api/v1/rig-well/wells", headers, {
        "rig_id": rig["id"], "block_id": block["id"], "well_code": well_code,
        "well_name": f"{well_code} Well", "well_location": "Field", "objective": "Development", "remarks": "",
    })
    config = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json={
        "depth_unit": "m",
        "sections": [{
            "hole_section_id": hole["id"], "from_depth": str(section_from),
            "to_depth": str(section_to), "remarks": "",
            "phases": [{"phase_id": phase["id"], "days": "10", "remarks": ""}],
        } for hole, section_from, section_to in sections],
    })
    assert config.status_code == 200, config.text
    transition = client.post(f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers,
                             json={"action": "configure", "remarks": "Plan checked"})
    assert transition.status_code == 200, transition.text
    subs = []
    for index, activity in enumerate(activities):
        subs.append(_post(client, "/api/v1/rig-well/sub-activities", headers, {
            "well_id": well["id"], "sub_activity_code": f"{well_code}-SA{index}",
            "sub_activity_name": f"Sub {activity['code']}",
            "activity_id": activity["id"], "responsible_party": "Operations",
            "description": "Work step",
        }))
    return {"rig": rig, "block": block, "well": well, "subs": subs}


def _afe_with_service(client, headers, rig, well, service, hole, phase, *, code="AFE-01", currency="USD"):
    afe = _post(client, "/api/v1/afe/afes", headers, {
        "rig_id": rig["id"], "well_id": well["id"], "afe_code": code,
        "afe_name": f"{code} AFE", "afe_type": "Drilling", "remarks": "",
    }, status=200)
    estimate = client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=headers, json={
        "services": [{
            "client_key": "svc-1", "service_id": service["id"], "charging_basis": "Day Rate",
            "hole_section_id": hole["id"], "phase_id": phase["id"], "currency": currency,
            "service_amount": "0", "remarks": "",
            "rates": [{"category": "Operation", "unit_rate": "100"}],
            "charges": [{"category": "Operation", "quantity": "10", "quantity_unit": "days"}],
            "section_rates": [],
        }],
        "consumables": [], "tangibles": [],
        "standard_currency": "" if currency == "USD" else currency,
        "exchange_rates": [],
    })
    assert estimate.status_code == 200, estimate.text
    return afe


def _entry(client, headers, well, afe, cost_date):
    created = _post(client, "/api/v1/daily-cost/entries", headers, {
        "well_id": well["id"], "afe_id": afe["id"], "cost_date": cost_date, "remarks": "",
    })
    return created["entry"]["id"]


def _baseline_rate(client, headers, entry_id):
    baseline = client.get(f"/api/v1/daily-cost/entries/{entry_id}/baseline", headers=headers).json()
    return baseline["service_rates"][0]


def _service_line(activity, sub, vendor, service, rate, hole, phase, *, currency="USD", exchange_rate=None):
    line = {
        "activity_id": activity["id"], "hole_section_id": hole["id"], "phase_id": phase["id"],
        "sub_activity_id": sub["id"], "vendor_id": vendor["id"], "quantity": "1",
        "quantity_unit": "days", "currency": currency, "service_id": service["id"],
        "baseline_service_rate_id": rate["id"] if currency == "USD" else None,
        "charging_basis": "Day Rate", "charge_category": "Operation",
        "override_rate": None, "override_reason": "", "remarks": "Planned service",
    }
    if exchange_rate:
        line["exchange_rate"] = exchange_rate
    return line


def _consumable(activity, sub, vendor, hole, phase, *, category, item_kind, item_id,
                quantity, rate, currency="USD", exchange_rate=None):
    line = {
        "activity_id": activity["id"], "hole_section_id": hole["id"], "phase_id": phase["id"],
        "sub_activity_id": sub["id"], "vendor_id": vendor["id"], "quantity": quantity,
        "currency": currency, "override_rate": rate, "override_reason": "Report test override",
        "remarks": "Consumable usage", "category": category, "item_kind": item_kind, "item_id": item_id,
    }
    if exchange_rate:
        line["exchange_rate"] = exchange_rate
    return line


def _tangible(activity, sub, vendor, hole, phase, tangible_id, *, quantity, rate, currency="USD", exchange_rate=None):
    line = {
        "activity_id": activity["id"], "hole_section_id": hole["id"], "phase_id": phase["id"],
        "sub_activity_id": sub["id"], "vendor_id": vendor["id"], "quantity": quantity,
        "currency": currency, "override_rate": rate, "override_reason": "Report test override",
        "remarks": "Tangible usage", "tangible_id": tangible_id,
    }
    if exchange_rate:
        line["exchange_rate"] = exchange_rate
    return line


def _save(client, headers, entry_id, payload):
    saved = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    return saved.json()


def _setup(client, headers):
    _post(client, "/api/v1/master-data/currencies", headers,
          {"code": "USD", "name": "US Dollar", "symbol": "$", "is_default": True})
    _post(client, "/api/v1/master-data/currencies", headers,
          {"code": "EUR", "name": "Euro", "symbol": "€"})
    _post(client, "/api/v1/master-data/uom", headers, {"code": "MT", "name": "Metric tonne", "symbol": "MT"})
    _post(client, "/api/v1/master-data/uom", headers, {"code": "EA", "name": "Each", "symbol": "EA"})
    hole_1 = _post(client, "/api/v1/master-data/hole-sections", headers,
                   {"code": "17-1/2", "name": "Surface hole"})
    hole_2 = _post(client, "/api/v1/master-data/hole-sections", headers,
                   {"code": "12-1/4", "name": "Intermediate hole"})
    phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
    act_planned = _post(client, "/api/v1/master-data/activities", headers,
                        {"code": "DRL", "name": "Drilling"})
    act_upa = _post(client, "/api/v1/master-data/activities", headers,
                    {"code": "UPA", "name": "Unplanned activity"})
    act_npt = _post(client, "/api/v1/master-data/activities", headers,
                    {"code": "NPT", "name": "Non-productive time"})

    chem_group = _option(client, headers, "mud_chemical_group", "Weighting agent")
    manufacturer = _option(client, headers, "manufacturer", "Halliburton")
    bit_type = _option(client, headers, "drill_bit_type", "PDC")
    t_category = _option(client, headers, "tangible_category", "Casing Accessories")
    t_subcategory = _option(client, headers, "tangible_subcategory", "Centralisers", t_category["id"])

    barite = _post(client, "/api/v1/master-data/mud-chemicals", headers, {
        "chemical_code": "BARITE", "chemical_name": "Barite", "group_id": chem_group["id"],
        "manufacturer_id": manufacturer["id"], "part_number": "BR-25", "uom": "MT",
        "unit_rate": "50", "currency": "USD", "effective_date": "2026-01-15",
    })
    bentonite = _post(client, "/api/v1/master-data/mud-chemicals", headers, {
        "chemical_code": "BENTONITE", "chemical_name": "Bentonite", "group_id": chem_group["id"],
        "part_number": "BN-9", "uom": "MT", "unit_rate": "5", "currency": "USD",
        "effective_date": "2026-01-15",
    })
    bit = _post(client, "/api/v1/master-data/drill-bits", headers, {
        "bit_code": "DB-01", "bit_name": "PDC bit 8-1/2in", "bit_type_id": bit_type["id"],
        "manufacturer_id": manufacturer["id"], "model_no": "M1365", "size": "8-1/2 in",
        "iadc_code": "M423", "serial_number": "SN-88421", "unit_rate": "85000",
        "currency": "USD", "effective_date": "2026-02-01",
    })
    tangible = _post(client, "/api/v1/master-data/tangibles", headers, {
        "tangible_code": "TNG-01", "tangible_name": "Centraliser 9-5/8",
        "scope": "Drilling", "category_id": t_category["id"], "subcategory_id": t_subcategory["id"],
        "manufacturer_id": manufacturer["id"], "uom": "EA", "unit_rate": "1000",
        "currency": "USD", "effective_date": "2026-02-01",
    })
    vendor = _post(client, "/api/v1/master-data/vendors", headers, {
        "vendor_code": "VEND-01", "vendor_name": "Acme Services", "vendor_type": "Third party",
        "category": "Drilling", "status": "active",
    })
    service = _post(client, "/api/v1/master-data/services", headers, {
        "service_code": "MUD-LOG", "service_name": "Mud logging",
        "service_category": "Drilling Services", "provider_type": "Third Party Services",
        "vendor_id": vendor["id"], "description": "Wellsite logging crew",
    })

    well_one = _make_well(
        client, headers, rig_code="RIG-01", block_code="BLOCK-A", well_code="WELL-01",
        sections=[(hole_1, 0, 1000), (hole_2, 1000, 2000)],
        activities=[act_planned, act_upa, act_npt], phase=phase,
    )
    well_two = _make_well(
        client, headers, rig_code="RIG-02", block_code="BLOCK-B", well_code="WELL-02",
        sections=[(hole_1, 0, 800)],
        activities=[act_planned], phase=phase,
    )

    afe_one = _afe_with_service(
        client, headers, well_one["rig"], well_one["well"], service, hole_1, phase)
    afe_two = _afe_with_service(
        client, headers, well_two["rig"], well_two["well"], service, hole_1, phase, code="AFE-02")

    # --- Well 1, day 1 (section 1): planned service + barite + bit + tangible ---
    entry_1 = _entry(client, headers, well_one["well"], afe_one, "2026-10-10")
    rate = _baseline_rate(client, headers, entry_1)
    _save(client, headers, entry_1, {
        "remarks": "day 1",
        "services": [_service_line(act_planned, well_one["subs"][0], vendor, service, rate, hole_1, phase)],
        "consumables": [
            _consumable(act_planned, well_one["subs"][0], vendor, hole_1, phase,
                        category="Mud Chemicals", item_kind="mud_chemical",
                        item_id=barite["id"], quantity="10", rate="50"),
            _consumable(act_planned, well_one["subs"][0], vendor, hole_1, phase,
                        category="Drill Bits", item_kind="drill_bit",
                        item_id=bit["id"], quantity="1", rate="85000"),
        ],
        "tangibles": [_tangible(act_planned, well_one["subs"][0], vendor, hole_1, phase,
                                tangible["id"], quantity="2", rate="1000")],
    })

    # --- Well 1, day 2 (section 2): barite + bentonite + UPA + NPT service ---
    entry_2 = _entry(client, headers, well_one["well"], afe_one, "2026-10-11")
    rate_2 = _baseline_rate(client, headers, entry_2)
    upa_line = _service_line(act_upa, well_one["subs"][1], vendor, service, rate_2, hole_2, phase)
    upa_line.update({"override_rate": "300", "override_reason": "Unplanned diagnostic call-out",
                     "baseline_service_rate_id": None, "remarks": "UPA work"})
    npt_line = _service_line(act_npt, well_one["subs"][2], vendor, service, rate_2, hole_2, phase)
    npt_line.update({"override_rate": "200", "override_reason": "Rig repair standby time",
                     "baseline_service_rate_id": None, "remarks": "NPT standby"})
    _save(client, headers, entry_2, {
        "remarks": "day 2",
        "services": [upa_line, npt_line],
        "consumables": [
            _consumable(act_upa, well_one["subs"][1], vendor, hole_2, phase,
                        category="Mud Chemicals", item_kind="mud_chemical",
                        item_id=barite["id"], quantity="5", rate="50"),
            _consumable(act_upa, well_one["subs"][1], vendor, hole_2, phase,
                        category="Mud Chemicals", item_kind="mud_chemical",
                        item_id=bentonite["id"], quantity="20", rate="5"),
        ],
        "tangibles": [],
    })

    # --- Well 2, day 3: barite in section 1 ---
    entry_3 = _entry(client, headers, well_two["well"], afe_two, "2026-10-12")
    rate_3 = _baseline_rate(client, headers, entry_3)
    _save(client, headers, entry_3, {
        "remarks": "well two day",
        "services": [_service_line(act_planned, well_two["subs"][0], vendor, service, rate_3, hole_1, phase)],
        "consumables": [
            _consumable(act_planned, well_two["subs"][0], vendor, hole_1, phase,
                        category="Mud Chemicals", item_kind="mud_chemical",
                        item_id=barite["id"], quantity="3", rate="50"),
        ],
        "tangibles": [],
    })

    # --- EUR sheet on well 2: currency-excluded when reporting in USD ---
    afe_eur = _afe_with_service(
        client, headers, well_two["rig"], well_two["well"], service, hole_1, phase,
        code="AFE-EUR", currency="EUR")
    entry_eur = _entry(client, headers, well_two["well"], afe_eur, "2026-10-13")
    _save(client, headers, entry_eur, {
        "remarks": "euro sheet",
        "services": [],
        "consumables": [
            _consumable(act_planned, well_two["subs"][0], vendor, hole_1, phase,
                        category="Mud Chemicals", item_kind="mud_chemical",
                        item_id=barite["id"], quantity="4", rate="40",
                        currency="EUR", exchange_rate="1.10"),
        ],
        "tangibles": [],
    })

    return {
        "well_one": well_one, "well_two": well_two,
        "barite": barite, "bentonite": bentonite, "bit": bit, "tangible": tangible,
        "vendor": vendor, "service": service, "hole_1": hole_1, "hole_2": hole_2,
        "afe_one": afe_one, "afe_eur": afe_eur,
    }


def _get(client, path, headers):
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_reference_lists_blocks_wells_scopes_and_currencies():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup(client, headers)
        data = _get(client, "/api/v1/usage-reports/reference", headers)
        assert {row["block_code"] for row in data["blocks"]} == {"BLOCK-A", "BLOCK-B"}
        assert {row["rig_code"] for row in data["rigs"]} == {"RIG-01", "RIG-02"}
        well_codes = {row["well_code"]: row for row in data["wells"]}
        assert set(well_codes) == {"WELL-01", "WELL-02"}
        assert well_codes["WELL-01"]["status"] == "active"
        assert well_codes["WELL-01"]["config_status"] == "configured"
        assert "drilling" in well_codes["WELL-01"]["scopes"]
        assert well_codes["WELL-01"]["has_costs"] is True
        assert {row["code"] for row in data["currencies"]} == {"USD", "EUR"}
        assert data["default_currency"] == "USD"
        assert setup["barite"]["id"]


def test_mud_chemicals_matrix_quantities_costs_sections_and_well_totals():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup(client, headers)
        data = _get(client, "/api/v1/usage-reports/matrix/mud-chemicals", headers)
        assert data["report"] == "mud-chemicals"
        assert data["mode"] == "usage"
        assert data["currency"] == "USD"
        # USD reporting uses the stored USD amounts, so the EUR sheet is included.
        assert data["excluded_entry_count"] == 0
        assert [column["well_code"] for column in data["wells"]] == ["WELL-01", "WELL-02"]
        # Well 1 carries two sections in the column sub headers.
        well_one = next(column for column in data["wells"] if column["well_code"] == "WELL-01")
        assert [section["section_code"] for section in well_one["sections"]] == ["17-1/2", "12-1/4"]

        rows = {row["item_code"]: row for row in data["rows"]}
        barite = rows["BARITE"]
        assert barite["uom"] == "MT"
        assert barite["manufacturer"] == "Halliburton"
        well_one_cell = next(cell for cell in barite["cells"] if cell["well_id"] == setup["well_one"]["well"]["id"])
        section_values = {section["section_key"]: section for section in well_one_cell["sections"]}
        assert Decimal(section_values[setup["hole_1"]["id"]]["quantity"]) == Decimal("10")
        assert Decimal(section_values[setup["hole_1"]["id"]]["amount"]) == Decimal("500.00")
        assert Decimal(section_values[setup["hole_2"]["id"]]["quantity"]) == Decimal("5")
        assert Decimal(section_values[setup["hole_2"]["id"]]["amount"]) == Decimal("250.00")
        assert Decimal(well_one_cell["quantity"]) == Decimal("15")
        assert Decimal(well_one_cell["amount"]) == Decimal("750.00")
        well_two_cell = next(cell for cell in barite["cells"] if cell["well_id"] == setup["well_two"]["well"]["id"])
        # 3 MT USD sheet + 4 MT EUR sheet (160 EUR × 1.10 = 176 USD) = 7 MT / 326 USD.
        assert Decimal(well_two_cell["quantity"]) == Decimal("7")
        assert Decimal(well_two_cell["amount"]) == Decimal("326.00")
        assert Decimal(barite["quantity_total"]) == Decimal("22")
        assert Decimal(barite["amount_total"]) == Decimal("1076.00")

        bentonite = rows["BENTONITE"]
        bentonite_cell = next(cell for cell in bentonite["cells"] if cell["well_id"] == setup["well_one"]["well"]["id"])
        assert Decimal(bentonite_cell["quantity"]) == Decimal("20")
        assert Decimal(bentonite_cell["amount"]) == Decimal("100.00")
        assert Decimal(data["grand_quantity"]) == Decimal("42")
        assert Decimal(data["grand_amount"]) == Decimal("1176.00")
        # Flat detail rows feed the filterable grid: one per item × well × section.
        assert {row["section_name"] for row in data["detail"] if row["item_code"] == "BARITE"} == {
            "Surface hole", "Intermediate hole", "Surface hole",
        }
        assert all(row["currency"] == "USD" for row in data["detail"])


def test_drill_bits_report_carries_make_model_size_and_iadc_details():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup(client, headers)
        data = _get(client, "/api/v1/usage-reports/matrix/drill-bits", headers)
        assert len(data["rows"]) == 1
        row = data["rows"][0]
        assert row["item_code"] == "DB-01"
        assert row["category"] == "PDC"
        assert row["manufacturer"] == "Halliburton"
        assert "M1365" in row["detail"] and "8-1/2 in" in row["detail"] and "M423" in row["detail"]
        cell = row["cells"][0]
        assert Decimal(cell["quantity"]) == Decimal("1")
        assert Decimal(cell["amount"]) == Decimal("85000.00")
        assert Decimal(data["grand_amount"]) == Decimal("85000.00")


def test_tangibles_report_groups_rows_by_category_and_subcategory():
    with TestClient(app) as client:
        headers = login(client)
        _setup(client, headers)
        data = _get(client, "/api/v1/usage-reports/matrix/tangibles", headers)
        assert len(data["rows"]) == 1
        row = data["rows"][0]
        assert row["item_code"] == "TNG-01"
        assert row["category"] == "Casing Accessories"
        assert row["subcategory"] == "Centralisers"
        assert row["manufacturer"] == "Halliburton"
        cell = row["cells"][0]
        assert Decimal(cell["quantity"]) == Decimal("2")
        assert Decimal(cell["amount"]) == Decimal("2000.00")
        detail = data["detail"][0]
        assert detail["cost_group"] == "Tangibles"


def test_service_and_vendor_reports_are_cost_only_and_vendor_spans_groups():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup(client, headers)
        services = _get(client, "/api/v1/usage-reports/matrix/services", headers)
        assert services["mode"] == "cost"
        service_row = services["rows"][0]
        assert service_row["item_code"] == "MUD-LOG"
        assert Decimal(service_row["quantity_total"]) == Decimal("0")  # cost only
        # Planned 100 (day 1) + UPA 300 + NPT 200 (day 2, well 1) + 100 (well 2) = 700
        assert Decimal(service_row["amount_total"]) == Decimal("700.00")
        assert Decimal(services["grand_quantity"]) == Decimal("0")

        vendors = _get(client, "/api/v1/usage-reports/matrix/vendors", headers)
        assert vendors["mode"] == "cost"
        assert len(vendors["rows"]) == 1
        vendor_row = vendors["rows"][0]
        assert vendor_row["item_code"] == "VEND-01"
        assert vendor_row["category"] == "Third party"
        # Every line in the setup books against VEND-01: services 700 + mud 1176
        # + bit 85000 + tangible 2000 = 88876 USD (EUR sheet included at USD rate).
        assert Decimal(vendor_row["amount_total"]) == Decimal("88876.00")
        groups = {row["cost_group"] for row in vendors["detail"]}
        assert groups == {"Services", "Consumables", "Tangibles"}


def test_npt_upa_report_counts_distinct_days_and_classification_costs():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup(client, headers)
        data = _get(client, "/api/v1/usage-reports/npt-upa", headers)
        assert data["currency"] == "USD"
        assert data["excluded_entry_count"] == 0
        well_one = next(row for row in data["wells"] if row["well_code"] == "WELL-01")
        assert well_one["npt_days"] == 1
        assert well_one["upa_days"] == 1
        assert well_one["planned_days"] == 1  # only day 1 carries a planned line
        assert Decimal(well_one["npt_amount"]) == Decimal("200.00")
        # UPA = 300 service + 250 barite + 100 bentonite.
        assert Decimal(well_one["upa_amount"]) == Decimal("650.00")
        assert Decimal(well_one["total_amount"]) == Decimal(
            Decimal(well_one["planned_amount"]) + Decimal(well_one["upa_amount"]) + Decimal(well_one["npt_amount"])
        )
        well_two = next(row for row in data["wells"] if row["well_code"] == "WELL-02")
        # Two planned cost dates: the USD sheet (12 Oct) and the EUR sheet (13 Oct).
        assert well_two["planned_days"] == 2
        assert well_two["npt_days"] == 0
        assert data["totals"]["npt_days"] == 1
        assert Decimal(data["totals"]["npt_amount"]) == Decimal("200.00")
        classifications = {(row["well_code"], row["classification"]) for row in data["detail"]}
        assert ("WELL-01", "NPT") in classifications
        assert ("WELL-01", "UPA") in classifications
        assert ("WELL-01", "Planned") in classifications
        assert setup["afe_one"]["id"]


def test_filters_block_scope_lifecycle_date_range_and_explicit_wells():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup(client, headers)
        block_a = setup["well_one"]["block"]["id"]
        well_one_id = setup["well_one"]["well"]["id"]

        blocked = _get(client, f"/api/v1/usage-reports/matrix/mud-chemicals?block_id={block_a}", headers)
        assert [column["well_code"] for column in blocked["wells"]] == ["WELL-01"]

        ranged = _get(client, "/api/v1/usage-reports/matrix/mud-chemicals?from=2026-10-11&to=2026-10-11", headers)
        barite = next(row for row in ranged["rows"] if row["item_code"] == "BARITE")
        # Only the 5 MT section-2 usage on 11 Oct remains for well 1.
        well_one_cell = next(cell for cell in barite["cells"] if cell["well_id"] == well_one_id)
        assert Decimal(well_one_cell["quantity"]) == Decimal("5")
        assert ranged["entry_count"] == 1

        explicit = _get(
            client,
            f"/api/v1/usage-reports/matrix/mud-chemicals?well_id={well_one_id}",
            headers,
        )
        assert [column["well_code"] for column in explicit["wells"]] == ["WELL-01"]
        # An explicit selection keeps the column even when it has no matching fact.
        empty = _get(
            client,
            f"/api/v1/usage-reports/matrix/drill-bits?from=2026-10-12&well_id={well_one_id}",
            headers,
        )
        assert [column["well_code"] for column in empty["wells"]] == ["WELL-01"]
        assert empty["rows"] == []

        scoped = _get(client, "/api/v1/usage-reports/matrix/mud-chemicals?scope=drilling", headers)
        assert len(scoped["wells"]) == 2
        lifecycle = _get(client, "/api/v1/usage-reports/matrix/mud-chemicals?lifecycle=active", headers)
        assert {column["well_code"] for column in lifecycle["wells"]} == {"WELL-01", "WELL-02"}
        completed = _get(client, "/api/v1/usage-reports/matrix/mud-chemicals?lifecycle=completed", headers)
        assert completed["wells"] == []

        # Submitted-only filtering excludes the draft sheets (none were submitted).
        drafts_excluded = _get(
            client, "/api/v1/usage-reports/matrix/mud-chemicals?include_draft=false", headers
        )
        assert drafts_excluded["rows"] == []
        assert drafts_excluded["entry_count"] == 0


def test_eur_currency_report_excludes_usd_and_marks_excluded_sheets():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup(client, headers)
        data = _get(client, "/api/v1/usage-reports/matrix/mud-chemicals?currency=EUR", headers)
        assert data["currency"] == "EUR"
        assert data["excluded_entry_count"] == 3  # three USD sheets
        barite = next(row for row in data["rows"] if row["item_code"] == "BARITE")
        well_two_cell = next(cell for cell in barite["cells"] if cell["well_id"] == setup["well_two"]["well"]["id"])
        # 4 MT at EUR 40 = 160 EUR, converted only for USD reporting, kept native here.
        assert Decimal(well_two_cell["amount"]) == Decimal("160.00")
        assert Decimal(well_two_cell["quantity"]) == Decimal("4")


def test_usage_reports_are_tenant_scoped_rbac_gated_and_audited():
    with TestClient(app) as client:
        headers = login(client)
        _setup(client, headers)

        # A second workspace sees none of the first workspace's data.
        south_headers = login(client, "south")
        south = _get(client, "/api/v1/usage-reports/matrix/mud-chemicals", south_headers)
        assert south["rows"] == []
        assert south["wells"] == []

        # A role without daily-cost:read is refused by the API (the authority).
        with SessionLocal() as db:
            org = db.query(Organization).filter_by(slug="north").one()
            limited_role = Role(organization_id=org.id, name="No reports", is_owner=False, permissions=[])
            reader = User(
                organization_id=org.id, email="reader@example.com", full_name="No Access",
                password_hash=hash_password("correct-password-123"), roles=[limited_role],
            )
            db.add(reader)
            db.commit()
            reader_id = reader.id
        login_response = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "reader@example.com",
            "password": "correct-password-123",
        })
        limited_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        denied = client.get("/api/v1/usage-reports/matrix/mud-chemicals", headers=limited_headers)
        assert denied.status_code == 403
        denied_audit = client.post("/api/v1/usage-reports/export-audit", headers=limited_headers, json={
            "report": "mud-chemicals", "format": "xlsx", "record_count": 2,
        })
        assert denied_audit.status_code == 403

        # Export writes the typed audit trail.
        audit_response = client.post("/api/v1/usage-reports/export-audit", headers=headers, json={
            "report": "mud-chemicals", "format": "xlsx", "record_count": 2,
            "block_id": "", "rig_id": "", "well_ids": [], "scope": "", "lifecycle": "",
            "currency": "USD", "date_from": None, "date_to": None, "include_draft": True,
        })
        assert audit_response.status_code == 204
        with SessionLocal() as db:
            entry = db.query(AuditLog).filter_by(entity_type="usage_report_export").one()
            assert "Mud chemicals usage" in entry.entity_label
            assert "XLSX" in entry.summary
            assert "currency=USD" in entry.summary
        assert reader_id
