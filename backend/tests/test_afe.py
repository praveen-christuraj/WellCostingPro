import os
import tempfile

# Set the database before importing app modules (the engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
# Set TEST_DATABASE_URL (a PostgreSQL URL, as CI does) to run this suite against
# a real server instead of the throwaway SQLite file.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.domain import afe_costing as engine_rules
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User


AFE_PERMISSIONS = [
    "afe:read", "afe:create", "afe:update", "afe:delete", "afe:restore", "afe:permanent-delete",
    "afe:import", "afe:export", "afe:estimate", "afe:submit", "afe:review", "afe:approve", "afe:reopen",
]
MASTER_PERMISSIONS = ["master-data:read", "master-data:create", "master-data:update", "master-data:delete"]
RIG_WELL_PERMISSIONS = ["rig-well:read", "rig-well:create", "rig-well:update", "rig-well:delete"]


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
                for key in AFE_PERMISSIONS + MASTER_PERMISSIONS + RIG_WELL_PERMISSIONS + ["audit:read"]
            ]
            owner_role = Role(organization_id=organization.id, name="Owner", is_owner=True, permissions=permissions)
            db.add(
                User(
                    organization_id=organization.id,
                    email="owner@example.com",
                    full_name="Test Owner",
                    password_hash=hash_password("correct-password-123"),
                    roles=[owner_role],
                )
            )
        db.commit()
    yield


def login(client: TestClient, organization: str = "north", email: str = "owner@example.com") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"organization": organization, "email": email, "password": "correct-password-123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_rig(client, headers, code="RIG-01"):
    response = client.post(
        "/api/v1/rig-well/rigs", headers=headers,
        json={"rig_code": code, "rig_name": f"Rig {code}", "remarks": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_well(client, headers, rig_id, code="WELL-01"):
    response = client.post(
        "/api/v1/rig-well/wells", headers=headers,
        json={
            "rig_id": rig_id, "well_code": code, "well_name": f"Well {code}", "well_location": "North field",
            "block": "Block A", "objective": "Production appraisal", "remarks": "",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _option(client, headers, list_key, value):
    response = client.post(
        "/api/v1/master-data/catalogue-options", headers=headers, json={"list_key": list_key, "value": value}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _master_setup(client, headers):
    """Currency, hole sections, phases, a service, a tangible and a drill bit."""

    assert client.post("/api/v1/master-data/currencies", headers=headers, json={"code": "usd", "name": "US Dollar", "symbol": "$"}).status_code == 201
    assert client.post("/api/v1/master-data/uom", headers=headers, json={"code": "ea", "name": "Each", "symbol": "ea"}).status_code == 201
    hole_1 = client.post("/api/v1/master-data/hole-sections", headers=headers, json={"code": "17-1/2", "name": "Surface hole"}).json()
    hole_2 = client.post("/api/v1/master-data/hole-sections", headers=headers, json={"code": "12-1/4", "name": "Intermediate hole"}).json()
    phase = client.post("/api/v1/master-data/phases", headers=headers, json={"code": "DRILL", "name": "Drilling"}).json()
    inhouse = client.post(
        "/api/v1/master-data/vendors", headers=headers,
        json={"vendor_code": "INH-01", "vendor_name": "In-house crews", "vendor_type": "Inhouse", "category": "Drilling", "status": "active"},
    )
    assert inhouse.status_code == 201, inhouse.text
    vendor = client.post(
        "/api/v1/master-data/vendors", headers=headers,
        json={"vendor_code": "VEND-01", "vendor_name": "Acme Services", "category": "Drilling", "status": "active"},
    ).json()
    service_in_house = client.post(
        "/api/v1/master-data/services", headers=headers,
        json={
            "service_code": "MUD-LOGGING", "service_name": "Mud logging", "service_category": "Drilling Services",
            "provider_type": "In House Services", "vendor_id": inhouse.json()["id"], "description": "Wellsite logging crew",
        },
    )
    assert service_in_house.status_code == 201, service_in_house.text
    service_third = client.post(
        "/api/v1/master-data/services", headers=headers,
        json={
            "service_code": "CEMENTING", "service_name": "Cementing", "service_category": "Drilling Services",
            "provider_type": "Third Party Services", "vendor_id": vendor["id"], "description": "Cement unit",
        },
    )
    assert service_third.status_code == 201, service_third.text
    category = _option(client, headers, "tangible_category", "Casing Accessories")
    subcategory = client.post(
        "/api/v1/master-data/catalogue-options", headers=headers,
        json={"list_key": "tangible_subcategory", "parent_id": category["id"], "value": "Centralisers"},
    )
    assert subcategory.status_code == 201, subcategory.text
    subcategory = subcategory.json()
    manufacturer = _option(client, headers, "manufacturer", "Weatherford")
    tangible = client.post(
        "/api/v1/master-data/tangibles", headers=headers,
        json={
            "tangible_code": "TNG-0001", "tangible_name": "Casing centraliser 9-5/8in", "scope": "Drilling",
            "category_id": category["id"], "subcategory_id": subcategory["id"], "manufacturer_id": manufacturer["id"],
            "uom": "ea", "po_number": "PO-4500123", "unit_rate": "1250", "cost_uplift": "120", "currency": "usd",
            "effective_date": "2026-01-31", "description": "Bow spring centraliser", "remarks": "",
        },
    )
    assert tangible.status_code == 201, tangible.text
    bit_type = _option(client, headers, "drill_bit_type", "PDC")
    bit = client.post(
        "/api/v1/master-data/drill-bits", headers=headers,
        json={
            "bit_code": "DB-0001", "bit_name": "PDC bit 8-1/2in", "bit_type_id": bit_type["id"],
            "manufacturer_id": manufacturer["id"], "model_no": "M1365", "size": "8-1/2 in", "iadc_code": "M423",
            "serial_number": "SN-88421", "po_number": "PO-1", "unit_rate": "85000", "cost_uplift": "100",
            "currency": "USD", "effective_date": "2026-02-01",
        },
    )
    assert bit.status_code == 201, bit.text
    return {
        "hole_1": hole_1["id"], "hole_2": hole_2["id"], "phase": phase["id"],
        "service": service_in_house.json()["id"], "service_third": service_third.json()["id"],
        "tangible": tangible.json()["id"], "bit": bit.json()["id"],
    }


def _configure_well(client, headers, well_id, master):
    def section(hole, start, end, days):
        return {
            "hole_section_id": hole, "from_depth": start, "to_depth": end, "remarks": "",
            "phases": [{"phase_id": master["phase"], "days": days, "remarks": ""}],
        }

    payload = {"depth_unit": "m", "sections": [section(master["hole_1"], "0", "100", "10"), section(master["hole_2"], "100", "500", "30")]}
    saved = client.put(f"/api/v1/rig-well/wells/{well_id}/configuration", headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    # An AFE needs the plan marked Configured, which is a separate sign-off from saving the plan.
    marked = client.post(
        f"/api/v1/rig-well/wells/{well_id}/transition", headers=headers, json={"action": "configure", "remarks": "Plan checked"}
    )
    assert marked.status_code == 200, marked.text
    return saved.json()


def _setup(client, headers, code="AFE-DR-001"):
    master = _master_setup(client, headers)
    rig = create_rig(client, headers)
    well = create_well(client, headers, rig["id"])
    _configure_well(client, headers, well["id"], master)
    afe = client.post(
        "/api/v1/afe/afes", headers=headers,
        json={"rig_id": rig["id"], "well_id": well["id"], "afe_code": code, "afe_name": "Drill intermediate hole", "afe_type": "Drilling", "remarks": ""},
    )
    assert afe.status_code == 200, afe.text
    return master, rig, well, afe.json()


def _estimate_payload(master, **overrides):
    payload = {
        "services": [
            {
                "client_key": "svc-day",
                "service_id": master["service"],
                "charging_basis": "Day Rate",
                "hole_section_id": None,
                "phase_id": None,
                "currency": "USD",
                "service_amount": "0",
                "remarks": "Mud logging crew",
                "rates": [{"category": "Operation", "unit_rate": "1000"}, {"category": "Mobilization", "unit_rate": "5000"}],
                "charges": [],
                "section_rates": [],
            }
        ],
        "consumables": [
            {
                "client_key": "bit-1", "category": "Drill Bits", "hole_section_id": master["hole_2"], "phase_id": master["phase"],
                "drill_bit_id": master["bit"], "quantity": "2", "override_rate": "90000", "estimated_amount": None,
                "currency": "", "remarks": "Two bits",
            },
            {
                "client_key": "mud-1", "category": "Mud Chemicals", "hole_section_id": master["hole_1"], "phase_id": None,
                "drill_bit_id": None, "quantity": "1", "override_rate": None, "estimated_amount": "20000", "currency": "USD", "remarks": "Surface mud",
            },
            {
                "client_key": "mud-2", "category": "Mud Chemicals", "hole_section_id": master["hole_2"], "phase_id": None,
                "drill_bit_id": None, "quantity": "1", "override_rate": None, "estimated_amount": "5000", "currency": "USD", "remarks": "Second lump sum",
            },
            {
                "client_key": "fuel-1", "category": "Fuel", "hole_section_id": master["hole_2"], "phase_id": None,
                "drill_bit_id": None, "quantity": "1", "override_rate": None, "estimated_amount": "7000", "currency": "USD", "remarks": "",
            },
        ],
        "tangibles": [
            {"client_key": "tng-1", "tangible_id": master["tangible"], "quantity": "3", "override_rate": None, "remarks": ""},
            {"client_key": "tng-2", "tangible_id": master["tangible"], "quantity": "2", "override_rate": "1000", "remarks": "Negotiated"},
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pure engine
# ---------------------------------------------------------------------------


def _scope():
    return engine_rules.WellScope(
        sections=(
            engine_rules.SectionScope("s1", "17-1/2", (engine_rules.PhaseScope("p1", "Drilling", Decimal("10")),)),
            engine_rules.SectionScope("s2", "12-1/4", (engine_rules.PhaseScope("p1", "Drilling", Decimal("30")),)),
        )
    )


def test_service_and_consumable_currency_codes_are_normalised_to_upper_case():
    from app.schemas.afe import ConsumableLineIn, ServiceLineIn

    service = ServiceLineIn(service_id="svc-1", charging_basis="Per Service Rate", currency=" usd ")
    consumable = ConsumableLineIn(category="Fuel", hole_section_id="sec-1", estimated_amount="10", currency=" eur")
    assert service.currency == "USD"
    assert consumable.currency == "EUR"


def test_engine_splits_well_wide_day_rates_by_planned_days_and_keeps_one_time_well_level():
    service = engine_rules.ServiceLine(
        key="k", label="Mud logging", charging_basis=engine_rules.BASIS_DAY_RATE, currency="USD",
        rates=(engine_rules.RateInput("Operation", Decimal("1000")), engine_rules.RateInput("Mobilization", Decimal("5000"))),
    )
    result = engine_rules.compile_estimate(_scope(), services=[service])
    assert result.services_total == Decimal("45000.00")
    by_section = {row.section_id: row for row in result.by_section}
    assert by_section["s1"].services == Decimal("10000.00")
    assert by_section["s2"].services == Decimal("30000.00")
    assert by_section[None].services == Decimal("5000.00")
    assert by_section["s1"].planned_days == Decimal("10")


def test_engine_converts_hours_and_accepts_fractional_days():
    assert engine_rules.normalize_days(Decimal("6"), "hours") == Decimal("0.2500")
    assert engine_rules.normalize_days(Decimal("0.73"), "days") == Decimal("0.7300")
    service = engine_rules.ServiceLine(
        key="k", label="Standby", charging_basis=engine_rules.BASIS_DAY_RATE, currency="USD",
        section_id="s1", phase_id="p1",
        rates=(engine_rules.RateInput("Standby", Decimal("400")),),
        charges=(engine_rules.ChargeInput("Standby", Decimal("6"), "hours"),),
    )
    result = engine_rules.compile_estimate(_scope(), services=[service])
    assert result.services[0].amount == Decimal("100.00")


def test_engine_explicit_operation_days_replace_planned_days_and_warn_without_rate():
    service = engine_rules.ServiceLine(
        key="k", label="Rig", charging_basis=engine_rules.BASIS_DAY_RATE, currency="USD",
        rates=(engine_rules.RateInput("Operation", Decimal("100")),),
        charges=(engine_rules.ChargeInput("Operation", Decimal("5"), "days"),),
    )
    result = engine_rules.compile_estimate(_scope(), services=[service])
    assert result.services_total == Decimal("500.00")  # 5 days, split 1:3 by planned days
    assert [row.services for row in result.by_section if row.section_id] == [Decimal("125.00"), Decimal("375.00")]
    unpriced = engine_rules.ServiceLine(
        key="u", label="Standby", charging_basis=engine_rules.BASIS_DAY_RATE, currency="USD",
        charges=(engine_rules.ChargeInput("Standby", Decimal("2"), "days"),),
    )
    warned = engine_rules.compile_estimate(_scope(), services=[unpriced])
    assert warned.services_total == Decimal("0.00")
    assert any("without a unit rate" in text for text in warned.warnings)


def test_engine_per_section_and_per_service_rates_are_scoped_and_out_of_config_is_flagged():
    per_section = engine_rules.ServiceLine(
        key="ps", label="Cementing", charging_basis=engine_rules.BASIS_PER_SECTION, currency="USD",
        section_rates=(
            engine_rules.SectionRateInput("s1", None, Decimal("2500")),
            engine_rules.SectionRateInput("s2", "p1", Decimal("4000")),
        ),
    )
    per_service = engine_rules.ServiceLine(
        key="pv", label="Logging", charging_basis=engine_rules.BASIS_PER_SERVICE, currency="USD",
        section_id="s2", phase_id="p1", service_amount=Decimal("1500"),
    )
    stray = engine_rules.ServiceLine(
        key="x", label="Stray", charging_basis=engine_rules.BASIS_PER_SERVICE, currency="USD",
        section_id="not-in-plan", service_amount=Decimal("10"),
    )
    result = engine_rules.compile_estimate(_scope(), services=[per_section, per_service, stray])
    assert result.services_total == Decimal("8010.00")
    by_section = {row.section_id: row.services for row in result.by_section}
    assert by_section["s1"] == Decimal("2500.00")
    assert by_section["s2"] == Decimal("5500.00")
    assert by_section[None] == Decimal("10.00")
    assert any("Section is not in the well configuration" in text for text in result.warnings)


def test_engine_warns_when_currencies_are_mixed_and_rounds_half_up():
    tangible = engine_rules.TangibleLine(key="t", label="Centraliser", quantity=Decimal("3"), captured_rate=Decimal("1.005"), currency="USD")
    other = engine_rules.TangibleLine(key="o", label="Shoe", quantity=Decimal("1"), captured_rate=Decimal("10"), currency="EUR")
    result = engine_rules.compile_estimate(_scope(), tangibles=[tangible, other])
    assert result.tangibles[0].amount == Decimal("3.02")  # 3.015 rounds half-up to 3.02
    assert any("mixes currencies" in text for text in result.warnings)


# ---------------------------------------------------------------------------
# API: register, scope and validation
# ---------------------------------------------------------------------------


def test_afe_register_requires_configured_well_and_matching_rig_and_unique_codes():
    with TestClient(app) as client:
        headers = login(client)
        master = _master_setup(client, headers)
        rig = create_rig(client, headers)
        other_rig = create_rig(client, headers, code="RIG-02")
        well = create_well(client, headers, rig["id"])
        body = {"rig_id": rig["id"], "well_id": well["id"], "afe_code": "afe-1", "afe_name": "Drill", "afe_type": "Drilling"}

        unconfigured = client.post("/api/v1/afe/afes", headers=headers, json=body)
        assert unconfigured.status_code == 422
        assert "Configure the well" in unconfigured.json()["detail"]

        _configure_well(client, headers, well["id"], master)
        mismatch = client.post("/api/v1/afe/afes", headers=headers, json={**body, "rig_id": other_rig["id"]})
        assert mismatch.status_code == 422
        assert "does not belong" in mismatch.json()["detail"]

        created = client.post("/api/v1/afe/afes", headers=headers, json=body)
        assert created.status_code == 200, created.text
        assert created.json()["afe_code"] == "AFE-1"  # codes are normalised to upper case
        assert created.json()["status"] == "draft"

        duplicate = client.post("/api/v1/afe/afes", headers=headers, json={**body, "afe_code": "AFE-1"})
        assert duplicate.status_code == 409
        assert "already used" in duplicate.json()["detail"]

        reference = client.get("/api/v1/afe/reference", headers=headers).json()
        assert [row["id"] for row in reference["wells"] if row["rig_id"] == rig["id"]] == [well["id"]]
        assert reference["wells"][0]["section_count"] == 2
        assert {row["id"] for row in reference["services"]} == {master["service"], master["service_third"]}
        assert Decimal(reference["tangibles"][0]["captured_rate"]) == Decimal("1500")  # final cost with 120% uplift


# ---------------------------------------------------------------------------
# API: estimation, preview and persistence
# ---------------------------------------------------------------------------


def test_preview_prices_without_writing_and_save_round_trips_without_duplicates():
    with TestClient(app) as client:
        headers = login(client)
        master, rig, well, afe = _setup(client, headers)
        url = f"/api/v1/afe/afes/{afe['id']}/estimate"
        payload = _estimate_payload(master)

        preview = client.post(f"{url}/preview", headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()["persisted"] is False
        assert preview.json()["summary"]["total"] == "263500.00"
        assert client.get(url, headers=headers).json()["services"] == []  # preview wrote nothing

        saved = client.put(url, headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        first = saved.json()
        assert first["persisted"] is True
        assert first["summary"]["total"] == "263500.00"
        assert len(first["services"]) == 1 and len(first["consumables"]) == 4 and len(first["tangibles"]) == 2

        again = client.put(url, headers=headers, json=payload)
        second = again.json()
        assert len(second["services"]) == 1 and len(second["consumables"]) == 4 and len(second["tangibles"]) == 2
        assert second["summary"]["total"] == "263500.00"

        reloaded = client.get(url, headers=headers).json()
        assert reloaded["summary"]["total"] == "263500.00"
        assert [row["amount"] for row in reloaded["consumables"]] == [row["amount"] for row in second["consumables"]]


def test_day_rate_split_is_per_section_and_one_time_charges_stay_well_level():
    with TestClient(app) as client:
        headers = login(client)
        master, _, _, afe = _setup(client, headers)
        saved = client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=headers, json=_estimate_payload(master)).json()
        rows = {row["label"]: row for row in saved["summary"]["by_section"]}
        assert rows["17-1/2 — Surface hole"]["services"] == "10000.00"
        assert rows["12-1/4 — Intermediate hole"]["services"] == "30000.00"
        assert rows["Well-level (not section-specific)"]["services"] == "5000.00"
        assert Decimal(rows["17-1/2 — Surface hole"]["planned_days"]) == Decimal("10")
        operation = [c for c in saved["services"][0]["components"] if c["category"] == "Operation"]
        assert {c["section_label"] for c in operation} == {"17-1/2 — Surface hole", "12-1/4 — Intermediate hole"}


def test_bit_override_uses_master_currency_and_lump_sums_round_trip_with_separate_lines():
    with TestClient(app) as client:
        headers = login(client)
        master, _, _, afe = _setup(client, headers)
        saved = client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=headers, json=_estimate_payload(master)).json()
        bit = next(row for row in saved["consumables"] if row["category"] == "Drill Bits")
        assert bit["currency"] == "USD"  # from the bit's master record, not typed by the user
        assert Decimal(bit["effective_rate"]) == Decimal("90000") and bit["amount"] == "180000.00"
        lumps = [row for row in saved["consumables"] if row["category"] == "Mud Chemicals"]
        assert [row["estimated_amount"] for row in lumps] == ["20000.00", "5000.00"]
        assert all(row["drill_bit_id"] is None and row["bit_code"] == "" for row in lumps)
        assert all(not row["warnings"] for row in lumps)


def test_invalid_lines_are_reported_together_and_inactive_master_records_are_rejected():
    with TestClient(app) as client:
        headers = login(client)
        master, _, _, afe = _setup(client, headers)
        url = f"/api/v1/afe/afes/{afe['id']}/estimate"
        broken = _estimate_payload(master)
        broken["services"].append({
            "service_id": master["service"], "charging_basis": "Day Rate", "currency": "USD",
            "charges": [{"category": "Mobilization", "quantity": "2", "quantity_unit": "days"}],
            "rates": [], "section_rates": [], "hole_section_id": None, "phase_id": None, "service_amount": "0", "remarks": "",
        })
        broken["consumables"].append({
            "category": "Drill Bits", "hole_section_id": "not-in-config", "phase_id": None,
            "drill_bit_id": master["bit"], "quantity": "1", "currency": "", "remarks": "",
        })
        rejected = client.put(url, headers=headers, json=broken)
        assert rejected.status_code == 422
        details = rejected.json()["detail"]
        assert any("one-time charge" in text for text in details)
        assert any("not in this well's configuration" in text for text in details)
        assert len(details) >= 2

        per_service_no_section = _estimate_payload(master, services=[{
            "service_id": master["service"], "charging_basis": "Per Service Rate", "currency": "USD",
            "service_amount": "1500", "hole_section_id": None, "phase_id": None, "remarks": "",
            "rates": [], "charges": [], "section_rates": [],
        }], consumables=[], tangibles=[])
        no_section = client.post(f"{url}/preview", headers=headers, json=per_service_no_section)
        assert no_section.status_code == 422
        assert "Select a section" in no_section.json()["detail"][0]

        # Deactivating a tangible in master data blocks it in new estimates with an actionable message.
        assert client.delete(f"/api/v1/master-data/tangibles/{master['tangible']}", headers=headers).status_code == 200
        inactive = client.post(f"{url}/preview", headers=headers, json=_estimate_payload(master, services=[], consumables=[]))
        assert inactive.status_code == 422
        assert "inactive in Master Data" in inactive.json()["detail"][0]


def test_per_section_and_per_service_lines_save_and_price_in_scope():
    with TestClient(app) as client:
        headers = login(client)
        master, _, _, afe = _setup(client, headers)
        url = f"/api/v1/afe/afes/{afe['id']}/estimate"
        payload = _estimate_payload(master, consumables=[], tangibles=[], services=[
            {
                "service_id": master["service_third"], "charging_basis": "Per Section Rate", "currency": "USD",
                "service_amount": "0", "hole_section_id": None, "phase_id": None, "remarks": "Cement unit",
                "rates": [], "charges": [],
                "section_rates": [
                    {"hole_section_id": master["hole_1"], "phase_id": None, "amount": "2500"},
                    {"hole_section_id": master["hole_2"], "phase_id": master["phase"], "amount": "4000"},
                ],
            },
            {
                "service_id": master["service"], "charging_basis": "Per Service Rate", "currency": "USD",
                "service_amount": "1500", "hole_section_id": master["hole_2"], "phase_id": master["phase"], "remarks": "",
                "rates": [], "charges": [], "section_rates": [],
            },
        ])
        saved = client.put(url, headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["summary"]["total"] == "8000.00"
        by_section = {row["label"]: row["services"] for row in body["summary"]["by_section"]}
        assert by_section["17-1/2 — Surface hole"] == "2500.00"
        assert by_section["12-1/4 — Intermediate hole"] == "5500.00"


def test_status_moves_are_controlled_from_estimate_and_gated_by_permission():
    with TestClient(app) as client:
        headers = login(client)
        master, _, _, afe = _setup(client, headers)
        base = f"/api/v1/afe/afes/{afe['id']}"

        blocked = client.post(f"{base}/status", headers=headers, json={"action": "submit", "remarks": ""})
        assert blocked.status_code == 409
        assert "Save the AFE cost estimate" in blocked.json()["detail"]

        client.put(f"{base}/estimate", headers=headers, json=_estimate_payload(master))
        submitted = client.post(f"{base}/status", headers=headers, json={"action": "submit", "remarks": "Ready for review"})
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"

        locked = client.put(f"{base}/estimate", headers=headers, json=_estimate_payload(master))
        assert locked.status_code == 409
        header_edit = client.patch(base, headers=headers, json={"afe_name": "Renamed"})
        assert header_edit.status_code == 409
        assert client.delete(base, headers=headers).status_code == 409

        with SessionLocal() as db:
            org = db.scalar(select(Organization).where(Organization.slug == "north"))
            reviewer = Role(organization_id=org.id, name="Submitter", is_owner=False, permissions=[
                db.scalar(select(Permission).where(Permission.organization_id == org.id, Permission.key == key))
                for key in ("afe:read", "afe:submit")
            ])
            db.add(reviewer)
            db.add(User(organization_id=org.id, email="submitter@example.com", full_name="Submitter", password_hash=hash_password("correct-password-123"), roles=[reviewer]))
            db.commit()
        restricted = login(client, email="submitter@example.com")
        approve = client.post(f"{base}/status", headers=restricted, json={"action": "approve", "remarks": "Looks good"})
        assert approve.status_code == 403
        review = client.post(f"{base}/status", headers=restricted, json={"action": "review", "remarks": ""})
        assert review.status_code == 403

        reviewed = client.post(f"{base}/status", headers=headers, json={"action": "review", "remarks": ""})
        assert reviewed.status_code == 200 and reviewed.json()["status"] == "review"
        short = client.post(f"{base}/status", headers=headers, json={"action": "approve", "remarks": "ok"})
        assert short.status_code == 422
        approved = client.post(f"{base}/status", headers=headers, json={"action": "approve", "remarks": "Approved by management"})
        assert approved.status_code == 200 and approved.json()["status"] == "approval"
        reopened = client.post(f"{base}/status", headers=headers, json={"action": "reopen", "remarks": "Scope change"})
        assert reopened.status_code == 200 and reopened.json()["status"] == "draft"


def test_soft_delete_restore_permanent_delete_and_bulk_actions_are_audited():
    with TestClient(app) as client:
        headers = login(client)
        master, rig, well, afe = _setup(client, headers)
        second = client.post("/api/v1/afe/afes", headers=headers, json={
            "rig_id": rig["id"], "well_id": well["id"], "afe_code": "AFE-CMP-002", "afe_name": "Completion", "afe_type": "Completion", "remarks": "",
        }).json()

        bulk = client.post("/api/v1/afe/afes/bulk-delete", headers=headers, json={"ids": [afe["id"], second["id"]]})
        assert bulk.status_code == 200, bulk.text
        assert bulk.json()["affected_count"] == 2
        assert client.get("/api/v1/afe/afes", headers=headers).json() == []
        deleted = client.get("/api/v1/afe/afes/deleted", headers=headers).json()
        assert {row["afe_code"] for row in deleted} == {"AFE-DR-001", "AFE-CMP-002"}

        assert client.post(f"/api/v1/afe/afes/{afe['id']}/restore", headers=headers).status_code == 200
        blocked_purge = client.delete(f"/api/v1/afe/afes/{afe['id']}/permanent", headers=headers)
        assert blocked_purge.status_code == 409
        assert "Deleted Entries first" in blocked_purge.json()["detail"]
        assert client.post("/api/v1/afe/afes/bulk-restore", headers=headers, json={"ids": [second["id"]]}).json()["affected_count"] == 1
        assert client.delete(f"/api/v1/afe/afes/{second['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/afe/afes/{second['id']}/permanent", headers=headers).status_code == 204
        assert client.get("/api/v1/afe/afes/deleted", headers=headers).json() == []

        with SessionLocal() as db:
            actions = {row.action for row in db.scalars(select(AuditLog).where(AuditLog.entity_type == "afe"))}
        assert {"create", "soft_delete", "restore", "permanent_delete"} <= actions


def test_import_reports_row_errors_and_export_print_and_overview_are_audited():
    with TestClient(app) as client:
        headers = login(client)
        master, rig, well, _ = _setup(client, headers, code="AFE-IMP-000")
        rows = [
            {"rig_code": rig["rig_code"], "well_code": well["well_code"], "afe_code": "AFE-IMP-1", "afe_name": "Imported", "afe_type": "Drilling"},
            {"rig_code": rig["rig_code"], "well_code": well["well_code"], "afe_code": "AFE-IMP-2", "afe_name": "Bad type", "afe_type": "Workover"},
            {"rig_code": "NOPE", "well_code": well["well_code"], "afe_code": "AFE-IMP-3", "afe_name": "No rig", "afe_type": "Drilling"},
        ]
        response = client.post("/api/v1/afe/afes/import", headers=headers, json={"rows": rows})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["imported_count"] == 1 and body["error_count"] == 2 and body["success"] is False
        assert any("Row 2" in text for text in body["errors"]) and any("rig_code" in text for text in body["errors"])

        afe_id = next(row["id"] for row in client.get("/api/v1/afe/afes", headers=headers).json() if row["afe_code"] == "AFE-IMP-1")
        assert client.post(f"/api/v1/afe/afes/{afe_id}/print", headers=headers).status_code == 204
        assert client.post("/api/v1/afe/export-audit", headers=headers, json={"module": "estimates", "format": "xlsx", "record_count": 2}).status_code == 204

        overview = client.get("/api/v1/afe/overview", headers=headers).json()
        assert overview["active_afes"] == 2
        assert overview["drilling_afes"] == 2
        assert {row["status"] for row in overview["statuses"]} == {"draft", "submitted", "review", "approval"}
        assert any(item["entity_type"] == "afe_export" for item in overview["recent_activity"])


def test_afe_endpoints_enforce_tenant_isolation_and_rbac():
    with TestClient(app) as client:
        north = login(client)
        master, rig, well, afe = _setup(client, north)
        south = login(client, organization="south")
        assert client.get(f"/api/v1/afe/afes/{afe['id']}", headers=south).status_code == 404
        assert client.get(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=south).status_code == 404
        assert client.get("/api/v1/afe/afes", headers=south).json() == []

        with SessionLocal() as db:
            org = db.scalar(select(Organization).where(Organization.slug == "north"))
            viewer = Role(organization_id=org.id, name="Viewer", is_owner=False, permissions=[
                db.scalar(select(Permission).where(Permission.organization_id == org.id, Permission.key == "afe:read")),
            ])
            db.add(viewer)
            db.add(User(organization_id=org.id, email="viewer@example.com", full_name="Viewer", password_hash=hash_password("correct-password-123"), roles=[viewer]))
            db.commit()
        viewer_headers = login(client, email="viewer@example.com")
        assert client.get("/api/v1/afe/afes", headers=viewer_headers).status_code == 200
        assert client.post("/api/v1/afe/afes", headers=viewer_headers, json={
            "rig_id": rig["id"], "well_id": well["id"], "afe_code": "X-1", "afe_name": "x", "afe_type": "Drilling",
        }).status_code == 403
        assert client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=viewer_headers, json=_estimate_payload(master)).status_code == 403


def test_provisioning_seeds_afe_capabilities_for_new_tenants():
    from app.services.provisioning import CAPABILITIES

    assert set(CAPABILITIES["afe"]) >= {"read", "create", "estimate", "submit", "review", "approve", "reopen"}


# ---------------------------------------------------------------------------
# Configured plan, currency standard and conversion
# ---------------------------------------------------------------------------


def _service_line(master, key, currency, amount, **overrides):
    line = {
        "client_key": key, "service_id": master["service"], "charging_basis": "Per Service Rate",
        "hole_section_id": master["hole_2"], "phase_id": master["phase"], "currency": currency,
        "service_amount": amount, "remarks": "", "rates": [], "charges": [], "section_rates": [],
    }
    line.update(overrides)
    return line


def test_engine_currency_rules_pick_standard_and_report_missing_rates():
    single = engine_rules.resolve_currency(["USD", "USD"], standard="EUR")
    assert single.standard_currency == "USD" and single.converted and single.exchange_rates == ()

    unset = engine_rules.resolve_currency(["USD", "EUR"])
    assert unset.standard_missing and not unset.converted and unset.standard_currency == ""

    partial = engine_rules.resolve_currency(["USD", "EUR", "GBP"], "usd", {"EUR": Decimal("1.1")})
    assert partial.standard_currency == "USD"
    assert partial.missing_rates == ("GBP",) and not partial.converted
    assert partial.factor("USD") == Decimal("1") and partial.factor("EUR") == Decimal("1.1") and partial.factor("GBP") is None


def test_engine_converts_lines_and_sections_only_when_every_rate_is_present():
    scope = _scope()
    usd = engine_rules.ServiceLine(
        key="a", label="Logging", charging_basis=engine_rules.BASIS_PER_SERVICE, currency="USD",
        section_id="s1", phase_id="p1", service_amount=Decimal("1000"),
    )
    eur = engine_rules.TangibleLine(key="t", label="Shoe", quantity=Decimal("1"), captured_rate=Decimal("10"), currency="EUR")

    converted = engine_rules.compile_estimate(scope, services=[usd], tangibles=[eur], standard_currency="USD", exchange_rates={"EUR": Decimal("2")})
    assert converted.total == Decimal("1020.00")
    assert converted.services_total == Decimal("1000.00") and converted.tangibles_total == Decimal("20.00")
    section = next(row for row in converted.by_section if row.section_id == "s1")
    assert section.total == Decimal("1000.00")
    assert converted.totals_by_currency == (("EUR", Decimal("10.00")), ("USD", Decimal("1000.00")))  # as entered

    withheld = engine_rules.compile_estimate(scope, services=[usd], tangibles=[eur], standard_currency="USD")
    assert withheld.total is None and withheld.services_total is None
    assert all(row.total is None for row in withheld.by_section)
    assert any("conversion rate to USD for EUR" in text for text in withheld.warnings)


def test_afe_needs_a_configured_plan_for_create_estimate_save_and_submit():
    with TestClient(app) as client:
        headers = login(client)
        master = _master_setup(client, headers)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        plan = {
            "depth_unit": "m",
            "sections": [{
                "hole_section_id": master["hole_1"], "from_depth": "0", "to_depth": "100", "remarks": "",
                "phases": [{"phase_id": master["phase"], "days": "10", "remarks": ""}],
            }],
        }
        saved = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json=plan)
        assert saved.status_code == 200, saved.text
        afe_body = {"rig_id": rig["id"], "well_id": well["id"], "afe_code": "AFE-CFG", "afe_name": "Drill", "afe_type": "Drilling"}

        draft_plan = client.post("/api/v1/afe/afes", headers=headers, json=afe_body)
        assert draft_plan.status_code == 422
        assert "Configured" in draft_plan.json()["detail"]

        assert client.post(f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers, json={"action": "configure", "remarks": "Checked"}).status_code == 200
        afe = client.post("/api/v1/afe/afes", headers=headers, json=afe_body)
        assert afe.status_code == 200, afe.text
        url = f"/api/v1/afe/afes/{afe.json()['id']}/estimate"
        day_rate_only = _estimate_payload(master, consumables=[], tangibles=[])  # only the well-wide service
        assert client.put(url, headers=headers, json=day_rate_only).status_code == 200

        # Reopening the plan blocks estimate saves and submission until it is configured again.
        assert client.post(f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers, json={"action": "draft", "remarks": "Revise"}).status_code == 200
        blocked_save = client.put(url, headers=headers, json=day_rate_only)
        assert blocked_save.status_code == 409 and "Configured" in blocked_save.json()["detail"]
        blocked_submit = client.post(f"/api/v1/afe/afes/{afe.json()['id']}/status", headers=headers, json={"action": "submit", "remarks": ""})
        assert blocked_submit.status_code == 409 and "not Configured" in blocked_submit.json()["detail"]


def test_mixed_currency_estimate_needs_standard_currency_and_rates_then_converts_totals():
    with TestClient(app) as client:
        headers = login(client)
        master, _, _, afe = _setup(client, headers)
        url = f"/api/v1/afe/afes/{afe['id']}/estimate"
        services = [_service_line(master, "usd-svc", "USD", "1000"), _service_line(master, "eur-svc", "EUR", "2000")]
        payload = _estimate_payload(master, services=services, consumables=[], tangibles=[])

        unset = client.post(f"{url}/preview", headers=headers, json=payload).json()
        assert unset["summary"]["total"] is None
        assert unset["summary"]["currency"]["standard_missing"] is True and unset["summary"]["currency"]["converted"] is False
        assert unset["summary"]["currency"]["currencies"] == ["EUR", "USD"]
        assert {row["currency"]: row["amount"] for row in unset["summary"]["totals_by_currency"]} == {"EUR": "2000.00", "USD": "1000.00"}
        assert any("mixes currencies" in text for text in unset["summary"]["warnings"])
        assert unset["afe"]["conversion_pending"] is True and unset["afe"]["total_cost"] is None
        refused = client.put(url, headers=headers, json=payload)
        assert refused.status_code == 422 and "standard currency" in refused.json()["detail"]

        missing = client.post(f"{url}/preview", headers=headers, json={**payload, "standard_currency": "USD"}).json()
        assert missing["summary"]["currency"]["missing_rates"] == ["EUR"] and missing["summary"]["total"] is None
        refused = client.put(url, headers=headers, json={**payload, "standard_currency": "USD"})
        assert refused.status_code == 422 and "conversion rate to USD for EUR" in refused.json()["detail"]

        rated = {**payload, "standard_currency": "usd", "exchange_rates": [{"currency_code": "eur", "rate": "1.1"}]}
        preview = client.post(f"{url}/preview", headers=headers, json=rated).json()
        assert preview["summary"]["total"] == "3200.00"  # 1000 USD + 2000 EUR x 1.1
        assert preview["summary"]["services_total"] == "3200.00"
        assert preview["summary"]["currency"]["standard_currency"] == "USD"

        saved = client.put(url, headers=headers, json=rated)
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["summary"]["total"] == "3200.00" and body["afe"]["total_cost"] == "3200.00"
        assert body["afe"]["standard_currency"] == "USD" and body["afe"]["conversion_pending"] is False
        assert body["summary"]["currency"]["exchange_rates"] == [{"currency_code": "EUR", "rate": "1.100000"}]
        reloaded = client.get(url, headers=headers).json()
        assert reloaded["summary"]["total"] == "3200.00"
        by_section = {row["hole_section_id"]: row["services"] for row in reloaded["summary"]["by_section"]}
        assert by_section[master["hole_2"]] == "3200.00"  # converted, not 1000 + 2000 as entered
        assert by_section[master["hole_1"]] == "0.00"

        updated = client.put(url, headers=headers, json={**rated, "exchange_rates": [{"currency_code": "EUR", "rate": "1.2"}]})
        assert updated.json()["summary"]["total"] == "3400.00"  # the new rate replaces the saved one

        overview = client.get("/api/v1/afe/overview", headers=headers).json()
        assert overview["totals_by_currency"] == [{"currency": "USD", "amount": "3400.00"}]
        assert overview["conversion_pending_afes"] == 0


def test_single_currency_estimate_needs_no_rates_and_ignores_a_stored_standard():
    with TestClient(app) as client:
        headers = login(client)
        master, _, _, afe = _setup(client, headers)
        url = f"/api/v1/afe/afes/{afe['id']}/estimate"
        payload = _estimate_payload(master, services=[_service_line(master, "usd-only", "USD", "1500")], consumables=[], tangibles=[])
        body = client.put(url, headers=headers, json={**payload, "standard_currency": "EUR"}).json()
        assert body["summary"]["currency"]["converted"] is True and body["summary"]["currency"]["multi_currency"] is False
        assert body["summary"]["currency"]["standard_currency"] == "USD"
        assert body["summary"]["currency"]["exchange_rates"] == []
        assert body["summary"]["total"] == "1500.00"
        assert body["afe"]["standard_currency"] == "USD"
        dup = client.put(url, headers=headers, json={**payload, "exchange_rates": [{"currency_code": "EUR", "rate": "1"}, {"currency_code": "EUR", "rate": "2"}]})
        assert dup.status_code == 422


def test_scoped_plans_keep_rows_units_days_and_lifecycles_independent():
    with TestClient(app) as client:
        headers = login(client)
        master, rig, well, drilling_afe = _setup(client, headers)
        url = f"/api/v1/rig-well/wells/{well['id']}"
        drilling = client.get(f"{url}/configuration", headers=headers).json()
        empty = client.get(f"{url}/configuration?scope=completion", headers=headers).json()
        assert empty["sections"] == [] and empty["config_status"] == "draft"
        plan = {"scope": "completion", "depth_unit": "ft", "sections": [{
            "hole_section_id": master["hole_1"], "from_depth": "0", "to_depth": "2000",
            "phases": [{"phase_id": master["phase"], "days": "3.5"}],
        }]}
        saved = client.put(f"{url}/configuration", headers=headers, json=plan)
        assert saved.status_code == 200, saved.text
        assert saved.json()["scope"] == "completion"
        assert saved.json()["total_days"] == "3.50"
        assert saved.json()["depth_unit"] == "ft"
        # Replacing Completion rows must not touch any Drilling row IDs or values.
        plan["sections"][0]["phases"][0]["days"] = "4"
        assert client.put(f"{url}/configuration", headers=headers, json=plan).status_code == 200
        assert client.get(f"{url}/configuration", headers=headers).json() == drilling
        assert client.put(f"{url}/configuration", headers=headers, json={**plan, "scope": "drilling"}).status_code == 409
        assert client.get(f"{url}/configuration?scope=unknown", headers=headers).status_code == 422
        other = login(client, "south")
        assert client.get(f"{url}/configuration?scope=completion", headers=other).status_code == 404
        assert client.put(f"{url}/configuration", headers=other, json=plan).status_code == 404
        assert client.post(f"{url}/transition", headers=other, json={"scope": "completion", "action": "configure", "remarks": "Checked"}).status_code == 404

        def transition(scope, action):
            response = client.post(f"{url}/transition", headers=headers, json={"scope": scope, "action": action, "remarks": "Checked scope"})
            assert response.status_code == 200, response.text

        transition("drilling", "complete")
        transition("completion", "configure")
        transition("completion", "complete")
        completion = client.get(f"{url}/configuration?scope=completion", headers=headers).json()
        assert completion["status"] == "completed" and completion["config_status"] == "configured"
        transition("completion", "activate")
        transition("completion", "draft")
        assert client.get(f"{url}/configuration", headers=headers).json()["status"] == "completed"
        assert client.get(f"{url}/configuration", headers=headers).json()["config_status"] == "configured"
        assert client.put(f"{url}/configuration", headers=headers, json=plan).status_code == 200
        with SessionLocal() as db:
            assert any("completion" in entry.summary for entry in db.scalars(select(AuditLog)).all())


def test_afe_prices_and_validates_only_the_selected_configuration_scope():
    with TestClient(app) as client:
        headers = login(client)
        master, rig, well, drilling = _setup(client, headers)
        url = f"/api/v1/rig-well/wells/{well['id']}"
        afe_body = {"rig_id": rig["id"], "well_id": well["id"], "afe_code": "AFE-COMP", "afe_name": "Complete well", "afe_type": "Completion", "configuration_scope": "completion"}
        assert client.post("/api/v1/afe/afes", headers=headers, json=afe_body).status_code == 422
        phase_response = client.post("/api/v1/master-data/phases", headers=headers, json={"code": "COMP", "name": "Completion"})
        assert phase_response.status_code == 201, phase_response.text
        completion_phase = phase_response.json()["id"]
        plan = {"scope": "completion", "depth_unit": "ft", "sections": [{
            "hole_section_id": master["hole_1"], "from_depth": "0", "to_depth": "2000",
            "phases": [{"phase_id": completion_phase, "days": "3.5"}],
        }]}
        assert client.put(f"{url}/configuration", headers=headers, json=plan).status_code == 200
        assert client.post("/api/v1/afe/afes", headers=headers, json=afe_body).status_code == 422
        assert client.post(f"{url}/transition", headers=headers, json={"scope": "completion", "action": "configure", "remarks": "Checked"}).status_code == 200
        assert client.post(f"{url}/transition", headers=headers, json={"scope": "drilling", "action": "complete", "remarks": "Drilling finished"}).status_code == 200
        response = client.post("/api/v1/afe/afes", headers=headers, json=afe_body)
        assert response.status_code == 200, response.text
        completion = response.json()
        assert completion["configuration_scope"] == "completion"
        assert completion["well_status"] == "active"
        estimate_url = f"/api/v1/afe/afes/{completion['id']}/estimate"
        payload = _estimate_payload(master, consumables=[], tangibles=[])
        saved = client.put(estimate_url, headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        assert saved.json()["summary"]["total"] == "8500.00"  # 3.5 * 1000 + 5000
        assert saved.json()["well"]["scope"] == "completion"
        assert saved.json()["well"]["depth_unit"] == "ft"
        assert len(saved.json()["well"]["sections"]) == 1
        assert client.get(estimate_url, headers=headers).json()["summary"]["total"] == "8500.00"
        drilling_preview = client.post(f"/api/v1/afe/afes/{drilling['id']}/estimate/preview", headers=headers, json=payload)
        assert drilling_preview.json()["summary"]["total"] == "45000.00"
        # A Drilling-only section is rejected for a Completion estimate.
        invalid = _estimate_payload(master, tangibles=[])
        assert client.post(f"{estimate_url}/preview", headers=headers, json=invalid).status_code == 422
        invalid_phase = _estimate_payload(master, services=[_service_line(master, "wrong-phase", "USD", "100", hole_section_id=master["hole_1"])], consumables=[], tangibles=[])
        assert client.post(f"{estimate_url}/preview", headers=headers, json=invalid_phase).status_code == 422
        valid_phase = _estimate_payload(master, services=[_service_line(master, "comp-phase", "USD", "100", hole_section_id=master["hole_1"], phase_id=completion_phase)], consumables=[], tangibles=[])
        assert client.post(f"{estimate_url}/preview", headers=headers, json=valid_phase).status_code == 200
        # Stored lines cannot silently be repriced against a different scoped plan.
        changed = client.patch(f"/api/v1/afe/afes/{completion['id']}", headers=headers, json={"configuration_scope": "drilling"})
        assert changed.status_code == 409
        # Reopening only Completion blocks Completion saves/submission, not Drilling.
        assert client.post(f"{url}/transition", headers=headers, json={"scope": "completion", "action": "draft", "remarks": "Revise"}).status_code == 200
        assert client.put(estimate_url, headers=headers, json=payload).status_code == 409
        assert client.post(f"/api/v1/afe/afes/{completion['id']}/status", headers=headers, json={"action": "submit"}).status_code == 409
        assert client.put(f"/api/v1/afe/afes/{drilling['id']}/estimate", headers=headers, json=payload).status_code == 200
        reference = client.get("/api/v1/afe/reference", headers=headers).json()["wells"][0]
        assert reference["config_status"] == "configured" and reference["completion_config_status"] == "draft"
        assert reference["completion_section_count"] == 1


def test_completion_only_well_supports_scoped_afe_creation_and_import():
    with TestClient(app) as client:
        headers = login(client)
        master = _master_setup(client, headers)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        url = f"/api/v1/rig-well/wells/{well['id']}"
        plan = {"scope": "completion", "sections": [{"hole_section_id": master["hole_1"], "from_depth": 0, "to_depth": 100,
                 "phases": [{"phase_id": master["phase"], "days": 2}]}]}
        assert client.put(f"{url}/configuration", headers=headers, json=plan).status_code == 200
        assert client.post(f"{url}/transition", headers=headers, json={"scope": "completion", "action": "configure", "remarks": "Checked"}).status_code == 200
        row = {"rig_code": rig["rig_code"], "well_code": well["well_code"], "afe_code": "IMPORT-COMP", "afe_name": "Completion only", "afe_type": "Completion", "configuration_scope": "completion"}
        imported = client.post("/api/v1/afe/afes/import", headers=headers, json={"rows": [row]})
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported_count"] == 1 and imported.json()["error_count"] == 0
        rows = client.get("/api/v1/afe/afes", headers=headers).json()
        assert rows[0]["configuration_scope"] == "completion"
        assert client.get(f"{url}/configuration", headers=headers).json()["sections"] == []
        afe_body = {"rig_id": rig["id"], "well_id": well["id"], "afe_code": "DIRECT-COMP", "afe_name": "Completion only", "afe_type": "Completion", "configuration_scope": "completion"}
        created = client.post("/api/v1/afe/afes", headers=headers, json=afe_body)
        assert created.status_code == 200, created.text
        assert client.post("/api/v1/afe/afes", headers=headers, json={**afe_body, "afe_code": "NO-DRILL", "configuration_scope": "drilling"}).status_code == 422
